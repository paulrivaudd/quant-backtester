"""Strategies written the way a user is meant to write one.

Each of these is short on purpose: the whole point of the layers underneath is
that a decision reads like the reasoning behind it, and that none of the
machinery - calendars, corporate actions, point-in-time reads, fills, costs -
appears in the file.

They are also the smallest honest examples of three different shapes. Buy and
hold needs no signal at all. A single-asset momentum needs one, and a rule
about what to do when it cannot be computed. A rotation needs a ranking, and a
decision about how many names to hold when fewer are usable than wanted.
"""

from __future__ import annotations

from quant_backtester.strategies.examples.buy_and_hold import BuyAndHold
from quant_backtester.strategies.examples.momentum_rotation import MomentumRotation
from quant_backtester.strategies.examples.momentum_single_asset import MomentumSingleAsset
from quant_backtester.strategies.examples.momentum_vix import MomentumVix

__all__ = ["BuyAndHold", "MomentumRotation", "MomentumSingleAsset", "MomentumVix"]
