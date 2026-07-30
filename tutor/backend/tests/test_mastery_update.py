"""Tests for the direct update rule, propagation, decay, and reconciliation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.mastery.decay import DecayInput, decay_all, decay_state, elapsed_days
from app.mastery.elo import (
    difficulty_match,
    difficulty_to_ability,
    expected_score,
    update_mastery,
)
from app.mastery.propagation import (
    apply_propagation,
    propagate_evidence,
    smooth_posterior,
)
from app.mastery.reconcile import merge_mastery, seed_mastery, split_mastery
from app.mastery.state import DEFAULT_PARAMS as P
from app.mastery.state import MasteryParams, MasteryState
from tests.factories import chain, diamond

MID = MasteryState(mastery=0.5, confidence=0.2)


# --- the update rule -----------------------------------------------------------


def test_difficulty_maps_onto_the_mastery_scale() -> None:
    """Tier 1 items suit low mastery, tier 5 items suit high mastery."""
    assert difficulty_to_ability(1) == pytest.approx(0.1)
    assert difficulty_to_ability(5) == pytest.approx(0.9)


def test_expected_score_rises_with_mastery_and_falls_with_difficulty() -> None:
    """The logistic curve points the way it should."""
    assert expected_score(0.9, 3, P) > expected_score(0.5, 3, P) > expected_score(0.1, 3, P)
    assert expected_score(0.5, 1, P) > expected_score(0.5, 3, P) > expected_score(0.5, 5, P)
    assert expected_score(0.5, 3, P) == pytest.approx(0.5, abs=0.02)


def test_correct_answer_raises_mastery_and_wrong_answer_lowers_it() -> None:
    """The sign of the update follows the sign of the surprise."""
    up = update_mastery(MID, difficulty=3, score=1.0, params=P)
    down = update_mastery(MID, difficulty=3, score=0.0, params=P)
    assert up.state.mastery > MID.mastery
    assert down.state.mastery < MID.mastery
    assert up.mastery_delta > 0 > down.mastery_delta


def test_step_size_grows_with_difficulty() -> None:
    """A hard item moves the estimate further than an easy one, all else equal."""
    state = MasteryState(mastery=0.5, confidence=0.0)
    easy = update_mastery(state, difficulty=1, score=1.0, params=P)
    hard = update_mastery(state, difficulty=5, score=1.0, params=P)
    # The easy item is also less surprising, so compare the step, not the delta.
    assert hard.mastery_delta / hard.surprise > easy.mastery_delta / easy.surprise


def test_step_size_shrinks_as_confidence_grows() -> None:
    """A well-established estimate does not swing on one answer."""
    unsure = MasteryState(mastery=0.5, confidence=0.0)
    sure = MasteryState(mastery=0.5, confidence=0.95)
    assert (
        update_mastery(unsure, difficulty=3, score=1.0, params=P).mastery_delta
        > update_mastery(sure, difficulty=3, score=1.0, params=P).mastery_delta
    )


def test_one_surprising_answer_barely_dents_a_confident_estimate() -> None:
    """Damping exists so noise cannot destroy a well-established estimate."""
    state = MasteryState(mastery=0.85, confidence=0.98)
    after_one = update_mastery(state, difficulty=3, score=0.0, params=P).state
    assert after_one.mastery == pytest.approx(0.81, abs=0.02)


def test_a_confident_estimate_still_moves_under_sustained_evidence() -> None:
    """Damping is partial: confidence must not make an estimate unfalsifiable."""
    state = MasteryState(mastery=0.85, confidence=0.98)
    for _ in range(15):
        state = update_mastery(state, difficulty=3, score=0.0, params=P).state
    assert state.mastery < 0.45


def test_confidence_rises_monotonically_and_never_exceeds_one() -> None:
    """Every observation adds confidence, with diminishing returns."""
    state = MasteryState(mastery=0.5, confidence=0.0)
    previous = -1.0
    for _ in range(40):
        state = update_mastery(state, difficulty=3, score=1.0, params=P).state
        assert state.confidence > previous
        previous = state.confidence
    assert state.confidence <= 1.0


def test_well_matched_items_add_more_confidence() -> None:
    """An item at the learner's level teaches more than one far from it."""
    state = MasteryState(mastery=0.9, confidence=0.1)
    matched = update_mastery(state, difficulty=5, score=1.0, params=P)
    mismatched = update_mastery(state, difficulty=1, score=1.0, params=P)
    assert matched.state.confidence > mismatched.state.confidence
    assert difficulty_match(0.9, 5, P) > difficulty_match(0.9, 1, P)


def test_mastery_stays_within_bounds() -> None:
    """Repeated evidence saturates rather than escaping [0, 1]."""
    high = MasteryState(mastery=0.99, confidence=0.0)
    low = MasteryState(mastery=0.01, confidence=0.0)
    for _ in range(50):
        high = update_mastery(high, difficulty=5, score=1.0, params=P).state
        low = update_mastery(low, difficulty=1, score=0.0, params=P).state
    assert 0.0 <= low.mastery <= high.mastery <= 1.0


def test_repeated_consistent_evidence_converges_near_the_item_difficulty() -> None:
    """Scoring exactly at chance on tier-3 items settles mastery near tier 3's level."""
    state = MasteryState(mastery=0.05, confidence=0.0)
    for _ in range(80):
        state = update_mastery(state, difficulty=3, score=0.5, params=P).state
    assert state.mastery == pytest.approx(difficulty_to_ability(3), abs=0.08)


def test_state_rejects_out_of_range_values() -> None:
    """Bad values fail loudly rather than being silently clamped."""
    with pytest.raises(ValueError, match="mastery out of range"):
        MasteryState(mastery=1.5, confidence=0.5)
    with pytest.raises(ValueError, match="confidence out of range"):
        MasteryState(mastery=0.5, confidence=-0.1)
    assert MasteryState.clamped(1.5, -0.1) == MasteryState(mastery=1.0, confidence=0.0)


# --- propagation ---------------------------------------------------------------


def test_success_flows_up_to_prerequisites_only() -> None:
    """Getting an advanced concept right is evidence for its prerequisites."""
    graph = chain(4)
    effects = propagate_evidence(
        graph,
        node_id="c4",
        mastery_delta=0.2,
        observed_mastery=0.7,
        params=P,
    )
    assert set(effects) == {"c3", "c2", "c1"}
    assert all(effect.mastery_delta > 0 for effect in effects.values())


def test_failure_flows_down_to_dependents_only() -> None:
    """Failing a foundation is evidence against everything built on it."""
    graph = chain(4)
    effects = propagate_evidence(
        graph,
        node_id="c1",
        mastery_delta=-0.2,
        observed_mastery=0.2,
        params=P,
    )
    assert set(effects) == {"c2", "c3", "c4"}
    assert all(effect.mastery_delta < 0 for effect in effects.values())


def test_success_on_a_foundation_does_not_flow_down() -> None:
    """Knowing a prerequisite says nothing about what is built on it."""
    assert (
        propagate_evidence(
            chain(4),
            node_id="c1",
            mastery_delta=0.2,
            observed_mastery=0.7,
            params=P,
        )
        == {}
    )


def test_failure_on_an_advanced_node_does_not_flow_up() -> None:
    """Failing an advanced concept says nothing against foundations you may hold."""
    assert (
        propagate_evidence(
            chain(4),
            node_id="c4",
            mastery_delta=-0.2,
            observed_mastery=0.2,
            params=P,
        )
        == {}
    )


def test_propagation_attenuates_by_one_decay_factor_per_hop() -> None:
    """The per-hop factor is exactly ``propagation_decay``, computed by hand."""
    params = MasteryParams(propagation_decay=0.5, propagation_max_hops=3)
    effects = propagate_evidence(
        chain(4),
        node_id="c4",
        mastery_delta=0.4,
        observed_mastery=0.7,
        params=params,
    )
    assert effects["c3"].mastery_delta == pytest.approx(0.4 * 0.5)
    assert effects["c2"].mastery_delta == pytest.approx(0.4 * 0.25)
    assert effects["c1"].mastery_delta == pytest.approx(0.4 * 0.125)
    assert (effects["c3"].hops, effects["c2"].hops, effects["c1"].hops) == (1, 2, 3)


def test_propagation_stops_at_the_hop_limit() -> None:
    """Nodes beyond the limit are dropped, not attenuated to nearly nothing."""
    params = MasteryParams(propagation_max_hops=2)
    effects = propagate_evidence(
        chain(5),
        node_id="c5",
        mastery_delta=0.3,
        observed_mastery=0.7,
        params=params,
    )
    assert set(effects) == {"c4", "c3"}


def test_propagation_uses_the_shortest_path_in_a_diamond() -> None:
    """A node reachable twice is adjusted once, by its shortest distance."""
    effects = propagate_evidence(
        diamond(),
        node_id="top",
        mastery_delta=0.4,
        observed_mastery=0.7,
        params=P,
    )
    assert effects["base"].hops == 2
    assert effects["base"].mastery_delta == pytest.approx(0.4 * P.propagation_decay**2)


def test_zero_delta_propagates_nothing() -> None:
    """No change means no inference."""
    assert (
        propagate_evidence(
            chain(3),
            node_id="c2",
            mastery_delta=0.0,
            observed_mastery=0.2,
            params=P,
        )
        == {}
    )


def test_propagated_confidence_is_worth_less_than_direct() -> None:
    """Inference is weaker evidence than measurement."""
    effects = propagate_evidence(
        chain(2),
        node_id="c2",
        mastery_delta=0.2,
        observed_mastery=0.7,
        params=P,
    )
    assert effects["c1"].confidence_gain < P.confidence_gain


def test_apply_propagation_clamps_and_reports_only_changes() -> None:
    """Applying adjustments respects bounds and skips untouched nodes."""
    graph = chain(3)
    states = {
        "c1": MasteryState(mastery=0.98, confidence=0.5),
        "c2": MasteryState(mastery=0.5, confidence=0.5),
        "c3": MasteryState(mastery=0.5, confidence=0.5),
    }
    effects = propagate_evidence(
        graph,
        node_id="c3",
        mastery_delta=0.5,
        observed_mastery=0.7,
        params=P,
    )
    changed = apply_propagation(states, effects)
    assert changed["c1"].mastery == 1.0
    assert "c3" not in changed
    assert changed["c2"].confidence > states["c2"].confidence


def test_apply_propagation_ignores_unknown_nodes() -> None:
    """An adjustment for a node with no state is dropped rather than crashing."""
    effects = propagate_evidence(
        chain(2),
        node_id="c2",
        mastery_delta=0.2,
        observed_mastery=0.7,
        params=P,
    )
    assert apply_propagation({}, effects) == {}


def test_smooth_posterior_caps_a_node_its_new_prerequisites_cannot_support() -> None:
    """After an edge change, an over-optimistic estimate is pulled back."""
    graph = chain(2)
    states = {
        "c1": MasteryState(mastery=0.1, confidence=0.8),
        "c2": MasteryState(mastery=0.95, confidence=0.8),
    }
    changed = smooth_posterior(graph, states, affected=frozenset({"c2"}), params=P)
    assert changed["c2"].mastery == pytest.approx(0.1 + P.posterior_slack)
    assert changed["c2"].confidence < states["c2"].confidence


def test_smooth_posterior_leaves_supported_estimates_alone() -> None:
    """A node whose prerequisites justify it is untouched."""
    graph = chain(2)
    states = {
        "c1": MasteryState(mastery=0.9, confidence=0.8),
        "c2": MasteryState(mastery=0.8, confidence=0.8),
    }
    assert smooth_posterior(graph, states, affected=frozenset({"c2"}), params=P) == {}


def test_smooth_posterior_cascades_downstream() -> None:
    """Capping one node can cap what depends on it."""
    graph = chain(3)
    states = {
        "c1": MasteryState(mastery=0.0, confidence=0.5),
        "c2": MasteryState(mastery=0.95, confidence=0.5),
        "c3": MasteryState(mastery=0.95, confidence=0.5),
    }
    changed = smooth_posterior(graph, states, affected=frozenset({"c2"}), params=P)
    assert set(changed) == {"c2", "c3"}
    assert changed["c3"].mastery < 0.95


def test_smooth_posterior_with_no_affected_nodes_is_a_no_op() -> None:
    """Nothing changed means nothing to reconcile."""
    assert smooth_posterior(chain(3), {}, affected=frozenset(), params=P) == {}


# --- decay ---------------------------------------------------------------------


def test_mastery_halves_toward_its_floor_over_one_half_life() -> None:
    """The retention curve matches the configured half-life exactly."""
    params = MasteryParams(mastery_half_life_days=60.0, retained_fraction=0.35)
    aged = decay_state(MasteryState(mastery=1.0, confidence=1.0), days=60.0, params=params)
    assert aged.mastery == pytest.approx(0.35 + 0.65 * 0.5)


def test_mastery_never_decays_below_its_retained_fraction() -> None:
    """Having once understood something leaves a trace."""
    params = MasteryParams(retained_fraction=0.35)
    aged = decay_state(MasteryState(mastery=0.8, confidence=1.0), days=10_000, params=params)
    assert aged.mastery == pytest.approx(0.8 * 0.35, abs=1e-6)


def test_confidence_decays_toward_zero() -> None:
    """After long enough, the honest position is that we no longer know."""
    aged = decay_state(MasteryState(mastery=0.8, confidence=1.0), days=10_000, params=P)
    assert aged.confidence == pytest.approx(0.0, abs=1e-6)


def test_confidence_halves_over_its_own_half_life() -> None:
    """Confidence uses its own, shorter half-life."""
    params = MasteryParams(confidence_half_life_days=45.0)
    aged = decay_state(MasteryState(mastery=0.5, confidence=0.8), days=45.0, params=params)
    assert aged.confidence == pytest.approx(0.4)


def test_decay_over_zero_or_negative_days_changes_nothing() -> None:
    """A clock skew must not age an estimate."""
    state = MasteryState(mastery=0.6, confidence=0.4)
    assert decay_state(state, days=0.0, params=P) is state
    assert decay_state(state, days=-5.0, params=P) is state


def test_decay_is_computed_from_a_stored_timestamp_not_compounded() -> None:
    """Two 30-day steps equal one 60-day step, so reading a report cannot age it."""
    start = MasteryState(mastery=0.9, confidence=0.9)
    once = decay_state(start, days=60.0, params=P)
    twice = decay_state(decay_state(start, days=30.0, params=P), days=30.0, params=P)
    assert once.mastery == pytest.approx(twice.mastery, abs=0.02)


def test_decay_all_skips_nodes_never_touched() -> None:
    """A node with no retrieval history has nothing to forget."""
    now = datetime(2026, 7, 30, tzinfo=UTC)
    inputs = {
        "fresh": DecayInput(MasteryState(mastery=0.8, confidence=0.8), now),
        "stale": DecayInput(MasteryState(mastery=0.8, confidence=0.8), now - timedelta(days=120)),
        "untouched": DecayInput(MasteryState(mastery=0.15, confidence=0.1), None),
    }
    changed = decay_all(inputs, now=now, params=P)
    assert set(changed) == {"stale"}
    assert changed["stale"].mastery < 0.8


def test_elapsed_days_floors_at_zero() -> None:
    """A future timestamp yields zero elapsed days, not a negative interval."""
    now = datetime(2026, 7, 30, tzinfo=UTC)
    assert elapsed_days(now + timedelta(days=3), now) == 0.0
    assert elapsed_days(None, now) == 0.0
    assert elapsed_days(now - timedelta(days=2), now) == pytest.approx(2.0)


# --- reconciliation ------------------------------------------------------------


def test_split_gives_each_child_the_parent_mastery_and_half_the_confidence() -> None:
    """You knew the thing; we no longer know which part."""
    parent = MasteryState(mastery=0.82, confidence=0.6)
    children = split_mastery(parent, into=3, params=P)
    assert len(children) == 3
    for child in children:
        assert child.mastery == pytest.approx(0.82)
        assert child.confidence == pytest.approx(0.3)


def test_split_requires_at_least_two_children() -> None:
    """A one-way split is a rename, and should be rejected as a split."""
    with pytest.raises(ValueError, match="at least two"):
        split_mastery(MID, into=1, params=P)


def test_merge_uses_confidence_weighted_mean_mastery() -> None:
    """A well-evidenced estimate should dominate a barely-evidenced one."""
    merged = merge_mastery(
        [
            MasteryState(mastery=0.9, confidence=0.8),
            MasteryState(mastery=0.3, confidence=0.2),
        ]
    )
    assert merged.mastery == pytest.approx((0.9 * 0.8 + 0.3 * 0.2) / 1.0)


def test_merge_takes_the_minimum_confidence_not_the_mean() -> None:
    """A merged concept is only as well understood as its least-known part."""
    merged = merge_mastery(
        [
            MasteryState(mastery=0.9, confidence=0.9),
            MasteryState(mastery=0.8, confidence=0.1),
        ]
    )
    assert merged.confidence == pytest.approx(0.1)


def test_merge_with_no_evidence_falls_back_to_the_plain_mean() -> None:
    """Zero total confidence must not divide by zero."""
    merged = merge_mastery(
        [
            MasteryState(mastery=0.4, confidence=0.0),
            MasteryState(mastery=0.8, confidence=0.0),
        ]
    )
    assert merged.mastery == pytest.approx(0.6)
    assert merged.confidence == 0.0


def test_merge_of_one_state_is_that_state() -> None:
    """A degenerate merge is the identity."""
    assert merge_mastery([MID]) == MID


def test_merge_of_nothing_is_an_error() -> None:
    """There is no sensible answer, so do not invent one."""
    with pytest.raises(ValueError, match="zero states"):
        merge_mastery([])


def test_a_new_node_is_never_seeded_at_zero() -> None:
    """Seeding at zero invents a weakness and wastes diagnostic questions."""
    from_nothing = seed_mastery([], P)
    from_weak = seed_mastery([MasteryState(mastery=0.0, confidence=0.9)], P)
    assert from_nothing.mastery >= P.default_seed_mastery > 0.0
    assert from_weak.mastery >= P.default_seed_mastery > 0.0


def test_a_new_node_inherits_a_decayed_mean_of_its_prerequisites() -> None:
    """Depending on things you know is real but weaker evidence than being tested."""
    prereqs = [
        MasteryState(mastery=0.9, confidence=0.8),
        MasteryState(mastery=0.7, confidence=0.8),
    ]
    seeded = seed_mastery(prereqs, P)
    assert seeded.mastery == pytest.approx(P.seed_prereq_decay * 0.8)
    assert seeded.mastery < 0.8
    assert seeded.confidence == pytest.approx(P.seeded_confidence)


def test_a_new_node_weights_prerequisites_by_confidence() -> None:
    """A guessed prerequisite should not drag a well-established one around."""
    seeded = seed_mastery(
        [
            MasteryState(mastery=0.9, confidence=0.9),
            MasteryState(mastery=0.1, confidence=0.05),
        ],
        P,
    )
    naive = seed_mastery(
        [
            MasteryState(mastery=0.9, confidence=0.5),
            MasteryState(mastery=0.1, confidence=0.5),
        ],
        P,
    )
    assert seeded.mastery > naive.mastery
