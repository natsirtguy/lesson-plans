"""Graph builders shared by the mastery tests."""

from __future__ import annotations

from app.mastery.graph import ConceptGraph, Edge, NodeMeta


def chain(length: int = 4) -> ConceptGraph:
    """A straight prerequisite chain ``c1 -> c2 -> ... -> cn``.

    Each node's tier equals its position, so the chain is tier-monotonic.

    :param length: Number of concepts.
    """
    nodes = [NodeMeta(node_id=f"c{i}", name=f"C{i}", tier=min(i, 5)) for i in range(1, length + 1)]
    edges = [Edge(prereq_id=f"c{i}", node_id=f"c{i + 1}") for i in range(1, length)]
    return ConceptGraph(nodes, edges)


def diamond() -> ConceptGraph:
    """A diamond: ``base`` feeds ``left`` and ``right``, which both feed ``top``.

    Used to check that a node reachable by two paths is counted once, at its
    shortest hop distance.
    """
    nodes = [
        NodeMeta(node_id="base", name="Base", tier=1),
        NodeMeta(node_id="left", name="Left", tier=2),
        NodeMeta(node_id="right", name="Right", tier=2),
        NodeMeta(node_id="top", name="Top", tier=3),
    ]
    edges = [
        Edge(prereq_id="base", node_id="left"),
        Edge(prereq_id="base", node_id="right"),
        Edge(prereq_id="left", node_id="top"),
        Edge(prereq_id="right", node_id="top"),
    ]
    return ConceptGraph(nodes, edges)


def layered(per_tier: int = 12, tiers: int = 5, prereqs_per_node: int = 2) -> ConceptGraph:
    """A wide layered graph, shaped like a real generated concept graph.

    Every node above tier 1 draws its prerequisites from the tier below, so the
    result is acyclic and tier-monotonic by construction.

    :param per_tier: Concepts in each tier.
    :param tiers: Number of tiers.
    :param prereqs_per_node: Prerequisites each non-root node gets.
    """
    nodes: list[NodeMeta] = []
    edges: list[Edge] = []
    for tier in range(1, tiers + 1):
        for index in range(per_tier):
            node_id = f"t{tier}n{index:02d}"
            nodes.append(
                NodeMeta(node_id=node_id, name=f"Tier {tier} Concept {index:02d}", tier=tier)
            )
            if tier == 1:
                continue
            for offset in range(prereqs_per_node):
                parent_index = (index + offset) % per_tier
                edges.append(Edge(prereq_id=f"t{tier - 1}n{parent_index:02d}", node_id=node_id))
    return ConceptGraph(nodes, edges)
