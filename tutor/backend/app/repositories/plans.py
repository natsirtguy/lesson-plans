"""Persistence for lesson plans, their units, and cached lesson content."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import PlanStatus, UnitStatus
from app.models.plan import Lesson, LessonPlan, PlanUnit


class PlanRepository:
    """Reads and writes plans, units, and lessons."""

    def __init__(self, session: AsyncSession) -> None:
        """
        :param session: The active database session.
        """
        self._session = session

    # --- plans ---------------------------------------------------------------

    def add_plan(self, plan: LessonPlan) -> LessonPlan:
        """Stage a plan for insertion.

        :param plan: The plan to add.
        """
        self._session.add(plan)
        return plan

    async def get_plan(self, plan_id: str) -> LessonPlan | None:
        """Fetch one plan.

        :param plan_id: The plan's id.
        """
        return await self._session.get(LessonPlan, plan_id)

    async def active_plan(self, subject_id: str) -> LessonPlan | None:
        """Fetch a subject's current plan, if it has one.

        :param subject_id: The subject to read.
        """
        result = await self._session.execute(
            select(LessonPlan)
            .where(
                LessonPlan.subject_id == subject_id,
                LessonPlan.status == PlanStatus.ACTIVE,
            )
            .order_by(LessonPlan.created_at.desc())
        )
        return result.scalars().first()

    async def supersede_plans(self, subject_id: str) -> None:
        """Mark a subject's existing plans superseded.

        Regenerating a plan does not delete the old one: the units it completed are
        part of the learner's history.

        :param subject_id: The subject whose plans are being replaced.
        """
        for plan in (
            await self._session.execute(
                select(LessonPlan).where(
                    LessonPlan.subject_id == subject_id,
                    LessonPlan.status == PlanStatus.ACTIVE,
                )
            )
        ).scalars():
            plan.status = PlanStatus.SUPERSEDED

    # --- units ---------------------------------------------------------------

    def add_unit(self, unit: PlanUnit) -> PlanUnit:
        """Stage a unit for insertion.

        :param unit: The unit to add.
        """
        self._session.add(unit)
        return unit

    async def get_unit(self, unit_id: str) -> PlanUnit | None:
        """Fetch one unit.

        :param unit_id: The unit's id.
        """
        return await self._session.get(PlanUnit, unit_id)

    async def units_for_plan(self, plan_id: str) -> list[PlanUnit]:
        """Fetch a plan's units in sequence order.

        :param plan_id: The plan's id.
        """
        result = await self._session.execute(
            select(PlanUnit).where(PlanUnit.plan_id == plan_id).order_by(PlanUnit.seq)
        )
        return list(result.scalars())

    async def active_units(self, subject_id: str) -> list[PlanUnit]:
        """Fetch the units of a subject's current plan.

        Used by changeset validation, which must refuse to remove a concept the plan
        still intends to teach.

        :param subject_id: The subject to read.
        """
        plan = await self.active_plan(subject_id)
        if plan is None:
            return []
        return await self.units_for_plan(plan.id)

    async def taught_node_ids(self, subject_id: str) -> set[str]:
        """Concepts the learner has already been through a unit for.

        Spans every plan the subject has ever had, superseded ones included: being
        taught a concept is a fact about the learner, not about the plan that
        happened to be current at the time. A regenerated plan uses this to avoid
        claiming a re-taught concept is a first acquisition.

        :param subject_id: The subject to read.
        """
        result = await self._session.execute(
            select(PlanUnit.node_id).where(
                PlanUnit.subject_id == subject_id,
                PlanUnit.status.in_([UnitStatus.COMPLETE, UnitStatus.SKIPPED]),
            )
        )
        return set(result.scalars())

    async def next_unit(self, plan_id: str) -> PlanUnit | None:
        """Fetch the earliest unit not yet completed or skipped.

        :param plan_id: The plan's id.
        """
        result = await self._session.execute(
            select(PlanUnit)
            .where(
                PlanUnit.plan_id == plan_id,
                PlanUnit.status.in_([UnitStatus.PENDING, UnitStatus.IN_PROGRESS]),
            )
            .order_by(PlanUnit.seq)
        )
        return result.scalars().first()

    # --- lessons -------------------------------------------------------------

    def add_lesson(self, lesson: Lesson) -> Lesson:
        """Stage a lesson for insertion.

        :param lesson: The lesson to add.
        """
        self._session.add(lesson)
        return lesson

    async def get_lesson(self, lesson_id: str) -> Lesson | None:
        """Fetch one lesson.

        :param lesson_id: The lesson's id.
        """
        return await self._session.get(Lesson, lesson_id)

    async def lesson_by_cache_key(self, cache_key: str) -> Lesson | None:
        """Fetch cached lesson content by its key.

        :param cache_key: The key from the lesson's (node, difficulty, level).
        """
        result = await self._session.execute(select(Lesson).where(Lesson.cache_key == cache_key))
        return result.scalars().first()

    async def lesson_for_unit(self, unit_id: str) -> Lesson | None:
        """Fetch the lesson generated for one plan unit.

        :param unit_id: The unit's id.
        """
        result = await self._session.execute(select(Lesson).where(Lesson.unit_id == unit_id))
        return result.scalars().first()
