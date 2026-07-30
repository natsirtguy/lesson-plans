"""Carrying mastery across a change in graph structure.

This is the part that is easy to get wrong, so each rule is spelled out with its
justification. The rules are not symmetric, because the epistemics are not:

* **Split.** Each child inherits the parent's mastery, but half its confidence.
  You knew "the thing"; we no longer know which part of it you knew.
* **Merge.** Mastery is the confidence-weighted mean -- estimates backed by more
  evidence should dominate. Confidence is the **minimum** of the inputs, not the
  mean, because a merged concept is only as well understood as its least-known
  part. Averaging here would manufacture certainty out of a gap.
* **Add.** Mastery is seeded from a decayed mean of the prerequisites, with low
  confidence. Seeding at zero is the tempting default and it is wrong: it invents
  a weakness the evidence does not support, and the diagnostic then spends
  questions confirming the learner does not know something their prerequisites
  suggest they probably do.
* **Remove.** Nothing is discarded. The row is soft-deleted and restored intact if
  the concept comes back.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.mastery.state import MasteryParams, MasteryState, clamp


def split_mastery(parent: MasteryState, *, into: int, params: MasteryParams) -> list[MasteryState]:
    """Distribute a parent's state across the children of a split.

    :param parent: The state of the node being split.
    :param into: How many children the split produces.
    :param params: Model constants.
    :raises ValueError: If fewer than two children are requested.
    """
    if into < 2:
        raise ValueError("a split must produce at least two children")
    child = MasteryState(
        mastery=parent.mastery,
        confidence=clamp(parent.confidence * params.split_confidence_factor),
    )
    return [child for _ in range(into)]


def merge_mastery(inputs: Sequence[MasteryState]) -> MasteryState:
    """Combine several states into one.

    :param inputs: States of the nodes being merged.
    :raises ValueError: If no states are given.
    """
    if not inputs:
        raise ValueError("cannot merge zero states")
    if len(inputs) == 1:
        return inputs[0]

    total_confidence = sum(state.confidence for state in inputs)
    if total_confidence > 0:
        mastery = sum(s.mastery * s.confidence for s in inputs) / total_confidence
    else:
        # No evidence anywhere: fall back to the plain mean rather than dividing
        # by zero or arbitrarily picking one input.
        mastery = sum(s.mastery for s in inputs) / len(inputs)

    return MasteryState(
        mastery=clamp(mastery),
        confidence=min(state.confidence for state in inputs),
    )


def seed_mastery(prereq_states: Sequence[MasteryState], params: MasteryParams) -> MasteryState:
    """Seed a brand-new node from what its prerequisites imply.

    :param prereq_states: States of the new node's prerequisites, possibly empty.
    :param params: Model constants.
    """
    if not prereq_states:
        return MasteryState(
            mastery=params.default_seed_mastery,
            confidence=params.seeded_confidence,
        )

    total_confidence = sum(state.confidence for state in prereq_states)
    if total_confidence > 0:
        mean = sum(s.mastery * s.confidence for s in prereq_states) / total_confidence
    else:
        mean = sum(s.mastery for s in prereq_states) / len(prereq_states)

    # Depending on something the learner knows is real but weak evidence, so the
    # mean is decayed -- and floored, so a new node under weak prerequisites still
    # starts above zero.
    seeded = max(params.default_seed_mastery, params.seed_prereq_decay * mean)
    return MasteryState(mastery=clamp(seeded), confidence=params.seeded_confidence)
