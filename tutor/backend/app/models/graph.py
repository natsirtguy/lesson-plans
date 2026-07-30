"""Concept nodes, prerequisite edges, and per-node mastery state.

Edge direction is load-bearing and easy to invert: an edge is stored as
``(prereq_id -> node_id)`` and means *prereq must be learned before node*.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, IdMixin, TimestampMixin, UTCDateTime
from app.models.enums import NodeOrigin


class ConceptNode(Base, IdMixin, TimestampMixin):
    """One concept in a subject's graph.

    Nodes are soft-deleted so that mastery history survives removal: re-adding a
    concept with the same ``name_key`` restores the learner's prior estimate
    rather than starting from scratch.
    """

    __tablename__ = "concept_nodes"
    __table_args__ = (
        UniqueConstraint("subject_id", "name_key", name="uq_concept_nodes_subject_name_key"),
        Index("ix_concept_nodes_subject_live", "subject_id", "deleted_at"),
    )

    subject_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    #: Normalized name used for stable identity across remove/re-add cycles.
    name_key: Mapped[str] = mapped_column(String(200), nullable=False)
    definition: Mapped[str] = mapped_column(Text, nullable=False)
    #: Difficulty tier, 1 (foundational) through 5 (advanced).
    tier: Mapped[int] = mapped_column(Integer, nullable=False)
    origin: Mapped[str] = mapped_column(String(24), default=NodeOrigin.GENERATED, nullable=False)
    #: True for concepts that are adjacent to but outside the subject proper.
    is_satellite: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    #: Graph version at which the node first appeared, and at which it was removed.
    introduced_in_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    removed_in_version: Mapped[int | None] = mapped_column(Integer, default=None)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)

    #: Set when this node was superseded by a merge or split, for lineage queries.
    superseded_by: Mapped[str | None] = mapped_column(String(36), default=None)


class ConceptEdge(Base, IdMixin, TimestampMixin):
    """A prerequisite relation: ``prereq_id`` must be learned before ``node_id``."""

    __tablename__ = "concept_edges"
    __table_args__ = (
        UniqueConstraint(
            "subject_id", "prereq_id", "node_id", name="uq_concept_edges_subject_pair"
        ),
        Index("ix_concept_edges_subject_live", "subject_id", "deleted_at"),
    )

    subject_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    prereq_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("concept_nodes.id", ondelete="CASCADE"), nullable=False
    )
    node_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("concept_nodes.id", ondelete="CASCADE"), nullable=False
    )
    introduced_in_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    removed_in_version: Mapped[int | None] = mapped_column(Integer, default=None)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)


class MasteryRecord(Base, IdMixin, TimestampMixin):
    """The learner's estimated mastery of one concept.

    Kept in a separate table from the node so that a soft-deleted node's history
    is trivially preserved and restorable. One row per node, ever.
    """

    __tablename__ = "mastery_records"
    __table_args__ = (UniqueConstraint("node_id", name="uq_mastery_records_node_id"),)

    subject_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    node_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("concept_nodes.id", ondelete="CASCADE"), nullable=False
    )
    #: Point estimate in [0, 1].
    mastery: Mapped[float] = mapped_column(Float, default=0.15, nullable=False)
    #: Inverse-variance style certainty in [0, 1]; 0 means "we know nothing".
    confidence: Mapped[float] = mapped_column(Float, default=0.05, nullable=False)
    #: Count of observations that targeted this node directly.
    direct_observations: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    #: Count of observations that reached this node only by propagation.
    indirect_observations: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    #: Last time decay was applied, so elapsed time is never double-counted.
    decayed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
