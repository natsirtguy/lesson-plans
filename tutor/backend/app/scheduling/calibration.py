"""Judging whether the spacing is pitched right, from retrieval success alone.

The target is roughly 85% success. Consistently above that means intervals are too
short and the learner is spending time on things they already have; consistently
below it means intervals are too long and retrieval is failing outright, which is
both demoralising and a poor use of the attempt.

Deliberately a pure function over recent rubric scores. It has no view on *what*
to do about the verdict -- widening intervals is the scheduler's job -- and no
access to the clock, so it can be tested by handing it a list of numbers.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.config import Settings


@dataclass(frozen=True, slots=True)
class Calibration:
    """How well recent retrieval matched the target success rate.

    :param success_rate: Share of recent retrievals graded a success, or None when
        there is not enough data to compute one worth reporting.
    :param sample_size: Retrievals considered.
    :param verdict: ``widen``, ``tighten``, ``on_target``, or ``insufficient_data``.
    :param advice: One sentence for the learner.
    """

    success_rate: float | None
    sample_size: int
    verdict: str
    advice: str


def calibrate(scores: Sequence[float], settings: Settings) -> Calibration:
    """Assess recent retrieval success against the target retention rate.

    :param scores: Recent rubric scores in [0, 1], any order.
    :param settings: Runtime configuration supplying the thresholds.
    """
    sample = len(scores)
    if sample < settings.calibration_min_samples:
        return Calibration(
            success_rate=(sum(1 for s in scores if s >= settings.grade_again_below) / sample)
            if sample
            else None,
            sample_size=sample,
            verdict="insufficient_data",
            advice=(
                f"Not enough graded retrievals yet -- {sample} of the "
                f"{settings.calibration_min_samples} needed before the spacing can be judged."
            ),
        )

    rate = sum(1 for score in scores if score >= settings.grade_again_below) / sample
    target = settings.target_retention
    if rate > settings.calibration_high_watermark:
        return Calibration(
            success_rate=rate,
            sample_size=sample,
            verdict="widen",
            advice=(
                f"You are recalling {rate:.0%} of what you review, against a target of "
                f"{target:.0%}. The intervals are shorter than they need to be, so some of "
                "that time is being spent on material you already have."
            ),
        )
    if rate < settings.calibration_low_watermark:
        return Calibration(
            success_rate=rate,
            sample_size=sample,
            verdict="tighten",
            advice=(
                f"You are recalling {rate:.0%} of what you review, against a target of "
                f"{target:.0%}. The intervals have run ahead of your retention -- reviews "
                "are arriving after the material has gone."
            ),
        )
    return Calibration(
        success_rate=rate,
        sample_size=sample,
        verdict="on_target",
        advice=(
            f"Retrieval is running at {rate:.0%}, which is where it should be. Difficult "
            "enough to be worth the attempt, easy enough to succeed."
        ),
    )
