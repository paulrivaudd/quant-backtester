"""A runner over the synthetic market, as the research layer is handed one."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, time

import pandas as pd
import pytest

from quant_backtester.analytics.config import AnalyticsConfig
from quant_backtester.backtest.runner import StrategyRunner
from quant_backtester.backtest.timetable import BacktestTimetable
from quant_backtester.data.calendars import CalendarRegistry, TradingCalendar
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.execution.costs import CostModel
from quant_backtester.execution.model import ExecutionModel
from quant_backtester.provenance import SourceState, SourceStatus

COMMIT = "0123456789abcdef0123456789abcdef01234567"
"""A full commit id, standing for a clean checkout."""


@pytest.fixture
def research_runner(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    calendars: CalendarRegistry,
    xpar: TradingCalendar,
    prices: Callable[..., dict[date, float]],
) -> StrategyRunner:
    """Return a runner over two rising funds, recording a clean checkout."""
    market = make_market(
        {
            "ETF_EU": make_bars("ETF_EU", xpar, prices(100.0, 1.0)),
            "ETF_OTHER": make_bars("ETF_OTHER", xpar, prices(200.0, 3.0)),
        }
    )
    return StrategyRunner(
        reader=market,
        calendars=calendars,
        reference_calendar_id="XPAR",
        base_currency="EUR",
        analytics=AnalyticsConfig(sessions_per_year=255, risk_free_rate=0.0),
        initial_cash=10_000.0,
        execution=ExecutionModel(costs=CostModel()),
        timetable=BacktestTimetable(
            decision_time=time(23, 0), execution_time=time(9, 1), valuation_time=time(23, 0)
        ),
        source=SourceState(SourceStatus.CLEAN, COMMIT),
    )
