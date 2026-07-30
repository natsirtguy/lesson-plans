"""Spreading evidence through prerequisite edges.

One answer tells you about more than one concept, and the inference is asymmetric:

* **Success flows up.** Answering a tier-4 question correctly is evidence that you
  hold its prerequisites, because you could not have got there otherwise. So a
  positive update raises the posterior on the node's *ancestors*.
* **Failure flows down.** Failing a tier-1 question is evidence against everything
  built on it, because those concepts assume it. So a negative update lowers the
  posterior on the node's *descendants*.

The reverse directions are deliberately not propagated. Knowing a prerequisite
says little about the concept built on it -- that is exactly the gap teaching
fills -- and failing an advanced concept says little about foundations you may
hold perfectly well.

Each hop attenuates by ``propagation_decay``, and propagated evidence is worth
less confidence than a direct observation, because it is inference rather than
measurement.

**Why a bound and not just a delta.** Nudging a neighbour's estimate by a decayed
share of the delta is too weak to carry the inference. Answering a tier-4 item
correctly does not merely make its prerequisites slightly more likely: it means
the learner *did the thing that requires them*, so their mastery is at least
roughly what the answered concept now shows. So each propagated effect carries a
bound as well as a delta -- a floor on prerequisites after success, a ceiling on
dependents after failure -- expressing the constraint that a concept cannot be
much better known than what it is built on. The bound loosens by
``prereq_bound_slack`` per hop, so the inference weakens with distance rather than
asserting equality across the whole graph.

Without this, an estimate cannot travel: a learner who demonstrates tier-4
competence still reads as a beginner at tier 1, because thirty questions cannot
directly touch a hundred nodes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.mastery.graph import ConceptGraph
from app.mastery.state import MasteryParams, MasteryState, clamp


@dataclass(frozen=True, slots=True)
class Propagated:
    """One node's share of an observation that targeted a different node.

    :param mastery_delta: Signed mastery adjustment for this node.
    :param bound: The level this node's mastery is constrained to, given what the
        observed node demonstrated.
    :param bound_is_floor: True when ``bound`` is a lower limit (success flowing up
        to prerequisites), False when it is an upper limit (failure flowing down to
        dependents).
    :param confidence_gain: Fraction of remaining uncertainty this removes.
    :param hops: Prerequisite hops between the observed node and this one.
    """

    mastery_delta: float
    bound: float
    bound_is_floor: bool
    confidence_gain: float
    hops: int


def propagate_evidence(
    graph: ConceptGraph,
    *,
    node_id: str,
    mastery_delta: float,
    observed_mastery: float,
    params: MasteryParams,
) -> dict[str, Propagated]:
    """Work out what one node's update implies about its neighbourhood.

    Returns adjustments for other nodes only; the observed node is already
    handled by :func:`~app.mastery.elo.update_mastery`.

    :param graph: The prerequisite graph.
    :param node_id: The node that was directly observed.
    :param mastery_delta: The signed mastery change applied to that node.
    :param observed_mastery: That node's mastery *after* the update, which is what
        the bound on its neighbours is derived from.
    :param params: Model constants.
    """
    if mastery_delta == 0.0 or node_id not in graph:
        return {}

    success = mastery_delta > 0
    targets: Mapping[str, int] = graph.ancestors(node_id) if success else graph.descendants(node_id)

    result: dict[str, Propagated] = {}
    for target_id, hops in targets.items():
        if hops > params.propagation_max_hops:
            continue
        factor = params.propagation_decay**hops
        slack = params.prereq_bound_slack * hops
        # Success: a prerequisite is at least as well held as what it supports.
        # Failure: a dependent is at most as well held as what it rests on.
        bound = observed_mastery - slack if success else observed_mastery + slack
        result[target_id] = Propagated(
            mastery_delta=mastery_delta * factor,
            bound=clamp(bound),
            bound_is_floor=success,
            confidence_gain=(params.confidence_gain * params.propagation_confidence_share * factor),
            hops=hops,
        )
    return result


def apply_propagation(
    states: Mapping[str, MasteryState],
    propagated: Mapping[str, Propagated],
) -> dict[str, MasteryState]:
    """Apply propagated adjustments to the states they affect.

    Returns only the nodes that changed, so callers can persist a minimal update.

    :param states: Current states, keyed by node id.
    :param propagated: Adjustments from :func:`propagate_evidence`.
    """
    changed: dict[str, MasteryState] = {}
    for node_id, effect in propagated.items():
        current = states.get(node_id)
        if current is None:
            continue
        mastery = clamp(current.mastery + effect.mastery_delta)
        if effect.bound_is_floor:
            mastery = max(mastery, effect.bound)
        else:
            mastery = min(mastery, effect.bound)
        confidence = clamp(current.confidence + (1.0 - current.confidence) * effect.confidence_gain)
        if mastery != current.mastery or confidence != current.confidence:
            changed[node_id] = MasteryState(mastery=mastery, confidence=confidence)
    return changed


def prior_from_prereqs(prereq_states: Sequence[MasteryState], params: MasteryParams) -> float:
    """The mastery an untested concept is expected to have, given its prerequisites.

    Shrinks the prerequisites' mean toward the no-information baseline rather than
    scaling it down multiplicatively. The difference matters over a five-tier
    graph: a multiplicative factor compounds once per tier, so a learner confirmed
    at 0.9 in the foundations is predicted at 0.9 x 0.6^4 = 0.12 at the top --
    indistinguishable from a beginner, and enough to stop the diagnostic ever
    offering them a hard question. Shrinking toward the baseline instead keeps the
    prediction ordered by what the learner has actually shown.

    :param prereq_states: States of the concept's prerequisites.
    :param params: Model constants.
    """
    if not prereq_states:
        return params.default_seed_mastery
    total_confidence = sum(state.confidence for state in prereq_states)
    if total_confidence > 0:
        mean = sum(s.mastery * s.confidence for s in prereq_states) / total_confidence
    else:
        mean = sum(s.mastery for s in prereq_states) / len(prereq_states)
    baseline = params.default_seed_mastery
    return clamp(baseline + (mean - baseline) * params.prior_retention)


def observed_tier_levels(
    graph: ConceptGraph,
    states: Mapping[str, MasteryState],
    params: MasteryParams,
) -> dict[int, tuple[float, int]]:
    """Mean mastery per tier over concepts with real evidence behind them.

    How a learner has actually fared on concepts of a given difficulty is evidence
    about the concepts of that difficulty nobody has asked them about. Without it,
    an untested concept is predicted purely from its prerequisites, which is why a
    learner who has just failed eight tier-4 questions still reads as competent on
    the other twelve.

    :param graph: The prerequisite graph.
    :param states: Current states, keyed by node id.
    :param params: Model constants.
    """
    buckets: dict[int, list[float]] = {}
    for node_id, state in states.items():
        if node_id not in graph or state.confidence < params.prior_trust_confidence:
            continue
        buckets.setdefault(graph.tier(node_id), []).append(state.mastery)
    return {tier: (sum(values) / len(values), len(values)) for tier, values in buckets.items()}


def refresh_priors(
    graph: ConceptGraph,
    states: Mapping[str, MasteryState],
    *,
    params: MasteryParams,
) -> dict[str, MasteryState]:
    """Re-derive the prior of weakly-evidenced nodes from their prerequisites.

    This is distinct from evidence propagation above, and the distinction matters.
    Propagation moves the *posterior* on the strength of an observation, and only
    in the two directions the inference supports. This moves the *prior* of a node
    nobody has tested, because the prior was always "whatever its prerequisites
    imply" -- and once those prerequisites are known, the implication changes.

    Without it, an untested tier-4 concept sits at the seed it was given before
    anything was known about the subject, no matter how much the learner turns out
    to know about tier 3. The selector then reads it as an unresolved question
    forever, and coverage understates what the learner holds.

    The prior itself comes from two sources: what the concept's prerequisites imply,
    and how the learner has fared on other concepts at the same difficulty tier.
    The tier term gains weight as evidence at that tier accumulates, so early on the
    prediction follows the prerequisite structure and later it follows demonstrated
    performance.

    Each node's own estimate and that prior are then blended in proportion to its
    confidence, so a well-tested node ignores the prior entirely and an untouched one
    follows it closely. Confidence is never raised here: this adds no evidence, it
    only stops the prior going stale.

    :param graph: The prerequisite graph.
    :param states: Current states, keyed by node id.
    :param params: Model constants.
    """
    working = dict(states)
    tier_levels = observed_tier_levels(graph, states, params)
    changed: dict[str, MasteryState] = {}
    for node_id in graph.topological_order():
        current = working.get(node_id)
        if current is None or current.confidence >= params.prior_trust_confidence:
            continue
        prereq_states = [working[p] for p in graph.prereqs(node_id) if p in working]
        if not prereq_states:
            continue
        prior = prior_from_prereqs(prereq_states, params)

        observed = tier_levels.get(graph.tier(node_id))
        if observed is not None:
            tier_mean, sample_size = observed
            weight = sample_size / (sample_size + params.tier_prior_strength)
            prior = clamp(weight * tier_mean + (1.0 - weight) * prior)

        trust = current.confidence / params.prior_trust_confidence
        blended = clamp(trust * current.mastery + (1.0 - trust) * prior)
        if abs(blended - current.mastery) < 1e-9:
            continue
        updated = MasteryState(mastery=blended, confidence=current.confidence)
        working[node_id] = updated
        changed[node_id] = updated
    return changed


def smooth_posterior(
    graph: ConceptGraph,
    states: Mapping[str, MasteryState],
    *,
    affected: frozenset[str],
    params: MasteryParams,
) -> dict[str, MasteryState]:
    """Pull mastery back in line with prerequisites after the graph changes.

    Adding or retargeting an edge can leave a node claiming more mastery than its
    new prerequisites support -- the estimate was justified under the old
    structure, and nothing about the learner changed, but the claim no longer
    follows. This walks the affected subgraph in prerequisite order and caps each
    node at its prerequisites' mean plus ``posterior_slack``.

    Note that this is a consistency pass, not a re-derivation. When the full
    response history is available, :func:`~app.mastery.replay.replay` recomputes
    the posterior properly; this exists for the cheap path and for nodes whose
    evidence is entirely propagated.

    :param graph: The graph *after* the change.
    :param states: Current states, keyed by node id.
    :param affected: Nodes whose incoming edges changed.
    :param params: Model constants.
    """
    if not affected:
        return {}

    # Everything downstream of a changed node is also affected: a cap applied to
    # one node can cascade to what depends on it.
    scope: set[str] = set()
    for node_id in affected:
        if node_id in graph:
            scope.add(node_id)
            scope.update(graph.descendants(node_id))

    working = dict(states)
    changed: dict[str, MasteryState] = {}
    for node_id in graph.topological_order():
        if node_id not in scope:
            continue
        current = working.get(node_id)
        prereqs = graph.prereqs(node_id)
        if current is None or not prereqs:
            continue
        prereq_states = [working[p] for p in prereqs if p in working]
        if not prereq_states:
            continue
        implied = sum(s.mastery for s in prereq_states) / len(prereq_states)
        ceiling = clamp(implied + params.posterior_slack)
        if current.mastery <= ceiling:
            continue
        # The structural change invalidated part of what supported this estimate,
        # so confidence drops alongside the point estimate.
        updated = MasteryState(
            mastery=ceiling,
            confidence=clamp(current.confidence * (1.0 - params.propagation_decay * 0.5)),
        )
        working[node_id] = updated
        changed[node_id] = updated
    return changed
