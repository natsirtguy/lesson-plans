"""Shaping the graph for the report view."""

from __future__ import annotations

from app.mastery.coverage import ready_to_learn
from app.mastery.state import MasteryParams
from app.schemas.graph import EdgeRead, GraphRead, NodeRead
from app.services.graph_loader import LoadedSubject


def render_graph(loaded: LoadedSubject, params: MasteryParams) -> GraphRead:
    """Build the graph payload the visualisation consumes.

    The locked and ready flags are computed here rather than in the client so that
    "can the learner cross this edge yet" has one definition. Locked means every
    prerequisite is still below the mastery threshold, which is what greys an edge
    out; ready means the concept is unmastered but everything it rests on is done.

    :param loaded: The subject with its graph and mastery.
    :param params: Mastery model constants.
    """
    graph = loaded.graph
    states = loaded.states
    ready = set(ready_to_learn(graph, states, params))
    threshold = params.mastery_threshold

    nodes: list[NodeRead] = []
    for node_id, meta in graph.nodes.items():
        row = loaded.nodes[node_id]
        state = states[node_id]
        record = loaded.records.get(node_id)
        prereqs = graph.prereqs(node_id)
        locked = bool(prereqs) and all(
            (states[p].mastery if p in states else 0.0) < threshold for p in prereqs
        )
        nodes.append(
            NodeRead(
                id=node_id,
                name=meta.name,
                definition=row.definition,
                tier=meta.tier,
                origin=row.origin,
                mastery=state.mastery,
                confidence=state.confidence,
                direct_observations=record.direct_observations if record else 0,
                unblocks=graph.unblocking_power(node_id),
                locked=locked,
                ready=node_id in ready,
                introduced_in_version=row.introduced_in_version,
            )
        )

    edges = [
        EdgeRead(
            prereq_id=edge.prereq_id,
            node_id=edge.node_id,
            locked=(
                states[edge.prereq_id].mastery < threshold if edge.prereq_id in states else True
            ),
        )
        for edge in graph.edges
    ]

    return GraphRead(
        subject_id=loaded.subject.id,
        graph_version=loaded.subject.graph_version,
        graph_status=loaded.subject.graph_status,
        nodes=nodes,
        edges=edges,
    )
