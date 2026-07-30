"""Subject and graph endpoints.

Routers parse input, delegate, and shape the response. The only logic here is
mapping service exceptions onto HTTP statuses.
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, status

from app.deps import (
    AdapterDep,
    ParamsDep,
    SessionDep,
    SessionFactoryDep,
    SettingsDep,
    not_found,
    translate_load_error,
)
from app.schemas.graph import GraphRead
from app.schemas.subject import CadenceUpdate, SubjectCreate, SubjectRead
from app.services.graph_loader import GraphLoader, SubjectNotFoundError
from app.services.graph_service import render_graph
from app.services.subject_service import SubjectService, generate_graph_in_background

router = APIRouter(prefix="/subjects", tags=["subjects"])


@router.post("", response_model=SubjectRead, status_code=status.HTTP_201_CREATED)
async def create_subject(
    payload: SubjectCreate,
    background: BackgroundTasks,
    session: SessionDep,
    adapter: AdapterDep,
    settings: SettingsDep,
    factory: SessionFactoryDep,
) -> SubjectRead:
    """Create a subject and start building its concept graph.

    Returns immediately with ``graph_status`` set to pending; decomposing a subject
    is a slow reasoning call, and holding the request open for it would risk a
    client timeout on the very first thing the learner does. Poll
    ``GET /subjects/{id}`` for readiness.

    :param payload: The subject to create.
    :param background: FastAPI's background-task registry.
    :param session: The request's database session.
    :param adapter: The LLM boundary.
    :param settings: Runtime configuration.
    :param factory: Session factory for the background task.
    """
    service = SubjectService(session, adapter, settings)
    subject = await service.create(payload)
    background.add_task(generate_graph_in_background, factory, adapter, settings, subject.id)
    return SubjectRead.model_validate(subject, from_attributes=True)


@router.get("", response_model=list[SubjectRead])
async def list_subjects(
    session: SessionDep, adapter: AdapterDep, settings: SettingsDep
) -> list[SubjectRead]:
    """Every subject the learner has started, newest first.

    :param session: The request's database session.
    :param adapter: The LLM boundary.
    :param settings: Runtime configuration.
    """
    service = SubjectService(session, adapter, settings)
    return [
        SubjectRead.model_validate(
            {**_subject_fields(subject), "node_count": count},
        )
        for subject, count in await service.list_subjects()
    ]


@router.get("/{subject_id}", response_model=SubjectRead)
async def get_subject(subject_id: str, session: SessionDep, params: ParamsDep) -> SubjectRead:
    """One subject's metadata, cadence, and graph status.

    :param subject_id: The subject to read.
    :param session: The request's database session.
    :param params: Mastery model constants.
    """
    loader = GraphLoader(session, params)
    try:
        loaded = await loader.load(subject_id, apply_decay=False)
    except SubjectNotFoundError as exc:
        raise not_found("subject not found") from exc
    return SubjectRead.model_validate(
        {**_subject_fields(loaded.subject), "node_count": len(loaded.graph)},
    )


@router.get("/{subject_id}/graph", response_model=GraphRead)
async def get_graph(subject_id: str, session: SessionDep, params: ParamsDep) -> GraphRead:
    """A subject's concepts, prerequisite edges, and current mastery.

    :param subject_id: The subject to read.
    :param session: The request's database session.
    :param params: Mastery model constants.
    """
    loader = GraphLoader(session, params)
    try:
        loaded = await loader.load(subject_id)
    except SubjectNotFoundError as exc:
        raise translate_load_error(exc) from exc
    await session.commit()
    return render_graph(loaded, params)


@router.patch("/{subject_id}/cadence", response_model=SubjectRead)
async def patch_cadence(
    subject_id: str,
    payload: CadenceUpdate,
    session: SessionDep,
    adapter: AdapterDep,
    settings: SettingsDep,
) -> SubjectRead:
    """Change days per week, minutes per session, daily cap, or deadline.

    :param subject_id: The subject to change.
    :param payload: Fields to change; omitted fields are left alone.
    :param session: The request's database session.
    :param adapter: The LLM boundary.
    :param settings: Runtime configuration.
    """
    service = SubjectService(session, adapter, settings)
    try:
        subject = await service.update_cadence(subject_id, payload)
    except LookupError as exc:
        raise not_found("subject not found") from exc
    return SubjectRead.model_validate(_subject_fields(subject))


def _subject_fields(subject: object) -> dict[str, object]:
    """Extract the subject fields the read schema needs.

    Done explicitly rather than by attribute scraping so that adding a column does
    not silently widen the API surface.

    :param subject: The subject row.
    """
    return {
        field: getattr(subject, field)
        for field in (
            "id",
            "name",
            "description",
            "graph_version",
            "graph_status",
            "graph_error",
            "days_per_week",
            "minutes_per_session",
            "daily_review_cap",
            "deadline",
            "target_retention",
            "recovery_aware",
            "created_at",
        )
    }
