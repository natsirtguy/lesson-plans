"""Generating and grading assessment items.

Two things make this cheap enough to use freely. Items are cached on
``(node, difficulty, level, format)``, so the second time the app needs a
difficulty-3 multiple-choice item about a concept for a proficient learner, it
already has one. And each item stores the rubric it was generated with, so grading
is reproducible even after the learner's level moves on -- the grader sees the same
criteria the item was written against, not today's.
"""

from __future__ import annotations

import hashlib

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db import new_id
from app.llm.base import LLMAdapter
from app.llm.prompts import GRADING_SYSTEM, ITEM_GENERATION_SYSTEM
from app.llm.schemas import GeneratedItem, GradeResult
from app.mastery.state import MasteryState
from app.models.assessment import QuizItem
from app.models.enums import ItemFormat
from app.repositories.assessment import AssessmentRepository
from app.services.graph_loader import LoadedSubject

#: Coarse buckets for how advanced the learner is on a concept. Used in the cache
#: key so a beginner and an expert do not share an item pitched at one of them.
LEVEL_BOUNDS: tuple[tuple[float, str], ...] = (
    (0.35, "novice"),
    (0.6, "developing"),
    (0.85, "proficient"),
    (1.01, "advanced"),
)


def level_for(mastery: float) -> str:
    """Bucket a mastery estimate into a coarse level.

    :param mastery: Current mastery estimate.
    """
    for bound, name in LEVEL_BOUNDS:
        if mastery < bound:
            return name
    return "advanced"


def choose_format(*, difficulty: int, observations: int) -> ItemFormat:
    """Pick the item format that discriminates best at this point.

    Recognition first, then production, then diagnosis. A learner meeting a concept
    for the first time is best served by a multiple-choice item whose distractors
    encode specific misconceptions; once they have shown recognition, asking them to
    produce the explanation tests more; and "explain why this is wrong" is the
    hardest of the three because it requires holding the correct model firmly enough
    to see where a plausible statement departs from it.

    :param difficulty: The item's difficulty, 1 through 5.
    :param observations: How many times this concept has already been tested.
    """
    if observations == 0 or difficulty <= 2:
        return ItemFormat.MULTIPLE_CHOICE
    if difficulty >= 4 and observations >= 1:
        return ItemFormat.EXPLAIN_WHY_WRONG
    return ItemFormat.SHORT_FREE_TEXT


def cache_key(node_id: str, difficulty: int, level: str, item_format: str) -> str:
    """Build the key an item is cached under.

    Hashed so it fits a bounded column regardless of id length.

    :param node_id: The concept being tested.
    :param difficulty: Item difficulty.
    :param level: The learner-level bucket.
    :param item_format: The item format.
    """
    raw = f"{node_id}|{difficulty}|{level}|{item_format}"
    return hashlib.sha256(raw.encode()).hexdigest()[:48]


class ItemService:
    """Generates, caches, and grades assessment items."""

    def __init__(self, session: AsyncSession, adapter: LLMAdapter, settings: Settings) -> None:
        """
        :param session: The active database session.
        :param adapter: The LLM boundary.
        :param settings: Runtime configuration.
        """
        self._session = session
        self._adapter = adapter
        self._settings = settings
        self._repo = AssessmentRepository(session)

    async def item_for(
        self,
        loaded: LoadedSubject,
        node_id: str,
        *,
        difficulty: int,
        observations: int = 0,
        item_format: ItemFormat | None = None,
    ) -> QuizItem:
        """Return an item testing one concept, generating it only if needed.

        :param loaded: The subject being assessed.
        :param node_id: The concept to test.
        :param difficulty: The item's difficulty, 1 through 5.
        :param observations: How many times this concept has been tested already.
        :param item_format: Force a format instead of inferring one. An exit check
            asks for two items about the same concept at the same difficulty, and
            since the cache key includes the format, naming them explicitly is what
            stops the second request returning the first item again.
        """
        state = loaded.states.get(node_id, MasteryState(0.15, 0.05))
        level = level_for(state.mastery)
        item_format = item_format or choose_format(difficulty=difficulty, observations=observations)
        key = cache_key(node_id, difficulty, level, item_format)

        cached = await self._repo.item_by_cache_key(key)
        if cached is not None:
            return cached

        generated = await self._adapter.generate_structured(
            schema=GeneratedItem,
            system=ITEM_GENERATION_SYSTEM,
            prompt=self._item_prompt(loaded, node_id, difficulty, item_format),
            task="item_generation",
            context=loaded.context(),
        )
        item = QuizItem(
            id=new_id(),
            subject_id=loaded.subject.id,
            node_id=node_id,
            item_format=generated.item_format,
            difficulty=difficulty,
            level=level,
            stem=generated.stem,
            choices=list(generated.choices),
            correct_choice=generated.correct_choice,
            answer_key=generated.answer_key,
            rubric=generated.rubric,
            cache_key=key,
        )
        self._repo.add_item(item)
        await self._session.flush()
        return item

    def _item_prompt(
        self,
        loaded: LoadedSubject,
        node_id: str,
        difficulty: int,
        item_format: ItemFormat,
    ) -> str:
        """Build the generation instruction for one item.

        :param loaded: The subject being assessed.
        :param node_id: The concept to test.
        :param difficulty: The item's difficulty.
        :param item_format: The format to produce.
        """
        meta = loaded.graph.nodes[node_id]
        node = loaded.nodes[node_id]
        prereqs = sorted(loaded.graph.nodes[p].name for p in loaded.graph.prereqs(node_id))
        lines = [
            f"CONCEPT: {meta.name}",
            f"DEFINITION: {node.definition}",
            f"TIER: {meta.tier}",
            f"DIFFICULTY: {difficulty}",
            f"FORMAT: {item_format}",
            f"PREREQUISITES: {', '.join(prereqs) if prereqs else '(none)'}",
            "",
            "Write one item testing this concept at the stated difficulty.",
        ]
        return "\n".join(lines)

    async def grade(self, loaded: LoadedSubject, item: QuizItem, answer: str) -> GradeResult:
        """Grade one answer against the rubric the item was generated with.

        A multiple-choice item is graded arithmetically rather than by the model:
        the answer is an index, the key is an index, and spending a model call to
        compare two integers would be absurd.

        :param loaded: The subject being assessed.
        :param item: The item that was answered.
        :param answer: The learner's answer.
        """
        if item.item_format == ItemFormat.MULTIPLE_CHOICE:
            return self._grade_choice(item, answer)

        return await self._adapter.generate_structured(
            schema=GradeResult,
            system=GRADING_SYSTEM,
            prompt=(
                f"CONCEPT: {loaded.graph.nodes[item.node_id].name}\n"
                f"QUESTION: {item.stem}\n"
                f"REFERENCE ANSWER: {item.answer_key}\n"
                f"RUBRIC: {item.rubric}\n"
                f"ANSWER: {answer}\n\n"
                "Grade this answer."
            ),
            task="grading",
            context=loaded.context(),
        )

    def _grade_choice(self, item: QuizItem, answer: str) -> GradeResult:
        """Grade a multiple-choice answer by comparing indices.

        :param item: The item that was answered.
        :param answer: The learner's answer, expected to be a choice index.
        """
        try:
            chosen = int(answer.strip())
        except ValueError:
            chosen = -1
        correct = chosen == item.correct_choice
        return GradeResult(
            score=1.0 if correct else 0.0,
            correct=correct,
            feedback=(
                "Correct." if correct else f"Not quite. The right answer is: {item.answer_key}"
            ),
            misconception=None if correct else _chosen_text(item, chosen),
        )


def _chosen_text(item: QuizItem, chosen: int) -> str | None:
    """The text of the option the learner picked, if it was a real option.

    Recording which distractor was chosen is what makes the misconception
    actionable later -- the distractors were written to encode specific ones.

    :param item: The item that was answered.
    :param chosen: The index the learner picked.
    """
    if 0 <= chosen < len(item.choices):
        return item.choices[chosen]
    return None
