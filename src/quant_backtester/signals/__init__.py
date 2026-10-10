"""Signal research: transform market data into forecasts.

A signal maps information available *strictly before* a decision timestamp to a
numeric score per instrument. Signals never see future bars and never size
positions - that is the portfolio layer's job.

Three properties hold the layer together, and every one of them is a rule the
data below cannot enforce on its own:

**A signal cannot see the future.** It receives a ``PointInTimeReader`` already
fixed at one instant, whose methods take no ``as_of`` argument. There is no
expression a signal can write that reads past it.

**A window of N sessions really is N sessions.** The reader drops a session it
cannot serve rather than returning a ``NaN``, so the last twenty observations
may span twenty-six sessions. ``signals.windows`` checks what was asked for
against the venue calendar and refuses a window that is not it.

**A value that is missing or too old never quietly becomes a usable one.**
Nothing here forward-fills, interpolates or drops an inconvenient point to make
a window valid. Every result carries a status saying which of those cases it is.
"""

from __future__ import annotations

from quant_backtester.signals.base import Signal, SignalResult
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.cross_asset.correlation import ReturnLevelCorrelationSignal
from quant_backtester.signals.cross_asset.relative_residual import RelativeResidualSignal
from quant_backtester.signals.cross_sectional.rank import CrossSectionalRank
from quant_backtester.signals.engine import SignalEngine, SignalRequest
from quant_backtester.signals.level.change import LevelChangeSignal
from quant_backtester.signals.level.vix_relief import VixReliefSignal
from quant_backtester.signals.level.zscore import LevelZScoreSignal
from quant_backtester.signals.models.arima_garch import ArimaGarchForecastSignal
from quant_backtester.signals.models.garch import EwmaVolatilitySignal, GarchVolatilitySignal
from quant_backtester.signals.price.mean_reversion import MeanReversionSignal
from quant_backtester.signals.price.momentum import MomentumSignal
from quant_backtester.signals.price.normalized_pullback import NormalizedPullbackSignal
from quant_backtester.signals.price.returns import ReturnSignal
from quant_backtester.signals.price.trend import (
    MovingAverageCrossSignal,
    MovingAverageTrendSignal,
)
from quant_backtester.signals.risk.drawdown import CurrentDrawdownSignal
from quant_backtester.signals.risk.volatility import RealizedVolatilitySignal
from quant_backtester.signals.snapshot import SignalSnapshot
from quant_backtester.signals.types import (
    PriceBasis,
    SignalStatus,
    SignalUnit,
    WindowMode,
    WindowSpec,
)

__all__ = [
    "ArimaGarchForecastSignal",
    "CrossSectionalRank",
    "CurrentDrawdownSignal",
    "EwmaVolatilitySignal",
    "GarchVolatilitySignal",
    "LevelChangeSignal",
    "LevelZScoreSignal",
    "MeanReversionSignal",
    "MomentumSignal",
    "MovingAverageCrossSignal",
    "MovingAverageTrendSignal",
    "NormalizedPullbackSignal",
    "PriceBasis",
    "RealizedVolatilitySignal",
    "RelativeResidualSignal",
    "ReturnLevelCorrelationSignal",
    "ReturnSignal",
    "Signal",
    "SignalContext",
    "SignalEngine",
    "SignalRequest",
    "SignalResult",
    "SignalSnapshot",
    "SignalStatus",
    "SignalUnit",
    "VixReliefSignal",
    "WindowMode",
    "WindowSpec",
]
