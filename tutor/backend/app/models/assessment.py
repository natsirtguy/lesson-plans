"""Diagnostic sessions, generated quiz items, and graded responses."""

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
from app.models.enums import QueueKind, SessionStatus


class DiagnosticSession(Base, IdMixin, TimestampMixin):
    """One adaptive diagnostic run over a subject's graph."""

    __tablename__ = "diagnostic_sessions"

    subject_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(16), default=SessionStatus.ACTIVE, nullable=False)
    #: Graph version the session ran against; a committed changeset mid-session is fine,
    #: but the recorded version explains why the item mix looks the way it does.
    graph_version: Mapped[int] = mapped_column(Integer, nullable=False)
    max_items: Mapped[int] = mapped_column(Integer, nullable=False)
    min_items: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Stop once mean confidence over live nodes reaches this.
    confidence_target: Mapped[float] = mapped_column(Float, nullable=False)
    asked_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    #: Mean confidence when the session ended, for after-the-fact tuning.
    final_mean_confidence: Mapped[float | None] = mapped_column(Float, default=None)
    stop_reason: Mapped[str | None] = mapped_column(String(32), default=None)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class QuizItem(Base, IdMixin, TimestampMixin):
    """A generated assessment item, cached for reuse.

    Each item carries its own rubric and target node so grading is reproducible
    even after the graph or the learner's level moves on. ``cache_key`` is what
    makes generation idempotent for a given (node, difficulty, level, format).
    """

    __tablename__ = "quiz_items"
    __table_args__ = (UniqueConstraint("cache_key", name="uq_quiz_items_cache_key"),)

    subject_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    node_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("concept_nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    item_format: Mapped[str] = mapped_column(String(24), nullable=False)
    #: Item difficulty on the same 1-5 scale as node tiers.
    difficulty: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Coarse learner-level bucket the item was pitched at, e.g. "novice".
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    stem: Mapped[str] = mapped_column(Text, nullable=False)
    #: Present for multiple choice; empty otherwise.
    choices: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    #: Index into ``choices`` for multiple choice; null for free-text formats.
    correct_choice: Mapped[int | None] = mapped_column(Integer, default=None)
    #: The reference answer a grader compares against.
    answer_key: Mapped[str] = mapped_column(Text, nullable=False)
    #: Scoring guidance handed to the grader verbatim.
    rubric: Mapped[str] = mapped_column(Text, nullable=False)
    cache_key: Mapped[str] = mapped_column(String(200), nullable=False)


class ItemResponse(Base, IdMixin, TimestampMixin):
    """A graded answer to one item."""

    __tablename__ = "item_responses"

    subject_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("quiz_items.id", ondelete="CASCADE"), nullable=False
    )
    node_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("concept_nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[str | None] = mapped_column(String(36), default=None, index=True)
    #: Where this retrieval came from, which decides whether FSRS sees it.
    source: Mapped[str] = mapped_column(String(16), default=QueueKind.DIAGNOSTIC, nullable=False)
    raw_answer: Mapped[str] = mapped_column(Text, default="", nullable=False)
    #: Rubric score in [0, 1].
    score: Mapped[float] = mapped_column(Float, nullable=False)
    #: Four-point FSRS grade derived from ``score``.
    grade: Mapped[int] = mapped_column(Integer, nullable=False)
    correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    #: Grader's explanation, shown to the learner as feedback.
    feedback: Mapped[str] = mapped_column(Text, default="", nullable=False)
    #: Mastery before and after this response, for debugging the update rule.
    mastery_before: Mapped[float | None] = mapped_column(Float, default=None)
    mastery_after: Mapped[float | None] = mapped_column(Float, default=None)
    #: Nodes touched by propagation and by how much.
    propagation: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
