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
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db import new_id
from app.llm.base import LLMAdapter
from app.llm.prompts import LESSON_SYSTEM
from app.mastery.state import MasteryParams
from app.models.plan import Lesson, PlanUnit
from app.repositories.plans import PlanRepository
from app.services.graph_loader import GraphLoader, LoadedSubject
from app.services.item_service import level_for
from app.sse import sse

#: Characters per replayed chunk when a lesson comes from cache.
REPLAY_CHUNK = 256


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


class LessonStreamer:
    """Streams a lesson's prose into its row and out to the client.

    Like :class:`~app.services.ask_service.AskService`, this takes a session
    factory: the body of a streaming response runs after the request's own
    dependencies have been torn down, so it must own the session it writes through.
    """

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        adapter: LLMAdapter,
        settings: Settings,
    ) -> None:
        """
        :param factory: Session factory the stream opens its own session from.
        :param adapter: The LLM boundary.
        :param settings: Runtime configuration.
        """
        self._factory = factory
        self._adapter = adapter
        self._settings = settings
        self._params = MasteryParams.from_settings(settings)

    async def stream(self, lesson_id: str) -> AsyncIterator[str]:
        """Emit a lesson as SSE frames, generating the prose if it is not written.

        A lesson already marked complete is replayed from the row rather than
        regenerated. That is the whole reason the row exists: a second read of a
        lesson must not cost a second generation.

        :param lesson_id: The lesson to stream.
        """
        async with self._factory() as session:
            repo = PlanRepository(session)
            lesson = await repo.get_lesson(lesson_id)
            if lesson is None:
                yield sse("error", {"detail": "lesson not found"})
                return

            loaded = await GraphLoader(session, self._params).load(lesson.subject_id)
            yield sse(
                "meta",
                {
                    "lesson_id": lesson.id,
                    "title": lesson.title,
                    "node_id": lesson.node_id,
                    "unit_id": lesson.unit_id,
                    "difficulty": lesson.difficulty,
                    "level": lesson.level,
                    "cached": lesson.complete,
                },
            )

            if lesson.complete:
                for start in range(0, len(lesson.markdown), REPLAY_CHUNK):
                    yield sse("delta", lesson.markdown[start : start + REPLAY_CHUNK])
                yield sse(
                    "done",
                    {"lesson_id": lesson.id, "complete": True, "characters": len(lesson.markdown)},
                )
                return

            pieces: list[str] = []
            async for delta in self._adapter.stream_text(
                system=LESSON_SYSTEM,
                prompt=self._prompt(loaded, lesson),
                task="lesson",
                context=loaded.context(),
            ):
                pieces.append(delta)
                yield sse("delta", delta)

            lesson.markdown = "".join(pieces)
            lesson.complete = True
            await session.commit()
            yield sse(
                "done",
                {"lesson_id": lesson.id, "complete": True, "characters": len(lesson.markdown)},
            )

    def _prompt(self, loaded: LoadedSubject, lesson: Lesson) -> str:
        """Build the teaching instruction for one lesson.

        Prerequisites are split by how well the learner holds them, because the
        system prompt treats the two differently: solid ones are referenced by name
        and not re-taught, weak ones get a sentence of refresher inline.

        :param loaded: The subject the lesson belongs to.
        :param lesson: The lesson row being filled in.
        """
        node_id = lesson.node_id
        if node_id is None or node_id not in loaded.graph:
            return f"CONCEPT: {lesson.title}\n\nTeach this concept."

        meta = loaded.graph.nodes[node_id]
        state = loaded.states[node_id]
        solid: list[str] = []
        shaky: list[str] = []
        for prereq in sorted(
            loaded.graph.prereqs(node_id), key=lambda p: loaded.graph.nodes[p].name
        ):
            name = loaded.graph.nodes[prereq].name
            target = (
                solid if loaded.states[prereq].mastery >= self._params.mastery_threshold else shaky
            )
            target.append(name)

        return "\n".join(
            [
                f"CONCEPT: {meta.name}",
                f"DEFINITION: {loaded.nodes[node_id].definition}",
                f"TIER: {meta.tier}",
                f"DIFFICULTY: {lesson.difficulty}",
                f"CURRENT MASTERY: {state.mastery:.2f}",
                f"MASTERED PREREQUISITES: {', '.join(solid) if solid else '(none)'}",
                f"WEAK PREREQUISITES: {', '.join(shaky) if shaky else '(none)'}",
                "",
                "Teach this concept.",
            ]
        )
