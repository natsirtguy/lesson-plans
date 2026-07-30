"""Tests for ask-anything, lesson streaming, and plan insertion.

The load-bearing test here is
:func:`test_an_off_subject_question_does_not_touch_the_graph`, which is an
acceptance criterion. It checks the whole graph state before and after, not just
that no exception was raised, because "does not corrupt the graph" is a claim about
what did *not* happen.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.llm.fake import FakeLLMAdapter, ParsedNode
from app.llm.schemas import QueryClassification
from app.mastery.state import MasteryParams
from app.models.enums import SuggestionStatus, UnitStatus
from app.models.subject import Subject
from app.repositories.changesets import ChangesetRepository
from app.repositories.graph import GraphRepository
from app.repositories.plans import PlanRepository
from app.schemas.plan import PlanCreate, UnitComplete
from app.services.ask_service import AskService, ask_cache_key
from app.services.graph_loader import GraphLoader
from app.services.lesson_service import LessonStreamer, lesson_cache_key
from app.services.plan_service import PlanService, UnitAlreadyScheduled
from app.sse import parse_events, sse
from tests.test_subjects import build_subject


async def collect(events: Any) -> list[tuple[str, Any]]:
    """Drain an SSE generator into parsed (name, data) pairs.

    :param events: The generator of SSE frames.
    """
    frames = [frame async for frame in events]
    return parse_events("".join(frames))


def only(events: list[tuple[str, Any]], name: str) -> list[Any]:
    """Payloads of every event with one name.

    :param events: Parsed events.
    :param name: The event name to select.
    """
    return [data for event, data in events if event == name]


def one(events: list[tuple[str, Any]], name: str) -> Any:
    """The single payload of a named event, asserting there is exactly one.

    :param events: Parsed events.
    :param name: The event name to select.
    """
    found = only(events, name)
    assert len(found) == 1, f"expected exactly one {name!r} event, got {len(found)}"
    return found[0]


def classify_as(kind: str, *, node_index: int = 0, concept: str | None = None) -> Any:
    """Build a classify hook that always returns one verdict.

    :param kind: The classification to return.
    :param node_index: Which graph node to match, for ``existing_node``.
    :param concept: Concept name to propose, for ``new_node``.
    """

    def hook(prompt: str, nodes: list[ParsedNode]) -> QueryClassification:
        matched = nodes[node_index] if kind == "existing_node" and nodes else None
        return QueryClassification(
            kind=kind,
            matched_node_id=matched.node_id if matched else None,
            title=concept or (matched.name if matched else "A Question"),
            concept_name=concept or (matched.name if matched else None),
            definition="A concept the question is about." if concept or matched else None,
            tier=matched.tier if matched else 2,
            prereq_names=[],
            reason=f"Classified as {kind} by the test hook.",
        )

    return hook


async def graph_snapshot(session: AsyncSession, subject_id: str) -> Any:
    """Capture everything about a subject's graph that a corrupting write would move.

    Every node including soft-deleted ones, every live edge, the graph version, and
    the open-suggestion count. Comparing this before and after is what turns "does
    not corrupt the graph" into an assertion rather than a hope.

    :param session: The test session.
    :param subject_id: The subject to snapshot.
    """
    graph = GraphRepository(session)
    subject = await session.get(Subject, subject_id)
    assert subject is not None
    return {
        "version": subject.graph_version,
        "nodes": sorted(
            (n.id, n.name, n.tier, n.definition, n.deleted_at, n.origin, n.is_satellite)
            for n in await graph.all_nodes(subject_id)
        ),
        "edges": sorted((e.prereq_id, e.node_id) for e in await graph.live_edges(subject_id)),
        "suggestions": len(await ChangesetRepository(session).open_suggestions(subject_id)),
    }


# --- SSE framing ---------------------------------------------------------------


def test_a_delta_containing_newlines_survives_the_wire() -> None:
    """Markdown is full of newlines; a raw frame would split into two events."""
    body = "## Heading\n\nA paragraph.\n\n```python\nx = 1\n```\n"
    events = parse_events(sse("delta", body))
    assert events == [("delta", body)]


def test_events_round_trip_in_order() -> None:
    """The parser is the inverse of the formatter, including structured payloads."""
    payload = sse("meta", {"a": 1}) + sse("delta", "text") + sse("done", {"b": True})
    assert parse_events(payload) == [("meta", {"a": 1}), ("delta", "text"), ("done", {"b": True})]


# --- classification routing ----------------------------------------------------


async def test_a_question_about_a_known_concept_attaches_to_it(
    sessionmaker_: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    fake_llm: FakeLLMAdapter,
    app_settings: Settings,
) -> None:
    """The answer is pitched at, and recorded against, the matched concept."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    fake_llm.classify_hook = classify_as("existing_node")

    service = AskService(sessionmaker_, fake_llm, app_settings)
    events = await collect(service.stream(subject_id, "How does concept 01 work?"))

    meta = one(events, "meta")
    assert meta["resolved_kind"] == "existing_node"
    assert meta["node_id"] is not None
    assert meta["node_name"]
    assert only(events, "delta")


async def test_an_in_subject_gap_becomes_a_reviewable_suggestion(
    sessionmaker_: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    fake_llm: FakeLLMAdapter,
    app_settings: Settings,
) -> None:
    """Finding a missing concept records a proposal, and adds nothing."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    before = len(await GraphRepository(session).live_nodes(subject_id))
    fake_llm.classify_hook = classify_as("new_node", concept="Ergodic Hypothesis")

    service = AskService(sessionmaker_, fake_llm, app_settings)
    events = await collect(service.stream(subject_id, "What is the ergodic hypothesis?"))

    done = one(events, "done")
    assert done["offer"]["kind"] == "review_suggestion"
    assert done["offer"]["suggestion_id"]

    session.expire_all()
    assert len(await GraphRepository(session).live_nodes(subject_id)) == before
    suggestions = await ChangesetRepository(session).open_suggestions(subject_id)
    assert any(s.summary.startswith("You asked about 'Ergodic Hypothesis'") for s in suggestions)
    assert all(s.status == SuggestionStatus.OPEN for s in suggestions)


async def test_an_off_subject_question_does_not_touch_the_graph(
    sessionmaker_: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    fake_llm: FakeLLMAdapter,
    app_settings: Settings,
) -> None:
    """The acceptance criterion, checked against the whole graph state."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    before = await graph_snapshot(session, subject_id)

    fake_llm.classify_hook = classify_as("off_subject")
    service = AskService(sessionmaker_, fake_llm, app_settings)
    events = await collect(service.stream(subject_id, "Who won the 1998 World Cup?"))

    assert one(events, "meta")["resolved_kind"] == "off_subject"
    assert one(events, "done")["offer"]["kind"] == "none"

    session.expire_all()
    assert await graph_snapshot(session, subject_id) == before


async def test_an_off_subject_answer_is_still_stored_and_readable(
    sessionmaker_: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    fake_llm: FakeLLMAdapter,
    app_settings: Settings,
) -> None:
    """Not touching the graph does not mean discarding the answer."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    fake_llm.classify_hook = classify_as("off_subject")

    service = AskService(sessionmaker_, fake_llm, app_settings)
    events = await collect(service.stream(subject_id, "Who won the 1998 World Cup?"))

    lesson = await PlanRepository(session).get_lesson(one(events, "done")["lesson_id"])
    assert lesson is not None
    assert lesson.node_id is None
    assert lesson.complete
    assert lesson.markdown
    assert lesson.provenance["source"] == "ask"


async def test_a_matched_id_the_graph_does_not_have_degrades_safely(
    sessionmaker_: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    fake_llm: FakeLLMAdapter,
    app_settings: Settings,
) -> None:
    """A stale node id must not attach an answer to a concept that is not there."""
    subject_id = await build_subject(session, fake_llm, app_settings)

    def hook(prompt: str, nodes: list[ParsedNode]) -> QueryClassification:
        return QueryClassification(
            kind="existing_node",
            matched_node_id="a-node-that-was-removed",
            title="Stale Match",
            concept_name="Stale Match",
            definition="A concept the classifier thought existed.",
            tier=2,
            prereq_names=[],
            reason="The graph moved since the context was cached.",
        )

    fake_llm.classify_hook = hook
    service = AskService(sessionmaker_, fake_llm, app_settings)
    events = await collect(service.stream(subject_id, "Tell me about the stale match."))

    meta = one(events, "meta")
    assert meta["kind"] == "existing_node"
    assert meta["resolved_kind"] == "new_node"
    assert meta["node_id"] is None


# --- caching -------------------------------------------------------------------


async def test_the_same_question_twice_is_answered_from_cache(
    sessionmaker_: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    fake_llm: FakeLLMAdapter,
    app_settings: Settings,
) -> None:
    """A repeated question replays the stored answer instead of regenerating it."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    fake_llm.classify_hook = classify_as("existing_node")
    service = AskService(sessionmaker_, fake_llm, app_settings)

    first = await collect(service.stream(subject_id, "Explain concept 01."))
    streams_after_first = sum(1 for call in fake_llm.calls if call.schema == "stream")
    second = await collect(service.stream(subject_id, "  EXPLAIN CONCEPT 01.  "))

    assert one(first, "meta")["cached"] is False
    assert one(second, "meta")["cached"] is True
    assert one(second, "done")["lesson_id"] == one(first, "done")["lesson_id"]
    assert sum(1 for call in fake_llm.calls if call.schema == "stream") == streams_after_first
    assert "".join(only(second, "delta")) == "".join(only(first, "delta"))


def test_an_ask_and_a_unit_lesson_never_share_a_cache_key() -> None:
    """Two different documents about one concept must not be served for each other."""
    assert ask_cache_key("s1", "n1", "What is this?") != lesson_cache_key("n1", 3, "developing")


def test_different_questions_about_one_concept_get_different_answers() -> None:
    """Keying on the concept alone would serve the first answer forever."""
    assert ask_cache_key("s1", "n1", "Why does it work?") != ask_cache_key("s1", "n1", "When?")


# --- lesson streaming ----------------------------------------------------------


async def test_a_unit_lesson_streams_then_persists(
    sessionmaker_: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    fake_llm: FakeLLMAdapter,
    app_settings: Settings,
) -> None:
    """The row is written so a later plain GET can serve it offline."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    plan_service = PlanService(session, fake_llm, app_settings)
    plan = await plan_service.create(subject_id, PlanCreate())
    served = await plan_service.next_unit(plan.id)
    assert served.lesson_id is not None

    streamer = LessonStreamer(sessionmaker_, fake_llm, app_settings)
    events = await collect(streamer.stream(served.lesson_id))

    assert one(events, "meta")["cached"] is False
    body = "".join(only(events, "delta"))
    assert "## Objective" in body
    assert one(events, "done")["characters"] == len(body)

    session.expire_all()
    lesson = await PlanRepository(session).get_lesson(served.lesson_id)
    assert lesson is not None
    assert lesson.complete
    assert lesson.markdown == body


async def test_rereading_a_lesson_costs_nothing(
    sessionmaker_: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    fake_llm: FakeLLMAdapter,
    app_settings: Settings,
) -> None:
    """A second read replays the row rather than paying to write it again."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    plan_service = PlanService(session, fake_llm, app_settings)
    plan = await plan_service.create(subject_id, PlanCreate())
    served = await plan_service.next_unit(plan.id)
    assert served.lesson_id is not None

    streamer = LessonStreamer(sessionmaker_, fake_llm, app_settings)
    first = await collect(streamer.stream(served.lesson_id))
    streams = sum(1 for call in fake_llm.calls if call.schema == "stream")
    second = await collect(streamer.stream(served.lesson_id))

    assert one(second, "meta")["cached"] is True
    assert sum(1 for call in fake_llm.calls if call.schema == "stream") == streams
    assert "".join(only(second, "delta")) == "".join(only(first, "delta"))


async def test_streaming_a_missing_lesson_reports_it_in_band(
    sessionmaker_: async_sessionmaker[AsyncSession],
    fake_llm: FakeLLMAdapter,
    app_settings: Settings,
) -> None:
    """Once a stream has started the status is committed, so failures are events."""
    streamer = LessonStreamer(sessionmaker_, fake_llm, app_settings)
    events = await collect(streamer.stream("no-such-lesson"))
    assert one(events, "error")["detail"] == "lesson not found"


# --- plan insertion ------------------------------------------------------------


async def test_inserting_a_unit_brings_its_missing_prerequisites_with_it(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """A truncated plan has unmastered prerequisites it never scheduled.

    Dropping a deep concept in on its own would produce exactly the unit the
    acceptance criterion forbids: one depending on something the learner is never
    taught. The whole unscheduled chain has to come with it.
    """
    subject_id = await build_subject(session, fake_llm, app_settings)
    service = PlanService(session, fake_llm, app_settings)
    plan = await service.create(subject_id, PlanCreate(limit=3))
    loaded = await GraphLoader(session, MasteryParams.from_settings(app_settings)).load(subject_id)

    planned = {unit.node_id for unit in plan.units}
    deep = max(
        (node_id for node_id in loaded.graph.node_ids if node_id not in planned),
        key=lambda node_id: loaded.graph.tier(node_id),
    )
    assert loaded.graph.ancestors(deep)

    updated = await service.insert_unit(plan.id, deep)
    position = {unit.node_id: unit.seq for unit in updated.units}
    assert deep in position
    for prereq in loaded.graph.prereqs(deep):
        assert prereq in position, "an unscheduled prerequisite was left untaught"
        assert position[prereq] < position[deep]
    assert [unit.seq for unit in updated.units] == list(range(len(updated.units)))


async def test_insertion_does_not_displace_finished_units(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """History does not move, so a new unit never lands before a closed one."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    service = PlanService(session, fake_llm, app_settings)
    plan = await service.create(subject_id, PlanCreate(limit=3))
    first = await service.next_unit(plan.id)
    assert first.unit is not None
    await service.complete_unit(first.unit.id, UnitComplete(skipped=True))

    loaded = await GraphLoader(session, MasteryParams.from_settings(app_settings)).load(subject_id)
    planned = {unit.node_id for unit in plan.units}
    # A root concept has no prerequisites, so nothing but history constrains it.
    root = next(node_id for node_id in loaded.graph.roots() if node_id not in planned)

    updated = await service.insert_unit(plan.id, root)
    inserted = next(unit for unit in updated.units if unit.node_id == root)
    closed = next(unit for unit in updated.units if unit.node_id == first.unit.node_id)
    assert closed.status == UnitStatus.SKIPPED
    assert inserted.seq > closed.seq


async def test_units_keep_a_contiguous_sequence_after_insertion(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """The unique (plan, seq) constraint holds and no gaps are left behind."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    service = PlanService(session, fake_llm, app_settings)
    plan = await service.create(subject_id, PlanCreate(limit=6))
    loaded = await GraphLoader(session, MasteryParams.from_settings(app_settings)).load(subject_id)

    planned = {unit.node_id for unit in plan.units}
    spare = next(node_id for node_id in loaded.graph.roots() if node_id not in planned)

    updated = await service.insert_unit(plan.id, spare)
    assert [unit.seq for unit in updated.units] == list(range(len(updated.units)))
    assert len(updated.units) == 7


async def test_inserting_an_already_planned_concept_is_refused(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """Two pending units for one concept would teach it twice."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    service = PlanService(session, fake_llm, app_settings)
    plan = await service.create(subject_id, PlanCreate())

    with pytest.raises(UnitAlreadyScheduled):
        await service.insert_unit(plan.id, plan.units[0].node_id)


# --- HTTP surface --------------------------------------------------------------


async def test_asking_over_http_streams_events(client: AsyncClient) -> None:
    """The endpoint returns an event stream, not a buffered JSON body."""
    created = await client.post("/subjects", json={"name": "Fluid Dynamics"})
    subject_id = created.json()["id"]

    async with client.stream(
        "POST", f"/subjects/{subject_id}/ask", json={"question": "What is turbulence?"}
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["x-accel-buffering"] == "no"
        body = "".join([chunk async for chunk in response.aiter_text()])

    events = parse_events(body)
    names = [name for name, _ in events]
    assert names[0] == "meta"
    assert names[-1] == "done"
    assert only(events, "delta")


async def test_a_streamed_answer_is_fetchable_afterwards(client: AsyncClient) -> None:
    """This is what makes an answer readable offline once the stream is gone."""
    created = await client.post("/subjects", json={"name": "Electromagnetism"})
    subject_id = created.json()["id"]

    async with client.stream(
        "POST", f"/subjects/{subject_id}/ask", json={"question": "Why is light a wave?"}
    ) as response:
        body = "".join([chunk async for chunk in response.aiter_text()])
    events = parse_events(body)
    lesson_id = one(events, "done")["lesson_id"]

    fetched = await client.get(f"/lessons/{lesson_id}")
    assert fetched.status_code == 200
    assert fetched.json()["complete"] is True
    assert fetched.json()["markdown"] == "".join(only(events, "delta"))


async def test_streaming_a_unit_lesson_over_http(client: AsyncClient) -> None:
    """The plan hands out a lesson id; this is what turns it into prose."""
    created = await client.post("/subjects", json={"name": "Linear Algebra"})
    plan = await client.post(f"/subjects/{created.json()['id']}/plan", json={})
    served = (await client.get(f"/plan/{plan.json()['id']}/next")).json()

    async with client.stream("POST", f"/lessons/{served['lesson_id']}/stream") as response:
        assert response.status_code == 200
        body = "".join([chunk async for chunk in response.aiter_text()])

    events = parse_events(body)
    assert "## Worked examples" in "".join(only(events, "delta"))
    assert one(events, "done")["complete"] is True


async def test_inserting_a_unit_over_http(client: AsyncClient) -> None:
    """Accepting a plan offer, end to end."""
    created = await client.post("/subjects", json={"name": "Probability"})
    subject_id = created.json()["id"]
    plan = (await client.post(f"/subjects/{subject_id}/plan", json={"limit": 5})).json()
    graph = (await client.get(f"/subjects/{subject_id}/graph")).json()

    planned = {unit["node_id"] for unit in plan["units"]}
    spare = next(
        node["id"] for node in graph["nodes"] if node["tier"] == 1 and node["id"] not in planned
    )
    inserted = await client.post(f"/plan/{plan['id']}/units", json={"node_id": spare})
    assert inserted.status_code == 201
    assert spare in {unit["node_id"] for unit in inserted.json()["units"]}

    duplicate = await client.post(f"/plan/{plan['id']}/units", json={"node_id": spare})
    assert duplicate.status_code == 409


async def test_asking_an_unknown_subject_is_a_404(client: AsyncClient) -> None:
    """A missing subject fails before the stream starts, so the status is honest."""
    response = await client.post("/subjects/nope/ask", json={"question": "Anything?"})
    assert response.status_code == 404
    assert (await client.post("/lessons/nope/stream")).status_code == 404


async def test_an_empty_question_is_rejected(client: AsyncClient) -> None:
    """Validation happens in the router, before anything is generated."""
    created = await client.post("/subjects", json={"name": "Astrophysics"})
    response = await client.post(f"/subjects/{created.json()['id']}/ask", json={"question": ""})
    assert response.status_code == 422
