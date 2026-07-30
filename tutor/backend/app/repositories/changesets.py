"""Persistence for the changeset log and proactive suggestions."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.changeset import Changeset, ChangesetOp, GraphSuggestion
from app.models.enums import SuggestionStatus


class ChangesetRepository:
    """Reads and writes changesets, their operations, and suggestions."""

    def __init__(self, session: AsyncSession) -> None:
        """
        :param session: The active database session.
        """
        self._session = session

    def add(self, changeset: Changeset) -> Changeset:
        """Stage a changeset for insertion.

        :param changeset: The changeset to add.
        """
        self._session.add(changeset)
        return changeset

    def add_op(self, op: ChangesetOp) -> ChangesetOp:
        """Stage one operation for insertion.

        :param op: The operation to add.
        """
        self._session.add(op)
        return op

    async def get(self, changeset_id: str) -> Changeset | None:
        """Fetch one changeset.

        :param changeset_id: The changeset's id.
        """
        return await self._session.get(Changeset, changeset_id)

    async def ops_for(self, changeset_id: str) -> list[ChangesetOp]:
        """Fetch a changeset's operations in application order.

        :param changeset_id: The changeset's id.
        """
        result = await self._session.execute(
            select(ChangesetOp)
            .where(ChangesetOp.changeset_id == changeset_id)
            .order_by(ChangesetOp.seq)
        )
        return list(result.scalars())

    async def log_for(self, subject_id: str) -> list[Changeset]:
        """Fetch a subject's changeset history, newest first.

        :param subject_id: The subject to read.
        """
        result = await self._session.execute(
            select(Changeset)
            .where(Changeset.subject_id == subject_id)
            .order_by(Changeset.created_at.desc())
        )
        return list(result.scalars())

    async def op_counts(self, changeset_ids: list[str]) -> dict[str, tuple[int, int]]:
        """Count operations and accepted operations per changeset.

        :param changeset_ids: Changesets to count for.
        """
        if not changeset_ids:
            return {}
        result = await self._session.execute(
            select(ChangesetOp).where(ChangesetOp.changeset_id.in_(changeset_ids))
        )
        counts: dict[str, tuple[int, int]] = {}
        for op in result.scalars():
            total, accepted = counts.get(op.changeset_id, (0, 0))
            counts[op.changeset_id] = (
                total + 1,
                accepted + (1 if op.accepted else 0),
            )
        return counts

    # --- suggestions ---------------------------------------------------------

    def add_suggestion(self, suggestion: GraphSuggestion) -> GraphSuggestion:
        """Stage a suggestion for insertion.

        :param suggestion: The suggestion to add.
        """
        self._session.add(suggestion)
        return suggestion

    async def open_suggestions(self, subject_id: str) -> list[GraphSuggestion]:
        """Fetch a subject's unresolved suggestions, newest first.

        :param subject_id: The subject to read.
        """
        result = await self._session.execute(
            select(GraphSuggestion)
            .where(
                GraphSuggestion.subject_id == subject_id,
                GraphSuggestion.status == SuggestionStatus.OPEN,
            )
            .order_by(GraphSuggestion.created_at.desc())
        )
        return list(result.scalars())

    async def suggestion_keys(self, subject_id: str) -> set[str]:
        """Deduplication keys of every suggestion ever raised for a subject.

        Includes dismissed ones: a suggestion the learner rejected should not come
        back the next time the same observation is made.

        :param subject_id: The subject to read.
        """
        result = await self._session.execute(
            select(GraphSuggestion.dedupe_key).where(GraphSuggestion.subject_id == subject_id)
        )
        return set(result.scalars())

    async def get_suggestion(self, suggestion_id: str) -> GraphSuggestion | None:
        """Fetch one suggestion.

        :param suggestion_id: The suggestion's id.
        """
        return await self._session.get(GraphSuggestion, suggestion_id)
