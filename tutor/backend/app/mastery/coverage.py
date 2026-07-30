"""Reporting: coverage, strengths, gaps, and what is blocking progress.

Coverage is the mean mastery over every live concept, not the fraction of lessons
completed. Those two numbers diverge badly and only one of them is honest: a
learner who has read every unit and retained a third of it has not covered the
subject, and a learner who already knew half the graph before starting has covered
more than their completion count suggests.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from math import log1p

from app.mastery.graph import ConceptGraph
from app.mastery.state import MasteryParams, MasteryState


@dataclass(frozen=True, slots=True)
class NodeScore:
    """One concept's standing, for ranked lists.

    :param node_id: The concept's id.
    :param name: Concept name.
    :param tier: Difficulty tier.
    :param mastery: Current mastery estimate.
    :param confidence: Current confidence.
    :param unblocks: Concepts downstream of this one.
    """

    node_id: str
    name: str
    tier: int
    mastery: float
    confidence: float
    unblocks: int


@dataclass(frozen=True, slots=True)
class TierSummary:
    """Aggregate standing within one difficulty tier.

    :param tier: The tier.
    :param count: Concepts in it.
    :param mean_mastery: Mean mastery across them.
    :param mean_confidence: Mean confidence across them.
    :param mastered: How many are at or above the mastery threshold.
    """

    tier: int
    count: int
    mean_mastery: float
    mean_confidence: float
    mastered: int


@dataclass(frozen=True, slots=True)
class BlockingReport:
    """What stands between the learner and the next tier they have not cleared.

    :param target_tier: The lowest tier not yet at the mastery threshold, or None
        when every tier is clear.
    :param blocked: Concepts in that tier held back by unmastered prerequisites.
    :param blockers: What the plan should attack, worst first. Normally the
        unmastered prerequisites of the blocked concepts; when the target tier has
        no unmastered prerequisites -- the root tier, most obviously -- the tier's
        own weak concepts, so the report always names something to do.
    """

    target_tier: int | None
    blocked: tuple[NodeScore, ...]
    blockers: tuple[NodeScore, ...]


@dataclass(frozen=True, slots=True)
class CoverageReport:
    """The headline numbers for a subject.

    :param coverage: Mean mastery across all live concepts, in [0, 1].
    :param mean_confidence: Mean confidence across all live concepts.
    :param total_nodes: Live concept count.
    :param mastered_nodes: How many are at or above the mastery threshold.
    :param unassessed_nodes: How many have effectively no evidence behind them.
    :param tiers: Per-tier breakdown, ascending.
    """

    coverage: float
    mean_confidence: float
    total_nodes: int
    mastered_nodes: int
    unassessed_nodes: int
    tiers: tuple[TierSummary, ...]


#: Confidence below which a node's estimate is treated as a prior, not a finding.
UNASSESSED_CONFIDENCE = 0.2


def coverage(states: Mapping[str, MasteryState]) -> float:
    """Mean mastery across the graph.

    :param states: Current states, keyed by node id.
    """
    if not states:
        return 0.0
    return sum(state.mastery for state in states.values()) / len(states)


def node_scores(graph: ConceptGraph, states: Mapping[str, MasteryState]) -> list[NodeScore]:
    """Build a score record for every node present in both graph and states.

    :param graph: The prerequisite graph.
    :param states: Current states, keyed by node id.
    """
    scores: list[NodeScore] = []
    for node_id, meta in graph.nodes.items():
        state = states.get(node_id)
        if state is None:
            continue
        scores.append(
            NodeScore(
                node_id=node_id,
                name=meta.name,
                tier=meta.tier,
                mastery=state.mastery,
                confidence=state.confidence,
                unblocks=graph.unblocking_power(node_id),
            )
        )
    return scores


def build_report(
    graph: ConceptGraph, states: Mapping[str, MasteryState], params: MasteryParams
) -> CoverageReport:
    """Compute the headline coverage numbers.

    :param graph: The prerequisite graph.
    :param states: Current states, keyed by node id.
    :param params: Model constants.
    """
    scores = node_scores(graph, states)
    if not scores:
        return CoverageReport(
            coverage=0.0,
            mean_confidence=0.0,
            total_nodes=0,
            mastered_nodes=0,
            unassessed_nodes=0,
            tiers=(),
        )

    tiers: list[TierSummary] = []
    for tier in sorted({score.tier for score in scores}):
        members = [score for score in scores if score.tier == tier]
        tiers.append(
            TierSummary(
                tier=tier,
                count=len(members),
                mean_mastery=sum(m.mastery for m in members) / len(members),
                mean_confidence=sum(m.confidence for m in members) / len(members),
                mastered=sum(1 for m in members if m.mastery >= params.mastery_threshold),
            )
        )

    return CoverageReport(
        coverage=sum(s.mastery for s in scores) / len(scores),
        mean_confidence=sum(s.confidence for s in scores) / len(scores),
        total_nodes=len(scores),
        mastered_nodes=sum(1 for s in scores if s.mastery >= params.mastery_threshold),
        unassessed_nodes=sum(1 for s in scores if s.confidence < UNASSESSED_CONFIDENCE),
        tiers=tuple(tiers),
    )


def strengths(
    graph: ConceptGraph,
    states: Mapping[str, MasteryState],
    *,
    limit: int = 8,
) -> tuple[NodeScore, ...]:
    """Concepts the learner holds most solidly.

    Requires real evidence: a seeded node sitting high on inference alone is not a
    strength worth reporting back.

    :param graph: The prerequisite graph.
    :param states: Current states, keyed by node id.
    :param limit: Maximum entries to return.
    """
    scored = [
        score for score in node_scores(graph, states) if score.confidence >= UNASSESSED_CONFIDENCE
    ]
    scored.sort(key=lambda s: (-s.mastery, -s.confidence, s.name))
    return tuple(scored[:limit])


def weaknesses(
    graph: ConceptGraph,
    states: Mapping[str, MasteryState],
    params: MasteryParams,
    *,
    limit: int = 8,
) -> tuple[NodeScore, ...]:
    """Concepts most worth attacking next.

    Ranked by weakness times downstream reach, so a weak concept that unlocks a
    branch outranks an equally weak dead end.

    :param graph: The prerequisite graph.
    :param states: Current states, keyed by node id.
    :param params: Model constants.
    :param limit: Maximum entries to return.
    """
    scored = [
        score for score in node_scores(graph, states) if score.mastery < params.mastery_threshold
    ]
    scored.sort(key=lambda s: (-priority(s), s.tier, s.name))
    return tuple(scored[:limit])


def priority(score: NodeScore) -> float:
    """How much attention a concept deserves: weakness times unblocking power.

    :param score: The concept's standing.
    """
    return (1.0 - score.mastery) * (1.0 + log1p(score.unblocks))


def ready_to_learn(
    graph: ConceptGraph, states: Mapping[str, MasteryState], params: MasteryParams
) -> tuple[str, ...]:
    """Concepts whose every prerequisite is mastered but which are not.

    These are the only concepts a plan may legitimately teach next.

    :param graph: The prerequisite graph.
    :param states: Current states, keyed by node id.
    :param params: Model constants.
    """
    ready: list[str] = []
    for node_id in graph.node_ids:
        state = states.get(node_id)
        if state is None or state.mastery >= params.mastery_threshold:
            continue
        prereqs = graph.prereqs(node_id)
        if all(
            (states[p].mastery if p in states else 0.0) >= params.mastery_threshold for p in prereqs
        ):
            ready.append(node_id)
    return tuple(ready)


def locked_nodes(
    graph: ConceptGraph, states: Mapping[str, MasteryState], params: MasteryParams
) -> tuple[str, ...]:
    """Concepts no path currently reaches, because every prerequisite is unmastered.

    A node in this state cannot be taught and cannot be usefully tested, which
    often means the graph has given it prerequisites it does not really have.
    Surfaced as a proactive suggestion rather than silently left unreachable.

    :param graph: The prerequisite graph.
    :param states: Current states, keyed by node id.
    :param params: Model constants.
    """
    locked: list[str] = []
    for node_id in graph.node_ids:
        prereqs = graph.prereqs(node_id)
        if not prereqs:
            continue
        if all(
            (states[p].mastery if p in states else 0.0) < params.mastery_threshold for p in prereqs
        ):
            locked.append(node_id)
    return tuple(locked)


def next_tier_blockers(
    graph: ConceptGraph,
    states: Mapping[str, MasteryState],
    params: MasteryParams,
    *,
    limit: int = 6,
) -> BlockingReport:
    """Identify the next tier to clear and what is holding it up.

    :param graph: The prerequisite graph.
    :param states: Current states, keyed by node id.
    :param params: Model constants.
    :param limit: Maximum blockers to return.
    """
    report = build_report(graph, states, params)
    target: int | None = None
    for summary in report.tiers:
        if summary.mean_mastery < params.mastery_threshold:
            target = summary.tier
            break
    if target is None:
        return BlockingReport(target_tier=None, blocked=(), blockers=())

    by_id = {score.node_id: score for score in node_scores(graph, states)}
    blocked: list[NodeScore] = []
    blockers: dict[str, NodeScore] = {}
    for node_id, score in by_id.items():
        if score.tier != target or score.mastery >= params.mastery_threshold:
            continue
        unmastered = [
            by_id[p]
            for p in graph.prereqs(node_id)
            if p in by_id and by_id[p].mastery < params.mastery_threshold
        ]
        if unmastered:
            blocked.append(score)
            for prereq in unmastered:
                blockers[prereq.node_id] = prereq

    if not blockers:
        # Nothing upstream is holding this tier back -- either it is the root tier,
        # or its prerequisites are all mastered. Either way the report still has to
        # be actionable, so the tier's own weak concepts are the thing to attack.
        blockers = {
            score.node_id: score
            for score in by_id.values()
            if score.tier == target and score.mastery < params.mastery_threshold
        }

    blocked.sort(key=lambda s: (-priority(s), s.name))
    ranked_blockers = sorted(blockers.values(), key=lambda s: (-priority(s), s.name))
    return BlockingReport(
        target_tier=target,
        blocked=tuple(blocked[:limit]),
        blockers=tuple(ranked_blockers[:limit]),
    )
