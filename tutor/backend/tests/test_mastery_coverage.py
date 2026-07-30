"""Tests for coverage reporting, rankings, and blocking analysis."""

from __future__ import annotations

import pytest

from app.mastery.coverage import (
    UNASSESSED_CONFIDENCE,
    build_report,
    coverage,
    locked_nodes,
    next_tier_blockers,
    node_scores,
    priority,
    ready_to_learn,
    strengths,
    weaknesses,
)
from app.mastery.state import DEFAULT_PARAMS as P
from app.mastery.state import MasteryState
from tests.factories import chain, layered


def test_coverage_is_mean_mastery_not_a_completion_count() -> None:
    """The headline number reflects estimated mastery over the whole graph."""
    states = {
        "a": MasteryState(mastery=1.0, confidence=0.9),
        "b": MasteryState(mastery=0.0, confidence=0.9),
    }
    assert coverage(states) == pytest.approx(0.5)


def test_coverage_of_an_empty_graph_is_zero() -> None:
    """No concepts means nothing covered, not a division by zero."""
    assert coverage({}) == 0.0


def test_report_counts_mastered_and_unassessed_separately() -> None:
    """Knowing something and having measured it are different facts."""
    graph = chain(3)
    states = {
        "c1": MasteryState(mastery=0.9, confidence=0.8),
        "c2": MasteryState(mastery=0.9, confidence=0.05),
        "c3": MasteryState(mastery=0.2, confidence=0.8),
    }
    report = build_report(graph, states, P)
    assert report.total_nodes == 3
    assert report.mastered_nodes == 2
    assert report.unassessed_nodes == 1
    assert report.coverage == pytest.approx((0.9 + 0.9 + 0.2) / 3)


def test_report_breaks_down_by_tier_in_ascending_order() -> None:
    """The per-tier view is what locates a learner's frontier."""
    graph = layered(per_tier=2, tiers=3)
    states = {
        node_id: MasteryState(mastery=1.0 - 0.3 * (meta.tier - 1), confidence=0.6)
        for node_id, meta in graph.nodes.items()
    }
    report = build_report(graph, states, P)
    assert [summary.tier for summary in report.tiers] == [1, 2, 3]
    assert report.tiers[0].mean_mastery > report.tiers[2].mean_mastery
    assert all(summary.count == 2 for summary in report.tiers)


def test_report_of_an_empty_graph_is_all_zeros() -> None:
    """A subject whose graph has not been generated yet reports nothing."""
    report = build_report(chain(2), {}, P)
    assert report.total_nodes == 0
    assert report.coverage == 0.0
    assert report.tiers == ()


def test_node_scores_skip_nodes_without_state() -> None:
    """A node with no mastery row is omitted rather than defaulted."""
    assert [score.node_id for score in node_scores(chain(3), {"c2": MasteryState(0.5, 0.5)})] == [
        "c2"
    ]


def test_strengths_require_real_evidence() -> None:
    """A seeded node sitting high on inference alone is not a reportable strength."""
    graph = chain(2)
    states = {
        "c1": MasteryState(mastery=0.99, confidence=UNASSESSED_CONFIDENCE - 0.01),
        "c2": MasteryState(mastery=0.75, confidence=0.8),
    }
    assert [score.node_id for score in strengths(graph, states)] == ["c2"]


def test_weaknesses_rank_by_weakness_times_unblocking_power() -> None:
    """A weak concept that unlocks a branch outranks an equally weak dead end."""
    graph = layered(per_tier=3, tiers=3)
    states = {node_id: MasteryState(mastery=0.2, confidence=0.6) for node_id in graph.node_ids}
    ranked = weaknesses(graph, states, P, limit=3)
    assert all(graph.tier(score.node_id) == 1 for score in ranked)


def test_weaknesses_exclude_mastered_concepts() -> None:
    """There is no point attacking what the learner already holds."""
    graph = chain(3)
    states = {
        "c1": MasteryState(mastery=0.95, confidence=0.8),
        "c2": MasteryState(mastery=0.3, confidence=0.8),
        "c3": MasteryState(mastery=0.4, confidence=0.8),
    }
    assert "c1" not in {score.node_id for score in weaknesses(graph, states, P)}


def test_priority_rises_with_weakness_and_with_reach() -> None:
    """Both halves of the ranking rule pull in the expected direction."""
    graph = layered(per_tier=2, tiers=3)
    scores = {
        score.node_id: score
        for score in node_scores(graph, {n: MasteryState(0.3, 0.5) for n in graph.node_ids})
    }
    assert priority(scores["t1n00"]) > priority(scores["t3n00"])


def test_ready_to_learn_requires_every_prerequisite_mastered() -> None:
    """A unit may only be taught once everything it rests on is in place."""
    graph = chain(3)
    states = {
        "c1": MasteryState(mastery=0.9, confidence=0.8),
        "c2": MasteryState(mastery=0.3, confidence=0.8),
        "c3": MasteryState(mastery=0.1, confidence=0.8),
    }
    assert ready_to_learn(graph, states, P) == ("c2",)


def test_ready_to_learn_includes_unmastered_roots() -> None:
    """A foundational concept with no prerequisites is always available."""
    graph = chain(2)
    states = {
        "c1": MasteryState(mastery=0.2, confidence=0.3),
        "c2": MasteryState(mastery=0.2, confidence=0.3),
    }
    assert "c1" in ready_to_learn(graph, states, P)


def test_locked_nodes_are_those_with_no_mastered_prerequisite() -> None:
    """A concept nothing reaches cannot be taught or usefully tested."""
    graph = chain(3)
    states = {
        "c1": MasteryState(mastery=0.2, confidence=0.5),
        "c2": MasteryState(mastery=0.2, confidence=0.5),
        "c3": MasteryState(mastery=0.2, confidence=0.5),
    }
    locked = locked_nodes(graph, states, P)
    assert "c1" not in locked, "a root is never locked"
    assert set(locked) == {"c2", "c3"}


def test_blocking_report_names_the_next_tier_and_its_blockers() -> None:
    """The report has to say what to do next, not just where the learner stands."""
    graph = layered(per_tier=2, tiers=3)
    # Tier 1 averages above the threshold, so tier 2 is the target -- but one
    # tier-1 concept is still short, and that is what holds tier 2 back.
    states = {node_id: MasteryState(mastery=0.3, confidence=0.8) for node_id in graph.node_ids}
    states["t1n00"] = MasteryState(mastery=0.95, confidence=0.8)
    states["t1n01"] = MasteryState(mastery=0.65, confidence=0.8)
    report = next_tier_blockers(graph, states, P)
    assert report.target_tier == 2
    assert "t1n01" in {score.node_id for score in report.blockers}
    assert {score.node_id for score in report.blocked} == {"t2n00", "t2n01"}


def test_blocking_report_is_actionable_even_at_the_root_tier() -> None:
    """A root tier has no prerequisites, so the tier's own weak concepts are named.

    Otherwise the report would say "tier 1 is the problem" and list nothing to do
    about it.
    """
    graph = layered(per_tier=2, tiers=3)
    states = {node_id: MasteryState(mastery=0.2, confidence=0.8) for node_id in graph.node_ids}
    report = next_tier_blockers(graph, states, P)
    assert report.target_tier == 1
    assert {score.node_id for score in report.blockers} == {"t1n00", "t1n01"}


def test_blocking_report_is_empty_when_every_tier_is_clear() -> None:
    """Nothing to report is a valid answer."""
    graph = layered(per_tier=2, tiers=3)
    states = {node_id: MasteryState(mastery=0.95, confidence=0.9) for node_id in graph.node_ids}
    report = next_tier_blockers(graph, states, P)
    assert report.target_tier is None
    assert report.blocked == () and report.blockers == ()
