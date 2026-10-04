"""alpha_vs_benchmark: a reading of the existing regression, plus the outperformance."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from quant_backtester.analytics.benchmark_comparison import BenchmarkAlpha, alpha_vs_benchmark
from quant_backtester.analytics.config import AnalyticsConfig
from quant_backtester.analytics.relative import (
    INSUFFICIENT_OBSERVATIONS,
    ZERO_BENCHMARK_VARIANCE,
    RelativePerformanceStats,
)

CONFIG = AnalyticsConfig(sessions_per_year=252, risk_free_rate=0.0, minimum_sessions=4)
"""The convention of the comparison: 252 sessions, cash earning nothing."""

BENCHMARK = np.array([0.010, 0.000, -0.020, 0.000, 0.015, 0.005, 0.000, -0.010])
"""The benchmark's session returns; the zeros are sessions it spent in cash."""


def wealth(returns: np.ndarray, start: float = 100.0, first: int = 0) -> pd.Series:
    """Return the curve that earns ``returns``, one session a day."""
    index = pd.Index(
        [date(2026, 9, 7) + timedelta(days=first + i) for i in range(len(returns) + 1)],
        dtype="object",
    )
    return pd.Series(start * np.r_[1.0, np.cumprod(1.0 + returns)], index=index, dtype="float64")


def test_a_strategy_built_from_its_benchmark_gives_back_its_beta_and_alpha() -> None:
    """``R_s = 0.0002 + 0.5 R_b``: beta 0.5 and an annual alpha of 252 * 0.0002."""
    measured = alpha_vs_benchmark(wealth(0.0002 + 0.5 * BENCHMARK), wealth(BENCHMARK), CONFIG)

    assert isinstance(measured, BenchmarkAlpha)
    assert measured.beta == pytest.approx(0.5)
    assert measured.alpha_annualised == pytest.approx(252 * 0.0002)
    assert measured.observations == len(BENCHMARK)
    assert measured.diagnostics == ()


def test_the_figures_are_the_covariance_formulas_of_the_two_return_series() -> None:
    strategy = BENCHMARK[::-1] * 0.7 + 0.3 * BENCHMARK + 0.001
    measured = alpha_vs_benchmark(wealth(strategy), wealth(BENCHMARK), CONFIG)

    beta = np.cov(strategy, BENCHMARK, ddof=1)[0, 1] / np.var(BENCHMARK, ddof=1)
    assert measured.beta == pytest.approx(beta)
    assert measured.alpha_annualised == pytest.approx(
        252 * (strategy.mean() - beta * BENCHMARK.mean())
    )


def test_the_figures_are_read_from_the_existing_regression() -> None:
    strategy, benchmark = wealth(0.001 + 0.8 * BENCHMARK), wealth(BENCHMARK)
    measured = alpha_vs_benchmark(strategy, benchmark, CONFIG)

    assert measured.relative == RelativePerformanceStats.from_equity(strategy, benchmark, CONFIG)
    assert measured.beta == measured.relative.beta
    assert measured.alpha_annualised == measured.relative.alpha_annualised


def test_a_benchmark_against_itself_has_a_beta_of_one_and_no_alpha() -> None:
    measured = alpha_vs_benchmark(wealth(BENCHMARK), wealth(BENCHMARK), CONFIG)

    assert measured.beta == pytest.approx(1.0)
    assert measured.alpha_annualised == pytest.approx(0.0, abs=1e-15)
    assert measured.outperformance == 0.0


def test_the_outperformance_is_the_difference_of_total_returns_not_the_alpha() -> None:
    strategy, benchmark = wealth(2.0 * BENCHMARK, start=50.0), wealth(BENCHMARK)
    measured = alpha_vs_benchmark(strategy, benchmark, CONFIG)

    expected = np.prod(1.0 + 2.0 * BENCHMARK) - np.prod(1.0 + BENCHMARK)
    assert measured.outperformance == pytest.approx(expected)
    assert measured.beta == pytest.approx(2.0)
    assert measured.alpha_annualised == pytest.approx(0.0, abs=1e-12)


def test_a_benchmark_that_never_moved_has_no_beta_and_says_why() -> None:
    measured = alpha_vs_benchmark(wealth(BENCHMARK), wealth(np.zeros(len(BENCHMARK))), CONFIG)

    assert measured.beta is None
    assert measured.alpha_annualised is None
    assert ZERO_BENCHMARK_VARIANCE in measured.diagnostics


def test_too_short_a_sample_has_no_figure_and_says_why() -> None:
    measured = alpha_vs_benchmark(wealth(BENCHMARK[:2]), wealth(BENCHMARK[:2]), CONFIG)

    assert measured.beta is None
    assert measured.diagnostics == (INSUFFICIENT_OBSERVATIONS,)
    assert measured.observations == 2


def test_only_the_shared_span_is_measured() -> None:
    """The benchmark starts two sessions later: the comparison starts with it."""
    strategy = wealth(0.5 * BENCHMARK)
    benchmark = wealth(BENCHMARK[2:], first=2)

    measured = alpha_vs_benchmark(strategy, benchmark, CONFIG)

    assert measured.observations == len(BENCHMARK) - 2
    assert measured.beta == pytest.approx(0.5)


def test_a_session_missing_on_one_side_is_refused_not_filled() -> None:
    strategy, benchmark = wealth(BENCHMARK), wealth(BENCHMARK)

    with pytest.raises(ValueError, match="same sessions"):
        alpha_vs_benchmark(strategy.drop(strategy.index[3]), benchmark, CONFIG)
