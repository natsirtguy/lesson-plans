"""Turning stored rows into the pure structures the mastery model works on.

Every service that reasons about a subject starts here. Loading also applies
forgetting: decay is computed from each record's stored ``decayed_at`` and written
back, so it advances once per elapsed day rather than once per read. Opening the
report ten times must not age the estimate ten times.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import utcnow
from app.llm.base import CacheableContext
from app.llm.prompts import NodeContext, graph_context
from app.mastery.decay import DecayInput, decay_all
from app.mastery.graph import ConceptGraph, Edge, NodeMeta
from app.mastery.state import MasteryParams, MasteryState
from app.models.graph import ConceptNode, MasteryRecord
from app.models.subject import Subject
from app.repositories.graph import GraphRepository
from app.repositories.subjects import SubjectRepository


class SubjectNotFoundError(LookupError):
    """Raised when a subject id does not exist."""


class GraphNotReadyError(RuntimeError):
    """Raised when a subject's graph has not finished generating."""


@dataclass(slots=True)
class LoadedSubject:
    """A subject's graph and mastery, in both stored and pure form.

    :param subject: The subject row.
    :param graph: The live prerequisite graph.
    :param states: Mastery state per live node id.
    :param records: Mastery rows per node id, including soft-deleted concepts.
    :param nodes: Live concept rows per node id.
    """

    subject: Subject
    graph: ConceptGraph
    states: dict[str, MasteryState]
    records: dict[str, MasteryRecord]
    nodes: dict[str, ConceptNode]

    def context(self) -> CacheableContext:
        """Render the cacheable prompt prefix for this subject.

        Nodes are emitted in a stable order so the rendered bytes -- and therefore
        the provider-side cache entry -- do not move between calls.
        """
        ordered = sorted(self.graph.nodes.values(), key=lambda meta: (meta.tier, meta.name))
        contexts = [
            NodeContext(
                node_id=meta.node_id,
                name=meta.name,
                definition=self.nodes[meta.node_id].definition,
                tier=meta.tier,
                mastery=self.states[meta.node_id].mastery,
                confidence=self.states[meta.node_id].confidence,
                prereq_names=tuple(
                    sorted(self.graph.nodes[p].name for p in self.graph.prereqs(meta.node_id))
                ),
            )
            for meta in ordered
        ]
        return graph_context(
            subject_name=self.subject.name,
            graph_version=self.subject.graph_version,
            nodes=contexts,
        )


class GraphLoader:
    """Loads a subject's graph, applying decay as it goes."""

    def __init__(self, session: AsyncSession, params: MasteryParams) -> None:
        """
        :param session: The active database session.
        :param params: Mastery model constants.
        """
        self._session = session
        self._params = params
        self._graph = GraphRepository(session)
        self._subjects = SubjectRepository(session)

    async def load(
        self, subject_id: str, *, apply_decay: bool = True, now: datetime | None = None
    ) -> LoadedSubject:
        """Load a subject's live graph and current mastery.

        :param subject_id: The subject to load.
        :param apply_decay: Whether to age and persist estimates on the way through.
        :param now: The instant to age to; defaults to the current time.
        :raises SubjectNotFoundError: If the subject does not exist.
        """
        subject = await self._subjects.get(subject_id)
        if subject is None:
            raise SubjectNotFoundError(subject_id)

        nodes = await self._graph.live_nodes(subject_id)
        edges = await self._graph.live_edges(subject_id)
        records = {
            record.node_id: record for record in await self._graph.mastery_records(subject_id)
        }

        graph = ConceptGraph(
            (NodeMeta(node_id=n.id, name=n.name, tier=n.tier) for n in nodes),
            (Edge(prereq_id=e.prereq_id, node_id=e.node_id) for e in edges),
        )

        moment = now or utcnow()
        if apply_decay:
            self._apply_decay(records, graph.node_ids, moment)

        states = {
            node.id: MasteryState(
                mastery=records[node.id].mastery,
                confidence=records[node.id].confidence,
            )
            for node in nodes
            if node.id in records
        }

        return LoadedSubject(
            subject=subject,
            graph=graph,
            states=states,
            records=records,
            nodes={node.id: node for node in nodes},
        )

    def _apply_decay(
        self,
        records: dict[str, MasteryRecord],
        node_ids: tuple[str, ...],
        now: datetime,
    ) -> None:
        """Age live records to ``now`` and stamp them so it is not repeated.

        :param records: Mastery rows per node id.
        :param node_ids: Live node ids; removed concepts are not aged.
        :param now: The instant to age to.
        """
        inputs = {
            node_id: DecayInput(
                state=MasteryState(
                    mastery=records[node_id].mastery,
                    confidence=records[node_id].confidence,
                ),
                last_touched=records[node_id].decayed_at or records[node_id].last_seen_at,
            )
            for node_id in node_ids
            if node_id in records
        }
        for node_id, aged in decay_all(inputs, now=now, params=self._params).items():
            record = records[node_id]
            record.mastery = aged.mastery
            record.confidence = aged.confidence
        # Stamp every live record, including unchanged ones, so the next read
        # measures elapsed time from now rather than from the original observation.
        for node_id in inputs:
            records[node_id].decayed_at = now

    async def require_ready(self, subject_id: str) -> LoadedSubject:
        """Load a subject, refusing if its graph is still being generated.

        :param subject_id: The subject to load.
        :raises GraphNotReadyError: If generation is pending, running, or failed.
        """
        loaded = await self.load(subject_id)
        if not loaded.graph.node_ids:
            raise GraphNotReadyError(loaded.subject.graph_status)
        return loaded
