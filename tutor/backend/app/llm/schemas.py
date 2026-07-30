"""Pydantic schemas for structured model output.

These are the contract for what the model returns, and they are deliberately
separate from both the ORM models and the API schemas: the shape convenient for a
model to emit (prerequisites by *name*, one flat operation record) is not the
shape the database or the client wants.

Constraint keywords like ``ge``/``le`` are stripped before the schema reaches the
API, which does not support them, but they still run during client-side
validation -- so a tier of 9 fails validation and triggers the adapter's retry.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

#: ``extra="forbid"`` makes Pydantic emit ``additionalProperties: false``, which
#: the structured-output endpoint requires on every object.
_STRICT = ConfigDict(extra="forbid")


class GeneratedNode(BaseModel):
    """One concept in a freshly generated graph."""

    model_config = _STRICT

    name: str = Field(description="Short concept name, title case, no numbering.")
    definition: str = Field(description="One sentence defining the concept precisely.")
    tier: int = Field(ge=1, le=5, description="1 is foundational, 5 is advanced.")
    prerequisites: list[str] = Field(
        description=(
            "Names of concepts in this same graph that must be learned first. "
            "Use exact names. Empty for foundational concepts."
        )
    )


class GeneratedGraph(BaseModel):
    """A decomposition of a subject into a prerequisite DAG."""

    model_config = _STRICT

    subject_summary: str = Field(description="One paragraph on what this subject covers.")
    nodes: list[GeneratedNode] = Field(description="Between 40 and 120 concepts.")


class ProposedOperation(BaseModel):
    """One graph edit proposed by the model.

    A flat record with nullable fields rather than a discriminated union of
    per-operation payloads: strict JSON Schema forces every declared property to
    be present, which makes a union of ten variants far more error-prone for the
    model to emit than one record where irrelevant fields are null. The service
    layer converts this into the typed operations in ``app.schemas.changeset``.
    """

    model_config = _STRICT

    op_type: Literal[
        "add_node",
        "remove_node",
        "merge_nodes",
        "split_node",
        "retier_node",
        "add_edge",
        "remove_edge",
        "retarget_edge",
        "rename_node",
        "redefine_node",
    ]
    rationale: str = Field(description="Why this specific edit, in one or two sentences.")

    node_id: str | None = Field(
        default=None, description="Target node id for single-node operations."
    )
    node_ids: list[str] | None = Field(default=None, description="Target node ids for merge_nodes.")
    name: str | None = Field(default=None, description="New or replacement concept name.")
    definition: str | None = Field(default=None, description="New or replacement definition.")
    tier: int | None = Field(default=None, ge=1, le=5, description="New tier.")
    prereq_names: list[str] | None = Field(
        default=None, description="Prerequisite names for add_node."
    )
    children: list[GeneratedNode] | None = Field(
        default=None, description="Replacement concepts for split_node."
    )
    prereq_id: str | None = Field(default=None, description="Source node id for edge operations.")
    new_prereq_id: str | None = Field(
        default=None, description="Replacement source node id for retarget_edge."
    )
    new_node_id: str | None = Field(
        default=None, description="Replacement target node id for retarget_edge."
    )
    cascade: bool | None = Field(
        default=None, description="For remove_node, also remove nodes it solely unblocks."
    )


class ProposedChangeset(BaseModel):
    """A reviewable batch of graph edits with an overall rationale."""

    model_config = _STRICT

    rationale: str = Field(description="Plain-language summary of the proposed change.")
    operations: list[ProposedOperation]


class GeneratedItem(BaseModel):
    """One assessment item targeting a single concept."""

    model_config = _STRICT

    item_format: Literal["multiple_choice", "short_free_text", "explain_why_wrong"]
    stem: str = Field(description="The question as the learner sees it.")
    choices: list[str] = Field(
        description="Four options for multiple_choice; empty list otherwise."
    )
    correct_choice: int | None = Field(
        default=None, description="Zero-based index into choices; null for free text."
    )
    answer_key: str = Field(description="The reference answer, stated fully.")
    rubric: str = Field(
        description=(
            "Scoring guidance: what earns full credit, partial credit, and none. "
            "Written so a grader with no other context can apply it."
        )
    )


class GradeResult(BaseModel):
    """The grader's assessment of one answer."""

    model_config = _STRICT

    score: float = Field(ge=0.0, le=1.0, description="Rubric score, 0 to 1.")
    correct: bool = Field(description="Whether the answer is substantially right.")
    feedback: str = Field(
        description="Two or three sentences addressed to the learner, naming the gap."
    )
    misconception: str | None = Field(
        default=None,
        description="The specific wrong belief the answer reveals, if it reveals one.",
    )


class QueryClassification(BaseModel):
    """Where a free-form question sits relative to the learner's concept graph."""

    model_config = _STRICT

    kind: Literal["existing_node", "new_node", "off_subject"]
    matched_node_id: str | None = Field(
        default=None, description="Node id when kind is existing_node."
    )
    title: str = Field(description="A short title for the lesson this query deserves.")
    concept_name: str | None = Field(
        default=None, description="Concept name when a node should be created."
    )
    definition: str | None = Field(
        default=None, description="One-sentence definition for a new node."
    )
    tier: int | None = Field(default=None, ge=1, le=5, description="Tier for a new node.")
    prereq_names: list[str] | None = Field(
        default=None, description="Existing node names this new concept depends on."
    )
    reason: str = Field(description="Why this classification, in one sentence.")


class UnitBrief(BaseModel):
    """The teaching frame for one lesson-plan unit."""

    model_config = _STRICT

    title: str = Field(description="Unit title, naming the concept plainly.")
    objective: str = Field(
        description=(
            "One sentence starting with a verb, stating what the learner will be able to do."
        )
    )
    estimated_minutes: int = Field(ge=5, le=60)
