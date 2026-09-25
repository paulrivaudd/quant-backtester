"""How often a strategy is asked, and what a session it is not asked on records."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, time

import pandas as pd
import pytest

from quant_backtester.backtest.config import BacktestConfig
from quant_backtester.backtest.context import StrategyContext
from quant_backtester.backtest.engine import BacktestEngine
from quant_backtester.backtest.schedule import (
    EveryNSessions,
    EverySession,
    Monthly,
    Weekly,
)
from quant_backtester.backtest.timetable import BacktestTimetable
from quant_backtester.data.calendars import CalendarRegistry, TradingCalendar
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.execution.costs import CostModel
from quant_backtester.execution.model import ExecutionModel
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.strategies.base import Strategy

PARIS = BacktestTimetable(
    decision_time=time(23, 0), execution_time=time(9, 1), valuation_time=time(23, 0)
)

SEPTEMBER = [
    date(2026, 9, 1),
    date(2026, 9, 2),
    date(2026, 9, 3),
    date(2026, 9, 4),
    date(2026, 9, 7),
    date(2026, 9, 8),
    date(2026, 9, 9),
    date(2026, 9, 10),
    date(2026, 9, 11),
    date(2026, 9, 14),
]
"""Ten Paris sessions, two weekends inside them."""


def test_every_session_asks_on_all_of_them() -> None:
    """The default, and the most expensive."""
    assert EverySession().decision_sessions(SEPTEMBER) == frozenset(SEPTEMBER)


def test_every_n_sessions_counts_from_the_start_of_the_run() -> None:
    """A fortnightly rebalancing is ten sessions apart, not fourteen days."""
    chosen = EveryNSessions(3).decision_sessions(SEPTEMBER)

    assert sorted(chosen) == [
        date(2026, 9, 1),
        date(2026, 9, 4),
        date(2026, 9, 9),
        date(2026, 9, 14),
    ]


def test_a_period_of_no_sessions_is_refused() -> None:
    """Deciding every zero sessions is a parameter written wrong."""
    with pytest.raises(ValueError, match="n"):
        EveryNSessions(0)


def test_weekly_takes_the_last_session_of_each_week() -> None:
    """The last session that exists, not Friday: a holiday must not skip a week."""
    chosen = Weekly().decision_sessions(SEPTEMBER)

    assert sorted(chosen) == [date(2026, 9, 4), date(2026, 9, 11), date(2026, 9, 14)]


def test_monthly_takes_the_last_session_of_each_month() -> None:
    """Two months, two decisions, whatever the calendar days are."""
    august = [date(2026, 8, 28), date(2026, 8, 31)]

    chosen = Monthly().decision_sessions([*august, *SEPTEMBER])

    assert sorted(chosen) == [date(2026, 8, 31), date(2026, 9, 14)]


def test_a_holiday_does_not_move_a_weekly_decision_off_the_calendar() -> None:
    """The schedule is a function of the sessions, never of the days."""
    without_friday = [day for day in SEPTEMBER if day != date(2026, 9, 4)]

    chosen = Weekly().decision_sessions(without_friday)

    assert date(2026, 9, 3) in chosen


@dataclass(frozen=True, slots=True)
class Counting(Strategy):
    """A strategy that records every session it is asked on."""

    weights_wanted: Mapping[str, float]
    asked: list[date] = field(repr=False, compare=False)
    strategy_id: str = "counting"

    def decide(self, ctx: StrategyContext) -> TargetAllocation:
        """Record the instant, and always want the same book."""
        self.asked.append(ctx.as_of.date())
        return ctx.weights(dict(self.weights_wanted))


def engine_over(
    market: MarketDataReader,
    calendars: CalendarRegistry,
    strategy: Strategy,
    schedule: object,
    start: date,
    end: date,
) -> BacktestEngine:
    """Wire an engine with a decision schedule."""
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
            schedule=schedule,  # type: ignore[arg-type]
            timetable=PARIS,
        ),
        execution=ExecutionModel(costs=CostModel()),
    )


def test_a_strategy_is_not_asked_on_a_session_it_does_not_decide_on(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    calendars: CalendarRegistry,
    xpar: TradingCalendar,
    prices: Callable[..., dict[date, float]],
    sessions: tuple[date, ...],
) -> None:
    """Which is the whole point: a monthly strategy is a monthly strategy."""
    market = make_market({"ETF_EU": make_bars("ETF_EU", xpar, prices(100.0, 1.0))})
    asked: list[date] = []
    strategy = Counting(weights_wanted={"ETF_EU": 1.0}, asked=asked)

    engine_over(market, calendars, strategy, EveryNSessions(3), sessions[-6], sessions[-1]).run()

    # Asked at 23:00 Paris, which is the same date in UTC.
    assert len(asked) == 2


def test_a_session_with_no_decision_sends_no_order(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    calendars: CalendarRegistry,
    xpar: TradingCalendar,
    prices: Callable[..., dict[date, float]],
    sessions: tuple[date, ...],
) -> None:
    """The book drifts with the prices rather than being restated daily.

    That is what makes a low-frequency strategy cheaper, and it is the reason
    the schedule belongs in the run rather than inside the strategy.
    """
    market = make_market({"ETF_EU": make_bars("ETF_EU", xpar, prices(100.0, 1.0))})
    asked: list[date] = []
    strategy = Counting(weights_wanted={"ETF_EU": 1.0}, asked=asked)

    result = engine_over(
        market, calendars, strategy, EveryNSessions(3), sessions[-6], sessions[-1]
    ).run()

    traded = [record for record in result.records if record.traded_value > 0.0]
    assert len(traded) == 1
    assert [record.decided for record in result.records] == [True, False, False, True, False, False]


def test_a_session_with_no_decision_carries_the_target_still_standing(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    calendars: CalendarRegistry,
    xpar: TradingCalendar,
    prices: Callable[..., dict[date, float]],
    sessions: tuple[date, ...],
) -> None:
    """The record says what the book is aiming at, not that it wanted nothing."""
    market = make_market({"ETF_EU": make_bars("ETF_EU", xpar, prices(100.0, 1.0))})
    strategy = Counting(weights_wanted={"ETF_EU": 1.0}, asked=[])

    result = engine_over(
        market, calendars, strategy, EveryNSessions(3), sessions[-6], sessions[-1]
    ).run()

    standing = result.target_weights()
    assert standing.loc[sessions[-5], "ETF_EU"] == 1.0
    assert result.records[1].target_invested == 1.0
    assert result.records[1].decided is False
    assert result.records[1].decision is None
