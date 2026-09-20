"""Hold the same book in equal parts, and put it back there at every decision."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.signals.types import require_identifier
from quant_backtester.strategies.base import Strategy


@dataclass(frozen=True, slots=True)
class EqualWeightRebalance(Strategy):
    """Hold the named instruments in equal parts, restated at every decision.

    Attributes
    ----------
    instruments : tuple[str, ...]
        What to hold. Every one of them must be in the session's universe and
        tradable, which the helper checks.
    strategy_id : str
        Name this configuration is recorded under.

    Raises
    ------
    ValueError
        If no instrument is named, a name is empty, or a name appears twice -
        which would give it two shares of the book under one weight.

    Notes
    -----
    This is **not** buy and hold, and the difference is the whole point of
    having both. Buying two funds at half each and leaving them alone lets the
    winner grow into two thirds of the book; restating the target at every
    decision sells the winner and buys the loser to get back to half. The two
    hold different books, pay different amounts of turnover, and one of them
    has a rebalancing premium the other does not.

    So it is the constant-weight baseline: what an investor who rebalances
    religiously would have had, costs included. :class:`BuyAndHold` is the one
    that does nothing after the first purchase, and the gap between the two is
    what rebalancing was worth over the period.
    """

    instruments: tuple[str, ...]
    strategy_id: str = "equal_weight_rebalance"

    def __post_init__(self) -> None:
        """Reject a book that cannot be held as stated."""
        require_identifier(self.strategy_id, "strategy_id")
        if not self.instruments:
            raise ValueError("hold what? name at least one instrument")
        for instrument_id in self.instruments:
            require_identifier(instrument_id, "an instrument")
        repeated = sorted(name for name, count in Counter(self.instruments).items() if count > 1)
        if repeated:
            raise ValueError(
                f"{', '.join(repeated)} is named more than once; a book holds one "
                "position per instrument"
            )

    def decide(self, ctx: StrategyContext) -> TargetAllocation:
        """Return the same equally weighted book at every decision."""
        return ctx.equal_weight(self.instruments)
