"""Alpha, beta, tracking error and information ratio of a strategy against a benchmark.

Every expected value below is worked out by hand, or from the definitions on a
series built so that the answer is known: a strategy that is exactly ``c +
beta x`` of its benchmark must give back ``c`` and ``beta``. The calendar is a
synthetic run of consecutive days, and does not claim to be a venue's.
"""

from __future__ import annotations

import json
import math
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from quant_backtester.analytics.config import AnalyticsConfig
from quant_backtester.analytics.relative import (
    INSUFFICIENT_OBSERVATIONS,
    RETURN_STD_TOLERANCE,
    STATISTICS,
    ZERO_BENCHMARK_VARIANCE,
    ZERO_STRATEGY_VARIANCE,
    ZERO_TRACKING_ERROR,
    RelativePerformanceStats,
)

A = 252
RF_SESSION = 0.0001
X = np.array([-0.02, -0.01, 0.00, 0.01, 0.02])
"""The benchmark's excess returns of the specification's worked example."""

RESIDUALS = np.array([0.001, -0.002, 0.002, -0.002, 0.001])
"""Sum zero and orthogonal to ``X``: added to the strategy, the fit is unchanged."""

REL, ABS = 1e-9, 1e-10
"""Relative and absolute tolerances of the comparisons on these small samples."""


def wealth(returns: np.ndarray, start: float = 100.0) -> pd.Series:
    """Return the curve that earns ``returns``, one session a day from 2026-09-07."""
    index = pd.Index(
        [date(2026, 9, 7) + timedelta(days=i) for i in range(len(returns) + 1)], dtype="object"
    )
    return pd.Series(start * np.r_[1.0, np.cumprod(1.0 + returns)], index=index, dtype="float64")


def config(
    minimum: int = 3, rate_per_session: float = RF_SESSION, per_year: int = A
) -> AnalyticsConfig:
    """Return a convention whose per-session risk-free rate is ``rate_per_session``."""
    return AnalyticsConfig(
        sessions_per_year=per_year,
        risk_free_rate=(1.0 + rate_per_session) ** per_year - 1.0,
        minimum_sessions=minimum,
    )


def stats(
    strategy: np.ndarray, benchmark: np.ndarray, convention: AnalyticsConfig | None = None
) -> RelativePerformanceStats:
    """Return the relative statistics of two return series."""
    return RelativePerformanceStats.from_equity(
        wealth(strategy), wealth(benchmark), convention or config()
    )


def worked_example() -> RelativePerformanceStats:
    """Return the specification's example: alpha 0.0005, beta 1.5."""
    return stats(RF_SESSION + 0.0005 + 1.5 * X, RF_SESSION + X)


# --- M: the arithmetic ----------------------------------------------------------


def test_m01_the_worked_example_is_found_again() -> None:
    result = worked_example()
    assert result.sessions == 6 and result.observations == 5
    assert result.beta == pytest.approx(1.5, rel=REL, abs=ABS)
    assert result.alpha_per_session == pytest.approx(0.0005, rel=REL, abs=ABS)
    assert result.alpha_annualised == pytest.approx(0.126, rel=REL, abs=ABS)
    assert result.active_return_annualised == pytest.approx(0.126, rel=REL, abs=ABS)
    assert result.tracking_error_annualised == pytest.approx(0.12549900398011132, rel=REL, abs=ABS)
    assert result.information_ratio == pytest.approx(1.003992031840891, rel=REL, abs=ABS)
    assert result.r_squared == pytest.approx(1.0, rel=REL, abs=ABS)
    assert result.diagnostics == ()


def test_m02_orthogonal_residuals_leave_the_fit_and_lower_r_squared() -> None:
    strategy = RF_SESSION + 0.0005 + 1.5 * X + RESIDUALS
    result = stats(strategy, RF_SESSION + X)
    assert result.beta == pytest.approx(1.5, rel=REL, abs=ABS)
    assert result.alpha_per_session == pytest.approx(0.0005, rel=REL, abs=ABS)
    assert result.r_squared == pytest.approx(0.9938162544169611, rel=REL, abs=ABS)
    active = strategy - (RF_SESSION + X)
    spread = float(np.std(active, ddof=1))
    assert result.tracking_error_annualised == pytest.approx(
        math.sqrt(A) * spread, rel=REL, abs=ABS
    )
    assert result.information_ratio == pytest.approx(
        math.sqrt(A) * float(np.mean(active)) / spread, rel=REL, abs=ABS
    )


def test_m03_exposure_without_alpha_still_has_an_active_return() -> None:
    x = X + 0.003  # the benchmark earns more than the risk-free rate on average
    result = stats(RF_SESSION + 1.5 * x, RF_SESSION + x)
    assert result.beta == pytest.approx(1.5, rel=REL, abs=ABS)
    assert result.alpha_per_session == pytest.approx(0.0, abs=1e-12)
    assert result.active_return_annualised == pytest.approx(A * 0.5 * 0.003, rel=REL, abs=ABS)


def test_m04_a_negative_beta_is_a_valid_answer() -> None:
    result = stats(RF_SESSION + 0.0002 - 0.4 * X, RF_SESSION + X)
    assert result.beta == pytest.approx(-0.4, rel=REL, abs=ABS)
    assert result.alpha_per_session == pytest.approx(0.0002, rel=REL, abs=ABS)


def test_m05_the_risk_free_rate_moves_alpha_by_beta_minus_one_and_nothing_else() -> None:
    strategy, benchmark = RF_SESSION + 0.0005 + 1.5 * X + RESIDUALS, RF_SESSION + X
    low = stats(strategy, benchmark, config(rate_per_session=0.0))
    high = stats(strategy, benchmark, config(rate_per_session=0.0002))
    assert high.beta == pytest.approx(low.beta, rel=REL, abs=ABS)
    assert high.information_ratio == pytest.approx(low.information_ratio, rel=REL, abs=ABS)
    assert high.tracking_error_annualised == pytest.approx(
        low.tracking_error_annualised, rel=REL, abs=ABS
    )
    assert high.active_return_annualised == pytest.approx(
        low.active_return_annualised, rel=REL, abs=ABS
    )
    assert low.alpha_per_session is not None and high.alpha_per_session is not None
    assert low.beta is not None
    assert high.alpha_per_session - low.alpha_per_session == pytest.approx(
        (low.beta - 1.0) * 0.0002, rel=REL, abs=ABS
    )


def test_m06_alpha_scales_with_a_and_the_ratios_with_its_root() -> None:
    strategy, benchmark = 0.0005 + 1.5 * X + RESIDUALS, X
    daily = stats(strategy, benchmark, config(rate_per_session=0.0, per_year=252))
    other = stats(strategy, benchmark, config(rate_per_session=0.0, per_year=255))
    assert other.beta == pytest.approx(daily.beta, rel=REL, abs=ABS)
    assert other.alpha_per_session == pytest.approx(daily.alpha_per_session, rel=REL, abs=ABS)
    assert daily.alpha_annualised is not None and other.alpha_annualised is not None
    assert other.alpha_annualised / daily.alpha_annualised == pytest.approx(255 / 252)
    assert daily.tracking_error_annualised is not None
    assert other.tracking_error_annualised is not None
    assert other.tracking_error_annualised / daily.tracking_error_annualised == pytest.approx(
        math.sqrt(255 / 252)
    )
    assert daily.information_ratio is not None and other.information_ratio is not None
    assert other.information_ratio / daily.information_ratio == pytest.approx(math.sqrt(255 / 252))


def test_m07_the_tracking_error_divides_by_n_minus_one() -> None:
    benchmark = np.array([0.01, -0.01, 0.02])
    strategy = benchmark + np.array([0.001, 0.003, 0.002])
    result = stats(strategy, benchmark)
    # Active returns 0.001, 0.003, 0.002: mean 0.002, squares 1e-6 + 1e-6 + 0 over 2.
    assert result.tracking_error_annualised == pytest.approx(
        math.sqrt(A) * math.sqrt(1e-6), rel=REL, abs=ABS
    )
    assert result.information_ratio == pytest.approx(math.sqrt(A) * 0.002 / 0.001, rel=REL, abs=ABS)


def test_m08_scaling_either_curve_changes_nothing() -> None:
    strategy, benchmark = RF_SESSION + 0.0005 + 1.5 * X + RESIDUALS, RF_SESSION + X
    reference = stats(strategy, benchmark)
    scaled = RelativePerformanceStats.from_equity(
        wealth(strategy, start=3_000.0), wealth(benchmark, start=7.0), config()
    )
    for name in STATISTICS:
        assert getattr(scaled, name) == pytest.approx(getattr(reference, name), rel=REL, abs=ABS)


def test_m09_the_fit_is_an_ordinary_least_squares_fit() -> None:
    rng = np.random.default_rng(20240101)
    benchmark = rng.normal(0.0003, 0.01, 40)
    strategy = 0.0001 + 0.7 * benchmark + rng.normal(0.0, 0.004, 40)
    result = stats(strategy, benchmark, config(minimum=10))
    assert result.alpha_per_session is not None and result.beta is not None
    x, y = benchmark - RF_SESSION, strategy - RF_SESSION
    residuals = y - result.alpha_per_session - result.beta * x
    assert float(np.mean(residuals)) == pytest.approx(0.0, abs=1e-12)
    assert float(np.sum((x - x.mean()) * residuals)) == pytest.approx(0.0, abs=1e-12)
    # And the same slope as numpy's own fit.
    slope, intercept = np.polyfit(x, y, 1)
    assert result.beta == pytest.approx(slope, rel=REL, abs=ABS)
    assert result.alpha_per_session == pytest.approx(intercept, rel=REL, abs=ABS)


def test_m10_alpha_active_return_and_excess_total_return_are_three_numbers() -> None:
    x = X + 0.004
    strategy = RF_SESSION + 0.0003 + 0.6 * x + RESIDUALS
    benchmark = RF_SESSION + x
    result = stats(strategy, benchmark)
    excess_total = float(np.prod(1 + strategy) - np.prod(1 + benchmark))
    assert result.alpha_annualised is not None and result.active_return_annualised is not None
    assert result.alpha_annualised != pytest.approx(result.active_return_annualised)
    assert result.active_return_annualised == pytest.approx(
        A * float(np.mean(strategy - benchmark)), rel=REL, abs=ABS
    )
    assert result.active_return_annualised != pytest.approx(excess_total)
    assert result.alpha_annualised != pytest.approx((1 + result.alpha_annualised / A) ** A - 1)


# --- D: degenerate samples and bad data -----------------------------------------


def test_d01_a_strategy_identical_to_a_varying_benchmark() -> None:
    result = stats(RF_SESSION + X, RF_SESSION + X)
    assert result.beta == pytest.approx(1.0, rel=REL, abs=ABS)
    assert result.alpha_per_session == pytest.approx(0.0, abs=1e-15)
    assert result.tracking_error_annualised == 0.0
    assert result.information_ratio is None
    assert result.r_squared == pytest.approx(1.0, rel=REL, abs=ABS)
    assert result.diagnostics == (ZERO_TRACKING_ERROR,)


def test_d02_a_constant_active_edge_has_a_mean_and_no_ratio() -> None:
    result = stats(RF_SESSION + X + 0.001, RF_SESSION + X)
    assert result.tracking_error_annualised == 0.0
    assert result.information_ratio is None
    assert result.active_return_annualised == pytest.approx(A * 0.001, rel=REL, abs=ABS)
    assert result.diagnostics == (ZERO_TRACKING_ERROR,)


def test_d03_a_constant_benchmark_has_no_regression_but_an_active_block() -> None:
    result = stats(RF_SESSION + X, np.full(5, 0.001))
    assert (result.alpha_per_session, result.beta, result.r_squared) == (None, None, None)
    assert result.alpha_annualised is None
    assert result.information_ratio is not None
    assert result.tracking_error_annualised is not None and result.tracking_error_annualised > 0
    assert result.diagnostics == (ZERO_BENCHMARK_VARIANCE,)


def test_d04_a_constant_strategy_has_a_zero_beta_and_no_r_squared() -> None:
    result = stats(np.full(5, 0.0003), RF_SESSION + X)
    assert result.beta == pytest.approx(0.0, abs=1e-12)
    assert result.alpha_per_session == pytest.approx(0.0003 - RF_SESSION, rel=REL, abs=ABS)
    assert result.r_squared is None
    assert result.diagnostics == (ZERO_STRATEGY_VARIANCE,)


def test_d05_two_constant_series() -> None:
    result = stats(np.full(5, 0.0003), np.full(5, 0.0001))
    assert (result.alpha_per_session, result.beta, result.r_squared) == (None, None, None)
    assert result.information_ratio is None
    assert result.tracking_error_annualised == 0.0
    assert result.active_return_annualised == pytest.approx(A * 0.0002, rel=REL, abs=ABS)
    assert result.diagnostics == (
        ZERO_BENCHMARK_VARIANCE,
        ZERO_STRATEGY_VARIANCE,
        ZERO_TRACKING_ERROR,
    )


@pytest.mark.parametrize(
    ("minimum", "sessions", "available"),
    [(60, 59, False), (60, 60, True), (2, 2, False), (2, 3, True)],
)
def test_d06_the_sample_size_boundary(minimum: int, sessions: int, available: bool) -> None:
    rng = np.random.default_rng(7)
    benchmark = rng.normal(0.0, 0.01, sessions - 1)
    strategy = 0.5 * benchmark + rng.normal(0.0, 0.005, sessions - 1)
    result = stats(strategy, benchmark, config(minimum=minimum))
    assert result.sessions == sessions and result.observations == sessions - 1
    if available:
        assert all(getattr(result, name) is not None for name in STATISTICS)
        assert result.diagnostics == ()
    else:
        assert all(getattr(result, name) is None for name in STATISTICS)
        assert result.diagnostics == (INSUFFICIENT_OBSERVATIONS,)


def test_d07_an_invalid_value_anywhere_is_refused() -> None:
    good = wealth(RF_SESSION + X)
    for bad_value in (float("nan"), float("inf"), 0.0, -5.0):
        bad = good.copy()
        bad.iloc[0] = bad_value
        with pytest.raises(ValueError):
            RelativePerformanceStats.from_equity(bad, good, config())
    with pytest.raises(ValueError, match="must hold numbers"):
        RelativePerformanceStats.from_equity(good.astype(bool), good, config())


def test_d08_a_duplicated_date_is_refused() -> None:
    good = wealth(RF_SESSION + X)
    days = list(good.index)
    days[2] = days[1]
    bad = pd.Series(good.to_numpy(), index=pd.Index(days, dtype="object"))
    with pytest.raises(ValueError, match="twice"):
        RelativePerformanceStats.from_equity(bad, good, config())


def test_d09_d10_the_period_is_trimmed_at_the_ends_and_never_bridged_inside() -> None:
    strategy, benchmark = wealth(RF_SESSION + 0.0005 + 1.5 * X), wealth(RF_SESSION + X)
    trimmed = RelativePerformanceStats.from_equity(strategy, benchmark.iloc[1:], config())
    assert trimmed.sessions == 5 and trimmed.sample_start == benchmark.index[1]
    holed = benchmark.drop(benchmark.index[3])
    with pytest.raises(ValueError, match="do not hold the same sessions"):
        RelativePerformanceStats.from_equity(strategy, holed, config())
    one_day = RelativePerformanceStats.from_equity(strategy, benchmark.iloc[:1], config())
    assert one_day.observations == 0
    assert one_day.diagnostics == (INSUFFICIENT_OBSERVATIONS,)


@pytest.mark.parametrize(("wobble", "varies"), [(1e-14, False), (1e-9, True)])
def test_d11_the_constant_series_tolerance(wobble: float, varies: bool) -> None:
    # A spread of about 1e-14 is below the 1e-12 tolerance, one of 1e-9 well above.
    benchmark = 0.001 + wobble * np.array([1.0, -1.0, 1.0, -1.0, 1.0])
    result = stats(RF_SESSION + X, benchmark)
    assert (result.beta is not None) is varies
    assert (ZERO_BENCHMARK_VARIANCE in result.diagnostics) is not varies


def test_d12_neither_input_nor_result_can_be_changed_through_the_other() -> None:
    strategy, benchmark = wealth(RF_SESSION + 0.0005 + 1.5 * X), wealth(RF_SESSION + X)
    before = strategy.copy(), benchmark.copy()
    result = RelativePerformanceStats.from_equity(strategy, benchmark, config())
    assert strategy.equals(before[0]) and benchmark.equals(before[1])
    frame = result.as_frame()
    frame.iloc[0, 0] = 99.0
    assert result.as_frame().iloc[0, 0] == pytest.approx(0.0005, rel=REL, abs=ABS)
    with pytest.raises(AttributeError):
        result.beta = 2.0  # type: ignore[misc]


def test_d13_no_return_is_invented_for_the_first_session() -> None:
    result = worked_example()
    assert result.observations == result.sessions - 1
    assert result.sample_start == date(2026, 9, 7)
    assert result.sample_end == date(2026, 9, 12)


def test_an_overflow_is_an_error_and_not_a_number() -> None:
    days = pd.Index([date(2026, 9, 7) + timedelta(days=i) for i in range(4)], dtype="object")
    wild = pd.Series([1e-300, 1e300, 1e-300, 1e300], index=days)
    calm = pd.Series([1.0, 1.01, 1.02, 1.0], index=days)
    with pytest.raises(ValueError, match="numerically"):
        RelativePerformanceStats.from_equity(wild, calm, config())


# --- the frame and the record ---------------------------------------------------


def test_the_frame_lists_the_seven_figures_in_order() -> None:
    frame = worked_example().as_frame()
    assert list(frame.index) == list(STATISTICS)
    assert list(frame.columns) == ["value"]
    assert frame.index.name == "statistic"


def test_the_definition_is_strict_json_with_missing_figures_as_null() -> None:
    result = stats(np.full(5, 0.0003), np.full(5, 0.0001))
    text = json.dumps(result.definition(), allow_nan=False)
    record = json.loads(text)
    assert record["beta"] is None
    assert record["sample_start"] == "2026-09-07"
    assert record["config"] == result.config.definition()
    assert record["return_std_tolerance"] == RETURN_STD_TOLERANCE
    assert record["diagnostics"] == [
        ZERO_BENCHMARK_VARIANCE,
        ZERO_STRATEGY_VARIANCE,
        ZERO_TRACKING_ERROR,
    ]
