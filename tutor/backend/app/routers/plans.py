"""Report, lesson-plan, and lesson endpoints."""

from __future__ import annotations

from fastapi import APIRouter, status

from app.deps import (
    AdapterDep,
    SessionDep,
    SettingsDep,
    bad_request,
    conflict,
    not_found,
    translate_load_error,
)
from app.mastery.graph import GraphCycleError
from app.repositories.plans import PlanRepository
from app.schemas.plan import (
    LessonRead,
    NextUnit,
    PlanCreate,
    PlanRead,
    UnitComplete,
    UnitCompleteResult,
    UnitInsert,
)
from app.schemas.report import CalibrationRead, ReportRead
from app.services.graph_loader import GraphNotReadyError, SubjectNotFoundError
from app.services.plan_service import (
    PlanService,
    UnitAlreadyClosed,
    UnitAlreadyScheduled,
    UnitItemMismatch,
)
from app.services.report_service import ReportService

router = APIRouter(tags=["plans"])


@router.get("/subjects/{subject_id}/report", response_model=ReportRead)
async def get_report(subject_id: str, session: SessionDep, settings: SettingsDep) -> ReportRead:
    """Where the learner stands: coverage, strengths, gaps, and what is blocking.

    :param subject_id: The subject to report on.
    :param session: The request's database session.
    :param settings: Runtime configuration.
    """
    service = ReportService(session, settings)
    try:
        return await service.build(subject_id)
    except SubjectNotFoundError as exc:
        raise translate_load_error(exc) from exc


@router.get("/subjects/{subject_id}/calibration", response_model=CalibrationRead)
async def get_calibration(
    subject_id: str, session: SessionDep, settings: SettingsDep
) -> CalibrationRead:
    """Whether recent retrieval success says the spacing should widen or tighten.

    :param subject_id: The subject to assess.
    :param session: The request's database session.
    :param settings: Runtime configuration.
    """
    service = ReportService(session, settings)
    return await service.calibrate(subject_id)


@router.post(
    "/subjects/{subject_id}/plan",
    response_model=PlanRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_plan(
    subject_id: str,
    payload: PlanCreate,
    session: SessionDep,
    adapter: AdapterDep,
    settings: SettingsDep,
) -> PlanRead:
    """Generate a prerequisite-respecting plan, superseding any current one.

    :param subject_id: The subject to plan.
    :param payload: Generation options.
    :param session: The request's database session.
    :param adapter: The LLM boundary.
    :param settings: Runtime configuration.
    """
    service = PlanService(session, adapter, settings)
    try:
        return await service.create(subject_id, payload)
    except (SubjectNotFoundError, GraphNotReadyError) as exc:
        raise translate_load_error(exc) from exc
    except GraphCycleError as exc:
        raise conflict(f"the stored graph is cyclic and cannot be sequenced: {exc}") from exc


@router.get("/subjects/{subject_id}/plan", response_model=PlanRead)
async def get_active_plan(
    subject_id: str, session: SessionDep, adapter: AdapterDep, settings: SettingsDep
) -> PlanRead:
    """The subject's current plan.

    :param subject_id: The subject to read.
    :param session: The request's database session.
    :param adapter: The LLM boundary.
    :param settings: Runtime configuration.
    """
    service = PlanService(session, adapter, settings)
    plan = await service.active(subject_id)
    if plan is None:
        raise not_found("this subject has no plan yet")
    return plan


@router.get("/plan/{plan_id}", response_model=PlanRead)
async def get_plan(
    plan_id: str, session: SessionDep, adapter: AdapterDep, settings: SettingsDep
) -> PlanRead:
    """One plan and its units.

    :param plan_id: The plan to read.
    :param session: The request's database session.
    :param adapter: The LLM boundary.
    :param settings: Runtime configuration.
    """
    service = PlanService(session, adapter, settings)
    try:
        return await service.read(plan_id)
    except LookupError as exc:
        raise not_found("plan not found") from exc


@router.post("/plan/{plan_id}/units", response_model=PlanRead, status_code=status.HTTP_201_CREATED)
async def insert_unit(
    plan_id: str,
    payload: UnitInsert,
    session: SessionDep,
    adapter: AdapterDep,
    settings: SettingsDep,
) -> PlanRead:
    """Add a unit for one concept, as early as its prerequisites allow.

    This is what accepting an ask-anything plan offer does.

    :param plan_id: The plan to insert into.
    :param payload: The concept to schedule.
    :param session: The request's database session.
    :param adapter: The LLM boundary.
    :param settings: Runtime configuration.
    """
    service = PlanService(session, adapter, settings)
    try:
        return await service.insert_unit(plan_id, payload.node_id)
    except UnitAlreadyScheduled as exc:
        raise conflict("this plan already has a pending unit for that concept") from exc
    except LookupError as exc:
        raise not_found("plan or concept not found") from exc


@router.get("/plan/{plan_id}/next", response_model=NextUnit)
async def next_unit(
    plan_id: str, session: SessionDep, adapter: AdapterDep, settings: SettingsDep
) -> NextUnit:
    """The next unit to study, with its exit check and lesson handle.

    :param plan_id: The plan being followed.
    :param session: The request's database session.
    :param adapter: The LLM boundary.
    :param settings: Runtime configuration.
    """
    service = PlanService(session, adapter, settings)
    try:
        return await service.next_unit(plan_id)
    except LookupError as exc:
        raise not_found("plan not found") from exc


@router.post("/plan/units/{unit_id}/complete", response_model=UnitCompleteResult)
async def complete_unit(
    unit_id: str,
    payload: UnitComplete,
    session: SessionDep,
    adapter: AdapterDep,
    settings: SettingsDep,
) -> UnitCompleteResult:
    """Submit a unit's exit check and close it.

    :param unit_id: The unit being closed.
    :param payload: The learner's answers.
    :param session: The request's database session.
    :param adapter: The LLM boundary.
    :param settings: Runtime configuration.
    """
    service = PlanService(session, adapter, settings)
    try:
        return await service.complete_unit(unit_id, payload)
    except UnitAlreadyClosed as exc:
        raise conflict("this unit has already been closed") from exc
    except UnitItemMismatch as exc:
        raise bad_request("that item is not part of this unit's exit check") from exc
    except LookupError as exc:
        raise not_found("unit or item not found") from exc


@router.get("/lessons/{lesson_id}", response_model=LessonRead)
async def get_lesson(lesson_id: str, session: SessionDep) -> LessonRead:
    """Fetch generated lesson prose.

    A plain GET of the persisted markdown, which is what makes a lesson readable
    offline: the SSE stream that produced it cannot be cached by a service worker.

    :param lesson_id: The lesson to read.
    :param session: The request's database session.
    """
    lesson = await PlanRepository(session).get_lesson(lesson_id)
    if lesson is None:
        raise not_found("lesson not found")
    return LessonRead.model_validate(lesson, from_attributes=True)
