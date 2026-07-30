"""Tests for the pure plan sequencer.

The load-bearing test in this file is
:func:`test_no_unit_precedes_a_prerequisite_it_needs`, which is the acceptance
criterion stated directly: every unit's prerequisites are either already mastered
or scheduled earlier. It is asserted over every unit of every plan the other tests
generate, because the property is meant to be structural rather than usually true.
"""

from __future__ import annotations

import pytest

from app.graphs.sequencer import PlanSequence, sequence_plan
from app.mastery.graph import ConceptGraph, Edge, GraphCycleError, NodeMeta
from app.mastery.state import DEFAULT_PARAMS as P
from app.mastery.state import MasteryState
from tests.factories import chain, diamond, layered


def uniform(
    graph: ConceptGraph, mastery: float, confidence: float = 0.5
) -> dict[str, MasteryState]:
    """Give every concept the same state.

    :param graph: The graph to cover.
    :param mastery: Mastery for every node.
    :param confidence: Confidence for every node.
    """
    return {node_id: MasteryState(mastery, confidence) for node_id in graph.node_ids}


def assert_prerequisites_respected(graph: ConceptGraph, sequenced: PlanSequence) -> None:
    """Assert no unit depends on something not yet taught or already known.

    :param graph: The graph the plan was built from.
    :param sequenced: The sequencing result to check.
    """
    units = sequenced.units
    skipped = set(sequenced.skipped_mastered)
    position = {unit.node_id: unit.seq for unit in units}
    for unit in units:
        for prereq in graph.prereqs(unit.node_id):
            assert prereq in skipped or position.get(prereq, len(units)) < unit.seq, (
                f"{graph.nodes[unit.node_id].name} is scheduled before its "
                f"prerequisite {graph.nodes[prereq].name}"
            )


# --- the ordering invariant ----------------------------------------------------


@pytest.mark.parametrize(
    "graph", [chain(6), diamond(), layered(per_tier=8, tiers=5)], ids=["chain", "diamond", "wide"]
)
def test_no_unit_precedes_a_prerequisite_it_needs(graph: ConceptGraph) -> None:
    """The acceptance criterion, over three graph shapes."""
    sequenced = sequence_plan(graph, uniform(graph, 0.1), P)
    assert len(sequenced.units) == len(graph)
    assert_prerequisites_respected(graph, sequenced)


def test_the_invariant_survives_partial_mastery() -> None:
    """Mastered prerequisites satisfy the constraint without being scheduled."""
    graph = layered(per_tier=6, tiers=4)
    states = {
        node_id: MasteryState(0.9 if graph.tier(node_id) <= 2 else 0.2, 0.6)
        for node_id in graph.node_ids
    }
    sequenced = sequence_plan(graph, states, P)

    assert_prerequisites_respected(graph, sequenced)
    assert len(sequenced.skipped_mastered) == 12
    assert all(graph.tier(unit.node_id) >= 3 for unit in sequenced.units)


def test_a_fully_mastered_subject_produces_an_empty_plan() -> None:
    """There is nothing to do, and the plan says so rather than inventing work."""
    graph = chain(5)
    sequenced = sequence_plan(graph, uniform(graph, 0.95), P)
    assert sequenced.units == ()
    assert len(sequenced.skipped_mastered) == 5


def test_a_cyclic_graph_is_refused_rather_than_looped_over() -> None:
    """Sequencing a cyclic graph raises instead of spinning."""
    nodes = [NodeMeta(node_id=f"n{i}", name=f"N{i}", tier=2) for i in range(3)]
    edges = [
        Edge(prereq_id="n0", node_id="n1"),
        Edge(prereq_id="n1", node_id="n2"),
        Edge(prereq_id="n2", node_id="n0"),
    ]
    cyclic = ConceptGraph(nodes, edges)
    with pytest.raises(GraphCycleError):
        sequence_plan(cyclic, uniform(cyclic, 0.1), P)


# --- priority ------------------------------------------------------------------


def test_the_weakest_high_leverage_concept_comes_first() -> None:
    """Among concepts that are all ready, priority decides the order."""
    nodes = [
        NodeMeta(node_id="hub", name="Hub", tier=1),
        NodeMeta(node_id="dead", name="Dead End", tier=1),
        NodeMeta(node_id="a", name="A", tier=2),
        NodeMeta(node_id="b", name="B", tier=2),
    ]
    edges = [Edge(prereq_id="hub", node_id="a"), Edge(prereq_id="hub", node_id="b")]
    graph = ConceptGraph(nodes, edges)
    # Equal weakness, unequal reach: the hub unblocks two concepts, the dead end none.
    sequenced = sequence_plan(graph, uniform(graph, 0.2), P)
    assert sequenced.units[0].node_id == "hub"


def test_weakness_outranks_reach_when_the_gap_is_wide() -> None:
    """A concept the learner nearly has does not lead the plan just for its reach."""
    nodes = [
        NodeMeta(node_id="hub", name="Hub", tier=1),
        NodeMeta(node_id="gap", name="Gap", tier=1),
        NodeMeta(node_id="a", name="A", tier=2),
        NodeMeta(node_id="b", name="B", tier=2),
    ]
    edges = [Edge(prereq_id="hub", node_id="a"), Edge(prereq_id="hub", node_id="b")]
    graph = ConceptGraph(nodes, edges)
    states = uniform(graph, 0.2) | {
        "hub": MasteryState(0.65, 0.6),
        "gap": MasteryState(0.02, 0.6),
    }
    sequenced = sequence_plan(graph, states, P)
    assert sequenced.units[0].node_id == "gap"


def test_sequencing_is_deterministic() -> None:
    """The same graph and estimates always produce the same plan."""
    graph = layered(per_tier=7, tiers=4)
    states = uniform(graph, 0.3)
    first = sequence_plan(graph, states, P)
    second = sequence_plan(graph, states, P)
    assert [u.node_id for u in first.units] == [u.node_id for u in second.units]


# --- truncation, interleaving, and reasons -------------------------------------


def test_a_limited_plan_reports_what_it_left_out() -> None:
    """Truncation is visible, so a prefix is never mistaken for the whole subject."""
    graph = layered(per_tier=6, tiers=4)
    sequenced = sequence_plan(graph, uniform(graph, 0.1), P, limit=5)
    assert len(sequenced.units) == 5
    assert len(sequenced.truncated) == len(graph) - 5
    assert_prerequisites_respected(graph, sequenced)


def test_the_first_unit_has_nothing_to_interleave() -> None:
    """Interleaving needs earlier material; the opening unit has none."""
    graph = layered(per_tier=5, tiers=3)
    sequenced = sequence_plan(graph, uniform(graph, 0.1), P)
    assert sequenced.units[0].interleaved_node_ids == ()


def test_interleaving_draws_only_on_concepts_already_taught() -> None:
    """A unit never retrieves something the learner has not met."""
    graph = layered(per_tier=6, tiers=4)
    sequenced = sequence_plan(graph, uniform(graph, 0.1), P)
    for unit in sequenced.units:
        earlier = {other.node_id for other in sequenced.units[: unit.seq]}
        assert set(unit.interleaved_node_ids) <= earlier
        assert len(unit.interleaved_node_ids) <= 2


def test_interleaving_leads_with_a_direct_prerequisite() -> None:
    """When a prerequisite was taught earlier, it is the first thing retrieved."""
    graph = chain(5)
    sequenced = sequence_plan(graph, uniform(graph, 0.1), P)
    later = sequenced.units[-1]
    prereqs = graph.prereqs(later.node_id)
    assert later.interleaved_node_ids[0] in prereqs


def test_interleaving_can_be_switched_off() -> None:
    """A learner who wants block practice gets it."""
    graph = layered(per_tier=4, tiers=3)
    sequenced = sequence_plan(graph, uniform(graph, 0.1), P, interleave=0)
    assert all(unit.interleaved_node_ids == () for unit in sequenced.units)


def test_every_unit_states_a_checkable_reason_for_its_position() -> None:
    """Placement is arguable with: each reason names graph facts and an estimate."""
    graph = layered(per_tier=5, tiers=3)
    sequenced = sequence_plan(graph, uniform(graph, 0.2), P)
    for unit in sequenced.units:
        assert unit.placement_reason
        assert "20%" in unit.placement_reason
        if graph.prereqs(unit.node_id):
            assert "Comes after" in unit.placement_reason
        else:
            assert "Foundational" in unit.placement_reason


def test_a_reason_credits_prerequisites_the_learner_already_knows() -> None:
    """A plan starting mid-graph explains what it is standing on."""
    graph = chain(3)
    states = {
        "c1": MasteryState(0.95, 0.8),
        "c2": MasteryState(0.2, 0.5),
        "c3": MasteryState(0.2, 0.5),
    }
    sequenced = sequence_plan(graph, states, P)
    assert "C1" in sequenced.units[0].placement_reason
    assert "already know" in sequenced.units[0].placement_reason


def test_re_taught_concepts_are_not_first_acquisitions() -> None:
    """History decides whether block practice is still the right shape."""
    graph = chain(3)
    sequenced = sequence_plan(graph, uniform(graph, 0.2), P, taught=frozenset({"c2"}))
    by_node = {unit.node_id: unit for unit in sequenced.units}
    assert by_node["c1"].first_acquisition
    assert not by_node["c2"].first_acquisition
