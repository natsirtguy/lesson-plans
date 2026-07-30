"""Lesson rows: the persisted home for generated teaching prose.

A lesson row is created *before* its prose exists, with ``complete`` false. That
looks odd until you consider how the content arrives: it is streamed token by
token over SSE, and a streamed response cannot be cached by a service worker. The
row is the addressable, cacheable copy -- ``GET /lessons/{id}`` returns it -- so
creating it up front is what gives the client something to point at while the
stream is still running, and what makes the lesson readable offline afterwards.

Content is keyed on ``(node, difficulty, level)`` like items are: a lesson written
for a novice at difficulty 2 is reusable the next time that combination comes up,
and regenerating it would cost money for no gain.
"""

from __future__ import annotations

import hashlib

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import new_id
from app.models.plan import Lesson, PlanUnit
from app.repositories.plans import PlanRepository
from app.services.graph_loader import LoadedSubject
from app.services.item_service import level_for


def lesson_cache_key(node_id: str, difficulty: int, level: str) -> str:
    """Build the key a lesson's content is cached under.

    :param node_id: The concept being taught.
    :param difficulty: The pitch of the lesson, 1 through 5.
    :param level: The learner-level bucket the lesson was written for.
    """
    raw = f"lesson|{node_id}|{difficulty}|{level}"
    return hashlib.sha256(raw.encode()).hexdigest()[:48]


class LessonService:
    """Finds or creates the lesson row backing a plan unit."""

    def __init__(self, session: AsyncSession) -> None:
        """
        :param session: The active database session.
        """
        self._session = session
        self._repo = PlanRepository(session)

    async def ensure_for_unit(self, loaded: LoadedSubject, unit: PlanUnit) -> Lesson:
        """Return the lesson row for a unit, creating an empty one if needed.

        An existing row is reused even when its prose is already written, which is
        the cache hit: the same concept at the same level does not get taught twice
        at the model's expense. A row already attached to another unit is left
        attached to it; the content is shared, the association is not.

        :param loaded: The subject the unit belongs to.
        :param unit: The unit being studied.
        """
        existing = await self._repo.lesson_for_unit(unit.id)
        if existing is not None:
            return existing

        state = loaded.states.get(unit.node_id)
        mastery = state.mastery if state is not None else 0.0
        level = level_for(mastery)
        difficulty = loaded.graph.tier(unit.node_id)
        key = lesson_cache_key(unit.node_id, difficulty, level)

        cached = await self._repo.lesson_by_cache_key(key)
        if cached is not None:
            return cached

        lesson = self._repo.add_lesson(
            Lesson(
                id=new_id(),
                subject_id=loaded.subject.id,
                node_id=unit.node_id,
                unit_id=unit.id,
                title=unit.title,
                difficulty=difficulty,
                level=level,
                markdown="",
                complete=False,
                cache_key=key,
                provenance={"source": "plan_unit", "unit_id": unit.id},
            )
        )
        await self._session.flush()
        return lesson
