"""Ask anything: a free-form question, classified and answered as a lesson.

Three routes out of one question, decided by a structured classification call
against the live graph:

* **existing_node** -- the graph already covers it. The answer is pitched at the
  learner's current estimate for that concept, and the offer afterwards is to move
  the concept up the plan.
* **new_node** -- inside the subject, missing from the graph. This is the most
  valuable case, because the learner has just found a gap the decomposition missed.
  A graph *suggestion* is recorded proposing the concept properly. Nothing is added.
* **off_subject** -- outside the subject. Answered, and the graph is not touched at
  all: no node, no edge, no suggestion, no version bump.

**Why nothing is ever written to the graph here.** The acceptance criterion is that
an off-subject question must not corrupt the graph, and the way to satisfy that is
not to be careful -- it is to have no code path from this module to a node insert.
Every structural consequence of a question goes through the same per-operation
review as any other changeset. A question is evidence that the graph might be
wrong; it is not authority to change it.

**Reading is not evidence.** An answer streamed here does not move any mastery
estimate. The learner read something; they have not retrieved it. The fold-back into
the knowledge model is the suggestion, the plan offer, and the cached lesson the
plan will reuse -- not a silent bump to a number that is supposed to mean "can
recall this on demand".
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db import new_id
from app.llm.base import LLMAdapter
from app.llm.prompts import ASK_SYSTEM, CLASSIFY_SYSTEM
from app.llm.schemas import QueryClassification
from app.mastery.state import MasteryParams
from app.models.enums import UnitStatus
from app.models.plan import Lesson
from app.repositories.graph import GraphRepository, name_key
from app.repositories.plans import PlanRepository
from app.schemas.ask import AskDone, AskMeta, PlanOffer
from app.services.graph_loader import GraphLoader, LoadedSubject
from app.services.item_service import level_for
from app.services.suggestion_service import SuggestionService
from app.sse import sse

#: Characters per replayed chunk when an answer comes from cache. Chunked rather
#: than sent whole so the client's rendering path is the same either way.
REPLAY_CHUNK = 256


def ask_cache_key(subject_id: str, node_id: str | None, question: str) -> str:
    """Build the key an answer is cached under.

    Keyed on the *question*, not on the concept, and in a namespace of its own.
    A unit lesson and an answer to a question about the same concept are different
    documents written from different system prompts, and letting them share a key
    would serve one in place of the other.

    :param subject_id: The subject the question was asked against.
    :param node_id: The concept it resolved to, if any.
    :param question: The question as asked, normalized for whitespace and case.
    """
    normalized = " ".join(question.lower().split())
    raw = f"ask|{subject_id}|{node_id or '-'}|{normalized}"
    return hashlib.sha256(raw.encode()).hexdigest()[:48]


class AskService:
    """Answers free-form questions, streaming the result.

    Takes a session *factory* rather than a session. The answer is produced inside
    a streaming response body, which runs after the request's own dependencies have
    been torn down, so it has to own the session it writes through.
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

    async def stream(self, subject_id: str, question: str) -> AsyncIterator[str]:
        """Classify a question, then stream its answer as SSE frames.

        :param subject_id: The subject the question is asked against.
        :param question: The learner's question.
        """
        async with self._factory() as session:
            loader = GraphLoader(session, self._params)
            loaded = await loader.load(subject_id)
            classification = await self._classify(loaded, question)
            resolved, node_id = self._resolve(loaded, classification)

            suggestion_id: str | None = None
            if resolved == "new_node":
                suggestion_id = await self._suggest(session, loaded, question, classification)

            lesson, cached = await self._lesson_row(
                session, loaded, question, classification, node_id
            )
            await session.commit()

            yield sse(
                "meta",
                AskMeta(
                    question=question,
                    kind=classification.kind,
                    resolved_kind=resolved,
                    title=classification.title,
                    node_id=node_id,
                    node_name=loaded.graph.nodes[node_id].name if node_id else None,
                    reason=classification.reason,
                    lesson_id=lesson.id,
                    cached=cached,
                    graph_version=loaded.subject.graph_version,
                ).model_dump(),
            )

            body = ""
            if cached:
                body = lesson.markdown
                for start in range(0, len(body), REPLAY_CHUNK):
                    yield sse("delta", body[start : start + REPLAY_CHUNK])
            else:
                pieces: list[str] = []
                async for delta in self._adapter.stream_text(
                    system=ASK_SYSTEM,
                    prompt=self._answer_prompt(loaded, question, classification, node_id),
                    task="ask",
                    context=loaded.context(),
                ):
                    pieces.append(delta)
                    yield sse("delta", delta)
                body = "".join(pieces)
                lesson.markdown = body
                lesson.complete = True
                await session.commit()

            offer = await self._offer(session, loaded, resolved, node_id, suggestion_id)
            yield sse(
                "done",
                AskDone(
                    lesson_id=lesson.id,
                    complete=True,
                    characters=len(body),
                    offer=offer,
                ).model_dump(),
            )

    # --- classification ------------------------------------------------------

    async def _classify(self, loaded: LoadedSubject, question: str) -> QueryClassification:
        """Place a question relative to the live graph.

        :param loaded: The subject being asked about.
        :param question: The learner's question.
        """
        return await self._adapter.generate_structured(
            schema=QueryClassification,
            system=CLASSIFY_SYSTEM,
            prompt=(
                f"SUBJECT: {loaded.subject.name}\nQUESTION: {question}\n\nClassify this question."
            ),
            task="classification",
            context=loaded.context(),
        )

    @staticmethod
    def _resolve(
        loaded: LoadedSubject, classification: QueryClassification
    ) -> tuple[str, str | None]:
        """Reconcile the classifier's verdict with what is actually in the graph.

        A model can name a concept id that no longer exists -- the graph may have
        moved since the context was cached. Trusting it would attach an answer to a
        dangling id, so an unresolvable match degrades to the next most conservative
        reading rather than failing the request.

        :param loaded: The subject being asked about.
        :param classification: What the model decided.
        """
        if classification.kind == "existing_node":
            matched = classification.matched_node_id
            if matched is not None and matched in loaded.graph:
                return "existing_node", matched
            return ("new_node" if classification.concept_name else "off_subject"), None
        if classification.kind == "new_node" and classification.concept_name:
            return "new_node", None
        # Either genuinely off-subject, or a new_node the model failed to name --
        # which is not enough to propose a concept, so it is answered and dropped.
        return "off_subject", None

    async def _suggest(
        self,
        session: AsyncSession,
        loaded: LoadedSubject,
        question: str,
        classification: QueryClassification,
    ) -> str | None:
        """Record that a question found a gap in the graph.

        :param session: The stream's database session.
        :param loaded: The subject being asked about.
        :param question: The learner's question.
        :param classification: What the model decided.
        """
        graph = GraphRepository(session)
        prereq_ids: list[str] = []
        for written in classification.prereq_names or []:
            found = await graph.find_by_key(loaded.subject.id, name_key(written))
            if found is not None and found.id in loaded.graph:
                prereq_ids.append(found.id)

        suggestion = await SuggestionService(session, self._params).record_off_graph(
            loaded,
            question=question,
            concept_name=classification.concept_name or classification.title,
            definition=classification.definition or f"Introduced by the question: {question}",
            tier=classification.tier or 2,
            prereq_ids=prereq_ids,
        )
        return suggestion.id if suggestion is not None else None

    # --- content -------------------------------------------------------------

    async def _lesson_row(
        self,
        session: AsyncSession,
        loaded: LoadedSubject,
        question: str,
        classification: QueryClassification,
        node_id: str | None,
    ) -> tuple[Lesson, bool]:
        """Find or create the row this answer is written to.

        :param session: The stream's database session.
        :param loaded: The subject being asked about.
        :param question: The learner's question.
        :param classification: What the model decided.
        :param node_id: The concept it resolved to, if any.
        """
        repo = PlanRepository(session)
        key = ask_cache_key(loaded.subject.id, node_id, question)
        existing = await repo.lesson_by_cache_key(key)
        if existing is not None and existing.complete:
            return existing, True
        if existing is not None:
            # A previous attempt died mid-stream. Reuse the row and overwrite it
            # rather than leaving an empty lesson behind and minting a second one.
            return existing, False

        state = loaded.states.get(node_id) if node_id else None
        lesson = repo.add_lesson(
            Lesson(
                id=new_id(),
                subject_id=loaded.subject.id,
                node_id=node_id,
                unit_id=None,
                title=classification.title[:300],
                difficulty=loaded.graph.tier(node_id) if node_id else 3,
                level="developing" if state is None else level_for(state.mastery),
                markdown="",
                complete=False,
                cache_key=key,
                provenance={
                    "source": "ask",
                    "question": question[:1000],
                    "kind": classification.kind,
                    "reason": classification.reason[:500],
                },
            )
        )
        await session.flush()
        return lesson, False

    def _answer_prompt(
        self,
        loaded: LoadedSubject,
        question: str,
        classification: QueryClassification,
        node_id: str | None,
    ) -> str:
        """Build the instruction that answers one question.

        :param loaded: The subject being asked about.
        :param question: The learner's question.
        :param classification: What the model decided.
        :param node_id: The concept it resolved to, if any.
        """
        lines = [f"SUBJECT: {loaded.subject.name}", f"QUESTION: {question}"]
        if node_id is not None:
            meta = loaded.graph.nodes[node_id]
            state = loaded.states[node_id]
            prereqs = sorted(loaded.graph.nodes[p].name for p in loaded.graph.prereqs(node_id))
            lines += [
                f"CONCEPT: {meta.name}",
                f"DEFINITION: {loaded.nodes[node_id].definition}",
                f"CURRENT MASTERY: {state.mastery:.2f}",
                f"PREREQUISITES: {', '.join(prereqs) if prereqs else '(none)'}",
            ]
        elif classification.kind == "off_subject":
            lines.append(
                "NOTE: this question is outside the subject. Answer it on its own terms "
                "and do not force a connection to the concept graph."
            )
        else:
            lines.append(
                f"NOTE: this concept is not yet in the graph. Treat it as "
                f"{classification.concept_name or classification.title!r} and connect it to "
                "the concepts the learner already has."
            )
        lines += ["", "Answer the question."]
        return "\n".join(lines)

    # --- what to do next -----------------------------------------------------

    async def _offer(
        self,
        session: AsyncSession,
        loaded: LoadedSubject,
        resolved: str,
        node_id: str | None,
        suggestion_id: str | None,
    ) -> PlanOffer:
        """Decide what the learner can do with the concept they just asked about.

        :param session: The stream's database session.
        :param loaded: The subject being asked about.
        :param resolved: How the question was resolved.
        :param node_id: The concept it resolved to, if any.
        :param suggestion_id: The suggestion recorded for a missing concept.
        """
        if resolved == "new_node":
            if suggestion_id is None:
                return PlanOffer(
                    kind="none",
                    node_id=None,
                    suggestion_id=None,
                    message="This gap is already on your list of suggested graph changes.",
                )
            return PlanOffer(
                kind="review_suggestion",
                node_id=None,
                suggestion_id=suggestion_id,
                message=(
                    "This is part of the subject but missing from your graph. Review the "
                    "suggested change to add it, then it can be planned."
                ),
            )
        if resolved != "existing_node" or node_id is None:
            return PlanOffer(
                kind="none",
                node_id=None,
                suggestion_id=None,
                message="Outside this subject, so nothing in your graph or plan changes.",
            )

        name = loaded.graph.nodes[node_id].name
        state = loaded.states[node_id]
        if state.mastery >= self._params.mastery_threshold:
            return PlanOffer(
                kind="none",
                node_id=node_id,
                suggestion_id=None,
                message=f"You are already estimated at {state.mastery:.0%} on {name}.",
            )

        plan = await PlanRepository(session).active_plan(loaded.subject.id)
        if plan is None:
            return PlanOffer(
                kind="none",
                node_id=node_id,
                suggestion_id=None,
                message=f"{name} is in your graph. Generate a plan and it will be scheduled.",
            )
        units = await PlanRepository(session).units_for_plan(plan.id)
        pending = next(
            (
                unit
                for unit in units
                if unit.node_id == node_id
                and unit.status in {UnitStatus.PENDING, UnitStatus.IN_PROGRESS}
            ),
            None,
        )
        if pending is not None:
            return PlanOffer(
                kind="already_planned",
                node_id=node_id,
                suggestion_id=None,
                message=f"{name} is already unit {pending.seq + 1} of your plan.",
            )
        return PlanOffer(
            kind="insert_unit",
            node_id=node_id,
            suggestion_id=None,
            message=f"Add a unit on {name} to your plan, as early as its prerequisites allow.",
        )
