"""Backtest engine: the event loop that ties the layers together.

Walks the trading calendar one decision point at a time, calling data ->
signals -> portfolio -> execution, and records the resulting state. The engine
is the single place allowed to advance time.

The order inside a session is what the layer is really for: the target decided
after one close is filled at the next open, so a decision is never filled at a
price that produced it. And gross and net are reported side by side, being the
same trades with and without what execution took.
"""

from __future__ import annotations

from quant_backtester.backtest.engine import (
    BacktestEngine,
    BacktestRecord,
    BacktestResult,
    Strategy,
    Timetable,
)

__all__ = [
    "BacktestEngine",
    "BacktestRecord",
    "BacktestResult",
    "Strategy",
    "Timetable",
]
