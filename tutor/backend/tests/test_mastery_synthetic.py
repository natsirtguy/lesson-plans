"""The headline test: does the estimator actually estimate?

A synthetic learner with a known ground-truth mastery vector answers a simulated
adaptive diagnostic, and the recovered estimates are compared against the truth.
This is the test that catches the failures unit tests miss -- a propagation sign
error, a selector that starves, a prior that collapses -- because all of those
leave every individual function looking correct while the whole thing fails to
learn anything.

The tolerances below are measured, not aspirational. On a 100-node graph with 30
questions the model recovers a mean absolute error of roughly 0.14-0.18 across
four learner profiles and seven seeds, against 0.375 for the uninformed prior, and
the thresholds sit a little above the worst observed run. They are deliberately
loose enough not to fail on sampling noise and tight enough that any of the
regressions above would break them.

What 30 questions over 100 concepts cannot do is certify a specific concept to
high precision, and the assertions do not pretend otherwise. What they do check is
that the estimator gets the *shape* right: which learner is stronger, which tier is
the frontier, and which concepts to attack next.
"""

from __future__ import annotations

import statistics

import pytest

from app.mastery.coverage import coverage
from app.mastery.replay import initial_states, replay
from app.mastery.state import DEFAULT_PARAMS as P
from app.mastery.state import MasteryState
from tests.factories import layered
from tests.synthetic import Learner, mean_absolute_error, run_diagnostic, tiered_learner

#: Roughly the graph size the app generates, at the top of the spec's range.
GRAPH = layered(per_tier=20, tiers=5)

PROFILES: dict[str, dict[int, float]] = {
    # Knows the foundations, half-way through the middle, nothing above.
    "frontier": {1: 0.92, 2: 0.85, 3: 0.55, 4: 0.15, 5: 0.08},
    "expert": {1: 0.95, 2: 0.92, 3: 0.90, 4: 0.85, 5: 0.80},
    "beginner": {1: 0.15, 2: 0.10, 3: 0.08, 4: 0.05, 5: 0.05},
    # A real gap in the middle of otherwise decent knowledge.
    "uneven": {1: 0.90, 2: 0.30, 3: 0.70, 4: 0.20, 5: 0.10},
}

#: No single scenario may exceed this mean absolute error.
PER_SCENARIO_TOLERANCE = 0.30
#: Averaged over scenarios, the estimator must do at least this well.
AVERAGE_TOLERANCE = 0.20


def tier_means(states: dict[str, MasteryState]) -> dict[int, float]:
    """Mean estimated mastery per tier.

    :param states: Estimated states, keyed by node id.
    """
    return {
        tier: statistics.mean(
            states[node_id].mastery for node_id, meta in GRAPH.nodes.items() if meta.tier == tier
        )
        for tier in range(1, 6)
    }


@pytest.mark.parametrize("profile", sorted(PROFILES))
def test_synthetic_learner_is_recovered_within_tolerance(profile: str) -> None:
    """Each learner profile is estimated close to its ground truth."""
    learner = tiered_learner(GRAPH, PROFILES[profile], jitter=0.08)
    run = run_diagnostic(GRAPH, learner, P, max_items=30)
    error = mean_absolute_error(run.states, learner.true_mastery)
    assert error < PER_SCENARIO_TOLERANCE, f"{profile}: MAE {error:.3f}"


def test_the_estimator_beats_the_uninformed_prior() -> None:
    """Asking questions has to be worth more than not asking them.

    The comparison is averaged over profiles on purpose. A learner who happens to
    sit at the seed value is estimated well by doing nothing at all, so a
    per-profile version of this assertion would be measuring a coincidence.
    """
    estimated: list[float] = []
    baseline: list[float] = []
    for by_tier in PROFILES.values():
        learner = tiered_learner(GRAPH, by_tier, jitter=0.08)
        run = run_diagnostic(GRAPH, learner, P, max_items=30)
        estimated.append(mean_absolute_error(run.states, learner.true_mastery))
        baseline.append(mean_absolute_error(initial_states(GRAPH, P), learner.true_mastery))
    mean_estimated = statistics.mean(estimated)
    assert mean_estimated < AVERAGE_TOLERANCE
    assert mean_estimated < 0.6 * statistics.mean(baseline)


def test_the_diagnostic_tells_learners_apart() -> None:
    """Coverage has to order the learners the way their true mastery does."""
    scores: dict[str, float] = {}
    for name, by_tier in PROFILES.items():
        learner = tiered_learner(GRAPH, by_tier, jitter=0.08)
        run = run_diagnostic(GRAPH, learner, P, max_items=30)
        scores[name] = coverage(run.states)
    assert scores["expert"] > scores["frontier"] > scores["beginner"]
    assert scores["expert"] - scores["beginner"] > 0.4


def test_tier_profile_is_monotonic_for_a_uniformly_strong_learner() -> None:
    """An expert should not read as weak at the top of the graph."""
    learner = tiered_learner(GRAPH, PROFILES["expert"], jitter=0.08)
    run = run_diagnostic(GRAPH, learner, P, max_items=30)
    means = tier_means(run.states)
    assert min(means.values()) > 0.6, means


def test_tier_profile_stays_low_for_a_beginner() -> None:
    """A beginner should not be credited with knowledge they do not have."""
    learner = tiered_learner(GRAPH, PROFILES["beginner"], jitter=0.08)
    run = run_diagnostic(GRAPH, learner, P, max_items=30)
    means = tier_means(run.states)
    assert max(means.values()) < 0.45, means


def test_the_frontier_learner_is_ranked_top_down() -> None:
    """The estimate must put the known foundations above the unknown ceiling."""
    learner = tiered_learner(GRAPH, PROFILES["frontier"], jitter=0.08)
    run = run_diagnostic(GRAPH, learner, P, max_items=30)
    means = tier_means(run.states)
    assert means[1] > means[5]
    assert means[2] > means[4]


def test_the_diagnostic_respects_its_question_budget() -> None:
    """Thirty questions for a hundred concepts, and it stops on its own terms."""
    learner = tiered_learner(GRAPH, PROFILES["frontier"], jitter=0.08)
    run = run_diagnostic(GRAPH, learner, P, max_items=30, min_items=8)
    assert len(run.asked) <= 30
    assert run.stop_reason in {"max_items", "confidence_target"}


def test_the_selector_does_not_starve_on_one_part_of_the_graph() -> None:
    """A selector that fixates asks the same handful of nodes and learns nothing."""
    learner = tiered_learner(GRAPH, PROFILES["frontier"], jitter=0.08)
    run = run_diagnostic(GRAPH, learner, P, max_items=30)
    assert len(set(run.asked)) == len(run.asked), "no node should be asked twice"
    tiers_touched = {GRAPH.tier(node_id) for node_id in run.asked}
    assert len(tiers_touched) >= 3, tiers_touched


def test_recovery_is_stable_across_answer_sampling() -> None:
    """The result must not depend on a lucky random seed."""
    errors = []
    for seed in (1, 7, 13, 42, 101):
        learner = tiered_learner(GRAPH, PROFILES["frontier"], jitter=0.08, seed=seed)
        run = run_diagnostic(GRAPH, learner, P, max_items=30)
        errors.append(mean_absolute_error(run.states, learner.true_mastery))
    assert max(errors) < PER_SCENARIO_TOLERANCE
    assert statistics.pstdev(errors) < 0.05


def test_a_perfect_learner_is_not_reported_as_weak() -> None:
    """The extreme case, where any sign error shows up unmistakably."""
    learner = Learner(true_mastery=dict.fromkeys(GRAPH.node_ids, 1.0))
    run = run_diagnostic(GRAPH, learner, P, max_items=30)
    assert coverage(run.states) > 0.75


def test_a_learner_who_knows_nothing_is_not_reported_as_strong() -> None:
    """The opposite extreme."""
    learner = Learner(true_mastery=dict.fromkeys(GRAPH.node_ids, 0.0))
    run = run_diagnostic(GRAPH, learner, P, max_items=30)
    assert coverage(run.states) < 0.25


# --- replay --------------------------------------------------------------------


def test_replay_reproduces_the_incremental_estimate_exactly() -> None:
    """Recomputing from the log must agree with having updated as answers arrived.

    Exact equality, over every node and not just the ones asked about. The two
    paths have to perform the same operations in the same order, or recomputing
    after a graph edit would shift estimates for reasons unrelated to the edit --
    and that discrepancy would be nearly impossible to attribute later.
    """
    learner = tiered_learner(GRAPH, PROFILES["frontier"], jitter=0.08)
    run = run_diagnostic(GRAPH, learner, P, max_items=30)
    result = replay(GRAPH, run.observations, params=P)
    assert result.states == run.states


def test_replay_skips_observations_for_removed_nodes() -> None:
    """A response about a concept that no longer exists is dropped, not fatal."""
    learner = tiered_learner(GRAPH, PROFILES["frontier"], jitter=0.08)
    run = run_diagnostic(GRAPH, learner, P, max_items=12)
    dropped = run.asked[0]
    smaller = GRAPH.with_changes(remove_nodes=[dropped])
    result = replay(smaller, run.observations, params=P)
    assert result.skipped >= 1
    assert result.applied == len(run.observations) - result.skipped
    assert dropped not in result.states


def test_replay_orders_observations_chronologically() -> None:
    """The log may arrive in any order; the recomputation must not care."""
    learner = tiered_learner(GRAPH, PROFILES["uneven"], jitter=0.08)
    run = run_diagnostic(GRAPH, learner, P, max_items=15)
    forward = replay(GRAPH, run.observations, params=P)
    shuffled = replay(GRAPH, list(reversed(run.observations)), params=P)
    for node_id in forward.states:
        assert forward.states[node_id] == shuffled.states[node_id]


def test_replay_applies_decay_once_at_the_end() -> None:
    """Passing a later ``now`` ages the result; omitting it does not."""
    from datetime import UTC, datetime

    learner = tiered_learner(GRAPH, PROFILES["expert"], jitter=0.08)
    run = run_diagnostic(GRAPH, learner, P, max_items=12)
    fresh = replay(GRAPH, run.observations, params=P)
    aged = replay(GRAPH, run.observations, params=P, now=datetime(2027, 7, 30, tzinfo=UTC))
    node_id = run.asked[0]
    assert aged.states[node_id].mastery < fresh.states[node_id].mastery
    assert aged.states[node_id].confidence < fresh.states[node_id].confidence


def test_replay_with_no_observations_returns_the_seeded_prior() -> None:
    """An empty log is the uninformed starting point, not an error."""
    result = replay(GRAPH, [], params=P)
    assert result.applied == 0
    assert result.states == initial_states(GRAPH, P)
