"""The three series every performance figure below is computed from.

A run is a list of records; a statistic is a function of a curve. Keeping the
two apart means the statistics can be tested on a curve written by hand, and
that they can be applied to something a backtest did not produce - a benchmark,
a single instrument, a book kept elsewhere.

The drawdown curve is the one worth being careful about: its peak is the
highest equity **seen so far**, never the highest of the run. A drawdown
measured against a peak that has not happened yet is not a drawdown an investor
could have lived through, and a report full of them would flatter every
strategy that ends well.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from itertools import pairwise

import numpy as np
import pandas as pd

from quant_backtester.backtest.result import BacktestResult


class Book(Enum):
    """Which of the two books a curve is taken from."""

    NET = "NET"
    """What the strategy was actually worth, costs paid."""

    GROSS = "GROSS"
    """What the same trades would have been worth having paid the market price
    and no fee. The difference between the two curves is everything execution
    took."""


def equity_curve(result: BacktestResult, book: Book) -> pd.Series:
    """Return one book's worth, session by session.

    Parameters
    ----------
    result : BacktestResult
        A finished run. Nothing here advances time or reads market data: the
        equity was valued by the engine at each session's valuation instant, and
        this only lines the numbers up.
    book : Book
        Which book to read. Required rather than defaulted: a gross number read
        as a net one is the single easiest mistake to make in a report.

    Returns
    -------
    pd.Series
        Indexed by session date, in the order the run walked them, named after
        the book. Empty when the run holds no session.

    Raises
    ------
    ValueError
        If ``book`` is not a :class:`Book`. Checked with ``isinstance`` and not
        with ``in``: since Python 3.12 the string ``"NET"`` is *in* the
        enumeration while it is not ``Book.NET``, so the membership test would
        wave it through and the line below would then hand back the gross
        curve under a net name.
    """
    if not isinstance(book, Book):
        raise ValueError(f"book must be a Book, got {book!r}")
    values = [
        record.net_equity if book is Book.NET else record.gross_equity for record in result.records
    ]
    index = pd.Index(
        [record.session_date for record in result.records], dtype="object", name="session_date"
    )
    return pd.Series(values, index=index, dtype="float64", name=book.value.lower())


def session_returns(equity: pd.Series) -> pd.Series:
    """Return the simple return of each session against the one before it.

    Parameters
    ----------
    equity : pd.Series
        An equity curve, indexed by session date.

    Returns
    -------
    pd.Series
        One value fewer than the curve: the first session has nothing to be
        compared against, and is left out rather than reported as a zero that
        would drag a volatility down.

    Raises
    ------
    ValueError
        If the curve holds a value that is not strictly positive. A book worth
        nothing is not a percentage change; it is a run that should be looked
        at rather than summarised.
    """
    if equity.empty:
        return pd.Series(dtype="float64", index=equity.index[:0], name="return")
    if (equity <= 0).any():
        raise ValueError("an equity curve at or below zero cannot be turned into returns")
    return (equity / equity.shift(1) - 1.0).iloc[1:].rename("return")


def aligned_equity_curves(
    strategy: pd.Series,  # type: ignore[type-arg]
    benchmark: pd.Series,  # type: ignore[type-arg]
) -> tuple[pd.Series, pd.Series]:  # type: ignore[type-arg]
    """Return two curves on one period, with no session missing on either side.

    Parameters
    ----------
    strategy, benchmark : pd.Series
        Equity curves in one currency, indexed by session date. Every value is
        checked, including those outside the period kept: an invalid value is
        refused wherever it sits rather than hidden by a restriction.

    Returns
    -------
    tuple[pd.Series, pd.Series]
        Copies of both curves restricted to the span from the first to the
        last date they share, bounds included. Inside that span both hold
        exactly the same sessions, in the same order. Nothing is sorted,
        interpolated, filled or dropped.

    Raises
    ------
    ValueError
        If a curve is not a numeric series, holds a boolean, a value that is
        not finite or not strictly positive; if its index holds anything but
        ``datetime.date`` (a ``datetime`` or a ``Timestamp`` included: the
        caller converts explicitly), a duplicate, or dates out of order; if
        the two share no date; or if, inside the shared span, a session is on
        one side only.

    Notes
    -----
    An intersection of the two indexes is not enough. A curve without Tuesday
    intersected with one that has it yields a Monday-to-Wednesday return,
    counted and annualised as one session. Trimming the ends is allowed - a
    Monday-to-Friday curve and a Tuesday-to-Friday one are compared from
    Tuesday - and a hole inside is refused.

    Two curves missing the very same session cannot be told apart from two
    curves on a calendar without it: that check needs the run's own sessions,
    and :meth:`PerformanceReport.of` makes it. A caller passing bare series
    promises that each holds every session of its calendar.
    """
    for name, curve in (("strategy", strategy), ("benchmark", benchmark)):
        _require_equity_curve(curve, name)
    shared = set(strategy.index) & set(benchmark.index)
    if not shared:
        raise ValueError("the strategy and the benchmark share no session")
    first, last = min(shared), max(shared)
    left = [day for day in strategy.index if first <= day <= last]
    right = [day for day in benchmark.index if first <= day <= last]
    if left != right:
        only_left = [day for day in left if day not in shared][:3]
        only_right = [day for day in right if day not in shared][:3]
        raise ValueError(
            f"between {first} and {last} the two curves do not hold the same sessions: "
            f"strategy only {[str(day) for day in only_left]}, "
            f"benchmark only {[str(day) for day in only_right]}. A return across a missing "
            "session would be counted as one session."
        )
    keep_left = [first <= day <= last for day in strategy.index]
    keep_right = [first <= day <= last for day in benchmark.index]
    return strategy.loc[keep_left].copy(), benchmark.loc[keep_right].copy()


def _require_equity_curve(curve: object, name: str) -> None:
    """Raise unless ``curve`` is a valid equity curve indexed by session dates."""
    if not isinstance(curve, pd.Series):
        raise ValueError(f"the {name} curve must be a pandas Series, got {type(curve).__name__}")
    if pd.api.types.is_bool_dtype(curve.dtype) or not pd.api.types.is_numeric_dtype(curve.dtype):
        raise ValueError(f"the {name} curve must hold numbers, got dtype {curve.dtype}")
    values = curve.to_numpy(dtype="float64")
    if not np.isfinite(values).all():
        raise ValueError(f"the {name} curve holds a value that is not finite")
    if (values <= 0.0).any():
        raise ValueError(f"the {name} curve holds a value at or below zero")
    days = list(curve.index)
    for day in days:
        if type(day) is not date:
            raise ValueError(
                f"the {name} curve is indexed by datetime.date, got {type(day).__name__} {day!r}"
            )
    for before, after in pairwise(days):
        if after == before:
            raise ValueError(f"the {name} curve holds {after} twice")
        if after < before:
            raise ValueError(f"the {name} curve is out of order: {after} after {before}")


def drawdown_curve(equity: pd.Series) -> pd.Series:
    """Return how far below its own past peak the book is at each session.

    Parameters
    ----------
    equity : pd.Series
        An equity curve, indexed by session date.

    Returns
    -------
    pd.Series
        Zero at a new high and negative below it, as a fraction of the peak.
        The peak is the running maximum, so the value at a session depends only
        on the sessions up to it: appending a later one never changes it.
    """
    if equity.empty:
        return pd.Series(dtype="float64", index=equity.index[:0], name="drawdown")
    peak = equity.cummax()
    return (equity / peak - 1.0).rename("drawdown")


def elapsed_years(sessions: pd.Index) -> float:
    """Return the calendar time a run covered, in years.

    Parameters
    ----------
    sessions : pd.Index
        The session dates of a curve, in order.

    Returns
    -------
    float
        Days between the first and the last session over ``365.25``, and zero
        for a run of one session. Calendar time, not sessions counted: a year
        of a strategy that trades twice a week is still a year, and an investor
        waited it.
    """
    if len(sessions) < 2:
        return 0.0
    first, last = sessions[0], sessions[-1]
    if not isinstance(first, date) or not isinstance(last, date):
        raise ValueError("an equity curve is indexed by session dates")
    return (last - first).days / 365.25
