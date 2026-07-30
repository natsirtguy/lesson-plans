"""Turning a rubric score into a four-point retrieval grade.

FSRS wants again/hard/good/easy. The spec is explicit that this comes from the
grader's rubric score rather than the learner's self-report, which removes the
usual self-assessment bias -- people rate a barely-recalled answer "good" far more
often than a grader does.

The cut points are configuration rather than constants because they encode a
judgement about what counts as a lapse, and that is exactly the kind of thing worth
tuning once real answer data exists.
"""

from __future__ import annotations

from enum import IntEnum

from app.config import Settings


class Grade(IntEnum):
    """The four-point FSRS retrieval grade."""

    AGAIN = 1
    HARD = 2
    GOOD = 3
    EASY = 4


def grade_from_score(
    score: float,
    *,
    again_below: float = 0.6,
    hard_below: float = 0.75,
    good_below: float = 0.9,
) -> Grade:
    """Map a rubric score in [0, 1] onto a retrieval grade.

    :param score: The grader's rubric score.
    :param again_below: Below this is a lapse.
    :param hard_below: Below this is a struggling success.
    :param good_below: Below this is an ordinary success.
    """
    if score < again_below:
        return Grade.AGAIN
    if score < hard_below:
        return Grade.HARD
    if score < good_below:
        return Grade.GOOD
    return Grade.EASY


def grade_for(score: float, settings: Settings) -> Grade:
    """Map a rubric score onto a grade using configured cut points.

    :param score: The grader's rubric score.
    :param settings: Runtime configuration.
    """
    return grade_from_score(
        score,
        again_below=settings.grade_again_below,
        hard_below=settings.grade_hard_below,
        good_below=settings.grade_good_below,
    )
