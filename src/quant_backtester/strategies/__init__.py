"""Concrete strategies composed from the building blocks above.

Each strategy is a declarative configuration (universe, signals, portfolio
rules, execution assumptions) plus any strategy-specific glue code.

A strategy receives a
:class:`~quant_backtester.backtest.context.StrategyContext` and nothing else.
Not a reader, not a repository, not a calendar: holding one of those, it could
write its own ``tail(20)`` and get twenty observations spanning twenty-six
sessions, or read a price it had no business seeing at the instant it was
deciding. What it gets instead is the signals of that instant, a market façade
whose every reading carries its status and its age, the book as it stands, and
the names it is allowed to hold - all fixed at one instant, with no method
anywhere that takes another.

The context is defined beside the engine rather than here, because the engine
builds one per session and a lower layer never imports a higher one.
"""

from __future__ import annotations

from quant_backtester.strategies.base import Strategy
from quant_backtester.strategies.examples import (
    BuyAndHold,
    MomentumRotation,
    MomentumSingleAsset,
    MomentumVix,
)
from quant_backtester.strategies.functional import FunctionalStrategy, strategy
from quant_backtester.strategies.risk_gated import RiskGatedRotation
from quant_backtester.strategies.rotation import TopRankRotation

__all__ = [
    "BuyAndHold",
    "FunctionalStrategy",
    "MomentumRotation",
    "MomentumSingleAsset",
    "MomentumVix",
    "RiskGatedRotation",
    "Strategy",
    "TopRankRotation",
    "strategy",
]
