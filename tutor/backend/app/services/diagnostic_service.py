"""The adaptive diagnostic loop.

Select the most informative concept, generate an item pitched at the learner's
level for it, grade the answer, update the estimate, propagate what the answer
implies about the neighbourhood, and stop as soon as the estimate is good enough.

The selection and update logic lives in :mod:`app.mastery` and is tested against a
synthetic learner; this module is the part that talks to the database and the
model.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db import new_id, utcnow
from app.llm.base import LLMAdapter
from app.mastery.selection import select_difficulty, select_next_node, should_stop
from app.mastery.state import MasteryParams
from app.models.assessment import DiagnosticSession, ItemResponse
from app.models.enums import QueueKind, SessionStatus
from app.models.graph import MasteryRecord
from app.repositories.assessment import AssessmentRepository
from app.repositories.graph import GraphRepository
from app.scheduling.grading import grade_for
from app.schemas.diagnostic import (
    AnswerResult,
    ItemRead,
    NextItem,
    SessionRead,
)
from app.services.graph_loader import GraphLoader, GraphNotReadyError
from app.services.item_service import ItemService
from app.services.mastery_service import MasteryUpdater


class DiagnosticFinished(RuntimeError):
    """Raised when an answer arrives for a session that has already stopped."""


class ItemMismatch(ValueError):
    """Raised when an answer names an item that was not the one asked."""


class DiagnosticService:
    """Runs adaptive diagnostic sessions."""

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
        self._repo = AssessmentRepository(session)
        self._graph = GraphRepository(session)
        self._items = ItemService(session, adapter, settings)
        self._mastery = MasteryUpdater(self._params)

    async def start(self, subject_id: str, *, max_items: int | None = None) -> DiagnosticSession:
        """Begin a diagnostic, or resume one already in progress.

        Resuming rather than starting fresh means a closed tab does not throw away
        the answers already given.

        :param subject_id: The subject to assess.
        :param max_items: Override for the configured item cap.
        :raises GraphNotReadyError: If the concept graph is not built yet.
        """
        loaded = await self._loader.load(subject_id)
        if not loaded.graph.node_ids:
            raise GraphNotReadyError(loaded.subject.graph_status)

        existing = await self._repo.active_session(subject_id)
        if existing is not None:
            return existing

        diagnostic = self._repo.add_session(
            DiagnosticSession(
                id=new_id(),
                subject_id=subject_id,
                status=SessionStatus.ACTIVE,
                graph_version=loaded.subject.graph_version,
                max_items=max_items or self._settings.diagnostic_max_items,
                min_items=self._settings.diagnostic_min_items,
                confidence_target=self._settings.diagnostic_confidence_target,
            )
        )
        await self._session.commit()
        return diagnostic

    async def next_item(self, session_id: str) -> NextItem:
        """Choose and return the next question, or report that the session is done.

        :param session_id: The diagnostic session.
        :raises LookupError: If the session does not exist.
        """
        diagnostic = await self._require(session_id)
        loaded = await self._loader.load(diagnostic.subject_id)

        asked = await self._asked_node_ids(session_id)
        decision = should_stop(
            loaded.states,
            asked=diagnostic.asked_count,
            min_items=diagnostic.min_items,
            max_items=diagnostic.max_items,
            confidence_target=diagnostic.confidence_target,
        )
        node_id = (
            None
            if decision.stop
            else select_next_node(
                loaded.graph, loaded.states, self._params, exclude=frozenset(asked)
            )
        )
        if node_id is None:
            reason = decision.reason or "exhausted"
            await self._finish(diagnostic, reason, decision.mean_confidence)
            return NextItem(
                item=None,
                finished=True,
                stop_reason=reason,
                session=self._render(diagnostic, decision.mean_confidence),
            )

        state = loaded.states[node_id]
        difficulty = select_difficulty(loaded.graph, node_id, state, self._params)
        counts = await self._repo.response_counts(diagnostic.subject_id)
        item = await self._items.item_for(
            loaded,
            node_id,
            difficulty=difficulty,
            observations=counts.get(node_id, 0),
        )
        await self._session.commit()

        return NextItem(
            item=ItemRead(
                id=item.id,
                node_id=node_id,
                node_name=loaded.graph.nodes[node_id].name,
                tier=loaded.graph.tier(node_id),
                item_format=item.item_format,
                difficulty=item.difficulty,
                stem=item.stem,
                choices=list(item.choices),
                asked_count=diagnostic.asked_count,
                max_items=diagnostic.max_items,
            ),
            finished=False,
            stop_reason=None,
            session=self._render(diagnostic, decision.mean_confidence),
        )

    async def answer(self, session_id: str, item_id: str, answer: str) -> AnswerResult:
        """Grade an answer, update the model, and report what moved.

        :param session_id: The diagnostic session.
        :param item_id: The item being answered.
        :param answer: The learner's answer.
        :raises LookupError: If the session or item does not exist.
        :raises DiagnosticFinished: If the session has already stopped.
        :raises ItemMismatch: If the item belongs to a different subject.
        """
        diagnostic = await self._require(session_id)
        if diagnostic.status != SessionStatus.ACTIVE:
            raise DiagnosticFinished(session_id)

        item = await self._repo.get_item(item_id)
        if item is None:
            raise LookupError(item_id)
        if item.subject_id != diagnostic.subject_id:
            raise ItemMismatch(item_id)

        loaded = await self._loader.load(diagnostic.subject_id)
        result = await self._items.grade(loaded, item, answer)
        applied = self._mastery.apply(
            loaded, node_id=item.node_id, difficulty=item.difficulty, score=result.score
        )

        grade = grade_for(result.score, self._settings)
        self._repo.add_response(
            ItemResponse(
                id=new_id(),
                subject_id=diagnostic.subject_id,
                item_id=item.id,
                node_id=item.node_id,
                session_id=session_id,
                source=QueueKind.DIAGNOSTIC,
                raw_answer=answer,
                score=result.score,
                grade=int(grade),
                correct=result.correct,
                feedback=result.feedback,
                mastery_before=applied.direct_before.mastery,
                mastery_after=applied.direct_after.mastery,
                propagation={
                    change.node_id: change.mastery_after
                    for change in applied.changes
                    if change.propagated
                },
            )
        )
        diagnostic.asked_count += 1

        decision = should_stop(
            loaded.states,
            asked=diagnostic.asked_count,
            min_items=diagnostic.min_items,
            max_items=diagnostic.max_items,
            confidence_target=diagnostic.confidence_target,
        )
        if decision.stop:
            await self._finish(diagnostic, decision.reason or "complete", decision.mean_confidence)
        await self._session.commit()

        return AnswerResult(
            correct=result.correct,
            score=result.score,
            feedback=result.feedback,
            misconception=result.misconception,
            answer_key=item.answer_key,
            changes=applied.changes,
            session=self._render(diagnostic, decision.mean_confidence),
        )

    async def _asked_node_ids(self, session_id: str) -> set[str]:
        """Concepts already asked about in this session.

        :param session_id: The diagnostic session.
        """
        return {response.node_id for response in await self._repo.responses_for_session(session_id)}

    async def _require(self, session_id: str) -> DiagnosticSession:
        """Fetch a session or raise.

        :param session_id: The diagnostic session.
        :raises LookupError: If it does not exist.
        """
        diagnostic = await self._repo.get_session(session_id)
        if diagnostic is None:
            raise LookupError(session_id)
        return diagnostic

    async def _finish(
        self, diagnostic: DiagnosticSession, reason: str, mean_confidence: float
    ) -> None:
        """Close a session, recording why and how confident it ended.

        :param diagnostic: The session to close.
        :param reason: Machine-readable stop reason.
        :param mean_confidence: Mean confidence at the end.
        """
        diagnostic.status = SessionStatus.COMPLETE
        diagnostic.stop_reason = reason
        diagnostic.final_mean_confidence = mean_confidence
        diagnostic.completed_at = utcnow()
        await self._session.commit()

    @staticmethod
    def _render(diagnostic: DiagnosticSession, mean_confidence: float) -> SessionRead:
        """Shape a session for the API.

        :param diagnostic: The session.
        :param mean_confidence: Mean confidence across the graph.
        """
        return SessionRead(
            id=diagnostic.id,
            subject_id=diagnostic.subject_id,
            status=diagnostic.status,
            asked_count=diagnostic.asked_count,
            max_items=diagnostic.max_items,
            min_items=diagnostic.min_items,
            mean_confidence=mean_confidence,
            stop_reason=diagnostic.stop_reason,
        )


__all__ = [
    "DiagnosticFinished",
    "DiagnosticService",
    "ItemMismatch",
    "MasteryRecord",
]
