"""Tests for the session planner and the rolling schedule.

The acceptance criterion this file exists for is the last clause of the spec's
scheduling requirement: the schedule respects the cadence and the daily cap, *and
says so if it cannot hit a deadline*. All three are asserted directly.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from itertools import pairwise

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.integrations import (
    NullCalendarSink,
    NullRecoverySignal,
    ScheduledEvent,
    get_calendar_sink,
    get_recovery_signal,
)
from app.llm.fake import FakeLLMAdapter
from app.mastery.state import MasteryParams
from app.models.enums import StudySessionStatus
from app.models.scheduling import StudySession
from app.scheduling.grading import Grade
from app.scheduling.planner import (
    Cadence,
    DueItem,
    assess_deadline,
    interleave,
    plan_schedule,
    session_capacity,
    session_days,
    session_days_until,
)
from app.schemas.plan import PlanCreate
from app.schemas.schedule import ScheduleRequest
from app.services.graph_loader import GraphLoader
from app.services.plan_service import PlanService
from app.services.review_service import ReviewService
from app.services.schedule_service import ScheduleService, SessionAlreadyClosed, branch_of
from tests.test_subjects import build_subject

#: A Monday, so weekday arithmetic in the assertions is readable.
MONDAY = date(2026, 8, 3)


def units(count: int) -> tuple[list[str], list[str]]:
    """Build parallel unit-id and node-id lists.

    :param count: How many units to build.
    """
    return ([f"u{i}" for i in range(count)], [f"n{i}" for i in range(count)])


# --- cadence -------------------------------------------------------------------


@pytest.mark.parametrize("days_per_week", [1, 2, 3, 4, 5, 6, 7])
def test_a_cadence_produces_that_many_sessions_a_week(days_per_week: int) -> None:
    """The headline promise of the cadence setting."""
    cadence = Cadence(days_per_week=days_per_week)
    week = session_days_until(MONDAY, MONDAY + timedelta(days=6), cadence)
    assert len(week) == days_per_week


def test_sessions_are_spread_rather_than_clumped() -> None:
    """Four days a week is Mon/Tue/Thu/Sat, not four days running."""
    days = session_days_until(MONDAY, MONDAY + timedelta(days=6), Cadence(days_per_week=4))
    gaps = [(later - earlier).days for earlier, later in pairwise(days)]
    assert max(gaps) > 1


def test_asking_for_no_session_days_returns_none() -> None:
    """A degenerate request is answered, not crashed on."""
    assert session_days(MONDAY, 0, Cadence()) == ()


def test_a_longer_sitting_holds_more_new_material() -> None:
    """Capacity follows the minutes, not a fixed guess."""
    _, short = session_capacity(Cadence(minutes_per_session=20))
    _, long = session_capacity(Cadence(minutes_per_session=60))
    assert long > short


def test_even_a_tiny_sitting_teaches_something() -> None:
    """Otherwise a tight cadence yields pure review and the plan never advances."""
    reviews, new_nodes = session_capacity(Cadence(minutes_per_session=5, retrieval_minutes=5))
    assert reviews >= 1
    assert new_nodes >= 1


# --- session shape -------------------------------------------------------------


def test_a_session_opens_with_retrieval_and_then_teaches() -> None:
    """Retrieval before instruction, always."""
    unit_ids, node_ids = units(10)
    due = [DueItem(node_id="old", due_on=MONDAY, priority=1.0)]
    schedule = plan_schedule(
        start=MONDAY, due=due, unit_ids=unit_ids, unit_node_ids=node_ids, cadence=Cadence()
    )
    first = schedule.sessions[0]
    assert first.retrieval_minutes > 0
    assert first.review_node_ids == ("old",)
    assert first.new_node_ids


def test_the_schedule_respects_the_cadence() -> None:
    """Two weeks at four days a week is eight sittings, on the cadence's days."""
    unit_ids, node_ids = units(40)
    schedule = plan_schedule(
        start=MONDAY,
        due=[],
        unit_ids=unit_ids,
        unit_node_ids=node_ids,
        cadence=Cadence(days_per_week=4),
        horizon_days=14,
    )
    assert len(schedule.sessions) == 8
    assert all(session.on.weekday() in {0, 1, 3, 5} for session in schedule.sessions)


def test_the_schedule_respects_the_daily_cap() -> None:
    """The cap binds even when the sitting has minutes to spare."""
    due = [DueItem(node_id=f"d{i}", due_on=MONDAY, priority=1.0) for i in range(30)]
    schedule = plan_schedule(
        start=MONDAY,
        due=due,
        unit_ids=[],
        unit_node_ids=[],
        cadence=Cadence(daily_review_cap=3),
    )
    assert len(schedule.sessions[0].review_node_ids) == 3


def test_reviews_past_the_cap_are_deferred_and_reported() -> None:
    """A planner that silently drops work is worse than one that admits it is behind."""
    due = [DueItem(node_id=f"d{i}", due_on=MONDAY, priority=1.0) for i in range(30)]
    schedule = plan_schedule(
        start=MONDAY,
        due=due,
        unit_ids=[],
        unit_node_ids=[],
        cadence=Cadence(daily_review_cap=3),
    )
    first = schedule.sessions[0]
    assert len(first.deferred_node_ids) == 27
    assert any("did not fit" in note for note in first.notes)


def test_deferred_reviews_lead_the_next_session() -> None:
    """Deferring is a delay, not a deletion."""
    due = [DueItem(node_id=f"d{i}", due_on=MONDAY, priority=1.0) for i in range(6)]
    schedule = plan_schedule(
        start=MONDAY,
        due=due,
        unit_ids=[],
        unit_node_ids=[],
        cadence=Cadence(daily_review_cap=2),
    )
    scheduled = [node_id for session in schedule.sessions for node_id in session.review_node_ids]
    assert sorted(scheduled) == sorted(item.node_id for item in due)


def test_a_review_is_not_scheduled_before_it_comes_due() -> None:
    """The planner spreads work out; it does not pull it forward."""
    later = MONDAY + timedelta(days=9)
    schedule = plan_schedule(
        start=MONDAY,
        due=[DueItem(node_id="future", due_on=later, priority=1.0)],
        unit_ids=[],
        unit_node_ids=[],
        cadence=Cadence(),
    )
    for session in schedule.sessions:
        if "future" in session.review_node_ids:
            assert session.on >= later


def test_plan_units_are_scheduled_in_plan_order() -> None:
    """The sequencer's ordering is the whole point; the planner must not shuffle it."""
    unit_ids, node_ids = units(12)
    schedule = plan_schedule(
        start=MONDAY, due=[], unit_ids=unit_ids, unit_node_ids=node_ids, cadence=Cadence()
    )
    placed = [unit_id for session in schedule.sessions for unit_id in session.unit_ids]
    assert placed == unit_ids[: len(placed)]


def test_an_idle_session_says_so_rather_than_inventing_work() -> None:
    """Nothing due and nothing left to teach is a fact worth stating."""
    schedule = plan_schedule(start=MONDAY, due=[], unit_ids=[], unit_node_ids=[], cadence=Cadence())
    assert all(any("free" in note for note in s.notes) for s in schedule.sessions)


# --- deadline mode -------------------------------------------------------------


def test_a_reachable_deadline_is_reported_as_on_track() -> None:
    """Six units at four sessions a week over a month fits comfortably."""
    verdict = assess_deadline(
        start=MONDAY,
        remaining_units=6,
        cadence=Cadence(days_per_week=4, deadline=MONDAY + timedelta(days=28)),
        per_new=2,
    )
    assert verdict.achievable
    assert verdict.shortfall_sessions == 0
    assert "On track" in verdict.message


def test_an_unreachable_deadline_is_named_with_its_shortfall() -> None:
    """The acceptance criterion: it says so, and by how much."""
    verdict = assess_deadline(
        start=MONDAY,
        remaining_units=80,
        cadence=Cadence(days_per_week=2, deadline=MONDAY + timedelta(days=14)),
        per_new=2,
    )
    assert not verdict.achievable
    assert verdict.sessions_needed == 40
    assert verdict.shortfall_sessions == verdict.sessions_needed - verdict.sessions_available
    assert "will not fit" in verdict.message
    assert str(verdict.shortfall_sessions) in verdict.message


def test_an_unreachable_deadline_suggests_what_would_fix_it() -> None:
    """A shortfall that a heavier cadence closes should say which cadence."""
    verdict = assess_deadline(
        start=MONDAY,
        remaining_units=10,
        cadence=Cadence(days_per_week=1, deadline=MONDAY + timedelta(days=28)),
        per_new=2,
    )
    assert not verdict.achievable
    assert "days a week" in verdict.message


def test_a_hopeless_deadline_says_so_instead_of_promising_a_cadence() -> None:
    """Seven days a week still does not fit, so proposing a cadence would be a lie."""
    verdict = assess_deadline(
        start=MONDAY,
        remaining_units=400,
        cadence=Cadence(days_per_week=4, deadline=MONDAY + timedelta(days=7)),
        per_new=2,
    )
    assert not verdict.achievable
    assert "extending the deadline" in verdict.message


def test_a_passed_deadline_is_reported_honestly() -> None:
    """Not an error, and not silently ignored."""
    verdict = assess_deadline(
        start=MONDAY,
        remaining_units=5,
        cadence=Cadence(deadline=MONDAY - timedelta(days=3)),
        per_new=2,
    )
    assert not verdict.achievable
    assert "has passed" in verdict.message


def test_without_a_deadline_the_verdict_is_an_estimate_not_a_failure() -> None:
    """No deadline set is a normal state, not a shortfall."""
    verdict = assess_deadline(start=MONDAY, remaining_units=9, cadence=Cadence(), per_new=2)
    assert verdict.achievable
    assert verdict.sessions_needed == 5
    assert "No deadline set" in verdict.message


# --- the service ---------------------------------------------------------------


async def test_a_schedule_covers_the_plan_and_persists(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """The generated schedule is stored so it can be reopened and completed."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    await PlanService(session, fake_llm, app_settings).create(subject_id, PlanCreate())

    service = ScheduleService(session, fake_llm, app_settings)
    schedule = await service.build(subject_id, ScheduleRequest(), today=MONDAY)

    assert schedule.sessions
    assert schedule.units_scheduled > 0
    assert all(s.id is not None for s in schedule.sessions)
    assert all(s.new_names for s in schedule.sessions if s.new_node_ids)

    stored = list(
        (
            await session.execute(select(StudySession).where(StudySession.subject_id == subject_id))
        ).scalars()
    )
    assert len(stored) == len(schedule.sessions)


async def test_reading_a_schedule_does_not_rewrite_it(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """A GET is a read; only an explicit build replaces stored sittings."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    await PlanService(session, fake_llm, app_settings).create(subject_id, PlanCreate())
    service = ScheduleService(session, fake_llm, app_settings)

    built = await service.build(subject_id, ScheduleRequest(), today=MONDAY)
    ids = {s.id for s in built.sessions}
    peeked = await service.build(subject_id, ScheduleRequest(persist=False), today=MONDAY)

    assert all(s.id is None for s in peeked.sessions)
    stored = list(
        (
            await session.execute(select(StudySession).where(StudySession.subject_id == subject_id))
        ).scalars()
    )
    assert {row.id for row in stored} == ids


async def test_the_service_honours_a_patched_cadence(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """Cadence is configuration the learner sets, and the planner reads it."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    await PlanService(session, fake_llm, app_settings).create(subject_id, PlanCreate())
    service = ScheduleService(session, fake_llm, app_settings)

    loaded = await service._loader.load(subject_id)
    loaded.subject.days_per_week = 2
    loaded.subject.minutes_per_session = 60
    await session.commit()

    schedule = await service.build(subject_id, ScheduleRequest(), today=MONDAY)
    assert schedule.days_per_week == 2
    assert len(schedule.sessions) == 4
    assert schedule.minutes_per_session == 60


async def test_an_unreachable_deadline_reaches_the_api(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """The verdict is not buried in a log; it is part of the schedule response."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    await PlanService(session, fake_llm, app_settings).create(subject_id, PlanCreate())
    service = ScheduleService(session, fake_llm, app_settings)

    loaded = await service._loader.load(subject_id)
    loaded.subject.deadline = MONDAY + timedelta(days=3)
    loaded.subject.days_per_week = 1
    await session.commit()

    schedule = await service.build(subject_id, ScheduleRequest(), today=MONDAY)
    assert not schedule.deadline.achievable
    assert schedule.deadline.shortfall_sessions > 0
    assert schedule.deadline.message


async def test_completing_a_session_counts_toward_adherence(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """Counts, not points: the numbers are there to judge the cadence by."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    await PlanService(session, fake_llm, app_settings).create(subject_id, PlanCreate())
    service = ScheduleService(session, fake_llm, app_settings)

    schedule = await service.build(subject_id, ScheduleRequest(), today=MONDAY)
    first = schedule.sessions[0]
    assert first.id is not None
    done = await service.complete_session(first.id, "went fine")
    assert done.status == StudySessionStatus.COMPLETE
    assert done.completed_at is not None

    # The next day that sitting is in the past, and it is the only past one.
    later = await service.build(subject_id, ScheduleRequest(), today=MONDAY + timedelta(days=1))
    assert later.adherence.sessions_completed == 1
    assert later.adherence.sessions_missed == 0
    assert later.adherence.current_streak == 1
    assert later.adherence.completion_rate == 1.0


async def test_the_streak_reflects_the_most_recent_sittings_not_the_best_run(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """A completed sitting followed by missed ones is a history, not a live streak."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    await PlanService(session, fake_llm, app_settings).create(subject_id, PlanCreate())
    service = ScheduleService(session, fake_llm, app_settings)

    schedule = await service.build(subject_id, ScheduleRequest(), today=MONDAY)
    first = schedule.sessions[0]
    assert first.id is not None
    await service.complete_session(first.id, "")

    later = await service.build(subject_id, ScheduleRequest(), today=MONDAY + timedelta(days=7))
    assert later.adherence.sessions_completed == 1
    assert later.adherence.sessions_missed > 0
    assert later.adherence.longest_streak == 1
    assert later.adherence.current_streak == 0


async def test_a_skipped_sitting_becomes_missed_rather_than_vanishing(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """Otherwise adherence would improve every time the schedule was regenerated."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    await PlanService(session, fake_llm, app_settings).create(subject_id, PlanCreate())
    service = ScheduleService(session, fake_llm, app_settings)

    await service.build(subject_id, ScheduleRequest(), today=MONDAY)
    later = await service.build(subject_id, ScheduleRequest(), today=MONDAY + timedelta(days=7))

    assert later.adherence.sessions_missed > 0
    assert later.adherence.completion_rate == 0.0
    assert later.adherence.current_streak == 0


async def test_a_closed_session_cannot_be_closed_again(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """Double submission must not double-count adherence."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    await PlanService(session, fake_llm, app_settings).create(subject_id, PlanCreate())
    service = ScheduleService(session, fake_llm, app_settings)

    schedule = await service.build(subject_id, ScheduleRequest(), today=MONDAY)
    first = schedule.sessions[0]
    assert first.id is not None
    await service.complete_session(first.id, "")
    with pytest.raises(SessionAlreadyClosed):
        await service.complete_session(first.id, "")


# --- HTTP surface --------------------------------------------------------------


async def test_the_schedule_endpoints_work_end_to_end(client: AsyncClient) -> None:
    """Cadence, plan, schedule, complete a sitting."""
    created = await client.post("/subjects", json={"name": "Control Theory"})
    subject_id = created.json()["id"]
    await client.patch(
        f"/subjects/{subject_id}/cadence", json={"days_per_week": 3, "minutes_per_session": 30}
    )
    await client.post(f"/subjects/{subject_id}/plan", json={})

    built = await client.post(f"/subjects/{subject_id}/schedule", json={"horizon_days": 14})
    assert built.status_code == 200
    body = built.json()
    assert body["days_per_week"] == 3
    assert len(body["sessions"]) == 6
    assert body["deadline"]["message"]

    completed = await client.post(
        f"/sessions/{body['sessions'][0]['id']}/complete", json={"notes": "done"}
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "complete"
    assert (
        await client.post(f"/sessions/{body['sessions'][0]['id']}/complete", json={})
    ).status_code == 409


async def test_a_deadline_that_cannot_be_met_is_visible_over_http(client: AsyncClient) -> None:
    """The acceptance criterion, through the API the UI actually calls."""
    created = await client.post("/subjects", json={"name": "Real Analysis"})
    subject_id = created.json()["id"]
    await client.post(f"/subjects/{subject_id}/plan", json={})
    await client.patch(
        f"/subjects/{subject_id}/cadence",
        json={"days_per_week": 1, "deadline": (date.today() + timedelta(days=2)).isoformat()},
    )

    schedule = await client.get(f"/subjects/{subject_id}/schedule")
    assert schedule.status_code == 200
    verdict = schedule.json()["deadline"]
    assert verdict["achievable"] is False
    assert verdict["shortfall_sessions"] > 0
    assert "will not fit" in verdict["message"]


async def test_schedule_endpoints_404_on_an_unknown_subject(client: AsyncClient) -> None:
    """A missing subject is not a server error."""
    assert (await client.get("/subjects/nope/schedule")).status_code == 404
    assert (await client.post("/subjects/nope/schedule", json={})).status_code == 404
    assert (await client.post("/sessions/nope/complete", json={})).status_code == 404


# --- interleaving ---------------------------------------------------------------


def test_interleaving_alternates_between_parts_of_the_subject() -> None:
    """Blocked retrieval is easy for the wrong reason: the pile gives the answer away."""
    items = [
        DueItem(node_id="a1", due_on=MONDAY, priority=9.0, group="a"),
        DueItem(node_id="a2", due_on=MONDAY, priority=8.0, group="a"),
        DueItem(node_id="a3", due_on=MONDAY, priority=7.0, group="a"),
        DueItem(node_id="b1", due_on=MONDAY, priority=6.0, group="b"),
        DueItem(node_id="b2", due_on=MONDAY, priority=5.0, group="b"),
    ]
    assert interleave(items) == ("a1", "b1", "a2", "b2", "a3")


def test_interleaving_keeps_every_item() -> None:
    """Reordering is not filtering."""
    items = [
        DueItem(node_id=f"n{i}", due_on=MONDAY, priority=float(20 - i), group=f"g{i % 4}")
        for i in range(20)
    ]
    woven = interleave(items)
    assert sorted(woven) == sorted(item.node_id for item in items)


def test_interleaving_leads_with_the_highest_priority_item() -> None:
    """Weaving must not demote the thing most worth doing."""
    items = [
        DueItem(node_id="low", due_on=MONDAY, priority=1.0, group="a"),
        DueItem(node_id="high", due_on=MONDAY, priority=99.0, group="b"),
    ]
    assert interleave(items)[0] == "high"


def test_a_single_group_degenerates_to_priority_order() -> None:
    """There is nothing to interleave against, so the weave is a no-op."""
    items = [
        DueItem(node_id="c", due_on=MONDAY, priority=1.0, group="a"),
        DueItem(node_id="a", due_on=MONDAY, priority=3.0, group="a"),
        DueItem(node_id="b", due_on=MONDAY, priority=2.0, group="a"),
    ]
    assert interleave(items) == ("a", "b", "c")


def test_interleaving_an_empty_queue_is_empty() -> None:
    """A degenerate input is answered, not crashed on."""
    assert interleave([]) == ()


def test_the_cap_is_applied_before_the_weave() -> None:
    """What gets dropped is decided by value; the weave only reorders survivors."""
    due = [
        DueItem(node_id="keep", due_on=MONDAY, priority=99.0, group="a"),
        *[DueItem(node_id=f"drop{i}", due_on=MONDAY, priority=1.0, group="b") for i in range(5)],
    ]
    schedule = plan_schedule(
        start=MONDAY,
        due=due,
        unit_ids=[],
        unit_node_ids=[],
        cadence=Cadence(daily_review_cap=1),
    )
    assert schedule.sessions[0].review_node_ids == ("keep",)
    assert len(schedule.sessions[0].deferred_node_ids) == 5


def test_new_material_is_never_interleaved() -> None:
    """Plan order is a correctness property; shuffling it for study technique is a trade
    the planner is not allowed to make."""
    unit_ids, node_ids = units(12)
    schedule = plan_schedule(
        start=MONDAY, due=[], unit_ids=unit_ids, unit_node_ids=node_ids, cadence=Cadence()
    )
    taught = [node_id for session in schedule.sessions for node_id in session.new_node_ids]
    assert taught == node_ids[: len(taught)]


async def test_the_service_groups_by_branch_of_the_subject(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """Two concepts sharing a root are one pile; different roots are different piles."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    loaded = await GraphLoader(session, MasteryParams.from_settings(app_settings)).load(subject_id)

    roots = loaded.graph.roots()
    assert len(roots) > 1
    for root in roots:
        assert branch_of(loaded, root) == root

    deep = max(loaded.graph.node_ids, key=lambda n: loaded.graph.tier(n))
    assert branch_of(loaded, deep) in roots


async def test_a_scheduled_session_interleaves_its_retrieval(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """End to end: the order that reaches the database is the woven one."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    loaded = await GraphLoader(session, MasteryParams.from_settings(app_settings)).load(subject_id)
    reviews = ReviewService(session, fake_llm, app_settings)

    long_ago = datetime.now(UTC) - timedelta(days=30)
    for node_id in loaded.graph.node_ids[:10]:
        await reviews.record_retrieval(loaded, node_id, Grade.GOOD, now=long_ago)
    await session.commit()

    schedule = await ScheduleService(session, fake_llm, app_settings).build(
        subject_id, ScheduleRequest(), today=MONDAY
    )
    first = schedule.sessions[0]
    assert first.review_node_ids
    groups = [branch_of(loaded, node_id) for node_id in first.review_node_ids]
    if len(set(groups)) > 1:
        # With more than one branch present, no two neighbours should share one
        # until the shorter piles run out.
        assert groups[0] != groups[1]


# --- projected coverage ---------------------------------------------------------


async def test_projected_coverage_rises_across_the_horizon(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """Each session teaches more, so the projection cannot go backwards."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    await PlanService(session, fake_llm, app_settings).create(subject_id, PlanCreate())
    schedule = await ScheduleService(session, fake_llm, app_settings).build(
        subject_id, ScheduleRequest(), today=MONDAY
    )

    projections = [s.projected_coverage for s in schedule.sessions]
    assert projections == sorted(projections)
    assert projections[-1] > 0.0


async def test_projected_coverage_never_exceeds_one(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """It is a coverage figure, so the same bound applies as anywhere else."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    await PlanService(session, fake_llm, app_settings).create(subject_id, PlanCreate())
    schedule = await ScheduleService(session, fake_llm, app_settings).build(
        subject_id, ScheduleRequest(), today=MONDAY
    )
    assert all(0.0 <= s.projected_coverage <= 1.0 for s in schedule.sessions)


# --- optional integrations ------------------------------------------------------


async def test_the_null_integrations_leave_their_columns_empty(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """Off means off: no fabricated calendar id, no invented recovery score."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    await PlanService(session, fake_llm, app_settings).create(subject_id, PlanCreate())
    await ScheduleService(session, fake_llm, app_settings).build(
        subject_id, ScheduleRequest(), today=MONDAY
    )

    rows = list(
        (
            await session.execute(select(StudySession).where(StudySession.subject_id == subject_id))
        ).scalars()
    )
    assert rows
    assert all(row.calendar_event_id is None for row in rows)
    assert all(row.recovery_score is None for row in rows)


async def test_a_null_recovery_signal_says_unknown_not_average() -> None:
    """0.5 means "an average day"; None means "nobody measured". Conflating them
    would let the scheduler bias a plan on a number that does not exist."""
    signal = NullRecoverySignal()
    assert signal.enabled is False
    assert await signal.score_for(MONDAY) is None


async def test_a_null_calendar_sink_reports_that_nothing_was_written() -> None:
    """Returning a fabricated id would make downstream code believe an entry exists."""
    sink = NullCalendarSink()
    assert sink.enabled is False
    written = await sink.publish(
        ScheduledEvent(on=MONDAY, minutes=20, title="Study", description="x"),
        existing_id=None,
    )
    assert written is None


def test_the_resolvers_return_null_providers_even_when_the_flags_are_on(
    app_settings: Settings,
) -> None:
    """No real provider ships. The flag selects between null and null, and the test
    says so rather than implying a capability that is not there."""
    enabled = app_settings.model_copy(
        update={"enable_calendar": True, "enable_recovery_signal": True}
    )
    assert isinstance(get_calendar_sink(enabled), NullCalendarSink)
    assert isinstance(get_recovery_signal(enabled), NullRecoverySignal)
