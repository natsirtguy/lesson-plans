"""Append-only changeset log and proactive graph suggestions.

A changeset is the only way the graph changes after generation. It is proposed
whole, approved per operation, and committed atomically. Committed changesets are
never rewritten -- they are the audit trail for how the learner's map of a
subject evolved, and the first place to look when propagation misbehaves.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, IdMixin, TimestampMixin
from app.models.enums import ChangesetStatus, SuggestionStatus


class Changeset(Base, IdMixin, TimestampMixin):
    """A proposed or committed batch of graph edits."""

    __tablename__ = "changesets"

    subject_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: The learner's plain-language request, verbatim.
    request_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    #: The model's overall explanation of what it proposes and why.
    rationale: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), default=ChangesetStatus.PROPOSED, nullable=False
    )
    #: Graph version this changeset was computed against.
    base_version: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Graph version produced by committing it; null until committed.
    result_version: Mapped[int | None] = mapped_column(Integer, default=None)
    #: Why validation rejected the changeset, if it did.
    validation_error: Mapped[str | None] = mapped_column(Text, default=None)
    #: Set when this changeset was generated from a proactive suggestion.
    suggestion_id: Mapped[str | None] = mapped_column(String(36), default=None)


class ChangesetOp(Base, IdMixin, TimestampMixin):
    """One operation within a changeset, individually approvable.

    ``payload`` holds the operation-specific arguments, shaped by the matching
    Pydantic model in ``app.schemas.changeset``. Storing it as JSON keeps the
    operation vocabulary extensible without a migration per new operation.
    """

    __tablename__ = "changeset_ops"

    changeset_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("changesets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: Position within the changeset; operations apply in this order.
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    op_type: Mapped[str] = mapped_column(String(24), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    #: Plain-language justification shown next to this operation in the diff.
    rationale: Mapped[str] = mapped_column(Text, default="", nullable=False)
    #: Null while awaiting review; the learner sets it per operation.
    accepted: Mapped[bool | None] = mapped_column(Boolean, default=None)
    applied: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: Node ids created or affected by applying this operation, for lineage.
    result_node_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)


class GraphSuggestion(Base, IdMixin, TimestampMixin):
    """A proactive proposal that the graph is wrong, with its evidence.

    Surfaced in the report view rather than interrupting a session.
    """

    __tablename__ = "graph_suggestions"

    subject_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    #: Human-readable statement of what looks wrong.
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    #: What the app observed that triggered the suggestion.
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    #: Draft operations, in the same shape as ``ChangesetOp.payload``.
    proposed_ops: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    #: Node this suggestion is about, when it is about one node.
    node_id: Mapped[str | None] = mapped_column(String(36), default=None)
    status: Mapped[str] = mapped_column(String(16), default=SuggestionStatus.OPEN, nullable=False)
    #: Deduplication key so the same observation is not surfaced twice.
    dedupe_key: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
