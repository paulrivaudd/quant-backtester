"""What a curve is worth, and what it put its holder through to get there.

Every figure here is a function of an equity curve and of the conventions in
:class:`~quant_backtester.analytics.config.AnalyticsConfig`. None of them reads
market data, and none of them can see past the session it is computed at.

A statistic that cannot be computed honestly is ``None`` rather than a number.
A volatility needs two returns, an annualised figure needs a run long enough
for compounding to mean something, and a Sharpe ratio needs a volatility that
is not zero. Returning ``0.0``, ``nan`` or an infinity for those would put a
number in a report that nobody could defend.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

import pandas as pd

from quant_backtester.analytics.config import AnalyticsConfig
from quant_backtester.analytics.curves import drawdown_curve, elapsed_years, session_returns


@dataclass(frozen=True, slots=True)
class Drawdown:
    """The worst fall from a past high the curve went through.

    Attributes
    ----------
    depth : float
        How far below the peak, as a negative fraction. Zero for a curve that
        never fell, which is a fact and not a missing value.
    peak_date : date | None
        The session of the high the fall started from.
    trough_date : date | None
        The session the fall reached its worst.
    recovery_date : date | None
        The first session back at or above the peak, or ``None`` if the run
        ended under water. The distinction matters: a twenty percent fall that
        took two years to come back is a different strategy from one that came
        back in a month, and the depth alone tells them apart not at all.
    """

    depth: float
    peak_date: date | None
    trough_date: date | None
    recovery_date: date | None

    @property
    def recovered(self) -> bool:
        """Return whether the curve climbed back to its peak before the run ended."""
        return self.recovery_date is not None


@dataclass(frozen=True, slots=True)
class PerformanceStats:
    """One book's record over a run.

    Attributes
    ----------
    sessions : int
        Sessions the curve covers.
    years : float
        Calendar time between the first and the last of them.
    total_return : float
        Growth from the first session to the last, as a fraction.
    annualised_return : float | None
        The rate that, compounded over ``years``, gives ``total_return``.
        ``None`` for a run shorter than the configured minimum.
    annualised_volatility : float | None
        Standard deviation of the session returns, scaled by the configured
        sessions a year. ``None`` when there are fewer than two returns.
    sharpe_ratio : float | None
        Mean excess return over its own standard deviation, annualised.
        ``None`` when the volatility is zero or the run is too short.
    drawdown : Drawdown
        The worst fall from a past high.
    best_session : float | None
        The largest single-session return, and the smallest in
        ``worst_session``. Cheap to compute and the first thing to look at
        when a Sharpe ratio looks too good: one session doing all the work is
        a data problem until proven otherwise.
    worst_session : float | None
        See ``best_session``.
    """

    sessions: int
    years: float
    total_return: float
    annualised_return: float | None
    annualised_volatility: float | None
    sharpe_ratio: float | None
    drawdown: Drawdown
    best_session: float | None
    worst_session: float | None

    @classmethod
    def from_equity(cls, equity: pd.Series, config: AnalyticsConfig) -> PerformanceStats:
        """Compute every statistic of one curve.

        Parameters
        ----------
        equity : pd.Series
            An equity curve indexed by session date, in order.
        config : AnalyticsConfig
            The annualisation convention and the rate to compare against.

        Returns
        -------
        PerformanceStats
            The run's record, with ``None`` wherever the curve does not support
            a figure.

        Raises
        ------
        ValueError
            If the curve holds a value at or below zero.
        """
        sessions = len(equity)
        years = elapsed_years(equity.index)
        returns = session_returns(equity)
        total = float(equity.iloc[-1] / equity.iloc[0] - 1.0) if sessions else 0.0
        long_enough = sessions >= config.minimum_sessions and years > 0.0
        volatility = _annualised_volatility(returns, config)
        return cls(
            sessions=sessions,
            years=years,
            total_return=total,
            annualised_return=_annualised_return(total, years) if long_enough else None,
            annualised_volatility=volatility,
            sharpe_ratio=_sharpe_ratio(returns, config) if long_enough else None,
            drawdown=max_drawdown(equity),
            best_session=float(returns.to_numpy().max()) if not returns.empty else None,
            worst_session=float(returns.to_numpy().min()) if not returns.empty else None,
        )


def _annualised_return(total_return: float, years: float) -> float:
    """Return the constant yearly rate that compounds to ``total_return``."""
    return (1.0 + total_return) ** (1.0 / years) - 1.0


def _annualised_volatility(returns: pd.Series, config: AnalyticsConfig) -> float | None:
    """Return the session returns' spread, scaled to a year.

    Notes
    -----
    The sample standard deviation, so a run of two sessions has one degree of
    freedom rather than a spread of zero it did not earn.
    """
    if len(returns) < 2:
        return None
    # Through numpy: a pandas reduction is typed as possibly returning a
    # Series, and the spread of a series of returns is one number.
    return float(returns.to_numpy().std(ddof=1)) * math.sqrt(config.sessions_per_year)


def _sharpe_ratio(returns: pd.Series, config: AnalyticsConfig) -> float | None:
    """Return the annualised ratio of excess return to its own spread.

    Notes
    -----
    Computed on the session excess returns, not on the annualised figures
    above: the numerator is then the arithmetic mean of what the strategy
    actually earned over the rate, and the denominator is the spread of those
    same numbers. Mixing a compounded return with a per-session spread is a
    common way of publishing a ratio the data does not support.
    """
    if len(returns) < 2:
        return None
    excess = (returns - config.risk_free_per_session).to_numpy()
    spread = float(excess.std(ddof=1))
    if spread == 0.0:
        return None
    return float(excess.mean()) / spread * math.sqrt(config.sessions_per_year)


def max_drawdown(equity: pd.Series) -> Drawdown:
    """Return the worst fall from a past high, and when it happened.

    Parameters
    ----------
    equity : pd.Series
        An equity curve indexed by session date, in order.

    Returns
    -------
    Drawdown
        Its depth, the peak it fell from, the trough, and the session it came
        back at - ``None`` there when the run ended before it did.

    Notes
    -----
    The peak is the running maximum, so the trough of a fall is found among
    the sessions that had already happened. Nothing here looks forward except
    the recovery date, which is a statement about the run being over and is
    reported as such.
    """
    if equity.empty:
        return Drawdown(depth=0.0, peak_date=None, trough_date=None, recovery_date=None)
    drawdown = drawdown_curve(equity)
    trough_position = int(drawdown.to_numpy().argmin())
    depth = float(drawdown.iloc[trough_position])
    if depth == 0.0:
        return Drawdown(depth=0.0, peak_date=None, trough_date=None, recovery_date=None)
    before_trough = equity.iloc[: trough_position + 1]
    peak_position = int(before_trough.to_numpy().argmax())
    peak = float(before_trough.iloc[peak_position])
    after = equity.iloc[trough_position + 1 :]
    recovered = after[after >= peak]
    return Drawdown(
        depth=depth,
        peak_date=_session_at(equity, peak_position),
        trough_date=_session_at(equity, trough_position),
        recovery_date=_session_at(recovered, 0) if not recovered.empty else None,
    )


def _session_at(series: pd.Series, position: int) -> date:
    """Return the session date at one position of a curve."""
    session = series.index[position]
    if not isinstance(session, date):
        raise ValueError(f"an equity curve is indexed by session dates, got {session!r}")
    return session
