"""Portfolio construction: turn signals into target positions.

Handles sizing, risk limits, leverage and turnover constraints. Consumes signal
scores and current holdings; emits target weights or target quantities.

Two things live here and nowhere else. The vocabulary a decision is expressed
in - a target as a fraction of capital, holdings as quantities that exist - and
the limits that decision is held to. Keeping the limits out of the strategy is
what makes them visible: "hold the two best" and "never more than 40% in one
name" are different statements, and a backtest report has to be able to show
what each of them cost.
"""

from __future__ import annotations

from quant_backtester.portfolio.limits import PositionLimits
from quant_backtester.portfolio.targets import Holdings, TargetAllocation

__all__ = ["Holdings", "PositionLimits", "TargetAllocation"]
