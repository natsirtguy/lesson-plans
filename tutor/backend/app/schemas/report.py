"""Report schemas: where the learner stands and what is blocking them."""

from __future__ import annotations

from app.schemas.common import ApiModel


class NodeScoreRead(ApiModel):
    """One concept's standing in a ranked list."""

    node_id: str
    name: str
    tier: int
    mastery: float
    confidence: float
    unblocks: int


class TierSummaryRead(ApiModel):
    """Aggregate standing within one difficulty tier."""

    tier: int
    count: int
    mean_mastery: float
    mean_confidence: float
    mastered: int


class BlockingRead(ApiModel):
    """The next tier to clear, and what is holding it up."""

    target_tier: int | None
    blocked: list[NodeScoreRead]
    blockers: list[NodeScoreRead]


class CalibrationRead(ApiModel):
    """Whether the spacing is pitched right, judged by retrieval success.

    The target is ~85%: consistently above 90% means intervals are too short and
    time is being spent on things already known; below 75% means they are too long
    and retrieval is failing.
    """

    #: Share of recent retrievals scored as successes.
    success_rate: float | None
    sample_size: int
    #: "widen", "tighten", "on_target", or "insufficient_data".
    verdict: str
    advice: str


class ReportRead(ApiModel):
    """Everything the report view shows."""

    subject_id: str
    subject_name: str
    graph_version: int
    #: Mean estimated mastery across every live concept, in [0, 1].
    coverage: float
    mean_confidence: float
    total_nodes: int
    mastered_nodes: int
    #: Concepts with too little evidence for the estimate to mean much.
    unassessed_nodes: int
    tiers: list[TierSummaryRead]
    strengths: list[NodeScoreRead]
    weaknesses: list[NodeScoreRead]
    blocking: BlockingRead
    calibration: CalibrationRead
    #: Concepts that are unmastered but whose prerequisites are all done.
    ready_to_learn: list[NodeScoreRead]
    open_suggestions: int
    has_plan: bool
    diagnostic_responses: int
