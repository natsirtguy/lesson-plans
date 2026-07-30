"""Tests for changeset simulation and validation, without a database.

These are the guarantees the acceptance criteria name: no committed changeset can
produce a cyclic graph, splitting a node does not destroy mastery history, and a
removal that a plan depends on is refused.
"""

from __future__ import annotations

import pytest

from app.graphs.mutation import (
    MutationError,
    MutationPlan,
    plan_mutation,
    preview_changes,
    summarize,
    validate_plan,
)
from app.mastery.graph import ConceptGraph, Edge, NodeMeta
from app.mastery.state import DEFAULT_PARAMS as P
from app.mastery.state import MasteryState
from app.repositories.graph import name_key
from app.schemas.changeset import (
    AddEdge,
    AddNode,
    MergeNodes,
    NewNodeSpec,
    Operation,
    RedefineNode,
    RemoveEdge,
    RemoveNode,
    RenameNode,
    RetargetEdge,
    RetierNode,
    SplitNode,
)
from tests.factories import chain, diamond


def states_for(
    graph: ConceptGraph, mastery: float = 0.5, confidence: float = 0.5
) -> dict[str, MasteryState]:
    """Give every node in a graph the same state.

    :param graph: The graph whose nodes to populate.
    :param mastery: Mastery to assign.
    :param confidence: Confidence to assign.
    """
    return {
        node_id: MasteryState(mastery=mastery, confidence=confidence) for node_id in graph.node_ids
    }


def definitions_for(graph: ConceptGraph) -> dict[str, str]:
    """Give every node a placeholder definition.

    :param graph: The graph whose nodes to describe.
    """
    return {node_id: f"definition of {node_id}" for node_id in graph.node_ids}


def plan_for(
    graph: ConceptGraph,
    operations: list[Operation],
    mastery: float = 0.5,
    confidence: float = 0.5,
) -> MutationPlan:
    """Simulate operations against a graph with uniform mastery.

    :param graph: The current graph.
    :param operations: Operations to apply.
    :param mastery: Mastery to give every existing concept.
    :param confidence: Confidence to give every existing concept.
    """
    return plan_mutation(
        graph,
        states_for(graph, mastery=mastery, confidence=confidence),
        definitions_for(graph),
        operations,
        P,
    )


# --- individual operations -----------------------------------------------------


def test_add_node_creates_it_and_seeds_from_prerequisites() -> None:
    """A new concept starts from what its prerequisites imply, not from zero."""
    graph = chain(2)
    plan = plan_for(
        graph,
        [
            AddNode(
                node=NewNodeSpec(
                    name="New Thing", definition="Something new.", tier=3, prereq_ids=["c2"]
                )
            )
        ],
        mastery=0.8,
        confidence=0.9,
    )
    assert len(plan.added) == 1
    added = plan.added[0]
    assert added.name == "New Thing"
    assert ("c2", added.node_id) in plan.edges
    seeded = plan.seeds[added.node_id]
    assert 0.0 < seeded.mastery < 0.8
    assert seeded.confidence == pytest.approx(P.seeded_confidence)


def test_add_node_drops_a_prerequisite_that_does_not_exist() -> None:
    """A stale reference becomes a note, not a dangling edge."""
    plan = plan_for(
        chain(2),
        [
            AddNode(
                node=NewNodeSpec(name="Thing", definition="d", tier=2, prereq_ids=["c1", "ghost"])
            )
        ],
    )
    added = plan.added[0]
    assert ("c1", added.node_id) in plan.edges
    assert any("ghost" in note for note in plan.notes)


def test_remove_node_soft_deletes_and_drops_its_edges() -> None:
    """Removal takes the concept's relations with it."""
    plan = plan_for(chain(3), [RemoveNode(node_id="c2")])
    assert plan.removed == {"c2"}
    assert "c2" not in plan.nodes
    assert all("c2" not in pair for pair in plan.edges)


def test_remove_node_with_cascade_takes_stranded_dependents() -> None:
    """A chain that only existed to support the removed concept goes with it."""
    plan = plan_for(chain(4), [RemoveNode(node_id="c2", cascade=True)])
    assert plan.removed == {"c2", "c3", "c4"}
    assert set(plan.nodes) == {"c1"}


def test_remove_node_without_cascade_leaves_dependents_with_other_paths() -> None:
    """A dependent that still has another prerequisite survives."""
    plan = plan_for(diamond(), [RemoveNode(node_id="left", cascade=True)])
    assert "top" in plan.nodes, "top still has 'right' as a prerequisite"
    assert plan.removed == {"left"}


def test_remove_node_rejects_an_unknown_id() -> None:
    """An operation against a missing concept fails before any graph is built."""
    with pytest.raises(MutationError, match="unknown concept"):
        plan_for(chain(2), [RemoveNode(node_id="ghost")])


def test_merge_uses_the_reconciliation_rules_and_inherits_edges() -> None:
    """Mastery is confidence-weighted; confidence is the minimum, not the mean."""
    graph = diamond()
    states = {
        "base": MasteryState(0.9, 0.9),
        "left": MasteryState(0.9, 0.9),
        "right": MasteryState(0.3, 0.1),
        "top": MasteryState(0.5, 0.5),
    }
    plan = plan_mutation(
        graph,
        states,
        definitions_for(graph),
        [
            MergeNodes(
                node_ids=["left", "right"],
                new_name="Sides",
                new_definition="Left and right together.",
            )
        ],
        P,
    )
    merged = plan.added[0]
    assert plan.removed == {"left", "right"}
    assert ("base", merged.node_id) in plan.edges
    assert (merged.node_id, "top") in plan.edges
    seeded = plan.seeds[merged.node_id]
    assert seeded.mastery == pytest.approx((0.9 * 0.9 + 0.3 * 0.1) / 1.0)
    assert seeded.confidence == pytest.approx(0.1), "minimum, not mean"
    assert merged.tier == 2, "the merged concept is as hard as its hardest part"


def test_split_preserves_mastery_and_halves_confidence() -> None:
    """Splitting mid-course must not destroy what the learner has shown."""
    graph = chain(3)
    states = {
        "c1": MasteryState(0.9, 0.9),
        "c2": MasteryState(0.82, 0.6),
        "c3": MasteryState(0.4, 0.4),
    }
    plan = plan_mutation(
        graph,
        states,
        definitions_for(graph),
        [
            SplitNode(
                node_id="c2",
                into=[
                    NewNodeSpec(name="C2 Part A", definition="First half.", tier=2),
                    NewNodeSpec(name="C2 Part B", definition="Second half.", tier=2),
                ],
            )
        ],
        P,
    )
    assert plan.removed == {"c2"}
    assert len(plan.added) == 2
    for child in plan.added:
        seeded = plan.seeds[child.node_id]
        assert seeded.mastery == pytest.approx(0.82), "each child inherits the estimate"
        assert seeded.confidence == pytest.approx(0.3), "but half the certainty"


def test_split_children_inherit_the_parents_position_in_the_graph() -> None:
    """Each child requires what the parent required, and unlocks what it unlocked."""
    plan = plan_for(
        chain(3),
        [
            SplitNode(
                node_id="c2",
                into=[
                    NewNodeSpec(name="Part A", definition="d", tier=2),
                    NewNodeSpec(name="Part B", definition="d", tier=2),
                ],
            )
        ],
    )
    for child in plan.added:
        assert ("c1", child.node_id) in plan.edges
        assert (child.node_id, "c3") in plan.edges


def test_split_children_may_declare_their_own_prerequisites() -> None:
    """An explicit prerequisite list overrides inheriting the parent's."""
    plan = plan_for(
        chain(3),
        [
            SplitNode(
                node_id="c3",
                into=[
                    NewNodeSpec(name="Part A", definition="d", tier=3, prereq_ids=["c1"]),
                    NewNodeSpec(name="Part B", definition="d", tier=3, prereq_ids=["c2"]),
                ],
            )
        ],
    )
    first, second = plan.added
    assert ("c1", first.node_id) in plan.edges
    assert ("c2", first.node_id) not in plan.edges
    assert ("c2", second.node_id) in plan.edges


def test_edge_operations_change_the_edge_set_and_flag_recomputation() -> None:
    """Any edge movement marks the posterior as needing recomputation."""
    added = plan_for(chain(3), [AddEdge(prereq_id="c1", node_id="c3")])
    assert ("c1", "c3") in added.edges and added.edges_changed

    removed = plan_for(chain(3), [RemoveEdge(prereq_id="c1", node_id="c2")])
    assert ("c1", "c2") not in removed.edges and removed.edges_changed

    moved = plan_for(
        chain(3),
        [RetargetEdge(prereq_id="c1", node_id="c2", new_prereq_id="c1", new_node_id="c3")],
    )
    assert ("c1", "c2") not in moved.edges
    assert ("c1", "c3") in moved.edges


def test_metadata_operations_do_not_flag_recomputation() -> None:
    """A rename does not change what the evidence implies."""
    plan = plan_for(
        chain(2),
        [
            RenameNode(node_id="c1", name="Renamed"),
            RedefineNode(node_id="c2", definition="Rewritten."),
            RetierNode(node_id="c2", tier=3),
        ],
    )
    assert plan.edges_changed is False
    assert plan.renamed == {"c1": "Renamed"}
    assert plan.redefined == {"c2": "Rewritten."}
    assert plan.retiered == {"c2": 3}
    assert plan.nodes["c1"].name == "Renamed"


def test_operations_apply_in_order_so_a_later_one_can_use_an_earlier_result() -> None:
    """Adding a concept and then requiring it in the same changeset works."""
    graph = chain(2)
    plan = plan_mutation(
        graph,
        states_for(graph),
        definitions_for(graph),
        [
            AddNode(node=NewNodeSpec(name="Middle", definition="d", tier=2)),
            RetierNode(node_id="c2", tier=3),
        ],
        P,
    )
    assert plan.nodes["c2"].tier == 3
    assert len(plan.added) == 1


def test_an_empty_operation_list_changes_nothing() -> None:
    """A refinement that concluded no change is needed is not an error."""
    plan = plan_for(chain(3), [])
    assert plan.is_empty is True
    assert validate_plan(plan) is None


# --- validation ----------------------------------------------------------------


def test_a_cycle_is_rejected_and_the_message_names_the_loop() -> None:
    """The headline guarantee: no committed changeset can produce a cyclic graph."""
    plan = plan_for(chain(3), [AddEdge(prereq_id="c3", node_id="c1")])
    error = validate_plan(plan)
    assert error is not None
    assert "circular" in error
    assert "C1" in error


def test_a_tier_inversion_is_rejected() -> None:
    """A prerequisite may not be harder than what it unlocks.

    Two independent branches, so the edge is a pure tier inversion rather than also
    a cycle -- the cycle check fires first and would mask this one.
    """
    graph = ConceptGraph(
        [
            NodeMeta("easy_root", "Easy Root", 1),
            NodeMeta("easy", "Easy", 2),
            NodeMeta("hard_root", "Hard Root", 1),
            NodeMeta("hard", "Hard", 4),
        ],
        [
            Edge(prereq_id="easy_root", node_id="easy"),
            Edge(prereq_id="hard_root", node_id="hard"),
        ],
    )
    plan = plan_for(graph, [AddEdge(prereq_id="hard", node_id="easy")])
    error = validate_plan(plan)
    assert error is not None
    assert "prerequisite" in error and "harder" in error
    assert "'Hard'" in error and "'Easy'" in error


def test_a_cycle_is_reported_before_a_tier_inversion() -> None:
    """When a change is both, the cycle is the more fundamental problem to name."""
    plan = plan_for(chain(4), [AddEdge(prereq_id="c4", node_id="c2")])
    error = validate_plan(plan)
    assert error is not None and "circular" in error


def test_an_orphan_is_rejected_with_advice() -> None:
    """A tier-3 concept with nothing leading to it cannot be sequenced."""
    plan = plan_for(chain(3), [RemoveEdge(prereq_id="c2", node_id="c3")])
    error = validate_plan(plan)
    assert error is not None
    assert "no prerequisites" in error
    assert "cascade" in error


def test_removing_a_concept_the_plan_teaches_is_rejected() -> None:
    """A pending lesson-plan unit protects its concept from removal."""
    plan = plan_for(chain(3), [RemoveNode(node_id="c3")])
    error = validate_plan(plan, protected={"c3": "Unit 4: C3"})
    assert error is not None
    assert "lesson plan" in error
    assert "Unit 4: C3" in error


def test_a_duplicate_concept_name_is_rejected() -> None:
    """Adding a concept that already exists would fragment its history."""
    plan = plan_for(chain(2), [AddNode(node=NewNodeSpec(name="C1", definition="d", tier=1))])
    error = validate_plan(plan, existing_name_keys={"c1": "c1"}, key_of=name_key)
    assert error is not None
    assert "already exists" in error


def test_a_duplicate_name_is_allowed_when_the_original_is_being_removed() -> None:
    """Replacing a concept with a same-named one is a rename, not a collision."""
    plan = plan_for(
        chain(2),
        [
            RemoveNode(node_id="c2"),
            AddNode(
                node=NewNodeSpec(name="C2", definition="Rewritten.", tier=2, prereq_ids=["c1"])
            ),
        ],
    )
    assert validate_plan(plan, existing_name_keys={"c2": "c2"}, key_of=name_key) is None


def test_a_valid_plan_passes_every_rule() -> None:
    """The happy path: a well-formed change is accepted."""
    plan = plan_for(
        chain(3),
        [AddNode(node=NewNodeSpec(name="Extra", definition="d", tier=3, prereq_ids=["c2"]))],
    )
    assert validate_plan(plan, protected={}, existing_name_keys={}, key_of=name_key) is None


# --- presentation --------------------------------------------------------------


def test_every_operation_renders_a_readable_summary() -> None:
    """The diff view shows sentences, not payloads."""
    names = {"c1": "Foundations", "c2": "Middle", "c3": "Advanced"}
    operations: list[Operation] = [
        AddNode(node=NewNodeSpec(name="New", definition="d", tier=2, prereq_ids=["c1"])),
        RemoveNode(node_id="c2", cascade=True),
        MergeNodes(node_ids=["c1", "c2"], new_name="Both", new_definition="d"),
        SplitNode(
            node_id="c2",
            into=[
                NewNodeSpec(name="A", definition="d", tier=2),
                NewNodeSpec(name="B", definition="d", tier=2),
            ],
        ),
        RetierNode(node_id="c3", tier=4),
        AddEdge(prereq_id="c1", node_id="c3"),
        RemoveEdge(prereq_id="c1", node_id="c2"),
        RetargetEdge(prereq_id="c1", node_id="c2", new_prereq_id="c2", new_node_id="c3"),
        RenameNode(node_id="c1", name="Basics"),
        RedefineNode(node_id="c1", definition="d"),
    ]
    summaries = [summarize(operation, names) for operation in operations]
    assert len(summaries) == 10, "every operation type is covered"
    assert all(summary and summary[0].isupper() for summary in summaries)
    assert "Foundations" in summaries[0]
    assert "Middle" in summaries[1]


def test_preview_labels_each_concept_with_its_fate() -> None:
    """The preview panel distinguishes added, removed, changed, and untouched."""
    graph = chain(3)
    plan = plan_for(
        graph,
        [
            RemoveNode(node_id="c3"),
            RenameNode(node_id="c2", name="Renamed"),
            AddNode(node=NewNodeSpec(name="Fresh", definition="d", tier=2, prereq_ids=["c1"])),
        ],
    )
    changes = {name: change for _id, name, _tier, change in preview_changes(plan, graph)}
    assert changes["C3"] == "removed"
    assert changes["Renamed"] == "changed"
    assert changes["Fresh"] == "added"
    assert changes["C1"] == "unchanged"
