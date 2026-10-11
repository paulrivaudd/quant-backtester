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

Every strategy kept has a code and a label in ``catalogue``, ``SA1 - std MA20``
to ``SA14 - neural allocation``, and its module carries that code:
``SA3_smooth_moving_average``. ``SA13`` and ``SA14`` are not imported here.
``SA13`` is built from a schedule of models calibrated before the run, and
``SA14`` needs PyTorch, an optional dependency (the ``ml`` extra), which the
other strategies must keep importing without: both are reached through the
catalogue or their own module.

The books a study is measured against - the fund held, the even split, a
constant target - are not strategies of the catalogue and live in
``quant_backtester.research.references``.

``GarchVolControl`` (``SA11``) is imported here although its estimator, the
``arch`` package, is optional too (the ``stats`` extra): the class imports
without it, and a run of it stops at ``validate`` with the name of what is
missing. ``EwmaVolControl`` is its control and carries no catalogue code.
"""

from __future__ import annotations

from quant_backtester.strategies.base import Strategy
from quant_backtester.strategies.functional import FunctionalStrategy, strategy
from quant_backtester.strategies.SA1_world_ma20_benchmark import WorldMA20Benchmark
from quant_backtester.strategies.SA2_buffered_dual_momentum import BufferedDualMomentum
from quant_backtester.strategies.SA3_smooth_moving_average import SmoothMovingAverage
from quant_backtester.strategies.SA4_trend_filtered_pullback import TrendFilteredPullback
from quant_backtester.strategies.SA5_relative_residual_tilt import RelativeResidualTilt
from quant_backtester.strategies.SA6_realized_vol_control import RealizedVolControl
from quant_backtester.strategies.SA7_factor_etf_blend import FactorETFBlend
from quant_backtester.strategies.SA8_monetary_carry import MonetaryCarry
from quant_backtester.strategies.SA9_vix_relief_entry import VixReliefEntry
from quant_backtester.strategies.SA10_etf_ensemble import ETFEnsemble
from quant_backtester.strategies.SA11_garch_vol_control import EwmaVolControl, GarchVolControl
from quant_backtester.strategies.SA12_arima_garch import ArimaGarch

__all__ = [
    "ArimaGarch",
    "BufferedDualMomentum",
    "ETFEnsemble",
    "EwmaVolControl",
    "FactorETFBlend",
    "FunctionalStrategy",
    "GarchVolControl",
    "MonetaryCarry",
    "RealizedVolControl",
    "RelativeResidualTilt",
    "SmoothMovingAverage",
    "Strategy",
    "TrendFilteredPullback",
    "VixReliefEntry",
    "WorldMA20Benchmark",
    "strategy",
]
