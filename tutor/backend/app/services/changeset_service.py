"""Refining the concept graph.

The rule this module exists to enforce: **nothing changes the graph without
per-operation approval, and no approved set commits if it would break the graph.**
Everything else here is in service of that.

The flow is deliberately three-step. A plain-language request produces a *proposal*
-- a changeset row with its operations, each awaiting a verdict. The learner accepts
or rejects operations individually. Only then is the accepted subset simulated,
validated, and written, as one atomic commit that bumps the graph version.

Mastery is carried across explicitly rather than left to fall where it may. The
reconciliation rules live in :mod:`app.mastery.reconcile`; this module decides which
concepts they apply to, and then recomputes everything else by replaying the
response log against the new graph -- because a propagated estimate depends on the
edges that existed when the answer was given, and those have just changed.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from pydantic import TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db import new_id, utcnow
from app.graphs.mutation import (
    MutationError,
    MutationPlan,
    NodeDraft,
    affected_subgraph,
    plan_mutation,
    preview_changes,
    summarize,
    validate_plan,
)
from app.llm.base import LLMAdapter
from app.llm.prompts import REFINE_SYSTEM
from app.llm.schemas import ProposedChangeset, ProposedOperation
from app.mastery.propagation import smooth_posterior
from app.mastery.replay import replay
from app.mastery.state import MasteryParams, MasteryState
from app.models.changeset import Changeset, ChangesetOp
from app.models.enums import ChangesetStatus, NodeOrigin, UnitStatus
from app.models.graph import ConceptNode, MasteryRecord
from app.repositories.assessment import AssessmentRepository
from app.repositories.changesets import ChangesetRepository
from app.repositories.graph import GraphRepository, name_key
from app.repositories.plans import PlanRepository
from app.schemas.changeset import (
    AddEdge,
    AddNode,
    ChangesetPreview,
    ChangesetRead,
    ChangesetSummary,
    CommitRequest,
    GraphPreviewNode,
    MergeNodes,
    NewNodeSpec,
    Operation,
    OperationRead,
    RedefineNode,
    RemoveEdge,
    RemoveNode,
    RenameNode,
    RetargetEdge,
    RetierNode,
    SplitNode,
)
from app.services.graph_loader import GraphLoader, LoadedSubject

logger = logging.getLogger(__name__)

#: Rehydrates a stored operation payload into its typed form.
_OPERATION: TypeAdapter[Operation] = TypeAdapter(Operation)


class ChangesetRejected(ValueError):
    """Raised when the accepted operations would break the graph."""


class IncompleteReview(ValueError):
    """Raised when a commit does not carry a verdict for every operation."""


@dataclass(slots=True)
class CommitResult:
    """What a commit did.

    :param changeset: The committed changeset row.
    :param graph_version: The version the graph is now at.
    :param applied: How many operations were applied.
    :param notes: Advisory messages produced while planning.
    """

    changeset: Changeset
    graph_version: int
    applied: int
    notes: list[str]


class ChangesetService:
    """Proposes, validates, and commits graph changesets."""

    def __init__(self, session: AsyncSession, adapter: LLMAdapter, settings: Settings) -> None:
        """
        :param session: The active database session.
        :param adapter: The LLM boundary.
        :param settings: Runtime configuration.
        """
        self._session = session
        self._adapter = adapter
        self._settings = settings
        self._params = MasteryParams.from_settings(settings)
        self._changesets = ChangesetRepository(session)
        self._graph = GraphRepository(session)
        self._plans = PlanRepository(session)
        self._assessment = AssessmentRepository(session)
        self._loader = GraphLoader(session, self._params)

    # --- proposing -----------------------------------------------------------

    async def propose(self, subject_id: str, request: str) -> Changeset:
        """Turn a plain-language request into a reviewable changeset.

        Nothing is committed. Operations are stored with ``accepted`` null, which is
        what "awaiting review" means.

        :param subject_id: The subject to refine.
        :param request: The learner's request, verbatim.
        :raises LLMError: If the model cannot produce a usable changeset.
        """
        loaded = await self._loader.load(subject_id)
        proposal = await self._adapter.generate_structured(
            schema=ProposedChangeset,
            system=REFINE_SYSTEM,
            prompt=f"REQUEST: {request}\n\nPropose the changeset.",
            task="graph_refinement",
            context=loaded.context(),
            reasoning=True,
        )

        changeset = self._changesets.add(
            Changeset(
                id=new_id(),
                subject_id=subject_id,
                request_text=request,
                rationale=proposal.rationale,
                status=ChangesetStatus.PROPOSED,
                base_version=loaded.subject.graph_version,
            )
        )

        seq = 0
        for raw in proposal.operations:
            operation = self._convert(raw, loaded)
            if operation is None:
                continue
            self._changesets.add_op(
                ChangesetOp(
                    id=new_id(),
                    changeset_id=changeset.id,
                    seq=seq,
                    op_type=operation.op_type,
                    payload=operation.model_dump(mode="json"),
                    rationale=raw.rationale,
                )
            )
            seq += 1

        await self._session.commit()
        return changeset

    def _convert(self, raw: ProposedOperation, loaded: LoadedSubject) -> Operation | None:
        """Convert the model's flat operation record into a typed operation.

        Returns None when the operation cannot be made sense of -- it names a
        concept that does not exist, or omits a field its type requires. Dropping it
        is better than proposing an operation that would fail at commit time, and
        better than failing the whole proposal over one bad entry.

        :param raw: The model's operation record.
        :param loaded: The subject being refined, for resolving references.
        """
        known = set(loaded.graph.node_ids)
        by_name = {name_key(meta.name): node_id for node_id, meta in loaded.graph.nodes.items()}

        def resolve(node_id: str | None) -> str | None:
            if node_id is None:
                return None
            if node_id in known:
                return node_id
            # Models occasionally answer with a name where an id was asked for.
            return by_name.get(name_key(node_id))

        def resolve_names(names: Sequence[str] | None) -> list[str]:
            resolved: list[str] = []
            for name in names or []:
                found = resolve(name) or by_name.get(name_key(name))
                if found is not None and found not in resolved:
                    resolved.append(found)
            return resolved

        try:
            return self._build(raw, resolve, resolve_names, loaded)
        except (ValidationError, ValueError) as exc:
            logger.info("dropping unusable proposed operation %s: %s", raw.op_type, exc)
            return None

    def _build(
        self,
        raw: ProposedOperation,
        resolve: Callable[[str | None], str | None],
        resolve_names: Callable[[Sequence[str] | None], list[str]],
        loaded: LoadedSubject,
    ) -> Operation | None:
        """Assemble one typed operation from the model's flat record.

        :param raw: The model's operation record.
        :param resolve: Maps a reference to a node id, or None if it is unknown.
        :param resolve_names: Maps names to the node ids they resolve to.
        :param loaded: The subject being refined.
        """
        node_id = resolve(raw.node_id)

        match raw.op_type:
            case "add_node":
                if not raw.name or not raw.definition:
                    return None
                return AddNode(
                    node=NewNodeSpec(
                        name=raw.name,
                        definition=raw.definition,
                        tier=raw.tier or 2,
                        prereq_ids=resolve_names(raw.prereq_names),
                    )
                )
            case "remove_node":
                return (
                    None
                    if node_id is None
                    else RemoveNode(node_id=node_id, cascade=bool(raw.cascade))
                )
            case "merge_nodes":
                ids = [i for i in (resolve(v) for v in raw.node_ids or []) if i]
                if len(ids) < 2 or not raw.name or not raw.definition:
                    return None
                return MergeNodes(
                    node_ids=ids,
                    new_name=raw.name,
                    new_definition=raw.definition,
                    tier=raw.tier,
                )
            case "split_node":
                if node_id is None or not raw.children or len(raw.children) < 2:
                    return None
                parent_tier = loaded.graph.tier(node_id)
                return SplitNode(
                    node_id=node_id,
                    into=[
                        NewNodeSpec(
                            name=child.name,
                            definition=child.definition,
                            tier=child.tier or parent_tier,
                            prereq_ids=resolve_names(child.prerequisites),
                        )
                        for child in raw.children
                    ],
                )
            case "retier_node":
                return (
                    None
                    if node_id is None or raw.tier is None
                    else RetierNode(node_id=node_id, tier=raw.tier)
                )
            case "add_edge" | "remove_edge":
                prereq = resolve(raw.prereq_id)
                if prereq is None or node_id is None:
                    return None
                cls = AddEdge if raw.op_type == "add_edge" else RemoveEdge
                return cls(prereq_id=prereq, node_id=node_id)
            case "retarget_edge":
                prereq = resolve(raw.prereq_id)
                new_prereq = resolve(raw.new_prereq_id) or prereq
                new_node = resolve(raw.new_node_id) or node_id
                if None in (prereq, node_id, new_prereq, new_node):
                    return None
                return RetargetEdge(
                    prereq_id=str(prereq),
                    node_id=str(node_id),
                    new_prereq_id=str(new_prereq),
                    new_node_id=str(new_node),
                )
            case "rename_node":
                return (
                    None
                    if node_id is None or not raw.name
                    else RenameNode(node_id=node_id, name=raw.name)
                )
            case "redefine_node":
                return (
                    None
                    if node_id is None or not raw.definition
                    else RedefineNode(node_id=node_id, definition=raw.definition)
                )

    # --- reading -------------------------------------------------------------

    async def read(self, changeset_id: str) -> ChangesetRead:
        """Render a changeset and its operations for review.

        :param changeset_id: The changeset to read.
        :raises LookupError: If it does not exist.
        """
        changeset = await self._changesets.get(changeset_id)
        if changeset is None:
            raise LookupError(changeset_id)
        loaded = await self._loader.load(changeset.subject_id, apply_decay=False)
        names = {node_id: meta.name for node_id, meta in loaded.graph.nodes.items()}
        ops = await self._changesets.ops_for(changeset_id)
        return ChangesetRead(
            id=changeset.id,
            subject_id=changeset.subject_id,
            request_text=changeset.request_text,
            rationale=changeset.rationale,
            status=changeset.status,
            base_version=changeset.base_version,
            result_version=changeset.result_version,
            validation_error=changeset.validation_error,
            created_at=changeset.created_at,
            operations=[
                OperationRead(
                    id=op.id,
                    seq=op.seq,
                    op_type=op.op_type,
                    rationale=op.rationale,
                    accepted=op.accepted,
                    applied=op.applied,
                    operation=_OPERATION.validate_python(op.payload),
                    summary=summarize(_OPERATION.validate_python(op.payload), names),
                )
                for op in ops
            ],
        )

    async def log(self, subject_id: str) -> list[ChangesetSummary]:
        """The subject's changeset history, newest first.

        :param subject_id: The subject to read.
        """
        changesets = await self._changesets.log_for(subject_id)
        counts = await self._changesets.op_counts([c.id for c in changesets])
        return [
            ChangesetSummary(
                id=changeset.id,
                request_text=changeset.request_text,
                rationale=changeset.rationale,
                status=changeset.status,
                base_version=changeset.base_version,
                result_version=changeset.result_version,
                created_at=changeset.created_at,
                operation_count=counts.get(changeset.id, (0, 0))[0],
                accepted_count=counts.get(changeset.id, (0, 0))[1],
            )
            for changeset in changesets
        ]

    async def preview(
        self, changeset_id: str, accepted_ids: set[str] | None = None
    ) -> ChangesetPreview:
        """Show the graph a set of operations would produce, without committing.

        :param changeset_id: The changeset to preview.
        :param accepted_ids: Operation ids to include; defaults to all of them.
        """
        changeset = await self._changesets.get(changeset_id)
        if changeset is None:
            raise LookupError(changeset_id)
        loaded = await self._loader.load(changeset.subject_id, apply_decay=False)
        ops = await self._changesets.ops_for(changeset_id)
        chosen = [op for op in ops if accepted_ids is None or op.id in accepted_ids]
        try:
            plan = self._plan(loaded, chosen)
        except MutationError as exc:
            return ChangesetPreview(
                valid=False, error=str(exc), node_count=0, edge_count=0, nodes=[]
            )
        error = validate_plan(
            plan,
            protected=await self._protected(loaded.subject.id),
            existing_name_keys=await self._name_keys(loaded.subject.id),
            key_of=name_key,
        )
        return ChangesetPreview(
            valid=error is None,
            error=error,
            node_count=len(plan.nodes),
            edge_count=len(plan.edges),
            nodes=[
                GraphPreviewNode(id=node_id, name=name, tier=tier, change=change)
                for node_id, name, tier, change in preview_changes(plan, loaded.graph)
            ],
        )

    # --- committing ----------------------------------------------------------

    async def commit(self, changeset_id: str, payload: CommitRequest) -> CommitResult:
        """Apply the operations the learner accepted.

        :param changeset_id: The changeset to commit.
        :param payload: A verdict for every operation in the changeset.
        :raises LookupError: If the changeset does not exist.
        :raises IncompleteReview: If any operation has no verdict.
        :raises ChangesetRejected: If the accepted set would break the graph.
        """
        changeset = await self._changesets.get(changeset_id)
        if changeset is None:
            raise LookupError(changeset_id)
        if changeset.status == ChangesetStatus.COMMITTED:
            raise ChangesetRejected("this changeset has already been committed")

        ops = await self._changesets.ops_for(changeset_id)
        decisions = {d.operation_id: d.accepted for d in payload.decisions}
        missing = [op.id for op in ops if op.id not in decisions]
        if missing:
            raise IncompleteReview(f"{len(missing)} operation(s) have no accept or reject decision")

        for op in ops:
            op.accepted = decisions[op.id]
        accepted = [op for op in ops if op.accepted]

        loaded = await self._loader.load(changeset.subject_id)
        try:
            plan = self._plan(loaded, accepted)
        except MutationError as exc:
            await self._mark_invalid(changeset, str(exc))
            raise ChangesetRejected(str(exc)) from exc

        error = validate_plan(
            plan,
            protected=await self._protected(loaded.subject.id),
            existing_name_keys=await self._name_keys(loaded.subject.id),
            key_of=name_key,
        )
        if error is not None:
            await self._mark_invalid(changeset, error)
            raise ChangesetRejected(error)

        version = loaded.subject.graph_version + (0 if plan.is_empty else 1)
        await self._write(loaded, plan, version)
        await self._reconcile_mastery(loaded, plan)

        loaded.subject.graph_version = version
        changeset.status = ChangesetStatus.COMMITTED
        changeset.result_version = version
        changeset.validation_error = None
        for op in accepted:
            op.applied = True
            op.result_node_ids = [
                draft.node_id for draft in plan.added if draft.node_id in plan.nodes
            ]
        await self._session.commit()

        return CommitResult(
            changeset=changeset,
            graph_version=version,
            applied=len(accepted),
            notes=plan.notes,
        )

    def _plan(self, loaded: LoadedSubject, ops: Sequence[ChangesetOp]) -> MutationPlan:
        """Simulate a set of stored operations.

        :param loaded: The subject being changed.
        :param ops: Operation rows to apply, in order.
        """
        operations = [_OPERATION.validate_python(op.payload) for op in ops]
        return plan_mutation(
            loaded.graph,
            loaded.states,
            {node_id: node.definition for node_id, node in loaded.nodes.items()},
            operations,
            self._params,
        )

    async def _mark_invalid(self, changeset: Changeset, error: str) -> None:
        """Record why a changeset could not be committed.

        The changeset stays in the log with its reason, so a rejected refinement is
        visible rather than vanishing.

        :param changeset: The rejected changeset.
        :param error: The reason.
        """
        changeset.status = ChangesetStatus.INVALID
        changeset.validation_error = error
        await self._session.commit()

    async def _protected(self, subject_id: str) -> dict[str, str]:
        """Node ids that a pending lesson-plan unit still teaches.

        :param subject_id: The subject to check.
        """
        units = await self._plans.active_units(subject_id)
        return {
            unit.node_id: unit.title
            for unit in units
            if unit.status in {UnitStatus.PENDING, UnitStatus.IN_PROGRESS}
        }

    async def _name_keys(self, subject_id: str) -> dict[str, str]:
        """Normalized names of live concepts, mapped to their id.

        :param subject_id: The subject to read.
        """
        return {node.name_key: node.id for node in await self._graph.live_nodes(subject_id)}

    async def _write(self, loaded: LoadedSubject, plan: MutationPlan, version: int) -> None:
        """Write a validated plan to the database.

        :param loaded: The subject being changed.
        :param plan: The validated plan.
        :param version: The graph version these changes belong to.
        """
        await self._resolve_resurrections(loaded, plan)

        for node_id in plan.removed:
            node = loaded.nodes.get(node_id)
            if node is not None:
                self._graph.soft_delete_node(node, version=version)

        for draft in plan.added:
            await self._create_node(loaded, draft, version)

        for node_id, name in plan.renamed.items():
            node = loaded.nodes.get(node_id)
            if node is not None:
                node.name = name
                node.name_key = name_key(name)
        for node_id, definition in plan.redefined.items():
            node = loaded.nodes.get(node_id)
            if node is not None:
                node.definition = definition
        for node_id, tier in plan.retiered.items():
            node = loaded.nodes.get(node_id)
            if node is not None:
                node.tier = tier

        existing = {
            (e.prereq_id, e.node_id): e for e in await self._graph.live_edges(loaded.subject.id)
        }
        for pair in plan.edges:
            if pair not in existing:
                await self._graph.add_edge(loaded.subject.id, pair[0], pair[1], version=version)
        for pair, edge in existing.items():
            if pair not in plan.edges:
                self._graph.soft_delete_edge(edge, version=version)
        await self._session.flush()

    async def _resolve_resurrections(self, loaded: LoadedSubject, plan: MutationPlan) -> None:
        """Point new concepts at existing soft-deleted rows with the same name.

        This is what makes "re-adding a removed concept restores my history" true.
        The mastery record was never deleted, so the estimate comes back with the
        node -- but only if the plan's edges and seeds are rewritten to the
        resurrected row's id *before* anything is written. Doing the substitution at
        insert time instead would leave edges pointing at an id that never existed.

        :param loaded: The subject being changed.
        :param plan: The plan about to be written, mutated in place.
        """
        for draft in plan.added:
            existing = await self._graph.find_by_key(loaded.subject.id, name_key(draft.name))
            if existing is None or existing.deleted_at is None:
                continue
            old_id, new_id_ = draft.node_id, existing.id
            if old_id == new_id_:
                continue
            draft.node_id = new_id_
            plan.nodes[new_id_] = plan.nodes.pop(old_id)
            plan.edges = {
                (new_id_ if p == old_id else p, new_id_ if n == old_id else n)
                for p, n in plan.edges
            }
            # Drop the seed rather than carrying it over. The concept already has a
            # mastery record holding everything the learner ever demonstrated about
            # it, and overwriting that with a fresh prerequisite-derived seed is
            # precisely the data loss re-adding is supposed to avoid.
            plan.seeds.pop(old_id, None)
            plan.restored.add(new_id_)
            # The row is being revived, so it is no longer a removal.
            plan.removed.discard(new_id_)
            plan.notes.append(
                f"{draft.name!r} was previously removed; its mastery history has been restored"
            )

    async def _create_node(self, loaded: LoadedSubject, draft: NodeDraft, version: int) -> None:
        """Insert a new concept, or revive the soft-deleted row it resolved to.

        :param loaded: The subject being changed.
        :param draft: The concept to create.
        :param version: The graph version this belongs to.
        """
        key = name_key(draft.name)
        existing = await self._graph.find_by_key(loaded.subject.id, key)
        if existing is not None:
            self._graph.restore_node(existing, version=version)
            existing.name = draft.name
            existing.definition = draft.definition
            existing.tier = draft.tier
            return

        self._graph.add_node(
            ConceptNode(
                id=draft.node_id,
                subject_id=loaded.subject.id,
                name=draft.name,
                name_key=key,
                definition=draft.definition,
                tier=draft.tier,
                origin=NodeOrigin.REFINEMENT,
                introduced_in_version=version,
                superseded_by=draft.sources[0] if draft.sources else None,
            )
        )
        self._graph.add_mastery(
            MasteryRecord(
                subject_id=loaded.subject.id,
                node_id=draft.node_id,
                mastery=self._params.default_seed_mastery,
                confidence=self._params.seeded_confidence,
            )
        )

    async def _reconcile_mastery(self, loaded: LoadedSubject, plan: MutationPlan) -> None:
        """Carry mastery across the structural change.

        Two things happen, in this order:

        1. Concepts created by a split, a merge, or an addition get the mastery the
           reconciliation rules prescribe. Their evidence cannot be replayed --
           there are no responses against a node that did not exist -- so this is
           the only place their estimate comes from.
        2. If any prerequisite edge moved, every other estimate is recomputed by
           replaying the response log against the new graph. A propagated estimate
           depends on the edges that existed when the answer was given; those have
           just changed, so the old posterior no longer follows from the evidence.

        Removed concepts are untouched. Their rows stay, holding their history for
        if the concept comes back.

        :param loaded: The subject being changed.
        :param plan: The committed plan.
        """
        await self._session.flush()
        records = {r.node_id: r for r in await self._graph.mastery_records(loaded.subject.id)}

        for node_id, seeded in plan.seeds.items():
            record = records.get(node_id)
            if record is None:
                record = self._graph.add_mastery(
                    MasteryRecord(
                        subject_id=loaded.subject.id,
                        node_id=node_id,
                        mastery=seeded.mastery,
                        confidence=seeded.confidence,
                    )
                )
                records[node_id] = record
            else:
                record.mastery = seeded.mastery
                record.confidence = seeded.confidence
            record.decayed_at = utcnow()

        if not plan.edges_changed:
            return

        candidate = plan.candidate_graph()
        observations = await self._assessment.observations(loaded.subject.id)
        seeds = {
            node_id: MasteryState(
                mastery=records[node_id].mastery, confidence=records[node_id].confidence
            )
            for node_id in (set(plan.seeds) | plan.restored)
            if node_id in records
        }
        result = replay(candidate, observations, params=self._params, seeds=seeds)

        # A concept with no responses anywhere gets only its prior, so the
        # consistency pass below is what keeps it in line with its new prerequisites.
        smoothed = smooth_posterior(
            candidate,
            result.states,
            affected=affected_subgraph(plan, candidate),
            params=self._params,
            protected=frozenset(plan.seeds) | frozenset(plan.restored),
        )
        result.states.update(smoothed)

        for node_id, state in result.states.items():
            record = records.get(node_id)
            if record is None:
                continue
            record.mastery = state.mastery
            record.confidence = state.confidence
            touched = result.last_touched.get(node_id)
            if touched is not None:
                record.last_seen_at = touched
            record.decayed_at = utcnow()
