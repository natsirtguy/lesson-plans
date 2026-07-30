"""Enumerated values used across the schema.

These are ``StrEnum`` so they compare equal to the plain strings stored in the
database. Columns are declared as ``str`` rather than ``sa.Enum`` to avoid
creating Postgres enum types that then need a migration to extend.
"""

from __future__ import annotations

from enum import StrEnum


class QueueKind(StrEnum):
    """Origin of a graded response, used to attribute evidence."""

    DIAGNOSTIC = "diagnostic"
    EXIT_CHECK = "exit_check"
    REVIEW = "review"
    ASK = "ask"


class ItemFormat(StrEnum):
    """Question formats the diagnostic and exit checks can use."""

    MULTIPLE_CHOICE = "multiple_choice"
    SHORT_FREE_TEXT = "short_free_text"
    EXPLAIN_WHY_WRONG = "explain_why_wrong"


class SessionStatus(StrEnum):
    """Lifecycle of a diagnostic session."""

    ACTIVE = "active"
    COMPLETE = "complete"
    ABANDONED = "abandoned"


class GraphGenerationStatus(StrEnum):
    """Lifecycle of the initial concept-graph build for a subject."""

    PENDING = "pending"
    GENERATING = "generating"
    READY = "ready"
    FAILED = "failed"


class ChangesetStatus(StrEnum):
    """Lifecycle of a proposed graph changeset."""

    PROPOSED = "proposed"
    COMMITTED = "committed"
    REJECTED = "rejected"
    INVALID = "invalid"


class OpType(StrEnum):
    """The graph edit operations a changeset may contain."""

    ADD_NODE = "add_node"
    REMOVE_NODE = "remove_node"
    MERGE_NODES = "merge_nodes"
    SPLIT_NODE = "split_node"
    RETIER_NODE = "retier_node"
    ADD_EDGE = "add_edge"
    REMOVE_EDGE = "remove_edge"
    RETARGET_EDGE = "retarget_edge"
    RENAME_NODE = "rename_node"
    REDEFINE_NODE = "redefine_node"


class PlanStatus(StrEnum):
    """Lifecycle of a generated lesson plan."""

    ACTIVE = "active"
    SUPERSEDED = "superseded"


class UnitStatus(StrEnum):
    """Progress of a single lesson-plan unit."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    SKIPPED = "skipped"


class CardState(StrEnum):
    """FSRS card states."""

    NEW = "new"
    LEARNING = "learning"
    REVIEW = "review"
    RELEARNING = "relearning"


class SuggestionKind(StrEnum):
    """Why the app thinks the graph may be wrong."""

    OFF_GRAPH_IN_SUBJECT = "off_graph_in_subject"
    BIMODAL_NODE = "bimodal_node"
    UNREACHABLE_NODE = "unreachable_node"
    ORPHAN_NODE = "orphan_node"


class SuggestionStatus(StrEnum):
    """Lifecycle of a proactive suggestion."""

    OPEN = "open"
    APPLIED = "applied"
    DISMISSED = "dismissed"


class NodeOrigin(StrEnum):
    """How a concept node came to exist."""

    GENERATED = "generated"
    REFINEMENT = "refinement"
    ASK = "ask"
    SATELLITE = "satellite"


class StudySessionStatus(StrEnum):
    """Lifecycle of a planned study session."""

    PLANNED = "planned"
    COMPLETE = "complete"
    MISSED = "missed"
