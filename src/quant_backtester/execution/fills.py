"""What the market did with an order, and why an order was not done.

A fill keeps everything an audit needs about one trade: the price the order
was sized against, the price it was done at, and the three costs apart. Both
prices are kept because their difference is the market's share of the cost,
and separating it from the commission is what lets a report say whether a
strategy is dying of fees or of turnover.

A reject is kept with the same care. An order that could not be sent is not an
absence in the record, it is a line: which instrument, which way, how much, and
the reason - no price at the open, a stale one, a trade too small to be worth
sending, not enough cash. A run that quietly dropped those would report a book
that never matched its target without ever saying why.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from quant_backtester.execution.costs import CostBreakdown, CostModel
from quant_backtester.execution.orders import Order, Side
from quant_backtester.numbers import require_finite_non_negative, require_finite_positive
from quant_backtester.signals.types import require_identifier


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
    market_price : float
        The price the order was sized against - the opening auction.
    fill_price : float
        What it was done at, once the spread and the slippage were paid:
        above the market price for a buy, below it for a sale.
    commission : float
        The broker's fee on this order.
    spread_cost : float
        What crossing half the spread took, in currency units.
    slippage_cost : float
        What the order's own impact took, in currency units.
    executed_at : datetime
        When it was done. Timezone-aware.

    Raises
    ------
    ValueError
        If a quantity or a price is not a finite positive number, a cost is
        negative or not finite, the fill price is on the wrong side of the
        market price for the direction of the trade, or the instant is naive.
    """

    instrument_id: str
    side: Side
    quantity: float
    market_price: float
    fill_price: float
    commission: float
    spread_cost: float
    slippage_cost: float
    executed_at: datetime

    def __post_init__(self) -> None:
        """Reject a trade that could not have happened."""
        require_identifier(self.instrument_id, "instrument_id")
        if not isinstance(self.side, Side):
            raise ValueError(f"side must be a Side, got {self.side!r}")
        require_finite_positive(self.quantity, f"the quantity filled in {self.instrument_id}")
        require_finite_positive(self.market_price, f"the market price of {self.instrument_id}")
        require_finite_positive(self.fill_price, f"the fill price of {self.instrument_id}")
        for name in ("commission", "spread_cost", "slippage_cost"):
            require_finite_non_negative(getattr(self, name), f"the {name} of {self.instrument_id}")
        against = (
            self.fill_price >= self.market_price
            if self.side is Side.BUY
            else self.fill_price <= self.market_price
        )
        if not against:
            raise ValueError(
                f"{self.instrument_id}: a {self.side.value} filled at {self.fill_price} against "
                f"a market price of {self.market_price} would be paid to trade"
            )
        if not isinstance(self.executed_at, datetime) or self.executed_at.tzinfo is None:
            raise ValueError(
                f"executed_at must be a timezone-aware datetime, got {self.executed_at!r}"
            )

    @classmethod
    def of(cls, order: Order, market_price: float, costs: CostModel) -> Fill:
        """Return the fill an order is done at, at a market price, under a cost model.

        Parameters
        ----------
        order : Order
            The order, done in full.
        market_price : float
            The price it was sized against.
        costs : CostModel
            What trading costs.

        Returns
        -------
        Fill
            Executed at the instant the order was submitted: a daily model
            fills a market order at the auction it was sent into.
        """
        breakdown = costs.breakdown(order.side, order.quantity, market_price)
        return cls(
            instrument_id=order.instrument_id,
            side=order.side,
            quantity=order.quantity,
            market_price=market_price,
            fill_price=costs.fill_price(order.side, market_price),
            commission=breakdown.commission,
            spread_cost=breakdown.spread_cost,
            slippage_cost=breakdown.slippage_cost,
            executed_at=order.submitted_at,
        )

    @property
    def costs(self) -> CostBreakdown:
        """Return the three costs of this trade together."""
        return CostBreakdown(
            commission=self.commission,
            spread_cost=self.spread_cost,
            slippage_cost=self.slippage_cost,
        )

    @property
    def market_cost(self) -> float:
        """Return what the spread and the slippage took, in currency units."""
        return self.spread_cost + self.slippage_cost

    @property
    def total_cost(self) -> float:
        """Return everything this trade cost: commission, spread and slippage."""
        return math.fsum((self.commission, self.spread_cost, self.slippage_cost))

    @property
    def traded_value(self) -> float:
        """Return the value exchanged, at the fill price."""
        return self.quantity * self.fill_price

    @property
    def market_value(self) -> float:
        """Return the value exchanged, at the market price."""
        return self.quantity * self.market_price

    @property
    def cash_flow(self) -> float:
        """Return the effect on cash: negative for a buy, positive for a sale, fees paid."""
        if self.side is Side.BUY:
            return -(self.traded_value + self.commission)
        return self.traded_value - self.commission

    @property
    def gross_cash_flow(self) -> float:
        """Return the effect on the cash of a book that pays no costs: the market value."""
        return -self.market_value if self.side is Side.BUY else self.market_value


class OrderStatus(Enum):
    """What became of an order sent at the open."""

    FILLED = "FILLED"
    """Done in full."""

    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    """Done for part of its quantity; a reject names the rest and why."""

    REJECTED = "REJECTED"
    """Not done at all; a reject says why."""


class ExecutionRejectReason(Enum):
    """Why an order the target called for was not done, or not in full."""

    NON_TRADABLE = "NON_TRADABLE"
    """The registry declares the instrument ``tradable = false``. The portfolio
    layer refuses such a target before it gets here; this is the last guard, for
    an execution model used on its own."""

    NO_EXECUTION_PRICE = "NO_EXECUTION_PRICE"
    """No price at the execution instant: the instrument is not listed, or the
    venue held the session and no opening print is stored. Nothing is filled
    on a price that does not exist."""

    STALE_EXECUTION_PRICE = "STALE_EXECUTION_PRICE"
    """The latest opening price is from an earlier session - the venue did not
    trade this one, or has not opened yet. Filling on it would put a trade in
    the record at a price nobody could have got that morning."""

    BELOW_MINIMUM_TRADE = "BELOW_MINIMUM_TRADE"
    """The order is worth less than the declared minimum trade value, so it is
    not sent: a commission floor paid to change nothing."""

    INSUFFICIENT_CASH = "INSUFFICIENT_CASH"
    """The book did not hold the cash to pay for the order, or for all of it.
    The purchase is cut down to what the cash can carry, and what was cut is
    this reject."""

    INVALID_QUANTITY = "INVALID_QUANTITY"
    """The position held is not a whole number of the instrument's lots, so no
    order on the lot grid reaches the target. A book built by this engine never
    gets there; one handed to an execution model from outside can."""

    OUTSIDE_TRADING_UNIVERSE = "OUTSIDE_TRADING_UNIVERSE"
    """A purchase of an instrument that is not in the trading universe on the
    execution session - it left between the decision and the open. A sale of
    one is never refused: leaving a universe is exactly when a position must
    be closable."""

    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
    """The instrument is quoted in another currency than the book. Refused by
    the portfolio layer first; this is the last guard, as for
    ``NON_TRADABLE``."""

    NO_DECISION_PRICE = "NO_DECISION_PRICE"
    """Quantities are fixed at the decision's close, and the instrument had no
    close then to fix them on. Not guessed from the open: that would be the
    other sizing model."""


@dataclass(frozen=True, slots=True)
class ExecutionReject:
    """An order the target called for that was not done, or the part of it that was not.

    Attributes
    ----------
    instrument_id : str
        The instrument.
    reason : ExecutionRejectReason
        Why.
    side : Side | None
        Which way the order would have gone. ``None`` when that could not be
        known: without a price, a position that is held and still wanted may
        need a purchase or a sale, and guessing which is exactly what this
        layer does not do.
    requested_quantity : float | None
        Units not traded: the whole order when it was refused, the part cut
        away when it was reduced. ``None`` when there was no price to size it
        at - a missing number is recorded as missing, never as zero.

    Raises
    ------
    ValueError
        If the reason is not an :class:`ExecutionRejectReason`, or a quantity
        is given and is not a finite positive number.
    """

    instrument_id: str
    reason: ExecutionRejectReason
    side: Side | None = None
    requested_quantity: float | None = None

    def __post_init__(self) -> None:
        """Reject a reject that says nothing a report could count."""
        require_identifier(self.instrument_id, "instrument_id")
        if not isinstance(self.reason, ExecutionRejectReason):
            raise ValueError(f"reason must be an ExecutionRejectReason, got {self.reason!r}")
        if self.side is not None and not isinstance(self.side, Side):
            raise ValueError(f"side must be a Side or None, got {self.side!r}")
        if self.requested_quantity is not None:
            require_finite_positive(
                self.requested_quantity, f"the quantity rejected in {self.instrument_id}"
            )
