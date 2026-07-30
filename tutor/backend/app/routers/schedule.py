"""Study-schedule endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.deps import (
    AdapterDep,
    SessionDep,
    SettingsDep,
    conflict,
    not_found,
    translate_load_error,
)
from app.schemas.schedule import ScheduleRead, ScheduleRequest, SessionComplete, SessionRead
from app.services.graph_loader import GraphNotReadyError, SubjectNotFoundError
from app.services.schedule_service import ScheduleService, SessionAlreadyClosed

router = APIRouter(tags=["schedule"])


@router.post("/subjects/{subject_id}/schedule", response_model=ScheduleRead)
async def build_schedule(
    subject_id: str,
    payload: ScheduleRequest,
    session: SessionDep,
    adapter: AdapterDep,
    settings: SettingsDep,
) -> ScheduleRead:
    """Generate a rolling schedule from the cadence, the due queue, and the plan.

    :param subject_id: The subject to schedule.
    :param payload: Horizon and persistence options.
    :param session: The request's database session.
    :param adapter: The LLM boundary.
    :param settings: Runtime configuration.
    """
    service = ScheduleService(session, adapter, settings)
    try:
        return await service.build(subject_id, payload)
    except (SubjectNotFoundError, GraphNotReadyError) as exc:
        raise translate_load_error(exc) from exc


@router.get("/subjects/{subject_id}/schedule", response_model=ScheduleRead)
async def get_schedule(
    subject_id: str, session: SessionDep, adapter: AdapterDep, settings: SettingsDep
) -> ScheduleRead:
    """The current rolling schedule, recomputed without replacing what is stored.

    :param subject_id: The subject to read.
    :param session: The request's database session.
    :param adapter: The LLM boundary.
    :param settings: Runtime configuration.
    """
    service = ScheduleService(session, adapter, settings)
    try:
        return await service.build(subject_id, ScheduleRequest(persist=False))
    except (SubjectNotFoundError, GraphNotReadyError) as exc:
        raise translate_load_error(exc) from exc


@router.post("/sessions/{session_id}/complete", response_model=SessionRead)
async def complete_session(
    session_id: str,
    payload: SessionComplete,
    session: SessionDep,
    adapter: AdapterDep,
    settings: SettingsDep,
) -> SessionRead:
    """Mark a planned sitting as done.

    :param session_id: The sitting to close.
    :param payload: Anything the learner wants recorded against it.
    :param session: The request's database session.
    :param adapter: The LLM boundary.
    :param settings: Runtime configuration.
    """
    service = ScheduleService(session, adapter, settings)
    try:
        return await service.complete_session(session_id, payload.notes)
    except SessionAlreadyClosed as exc:
        raise conflict("this session has already been closed") from exc
    except LookupError as exc:
        raise not_found("session not found") from exc
