"""Graph refinement endpoints.

The split across three endpoints is the approval guarantee made structural:
``/graph/refine`` can only propose, ``/changesets`` can only commit what was
explicitly accepted, and there is no endpoint that does both.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status
from pydantic import TypeAdapter

from app.deps import (
    AdapterDep,
    ParamsDep,
    SessionDep,
    SettingsDep,
    bad_request,
    conflict,
    not_found,
)
from app.llm.base import LLMError
from app.schemas.changeset import (
    ChangesetPreview,
    ChangesetRead,
    ChangesetSummary,
    CommitRequest,
    Operation,
    RefineRequest,
    SuggestionRead,
)
from app.services.changeset_service import (
    ChangesetRejected,
    ChangesetService,
    IncompleteReview,
)
from app.services.graph_loader import SubjectNotFoundError
from app.services.suggestion_service import SuggestionService

router = APIRouter(tags=["graph refinement"])

_OPERATIONS: TypeAdapter[list[Operation]] = TypeAdapter(list[Operation])


@router.post(
    "/subjects/{subject_id}/graph/refine",
    response_model=ChangesetRead,
    status_code=status.HTTP_201_CREATED,
)
async def refine_graph(
    subject_id: str,
    payload: RefineRequest,
    session: SessionDep,
    adapter: AdapterDep,
    settings: SettingsDep,
) -> ChangesetRead:
    """Turn a plain-language request into a proposed changeset.

    Commits nothing. Every operation comes back awaiting a verdict.

    :param subject_id: The subject to refine.
    :param payload: The learner's request.
    :param session: The request's database session.
    :param adapter: The LLM boundary.
    :param settings: Runtime configuration.
    """
    service = ChangesetService(session, adapter, settings)
    try:
        changeset = await service.propose(subject_id, payload.request)
    except SubjectNotFoundError as exc:
        raise not_found("subject not found") from exc
    except LLMError as exc:
        raise bad_request(f"could not produce a changeset: {exc}") from exc
    return await service.read(changeset.id)


@router.get("/changesets/{changeset_id}", response_model=ChangesetRead)
async def get_changeset(
    changeset_id: str, session: SessionDep, adapter: AdapterDep, settings: SettingsDep
) -> ChangesetRead:
    """One changeset with its operations and their verdicts.

    :param changeset_id: The changeset to read.
    :param session: The request's database session.
    :param adapter: The LLM boundary.
    :param settings: Runtime configuration.
    """
    service = ChangesetService(session, adapter, settings)
    try:
        return await service.read(changeset_id)
    except LookupError as exc:
        raise not_found("changeset not found") from exc


@router.get("/changesets/{changeset_id}/preview", response_model=ChangesetPreview)
async def preview_changeset(
    changeset_id: str,
    session: SessionDep,
    adapter: AdapterDep,
    settings: SettingsDep,
    accept: Annotated[list[str] | None, Query()] = None,
) -> ChangesetPreview:
    """Show the graph a subset of operations would produce, without committing.

    :param changeset_id: The changeset to preview.
    :param session: The request's database session.
    :param adapter: The LLM boundary.
    :param settings: Runtime configuration.
    :param accept: Operation ids to include; all of them when omitted.
    """
    service = ChangesetService(session, adapter, settings)
    try:
        return await service.preview(changeset_id, set(accept) if accept else None)
    except LookupError as exc:
        raise not_found("changeset not found") from exc


@router.post("/subjects/{subject_id}/changesets/{changeset_id}", response_model=ChangesetRead)
async def commit_changeset(
    subject_id: str,
    changeset_id: str,
    payload: CommitRequest,
    session: SessionDep,
    adapter: AdapterDep,
    settings: SettingsDep,
) -> ChangesetRead:
    """Commit the operations the learner accepted.

    Every operation must carry a verdict. A rejected changeset stays in the log with
    the reason it was refused.

    :param subject_id: The subject being changed.
    :param changeset_id: The changeset to commit.
    :param payload: A verdict per operation.
    :param session: The request's database session.
    :param adapter: The LLM boundary.
    :param settings: Runtime configuration.
    """
    service = ChangesetService(session, adapter, settings)
    try:
        await service.commit(changeset_id, payload)
    except LookupError as exc:
        raise not_found("changeset not found") from exc
    except IncompleteReview as exc:
        raise bad_request(str(exc)) from exc
    except ChangesetRejected as exc:
        raise conflict(str(exc)) from exc
    return await service.read(changeset_id)


@router.get("/subjects/{subject_id}/changesets", response_model=list[ChangesetSummary])
async def list_changesets(
    subject_id: str, session: SessionDep, adapter: AdapterDep, settings: SettingsDep
) -> list[ChangesetSummary]:
    """The subject's changeset log, newest first.

    :param subject_id: The subject to read.
    :param session: The request's database session.
    :param adapter: The LLM boundary.
    :param settings: Runtime configuration.
    """
    service = ChangesetService(session, adapter, settings)
    return await service.log(subject_id)


@router.get("/subjects/{subject_id}/suggestions", response_model=list[SuggestionRead])
async def list_suggestions(
    subject_id: str, session: SessionDep, params: ParamsDep
) -> list[SuggestionRead]:
    """Proactive proposals that the graph is wrong.

    :param subject_id: The subject to inspect.
    :param session: The request's database session.
    :param params: Mastery model constants.
    """
    service = SuggestionService(session, params)
    try:
        suggestions = await service.open_for(subject_id)
    except SubjectNotFoundError as exc:
        raise not_found("subject not found") from exc
    return [
        SuggestionRead(
            id=suggestion.id,
            kind=suggestion.kind,
            summary=suggestion.summary,
            evidence=suggestion.evidence,
            node_id=suggestion.node_id,
            status=suggestion.status,
            created_at=suggestion.created_at,
            operations=_OPERATIONS.validate_python(suggestion.proposed_ops),
        )
        for suggestion in suggestions
    ]


@router.post("/suggestions/{suggestion_id}/dismiss", status_code=status.HTTP_204_NO_CONTENT)
async def dismiss_suggestion(suggestion_id: str, session: SessionDep, params: ParamsDep) -> None:
    """Mark a suggestion as not worth acting on, so it is not raised again.

    :param suggestion_id: The suggestion to dismiss.
    :param session: The request's database session.
    :param params: Mastery model constants.
    """
    service = SuggestionService(session, params)
    try:
        await service.dismiss(suggestion_id)
    except LookupError as exc:
        raise not_found("suggestion not found") from exc
