"""Layer 2: when the learner sits down, and what happens in that sitting.

FSRS answers "when is this concept due". It has no idea the learner studies four
evenings a week for twenty minutes, and left to itself it will happily produce a
day with ninety due cards. This module takes the due queue and the plan and fits
them into sittings a person will actually do.

**Session shape is fixed.** Retrieval first, then new material, then an exit check.
Opening with retrieval rather than instruction is the whole point: the strongest
version of the testing effect comes from trying to recall *before* being reminded,
and a session that opens by teaching turns every review into recognition.

**The cap is a real constraint, not a suggestion.** Reviews past the daily cap are
deferred, and deferring them is reported. A planner that silently drops work is
worse than one that admits it is behind, because the learner cannot act on
something they were not told.

**Deadline mode does not lie.** Given a target date, the planner computes what the
remaining plan costs in sessions and compares it to the sessions the cadence
actually provides. If it does not fit, it says so and by how much, rather than
quietly compressing the schedule into something that will not be done.

Pure: dates in, plan out. No database, no clock read that is not an argument.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

#: Weekday spread used when a cadence asks for N days a week. Chosen to spread
#: sessions apart rather than clumping them, because spacing is the point: 4 days
#: a week is Mon/Tue/Thu/Sat, not Mon/Tue/Wed/Thu.
WEEKDAY_SPREADS: dict[int, tuple[int, ...]] = {
    1: (2,),
    2: (1, 4),
    3: (0, 2, 4),
    4: (0, 1, 3, 5),
    5: (0, 1, 2, 4, 5),
    6: (0, 1, 2, 3, 4, 5),
    7: (0, 1, 2, 3, 4, 5, 6),
}


@dataclass(frozen=True, slots=True)
class Cadence:
    """How the learner wants to study.

    :param days_per_week: Sessions per week, 1 through 7.
    :param minutes_per_session: Length of one sitting.
    :param daily_review_cap: Most reviews to schedule into a single session.
    :param retrieval_minutes: Minutes of the sitting reserved for opening retrieval.
    :param minutes_per_review: Assumed wall-clock cost of one retrieval.
    :param minutes_per_new_node: Assumed wall-clock cost of one new concept.
    :param deadline: Target date, which switches the planner into deadline mode.
    """

    days_per_week: int = 4
    minutes_per_session: int = 20
    daily_review_cap: int = 20
    retrieval_minutes: int = 5
    minutes_per_review: float = 0.5
    minutes_per_new_node: float = 7.0
    deadline: date | None = None


@dataclass(frozen=True, slots=True)
class DueItem:
    """One concept competing for a slot in the opening retrieval.

    :param node_id: The concept.
    :param due_on: The day it came due.
    :param priority: How much clearing it is worth, from the review queue.
    """

    node_id: str
    due_on: date
    priority: float


@dataclass(frozen=True, slots=True)
class PlannedSession:
    """One sitting.

    :param on: The date it is planned for.
    :param planned_minutes: Total length.
    :param retrieval_minutes: Minutes budgeted for the opening retrieval.
    :param review_node_ids: Concepts to retrieve, in interleaved order.
    :param new_node_ids: Concepts taught as new material.
    :param unit_ids: Plan units this session covers.
    :param deferred_node_ids: Reviews that were due but did not fit.
    :param notes: What the learner should know about this session's shape.
    """

    on: date
    planned_minutes: int
    retrieval_minutes: int
    review_node_ids: tuple[str, ...]
    new_node_ids: tuple[str, ...]
    unit_ids: tuple[str, ...]
    deferred_node_ids: tuple[str, ...]
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DeadlineVerdict:
    """Whether the cadence can finish the plan in time.

    :param deadline: The target date, when there is one.
    :param sessions_available: Sessions the cadence provides before the deadline.
    :param sessions_needed: Sessions the remaining plan actually costs.
    :param achievable: Whether it fits.
    :param shortfall_sessions: How many sessions short, zero when it fits.
    :param message: What to tell the learner, in one sentence.
    """

    deadline: date | None
    sessions_available: int
    sessions_needed: int
    achievable: bool
    shortfall_sessions: int
    message: str


@dataclass(frozen=True, slots=True)
class Schedule:
    """A rolling schedule with its deadline verdict.

    :param sessions: Sittings, in date order.
    :param verdict: The deadline assessment.
    :param units_scheduled: Plan units placed into sessions.
    :param units_remaining: Plan units still beyond the horizon.
    """

    sessions: tuple[PlannedSession, ...] = ()
    verdict: DeadlineVerdict | None = None
    units_scheduled: int = 0
    units_remaining: int = 0


@dataclass(slots=True)
class _Budget:
    """Working state while filling one session.

    :param reviews: Concepts accepted into the opening retrieval.
    :param new_nodes: Concepts accepted as new material.
    :param units: Units accepted.
    """

    reviews: list[str] = field(default_factory=list)
    new_nodes: list[str] = field(default_factory=list)
    units: list[str] = field(default_factory=list)


def session_days(start: date, count: int, cadence: Cadence) -> tuple[date, ...]:
    """The next ``count`` dates the learner has agreed to study on.

    :param start: First date to consider, inclusive.
    :param count: How many session dates to produce.
    :param cadence: The learner's cadence.
    """
    if count <= 0:
        return ()
    wanted = set(WEEKDAY_SPREADS[min(max(cadence.days_per_week, 1), 7)])
    days: list[date] = []
    day = start
    # Bounded so a nonsensical cadence cannot spin: at worst one session a week.
    for _ in range(count * 7 + 7):
        if len(days) >= count:
            break
        if day.weekday() in wanted:
            days.append(day)
        day += timedelta(days=1)
    return tuple(days)


def session_days_until(start: date, end: date, cadence: Cadence) -> tuple[date, ...]:
    """Every date between two days, inclusive, that the cadence studies on.

    :param start: First date to consider, inclusive.
    :param end: Last date to consider, inclusive.
    :param cadence: The learner's cadence.
    """
    wanted = set(WEEKDAY_SPREADS[min(max(cadence.days_per_week, 1), 7)])
    days: list[date] = []
    day = start
    while day <= end:
        if day.weekday() in wanted:
            days.append(day)
        day += timedelta(days=1)
    return tuple(days)


def session_capacity(cadence: Cadence) -> tuple[int, int]:
    """How many reviews and new concepts one sitting holds.

    :param cadence: The learner's cadence.
    """
    retrieval = min(cadence.retrieval_minutes, cadence.minutes_per_session)
    reviews = int(retrieval / max(cadence.minutes_per_review, 0.01))
    remaining = cadence.minutes_per_session - retrieval
    new_nodes = int(remaining / max(cadence.minutes_per_new_node, 0.01))
    # Even a very short sitting teaches something; otherwise a tight cadence
    # produces a schedule of pure review that never advances the plan.
    return max(reviews, 1), max(new_nodes, 1)


def plan_schedule(
    *,
    start: date,
    due: list[DueItem],
    unit_ids: list[str],
    unit_node_ids: list[str],
    cadence: Cadence,
    horizon_days: int = 14,
) -> Schedule:
    """Lay the due queue and the remaining plan into a rolling schedule.

    :param start: First date to schedule from.
    :param due: Concepts already due, in priority order.
    :param unit_ids: Remaining plan units, in plan order.
    :param unit_node_ids: The concept each of those units teaches, same order.
    :param cadence: The learner's cadence.
    :param horizon_days: How far ahead to schedule.
    """
    per_review, per_new = session_capacity(cadence)
    dates = session_days_until(start, start + timedelta(days=horizon_days - 1), cadence)

    pending_reviews = list(due)
    pending_units = list(zip(unit_ids, unit_node_ids, strict=True))
    sessions: list[PlannedSession] = []
    scheduled_units = 0

    for day in dates:
        budget = _Budget()
        cap = min(per_review, cadence.daily_review_cap)
        arrived = [item for item in pending_reviews if item.due_on <= day]
        budget.reviews = [item.node_id for item in arrived[:cap]]
        deferred = [item.node_id for item in arrived[cap:]]
        pending_reviews = [
            item for item in pending_reviews if item.node_id not in set(budget.reviews)
        ]

        for unit_id, node_id in pending_units[:per_new]:
            budget.units.append(unit_id)
            budget.new_nodes.append(node_id)
        pending_units = pending_units[len(budget.units) :]
        scheduled_units += len(budget.units)

        notes: list[str] = []
        if deferred:
            notes.append(
                f"{len(deferred)} review{'s' if len(deferred) != 1 else ''} did not fit and "
                "will lead the next session."
            )
        if not budget.units and not budget.reviews:
            notes.append("Nothing is due and the plan is finished; this session is free.")

        sessions.append(
            PlannedSession(
                on=day,
                planned_minutes=cadence.minutes_per_session,
                retrieval_minutes=min(cadence.retrieval_minutes, cadence.minutes_per_session),
                review_node_ids=tuple(budget.reviews),
                new_node_ids=tuple(budget.new_nodes),
                unit_ids=tuple(budget.units),
                deferred_node_ids=tuple(deferred),
                notes=tuple(notes),
            )
        )

    return Schedule(
        sessions=tuple(sessions),
        verdict=assess_deadline(
            start=start, remaining_units=len(unit_ids), cadence=cadence, per_new=per_new
        ),
        units_scheduled=scheduled_units,
        units_remaining=len(pending_units),
    )


def assess_deadline(
    *, start: date, remaining_units: int, cadence: Cadence, per_new: int
) -> DeadlineVerdict:
    """Say plainly whether the cadence finishes the plan by the deadline.

    :param start: The date the assessment is made from.
    :param remaining_units: Plan units still to teach.
    :param cadence: The learner's cadence.
    :param per_new: New concepts one sitting holds.
    """
    needed = -(-remaining_units // max(per_new, 1))
    if cadence.deadline is None:
        return DeadlineVerdict(
            deadline=None,
            sessions_available=0,
            sessions_needed=needed,
            achievable=True,
            shortfall_sessions=0,
            message=(
                f"No deadline set. At this cadence the remaining plan takes about "
                f"{needed} session{'s' if needed != 1 else ''}."
            ),
        )

    days_left = (cadence.deadline - start).days
    if days_left < 0:
        return DeadlineVerdict(
            deadline=cadence.deadline,
            sessions_available=0,
            sessions_needed=needed,
            achievable=needed == 0,
            shortfall_sessions=needed,
            message=(
                f"The deadline of {cadence.deadline.isoformat()} has passed with "
                f"{remaining_units} concept{'s' if remaining_units != 1 else ''} left."
            ),
        )

    available = len(session_days_until(start, cadence.deadline, cadence))
    if needed <= available:
        return DeadlineVerdict(
            deadline=cadence.deadline,
            sessions_available=available,
            sessions_needed=needed,
            achievable=True,
            shortfall_sessions=0,
            message=(
                f"On track: {needed} session{'s' if needed != 1 else ''} of work and "
                f"{available} available before {cadence.deadline.isoformat()}."
            ),
        )

    shortfall = needed - available
    extra_days = _days_per_week_needed(needed, days_left)
    advice = (
        f"studying {extra_days} days a week instead of {cadence.days_per_week}"
        if extra_days is not None
        else "extending the deadline or narrowing the subject"
    )
    return DeadlineVerdict(
        deadline=cadence.deadline,
        sessions_available=available,
        sessions_needed=needed,
        achievable=False,
        shortfall_sessions=shortfall,
        message=(
            f"This will not fit: {needed} sessions of work against {available} available "
            f"before {cadence.deadline.isoformat()}, a shortfall of {shortfall}. "
            f"It becomes achievable by {advice}."
        ),
    )


def _days_per_week_needed(needed: int, days_left: int) -> int | None:
    """The smallest weekly cadence that would fit the work, if one exists.

    :param needed: Sessions of work remaining.
    :param days_left: Calendar days until the deadline.
    """
    weeks = max(days_left, 1) / 7.0
    for candidate in range(1, 8):
        if candidate * weeks >= needed:
            return candidate
    return None
