"""Study: a trend rule that holds through a panic while bonds still hedge shares.

Hypothesis ``rate_regime_trend`` of ``research/hypotheses.toml``, written with
its parameters before this script was first run. Three books are run over each
window: the fund bought and held, the plain 200-session trend rule
(``MovingAverageBandETF``), and ``RateRegimeTrend``, which is that rule plus
one exception. From the repository root, once the store is filled:

    uv run python scripts/run_rate_regime_study.py --output rate_regime_output

The discovery window is ``ETF_WORLD`` over the period of the exercises, with
the runner of ``scripts/run_golden_cross_exercise.py``. Nothing is fitted on
it: it is a first run, not a calibration.

The validation window is the S&P 500 index from 1991 to 2018, which the first
never saw. **It is a paper run.** An index cannot be bought, and the registry
says so; this script hands the engine a copy of the registry in which
``SP500`` is tradable, in a USD book on the New York calendar, and nothing
else is changed. What that run is worth:

- before 2008 the stored open of the index is the close of the day before on
  most sessions, so an order decided after a close is filled at that close: the
  assumption of a trade at the close, not a price anybody was quoted;
- the index pays no dividend, so neither the fund held nor the benchmark earns
  one, and cash earns no interest: the two omissions pull in opposite
  directions for a rule that is sometimes out, and neither is measured here;
- the costs are those of the exercises, a retail order in a Paris ETF.

The tests are in ``tests/scripts/test_run_rate_regime_study.py``.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, time
from pathlib import Path
from typing import cast

import pandas as pd
from matplotlib.figure import Figure
from run_golden_cross_exercise import (
    ANALYTICS,
    EXECUTION,
    FIGURE_DPI,
    HELD_COLOUR,
    INITIAL_CASH,
    PRICE_COLOUR,
    REPOSITORY,
    SELL_COLOUR,
    SLOW_COLOUR,
    STORE,
    session_date,
)

from quant_backtester.analytics.comparison import BenchmarkBasis, BenchmarkSpec
from quant_backtester.analytics.uncertainty import PairedStatistic, paired_block_bootstrap
from quant_backtester.backtest.runner import StrategyResult, StrategyRunner
from quant_backtester.backtest.timetable import BacktestTimetable
from quant_backtester.data.calendars import CalendarRegistry
from quant_backtester.data.instruments import InstrumentRegistry
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.data.repository import MarketDataRepository
from quant_backtester.provenance import git_source_state
from quant_backtester.strategies import BuyAndHold, MovingAverageBandETF, RateRegimeTrend
from quant_backtester.strategies.base import Strategy

TREND_SESSIONS = 200
"""Length of the average both trend rules read, in sessions."""

EQUITY_ID, RATE_ID, STRESS_ID = "SP500", "US10Y", "VIX"
"""The index, the yield and the volatility index the regime is read from."""

BOOTSTRAP_BLOCK, BOOTSTRAP_DRAWS, BOOTSTRAP_SEED, BOOTSTRAP_LEVEL = 20, 2000, 20261003, 0.95
"""The paired block bootstrap of a Sharpe difference: blocks of twenty sessions."""

HOLD, TREND, REGIME = "buy_and_hold", "trend_200", "rate_regime_trend"
"""The three books of a window, in the order they are run and printed."""

BOOK_COLOURS = {HOLD: PRICE_COLOUR, TREND: "#c05621", REGIME: SLOW_COLOUR}


@dataclass(frozen=True, slots=True)
class Window:
    """One instrument over one period, and how the engine is set up for it.

    Attributes
    ----------
    role : str
        ``discovery`` or ``validation``.
    instrument_id : str
        The fund the three books hold.
    start, end : date
        Inclusive bounds of the run.
    calendar_id : str
        Reference calendar of the run: the venue of the fund.
    currency : str
        Currency of the book.
    timetable : BacktestTimetable
        The three instants of a session, in the hours of that venue.
    paper : bool
        Whether the fund is an index made tradable for this run only.
    """

    role: str
    instrument_id: str
    start: date
    end: date
    calendar_id: str
    currency: str
    timetable: BacktestTimetable
    paper: bool


WINDOWS = (
    Window(
        "discovery",
        "ETF_WORLD",
        date(2019, 4, 1),
        date(2026, 9, 17),
        "XPAR",
        "EUR",
        BacktestTimetable(
            decision_time=time(23, 0),
            execution_time=time(9, 1),
            valuation_time=time(23, 0),
            timezone="Europe/Paris",
        ),
        paper=False,
    ),
    Window(
        "validation",
        "SP500",
        date(1991, 1, 2),
        date(2018, 12, 31),
        "XNYS",
        "USD",
        BacktestTimetable(
            decision_time=time(17, 30),
            execution_time=time(9, 31),
            valuation_time=time(17, 30),
            timezone="America/New_York",
        ),
        paper=True,
    ),
)
"""The first run, and the market and the years it never saw."""


def strategies(instrument_id: str) -> dict[str, Strategy]:
    """Return the three books of a window, every parameter written here.

    Parameters
    ----------
    instrument_id : str
        The fund the three hold.

    Returns
    -------
    dict[str, Strategy]
        Buy and hold, the plain trend rule, and the rule under test. The
        parameters of the last are those of the hypothesis: a 200-session
        average, a correlation over 60 pairs, a volatility index more than 1.5
        standard deviations above its mean of 60 observations. The regime
        accepts inputs three sessions old - a yield is published the day after
        it is fixed, and a holiday on either side of the Atlantic adds a
        session - and the volatility index two.
    """
    return {
        HOLD: BuyAndHold(instruments=(instrument_id,)),
        TREND: MovingAverageBandETF(
            instrument_id=instrument_id,
            window_sessions=TREND_SESSIONS,
            sell_below=1.0,
            buy_above=1.0,
            strategy_id=TREND,
        ),
        REGIME: RateRegimeTrend(
            instrument_id=instrument_id,
            equity_id=EQUITY_ID,
            rate_id=RATE_ID,
            stress_id=STRESS_ID,
            trend_sessions=TREND_SESSIONS,
            correlation_pairs=60,
            stress_observations=60,
            stress_minimum=1.5,
            regime_max_age_sessions=3,
            stress_max_age_sessions=2,
            strategy_id=REGIME,
        ),
    }


def paper_registry(registry: InstrumentRegistry, instrument_id: str) -> InstrumentRegistry:
    """Return a copy of the registry in which one instrument can be held.

    Parameters
    ----------
    registry : InstrumentRegistry
        The committed registry.
    instrument_id : str
        The index to hold on paper.

    Returns
    -------
    InstrumentRegistry
        The same instruments, that one declared ``tradable``. The committed
        registry is not touched: an index stays something nobody can buy
        everywhere but in the run this is handed to.
    """
    registry.get(instrument_id)
    return InstrumentRegistry(
        [
            replace(instrument, tradable=True) if instrument.id == instrument_id else instrument
            for instrument in registry.list_all()
        ]
    )


def build_runner(root: Path, window: Window) -> StrategyRunner:
    """Return the runner of a window: its calendar, its currency, its timetable."""
    instruments = InstrumentRegistry.from_toml(root / "metadata" / "instruments.toml")
    if window.paper:
        instruments = paper_registry(instruments, window.instrument_id)
    calendars = CalendarRegistry.from_directory(root / "metadata" / "calendars")
    reader = MarketDataReader(
        repository=MarketDataRepository(root),
        instruments=instruments,
        calendars=calendars,
        reference_calendar_id=window.calendar_id,
    )
    return StrategyRunner(
        reader=reader,
        calendars=calendars,
        reference_calendar_id=window.calendar_id,
        base_currency=window.currency,
        analytics=ANALYTICS,
        execution=EXECUTION,
        initial_cash=INITIAL_CASH,
        timetable=window.timetable,
        source=git_source_state(REPOSITORY),
        benchmark=BenchmarkSpec(window.instrument_id, basis=BenchmarkBasis.TOTAL_RETURN),
        lockfile=REPOSITORY / "uv.lock",
    )


def summary_row(name: str, result: StrategyResult) -> str:
    """Return one line of the table: what a book earned, gross and net, and at what risk."""
    report = result.report()
    net, gross = report.net, report.gross

    def shown(value: float | None, pattern: str) -> str:
        return "n/a" if value is None else format(value, pattern)

    return (
        f"{name:<18} {gross.total_return:>+9.1%} {net.total_return:>+9.1%} "
        f"{shown(net.annualised_return, '+.2%'):>8} {shown(net.annualised_volatility, '.2%'):>8} "
        f"{shown(net.sharpe_ratio, '+.3f'):>7} {net.drawdown.depth:>8.1%} {len(result.fills()):>6}"
    )


SUMMARY_HEADER = (
    f"{'book':<18} {'gross':>9} {'net':>9} {'net/yr':>8} {'vol':>8} {'sharpe':>7} "
    f"{'max dd':>8} {'fills':>6}"
)


def sharpe_difference(strategy: StrategyResult, control: StrategyResult) -> str:
    """Return the net Sharpe of one book less another's, with its bootstrap interval."""
    paired = paired_block_bootstrap(
        strategy.equity(),
        control.equity(),
        statistic=PairedStatistic.SHARPE,
        block=BOOTSTRAP_BLOCK,
        draws=BOOTSTRAP_DRAWS,
        seed=BOOTSTRAP_SEED,
        level=BOOTSTRAP_LEVEL,
        config=ANALYTICS,
    )
    return (
        f"{paired.estimate:+.3f}  [{paired.low:+.3f}, {paired.high:+.3f}] at {BOOTSTRAP_LEVEL:.0%}"
    )


def trailing_average(closes: pd.Series, window: int) -> pd.Series:  # type: ignore[type-arg]
    """Return the mean of the last ``window`` closes, for drawing only.

    Counted in observations, not in sessions in a row: a hole in the closes
    shortens nothing here. The signal the rule decides on refuses such a
    window; this line explains a figure and decides nothing.
    """
    return cast(pd.Series, closes.rolling(window).mean())


def study_figure(
    closes: pd.Series,  # type: ignore[type-arg]
    average: pd.Series,  # type: ignore[type-arg]
    held: Collection[date],
    fills: pd.DataFrame,
    profits: Mapping[str, pd.Series],  # type: ignore[type-arg]
    *,
    title: str,
) -> Figure:
    """Draw the price and the trades of the rule above the profit of the three books.

    Parameters
    ----------
    closes, average : pd.Series
        The adjusted close of the fund and its trailing average, indexed by
        session date, over the period to draw.
    held : Collection[date]
        The sessions at whose close the rule under test held the fund.
    fills : pd.DataFrame
        Its executions: columns ``session_date`` and ``side``.
    profits : Mapping[str, pd.Series]
        Net equity less the starting capital, per book, indexed by session.
    title : str
        What the figure shows.

    Returns
    -------
    Figure
        Two panels on one time axis. Above, the close and its average, a
        shaded background on the sessions invested, a green cross at every buy
        and a red one at every sell. Below, the profit and loss of each book.

    Raises
    ------
    ValueError
        If ``closes`` holds no session.
    """
    if len(closes) == 0:
        raise ValueError("there is nothing to draw: the closes hold no session")
    days = [session_date(day) for day in closes.index]
    figure = Figure(figsize=(11, 7.5), layout="constrained")
    price_axes, pnl_axes = figure.subplots(2, 1, sharex=True)
    price_axes.fill_between(
        days,
        0.0,
        1.0,
        where=[day in held for day in days],
        transform=price_axes.get_xaxis_transform(),
        color=HELD_COLOUR,
        alpha=0.10,
        linewidth=0.0,
        label="invested",
    )
    price_axes.plot(days, list(closes), color=PRICE_COLOUR, linewidth=0.9, label="close")
    price_axes.plot(
        days, list(average), color=SLOW_COLOUR, linewidth=1.3, label=f"MA{TREND_SESSIONS}"
    )
    price_of = dict(zip(days, (float(value) for value in closes), strict=True))
    for side, colour in (("BUY", HELD_COLOUR), ("SELL", SELL_COLOUR)):
        traded = [
            day for day in fills.loc[fills["side"] == side, "session_date"] if day in price_of
        ]
        price_axes.scatter(
            traded,
            [price_of[day] for day in traded],
            marker="x",
            color=colour,
            s=90,
            linewidths=2.2,
            zorder=3,
            label=side.lower(),
        )
    price_axes.set_title(title)
    price_axes.set_ylabel("adjusted close")
    for name, profit in profits.items():
        pnl_axes.plot(
            [session_date(day) for day in profit.index],
            list(profit),
            color=BOOK_COLOURS.get(name, PRICE_COLOUR),
            linewidth=1.4,
            label=name,
        )
    pnl_axes.axhline(0.0, color=PRICE_COLOUR, linewidth=0.6)
    pnl_axes.set_ylabel("net profit and loss")
    for axes in (price_axes, pnl_axes):
        axes.grid(visible=True, alpha=0.25)
        axes.legend(loc="upper left", frameon=False)
    return figure


def save_figure(window: Window, results: Mapping[str, StrategyResult], directory: Path) -> None:
    """Save the figure of a window: the rule under test, against the two others.

    The closes drawn are the adjusted closes as they are known after the last
    close of the run, not as each decision saw them.
    """
    regime = results[REGIME]
    reader = regime.reader.at(regime.records()[-1].valuation_time)
    closes = reader.adjusted_history(window.instrument_id, end=regime.end)
    average = trailing_average(closes, TREND_SESSIONS)
    weights = regime.weights()[window.instrument_id]
    figure = study_figure(
        closes.loc[regime.start :],
        average.loc[regime.start :],
        held={session_date(day) for day, weight in weights.items() if weight > 0},
        fills=regime.fills(),
        profits={name: result.equity() - INITIAL_CASH for name, result in results.items()},
        title=f"{window.instrument_id}  {REGIME}  {regime.start} to {regime.end}"
        + ("  (paper run)" if window.paper else ""),
    )
    figure.savefig(directory / f"{window.role}_{window.instrument_id}.png", dpi=FIGURE_DPI)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the three books over every window, print them and save a figure of each."""
    parser = argparse.ArgumentParser(description="Run the rate regime study.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("rate_regime_output"),
        help="where the figures are written",
    )
    arguments = parser.parse_args(argv)
    arguments.output.mkdir(parents=True, exist_ok=True)

    for window in WINDOWS:
        runner = build_runner(STORE, window)
        results = {
            name: runner.run(strategy, (window.instrument_id,), window.start, window.end)
            for name, strategy in strategies(window.instrument_id).items()
        }
        paper = "  (paper run)" if window.paper else ""
        print(f"\n{window.role}: {window.instrument_id}  {window.start} to {window.end}{paper}")
        print(SUMMARY_HEADER)
        for name, result in results.items():
            print(summary_row(name, result))
        for control in (HOLD, TREND):
            difference = sharpe_difference(results[REGIME], results[control])
            print(f"net Sharpe, {REGIME} less {control}: {difference}", flush=True)
        save_figure(window, results, arguments.output)
    print(f"\nFigures written to {arguments.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
