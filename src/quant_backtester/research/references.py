"""The books a study measures a strategy against: the fund held, the even split, a constant target.

None of the three is a candidate, and none has a catalogue code. ``BuyAndHold``
is the reference of every study - the fund bought once, under the same costs,
lots and cash as the strategy it is compared with. ``EqualWeightRebalance`` is
the same basket put back to equal parts at every decision: the gap between
those two is what rebalancing was worth. ``FixedWeights`` aims at constant
weights inside the common rebalancing band, and is the control a rule that
moves its exposure is read beside.

They are written like any strategy and run by the same engine, so that a
comparison is between two books that could both have been held. They live here
and not among the strategies because a reference is part of how an experiment
is read, not something the experiment is about.
"""

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
        return ctx.keep_and_buy({name: 1.0 / len(missing) for name in missing})


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
