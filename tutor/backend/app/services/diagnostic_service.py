"""The adaptive diagnostic loop.

Select the most informative concept, generate an item pitched at the learner's
level for it, grade the answer, update the estimate, propagate what the answer
implies about the neighbourhood, and stop as soon as the estimate is good enough.

The selection and update logic lives in :mod:`app.mastery` and is tested against a
synthetic learner; this module is the part that talks to the database and the
model.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db import new_id, utcnow
from app.llm.base import LLMAdapter
from app.mastery.elo import update_mastery
from app.mastery.propagation import apply_propagation, propagate_evidence, refresh_priors
from app.mastery.selection import select_difficulty, select_next_node, should_stop
from app.mastery.state import MasteryParams, MasteryState
from app.models.assessment import DiagnosticSession, ItemResponse, QuizItem
from app.models.enums import QueueKind, SessionStatus
from app.models.graph import MasteryRecord
from app.repositories.assessment import AssessmentRepository
from app.repositories.graph import GraphRepository
from app.scheduling.grading import grade_for
from app.schemas.diagnostic import (
    AnswerResult,
    ItemRead,
    MasteryChange,
    NextItem,
    SessionRead,
)
from app.services.graph_loader import GraphLoader, GraphNotReadyError, LoadedSubject
from app.services.item_service import ItemService


class DiagnosticFinished(RuntimeError):
    """Raised when an answer arrives for a session that has already stopped."""


class ItemMismatch(ValueError):
    """Raised when an answer names an item that was not the one asked."""


@dataclass(slots=True)
class _Applied:
    """The mastery movement caused by one answer.

    :param changes: Per-concept before and after values.
    :param direct_after: The answered concept's new state.
    """

    changes: list[MasteryChange]
    direct_after: MasteryState


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
        applied = self._apply(loaded, item, result.score)

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
                mastery_before=next(
                    (c.mastery_before for c in applied.changes if c.node_id == item.node_id),
                    None,
                ),
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

    def _apply(self, loaded: LoadedSubject, item: QuizItem, score: float) -> _Applied:
        """Update the answered concept and everything the answer informs.

        :param loaded: The subject being assessed.
        :param item: The item that was answered.
        :param score: The rubric score.
        """
        node_id = item.node_id
        before = loaded.states[node_id]
        update = update_mastery(
            before, difficulty=item.difficulty, score=score, params=self._params
        )
        loaded.states[node_id] = update.state

        propagated = propagate_evidence(
            loaded.graph,
            node_id=node_id,
            mastery_delta=update.mastery_delta,
            observed_mastery=update.state.mastery,
            params=self._params,
        )
        moved = apply_propagation(loaded.states, propagated)
        loaded.states.update(moved)
        # An answer changes what untested concepts should be expected to know, and
        # the priors have to follow or the selector keeps re-asking settled ground.
        reseeded = refresh_priors(loaded.graph, loaded.states, params=self._params)
        loaded.states.update(reseeded)

        changes = [
            MasteryChange(
                node_id=node_id,
                node_name=loaded.graph.nodes[node_id].name,
                mastery_before=before.mastery,
                mastery_after=update.state.mastery,
                confidence_after=update.state.confidence,
                propagated=False,
            )
        ]
        for other_id, state in moved.items():
            changes.append(
                MasteryChange(
                    node_id=other_id,
                    node_name=loaded.graph.nodes[other_id].name,
                    mastery_before=state.mastery - propagated[other_id].mastery_delta,
                    mastery_after=state.mastery,
                    confidence_after=state.confidence,
                    propagated=True,
                )
            )

        self._persist(loaded, node_id, set(moved) | set(reseeded))
        return _Applied(changes=changes, direct_after=update.state)

    def _persist(self, loaded: LoadedSubject, direct_id: str, indirect_ids: set[str]) -> None:
        """Write updated estimates back to their rows.

        :param loaded: The subject being assessed.
        :param direct_id: The concept that was answered.
        :param indirect_ids: Concepts changed by propagation or prior refresh.
        """
        now = utcnow()
        for node_id in {direct_id} | indirect_ids:
            record = loaded.records.get(node_id)
            state = loaded.states.get(node_id)
            if record is None or state is None:
                continue
            record.mastery = state.mastery
            record.confidence = state.confidence
            record.last_seen_at = now
            record.decayed_at = now
            if node_id == direct_id:
                record.direct_observations += 1
            else:
                record.indirect_observations += 1

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
