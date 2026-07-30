"""Choosing the next diagnostic item.

The goal is to estimate mastery over the whole graph in ~20-30 questions for a
100-node graph, which means each question has to earn its place. Three factors,
multiplied:

* **Proximity to 0.5.** An answer is only informative if the outcome is in doubt.
  A node we already believe is mastered, or clearly is not, teaches us little.
* **Remaining uncertainty.** Asking again about a node we have already pinned down
  wastes a question.
* **Expected reach.** How many *other* nodes the answer will inform.

That third term deserves an explanation, because the obvious version of it is
wrong. Weighting by unblocking power alone -- how many concepts depend on this one --
sends the selector straight to the foundations and keeps it there, sweeping tier 1
before it ever looks higher. The reason is the propagation asymmetry: success flows
*up* to prerequisites, and a root has none, so a correct answer at the very bottom
of the graph informs nothing at all.

The reach term is therefore the *expected* number of nodes informed, which splits
by outcome::

    reach = P(correct) x (weighted prerequisites) + P(wrong) x (weighted dependents)

Unblocking power is the failure half of that expectation rather than the whole
thing. Each side is discounted by ``propagation_decay`` per hop, so it measures
information actually delivered rather than nodes merely connected.

This is what makes the search bisect the DAG. For a learner the model currently
expects to fail, the informative question is low, where failure cascades downward;
as their estimates rise, the expected-correct branch dominates and the selector
climbs, because success high up confirms everything beneath it. Getting a question
right moves the frontier up, getting one wrong moves it down.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from app.mastery.elo import difficulty_match, expected_score
from app.mastery.graph import ConceptGraph
from app.mastery.state import MasteryParams, MasteryState


@dataclass(frozen=True, slots=True)
class Candidate:
    """A node scored for selection.

    :param node_id: The concept's id.
    :param gain: Expected information gain, arbitrary units, higher is better.
    :param difficulty: The item difficulty this node would be tested at.
    :param proximity: How close mastery is to 0.5, in [0, 1].
    :param uncertainty: One minus confidence.
    :param unblocks: Number of concepts downstream of this one.
    :param reach: Expected number of other nodes the answer will inform,
        discounted by distance.
    """

    node_id: str
    gain: float
    difficulty: int
    proximity: float
    uncertainty: float
    unblocks: int
    reach: float


def proximity_to_threshold(mastery: float, params: MasteryParams) -> float:
    """How undecided the model is about this concept, in [0, 1].

    :param mastery: Current mastery estimate.
    :param params: Model constants.
    """
    gap = (mastery - 0.5) / params.proximity_width
    return math.exp(-(gap**2))


def discounted_reach(
    hops: Mapping[str, int],
    states: Mapping[str, MasteryState],
    params: MasteryParams,
) -> float:
    """Sum the per-hop propagation weight over a set of reachable nodes.

    Nodes beyond the propagation hop limit contribute nothing, because evidence
    would not reach them. Each remaining node contributes in proportion to how
    uncertain it still is, so confirming something already pinned down counts for
    little -- but not for nothing, which matters: a node asked once at an easy
    difficulty is not settled, and refusing to count it is what makes an adaptive
    test unwilling to probe upward at all.

    :param hops: Node ids mapped to their hop distance.
    :param states: Current states, keyed by node id.
    :param params: Model constants.
    """
    total = 0.0
    for node_id, distance in hops.items():
        if distance > params.propagation_max_hops:
            continue
        state = states.get(node_id)
        residual = state.uncertainty if state is not None else 1.0
        total += (params.propagation_decay**distance) * residual
    return total


def information_gain(
    graph: ConceptGraph,
    node_id: str,
    state: MasteryState,
    params: MasteryParams,
    *,
    states: Mapping[str, MasteryState] | None = None,
) -> Candidate:
    """Score one node as a candidate for the next question.

    :param graph: The prerequisite graph.
    :param node_id: The concept to score.
    :param state: The concept's current state.
    :param params: Model constants.
    :param states: All current states, used to discount reach by how uncertain the
        reachable nodes still are. Defaults to treating them as fully uncertain.
    """
    resolved = states if states is not None else {}
    difficulty = select_difficulty(graph, node_id, state, params)
    probability_correct = expected_score(state.mastery, difficulty, params)

    # Success informs prerequisites, failure informs dependents; weight each side
    # by how likely that outcome is.
    reach = probability_correct * discounted_reach(graph.ancestors(node_id), resolved, params) + (
        1.0 - probability_correct
    ) * discounted_reach(graph.descendants(node_id), resolved, params)

    proximity = proximity_to_threshold(state.mastery, params)
    # A floor on the proximity term keeps a high-uncertainty node reachable even
    # when its prior sits far from 0.5, which matters on the first few questions
    # when every estimate is a seed.
    proximity_term = params.proximity_floor + (1 - params.proximity_floor) * proximity
    reach_term = 1.0 + params.unblocking_weight * math.log1p(reach)
    gain = proximity_term * state.uncertainty * reach_term
    return Candidate(
        node_id=node_id,
        gain=gain,
        difficulty=difficulty,
        proximity=proximity,
        uncertainty=state.uncertainty,
        unblocks=graph.unblocking_power(node_id),
        reach=reach,
    )


def rank_candidates(
    graph: ConceptGraph,
    states: Mapping[str, MasteryState],
    params: MasteryParams,
    *,
    exclude: frozenset[str] = frozenset(),
) -> list[Candidate]:
    """Score every eligible node, best first.

    :param graph: The prerequisite graph.
    :param states: Current states, keyed by node id.
    :param params: Model constants.
    :param exclude: Nodes already asked about in this session.
    """
    candidates = [
        information_gain(graph, node_id, states[node_id], params, states=states)
        for node_id in graph.node_ids
        if node_id not in exclude and node_id in states
    ]
    # Deterministic tie-break: lower tier first, so a tie resolves toward
    # foundations, then by id.
    candidates.sort(key=lambda c: (-c.gain, graph.tier(c.node_id), c.node_id))
    return candidates


def select_next_node(
    graph: ConceptGraph,
    states: Mapping[str, MasteryState],
    params: MasteryParams,
    *,
    exclude: frozenset[str] = frozenset(),
) -> str | None:
    """Pick the node the next question should target.

    :param graph: The prerequisite graph.
    :param states: Current states, keyed by node id.
    :param params: Model constants.
    :param exclude: Nodes already asked about in this session.
    """
    ranked = rank_candidates(graph, states, params, exclude=exclude)
    return ranked[0].node_id if ranked else None


def select_difficulty(
    graph: ConceptGraph,
    node_id: str,
    state: MasteryState,
    params: MasteryParams,
) -> int:
    """Choose the item difficulty that discriminates best for this learner.

    Bounded below by the node's tier minus one and above by its tier, because an
    item far from the concept's inherent level stops being an item about that
    concept.

    :param graph: The prerequisite graph.
    :param node_id: The concept being tested.
    :param state: The concept's current state.
    :param params: Model constants.
    """
    tier = graph.tier(node_id)
    best = max(
        range(1, 6),
        key=lambda d: (difficulty_match(state.mastery, d, params), -abs(d - tier)),
    )
    return max(1, min(5, min(max(best, tier - 1), tier)))


@dataclass(frozen=True, slots=True)
class StopDecision:
    """Whether the diagnostic should end, and why.

    :param stop: Whether to stop.
    :param reason: Machine-readable reason, or None while continuing.
    :param mean_confidence: Mean confidence across the graph at this point.
    """

    stop: bool
    reason: str | None
    mean_confidence: float


def should_stop(
    states: Mapping[str, MasteryState],
    *,
    asked: int,
    min_items: int,
    max_items: int,
    confidence_target: float,
) -> StopDecision:
    """Decide whether the diagnostic has learned enough.

    Stops on whichever comes first: mean confidence crossing the target, or the
    item cap. The minimum floor exists because mean confidence over a large graph
    can drift past a low target on propagation alone, before the learner has
    answered enough to justify it.

    :param states: Current states, keyed by node id.
    :param asked: Items answered so far.
    :param min_items: Never stop before this many, unless nothing is left to ask.
    :param max_items: Always stop at this many.
    :param confidence_target: Mean-confidence threshold to stop at.
    """
    mean_confidence = (
        sum(state.confidence for state in states.values()) / len(states) if states else 1.0
    )
    if asked >= max_items:
        return StopDecision(True, "max_items", mean_confidence)
    if asked >= min_items and mean_confidence >= confidence_target:
        return StopDecision(True, "confidence_target", mean_confidence)
    return StopDecision(False, None, mean_confidence)
