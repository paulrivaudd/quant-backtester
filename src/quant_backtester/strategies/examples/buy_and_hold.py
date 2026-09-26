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

    How it knows what it has bought: the book. Nothing is held on the first
    session of a run, so the target is the purchase in equal parts. Once every
    name is held, the decision is to keep the positions as they are, and no
    order is sent - not the weights of the close restated at the next open,
    which would trade the overnight drift every morning.

    Between the two, the basket is completed (decision D5 of the 2026-09-26
    audit). A name whose first purchase could not go through - no opening
    price, too little cash, a lot too large for its share - is bought at the
    next decision with the cash the book still has, split equally among the
    names still missing; the names already held are kept, and never traded
    back to equal weights. It used to switch to holding as soon as one name
    was held, and a basket of two could stay half in cash for good.
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
        """Buy the basket, complete it with the cash left, then keep it untouched."""
        held = ctx.portfolio.quantities
        missing = [name for name in self.instruments if name not in held]
        if len(missing) == len(self.instruments):
            return ctx.equal_weight(self.instruments)
        if not missing:
            return ctx.hold_positions()
        book = ctx.portfolio
        cash = book.cash / book.equity if book.equity > 0.0 else 0.0
        return ctx.keep_and_buy({name: cash / len(missing) for name in missing})
