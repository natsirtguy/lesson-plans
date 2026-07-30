"""Lesson plans, their units, and cached lesson content."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, IdMixin, TimestampMixin
from app.models.enums import PlanStatus, UnitStatus


class LessonPlan(Base, IdMixin, TimestampMixin):
    """A sequenced plan driving the learner toward full coverage of a subject."""

    __tablename__ = "lesson_plans"

    subject_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(16), default=PlanStatus.ACTIVE, nullable=False)
    #: Graph version the sequencing was computed from.
    graph_version: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Estimated coverage at plan creation, so progress can be shown against it.
    coverage_at_creation: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)


class PlanUnit(Base, IdMixin, TimestampMixin):
    """One sitting-sized unit of a lesson plan, targeting a single concept."""

    __tablename__ = "plan_units"
    __table_args__ = (UniqueConstraint("plan_id", "seq", name="uq_plan_units_plan_seq"),)

    plan_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("lesson_plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subject_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    node_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("concept_nodes.id", ondelete="CASCADE"), nullable=False
    )
    #: Position in the plan; prerequisite units always have a lower seq.
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    estimated_minutes: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=UnitStatus.PENDING, nullable=False)
    #: Nodes interleaved into this unit's opening retrieval.
    interleaved_node_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    #: True on a concept's first-ever unit, where block practice is correct.
    first_acquisition: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    #: Why the sequencer put this unit here, shown in the plan view.
    placement_reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    #: Score the sequencer assigned: weakness x unblocking power.
    priority: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    #: Ids of the exit-check items generated for this unit.
    exit_check_item_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)


class Lesson(Base, IdMixin, TimestampMixin):
    """Generated lesson prose, cached by (node, difficulty, level).

    Persisting the assembled markdown after a stream is what lets the service
    worker serve it offline: a streamed SSE response cannot be cached, a plain GET
    of this row can.
    """

    __tablename__ = "lessons"
    __table_args__ = (UniqueConstraint("cache_key", name="uq_lessons_cache_key"),)

    subject_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: Null for off-subject ask-anything answers that were never attached to a node.
    node_id: Mapped[str | None] = mapped_column(String(36), default=None, index=True)
    unit_id: Mapped[str | None] = mapped_column(String(36), default=None, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    difficulty: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    level: Mapped[str] = mapped_column(String(16), default="novice", nullable=False)
    markdown: Mapped[str] = mapped_column(Text, default="", nullable=False)
    #: False while a stream is in flight; the row is written before content arrives.
    complete: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    cache_key: Mapped[str] = mapped_column(String(200), nullable=False)
    #: Where an ask-anything lesson came from: the query and its classification.
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
