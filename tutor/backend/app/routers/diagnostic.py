"""Diagnostic endpoints."""

from __future__ import annotations

from fastapi import APIRouter, status

from app.deps import (
    AdapterDep,
    SessionDep,
    SettingsDep,
    bad_request,
    conflict,
    not_found,
)
from app.schemas.diagnostic import (
    AnswerResult,
    AnswerSubmit,
    DiagnosticStart,
    NextItem,
    SessionRead,
)
from app.services.diagnostic_service import (
    DiagnosticFinished,
    DiagnosticService,
    ItemMismatch,
)
from app.services.graph_loader import GraphNotReadyError, SubjectNotFoundError

router = APIRouter(tags=["diagnostic"])


@router.post(
    "/subjects/{subject_id}/diagnostic",
    response_model=SessionRead,
    status_code=status.HTTP_201_CREATED,
)
async def start_diagnostic(
    subject_id: str,
    payload: DiagnosticStart,
    session: SessionDep,
    adapter: AdapterDep,
    settings: SettingsDep,
) -> SessionRead:
    """Start a diagnostic, or resume one already in progress.

    :param subject_id: The subject to assess.
    :param payload: Optional overrides.
    :param session: The request's database session.
    :param adapter: The LLM boundary.
    :param settings: Runtime configuration.
    """
    service = DiagnosticService(session, adapter, settings)
    try:
        diagnostic = await service.start(subject_id, max_items=payload.max_items)
    except SubjectNotFoundError as exc:
        raise not_found("subject not found") from exc
    except GraphNotReadyError as exc:
        raise conflict(f"the concept graph is not ready yet (status: {exc.args[0]})") from exc
    return SessionRead(
        id=diagnostic.id,
        subject_id=diagnostic.subject_id,
        status=diagnostic.status,
        asked_count=diagnostic.asked_count,
        max_items=diagnostic.max_items,
        min_items=diagnostic.min_items,
        mean_confidence=0.0,
        stop_reason=diagnostic.stop_reason,
    )


@router.get("/diagnostic/{session_id}/next", response_model=NextItem)
async def next_item(
    session_id: str, session: SessionDep, adapter: AdapterDep, settings: SettingsDep
) -> NextItem:
    """The next adaptive question, or the reason there is not one.

    :param session_id: The diagnostic session.
    :param session: The request's database session.
    :param adapter: The LLM boundary.
    :param settings: Runtime configuration.
    """
    service = DiagnosticService(session, adapter, settings)
    try:
        return await service.next_item(session_id)
    except LookupError as exc:
        raise not_found("diagnostic session not found") from exc


@router.post("/diagnostic/{session_id}/answer", response_model=AnswerResult)
async def submit_answer(
    session_id: str,
    payload: AnswerSubmit,
    session: SessionDep,
    adapter: AdapterDep,
    settings: SettingsDep,
) -> AnswerResult:
    """Submit an answer and get graded feedback plus what it changed.

    :param session_id: The diagnostic session.
    :param payload: The answer.
    :param session: The request's database session.
    :param adapter: The LLM boundary.
    :param settings: Runtime configuration.
    """
    service = DiagnosticService(session, adapter, settings)
    try:
        return await service.answer(session_id, payload.item_id, payload.answer)
    except DiagnosticFinished as exc:
        raise conflict("this diagnostic has already finished") from exc
    except ItemMismatch as exc:
        raise bad_request("that item does not belong to this subject") from exc
    except LookupError as exc:
        raise not_found("diagnostic session or item not found") from exc
