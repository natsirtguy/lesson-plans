"""Tests for the harness itself: schema creation, the app, and the fake adapter.

If these fail, nothing downstream can be trusted, so they assert the guarantees
the rest of the suite relies on rather than any product behaviour.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Base
from app.llm.fake import FakeLLMAdapter, parse_nodes
from app.llm.prompts import NodeContext, graph_context
from app.llm.schema_tools import UNSUPPORTED_KEYWORDS, response_schema
from app.llm.schemas import GeneratedGraph, GradeResult
from app.models import ConceptNode, Subject


async def test_health(client: AsyncClient) -> None:
    """The app boots and reports the fake provider under test."""
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["llm_provider"] == "fake"


async def test_schema_has_every_table() -> None:
    """Every model is imported, so metadata is complete for Alembic."""
    expected = {
        "subjects",
        "concept_nodes",
        "concept_edges",
        "mastery_records",
        "changesets",
        "changeset_ops",
        "graph_suggestions",
        "diagnostic_sessions",
        "quiz_items",
        "item_responses",
        "lesson_plans",
        "plan_units",
        "lessons",
        "review_cards",
        "study_sessions",
    }
    assert expected <= set(Base.metadata.tables)


async def test_database_round_trip(session: AsyncSession) -> None:
    """Rows persist with their defaults applied."""
    subject = Subject(name="Statistical Mechanics")
    session.add(subject)
    await session.flush()
    session.add(
        ConceptNode(
            subject_id=subject.id,
            name="Ensemble",
            name_key="ensemble",
            definition="A collection of microstates consistent with macroscopic constraints.",
            tier=2,
        )
    )
    await session.commit()

    found = (await session.execute(select(ConceptNode))).scalar_one()
    assert found.tier == 2
    assert found.deleted_at is None
    assert found.is_satellite is False
    assert subject.graph_version == 1


async def test_fake_graph_is_a_tier_monotonic_dag(fake_llm: FakeLLMAdapter) -> None:
    """The fake produces structurally valid graphs, not arbitrary filler."""
    graph = await fake_llm.generate_structured(
        schema=GeneratedGraph,
        system="",
        prompt="SUBJECT: Kubernetes",
        task="test",
    )
    by_name = {node.name: node for node in graph.nodes}
    assert len(by_name) == len(graph.nodes), "names must be unique"
    for node in graph.nodes:
        for prereq in node.prerequisites:
            assert prereq in by_name, "prerequisites reference concepts in the graph"
            assert by_name[prereq].tier <= node.tier, "no edge from a higher tier down"
    assert {node.tier for node in graph.nodes} == {1, 2, 3, 4, 5}


async def test_fake_records_calls_and_context_key(fake_llm: FakeLLMAdapter) -> None:
    """Calls are recorded, including which cacheable prefix was used."""
    context = graph_context(
        subject_name="Optics",
        graph_version=3,
        nodes=[
            NodeContext(
                node_id="n1",
                name="Refraction",
                definition="Bending of light at an interface between media.",
                tier=1,
                mastery=0.4,
                confidence=0.2,
                prereq_names=(),
            )
        ],
    )
    await fake_llm.generate_structured(
        schema=GradeResult,
        system="",
        prompt="ANSWER: this is correct",
        task="grade",
        context=context,
    )
    call = fake_llm.calls[-1]
    assert call.task == "grade"
    assert call.context_key == "subject:Optics:v3:n1"


async def test_graph_context_round_trips(fake_llm: FakeLLMAdapter) -> None:
    """The rendered context parses back to the concepts that went into it."""
    nodes = [
        NodeContext(
            node_id=f"id-{index}",
            name=f"Concept {index}",
            definition=f"Definition {index}.",
            tier=index,
            mastery=0.5,
            confidence=0.5,
            prereq_names=(),
        )
        for index in (1, 2, 3)
    ]
    context = graph_context(subject_name="Subject", graph_version=1, nodes=nodes)
    parsed = parse_nodes(context.text)
    assert [p.node_id for p in parsed] == ["id-1", "id-2", "id-3"]
    assert [p.tier for p in parsed] == [1, 2, 3]
    assert parsed[0].definition == "Definition 1."


@pytest.mark.parametrize("schema", [GeneratedGraph, GradeResult])
async def test_response_schema_is_api_compatible(schema: type) -> None:
    """Generated schemas are inlined, closed, and free of rejected keywords."""
    built = response_schema(schema)
    flat = repr(built)
    assert "$ref" not in flat and "$defs" not in flat
    for keyword in UNSUPPORTED_KEYWORDS:
        assert f"'{keyword}'" not in flat
    _assert_objects_closed(built)


def _assert_objects_closed(node: object) -> None:
    """Recursively assert every object node forbids extra properties.

    :param node: A JSON Schema fragment.
    """
    if isinstance(node, list):
        for item in node:
            _assert_objects_closed(item)
        return
    if not isinstance(node, dict):
        return
    if node.get("type") == "object":
        assert node.get("additionalProperties") is False
        assert set(node.get("required", [])) == set(node.get("properties", {}))
    for value in node.values():
        _assert_objects_closed(value)


async def test_grade_hook_overrides_scoring(fake_llm: FakeLLMAdapter) -> None:
    """A test can drive grading deterministically without touching internals."""
    fake_llm.grade_hook = lambda _prompt: 0.42
    result = await fake_llm.generate_structured(
        schema=GradeResult,
        system="",
        prompt="ANSWER: anything",
        task="grade",
    )
    assert result.score == pytest.approx(0.42)
    assert result.correct is False


async def test_fake_streams_a_full_lesson(fake_llm: FakeLLMAdapter) -> None:
    """Streaming yields multiple deltas that reassemble into the lesson."""
    deltas = [
        chunk
        async for chunk in fake_llm.stream_text(
            system="", prompt="CONCEPT: Refraction", task="lesson"
        )
    ]
    assert len(deltas) > 1
    body = "".join(deltas)
    assert "## Objective" in body and "## Exit check" in body
