"""FastAPI dependencies.

Every dependency here is overridable in tests, which is what keeps the suite off
the network and off the developer's database.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.db import get_session, get_sessionmaker
from app.llm import get_adapter
from app.llm.base import LLMAdapter
from app.mastery.state import MasteryParams
from app.services.graph_loader import GraphNotReadyError, SubjectNotFoundError


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the session factory background tasks should open sessions from.

    A background task outlives the request that scheduled it, so it cannot reuse
    the request's session. Exposed as a dependency so tests can point it at their
    own throwaway database.
    """
    return get_sessionmaker()


SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
AdapterDep = Annotated[LLMAdapter, Depends(get_adapter)]
SessionFactoryDep = Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)]


def get_mastery_params(settings: SettingsDep) -> MasteryParams:
    """Build the mastery model constants from configuration.

    :param settings: Runtime configuration.
    """
    return MasteryParams.from_settings(settings)


ParamsDep = Annotated[MasteryParams, Depends(get_mastery_params)]


def not_found(detail: str) -> HTTPException:
    """Build a 404.

    :param detail: Message for the client.
    """
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def conflict(detail: str) -> HTTPException:
    """Build a 409.

    :param detail: Message for the client.
    """
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def bad_request(detail: str) -> HTTPException:
    """Build a 400.

    :param detail: Message for the client.
    """
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def translate_load_error(exc: Exception) -> HTTPException:
    """Map a graph-loading failure onto the right HTTP status.

    :param exc: The failure raised by the loader.
    """
    if isinstance(exc, SubjectNotFoundError):
        return not_found("subject not found")
    if isinstance(exc, GraphNotReadyError):
        return conflict(f"the concept graph is not ready yet (status: {exc.args[0]})")
    raise exc
