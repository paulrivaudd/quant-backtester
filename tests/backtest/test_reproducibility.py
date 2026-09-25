"""Same code, same configuration, same data: the same numbers, bit for bit.

Equality here is the dataclasses' own, which compares every float exactly -
not ``approx``. A run that differed from itself in the last digit would be a
run whose history could not be reproduced, and the difference would compound.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date

import pandas as pd

from quant_backtester.backtest.config import BacktestConfig
from quant_backtester.backtest.context import StrategyContext
from quant_backtester.backtest.engine import BacktestEngine
from quant_backtester.backtest.result import BacktestResult
from quant_backtester.backtest.schedule import EverySession
from quant_backtester.backtest.timetable import BacktestTimetable
from quant_backtester.data.calendars import CalendarRegistry, TradingCalendar
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.execution.costs import CostModel
from quant_backtester.execution.model import ExecutionModel
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.signals.cross_sectional.rank import CrossSectionalRank
from quant_backtester.signals.engine import SignalRequest
from quant_backtester.signals.price.returns import ReturnSignal
from quant_backtester.signals.types import PriceBasis
from quant_backtester.strategies.base import Strategy

COSTLY = ExecutionModel(
    costs=CostModel(
        commission_rate=0.001, minimum_commission=1.0, half_spread_rate=0.002, slippage_rate=0.001
    ),
    minimum_trade_value=50.0,
)


@dataclass(frozen=True, slots=True)
class Fixed(Strategy):
    """Always the same weights."""

    weights: Mapping[str, float]
    strategy_id: str = "fixed"

    def decide(self, ctx: StrategyContext) -> TargetAllocation:
        """Return the weights as given."""
        return TargetAllocation(as_of=ctx.as_of, weights=dict(self.weights))


@dataclass(frozen=True, slots=True)
class BestOne(Strategy):
    """All of the book in the best two-session return, the first on a tie."""

    strategy_id: str = "best_one"

    def required_signals(self) -> Sequence[ReturnSignal | CrossSectionalRank | SignalRequest]:
        """Return a two-session return and its ranking across the universe."""
        momentum = ReturnSignal(
            signal_id="return_2d", lookback_sessions=2, price_basis=PriceBasis.RAW
        )
        return (momentum, CrossSectionalRank(signal_id="rank", source=momentum))

    def decide(self, ctx: StrategyContext) -> TargetAllocation:
        """Hold the top of the ranking."""
        return ctx.equal_weight(ctx.top("rank", 1))


def run(
    market: MarketDataReader,
    calendars: CalendarRegistry,
    strategy: Strategy,
    universe: Sequence[str],
) -> BacktestResult:
    """Run over the last six synthetic sessions, with every cost declared."""
    return BacktestEngine(
        reader=market,
        calendars=calendars,
        strategy=strategy,
        universe=universe,
        config=BacktestConfig(
            start=date(2026, 9, 7),
            end=date(2026, 9, 14),
            initial_cash=10_000.0,
            base_currency="EUR",
            reference_calendar="XPAR",
            schedule=EverySession(),
            timetable=BacktestTimetable(),
        ),
        execution=COSTLY,
    ).run()


def two_funds(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    xpar: TradingCalendar,
    prices: Callable[..., dict[date, float]],
    *,
    tied: bool = False,
) -> MarketDataReader:
    """Return two Paris funds - rising at the same rate when ``tied``."""
    return make_market(
        {
            "ETF_EU": make_bars("ETF_EU", xpar, prices(100.0, 1.0)),
            "ETF_OTHER": make_bars(
                "ETF_OTHER", xpar, prices(100.0, 1.0) if tied else prices(200.0, 3.0)
            ),
        }
    )


def test_the_same_run_twice_is_the_same_run(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    calendars: CalendarRegistry,
    xpar: TradingCalendar,
    prices: Callable[..., dict[date, float]],
) -> None:
    """Records, fingerprint and configuration, all equal to the last bit."""
    market = two_funds(make_market, make_bars, xpar, prices)
    universe = ("ETF_EU", "ETF_OTHER")

    first = run(market, calendars, BestOne(), universe)
    second = run(market, calendars, BestOne(), universe)

    assert first.records == second.records
    assert first.strategy_fingerprint == second.strategy_fingerprint
    assert first.configuration == second.configuration
    pd.testing.assert_frame_equal(first.frame(), second.frame())
    pd.testing.assert_frame_equal(first.fills(), second.fills())


def test_two_engines_built_apart_from_the_same_inputs_agree(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    calendars: CalendarRegistry,
    xpar: TradingCalendar,
    prices: Callable[..., dict[date, float]],
) -> None:
    """No state hides between two runs: not in the strategy, not in the engine."""
    market = two_funds(make_market, make_bars, xpar, prices)
    weights = {"ETF_EU": 0.6, "ETF_OTHER": 0.4}

    first = run(market, calendars, Fixed(weights), ("ETF_EU", "ETF_OTHER"))
    second = run(market, calendars, Fixed(dict(weights)), ("ETF_EU", "ETF_OTHER"))

    assert first.records == second.records
    assert first.strategy_fingerprint == second.strategy_fingerprint


def test_the_order_of_the_universe_does_not_change_the_result(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    calendars: CalendarRegistry,
    xpar: TradingCalendar,
    prices: Callable[..., dict[date, float]],
) -> None:
    """Two funds tied on every signal: the tie is broken by name, not by the order written.

    A ranking breaks ties in the order its universe is asked in. Handed the
    universe as declared, the same experiment would hold one fund or the other
    depending on how a list was typed.
    """
    market = two_funds(make_market, make_bars, xpar, prices, tied=True)

    forward = run(market, calendars, BestOne(), ("ETF_EU", "ETF_OTHER"))
    backward = run(market, calendars, BestOne(), ("ETF_OTHER", "ETF_EU"))

    assert forward.records == backward.records
    assert forward.configuration == backward.configuration
    held = {name for record in forward.records for name in record.holdings}
    assert held == {"ETF_EU"}


def test_the_order_of_the_weights_does_not_change_the_result(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    calendars: CalendarRegistry,
    xpar: TradingCalendar,
    prices: Callable[..., dict[date, float]],
) -> None:
    """The same target written two ways is one decision, one set of fills, one fingerprint."""
    market = two_funds(make_market, make_bars, xpar, prices)
    universe = ("ETF_EU", "ETF_OTHER")

    forward = run(market, calendars, Fixed({"ETF_EU": 0.3, "ETF_OTHER": 0.7}), universe)
    backward = run(market, calendars, Fixed({"ETF_OTHER": 0.7, "ETF_EU": 0.3}), universe)

    assert forward.records == backward.records
    assert forward.strategy_fingerprint == backward.strategy_fingerprint
