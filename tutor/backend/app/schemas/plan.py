"""Lesson plan schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.schemas.common import ApiModel


class PlanCreate(ApiModel):
    """Options when generating a plan."""

    #: Cap the number of units; the rest are reported as truncated rather than lost.
    limit: int | None = Field(default=None, ge=1, le=500)
    #: Earlier concepts folded into each unit's opening retrieval.
    interleave: int | None = Field(default=None, ge=0, le=4)


class PlanUnitRead(ApiModel):
    """One sitting-sized unit."""

    id: str
    seq: int
    node_id: str
    node_name: str
    tier: int
    title: str
    objective: str
    estimated_minutes: int
    status: str
    #: Why the sequencer put this unit here.
    placement_reason: str
    priority: float
    #: Already-taught concepts folded into this unit's opening retrieval.
    interleaved_node_ids: list[str]
    interleaved_names: list[str]
    #: True on a concept's first unit, where block practice is correct.
    first_acquisition: bool
    completed_at: datetime | None


class PlanRead(ApiModel):
    """A generated plan and its units."""

    id: str
    subject_id: str
    status: str
    graph_version: int
    coverage_at_creation: float
    #: Coverage now, so progress against the plan is visible.
    coverage_now: float
    created_at: datetime
    units: list[PlanUnitRead]
    #: Concepts left out because they are already mastered.
    skipped_mastered: int
    #: Concepts that fell past ``limit``; non-zero means this plan is a prefix.
    truncated: int


class LessonRead(ApiModel):
    """Generated lesson prose, or the placeholder awaiting it."""

    id: str
    subject_id: str
    node_id: str | None
    unit_id: str | None
    title: str
    difficulty: int
    level: str
    markdown: str
    #: False while the prose is still being streamed in.
    complete: bool
    created_at: datetime


class ExitCheckItemRead(ApiModel):
    """One exit-check question, as the learner sees it.

    Deliberately not the diagnostic's :class:`~app.schemas.diagnostic.ItemRead`:
    that one carries session progress counters, which mean nothing here. Like it,
    this carries no answer key -- the client must not be able to grade itself.
    """

    id: str
    node_id: str
    node_name: str
    tier: int
    item_format: str
    difficulty: int
    stem: str
    choices: list[str]


class NextUnit(ApiModel):
    """The next unit to study, with its exit check."""

    unit: PlanUnitRead | None
    finished: bool
    #: Items the learner must answer to close the unit.
    exit_check: list[ExitCheckItemRead]
    #: Id of the lesson record whose prose can be streamed or fetched.
    lesson_id: str | None


class ExitCheckAnswer(ApiModel):
    """One answer in a unit's exit check."""

    item_id: str
    answer: str = Field(max_length=8000)


class UnitComplete(ApiModel):
    """Exit-check results for a finished unit."""

    answers: list[ExitCheckAnswer] = Field(default_factory=list)
    #: Set when the learner is closing the unit without attempting the check.
    skipped: bool = False


class UnitCompleteResult(ApiModel):
    """What completing a unit changed."""

    unit_id: str
    status: str
    #: Mean rubric score across the exit check, or None when it was skipped.
    exit_score: float | None
    mastery_before: float
    mastery_after: float
    feedback: list[str]
    coverage_now: float
    next_unit_id: str | None
