"""Assembling the report the learner sees after a diagnostic.

Almost all of the thinking lives in :mod:`app.mastery.coverage`, which is pure and
tested on its own. This module's job is to load the subject, ask those functions
their questions, and add the three facts they cannot know: how calibrated the
spacing is, whether a plan already exists, and how many graph suggestions are still
open.

The one number worth guarding is coverage. It is the mean estimated mastery over
every live concept and nothing else -- not lessons completed, not units passed. A
learner who has read every unit and retained a third of it has not covered the
subject, and reporting otherwise would make the headline number a measure of
diligence rather than of knowledge.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.mastery.coverage import (
    BlockingReport,
    NodeScore,
    build_report,
    next_tier_blockers,
    node_scores,
    ready_to_learn,
    strengths,
    weaknesses,
)
from app.mastery.state import MasteryParams
from app.repositories.assessment import AssessmentRepository
from app.repositories.changesets import ChangesetRepository
from app.repositories.plans import PlanRepository
from app.scheduling.calibration import Calibration, calibrate
from app.schemas.report import (
    BlockingRead,
    CalibrationRead,
    NodeScoreRead,
    ReportRead,
    TierSummaryRead,
)
from app.services.graph_loader import GraphLoader, LoadedSubject

#: Concepts listed as immediately available to study.
READY_LIMIT = 8


class ReportService:
    """Builds the coverage report for a subject."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        """
        :param session: The active database session.
        :param settings: Runtime configuration.
        """
        self._session = session
        self._settings = settings
        self._params = MasteryParams.from_settings(settings)
        self._loader = GraphLoader(session, self._params)
        self._assessment = AssessmentRepository(session)
        self._changesets = ChangesetRepository(session)
        self._plans = PlanRepository(session)

    async def build(self, subject_id: str) -> ReportRead:
        """Assemble the whole report.

        :param subject_id: The subject to report on.
        :raises SubjectNotFoundError: If the subject does not exist.
        """
        loaded = await self._loader.load(subject_id)
        report = build_report(loaded.graph, loaded.states, self._params)
        blocking = next_tier_blockers(loaded.graph, loaded.states, self._params)
        calibration = await self.calibrate(subject_id)

        by_id = {score.node_id: score for score in node_scores(loaded.graph, loaded.states)}
        ready = [
            by_id[node_id]
            for node_id in ready_to_learn(loaded.graph, loaded.states, self._params)
            if node_id in by_id
        ]
        ready.sort(key=lambda score: (score.mastery, score.tier, score.name))

        responses = await self._assessment.responses_for_subject(subject_id)
        open_suggestions = await self._changesets.open_suggestions(subject_id)
        plan = await self._plans.active_plan(subject_id)
        # Loading applies decay, and decay is persisted so it is not re-applied on
        # the next read. Reading the report is therefore a write.
        await self._session.commit()

        return ReportRead(
            subject_id=subject_id,
            subject_name=loaded.subject.name,
            graph_version=loaded.subject.graph_version,
            coverage=report.coverage,
            mean_confidence=report.mean_confidence,
            total_nodes=report.total_nodes,
            mastered_nodes=report.mastered_nodes,
            unassessed_nodes=report.unassessed_nodes,
            tiers=[
                TierSummaryRead(
                    tier=tier.tier,
                    count=tier.count,
                    mean_mastery=tier.mean_mastery,
                    mean_confidence=tier.mean_confidence,
                    mastered=tier.mastered,
                )
                for tier in report.tiers
            ],
            strengths=_render_all(strengths(loaded.graph, loaded.states)),
            weaknesses=_render_all(weaknesses(loaded.graph, loaded.states, self._params)),
            blocking=_render_blocking(blocking),
            calibration=calibration,
            ready_to_learn=_render_all(ready[:READY_LIMIT]),
            open_suggestions=len(open_suggestions),
            has_plan=plan is not None,
            diagnostic_responses=len(responses),
        )

    async def calibrate(self, subject_id: str) -> CalibrationRead:
        """Judge whether the spacing is pitched right for this subject.

        :param subject_id: The subject to assess.
        """
        scores = await self._assessment.retrieval_stats(subject_id)
        return _render_calibration(calibrate(scores, self._settings))

    async def load(self, subject_id: str) -> LoadedSubject:
        """Load a subject, for callers that want the report's view of it.

        :param subject_id: The subject to load.
        :raises SubjectNotFoundError: If the subject does not exist.
        """
        return await self._loader.load(subject_id)


def _render(score: NodeScore) -> NodeScoreRead:
    """Shape one concept's standing for the API.

    :param score: The concept's standing.
    """
    return NodeScoreRead(
        node_id=score.node_id,
        name=score.name,
        tier=score.tier,
        mastery=score.mastery,
        confidence=score.confidence,
        unblocks=score.unblocks,
    )


def _render_all(scores: tuple[NodeScore, ...] | list[NodeScore]) -> list[NodeScoreRead]:
    """Shape a ranked list of concepts for the API.

    :param scores: The concepts to shape.
    """
    return [_render(score) for score in scores]


def _render_blocking(blocking: BlockingReport) -> BlockingRead:
    """Shape the blocking report for the API.

    :param blocking: What is holding the next tier up.
    """
    return BlockingRead(
        target_tier=blocking.target_tier,
        blocked=_render_all(blocking.blocked),
        blockers=_render_all(blocking.blockers),
    )


def _render_calibration(calibration: Calibration) -> CalibrationRead:
    """Shape the calibration verdict for the API.

    :param calibration: The verdict.
    """
    return CalibrationRead(
        success_rate=calibration.success_rate,
        sample_size=calibration.sample_size,
        verdict=calibration.verdict,
        advice=calibration.advice,
    )
