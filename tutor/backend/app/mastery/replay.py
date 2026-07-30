"""Recomputing the whole posterior from the response log.

The incremental path -- update the answered node, propagate, persist -- is what
runs during a diagnostic. But it bakes the graph's shape into the result: a
propagated adjustment depends on the edges that existed when the answer was given.
When the graph changes, the estimate that follows from the evidence changes too.

Rather than approximate that, this replays every graded response through the new
graph in chronological order. The response log is small (hundreds of rows at most,
against a bounded graph), so an honest recomputation is affordable, and it means
"recompute the posterior across the affected subgraph" is a real operation rather
than a fudge factor.

Decay is applied once at the end, per node, from that node's last touch. Modelling
forgetting *between* study sessions inside the replay would compound decay against
estimates that were themselves mid-revision; the retention curve is about calendar
time since the last retrieval, which is exactly what the final pass computes.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime

from app.mastery.decay import decay_state, elapsed_days
from app.mastery.elo import update_mastery
from app.mastery.graph import ConceptGraph
from app.mastery.propagation import (
    apply_propagation,
    propagate_evidence,
    refresh_priors,
)
from app.mastery.reconcile import seed_mastery
from app.mastery.state import MasteryParams, MasteryState


@dataclass(frozen=True, slots=True)
class Observation:
    """One graded answer, as the replay sees it.

    :param node_id: The concept the item targeted.
    :param difficulty: Item difficulty, 1 through 5.
    :param score: Rubric score in [0, 1].
    :param at: When the answer was graded.
    """

    node_id: str
    difficulty: int
    score: float
    at: datetime


@dataclass(slots=True)
class ReplayResult:
    """The posterior implied by a response log against a particular graph.

    :param states: Mastery state per node id.
    :param last_touched: When each node last received evidence, direct or
        propagated. Absent for nodes the log never reached.
    :param applied: How many observations were replayed.
    :param skipped: How many were dropped because their node is no longer present.
    """

    states: dict[str, MasteryState] = field(default_factory=dict)
    last_touched: dict[str, datetime] = field(default_factory=dict)
    applied: int = 0
    skipped: int = 0


def initial_states(
    graph: ConceptGraph,
    params: MasteryParams,
    *,
    seeds: Mapping[str, MasteryState] | None = None,
) -> dict[str, MasteryState]:
    """Build starting states, seeding any node without one from its prerequisites.

    Walks in prerequisite order so a node's prerequisites always have a state by
    the time it is seeded from them.

    :param graph: The prerequisite graph.
    :param params: Model constants.
    :param seeds: Known states to keep as-is, keyed by node id.
    """
    known = dict(seeds or {})
    states: dict[str, MasteryState] = {}
    for node_id in graph.topological_order():
        existing = known.get(node_id)
        if existing is not None:
            states[node_id] = existing
            continue
        prereq_states = [states[p] for p in graph.prereqs(node_id) if p in states]
        states[node_id] = seed_mastery(prereq_states, params)
    return states


def replay(
    graph: ConceptGraph,
    observations: Iterable[Observation],
    *,
    params: MasteryParams,
    seeds: Mapping[str, MasteryState] | None = None,
    now: datetime | None = None,
) -> ReplayResult:
    """Recompute mastery for every node from a response log.

    :param graph: The graph to evaluate the log against.
    :param observations: Graded answers, in any order; replayed chronologically.
    :param params: Model constants.
    :param seeds: Starting states to use instead of prerequisite-derived seeds.
    :param now: If given, decay each node from its last touch to this instant.
    """
    result = ReplayResult(states=initial_states(graph, params, seeds=seeds))

    ordered = sorted(observations, key=lambda o: (o.at, o.node_id))
    for observation in ordered:
        state = result.states.get(observation.node_id)
        if state is None:
            result.skipped += 1
            continue

        update = update_mastery(
            state,
            difficulty=observation.difficulty,
            score=observation.score,
            params=params,
        )
        result.states[observation.node_id] = update.state
        result.last_touched[observation.node_id] = observation.at

        propagated = propagate_evidence(
            graph,
            node_id=observation.node_id,
            mastery_delta=update.mastery_delta,
            observed_mastery=update.state.mastery,
            params=params,
        )
        for node_id, new_state in apply_propagation(result.states, propagated).items():
            result.states[node_id] = new_state
            result.last_touched[node_id] = observation.at

        # The incremental path refreshes priors after every answer, so the replay
        # must too -- otherwise recomputing after a graph edit would shift every
        # estimate for a reason that has nothing to do with the edit.
        result.states.update(refresh_priors(graph, result.states, params=params))
        result.applied += 1

    if now is not None:
        for node_id, state in result.states.items():
            days = elapsed_days(result.last_touched.get(node_id), now)
            if days > 0:
                result.states[node_id] = decay_state(state, days=days, params=params)

    return result
