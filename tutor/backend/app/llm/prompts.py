"""Prompt construction.

All prompt text lives here so the wording is reviewable in one place and the
cacheable prefix has exactly one definition. ``NODE_LINE`` is that definition:
the graph context is rendered as one line per concept in a fixed format, which
the fake adapter parses to answer deterministically without a network call.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.llm.base import CacheableContext

#: Rendered form of one concept in the cacheable graph context.
NODE_LINE = "[{node_id}] T{tier} {name} :: {definition}"

#: Parses :data:`NODE_LINE` back into its parts.
NODE_LINE_RE = re.compile(
    r"^\[(?P<id>[^\]]+)\] T(?P<tier>\d) (?P<name>[^:]+?) :: (?P<definition>.*)$"
)


@dataclass(frozen=True, slots=True)
class NodeContext:
    """One concept as the model sees it in the cacheable prefix.

    :param node_id: Persistent node identifier.
    :param name: Concept name.
    :param definition: One-sentence definition.
    :param tier: Difficulty tier, 1 through 5.
    :param mastery: Current mastery estimate in [0, 1].
    :param confidence: Current confidence in [0, 1].
    :param prereq_names: Names of this concept's prerequisites.
    """

    node_id: str
    name: str
    definition: str
    tier: int
    mastery: float
    confidence: float
    prereq_names: tuple[str, ...]


def graph_context(
    *, subject_name: str, graph_version: int, nodes: Sequence[NodeContext]
) -> CacheableContext:
    """Render the concept graph and mastery summary as a cacheable prefix.

    This is the shared prefix of nearly every call for a subject, so it is keyed
    on the graph version: a committed changeset produces a new key and a new cache
    entry, and everything in between reuses one.

    :param subject_name: Name of the subject.
    :param graph_version: Current graph version, which becomes part of the key.
    :param nodes: Live concepts, ordered by tier then name for byte stability.
    """
    lines = [
        f"SUBJECT: {subject_name}",
        f"GRAPH VERSION: {graph_version}",
        "",
        "CONCEPT GRAPH (one line per concept, [id] Ttier Name :: definition):",
    ]
    lines.extend(
        NODE_LINE.format(node_id=n.node_id, tier=n.tier, name=n.name, definition=n.definition)
        for n in nodes
    )
    lines.append("")
    lines.append("PREREQUISITES (concept <- its prerequisites):")
    lines.extend(
        f"{n.name} <- {', '.join(n.prereq_names) if n.prereq_names else '(none)'}" for n in nodes
    )
    lines.append("")
    lines.append("LEARNER MASTERY (mastery 0-1, confidence 0-1):")
    lines.extend(f"{n.name}: mastery={n.mastery:.2f} confidence={n.confidence:.2f}" for n in nodes)
    return CacheableContext(
        key=f"subject:{subject_name}:v{graph_version}:n{len(nodes)}",
        text="\n".join(lines),
    )


GRAPH_GENERATION_SYSTEM = """\
You decompose a subject into a prerequisite graph for an adult self-learner.

Produce between 40 and 120 concepts. Requirements:

- Cover the subject's real conceptual territory, not a syllabus of chapter titles. \
A concept is something you can be examined on and either understand or not.
- Every prerequisite name must exactly match another concept's name in your output.
- The prerequisite relation must be a DAG: no cycles, direct or indirect.
- A prerequisite must never have a higher tier than the concept that depends on it.
- Tier 1 concepts have no prerequisites and assume only general education. Tier 5 \
concepts are what a specialist works with.
- Definitions are one sentence, specific enough to distinguish the concept from its \
neighbours. "An important idea in the field" is useless; say what it asserts.
- Prefer several sharp concepts over one broad one, but do not split a single idea \
into artificial pieces just to raise the count.\
"""

REFINE_SYSTEM = """\
You translate a learner's plain-language complaint about their concept graph into a \
precise changeset.

Rules:

- Propose the smallest set of operations that addresses what they said. Do not \
tidy up unrelated parts of the graph.
- Reference existing concepts by the id shown in brackets in the graph context, \
never by name, for every field that takes an id.
- Never propose an operation that would create a cycle or point a prerequisite \
edge from a higher tier to a lower one.
- Every operation carries its own rationale, written for the learner, saying what \
it does and why it follows from their request.
- If the request is ambiguous, choose the reading that changes least, and say so in \
that operation's rationale.
- If the request needs no graph change, return an empty operations list and explain \
why in the rationale.\
"""

ITEM_GENERATION_SYSTEM = """\
You write one assessment item that discriminates between a learner who understands a \
concept and one who has only heard of it.

Rules:

- Test the concept named in the instruction, not its prerequisites and not the \
concepts that build on it.
- A multiple_choice item has exactly four options, with distractors that each \
encode a specific plausible misconception. Never use "all of the above" or \
throwaway options.
- A short_free_text item asks for something answerable in one to three sentences.
- An explain_why_wrong item presents a confident, specific, incorrect statement and \
asks the learner to identify what is wrong with it.
- The rubric must be usable by a grader who cannot see this instruction: state what \
earns full credit, what earns partial credit, and what earns none.
- Match the stated difficulty. A difficulty-1 item checks recognition; a \
difficulty-5 item requires applying the concept to an unfamiliar case.\
"""

GRADING_SYSTEM = """\
You grade one answer against its rubric.

Rules:

- Apply the rubric as written. Do not invent additional criteria and do not award \
credit the rubric does not describe.
- Score on understanding of the concept, not on spelling, phrasing, or length.
- A correct answer reached by faulty reasoning earns partial credit at most; say so.
- Feedback speaks to the learner in two or three sentences, names the specific gap \
or confirms the specific thing they got right, and never merely restates the score.
- If the answer reveals a specific false belief, state that belief plainly in the \
misconception field. Leave it null if the answer is simply incomplete.\
"""

CLASSIFY_SYSTEM = """\
You place a learner's question relative to their existing concept graph.

Choose exactly one:

- existing_node: the question is about a concept already in the graph. Return its id.
- new_node: the question is within the subject but no existing concept covers it. \
Return a name, a one-sentence definition, a tier, and the names of existing \
concepts it depends on.
- off_subject: the question is outside the subject. Do not invent a concept for it; \
it will be answered without touching the graph.

Bias toward existing_node when an existing concept genuinely covers the question -- \
creating a near-duplicate concept fragments the learner's mastery history. Bias \
toward off_subject only when the question really is about something else; a hard or \
unusual question within the subject is a new_node, not off-subject.\
"""

LESSON_SYSTEM = """\
You teach one concept to one adult learner in about fifteen minutes of reading.

Write markdown with these sections, in this order, using these exact headings:

## Objective
One sentence, starting with a verb, naming what they will be able to do.

## Explanation
The actual teaching. Build from what they already know, per the mastery summary. \
Name the real terminology and then explain it -- never substitute a vague paraphrase \
for the correct term. State mechanisms, not just outcomes. Use LaTeX between $ for \
inline mathematics and $$ for display mathematics. Use fenced code blocks with a \
language tag for code.

## Worked examples
Two examples, fully worked, each showing the reasoning step by step rather than \
just the result. The second should be harder than the first.

## Practice
Three problems, hardest last, with no answers given.

## Exit check
One question that cannot be answered without having understood the explanation.

Constraints:

- Address the learner directly as "you". No preamble, no meta-commentary about the \
lesson itself, no closing summary of what was covered.
- Assume the prerequisites listed as mastered are mastered. Do not re-teach them; \
reference them by name.
- Where a listed prerequisite has low mastery, give it one sentence of refresher \
inline rather than skipping it or teaching it in full.
- Prefer being concrete over being comprehensive. One well-developed mechanism \
teaches more than five mentioned ones.\
"""

ASK_SYSTEM = """\
You answer one question from a learner, at the level their mastery summary implies.

Write markdown. Lead with the answer itself -- the first sentence should be the \
thing they asked for, not a restatement of the question. Then develop it: the \
mechanism, why it works that way, and where it connects to concepts they already \
know, referencing those by name.

Name real terminology and explain it. Use LaTeX between $ for inline mathematics \
and fenced code blocks with a language tag for code. No preamble, no closing \
summary. If the question rests on a false premise, say so first, then answer the \
question they meant to ask.\
"""
