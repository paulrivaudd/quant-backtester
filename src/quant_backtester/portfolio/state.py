"""What the book actually holds, and what it is worth at one instant.

A target is an intention; this is the fact it is measured against. The two are
kept apart on purpose: a strategy asking for half its capital in a fund and a
book holding 493 shares of it are different statements, and the difference -
lot rounding, a price that did not print, a purchase the cash could not carry -
is exactly what a backtest report has to be able to show.

Two invariants are enforced where a state is built rather than checked after
the fact. Cash is never below zero, because nothing here grants a loan, and a
position is never below zero, because nothing here borrows a security. A state
that breaks either cannot be constructed, so no later layer has to wonder.

Valuing a state is the other half of this module, and it follows one rule:
**a valuation may be an estimate, as long as it says so**. A position whose
close did not print for the session is marked at the last price the run knew
and named; a position with no price at all, ever, stops the run - inventing
zero would show a loss that did not happen and give it back the next day.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

from quant_backtester.data.reader import Observation, ObservationStatus
from quant_backtester.numbers import (
    require_finite,
    require_finite_non_negative,
    require_finite_positive,
)
from quant_backtester.portfolio.holdings import Holding


class UnvaluablePosition(ValueError):
    """Raised when a held position cannot be given a price at all.

    Separate from an estimate, which is an ordinary market situation: a close
    that did not print is marked at the last price known and named. This is
    the other case - no price ever, or an instrument the registry says is not
    listed - where the equity of the book is simply unknown, and a run that
    carried on would be reporting a number nobody computed.
    """


def _require_aware(instant: datetime, name: str) -> None:
    """Raise unless ``instant`` is a timezone-aware datetime."""
    if not isinstance(instant, datetime) or instant.tzinfo is None:
        raise ValueError(f"{name} must be a timezone-aware datetime, got {instant!r}")


@dataclass(frozen=True, slots=True)
class PortfolioState:
    """Cash and positions actually held, from one instant on.

    Attributes
    ----------
    as_of : datetime
        The instant this state starts to hold: the start of the run, or the
        execution that last changed it. Timezone-aware.
    cash : float
        Currency units not invested, in the book's base currency. Never below
        zero.
    holdings : Mapping[str, Holding]
        Positions, keyed by instrument. A position closed in full is absent
        rather than held at zero, so a book does not grow ghosts.

    Raises
    ------
    ValueError
        If ``as_of`` is naive, the cash is not a finite number of zero or more,
        or a holding is filed under another instrument's id.

    Notes
    -----
    The positions are kept in instrument order, whatever order they were given
    in: two books holding the same things are the same book, and every sum
    taken over them below is taken in that order, so a valuation does not
    depend on the sequence a mapping happened to be filled in.
    """

    as_of: datetime
    cash: float
    holdings: Mapping[str, Holding] = MappingProxyType({})

    def __post_init__(self) -> None:
        """Check the state could exist, drop the closed positions, and freeze it."""
        _require_aware(self.as_of, "as_of")
        require_finite_non_negative(self.cash, "cash")
        held: dict[str, Holding] = {}
        for instrument_id in sorted(self.holdings):
            holding = self.holdings[instrument_id]
            if not isinstance(holding, Holding):
                raise ValueError(f"{instrument_id} is held as {holding!r}, which is not a Holding")
            if holding.instrument_id != instrument_id:
                raise ValueError(
                    f"a holding of {holding.instrument_id} is filed under {instrument_id}"
                )
            if holding.quantity != 0.0:
                held[instrument_id] = holding
        object.__setattr__(self, "holdings", MappingProxyType(held))

    @classmethod
    def opening(cls, cash: float, as_of: datetime) -> PortfolioState:
        """Return a book holding nothing but cash.

        Parameters
        ----------
        cash : float
            What the run starts with.
        as_of : datetime
            When it starts.

        Returns
        -------
        PortfolioState
            No position at all.
        """
        return cls(as_of=as_of, cash=cash)

    @property
    def quantities(self) -> Mapping[str, float]:
        """Return the units held per instrument."""
        return MappingProxyType(
            {instrument_id: holding.quantity for instrument_id, holding in self.holdings.items()}
        )

    def quantity(self, instrument_id: str) -> float:
        """Return the units held of one instrument, ``0.0`` when it is not held."""
        holding = self.holdings.get(instrument_id)
        return 0.0 if holding is None else holding.quantity

    def holds(self, instrument_id: str) -> bool:
        """Return whether the book has a position in one instrument."""
        return instrument_id in self.holdings

    def value_at(self, prices: Mapping[str, float]) -> float:
        """Return the total worth of the book at the given prices.

        Parameters
        ----------
        prices : Mapping[str, float]
            One price per held instrument.

        Returns
        -------
        float
            Cash plus the value of every position, summed exactly (``fsum``)
            in instrument order.

        Raises
        ------
        KeyError
            If an instrument is held and no price is given for it. Valuing a
            position at nothing because its price is missing would show a loss
            that did not happen, then show it back the next day.
        ValueError
            If a price is not a finite positive number.
        """
        return math.fsum(
            [self.cash]
            + [holding.value_at(prices[name]) for name, holding in self.holdings.items()]
        )

    def weights_at(self, prices: Mapping[str, float]) -> dict[str, float]:
        """Return the fraction of total worth each position represents.

        Parameters
        ----------
        prices : Mapping[str, float]
            One price per held instrument.

        Returns
        -------
        dict[str, float]
            Per held instrument. Empty for a book worth nothing, which has no
            fractions to speak of.
        """
        total = self.value_at(prices)
        if total == 0.0:
            return {}
        return {
            name: holding.value_at(prices[name]) / total for name, holding in self.holdings.items()
        }

    def bought(
        self, instrument_id: str, quantity: float, cash_paid: float, at: datetime
    ) -> PortfolioState:
        """Return the book after a purchase.

        Parameters
        ----------
        instrument_id : str
            What was bought.
        quantity : float
            Units bought, positive.
        cash_paid : float
            Everything that left the cash account for it: the value at the
            fill price plus the commission. The position's average cost is
            taken from it, so it records what the units actually cost.
        at : datetime
            When the purchase was done. Never before the state it changes.

        Returns
        -------
        PortfolioState
            The new book.

        Raises
        ------
        ValueError
            If the purchase would take the cash below zero - that would be a
            loan nobody granted - or if it is dated before this state.
        """
        self._require_not_before(at)
        require_finite_positive(quantity, "quantity")
        require_finite_positive(cash_paid, "cash_paid")
        cash = self.cash - cash_paid
        if cash < 0.0:
            raise ValueError(
                f"buying {quantity} {instrument_id} for {cash_paid} would leave {cash} in "
                "cash; nothing here lends the difference"
            )
        current = self.holdings.get(instrument_id, Holding(instrument_id, 0.0))
        holdings = dict(self.holdings)
        holdings[instrument_id] = current.bought(quantity, cash_paid / quantity)
        return PortfolioState(as_of=at, cash=cash, holdings=holdings)

    def sold(
        self, instrument_id: str, quantity: float, cash_received: float, at: datetime
    ) -> PortfolioState:
        """Return the book after a sale.

        Parameters
        ----------
        instrument_id : str
            What was sold.
        quantity : float
            Units sold, positive and never more than are held.
        cash_received : float
            What the sale brought into the cash account: the value at the fill
            price minus the commission. Negative when a commission floor is
            larger than the value sold, which is possible and is why the cash
            check below is not only about purchases.
        at : datetime
            When the sale was done. Never before the state it changes.

        Returns
        -------
        PortfolioState
            The new book. A position sold in full disappears from it.

        Raises
        ------
        ValueError
            If more is sold than is held, if the cash would end below zero, or
            if the sale is dated before this state.
        """
        self._require_not_before(at)
        if instrument_id not in self.holdings:
            raise ValueError(f"{instrument_id} is not held, so none of it can be sold")
        require_finite_positive(quantity, "quantity")
        require_finite(cash_received, "cash_received")
        cash = self.cash + cash_received
        if not math.isfinite(cash) or cash < 0.0:
            raise ValueError(
                f"selling {quantity} {instrument_id} for {cash_received} would leave {cash} "
                "in cash; the commission would be paid with money the book has not got"
            )
        holdings = dict(self.holdings)
        holdings[instrument_id] = self.holdings[instrument_id].sold(quantity)
        return PortfolioState(as_of=at, cash=cash, holdings=holdings)

    def _require_not_before(self, at: datetime) -> None:
        """Raise unless ``at`` is a timezone-aware instant no earlier than this state."""
        _require_aware(at, "at")
        if at < self.as_of:
            raise ValueError(
                f"a trade at {at.isoformat()} cannot change a book that stands from "
                f"{self.as_of.isoformat()}; time runs one way"
            )


@dataclass(frozen=True, slots=True)
class ValuationResult:
    """What a book was worth at one instant, and how much of that is an estimate.

    Attributes
    ----------
    as_of : datetime
        When the book was valued.
    equity : float
        Cash plus every position at the prices below.
    prices : Mapping[str, float]
        The price each held instrument was marked at.
    estimated_instruments : tuple[str, ...]
        Held instruments marked at an older price than the session's own,
        because none was published for it. The equity is an estimate for
        those, and says so.

    Raises
    ------
    ValueError
        If ``as_of`` is naive, the equity is not finite, a price is not a
        finite positive number, or an estimated instrument has no price.
    """

    as_of: datetime
    equity: float
    prices: Mapping[str, float]
    estimated_instruments: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Check the valuation is one, and freeze it."""
        _require_aware(self.as_of, "as_of")
        require_finite_non_negative(self.equity, "equity")
        prices = {name: self.prices[name] for name in sorted(self.prices)}
        for name, price in prices.items():
            require_finite_positive(price, f"the valuation price of {name}")
        estimated = tuple(sorted(self.estimated_instruments))
        unpriced = sorted(set(estimated) - set(prices))
        if unpriced:
            raise ValueError(f"{', '.join(unpriced)} is estimated and has no price")
        object.__setattr__(self, "prices", MappingProxyType(prices))
        object.__setattr__(self, "estimated_instruments", estimated)

    @property
    def is_estimate(self) -> bool:
        """Return whether any position was marked at an older price."""
        return bool(self.estimated_instruments)


def value_state(
    state: PortfolioState,
    observations: Mapping[str, Observation],
    last_known: Mapping[str, float],
    as_of: datetime,
) -> ValuationResult:
    """Value a book at the prices knowable at one instant.

    Parameters
    ----------
    state : PortfolioState
        The book to value.
    observations : Mapping[str, Observation]
        The latest knowable closing price of every held instrument, as the
        reader gives it: the value with its status.
    last_known : Mapping[str, float]
        The last price the run knew for each instrument - a close it valued
        the book at, or the price it last traded at. Used only when the
        session's own close did not print.
    as_of : datetime
        The valuation instant.

    Returns
    -------
    ValuationResult
        The equity, the price of each position, and which of them are
        estimates.

    Raises
    ------
    UnvaluablePosition
        If a held instrument is not listed at the instant - a position in a
        delisted instrument has to be closed, and this model does not know at
        what price - or has no price at all, now or ever.
    KeyError
        If a held instrument has no observation. The caller reads every
        position; one missing from the reading is a wiring mistake.

    Notes
    -----
    The rules, in the order they are applied:

    - ``OK``: the session's own price. Not an estimate.
    - ``STALE``: the latest price there is, from an earlier session - the
      venue did not trade since. A real number, and still an estimate of what
      this session's price would have been, so it is named.
    - ``MISSING``: the venue held the session and the price is not there. The
      last price the run knew, named.
    - ``NOT_LISTED``: refused. A position cannot be held in an instrument that
      does not exist.

    Valuation may estimate; execution never does. A book can be worth a price
    from yesterday, and no order is ever filled at one.
    """
    prices: dict[str, float] = {}
    estimated: list[str] = []
    for instrument_id in state.holdings:
        observation = observations[instrument_id]
        if observation.status is ObservationStatus.NOT_LISTED:
            raise UnvaluablePosition(
                f"{instrument_id} is held and is not listed at {as_of.isoformat()}; a position "
                "in a delisted instrument has to be closed, and this model does not know at "
                "what price"
            )
        if observation.status is ObservationStatus.OK and observation.value is not None:
            prices[instrument_id] = observation.value
            continue
        if observation.value is not None:
            # STALE: a close from an earlier session, real and still an estimate.
            prices[instrument_id] = observation.value
            estimated.append(instrument_id)
            continue
        carried = last_known.get(instrument_id)
        if carried is None:
            raise UnvaluablePosition(
                f"{instrument_id} is held and has never had a knowable price; the book "
                f"cannot be valued at {as_of.isoformat()}"
            )
        prices[instrument_id] = carried
        estimated.append(instrument_id)
    return ValuationResult(
        as_of=as_of,
        equity=state.value_at(prices),
        prices=prices,
        estimated_instruments=tuple(estimated),
    )
