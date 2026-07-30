"""Review-queue schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.schemas.common import ApiModel
from app.schemas.diagnostic import MasteryChange


class CardRead(ApiModel):
    """One concept's scheduling state."""

    node_id: str
    node_name: str
    tier: int
    state: str
    stability: float
    difficulty: float
    due_at: datetime | None
    last_review_at: datetime | None
    reps: int
    lapses: int
    #: Days overdue, negative when the card is not due yet.
    overdue_days: float
    #: Estimated probability the learner still has it, right now.
    retrievability: float
    mastery: float
    #: Concepts downstream of this one, which is half of the queue's priority.
    unblocks: int


class DueQueueRead(ApiModel):
    """What is worth retrieving today."""

    subject_id: str
    #: Cards due now, already ordered and capped.
    due: list[CardRead]
    #: How many were due but pushed past the daily cap.
    deferred: int
    daily_cap: int
    total_cards: int
    #: Cards not due yet, for a "coming up" view.
    upcoming: list[CardRead]


class ReviewItemRead(ApiModel):
    """A question drawn for one due concept."""

    id: str
    node_id: str
    node_name: str
    tier: int
    item_format: str
    difficulty: int
    stem: str
    choices: list[str]
    #: Remaining due cards including this one, so the client can show progress.
    remaining: int


class ReviewAnswer(ApiModel):
    """An answer submitted from the review queue."""

    item_id: str
    answer: str = Field(max_length=8000)


class ReviewResult(ApiModel):
    """Grading, mastery movement, and the new schedule."""

    correct: bool
    score: float
    grade: int
    feedback: str
    misconception: str | None
    answer_key: str
    changes: list[MasteryChange]
    card: CardRead
    #: Days until the next retrieval of this concept.
    interval_days: float
    #: Which scheduling path ran, in plain language.
    schedule_reason: str
    remaining: int
