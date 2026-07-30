"""Tests for the report, the plan service, and the unit loop."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.llm.fake import FakeLLMAdapter
from app.models.enums import ItemFormat, PlanStatus, QueueKind, UnitStatus
from app.repositories.assessment import AssessmentRepository
from app.repositories.plans import PlanRepository
from app.scheduling.calibration import calibrate
from app.schemas.plan import ExitCheckAnswer, PlanCreate, UnitComplete
from app.services.diagnostic_service import DiagnosticService
from app.services.plan_service import PlanService, UnitAlreadyClosed, UnitItemMismatch
from app.services.report_service import ReportService
from tests.test_subjects import build_subject


async def run_diagnostic(
    session: AsyncSession,
    fake_llm: FakeLLMAdapter,
    settings: Settings,
    subject_id: str,
    *,
    well: bool,
) -> None:
    """Answer a whole diagnostic well or badly, to move estimates off their seeds.

    The answer has to match the format. A multiple-choice item is graded by
    comparing indices, so submitting the word "correct" to one scores zero -- which
    is how a "strong" learner previously came out looking exactly like a weak one.

    :param session: The test session.
    :param fake_llm: The offline adapter.
    :param settings: Test settings.
    :param subject_id: The subject to assess.
    :param well: Whether the learner answers correctly.
    """
    service = DiagnosticService(session, fake_llm, settings)
    diagnostic = await service.start(subject_id)
    for _ in range(60):
        nxt = await service.next_item(diagnostic.id)
        if nxt.item is None:
            return
        await service.answer(diagnostic.id, nxt.item.id, answer_for(nxt.item.item_format, well))
    pytest.fail("the diagnostic did not stop")  # pragma: no cover


def answer_for(item_format: str, well: bool) -> str:
    """Build an answer of the right shape for one item format.

    :param item_format: The item's format.
    :param well: Whether the answer should be a correct one.
    """
    if item_format == ItemFormat.MULTIPLE_CHOICE:
        return "0" if well else "3"
    return "correct" if well else "no idea"


# --- calibration ---------------------------------------------------------------


def test_calibration_withholds_a_verdict_until_it_has_evidence(app_settings: Settings) -> None:
    """Three answers is not enough to judge the spacing, and it says so."""
    result = calibrate([1.0, 1.0, 0.0], app_settings)
    assert result.verdict == "insufficient_data"
    assert result.sample_size == 3


def test_calibration_says_widen_when_retrieval_is_too_easy(app_settings: Settings) -> None:
    """Near-perfect recall means the intervals are shorter than they need to be."""
    result = calibrate([1.0] * 20, app_settings)
    assert result.verdict == "widen"
    assert result.success_rate == 1.0
    assert "too" not in result.advice.lower() or "shorter" in result.advice


def test_calibration_says_tighten_when_retrieval_is_failing(app_settings: Settings) -> None:
    """Recall well under target means reviews are arriving too late."""
    result = calibrate([0.0] * 15 + [1.0] * 5, app_settings)
    assert result.verdict == "tighten"


def test_calibration_is_content_at_the_target_rate(app_settings: Settings) -> None:
    """Around 85% is the goal, not a problem to be fixed."""
    result = calibrate([1.0] * 17 + [0.0] * 3, app_settings)
    assert result.verdict == "on_target"


# --- report --------------------------------------------------------------------


async def test_coverage_is_mean_mastery_not_lessons_completed(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """The headline number measures knowledge, and never counts completions."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    report = await ReportService(session, app_settings).build(subject_id)

    loaded = await ReportService(session, app_settings).load(subject_id)
    expected = sum(state.mastery for state in loaded.states.values()) / len(loaded.states)
    assert report.coverage == pytest.approx(expected, abs=1e-9)
    assert report.total_nodes == len(loaded.graph)


async def test_a_strong_diagnostic_raises_coverage_and_a_weak_one_does_not(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """Coverage tracks the answers, which is the only thing making it honest."""
    strong_id = await build_subject(session, fake_llm, app_settings, name="Strong Subject")
    weak_id = await build_subject(session, fake_llm, app_settings, name="Weak Subject")
    await run_diagnostic(session, fake_llm, app_settings, strong_id, well=True)
    await run_diagnostic(session, fake_llm, app_settings, weak_id, well=False)

    service = ReportService(session, app_settings)
    strong = await service.build(strong_id)
    weak = await service.build(weak_id)
    assert strong.coverage > weak.coverage
    assert strong.mastered_nodes > weak.mastered_nodes


async def test_the_report_always_names_something_to_do(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """Blockers and weaknesses are actionable even at the root tier."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    await run_diagnostic(session, fake_llm, app_settings, subject_id, well=False)
    report = await ReportService(session, app_settings).build(subject_id)

    assert report.weaknesses
    assert report.blocking.target_tier is not None
    assert report.blocking.blockers
    assert report.ready_to_learn


async def test_the_report_counts_responses_and_notices_a_plan(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """Two facts the coverage functions cannot know on their own."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    await run_diagnostic(session, fake_llm, app_settings, subject_id, well=True)

    before = await ReportService(session, app_settings).build(subject_id)
    assert before.diagnostic_responses > 0
    assert not before.has_plan

    await PlanService(session, fake_llm, app_settings).create(subject_id, PlanCreate())
    after = await ReportService(session, app_settings).build(subject_id)
    assert after.has_plan


# --- plan generation -----------------------------------------------------------


async def test_every_plan_unit_is_defensibly_positioned(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """The acceptance criterion, asserted over a plan built from a real graph."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    await run_diagnostic(session, fake_llm, app_settings, subject_id, well=True)
    plan = await PlanService(session, fake_llm, app_settings).create(subject_id, PlanCreate())

    loaded = await ReportService(session, app_settings).load(subject_id)
    position = {unit.node_id: unit.seq for unit in plan.units}
    planned = set(position)
    for unit in plan.units:
        assert unit.placement_reason
        for prereq in loaded.graph.prereqs(unit.node_id):
            if prereq in planned:
                assert position[prereq] < unit.seq
            else:
                assert loaded.states[prereq].mastery >= app_settings.mastery_threshold


async def test_a_plan_skips_what_the_learner_already_knows(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """A learner who tested well is not made to sit through what they proved."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    await run_diagnostic(session, fake_llm, app_settings, subject_id, well=True)

    loaded = await ReportService(session, app_settings).load(subject_id)
    mastered = {
        node_id
        for node_id, state in loaded.states.items()
        if state.mastery >= app_settings.mastery_threshold
    }
    plan = await PlanService(session, fake_llm, app_settings).create(subject_id, PlanCreate())

    assert mastered
    assert plan.skipped_mastered == len(mastered)
    assert not {unit.node_id for unit in plan.units} & mastered


async def test_generating_a_plan_costs_no_model_calls(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """Sequencing is arithmetic over the graph; prose is written on first serve."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    before = len(fake_llm.calls)
    await PlanService(session, fake_llm, app_settings).create(subject_id, PlanCreate())
    assert len(fake_llm.calls) == before


async def test_a_limited_plan_reports_the_rest_rather_than_hiding_it(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """A prefix is labelled a prefix."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    plan = await PlanService(session, fake_llm, app_settings).create(
        subject_id, PlanCreate(limit=4)
    )
    assert len(plan.units) == 4
    assert plan.truncated > 0


async def test_regenerating_supersedes_the_old_plan_without_deleting_it(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """Completed units are history, and history is not discarded."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    service = PlanService(session, fake_llm, app_settings)
    first = await service.create(subject_id, PlanCreate())
    second = await service.create(subject_id, PlanCreate())

    repo = PlanRepository(session)
    original = await repo.get_plan(first.id)
    assert original is not None
    assert original.status == PlanStatus.SUPERSEDED
    active = await repo.active_plan(subject_id)
    assert active is not None
    assert active.id == second.id


async def test_a_re_taught_concept_is_not_a_first_acquisition(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """The second plan reads the first plan's history."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    service = PlanService(session, fake_llm, app_settings)
    plan = await service.create(subject_id, PlanCreate())
    first_node = plan.units[0].node_id

    served = await service.next_unit(plan.id)
    assert served.unit is not None
    await service.complete_unit(served.unit.id, UnitComplete(skipped=True))

    regenerated = await service.create(subject_id, PlanCreate())
    by_node = {unit.node_id: unit for unit in regenerated.units}
    if first_node in by_node:
        assert not by_node[first_node].first_acquisition


# --- running a unit ------------------------------------------------------------


async def test_serving_a_unit_writes_its_frame_and_exit_check(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """First serve is where the model call and the item generation happen."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    service = PlanService(session, fake_llm, app_settings)
    plan = await service.create(subject_id, PlanCreate())

    served = await service.next_unit(plan.id)
    assert served.unit is not None
    assert served.unit.status == UnitStatus.IN_PROGRESS
    assert served.unit.objective.startswith("Explain")
    assert len(served.exit_check) == app_settings.exit_check_items
    assert served.lesson_id is not None
    assert any(call.schema == "UnitBrief" for call in fake_llm.calls)


async def test_an_exit_check_asks_two_distinct_questions(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """Same concept, same difficulty: only naming the format keeps them different."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    service = PlanService(session, fake_llm, app_settings)
    plan = await service.create(subject_id, PlanCreate())
    served = await service.next_unit(plan.id)

    ids = {item.id for item in served.exit_check}
    formats = {item.item_format for item in served.exit_check}
    assert len(ids) == 2
    assert formats == {ItemFormat.SHORT_FREE_TEXT, ItemFormat.EXPLAIN_WHY_WRONG}


async def test_serving_the_same_unit_twice_does_not_regenerate_it(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """A reload is not a reason to pay for the unit again."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    service = PlanService(session, fake_llm, app_settings)
    plan = await service.create(subject_id, PlanCreate())

    first = await service.next_unit(plan.id)
    calls = len(fake_llm.calls)
    second = await service.next_unit(plan.id)

    assert len(fake_llm.calls) == calls
    assert first.unit is not None
    assert second.unit is not None
    assert first.unit.id == second.unit.id
    assert [i.id for i in first.exit_check] == [i.id for i in second.exit_check]


async def test_a_good_exit_check_raises_the_estimate(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """Exit-check evidence feeds the same model the diagnostic does."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    service = PlanService(session, fake_llm, app_settings)
    plan = await service.create(subject_id, PlanCreate())
    served = await service.next_unit(plan.id)
    assert served.unit is not None

    result = await service.complete_unit(
        served.unit.id,
        UnitComplete(
            answers=[
                ExitCheckAnswer(item_id=item.id, answer="correct") for item in served.exit_check
            ]
        ),
    )
    assert result.status == UnitStatus.COMPLETE
    assert result.exit_score == 1.0
    assert result.mastery_after > result.mastery_before
    assert result.next_unit_id is not None


async def test_a_failed_exit_check_lowers_the_estimate_and_still_closes(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """A bad unit is recorded as evidence, not as a trap the learner is stuck in."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    await run_diagnostic(session, fake_llm, app_settings, subject_id, well=True)
    service = PlanService(session, fake_llm, app_settings)
    plan = await service.create(subject_id, PlanCreate())
    served = await service.next_unit(plan.id)
    assert served.unit is not None

    result = await service.complete_unit(
        served.unit.id,
        UnitComplete(
            answers=[
                ExitCheckAnswer(item_id=item.id, answer="no idea") for item in served.exit_check
            ]
        ),
    )
    assert result.status == UnitStatus.COMPLETE
    assert result.mastery_after < result.mastery_before


async def test_exit_check_answers_are_logged_as_retrievals(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """The scheduler needs to see these later, so they are attributed to the queue."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    service = PlanService(session, fake_llm, app_settings)
    plan = await service.create(subject_id, PlanCreate())
    served = await service.next_unit(plan.id)
    assert served.unit is not None
    await service.complete_unit(
        served.unit.id,
        UnitComplete(
            answers=[
                ExitCheckAnswer(item_id=item.id, answer="correct") for item in served.exit_check
            ]
        ),
    )

    responses = await AssessmentRepository(session).responses_for_subject(subject_id)
    assert [r.source for r in responses] == [QueueKind.EXIT_CHECK] * len(served.exit_check)


async def test_a_skipped_exit_check_gathers_no_evidence(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """Closing a unit without answering must not move the estimate either way."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    service = PlanService(session, fake_llm, app_settings)
    plan = await service.create(subject_id, PlanCreate())
    served = await service.next_unit(plan.id)
    assert served.unit is not None

    result = await service.complete_unit(served.unit.id, UnitComplete(skipped=True))
    assert result.status == UnitStatus.SKIPPED
    assert result.exit_score is None
    assert result.mastery_after == result.mastery_before


async def test_a_closed_unit_cannot_be_closed_again(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """Double submission must not double-count the evidence."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    service = PlanService(session, fake_llm, app_settings)
    plan = await service.create(subject_id, PlanCreate())
    served = await service.next_unit(plan.id)
    assert served.unit is not None
    await service.complete_unit(served.unit.id, UnitComplete(skipped=True))

    with pytest.raises(UnitAlreadyClosed):
        await service.complete_unit(served.unit.id, UnitComplete(skipped=True))


async def test_an_answer_to_someone_elses_item_is_refused(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """An exit check grades its own questions and nothing else."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    service = PlanService(session, fake_llm, app_settings)
    plan = await service.create(subject_id, PlanCreate())
    served = await service.next_unit(plan.id)
    assert served.unit is not None

    with pytest.raises(UnitItemMismatch):
        await service.complete_unit(
            served.unit.id,
            UnitComplete(answers=[ExitCheckAnswer(item_id="not-an-item", answer="correct")]),
        )


async def test_the_plan_advances_through_its_units(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """Closing a unit hands back the next one, and the plan eventually ends."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    service = PlanService(session, fake_llm, app_settings)
    plan = await service.create(subject_id, PlanCreate(limit=3))

    seen: list[int] = []
    for _ in range(4):
        served = await service.next_unit(plan.id)
        if served.unit is None:
            assert served.finished
            break
        seen.append(served.unit.seq)
        await service.complete_unit(served.unit.id, UnitComplete(skipped=True))
    else:  # pragma: no cover - only reached if the plan never finishes
        pytest.fail("the plan did not finish")
    assert seen == [0, 1, 2]


# --- HTTP surface --------------------------------------------------------------


async def test_the_report_and_plan_endpoints_work_end_to_end(client: AsyncClient) -> None:
    """Subject to report to plan to first unit, over HTTP."""
    created = await client.post("/subjects", json={"name": "Thermodynamics"})
    subject_id = created.json()["id"]

    report = await client.get(f"/subjects/{subject_id}/report")
    assert report.status_code == 200
    assert report.json()["coverage"] >= 0.0
    assert report.json()["has_plan"] is False

    plan = await client.post(f"/subjects/{subject_id}/plan", json={})
    assert plan.status_code == 201
    plan_id = plan.json()["id"]
    assert plan.json()["units"]

    served = await client.get(f"/plan/{plan_id}/next")
    assert served.status_code == 200
    body = served.json()
    assert body["unit"]["seq"] == 0
    assert body["exit_check"]

    completed = await client.post(
        f"/plan/units/{body['unit']['id']}/complete",
        json={
            "answers": [{"item_id": item["id"], "answer": "correct"} for item in body["exit_check"]]
        },
    )
    assert completed.status_code == 200
    assert completed.json()["exit_score"] == 1.0


async def test_the_lesson_endpoint_returns_the_units_placeholder(client: AsyncClient) -> None:
    """The row exists before its prose does, which is what makes it addressable."""
    created = await client.post("/subjects", json={"name": "Optics"})
    subject_id = created.json()["id"]
    plan = await client.post(f"/subjects/{subject_id}/plan", json={})
    served = (await client.get(f"/plan/{plan.json()['id']}/next")).json()

    lesson = await client.get(f"/lessons/{served['lesson_id']}")
    assert lesson.status_code == 200
    assert lesson.json()["complete"] is False
    assert lesson.json()["markdown"] == ""


async def test_an_exit_check_never_leaks_its_answer_key(client: AsyncClient) -> None:
    """The client must not be able to grade itself."""
    created = await client.post("/subjects", json={"name": "Number Theory"})
    plan = await client.post(f"/subjects/{created.json()['id']}/plan", json={})
    served = (await client.get(f"/plan/{plan.json()['id']}/next")).json()
    for item in served["exit_check"]:
        assert "answer_key" not in item
        assert "rubric" not in item


async def test_the_calibration_endpoint_reports_insufficient_data_early(
    client: AsyncClient,
) -> None:
    """With no retrievals yet, the honest answer is that it cannot tell."""
    created = await client.post("/subjects", json={"name": "Topology"})
    response = await client.get(f"/subjects/{created.json()['id']}/calibration")
    assert response.status_code == 200
    assert response.json()["verdict"] == "insufficient_data"


async def test_planning_an_unknown_subject_is_a_404(client: AsyncClient) -> None:
    """A missing subject is not a server error."""
    assert (await client.post("/subjects/nope/plan", json={})).status_code == 404
    assert (await client.get("/subjects/nope/report")).status_code == 404
    assert (await client.get("/plan/nope/next")).status_code == 404
    assert (await client.get("/lessons/nope")).status_code == 404


async def test_a_subject_without_a_plan_says_so(client: AsyncClient) -> None:
    """Asking for a plan that was never generated is a 404, not an empty plan."""
    created = await client.post("/subjects", json={"name": "Cryptography"})
    response = await client.get(f"/subjects/{created.json()['id']}/plan")
    assert response.status_code == 404
