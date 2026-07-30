"""A deterministic, offline :class:`~app.llm.base.LLMAdapter` for tests and demos.

Every response is a pure function of the prompt, so the whole test suite runs with
zero network calls and no flakiness. It is not a mock that returns canned blobs:
the graphs it produces are real DAGs with tier-monotonic edges, so the graph
validator, the changeset machinery, and the diagnostic loop are all exercised
against structurally valid input.

Tests that need specific behaviour inject a hook rather than patching internals:
``grade_hook`` decides scores (this is how the synthetic-learner tests drive a
known ground-truth mastery vector), ``classify_hook`` decides ask-anything
routing, and ``changeset_hook`` supplies proposed operations.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field

from pydantic import BaseModel

from app.llm.base import CacheableContext, SchemaT, StructuredOutputError
from app.llm.prompts import NODE_LINE_RE
from app.llm.schemas import (
    GeneratedGraph,
    GeneratedItem,
    GeneratedNode,
    GradeResult,
    ProposedChangeset,
    QueryClassification,
    UnitBrief,
)

#: Number of concepts the fake generates when nothing else is specified. Small
#: enough to keep tests fast, large enough to span all five tiers.
DEFAULT_GRAPH_SIZE = 24


@dataclass(frozen=True, slots=True)
class FakeCall:
    """One recorded call, for assertions about how services drive the adapter.

    :param task: The task identifier the caller passed.
    :param schema: Name of the requested schema, or ``"stream"`` for prose.
    :param prompt: The user-turn prompt.
    :param context_key: Key of the cacheable context, if one was supplied.
    """

    task: str
    schema: str
    prompt: str
    context_key: str | None


@dataclass(slots=True)
class ParsedNode:
    """A concept recovered from the cacheable graph context.

    :param node_id: Node identifier.
    :param name: Concept name.
    :param definition: One-sentence definition.
    :param tier: Difficulty tier.
    """

    node_id: str
    name: str
    definition: str
    tier: int


@dataclass
class FakeLLMAdapter:
    """Deterministic adapter. Satisfies the :class:`LLMAdapter` protocol."""

    graph_size: int = DEFAULT_GRAPH_SIZE
    calls: list[FakeCall] = field(default_factory=list)
    #: Maps a prompt to a rubric score in [0, 1].
    grade_hook: Callable[[str], float] | None = None
    #: Maps (prompt, parsed nodes) to a classification.
    classify_hook: Callable[[str, list[ParsedNode]], QueryClassification] | None = None
    #: Maps (prompt, parsed nodes) to a proposed changeset.
    changeset_hook: Callable[[str, list[ParsedNode]], ProposedChangeset] | None = None
    #: Overrides the streamed lesson body.
    stream_hook: Callable[[str], str] | None = None

    async def generate_structured(
        self,
        *,
        schema: type[SchemaT],
        system: str,
        prompt: str,
        task: str,
        context: CacheableContext | None = None,
        max_tokens: int | None = None,
        reasoning: bool = False,
    ) -> SchemaT:
        """Return a deterministic instance of ``schema``.

        :param schema: Pydantic model describing the expected output.
        :param system: Ignored; recorded only.
        :param prompt: Drives the generated content.
        :param task: Recorded for assertions.
        :param context: Cacheable prefix; parsed for existing concepts.
        :param max_tokens: Ignored.
        :param reasoning: Ignored.
        :raises StructuredOutputError: If the schema is not one the fake handles.
        """
        self.calls.append(
            FakeCall(
                task=task,
                schema=schema.__name__,
                prompt=prompt,
                context_key=context.key if context else None,
            )
        )
        nodes = parse_nodes(context.text if context else "")
        result: BaseModel
        if schema is GeneratedGraph:
            result = self._graph(prompt)
        elif schema is ProposedChangeset:
            result = self._changeset(prompt, nodes)
        elif schema is GeneratedItem:
            result = self._item(prompt)
        elif schema is GradeResult:
            result = self._grade(prompt)
        elif schema is QueryClassification:
            result = self._classify(prompt, nodes)
        elif schema is UnitBrief:
            result = self._unit(prompt)
        else:  # pragma: no cover - a new schema needs a handler here
            raise StructuredOutputError(f"FakeLLMAdapter has no handler for {schema.__name__}")
        # Round-trip through validation so the fake cannot emit something the real
        # adapter's schema would reject.
        return schema.model_validate(result.model_dump())

    def stream_text(
        self,
        *,
        system: str,
        prompt: str,
        task: str,
        context: CacheableContext | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """Stream a deterministic markdown lesson.

        :param system: Ignored; recorded only.
        :param prompt: Drives the generated content.
        :param task: Recorded for assertions.
        :param context: Cacheable prefix; recorded only.
        :param max_tokens: Ignored.
        """
        self.calls.append(
            FakeCall(
                task=task,
                schema="stream",
                prompt=prompt,
                context_key=context.key if context else None,
            )
        )
        body = self.stream_hook(prompt) if self.stream_hook else _lesson_body(prompt)
        return _chunk(body)

    # --- generators ----------------------------------------------------------

    def _graph(self, prompt: str) -> GeneratedGraph:
        """Build a valid DAG with tier-monotonic prerequisite edges.

        :param prompt: Used to recover the subject name.
        """
        subject = _field(prompt, "SUBJECT") or "Subject"
        size = max(2, self.graph_size)
        tiers = [1 + (index * 5) // size for index in range(size)]
        names = [f"{subject} Concept {index + 1:02d}" for index in range(size)]
        nodes: list[GeneratedNode] = []
        for index, (name, tier) in enumerate(zip(names, tiers, strict=True)):
            # Prerequisites come only from the immediately lower tier, which makes
            # the result acyclic and tier-monotonic by construction.
            lower = [names[j] for j in range(index) if tiers[j] == tier - 1]
            nodes.append(
                GeneratedNode(
                    name=name,
                    definition=f"Tier {tier} concept number {index + 1} within {subject}.",
                    tier=tier,
                    prerequisites=lower[-2:],
                )
            )
        return GeneratedGraph(
            subject_summary=f"A deterministic stand-in decomposition of {subject}.",
            nodes=nodes,
        )

    def _changeset(self, prompt: str, nodes: list[ParsedNode]) -> ProposedChangeset:
        """Propose a changeset, defaulting to a no-op when no hook is set.

        :param prompt: The learner's refinement request.
        :param nodes: Concepts recovered from the graph context.
        """
        if self.changeset_hook:
            return self.changeset_hook(prompt, nodes)
        return ProposedChangeset(
            rationale="No structural change is needed for this request.",
            operations=[],
        )

    def _item(self, prompt: str) -> GeneratedItem:
        """Build an item whose correct answer is derivable from the concept name.

        :param prompt: Carries the target concept and difficulty.
        """
        concept = _field(prompt, "CONCEPT") or "the concept"
        difficulty = _field(prompt, "DIFFICULTY") or "3"
        fmt = _field(prompt, "FORMAT") or "multiple_choice"
        if fmt == "multiple_choice":
            return GeneratedItem(
                item_format="multiple_choice",
                stem=f"Which statement about {concept} is correct?",
                choices=[
                    f"{concept} is correctly described this way.",
                    f"{concept} is confused with its prerequisite.",
                    f"{concept} is confused with a later concept.",
                    f"{concept} is described with a reversed mechanism.",
                ],
                correct_choice=0,
                answer_key=f"{concept} is correctly described this way.",
                rubric=(
                    f"Full credit for selecting the option that describes {concept} "
                    "accurately. No credit otherwise."
                ),
            )
        if fmt == "explain_why_wrong":
            return GeneratedItem(
                item_format="explain_why_wrong",
                stem=(
                    f'A learner claims: "{concept} works in reverse of how it '
                    'actually does." Explain what is wrong with this.'
                ),
                choices=[],
                correct_choice=None,
                answer_key=f"The claim inverts the mechanism of {concept}.",
                rubric=(
                    "Full credit for identifying the inverted mechanism. Partial "
                    "credit for noticing the claim is wrong without saying why."
                ),
            )
        return GeneratedItem(
            item_format="short_free_text",
            stem=f"In two sentences, explain {concept} at difficulty {difficulty}.",
            choices=[],
            correct_choice=None,
            answer_key=f"A correct two-sentence account of {concept}.",
            rubric=(
                f"Full credit for a correct account of {concept} that names its "
                "mechanism. Partial credit for a correct but mechanism-free answer."
            ),
        )

    def _grade(self, prompt: str) -> GradeResult:
        """Grade an answer, via the hook if one is set.

        Without a hook, the answer text itself carries the verdict, which keeps
        service-level tests readable: they submit "correct" or "wrong" and assert
        on the mastery movement.

        :param prompt: Carries the answer and the rubric.
        """
        score = self.grade_hook(prompt) if self.grade_hook else _heuristic_score(prompt)
        score = min(1.0, max(0.0, score))
        return GradeResult(
            score=score,
            correct=score >= 0.6,
            feedback=(
                "That matches the rubric's account of the mechanism."
                if score >= 0.6
                else "That misses the mechanism the rubric asks for."
            ),
            misconception=None if score >= 0.6 else "Mechanism stated in reverse.",
        )

    def _classify(self, prompt: str, nodes: list[ParsedNode]) -> QueryClassification:
        """Classify a free-form query against the graph.

        :param prompt: Carries the learner's question.
        :param nodes: Concepts recovered from the graph context.
        """
        if self.classify_hook:
            return self.classify_hook(prompt, nodes)
        question = _field(prompt, "QUESTION") or prompt
        lowered = question.lower()
        for node in nodes:
            if node.name.lower() in lowered:
                return QueryClassification(
                    kind="existing_node",
                    matched_node_id=node.node_id,
                    title=node.name,
                    concept_name=node.name,
                    definition=node.definition,
                    tier=node.tier,
                    prereq_names=[],
                    reason="An existing concept covers this question.",
                )
        return QueryClassification(
            kind="new_node",
            matched_node_id=None,
            title=question[:120] or "Untitled question",
            concept_name=question[:80] or "New Concept",
            definition=f"A concept introduced by the question: {question[:160]}",
            tier=nodes[0].tier if nodes else 2,
            prereq_names=[],
            reason="No existing concept covers this question.",
        )

    def _unit(self, prompt: str) -> UnitBrief:
        """Build a unit brief for the concept named in the prompt.

        :param prompt: Carries the target concept.
        """
        concept = _field(prompt, "CONCEPT") or "the concept"
        return UnitBrief(
            title=concept,
            objective=f"Explain {concept} and apply it to an unfamiliar case.",
            estimated_minutes=20,
        )


def parse_nodes(context_text: str) -> list[ParsedNode]:
    """Recover concepts from a rendered graph context.

    :param context_text: The cacheable prefix text.
    """
    nodes: list[ParsedNode] = []
    for line in context_text.splitlines():
        match = NODE_LINE_RE.match(line.strip())
        if match:
            nodes.append(
                ParsedNode(
                    node_id=match.group("id"),
                    name=match.group("name").strip(),
                    definition=match.group("definition").strip(),
                    tier=int(match.group("tier")),
                )
            )
    return nodes


def _field(prompt: str, label: str) -> str | None:
    """Read a ``LABEL: value`` line out of a prompt.

    :param prompt: The prompt text.
    :param label: The uppercase label to look for.
    """
    match = re.search(rf"^{re.escape(label)}:[ \t]*(.+)$", prompt, re.MULTILINE)
    return match.group(1).strip() if match else None


def _heuristic_score(prompt: str) -> float:
    """Derive a score from marker words in the submitted answer.

    :param prompt: The grading prompt, which embeds the learner's answer.
    """
    answer = (_field(prompt, "ANSWER") or "").lower()
    if "correct" in answer or "right" in answer:
        return 1.0
    if "partial" in answer or "partly" in answer:
        return 0.6
    if not answer.strip():
        return 0.0
    return 0.15


def _lesson_body(prompt: str) -> str:
    """Build a deterministic lesson in the shape the real prompt asks for.

    :param prompt: Carries the target concept.
    """
    concept = _field(prompt, "CONCEPT") or _field(prompt, "QUESTION") or "this concept"
    return f"""## Objective

Explain {concept} and apply it to a case you have not seen before.

## Explanation

{concept} is best understood through its mechanism rather than its definition. The
governing relation is $y = f(x)$, where the interesting behaviour comes from how
$f$ responds near its boundaries.

```python
def mechanism(x: float) -> float:
    return x * 2
```

## Worked examples

1. Taking $x = 1$, the mechanism yields $2$, because the relation doubles its input.
2. Taking $x = -3$, it yields $-6$; the sign carries through because the relation is
   linear and odd.

## Practice

1. Compute the result for $x = 5$.
2. Describe what happens as $x$ grows without bound.
3. Construct an input for which the mechanism is a poor model, and say why.

## Exit check

Why does the mechanism preserve the sign of its input?
"""


async def _chunk(text: str, size: int = 64) -> AsyncIterator[str]:
    """Yield ``text`` in fixed-size pieces, imitating token deltas.

    :param text: The full body to stream.
    :param size: Characters per chunk.
    """
    for start in range(0, len(text), size):
        yield text[start : start + size]
