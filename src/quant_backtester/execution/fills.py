"""Turning a target into trades, at a price and an instant that are declared.

The fill assumption of this layer, stated once here rather than buried in a
loop: **an order decided after the close of session t is filled at the opening
auction of the next session of the execution calendar**. Nothing is filled at
the price that produced the decision, which is the oldest way of inventing
performance - a strategy that buys at the close it just read has already seen
the number it is trading on.

An instrument whose opening price is not knowable at that instant is not
traded. Not skipped quietly: the order is refused and named, and the position
stays where it was. Filling it at yesterday's price would put a trade in the
record at a price nobody could have got.

An order is also never paid for with money the book does not have. A target of
a whole book is sized on the equity before this rebalancing's costs, and the
costs still have to come from somewhere: the buys are cut down to what the cash
can carry, and what was cut is named. The alternative - letting cash go
negative - is a loan the model never granted and never charges for, and it
compounds quietly in any strategy that rebalances often.

An order is placed in the units the venue deals in. Where an instrument
declares a ``quantity_step`` - one whole share for an ETF held in a retail
account - the quantity is cut down to a multiple of it, and what the rounding
leaves stays in cash. Fractional quantities make a backtest allocate its
capital perfectly, which is exactly the small, systematic optimism that turns
into a return the account never sees.

Being worth something and being tradable are two different questions, and this
layer keeps them apart. A position whose opening auction did not print still
has a value - the book has to be worth something for the other orders to be
sized against - and it still cannot be traded. So a rebalancing is given prices
for everything it holds, and told separately which of them may be dealt at.
"""

from __future__ import annotations

import math
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace

from quant_backtester.execution.costs import CostModel, Side
from quant_backtester.numbers import (
    require_finite_non_negative,
    require_finite_positive,
    require_unit_fraction,
)
from quant_backtester.portfolio.targets import Holdings


def _dealable_quantity(quantity: float, step: float | None) -> float:
    """Return the part of ``quantity`` an order may actually be placed for.

    Parameters
    ----------
    quantity : float
        Units wanted, always positive.
    step : float | None
        Smallest dealable number of units, or ``None`` when the instrument is
        dealt in fractions.

    Returns
    -------
    float
        The largest multiple of ``step`` at or below ``quantity``, or
        ``quantity`` itself when there is no step. Never more than was wanted:
        rounding an order up would buy units with money the sizing never set
        aside, and would do it on every line of every rebalancing.

    Notes
    -----
    The multiple is rebuilt as ``lots * step`` rather than kept as the
    remainder of a division, so a hundred whole shares are a hundred and not
    99.999999999999986, and a position closed in full closes to exactly zero.
    """
    if step is None:
        return quantity
    lots = math.floor(quantity / step)
    return lots * step


@dataclass(frozen=True, slots=True)
class Fill:
    """One trade, as it was actually done.

    Attributes
    ----------
    instrument_id : str
        What was traded.
    side : Side
        Which way.
    quantity : float
        Units traded, always positive; ``side`` carries the direction.
    reference_price : float
        The price the order was sized against - the opening auction.
    fill_price : float
        What it was done at, once the spread and the slippage were paid.
    commission : float
        The broker's fee on this order.

    Notes
    -----
    Both prices are kept. Their difference is the market's share of the cost,
    and separating it from the commission is what lets a report say whether a
    strategy is dying of fees or of turnover.
    """

    instrument_id: str
    side: Side
    quantity: float
    reference_price: float
    fill_price: float
    commission: float

    @property
    def traded_value(self) -> float:
        """Return the value exchanged, at the fill price."""
        return self.quantity * self.fill_price

    @property
    def cash_flow(self) -> float:
        """Return the effect on cash: negative for a buy, positive for a sale."""
        signed = -self.traded_value if self.side is Side.BUY else self.traded_value
        return signed - self.commission

    @property
    def market_cost(self) -> float:
        """Return what the spread and the slippage took, in currency units."""
        return abs(self.fill_price - self.reference_price) * self.quantity


@dataclass(frozen=True, slots=True)
class _Order:
    """An order as it is wanted, before the cash has had its say.

    Attributes
    ----------
    instrument_id : str
        What to trade.
    side : Side
        Which way.
    quantity : float
        Units, always positive.
    reference_price : float
        The opening auction the order is sized against.
    fill_price : float
        What it would be done at, spread and slippage included.
    """

    instrument_id: str
    side: Side
    quantity: float
    reference_price: float
    fill_price: float

    @property
    def notional(self) -> float:
        """Return the value this order would exchange, at the fill price."""
        return self.quantity * self.fill_price


@dataclass(frozen=True, slots=True)
class Execution:
    """What one rebalancing did, and what it could not do.

    Attributes
    ----------
    holdings : Holdings
        The state after the trades.
    fills : tuple[Fill, ...]
        The orders that were done, in instrument order.
    untradable : tuple[str, ...]
        Instruments that could not be dealt at this instant - no opening price,
        or one too stale to trade on. Their positions were left exactly as they
        were.
    unfunded : tuple[str, ...]
        Instruments whose buy was cut down, or dropped, because the book did
        not hold the cash to pay for it. Named rather than silently trimmed: a
        strategy that keeps asking for more than it can afford is a strategy
        whose weights do not mean what they say.
    """

    holdings: Holdings
    fills: tuple[Fill, ...]
    untradable: tuple[str, ...]
    unfunded: tuple[str, ...] = ()

    @property
    def commission(self) -> float:
        """Return the total paid to the broker."""
        return sum(fill.commission for fill in self.fills)

    @property
    def market_cost(self) -> float:
        """Return the total paid to the market, spread and slippage together."""
        return sum(fill.market_cost for fill in self.fills)

    @property
    def cost(self) -> float:
        """Return everything this rebalancing cost."""
        return self.commission + self.market_cost

    @property
    def traded_value(self) -> float:
        """Return the total value exchanged, both directions counted."""
        return sum(fill.traded_value for fill in self.fills)


@dataclass(frozen=True, slots=True)
class ExecutionModel:
    """Fills a rebalancing at the opening auction, paying the declared costs.

    Attributes
    ----------
    costs : CostModel
        Commission, spread and slippage.
    minimum_trade_value : float
        Orders below this value are not sent. A rebalancing that moves a
        position by a few currency units pays a commission floor to change
        nothing, and a backtest without this threshold spends its return on
        noise no one would have traded.

    Raises
    ------
    ValueError
        If ``minimum_trade_value`` is not a finite number of zero or more. A
        threshold of ``NaN`` compares false against every order and would
        silently send them all.
    """

    costs: CostModel = field(default_factory=CostModel)
    minimum_trade_value: float = 0.0

    def __post_init__(self) -> None:
        """Reject a threshold that is not a value."""
        require_finite_non_negative(self.minimum_trade_value, "minimum_trade_value")

    def rebalance(
        self,
        holdings: Holdings,
        weights: Mapping[str, float],
        prices: Mapping[str, float],
        tradable: Collection[str] | None = None,
        quantity_steps: Mapping[str, float] | None = None,
    ) -> Execution:
        """Trade towards the target weights, at the given opening prices.

        Parameters
        ----------
        holdings : Holdings
            What is held before the trades.
        weights : Mapping[str, float]
            Target fraction of equity per instrument. An instrument absent from
            it is a target of zero: the position is closed.
        prices : Mapping[str, float]
            Price per instrument, used both to value the book and to size and
            fill the orders. It must cover everything held.
        tradable : Collection[str] | None
            Which of those instruments may actually be dealt at. ``None`` means
            all of them. A position whose opening auction did not print is
            valued at the price given here and left alone, which is not the
            same thing as being worth nothing.
        quantity_steps : Mapping[str, float] | None
            Smallest dealable number of units, per instrument. An instrument
            absent from it is dealt in fractions. The rounding is always
            downwards, in both directions: an order is never enlarged to reach
            a round lot, because the cash to pay for the extra units was not
            there.

        Returns
        -------
        Execution
            The state after the trades, the fills, and what could not be traded.

        Raises
        ------
        KeyError
            If a position is held and no price is given for it. The equity
            cannot be computed, and sizing every other order against a guess
            about it would be worse than stopping.
        ValueError
            If a target weight is not a finite fraction of ``[0, 1]``. A
            :class:`~quant_backtester.portfolio.targets.TargetAllocation`
            already refuses one, and this layer checks again because it is the
            layer that would turn it into a short: a negative weight is a
            negative target quantity, and the sale that reaches it from an
            empty position is a borrow nobody granted.

        Notes
        -----
        Equity is measured before any of this rebalancing's costs. Sizing on
        the equity left after them would make every order depend on the ones
        computed before it, and on the order they happened to be computed in.

        The sales are done first, because they are what pays for the purchases,
        and the purchases are then cut to the cash there actually is. A target
        of a whole book therefore ends a little under it: the difference is
        what execution charged, and it comes out of the position rather than
        out of a loan nobody granted.

        A purchase cut below the declared minimum is dropped, and the cash it
        would have taken is not offered back to the others. Redistributing it
        would size one order on whether another turned out too small to send,
        and a rebalancing whose result depends on the order its names happen to
        be considered in is not one anybody can reproduce.
        """
        for instrument_id, weight in weights.items():
            require_unit_fraction(weight, f"the target weight of {instrument_id}")
        equity = holdings.value_at(prices)
        dealable = set(prices) if tradable is None else set(tradable) & set(prices)
        wanted = set(weights) | set(holdings.quantities)
        untradable = tuple(sorted(name for name in wanted if name not in dealable))
        quantities = dict(holdings.quantities)
        cash = holdings.cash
        steps = dict(quantity_steps or {})
        for instrument_id, step in steps.items():
            require_finite_positive(step, f"the quantity step of {instrument_id}")
        orders = self._orders(equity, weights, prices, quantities, sorted(wanted & dealable), steps)

        fills = [self._fill(order) for order in orders if order.side is Side.SELL]
        for fill in fills:
            cash += fill.cash_flow
            quantities[fill.instrument_id] = quantities.get(fill.instrument_id, 0.0) - fill.quantity

        buys = [order for order in orders if order.side is Side.BUY]
        scale = self._affordable_scale(buys, cash)
        unfunded: list[str] = []
        for order in buys:
            afforded = replace(
                order,
                quantity=_dealable_quantity(order.quantity * scale, steps.get(order.instrument_id)),
            )
            # A trimmed order of nothing is not an order, and with no declared
            # minimum it would otherwise be sent as a fill of zero units.
            if afforded.quantity == 0.0 or afforded.notional < self.minimum_trade_value:
                unfunded.append(order.instrument_id)
                continue
            if scale < 1.0:
                unfunded.append(order.instrument_id)
            fill = self._fill(afforded)
            fills.append(fill)
            cash += fill.cash_flow
            quantities[order.instrument_id] = (
                quantities.get(order.instrument_id, 0.0) + fill.quantity
            )

        return Execution(
            holdings=Holdings(cash=cash, quantities=quantities),
            fills=tuple(sorted(fills, key=lambda fill: fill.instrument_id)),
            untradable=untradable,
            unfunded=tuple(sorted(unfunded)),
        )

    def _orders(
        self,
        equity: float,
        weights: Mapping[str, float],
        prices: Mapping[str, float],
        quantities: Mapping[str, float],
        dealable: Sequence[str],
        steps: Mapping[str, float],
    ) -> list[_Order]:
        """Return the order each instrument needs to reach its target weight.

        Parameters
        ----------
        equity : float
            The book's worth before this rebalancing's costs.
        weights : Mapping[str, float]
            Target fraction of equity per instrument.
        prices : Mapping[str, float]
            The reference price - the opening auction - per instrument.
        quantities : Mapping[str, float]
            What is held before the trades.
        dealable : Sequence[str]
            The instruments that may be traded, in the order to build them in.
        steps : Mapping[str, float]
            Smallest dealable number of units, for the instruments that have
            one.

        Returns
        -------
        list[_Order]
            One per instrument that has something to do worth doing. An order
            below the declared minimum is not one, and neither is one that
            rounds down to no units at all.
        """
        orders: list[_Order] = []
        for instrument_id in dealable:
            reference = prices[instrument_id]
            target = equity * weights.get(instrument_id, 0.0) / reference
            delta = target - quantities.get(instrument_id, 0.0)
            if delta == 0.0:
                continue
            side = Side.BUY if delta > 0 else Side.SELL
            quantity = _dealable_quantity(abs(delta), steps.get(instrument_id))
            if quantity == 0.0:
                continue
            order = _Order(
                instrument_id=instrument_id,
                side=side,
                quantity=quantity,
                reference_price=reference,
                fill_price=self.costs.fill_price(side, reference),
            )
            if order.notional < self.minimum_trade_value:
                continue
            orders.append(order)
        return orders

    def _fill(self, order: _Order) -> Fill:
        """Return the fill an order is done at, commission included."""
        return Fill(
            instrument_id=order.instrument_id,
            side=order.side,
            quantity=order.quantity,
            reference_price=order.reference_price,
            fill_price=order.fill_price,
            commission=self.costs.commission(order.notional),
        )

    def _cash_needed(self, buys: Sequence[_Order], scale: float) -> float:
        """Return what buying ``scale`` of every order would take out of cash.

        Notes
        -----
        Each notional is computed the way the fill will compute it - the
        quantity is scaled and then priced, not priced and then scaled - so
        that what was found affordable is what is afterwards paid, to the last
        bit. The other order of the same two multiplications differs by an ulp,
        and an ulp below zero is still a book that borrowed.
        """
        needed = 0.0
        for order in buys:
            notional = replace(order, quantity=order.quantity * scale).notional
            needed += notional + self.costs.commission(notional)
        return needed

    def _affordable_scale(self, buys: Sequence[_Order], cash: float) -> float:
        """Return the largest fraction of the purchases the cash can carry.

        Parameters
        ----------
        buys : Sequence[_Order]
            The purchases this rebalancing wants, at full size.
        cash : float
            What is left after the sales.

        Returns
        -------
        float
            ``1.0`` when everything fits, ``0.0`` when nothing does, and the
            fraction in between otherwise. Every order is cut by the same
            fraction, so the book keeps the proportions the strategy asked
            for - cutting one name to the bone to leave another whole would be
            a decision about the strategy, and this layer does not take those.

        Notes
        -----
        Found by bisection rather than by formula. A commission floor does not
        scale with the order it is charged on, so the cash a set of purchases
        needs is piecewise linear in their size and has no closed form. It is
        monotonic, which is all a bisection needs, and fifty halvings take the
        answer well past the precision of the numbers it is made of.
        """
        if not buys:
            return 1.0
        if self._cash_needed(buys, 1.0) <= cash:
            return 1.0
        if cash <= 0.0:
            return 0.0
        low, high = 0.0, 1.0
        for _ in range(50):
            middle = (low + high) / 2.0
            if self._cash_needed(buys, middle) <= cash:
                low = middle
            else:
                high = middle
        return low
