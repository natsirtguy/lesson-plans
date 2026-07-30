"""Persistence for diagnostic sessions, generated items, and graded responses."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.mastery.replay import Observation
from app.models.assessment import DiagnosticSession, ItemResponse, QuizItem


class AssessmentRepository:
    """Reads and writes assessment rows."""

    def __init__(self, session: AsyncSession) -> None:
        """
        :param session: The active database session.
        """
        self._session = session

    # --- sessions ------------------------------------------------------------

    def add_session(self, diagnostic: DiagnosticSession) -> DiagnosticSession:
        """Stage a diagnostic session for insertion.

        :param diagnostic: The session to add.
        """
        self._session.add(diagnostic)
        return diagnostic

    async def get_session(self, session_id: str) -> DiagnosticSession | None:
        """Fetch one diagnostic session.

        :param session_id: The session's id.
        """
        return await self._session.get(DiagnosticSession, session_id)

    async def active_session(self, subject_id: str) -> DiagnosticSession | None:
        """Fetch a subject's in-progress diagnostic, if there is one.

        :param subject_id: The subject to check.
        """
        result = await self._session.execute(
            select(DiagnosticSession)
            .where(
                DiagnosticSession.subject_id == subject_id,
                DiagnosticSession.status == "active",
            )
            .order_by(DiagnosticSession.created_at.desc())
        )
        return result.scalars().first()

    # --- items ---------------------------------------------------------------

    def add_item(self, item: QuizItem) -> QuizItem:
        """Stage an item for insertion.

        :param item: The item to add.
        """
        self._session.add(item)
        return item

    async def get_item(self, item_id: str) -> QuizItem | None:
        """Fetch one item.

        :param item_id: The item's id.
        """
        return await self._session.get(QuizItem, item_id)

    async def item_by_cache_key(self, cache_key: str) -> QuizItem | None:
        """Fetch a previously generated item by its cache key.

        This is what stops the app paying to regenerate identical content.

        :param cache_key: The key from the item's (node, difficulty, level, format).
        """
        result = await self._session.execute(
            select(QuizItem).where(QuizItem.cache_key == cache_key)
        )
        return result.scalars().first()

    # --- responses -----------------------------------------------------------

    def add_response(self, response: ItemResponse) -> ItemResponse:
        """Stage a graded response for insertion.

        :param response: The response to add.
        """
        self._session.add(response)
        return response

    async def responses_for_session(self, session_id: str) -> list[ItemResponse]:
        """Fetch a diagnostic session's responses in order.

        :param session_id: The session's id.
        """
        result = await self._session.execute(
            select(ItemResponse)
            .where(ItemResponse.session_id == session_id)
            .order_by(ItemResponse.created_at)
        )
        return list(result.scalars())

    async def responses_for_subject(self, subject_id: str) -> list[ItemResponse]:
        """Fetch every graded response for a subject, oldest first.

        :param subject_id: The subject to read.
        """
        result = await self._session.execute(
            select(ItemResponse)
            .where(ItemResponse.subject_id == subject_id)
            .order_by(ItemResponse.created_at)
        )
        return list(result.scalars())

    async def responses_for_node(self, node_id: str) -> list[ItemResponse]:
        """Fetch every graded response against one concept.

        :param node_id: The concept's id.
        """
        result = await self._session.execute(
            select(ItemResponse)
            .where(ItemResponse.node_id == node_id)
            .order_by(ItemResponse.created_at)
        )
        return list(result.scalars())

    async def observations(self, subject_id: str) -> list[Observation]:
        """Fetch the response log in the form the mastery replay consumes.

        Item difficulty is joined in, because the update rule needs it and the
        response row does not carry it -- the item does.

        :param subject_id: The subject to read.
        """
        result = await self._session.execute(
            select(ItemResponse, QuizItem.difficulty)
            .join(QuizItem, QuizItem.id == ItemResponse.item_id)
            .where(ItemResponse.subject_id == subject_id)
            .order_by(ItemResponse.created_at)
        )
        return [
            Observation(
                node_id=response.node_id,
                difficulty=difficulty,
                score=response.score,
                at=response.created_at,
            )
            for response, difficulty in result.all()
        ]

    async def retrieval_stats(self, subject_id: str, *, limit: int = 60) -> list[float]:
        """Recent rubric scores, newest first, for difficulty calibration.

        :param subject_id: The subject to read.
        :param limit: How many recent responses to consider.
        """
        result = await self._session.execute(
            select(ItemResponse.score)
            .where(ItemResponse.subject_id == subject_id)
            .order_by(ItemResponse.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars())

    async def response_counts(self, subject_id: str) -> dict[str, int]:
        """Number of graded responses per concept.

        :param subject_id: The subject to read.
        """
        result = await self._session.execute(
            select(ItemResponse.node_id, func.count())
            .where(ItemResponse.subject_id == subject_id)
            .group_by(ItemResponse.node_id)
        )
        return {row[0]: row[1] for row in result.all()}
