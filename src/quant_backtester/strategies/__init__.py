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

Every strategy exported here is runnable as it stands: it declares the signals
it reads, so ``runner.run(strategy, universe, start, end)`` is the whole of
what a user has to write. A rule that needed its signals wired in from outside
would look identical in an import list and fail at the first decision, which is
why there is no such thing here any more.

The strategies that are kept have a code and a label in ``catalogue``:
``SA1 - std MA20``, ``ML1 - neural allocation``. The ML family lives in
``strategies.ml`` and is not imported here: it needs PyTorch, an optional
dependency, and is reached through the catalogue or its own module.

``GarchVolControl`` (``SA11``) is imported here although its estimator, the
``arch`` package, is optional too (the ``stats`` extra): the class imports
without it, and a run of it stops at ``validate`` with the name of what is
missing. ``EwmaVolControl`` is its control and carries no catalogue code.
"""

from __future__ import annotations

from quant_backtester.strategies.adaptive.etf_ensemble import ETFEnsemble
from quant_backtester.strategies.base import Strategy
from quant_backtester.strategies.examples import (
    ArimaGarch,
    BufferedDualMomentum,
    BuyAndHold,
    EqualWeightRebalance,
    EwmaVolControl,
    FactorETFBlend,
    FixedWeights,
    GarchVolControl,
    GoldenCrossETF,
    MomentumRotation,
    MomentumSingleAsset,
    MomentumVix,
    MonetaryCarry,
    MovingAverageBandETF,
    MovingAverageCross,
    MovingAverageEntryExitETF,
    RateRegimeTrend,
    RealizedVolControl,
    RelativeResidualTilt,
    SmoothMovingAverage,
    TrendFilteredPullback,
    VixReliefEntry,
    WorldMA20Benchmark,
)
from quant_backtester.strategies.functional import FunctionalStrategy, strategy

__all__ = [
    "ArimaGarch",
    "BufferedDualMomentum",
    "BuyAndHold",
    "ETFEnsemble",
    "EqualWeightRebalance",
    "EwmaVolControl",
    "FactorETFBlend",
    "FixedWeights",
    "FunctionalStrategy",
    "GarchVolControl",
    "GoldenCrossETF",
    "MomentumRotation",
    "MomentumSingleAsset",
    "MomentumVix",
    "MonetaryCarry",
    "MovingAverageBandETF",
    "MovingAverageCross",
    "MovingAverageEntryExitETF",
    "RateRegimeTrend",
    "RealizedVolControl",
    "RelativeResidualTilt",
    "SmoothMovingAverage",
    "Strategy",
    "TrendFilteredPullback",
    "VixReliefEntry",
    "WorldMA20Benchmark",
    "strategy",
]
