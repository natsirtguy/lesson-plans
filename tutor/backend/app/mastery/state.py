"""The mastery state value type and the model's tunable constants."""

from __future__ import annotations

from dataclasses import dataclass, replace

from app.config import Settings


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    """Constrain a value to a closed interval.

    :param value: The value to constrain.
    :param low: Lower bound, inclusive.
    :param high: Upper bound, inclusive.
    """
    return max(low, min(high, value))


@dataclass(frozen=True, slots=True)
class MasteryState:
    """What the app believes about the learner's grasp of one concept.

    :param mastery: Point estimate in [0, 1]. 0.5 means "genuinely unsure".
    :param confidence: How much that estimate is worth, in [0, 1]. This is an
        inverse-variance stand-in: 0 means the estimate is a prior with no
        evidence behind it, 1 means further questions would tell us nothing.
    """

    mastery: float
    confidence: float

    def __post_init__(self) -> None:
        """Reject out-of-range values rather than silently clamping them."""
        if not 0.0 <= self.mastery <= 1.0:
            raise ValueError(f"mastery out of range: {self.mastery}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence out of range: {self.confidence}")

    @classmethod
    def clamped(cls, mastery: float, confidence: float) -> MasteryState:
        """Build a state from values that may fall outside [0, 1].

        :param mastery: Candidate mastery.
        :param confidence: Candidate confidence.
        """
        return cls(mastery=clamp(mastery), confidence=clamp(confidence))

    def with_mastery(self, mastery: float) -> MasteryState:
        """Return a copy with a different, clamped mastery.

        :param mastery: Candidate mastery.
        """
        return replace(self, mastery=clamp(mastery))

    @property
    def uncertainty(self) -> float:
        """How much room there is to learn something by asking about this."""
        return 1.0 - self.confidence


@dataclass(frozen=True, slots=True)
class MasteryParams:
    """Every constant the mastery model uses.

    Passed explicitly into each function rather than read from global config, so
    tests can vary one knob at a time and the functions stay pure.

    :param elo_base_step: Size of one mastery update at zero confidence. Large by
        Elo standards, because a diagnostic gets roughly one observation per node
        rather than hundreds: against an uninformative prior, the first answer
        should dominate the estimate, not nudge it.
    :param elo_logistic_scale: Steepness of the expected-score curve.
    :param confidence_damping: How much high confidence shrinks the step size.
        At 0.9, a fully confident node moves at a tenth of the base step. That is
        calibrated so one surprising answer barely dents a well-established
        estimate while a sustained run of them does move it, rather than leaving
        the estimate effectively unfalsifiable.
    :param confidence_gain: Fraction of remaining uncertainty a well-matched
        direct observation removes.
    :param match_floor: Share of the confidence gain awarded even when the item's
        difficulty is a poor match for the learner's level.
    :param propagation_decay: Per-hop attenuation of propagated evidence.
    :param propagation_max_hops: Hops beyond which propagation is dropped.
    :param propagation_confidence_share: How much of a direct observation's
        confidence gain a propagated one is worth.
    :param prereq_bound_slack: How much the "a concept cannot be much better known
        than its prerequisites" constraint loosens per hop. At 0.06, a prerequisite
        two hops below a concept answered at mastery 0.8 is inferred to be at least
        0.68, rather than exactly 0.8.
    :param default_seed_mastery: Mastery for a new node with no prerequisites.
    :param seeded_confidence: Confidence for any newly seeded node.
    :param seed_prereq_decay: Factor applied to the mean of a new node's
        prerequisites' mastery. Below 1 because depending on something you know
        is weaker evidence than having been tested.
    :param split_confidence_factor: Confidence multiplier for each child of a split.
    :param mastery_half_life_days: Days for mastery to fall halfway to its floor.
    :param retained_fraction: Share of mastery that never decays away, because
        having once understood something leaves a trace.
    :param confidence_half_life_days: Days for confidence to halve.
    :param mastery_threshold: Mastery at or above which a concept counts as known.
    :param proximity_width: Width of the informativeness peak around mastery 0.5.
    :param proximity_floor: Share of selection value a node keeps even when its
        mastery is far from 0.5.
    :param unblocking_weight: How strongly a node's downstream reach boosts its
        selection priority.
    :param posterior_slack: How far above what its prerequisites imply a node's
        mastery may sit before a structural change pulls it back down.
    :param prior_trust_confidence: Confidence at which a node's own estimate fully
        displaces the prior its prerequisites imply. Below it, the two are blended
        in proportion, so an untested concept tracks its prerequisites as they
        become known instead of sitting at its initial seed forever.
    :param prior_retention: How much of the gap between the no-information baseline
        and a concept's prerequisites' mean carries into its prior. Applied as a
        shrink toward the baseline rather than a multiplicative discount, so the
        prediction does not collapse to the baseline over a five-tier graph.
    :param tier_prior_strength: Pseudo-count controlling how fast demonstrated
        performance at a difficulty tier displaces the prerequisite-derived prior
        for untested concepts at that tier. At 3, three measured concepts in a tier
        give that tier's observed mean half the weight.
    """

    elo_base_step: float = 0.9
    elo_logistic_scale: float = 4.0
    confidence_damping: float = 0.9
    confidence_gain: float = 0.34
    match_floor: float = 0.4
    propagation_decay: float = 0.5
    propagation_max_hops: int = 4
    propagation_confidence_share: float = 0.5
    prereq_bound_slack: float = 0.06
    default_seed_mastery: float = 0.15
    seeded_confidence: float = 0.12
    seed_prereq_decay: float = 0.6
    split_confidence_factor: float = 0.5
    mastery_half_life_days: float = 60.0
    retained_fraction: float = 0.35
    confidence_half_life_days: float = 45.0
    mastery_threshold: float = 0.7
    proximity_width: float = 0.28
    proximity_floor: float = 0.25
    unblocking_weight: float = 0.45
    posterior_slack: float = 0.25
    prior_trust_confidence: float = 0.25
    prior_retention: float = 0.95
    tier_prior_strength: float = 3.0

    @classmethod
    def from_settings(cls, settings: Settings) -> MasteryParams:
        """Build params from application configuration.

        Only the knobs exposed in ``.env`` are overridden; the rest keep the
        defaults above.

        :param settings: Runtime configuration.
        """
        return cls(
            elo_base_step=settings.elo_base_step,
            elo_logistic_scale=settings.elo_logistic_scale,
            confidence_gain=settings.confidence_gain,
            propagation_decay=settings.propagation_decay,
            propagation_max_hops=settings.propagation_max_hops,
            default_seed_mastery=settings.default_seed_mastery,
            seeded_confidence=settings.seeded_confidence,
            split_confidence_factor=settings.split_confidence_factor,
            mastery_half_life_days=settings.mastery_half_life_days,
            confidence_half_life_days=settings.confidence_half_life_days,
            mastery_threshold=settings.mastery_threshold,
        )


DEFAULT_PARAMS = MasteryParams()
