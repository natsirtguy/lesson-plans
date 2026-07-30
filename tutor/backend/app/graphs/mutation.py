"""Simulating a changeset before committing it.

Nothing about a changeset touches the database until the resulting graph has been
built in memory and checked. That is what makes "no committed changeset can produce
a cyclic graph" enforceable rather than hoped for: the candidate graph is
constructed from the accepted operations, validated, and thrown away if it fails.

This module is pure. It takes the current graph, the learner's mastery, and a list
of operations, and returns a plan describing the graph that would result plus the
mastery each affected concept should carry. The service layer's job is only to
write that plan down.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from app.mastery.graph import ConceptGraph, Edge, NodeMeta
from app.mastery.reconcile import merge_mastery, seed_mastery, split_mastery
from app.mastery.state import MasteryParams, MasteryState
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


class MutationError(ValueError):
    """Raised when an operation cannot be applied at all.

    Distinct from a validation failure: this means the operation references
    something that does not exist, so there is no candidate graph to check.
    """


@dataclass(slots=True)
class NodeDraft:
    """A concept as it will exist after the mutation.

    :param node_id: The concept's id. New concepts get theirs here, so edges and
        mastery seeds can reference them before anything is written.
    :param name: Concept name.
    :param definition: One-sentence definition.
    :param tier: Difficulty tier.
    :param is_new: Whether this concept does not yet exist in the database.
    :param sources: Ids of the concepts this one derives from, for a split or merge.
    """

    node_id: str
    name: str
    definition: str
    tier: int
    is_new: bool = False
    sources: tuple[str, ...] = ()


@dataclass(slots=True)
class MutationPlan:
    """Everything a commit needs to do, computed and checked in advance.

    :param nodes: The final concept set, keyed by id.
    :param edges: The final prerequisite pairs, as ``(prereq_id, node_id)``.
    :param removed: Ids of existing concepts to soft-delete.
    :param added: Concepts to create, in order.
    :param renamed: New names for existing concepts.
    :param redefined: New definitions for existing concepts.
    :param retiered: New tiers for existing concepts.
    :param seeds: Reconciled mastery for concepts whose evidence cannot simply be
        replayed -- split children, merge results, and additions.
    :param restored: Ids of concepts that turned out to already exist, soft-deleted,
        and were revived. Their stored mastery is their history and must not be
        overwritten by a seed.
    :param edges_changed: Whether any prerequisite relation moved, which decides
        whether the posterior needs recomputing.
    :param notes: Things the learner should be told that are not errors, such as a
        prerequisite reference that could not be resolved.
    """

    nodes: dict[str, NodeDraft] = field(default_factory=dict)
    edges: set[tuple[str, str]] = field(default_factory=set)
    removed: set[str] = field(default_factory=set)
    added: list[NodeDraft] = field(default_factory=list)
    renamed: dict[str, str] = field(default_factory=dict)
    redefined: dict[str, str] = field(default_factory=dict)
    retiered: dict[str, int] = field(default_factory=dict)
    seeds: dict[str, MasteryState] = field(default_factory=dict)
    restored: set[str] = field(default_factory=set)
    edges_changed: bool = False
    notes: list[str] = field(default_factory=list)

    def candidate_graph(self) -> ConceptGraph:
        """Build the graph this plan would produce."""
        return ConceptGraph(
            (
                NodeMeta(node_id=draft.node_id, name=draft.name, tier=draft.tier)
                for draft in self.nodes.values()
            ),
            (Edge(prereq_id=prereq, node_id=node) for prereq, node in sorted(self.edges)),
        )

    @property
    def is_empty(self) -> bool:
        """Whether the plan would change nothing."""
        return not (
            self.removed
            or self.added
            or self.renamed
            or self.redefined
            or self.retiered
            or self.edges_changed
        )


def plan_mutation(
    graph: ConceptGraph,
    states: Mapping[str, MasteryState],
    definitions: Mapping[str, str],
    operations: Sequence[Operation],
    params: MasteryParams,
) -> MutationPlan:
    """Work out the graph and mastery a list of operations would produce.

    Operations apply in order, so a later one may reference a concept an earlier one
    created.

    :param graph: The current live graph.
    :param states: Current mastery per node id.
    :param definitions: Current definition per node id.
    :param operations: The accepted operations, in order.
    :param params: Mastery model constants.
    :raises MutationError: If an operation references a concept that does not exist.
    """
    plan = MutationPlan(
        nodes={
            node_id: NodeDraft(
                node_id=node_id,
                name=meta.name,
                definition=definitions.get(node_id, ""),
                tier=meta.tier,
            )
            for node_id, meta in graph.nodes.items()
        },
        edges={(edge.prereq_id, edge.node_id) for edge in graph.edges},
    )
    working_states = dict(states)

    for operation in operations:
        _apply(operation, plan, working_states, params)

    return plan


def _apply(
    operation: Operation,
    plan: MutationPlan,
    states: dict[str, MasteryState],
    params: MasteryParams,
) -> None:
    """Apply one operation to the plan in progress.

    :param operation: The operation to apply.
    :param plan: The plan being built.
    :param states: Mastery per node id, updated as concepts are created.
    :param params: Mastery model constants.
    :raises MutationError: If the operation references a missing concept.
    """
    match operation:
        case AddNode():
            _add_node(operation.node, plan, states, params)
        case RemoveNode():
            _remove_node(operation, plan)
        case MergeNodes():
            _merge_nodes(operation, plan, states)
        case SplitNode():
            _split_node(operation, plan, states, params)
        case RetierNode():
            _require(operation.node_id, plan)
            plan.nodes[operation.node_id].tier = operation.tier
            plan.retiered[operation.node_id] = operation.tier
        case AddEdge():
            _require(operation.prereq_id, plan)
            _require(operation.node_id, plan)
            plan.edges.add((operation.prereq_id, operation.node_id))
            plan.edges_changed = True
        case RemoveEdge():
            plan.edges.discard((operation.prereq_id, operation.node_id))
            plan.edges_changed = True
        case RetargetEdge():
            _require(operation.new_prereq_id, plan)
            _require(operation.new_node_id, plan)
            plan.edges.discard((operation.prereq_id, operation.node_id))
            plan.edges.add((operation.new_prereq_id, operation.new_node_id))
            plan.edges_changed = True
        case RenameNode():
            _require(operation.node_id, plan)
            plan.nodes[operation.node_id].name = operation.name
            plan.renamed[operation.node_id] = operation.name
        case RedefineNode():
            _require(operation.node_id, plan)
            plan.nodes[operation.node_id].definition = operation.definition
            plan.redefined[operation.node_id] = operation.definition


def _require(node_id: str, plan: MutationPlan) -> NodeDraft:
    """Look up a concept the operation depends on.

    :param node_id: The concept's id.
    :param plan: The plan being built.
    :raises MutationError: If the concept is absent or already removed.
    """
    draft = plan.nodes.get(node_id)
    if draft is None:
        raise MutationError(f"operation references unknown concept {node_id!r}")
    return draft


def _new_id() -> str:
    """Generate an id for a concept the plan creates."""
    return str(uuid.uuid4())


def _add_node(
    spec: NewNodeSpec,
    plan: MutationPlan,
    states: dict[str, MasteryState],
    params: MasteryParams,
) -> None:
    """Add a concept and seed its mastery from its prerequisites.

    :param spec: The concept to create.
    :param plan: The plan being built.
    :param states: Mastery per node id.
    :param params: Mastery model constants.
    """
    draft = NodeDraft(
        node_id=_new_id(),
        name=spec.name.strip(),
        definition=spec.definition.strip(),
        tier=spec.tier,
        is_new=True,
    )
    plan.nodes[draft.node_id] = draft
    plan.added.append(draft)

    prereq_states: list[MasteryState] = []
    for prereq_id in spec.prereq_ids:
        if prereq_id not in plan.nodes:
            plan.notes.append(
                f"prerequisite {prereq_id!r} for {draft.name!r} no longer exists and was dropped"
            )
            continue
        plan.edges.add((prereq_id, draft.node_id))
        plan.edges_changed = True
        if prereq_id in states:
            prereq_states.append(states[prereq_id])

    seeded = seed_mastery(prereq_states, params)
    plan.seeds[draft.node_id] = seeded
    states[draft.node_id] = seeded


def _remove_node(operation: RemoveNode, plan: MutationPlan) -> None:
    """Remove a concept, optionally taking its stranded dependents with it.

    :param operation: The removal.
    :param plan: The plan being built.
    """
    _require(operation.node_id, plan)
    doomed = {operation.node_id}

    if operation.cascade:
        # Repeatedly take anything whose every remaining prerequisite is going, so
        # a chain that only existed to support the removed concept goes with it.
        changed = True
        while changed:
            changed = False
            for node_id in list(plan.nodes):
                if node_id in doomed:
                    continue
                prereqs = {p for p, n in plan.edges if n == node_id}
                if prereqs and prereqs <= doomed:
                    doomed.add(node_id)
                    changed = True

    for node_id in doomed:
        draft = plan.nodes.pop(node_id, None)
        if draft is None:
            continue
        if not draft.is_new:
            plan.removed.add(node_id)
        else:
            plan.added = [d for d in plan.added if d.node_id != node_id]
            plan.seeds.pop(node_id, None)
        plan.edges = {(p, n) for p, n in plan.edges if p != node_id and n != node_id}
        plan.edges_changed = True


def _merge_nodes(
    operation: MergeNodes, plan: MutationPlan, states: dict[str, MasteryState]
) -> None:
    """Collapse several concepts into one new concept.

    A new concept is created rather than one input being kept, because the merged
    concept's mastery is a function of all the inputs -- the confidence-weighted
    mean, with the minimum confidence -- and reusing an input's id would silently
    keep that input's history as the merged concept's own.

    :param operation: The merge.
    :param plan: The plan being built.
    :param states: Mastery per node id.
    """
    drafts = [_require(node_id, plan) for node_id in operation.node_ids]
    tier = operation.tier or max(draft.tier for draft in drafts)

    merged = NodeDraft(
        node_id=_new_id(),
        name=operation.new_name.strip(),
        definition=operation.new_definition.strip(),
        tier=tier,
        is_new=True,
        sources=tuple(operation.node_ids),
    )

    inputs = set(operation.node_ids)
    inherited_prereqs = {p for p, n in plan.edges if n in inputs and p not in inputs}
    inherited_dependents = {n for p, n in plan.edges if p in inputs and n not in inputs}

    for node_id in inputs:
        draft = plan.nodes.pop(node_id, None)
        if draft is not None and not draft.is_new:
            plan.removed.add(node_id)
        elif draft is not None:
            plan.added = [d for d in plan.added if d.node_id != node_id]
    plan.edges = {(p, n) for p, n in plan.edges if p not in inputs and n not in inputs}

    plan.nodes[merged.node_id] = merged
    plan.added.append(merged)
    plan.edges.update((p, merged.node_id) for p in inherited_prereqs)
    plan.edges.update((merged.node_id, n) for n in inherited_dependents)
    plan.edges_changed = True

    input_states = [states[node_id] for node_id in operation.node_ids if node_id in states]
    reconciled = merge_mastery(input_states) if input_states else MasteryState(0.15, 0.05)
    plan.seeds[merged.node_id] = reconciled
    states[merged.node_id] = reconciled


def _split_node(
    operation: SplitNode,
    plan: MutationPlan,
    states: dict[str, MasteryState],
    params: MasteryParams,
) -> None:
    """Replace one concept with several, distributing its mastery.

    Each child inherits the parent's prerequisites unless it names its own, and
    every child becomes a prerequisite of whatever depended on the parent: the
    dependent needed all of what the parent covered, so it needs all the pieces.

    :param operation: The split.
    :param plan: The plan being built.
    :param states: Mastery per node id.
    :param params: Mastery model constants.
    """
    parent = _require(operation.node_id, plan)
    parent_prereqs = {p for p, n in plan.edges if n == operation.node_id}
    parent_dependents = {n for p, n in plan.edges if p == operation.node_id}

    parent_state = states.get(operation.node_id, MasteryState(0.15, 0.05))
    child_states = split_mastery(parent_state, into=len(operation.into), params=params)

    plan.nodes.pop(operation.node_id, None)
    if not parent.is_new:
        plan.removed.add(operation.node_id)
    else:
        plan.added = [d for d in plan.added if d.node_id != operation.node_id]
    plan.edges = {
        (p, n) for p, n in plan.edges if p != operation.node_id and n != operation.node_id
    }

    for spec, child_state in zip(operation.into, child_states, strict=True):
        child = NodeDraft(
            node_id=_new_id(),
            name=spec.name.strip(),
            definition=spec.definition.strip(),
            tier=spec.tier,
            is_new=True,
            sources=(operation.node_id,),
        )
        plan.nodes[child.node_id] = child
        plan.added.append(child)

        prereqs = (
            {p for p in spec.prereq_ids if p in plan.nodes}
            if spec.prereq_ids
            else parent_prereqs & set(plan.nodes)
        )
        plan.edges.update((p, child.node_id) for p in prereqs)
        plan.edges.update((child.node_id, n) for n in parent_dependents if n in plan.nodes)
        plan.seeds[child.node_id] = child_state
        states[child.node_id] = child_state

    plan.edges_changed = True


def validate_plan(
    plan: MutationPlan,
    *,
    protected: Mapping[str, str] | None = None,
    existing_name_keys: Mapping[str, str] | None = None,
    key_of: Callable[[str], str] | None = None,
) -> str | None:
    """Check a plan against the graph's invariants.

    Returns a message describing the first violation, or None when the plan is
    safe to commit. The four rules, in the order a learner is most likely to hit
    them:

    1. A concept a lesson-plan unit still depends on may not be removed.
    2. The prerequisite relation must stay acyclic.
    3. A prerequisite may not sit at a higher tier than what it unlocks.
    4. A concept above tier 1 must have some prerequisite path leading to it.

    :param plan: The plan to check.
    :param protected: Node ids a pending plan unit depends on, mapped to the unit
        title, so the message can name what would break.
    :param existing_name_keys: Normalized names of concepts already in the
        database, mapped to their node id, used to reject a duplicate.
    :param key_of: Callable normalizing a name to its identity key.
    """
    blocking = protected or {}
    for node_id in sorted(plan.removed):
        if node_id in blocking:
            return (
                f"cannot remove a concept the lesson plan still depends on: "
                f"{blocking[node_id]!r} teaches it"
            )

    if key_of is not None and existing_name_keys:
        for draft in plan.added:
            clash = existing_name_keys.get(key_of(draft.name))
            if clash is not None and clash not in plan.removed:
                return (
                    f"a concept named {draft.name!r} already exists; "
                    "rename it or merge into the existing one instead"
                )

    candidate = plan.candidate_graph()

    cycle = candidate.find_cycle()
    if cycle:
        names = " -> ".join(candidate.nodes[n].name for n in cycle if n in candidate.nodes)
        return f"these changes would make the prerequisites circular: {names}"

    violations = candidate.tier_violations()
    if violations:
        edge = violations[0]
        return (
            f"{candidate.nodes[edge.prereq_id].name!r} (tier "
            f"{candidate.tier(edge.prereq_id)}) cannot be a prerequisite of "
            f"{candidate.nodes[edge.node_id].name!r} (tier {candidate.tier(edge.node_id)}); "
            "a prerequisite must not be harder than what it unlocks"
        )

    orphans = candidate.orphaned_nodes()
    if orphans:
        names = ", ".join(sorted(candidate.nodes[n].name for n in orphans))
        return (
            f"these concepts would have no prerequisites and nothing leading to "
            f"them: {names}. Give them a prerequisite, move them to tier 1, or "
            "remove them with cascade."
        )

    return None


def affected_subgraph(plan: MutationPlan, candidate: ConceptGraph) -> frozenset[str]:
    """Nodes whose posterior may have moved because their prerequisites changed.

    :param plan: The committed plan.
    :param candidate: The graph the plan produced.
    """
    touched: set[str] = set()
    for prereq, node in plan.edges:
        touched.add(node)
        touched.add(prereq)
    touched.update(draft.node_id for draft in plan.added)
    return frozenset(node_id for node_id in touched if node_id in candidate)


def summarize(operation: Operation, names: Mapping[str, str]) -> str:
    """Render one operation as a sentence for the diff view.

    :param operation: The operation to describe.
    :param names: Concept names by id, for referring to concepts by name.
    """

    def label(node_id: str) -> str:
        return names.get(node_id, node_id)

    match operation:
        case AddNode():
            prereqs = ", ".join(label(p) for p in operation.node.prereq_ids)
            tail = f" after {prereqs}" if prereqs else ""
            return f"Add {operation.node.name!r} at tier {operation.node.tier}{tail}"
        case RemoveNode():
            extra = " and anything left stranded" if operation.cascade else ""
            return f"Remove {label(operation.node_id)!r}{extra}"
        case MergeNodes():
            parts = ", ".join(label(n) for n in operation.node_ids)
            return f"Merge {parts} into {operation.new_name!r}"
        case SplitNode():
            parts = ", ".join(spec.name for spec in operation.into)
            return f"Split {label(operation.node_id)!r} into {parts}"
        case RetierNode():
            return f"Move {label(operation.node_id)!r} to tier {operation.tier}"
        case AddEdge():
            return f"Require {label(operation.prereq_id)!r} before {label(operation.node_id)!r}"
        case RemoveEdge():
            return (
                f"Stop requiring {label(operation.prereq_id)!r} before {label(operation.node_id)!r}"
            )
        case RetargetEdge():
            return (
                f"Move the prerequisite {label(operation.prereq_id)!r} -> "
                f"{label(operation.node_id)!r} to {label(operation.new_prereq_id)!r} -> "
                f"{label(operation.new_node_id)!r}"
            )
        case RenameNode():
            return f"Rename {label(operation.node_id)!r} to {operation.name!r}"
        case RedefineNode():
            return f"Rewrite the definition of {label(operation.node_id)!r}"


def preview_changes(
    plan: MutationPlan, before: ConceptGraph
) -> Iterable[tuple[str, str, int, str]]:
    """Describe each concept's fate under a plan, for the preview panel.

    :param plan: The plan being previewed.
    :param before: The graph as it stands now.
    """
    for node_id in plan.removed:
        if node_id in before:
            meta = before.nodes[node_id]
            yield (node_id, meta.name, meta.tier, "removed")
    for draft in plan.nodes.values():
        if draft.is_new:
            yield (draft.node_id, draft.name, draft.tier, "added")
        elif (
            draft.node_id in plan.renamed
            or draft.node_id in plan.redefined
            or draft.node_id in plan.retiered
        ):
            yield (draft.node_id, draft.name, draft.tier, "changed")
        else:
            yield (draft.node_id, draft.name, draft.tier, "unchanged")
