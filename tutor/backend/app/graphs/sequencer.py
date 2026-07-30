"""Ordering concepts into a plan that never teaches something out of order.

The acceptance criterion this module exists to satisfy is structural, not
aspirational: *no unit may depend on a concept the learner has not been taught or
tested on*. That is guaranteed by construction rather than checked afterwards. The
sequencer only ever emits a concept from the **ready set** -- concepts whose every
prerequisite is either already mastered or already scheduled earlier in this same
plan -- and among those it takes the highest-priority one. It is a greedy
priority-ordered topological walk, so the ordering constraint is an invariant of
the loop and priority is what breaks the freedom that remains.

Two consequences of that shape, both of which look like omissions and are not:

* **Mastered concepts are skipped, not sequenced.** They still count as satisfied
  prerequisites, which is what lets a plan start in the middle of the graph for a
  learner who already knows the foundations. A plan is a list of things to *do*.
* **The walk cannot starve.** Every unmastered concept's prerequisites are either
  mastered -- satisfied immediately -- or unmastered, in which case they are
  themselves targets and sit earlier in topological order. Induction over that
  order says every target eventually becomes ready. The topological rank is
  computed up front regardless: it raises on a cyclic graph rather than spinning,
  and it doubles as the deterministic tie-break.

Nothing here touches the database or the model. The prose a unit carries -- title,
objective, minutes -- is written by the LLM later; the *placement* and the stated
reason for it are decided here, where they can be tested.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.mastery.coverage import NodeScore, priority
from app.mastery.graph import ConceptGraph
from app.mastery.state import MasteryParams, MasteryState

#: Concepts folded into a unit's opening retrieval, at most.
DEFAULT_INTERLEAVE = 2


@dataclass(frozen=True, slots=True)
class SequencedUnit:
    """One concept's position in a plan, and the justification for it.

    :param node_id: The concept the unit teaches.
    :param seq: Zero-based position in the plan.
    :param priority: Weakness times unblocking power, the score it was chosen on.
    :param placement_reason: Why the sequencer put it here, in the learner's words.
    :param scheduled_prereq_ids: Prerequisites taught earlier in this same plan.
    :param known_prereq_ids: Prerequisites the learner had already mastered.
    :param interleaved_node_ids: Earlier concepts to retrieve at the unit's start.
    :param first_acquisition: True when this concept has never been taught before,
        the one case where block practice beats interleaved practice.
    """

    node_id: str
    seq: int
    priority: float
    placement_reason: str
    scheduled_prereq_ids: tuple[str, ...]
    known_prereq_ids: tuple[str, ...]
    interleaved_node_ids: tuple[str, ...]
    first_acquisition: bool


@dataclass(frozen=True, slots=True)
class PlanSequence:
    """A full sequencing pass over a subject.

    :param units: The units, in the order they should be studied.
    :param skipped_mastered: Concepts left out because they are already known.
    :param truncated: Concepts that would have been sequenced but fell past
        ``limit``. Non-empty means the plan is a prefix, not the whole subject.
    """

    units: tuple[SequencedUnit, ...]
    skipped_mastered: tuple[str, ...]
    truncated: tuple[str, ...]


def sequence_plan(
    graph: ConceptGraph,
    states: Mapping[str, MasteryState],
    params: MasteryParams,
    *,
    taught: frozenset[str] = frozenset(),
    interleave: int = DEFAULT_INTERLEAVE,
    limit: int | None = None,
) -> PlanSequence:
    """Order every unmastered concept into a prerequisite-respecting plan.

    :param graph: The prerequisite graph.
    :param states: Current mastery, keyed by node id.
    :param params: Model constants, for the mastery threshold.
    :param taught: Concepts with a completed unit in the learner's history, which
        stops a regenerated plan from claiming a re-taught concept is new.
    :param interleave: Maximum earlier concepts folded into a unit's retrieval.
    :param limit: Maximum units to emit; the rest are reported as truncated.
    :raises GraphCycleError: If the graph is cyclic.
    """
    rank = {node_id: index for index, node_id in enumerate(graph.topological_order())}
    scores = {node_id: _score(graph, states, node_id, params) for node_id in graph.node_ids}

    known = {
        node_id
        for node_id in graph.node_ids
        if _mastery(states, node_id) >= params.mastery_threshold
    }
    remaining = {node_id for node_id in graph.node_ids if node_id not in known}

    order = _walk(graph, remaining, known, rank, scores)
    kept = order if limit is None else order[:limit]
    truncated = () if limit is None else tuple(order[limit:])

    units = tuple(
        _build_unit(
            graph,
            states,
            node_id=node_id,
            seq=seq,
            earlier=kept[:seq],
            known=known,
            score=scores[node_id],
            taught=taught,
            interleave=interleave,
        )
        for seq, node_id in enumerate(kept)
    )
    return PlanSequence(
        units=units,
        skipped_mastered=tuple(sorted(known, key=lambda n: rank[n])),
        truncated=truncated,
    )


def _walk(
    graph: ConceptGraph,
    remaining: set[str],
    known: set[str],
    rank: Mapping[str, int],
    scores: Mapping[str, float],
) -> tuple[str, ...]:
    """Run the greedy priority-ordered topological walk.

    :param graph: The prerequisite graph.
    :param remaining: Concepts still to place; consumed by this call.
    :param known: Concepts that count as already satisfied prerequisites.
    :param rank: Topological position per node id, used to break ties.
    :param scores: Priority per node id.
    """
    pending = set(remaining)
    scheduled: list[str] = []
    placed: set[str] = set()

    while pending:
        ready = [
            node_id
            for node_id in pending
            if all(prereq in known or prereq in placed for prereq in graph.prereqs(node_id))
        ]
        if not ready:  # pragma: no cover - unreachable while the graph is acyclic
            ready = [min(pending, key=lambda n: rank[n])]
        # Highest priority wins; ties go to whatever comes first topologically, so
        # the same graph and the same estimates always produce the same plan.
        chosen = min(ready, key=lambda n: (-scores[n], rank[n]))
        pending.discard(chosen)
        placed.add(chosen)
        scheduled.append(chosen)
    return tuple(scheduled)


def _build_unit(
    graph: ConceptGraph,
    states: Mapping[str, MasteryState],
    *,
    node_id: str,
    seq: int,
    earlier: Sequence[str],
    known: set[str],
    score: float,
    taught: frozenset[str],
    interleave: int,
) -> SequencedUnit:
    """Assemble one unit once its position is fixed.

    :param graph: The prerequisite graph.
    :param states: Current mastery, keyed by node id.
    :param node_id: The concept this unit teaches.
    :param seq: Its position in the plan.
    :param earlier: Concepts scheduled before it, in plan order.
    :param known: Concepts already mastered when the plan was built.
    :param score: The priority it was chosen on.
    :param taught: Concepts with a completed unit in the learner's history.
    :param interleave: Maximum earlier concepts to fold into its retrieval.
    """
    prereqs = graph.prereqs(node_id)
    earlier_index = {other: index for index, other in enumerate(earlier)}
    scheduled_prereqs = tuple(
        sorted((p for p in prereqs if p in earlier_index), key=lambda p: earlier_index[p])
    )
    known_prereqs = tuple(
        sorted((p for p in prereqs if p in known), key=lambda p: graph.nodes[p].name)
    )
    return SequencedUnit(
        node_id=node_id,
        seq=seq,
        priority=score,
        placement_reason=_reason(
            graph,
            states,
            node_id=node_id,
            scheduled_prereqs=scheduled_prereqs,
            known_prereqs=known_prereqs,
        ),
        scheduled_prereq_ids=scheduled_prereqs,
        known_prereq_ids=known_prereqs,
        interleaved_node_ids=_interleave(graph, node_id=node_id, earlier=earlier, limit=interleave),
        first_acquisition=node_id not in taught,
    )


def _interleave(
    graph: ConceptGraph, *, node_id: str, earlier: Sequence[str], limit: int
) -> tuple[str, ...]:
    """Choose earlier concepts to retrieve before this unit's new material.

    Two different jobs, in this order. The most recently taught direct
    prerequisite comes first, because retrieving what a concept is built on is the
    cheapest way to make the new material land. Whatever remains is filled from the
    *oldest* earlier unit, because that is where the retrieval interval is longest
    and a successful recall is worth the most.

    :param graph: The prerequisite graph.
    :param node_id: The concept this unit teaches.
    :param earlier: Concepts scheduled before it, in plan order.
    :param limit: Maximum concepts to return.
    """
    if limit <= 0 or not earlier:
        return ()
    prereqs = graph.prereqs(node_id)
    picks: list[str] = []
    recent_prereq = next((other for other in reversed(earlier) if other in prereqs), None)
    if recent_prereq is not None:
        picks.append(recent_prereq)
    for other in earlier:
        if len(picks) >= limit:
            break
        if other not in picks:
            picks.append(other)
    return tuple(picks[:limit])


def _reason(
    graph: ConceptGraph,
    states: Mapping[str, MasteryState],
    *,
    node_id: str,
    scheduled_prereqs: Sequence[str],
    known_prereqs: Sequence[str],
) -> str:
    """Explain a unit's position in terms the learner can check.

    Every clause is a fact about the graph and the learner's own estimates, which
    is the point: the plan should be arguable with, not taken on trust.

    :param graph: The prerequisite graph.
    :param states: Current mastery, keyed by node id.
    :param node_id: The concept this unit teaches.
    :param scheduled_prereqs: Prerequisites taught earlier in the plan.
    :param known_prereqs: Prerequisites already mastered.
    """
    parts: list[str] = []
    if scheduled_prereqs:
        parts.append(f"Comes after {_names(graph, scheduled_prereqs)}, taught earlier in this plan")
    if known_prereqs:
        clause = f"builds on {_names(graph, known_prereqs)}, which you already know"
        # Only the leading character, not str.capitalize, which would lowercase
        # every concept name in the clause.
        parts.append(clause if parts else clause[0].upper() + clause[1:])
    if not parts:
        parts.append("Foundational: nothing in the graph has to come before it")

    tail = f"Your estimate here is {_mastery(states, node_id):.0%}"
    unblocks = graph.unblocking_power(node_id)
    if unblocks:
        tail += f", and it stands between you and {unblocks} later concept"
        tail += "s" if unblocks != 1 else ""
    return f"{'; '.join(parts)}. {tail}."


def _names(graph: ConceptGraph, node_ids: Sequence[str]) -> str:
    """Join concept names into a readable list.

    :param graph: The prerequisite graph.
    :param node_ids: Concepts to name, in the order they should be read.
    """
    names = [graph.nodes[node_id].name for node_id in node_ids]
    if len(names) == 1:
        return names[0]
    return f"{', '.join(names[:-1])} and {names[-1]}"


def _score(
    graph: ConceptGraph,
    states: Mapping[str, MasteryState],
    node_id: str,
    params: MasteryParams,
) -> float:
    """Priority of one concept: how weak it is, times how much it unblocks.

    Shares :func:`app.mastery.coverage.priority` with the report rather than
    restating the formula, so the concepts the report calls out as worth attacking
    are exactly the ones the plan front-loads.

    :param graph: The prerequisite graph.
    :param states: Current mastery, keyed by node id.
    :param node_id: The concept to score.
    :param params: Model constants.
    """
    meta = graph.nodes[node_id]
    state = states.get(node_id)
    return priority(
        NodeScore(
            node_id=node_id,
            name=meta.name,
            tier=meta.tier,
            mastery=state.mastery if state else params.default_seed_mastery,
            confidence=state.confidence if state else 0.0,
            unblocks=graph.unblocking_power(node_id),
        )
    )


def _mastery(states: Mapping[str, MasteryState], node_id: str) -> float:
    """Current mastery of a concept, or zero when it has no state at all.

    :param states: Current mastery, keyed by node id.
    :param node_id: The concept to read.
    """
    state = states.get(node_id)
    return state.mastery if state is not None else 0.0
