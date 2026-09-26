"""Measuring a strategy against something else that could have been held.

The arithmetic is small. What the tests are about is fairness: both sides
measured on the same days, the benchmark valued at the instants the strategy
could have seen, and a currency mismatch refused rather than drawn.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from quant_backtester.analytics.comparison import (
    BenchmarkBasis,
    BenchmarkCurrencyMismatch,
    BenchmarkSpec,
    common_period,
    compare,
)
from quant_backtester.analytics.config import AnalyticsConfig
from quant_backtester.analytics.curves import Book, equity_curve
from quant_backtester.backtest.runner import StrategyRunner, value_benchmark
from quant_backtester.backtest.timetable import BacktestTimetable
from quant_backtester.data.calendars import CalendarRegistry, TradingCalendar
from quant_backtester.data.instruments import InstrumentRegistry
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.data.repository import MarketDataRepository
from quant_backtester.data.schemas import ActionType
from quant_backtester.execution.costs import CostModel
from quant_backtester.execution.model import ExecutionModel
from quant_backtester.strategies.examples import BuyAndHold

PARIS = BacktestTimetable(
    decision_time=time(23, 0), execution_time=time(9, 1), valuation_time=time(23, 0)
)
FREE = ExecutionModel(costs=CostModel())
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
        execution=FREE,
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


def test_a_benchmark_can_be_compared_on_its_price_return(runner: StrategyRunner) -> None:
    """Total return by default; the price return when a report wants it."""
    result = a_run(runner)

    raw = result.benchmark(
        BenchmarkSpec("ETF_OTHER", basis=BenchmarkBasis.PRICE_RETURN, label="raw")
    )

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
    ends. Every reading is taken at a valuation instant inside the period, so
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
            execution=FREE,
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
    empty = type(result.backtest)(
        records=(),
        config=result.backtest.config,
        configuration={},
        strategy_definition={"strategy_id": "nothing"},
        strategy_fingerprint="nothing",
    )

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


# --- a benchmark is a wealth, not a glued adjusted series (audit A01) -------------


PARIS_TZ = ZoneInfo("Europe/Paris")

Event = tuple[ActionType, int, float]
"""An action on ETF_OTHER: its type, the index of its ex-date in SESSIONS, its value."""


@pytest.fixture
def wealth(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    make_actions: Callable[..., pd.DataFrame],
    calendars: CalendarRegistry,
    xpar: TradingCalendar,
    sessions: tuple[date, ...],
) -> Callable[..., list[float]]:
    """Return a builder of ETF_OTHER's benchmark over a run, as growth of one unit.

    ``known_on`` moves the instant an action becomes known: by default the
    morning of its ex-date, as a provider announcing it in advance would have.
    """

    def build(
        closes: list[float],
        events: list[Event],
        basis: BenchmarkBasis = BenchmarkBasis.TOTAL_RETURN,
        known_on: int | None = None,
    ) -> list[float]:
        days = sessions[: len(closes)]
        actions = make_actions(
            [
                (
                    "ETF_OTHER",
                    kind,
                    sessions[index],
                    value,
                    datetime.combine(
                        sessions[index if known_on is None else known_on], time(9), PARIS_TZ
                    ),
                )
                for kind, index, value in events
            ]
        )
        market = make_market(
            {
                "ETF_EU": make_bars("ETF_EU", xpar, dict.fromkeys(days, 100.0)),
                "ETF_OTHER": make_bars("ETF_OTHER", xpar, dict(zip(days, closes, strict=True))),
            },
            actions=actions,
        )
        runner = StrategyRunner(
            reader=market,
            calendars=calendars,
            reference_calendar_id="XPAR",
            base_currency="EUR",
            analytics=CONFIG,
            execution=FREE,
            initial_cash=10_000.0,
            timetable=PARIS,
        )
        result = runner.run(BuyAndHold(instruments=("ETF_EU",)), ["ETF_EU"], days[0], days[-1])
        curve = value_benchmark(result.backtest, market, BenchmarkSpec("ETF_OTHER", basis=basis))
        return [value / curve.equity.iloc[0] for value in curve.equity]

    return build


def test_a_split_leaves_the_holder_as_rich_as_before(wealth: Callable[..., list[float]]) -> None:
    """2-for-1, the price halves, nothing else moves: the audit's curve fell to half."""
    curve = wealth([100.0, 50.0, 50.0, 50.0], [(ActionType.SPLIT, 1, 2.0)])

    assert curve == pytest.approx([1.0, 1.0, 1.0, 1.0])


def test_a_dividend_the_price_drop_pays_for_leaves_total_return_flat(
    wealth: Callable[..., list[float]],
) -> None:
    curve = wealth([100.0, 90.0, 90.0], [(ActionType.DIVIDEND, 1, 10.0)])

    assert curve == pytest.approx([1.0, 1.0, 1.0])


def test_the_price_return_leaves_the_dividend_out(wealth: Callable[..., list[float]]) -> None:
    curve = wealth(
        [100.0, 90.0, 90.0], [(ActionType.DIVIDEND, 1, 10.0)], basis=BenchmarkBasis.PRICE_RETURN
    )

    assert curve == pytest.approx([1.0, 0.9, 0.9])


def test_a_dividend_on_a_rising_day_is_received_and_reinvested_at_the_close(
    wealth: Callable[..., list[float]],
) -> None:
    """(110 + 10) / 100: twenty percent, where the adjusted series said 22.2 (audit A08)."""
    curve = wealth([100.0, 110.0, 121.0], [(ActionType.DIVIDEND, 1, 10.0)])

    # The cash buys 10/110 of a share at the close, which then earns the 10%.
    assert curve == pytest.approx([1.0, 1.2, 1.2 * 1.1])


def test_several_actions_compound_on_the_shares_held(wealth: Callable[..., list[float]]) -> None:
    """A dividend after a split is paid on the shares the split created."""
    curve = wealth(
        [100.0, 50.0, 50.0, 45.0],
        [(ActionType.SPLIT, 1, 2.0), (ActionType.DIVIDEND, 3, 5.0)],
    )

    assert curve == pytest.approx([1.0, 1.0, 1.0, 1.0])


def test_an_action_before_the_first_close_is_already_in_it(
    wealth: Callable[..., list[float]],
) -> None:
    """The run starts from a price that has already moved; counting it again is wrong."""
    curve = wealth([50.0, 50.0, 55.0], [(ActionType.SPLIT, 0, 2.0)])

    assert curve == pytest.approx([1.0, 1.0, 1.1])


def test_an_action_known_late_is_counted_when_known_and_not_back_dated(
    wealth: Callable[..., list[float]],
) -> None:
    """At the ex-date nobody knew of the split, so the curve shows the drop; then it catches up."""
    curve = wealth([100.0, 50.0, 50.0, 50.0], [(ActionType.SPLIT, 1, 2.0)], known_on=3)

    assert curve == pytest.approx([1.0, 0.5, 0.5, 1.0])


def test_a_spin_off_is_refused_rather_than_valued_as_a_split(
    wealth: Callable[..., list[float]],
) -> None:
    with pytest.raises(ValueError, match="spin-off"):
        wealth([100.0, 80.0, 80.0], [(ActionType.SPIN_OFF, 1, 1.25)])


def test_a_split_and_a_dividend_on_one_day_are_refused(
    wealth: Callable[..., list[float]],
) -> None:
    """Per share before or after the split? Unsaid, and the answers differ by the ratio."""
    with pytest.raises(ValueError, match="split and a distribution"):
        wealth([100.0, 50.0, 50.0], [(ActionType.SPLIT, 1, 2.0), (ActionType.DIVIDEND, 1, 5.0)])


def test_a_benchmark_is_not_carried_past_its_delisting(
    repository: MarketDataRepository,
    make_bars: Callable[..., pd.DataFrame],
    instruments: InstrumentRegistry,
    calendars: CalendarRegistry,
    xpar: TradingCalendar,
    sessions: tuple[date, ...],
) -> None:
    """Audit A15: the curve used to go flat at the last close, as if still held.

    The book stops on a delisted line; its yardstick is held to the same rule.
    """
    registry = InstrumentRegistry(
        [
            replace(instrument, last_session=sessions[1])
            if instrument.id == "ETF_OTHER"
            else instrument
            for instrument in instruments
        ]
    )
    days = sessions[:4]
    repository.save_checked_bars("ETF_EU", make_bars("ETF_EU", xpar, dict.fromkeys(days, 100.0)))
    repository.save_checked_bars(
        "ETF_OTHER", make_bars("ETF_OTHER", xpar, {days[0]: 100.0, days[1]: 101.0})
    )
    market = MarketDataReader(
        repository=repository,
        instruments=registry,
        calendars=calendars,
        reference_calendar_id="XPAR",
    )
    runner = StrategyRunner(
        reader=market,
        calendars=calendars,
        reference_calendar_id="XPAR",
        base_currency="EUR",
        analytics=CONFIG,
        execution=FREE,
        initial_cash=10_000.0,
        timetable=PARIS,
    )
    result = runner.run(BuyAndHold(instruments=("ETF_EU",)), ["ETF_EU"], days[0], days[-1])

    with pytest.raises(ValueError, match="stopped trading"):
        value_benchmark(result.backtest, market, "ETF_OTHER")


def test_a_dividend_on_a_session_the_run_does_not_hold_is_reinvested_at_its_own_close(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    make_actions: Callable[..., pd.DataFrame],
    calendars: CalendarRegistry,
    xpar: TradingCalendar,
    xnys: TradingCalendar,
) -> None:
    """Audit R02: the run's calendar skipped the ex-date, and the chain skipped it too.

    Paris is shut on Good Friday and Easter Monday; New York is not. The index
    goes 100, 90 (ex-dividend 10), 100, 110. Reinvested at the ex-date's close,
    as TOTAL_RETURN says, one unit becomes (90 + 10) / 100 x 100 / 90 x 110 / 100
    = 1.2222; chained only over the run's two sessions it was (110 + 10) / 100.
    """
    thursday, friday, monday, tuesday = (date(2026, 4, day) for day in (2, 3, 6, 7))
    market = make_market(
        {
            "ETF_EU": make_bars("ETF_EU", xpar, {thursday: 100.0, tuesday: 100.0}),
            "IDX_US": make_bars(
                "IDX_US", xnys, {thursday: 100.0, friday: 90.0, monday: 100.0, tuesday: 110.0}
            ),
        },
        actions=make_actions(
            [
                (
                    "IDX_US",
                    ActionType.DIVIDEND,
                    friday,
                    10.0,
                    datetime(2026, 4, 3, 13, 30, tzinfo=ZoneInfo("UTC")),
                )
            ]
        ),
    )
    runner = StrategyRunner(
        reader=market,
        calendars=calendars,
        reference_calendar_id="XPAR",
        base_currency="EUR",
        analytics=CONFIG,
        execution=FREE,
        initial_cash=10_000.0,
        timetable=PARIS,
    )
    result = runner.run(BuyAndHold(instruments=("ETF_EU",)), ["ETF_EU"], thursday, tuesday)

    curve = value_benchmark(
        result.backtest, market, BenchmarkSpec("IDX_US", basis=BenchmarkBasis.TOTAL_RETURN)
    )

    assert [record.session_date for record in result.records()] == [thursday, tuesday]
    assert curve.equity.iloc[-1] / curve.equity.iloc[0] == pytest.approx(
        (90.0 + 10.0) / 100.0 * 100.0 / 90.0 * 110.0 / 100.0
    )
