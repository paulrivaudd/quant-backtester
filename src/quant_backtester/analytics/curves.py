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

import pandas as pd

from quant_backtester.backtest.engine import BacktestResult


class Book(Enum):
    """Which of the two books a curve is taken from."""

    NET = "NET"
    """What the strategy was actually worth, costs paid."""

    GROSS = "GROSS"
    """What the same trades would have been worth having paid the reference
    price and no fee. The difference between the two curves is everything
    execution took."""


def equity_curve(result: BacktestResult, book: Book) -> pd.Series:
    """Return one book's worth, session by session.

    Parameters
    ----------
    result : BacktestResult
        A finished run. Nothing here advances time or reads market data: the
        equity was valued by the engine at each session's decision instant, and
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
        record.equity if book is Book.NET else record.gross_equity for record in result.records
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
