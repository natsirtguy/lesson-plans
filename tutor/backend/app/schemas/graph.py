"""Concept-graph read schemas.

The graph response is what the report view renders, so it carries everything the
visualisation needs in one payload: mastery for node colour, confidence for the
ring, tier for the layer, and a locked flag for greying out edges the learner
cannot yet cross.
"""

from __future__ import annotations

from app.schemas.common import ApiModel


class NodeRead(ApiModel):
    """One concept, with the learner's standing on it."""

    id: str
    name: str
    definition: str
    tier: int
    origin: str
    mastery: float
    confidence: float
    direct_observations: int
    #: Concepts that transitively depend on this one.
    unblocks: int
    #: True when every prerequisite is below the mastery threshold, so nothing
    #: currently leads here.
    locked: bool
    #: True when the concept is not yet mastered but all its prerequisites are.
    ready: bool
    introduced_in_version: int


class EdgeRead(ApiModel):
    """A prerequisite relation, oriented prerequisite-first."""

    prereq_id: str
    node_id: str
    #: True when the prerequisite is not yet mastered, so the edge is not crossable.
    locked: bool


class GraphRead(ApiModel):
    """A subject's full graph with current mastery."""

    subject_id: str
    graph_version: int
    graph_status: str
    nodes: list[NodeRead]
    edges: list[EdgeRead]
    #: Mean estimated mastery across every live concept, the same figure the report
    #: leads with. Carried here so the graph view can show where the learner stands
    #: without a second request for one number.
    coverage: float
