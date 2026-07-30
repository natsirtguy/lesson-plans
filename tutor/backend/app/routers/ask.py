"""Ask-anything and lesson-streaming endpoints.

Both stream over SSE, and both take a session *factory* rather than the request's
session. A streaming response body runs after FastAPI has torn down the request's
`yield`-based dependencies, so a service that wrote through the request session
would be writing through a closed one. The factory dependency already exists for
background tasks and is overridable in tests the same way.

The subject or lesson is resolved in the request itself, so a missing id is a plain
404 rather than an ``error`` frame inside a 200 response.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.deps import (
    AdapterDep,
    ParamsDep,
    SessionDep,
    SessionFactoryDep,
    SettingsDep,
    not_found,
    translate_load_error,
)
from app.repositories.plans import PlanRepository
from app.schemas.ask import AskRequest
from app.services.ask_service import AskService
from app.services.graph_loader import GraphLoader, GraphNotReadyError, SubjectNotFoundError
from app.services.lesson_service import LessonStreamer
from app.sse import stream

router = APIRouter(tags=["ask"])


@router.post("/subjects/{subject_id}/ask")
async def ask(
    subject_id: str,
    payload: AskRequest,
    session: SessionDep,
    params: ParamsDep,
    factory: SessionFactoryDep,
    adapter: AdapterDep,
    settings: SettingsDep,
) -> object:
    """Answer a free-form question, streaming the result as SSE.

    Emits ``meta`` (classification and lesson handle), then ``delta`` frames, then
    ``done`` (which carries the plan offer).

    :param subject_id: The subject the question is asked against.
    :param payload: The question.
    :param session: The request's database session, used only to resolve the subject.
    :param params: Mastery model constants.
    :param factory: Session factory the stream writes through.
    :param adapter: The LLM boundary.
    :param settings: Runtime configuration.
    """
    try:
        await GraphLoader(session, params).require_ready(subject_id)
    except (SubjectNotFoundError, GraphNotReadyError) as exc:
        raise translate_load_error(exc) from exc
    service = AskService(factory, adapter, settings)
    return stream(service.stream(subject_id, payload.question))


@router.post("/lessons/{lesson_id}/stream")
async def stream_lesson(
    lesson_id: str,
    session: SessionDep,
    factory: SessionFactoryDep,
    adapter: AdapterDep,
    settings: SettingsDep,
) -> object:
    """Stream a lesson's prose, generating it if the row is still empty.

    A POST rather than a GET because it has a side effect: the generated markdown
    is persisted into the row so that a later ``GET /lessons/{id}`` -- and the
    service worker's cache -- can serve it without regenerating.

    :param lesson_id: The lesson to stream.
    :param session: The request's database session, used only to resolve the lesson.
    :param factory: Session factory the stream writes through.
    :param adapter: The LLM boundary.
    :param settings: Runtime configuration.
    """
    if await PlanRepository(session).get_lesson(lesson_id) is None:
        raise not_found("lesson not found")
    streamer = LessonStreamer(factory, adapter, settings)
    return stream(streamer.stream(lesson_id))
