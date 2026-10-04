"""Performance and risk analytics on backtest results.

Return and drawdown statistics, cost attribution and the caveats a run has to
be read with. Read-only with respect to backtest state: nothing here advances
time, reads market data or touches a record. A statistic is a function of a
curve, and a curve is what a finished run leaves behind.

Alpha, beta, tracking error and information ratio against a benchmark live in
``relative``: they describe a finished run against a yardstick, and are never
an input to a decision.

Two rules the rest of the layer follows. A figure is reported gross **and**
net, because the difference between them is the whole question of whether a
strategy survives its own turnover. And a figure the run does not support -
a volatility of one session, a year compounded out of a fortnight, a ratio
over a spread of zero - is ``None`` rather than a number nobody could defend.
"""

from __future__ import annotations

from quant_backtester.analytics.attribution import CostAttribution, RunQuality
from quant_backtester.analytics.benchmark_comparison import BenchmarkAlpha, alpha_vs_benchmark
from quant_backtester.analytics.comparison import (
    BenchmarkBasis,
    BenchmarkCurrencyMismatch,
    BenchmarkCurve,
    BenchmarkSpec,
    Comparison,
    compare,
)
from quant_backtester.analytics.config import RETURN_STD_TOLERANCE, AnalyticsConfig
from quant_backtester.analytics.contribution import InstrumentAttribution, InstrumentPnL
from quant_backtester.analytics.curves import (
    Book,
    aligned_equity_curves,
    drawdown_curve,
    elapsed_years,
    equity_curve,
    session_returns,
)
from quant_backtester.analytics.performance import Drawdown, PerformanceStats, max_drawdown
from quant_backtester.analytics.plots import drawdown_figure, equity_figure
from quant_backtester.analytics.quality import (
    QUALITY_V1,
    QualityRules,
    QualityScore,
    quality_score,
)
from quant_backtester.analytics.relative import RelativePerformanceStats
from quant_backtester.analytics.report import PerformanceReport

__all__ = [
    "QUALITY_V1",
    "RETURN_STD_TOLERANCE",
    "AnalyticsConfig",
    "BenchmarkAlpha",
    "BenchmarkBasis",
    "BenchmarkCurrencyMismatch",
    "BenchmarkCurve",
    "BenchmarkSpec",
    "Book",
    "Comparison",
    "CostAttribution",
    "Drawdown",
    "InstrumentAttribution",
    "InstrumentPnL",
    "PerformanceReport",
    "PerformanceStats",
    "QualityRules",
    "QualityScore",
    "RelativePerformanceStats",
    "RunQuality",
    "aligned_equity_curves",
    "alpha_vs_benchmark",
    "compare",
    "drawdown_curve",
    "drawdown_figure",
    "elapsed_years",
    "equity_curve",
    "equity_figure",
    "max_drawdown",
    "quality_score",
    "session_returns",
]
