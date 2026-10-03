"""Study: a Paris-listed world fund, measured at night and during the session.

Hypothesis ``session_segments`` of ``research/hypotheses.toml``, written before
this script was first run. ``ETF_WORLD`` closes in Paris at 17:35 while New York
trades until 22:00, so the afternoon of Wall Street reaches the fund at the
next Paris open. The study splits every close-to-close return into a **night**
(previous close to open) and a **day** (open to close), and compares three
books: the fund held throughout, held at night only, held during the session
only. From the repository root, once the store is filled:

    uv run python scripts/run_session_segments_study.py --output session_segments_output

It is a measurement, not a backtest: the books are compounded straight from the
stored opens and closes, outside the event loop, at the costs of
``scripts/run_golden_cross_exercise.py``. Nothing is decided and no parameter
is fitted, so there is no decision instant to guard; the store is read as it
was known at ``AS_OF``, a constant, and never at the wall clock.

The discovery window is ``ETF_WORLD`` over the period of the exercises. The
validation window is ``ETF_SP500_PEA`` before that period starts. The ``SP500``
index is not used: from 1990 to 2006 its stored open is the close of the day
before on 44% to 98% of sessions, which makes its night a zero by construction.

The tests are in ``tests/scripts/test_run_session_segments_study.py``.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast

import pandas as pd
from matplotlib.figure import Figure
from run_golden_cross_exercise import (
    EXECUTION,
    FIGURE_DPI,
    HELD_COLOUR,
    INITIAL_CASH,
    PRICE_COLOUR,
    STORE,
)

from quant_backtester.analytics.segments import (
    HOLD,
    SegmentSummary,
    segment_books,
    segment_returns,
    segment_summary,
)
from quant_backtester.data.calendars import CalendarRegistry
from quant_backtester.data.instruments import InstrumentRegistry
from quant_backtester.data.reader import MarketDataReader, PointInTimeReader
from quant_backtester.data.repository import MarketDataRepository
from quant_backtester.data.schemas import BarField

AS_OF = datetime(2026, 10, 3, 0, 0, tzinfo=UTC)
"""The instant the store is read at: every bar and action known by then, none after."""

CALENDAR = "XPAR"
"""Both funds trade in Paris: the expected sessions are those of Euronext Paris."""

COST_RATE = EXECUTION.costs.commission_rate + EXECUTION.costs.drag
"""One leg, as a fraction of the amount traded: 5 + 2 + 1 = 8 basis points.

The minimum commission of 1 EUR is left out: on a book of 100 000 EUR the rate
is fifty times above it.
"""

ZOOM_SESSIONS = 30
"""Sessions drawn on the figure that marks every trade of the night book."""

SELL_COLOUR, NIGHT_COLOUR, DAY_COLOUR = "#c53030", "#1f4e79", "#c05621"


@dataclass(frozen=True, slots=True)
class Window:
    """One instrument over one period, and what the study uses it for."""

    role: str
    instrument_id: str
    start: date
    end: date


WINDOWS = (
    Window("discovery", "ETF_WORLD", date(2019, 4, 1), date(2026, 9, 17)),
    Window("validation", "ETF_SP500_PEA", date(2014, 3, 18), date(2019, 3, 29)),
    Window("control", "ETF_SP500_PEA", date(2019, 4, 1), date(2026, 9, 17)),
)
"""The discovery window, the one it never saw, and the same period on the other fund."""


def build_reader(root: Path) -> PointInTimeReader:
    """Return the store under ``root`` as it was known at :data:`AS_OF`."""
    reader = MarketDataReader(
        repository=MarketDataRepository(root),
        instruments=InstrumentRegistry.from_toml(root / "metadata" / "instruments.toml"),
        calendars=CalendarRegistry.from_directory(root / "metadata" / "calendars"),
        reference_calendar_id=CALENDAR,
    )
    return reader.at(AS_OF)


def window_prices(reader: PointInTimeReader, window: Window) -> pd.DataFrame:
    """Return the raw open, raw close and adjusted close of a window.

    Returns
    -------
    pd.DataFrame
        Columns ``open``, ``close`` and ``adjusted``, one row per session the
        store serves all three for, indexed by session date.
    """
    bounds = {"start": window.start, "end": window.end}
    frame = pd.DataFrame(
        {
            "open": reader.history(window.instrument_id, BarField.OPEN, **bounds),
            "close": reader.history(window.instrument_id, BarField.CLOSE, **bounds),
            "adjusted": reader.adjusted_history(window.instrument_id, **bounds),
        }
    )
    return frame.dropna()


def segments_figure(
    prices: pd.DataFrame, books: pd.DataFrame, *, initial: float, title: str, trades: bool
) -> Figure:
    """Draw the price of the fund above the profit of the three books.

    Parameters
    ----------
    prices : pd.DataFrame
        Columns ``open`` and ``close``, indexed by session date.
    books : pd.DataFrame
        The result of ``segment_books`` over the same sessions.
    initial : float
        Capital the books started from: the profit drawn is a book less it.
    title : str
        What the figure shows.
    trades : bool
        Whether every trade of the night book is marked on the price: a green
        cross on each close, where it buys, and a red cross on each open, where
        it sells. Readable on a few weeks, a solid band on several years.

    Returns
    -------
    Figure
        Two panels on one time axis: the close, then the profit and loss of
        holding, of the night book and of the day book, net of costs in full
        lines and gross in dotted ones.

    Raises
    ------
    ValueError
        If ``books`` holds no session.
    """
    if len(books) == 0:
        raise ValueError("there is nothing to draw: the books hold no session")
    days = list(books.index)
    figure = Figure(figsize=(11, 7.5), layout="constrained")
    price_axes, pnl_axes = figure.subplots(2, 1, sharex=True)
    closes = [float(prices.loc[day, "close"]) for day in days]
    price_axes.plot(days, closes, color=PRICE_COLOUR, linewidth=1.0, label="close")
    if trades:
        opens = [float(prices.loc[day, "open"]) for day in days]
        crosses = {"s": 60, "linewidths": 1.8, "zorder": 3, "marker": "x"}
        price_axes.scatter(days, closes, color=HELD_COLOUR, label="buy at the close", **crosses)
        price_axes.scatter(days, opens, color=SELL_COLOUR, label="sell at the open", **crosses)
    price_axes.set_title(title)
    price_axes.set_ylabel("price")
    curves = (
        (HOLD, PRICE_COLOUR, "-", "held throughout"),
        ("night_gross", NIGHT_COLOUR, ":", "night only, gross"),
        ("night_net", NIGHT_COLOUR, "-", "night only, net"),
        ("day_gross", DAY_COLOUR, ":", "session only, gross"),
        ("day_net", DAY_COLOUR, "-", "session only, net"),
    )
    for column, colour, style, label in curves:
        profit = [float(value) - initial for value in books[column]]
        pnl_axes.plot(days, profit, color=colour, linestyle=style, linewidth=1.4, label=label)
    pnl_axes.axhline(0.0, color=PRICE_COLOUR, linewidth=0.6)
    pnl_axes.set_ylabel("profit and loss")
    for axes in (price_axes, pnl_axes):
        axes.grid(visible=True, alpha=0.25)
    price_axes.legend(loc="best", frameon=False)
    pnl_axes.legend(loc="lower left", ncols=3, frameon=False, bbox_to_anchor=(0.0, 1.0))
    return figure


def print_window(
    window: Window, expected: int, summary: SegmentSummary, books: pd.DataFrame
) -> None:
    """Print what a window measured: the two segments, then the five books."""
    print(f"\n{window.role}: {window.instrument_id}  {window.start} to {window.end}")
    print(f"  sessions served        {summary.sessions} of {expected} expected")
    print(f"  night log return       {summary.night_log_return:+.4f}")
    print(f"  session log return     {summary.day_log_return:+.4f}")
    share = "n/a" if summary.night_share is None else f"{summary.night_share:.1%}"
    t_value = "n/a" if summary.difference_t is None else f"{summary.difference_t:+.2f}"
    print(f"  share of the night     {share}")
    print(f"  t of night - session   {t_value}")
    if len(books):
        for column in books.columns:
            profit = float(books[column].iloc[-1]) - INITIAL_CASH
            print(f"  {column:<12} profit   {profit:>+14,.0f}  ({profit / INITIAL_CASH:+.1%})")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the study on every window, print it and save its figures."""
    parser = argparse.ArgumentParser(description="Run the session segments study.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("session_segments_output"),
        help="where the figures are written",
    )
    arguments = parser.parse_args(argv)
    arguments.output.mkdir(parents=True, exist_ok=True)

    reader = build_reader(STORE)
    calendar = CalendarRegistry.from_directory(STORE / "metadata" / "calendars").get(CALENDAR)
    print(f"cost per leg: {COST_RATE:.4%} of the amount traded, capital {INITIAL_CASH:,.0f}")
    for window in WINDOWS:
        prices = window_prices(reader, window)
        sessions = [session.session_date for session in calendar.sessions(window.start, window.end)]
        returns = segment_returns(
            cast(pd.Series, prices["open"]),
            cast(pd.Series, prices["close"]),
            cast(pd.Series, prices["adjusted"]),
            sessions,
        )
        books = segment_books(returns, initial=INITIAL_CASH, cost_rate=COST_RATE)
        print_window(window, len(sessions), segment_summary(returns), books)
        name = f"{window.role}_{window.instrument_id}"
        label = f"{window.instrument_id}  night against session"
        figure = segments_figure(
            prices,
            books,
            initial=INITIAL_CASH,
            title=f"{label}  {window.start} to {window.end}",
            trades=False,
        )
        figure.savefig(arguments.output / f"{name}.png", dpi=FIGURE_DPI)
        recent = returns.tail(ZOOM_SESSIONS)
        figure = segments_figure(
            prices,
            segment_books(recent, initial=INITIAL_CASH, cost_rate=COST_RATE),
            initial=INITIAL_CASH,
            title=f"{label}  last {len(recent)} sessions, every trade of the night book",
            trades=True,
        )
        figure.savefig(arguments.output / f"{name}_trades.png", dpi=FIGURE_DPI)
    print(f"\nFigures written to {arguments.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
