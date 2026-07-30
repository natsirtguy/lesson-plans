"""Study-schedule schemas."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import Field

from app.schemas.common import ApiModel


class SessionRead(ApiModel):
    """One planned sitting."""

    id: str | None
    scheduled_for: date
    status: str
    planned_minutes: int
    retrieval_minutes: int
    review_node_ids: list[str]
    review_names: list[str]
    new_node_ids: list[str]
    new_names: list[str]
    unit_ids: list[str]
    #: Reviews that were due but exceeded the daily cap.
    deferred_node_ids: list[str]
    notes: str
    completed_at: datetime | None


class DeadlineRead(ApiModel):
    """Whether the cadence finishes the plan by the target date."""

    deadline: date | None
    sessions_available: int
    sessions_needed: int
    achievable: bool
    shortfall_sessions: int
    message: str


class AdherenceRead(ApiModel):
    """How consistently the learner has been showing up.

    Counts, not points. The spec is explicit that this is not to be gamified, so
    there are no badges, no levels, and no streak that "breaks" with a penalty --
    just the numbers, which are useful for deciding whether the cadence is
    realistic.
    """

    sessions_planned: int
    sessions_completed: int
    sessions_missed: int
    #: Completed share of sessions whose date has passed, or None if none have.
    completion_rate: float | None
    #: Consecutive most-recent past sessions that were completed.
    current_streak: int
    longest_streak: int


class ScheduleRead(ApiModel):
    """A rolling schedule and everything the schedule view shows."""

    subject_id: str
    generated_for: date
    horizon_days: int
    days_per_week: int
    minutes_per_session: int
    daily_review_cap: int
    sessions: list[SessionRead]
    deadline: DeadlineRead
    adherence: AdherenceRead
    units_scheduled: int
    units_remaining: int
    #: Reviews due right now, before the schedule spreads them out.
    due_now: int


class ScheduleRequest(ApiModel):
    """Options when generating a schedule."""

    horizon_days: int = Field(default=14, ge=1, le=90)
    #: Regenerate and persist, replacing any planned sessions from before.
    persist: bool = True


class SessionComplete(ApiModel):
    """Marking a planned sitting as done."""

    notes: str = Field(default="", max_length=2000)
