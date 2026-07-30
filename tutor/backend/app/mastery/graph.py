"""The pure concept-graph structure.

Deliberately free of ORM types: the mastery model, the changeset validator, and
the plan sequencer all reason over this, and none of them should need a database
session to do it.

**Edge direction.** An edge is ``(prereq_id -> node_id)`` and means *prereq must
be learned before node*. So ``ancestors(n)`` are the things ``n`` depends on, and
``descendants(n)`` are the things that depend on ``n``. Inverting this silently
inverts prerequisite propagation, which is why the direction is restated here and
tested directly.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass


class GraphCycleError(ValueError):
    """Raised when an operation would make the prerequisite relation cyclic."""

    def __init__(self, cycle: Sequence[str]) -> None:
        """
        :param cycle: Node ids forming the cycle, in order.
        """
        self.cycle = tuple(cycle)
        super().__init__(f"prerequisite cycle: {' -> '.join(cycle)}")


@dataclass(frozen=True, slots=True)
class NodeMeta:
    """The graph-shaped facts about one concept.

    :param node_id: Stable identifier.
    :param name: Concept name.
    :param tier: Difficulty tier, 1 through 5.
    """

    node_id: str
    name: str
    tier: int


@dataclass(frozen=True, slots=True)
class Edge:
    """A prerequisite relation.

    :param prereq_id: The concept that must come first.
    :param node_id: The concept that depends on it.
    """

    prereq_id: str
    node_id: str


class ConceptGraph:
    """An immutable prerequisite graph with the traversals the app needs.

    Adjacency and the ancestor/descendant closures are computed once at
    construction. Graphs are small (40-120 nodes) and rebuilt per request, so
    eager computation is cheaper than memoising lazily and much easier to reason
    about.
    """

    __slots__ = ("_ancestors", "_dependents", "_descendants", "_edges", "_nodes", "_prereqs")

    def __init__(self, nodes: Iterable[NodeMeta], edges: Iterable[Edge]) -> None:
        """
        :param nodes: Concepts in the graph.
        :param edges: Prerequisite relations. Edges naming an unknown node are
            dropped, so a caller that filters out soft-deleted nodes does not
            also have to filter their edges.
        """
        self._nodes: dict[str, NodeMeta] = {node.node_id: node for node in nodes}
        self._edges: tuple[Edge, ...] = tuple(
            edge for edge in edges if edge.prereq_id in self._nodes and edge.node_id in self._nodes
        )

        prereqs: dict[str, set[str]] = {node_id: set() for node_id in self._nodes}
        dependents: dict[str, set[str]] = {node_id: set() for node_id in self._nodes}
        for edge in self._edges:
            prereqs[edge.node_id].add(edge.prereq_id)
            dependents[edge.prereq_id].add(edge.node_id)
        self._prereqs: dict[str, frozenset[str]] = {k: frozenset(v) for k, v in prereqs.items()}
        self._dependents: dict[str, frozenset[str]] = {
            k: frozenset(v) for k, v in dependents.items()
        }

        self._ancestors: dict[str, dict[str, int]] = {
            node_id: _bfs(node_id, self._prereqs) for node_id in self._nodes
        }
        self._descendants: dict[str, dict[str, int]] = {
            node_id: _bfs(node_id, self._dependents) for node_id in self._nodes
        }

    # --- basics --------------------------------------------------------------

    def __contains__(self, node_id: object) -> bool:
        """Whether a node id is present."""
        return node_id in self._nodes

    def __len__(self) -> int:
        """Number of concepts."""
        return len(self._nodes)

    @property
    def node_ids(self) -> tuple[str, ...]:
        """Node ids in insertion order."""
        return tuple(self._nodes)

    @property
    def nodes(self) -> Mapping[str, NodeMeta]:
        """Concepts keyed by id."""
        return self._nodes

    @property
    def edges(self) -> tuple[Edge, ...]:
        """Prerequisite relations, with dangling edges already dropped."""
        return self._edges

    def meta(self, node_id: str) -> NodeMeta:
        """Look up one concept.

        :param node_id: The concept's id.
        :raises KeyError: If the id is not in the graph.
        """
        return self._nodes[node_id]

    def tier(self, node_id: str) -> int:
        """Difficulty tier of a concept.

        :param node_id: The concept's id.
        """
        return self._nodes[node_id].tier

    # --- adjacency -----------------------------------------------------------

    def prereqs(self, node_id: str) -> frozenset[str]:
        """Concepts that must be learned immediately before this one.

        :param node_id: The concept's id.
        """
        return self._prereqs.get(node_id, frozenset())

    def dependents(self, node_id: str) -> frozenset[str]:
        """Concepts that immediately depend on this one.

        :param node_id: The concept's id.
        """
        return self._dependents.get(node_id, frozenset())

    def ancestors(self, node_id: str) -> Mapping[str, int]:
        """All prerequisites, transitively, mapped to their hop distance.

        :param node_id: The concept's id.
        """
        return self._ancestors.get(node_id, {})

    def descendants(self, node_id: str) -> Mapping[str, int]:
        """Everything that transitively depends on this concept, by hop distance.

        :param node_id: The concept's id.
        """
        return self._descendants.get(node_id, {})

    def unblocking_power(self, node_id: str) -> int:
        """How many concepts this one stands between the learner and.

        :param node_id: The concept's id.
        """
        return len(self._descendants.get(node_id, {}))

    def roots(self) -> tuple[str, ...]:
        """Concepts with no prerequisites."""
        return tuple(node_id for node_id in self._nodes if not self._prereqs[node_id])

    def leaves(self) -> tuple[str, ...]:
        """Concepts nothing else depends on."""
        return tuple(node_id for node_id in self._nodes if not self._dependents[node_id])

    # --- structural checks ---------------------------------------------------

    def topological_order(self) -> tuple[str, ...]:
        """Order concepts so every prerequisite precedes what depends on it.

        Ties are broken by tier and then by name, so the order is deterministic
        and reads sensibly when handed to the plan sequencer.

        :raises GraphCycleError: If the graph is cyclic.
        """
        indegree = {node_id: len(self._prereqs[node_id]) for node_id in self._nodes}
        ready = sorted((n for n, d in indegree.items() if d == 0), key=self._ordering_key)
        order: list[str] = []
        frontier = deque(ready)
        while frontier:
            node_id = frontier.popleft()
            order.append(node_id)
            newly_ready = []
            for dependent in sorted(self._dependents[node_id], key=self._ordering_key):
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    newly_ready.append(dependent)
            frontier.extend(newly_ready)

        if len(order) != len(self._nodes):
            raise GraphCycleError(self._find_cycle())
        return tuple(order)

    def has_cycle(self) -> bool:
        """Whether the prerequisite relation contains a cycle."""
        try:
            self.topological_order()
        except GraphCycleError:
            return True
        return False

    def tier_violations(self) -> tuple[Edge, ...]:
        """Edges pointing from a higher tier to a lower one.

        A prerequisite that is harder than the thing it unlocks is a modelling
        error: it makes the plan sequencer teach an advanced concept first.
        """
        return tuple(
            edge for edge in self._edges if self.tier(edge.prereq_id) > self.tier(edge.node_id)
        )

    def orphaned_nodes(self) -> tuple[str, ...]:
        """Concepts above tier 1 that no prerequisite chain leads to.

        In a finite acyclic graph, following prerequisites upward from any node
        with at least one prerequisite always terminates at a root -- so
        "unreachable from every root" reduces to "has no prerequisites at all".
        Combined with a tier above 1, that is a concept floating free of the
        foundations, which the sequencer cannot place after anything.
        """
        return tuple(
            node_id
            for node_id, meta in self._nodes.items()
            if meta.tier > 1 and not self._prereqs[node_id]
        )

    def _ordering_key(self, node_id: str) -> tuple[int, str, str]:
        """Deterministic sort key: tier, then name, then id.

        :param node_id: The concept's id.
        """
        meta = self._nodes[node_id]
        return (meta.tier, meta.name, meta.node_id)

    def _find_cycle(self) -> tuple[str, ...]:
        """Locate one cycle, for the error message.

        Iterative depth-first search over prerequisite edges, tracking the
        current path so the reported cycle is the actual loop rather than just
        the set of nodes involved.
        """
        colour: dict[str, int] = dict.fromkeys(self._nodes, 0)
        path: list[str] = []

        for start in self._nodes:
            if colour[start] != 0:
                continue
            stack: list[tuple[str, bool]] = [(start, False)]
            while stack:
                node_id, leaving = stack.pop()
                if leaving:
                    colour[node_id] = 2
                    path.pop()
                    continue
                if colour[node_id] == 1:
                    continue
                colour[node_id] = 1
                path.append(node_id)
                stack.append((node_id, True))
                for prereq in sorted(self._prereqs[node_id]):
                    if colour[prereq] == 1:
                        loop = path[path.index(prereq) :]
                        return (*loop, prereq)
                    if colour[prereq] == 0:
                        stack.append((prereq, False))
        return ()

    def with_changes(
        self,
        *,
        add_nodes: Iterable[NodeMeta] = (),
        remove_nodes: Iterable[str] = (),
        add_edges: Iterable[Edge] = (),
        remove_edges: Iterable[Edge] = (),
        retier: Mapping[str, int] | None = None,
    ) -> ConceptGraph:
        """Build a new graph with edits applied, leaving this one untouched.

        This is what makes changeset validation possible without touching the
        database: the candidate graph is constructed, checked, and discarded if
        it fails.

        :param add_nodes: Concepts to add.
        :param remove_nodes: Ids of concepts to drop, along with their edges.
        :param add_edges: Prerequisite relations to add.
        :param remove_edges: Prerequisite relations to drop.
        :param retier: New tiers, keyed by node id.
        """
        dropped = set(remove_nodes)
        tiers = dict(retier or {})
        nodes = [
            NodeMeta(
                node_id=meta.node_id,
                name=meta.name,
                tier=tiers.get(meta.node_id, meta.tier),
            )
            for meta in self._nodes.values()
            if meta.node_id not in dropped
        ]
        nodes.extend(
            NodeMeta(
                node_id=meta.node_id,
                name=meta.name,
                tier=tiers.get(meta.node_id, meta.tier),
            )
            for meta in add_nodes
            if meta.node_id not in dropped
        )
        removed_edges = {(e.prereq_id, e.node_id) for e in remove_edges}
        edges = [
            edge
            for edge in self._edges
            if (edge.prereq_id, edge.node_id) not in removed_edges
            and edge.prereq_id not in dropped
            and edge.node_id not in dropped
        ]
        edges.extend(
            edge
            for edge in add_edges
            if (edge.prereq_id, edge.node_id) not in removed_edges
            and edge.prereq_id not in dropped
            and edge.node_id not in dropped
        )
        return ConceptGraph(nodes, edges)


def _bfs(start: str, adjacency: Mapping[str, frozenset[str]]) -> dict[str, int]:
    """Breadth-first reachability from ``start``, excluding ``start`` itself.

    :param start: Node to search from.
    :param adjacency: Either the prerequisite map or the dependent map.
    """
    distances: dict[str, int] = {}
    frontier = deque([(start, 0)])
    seen = {start}
    while frontier:
        node_id, depth = frontier.popleft()
        for neighbour in adjacency.get(node_id, frozenset()):
            if neighbour in seen:
                continue
            seen.add(neighbour)
            distances[neighbour] = depth + 1
            frontier.append((neighbour, depth + 1))
    return distances
