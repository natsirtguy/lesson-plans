"""Creating subjects and generating their concept graphs."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db import new_id
from app.llm.base import LLMAdapter, LLMError
from app.llm.prompts import GRAPH_GENERATION_SYSTEM
from app.llm.schemas import GeneratedGraph, GeneratedNode
from app.mastery.graph import ConceptGraph, Edge, NodeMeta
from app.mastery.reconcile import seed_mastery
from app.mastery.state import MasteryParams, MasteryState
from app.models.enums import GraphGenerationStatus, NodeOrigin
from app.models.graph import ConceptEdge, ConceptNode, MasteryRecord
from app.models.subject import Subject
from app.repositories.graph import GraphRepository, name_key
from app.repositories.subjects import SubjectRepository
from app.schemas.subject import CadenceUpdate, SubjectCreate

logger = logging.getLogger(__name__)

#: Minimum concepts a usable graph must have. Below this the model has produced a
#: table of contents rather than a decomposition, and it is better to fail loudly.
MIN_NODES = 12
#: Upper bound, enforced by truncation rather than rejection: an over-long graph is
#: still usable, and the alternative is discarding a slow, expensive generation.
MAX_NODES = 140


class GraphGenerationError(RuntimeError):
    """Raised when a generated graph cannot be made into a valid DAG."""


class SubjectService:
    """Creates subjects and builds their initial concept graphs."""

    def __init__(
        self,
        session: AsyncSession,
        adapter: LLMAdapter,
        settings: Settings,
    ) -> None:
        """
        :param session: The active database session.
        :param adapter: The LLM boundary.
        :param settings: Runtime configuration.
        """
        self._session = session
        self._adapter = adapter
        self._settings = settings
        self._subjects = SubjectRepository(session)
        self._graph = GraphRepository(session)
        self._params = MasteryParams.from_settings(settings)

    async def create(self, payload: SubjectCreate) -> Subject:
        """Create a subject with its graph marked pending.

        :param payload: The requested subject.
        """
        subject = Subject(
            name=payload.name.strip(),
            description=payload.description.strip(),
            days_per_week=payload.days_per_week or self._settings.default_days_per_week,
            minutes_per_session=(
                payload.minutes_per_session or self._settings.default_minutes_per_session
            ),
            daily_review_cap=self._settings.daily_review_cap,
            target_retention=self._settings.target_retention,
            graph_status=GraphGenerationStatus.PENDING,
        )
        await self._subjects.add(subject)
        await self._session.commit()
        return subject

    async def list_subjects(self) -> list[tuple[Subject, int]]:
        """Every subject with its live concept count."""
        subjects = await self._subjects.list_all()
        counts = await self._subjects.node_counts()
        return [(subject, counts.get(subject.id, 0)) for subject in subjects]

    async def update_cadence(self, subject_id: str, payload: CadenceUpdate) -> Subject:
        """Apply a partial cadence update.

        :param subject_id: The subject to change.
        :param payload: Fields to change; omitted fields are left alone.
        :raises LookupError: If the subject does not exist.
        """
        subject = await self._subjects.get(subject_id)
        if subject is None:
            raise LookupError(subject_id)
        if payload.days_per_week is not None:
            subject.days_per_week = payload.days_per_week
        if payload.minutes_per_session is not None:
            subject.minutes_per_session = payload.minutes_per_session
        if payload.daily_review_cap is not None:
            subject.daily_review_cap = payload.daily_review_cap
        if payload.target_retention is not None:
            subject.target_retention = payload.target_retention
        if payload.recovery_aware is not None:
            subject.recovery_aware = payload.recovery_aware
        # A deadline is cleared explicitly rather than by passing null, so that an
        # omitted field and a deliberate reset are distinguishable.
        if payload.clear_deadline:
            subject.deadline = None
        elif payload.deadline is not None:
            subject.deadline = payload.deadline
        await self._session.commit()
        return subject

    async def generate_graph(self, subject_id: str) -> Subject:
        """Decompose a subject into a concept graph and persist it.

        Idempotent by status: a subject already generating or ready is left alone,
        so a retried background task cannot produce a second graph.

        :param subject_id: The subject to build a graph for.
        :raises LookupError: If the subject does not exist.
        """
        subject = await self._subjects.get(subject_id)
        if subject is None:
            raise LookupError(subject_id)
        if subject.graph_status in {
            GraphGenerationStatus.GENERATING,
            GraphGenerationStatus.READY,
        }:
            return subject

        subject.graph_status = GraphGenerationStatus.GENERATING
        subject.graph_error = None
        await self._session.commit()

        try:
            generated = await self._adapter.generate_structured(
                schema=GeneratedGraph,
                system=GRAPH_GENERATION_SYSTEM,
                prompt=self._generation_prompt(subject),
                task="graph_generation",
                reasoning=True,
            )
            self._persist(subject, generated)
        except (LLMError, GraphGenerationError) as exc:
            await self._session.rollback()
            subject = await self._reload_for_failure(subject_id, exc)
            return subject

        subject.graph_status = GraphGenerationStatus.READY
        subject.description = subject.description or generated.subject_summary
        await self._session.commit()
        return subject

    async def _reload_for_failure(self, subject_id: str, exc: Exception) -> Subject:
        """Record a generation failure on the subject after a rollback.

        :param subject_id: The subject that failed.
        :param exc: The failure.
        """
        subject = await self._subjects.get(subject_id)
        if subject is None:  # pragma: no cover - the row cannot vanish mid-request
            raise LookupError(subject_id) from exc
        logger.warning("graph generation failed for %s: %s", subject_id, exc)
        subject.graph_status = GraphGenerationStatus.FAILED
        subject.graph_error = str(exc)[:2000]
        await self._session.commit()
        return subject

    def _generation_prompt(self, subject: Subject) -> str:
        """Build the user-turn instruction for graph generation.

        :param subject: The subject being decomposed.
        """
        lines = [f"SUBJECT: {subject.name}"]
        if subject.description:
            lines.append(f"LEARNER NOTES: {subject.description}")
        lines.append("")
        lines.append(
            "Decompose this subject into its concept graph. Aim for 40 to 120 "
            "concepts spanning all five tiers."
        )
        return "\n".join(lines)

    def _persist(self, subject: Subject, generated: GeneratedGraph) -> None:
        """Validate a generated graph and stage its rows.

        :param subject: The subject being populated.
        :param generated: The model's decomposition.
        :raises GraphGenerationError: If the result cannot be made into a valid DAG.
        """
        nodes = self._deduplicate(generated.nodes)
        if len(nodes) < MIN_NODES:
            raise GraphGenerationError(
                f"only {len(nodes)} usable concepts were produced, need at least {MIN_NODES}"
            )
        nodes = nodes[:MAX_NODES]

        by_key = {name_key(node.name): node for node in nodes}
        rows: dict[str, ConceptNode] = {}
        for node in nodes:
            row = ConceptNode(
                # Ids are assigned here rather than at flush, because the edges and
                # mastery seeds below reference them before anything is written.
                id=new_id(),
                subject_id=subject.id,
                name=node.name.strip(),
                name_key=name_key(node.name),
                definition=node.definition.strip(),
                tier=node.tier,
                origin=NodeOrigin.GENERATED,
                introduced_in_version=subject.graph_version,
            )
            rows[row.name_key] = self._graph.add_node(row)

        edges = self._resolve_edges(nodes, by_key, rows)
        candidate = ConceptGraph(
            (NodeMeta(node_id=r.id, name=r.name, tier=r.tier) for r in rows.values()),
            (Edge(prereq_id=p, node_id=n) for p, n in edges),
        )
        if candidate.has_cycle():
            raise GraphGenerationError("generated prerequisite graph contains a cycle")

        for prereq_id, node_id in edges:
            self._session.add(
                ConceptEdge(
                    subject_id=subject.id,
                    prereq_id=prereq_id,
                    node_id=node_id,
                    introduced_in_version=subject.graph_version,
                )
            )
        self._seed_mastery(subject, candidate, rows)

    @staticmethod
    def _deduplicate(nodes: list[GeneratedNode]) -> list[GeneratedNode]:
        """Drop concepts whose normalized name repeats an earlier one.

        :param nodes: Generated concepts in the order produced.
        """
        seen: set[str] = set()
        unique: list[GeneratedNode] = []
        for node in nodes:
            key = name_key(node.name)
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append(node)
        return unique

    @staticmethod
    def _resolve_edges(
        nodes: list[GeneratedNode],
        by_key: dict[str, GeneratedNode],
        rows: dict[str, ConceptNode],
    ) -> list[tuple[str, str]]:
        """Turn prerequisite *names* into edges between persisted ids.

        Prerequisites that name a concept not in the graph are dropped: the model
        occasionally references something it decided not to include, and a dangling
        prerequisite would make the node permanently unreachable. Edges pointing
        from a higher tier to a lower one are dropped for the same reason -- they
        would make the sequencer teach an advanced concept first.

        :param nodes: The generated concepts.
        :param by_key: Generated concepts by normalized name.
        :param rows: Persisted rows by normalized name.
        """
        edges: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for node in nodes:
            node_key = name_key(node.name)
            target = rows.get(node_key)
            if target is None:
                continue
            for prereq_name in node.prerequisites:
                prereq_key = name_key(prereq_name)
                source = rows.get(prereq_key)
                if source is None or prereq_key == node_key:
                    continue
                if by_key[prereq_key].tier > node.tier:
                    continue
                pair = (source.id, target.id)
                if pair in seen:
                    continue
                seen.add(pair)
                edges.append(pair)
        return edges

    def _seed_mastery(
        self,
        subject: Subject,
        graph: ConceptGraph,
        rows: dict[str, ConceptNode],
    ) -> None:
        """Create a mastery record for every concept.

        Seeded in prerequisite order so each node's seed can draw on its
        prerequisites', rather than every concept starting at the same flat prior.

        :param subject: The subject being populated.
        :param graph: The validated candidate graph.
        :param rows: Persisted concept rows by normalized name.
        """
        by_id = {row.id: row for row in rows.values()}
        states: dict[str, MasteryState] = {}
        for node_id in graph.topological_order():
            prereq_states = [states[p] for p in graph.prereqs(node_id) if p in states]
            state = seed_mastery(prereq_states, self._params)
            states[node_id] = state
            self._graph.add_mastery(
                MasteryRecord(
                    subject_id=subject.id,
                    node_id=by_id[node_id].id,
                    mastery=state.mastery,
                    confidence=state.confidence,
                )
            )


async def generate_graph_in_background(
    factory: async_sessionmaker[AsyncSession],
    adapter: LLMAdapter,
    settings: Settings,
    subject_id: str,
) -> None:
    """Run graph generation in its own session, for use as a background task.

    The request's session is closed by the time a background task runs, so this
    opens its own. Failures are recorded on the subject rather than raised, since
    there is no caller left to receive them.

    :param factory: Session factory to open a fresh session from.
    :param adapter: The LLM boundary.
    :param settings: Runtime configuration.
    :param subject_id: The subject to build a graph for.
    """
    async with factory() as session:
        service = SubjectService(session, adapter, settings)
        try:
            await service.generate_graph(subject_id)
        except Exception:  # a background task must not vanish silently
            logger.exception("background graph generation failed for %s", subject_id)
