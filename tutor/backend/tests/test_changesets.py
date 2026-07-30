"""Tests for the refine, review, commit flow and for proactive suggestions.

The acceptance criteria this file covers:

* no refinement ever commits without per-operation approval;
* no committed changeset can produce a cyclic graph;
* splitting a node mid-course does not destroy mastery history;
* re-adding a removed node restores it.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.llm.fake import FakeLLMAdapter, ParsedNode
from app.llm.schemas import GeneratedNode, ProposedChangeset, ProposedOperation
from app.mastery.state import MasteryParams
from app.models.changeset import Changeset, ChangesetOp
from app.models.enums import ChangesetStatus, SuggestionKind, UnitStatus
from app.models.graph import ConceptNode, MasteryRecord
from app.models.plan import LessonPlan, PlanUnit
from app.schemas.changeset import CommitRequest, OperationDecision
from app.services.changeset_service import (
    ChangesetRejected,
    ChangesetService,
    IncompleteReview,
)
from app.services.suggestion_service import SuggestionService
from tests.test_subjects import build_subject


async def node_named(session: AsyncSession, name: str) -> ConceptNode:
    """Fetch a concept by exact name.

    :param session: The test session.
    :param name: The concept's name.
    """
    result = await session.execute(select(ConceptNode).where(ConceptNode.name == name))
    return result.scalars().one()


async def mastery_of(session: AsyncSession, node_id: str) -> MasteryRecord:
    """Fetch a concept's mastery record.

    :param session: The test session.
    :param node_id: The concept's id.
    """
    result = await session.execute(select(MasteryRecord).where(MasteryRecord.node_id == node_id))
    return result.scalars().one()


def propose_ops(
    *ops: ProposedOperation,
) -> Callable[[str, list[ParsedNode]], ProposedChangeset]:
    """Build a changeset hook returning a fixed set of operations.

    :param ops: Operations the model should propose.
    """

    def hook(_prompt: str, _nodes: list[ParsedNode]) -> ProposedChangeset:
        return ProposedChangeset(rationale="Because you asked.", operations=list(ops))

    return hook


# --- proposing -----------------------------------------------------------------


async def test_a_proposal_commits_nothing(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """Refining produces operations awaiting a verdict, and no graph change."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    target = await node_named(session, "Statistical Mechanics Concept 01")
    fake_llm.changeset_hook = propose_ops(
        ProposedOperation(
            op_type="rename_node", rationale="Clearer name.", node_id=target.id, name="Renamed"
        )
    )

    service = ChangesetService(session, fake_llm, app_settings)
    changeset = await service.propose(subject_id, "rename the first concept")

    read = await service.read(changeset.id)
    assert read.status == ChangesetStatus.PROPOSED
    assert len(read.operations) == 1
    assert read.operations[0].accepted is None, "awaiting review"
    assert read.operations[0].applied is False
    assert read.operations[0].summary.startswith("Rename")

    await session.refresh(target)
    assert target.name == "Statistical Mechanics Concept 01", "the graph is untouched"


async def test_operations_that_cannot_be_resolved_are_dropped(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """A proposal naming a concept that does not exist loses that operation only."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    target = await node_named(session, "Statistical Mechanics Concept 01")
    fake_llm.changeset_hook = propose_ops(
        ProposedOperation(op_type="rename_node", rationale="ok", node_id="ghost", name="X"),
        ProposedOperation(op_type="rename_node", rationale="ok", node_id=target.id, name="Kept"),
    )
    service = ChangesetService(session, fake_llm, app_settings)
    changeset = await service.propose(subject_id, "rename things")
    read = await service.read(changeset.id)
    assert len(read.operations) == 1


async def test_a_proposal_may_reference_concepts_by_name(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """The model sometimes answers with a name where an id was asked for."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    fake_llm.changeset_hook = propose_ops(
        ProposedOperation(
            op_type="retier_node",
            rationale="Harder than it looks.",
            node_id="Statistical Mechanics Concept 01",
            tier=3,
        )
    )
    service = ChangesetService(session, fake_llm, app_settings)
    changeset = await service.propose(subject_id, "bump a tier")
    assert len((await service.read(changeset.id)).operations) == 1


# --- committing ----------------------------------------------------------------


async def test_commit_applies_only_the_accepted_operations(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """Rejecting an operation means it does not happen."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    first = await node_named(session, "Statistical Mechanics Concept 01")
    second = await node_named(session, "Statistical Mechanics Concept 02")
    fake_llm.changeset_hook = propose_ops(
        ProposedOperation(
            op_type="rename_node", rationale="a", node_id=first.id, name="Accepted Rename"
        ),
        ProposedOperation(
            op_type="rename_node", rationale="b", node_id=second.id, name="Rejected Rename"
        ),
    )
    service = ChangesetService(session, fake_llm, app_settings)
    changeset = await service.propose(subject_id, "rename both")
    ops = (await service.read(changeset.id)).operations

    result = await service.commit(
        changeset.id,
        CommitRequest(
            decisions=[
                OperationDecision(operation_id=ops[0].id, accepted=True),
                OperationDecision(operation_id=ops[1].id, accepted=False),
            ]
        ),
    )
    assert result.applied == 1
    await session.refresh(first)
    await session.refresh(second)
    assert first.name == "Accepted Rename"
    assert second.name == "Statistical Mechanics Concept 02"


async def test_commit_requires_a_verdict_for_every_operation(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """An unfinished review is refused rather than guessed at."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    first = await node_named(session, "Statistical Mechanics Concept 01")
    second = await node_named(session, "Statistical Mechanics Concept 02")
    fake_llm.changeset_hook = propose_ops(
        ProposedOperation(op_type="rename_node", rationale="a", node_id=first.id, name="A"),
        ProposedOperation(op_type="rename_node", rationale="b", node_id=second.id, name="B"),
    )
    service = ChangesetService(session, fake_llm, app_settings)
    changeset = await service.propose(subject_id, "rename both")
    ops = (await service.read(changeset.id)).operations

    with pytest.raises(IncompleteReview):
        await service.commit(
            changeset.id,
            CommitRequest(decisions=[OperationDecision(operation_id=ops[0].id, accepted=True)]),
        )
    await session.refresh(first)
    assert first.name != "A", "nothing is applied when the review is incomplete"


async def test_commit_bumps_the_graph_version(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """A committed change advances the version; a no-op change does not."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    target = await node_named(session, "Statistical Mechanics Concept 03")
    fake_llm.changeset_hook = propose_ops(
        ProposedOperation(op_type="rename_node", rationale="a", node_id=target.id, name="Bumped")
    )
    service = ChangesetService(session, fake_llm, app_settings)
    changeset = await service.propose(subject_id, "rename")
    ops = (await service.read(changeset.id)).operations
    result = await service.commit(
        changeset.id,
        CommitRequest(decisions=[OperationDecision(operation_id=ops[0].id, accepted=True)]),
    )
    assert result.graph_version == 2
    assert result.changeset.result_version == 2


async def test_rejecting_everything_leaves_the_version_alone(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """A review that accepts nothing is a valid outcome, not a version bump."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    target = await node_named(session, "Statistical Mechanics Concept 03")
    fake_llm.changeset_hook = propose_ops(
        ProposedOperation(op_type="rename_node", rationale="a", node_id=target.id, name="No")
    )
    service = ChangesetService(session, fake_llm, app_settings)
    changeset = await service.propose(subject_id, "rename")
    ops = (await service.read(changeset.id)).operations
    result = await service.commit(
        changeset.id,
        CommitRequest(decisions=[OperationDecision(operation_id=ops[0].id, accepted=False)]),
    )
    assert result.graph_version == 1
    assert result.applied == 0


async def test_a_cyclic_changeset_is_refused_and_the_graph_is_unchanged(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """The headline guarantee, enforced at the commit boundary."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    service = ChangesetService(session, fake_llm, app_settings)
    # Reversing an edge that already exists is the shortest route to a cycle.
    existing = (await service._graph.live_edges(subject_id))[0]
    fake_llm.changeset_hook = propose_ops(
        ProposedOperation(
            op_type="add_edge",
            rationale="wrong way round",
            prereq_id=existing.node_id,
            node_id=existing.prereq_id,
        )
    )
    changeset = await service.propose(subject_id, "reverse a dependency")
    ops = (await service.read(changeset.id)).operations

    with pytest.raises(ChangesetRejected):
        await service.commit(
            changeset.id,
            CommitRequest(decisions=[OperationDecision(operation_id=ops[0].id, accepted=True)]),
        )

    stored = await session.get(Changeset, changeset.id)
    assert stored is not None
    assert stored.status == ChangesetStatus.INVALID
    assert stored.validation_error is not None
    assert stored.result_version is None

    edges = await service._graph.live_edges(subject_id)
    assert not any(
        e.prereq_id == existing.node_id and e.node_id == existing.prereq_id for e in edges
    )


async def test_removing_a_concept_the_plan_teaches_is_refused(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """A pending lesson-plan unit protects its concept."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    target = await node_named(session, "Statistical Mechanics Concept 20")
    plan = LessonPlan(subject_id=subject_id, graph_version=1)
    session.add(plan)
    await session.flush()
    session.add(
        PlanUnit(
            plan_id=plan.id,
            subject_id=subject_id,
            node_id=target.id,
            seq=0,
            title="Unit 1",
            objective="Learn it.",
            status=UnitStatus.PENDING,
        )
    )
    await session.commit()

    fake_llm.changeset_hook = propose_ops(
        ProposedOperation(op_type="remove_node", rationale="not needed", node_id=target.id)
    )
    service = ChangesetService(session, fake_llm, app_settings)
    changeset = await service.propose(subject_id, "drop it")
    ops = (await service.read(changeset.id)).operations
    with pytest.raises(ChangesetRejected, match="lesson plan"):
        await service.commit(
            changeset.id,
            CommitRequest(decisions=[OperationDecision(operation_id=ops[0].id, accepted=True)]),
        )


async def test_a_committed_changeset_cannot_be_committed_twice(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """The log is append-only; a commit is not repeatable."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    target = await node_named(session, "Statistical Mechanics Concept 04")
    fake_llm.changeset_hook = propose_ops(
        ProposedOperation(op_type="rename_node", rationale="a", node_id=target.id, name="Once")
    )
    service = ChangesetService(session, fake_llm, app_settings)
    changeset = await service.propose(subject_id, "rename")
    ops = (await service.read(changeset.id)).operations
    decisions = CommitRequest(decisions=[OperationDecision(operation_id=ops[0].id, accepted=True)])
    await service.commit(changeset.id, decisions)
    with pytest.raises(ChangesetRejected, match="already been committed"):
        await service.commit(changeset.id, decisions)


# --- mastery reconciliation ----------------------------------------------------


async def test_splitting_a_node_preserves_its_mastery_history(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """Each child keeps the parent's estimate with halved confidence."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    parent = await node_named(session, "Statistical Mechanics Concept 10")
    record = await mastery_of(session, parent.id)
    record.mastery = 0.84
    record.confidence = 0.62
    await session.commit()

    fake_llm.changeset_hook = propose_ops(
        ProposedOperation(
            op_type="split_node",
            rationale="Two ideas in one.",
            node_id=parent.id,
            children=[
                GeneratedNode(
                    name="Split Part A", definition="First half.", tier=3, prerequisites=[]
                ),
                GeneratedNode(
                    name="Split Part B", definition="Second half.", tier=3, prerequisites=[]
                ),
            ],
        )
    )
    service = ChangesetService(session, fake_llm, app_settings)
    changeset = await service.propose(subject_id, "split it")
    ops = (await service.read(changeset.id)).operations
    await service.commit(
        changeset.id,
        CommitRequest(decisions=[OperationDecision(operation_id=ops[0].id, accepted=True)]),
    )

    for name in ("Split Part A", "Split Part B"):
        child = await node_named(session, name)
        child_record = await mastery_of(session, child.id)
        assert child_record.mastery == pytest.approx(0.84, abs=0.05)
        assert child_record.confidence == pytest.approx(0.31, abs=0.05)

    await session.refresh(parent)
    assert parent.deleted_at is not None, "the parent is soft-deleted, not destroyed"
    kept = await mastery_of(session, parent.id)
    assert kept.mastery == pytest.approx(0.84), "its history is still on the record"


async def test_re_adding_a_removed_concept_restores_its_history(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """The acceptance criterion: remove then re-add, and the estimate comes back."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    target = await node_named(session, "Statistical Mechanics Concept 24")
    record = await mastery_of(session, target.id)
    record.mastery = 0.77
    record.confidence = 0.55
    await session.commit()
    original_id, original_name = target.id, target.name

    service = ChangesetService(session, fake_llm, app_settings)

    fake_llm.changeset_hook = propose_ops(
        ProposedOperation(op_type="remove_node", rationale="drop", node_id=original_id)
    )
    removal = await service.propose(subject_id, "remove it")
    ops = (await service.read(removal.id)).operations
    await service.commit(
        removal.id,
        CommitRequest(decisions=[OperationDecision(operation_id=ops[0].id, accepted=True)]),
    )
    await session.refresh(target)
    assert target.deleted_at is not None

    # Re-adding states the prerequisites explicitly: reviving a row restores its
    # mastery history, not its position in the graph.
    anchor = await node_named(session, "Statistical Mechanics Concept 20")
    fake_llm.changeset_hook = propose_ops(
        ProposedOperation(
            op_type="add_node",
            rationale="I want it back",
            name=original_name,
            definition="Back again.",
            tier=5,
            prereq_names=[anchor.name],
        )
    )
    restore = await service.propose(subject_id, "put it back")
    ops = (await service.read(restore.id)).operations
    result = await service.commit(
        restore.id,
        CommitRequest(decisions=[OperationDecision(operation_id=ops[0].id, accepted=True)]),
    )

    # Re-fetch rather than refresh in place: the point of the assertion is that the
    # *same row* came back, so it should be looked up by name like any other read.
    revived = await node_named(session, original_name)
    assert revived.id == original_id, "the original row was revived, not a new one"
    assert revived.deleted_at is None
    restored = await mastery_of(session, original_id)
    assert restored.mastery == pytest.approx(0.77, abs=0.05)
    assert any("restored" in note for note in result.notes)


async def test_a_merge_takes_the_minimum_confidence_of_its_inputs(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """A merged concept is only as well understood as its least-known part."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    first = await node_named(session, "Statistical Mechanics Concept 01")
    second = await node_named(session, "Statistical Mechanics Concept 02")
    for node, mastery, confidence in ((first, 0.9, 0.8), (second, 0.5, 0.15)):
        record = await mastery_of(session, node.id)
        record.mastery, record.confidence = mastery, confidence
    await session.commit()

    fake_llm.changeset_hook = propose_ops(
        ProposedOperation(
            op_type="merge_nodes",
            rationale="Same idea twice.",
            node_ids=[first.id, second.id],
            name="Merged Concept",
            definition="Both at once.",
        )
    )
    service = ChangesetService(session, fake_llm, app_settings)
    changeset = await service.propose(subject_id, "merge them")
    ops = (await service.read(changeset.id)).operations
    await service.commit(
        changeset.id,
        CommitRequest(decisions=[OperationDecision(operation_id=ops[0].id, accepted=True)]),
    )

    merged = await node_named(session, "Merged Concept")
    record = await mastery_of(session, merged.id)
    assert record.confidence == pytest.approx(0.15, abs=0.03), "the minimum"
    assert record.mastery == pytest.approx((0.9 * 0.8 + 0.5 * 0.15) / 0.95, abs=0.05)


# --- log and endpoints ---------------------------------------------------------


async def test_the_changeset_log_records_rejected_attempts(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """A refused refinement stays visible with its reason, rather than vanishing."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    service = ChangesetService(session, fake_llm, app_settings)
    existing = (await service._graph.live_edges(subject_id))[0]
    fake_llm.changeset_hook = propose_ops(
        ProposedOperation(
            op_type="add_edge",
            rationale="x",
            prereq_id=existing.node_id,
            node_id=existing.prereq_id,
        )
    )
    changeset = await service.propose(subject_id, "break it")
    ops = (await service.read(changeset.id)).operations
    with pytest.raises(ChangesetRejected):
        await service.commit(
            changeset.id,
            CommitRequest(decisions=[OperationDecision(operation_id=ops[0].id, accepted=True)]),
        )
    log = await service.log(subject_id)
    assert len(log) == 1
    assert log[0].status == ChangesetStatus.INVALID
    assert log[0].operation_count == 1


async def test_refine_and_commit_over_http(client: AsyncClient, fake_llm: FakeLLMAdapter) -> None:
    """The endpoints enforce the same propose-review-commit split."""
    created = (await client.post("/subjects", json={"name": "Optics"})).json()
    graph = (await client.get(f"/subjects/{created['id']}/graph")).json()
    target = graph["nodes"][0]

    fake_llm.changeset_hook = propose_ops(
        ProposedOperation(
            op_type="rename_node", rationale="Clearer.", node_id=target["id"], name="Refraction"
        )
    )
    proposed = await client.post(
        f"/subjects/{created['id']}/graph/refine", json={"request": "rename the first one"}
    )
    assert proposed.status_code == 201
    body = proposed.json()
    assert body["status"] == ChangesetStatus.PROPOSED
    assert body["operations"][0]["accepted"] is None

    preview = await client.get(f"/changesets/{body['id']}/preview")
    assert preview.status_code == 200
    assert preview.json()["valid"] is True

    committed = await client.post(
        f"/subjects/{created['id']}/changesets/{body['id']}",
        json={"decisions": [{"operation_id": body["operations"][0]["id"], "accepted": True}]},
    )
    assert committed.status_code == 200
    assert committed.json()["status"] == ChangesetStatus.COMMITTED
    assert committed.json()["result_version"] == 2

    after = (await client.get(f"/subjects/{created['id']}/graph")).json()
    assert any(node["name"] == "Refraction" for node in after["nodes"])


async def test_committing_an_invalid_changeset_over_http_is_a_409(
    client: AsyncClient, fake_llm: FakeLLMAdapter
) -> None:
    """The client is told why, and the graph does not move."""
    created = (await client.post("/subjects", json={"name": "Topology"})).json()
    graph = (await client.get(f"/subjects/{created['id']}/graph")).json()
    by_tier = sorted(graph["nodes"], key=lambda n: n["tier"])
    low, high = by_tier[0], by_tier[-1]

    fake_llm.changeset_hook = propose_ops(
        ProposedOperation(
            op_type="add_edge", rationale="x", prereq_id=high["id"], node_id=low["id"]
        )
    )
    proposed = (
        await client.post(f"/subjects/{created['id']}/graph/refine", json={"request": "invert"})
    ).json()
    response = await client.post(
        f"/subjects/{created['id']}/changesets/{proposed['id']}",
        json={"decisions": [{"operation_id": proposed["operations"][0]["id"], "accepted": True}]},
    )
    assert response.status_code == 409
    assert "circular" in response.json()["detail"] or "prerequisite" in response.json()["detail"]


async def test_incomplete_review_over_http_is_a_400(
    client: AsyncClient, fake_llm: FakeLLMAdapter
) -> None:
    """Omitting a verdict is a client error, not a silent partial commit."""
    created = (await client.post("/subjects", json={"name": "Rust"})).json()
    graph = (await client.get(f"/subjects/{created['id']}/graph")).json()
    fake_llm.changeset_hook = propose_ops(
        ProposedOperation(
            op_type="rename_node", rationale="a", node_id=graph["nodes"][0]["id"], name="A"
        ),
        ProposedOperation(
            op_type="rename_node", rationale="b", node_id=graph["nodes"][1]["id"], name="B"
        ),
    )
    proposed = (
        await client.post(f"/subjects/{created['id']}/graph/refine", json={"request": "rename"})
    ).json()
    response = await client.post(
        f"/subjects/{created['id']}/changesets/{proposed['id']}",
        json={"decisions": [{"operation_id": proposed["operations"][0]["id"], "accepted": True}]},
    )
    assert response.status_code == 400


# --- suggestions ---------------------------------------------------------------


async def test_an_orphan_is_surfaced_as_a_suggestion(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """A concept above tier 1 with nothing leading to it is reported."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    stranded = await node_named(session, "Statistical Mechanics Concept 24")
    for edge in await ChangesetService(session, fake_llm, app_settings)._graph.live_edges(
        subject_id
    ):
        if edge.node_id == stranded.id:
            edge.deleted_at = None
            await session.delete(edge)
    await session.commit()

    service = SuggestionService(session, MasteryParams.from_settings(app_settings))
    created = await service.refresh(subject_id)
    kinds = {suggestion.kind for suggestion in created}
    assert SuggestionKind.ORPHAN_NODE in kinds
    orphan = next(s for s in created if s.kind == SuggestionKind.ORPHAN_NODE)
    assert stranded.name in orphan.summary


async def test_suggestions_are_not_raised_twice(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """Refreshing repeatedly must not accumulate duplicates."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    service = SuggestionService(session, MasteryParams.from_settings(app_settings))
    first = await service.refresh(subject_id)
    second = await service.refresh(subject_id)
    assert second == []
    assert len(await service.open_for(subject_id)) == len(first)


async def test_a_dismissed_suggestion_does_not_come_back(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """Rejecting a proposal is a decision the app has to remember."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    stranded = await node_named(session, "Statistical Mechanics Concept 24")
    for edge in await ChangesetService(session, fake_llm, app_settings)._graph.live_edges(
        subject_id
    ):
        if edge.node_id == stranded.id:
            await session.delete(edge)
    await session.commit()

    service = SuggestionService(session, MasteryParams.from_settings(app_settings))
    created = await service.refresh(subject_id)
    orphan = next(s for s in created if s.kind == SuggestionKind.ORPHAN_NODE)
    await service.dismiss(orphan.id)
    remaining = await service.open_for(subject_id)
    assert orphan.id not in {s.id for s in remaining}


async def test_suggestions_endpoint_returns_typed_operations(
    client: AsyncClient,
) -> None:
    """Draft operations come back in the same vocabulary the commit endpoint takes."""
    created = (await client.post("/subjects", json={"name": "Go"})).json()
    response = await client.get(f"/subjects/{created['id']}/suggestions")
    assert response.status_code == 200
    for suggestion in response.json():
        for operation in suggestion["operations"]:
            assert "op_type" in operation


async def test_ops_are_marked_applied_after_a_commit(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """The log records which operations actually ran."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    target = await node_named(session, "Statistical Mechanics Concept 06")
    fake_llm.changeset_hook = propose_ops(
        ProposedOperation(op_type="rename_node", rationale="a", node_id=target.id, name="Applied")
    )
    service = ChangesetService(session, fake_llm, app_settings)
    changeset = await service.propose(subject_id, "rename")
    ops = (await service.read(changeset.id)).operations
    await service.commit(
        changeset.id,
        CommitRequest(decisions=[OperationDecision(operation_id=ops[0].id, accepted=True)]),
    )
    stored = (
        (await session.execute(select(ChangesetOp).where(ChangesetOp.changeset_id == changeset.id)))
        .scalars()
        .all()
    )
    assert all(op.applied for op in stored)
    assert all(op.accepted for op in stored)
