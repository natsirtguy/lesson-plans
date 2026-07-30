"""Changeset schemas: the graph edit vocabulary, and the reviewable diff.

Operations are a discriminated union rather than one record with nullable fields.
The model emits the flat form (see ``app.llm.schemas.ProposedOperation``) because
strict JSON Schema makes a ten-variant union awkward to generate; the service
converts it into these types immediately, so everything downstream -- validation,
reconciliation, the diff UI -- works against a shape where an invalid combination
of fields cannot be represented.

Node references are always ids, never names, by the time an operation reaches
here. Name resolution happens once, at proposal time.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from app.schemas.common import ApiModel


class NewNodeSpec(ApiModel):
    """A concept being created, by an add or a split."""

    name: str = Field(min_length=1, max_length=200)
    definition: str = Field(min_length=1, max_length=2000)
    tier: int = Field(ge=1, le=5)
    #: Existing concepts this one requires. Ids, already resolved.
    prereq_ids: list[str] = Field(default_factory=list)


class AddNode(ApiModel):
    """Add a concept the graph is missing."""

    op_type: Literal["add_node"] = "add_node"
    node: NewNodeSpec


class RemoveNode(ApiModel):
    """Remove a concept.

    The row is soft-deleted, so re-adding the concept later restores its history.
    """

    op_type: Literal["remove_node"] = "remove_node"
    node_id: str
    #: Also remove concepts left with no remaining prerequisite path. Without it,
    #: a dependent stranded above tier 1 makes the changeset invalid, which is the
    #: signal that cascade is what was meant.
    cascade: bool = False


class MergeNodes(ApiModel):
    """Collapse several concepts that are really one thing into a new concept."""

    op_type: Literal["merge_nodes"] = "merge_nodes"
    node_ids: list[str] = Field(min_length=2)
    new_name: str = Field(min_length=1, max_length=200)
    new_definition: str = Field(min_length=1, max_length=2000)
    #: Defaults to the highest tier among the inputs, since the merged concept is
    #: at least as hard as its hardest part.
    tier: int | None = Field(default=None, ge=1, le=5)


class SplitNode(ApiModel):
    """Replace one concept with several finer ones."""

    op_type: Literal["split_node"] = "split_node"
    node_id: str
    into: list[NewNodeSpec] = Field(min_length=2)


class RetierNode(ApiModel):
    """Change a concept's difficulty tier."""

    op_type: Literal["retier_node"] = "retier_node"
    node_id: str
    tier: int = Field(ge=1, le=5)


class AddEdge(ApiModel):
    """Declare that one concept must be learned before another."""

    op_type: Literal["add_edge"] = "add_edge"
    prereq_id: str
    node_id: str


class RemoveEdge(ApiModel):
    """Withdraw a prerequisite relation."""

    op_type: Literal["remove_edge"] = "remove_edge"
    prereq_id: str
    node_id: str


class RetargetEdge(ApiModel):
    """Move a prerequisite relation to a different pair of concepts."""

    op_type: Literal["retarget_edge"] = "retarget_edge"
    prereq_id: str
    node_id: str
    new_prereq_id: str
    new_node_id: str


class RenameNode(ApiModel):
    """Rename a concept without changing what it means."""

    op_type: Literal["rename_node"] = "rename_node"
    node_id: str
    name: str = Field(min_length=1, max_length=200)


class RedefineNode(ApiModel):
    """Rewrite a concept's definition without changing its identity."""

    op_type: Literal["redefine_node"] = "redefine_node"
    node_id: str
    definition: str = Field(min_length=1, max_length=2000)


#: Every operation the graph vocabulary supports.
Operation = Annotated[
    AddNode
    | RemoveNode
    | MergeNodes
    | SplitNode
    | RetierNode
    | AddEdge
    | RemoveEdge
    | RetargetEdge
    | RenameNode
    | RedefineNode,
    Field(discriminator="op_type"),
]


class RefineRequest(ApiModel):
    """A plain-language complaint about the graph."""

    request: str = Field(min_length=3, max_length=4000)


class OperationRead(ApiModel):
    """One operation in a proposed or committed changeset."""

    id: str
    seq: int
    op_type: str
    rationale: str
    #: Null while awaiting review. The learner sets it per operation.
    accepted: bool | None
    applied: bool
    operation: Operation
    #: A human-readable rendering of what this operation does, for the diff view.
    summary: str


class ChangesetRead(ApiModel):
    """A proposed or committed changeset, with its operations."""

    id: str
    subject_id: str
    request_text: str
    rationale: str
    status: str
    base_version: int
    result_version: int | None
    validation_error: str | None
    created_at: datetime
    operations: list[OperationRead]


class OperationDecision(ApiModel):
    """The learner's verdict on one operation."""

    operation_id: str
    accepted: bool


class CommitRequest(ApiModel):
    """Commit the operations the learner accepted.

    Every operation in the changeset must appear exactly once. An operation whose
    verdict is missing is a review that was not finished, and committing it would
    guess at the learner's intent.
    """

    decisions: list[OperationDecision] = Field(min_length=1)


class GraphPreviewNode(ApiModel):
    """A concept as it would look after a changeset commits."""

    id: str
    name: str
    tier: int
    #: What the operation does to this node: added, removed, changed, or unchanged.
    change: str


class ChangesetPreview(ApiModel):
    """The resulting graph if the accepted operations were committed.

    Returned alongside a proposal so the learner sees the consequence, not just the
    list of edits.
    """

    valid: bool
    error: str | None
    node_count: int
    edge_count: int
    nodes: list[GraphPreviewNode]


class SuggestionRead(ApiModel):
    """A proactive proposal that the graph is wrong."""

    id: str
    kind: str
    summary: str
    evidence: dict[str, object]
    node_id: str | None
    status: str
    created_at: datetime
    operations: list[Operation]


class ChangesetSummary(ApiModel):
    """One entry in the changeset log."""

    id: str
    request_text: str
    rationale: str
    status: str
    base_version: int
    result_version: int | None
    created_at: datetime
    operation_count: int
    accepted_count: int
