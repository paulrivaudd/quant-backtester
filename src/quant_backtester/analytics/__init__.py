"""Performance and risk analytics on backtest results.

Return and drawdown statistics, cost attribution and the caveats a run has to
be read with. Read-only with respect to backtest state: nothing here advances
time, reads market data or touches a record. A statistic is a function of a
curve, and a curve is what a finished run leaves behind.

Two rules the rest of the layer follows. A figure is reported gross **and**
net, because the difference between them is the whole question of whether a
strategy survives its own turnover. And a figure the run does not support -
a volatility of one session, a year compounded out of a fortnight, a ratio
over a spread of zero - is ``None`` rather than a number nobody could defend.
"""

from __future__ import annotations

from quant_backtester.analytics.attribution import CostAttribution, RunQuality
from quant_backtester.analytics.config import AnalyticsConfig
from quant_backtester.analytics.contribution import InstrumentAttribution, InstrumentPnL
from quant_backtester.analytics.curves import (
    Book,
    drawdown_curve,
    elapsed_years,
    equity_curve,
    session_returns,
)
from quant_backtester.analytics.performance import Drawdown, PerformanceStats, max_drawdown
from quant_backtester.analytics.report import PerformanceReport

__all__ = [
    "AnalyticsConfig",
    "Book",
    "CostAttribution",
    "Drawdown",
    "InstrumentAttribution",
    "InstrumentPnL",
    "PerformanceReport",
    "PerformanceStats",
    "RunQuality",
    "drawdown_curve",
    "elapsed_years",
    "equity_curve",
    "max_drawdown",
    "session_returns",
]
