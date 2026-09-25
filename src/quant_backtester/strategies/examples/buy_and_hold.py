"""Buy once, then leave it alone: the baseline every other strategy is judged against."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.signals.types import require_identifier
from quant_backtester.strategies.base import Strategy


@dataclass(frozen=True, slots=True)
class BuyAndHold(Strategy):
    """Buy the named instruments in equal parts once, and never trade again.

    Attributes
    ----------
    instruments : tuple[str, ...]
        What to buy. Every one of them must be in the session's universe and
        tradable, which the helper checks.
    strategy_id : str
        Name this configuration is recorded under.

    Raises
    ------
    ValueError
        If no instrument is named, a name is empty, or a name appears twice.

    Notes
    -----
    It reads no signal, which is what makes it the useful baseline: a strategy
    that does not beat it after costs is an expensive way of holding the same
    thing.

    The distinction from :class:`EqualWeightRebalance` is deliberate and it is
    not cosmetic. Here the weights are allowed to drift: two funds bought at
    half each, one of which doubles, end at two thirds and one third, and
    nothing is done about it. That is what "hold" means, and it is why this
    strategy pays for exactly one rebalancing over a run of any length.

    How it knows it has already bought: the book. Nothing is held on the first
    session of a run, so the target is the purchase; from the moment a position
    exists, the decision is to keep the positions as they are, and no order is
    sent - not the weights of the close restated at the next open, which would
    trade the overnight drift every morning. If that first order could not be
    sent - no opening price, not enough cash - nothing is held, and the
    purchase is simply attempted again at the next decision.
    """

    instruments: tuple[str, ...]
    strategy_id: str = "buy_and_hold"

    def __post_init__(self) -> None:
        """Reject a book that cannot be held as stated."""
        require_identifier(self.strategy_id, "strategy_id")
        if not self.instruments:
            raise ValueError("buy and hold what? name at least one instrument")
        for instrument_id in self.instruments:
            require_identifier(instrument_id, "an instrument")
        repeated = sorted(name for name, count in Counter(self.instruments).items() if count > 1)
        if repeated:
            raise ValueError(
                f"{', '.join(repeated)} is named more than once; a book holds one "
                "position per instrument"
            )

    def decide(self, ctx: StrategyContext) -> TargetAllocation:
        """Buy while the book is empty, then keep what is there without trading."""
        if not ctx.portfolio.quantities:
            return ctx.equal_weight(self.instruments)
        return ctx.hold_positions()
