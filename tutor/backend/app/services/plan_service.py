"""Generating and running lesson plans.

The ordering itself is decided by :mod:`app.graphs.sequencer`, which is pure and
guarantees by construction that no unit precedes a concept it depends on. What
happens here is everything around that: persisting the sequence, writing the
teaching frame for a unit when the learner actually reaches it, running the exit
check, and feeding the result back into the mastery model.

**Unit prose is written lazily, and that is deliberate.** A hundred-node subject
produces a plan with up to a hundred units; asking the model for a title and
objective for each one at creation time would mean a hundred calls before the
learner sees anything, which fails the "subject to plan in under five minutes"
criterion for no benefit -- most of those units will not be reached for weeks, and
the learner's mastery will have moved by then. So a unit is created with a
deterministic placeholder frame and upgraded by a single model call the first time
it is served, when the estimate it should be pitched against is current.

Regenerating a plan supersedes the old one rather than deleting it. The units the
learner completed are part of their history, and the next plan reads that history
back to know which concepts are re-acquisitions.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db import new_id, utcnow
from app.graphs.sequencer import DEFAULT_INTERLEAVE, PlanSequence, sequence_plan
from app.llm.base import LLMAdapter
from app.llm.prompts import UNIT_BRIEF_SYSTEM
from app.llm.schemas import UnitBrief
from app.mastery.coverage import coverage
from app.mastery.state import MasteryParams
from app.models.assessment import ItemResponse, QuizItem
from app.models.enums import ItemFormat, PlanStatus, QueueKind, UnitStatus
from app.models.plan import LessonPlan, PlanUnit
from app.repositories.assessment import AssessmentRepository
from app.repositories.plans import PlanRepository
from app.scheduling.grading import grade_for
from app.schemas.plan import (
    ExitCheckItemRead,
    NextUnit,
    PlanCreate,
    PlanRead,
    PlanUnitRead,
    UnitComplete,
    UnitCompleteResult,
)
from app.services.graph_loader import GraphLoader, LoadedSubject
from app.services.item_service import ItemService
from app.services.lesson_service import LessonService
from app.services.mastery_service import MasteryUpdater
from app.services.review_service import ReviewService

#: Formats an exit check rotates through. Production before diagnosis: "explain
#: it" tests whether the lesson landed, "say why this is wrong" tests whether it
#: landed firmly enough to detect a plausible departure from it.
EXIT_CHECK_FORMATS: tuple[ItemFormat, ...] = (
    ItemFormat.SHORT_FREE_TEXT,
    ItemFormat.EXPLAIN_WHY_WRONG,
)


class UnitAlreadyClosed(RuntimeError):
    """Raised when a unit that is already finished is completed again."""


class UnitItemMismatch(ValueError):
    """Raised when an exit-check answer names an item from a different unit."""


class UnitAlreadyScheduled(RuntimeError):
    """Raised when a concept the plan is already going to teach is inserted again."""


#: Offset used to move every unit out of the way before renumbering it. Larger than
#: any plan will ever be, so the shifted range cannot overlap the final one.
_SEQ_OFFSET = 1_000_000


class PlanService:
    """Generates plans and runs the learner through their units."""

    def __init__(self, session: AsyncSession, adapter: LLMAdapter, settings: Settings) -> None:
        """
        :param session: The active database session.
        :param adapter: The LLM boundary.
        :param settings: Runtime configuration.
        """
        self._session = session
        self._adapter = adapter
        self._settings = settings
        self._params = MasteryParams.from_settings(settings)
        self._loader = GraphLoader(session, self._params)
        self._repo = PlanRepository(session)
        self._assessment = AssessmentRepository(session)
        self._items = ItemService(session, adapter, settings)
        self._lessons = LessonService(session)
        self._mastery = MasteryUpdater(self._params)
        self._reviews = ReviewService(session, adapter, settings)

    # --- generation ----------------------------------------------------------

    async def create(self, subject_id: str, payload: PlanCreate) -> PlanRead:
        """Sequence a subject into a plan, replacing any current one.

        :param subject_id: The subject to plan.
        :param payload: Generation options.
        :raises SubjectNotFoundError: If the subject does not exist.
        :raises GraphNotReadyError: If the concept graph is not built yet.
        :raises GraphCycleError: If the stored graph is cyclic.
        """
        loaded = await self._loader.require_ready(subject_id)
        taught = await self._repo.taught_node_ids(subject_id)
        sequenced = sequence_plan(
            loaded.graph,
            loaded.states,
            self._params,
            taught=frozenset(taught),
            interleave=(DEFAULT_INTERLEAVE if payload.interleave is None else payload.interleave),
            limit=payload.limit,
        )

        await self._repo.supersede_plans(subject_id)
        plan = self._repo.add_plan(
            LessonPlan(
                id=new_id(),
                subject_id=subject_id,
                status=PlanStatus.ACTIVE,
                graph_version=loaded.subject.graph_version,
                coverage_at_creation=coverage(loaded.states),
            )
        )
        units = [
            self._persist_unit(plan, loaded, sequenced, index)
            for index in range(len(sequenced.units))
        ]
        await self._session.commit()
        return self._render_plan(plan, units, loaded, sequenced)

    def _persist_unit(
        self,
        plan: LessonPlan,
        loaded: LoadedSubject,
        sequenced: PlanSequence,
        index: int,
    ) -> PlanUnit:
        """Write one sequenced unit to the database.

        :param plan: The plan being built.
        :param loaded: The subject being planned.
        :param sequenced: The full sequencing result.
        :param index: Which unit of it to persist.
        """
        unit = sequenced.units[index]
        name = loaded.graph.nodes[unit.node_id].name
        return self._repo.add_unit(
            PlanUnit(
                id=new_id(),
                plan_id=plan.id,
                subject_id=plan.subject_id,
                node_id=unit.node_id,
                seq=unit.seq,
                title=name,
                objective=f"Explain {name} and apply it to a case you have not seen.",
                estimated_minutes=self._settings.default_unit_minutes,
                status=UnitStatus.PENDING,
                interleaved_node_ids=list(unit.interleaved_node_ids),
                first_acquisition=unit.first_acquisition,
                placement_reason=unit.placement_reason,
                priority=unit.priority,
                exit_check_item_ids=[],
            )
        )

    # --- reading -------------------------------------------------------------

    async def read(self, plan_id: str) -> PlanRead:
        """Fetch a plan and its units.

        :param plan_id: The plan to read.
        :raises LookupError: If the plan does not exist.
        """
        plan = await self._require_plan(plan_id)
        units = await self._repo.units_for_plan(plan_id)
        loaded = await self._loader.load(plan.subject_id)
        await self._session.commit()
        return self._render_plan(plan, units, loaded, None)

    async def active(self, subject_id: str) -> PlanRead | None:
        """Fetch a subject's current plan, if it has one.

        :param subject_id: The subject to read.
        """
        plan = await self._repo.active_plan(subject_id)
        if plan is None:
            return None
        return await self.read(plan.id)

    # --- insertion -----------------------------------------------------------

    async def insert_unit(self, plan_id: str, node_id: str) -> PlanRead:
        """Add a concept to a plan, as early as its prerequisites allow.

        This is what accepting an ask-anything plan offer does, and it has to keep
        the invariant the sequencer establishes rather than quietly breaking it for
        the sake of responsiveness. Two things follow:

        * **Any missing prerequisites come with it.** A concept whose prerequisite
          is unmastered *and* absent from the plan -- the normal case when the plan
          was generated with a limit -- cannot simply be dropped in; the unit would
          depend on something the learner is never taught. The whole unscheduled
          prerequisite chain is inserted ahead of it, in topological order.
        * **Finished units are never displaced.** History does not move, so the
          insertion point is never earlier than the last unit already started or
          closed.

        :param plan_id: The plan to insert into.
        :param node_id: The concept to schedule.
        :raises LookupError: If the plan or concept does not exist.
        :raises UnitAlreadyScheduled: If the plan already has a pending unit for it.
        """
        plan = await self._require_plan(plan_id)
        loaded = await self._loader.load(plan.subject_id)
        if node_id not in loaded.graph:
            raise LookupError(node_id)

        units = await self._repo.units_for_plan(plan_id)
        if any(
            unit.node_id == node_id and unit.status in {UnitStatus.PENDING, UnitStatus.IN_PROGRESS}
            for unit in units
        ):
            raise UnitAlreadyScheduled(node_id)

        chain = self._missing_chain(loaded, units, node_id)
        position = self._earliest_position(loaded, units, node_id)
        taught = await self._repo.taught_node_ids(plan.subject_id)
        await self._renumber(units, insert_at=position, count=len(chain))

        asked_name = loaded.graph.nodes[node_id].name
        for offset, needed_id in enumerate(chain):
            name = loaded.graph.nodes[needed_id].name
            reason = (
                f"Added because you asked about {asked_name}. Placed as early as its "
                "prerequisites allow."
                if needed_id == node_id
                else (
                    f"Added because {asked_name} depends on it and your plan did not cover it yet."
                )
            )
            self._repo.add_unit(
                PlanUnit(
                    id=new_id(),
                    plan_id=plan.id,
                    subject_id=plan.subject_id,
                    node_id=needed_id,
                    seq=position + offset,
                    title=name,
                    objective=f"Explain {name} and apply it to a case you have not seen.",
                    estimated_minutes=self._settings.default_unit_minutes,
                    status=UnitStatus.PENDING,
                    interleaved_node_ids=[],
                    first_acquisition=needed_id not in taught,
                    placement_reason=reason,
                    priority=0.0,
                    exit_check_item_ids=[],
                )
            )
        await self._session.commit()
        return await self.read(plan_id)

    def _missing_chain(
        self, loaded: LoadedSubject, units: list[PlanUnit], node_id: str
    ) -> tuple[str, ...]:
        """The concepts that have to be inserted for one concept to be teachable.

        Every unmastered prerequisite, transitively, that the plan does not already
        contain -- plus the concept itself -- in topological order so each precedes
        whatever depends on it.

        :param loaded: The subject the plan belongs to.
        :param units: The plan's existing units.
        :param node_id: The concept being inserted.
        """
        present = {unit.node_id for unit in units}
        needed = {node_id} | {
            ancestor
            for ancestor in loaded.graph.ancestors(node_id)
            if ancestor not in present
            and loaded.states[ancestor].mastery < self._params.mastery_threshold
        }
        return tuple(n for n in loaded.graph.topological_order() if n in needed)

    async def _renumber(self, units: list[PlanUnit], *, insert_at: int, count: int) -> None:
        """Open a gap of ``count`` positions at ``insert_at``.

        Done in two passes through a large offset because ``(plan_id, seq)`` is
        unique: shifting unit 3 to 4 in a single pass collides with the unit already
        at 4, and SQLite checks the constraint per statement rather than at commit.

        :param units: The plan's units, in sequence order.
        :param insert_at: The position being freed.
        :param count: How many positions to free.
        """
        originals = [(unit, unit.seq) for unit in units]
        for unit, _ in originals:
            unit.seq += _SEQ_OFFSET
        await self._session.flush()
        for unit, original in originals:
            unit.seq = original if original < insert_at else original + count
        await self._session.flush()

    def _earliest_position(self, loaded: LoadedSubject, units: list[PlanUnit], node_id: str) -> int:
        """Find the first sequence position a concept can legally occupy.

        Two floors, taken at their maximum: past every unit already started or
        closed, and past every prerequisite -- direct or transitive -- the plan
        already schedules.

        :param loaded: The subject the plan belongs to.
        :param units: The plan's existing units, in sequence order.
        :param node_id: The concept being inserted.
        """
        ancestors = set(loaded.graph.ancestors(node_id))
        settled = {UnitStatus.COMPLETE, UnitStatus.SKIPPED, UnitStatus.IN_PROGRESS}
        position = 0
        for index, unit in enumerate(units):
            if unit.status in settled or unit.node_id in ancestors:
                position = index + 1
        return min(position, len(units))

    # --- running -------------------------------------------------------------

    async def next_unit(self, plan_id: str) -> NextUnit:
        """Return the next unit to study, preparing it if it has not been served.

        Preparation is the model call that writes the unit's teaching frame, the
        generation of its exit check, and the creation of the lesson row its prose
        will stream into. All three happen once, on first serve.

        :param plan_id: The plan being followed.
        :raises LookupError: If the plan does not exist.
        """
        plan = await self._require_plan(plan_id)
        unit = await self._repo.next_unit(plan_id)
        if unit is None:
            return NextUnit(unit=None, finished=True, exit_check=[], lesson_id=None)

        loaded = await self._loader.load(plan.subject_id)
        if unit.status == UnitStatus.PENDING:
            await self._prepare(loaded, unit)
            unit.status = UnitStatus.IN_PROGRESS

        items = [
            item
            for item in [
                await self._assessment.get_item(item_id) for item_id in unit.exit_check_item_ids
            ]
            if item is not None
        ]
        lesson = await self._lessons.ensure_for_unit(loaded, unit)
        await self._session.commit()

        return NextUnit(
            unit=self._render_unit(unit, loaded),
            finished=False,
            exit_check=[self._render_item(item, loaded) for item in items],
            lesson_id=lesson.id,
        )

    async def _prepare(self, loaded: LoadedSubject, unit: PlanUnit) -> None:
        """Write a unit's teaching frame and generate its exit check.

        :param loaded: The subject the unit belongs to.
        :param unit: The unit being served for the first time.
        """
        brief = await self._adapter.generate_structured(
            schema=UnitBrief,
            system=UNIT_BRIEF_SYSTEM,
            prompt=self._brief_prompt(loaded, unit),
            task="unit_brief",
            context=loaded.context(),
        )
        unit.title = brief.title
        unit.objective = brief.objective
        unit.estimated_minutes = brief.estimated_minutes

        difficulty = loaded.graph.tier(unit.node_id)
        item_ids: list[str] = []
        for index in range(self._settings.exit_check_items):
            item = await self._items.item_for(
                loaded,
                unit.node_id,
                difficulty=difficulty,
                item_format=EXIT_CHECK_FORMATS[index % len(EXIT_CHECK_FORMATS)],
            )
            if item.id not in item_ids:
                item_ids.append(item.id)
        unit.exit_check_item_ids = item_ids

    def _brief_prompt(self, loaded: LoadedSubject, unit: PlanUnit) -> str:
        """Build the instruction that writes a unit's teaching frame.

        :param loaded: The subject the unit belongs to.
        :param unit: The unit being prepared.
        """
        meta = loaded.graph.nodes[unit.node_id]
        node = loaded.nodes[unit.node_id]
        state = loaded.states.get(unit.node_id)
        prereqs = sorted(loaded.graph.nodes[p].name for p in loaded.graph.prereqs(unit.node_id))
        return "\n".join(
            [
                f"CONCEPT: {meta.name}",
                f"DEFINITION: {node.definition}",
                f"TIER: {meta.tier}",
                f"CURRENT MASTERY: {state.mastery:.2f}" if state else "CURRENT MASTERY: unknown",
                f"PREREQUISITES: {', '.join(prereqs) if prereqs else '(none)'}",
                f"PLACEMENT: {unit.placement_reason}",
                "",
                "Write the teaching frame for this unit.",
            ]
        )

    async def complete_unit(self, unit_id: str, payload: UnitComplete) -> UnitCompleteResult:
        """Grade a unit's exit check, update mastery, and close the unit.

        A poor exit check still closes the unit. The evidence is what matters, and
        it is recorded: a low score lowers the estimate, which is what brings the
        concept back around rather than trapping the learner on it.

        :param unit_id: The unit being closed.
        :param payload: The learner's exit-check answers.
        :raises LookupError: If the unit does not exist.
        :raises UnitAlreadyClosed: If it has already been completed or skipped.
        :raises UnitItemMismatch: If an answer names an item outside this unit.
        """
        unit = await self._repo.get_unit(unit_id)
        if unit is None:
            raise LookupError(unit_id)
        if unit.status in {UnitStatus.COMPLETE, UnitStatus.SKIPPED}:
            raise UnitAlreadyClosed(unit_id)

        loaded = await self._loader.load(unit.subject_id)
        before = loaded.states[unit.node_id].mastery

        scores: list[float] = []
        feedback: list[str] = []
        if not payload.skipped:
            for answer in payload.answers:
                if answer.item_id not in unit.exit_check_item_ids:
                    raise UnitItemMismatch(answer.item_id)
                item = await self._assessment.get_item(answer.item_id)
                if item is None:
                    raise LookupError(answer.item_id)
                result = await self._items.grade(loaded, item, answer.answer)
                self._mastery.apply(
                    loaded,
                    node_id=item.node_id,
                    difficulty=item.difficulty,
                    score=result.score,
                )
                self._record(
                    unit, item, answer.answer, result.score, result.correct, result.feedback
                )
                scores.append(result.score)
                feedback.append(result.feedback)

        if scores:
            # The exit check is this concept's first retrieval, which is exactly the
            # observation the scheduler most needs. Without folding it in, a concept
            # would sit unscheduled after being taught and never come back around.
            await self._reviews.record_retrieval(
                loaded,
                unit.node_id,
                grade_for(sum(scores) / len(scores), self._settings),
            )

        unit.status = UnitStatus.SKIPPED if payload.skipped else UnitStatus.COMPLETE
        unit.completed_at = utcnow()
        # The new status has to reach the database before the next-unit query runs,
        # or that query re-selects the unit just closed and the plan never advances.
        await self._session.flush()
        following = await self._repo.next_unit(unit.plan_id)
        await self._session.commit()

        return UnitCompleteResult(
            unit_id=unit.id,
            status=unit.status,
            exit_score=(sum(scores) / len(scores)) if scores else None,
            mastery_before=before,
            mastery_after=loaded.states[unit.node_id].mastery,
            feedback=feedback,
            coverage_now=coverage(loaded.states),
            next_unit_id=following.id if following else None,
        )

    def _record(
        self,
        unit: PlanUnit,
        item: QuizItem,
        answer: str,
        score: float,
        correct: bool,
        feedback: str,
    ) -> None:
        """Log one graded exit-check answer.

        :param unit: The unit being closed.
        :param item: The item that was answered.
        :param answer: The learner's answer.
        :param score: The rubric score.
        :param correct: Whether it was substantially right.
        :param feedback: The grader's feedback.
        """
        self._assessment.add_response(
            ItemResponse(
                id=new_id(),
                subject_id=unit.subject_id,
                item_id=item.id,
                node_id=item.node_id,
                session_id=None,
                source=QueueKind.EXIT_CHECK,
                raw_answer=answer,
                score=score,
                grade=int(grade_for(score, self._settings)),
                correct=correct,
                feedback=feedback,
                mastery_before=None,
                mastery_after=None,
                propagation={},
            )
        )

    # --- rendering -----------------------------------------------------------

    async def _require_plan(self, plan_id: str) -> LessonPlan:
        """Fetch a plan or raise.

        :param plan_id: The plan's id.
        :raises LookupError: If it does not exist.
        """
        plan = await self._repo.get_plan(plan_id)
        if plan is None:
            raise LookupError(plan_id)
        return plan

    def _render_plan(
        self,
        plan: LessonPlan,
        units: list[PlanUnit],
        loaded: LoadedSubject,
        sequenced: PlanSequence | None,
    ) -> PlanRead:
        """Shape a plan and its units for the API.

        :param plan: The plan row.
        :param units: Its units, in sequence order.
        :param loaded: The subject, for concept names and current mastery.
        :param sequenced: The sequencing result when the plan was just generated;
            None when reading a stored plan, where the counts are recovered from
            the graph instead.
        """
        if sequenced is not None:
            skipped = len(sequenced.skipped_mastered)
            truncated = len(sequenced.truncated)
        else:
            planned = {unit.node_id for unit in units}
            skipped = sum(
                1
                for node_id in loaded.graph.node_ids
                if node_id not in planned
                and loaded.states[node_id].mastery >= self._params.mastery_threshold
            )
            truncated = sum(
                1
                for node_id in loaded.graph.node_ids
                if node_id not in planned
                and loaded.states[node_id].mastery < self._params.mastery_threshold
            )
        return PlanRead(
            id=plan.id,
            subject_id=plan.subject_id,
            status=plan.status,
            graph_version=plan.graph_version,
            coverage_at_creation=plan.coverage_at_creation,
            coverage_now=coverage(loaded.states),
            created_at=plan.created_at,
            units=[self._render_unit(unit, loaded) for unit in units],
            skipped_mastered=skipped,
            truncated=truncated,
        )

    @staticmethod
    def _render_unit(unit: PlanUnit, loaded: LoadedSubject) -> PlanUnitRead:
        """Shape one unit for the API.

        :param unit: The unit row.
        :param loaded: The subject, for concept names.
        """
        return PlanUnitRead(
            id=unit.id,
            seq=unit.seq,
            node_id=unit.node_id,
            node_name=loaded.graph.nodes[unit.node_id].name,
            tier=loaded.graph.tier(unit.node_id),
            title=unit.title,
            objective=unit.objective,
            estimated_minutes=unit.estimated_minutes,
            status=unit.status,
            placement_reason=unit.placement_reason,
            priority=unit.priority,
            interleaved_node_ids=list(unit.interleaved_node_ids),
            interleaved_names=[
                loaded.graph.nodes[node_id].name
                for node_id in unit.interleaved_node_ids
                if node_id in loaded.graph
            ],
            first_acquisition=unit.first_acquisition,
            completed_at=unit.completed_at,
        )

    @staticmethod
    def _render_item(item: QuizItem, loaded: LoadedSubject) -> ExitCheckItemRead:
        """Shape one exit-check item for the API.

        :param item: The item row.
        :param loaded: The subject, for concept names.
        """
        return ExitCheckItemRead(
            id=item.id,
            node_id=item.node_id,
            node_name=loaded.graph.nodes[item.node_id].name,
            tier=loaded.graph.tier(item.node_id),
            item_format=item.item_format,
            difficulty=item.difficulty,
            stem=item.stem,
            choices=list(item.choices),
        )
