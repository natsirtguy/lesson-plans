"""Diagnostic session schemas."""

from __future__ import annotations

from pydantic import Field

from app.schemas.common import ApiModel


class DiagnosticStart(ApiModel):
    """Options when starting a diagnostic."""

    #: Override the configured item cap, e.g. for a quick re-check.
    max_items: int | None = Field(default=None, ge=1, le=100)


class SessionRead(ApiModel):
    """A diagnostic session's state."""

    id: str
    subject_id: str
    status: str
    asked_count: int
    max_items: int
    min_items: int
    #: Mean confidence across the graph, which is what the stopping rule watches.
    mean_confidence: float
    stop_reason: str | None


class ItemRead(ApiModel):
    """The next question, as the learner sees it.

    Carries no answer key: the client must not be able to grade itself.
    """

    id: str
    node_id: str
    node_name: str
    tier: int
    item_format: str
    difficulty: int
    stem: str
    choices: list[str]
    #: How far through the session this is, for a progress indicator.
    asked_count: int
    max_items: int


class NextItem(ApiModel):
    """Either the next question, or the reason there is not one."""

    item: ItemRead | None
    finished: bool
    stop_reason: str | None
    session: SessionRead


class AnswerSubmit(ApiModel):
    """A learner's answer to one item."""

    item_id: str
    #: For multiple choice, the chosen index as a string; otherwise free text.
    answer: str = Field(max_length=8000)


class MasteryChange(ApiModel):
    """How one concept's estimate moved because of an answer."""

    node_id: str
    node_name: str
    mastery_before: float
    mastery_after: float
    confidence_after: float
    #: True when this concept was not the one asked about, but was informed by it.
    propagated: bool


class AnswerResult(ApiModel):
    """Graded feedback plus what the answer changed."""

    correct: bool
    score: float
    feedback: str
    misconception: str | None
    #: The reference answer, released only after the learner has answered.
    answer_key: str
    changes: list[MasteryChange]
    session: SessionRead
