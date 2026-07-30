"""The direct update rule: one graded answer against one concept.

An Elo-style rule rather than full Bayesian inference. The learner's mastery and
the item's difficulty live on the same 0-1 scale; the expected score is a logistic
function of their difference; the update moves mastery by the surprise, scaled by
how much the observation is worth.

Two scalings matter, and both come from the same idea -- move further when you
learn more:

* **Up with difficulty.** A hard item discriminates more than an easy one, so
  getting it right (or wrong) shifts the estimate further.
* **Down with confidence.** A well-established estimate should not swing on one
  answer. The damping is deliberately partial, so a confidently-held estimate
  still moves under repeated contrary evidence rather than becoming unfalsifiable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.mastery.state import MasteryParams, MasteryState, clamp

#: Difficulty tiers run 1-5; this maps them onto the mastery scale so that a
#: tier-1 item is expected to be passed by someone at mastery 0.1 and a tier-5
#: item by someone at 0.9.
_DIFFICULTY_SCALE = 5.0


def difficulty_to_ability(difficulty: int) -> float:
    """Convert a 1-5 item difficulty to the mastery level that matches it.

    :param difficulty: Item difficulty, 1 through 5.
    """
    return clamp((difficulty - 0.5) / _DIFFICULTY_SCALE)


def expected_score(mastery: float, difficulty: int, params: MasteryParams) -> float:
    """Probability the learner answers an item of this difficulty correctly.

    :param mastery: Current mastery estimate.
    :param difficulty: Item difficulty, 1 through 5.
    :param params: Model constants.
    """
    gap = mastery - difficulty_to_ability(difficulty)
    return 1.0 / (1.0 + math.exp(-params.elo_logistic_scale * gap))


def difficulty_match(mastery: float, difficulty: int, params: MasteryParams) -> float:
    """How informative an item of this difficulty is for this learner, in [0, 1].

    Peaks where the item sits at the learner's current level, because that is
    where the outcome is least predictable.

    :param mastery: Current mastery estimate.
    :param difficulty: Item difficulty, 1 through 5.
    :param params: Model constants.
    """
    gap = (mastery - difficulty_to_ability(difficulty)) / params.proximity_width
    return math.exp(-(gap**2))


@dataclass(frozen=True, slots=True)
class Update:
    """The result of one direct observation.

    :param state: The new mastery state.
    :param mastery_delta: Signed change in mastery, which is what propagates.
    :param surprise: Observed score minus expected score.
    """

    state: MasteryState
    mastery_delta: float
    surprise: float


def update_mastery(
    state: MasteryState,
    *,
    difficulty: int,
    score: float,
    params: MasteryParams,
) -> Update:
    """Apply one graded answer to one concept's state.

    :param state: The concept's state before this answer.
    :param difficulty: Item difficulty, 1 through 5.
    :param score: Rubric score in [0, 1].
    :param params: Model constants.
    """
    score = clamp(score)
    expected = expected_score(state.mastery, difficulty, params)
    surprise = score - expected

    difficulty_weight = 0.4 + 0.6 * (clamp(difficulty, 1, 5) - 1) / 4
    confidence_factor = 1.0 - params.confidence_damping * state.confidence
    step = params.elo_base_step * difficulty_weight * confidence_factor

    new_mastery = clamp(state.mastery + step * surprise)

    match = difficulty_match(state.mastery, difficulty, params)
    gain = params.confidence_gain * (params.match_floor + (1 - params.match_floor) * match)
    new_confidence = clamp(state.confidence + (1.0 - state.confidence) * gain)

    return Update(
        state=MasteryState(mastery=new_mastery, confidence=new_confidence),
        mastery_delta=new_mastery - state.mastery,
        surprise=surprise,
    )
