"""FSRS review cards (layer 1) and planned study sessions (layer 2).

These are deliberately separate tables: FSRS decides when an item is due, the
session planner decides when the learner sits down. Conflating them is how apps
end up handing someone a 90-card day and calling it a plan.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Date,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, IdMixin, TimestampMixin, UTCDateTime
from app.models.enums import CardState, StudySessionStatus


class ReviewCard(Base, IdMixin, TimestampMixin):
    """FSRS scheduling state for one concept.

    One card per concept rather than per generated item: items are disposable LLM
    output, so pinning intervals to a specific item would reset scheduling every
    time content is regenerated. Each retrieval draws a fresh item for the concept.
    """

    __tablename__ = "review_cards"
    __table_args__ = (UniqueConstraint("node_id", name="uq_review_cards_node_id"),)

    subject_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    node_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("concept_nodes.id", ondelete="CASCADE"), nullable=False
    )
    state: Mapped[str] = mapped_column(String(16), default=CardState.NEW, nullable=False)
    #: FSRS memory stability, in days.
    stability: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    #: FSRS item difficulty, on FSRS's own 1-10 scale (not the 1-5 tier scale).
    difficulty: Mapped[float] = mapped_column(Float, default=5.0, nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None, index=True)
    last_review_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    reps: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    lapses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    #: Index into the relearning step ladder while in the relearning state.
    step_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    #: Interval FSRS last scheduled, in days.
    scheduled_days: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    #: Position in the expanding ladder (1d, 3d, 7d, 21d) before FSRS takes over.
    acquisition_step: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class StudySession(Base, IdMixin, TimestampMixin):
    """A proposed sitting: opening retrieval, new material, exit check."""

    __tablename__ = "study_sessions"

    subject_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scheduled_for: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(16), default=StudySessionStatus.PLANNED, nullable=False
    )
    planned_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    retrieval_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Concepts whose cards open the session, in interleaved order.
    review_node_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    #: Concepts taught as new material this session.
    new_node_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    #: Plan units this session covers.
    unit_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    #: Reviews that exceeded the daily cap and were pushed out.
    deferred_node_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    #: Projected coverage after this session completes, in [0, 1].
    projected_coverage: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    #: Recovery score in [0, 1] if a signal was available when planning.
    recovery_score: Mapped[float | None] = mapped_column(Float, default=None)
    #: Notes the planner wants the learner to see, e.g. a load warning.
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    #: External calendar event id when the session was written to a calendar.
    calendar_event_id: Mapped[str | None] = mapped_column(String(200), default=None)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    #: Free-form planner diagnostics, kept for debugging schedule shape.
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
