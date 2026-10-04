"""Strategies written the way a user is meant to write one.

Each of these is short on purpose: the whole point of the layers underneath is
that a decision reads like the reasoning behind it, and that none of the
machinery - calendars, corporate actions, point-in-time reads, fills, costs -
appears in the file.

They are also the smallest honest examples of four different shapes. Buy and
hold needs no signal at all, and neither does the constant-weight baseline
beside it - the gap between those two *is* what rebalancing was worth. A
single-asset momentum needs one signal, and a rule about what to do when it
cannot be computed. A rotation needs a ranking, and a decision about how many
names to hold when fewer are usable than wanted. And a gated rotation needs two
universes at one instant.
"""

from __future__ import annotations

from quant_backtester.strategies.examples.buffered_dual_momentum import BufferedDualMomentum
from quant_backtester.strategies.examples.buy_and_hold import BuyAndHold
from quant_backtester.strategies.examples.equal_weight import EqualWeightRebalance
from quant_backtester.strategies.examples.factor_etf_blend import FactorETFBlend
from quant_backtester.strategies.examples.golden_cross_etf import GoldenCrossETF
from quant_backtester.strategies.examples.momentum_rotation import MomentumRotation
from quant_backtester.strategies.examples.momentum_single_asset import MomentumSingleAsset
from quant_backtester.strategies.examples.momentum_vix import MomentumVix
from quant_backtester.strategies.examples.monetary_carry import MonetaryCarry
from quant_backtester.strategies.examples.moving_average_band import MovingAverageBandETF
from quant_backtester.strategies.examples.moving_average_cross import MovingAverageCross
from quant_backtester.strategies.examples.moving_average_entry_exit import (
    MovingAverageEntryExitETF,
)
from quant_backtester.strategies.examples.rate_regime_trend import RateRegimeTrend
from quant_backtester.strategies.examples.realized_vol_control import RealizedVolControl
from quant_backtester.strategies.examples.relative_residual_tilt import RelativeResidualTilt
from quant_backtester.strategies.examples.smooth_moving_average import SmoothMovingAverage
from quant_backtester.strategies.examples.trend_filtered_pullback import TrendFilteredPullback
from quant_backtester.strategies.examples.vix_relief_entry import VixReliefEntry
from quant_backtester.strategies.examples.world_ma20_benchmark import WorldMA20Benchmark

__all__ = [
    "BufferedDualMomentum",
    "BuyAndHold",
    "EqualWeightRebalance",
    "FactorETFBlend",
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
    "TrendFilteredPullback",
    "VixReliefEntry",
    "WorldMA20Benchmark",
]
