"""The mastery model.

Pure functions over pure data. Nothing here touches the database, the clock, or
the network -- every input arrives as an argument, including "now". That is what
lets the model be tested against a synthetic learner with a known ground-truth
mastery vector, which is the only way to know the estimator actually estimates.

Reading order, if you are new to it: :mod:`state` for the value types,
:mod:`graph` for the structure and its edge-direction convention, :mod:`elo` for
the direct update, :mod:`propagation` for how one answer informs neighbours,
:mod:`selection` for what to ask next, :mod:`decay` for forgetting,
:mod:`reconcile` for surviving graph edits, :mod:`replay` for full
recomputation, and :mod:`coverage` for what the learner is shown.
"""

from __future__ import annotations

from app.mastery.coverage import (
    BlockingReport,
    CoverageReport,
    NodeScore,
    TierSummary,
    build_report,
    coverage,
    locked_nodes,
    next_tier_blockers,
    node_scores,
    priority,
    ready_to_learn,
    strengths,
    weaknesses,
)
from app.mastery.decay import DecayInput, decay_all, decay_state, elapsed_days
from app.mastery.elo import (
    Update,
    difficulty_match,
    difficulty_to_ability,
    expected_score,
    update_mastery,
)
from app.mastery.graph import ConceptGraph, Edge, GraphCycleError, NodeMeta
from app.mastery.propagation import (
    Propagated,
    apply_propagation,
    observed_tier_levels,
    prior_from_prereqs,
    propagate_evidence,
    refresh_priors,
    smooth_posterior,
)
from app.mastery.reconcile import merge_mastery, seed_mastery, split_mastery
from app.mastery.replay import Observation, ReplayResult, initial_states, replay
from app.mastery.selection import (
    Candidate,
    StopDecision,
    discounted_reach,
    information_gain,
    proximity_to_threshold,
    rank_candidates,
    select_difficulty,
    select_next_node,
    should_stop,
)
from app.mastery.state import DEFAULT_PARAMS, MasteryParams, MasteryState, clamp

__all__ = [
    "DEFAULT_PARAMS",
    "BlockingReport",
    "Candidate",
    "ConceptGraph",
    "CoverageReport",
    "DecayInput",
    "Edge",
    "GraphCycleError",
    "MasteryParams",
    "MasteryState",
    "NodeMeta",
    "NodeScore",
    "Observation",
    "Propagated",
    "ReplayResult",
    "StopDecision",
    "TierSummary",
    "Update",
    "apply_propagation",
    "build_report",
    "clamp",
    "coverage",
    "decay_all",
    "decay_state",
    "difficulty_match",
    "difficulty_to_ability",
    "discounted_reach",
    "elapsed_days",
    "expected_score",
    "information_gain",
    "initial_states",
    "locked_nodes",
    "merge_mastery",
    "next_tier_blockers",
    "node_scores",
    "observed_tier_levels",
    "prior_from_prereqs",
    "priority",
    "propagate_evidence",
    "proximity_to_threshold",
    "rank_candidates",
    "ready_to_learn",
    "refresh_priors",
    "replay",
    "seed_mastery",
    "select_difficulty",
    "select_next_node",
    "should_stop",
    "smooth_posterior",
    "split_mastery",
    "strengths",
    "update_mastery",
    "weaknesses",
]
