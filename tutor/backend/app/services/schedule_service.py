"""Generating and tracking the rolling study schedule.

The arithmetic is in :mod:`app.scheduling.planner`, which is pure. This module
gathers what that arithmetic needs -- the cadence, the due queue, the remaining
plan -- persists the result, and tracks whether the learner actually turned up.

**Adherence is counted, never scored.** Sessions planned, completed, missed, and
the current streak. No points, no badges, no levels, and no penalty for a broken
streak. The numbers exist so the learner can tell whether their cadence is
realistic, which is a decision they make, not a game they lose.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db import new_id, utcnow
from app.llm.base import LLMAdapter
from app.mastery.state import MasteryParams
from app.models.enums import StudySessionStatus, UnitStatus
from app.models.scheduling import StudySession
from app.repositories.plans import PlanRepository
from app.scheduling.planner import (
    Cadence,
    DueItem,
    PlannedSession,
    Schedule,
    plan_schedule,
)
from app.schemas.schedule import (
    AdherenceRead,
    DeadlineRead,
    ScheduleRead,
    ScheduleRequest,
    SessionRead,
)
from app.services.graph_loader import GraphLoader, LoadedSubject
from app.services.review_service import ReviewService


class SessionAlreadyClosed(RuntimeError):
    """Raised when a sitting that is already resolved is completed again."""


class ScheduleService:
    """Builds, stores, and reports on the rolling schedule."""

    def __init__(self, session: AsyncSession, adapter: LLMAdapter, settings: Settings) -> None:
        """
        :param session: The active database session.
        :param adapter: The LLM boundary.
        :param settings: Runtime configuration.
        """
        self._session = session
        self._settings = settings
        self._params = MasteryParams.from_settings(settings)
        self._loader = GraphLoader(session, self._params)
        self._plans = PlanRepository(session)
        self._reviews = ReviewService(session, adapter, settings)

    async def build(
        self, subject_id: str, payload: ScheduleRequest, *, today: date | None = None
    ) -> ScheduleRead:
        """Produce a rolling schedule for a subject.

        :param subject_id: The subject to schedule.
        :param payload: Horizon and persistence options.
        :param today: The day to schedule from; defaults to the current date.
        :raises SubjectNotFoundError: If the subject does not exist.
        """
        start = today or datetime.now(UTC).date()
        loaded = await self._loader.load(subject_id)
        cadence = self._cadence(loaded)

        queue = await self._reviews.due_queue(subject_id)
        due = [
            DueItem(
                node_id=card.node_id,
                due_on=card.due_at.date() if card.due_at else start,
                priority=1.0 + card.overdue_days,
            )
            for card in queue.due
        ]

        units = await self._pending_units(subject_id)
        schedule = plan_schedule(
            start=start,
            due=due,
            unit_ids=[unit_id for unit_id, _ in units],
            unit_node_ids=[node_id for _, node_id in units],
            cadence=cadence,
            horizon_days=payload.horizon_days,
        )

        stored = (
            await self._persist(subject_id, schedule, start=start)
            if payload.persist
            else [None] * len(schedule.sessions)
        )
        adherence = await self._adherence(subject_id, today=start)
        await self._session.commit()

        return ScheduleRead(
            subject_id=subject_id,
            generated_for=start,
            horizon_days=payload.horizon_days,
            days_per_week=cadence.days_per_week,
            minutes_per_session=cadence.minutes_per_session,
            daily_review_cap=cadence.daily_review_cap,
            sessions=[
                self._render(planned, row, loaded)
                for planned, row in zip(schedule.sessions, stored, strict=True)
            ],
            deadline=_render_verdict(schedule),
            adherence=adherence,
            units_scheduled=schedule.units_scheduled,
            units_remaining=schedule.units_remaining,
            due_now=len(queue.due) + queue.deferred,
        )

    async def complete_session(self, session_id: str, notes: str) -> SessionRead:
        """Mark a planned sitting as done.

        :param session_id: The sitting to close.
        :param notes: Anything the learner wants recorded against it.
        :raises LookupError: If the sitting does not exist.
        :raises SessionAlreadyClosed: If it is already complete or missed.
        """
        row = await self._session.get(StudySession, session_id)
        if row is None:
            raise LookupError(session_id)
        if row.status != StudySessionStatus.PLANNED:
            raise SessionAlreadyClosed(session_id)

        row.status = StudySessionStatus.COMPLETE
        row.completed_at = utcnow()
        if notes:
            row.notes = notes
        loaded = await self._loader.load(row.subject_id)
        await self._session.commit()
        return self._render(None, row, loaded)

    # --- inputs --------------------------------------------------------------

    def _cadence(self, loaded: LoadedSubject) -> Cadence:
        """Read a subject's cadence, falling back to configured defaults.

        :param loaded: The subject being scheduled.
        """
        subject = loaded.subject
        return Cadence(
            days_per_week=subject.days_per_week or self._settings.default_days_per_week,
            minutes_per_session=(
                subject.minutes_per_session or self._settings.default_minutes_per_session
            ),
            daily_review_cap=subject.daily_review_cap or self._settings.daily_review_cap,
            retrieval_minutes=self._settings.session_retrieval_minutes,
            minutes_per_review=self._settings.minutes_per_review_item,
            minutes_per_new_node=self._settings.minutes_per_new_node,
            deadline=subject.deadline,
        )

    async def _pending_units(self, subject_id: str) -> list[tuple[str, str]]:
        """The active plan's outstanding units, in plan order.

        :param subject_id: The subject to read.
        """
        plan = await self._plans.active_plan(subject_id)
        if plan is None:
            return []
        return [
            (unit.id, unit.node_id)
            for unit in await self._plans.units_for_plan(plan.id)
            if unit.status in {UnitStatus.PENDING, UnitStatus.IN_PROGRESS}
        ]

    # --- persistence ---------------------------------------------------------

    async def _persist(
        self, subject_id: str, schedule: Schedule, *, start: date
    ) -> list[StudySession]:
        """Replace the future part of the stored schedule with a fresh one.

        Only *planned* sittings from today onward are discarded. A completed
        session is a record of something that happened and is never rewritten, and
        a past planned session that was never completed becomes a missed one rather
        than disappearing -- otherwise adherence would improve every time the
        schedule was regenerated.

        :param subject_id: The subject being scheduled.
        :param schedule: The freshly computed schedule.
        :param start: The day the schedule begins.
        """
        existing = (
            (
                await self._session.execute(
                    select(StudySession).where(StudySession.subject_id == subject_id)
                )
            )
            .scalars()
            .all()
        )
        for row in existing:
            if row.status != StudySessionStatus.PLANNED:
                continue
            if row.scheduled_for < start:
                row.status = StudySessionStatus.MISSED
            else:
                await self._session.delete(row)
        await self._session.flush()

        rows: list[StudySession] = []
        for planned in schedule.sessions:
            row = StudySession(
                id=new_id(),
                subject_id=subject_id,
                scheduled_for=planned.on,
                status=StudySessionStatus.PLANNED,
                planned_minutes=planned.planned_minutes,
                retrieval_minutes=planned.retrieval_minutes,
                review_node_ids=list(planned.review_node_ids),
                new_node_ids=list(planned.new_node_ids),
                unit_ids=list(planned.unit_ids),
                deferred_node_ids=list(planned.deferred_node_ids),
                projected_coverage=0.0,
                notes=" ".join(planned.notes),
                detail={"reviews": len(planned.review_node_ids), "new": len(planned.new_node_ids)},
            )
            self._session.add(row)
            rows.append(row)
        await self._session.flush()
        return rows

    async def _adherence(self, subject_id: str, *, today: date) -> AdherenceRead:
        """Count how consistently past sittings were actually done.

        :param subject_id: The subject to read.
        :param today: The day to judge "past" against.
        """
        rows = list(
            (
                await self._session.execute(
                    select(StudySession)
                    .where(StudySession.subject_id == subject_id)
                    .order_by(StudySession.scheduled_for)
                )
            ).scalars()
        )
        past = [row for row in rows if row.scheduled_for < today]
        completed = sum(1 for row in past if row.status == StudySessionStatus.COMPLETE)
        missed = len(past) - completed

        longest = 0
        run = 0
        for row in past:
            run = run + 1 if row.status == StudySessionStatus.COMPLETE else 0
            longest = max(longest, run)

        current = 0
        for row in reversed(past):
            if row.status != StudySessionStatus.COMPLETE:
                break
            current += 1

        return AdherenceRead(
            sessions_planned=len(rows),
            sessions_completed=completed,
            sessions_missed=missed,
            completion_rate=(completed / len(past)) if past else None,
            current_streak=current,
            longest_streak=longest,
        )

    # --- rendering -----------------------------------------------------------

    @staticmethod
    def _render(
        planned: PlannedSession | None, row: StudySession | None, loaded: LoadedSubject
    ) -> SessionRead:
        """Shape one sitting for the API.

        :param planned: The computed sitting, when there is one.
        :param row: The stored sitting, when it was persisted.
        :param loaded: The subject, for concept names.
        """
        review_ids = list(
            planned.review_node_ids if planned else (row.review_node_ids if row else [])
        )
        new_ids = list(planned.new_node_ids if planned else (row.new_node_ids if row else []))

        def names(node_ids: list[str]) -> list[str]:
            """Concept names for a list of ids, skipping any no longer live.

            :param node_ids: The concepts to name.
            """
            return [loaded.graph.nodes[n].name for n in node_ids if n in loaded.graph]

        if planned is not None:
            return SessionRead(
                id=row.id if row else None,
                scheduled_for=planned.on,
                status=row.status if row else StudySessionStatus.PLANNED,
                planned_minutes=planned.planned_minutes,
                retrieval_minutes=planned.retrieval_minutes,
                review_node_ids=review_ids,
                review_names=names(review_ids),
                new_node_ids=new_ids,
                new_names=names(new_ids),
                unit_ids=list(planned.unit_ids),
                deferred_node_ids=list(planned.deferred_node_ids),
                notes=" ".join(planned.notes),
                completed_at=row.completed_at if row else None,
            )

        assert row is not None
        return SessionRead(
            id=row.id,
            scheduled_for=row.scheduled_for,
            status=row.status,
            planned_minutes=row.planned_minutes,
            retrieval_minutes=row.retrieval_minutes,
            review_node_ids=review_ids,
            review_names=names(review_ids),
            new_node_ids=new_ids,
            new_names=names(new_ids),
            unit_ids=list(row.unit_ids),
            deferred_node_ids=list(row.deferred_node_ids),
            notes=row.notes,
            completed_at=row.completed_at,
        )


def _render_verdict(schedule: Schedule) -> DeadlineRead:
    """Shape the deadline assessment for the API.

    :param schedule: The computed schedule.
    """
    verdict = schedule.verdict
    if verdict is None:  # pragma: no cover - the planner always produces one
        return DeadlineRead(
            deadline=None,
            sessions_available=0,
            sessions_needed=0,
            achievable=True,
            shortfall_sessions=0,
            message="No deadline set.",
        )
    return DeadlineRead(
        deadline=verdict.deadline,
        sessions_available=verdict.sessions_available,
        sessions_needed=verdict.sessions_needed,
        achievable=verdict.achievable,
        shortfall_sessions=verdict.shortfall_sessions,
        message=verdict.message,
    )


__all__ = ["ScheduleService", "SessionAlreadyClosed"]
