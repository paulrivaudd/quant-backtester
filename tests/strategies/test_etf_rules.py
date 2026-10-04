"""The rules as pure functions: thresholds, signs, caps, and what a missing input does."""

from __future__ import annotations

import itertools

import pytest

from quant_backtester.strategies.adaptive.rules import (
    INVESTED,
    MISSING_INPUT,
    NEUTRAL,
    STANDS_ASIDE,
    RuleTarget,
    above_average_rule,
    clip,
    conservative_volatility,
    dual_momentum_rule,
    factor_blend_rule,
    monetary_carry_rule,
    pullback_rule,
    relative_tilt_rule,
    relief_entry_rule,
    risk_scale,
    smooth_trend_rule,
    volatility_control_rule,
)

A, B = "A", "B"


def momentum(first: tuple[float | None, float | None], second: tuple[float | None, float | None]):
    """Return rule 1 on ``(medium, long)`` momenta, with the specified parameters."""
    return dual_momentum_rule(
        A,
        B,
        first_medium=first[0],
        first_long=first[1],
        second_medium=second[0],
        second_long=second[1],
        full_tilt_gap=0.05,
        neutral_weight=0.50,
        tilt=0.25,
        single_weight=0.75,
    )


def pullback(z: float | None, trend: float | None) -> RuleTarget:
    """Return rule 3 with the specified parameters."""
    return pullback_rule(A, z, trend, maximum_weight=0.50, entry_z=0.50, z_range=1.00)


def tilt(z: float | None) -> RuleTarget:
    """Return rule 4 with the specified parameters."""
    return relative_tilt_rule(A, B, z, full_tilt_z=2.0, neutral_weight=0.50, tilt=0.25)


def vol_control(short: float | None, long: float | None) -> RuleTarget:
    """Return rule 5 with the specified parameters."""
    return volatility_control_rule(A, short, long, target_volatility=0.12, floor=0.05)


def blend(volatilities: dict[str, float | None]) -> RuleTarget:
    """Return rule 6 with the specified parameters."""
    return factor_blend_rule(volatilities, floor=0.10, maximum_weight=0.40, equal_share=0.50)


def carry(momentum_63: float | None, volatility: float | None) -> RuleTarget:
    """Return rule 7 with the specified parameters."""
    return monetary_carry_rule(
        A,
        momentum_63,
        volatility,
        lookback_sessions=63,
        annualization=252,
        horizon_years=0.25,
        round_trip_cost=0.002,
        maximum_volatility=0.02,
    )


def test_clip_bounds_a_value() -> None:
    assert [clip(x, 0.0, 1.0) for x in (-1.0, 0.3, 2.0)] == [0.0, 0.3, 1.0]


def test_a_target_drops_its_zero_weights_and_cannot_be_edited() -> None:
    target = RuleTarget({A: 0.0, B: 0.4}, INVESTED)

    assert dict(target.weights) == {B: 0.4}
    with pytest.raises(TypeError):
        target.weights[A] = 1.0  # type: ignore[index]


# --- rule 0 ----------------------------------------------------------------------------


def test_rule_0_holds_the_fund_strictly_above_its_average_only() -> None:
    assert dict(above_average_rule(A, 0.001).weights) == {A: 1.0}
    assert dict(above_average_rule(A, 0.0).weights) == {}
    assert above_average_rule(A, 0.0).reason == STANDS_ASIDE
    assert dict(above_average_rule(A, -0.02).weights) == {}


def test_rule_0_without_a_distance_is_inactive() -> None:
    target = above_average_rule(A, None)

    assert dict(target.weights) == {}
    assert target.reason == MISSING_INPUT
    assert not target.active


# --- rule 1 ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("gap", "first_weight"),
    [(0.0, 0.50), (0.025, 0.625), (0.05, 0.75), (0.20, 0.75), (-0.025, 0.375), (-0.20, 0.25)],
)
def test_rule_1_leans_by_the_difference_of_scores(gap: float, first_weight: float) -> None:
    # The medium momentum carries twice the gap: the score is the mean of the two.
    target = momentum((0.10 + 2.0 * gap, 0.10), (0.10, 0.10))

    assert target.weights[A] == pytest.approx(first_weight)
    assert target.weights[B] == pytest.approx(1.0 - first_weight)


def test_rule_1_scores_the_mean_of_the_two_momenta() -> None:
    """Scores 0.12 and 0.10: a gap of two points is 40% of the full tilt."""
    target = momentum((0.20, 0.04), (0.10, 0.10))

    assert target.weights[A] == pytest.approx(0.50 + 0.25 * 0.4)


def test_rule_1_with_one_fund_rising_holds_three_quarters_of_it() -> None:
    assert dict(momentum((0.30, 0.10), (0.30, 0.0)).weights) == {A: 0.75}
    assert dict(momentum((0.30, -0.01), (0.0, 0.02)).weights) == {B: 0.75}


def test_rule_1_with_no_fund_rising_is_cash() -> None:
    target = momentum((0.30, -0.01), (0.30, 0.0))

    assert dict(target.weights) == {}
    assert target.reason == STANDS_ASIDE


def test_rule_1_missing_any_momentum_is_inactive() -> None:
    for first, second in (
        ((None, 0.1), (0.1, 0.1)),
        ((0.1, None), (0.1, 0.1)),
        ((0.1, 0.1), (None, 0.1)),
        ((0.1, 0.1), (0.1, None)),
    ):
        assert momentum(first, second).reason == MISSING_INPUT


# --- rule 2 ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cross", "weight"), [(-0.01, 0.0), (0.0, 0.0), (0.01, 0.5), (0.02, 1.0), (0.10, 1.0)]
)
def test_rule_2_grows_with_the_gap_between_the_averages(cross: float, weight: float) -> None:
    target = smooth_trend_rule(A, cross, full_exposure_gap=0.02)

    assert target.weights.get(A, 0.0) == pytest.approx(weight)


def test_rule_2_without_a_cross_is_inactive() -> None:
    assert smooth_trend_rule(A, None, full_exposure_gap=0.02).reason == MISSING_INPUT


# --- rule 3 ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("z", "weight"), [(-1.0, 0.0), (0.5, 0.0), (1.0, 0.25), (1.5, 0.50), (4.0, 0.50)]
)
def test_rule_3_buys_a_fall_up_to_half_the_book(z: float, weight: float) -> None:
    assert pullback(z, 0.05).weights.get(A, 0.0) == pytest.approx(weight)


def test_rule_3_holds_nothing_on_the_long_average_or_below_it() -> None:
    assert dict(pullback(3.0, 0.0).weights) == {}
    assert dict(pullback(3.0, -0.02).weights) == {}


def test_rule_3_missing_either_signal_is_inactive() -> None:
    assert pullback(None, 0.05).reason == MISSING_INPUT
    assert pullback(2.0, None).reason == MISSING_INPUT


# --- rule 4 ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("z", "first_weight"), [(0.0, 0.50), (1.0, 0.625), (2.0, 0.75), (9.0, 0.75), (-2.0, 0.25)]
)
def test_rule_4_overweights_the_fund_that_lagged(z: float, first_weight: float) -> None:
    target = tilt(z)

    assert target.weights[A] == pytest.approx(first_weight)
    assert target.weights[B] == pytest.approx(1.0 - first_weight)


def test_rule_4_with_nothing_to_lean_on_is_the_neutral_split_not_cash() -> None:
    assert tilt(0.0).reason == NEUTRAL
    assert tilt(0.0).active


def test_rule_4_without_a_residual_is_cash() -> None:
    assert dict(tilt(None).weights) == {}
    assert tilt(None).reason == MISSING_INPUT


# --- rule 5 ----------------------------------------------------------------------------


def test_rule_5_halves_the_exposure_at_twice_the_target() -> None:
    assert vol_control(0.24, 0.10).weights[A] == pytest.approx(0.5)


def test_rule_5_takes_the_larger_of_the_two_estimates() -> None:
    assert vol_control(0.10, 0.24).weights[A] == pytest.approx(0.5)


def test_rule_5_never_borrows() -> None:
    assert vol_control(0.08, 0.06).weights[A] == 1.0
    assert vol_control(0.01, 0.01).weights[A] == 1.0


def test_rule_5_missing_either_volatility_is_inactive() -> None:
    assert vol_control(None, 0.1).reason == MISSING_INPUT
    assert vol_control(0.1, None).reason == MISSING_INPUT
    assert conservative_volatility(0.1, None, floor=0.05) is None
    assert conservative_volatility(0.01, 0.02, floor=0.05) == 0.05


# --- rule 6 ----------------------------------------------------------------------------


def test_rule_6_with_equal_volatilities_is_equal_weights() -> None:
    target = blend({"V": 0.15, "Q": 0.15, "M": 0.15})

    assert [target.weights[name] for name in ("V", "Q", "M")] == pytest.approx([1 / 3] * 3)


def test_rule_6_caps_a_quiet_fund_and_leaves_the_cut_in_cash() -> None:
    """A = 10, 5, 5: the quiet fund would take 41.7% and is cut to 40%."""
    target = blend({"V": 0.20, "Q": 0.20, "M": 0.10})

    assert target.weights["M"] == pytest.approx(0.40)
    assert target.weights["V"] == pytest.approx(0.5 / 3 + 0.5 * 0.25)
    assert sum(target.weights.values()) == pytest.approx(0.40 + 2 * (0.5 / 3 + 0.125))
    assert sum(target.weights.values()) < 1.0


def test_rule_6_floors_a_volatility_at_ten_percent() -> None:
    assert dict(blend({"V": 0.02, "Q": 0.20, "M": 0.20}).weights) == dict(
        blend({"V": 0.10, "Q": 0.20, "M": 0.20}).weights
    )


def test_rule_6_missing_one_fund_holds_none_of_them() -> None:
    target = blend({"V": 0.15, "Q": None, "M": 0.15})

    assert dict(target.weights) == {}
    assert target.reason == MISSING_INPUT


# --- rule 7 ----------------------------------------------------------------------------


def test_rule_7_holds_the_fund_when_a_quarter_of_carry_covers_the_round_trip() -> None:
    target = carry(0.004, 0.01)

    assert dict(target.weights) == {A: 1.0}
    assert target.diagnostics["carry"] == pytest.approx(4.0 * 0.004, rel=1e-2)


def test_rule_7_stands_aside_when_the_carry_is_too_thin_or_the_fund_too_volatile() -> None:
    assert dict(carry(0.0015, 0.01).weights) == {}
    assert dict(carry(-0.001, 0.01).weights) == {}
    assert dict(carry(0.004, 0.021).weights) == {}
    assert dict(carry(0.004, 0.02).weights) == {A: 1.0}


def test_rule_7_missing_either_signal_is_inactive() -> None:
    assert carry(None, 0.01).reason == MISSING_INPUT
    assert carry(0.004, None).reason == MISSING_INPUT


# --- rule 8 ----------------------------------------------------------------------------


def test_rule_8_needs_the_relief_and_the_recovery_together() -> None:
    assert dict(relief_entry_rule(A, 1.0, 0.01, weight=0.50).weights) == {A: 0.50}
    assert dict(relief_entry_rule(A, 0.0, 0.01, weight=0.50).weights) == {}
    assert dict(relief_entry_rule(A, 1.0, 0.0, weight=0.50).weights) == {}
    assert dict(relief_entry_rule(A, 1.0, -0.01, weight=0.50).weights) == {}


def test_rule_8_missing_either_signal_is_inactive() -> None:
    assert relief_entry_rule(A, None, 0.01, weight=0.50).reason == MISSING_INPUT
    assert relief_entry_rule(A, 1.0, None, weight=0.50).reason == MISSING_INPUT


# --- the risk control ------------------------------------------------------------------


def test_the_scale_brings_the_estimated_risk_to_its_target() -> None:
    """V = 0.8, S = 0.4 * 0.2 + 0.4 * 0.3 = 0.2: lambda = 0.12 / 0.2."""
    scale = risk_scale(
        {A: 0.4, B: 0.4}, {A: 0.2, B: 0.3}, target_volatility=0.12, cash_volatility=0.0
    )

    assert scale == pytest.approx(0.6)


def test_the_scale_reserves_risk_for_what_the_rest_is_placed_in() -> None:
    weights, volatilities = {A: 0.4, B: 0.4}, {A: 0.2, B: 0.3}
    scale = risk_scale(weights, volatilities, target_volatility=0.12, cash_volatility=0.01)

    assert scale == pytest.approx((0.12 - 0.01) / (0.2 - 0.8 * 0.01))
    equity_risk = scale * 0.2
    rest = 1.0 - scale * 0.8
    assert equity_risk + rest * 0.01 == pytest.approx(0.12)


def test_the_scale_never_levers_a_quiet_book() -> None:
    assert risk_scale({A: 0.5}, {A: 0.05}, target_volatility=0.12, cash_volatility=0.0) == 1.0


def test_an_empty_book_has_a_scale_of_zero() -> None:
    assert risk_scale({}, {}, target_volatility=0.12, cash_volatility=0.0) == 0.0


def test_funds_no_riskier_than_the_rest_cannot_be_scaled() -> None:
    with pytest.raises(ValueError, match="nothing to scale"):
        risk_scale({A: 0.5}, {A: 0.01}, target_volatility=0.12, cash_volatility=0.02)


# --- every rule ------------------------------------------------------------------------


def test_every_rule_gives_positive_weights_adding_up_to_at_most_one() -> None:
    grid = (-3.0, -0.3, -0.01, 0.0, 0.004, 0.02, 0.3, 3.0)
    volatilities = (0.01, 0.08, 0.2, 0.9)
    targets = [above_average_rule(A, x) for x in grid]
    targets += [smooth_trend_rule(A, x, full_exposure_gap=0.02) for x in grid]
    targets += [tilt(x) for x in grid]
    targets += [pullback(x, y) for x, y in itertools.product(grid, grid)]
    targets += [relief_entry_rule(A, 1.0, x, weight=0.50) for x in grid]
    targets += [vol_control(x, y) for x, y in itertools.product(volatilities, volatilities)]
    targets += [carry(x, y) for x, y in itertools.product(grid[2:], volatilities)]
    targets += [
        blend({"V": x, "Q": y, "M": z})
        for x, y, z in itertools.product(volatilities, volatilities, volatilities)
    ]
    targets += [momentum((w, x), (y, z)) for w, x, y, z in itertools.product(grid[::2], repeat=4)]

    for target in targets:
        assert all(weight > 0.0 for weight in target.weights.values())
        assert sum(target.weights.values()) <= 1.0 + 1e-12
