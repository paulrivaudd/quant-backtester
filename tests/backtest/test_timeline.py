"""The three instants of a session, and the gap between a decision and its fill.

A daily backtest is full of "the price of the day", and there is no such thing.
These tests pin the timeline the engine walks: the order is filled at the open
of the session after the decision - after a weekend, after a holiday - never at
the close the decision read, and nothing that happens after an instant can
change what was done at it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from quant_backtester.backtest.config import BacktestConfig
from quant_backtester.backtest.context import StrategyContext
from quant_backtester.backtest.engine import BacktestEngine
from quant_backtester.backtest.result import BacktestResult
from quant_backtester.backtest.schedule import EverySession
from quant_backtester.backtest.timetable import BacktestTimetable, ExecutionTiming
from quant_backtester.data.calendars import CalendarRegistry, TradingCalendar
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.data.schemas import BarField
from quant_backtester.execution.costs import CostModel
from quant_backtester.execution.model import ExecutionModel
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.strategies.base import Strategy

PARIS = ZoneInfo("Europe/Paris")


@dataclass(frozen=True, slots=True)
class AlwaysHold(Strategy):
    """Always the same book, so every number comes from the timeline."""

    weights: Mapping[str, float]
    strategy_id: str = "always_hold"

    def decide(self, ctx: StrategyContext) -> TargetAllocation:
        """Return the fixed target, stamped at the decision instant."""
        return TargetAllocation(as_of=ctx.as_of, weights=dict(self.weights))


@dataclass(frozen=True, slots=True)
class ReadingTheClose(Strategy):
    """Hold the fund, and write down what the market said at each decision."""

    readings: list[tuple[datetime, date | None]] = field(
        default_factory=list, repr=False, compare=False
    )
    strategy_id: str = "reading_the_close"

    def decide(self, ctx: StrategyContext) -> TargetAllocation:
        """Record the date of the close the decision read, and hold the fund."""
        self.readings.append((ctx.as_of, ctx.market.value("ETF_EU").observation_date))
        return ctx.weights({"ETF_EU": 1.0})


def run(
    market: MarketDataReader,
    calendars: CalendarRegistry,
    strategy: Strategy,
    start: date,
    end: date,
    timetable: BacktestTimetable | None = None,
) -> BacktestResult:
    """Run a strategy over the synthetic market, free of costs, on the Paris calendar."""
    return BacktestEngine(
        reader=market,
        calendars=calendars,
        strategy=strategy,
        universe=("ETF_EU",),
        config=BacktestConfig(
            start=start,
            end=end,
            initial_cash=10_000.0,
            base_currency="EUR",
            reference_calendar="XPAR",
            schedule=EverySession(),
            timetable=timetable or BacktestTimetable(),
        ),
        execution=ExecutionModel(costs=CostModel()),
    ).run()


def by_date(result: BacktestResult) -> dict[date, object]:
    """Return the records of a run, keyed by session."""
    return {record.session_date: record for record in result.records}


# -- the timetable -----------------------------------------------------------------------


def test_the_default_timetable_is_the_project_s_canonical_one() -> None:
    """Fill just after the Paris open, value and decide after the New York close."""
    timetable = BacktestTimetable()

    assert timetable.definition() == {
        "decision_time": "23:00:00",
        "execution_time": "09:01:00",
        "valuation_time": "23:00:00",
        "timezone": "Europe/Paris",
        "execution": {"field": "open", "session_offset": 1},
    }


def test_the_three_instants_are_in_the_timetable_s_zone_and_survive_daylight_saving() -> None:
    """23:00 in Paris is 22:00 UTC in winter and 21:00 UTC in summer."""
    timetable = BacktestTimetable()

    winter = timetable.decision_instant(date(2026, 1, 15))
    summer = timetable.decision_instant(date(2026, 7, 15))

    assert winter.astimezone(UTC).hour == 22
    assert summer.astimezone(UTC).hour == 21
    assert timetable.execution_instant(date(2026, 7, 15)) == datetime(
        2026, 7, 15, 9, 1, tzinfo=PARIS
    )
    assert timetable.valuation_instant(date(2026, 7, 15)) == summer


def test_a_time_carrying_its_own_offset_is_refused() -> None:
    """A wall-clock time plus a zone survives a DST switch; an offset does not."""
    with pytest.raises(ValueError, match="naive local time"):
        BacktestTimetable(decision_time=time(23, 0, tzinfo=UTC))


def test_fills_come_before_the_valuation() -> None:
    """A book valued before its own fills would be marked on positions it did not hold yet."""
    with pytest.raises(ValueError, match="fills must come before its valuation"):
        BacktestTimetable(execution_time=time(18, 0), valuation_time=time(17, 45))


def test_the_book_is_valued_no_later_than_the_decision() -> None:
    """Otherwise the decision would be handed a portfolio from its own future."""
    with pytest.raises(ValueError, match="valued at"):
        BacktestTimetable(decision_time=time(22, 0), valuation_time=time(23, 0))


def test_an_unknown_zone_is_refused() -> None:
    """A zone nobody can resolve places the decision nowhere."""
    with pytest.raises(KeyError):
        BacktestTimetable(timezone="Europe/Atlantis")


def test_only_the_next_open_is_implemented() -> None:
    """Declared rather than hard-wired, and refused when it asks for anything else."""
    assert ExecutionTiming().definition() == {"field": "open", "session_offset": 1}
    with pytest.raises(ValueError, match="only the opening auction"):
        ExecutionTiming(field=BarField.CLOSE)
    with pytest.raises(ValueError, match="only the opening auction"):
        ExecutionTiming(session_offset=0)
    with pytest.raises(ValueError, match="only the opening auction"):
        ExecutionTiming(session_offset=2)


# -- the timeline a run walks ------------------------------------------------------------


def test_a_decision_is_filled_at_the_next_open_and_every_instant_is_recorded(
    market: MarketDataReader, calendars: CalendarRegistry
) -> None:
    """Decided after the close of the ninth, filled at 09:01 on the tenth, valued at 23:00."""
    result = run(
        market, calendars, AlwaysHold({"ETF_EU": 1.0}), date(2026, 9, 9), date(2026, 9, 10)
    )

    ninth, tenth = result.records
    assert ninth.decision_time == datetime(2026, 9, 9, 23, 0, tzinfo=PARIS)
    assert ninth.execution_time is None
    assert tenth.execution_time == datetime(2026, 9, 10, 9, 1, tzinfo=PARIS)
    assert tenth.executed_decision == date(2026, 9, 9)
    assert tenth.valuation_time == datetime(2026, 9, 10, 23, 0, tzinfo=PARIS)
    assert all(fill.executed_at == tenth.execution_time for fill in tenth.fills)


def test_the_fill_is_the_next_open_and_never_the_close_that_decided_it(
    market: MarketDataReader, calendars: CalendarRegistry
) -> None:
    """The prices rise by one a session: decided on 106, bought at 107."""
    result = run(
        market, calendars, AlwaysHold({"ETF_EU": 1.0}), date(2026, 9, 9), date(2026, 9, 10)
    )

    decided, filled = result.records
    assert decided.valuation_prices == {}
    assert filled.fills[0].market_price == 107.0
    assert filled.valuation_prices["ETF_EU"] == 107.0


def test_a_decision_reads_the_close_of_its_own_session_and_nothing_later(
    market: MarketDataReader, calendars: CalendarRegistry
) -> None:
    """No same-day hindsight: the evening of the ninth sees the close of the ninth."""
    strategy = ReadingTheClose()

    run(market, calendars, strategy, date(2026, 9, 9), date(2026, 9, 11))

    assert [read for _, read in strategy.readings] == [
        date(2026, 9, 9),
        date(2026, 9, 10),
        date(2026, 9, 11),
    ]


def test_a_friday_decision_is_filled_on_monday(
    market: MarketDataReader, calendars: CalendarRegistry
) -> None:
    """Two days without a session in between, and the order simply waits for the next open."""
    result = by_date(
        run(market, calendars, AlwaysHold({"ETF_EU": 1.0}), date(2026, 9, 3), date(2026, 9, 8))
    )

    monday = result[date(2026, 9, 7)]
    assert monday.executed_decision == date(2026, 9, 4)  # type: ignore[attr-defined]
    assert monday.execution_time == datetime(2026, 9, 7, 9, 1, tzinfo=PARIS)  # type: ignore[attr-defined]
    assert date(2026, 9, 5) not in result
    assert date(2026, 9, 6) not in result


def test_a_decision_before_a_paris_holiday_is_filled_at_the_next_paris_session(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    calendars: CalendarRegistry,
    xpar: TradingCalendar,
) -> None:
    """Good Friday and Easter Monday close Paris: Thursday's decision is filled on Tuesday."""
    closes = {
        date(2026, 4, 1): 100.0,
        date(2026, 4, 2): 101.0,
        date(2026, 4, 7): 102.0,
        date(2026, 4, 8): 103.0,
    }
    market = make_market({"ETF_EU": make_bars("ETF_EU", xpar, closes)})

    result = run(market, calendars, AlwaysHold({"ETF_EU": 1.0}), date(2026, 4, 2), date(2026, 4, 8))

    sessions = [record.session_date for record in result.records]
    assert sessions == [date(2026, 4, 2), date(2026, 4, 7), date(2026, 4, 8)]
    tuesday = result.records[1]
    assert tuesday.executed_decision == date(2026, 4, 2)
    assert tuesday.fills[0].market_price == 102.0


def test_data_after_the_run_changes_nothing_in_it(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    calendars: CalendarRegistry,
    xpar: TradingCalendar,
    prices: Callable[..., dict[date, float]],
    sessions: tuple[date, ...],
) -> None:
    """The look-ahead guard: a tenfold jump after the last session moves no number before it.

    Two stores, identical up to the end of the run, one of which knows about a
    crash and a rally afterwards. Every record of the two runs is the same, bit
    for bit - including the decision taken on the last evening, which the next
    open would otherwise have been the easiest thing in the world to peek at.
    """
    quiet = prices(100.0, 1.0)
    loud = dict(quiet)
    for day in sessions[-2:]:
        loud[day] = quiet[day] * 10.0

    results = [
        run(
            make_market({"ETF_EU": make_bars("ETF_EU", xpar, series)}),
            calendars,
            AlwaysHold({"ETF_EU": 1.0}),
            sessions[2],
            sessions[-3],
        )
        for series in (quiet, loud)
    ]

    assert results[0].records == results[1].records


def test_an_order_placed_before_the_open_prints_is_not_filled(
    market: MarketDataReader, calendars: CalendarRegistry
) -> None:
    """An execution time before the auction finds only yesterday's open, and refuses it."""
    early = BacktestTimetable(execution_time=time(8, 30))

    result = run(
        market, calendars, AlwaysHold({"ETF_EU": 1.0}), date(2026, 9, 9), date(2026, 9, 10), early
    )

    tenth = result.records[1]
    assert tenth.fills == ()
    assert [reject.reason.value for reject in tenth.rejects] == ["STALE_EXECUTION_PRICE"]
