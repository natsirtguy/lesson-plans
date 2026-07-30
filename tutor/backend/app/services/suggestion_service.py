"""Noticing that the graph is wrong before the learner has to say so.

The best evidence that a concept is missing or misplaced turns up while studying,
not while editing the graph. Three signals are worth acting on:

* **A bimodal node.** Answers about one concept that are confidently right and
  confidently wrong, in a pattern noise does not explain, usually mean the node is
  two concepts wearing one name.
* **An unreachable node.** A concept whose prerequisites are themselves all
  unreachable cannot be taught or usefully tested. Almost always the graph has
  given it prerequisites it does not really have.
* **An orphan.** A concept above tier 1 with nothing leading to it, which the plan
  sequencer cannot place after anything.

A fourth signal comes from elsewhere: an ask-anything query that lands off the
graph but inside the subject. :meth:`SuggestionService.record_off_graph` is what the
ask flow calls to log it.

Suggestions are surfaced in the report view rather than interrupting a session, and
are deduplicated against every suggestion ever raised for the subject -- including
dismissed ones, so a rejected proposal does not come back the next time the same
observation is made.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import new_id
from app.mastery.coverage import locked_nodes
from app.mastery.state import MasteryParams
from app.models.changeset import GraphSuggestion
from app.models.enums import SuggestionKind, SuggestionStatus
from app.repositories.assessment import AssessmentRepository
from app.repositories.changesets import ChangesetRepository
from app.schemas.changeset import (
    AddNode,
    NewNodeSpec,
    Operation,
    RemoveEdge,
    SplitNode,
)
from app.services.graph_loader import GraphLoader, LoadedSubject

#: Responses needed against one concept before a split is worth suggesting.
MIN_RESPONSES_FOR_BIMODAL = 4
#: A response at or above this counts as a confident success.
HIGH_SCORE = 0.8
#: A response at or below this counts as a confident failure.
LOW_SCORE = 0.25


@dataclass(slots=True)
class Detected:
    """A suggestion the detector wants to raise.

    :param kind: Which signal fired.
    :param summary: What to tell the learner.
    :param evidence: What was observed.
    :param operations: Draft operations that would address it.
    :param node_id: The concept in question, when it is about one concept.
    :param dedupe_key: Stable key so the same observation is raised once.
    """

    kind: SuggestionKind
    summary: str
    evidence: dict[str, object]
    operations: list[Operation]
    node_id: str | None
    dedupe_key: str


class SuggestionService:
    """Detects and records proactive graph suggestions."""

    def __init__(self, session: AsyncSession, params: MasteryParams) -> None:
        """
        :param session: The active database session.
        :param params: Mastery model constants.
        """
        self._session = session
        self._params = params
        self._repo = ChangesetRepository(session)
        self._assessment = AssessmentRepository(session)
        self._loader = GraphLoader(session, params)

    async def refresh(self, subject_id: str) -> list[GraphSuggestion]:
        """Look for problems and record any that are new.

        :param subject_id: The subject to inspect.
        """
        loaded = await self._loader.load(subject_id, apply_decay=False)
        seen = await self._repo.suggestion_keys(subject_id)

        detected = [
            *await self._bimodal(loaded),
            *self._unreachable(loaded),
            *self._orphans(loaded),
        ]
        created: list[GraphSuggestion] = []
        for item in detected:
            if item.dedupe_key in seen:
                continue
            seen.add(item.dedupe_key)
            created.append(self._persist(subject_id, item))
        if created:
            await self._session.commit()
        return created

    async def open_for(self, subject_id: str) -> list[GraphSuggestion]:
        """Refresh the detectors, then return every unresolved suggestion.

        :param subject_id: The subject to inspect.
        """
        await self.refresh(subject_id)
        return await self._repo.open_suggestions(subject_id)

    async def dismiss(self, suggestion_id: str) -> GraphSuggestion:
        """Mark a suggestion as not worth acting on.

        :param suggestion_id: The suggestion to dismiss.
        :raises LookupError: If it does not exist.
        """
        suggestion = await self._repo.get_suggestion(suggestion_id)
        if suggestion is None:
            raise LookupError(suggestion_id)
        suggestion.status = SuggestionStatus.DISMISSED
        await self._session.commit()
        return suggestion

    async def record_off_graph(
        self,
        loaded: LoadedSubject,
        *,
        question: str,
        concept_name: str,
        definition: str,
        tier: int,
        prereq_ids: list[str],
    ) -> GraphSuggestion | None:
        """Log that a question landed inside the subject but outside the graph.

        Called by the ask-anything flow. The suggestion proposes adding the concept
        properly, so a gap the learner found by asking becomes a gap the graph
        knows about.

        :param loaded: The subject the question was asked against.
        :param question: The learner's question.
        :param concept_name: The concept the classifier named.
        :param definition: Its one-sentence definition.
        :param tier: Its tier.
        :param prereq_ids: Existing concepts it depends on.
        """
        key = f"off_graph:{concept_name.lower()}"
        if key in await self._repo.suggestion_keys(loaded.subject.id):
            return None
        suggestion = self._persist(
            loaded.subject.id,
            Detected(
                kind=SuggestionKind.OFF_GRAPH_IN_SUBJECT,
                summary=(
                    f"You asked about {concept_name!r}, which is part of this subject "
                    "but missing from your graph."
                ),
                evidence={"question": question[:500]},
                operations=[
                    AddNode(
                        node=NewNodeSpec(
                            name=concept_name,
                            definition=definition,
                            tier=tier,
                            prereq_ids=prereq_ids,
                        )
                    )
                ],
                node_id=None,
                dedupe_key=key,
            ),
        )
        await self._session.commit()
        return suggestion

    def _persist(self, subject_id: str, detected: Detected) -> GraphSuggestion:
        """Write one detected suggestion.

        :param subject_id: The subject it belongs to.
        :param detected: What was detected.
        """
        return self._repo.add_suggestion(
            GraphSuggestion(
                id=new_id(),
                subject_id=subject_id,
                kind=detected.kind,
                summary=detected.summary,
                evidence=detected.evidence,
                proposed_ops=[op.model_dump(mode="json") for op in detected.operations],
                node_id=detected.node_id,
                dedupe_key=detected.dedupe_key,
            )
        )

    async def _bimodal(self, loaded: LoadedSubject) -> list[Detected]:
        """Find concepts whose answers split cleanly into right and wrong.

        Requires both a confident success and a confident failure, and a spread wide
        enough that a single unlucky answer does not trigger it.

        :param loaded: The subject to inspect.
        """
        found: list[Detected] = []
        for node_id, meta in loaded.graph.nodes.items():
            responses = await self._assessment.responses_for_node(node_id)
            scores = [response.score for response in responses]
            if len(scores) < MIN_RESPONSES_FOR_BIMODAL:
                continue
            highs = [s for s in scores if s >= HIGH_SCORE]
            lows = [s for s in scores if s <= LOW_SCORE]
            if not highs or not lows:
                continue
            if statistics.pstdev(scores) < 0.35:
                continue
            found.append(
                Detected(
                    kind=SuggestionKind.BIMODAL_NODE,
                    summary=(
                        f"Your answers on {meta.name!r} are split -- "
                        f"{len(highs)} confidently right and {len(lows)} confidently "
                        "wrong. That usually means it is really two concepts."
                    ),
                    evidence={
                        "scores": scores,
                        "high_count": len(highs),
                        "low_count": len(lows),
                    },
                    operations=[
                        SplitNode(
                            node_id=node_id,
                            into=[
                                NewNodeSpec(
                                    name=f"{meta.name} (part 1)",
                                    definition=(
                                        f"The part of {meta.name} you answer correctly. "
                                        "Rename this once you can see which part it is."
                                    ),
                                    tier=meta.tier,
                                ),
                                NewNodeSpec(
                                    name=f"{meta.name} (part 2)",
                                    definition=(f"The part of {meta.name} you answer incorrectly."),
                                    tier=meta.tier,
                                ),
                            ],
                        )
                    ],
                    node_id=node_id,
                    dedupe_key=f"bimodal:{node_id}:{len(scores)}",
                )
            )
        return found

    def _unreachable(self, loaded: LoadedSubject) -> list[Detected]:
        """Find concepts nothing can currently lead to.

        A node is unreachable when every prerequisite is itself locked -- not merely
        unmastered, which is the normal state early on, but blocked in turn. That
        pattern points at a prerequisite the concept does not really need.

        :param loaded: The subject to inspect.
        """
        graph = loaded.graph
        locked = set(locked_nodes(graph, loaded.states, self._params))
        found: list[Detected] = []
        for node_id in locked:
            prereqs = graph.prereqs(node_id)
            if not prereqs or not prereqs <= locked:
                continue
            meta = graph.nodes[node_id]
            deepest = max(prereqs, key=lambda p: graph.tier(p))
            found.append(
                Detected(
                    kind=SuggestionKind.UNREACHABLE_NODE,
                    summary=(
                        f"Nothing currently leads to {meta.name!r}: every one of its "
                        "prerequisites is itself blocked. One of them may not really "
                        "be required."
                    ),
                    evidence={"prerequisites": sorted(graph.nodes[p].name for p in prereqs)},
                    operations=[RemoveEdge(prereq_id=deepest, node_id=node_id)],
                    node_id=node_id,
                    dedupe_key=f"unreachable:{node_id}",
                )
            )
        return found

    def _orphans(self, loaded: LoadedSubject) -> list[Detected]:
        """Find advanced concepts with no prerequisites at all.

        :param loaded: The subject to inspect.
        """
        graph = loaded.graph
        return [
            Detected(
                kind=SuggestionKind.ORPHAN_NODE,
                summary=(
                    f"{graph.nodes[node_id].name!r} sits at tier "
                    f"{graph.tier(node_id)} with no prerequisites, so the plan has "
                    "nothing to teach before it."
                ),
                evidence={"tier": graph.tier(node_id)},
                operations=[],
                node_id=node_id,
                dedupe_key=f"orphan:{node_id}",
            )
            for node_id in graph.orphaned_nodes()
        ]
