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

Being worth something and being tradable are two different questions, and this
layer keeps them apart. A position whose opening auction did not print still
has a value - the book has to be worth something for the other orders to be
sized against - and it still cannot be traded. So a rebalancing is given prices
for everything it holds, and told separately which of them may be dealt at.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field

from quant_backtester.execution.costs import CostModel, Side
from quant_backtester.portfolio.targets import Holdings


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
    """

    holdings: Holdings
    fills: tuple[Fill, ...]
    untradable: tuple[str, ...]

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
        If ``minimum_trade_value`` is negative.
    """

    costs: CostModel = field(default_factory=CostModel)
    minimum_trade_value: float = 0.0

    def __post_init__(self) -> None:
        """Reject a threshold that is not a value."""
        if self.minimum_trade_value < 0:
            raise ValueError(
                f"minimum_trade_value must not be negative, got {self.minimum_trade_value}"
            )

    def rebalance(
        self,
        holdings: Holdings,
        weights: Mapping[str, float],
        prices: Mapping[str, float],
        tradable: Collection[str] | None = None,
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

        Notes
        -----
        Equity is measured before any of this rebalancing's costs. Sizing on
        the equity left after them would make every order depend on the ones
        computed before it, and on the order they happened to be computed in.
        """
        equity = holdings.value_at(prices)
        dealable = set(prices) if tradable is None else set(tradable) & set(prices)
        wanted = set(weights) | set(holdings.quantities)
        untradable = tuple(sorted(name for name in wanted if name not in dealable))
        quantities = dict(holdings.quantities)
        cash = holdings.cash
        fills: list[Fill] = []

        for instrument_id in sorted(wanted & dealable):
            reference = prices[instrument_id]
            target = equity * weights.get(instrument_id, 0.0) / reference
            delta = target - quantities.get(instrument_id, 0.0)
            side = Side.BUY if delta > 0 else Side.SELL
            fill_price = self.costs.fill_price(side, reference)
            if abs(delta) * fill_price < self.minimum_trade_value or delta == 0.0:
                continue
            fill = Fill(
                instrument_id=instrument_id,
                side=side,
                quantity=abs(delta),
                reference_price=reference,
                fill_price=fill_price,
                commission=self.costs.commission(abs(delta) * fill_price),
            )
            fills.append(fill)
            cash += fill.cash_flow
            quantities[instrument_id] = quantities.get(instrument_id, 0.0) + delta

        return Execution(
            holdings=Holdings(cash=cash, quantities=quantities),
            fills=tuple(fills),
            untradable=untradable,
        )
