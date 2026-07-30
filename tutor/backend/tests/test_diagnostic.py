"""Tests for the diagnostic loop, item generation, and grading."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.llm.fake import FakeLLMAdapter
from app.mastery.state import MasteryParams
from app.models.assessment import ItemResponse, QuizItem
from app.models.enums import ItemFormat, SessionStatus
from app.models.graph import MasteryRecord
from app.scheduling.grading import Grade, grade_from_score
from app.services.diagnostic_service import DiagnosticFinished, DiagnosticService
from app.services.item_service import cache_key, choose_format, level_for
from tests.test_subjects import build_subject


async def run_session(
    client: AsyncClient, subject_id: str, *, answer: str, limit: int = 40
) -> list[Any]:
    """Drive a diagnostic to completion, answering every item the same way.

    :param client: The HTTP client.
    :param subject_id: The subject to assess.
    :param answer: The answer to submit for every item.
    :param limit: Safety bound so a non-terminating loop fails the test.
    """
    started = (await client.post(f"/subjects/{subject_id}/diagnostic", json={})).json()
    results: list[Any] = []
    for _ in range(limit):
        nxt = (await client.get(f"/diagnostic/{started['id']}/next")).json()
        if nxt["finished"]:
            break
        submitted = await client.post(
            f"/diagnostic/{started['id']}/answer",
            json={"item_id": nxt["item"]["id"], "answer": answer},
        )
        assert submitted.status_code == 200
        results.append(submitted.json())
    else:  # pragma: no cover - only reached if the stopping rule fails
        pytest.fail("the diagnostic did not stop within the safety bound")
    return results


# --- item selection helpers ----------------------------------------------------


@pytest.mark.parametrize(
    ("mastery", "expected"),
    [(0.0, "novice"), (0.4, "developing"), (0.7, "proficient"), (0.99, "advanced")],
)
def test_level_buckets_are_ordered(mastery: float, expected: str) -> None:
    """A learner's level bucket tracks their mastery."""
    assert level_for(mastery) == expected


def test_format_moves_from_recognition_to_production_to_diagnosis() -> None:
    """First contact is recognition; harder repeat contact demands more."""
    assert choose_format(difficulty=3, observations=0) == ItemFormat.MULTIPLE_CHOICE
    assert choose_format(difficulty=1, observations=5) == ItemFormat.MULTIPLE_CHOICE
    assert choose_format(difficulty=3, observations=2) == ItemFormat.SHORT_FREE_TEXT
    assert choose_format(difficulty=5, observations=2) == ItemFormat.EXPLAIN_WHY_WRONG


def test_cache_key_separates_level_and_difficulty() -> None:
    """A beginner and an expert must not share an item pitched at one of them."""
    base = cache_key("n1", 3, "novice", "multiple_choice")
    assert base != cache_key("n1", 3, "advanced", "multiple_choice")
    assert base != cache_key("n1", 4, "novice", "multiple_choice")
    assert base != cache_key("n2", 3, "novice", "multiple_choice")
    assert base == cache_key("n1", 3, "novice", "multiple_choice")


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0.0, Grade.AGAIN),
        (0.59, Grade.AGAIN),
        (0.6, Grade.HARD),
        (0.74, Grade.HARD),
        (0.75, Grade.GOOD),
        (0.89, Grade.GOOD),
        (0.9, Grade.EASY),
        (1.0, Grade.EASY),
    ],
)
def test_grades_come_from_the_rubric_score(score: float, expected: Grade) -> None:
    """The four-point scale is derived, not self-reported."""
    assert grade_from_score(score) == expected


# --- the loop ------------------------------------------------------------------


async def test_a_correct_answer_raises_mastery_and_informs_prerequisites(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """One answer moves the concept asked about and the ones it implies."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    service = DiagnosticService(session, fake_llm, app_settings)
    diagnostic = await service.start(subject_id)

    nxt = await service.next_item(diagnostic.id)
    assert nxt.item is not None
    result = await service.answer(diagnostic.id, nxt.item.id, "0")

    direct = next(c for c in result.changes if not c.propagated)
    assert direct.mastery_after > direct.mastery_before
    assert direct.confidence_after > 0


async def test_a_wrong_answer_lowers_mastery(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """The sign of the update follows the answer."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    service = DiagnosticService(session, fake_llm, app_settings)
    diagnostic = await service.start(subject_id)
    nxt = await service.next_item(diagnostic.id)
    assert nxt.item is not None
    result = await service.answer(diagnostic.id, nxt.item.id, "3")
    direct = next(c for c in result.changes if not c.propagated)
    assert direct.mastery_after < direct.mastery_before
    assert result.correct is False


async def test_the_session_stops_within_its_item_cap(client: AsyncClient) -> None:
    """The stopping rule terminates, and never exceeds the cap."""
    created = (await client.post("/subjects", json={"name": "Kubernetes"})).json()
    results = await run_session(client, created["id"], answer="0")
    assert 0 < len(results) <= results[-1]["session"]["max_items"]
    assert results[-1]["session"]["asked_count"] == len(results)


async def test_a_finished_session_refuses_further_answers(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """Answering a closed session is an error, not a silent extra data point."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    service = DiagnosticService(session, fake_llm, app_settings)
    diagnostic = await service.start(subject_id, max_items=1)
    nxt = await service.next_item(diagnostic.id)
    assert nxt.item is not None
    await service.answer(diagnostic.id, nxt.item.id, "0")

    follow_up = await service.next_item(diagnostic.id)
    assert follow_up.finished is True
    with pytest.raises(DiagnosticFinished):
        await service.answer(diagnostic.id, nxt.item.id, "0")


async def test_starting_twice_resumes_the_same_session(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """A closed tab must not throw away the answers already given."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    service = DiagnosticService(session, fake_llm, app_settings)
    first = await service.start(subject_id)
    second = await service.start(subject_id)
    assert first.id == second.id


async def test_the_same_concept_is_not_asked_twice_in_one_session(client: AsyncClient) -> None:
    """A session that re-asks the same concept is wasting the learner's questions."""
    created = (await client.post("/subjects", json={"name": "Optics"})).json()
    started = (await client.post(f"/subjects/{created['id']}/diagnostic", json={})).json()
    seen: list[str] = []
    for _ in range(40):
        nxt = (await client.get(f"/diagnostic/{started['id']}/next")).json()
        if nxt["finished"]:
            break
        seen.append(nxt["item"]["node_id"])
        await client.post(
            f"/diagnostic/{started['id']}/answer",
            json={"item_id": nxt["item"]["id"], "answer": "0"},
        )
    assert len(seen) == len(set(seen))


async def test_every_answer_is_recorded_with_its_grade(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """The response log is what the mastery replay later depends on."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    service = DiagnosticService(session, fake_llm, app_settings)
    diagnostic = await service.start(subject_id, max_items=3)
    for _ in range(3):
        nxt = await service.next_item(diagnostic.id)
        if nxt.item is None:
            break
        await service.answer(diagnostic.id, nxt.item.id, "0")

    responses = list((await session.execute(select(ItemResponse))).scalars())
    assert len(responses) == 3
    assert all(response.session_id == diagnostic.id for response in responses)
    assert all(1 <= response.grade <= 4 for response in responses)
    assert all(response.mastery_after is not None for response in responses)


async def test_items_are_cached_rather_than_regenerated(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """Asking for the same item twice must not cost a second generation."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    service = DiagnosticService(session, fake_llm, app_settings)
    first = await service.start(subject_id)
    nxt = await service.next_item(first.id)
    assert nxt.item is not None

    generations = sum(1 for call in fake_llm.calls if call.task == "item_generation")
    # Fetching the next item again without answering re-selects the same concept.
    again = await service.next_item(first.id)
    assert again.item is not None and again.item.id == nxt.item.id
    assert sum(1 for call in fake_llm.calls if call.task == "item_generation") == generations


async def test_multiple_choice_is_graded_without_a_model_call(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """Comparing two integers does not need a language model."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    service = DiagnosticService(session, fake_llm, app_settings)
    diagnostic = await service.start(subject_id)
    nxt = await service.next_item(diagnostic.id)
    assert nxt.item is not None and nxt.item.item_format == ItemFormat.MULTIPLE_CHOICE

    before = sum(1 for call in fake_llm.calls if call.task == "grading")
    await service.answer(diagnostic.id, nxt.item.id, "0")
    assert sum(1 for call in fake_llm.calls if call.task == "grading") == before


async def test_a_wrong_multiple_choice_records_the_distractor_chosen(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """Distractors encode specific misconceptions, so which one was picked matters."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    service = DiagnosticService(session, fake_llm, app_settings)
    diagnostic = await service.start(subject_id)
    nxt = await service.next_item(diagnostic.id)
    assert nxt.item is not None
    result = await service.answer(diagnostic.id, nxt.item.id, "2")
    assert result.misconception == nxt.item.choices[2]


async def test_mastery_records_are_written_back(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """The estimate has to survive the request that produced it."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    service = DiagnosticService(session, fake_llm, app_settings)
    diagnostic = await service.start(subject_id)
    nxt = await service.next_item(diagnostic.id)
    assert nxt.item is not None
    await service.answer(diagnostic.id, nxt.item.id, "0")

    record = (
        (
            await session.execute(
                select(MasteryRecord).where(MasteryRecord.node_id == nxt.item.node_id)
            )
        )
        .scalars()
        .one()
    )
    assert record.direct_observations == 1
    assert record.last_seen_at is not None


async def test_a_strong_learner_ends_with_higher_coverage_than_a_weak_one(
    client: AsyncClient,
) -> None:
    """End to end, the diagnostic distinguishes learners.

    Answering every multiple-choice item correctly versus wrongly is a crude
    synthetic learner, but it exercises the whole path -- selection, generation,
    grading, update, propagation, persistence -- and the estimates must separate.
    """
    strong = (await client.post("/subjects", json={"name": "Strong Subject"})).json()
    weak = (await client.post("/subjects", json={"name": "Weak Subject"})).json()

    await run_session(client, strong["id"], answer="0")
    await run_session(client, weak["id"], answer="3")

    strong_graph = (await client.get(f"/subjects/{strong['id']}/graph")).json()
    weak_graph = (await client.get(f"/subjects/{weak['id']}/graph")).json()

    def mean(graph: Any) -> float:
        nodes = graph["nodes"]
        return float(sum(node["mastery"] for node in nodes) / len(nodes))

    assert mean(strong_graph) > mean(weak_graph) + 0.2


# --- endpoints -----------------------------------------------------------------


async def test_the_item_payload_never_leaks_the_answer(client: AsyncClient) -> None:
    """The client must not be able to grade itself."""
    created = (await client.post("/subjects", json={"name": "Rust"})).json()
    started = (await client.post(f"/subjects/{created['id']}/diagnostic", json={})).json()
    nxt = (await client.get(f"/diagnostic/{started['id']}/next")).json()
    assert "answer_key" not in nxt["item"]
    assert "correct_choice" not in nxt["item"]
    assert "rubric" not in nxt["item"]


async def test_the_answer_key_is_released_only_after_answering(
    client: AsyncClient,
) -> None:
    """Feedback is worth more when it names the right answer."""
    created = (await client.post("/subjects", json={"name": "Go"})).json()
    started = (await client.post(f"/subjects/{created['id']}/diagnostic", json={})).json()
    nxt = (await client.get(f"/diagnostic/{started['id']}/next")).json()
    result = (
        await client.post(
            f"/diagnostic/{started['id']}/answer",
            json={"item_id": nxt["item"]["id"], "answer": "0"},
        )
    ).json()
    assert result["answer_key"]
    assert result["feedback"]


async def test_diagnostic_on_an_unknown_subject_is_a_404(client: AsyncClient) -> None:
    """A bad id is a 404."""
    response = await client.post("/subjects/nope/diagnostic", json={})
    assert response.status_code == 404


async def test_an_item_from_another_subject_is_rejected(client: AsyncClient) -> None:
    """Answers are scoped to the session's subject."""
    first = (await client.post("/subjects", json={"name": "Alpha"})).json()
    second = (await client.post("/subjects", json={"name": "Beta"})).json()
    first_session = (await client.post(f"/subjects/{first['id']}/diagnostic", json={})).json()
    second_session = (await client.post(f"/subjects/{second['id']}/diagnostic", json={})).json()
    foreign = (await client.get(f"/diagnostic/{second_session['id']}/next")).json()

    response = await client.post(
        f"/diagnostic/{first_session['id']}/answer",
        json={"item_id": foreign["item"]["id"], "answer": "0"},
    )
    assert response.status_code == 400


async def test_generated_items_carry_their_rubric(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """Grading has to be reproducible, so the criteria travel with the item."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    service = DiagnosticService(session, fake_llm, app_settings)
    diagnostic = await service.start(subject_id)
    await service.next_item(diagnostic.id)

    item = (await session.execute(select(QuizItem))).scalars().first()
    assert item is not None
    assert item.rubric
    assert item.answer_key
    assert item.node_id


async def test_a_completed_session_reports_why_it_stopped(
    session: AsyncSession, fake_llm: FakeLLMAdapter, app_settings: Settings
) -> None:
    """The stop reason is recorded, for tuning the thresholds later."""
    subject_id = await build_subject(session, fake_llm, app_settings)
    service = DiagnosticService(session, fake_llm, app_settings)
    diagnostic = await service.start(subject_id, max_items=2)
    for _ in range(2):
        nxt = await service.next_item(diagnostic.id)
        if nxt.item is None:
            break
        await service.answer(diagnostic.id, nxt.item.id, "0")

    await session.refresh(diagnostic)
    assert diagnostic.status == SessionStatus.COMPLETE
    assert diagnostic.stop_reason in {"max_items", "confidence_target"}
    assert diagnostic.final_mean_confidence is not None


def test_mastery_params_come_from_settings(app_settings: Settings) -> None:
    """The tunables the diagnostic uses are the configured ones."""
    params = MasteryParams.from_settings(app_settings)
    assert params.propagation_decay == app_settings.propagation_decay
    assert params.mastery_threshold == app_settings.mastery_threshold
