"""Tests for FSRS scheduling and the review queue.

The claims worth guarding are the ones a scheduler gets quietly wrong: that
forgetting something does not erase it, that a harder retrieval buys more than an
easy one, and that the queue never silently drops work it could not fit.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.llm.fake import FakeLLMAdapter
from app.mastery.state import MasteryParams
from app.models.enums import CardState, QueueKind
from app.repositories.assessment import AssessmentRepository
from app.repositories.scheduling import SchedulingRepository
from app.scheduling.fsrs import (
    MIN_STABILITY,
    Card,
    FsrsParams,
    initial_stability,
    interval_for,
    post_lapse_stability,
    retrievability,
    review,
)
from app.scheduling.grading import Grade
from app.schemas.plan import ExitCheckAnswer, PlanCreate, UnitComplete
from app.services.graph_loader import GraphLoader
from app.services.plan_service import PlanService
from app.services.review_service import NothingDue, ReviewService
from tests.test_subjects import build_subject

P = FsrsParams()
NOW = datetime(2026, 7, 30, 9, 0, tzinfo=UTC)


def taught(grade: Grade = Grade.GOOD, *, at: datetime = NOW, params: FsrsParams = P) -> Card:
    """A card that has been through one successful retrieval.

    :param grade: The grade that first retrieval earned.
    :param at: When it happened.
    :param params: Scheduler parameters.
    """
    return review(Card(), grade, now=at, params=params).card


# --- the forgetting curve ------------------------------------------------------


def test_recall_is_ninety_percent_at_one_stability() -> None:
    """The curve is defined so that stability *is* the ninety-percent interval."""
    assert retrievability(10.0, 10.0) == pytest.approx(0.9, abs=1e-3)


def test_recall_falls_monotonically_with_time() -> None:
    """More days without retrieval never means better odds."""
    values = [retrievability(days, 10.0) for days in (0, 1, 5, 20, 100)]
    assert values == sorted(values, reverse=True)
    assert values[0] == pytest.approx(1.0)


def test_a_lower_retention_target_buys_longer_intervals() -> None:
    """This is the difficulty knob: accept more forgetting, review less often."""
    lenient = interval_for(20.0, FsrsParams(request_retention=0.80))
    strict = interval_for(20.0, FsrsParams(request_retention=0.95))
    assert lenient > strict


def test_intervals_respect_their_bounds() -> None:
    """A barely-held concept still gets a day; a solid one is not scheduled forever."""
    assert interval_for(0.01, P) == P.minimum_interval_days
    assert interval_for(10.0**9, P) == P.maximum_interval_days


# --- grading effects -----------------------------------------------------------


@pytest.mark.parametrize(
    ("worse", "better"),
    [(Grade.AGAIN, Grade.HARD), (Grade.HARD, Grade.GOOD), (Grade.GOOD, Grade.EASY)],
)
def test_a_better_first_answer_implies_more_stability(worse: Grade, better: Grade) -> None:
    """The initial weights are ordered, and the code reads them in that order."""
    assert initial_stability(worse, P) < initial_stability(better, P)


def test_grade_moves_stability_even_while_the_ladder_fixes_the_interval() -> None:
    """The ladder pins *when*; the model still learns *how well* from every answer."""
    card = taught()
    later = NOW + timedelta(days=30)
    hard = review(card, Grade.HARD, now=later, params=P)
    easy = review(card, Grade.EASY, now=later, params=P)
    assert hard.interval_days == easy.interval_days
    assert easy.card.stability > hard.card.stability


def test_an_easy_answer_schedules_further_out_than_a_hard_one() -> None:
    """Once FSRS governs, grade has to move the interval in the obvious direction."""
    card = taught(params=FsrsParams(use_acquisition_ladder=False))
    later = NOW + timedelta(days=30)
    params = FsrsParams(use_acquisition_ladder=False)
    hard = review(card, Grade.HARD, now=later, params=params)
    easy = review(card, Grade.EASY, now=later, params=params)
    assert easy.interval_days > hard.interval_days


def test_a_late_successful_retrieval_is_worth_more_than_a_prompt_one() -> None:
    """Retrieving something you had nearly forgotten is what strengthens memory."""
    card = taught()
    prompt = review(card, Grade.GOOD, now=NOW + timedelta(days=2), params=P)
    late = review(card, Grade.GOOD, now=NOW + timedelta(days=40), params=P)
    assert late.card.stability > prompt.card.stability


def test_struggling_makes_a_concept_harder_and_succeeding_makes_it_easier() -> None:
    """Difficulty tracks how much trouble the concept actually causes."""
    card = taught()
    later = NOW + timedelta(days=10)
    assert review(card, Grade.HARD, now=later, params=P).card.difficulty > card.difficulty
    assert review(card, Grade.EASY, now=later, params=P).card.difficulty < card.difficulty


# --- lapses --------------------------------------------------------------------


def test_a_lapse_never_resets_memory_to_zero() -> None:
    """Forgetting something once is not the same as never having learned it."""
    card = taught(Grade.EASY)
    lapsed = review(card, Grade.AGAIN, now=NOW + timedelta(days=30), params=P)
    assert lapsed.card.stability > 0
    assert lapsed.card.stability >= MIN_STABILITY
    assert lapsed.card.stability < card.stability
    assert lapsed.card.lapses == 1
    assert lapsed.card.state == CardState.RELEARNING


def test_post_lapse_stability_is_bounded_by_what_came_before() -> None:
    """A lapse is evidence the interval was too long, never evidence of progress."""
    for stability in (0.5, 5.0, 50.0, 500.0):
        lapsed = post_lapse_stability(stability, 5.0, 0.3, P)
        assert 0 < lapsed <= stability


def test_a_relapsed_concept_still_outranks_a_brand_new_one() -> None:
    """This is what "never reset" buys: relearning is faster than learning."""
    strong = taught(Grade.EASY)
    lapsed = review(strong, Grade.AGAIN, now=NOW + timedelta(days=60), params=P).card
    relearned = review(lapsed, Grade.GOOD, now=NOW + timedelta(days=60, minutes=20), params=P)
    fresh = review(Card(), Grade.GOOD, now=NOW, params=P)
    assert relearned.interval_days > fresh.interval_days


def test_relearning_steps_climb_and_then_hold() -> None:
    """Repeated failure does not run off the end of the ladder."""
    params = FsrsParams(relearning_steps_minutes=(10.0, 60.0))
    card = review(taught(), Grade.AGAIN, now=NOW + timedelta(days=10), params=params).card
    assert card.step_index == 0

    second = review(card, Grade.AGAIN, now=NOW + timedelta(days=10, minutes=10), params=params).card
    assert second.step_index == 1
    assert second.scheduled_days == pytest.approx(60.0 / 1440.0)

    third = review(
        second, Grade.AGAIN, now=NOW + timedelta(days=10, minutes=70), params=params
    ).card
    assert third.step_index == 1


def test_a_lapse_abandons_the_acquisition_ladder() -> None:
    """A forgotten concept is no longer being acquired, so FSRS takes over."""
    card = taught()
    assert card.acquisition_step == 1
    lapsed = review(card, Grade.AGAIN, now=NOW + timedelta(days=2), params=P).card
    assert lapsed.acquisition_step == len(P.acquisition_ladder_days)


def test_a_failed_first_retrieval_goes_straight_to_relearning() -> None:
    """Being taught something and failing the exit check is a lapse, not a pass."""
    result = review(Card(), Grade.AGAIN, now=NOW, params=P)
    assert result.card.state == CardState.RELEARNING
    assert result.card.lapses == 1
    assert result.interval_days > 0


# --- the acquisition ladder ----------------------------------------------------


def test_a_freshly_taught_concept_follows_the_expanding_ladder() -> None:
    """1, 3, 7, 21 days, then FSRS."""
    params = FsrsParams(use_acquisition_ladder=True)
    card = Card()
    at = NOW
    intervals: list[float] = []
    for _ in range(4):
        result = review(card, Grade.GOOD, now=at, params=params)
        intervals.append(result.interval_days)
        card = result.card
        at += timedelta(days=result.interval_days)
    assert intervals == list(params.acquisition_ladder_days)
    assert card.acquisition_step == len(params.acquisition_ladder_days)

    # Past the ladder, FSRS governs, and by then it has four observations to work with.
    after = review(card, Grade.GOOD, now=at, params=params)
    assert after.reason == "fsrs interval"
    assert after.interval_days > intervals[-1]


def test_the_ladder_overrides_a_longer_fsrs_interval_on_purpose() -> None:
    """FSRS's first interval is fitted on much stronger evidence than one exit check.

    At the default retention target FSRS asks for roughly six days after a single
    "good", because its initial weights come from Anki cards that graduated through
    same-session learning steps. One post-instruction retrieval is not that, so the
    ladder deliberately pulls the first review back to a day.
    """
    params = FsrsParams(use_acquisition_ladder=True)
    result = review(Card(), Grade.GOOD, now=NOW, params=params)
    assert interval_for(result.card.stability, params) > 5.0
    assert result.interval_days == params.acquisition_ladder_days[0]


def test_the_ladder_can_be_switched_off() -> None:
    """Configuration, not doctrine."""
    off = review(Card(), Grade.GOOD, now=NOW, params=FsrsParams(use_acquisition_ladder=False))
    assert off.reason == "fsrs interval"


def test_scheduler_parameters_come_from_settings(app_settings: Settings) -> None:
    """The retention target the report calibrates against is the one FSRS uses."""
    params = FsrsParams.from_settings(app_settings)
    assert params.request_retention == app_settings.target_retention
    assert params.use_acquisition_ladder == app_settings.use_acquisition_ladder


# --- the review queue ----------------------------------------------------------


async def complete_first_unit(
    session: AsyncSession, fake_llm: FakeLLMAdapter, settings: Settings, subject_id: str
) -> str:
    """Teach one concept and pass its exit check, returning the concept id.

    :param session: The test session.
    :param fake_llm: The offline adapter.
    :param settings: Test settings.
    :param subject_id: The subject to study.
    """
    service = PlanService(session, fake_llm, settings)
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
    return served.unit.node_id


async def test_passing_an_exit_check_schedules_the_concept(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """Without this a concept would be taught and then never come back around."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    node_id = await complete_first_unit(session, fake_llm, app_settings, subject_id)

    card = await SchedulingRepository(session).card_for(node_id)
    assert card is not None
    assert card.state == CardState.REVIEW
    assert card.due_at is not None
    assert card.reps == 1
    assert card.stability > 0


async def test_a_skipped_exit_check_schedules_nothing(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """No retrieval happened, so there is no observation to schedule from."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    service = PlanService(session, fake_llm, app_settings)
    plan = await service.create(subject_id, PlanCreate())
    served = await service.next_unit(plan.id)
    assert served.unit is not None
    await service.complete_unit(served.unit.id, UnitComplete(skipped=True))

    card = await SchedulingRepository(session).card_for(served.unit.node_id)
    assert card is None


async def test_new_material_never_appears_in_the_review_queue(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """The queue keeps what was taught; teaching is the plan's job."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    queue = await ReviewService(session, fake_llm, app_settings).due_queue(subject_id)
    assert queue.due == []
    assert queue.total_cards == 0


async def test_a_concept_becomes_due_once_its_interval_elapses(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """Nothing is due the moment it is taught, and it is due a few days later."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    node_id = await complete_first_unit(session, fake_llm, app_settings, subject_id)
    service = ReviewService(session, fake_llm, app_settings)

    today = await service.due_queue(subject_id)
    assert today.due == []
    assert [card.node_id for card in today.upcoming] == [node_id]

    later = await service.due_queue(subject_id, now=datetime.now(UTC) + timedelta(days=400))
    assert [card.node_id for card in later.due] == [node_id]


async def test_the_daily_cap_defers_rather_than_drops(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """Work past the cap stays due; it is not silently discarded."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    loader = GraphLoader(session, MasteryParams.from_settings(app_settings))
    loaded = await loader.load(subject_id)
    service = ReviewService(session, fake_llm, app_settings)

    long_ago = datetime.now(UTC) - timedelta(days=30)
    for node_id in loaded.graph.node_ids[:8]:
        await service.record_retrieval(loaded, node_id, Grade.GOOD, now=long_ago)
    await session.commit()

    subject = loaded.subject
    subject.daily_review_cap = 3
    await session.commit()

    queue = await service.due_queue(subject_id)
    assert len(queue.due) == 3
    assert queue.deferred == 5
    assert queue.daily_cap == 3


async def test_the_queue_leads_with_the_most_load_bearing_backlog(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """Two cards equally overdue: the one more of the graph depends on comes first."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    loader = GraphLoader(session, MasteryParams.from_settings(app_settings))
    loaded = await loader.load(subject_id)
    service = ReviewService(session, fake_llm, app_settings)

    ranked_by_reach = sorted(
        loaded.graph.node_ids,
        key=lambda node_id: loaded.graph.unblocking_power(node_id),
    )
    dead_end, hub = ranked_by_reach[0], ranked_by_reach[-1]
    assert loaded.graph.unblocking_power(hub) > loaded.graph.unblocking_power(dead_end)

    long_ago = datetime.now(UTC) - timedelta(days=30)
    for node_id in (dead_end, hub):
        await service.record_retrieval(loaded, node_id, Grade.GOOD, now=long_ago)
    await session.commit()

    queue = await service.due_queue(subject_id)
    assert next(card.node_id for card in queue.due) == hub


async def test_answering_a_review_moves_mastery_and_reschedules(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """One observation, two models: what is known, and when to ask again."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    loader = GraphLoader(session, MasteryParams.from_settings(app_settings))
    loaded = await loader.load(subject_id)
    service = ReviewService(session, fake_llm, app_settings)

    node_id = loaded.graph.node_ids[0]
    await service.record_retrieval(
        loaded, node_id, Grade.GOOD, now=datetime.now(UTC) - timedelta(days=30)
    )
    await session.commit()

    item = await service.next_item(subject_id)
    assert item.node_id == node_id
    result = await service.answer(subject_id, item.id, "0")

    assert result.card.due_at is not None
    assert result.interval_days > 0
    assert result.schedule_reason
    assert any(change.node_id == node_id and not change.propagated for change in result.changes)

    responses = await AssessmentRepository(session).responses_for_subject(subject_id)
    assert responses[-1].source == QueueKind.REVIEW
    assert responses[-1].grade == result.grade


async def test_a_failed_review_brings_the_concept_back_sooner(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """Forgetting is exactly the signal that the interval was too long."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    loader = GraphLoader(session, MasteryParams.from_settings(app_settings))
    loaded = await loader.load(subject_id)
    service = ReviewService(session, fake_llm, app_settings)

    node_id = loaded.graph.node_ids[0]
    card = await service.record_retrieval(
        loaded, node_id, Grade.GOOD, now=datetime.now(UTC) - timedelta(days=30)
    )
    before = card.scheduled_days
    await session.commit()

    item = await service.next_item(subject_id)
    result = await service.answer(subject_id, item.id, "3")

    assert result.grade == int(Grade.AGAIN)
    assert result.card.state == CardState.RELEARNING
    assert result.card.lapses == 1
    assert result.interval_days < before


async def test_asking_for_a_review_when_nothing_is_due_is_refused(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """An empty queue is a state, not an error to paper over with a random item."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    with pytest.raises(NothingDue):
        await ReviewService(session, fake_llm, app_settings).next_item(subject_id)


# --- HTTP surface --------------------------------------------------------------


async def test_the_review_endpoints_work_end_to_end(client: AsyncClient) -> None:
    """Teach a unit, jump forward, and clear the review it produced."""
    created = await client.post("/subjects", json={"name": "Signal Processing"})
    subject_id = created.json()["id"]
    plan = await client.post(f"/subjects/{subject_id}/plan", json={})
    served = (await client.get(f"/plan/{plan.json()['id']}/next")).json()
    await client.post(
        f"/plan/units/{served['unit']['id']}/complete",
        json={"answers": [{"item_id": i["id"], "answer": "correct"} for i in served["exit_check"]]},
    )

    queue = await client.get(f"/subjects/{subject_id}/reviews")
    assert queue.status_code == 200
    assert queue.json()["total_cards"] == 1
    assert queue.json()["upcoming"]

    # Nothing is due yet, which the API says plainly rather than inventing work.
    assert (await client.get(f"/subjects/{subject_id}/reviews/next")).status_code == 409


async def test_review_endpoints_404_on_an_unknown_subject(client: AsyncClient) -> None:
    """A missing subject is not a server error."""
    assert (await client.get("/subjects/nope/reviews")).status_code == 404
    assert (await client.get("/subjects/nope/reviews/next")).status_code == 404


async def test_a_review_answer_for_another_subject_is_refused(client: AsyncClient) -> None:
    """Items are scoped to their subject, and the queue enforces it."""
    first = (await client.post("/subjects", json={"name": "Acoustics"})).json()["id"]
    second = (await client.post("/subjects", json={"name": "Optics II"})).json()["id"]
    diagnostic = (await client.post(f"/subjects/{first}/diagnostic", json={})).json()
    item = (await client.get(f"/diagnostic/{diagnostic['id']}/next")).json()["item"]

    response = await client.post(
        f"/subjects/{second}/reviews/answer", json={"item_id": item["id"], "answer": "0"}
    )
    assert response.status_code == 400
