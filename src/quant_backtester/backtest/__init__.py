"""Backtest engine: the event loop that ties the layers together.

Walks the reference calendar one session at a time, calling data -> signals ->
strategy -> portfolio -> execution, and records every step. The engine is the
single place allowed to advance time.

It also holds what a decision is made of - the context a strategy is handed,
the market façade inside it, and the calendar of sessions a strategy is asked
on - because the engine builds those, and a lower layer never imports a higher
one. The runner beside it is the exception, and says so.

The order inside a session is what the layer is really for, and it is declared
in a :class:`BacktestTimetable`: the target decided after one close is filled
at the next open, so a decision is never filled at a price that produced it.
Gross and net are reported side by side, being the same trades with and
without what execution took.
"""

from __future__ import annotations

from quant_backtester.backtest.config import BacktestConfig
from quant_backtester.backtest.context import Selection, StrategyContext
from quant_backtester.backtest.engine import (
    BacktestEngine,
    Strategy,
    StrategyMutated,
    UnsupportedCorporateAction,
)
from quant_backtester.backtest.market import (
    MarketObservation,
    MarketWindow,
    StrategyMarketView,
)
from quant_backtester.backtest.records import BacktestRecord
from quant_backtester.backtest.result import BacktestResult
from quant_backtester.backtest.schedule import (
    DecisionSchedule,
    EveryNSessions,
    EverySession,
    Monthly,
    Weekly,
)
from quant_backtester.backtest.timetable import BacktestTimetable, ExecutionTiming

__all__ = [
    "BacktestConfig",
    "BacktestEngine",
    "BacktestRecord",
    "BacktestResult",
    "BacktestTimetable",
    "DecisionSchedule",
    "EveryNSessions",
    "EverySession",
    "ExecutionTiming",
    "MarketObservation",
    "MarketWindow",
    "Monthly",
    "Selection",
    "Strategy",
    "StrategyContext",
    "StrategyMarketView",
    "StrategyMutated",
    "UnsupportedCorporateAction",
    "Weekly",
]
