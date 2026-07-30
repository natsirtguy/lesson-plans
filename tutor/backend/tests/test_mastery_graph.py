"""Tests for the pure graph structure.

The first test is the load-bearing one: it pins the edge-direction convention.
If prerequisite and dependent are ever swapped, prerequisite propagation inverts
silently and every downstream estimate is wrong in a way no other test would name.
"""

from __future__ import annotations

import pytest

from app.mastery.graph import ConceptGraph, Edge, GraphCycleError, NodeMeta
from tests.factories import chain, diamond, layered


def test_edge_direction_is_prereq_to_node() -> None:
    """An edge (a -> b) means a is required before b."""
    graph = ConceptGraph(
        [NodeMeta("a", "A", 1), NodeMeta("b", "B", 2)],
        [Edge(prereq_id="a", node_id="b")],
    )
    assert graph.prereqs("b") == {"a"}
    assert graph.prereqs("a") == frozenset()
    assert graph.dependents("a") == {"b"}
    assert graph.dependents("b") == frozenset()
    # Ancestors are what you need first; descendants are what needs you.
    assert dict(graph.ancestors("b")) == {"a": 1}
    assert dict(graph.descendants("a")) == {"b": 1}


def test_hop_distances_accumulate_along_a_chain() -> None:
    """Transitive prerequisites are recorded with their distance."""
    graph = chain(4)
    assert dict(graph.ancestors("c4")) == {"c3": 1, "c2": 2, "c1": 3}
    assert dict(graph.descendants("c1")) == {"c2": 1, "c3": 2, "c4": 3}


def test_diamond_uses_shortest_hop_distance() -> None:
    """A node reachable by two paths is counted once, at the shorter distance."""
    graph = diamond()
    assert dict(graph.ancestors("top")) == {"left": 1, "right": 1, "base": 2}
    assert graph.unblocking_power("base") == 3


def test_topological_order_respects_prerequisites() -> None:
    """Every prerequisite precedes what depends on it."""
    graph = layered(per_tier=4, tiers=3)
    order = graph.topological_order()
    position = {node_id: index for index, node_id in enumerate(order)}
    assert len(order) == len(graph)
    for edge in graph.edges:
        assert position[edge.prereq_id] < position[edge.node_id]


def test_topological_order_is_deterministic() -> None:
    """The same graph always orders the same way."""
    graph = layered(per_tier=5, tiers=3)
    assert graph.topological_order() == graph.topological_order()


def test_cycle_is_detected_and_reported() -> None:
    """A cyclic graph raises, and the error names the actual loop."""
    graph = ConceptGraph(
        [NodeMeta("a", "A", 1), NodeMeta("b", "B", 1), NodeMeta("c", "C", 1)],
        [
            Edge(prereq_id="a", node_id="b"),
            Edge(prereq_id="b", node_id="c"),
            Edge(prereq_id="c", node_id="a"),
        ],
    )
    assert graph.has_cycle() is True
    with pytest.raises(GraphCycleError) as excinfo:
        graph.topological_order()
    assert set(excinfo.value.cycle) == {"a", "b", "c"}


def test_self_edge_is_a_cycle() -> None:
    """A node that is its own prerequisite is rejected."""
    graph = ConceptGraph([NodeMeta("a", "A", 1)], [Edge(prereq_id="a", node_id="a")])
    assert graph.has_cycle() is True


def test_acyclic_graph_has_no_cycle() -> None:
    """A layered graph is acyclic."""
    assert layered(per_tier=6, tiers=5).has_cycle() is False


def test_dangling_edges_are_dropped() -> None:
    """Edges naming a missing node are ignored rather than raising.

    Callers filter soft-deleted nodes out; they should not have to filter edges too.
    """
    graph = ConceptGraph(
        [NodeMeta("a", "A", 1)],
        [Edge(prereq_id="a", node_id="ghost"), Edge(prereq_id="ghost", node_id="a")],
    )
    assert graph.edges == ()
    assert graph.prereqs("a") == frozenset()


def test_tier_violations_are_found() -> None:
    """A prerequisite harder than what it unlocks is reported."""
    graph = ConceptGraph(
        [NodeMeta("hard", "Hard", 4), NodeMeta("easy", "Easy", 2)],
        [Edge(prereq_id="hard", node_id="easy")],
    )
    violations = graph.tier_violations()
    assert len(violations) == 1
    assert violations[0].prereq_id == "hard"
    assert layered().tier_violations() == ()


def test_orphans_are_advanced_nodes_with_no_prerequisites() -> None:
    """A tier-3 concept with nothing leading to it is an orphan; a tier-1 one is not."""
    graph = ConceptGraph(
        [
            NodeMeta("root", "Root", 1),
            NodeMeta("floating", "Floating", 3),
            NodeMeta("attached", "Attached", 2),
        ],
        [Edge(prereq_id="root", node_id="attached")],
    )
    assert graph.orphaned_nodes() == ("floating",)


def test_roots_and_leaves() -> None:
    """Roots have no prerequisites; leaves have no dependents."""
    graph = chain(3)
    assert graph.roots() == ("c1",)
    assert graph.leaves() == ("c3",)


def test_with_changes_leaves_the_original_untouched() -> None:
    """Candidate graphs are built for validation without mutating the current one."""
    graph = chain(3)
    candidate = graph.with_changes(
        add_nodes=[NodeMeta("c4", "C4", 4)],
        add_edges=[Edge(prereq_id="c3", node_id="c4")],
        remove_edges=[Edge(prereq_id="c1", node_id="c2")],
        retier={"c2": 1},
    )
    assert len(graph) == 3 and len(candidate) == 4
    assert graph.prereqs("c2") == {"c1"}
    assert candidate.prereqs("c2") == frozenset()
    assert candidate.tier("c2") == 1
    assert candidate.prereqs("c4") == {"c3"}


def test_with_changes_removing_a_node_removes_its_edges() -> None:
    """Dropping a node cannot leave edges pointing at it."""
    candidate = chain(3).with_changes(remove_nodes=["c2"])
    assert "c2" not in candidate
    assert candidate.edges == ()


def test_with_changes_can_introduce_a_cycle_for_validation_to_catch() -> None:
    """The builder does not police structure; the validator does."""
    candidate = chain(2).with_changes(add_edges=[Edge(prereq_id="c2", node_id="c1")])
    assert candidate.has_cycle() is True
