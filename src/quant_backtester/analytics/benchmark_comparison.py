"""A strategy's alpha against a benchmark run, from the two equity curves.

A thin reading of :mod:`quant_backtester.analytics.relative`, which holds the
regression: nothing is computed twice here. What this adds is the one figure
the regression does not carry - the plain difference of total returns - and a
result small enough to print beside a run.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from quant_backtester.analytics.config import AnalyticsConfig
from quant_backtester.analytics.curves import aligned_equity_curves
from quant_backtester.analytics.relative import RelativePerformanceStats


@dataclass(frozen=True, slots=True)
class BenchmarkAlpha:
    """Beta and alpha of a strategy against a benchmark, and how much more it made.

    Attributes
    ----------
    beta : float | None
        Sensitivity of the strategy's session returns to the benchmark's.
    alpha_annualised : float | None
        ``A * (mean(R_s) - beta * mean(R_b))`` on excess returns, a fraction
        per year. An arithmetic scaling of the regression's intercept, not a
        difference of compounded returns.
    observations : int
        Pairs of session returns the two figures are computed on.
    outperformance : float
        Total return of the strategy less total return of the benchmark over
        the aligned sample, a fraction. Not an alpha: it is not adjusted for
        the exposure to the benchmark.
    diagnostics : tuple[str, ...]
        Why a figure is ``None``, as the stable codes of
        :mod:`~quant_backtester.analytics.relative`.
    relative : RelativePerformanceStats
        The full regression the figures are read from.
    """

    beta: float | None
    alpha_annualised: float | None
    observations: int
    outperformance: float
    diagnostics: tuple[str, ...]
    relative: RelativePerformanceStats


def alpha_vs_benchmark(
    strategy_equity: pd.Series,  # type: ignore[type-arg]
    benchmark_equity: pd.Series,  # type: ignore[type-arg]
    config: AnalyticsConfig,
) -> BenchmarkAlpha:
    """Measure a strategy's net equity curve against a benchmark's.

    Parameters
    ----------
    strategy_equity : pd.Series
        The strategy's worth, session by session, indexed by date - the net
        curve of its run.
    benchmark_equity : pd.Series
        The benchmark's worth over the same sessions, from a run of the same
        engine with the same costs. Sessions on which it sat in cash are part
        of the sample: their return is zero.
    config : AnalyticsConfig
        Sessions per year, the risk-free rate and the smallest sample the
        figures are reported on. Declared, never defaulted.

    Returns
    -------
    BenchmarkAlpha
        ``R_s = alpha + beta * R_b + e`` on simple session returns in excess of
        the risk-free rate. A figure the sample cannot identify - too few
        sessions, a benchmark whose returns do not vary - is ``None``, with
        the reason in ``diagnostics``.

    Raises
    ------
    ValueError
        If a curve is invalid or the two do not hold the same sessions over
        the span they share: nothing is filled, and a return across a missing
        session is not counted as one session.

    Notes
    -----
    A positive alpha against one benchmark depends on that benchmark and on
    the sample. A benchmark measured against itself gives ``beta = 1`` and
    ``alpha = 0`` whenever its returns vary.
    """
    relative = RelativePerformanceStats.from_equity(strategy_equity, benchmark_equity, config)
    strategy, benchmark = aligned_equity_curves(strategy_equity, benchmark_equity)
    outperformance = float(strategy.iloc[-1] / strategy.iloc[0]) - float(
        benchmark.iloc[-1] / benchmark.iloc[0]
    )
    return BenchmarkAlpha(
        beta=relative.beta,
        alpha_annualised=relative.alpha_annualised,
        observations=relative.observations,
        outperformance=outperformance,
        diagnostics=relative.diagnostics,
        relative=relative,
    )
