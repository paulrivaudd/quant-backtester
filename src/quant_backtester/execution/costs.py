"""What a trade costs, in three terms that are not the same thing.

Commission is paid to a broker and is often a rate with a floor. A spread is
paid to the market and is not a fee at all: it is the difference between the
price a chart shows and the price a buyer gets. Slippage is what the order
itself moves, and it grows with size where the other two do not.

They are separate because they behave differently and because a report has to
be able to say which of them ate a strategy's return. Folded into one number,
"costs of 15 basis points" explains nothing and cannot be argued with - so a
fill keeps all three, and a run adds them up side by side.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from quant_backtester.execution.orders import Side
from quant_backtester.numbers import require_finite_non_negative, require_finite_positive


@dataclass(frozen=True, slots=True)
class CostBreakdown:
    """What one trade cost, term by term, in currency units.

    Attributes
    ----------
    commission : float
        Paid to the broker.
    spread_cost : float
        Paid to the market for crossing half the quoted spread.
    slippage_cost : float
        Lost to the order's own impact.

    Raises
    ------
    ValueError
        If a term is not a finite number of zero or more. A cost that pays the
        trader is not a cost model, it is a sign convention gone wrong.
    """

    commission: float
    spread_cost: float
    slippage_cost: float

    def __post_init__(self) -> None:
        """Reject a term that cannot be a cost."""
        for name in ("commission", "spread_cost", "slippage_cost"):
            require_finite_non_negative(getattr(self, name), name)

    @property
    def market_cost(self) -> float:
        """Return what the market took: the spread and the slippage together."""
        return self.spread_cost + self.slippage_cost

    @property
    def total(self) -> float:
        """Return everything the trade cost."""
        return math.fsum((self.commission, self.spread_cost, self.slippage_cost))


@dataclass(frozen=True, slots=True)
class CostModel:
    """Commission, spread and slippage, each declared on its own.

    Attributes
    ----------
    commission_rate : float
        Fraction of the traded value paid to the broker.
    minimum_commission : float
        Floor per order, in currency units. Most retail brokers have one, and
        it is what makes a small rebalancing trade uneconomic - a fact a
        backtest with a pure rate would never show.
    half_spread_rate : float
        Half the quoted spread, as a fraction of the market price. Half,
        because a round trip crosses it twice and each leg pays one side.
    slippage_rate : float
        Fraction of the market price lost to the order's own impact. Flat
        here: a model that grows with participation needs a volume the
        execution layer does not yet read, and a made-up curve would be worse
        than a stated constant.

    Raises
    ------
    ValueError
        If a term is not a finite number, is negative, or a fractional term
        reaches 1 - on its own, or once the spread and the slippage are added
        together, since the fill price pays both and a sale would otherwise be
        done at a price of zero or less.

    Notes
    -----
    All three rates are fractions, never percentages: ``0.001`` is ten basis
    points. The same convention as every other number in the project.
    """

    commission_rate: float = 0.0
    minimum_commission: float = 0.0
    half_spread_rate: float = 0.0
    slippage_rate: float = 0.0

    def __post_init__(self) -> None:
        """Reject a term that cannot describe a cost."""
        fractions = (
            ("commission_rate", self.commission_rate),
            ("half_spread_rate", self.half_spread_rate),
            ("slippage_rate", self.slippage_rate),
        )
        for name, value in (*fractions, ("minimum_commission", self.minimum_commission)):
            require_finite_non_negative(value, name)
        for name, value in fractions:
            if value >= 1.0:
                raise ValueError(
                    f"{name} is a fraction, not a percentage: {value} means "
                    f"{value * 100:g}% of every trade"
                )
        drag = self.half_spread_rate + self.slippage_rate
        if drag >= 1.0:
            raise ValueError(
                f"half_spread_rate and slippage_rate come to {drag}: a sale would be "
                f"done at {1.0 - drag:g} times the price on the screen"
            )

    def definition(self) -> dict[str, object]:
        """Return the model as it is recorded with a run."""
        return {
            "commission_rate": self.commission_rate,
            "minimum_commission": self.minimum_commission,
            "half_spread_rate": self.half_spread_rate,
            "slippage_rate": self.slippage_rate,
        }

    @property
    def drag(self) -> float:
        """Return the fraction of the market price a fill moves by, spread and slippage."""
        return self.half_spread_rate + self.slippage_rate

    def fill_price(self, side: Side, market_price: float) -> float:
        """Return the price a trade is actually done at.

        Parameters
        ----------
        side : Side
            Which way the trade goes.
        market_price : float
            The price the order was sized against - here, the opening auction
            of the execution session.

        Returns
        -------
        float
            The market price moved against the trader by the half spread and
            the slippage together: ``P (1 + s)`` for a buy, ``P (1 - s)`` for a
            sale. A round trip pays both.

        Raises
        ------
        ValueError
            If the market price is not a finite positive number.
        """
        require_finite_positive(market_price, "the market price")
        return (
            market_price * (1.0 + self.drag)
            if side is Side.BUY
            else market_price * (1.0 - self.drag)
        )

    def commission(self, traded_value: float) -> float:
        """Return the broker's fee on one order.

        Parameters
        ----------
        traded_value : float
            Absolute value traded, at the fill price.

        Returns
        -------
        float
            The rate applied to the value, never below the floor - and zero for
            an order of nothing, since no order was sent.
        """
        require_finite_non_negative(traded_value, "the traded value")
        if traded_value == 0.0:
            return 0.0
        return max(traded_value * self.commission_rate, self.minimum_commission)

    def breakdown(self, side: Side, quantity: float, market_price: float) -> CostBreakdown:
        """Return what trading ``quantity`` units at ``market_price`` costs, term by term.

        Parameters
        ----------
        side : Side
            Which way the trade goes.
        quantity : float
            Units traded, positive.
        market_price : float
            The price the order was sized against.

        Returns
        -------
        CostBreakdown
            The commission on the value at the fill price, and the spread and
            the slippage as the quantity times the market price times each
            rate. The last two add up to what the fill price moved by, to the
            rounding of the arithmetic.
        """
        require_finite_positive(quantity, "quantity")
        fill = self.fill_price(side, market_price)
        return CostBreakdown(
            commission=self.commission(quantity * fill),
            spread_cost=quantity * market_price * self.half_spread_rate,
            slippage_cost=quantity * market_price * self.slippage_rate,
        )
