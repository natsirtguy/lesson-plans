"""Applying one graded answer to the mastery model.

Every graded retrieval goes through here, whatever queue it came from: a
diagnostic item, a unit's exit check, or a scheduled review. That is the point of
the module. The sequence -- update the answered concept, propagate what the answer
implies about its neighbourhood, then re-derive the priors of everything still
weakly evidenced -- has to be identical across all three, because the estimate is
supposed to be a single belief about the learner rather than one belief per
feature that happened to write it.

The arithmetic is all in :mod:`app.mastery`, which is pure. This adds the two
things that are not: mutating the loaded subject's state map, and writing the
result back onto the mastery rows.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.db import utcnow
from app.mastery.elo import update_mastery
from app.mastery.propagation import apply_propagation, propagate_evidence, refresh_priors
from app.mastery.state import MasteryParams, MasteryState
from app.schemas.diagnostic import MasteryChange
from app.services.graph_loader import LoadedSubject


@dataclass(slots=True)
class AppliedUpdate:
    """The mastery movement caused by one answer.

    :param changes: Per-concept before and after values, direct change first.
    :param direct_before: The answered concept's state before the answer.
    :param direct_after: The answered concept's state after it.
    """

    changes: list[MasteryChange]
    direct_before: MasteryState
    direct_after: MasteryState


class MasteryUpdater:
    """Applies graded answers to a loaded subject's estimates."""

    def __init__(self, params: MasteryParams) -> None:
        """
        :param params: Mastery model constants.
        """
        self._params = params

    def apply(
        self, loaded: LoadedSubject, *, node_id: str, difficulty: int, score: float
    ) -> AppliedUpdate:
        """Update the answered concept and everything the answer informs.

        :param loaded: The subject being assessed.
        :param node_id: The concept that was tested.
        :param difficulty: The item's difficulty, 1 through 5.
        :param score: The rubric score in [0, 1].
        """
        before = loaded.states[node_id]
        update = update_mastery(before, difficulty=difficulty, score=score, params=self._params)
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
        changes.extend(
            MasteryChange(
                node_id=other_id,
                node_name=loaded.graph.nodes[other_id].name,
                mastery_before=state.mastery - propagated[other_id].mastery_delta,
                mastery_after=state.mastery,
                confidence_after=state.confidence,
                propagated=True,
            )
            for other_id, state in moved.items()
        )

        self._persist(loaded, node_id, set(moved) | set(reseeded))
        return AppliedUpdate(changes=changes, direct_before=before, direct_after=update.state)

    @staticmethod
    def _persist(loaded: LoadedSubject, direct_id: str, indirect_ids: set[str]) -> None:
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
