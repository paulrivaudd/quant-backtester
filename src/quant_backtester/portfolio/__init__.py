"""Portfolio construction: what a book may hold, and what it does hold.

The layer between a strategy's wish and an order. It knows which instruments
can be bought, in which currency the book is kept, what is held and at what
cost, and the limits a decision is held to - and nothing about signals, the
VIX, momentum or why a strategy wanted what it wanted.

Three objects keep three statements apart, because a report has to be able to
show the difference between each of them:

- :class:`TargetAllocation` - what the strategy asked for;
- :class:`ConstrainedTarget` - what the portfolio allowed of it, with every
  cut a limit made named beside it;
- :class:`PortfolioState` - what is actually held, once execution has had its
  say.
"""

from __future__ import annotations

from quant_backtester.portfolio.allocation import (
    ConstrainedTarget,
    PortfolioDecision,
    PortfolioModel,
)
from quant_backtester.portfolio.constraints import (
    CurrencyMismatch,
    CurrencyMismatchInTradingUniverse,
    InadmissibleTarget,
    InvalidTradingUniverse,
    NonTradableInstrument,
    NonTradableInstrumentInTradingUniverse,
    OutsideTradingUniverse,
    UnknownInstrument,
    UnknownInstrumentInTradingUniverse,
    check_admissible,
    check_trading_universe,
)
from quant_backtester.portfolio.holdings import Holding
from quant_backtester.portfolio.limits import LimitAdjustment, PortfolioLimits
from quant_backtester.portfolio.state import (
    PortfolioState,
    UnvaluablePosition,
    ValuationResult,
    value_state,
)
from quant_backtester.portfolio.targets import WEIGHT_SUM_TOLERANCE, TargetAllocation
from quant_backtester.portfolio.view import PortfolioView

__all__ = [
    "WEIGHT_SUM_TOLERANCE",
    "ConstrainedTarget",
    "CurrencyMismatch",
    "CurrencyMismatchInTradingUniverse",
    "Holding",
    "InadmissibleTarget",
    "InvalidTradingUniverse",
    "LimitAdjustment",
    "NonTradableInstrument",
    "NonTradableInstrumentInTradingUniverse",
    "OutsideTradingUniverse",
    "PortfolioDecision",
    "PortfolioLimits",
    "PortfolioModel",
    "PortfolioState",
    "PortfolioView",
    "TargetAllocation",
    "UnknownInstrument",
    "UnknownInstrumentInTradingUniverse",
    "UnvaluablePosition",
    "ValuationResult",
    "check_admissible",
    "check_trading_universe",
    "value_state",
]
