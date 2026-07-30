"""Forgetting.

Mastery and confidence both fall without retrieval, but they fall to different
places. Mastery decays toward a floor: having once understood something leaves a
trace, and treating a six-month-old success as worth nothing would send the
learner back to the beginning of a subject they largely still hold. Confidence
decays toward zero, because after long enough the honest position is that we no
longer know what they know.

Decay is applied from a stored ``decayed_at`` timestamp rather than compounded on
every read, so reading the report ten times in a row does not age the estimate ten
times.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from app.mastery.state import MasteryParams, MasteryState, clamp


@dataclass(frozen=True, slots=True)
class DecayInput:
    """One node's decay inputs.

    :param state: The stored state.
    :param last_touched: When decay was last applied, or when the node was last
        retrieved. None means the node has never been touched, so nothing decays.
    """

    state: MasteryState
    last_touched: datetime | None


def elapsed_days(since: datetime | None, now: datetime) -> float:
    """Days between two instants, floored at zero.

    :param since: The earlier instant, or None.
    :param now: The later instant.
    """
    if since is None:
        return 0.0
    return max(0.0, (now - since).total_seconds() / 86_400.0)


def decay_state(state: MasteryState, *, days: float, params: MasteryParams) -> MasteryState:
    """Age one state by a number of days without retrieval.

    :param state: The state to age.
    :param days: Days since the last retrieval.
    :param params: Model constants.
    """
    if days <= 0:
        return state
    mastery_retention = 0.5 ** (days / params.mastery_half_life_days)
    kept = params.retained_fraction + (1.0 - params.retained_fraction) * mastery_retention
    confidence_retention = 0.5 ** (days / params.confidence_half_life_days)
    return MasteryState(
        mastery=clamp(state.mastery * kept),
        confidence=clamp(state.confidence * confidence_retention),
    )


def decay_all(
    inputs: Mapping[str, DecayInput], *, now: datetime, params: MasteryParams
) -> dict[str, MasteryState]:
    """Age every node to ``now``, returning only those that changed.

    :param inputs: States with their last-touched timestamps, keyed by node id.
    :param now: The instant to age to.
    :param params: Model constants.
    """
    changed: dict[str, MasteryState] = {}
    for node_id, entry in inputs.items():
        days = elapsed_days(entry.last_touched, now)
        aged = decay_state(entry.state, days=days, params=params)
        if aged != entry.state:
            changed[node_id] = aged
    return changed
