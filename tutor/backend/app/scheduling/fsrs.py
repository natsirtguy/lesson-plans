"""FSRS-4.5: when a concept is next worth retrieving.

Layer 1 of the two scheduling layers. This decides *when an item is due* and
nothing else -- it has no opinion about when the learner sits down, how long they
have, or what else is competing for the slot. That is the session planner's job.

**Cards are keyed on concepts, not items.** Generated items are disposable; pinning
scheduling state to one would reset the interval every time content is regenerated.
Each retrieval draws a fresh item for the concept.

**Grades come from the rubric.** :func:`app.scheduling.grading.grade_for` maps the
grader's score onto again/hard/good/easy. Self-report is not consulted anywhere,
which removes the usual bias: people rate a barely-recalled answer "good" far more
often than a grader does.

**A lapse never resets memory to zero.** FSRS's post-lapse stability formula keeps
a fraction of what was there -- forgetting something once does not mean never having
learned it -- and the card enters short relearning steps rather than going back to
the start of the ladder. :func:`review` guarantees stability stays strictly
positive, and there is a test that a relapsed concept ends up scheduled further out
than a brand-new one.

Everything here is pure: values in, values out, no clock read that is not passed as
an argument.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from app.config import Settings
from app.mastery.decay import elapsed_days
from app.models.enums import CardState
from app.scheduling.grading import Grade

#: Published FSRS-4.5 default weights. Not tuned for this app -- tuning needs
#: thousands of reviews from one learner, which is exactly what a personal app does
#: not have on day one. They are configuration so they can be replaced later.
DEFAULT_WEIGHTS: tuple[float, ...] = (
    0.4872,
    1.4003,
    3.7145,
    13.8206,
    5.1618,
    1.2298,
    0.8975,
    0.0310,
    1.6474,
    0.1367,
    1.0461,
    2.1072,
    0.0793,
    0.3246,
    1.5870,
    0.2272,
    2.8755,
)

#: Exponent of the FSRS forgetting curve.
DECAY = -0.5
#: Scale factor that makes R(t=S) equal 0.9 exactly.
FACTOR = 19.0 / 81.0

#: Stability can never fall below this, which is what "never reset to zero" means
#: concretely: roughly an hour of memory, not none.
MIN_STABILITY = 0.05


@dataclass(frozen=True, slots=True)
class FsrsParams:
    """Everything the scheduler is allowed to vary.

    :param weights: The seventeen FSRS-4.5 weights.
    :param request_retention: Probability of recall the intervals aim for. Lower
        means longer intervals and more forgetting; this is the difficulty knob.
    :param maximum_interval_days: Ceiling on a scheduled interval.
    :param minimum_interval_days: Floor on a scheduled interval once a card is in
        review, so a barely-passed card still gets a day rather than reappearing
        within the same sitting.
    :param relearning_steps_minutes: Ladder of short delays a lapsed card climbs
        before it returns to review scheduling.
    :param acquisition_ladder_days: Fixed expanding schedule a freshly taught
        concept follows before FSRS intervals take over.
    :param use_acquisition_ladder: Whether that ladder applies at all.
    """

    weights: tuple[float, ...] = DEFAULT_WEIGHTS
    request_retention: float = 0.85
    maximum_interval_days: float = 36500.0
    minimum_interval_days: float = 1.0
    relearning_steps_minutes: tuple[float, ...] = (10.0, 1440.0)
    acquisition_ladder_days: tuple[float, ...] = (1.0, 3.0, 7.0, 21.0)
    use_acquisition_ladder: bool = True

    @classmethod
    def from_settings(cls, settings: Settings) -> FsrsParams:
        """Build scheduler parameters from application configuration.

        :param settings: Runtime configuration.
        """
        return cls(
            request_retention=settings.target_retention,
            maximum_interval_days=settings.fsrs_maximum_interval_days,
            relearning_steps_minutes=tuple(settings.fsrs_relearning_minutes),
            use_acquisition_ladder=settings.use_acquisition_ladder,
        )


@dataclass(frozen=True, slots=True)
class Card:
    """One concept's scheduling state.

    :param state: Where the card is in its lifecycle.
    :param stability: Memory stability in days -- the interval at which recall
        probability is exactly ``0.9``.
    :param difficulty: FSRS's own 1-10 difficulty, unrelated to the 1-5 item tier.
    :param due_at: When the concept is next worth retrieving.
    :param last_review_at: When it was last retrieved.
    :param reps: Successful and unsuccessful retrievals so far.
    :param lapses: How many times it has been forgotten.
    :param step_index: Position in the relearning ladder.
    :param scheduled_days: The interval last scheduled.
    :param acquisition_step: Position in the expanding acquisition ladder.
    """

    state: CardState = CardState.NEW
    stability: float = 0.0
    difficulty: float = 5.0
    due_at: datetime | None = None
    last_review_at: datetime | None = None
    reps: int = 0
    lapses: int = 0
    step_index: int = 0
    scheduled_days: float = 0.0
    acquisition_step: int = 0


@dataclass(frozen=True, slots=True)
class Review:
    """The outcome of scheduling one retrieval.

    :param card: The card's new state.
    :param interval_days: How far out the next retrieval was placed.
    :param retrievability: Estimated recall probability at the moment of review,
        before it was updated. ``None`` for a card with no history.
    :param reason: Which scheduling path ran, for display and for debugging.
    """

    card: Card
    interval_days: float
    retrievability: float | None
    reason: str


def retrievability(days: float, stability: float) -> float:
    """Probability of recalling a concept after some days without retrieval.

    :param days: Days since the last retrieval.
    :param stability: Memory stability in days.
    """
    if stability <= 0:
        return 0.0
    return float((1.0 + FACTOR * max(0.0, days) / stability) ** DECAY)


def interval_for(stability: float, params: FsrsParams) -> float:
    """The interval at which recall probability falls to the target retention.

    :param stability: Memory stability in days.
    :param params: Scheduler parameters.
    """
    retention = min(max(params.request_retention, 0.5), 0.99)
    raw = float((stability / FACTOR) * (retention ** (1.0 / DECAY) - 1.0))
    return min(max(raw, params.minimum_interval_days), params.maximum_interval_days)


def initial_stability(grade: Grade, params: FsrsParams) -> float:
    """Stability implied by the very first retrieval of a concept.

    :param grade: The retrieval grade.
    :param params: Scheduler parameters.
    """
    return max(MIN_STABILITY, float(params.weights[int(grade) - 1]))


def initial_difficulty(grade: Grade, params: FsrsParams) -> float:
    """Difficulty implied by the very first retrieval of a concept.

    :param grade: The retrieval grade.
    :param params: Scheduler parameters.
    """
    return _clamp_difficulty(params.weights[4] - (int(grade) - 3) * params.weights[5])


def next_difficulty(difficulty: float, grade: Grade, params: FsrsParams) -> float:
    """Update difficulty, with mean reversion toward the "easy" anchor.

    Without the reversion term difficulty ratchets in one direction and never comes
    back, so a concept the learner struggled with once stays permanently expensive.

    :param difficulty: Current difficulty.
    :param grade: The retrieval grade.
    :param params: Scheduler parameters.
    """
    moved = difficulty - params.weights[6] * (int(grade) - 3)
    anchor = params.weights[4] - (int(Grade.EASY) - 3) * params.weights[5]
    reverted = params.weights[7] * anchor + (1.0 - params.weights[7]) * moved
    return _clamp_difficulty(reverted)


def next_stability(
    stability: float, difficulty: float, recall: float, grade: Grade, params: FsrsParams
) -> float:
    """Stability after a successful retrieval.

    The gain is largest when recall probability was *low* -- retrieving something
    you had nearly forgotten is what actually strengthens memory, and retrieving
    something you knew perfectly well teaches the scheduler almost nothing.

    :param stability: Current stability.
    :param difficulty: Current difficulty.
    :param recall: Estimated recall probability at the moment of review.
    :param grade: The retrieval grade.
    :param params: Scheduler parameters.
    """
    w = params.weights
    hard_penalty = w[15] if grade == Grade.HARD else 1.0
    easy_bonus = w[16] if grade == Grade.EASY else 1.0
    growth = float(
        math.exp(w[8])
        * (11.0 - difficulty)
        * (stability ** -w[9])
        * (math.exp(w[10] * (1.0 - recall)) - 1.0)
        * hard_penalty
        * easy_bonus
    )
    return max(MIN_STABILITY, stability * (1.0 + growth))


def post_lapse_stability(
    stability: float, difficulty: float, recall: float, params: FsrsParams
) -> float:
    """Stability after forgetting.

    Lower than before, never zero, and never higher than it was: a lapse is
    evidence the interval was too long, not evidence of nothing.

    :param stability: Stability before the lapse.
    :param difficulty: Current difficulty.
    :param recall: Estimated recall probability at the moment of review.
    :param params: Scheduler parameters.
    """
    w = params.weights
    lapsed = float(
        w[11]
        * (difficulty ** -w[12])
        * ((stability + 1.0) ** w[13] - 1.0)
        * math.exp(w[14] * (1.0 - recall))
    )
    return max(MIN_STABILITY, min(lapsed, stability))


def review(card: Card, grade: Grade, *, now: datetime, params: FsrsParams) -> Review:
    """Schedule the next retrieval of one concept.

    :param card: The card's current state.
    :param grade: The grade this retrieval earned.
    :param now: The instant of the retrieval.
    :param params: Scheduler parameters.
    """
    if card.state == CardState.NEW:
        return _first_review(card, grade, now=now, params=params)
    if card.state in {CardState.LEARNING, CardState.RELEARNING}:
        return _relearning_review(card, grade, now=now, params=params)
    return _scheduled_review(card, grade, now=now, params=params)


def _first_review(card: Card, grade: Grade, *, now: datetime, params: FsrsParams) -> Review:
    """Handle a concept's very first retrieval.

    :param card: The card's current state.
    :param grade: The grade this retrieval earned.
    :param now: The instant of the retrieval.
    :param params: Scheduler parameters.
    """
    stability = initial_stability(grade, params)
    difficulty = initial_difficulty(grade, params)
    if grade == Grade.AGAIN:
        return _enter_relearning(
            replace(card, stability=stability, difficulty=difficulty, lapses=card.lapses + 1),
            now=now,
            params=params,
            step=0,
            reason="first retrieval failed, entering relearning",
        )

    interval, step, reason = _acquisition_interval(card, stability, params)
    return Review(
        card=replace(
            card,
            state=CardState.REVIEW,
            stability=stability,
            difficulty=difficulty,
            due_at=now + timedelta(days=interval),
            last_review_at=now,
            reps=card.reps + 1,
            step_index=0,
            scheduled_days=interval,
            acquisition_step=step,
        ),
        interval_days=interval,
        retrievability=None,
        reason=reason,
    )


def _scheduled_review(card: Card, grade: Grade, *, now: datetime, params: FsrsParams) -> Review:
    """Handle a retrieval of a card that was already in review.

    :param card: The card's current state.
    :param grade: The grade this retrieval earned.
    :param now: The instant of the retrieval.
    :param params: Scheduler parameters.
    """
    recall = retrievability(elapsed_days(card.last_review_at, now), card.stability)
    difficulty = next_difficulty(card.difficulty, grade, params)

    if grade == Grade.AGAIN:
        lapsed = post_lapse_stability(card.stability, card.difficulty, recall, params)
        return _enter_relearning(
            replace(
                card,
                stability=lapsed,
                difficulty=difficulty,
                lapses=card.lapses + 1,
                # The expanding ladder is for acquisition. Once a concept has been
                # forgotten it is no longer being acquired, so FSRS takes the wheel.
                acquisition_step=len(params.acquisition_ladder_days),
            ),
            now=now,
            params=params,
            step=0,
            reason="lapsed, entering relearning",
            recall=recall,
        )

    stability = next_stability(card.stability, difficulty, recall, grade, params)
    interval, step, reason = _acquisition_interval(card, stability, params)
    return Review(
        card=replace(
            card,
            state=CardState.REVIEW,
            stability=stability,
            difficulty=difficulty,
            due_at=now + timedelta(days=interval),
            last_review_at=now,
            reps=card.reps + 1,
            scheduled_days=interval,
            acquisition_step=step,
        ),
        interval_days=interval,
        retrievability=recall,
        reason=reason,
    )


def _relearning_review(card: Card, grade: Grade, *, now: datetime, params: FsrsParams) -> Review:
    """Handle a retrieval of a card working its way back after a lapse.

    :param card: The card's current state.
    :param grade: The grade this retrieval earned.
    :param now: The instant of the retrieval.
    :param params: Scheduler parameters.
    """
    if grade == Grade.AGAIN:
        return _enter_relearning(
            card,
            now=now,
            params=params,
            step=min(card.step_index + 1, len(params.relearning_steps_minutes) - 1),
            reason="still not recalled, repeating the relearning step",
        )

    # Stability was already reduced when the lapse happened; graduating uses that
    # reduced value rather than recomputing from scratch, which is what keeps a
    # relapsed concept scheduled sooner than a well-held one but later than a new one.
    interval = interval_for(card.stability, params)
    return Review(
        card=replace(
            card,
            state=CardState.REVIEW,
            due_at=now + timedelta(days=interval),
            last_review_at=now,
            reps=card.reps + 1,
            step_index=0,
            scheduled_days=interval,
        ),
        interval_days=interval,
        retrievability=None,
        reason="relearned, back on the review schedule",
    )


def _enter_relearning(
    card: Card,
    *,
    now: datetime,
    params: FsrsParams,
    step: int,
    reason: str,
    recall: float | None = None,
) -> Review:
    """Put a card on a short relearning delay.

    :param card: The card, with stability and lapse count already updated.
    :param now: The instant of the retrieval.
    :param params: Scheduler parameters.
    :param step: Which relearning step to use.
    :param reason: What to report about this transition.
    :param recall: Recall probability at review, when there was one.
    """
    minutes = params.relearning_steps_minutes[min(step, len(params.relearning_steps_minutes) - 1)]
    interval = minutes / 1440.0
    return Review(
        card=replace(
            card,
            state=CardState.RELEARNING,
            due_at=now + timedelta(minutes=minutes),
            last_review_at=now,
            reps=card.reps + 1,
            step_index=step,
            scheduled_days=interval,
        ),
        interval_days=interval,
        retrievability=recall,
        reason=reason,
    )


def _acquisition_interval(
    card: Card, stability: float, params: FsrsParams
) -> tuple[float, int, str]:
    """Choose between the fixed acquisition ladder and the FSRS interval.

    A freshly taught concept follows a fixed expanding schedule -- 1, 3, 7, 21 days
    -- and only afterwards is handed to FSRS. The ladder wins outright while it
    lasts, including when it is *shorter* than what FSRS would ask for, which at the
    default 85% retention it usually is: FSRS's first "good" interval works out
    around six days.

    That override is deliberate. FSRS's initial stability weights are fitted on Anki
    review logs, where a "good" on a new card means it graduated through several
    same-session learning steps. Here the first grade comes from a single exit check
    taken minutes after first reading about the concept, which is much weaker
    evidence for the same number. Six days after one exposure is optimistic; a day
    is not. Once the ladder is exhausted there are four real observations behind the
    estimate and FSRS does better than any fixed schedule.

    :param card: The card being scheduled.
    :param stability: The card's new stability.
    :param params: Scheduler parameters.
    """
    fsrs_interval = interval_for(stability, params)
    ladder = params.acquisition_ladder_days
    if not params.use_acquisition_ladder or card.acquisition_step >= len(ladder):
        return fsrs_interval, card.acquisition_step, "fsrs interval"

    step = card.acquisition_step
    return ladder[step], step + 1, f"acquisition ladder step {step + 1} of {len(ladder)}"


def _clamp_difficulty(value: float) -> float:
    """Hold difficulty inside FSRS's 1-10 range.

    :param value: The candidate difficulty.
    """
    return max(1.0, min(10.0, value))
