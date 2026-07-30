"""Tests for adaptive item selection and the stopping rule."""

from __future__ import annotations

import pytest

from app.mastery.graph import ConceptGraph, Edge, NodeMeta
from app.mastery.selection import (
    information_gain,
    proximity_to_threshold,
    rank_candidates,
    select_difficulty,
    select_next_node,
    should_stop,
)
from app.mastery.state import DEFAULT_PARAMS as P
from app.mastery.state import MasteryState
from tests.factories import chain, layered


def uniform(graph: ConceptGraph, mastery: float, confidence: float) -> dict[str, MasteryState]:
    """Give every node the same state.

    :param graph: The prerequisite graph.
    :param mastery: Mastery to assign.
    :param confidence: Confidence to assign.
    """
    return {
        node_id: MasteryState(mastery=mastery, confidence=confidence) for node_id in graph.node_ids
    }


def test_proximity_peaks_at_one_half() -> None:
    """An answer is most informative when the outcome is genuinely in doubt."""
    assert proximity_to_threshold(0.5, P) == pytest.approx(1.0)
    assert proximity_to_threshold(0.9, P) < proximity_to_threshold(0.7, P) < 1.0
    assert proximity_to_threshold(0.1, P) == pytest.approx(proximity_to_threshold(0.9, P))


def test_gain_prefers_the_less_certain_of_two_equal_nodes() -> None:
    """Asking about something already pinned down wastes a question."""
    graph = chain(2)
    states = {
        "c1": MasteryState(mastery=0.5, confidence=0.9),
        "c2": MasteryState(mastery=0.5, confidence=0.1),
    }
    assert select_next_node(graph, states, P) == "c2"


def test_gain_prefers_the_more_connected_of_two_equal_nodes() -> None:
    """Reach breaks the tie: an answer that informs more nodes is worth more."""
    graph = ConceptGraph(
        [
            NodeMeta("hub", "Hub", 1),
            NodeMeta("a", "A", 2),
            NodeMeta("b", "B", 2),
            NodeMeta("c", "C", 2),
            NodeMeta("isolated", "Isolated", 1),
        ],
        [Edge(prereq_id="hub", node_id=target) for target in ("a", "b", "c")],
    )
    states = uniform(graph, 0.5, 0.2)
    ranked = rank_candidates(graph, states, P)
    by_id = {candidate.node_id: candidate for candidate in ranked}
    assert by_id["hub"].gain > by_id["isolated"].gain
    assert by_id["hub"].reach > by_id["isolated"].reach == 0.0


def test_reach_splits_by_outcome_so_a_root_is_not_probed_first() -> None:
    """Success at a root informs nothing, and the rule has to know that.

    Weighting purely by unblocking power sends the selector to the foundations and
    keeps it there. Weighting by *expected* reach means a learner who looks strong
    gets probed higher up, where a correct answer confirms a whole chain.
    """
    graph = chain(5)
    confident = {node_id: MasteryState(mastery=0.85, confidence=0.1) for node_id in graph.node_ids}
    ranked = rank_candidates(graph, confident, P)
    assert graph.tier(ranked[0].node_id) > 1


def test_a_weak_learner_is_probed_low_where_failure_is_informative() -> None:
    """When failure is the likely outcome, the informative question is a foundation."""
    graph = chain(5)
    weak = {node_id: MasteryState(mastery=0.12, confidence=0.1) for node_id in graph.node_ids}
    ranked = rank_candidates(graph, weak, P)
    assert graph.tier(ranked[0].node_id) < 5


def test_excluded_nodes_are_never_selected() -> None:
    """A node already asked about is not asked again in the same session."""
    graph = chain(3)
    states = uniform(graph, 0.5, 0.1)
    chosen = select_next_node(graph, states, P, exclude=frozenset({"c1", "c2"}))
    assert chosen == "c3"


def test_selection_returns_none_when_everything_is_excluded() -> None:
    """An exhausted graph ends the session rather than raising."""
    graph = chain(2)
    states = uniform(graph, 0.5, 0.1)
    assert select_next_node(graph, states, P, exclude=frozenset(graph.node_ids)) is None


def test_selection_ignores_nodes_with_no_state() -> None:
    """A node the caller did not supply a state for is skipped."""
    graph = chain(3)
    assert select_next_node(graph, {"c2": MasteryState(0.5, 0.1)}, P) == "c2"


def test_ranking_is_deterministic() -> None:
    """Equal-gain nodes resolve the same way every time."""
    graph = layered(per_tier=6, tiers=3)
    states = uniform(graph, 0.5, 0.2)
    first = [candidate.node_id for candidate in rank_candidates(graph, states, P)]
    second = [candidate.node_id for candidate in rank_candidates(graph, states, P)]
    assert first == second


def test_difficulty_tracks_mastery_within_the_tier_band() -> None:
    """A stronger learner gets a harder item, bounded by the concept's own level."""
    graph = layered(per_tier=3, tiers=5)
    node = "t4n00"
    weak = select_difficulty(graph, node, MasteryState(0.1, 0.2), P)
    strong = select_difficulty(graph, node, MasteryState(0.95, 0.2), P)
    assert weak < strong
    assert 3 <= weak <= 4 and strong == 4


def test_difficulty_stays_within_one_to_five() -> None:
    """Every tier yields a legal difficulty."""
    graph = layered(per_tier=2, tiers=5)
    for node_id in graph.node_ids:
        for mastery in (0.0, 0.5, 1.0):
            difficulty = select_difficulty(graph, node_id, MasteryState(mastery, 0.2), P)
            assert 1 <= difficulty <= 5


def test_information_gain_reports_its_inputs() -> None:
    """The candidate record carries enough to debug a selection decision."""
    graph = chain(3)
    states = uniform(graph, 0.4, 0.3)
    candidate = information_gain(graph, "c2", states["c2"], P, states=states)
    assert candidate.node_id == "c2"
    assert candidate.uncertainty == pytest.approx(0.7)
    assert candidate.unblocks == 1
    assert candidate.gain > 0


def test_reach_discounts_nodes_that_are_already_certain() -> None:
    """Confirming something already settled is worth little."""
    graph = chain(3)
    uncertain = information_gain(
        graph, "c1", MasteryState(0.5, 0.2), P, states=uniform(graph, 0.5, 0.2)
    )
    settled = information_gain(
        graph,
        "c1",
        MasteryState(0.5, 0.2),
        P,
        states={
            "c1": MasteryState(0.5, 0.2),
            "c2": MasteryState(0.5, 0.99),
            "c3": MasteryState(0.5, 0.99),
        },
    )
    assert uncertain.reach > settled.reach


# --- stopping rule -------------------------------------------------------------


def test_stops_at_the_item_cap() -> None:
    """The hard cap always wins."""
    decision = should_stop({}, asked=30, min_items=8, max_items=30, confidence_target=0.9)
    assert decision.stop is True
    assert decision.reason == "max_items"


def test_stops_once_mean_confidence_reaches_the_target() -> None:
    """Enough is enough, well before the cap."""
    graph = chain(4)
    states = uniform(graph, 0.8, 0.7)
    decision = should_stop(states, asked=10, min_items=8, max_items=30, confidence_target=0.55)
    assert decision.stop is True
    assert decision.reason == "confidence_target"
    assert decision.mean_confidence == pytest.approx(0.7)


def test_does_not_stop_before_the_minimum_even_if_confidence_looks_high() -> None:
    """Propagation can lift mean confidence past a low target too early."""
    graph = chain(4)
    states = uniform(graph, 0.8, 0.9)
    decision = should_stop(states, asked=3, min_items=8, max_items=30, confidence_target=0.55)
    assert decision.stop is False
    assert decision.reason is None


def test_keeps_going_while_confidence_is_short_of_the_target() -> None:
    """An unfinished estimate keeps the session open."""
    graph = chain(4)
    states = uniform(graph, 0.5, 0.2)
    assert (
        should_stop(states, asked=12, min_items=8, max_items=30, confidence_target=0.55).stop
        is False
    )
