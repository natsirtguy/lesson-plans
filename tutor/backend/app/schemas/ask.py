"""Ask-anything schemas.

These describe the SSE payloads rather than a request/response pair, because the
answer streams. :class:`AskMeta` is everything the client can know before the prose
starts; :class:`AskDone` is everything only knowable after it finishes.
"""

from __future__ import annotations

from pydantic import Field

from app.schemas.common import ApiModel


class AskRequest(ApiModel):
    """A free-form question asked against a subject."""

    question: str = Field(min_length=1, max_length=4000)


class PlanOffer(ApiModel):
    """What the app can do about the concept a question was about.

    The offer is the whole mechanism by which asking a question feeds back into
    the plan. Nothing here happens on its own -- an offer is a suggestion the
    learner accepts or ignores, which is what keeps a stray question from
    rewriting the graph or the plan behind their back.
    """

    #: ``insert_unit``, ``review_suggestion``, ``already_planned``, or ``none``.
    kind: str
    node_id: str | None
    #: Set when the concept has to be added to the graph before it can be planned.
    suggestion_id: str | None
    message: str


class AskMeta(ApiModel):
    """What is known before the answer starts streaming."""

    question: str
    #: What the classifier decided: ``existing_node``, ``new_node``, ``off_subject``.
    kind: str
    #: How the app resolved that, which can differ when the model names a concept
    #: id that is not in the live graph.
    resolved_kind: str
    title: str
    node_id: str | None
    node_name: str | None
    reason: str
    #: The lesson row the prose is being written to, fetchable at ``/lessons/{id}``.
    lesson_id: str
    #: True when the answer is being replayed from cache rather than generated.
    cached: bool
    graph_version: int


class AskDone(ApiModel):
    """The outcome of a completed answer."""

    lesson_id: str
    complete: bool
    characters: int
    offer: PlanOffer
