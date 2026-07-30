"""Subject and cadence schemas."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import Field

from app.schemas.common import ApiModel


class SubjectCreate(ApiModel):
    """Request to start studying a subject."""

    name: str = Field(min_length=2, max_length=200)
    description: str = Field(default="", max_length=4000)
    #: Optional cadence, applied at creation so the first schedule is right.
    days_per_week: int | None = Field(default=None, ge=1, le=7)
    minutes_per_session: int | None = Field(default=None, ge=5, le=180)


class CadenceUpdate(ApiModel):
    """Partial update of how the learner wants to study.

    Every field is optional; omitted fields are left alone.
    """

    days_per_week: int | None = Field(default=None, ge=1, le=7)
    minutes_per_session: int | None = Field(default=None, ge=5, le=180)
    daily_review_cap: int | None = Field(default=None, ge=1, le=500)
    #: Setting a deadline switches the planner into compressed-spacing mode.
    #: Passing null clears it and returns to long-retention spacing.
    deadline: date | None = None
    clear_deadline: bool = False
    target_retention: float | None = Field(default=None, ge=0.7, le=0.97)
    recovery_aware: bool | None = None


class SubjectRead(ApiModel):
    """A subject, without its graph."""

    id: str
    name: str
    description: str
    graph_version: int
    graph_status: str
    graph_error: str | None
    days_per_week: int
    minutes_per_session: int
    daily_review_cap: int
    deadline: date | None
    target_retention: float
    recovery_aware: bool
    created_at: datetime
    #: Live concept count, or 0 while the graph is still being generated.
    node_count: int = 0
