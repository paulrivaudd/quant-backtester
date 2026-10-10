"""Aim at constant weights, traded back when they leave the common rebalancing band."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.numbers import require_unit_fraction
from quant_backtester.portfolio.targets import WEIGHT_SUM_TOLERANCE, TargetAllocation
from quant_backtester.signals.types import require_identifier
from quant_backtester.strategies.adaptive.rebalance import settle
from quant_backtester.strategies.base import Strategy


@dataclass(frozen=True, slots=True)
class FixedWeights(Strategy):
    """A book whose target weights never change; what is left is cash.

    Attributes
    ----------
    weights : tuple[tuple[str, float], ...]
        ``(instrument, weight)`` pairs: the fraction of equity each fund is
        held at. Together at most one.
    rebalance_band : float
        Largest gap between a weight and its target that sends no order, as
        for every rule of the SA family.
    strategy_id : str
        Name this configuration is recorded under.

    Raises
    ------
    ValueError
        If no fund is named, a name is empty or given twice, a weight is not
        in ``(0, 1]`` or the weights add up to more than the book.

    Notes
    -----
    A constant target with a band, not a constant exposure: between two
    orders the weights held drift with the prices, and an order is sent only
    when one of them is three points from its target. The exposure realised is
    therefore neither exactly the target nor that of a rule this book is set
    beside.

    Used as the control of a rule that moves its exposure - the same funds,
    the same costs, the same band - it gives the result of another executable
    rule. The comparison does not isolate, at an identical exposure, what the
    timing of the rule was worth: the level of exposure, the composition, the
    costs and the path differ as well. It reads no signal, so it is never
    without something to decide on.

    A weight taken from the average a strategy was *seen* to hold is chosen
    after the fact: such a control describes that strategy's past, it is not
    a rule anyone could have set in advance.
    """

    weights: tuple[tuple[str, float], ...]
    rebalance_band: float = 0.03
    strategy_id: str = "fixed_weights"

    def __post_init__(self) -> None:
        """Reject a book that cannot be held as stated."""
        object.__setattr__(
            self, "weights", tuple((str(name), float(weight)) for name, weight in self.weights)
        )
        require_identifier(self.strategy_id, "strategy_id")
        require_unit_fraction(self.rebalance_band, "rebalance_band")
        if not self.weights:
            raise ValueError("hold what? name at least one instrument and its weight")
        for name, weight in self.weights:
            require_identifier(name, "an instrument")
            if not (math.isfinite(weight) and 0.0 < weight <= 1.0):
                raise ValueError(f"the weight of {name} must be in (0, 1], got {weight!r}")
        repeated = sorted(
            name for name, count in Counter(name for name, _ in self.weights).items() if count > 1
        )
        if repeated:
            raise ValueError(f"{', '.join(repeated)} is given more than one weight")
        total = math.fsum(weight for _, weight in self.weights)
        if total > 1.0 + WEIGHT_SUM_TOLERANCE:
            raise ValueError(f"the weights add up to {total}: the book does not borrow")

    def decide(self, ctx: StrategyContext) -> TargetAllocation:
        """Return the constant target, or the book as it stands inside the band."""
        return settle(ctx, dict(self.weights), band=self.rebalance_band, readable=len(self.weights))
