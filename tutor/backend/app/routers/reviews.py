"""Review-queue endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.deps import (
    AdapterDep,
    SessionDep,
    SettingsDep,
    bad_request,
    conflict,
    not_found,
    translate_load_error,
)
from app.schemas.review import DueQueueRead, ReviewAnswer, ReviewItemRead, ReviewResult
from app.services.graph_loader import GraphNotReadyError, SubjectNotFoundError
from app.services.review_service import NotAReviewItem, NothingDue, ReviewService

router = APIRouter(tags=["reviews"])


@router.get("/subjects/{subject_id}/reviews", response_model=DueQueueRead)
async def due_queue(
    subject_id: str, session: SessionDep, adapter: AdapterDep, settings: SettingsDep
) -> DueQueueRead:
    """What is due for retrieval today, ordered and capped.

    :param subject_id: The subject to read.
    :param session: The request's database session.
    :param adapter: The LLM boundary.
    :param settings: Runtime configuration.
    """
    service = ReviewService(session, adapter, settings)
    try:
        return await service.due_queue(subject_id)
    except (SubjectNotFoundError, GraphNotReadyError) as exc:
        raise translate_load_error(exc) from exc


@router.get("/subjects/{subject_id}/reviews/next", response_model=ReviewItemRead)
async def next_review(
    subject_id: str, session: SessionDep, adapter: AdapterDep, settings: SettingsDep
) -> ReviewItemRead:
    """Draw a question for the most pressing due concept.

    :param subject_id: The subject to review.
    :param session: The request's database session.
    :param adapter: The LLM boundary.
    :param settings: Runtime configuration.
    """
    service = ReviewService(session, adapter, settings)
    try:
        return await service.next_item(subject_id)
    except NothingDue as exc:
        raise conflict("nothing is due for review right now") from exc
    except (SubjectNotFoundError, GraphNotReadyError) as exc:
        raise translate_load_error(exc) from exc


@router.post("/subjects/{subject_id}/reviews/answer", response_model=ReviewResult)
async def submit_review(
    subject_id: str,
    payload: ReviewAnswer,
    session: SessionDep,
    adapter: AdapterDep,
    settings: SettingsDep,
) -> ReviewResult:
    """Grade a review answer, update mastery, and reschedule the concept.

    :param subject_id: The subject being reviewed.
    :param payload: The answer.
    :param session: The request's database session.
    :param adapter: The LLM boundary.
    :param settings: Runtime configuration.
    """
    service = ReviewService(session, adapter, settings)
    try:
        return await service.answer(subject_id, payload.item_id, payload.answer)
    except NotAReviewItem as exc:
        raise bad_request("that item does not belong to this subject") from exc
    except LookupError as exc:
        raise not_found("item not found") from exc
