"""Turning an admissible target into orders, and orders into fills.

The fill assumption of this layer, stated once here rather than buried in a
loop: **an order is a market order sent just after the opening auction of the
execution session, sized against that auction's price and filled at it, moved
against the trader by the half spread and the slippage.** The engine decides
which session that is; this module only ever sees one instant, the prices
knowable at it, and the book as it stands.

Being worth something and being tradable are two different questions, and this
layer keeps them apart. A position whose opening auction did not print is still
worth something - the book has to be valued for the other orders to be sized
against it - and it still cannot be traded. So every line the target touches
comes with its observation, and only an opening price of the session itself is
ever filled on: a stale one is a price nobody could have got that morning, and
a missing one is no price at all. Valuation may estimate; execution never does.

The sequence, in full:

1. the book is valued at the execution instant - the opening price where one
   printed, the last known price otherwise - and that equity, before any of
   this rebalancing's costs, sizes every line;
2. each line becomes an order, a reject, or nothing (see
   :meth:`ExecutionModel.rebalance`): a purchase is sized at the price it will
   be paid, a target position is rounded down to whole lots, an order worth
   less than the minimum is not sent;
3. the sales are done first, because they pay for the purchases;
4. the purchases are cut to the cash there is, all by the same factor, and
   what was cut is named.

Nothing is ever bought with cash the book does not hold, and nothing is sold
that it does not own.
"""

from __future__ import annotations

import math
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime

from quant_backtester.data.instruments import InstrumentRegistry
from quant_backtester.data.reader import Observation, ObservationStatus
from quant_backtester.execution.costs import CostModel
from quant_backtester.execution.fills import (
    ExecutionReject,
    ExecutionRejectReason,
    Fill,
    OrderStatus,
)
from quant_backtester.execution.orders import Order, Side
from quant_backtester.execution.rounding import LOT_TOLERANCE, is_whole_lots, whole_lots
from quant_backtester.numbers import require_finite_non_negative, require_unit_fraction
from quant_backtester.portfolio.state import PortfolioState, UnvaluablePosition
from quant_backtester.portfolio.targets import WEIGHT_SUM_TOLERANCE


@dataclass(frozen=True, slots=True)
class Execution:
    """What one rebalancing did, and what it could not do.

    Attributes
    ----------
    at : datetime
        The execution instant.
    state : PortfolioState
        The book after the trades.
    equity : float
        What the book was worth at the execution instant, before any of this
        rebalancing's costs: the amount every target weight was a fraction of.
    orders : tuple[Order, ...]
        Every order the target called for, sales first and then purchases,
        each in instrument order - the order they were executed in.
    fills : tuple[Fill, ...]
        What was done, in the same order.
    rejects : tuple[ExecutionReject, ...]
        What was not, or not in full, and why - in instrument order.
    """

    at: datetime
    state: PortfolioState
    equity: float
    orders: tuple[Order, ...] = ()
    fills: tuple[Fill, ...] = ()
    rejects: tuple[ExecutionReject, ...] = ()

    def __post_init__(self) -> None:
        """Freeze what was recorded."""
        require_finite_non_negative(self.equity, "equity")
        object.__setattr__(self, "orders", tuple(self.orders))
        object.__setattr__(self, "fills", tuple(self.fills))
        object.__setattr__(self, "rejects", tuple(self.rejects))

    @property
    def commission(self) -> float:
        """Return the total paid to the broker."""
        return math.fsum(fill.commission for fill in self.fills)

    @property
    def spread_cost(self) -> float:
        """Return the total paid for crossing the spread."""
        return math.fsum(fill.spread_cost for fill in self.fills)

    @property
    def slippage_cost(self) -> float:
        """Return the total lost to the orders' own impact."""
        return math.fsum(fill.slippage_cost for fill in self.fills)

    @property
    def market_cost(self) -> float:
        """Return the total paid to the market, spread and slippage together."""
        return math.fsum(fill.market_cost for fill in self.fills)

    @property
    def total_cost(self) -> float:
        """Return everything this rebalancing cost."""
        return math.fsum(fill.total_cost for fill in self.fills)

    @property
    def traded_value(self) -> float:
        """Return the total value exchanged at the fill price, both directions counted."""
        return math.fsum(fill.traded_value for fill in self.fills)

    @property
    def gross_cash_flow(self) -> float:
        """Return what the same trades did to the cash of a book that pays no costs."""
        return math.fsum(fill.gross_cash_flow for fill in self.fills)

    def status(self, instrument_id: str) -> OrderStatus | None:
        """Return what became of the order in one instrument.

        Parameters
        ----------
        instrument_id : str
            Instrument to look up.

        Returns
        -------
        OrderStatus | None
            ``None`` when no order was built for it - nothing to do, or a
            reject before any order could be sized.
        """
        ordered = [order for order in self.orders if order.instrument_id == instrument_id]
        if not ordered:
            return None
        wanted = math.fsum(order.quantity for order in ordered)
        done = math.fsum(
            fill.quantity for fill in self.fills if fill.instrument_id == instrument_id
        )
        if done == 0.0:
            return OrderStatus.REJECTED
        if done < wanted:
            return OrderStatus.PARTIALLY_FILLED
        return OrderStatus.FILLED


@dataclass(frozen=True, slots=True)
class _Line:
    """An order with what it takes to fill it."""

    order: Order
    market_price: float
    step: float | None


@dataclass(frozen=True, slots=True)
class ExecutionModel:
    """Fills a rebalancing at the opening auction, paying the declared costs.

    Attributes
    ----------
    costs : CostModel
        Commission, spread and slippage. Required: a run reports no return
        without a cost model attached, and a default of zero would be one
        attached without anyone having said so.
    minimum_trade_value : float
        Orders worth less than this, at the fill price, are not sent. A
        rebalancing that moves a position by a few currency units pays a
        commission floor to change nothing, and a backtest without this
        threshold spends its return on noise no one would have traded.

    Raises
    ------
    ValueError
        If ``minimum_trade_value`` is not a finite number of zero or more. A
        threshold of ``NaN`` compares false against every order and would
        silently send them all.
    """

    costs: CostModel
    minimum_trade_value: float = 0.0

    def __post_init__(self) -> None:
        """Reject a threshold that is not a value, or a cost model that is not one."""
        if not isinstance(self.costs, CostModel):
            raise ValueError(f"costs must be a CostModel, got {self.costs!r}")
        require_finite_non_negative(self.minimum_trade_value, "minimum_trade_value")

    def definition(self) -> dict[str, object]:
        """Return the model as it is recorded with a run."""
        return {
            "fill": "market order at the opening auction, sized at its price",
            "costs": self.costs.definition(),
            "minimum_trade_value": self.minimum_trade_value,
        }

    def rebalance(
        self,
        state: PortfolioState,
        target: Mapping[str, float],
        *,
        at: datetime,
        session: date,
        quotes: Mapping[str, Observation],
        last_known: Mapping[str, float],
        instruments: InstrumentRegistry,
        base_currency: str,
        universe: Collection[str],
    ) -> Execution:
        """Trade the book towards the target weights, at one execution instant.

        Parameters
        ----------
        state : PortfolioState
            What is held before the trades.
        target : Mapping[str, float]
            Accepted fraction of equity per instrument. An instrument held and
            absent from it is a target of zero: the position is closed.
        at : datetime
            The execution instant. Every order is submitted and filled at it.
        session : date
            The session whose opening auction the orders are filled at. Only an
            opening price of that session is ever traded on: an observation the
            reader calls current can still be the previous session's, when the
            instant falls before this one's auction has printed.
        quotes : Mapping[str, Observation]
            The opening price knowable at ``at``, with its status, for every
            instrument that is held or targeted.
        last_known : Mapping[str, float]
            The last price the run knew for each held instrument. Used only to
            value a position whose opening price is not usable, so that the
            other orders can be sized - never to fill one.
        instruments : InstrumentRegistry
            Lot sizes, tradability and currencies.
        base_currency : str
            The currency the book is kept in.
        universe : Collection[str]
            The trading universe on the execution session. A purchase outside
            it is refused; a sale never is.

        Returns
        -------
        Execution
            The book after the trades, the orders, the fills and the rejects.

        Raises
        ------
        ValueError
            If a target weight is not a finite fraction, the weights add up to
            more than the book, or an observation was not yet knowable at
            ``at`` or describes a later session than ``session`` - a price
            from after the instant it is used at is look-ahead, and it is a
            bug rather than a market situation.
        KeyError
            If a held or targeted instrument has no observation, or is not in
            the registry.
        UnvaluablePosition
            If a held position has neither a usable opening price nor a last
            known price, so the book - and every order sized on it - cannot be
            valued.

        Notes
        -----
        How each line is turned into an order, in instrument order:

        - nothing held and nothing wanted: nothing;
        - an instrument that may not be traded at all - not tradable, another
          currency, a position that is not a whole number of lots - is
          rejected and left exactly as it is;
        - without an opening price of ``session`` itself, the line is
          rejected with ``STALE_EXECUTION_PRICE`` - an older open, including
          one the reader still calls current because this auction has not
          printed yet - or ``NO_EXECUTION_PRICE``.
          The rejection says which way and how much when that is knowable - a
          position to close is a sale of all of it - and leaves both unknown
          otherwise, rather than guessing;
        - a purchase is sized at the price it will be paid: the whole lots
          between what is held and ``w * equity / fill_price``, rounded down,
          so that the value spent is at most the value targeted. It is refused
          outside the universe of the execution session;
        - a sale sells the whole lots of the excess over
          ``w * equity / market_price``, rounded down too: it never sells more
          than the target calls for, and a position to close is sold in full;
        - an order worth less than the minimum trade value is rejected with
          ``BELOW_MINIMUM_TRADE``;
        - a target within a lot of what is held is no order at all: at this
          lot size, it has been reached. Rounding the *trade* rather than the
          target is what makes this true. A target recomputed at the open
          from weights taken at the close drifts by a fraction of a share
          every day; rounded as a position, 198.99 shares against 199 held is
          a sale of one, the next day's 199.01 no purchase, and a book asked
          to hold what it holds sells itself away one lot at a time.
        """
        self._require_target(target)
        equity = self._equity(state, quotes, last_known, at, session)
        sells, buys, rejects = self._plan(
            state,
            target,
            equity=equity,
            at=at,
            session=session,
            quotes=quotes,
            instruments=instruments,
            base_currency=base_currency,
            universe=universe,
        )
        fills: list[Fill] = []
        book = state
        for line in sells:
            fill = Fill.of(line.order, line.market_price, self.costs)
            if book.cash + fill.cash_flow < 0.0:
                # A commission floor larger than what the sale brings in, on a
                # book with nothing left in cash to pay the difference.
                rejects.append(
                    ExecutionReject(
                        line.order.instrument_id,
                        ExecutionRejectReason.INSUFFICIENT_CASH,
                        Side.SELL,
                        line.order.quantity,
                    )
                )
                continue
            book = book.sold(fill.instrument_id, fill.quantity, fill.cash_flow, at)
            fills.append(fill)

        scale = self._affordable_scale(buys, book.cash)
        for line in buys:
            quantity = self._scaled(line, scale)
            cut = line.order.quantity - quantity if quantity > 0.0 else line.order.quantity
            if quantity > 0.0:
                fill = self._fill(line, quantity)
                book = book.bought(fill.instrument_id, fill.quantity, -fill.cash_flow, at)
                fills.append(fill)
            if cut > LOT_TOLERANCE * line.order.quantity:
                rejects.append(
                    ExecutionReject(
                        line.order.instrument_id,
                        ExecutionRejectReason.INSUFFICIENT_CASH,
                        Side.BUY,
                        cut,
                    )
                )
        return Execution(
            at=at,
            state=book,
            equity=equity,
            orders=tuple(line.order for line in (*sells, *buys)),
            fills=tuple(fills),
            rejects=tuple(sorted(rejects, key=lambda reject: reject.instrument_id)),
        )

    @staticmethod
    def _require_target(target: Mapping[str, float]) -> None:
        """Raise unless the target is a set of long fractions of one book."""
        for instrument_id, weight in target.items():
            require_unit_fraction(weight, f"the target weight of {instrument_id}")
        total = math.fsum(target.values())
        if total > 1.0 + WEIGHT_SUM_TOLERANCE:
            raise ValueError(
                f"the target weights add up to {total}; this book does not borrow the rest"
            )

    @staticmethod
    def _equity(
        state: PortfolioState,
        quotes: Mapping[str, Observation],
        last_known: Mapping[str, float],
        at: datetime,
        session: date,
    ) -> float:
        """Return the book's worth at the execution instant, before any cost.

        Notes
        -----
        A position whose opening price printed is worth that price; one whose
        price did not is worth the last price the run knew. Being untradable
        this morning and being worthless are not the same thing, and sizing
        every other line as though it were would sell half a book because one
        auction was late.
        """
        prices: dict[str, float] = {}
        for instrument_id in state.holdings:
            price = _opening_price(quotes[instrument_id], at, session)
            if price is not None:
                prices[instrument_id] = price
                continue
            carried = last_known.get(instrument_id)
            if carried is None:
                raise UnvaluablePosition(
                    f"{instrument_id} is held and has never had a knowable price; the book "
                    f"cannot be valued at {at.isoformat()}, so no order can be sized"
                )
            prices[instrument_id] = carried
        return state.value_at(prices)

    def _plan(
        self,
        state: PortfolioState,
        target: Mapping[str, float],
        *,
        equity: float,
        at: datetime,
        session: date,
        quotes: Mapping[str, Observation],
        instruments: InstrumentRegistry,
        base_currency: str,
        universe: Collection[str],
    ) -> tuple[list[_Line], list[_Line], list[ExecutionReject]]:
        """Return the sales, the purchases and the rejects the target calls for."""
        sells: list[_Line] = []
        buys: list[_Line] = []
        rejects: list[ExecutionReject] = []
        for instrument_id in sorted(set(target) | set(state.holdings)):
            weight = target.get(instrument_id, 0.0)
            held = state.quantity(instrument_id)
            if weight == 0.0 and held == 0.0:
                continue
            instrument = instruments.get(instrument_id)
            step = instrument.quantity_step
            side, quantity = _known_order(weight, held)
            refusal: ExecutionRejectReason | None = None
            if not instrument.tradable:
                refusal = ExecutionRejectReason.NON_TRADABLE
            elif instrument.currency != base_currency:
                refusal = ExecutionRejectReason.CURRENCY_MISMATCH
            elif not is_whole_lots(held, step):
                refusal = ExecutionRejectReason.INVALID_QUANTITY
            else:
                quote = quotes[instrument_id]
                price = _opening_price(quote, at, session)
                if price is None:
                    refusal = (
                        ExecutionRejectReason.NO_EXECUTION_PRICE
                        if quote.value is None
                        else ExecutionRejectReason.STALE_EXECUTION_PRICE
                    )
                else:
                    line, refusal, side, quantity = self._line(
                        instrument_id,
                        price=price,
                        value=equity * weight,
                        held=held,
                        step=step,
                        at=at,
                        in_universe=instrument_id in universe,
                    )
                    if line is not None:
                        (buys if line.order.side is Side.BUY else sells).append(line)
            if refusal is not None:
                rejects.append(ExecutionReject(instrument_id, refusal, side, quantity))
        return sells, buys, rejects

    def _line(
        self,
        instrument_id: str,
        *,
        price: float,
        value: float,
        held: float,
        step: float | None,
        at: datetime,
        in_universe: bool,
    ) -> tuple[_Line | None, ExecutionRejectReason | None, Side | None, float | None]:
        """Return the order one line needs, or why it gets none.

        Returns
        -------
        tuple[_Line | None, ExecutionRejectReason | None, Side | None, float | None]
            The order to send, or the reason it is refused together with the
            side and the quantity refused. All four are ``None`` when the line
            is already at its target, to within a lot.
        """
        buy = _units_to_buy(value, self.costs.fill_price(Side.BUY, price), held, step)
        if buy > 0.0:
            if not in_universe:
                return None, ExecutionRejectReason.OUTSIDE_TRADING_UNIVERSE, Side.BUY, buy
            if buy * self.costs.fill_price(Side.BUY, price) < self.minimum_trade_value:
                return None, ExecutionRejectReason.BELOW_MINIMUM_TRADE, Side.BUY, buy
            return _Line(Order(instrument_id, Side.BUY, buy, at), price, step), None, None, None
        sell = _units_to_sell(value, price, held, step)
        if sell > 0.0:
            if sell * self.costs.fill_price(Side.SELL, price) < self.minimum_trade_value:
                return None, ExecutionRejectReason.BELOW_MINIMUM_TRADE, Side.SELL, sell
            return _Line(Order(instrument_id, Side.SELL, sell, at), price, step), None, None, None
        return None, None, None, None

    def _fill(self, line: _Line, quantity: float) -> Fill:
        """Return the fill of ``quantity`` units of a line's order."""
        order = line.order
        if quantity != order.quantity:
            order = Order(order.instrument_id, order.side, quantity, order.submitted_at)
        return Fill.of(order, line.market_price, self.costs)

    def _scaled(self, line: _Line, scale: float) -> float:
        """Return the units of a purchase sent at ``scale`` of its size, or ``0.0``.

        Notes
        -----
        Rounded down to the lot after scaling, and dropped when what remains
        is worth less than the minimum trade value - an order cut below the
        threshold is exactly the order the threshold exists to stop.
        """
        wanted = line.order.quantity
        if scale >= 1.0:
            return wanted
        if line.step is None:
            quantity = wanted * scale
        else:
            quantity = whole_lots(wanted * scale, line.step) * line.step
        if quantity <= 0.0:
            return 0.0
        price = self.costs.fill_price(Side.BUY, line.market_price)
        if quantity * price < self.minimum_trade_value:
            return 0.0
        return quantity

    def _cash_left(self, buys: Sequence[_Line], cash: float, scale: float) -> float:
        """Return the cash left after buying ``scale`` of every purchase.

        Notes
        -----
        Computed with the very operations the purchases are then booked with,
        in the same order - the fill's value plus its commission, subtracted
        one purchase at a time - so that what is found affordable is what is
        afterwards paid, to the last bit. The same numbers added in another
        order differ by an ulp, and an ulp below zero is a book that borrowed.
        """
        left = cash
        for line in buys:
            quantity = self._scaled(line, scale)
            if quantity > 0.0:
                fill = self._fill(line, quantity)
                left = left - (-fill.cash_flow)
        return left

    def _affordable_scale(self, buys: Sequence[_Line], cash: float) -> float:
        """Return the largest fraction of the purchases the cash can carry.

        Parameters
        ----------
        buys : Sequence[_Line]
            The purchases this rebalancing wants, at full size, in the order
            they will be booked.
        cash : float
            What is left after the sales.

        Returns
        -------
        float
            ``1.0`` when everything fits, and otherwise the largest fraction
            at which every purchase - scaled, then rounded down to its lot -
            still fits. Every order is cut by the same fraction, so the book
            keeps the proportions the strategy asked for: cutting one name to
            the bone to leave another whole would be a decision about the
            strategy, and this layer does not take those.

        Notes
        -----
        Found by bisection rather than by formula. A commission floor does not
        scale with the order it is charged on, and whole lots move in steps, so
        the cash a set of purchases needs is a step function of their size
        with no closed form. It never decreases as the size grows, which is
        all a bisection needs, and sixty halvings take the answer well past
        the precision of the numbers it is made of. Because the rounding is
        inside the search, the cash a rounded-down lot leaves is used by the
        others - in proportion, never by picking a winner.
        """
        if not buys or self._cash_left(buys, cash, 1.0) >= 0.0:
            return 1.0
        low, high = 0.0, 1.0
        for _ in range(60):
            middle = (low + high) / 2.0
            if self._cash_left(buys, cash, middle) >= 0.0:
                low = middle
            else:
                high = middle
        return low


def _known_order(weight: float, held: float) -> tuple[Side | None, float | None]:
    """Return the side and quantity a line needs, when they are knowable without a price.

    A position to close is a sale of all of it, and a position to open is a
    purchase of an unknown size. A position held and still wanted may need
    either, and saying which would take the price that is missing.
    """
    if weight == 0.0:
        return Side.SELL, held
    if held == 0.0:
        return Side.BUY, None
    return None, None


def _units_to_buy(value: float, price: float, held: float, step: float | None) -> float:
    """Return the units to buy so the position reaches ``value`` at ``price``, or ``0.0``."""
    if value == 0.0:
        return 0.0
    if step is None:
        wanted = value / price
        return wanted - held if wanted - held > LOT_TOLERANCE * wanted else 0.0
    lots = whole_lots(value / price, step) - round(held / step)
    return lots * step if lots > 0 else 0.0


def _units_to_sell(value: float, price: float, held: float, step: float | None) -> float:
    """Return the units to sell to bring the position down to ``value``, or ``0.0``.

    The excess over the target is sold in whole lots, rounded down: never more
    than the target calls for, and nothing at all when the excess is less than
    a lot. A target of nothing sells the whole position, however many lots
    that is, so that a position is always closable in full.
    """
    if held == 0.0:
        return 0.0
    if value == 0.0:
        return held
    excess = held - value / price
    if step is None:
        return excess if excess > LOT_TOLERANCE * held else 0.0
    if excess <= 0.0:
        return 0.0
    lots = whole_lots(excess, step)
    return min(lots * step, held) if lots > 0 else 0.0


def _opening_price(quote: Observation, at: datetime, session: date) -> float | None:
    """Return the opening price of ``session`` an observation carries, or ``None``.

    Parameters
    ----------
    quote : Observation
        The latest opening price the reader had at ``at``.
    at : datetime
        The execution instant.
    session : date
        The session the order is filled in.

    Returns
    -------
    float | None
        The price, when the observation is current *and* describes that very
        session. ``None`` otherwise: a stale open, a missing one, or an open
        the reader calls current because the instant falls before this
        session's auction - the previous session's open, still the latest
        one there is, and still not a price anyone could trade at today.

    Raises
    ------
    ValueError
        If the observation became knowable after ``at``, or describes a
        session after ``session``. Either is a price from the future, which
        is a bug in whoever read it, not a market situation.
    """
    if quote.available_at is not None and quote.available_at > at:
        raise ValueError(
            f"the price of {quote.instrument_id} became knowable at "
            f"{quote.available_at.isoformat()}, after the execution at {at.isoformat()}; "
            "filling on it would be look-ahead"
        )
    if quote.observation_date is not None and quote.observation_date > session:
        raise ValueError(
            f"the price of {quote.instrument_id} describes {quote.observation_date}, after "
            f"the session {session} it is used in; filling on it would be look-ahead"
        )
    if quote.status is not ObservationStatus.OK or quote.value is None:
        return None
    if quote.observation_date != session:
        return None
    return quote.value
