"""The review queue: retrieval practice for concepts already taught.

Three responsibilities, and the split matters.

**Ordering.** FSRS says *what is due*; it does not say what to do when more is due
than there is time for. The queue orders by how overdue a card is, weighted by how
much of the graph the concept unblocks, so a day that cannot clear the backlog
clears the most load-bearing part of it. Everything past the daily cap is deferred,
not dropped -- it stays due and leads tomorrow's queue.

**Item drawing.** A card is a concept, not a question. Each retrieval draws an item
for that concept at a difficulty chosen from the current estimate, which is why a
concept can be reviewed repeatedly without the learner memorising one question.

**Feeding both models.** A graded review updates mastery through the same
:class:`~app.services.mastery_service.MasteryUpdater` the diagnostic uses, and
updates the FSRS card. Those are different models answering different questions --
"how well is this known" and "when should it next be tested" -- and both need the
observation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import log1p

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db import new_id, utcnow
from app.llm.base import LLMAdapter
from app.mastery.decay import elapsed_days
from app.mastery.selection import select_difficulty
from app.mastery.state import MasteryParams
from app.models.assessment import ItemResponse
from app.models.enums import CardState, QueueKind
from app.models.scheduling import ReviewCard
from app.repositories.assessment import AssessmentRepository
from app.repositories.scheduling import SchedulingRepository
from app.scheduling.fsrs import Card, FsrsParams, retrievability, review
from app.scheduling.grading import Grade, grade_for
from app.schemas.diagnostic import MasteryChange
from app.schemas.review import CardRead, DueQueueRead, ReviewItemRead, ReviewResult
from app.services.graph_loader import GraphLoader, LoadedSubject
from app.services.item_service import ItemService
from app.services.mastery_service import MasteryUpdater

#: How many not-yet-due cards the queue reports as coming up.
UPCOMING_LIMIT = 10


class NothingDue(LookupError):
    """Raised when a review item is requested but the queue is empty."""


class NotAReviewItem(ValueError):
    """Raised when an answer names an item from a different subject."""


@dataclass(frozen=True, slots=True)
class Ranked:
    """A due card with the numbers the queue ordered it by.

    :param card: The card row.
    :param overdue: Days past due, at least zero.
    :param priority: Overdueness weighted by downstream reach.
    """

    card: ReviewCard
    overdue: float
    priority: float


class ReviewService:
    """Runs the spaced-retrieval queue."""

    def __init__(self, session: AsyncSession, adapter: LLMAdapter, settings: Settings) -> None:
        """
        :param session: The active database session.
        :param adapter: The LLM boundary.
        :param settings: Runtime configuration.
        """
        self._session = session
        self._settings = settings
        self._params = MasteryParams.from_settings(settings)
        self._fsrs = FsrsParams.from_settings(settings)
        self._loader = GraphLoader(session, self._params)
        self._repo = SchedulingRepository(session)
        self._assessment = AssessmentRepository(session)
        self._items = ItemService(session, adapter, settings)
        self._mastery = MasteryUpdater(self._params)

    # --- the queue -----------------------------------------------------------

    async def due_queue(self, subject_id: str, *, now: datetime | None = None) -> DueQueueRead:
        """What is worth retrieving, ordered and capped.

        :param subject_id: The subject to read.
        :param now: The instant to judge against; defaults to the current time.
        """
        moment = now or utcnow()
        loaded = await self._loader.load(subject_id)
        ranked = await self._ranked(loaded, moment)
        cap = loaded.subject.daily_review_cap or self._settings.daily_review_cap

        all_cards = await self._repo.cards_for_subject(subject_id)
        upcoming = sorted(
            (
                card
                for card in all_cards
                if card.due_at is not None and card.due_at > moment and card.node_id in loaded.graph
            ),
            key=lambda card: card.due_at or moment,
        )
        await self._session.commit()

        return DueQueueRead(
            subject_id=subject_id,
            due=[self._render_card(entry.card, loaded, moment) for entry in ranked[:cap]],
            deferred=max(0, len(ranked) - cap),
            daily_cap=cap,
            total_cards=len(all_cards),
            upcoming=[
                self._render_card(card, loaded, moment) for card in upcoming[:UPCOMING_LIMIT]
            ],
        )

    async def next_item(self, subject_id: str, *, now: datetime | None = None) -> ReviewItemRead:
        """Draw a question for the most pressing due concept.

        :param subject_id: The subject to review.
        :param now: The instant to judge against; defaults to the current time.
        :raises NothingDue: If nothing is due.
        """
        moment = now or utcnow()
        loaded = await self._loader.load(subject_id)
        ranked = await self._ranked(loaded, moment)
        if not ranked:
            raise NothingDue(subject_id)

        node_id = ranked[0].card.node_id
        state = loaded.states[node_id]
        counts = await self._assessment.response_counts(subject_id)
        item = await self._items.item_for(
            loaded,
            node_id,
            difficulty=select_difficulty(loaded.graph, node_id, state, self._params),
            observations=counts.get(node_id, 0),
        )
        await self._session.commit()

        return ReviewItemRead(
            id=item.id,
            node_id=node_id,
            node_name=loaded.graph.nodes[node_id].name,
            tier=loaded.graph.tier(node_id),
            item_format=item.item_format,
            difficulty=item.difficulty,
            stem=item.stem,
            choices=list(item.choices),
            remaining=len(ranked),
        )

    async def answer(
        self, subject_id: str, item_id: str, answer: str, *, now: datetime | None = None
    ) -> ReviewResult:
        """Grade a review answer, update mastery, and reschedule the concept.

        :param subject_id: The subject being reviewed.
        :param item_id: The item that was answered.
        :param answer: The learner's answer.
        :param now: The instant of the retrieval; defaults to the current time.
        :raises LookupError: If the item does not exist.
        :raises NotAReviewItem: If it belongs to another subject.
        """
        moment = now or utcnow()
        item = await self._assessment.get_item(item_id)
        if item is None:
            raise LookupError(item_id)
        if item.subject_id != subject_id:
            raise NotAReviewItem(item_id)

        loaded = await self._loader.load(subject_id)
        result = await self._items.grade(loaded, item, answer)
        applied = self._mastery.apply(
            loaded, node_id=item.node_id, difficulty=item.difficulty, score=result.score
        )
        grade = grade_for(result.score, self._settings)

        card = await self.ensure_card(loaded, item.node_id)
        scheduled = review(_to_card(card), grade, now=moment, params=self._fsrs)
        _apply_card(card, scheduled.card)

        self._assessment.add_response(
            ItemResponse(
                id=new_id(),
                subject_id=subject_id,
                item_id=item.id,
                node_id=item.node_id,
                session_id=None,
                source=QueueKind.REVIEW,
                raw_answer=answer,
                score=result.score,
                grade=int(grade),
                correct=result.correct,
                feedback=result.feedback,
                mastery_before=applied.direct_before.mastery,
                mastery_after=applied.direct_after.mastery,
                propagation={
                    change.node_id: change.mastery_after
                    for change in applied.changes
                    if change.propagated
                },
            )
        )
        await self._session.flush()
        remaining = len(await self._ranked(loaded, moment))
        await self._session.commit()

        return ReviewResult(
            correct=result.correct,
            score=result.score,
            grade=int(grade),
            feedback=result.feedback,
            misconception=result.misconception,
            answer_key=item.answer_key,
            changes=applied.changes,
            card=self._render_card(card, loaded, moment),
            interval_days=scheduled.interval_days,
            schedule_reason=scheduled.reason,
            remaining=remaining,
        )

    # --- card lifecycle ------------------------------------------------------

    async def ensure_card(self, loaded: LoadedSubject, node_id: str) -> ReviewCard:
        """Return the card for a concept, creating an unscheduled one if needed.

        A new card is created in the ``new`` state with no due date, so it does not
        appear in the review queue until something has actually been retrieved. New
        material belongs to the plan; the queue is for keeping what was taught.

        :param loaded: The subject the concept belongs to.
        :param node_id: The concept to schedule.
        """
        existing = await self._repo.card_for(node_id)
        if existing is not None:
            return existing
        card = self._repo.add_card(
            ReviewCard(
                id=new_id(),
                subject_id=loaded.subject.id,
                node_id=node_id,
                state=CardState.NEW,
            )
        )
        await self._session.flush()
        return card

    async def record_retrieval(
        self,
        loaded: LoadedSubject,
        node_id: str,
        grade: Grade,
        *,
        now: datetime | None = None,
    ) -> ReviewCard:
        """Fold a retrieval that happened elsewhere into the schedule.

        A unit's exit check is a retrieval like any other -- the first one, in fact,
        which is exactly the observation FSRS most needs. Without this the concept
        would sit in the ``new`` state after being taught and never become due.

        :param loaded: The subject the concept belongs to.
        :param node_id: The concept that was retrieved.
        :param grade: The grade it earned.
        :param now: The instant of the retrieval; defaults to the current time.
        """
        card = await self.ensure_card(loaded, node_id)
        scheduled = review(_to_card(card), grade, now=now or utcnow(), params=self._fsrs)
        _apply_card(card, scheduled.card)
        return card

    # --- ordering ------------------------------------------------------------

    async def _ranked(self, loaded: LoadedSubject, now: datetime) -> list[Ranked]:
        """Order the due cards by how much clearing them is worth.

        :param loaded: The subject being reviewed.
        :param now: The instant to judge against.
        """
        due = await self._repo.due_cards(loaded.subject.id, now=now)
        ranked: list[Ranked] = []
        for card in due:
            if card.node_id not in loaded.graph:
                continue
            overdue = elapsed_days(card.due_at, now)
            reach = loaded.graph.unblocking_power(card.node_id)
            # One full day overdue is the unit of urgency; reach breaks ties between
            # cards that came due together, which is most of them.
            ranked.append(
                Ranked(
                    card=card,
                    overdue=overdue,
                    priority=(1.0 + overdue) * (1.0 + log1p(reach)),
                )
            )
        ranked.sort(key=lambda entry: (-entry.priority, entry.card.node_id))
        return ranked

    def _render_card(self, card: ReviewCard, loaded: LoadedSubject, now: datetime) -> CardRead:
        """Shape one card for the API.

        :param card: The card row.
        :param loaded: The subject, for names and mastery.
        :param now: The instant to measure overdueness against.
        """
        meta = loaded.graph.nodes[card.node_id]
        state = loaded.states[card.node_id]
        since = elapsed_days(card.last_review_at, now)
        overdue = (now - card.due_at).total_seconds() / 86_400.0 if card.due_at is not None else 0.0
        return CardRead(
            node_id=card.node_id,
            node_name=meta.name,
            tier=meta.tier,
            state=card.state,
            stability=card.stability,
            difficulty=card.difficulty,
            due_at=card.due_at,
            last_review_at=card.last_review_at,
            reps=card.reps,
            lapses=card.lapses,
            overdue_days=overdue,
            retrievability=retrievability(since, card.stability),
            mastery=state.mastery,
            unblocks=loaded.graph.unblocking_power(card.node_id),
        )


def _to_card(row: ReviewCard) -> Card:
    """Convert a stored card into the pure value the scheduler works on.

    :param row: The card row.
    """
    return Card(
        state=CardState(row.state),
        stability=row.stability,
        difficulty=row.difficulty,
        due_at=row.due_at,
        last_review_at=row.last_review_at,
        reps=row.reps,
        lapses=row.lapses,
        step_index=row.step_index,
        scheduled_days=row.scheduled_days,
        acquisition_step=row.acquisition_step,
    )


def _apply_card(row: ReviewCard, card: Card) -> None:
    """Write a scheduled card back onto its row.

    :param row: The card row.
    :param card: The scheduler's result.
    """
    row.state = card.state
    row.stability = card.stability
    row.difficulty = card.difficulty
    row.due_at = card.due_at
    row.last_review_at = card.last_review_at
    row.reps = card.reps
    row.lapses = card.lapses
    row.step_index = card.step_index
    row.scheduled_days = card.scheduled_days
    row.acquisition_step = card.acquisition_step


__all__ = ["MasteryChange", "NotAReviewItem", "NothingDue", "ReviewService"]
