"""Database engine, session factory, and the declarative base."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import DateTime, MetaData, String, TypeDecorator, event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config import Settings, get_settings

#: Explicit naming convention so Alembic autogenerate produces stable constraint
#: names across SQLite and Postgres.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class UTCDateTime(TypeDecorator[datetime]):
    """A timezone-aware timestamp that survives a SQLite round trip.

    SQLite has no timestamp type, so it hands back naive datetimes regardless of
    ``timezone=True`` -- and comparing one of those to an aware value raises. Since
    the whole app computes elapsed time between stored timestamps and "now", that
    would turn every decay calculation into a crash on the dev database and pass
    silently on Postgres. Coercing on the way in and out means the rest of the code
    can assume UTC-aware everywhere.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: object) -> datetime | None:
        """Normalize a value being written to UTC.

        :param value: The timestamp to store.
        :param dialect: The active SQLAlchemy dialect.
        """
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: object) -> datetime | None:
        """Attach UTC to a value read back without a timezone.

        :param value: The timestamp as the driver returned it.
        :param dialect: The active SQLAlchemy dialect.
        """
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class Base(DeclarativeBase):
    """Declarative base for every ORM model."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def new_id() -> str:
    """Generate a fresh opaque identifier."""
    return str(uuid.uuid4())


def utcnow() -> datetime:
    """Return the current time as a timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class IdMixin:
    """Primary key as an application-generated UUID string."""

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)


class TimestampMixin:
    """Creation and update timestamps, both timezone-aware."""

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False
    )


class _DBAPICursor(Protocol):
    """The slice of the DBAPI cursor interface needed to set a pragma."""

    def execute(self, statement: str) -> object:
        """Execute a statement.

        :param statement: SQL to run.
        """
        ...

    def close(self) -> None:
        """Release the cursor."""
        ...


class _DBAPIConnection(Protocol):
    """The slice of the DBAPI connection interface needed to set a pragma."""

    def cursor(self) -> _DBAPICursor:
        """Open a cursor."""
        ...


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Return the process-wide async engine, creating it on first use."""
    global _engine
    if _engine is None:
        _engine = build_engine(get_settings())
    return _engine


def build_engine(settings: Settings) -> AsyncEngine:
    """Create an engine for the given settings.

    :param settings: Configuration supplying the database URL and echo flag.
    """
    kwargs: dict[str, Any] = {"echo": settings.debug, "future": True}
    if settings.is_sqlite:
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs["pool_pre_ping"] = True
    engine = create_async_engine(settings.database_url, **kwargs)
    if settings.is_sqlite:
        _enforce_sqlite_foreign_keys(engine)
    return engine


def _enforce_sqlite_foreign_keys(engine: AsyncEngine) -> None:
    """Switch on foreign-key enforcement for every SQLite connection.

    SQLite ignores foreign keys unless the pragma is set per connection, which
    would let dev and test runs accept rows that Postgres rejects.

    :param engine: The engine whose connections should enforce foreign keys.
    """

    @event.listens_for(engine.sync_engine, "connect")
    def _set_pragma(dbapi_connection: _DBAPIConnection, _record: object) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return the process-wide session factory."""
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False, autoflush=False)
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield a request-scoped session, rolling back on error.

    Used as a FastAPI dependency.
    """
    factory = get_sessionmaker()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    """Tear down the engine and session factory, e.g. between tests."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
