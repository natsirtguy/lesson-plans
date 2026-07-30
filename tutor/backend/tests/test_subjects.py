"""Tests for subject creation, graph generation, and the graph API."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.llm.fake import FakeLLMAdapter
from app.llm.schemas import GeneratedGraph, GeneratedNode
from app.mastery.graph import ConceptGraph, Edge, NodeMeta
from app.models.enums import GraphGenerationStatus
from app.models.graph import ConceptEdge, ConceptNode, MasteryRecord
from app.models.subject import Subject
from app.repositories.graph import name_key
from app.schemas.subject import SubjectCreate
from app.services.subject_service import GraphGenerationError, SubjectService


async def build_subject(
    session: AsyncSession,
    adapter: FakeLLMAdapter,
    settings: Settings,
    *,
    name: str = "Statistical Mechanics",
) -> str:
    """Create a subject and generate its graph, returning the subject id.

    :param session: The test session.
    :param adapter: The offline adapter.
    :param settings: Test settings.
    :param name: Subject name.
    """
    service = SubjectService(session, adapter, settings)
    subject = await service.create(SubjectCreate(name=name))
    await service.generate_graph(subject.id)
    return subject.id


# --- name normalization --------------------------------------------------------


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("Bayes' Theorem", "bayes theorem"),
        ("bayes   theorem", "bayes theorem"),
        ("Schrödinger Equation", "schrodinger equation"),
        ("  Entropy (Statistical)  ", "entropy statistical"),
    ],
)
def test_name_key_folds_to_a_stable_identity(written: str, expected: str) -> None:
    """Two spellings of the same concept must collide, so history can be restored."""
    assert name_key(written) == expected


# --- generation ----------------------------------------------------------------


async def test_generation_persists_nodes_edges_and_mastery(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """A generated graph lands as concepts, prerequisite edges, and seeded mastery."""
    subject_id = await build_subject(session, fake_llm, app_settings)

    nodes = list((await session.execute(select(ConceptNode))).scalars())
    edges = list((await session.execute(select(ConceptEdge))).scalars())
    records = list((await session.execute(select(MasteryRecord))).scalars())

    assert len(nodes) == fake_llm.graph_size
    assert len(edges) > 0
    assert len(records) == len(nodes), "every concept gets a mastery record"
    assert all(record.mastery > 0.0 for record in records), "never seeded at zero"

    subject = await session.get(Subject, subject_id)
    assert subject is not None
    assert subject.graph_status == GraphGenerationStatus.READY


async def test_generated_graph_is_an_acyclic_tier_monotonic_dag(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """The persisted graph satisfies the invariants everything downstream assumes."""
    await build_subject(session, fake_llm, app_settings)
    nodes = list((await session.execute(select(ConceptNode))).scalars())
    edges = list((await session.execute(select(ConceptEdge))).scalars())
    graph = ConceptGraph(
        (NodeMeta(node_id=n.id, name=n.name, tier=n.tier) for n in nodes),
        (Edge(prereq_id=e.prereq_id, node_id=e.node_id) for e in edges),
    )
    assert graph.has_cycle() is False
    assert graph.tier_violations() == ()


async def test_mastery_seeds_follow_prerequisite_structure(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """A concept deep in the graph starts lower than a foundational one.

    Seeding every node at the same flat prior would make the diagnostic's first
    few picks arbitrary.
    """
    await build_subject(session, fake_llm, app_settings)
    nodes = {node.id: node for node in (await session.execute(select(ConceptNode))).scalars()}
    records = {
        record.node_id: record
        for record in (await session.execute(select(MasteryRecord))).scalars()
    }
    tier_one = [records[n].mastery for n in nodes if nodes[n].tier == 1]
    tier_five = [records[n].mastery for n in nodes if nodes[n].tier == 5]
    assert min(tier_one) >= max(tier_five)


async def test_duplicate_concept_names_are_collapsed(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """A model that repeats a concept must not produce two rows for it."""

    def duplicated(_prompt: str) -> GeneratedGraph:
        nodes = [
            GeneratedNode(
                name="Entropy", definition="A measure of disorder.", tier=1, prerequisites=[]
            ),
            GeneratedNode(
                name="entropy", definition="Same thing, restated.", tier=1, prerequisites=[]
            ),
            *[
                GeneratedNode(
                    name=f"Concept {index}",
                    definition="Filler to clear the minimum size.",
                    tier=1,
                    prerequisites=[],
                )
                for index in range(15)
            ],
        ]
        return GeneratedGraph(subject_summary="s", nodes=nodes)

    fake_llm.graph_hook = duplicated
    service = SubjectService(session, fake_llm, app_settings)
    subject = await service.create(SubjectCreate(name="Thermodynamics"))
    await service.generate_graph(subject.id)
    names = [node.name_key for node in (await session.execute(select(ConceptNode))).scalars()]
    assert names.count("entropy") == 1


async def test_generation_records_failure_instead_of_raising(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """A graph too small to use fails visibly on the subject, not with a 500."""
    fake_llm.graph_size = 3
    service = SubjectService(session, fake_llm, app_settings)
    subject = await service.create(SubjectCreate(name="Too Small"))
    result = await service.generate_graph(subject.id)
    assert result.graph_status == GraphGenerationStatus.FAILED
    assert result.graph_error is not None and "usable concepts" in result.graph_error
    assert list((await session.execute(select(ConceptNode))).scalars()) == []


async def test_generation_is_idempotent(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """A retried background task must not build a second graph."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    service = SubjectService(session, fake_llm, app_settings)
    await service.generate_graph(subject_id)
    nodes = list((await session.execute(select(ConceptNode))).scalars())
    assert len(nodes) == fake_llm.graph_size


async def test_cyclic_generation_is_rejected(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """A cycle in generated prerequisites fails generation rather than persisting."""

    def cyclic(_prompt: str) -> GeneratedGraph:
        # Same tier throughout, so the tier-monotonicity filter cannot break the
        # cycle for us and the DAG check is what has to catch it.
        nodes = [
            GeneratedNode(
                name=f"Concept {index}",
                definition="Part of a deliberate cycle.",
                tier=2,
                prerequisites=[f"Concept {(index + 1) % 15}"],
            )
            for index in range(15)
        ]
        return GeneratedGraph(subject_summary="s", nodes=nodes)

    fake_llm.graph_hook = cyclic
    service = SubjectService(session, fake_llm, app_settings)
    subject = await service.create(SubjectCreate(name="Cyclic"))
    result = await service.generate_graph(subject.id)
    assert result.graph_status == GraphGenerationStatus.FAILED
    assert "cycle" in (result.graph_error or "")


async def test_unknown_prerequisite_names_are_dropped(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """A prerequisite naming a concept that was not generated is ignored.

    Keeping it would leave the node permanently unreachable.
    """

    def dangling(_prompt: str) -> GeneratedGraph:
        nodes = [
            GeneratedNode(
                name=f"Concept {index}",
                definition="Refers to something that does not exist.",
                tier=1,
                prerequisites=["Nonexistent Concept"],
            )
            for index in range(15)
        ]
        return GeneratedGraph(subject_summary="s", nodes=nodes)

    fake_llm.graph_hook = dangling
    service = SubjectService(session, fake_llm, app_settings)
    subject = await service.create(SubjectCreate(name="Dangling"))
    result = await service.generate_graph(subject.id)
    assert result.graph_status == GraphGenerationStatus.READY
    assert list((await session.execute(select(ConceptEdge))).scalars()) == []


def test_generation_error_is_its_own_type() -> None:
    """Services distinguish a bad graph from a transport failure."""
    assert issubclass(GraphGenerationError, RuntimeError)


# --- endpoints -----------------------------------------------------------------


async def test_create_subject_endpoint_kicks_off_generation(client: AsyncClient) -> None:
    """The POST returns immediately, and the background task fills the graph in."""
    response = await client.post("/subjects", json={"name": "Carnatic Rhythm Theory"})
    assert response.status_code == 201
    created = response.json()
    assert created["graph_status"] == GraphGenerationStatus.PENDING

    # httpx's ASGI transport runs background tasks before the response completes,
    # so by now generation has happened.
    detail = await client.get(f"/subjects/{created['id']}")
    assert detail.status_code == 200
    assert detail.json()["graph_status"] == GraphGenerationStatus.READY
    assert detail.json()["node_count"] > 0


async def test_graph_endpoint_returns_nodes_edges_and_flags(client: AsyncClient) -> None:
    """The graph payload carries everything the visualisation needs."""
    created = (await client.post("/subjects", json={"name": "Kubernetes"})).json()
    response = await client.get(f"/subjects/{created['id']}/graph")
    assert response.status_code == 200
    body = response.json()
    assert body["graph_version"] == 1
    assert len(body["nodes"]) > 0
    node = body["nodes"][0]
    assert {"mastery", "confidence", "tier", "locked", "ready", "unblocks"} <= set(node)
    assert any(edge["prereq_id"] for edge in body["edges"])


async def test_graph_of_unknown_subject_is_a_404(client: AsyncClient) -> None:
    """A bad id is a 404, not a 500."""
    assert (await client.get("/subjects/nope/graph")).status_code == 404
    assert (await client.get("/subjects/nope")).status_code == 404


async def test_list_subjects_reports_node_counts(client: AsyncClient) -> None:
    """The landing page needs to know which subjects have a graph yet."""
    await client.post("/subjects", json={"name": "Optics"})
    await client.post("/subjects", json={"name": "Topology"})
    body = (await client.get("/subjects")).json()
    assert len(body) == 2
    assert all(entry["node_count"] > 0 for entry in body)


async def test_cadence_patch_applies_only_supplied_fields(client: AsyncClient) -> None:
    """An omitted field is left alone; a deadline is cleared explicitly."""
    created = (await client.post("/subjects", json={"name": "Rust"})).json()
    patched = await client.patch(
        f"/subjects/{created['id']}/cadence",
        json={"days_per_week": 6, "deadline": "2026-12-01"},
    )
    assert patched.status_code == 200
    assert patched.json()["days_per_week"] == 6
    assert patched.json()["minutes_per_session"] == created["minutes_per_session"]
    assert patched.json()["deadline"] == "2026-12-01"

    cleared = await client.patch(
        f"/subjects/{created['id']}/cadence", json={"clear_deadline": True}
    )
    assert cleared.json()["deadline"] is None
    assert cleared.json()["days_per_week"] == 6


async def test_cadence_patch_rejects_out_of_range_values(client: AsyncClient) -> None:
    """Validation happens at the schema, before any service sees it."""
    created = (await client.post("/subjects", json={"name": "Go"})).json()
    response = await client.patch(f"/subjects/{created['id']}/cadence", json={"days_per_week": 99})
    assert response.status_code == 422
