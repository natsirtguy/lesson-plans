"""Shared fixtures.

Two guarantees this file exists to provide:

* **No network calls.** ``app_settings`` forces the fake LLM provider and the
  ``client`` fixture overrides the adapter dependency with a
  :class:`~app.llm.fake.FakeLLMAdapter`. Nothing in the suite can reach the API.
* **A real database.** Tests run against SQLite created from the ORM metadata, so
  constraints, defaults, and JSON columns behave as they do in production. Each
  test gets its own file-backed database in a temp directory, because an
  in-memory SQLite database is per-connection and would not survive the engine's
  connection pool.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings, get_settings
from app.db import Base, get_session
from app.llm import get_adapter
from app.llm.fake import FakeLLMAdapter
from app.main import create_app


@pytest.fixture
def app_settings(tmp_path: Path) -> Settings:
    """Settings pointed at a throwaway database with the fake LLM provider.

    :param tmp_path: pytest's per-test temporary directory.
    """
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        llm_provider="fake",
        anthropic_api_key="",
        prompt_caching=False,
    )


@pytest.fixture
async def engine(app_settings: Settings) -> AsyncIterator[AsyncEngine]:
    """An engine with the full schema created from ORM metadata.

    :param app_settings: Test settings supplying the database URL.
    """
    eng = create_async_engine(app_settings.database_url, future=True)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
def sessionmaker_(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """A session factory bound to the test engine.

    :param engine: The test engine.
    """
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


@pytest.fixture
async def session(
    sessionmaker_: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """A session for tests that drive services or repositories directly.

    :param sessionmaker_: The test session factory.
    """
    async with sessionmaker_() as db:
        yield db


@pytest.fixture
def fake_llm() -> FakeLLMAdapter:
    """The adapter the app under test will use, so tests can set hooks on it."""
    return FakeLLMAdapter()


@pytest.fixture
def configured_app(
    app_settings: Settings,
    sessionmaker_: async_sessionmaker[AsyncSession],
    fake_llm: FakeLLMAdapter,
) -> Iterator[object]:
    """The FastAPI app with database and LLM dependencies overridden.

    :param app_settings: Test settings.
    :param sessionmaker_: The test session factory.
    :param fake_llm: The offline adapter to inject.
    """
    application = create_app(app_settings)

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with sessionmaker_() as db:
            yield db

    application.dependency_overrides[get_session] = override_session
    application.dependency_overrides[get_adapter] = lambda: fake_llm
    application.dependency_overrides[get_settings] = lambda: app_settings
    yield application
    application.dependency_overrides.clear()


@pytest.fixture
async def client(configured_app: object) -> AsyncIterator[AsyncClient]:
    """An HTTP client wired straight to the ASGI app, with no sockets involved.

    :param configured_app: The dependency-overridden application.
    """
    transport = ASGITransport(app=configured_app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
