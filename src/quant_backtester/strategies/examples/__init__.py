"""The catalogued rules, and the reference books they are measured against.

Each of these is short on purpose: the whole point of the layers underneath is
that a decision reads like the reasoning behind it, and that none of the
machinery - calendars, corporate actions, point-in-time reads, fills, costs -
appears in the file.

A module named after a code (``SA1_world_ma20_benchmark`` ...) holds the
strategy the catalogue gives that code to. The three without a code are not
candidates: ``BuyAndHold`` and ``EqualWeightRebalance`` are the references of
every study - the fund held and the even split of the two funds, the gap
between those two being what rebalancing was worth - and ``FixedWeights`` is
the constant-target control of the review diagnostics.
"""

from __future__ import annotations

from quant_backtester.strategies.examples.buy_and_hold import BuyAndHold
from quant_backtester.strategies.examples.equal_weight import EqualWeightRebalance
from quant_backtester.strategies.examples.fixed_weights import FixedWeights
from quant_backtester.strategies.examples.SA1_world_ma20_benchmark import WorldMA20Benchmark
from quant_backtester.strategies.examples.SA2_buffered_dual_momentum import BufferedDualMomentum
from quant_backtester.strategies.examples.SA3_smooth_moving_average import SmoothMovingAverage
from quant_backtester.strategies.examples.SA4_trend_filtered_pullback import TrendFilteredPullback
from quant_backtester.strategies.examples.SA5_relative_residual_tilt import RelativeResidualTilt
from quant_backtester.strategies.examples.SA6_realized_vol_control import RealizedVolControl
from quant_backtester.strategies.examples.SA7_factor_etf_blend import FactorETFBlend
from quant_backtester.strategies.examples.SA8_monetary_carry import MonetaryCarry
from quant_backtester.strategies.examples.SA9_vix_relief_entry import VixReliefEntry
from quant_backtester.strategies.examples.SA11_garch_vol_control import (
    EwmaVolControl,
    GarchVolControl,
)
from quant_backtester.strategies.examples.SA12_arima_garch import ArimaGarch

__all__ = [
    "ArimaGarch",
    "BufferedDualMomentum",
    "BuyAndHold",
    "EqualWeightRebalance",
    "EwmaVolControl",
    "FactorETFBlend",
    "FixedWeights",
    "GarchVolControl",
    "MonetaryCarry",
    "RealizedVolControl",
    "RelativeResidualTilt",
    "SmoothMovingAverage",
    "TrendFilteredPullback",
    "VixReliefEntry",
    "WorldMA20Benchmark",
]
