"""A synthetic learner, for testing the estimator against known ground truth.

The generative model is the same logistic curve the estimator assumes: a learner
with true mastery ``m`` passes an item of difficulty ``d`` with probability
``expected_score(m, d)``. That is deliberate. The point of the synthetic-learner
test is not to prove the model handles a mis-specified world; it is to prove that
when the world *does* look like the model, the estimator recovers the parameters --
which is the weakest claim an estimator has to satisfy, and the one that catches
sign errors, propagation-direction bugs, and selection starvation.
"""

from __future__ import annotations

import random
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from app.mastery.elo import expected_score, update_mastery
from app.mastery.graph import ConceptGraph
from app.mastery.propagation import apply_propagation, propagate_evidence, refresh_priors
from app.mastery.replay import Observation, initial_states
from app.mastery.selection import select_difficulty, select_next_node, should_stop
from app.mastery.state import MasteryParams, MasteryState


@dataclass(frozen=True, slots=True)
class Learner:
    """Ground truth: what the learner actually knows.

    :param true_mastery: True mastery per node id, in [0, 1].
    :param seed: Seed for the answer sampler, so runs are reproducible.
    """

    true_mastery: Mapping[str, float]
    seed: int = 20260730

    def answer(
        self, node_id: str, difficulty: int, rng: random.Random, params: MasteryParams
    ) -> float:
        """Sample a rubric score for one item.

        :param node_id: The concept being tested.
        :param difficulty: Item difficulty, 1 through 5.
        :param rng: The sampler, passed in so a whole run shares one stream.
        :param params: Model constants, for the logistic curve.
        """
        probability = expected_score(self.true_mastery[node_id], difficulty, params)
        return 1.0 if rng.random() < probability else 0.0


@dataclass(slots=True)
class DiagnosticRun:
    """What a simulated diagnostic did and concluded.

    :param states: Final estimated states per node id.
    :param observations: The graded answers, in order.
    :param asked: Node ids asked about, in order.
    :param stop_reason: Why the session ended.
    """

    states: dict[str, MasteryState] = field(default_factory=dict)
    observations: list[Observation] = field(default_factory=list)
    asked: list[str] = field(default_factory=list)
    stop_reason: str | None = None


def run_diagnostic(
    graph: ConceptGraph,
    learner: Learner,
    params: MasteryParams,
    *,
    max_items: int = 30,
    min_items: int = 8,
    confidence_target: float = 0.55,
    start: datetime | None = None,
) -> DiagnosticRun:
    """Simulate a full adaptive diagnostic against a synthetic learner.

    This is the same loop the diagnostic service runs, minus persistence and item
    generation, so a regression in selection or propagation shows up here first.

    :param graph: The prerequisite graph.
    :param learner: Ground truth to sample answers from.
    :param params: Model constants.
    :param max_items: Hard cap on questions.
    :param min_items: Minimum questions before the confidence rule can stop it.
    :param confidence_target: Mean confidence at which to stop.
    :param start: Timestamp of the first answer.
    """
    rng = random.Random(learner.seed)
    now = start or datetime(2026, 7, 30, 9, 0, tzinfo=UTC)
    run = DiagnosticRun(states=initial_states(graph, params))

    while True:
        decision = should_stop(
            run.states,
            asked=len(run.asked),
            min_items=min_items,
            max_items=max_items,
            confidence_target=confidence_target,
        )
        if decision.stop:
            run.stop_reason = decision.reason
            break

        node_id = select_next_node(graph, run.states, params, exclude=frozenset(run.asked))
        if node_id is None:
            run.stop_reason = "exhausted"
            break

        difficulty = select_difficulty(graph, node_id, run.states[node_id], params)
        score = learner.answer(node_id, difficulty, rng, params)
        at = now + timedelta(minutes=len(run.asked))

        update = update_mastery(
            run.states[node_id], difficulty=difficulty, score=score, params=params
        )
        run.states[node_id] = update.state
        propagated = propagate_evidence(
            graph,
            node_id=node_id,
            mastery_delta=update.mastery_delta,
            observed_mastery=update.state.mastery,
            params=params,
        )
        run.states.update(apply_propagation(run.states, propagated))
        run.states.update(refresh_priors(graph, run.states, params=params))

        run.asked.append(node_id)
        run.observations.append(
            Observation(node_id=node_id, difficulty=difficulty, score=score, at=at)
        )

    return run


def mean_absolute_error(estimated: Mapping[str, MasteryState], truth: Mapping[str, float]) -> float:
    """Mean absolute difference between estimate and ground truth.

    :param estimated: Estimated states per node id.
    :param truth: True mastery per node id.
    """
    if not truth:
        return 0.0
    return sum(abs(estimated[k].mastery - v) for k, v in truth.items()) / len(truth)


def tiered_learner(
    graph: ConceptGraph, by_tier: Mapping[int, float], *, jitter: float = 0.0, seed: int = 7
) -> Learner:
    """Build a learner whose true mastery depends on tier, plus optional noise.

    :param graph: The prerequisite graph.
    :param by_tier: True mastery per tier.
    :param jitter: Half-width of uniform noise added per node.
    :param seed: Seed for the noise.
    """
    rng = random.Random(seed)
    truth = {
        node_id: min(
            1.0,
            max(0.0, by_tier[meta.tier] + (rng.uniform(-jitter, jitter) if jitter else 0.0)),
        )
        for node_id, meta in graph.nodes.items()
    }
    return Learner(true_mastery=truth, seed=seed)
