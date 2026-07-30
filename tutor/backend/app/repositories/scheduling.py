"""Persistence for FSRS review cards and planned study sessions."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import CardState
from app.models.scheduling import ReviewCard


class SchedulingRepository:
    """Reads and writes scheduling state."""

    def __init__(self, session: AsyncSession) -> None:
        """
        :param session: The active database session.
        """
        self._session = session

    def add_card(self, card: ReviewCard) -> ReviewCard:
        """Stage a card for insertion.

        :param card: The card to add.
        """
        self._session.add(card)
        return card

    async def card_for(self, node_id: str) -> ReviewCard | None:
        """Fetch the card for one concept.

        :param node_id: The concept's id.
        """
        result = await self._session.execute(
            select(ReviewCard).where(ReviewCard.node_id == node_id)
        )
        return result.scalars().first()

    async def cards_for_subject(self, subject_id: str) -> list[ReviewCard]:
        """Every card in a subject.

        :param subject_id: The subject to read.
        """
        result = await self._session.execute(
            select(ReviewCard).where(ReviewCard.subject_id == subject_id)
        )
        return list(result.scalars())

    async def due_cards(self, subject_id: str, *, now: datetime) -> list[ReviewCard]:
        """Cards whose next retrieval has come, soonest-due first.

        A card with no due date is not returned: it has never been studied, and new
        material is the plan's business rather than the review queue's.

        :param subject_id: The subject to read.
        :param now: The instant to judge against.
        """
        result = await self._session.execute(
            select(ReviewCard)
            .where(
                ReviewCard.subject_id == subject_id,
                ReviewCard.due_at.is_not(None),
                ReviewCard.due_at <= now,
                ReviewCard.state != CardState.NEW,
            )
            .order_by(ReviewCard.due_at)
        )
        return list(result.scalars())
