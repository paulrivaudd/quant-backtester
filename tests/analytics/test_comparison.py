"""Measuring a strategy against something else that could have been held.

The arithmetic is small. What the tests are about is fairness: both sides
measured on the same days, the benchmark valued at the instants the strategy
could have seen, and a currency mismatch refused rather than drawn.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, time

import pandas as pd
import pytest

from quant_backtester.analytics.comparison import (
    BenchmarkCurrencyMismatch,
    BenchmarkSpec,
    common_period,
    compare,
)
from quant_backtester.analytics.config import AnalyticsConfig
from quant_backtester.analytics.curves import Book, equity_curve
from quant_backtester.backtest.engine import Timetable
from quant_backtester.backtest.runner import StrategyRunner, value_benchmark
from quant_backtester.data.calendars import CalendarRegistry, TradingCalendar
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.signals.types import PriceBasis
from quant_backtester.strategies.examples import BuyAndHold

PARIS = Timetable(decision_time=time(23, 0), execution_time=time(9, 1), timezone="Europe/Paris")
CONFIG = AnalyticsConfig(sessions_per_year=255, risk_free_rate=0.0)


@pytest.fixture
def runner(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    calendars: CalendarRegistry,
    xpar: TradingCalendar,
    xnys: TradingCalendar,
    prices: Callable[..., dict[date, float]],
    us_sessions: tuple[date, ...],
) -> StrategyRunner:
    """Return a runner over two Paris funds and a New York index."""
    market = make_market(
        {
            "ETF_EU": make_bars("ETF_EU", xpar, prices(100.0, 1.0)),
            "ETF_OTHER": make_bars("ETF_OTHER", xpar, prices(200.0, 3.0)),
            "IDX_US": make_bars("IDX_US", xnys, prices(5_000.0, 10.0, us_sessions)),
        }
    )
    return StrategyRunner(
        reader=market,
        calendars=calendars,
        reference_calendar_id="XPAR",
        base_currency="EUR",
        analytics=CONFIG,
        initial_cash=10_000.0,
        timetable=PARIS,
    )


def a_run(runner: StrategyRunner):
    """Return a run holding the slower of the two funds."""
    return runner.run(BuyAndHold(instruments=("ETF_EU",)), ["ETF_EU"], "2026-09-01", "2026-09-14")


def test_a_benchmark_starts_where_the_strategy_started(runner: StrategyRunner) -> None:
    """Two curves on one scale, or the picture says nothing."""
    result = a_run(runner)

    curve = result.benchmark("ETF_OTHER")

    assert curve.equity.iloc[0] == pytest.approx(result.equity().iloc[0])


def test_a_benchmark_follows_its_own_prices(runner: StrategyRunner) -> None:
    """ETF_OTHER rises by three a session against ETF_EU's one."""
    result = a_run(runner)

    curve = result.benchmark("ETF_OTHER")

    assert curve.equity.iloc[-1] > result.equity().iloc[-1]


def test_a_benchmark_in_another_currency_is_refused(runner: StrategyRunner) -> None:
    """The difference between the two curves would be an exchange rate."""
    result = a_run(runner)

    with pytest.raises(BenchmarkCurrencyMismatch, match="USD"):
        result.benchmark("IDX_US")


def test_a_benchmark_need_not_be_tradable(runner: StrategyRunner) -> None:
    """An index is a legitimate yardstick even when nobody can buy it."""
    result = a_run(runner)

    curve = value_benchmark(result.backtest, runner.reader, "IDX_US")

    assert len(curve.equity) == len(result.backtest.records)


def test_a_session_the_benchmark_venue_did_not_hold_is_named(
    runner: StrategyRunner,
) -> None:
    """New York was shut on 7 September while Paris traded.

    The curve is marked at the last close that existed, and says so rather than
    looking like a day the index did not move.
    """
    result = a_run(runner)

    curve = value_benchmark(result.backtest, runner.reader, "IDX_US")

    assert date(2026, 9, 7) in curve.marked_from_earlier


def test_both_sides_are_measured_on_the_same_days(runner: StrategyRunner) -> None:
    """Comparing one period with another is how a comparison becomes a sales document."""
    result = a_run(runner)

    comparison = result.compare("ETF_OTHER")

    assert comparison.sessions == len(result.backtest.records)
    assert comparison.strategy.sessions == comparison.benchmark.sessions


def test_the_excess_return_is_the_difference_over_the_period(
    runner: StrategyRunner,
) -> None:
    """The one figure a comparison exists to produce."""
    result = a_run(runner)

    comparison = result.compare("ETF_OTHER")

    assert comparison.excess_return == pytest.approx(
        comparison.strategy.total_return - comparison.benchmark.total_return
    )
    assert comparison.excess_return < 0.0


def test_a_comparison_reads_as_a_frame_and_as_a_block(runner: StrategyRunner) -> None:
    """What a notebook reads, and what a terminal prints."""
    result = a_run(runner)

    comparison = result.compare("ETF_OTHER")
    frame = comparison.as_frame()

    assert list(frame.columns) == ["strategy", "ETF_OTHER"]
    assert "total return" in comparison.render()
    assert "ETF_OTHER" in comparison.render()


def test_a_benchmark_can_be_compared_on_raw_prices(runner: StrategyRunner) -> None:
    """Total return by default; the quoted series when a report wants it."""
    result = a_run(runner)

    raw = result.benchmark(BenchmarkSpec("ETF_OTHER", price_basis=PriceBasis.RAW, label="raw"))

    assert raw.spec.name == "raw"
    assert len(raw.equity) == len(result.backtest.records)


def test_data_after_the_run_changes_no_figure_of_it(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    calendars: CalendarRegistry,
    xpar: TradingCalendar,
    prices: Callable[..., dict[date, float]],
    sessions: tuple[date, ...],
) -> None:
    """A comparison is ex-post and still point-in-time.

    The second store carries a fifty percent jump on the session after the run
    ends. Every reading is taken at a decision instant inside the period, so
    neither the curve nor the statistics move.
    """
    quiet = prices(100.0, 1.0)
    loud = dict(quiet)
    loud[sessions[-1]] = loud[sessions[-2]] * 1.5

    curves = []
    for series in (quiet, loud):
        market = make_market(
            {
                "ETF_EU": make_bars("ETF_EU", xpar, prices(100.0, 1.0)),
                "ETF_OTHER": make_bars("ETF_OTHER", xpar, series),
            }
        )
        runner = StrategyRunner(
            reader=market,
            calendars=calendars,
            reference_calendar_id="XPAR",
            base_currency="EUR",
            analytics=CONFIG,
            initial_cash=10_000.0,
            timetable=PARIS,
        )
        result = runner.run(
            BuyAndHold(instruments=("ETF_EU",)), ["ETF_EU"], "2026-09-01", "2026-09-11"
        )
        curves.append(result.benchmark("ETF_OTHER").equity)

    pd.testing.assert_series_equal(curves[0], curves[1])


def test_two_curves_are_compared_over_what_they_share() -> None:
    """The intersection, and it is stated rather than assumed."""
    first = pd.Series([1.0, 2.0], index=[date(2026, 9, 1), date(2026, 9, 2)])
    second = pd.Series([1.0, 2.0], index=[date(2026, 9, 2), date(2026, 9, 3)])

    assert list(common_period(first, second)) == [date(2026, 9, 2)]


def test_two_curves_sharing_no_session_cannot_be_compared(
    runner: StrategyRunner,
) -> None:
    """Not an empty comparison: there is nothing to compare."""
    result = a_run(runner)
    elsewhere = result.benchmark("ETF_OTHER")
    moved = elsewhere.equity.copy()
    moved.index = pd.Index([date(2030, 1, day + 1) for day in range(len(moved))])

    with pytest.raises(ValueError, match="share no session"):
        compare(
            equity_curve(result.backtest, Book.NET),
            type(elsewhere)(spec=elsewhere.spec, equity=moved),
            CONFIG,
        )


def test_a_benchmark_of_a_run_with_no_session_is_refused(runner: StrategyRunner) -> None:
    """There is nothing to measure it over."""
    result = a_run(runner)
    empty = type(result.backtest)(records=(), initial_cash=10_000.0)

    with pytest.raises(ValueError, match="no session"):
        value_benchmark(empty, runner.reader, "ETF_OTHER")


def test_a_benchmark_nobody_declared_is_a_wiring_mistake(runner: StrategyRunner) -> None:
    """A name the registry does not know stops the comparison."""
    result = a_run(runner)

    with pytest.raises(KeyError):
        result.benchmark("NOT_A_THING")


def test_a_benchmark_needs_a_name() -> None:
    """A blank id is a comparison against nothing."""
    with pytest.raises(ValueError, match="instrument_id"):
        BenchmarkSpec("   ")
