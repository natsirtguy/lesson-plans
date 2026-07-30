"""The subject aggregate: what the learner is studying, and how they want to study it."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, IdMixin, TimestampMixin, UTCDateTime
from app.models.enums import GraphGenerationStatus


class Subject(Base, IdMixin, TimestampMixin):
    """A subject the learner is studying, plus its cadence configuration.

    Cadence lives here rather than in its own table because there is exactly one
    active cadence per subject and it is patched, not versioned.
    """

    __tablename__ = "subjects"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)

    #: Monotonic counter bumped by every committed changeset.
    graph_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    graph_status: Mapped[str] = mapped_column(
        String(24), default=GraphGenerationStatus.PENDING, nullable=False
    )
    graph_error: Mapped[str | None] = mapped_column(Text, default=None)

    # --- cadence -------------------------------------------------------------
    days_per_week: Mapped[int] = mapped_column(Integer, default=4, nullable=False)
    minutes_per_session: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    daily_review_cap: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    #: Optional target date. Its presence switches the planner into deadline mode.
    deadline: Mapped[date | None] = mapped_column(Date, default=None)
    target_retention: Mapped[float] = mapped_column(Float, default=0.85, nullable=False)
    #: Bias hard sessions toward high-recovery days when a signal is available.
    recovery_aware: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    #: Last time decay was applied, so it is applied once per read rather than compounded.
    last_decay_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
