"""A strategy measured against its benchmark: alpha, beta and information ratio.

These figures need two curves, and they describe a finished run. They are not
indicators a strategy decides on, and nothing here reads the market, an order
or a book: two equity curves and an :class:`AnalyticsConfig` go in, numbers
come out.

Everything is computed on simple per-session returns of two curves aligned by
:func:`~quant_backtester.analytics.curves.aligned_equity_curves`, with the
convention the rest of the layer uses: ``A = config.sessions_per_year`` and
``r_f = config.risk_free_per_session``, the annual rate compounded down to a
session.

- **Beta and alpha** come from the ordinary least squares fit, with a constant,
  of the strategy's excess return on the benchmark's:
  ``r_s - r_f = alpha + beta (r_b - r_f) + e``. Alpha is annualised by
  multiplying by ``A`` - a scaling of a coefficient, not a compounded return.
  Against a benchmark other than the market, it is a regression alpha against
  that benchmark, not Jensen's alpha.
- **Active return** is ``a = r_s - r_b``, session by session. Annualised as
  ``A * mean(a)``; its **tracking error** is ``sqrt(A) * std(a, ddof=1)``; the
  **information ratio** is their quotient. The risk-free rate cancels out of
  all three.
- **R squared** is the share of the strategy's excess-return variance the fit
  explains: a diagnostic of the regression, not a score.

Scaling by ``sqrt(A)`` is exact for uncorrelated returns of equal variance and
only a convention otherwise; a historical estimate is not a forecast.

A figure the sample cannot identify is ``None`` with a stable diagnostic code
naming why, never ``0`` or an infinity. A curve too short for the declared
``minimum_sessions`` gives every figure ``None``.

Not the same as ``Comparison.excess_return`` (total return of one less total
return of the other), nor as a difference of Sharpe ratios: the four measure
different things and none stands in for another.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields
from datetime import date
from typing import Final

import numpy as np
import pandas as pd

from quant_backtester.analytics.config import AnalyticsConfig
from quant_backtester.analytics.curves import aligned_equity_curves, session_returns

RETURN_STD_TOLERANCE: Final[float] = 1e-12
"""Per-session standard deviation, as a fraction, at or below which a series is
treated as constant.

A beta over a benchmark whose returns vary by rounding error alone, or a ratio
over a tracking error of that size, is a number made of noise; this is where
the line is drawn, and it is recorded in :meth:`RelativePerformanceStats.definition`.
Not ``numpy.isclose``'s default, which is a tolerance on values and not on a
spread of daily returns."""

R_SQUARED_ROUNDING: Final[float] = 1e-12
"""How far outside ``[0, 1]`` an R squared may fall to rounding and still be
brought back inside. Further out is a numerical failure, and raises."""

INSUFFICIENT_OBSERVATIONS: Final[str] = "insufficient_observations"
"""Fewer sessions than ``minimum_sessions``, or fewer than two returns."""

ZERO_BENCHMARK_VARIANCE: Final[str] = "zero_benchmark_variance"
"""The benchmark's excess returns do not vary: no slope can be fitted."""

ZERO_STRATEGY_VARIANCE: Final[str] = "zero_strategy_variance"
"""The strategy's excess returns do not vary: there is nothing for R squared to explain."""

ZERO_TRACKING_ERROR: Final[str] = "zero_tracking_error"
"""The active return does not vary: the information ratio has no denominator."""

STATISTICS: Final[tuple[str, ...]] = (
    "alpha_per_session",
    "alpha_annualised",
    "beta",
    "active_return_annualised",
    "tracking_error_annualised",
    "information_ratio",
    "r_squared",
)
"""The seven figures, in the order every frame lists them."""


@dataclass(frozen=True, slots=True)
class RelativePerformanceStats:
    """How a strategy moved with its benchmark, and what it earned beyond it.

    Attributes
    ----------
    sample_start, sample_end : date
        First and last valuation of the aligned sample.
    sessions : int
        ``N``, valuations in the sample.
    observations : int
        ``n = N - 1``, pairs of returns the figures are computed on.
    config : AnalyticsConfig
        The annualisation and the risk-free rate used.
    alpha_per_session : float | None
        Intercept of the fit, a fraction per session.
    alpha_annualised : float | None
        ``A * alpha_per_session``, a fraction per year.
    beta : float | None
        Slope of the fit, a plain number. Negative is allowed.
    active_return_annualised : float | None
        ``A * mean(r_s - r_b)``, a fraction per year.
    tracking_error_annualised : float | None
        ``sqrt(A) * std(r_s - r_b, ddof=1)``, a fraction per year; exactly
        ``0.0`` when the active return does not vary.
    information_ratio : float | None
        ``active_return_annualised / tracking_error_annualised``, a plain number.
    r_squared : float | None
        Share of the strategy's excess-return variance the fit explains.
    diagnostics : tuple[str, ...]
        Why a figure is ``None``, as stable codes, in the order: sample size,
        benchmark, strategy, tracking error.
    """

    sample_start: date
    sample_end: date
    sessions: int
    observations: int
    config: AnalyticsConfig
    alpha_per_session: float | None
    alpha_annualised: float | None
    beta: float | None
    active_return_annualised: float | None
    tracking_error_annualised: float | None
    information_ratio: float | None
    r_squared: float | None
    diagnostics: tuple[str, ...] = ()

    @classmethod
    def from_equity(
        cls,
        equity: pd.Series,  # type: ignore[type-arg]
        benchmark_equity: pd.Series,  # type: ignore[type-arg]
        config: AnalyticsConfig,
    ) -> RelativePerformanceStats:
        """Measure a strategy's curve against a benchmark's.

        Parameters
        ----------
        equity : pd.Series
            The strategy's worth, session by session, indexed by date.
        benchmark_equity : pd.Series
            The benchmark's worth over the same sessions, in the same currency.
            No conversion is made: a caller holding series in two currencies
            has to convert them first.
        config : AnalyticsConfig
            ``A``, the risk-free rate and the minimum sample size.

        Returns
        -------
        RelativePerformanceStats
            The figures over the aligned sample, ``None`` where the sample
            cannot identify them, with the reason in ``diagnostics``.

        Raises
        ------
        ValueError
            If a curve is invalid or the two cannot be aligned (see
            :func:`aligned_equity_curves`), or if a computation overflows.
        """
        strategy, benchmark = aligned_equity_curves(equity, benchmark_equity)
        sessions = len(strategy)
        observations = sessions - 1
        base = {
            "sample_start": strategy.index[0],
            "sample_end": strategy.index[-1],
            "sessions": sessions,
            "observations": observations,
            "config": config,
        }
        if sessions < config.minimum_sessions or observations < 2:
            return cls(
                **base,  # type: ignore[arg-type]
                **dict.fromkeys(STATISTICS),
                diagnostics=(INSUFFICIENT_OBSERVATIONS,),
            )
        strategy_returns = _returns(strategy)
        benchmark_returns = _returns(benchmark)
        try:
            with np.errstate(all="raise"):
                figures, diagnostics = _figures(strategy_returns, benchmark_returns, config)
        except FloatingPointError as error:
            raise ValueError(f"relative statistics failed numerically: {error}") from None
        for name, value in figures.items():
            if value is not None and not math.isfinite(value):
                raise ValueError(f"relative statistics failed numerically: {name} is {value}")
        return cls(**base, **figures, diagnostics=diagnostics)  # type: ignore[arg-type]

    def as_frame(self) -> pd.DataFrame:
        """Return the seven figures as a one-column frame.

        Returns
        -------
        pd.DataFrame
            Indexed by ``statistic`` in declaration order, one ``value``
            column; a missing figure is ``NaN``. A new frame on every call.
        """
        return pd.DataFrame(
            {"value": [getattr(self, name) for name in STATISTICS]},
            index=pd.Index(list(STATISTICS), dtype="object", name="statistic"),
            dtype="float64",
        )

    def definition(self) -> dict[str, object]:
        """Return everything the figures depend on, serialisable as strict JSON.

        Returns
        -------
        dict[str, object]
            Every field - dates in ISO format, the configuration as its own
            definition, missing figures as ``None`` and diagnostics as a list -
            plus the tolerance a constant series was judged by.
        """
        record: dict[str, object] = {}
        for field in fields(self):
            value = getattr(self, field.name)
            if isinstance(value, date):
                value = value.isoformat()
            elif isinstance(value, AnalyticsConfig):
                value = value.definition()
            elif isinstance(value, tuple):
                value = list(value)
            record[field.name] = value
        record["return_std_tolerance"] = RETURN_STD_TOLERANCE
        return record


def _returns(curve: pd.Series) -> np.ndarray:  # type: ignore[type-arg]
    """Return a curve's simple session returns as float64, refusing an overflow."""
    returns = session_returns(curve).to_numpy(dtype="float64")
    if not np.isfinite(returns).all():
        raise ValueError("relative statistics failed numerically: a session return is not finite")
    return returns


def _figures(
    strategy: np.ndarray,  # type: ignore[type-arg]
    benchmark: np.ndarray,  # type: ignore[type-arg]
    config: AnalyticsConfig,
) -> tuple[dict[str, float | None], tuple[str, ...]]:
    """Return the seven figures of two aligned return series, and the diagnostics.

    Parameters
    ----------
    strategy, benchmark : np.ndarray
        Simple returns of the same sessions, at least two each.
    config : AnalyticsConfig
        ``A`` and the per-session risk-free rate.

    Returns
    -------
    tuple[dict[str, float | None], tuple[str, ...]]
        One entry per name of :data:`STATISTICS`, and the diagnostic codes in
        their stable order.
    """
    per_year = config.sessions_per_year
    risk_free = config.risk_free_per_session
    x = benchmark - risk_free
    y = strategy - risk_free
    x_mean, y_mean = float(np.mean(x)), float(np.mean(y))
    x_centred, y_centred = x - x_mean, y - y_mean
    benchmark_varies = float(np.std(x, ddof=1)) > RETURN_STD_TOLERANCE
    strategy_varies = float(np.std(y, ddof=1)) > RETURN_STD_TOLERANCE

    diagnostics: list[str] = []
    alpha: float | None = None
    beta: float | None = None
    r_squared: float | None = None
    if not benchmark_varies:
        diagnostics.append(ZERO_BENCHMARK_VARIANCE)
    else:
        beta = float(np.sum(x_centred * y_centred) / np.sum(x_centred * x_centred))
        alpha = y_mean - beta * x_mean
    if not strategy_varies:
        diagnostics.append(ZERO_STRATEGY_VARIANCE)
    elif alpha is not None and beta is not None:
        residuals = y - alpha - beta * x
        r_squared = _bounded_r_squared(
            1.0 - float(np.sum(residuals * residuals)) / float(np.sum(y_centred * y_centred))
        )

    active = strategy - benchmark
    active_mean = float(np.mean(active))
    active_spread = float(np.std(active, ddof=1))
    active_return = per_year * active_mean
    tracking_error = 0.0
    information_ratio: float | None = None
    if active_spread <= RETURN_STD_TOLERANCE:
        diagnostics.append(ZERO_TRACKING_ERROR)
    else:
        tracking_error = math.sqrt(per_year) * active_spread
        information_ratio = math.sqrt(per_year) * active_mean / active_spread

    figures: dict[str, float | None] = {
        "alpha_per_session": alpha,
        "alpha_annualised": None if alpha is None else per_year * alpha,
        "beta": beta,
        "active_return_annualised": active_return,
        "tracking_error_annualised": tracking_error,
        "information_ratio": information_ratio,
        "r_squared": r_squared,
    }
    return figures, tuple(diagnostics)


def _bounded_r_squared(value: float) -> float:
    """Return an R squared, brought back into ``[0, 1]`` from a rounding slip only.

    Raises
    ------
    ValueError
        If it falls further outside than :data:`R_SQUARED_ROUNDING`.
    """
    if -R_SQUARED_ROUNDING <= value < 0.0:
        return 0.0
    if 1.0 < value <= 1.0 + R_SQUARED_ROUNDING:
        return 1.0
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"relative statistics failed numerically: R squared is {value}")
    return value


__all__ = [
    "INSUFFICIENT_OBSERVATIONS",
    "RETURN_STD_TOLERANCE",
    "STATISTICS",
    "ZERO_BENCHMARK_VARIANCE",
    "ZERO_STRATEGY_VARIANCE",
    "ZERO_TRACKING_ERROR",
    "RelativePerformanceStats",
]
