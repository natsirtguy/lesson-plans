"""Persistence for subjects."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.graph import ConceptNode
from app.models.subject import Subject


class SubjectRepository:
    """Reads and writes subject rows."""

    def __init__(self, session: AsyncSession) -> None:
        """
        :param session: The active database session.
        """
        self._session = session

    async def add(self, subject: Subject) -> Subject:
        """Insert a subject and populate its generated fields.

        :param subject: The subject to insert.
        """
        self._session.add(subject)
        await self._session.flush()
        return subject

    async def get(self, subject_id: str) -> Subject | None:
        """Fetch one subject by id.

        :param subject_id: The subject's id.
        """
        return await self._session.get(Subject, subject_id)

    async def list_all(self) -> list[Subject]:
        """Fetch every subject, newest first."""
        result = await self._session.execute(select(Subject).order_by(Subject.created_at.desc()))
        return list(result.scalars())

    async def node_counts(self) -> dict[str, int]:
        """Count live concepts per subject, keyed by subject id."""
        result = await self._session.execute(
            select(ConceptNode.subject_id, func.count())
            .where(ConceptNode.deleted_at.is_(None))
            .group_by(ConceptNode.subject_id)
        )
        return {row[0]: row[1] for row in result.all()}

    async def bump_graph_version(self, subject: Subject) -> int:
        """Advance the subject's graph version and return the new value.

        :param subject: The subject being changed.
        """
        subject.graph_version += 1
        await self._session.flush()
        return subject.graph_version
