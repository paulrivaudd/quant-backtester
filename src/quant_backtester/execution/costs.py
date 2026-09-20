"""What a trade costs, in three terms that are not the same thing.

Commission is paid to a broker and is often a rate with a floor. A spread is
paid to the market and is not a fee at all: it is the difference between the
price a chart shows and the price a buyer gets. Slippage is what the order
itself moves, and it grows with size where the other two do not.

They are separate because they behave differently and because a report has to
be able to say which of them ate a strategy's return. Folded into one number,
"costs of 15 basis points" explains nothing and cannot be argued with.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from quant_backtester.numbers import require_finite_non_negative


class Side(Enum):
    """Which way a trade goes, and therefore which way its costs point."""

    BUY = "BUY"
    """Pays the offer: the fill is above the reference price."""

    SELL = "SELL"
    """Hits the bid: the fill is below it."""


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
    half_spread : float
        Half the quoted spread, as a fraction of the reference price. Half,
        because a round trip crosses it twice and each leg pays one side.
    slippage_rate : float
        Fraction of the reference price lost to the order's own impact. Flat
        here: a model that grows with participation needs a volume the
        execution layer does not yet read, and a made-up curve would be worse
        than a stated constant.

    Raises
    ------
    ValueError
        If a term is not a finite number, is negative, or a fractional term
        reaches 1 - on its own, or once the spread and the slippage are added
        together, since the fill price pays both. A cost of a whole price is
        not a cost, it is a sign the units were confused.

    Notes
    -----
    All three are expressed as fractions, never as percentages: ``0.001`` is
    ten basis points. The same convention as every other number in the project.
    """

    commission_rate: float = 0.0
    minimum_commission: float = 0.0
    half_spread: float = 0.0
    slippage_rate: float = 0.0

    def __post_init__(self) -> None:
        """Reject a term that cannot describe a cost."""
        fractions = (
            ("commission_rate", self.commission_rate),
            ("half_spread", self.half_spread),
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
        drag = self.half_spread + self.slippage_rate
        if drag >= 1.0:
            raise ValueError(
                f"half_spread and slippage_rate come to {drag}: a sale would be "
                f"done at {1.0 - drag:g} times the price on the screen"
            )

    def fill_price(self, side: Side, reference: float) -> float:
        """Return the price a trade is actually done at.

        Parameters
        ----------
        side : Side
            Which way the trade goes.
        reference : float
            The price the strategy saw - here, the opening auction of the
            execution session.

        Returns
        -------
        float
            The reference moved against the trader by the half spread and the
            slippage together. A buy pays more, a sell receives less, and a
            round trip pays both.

        Raises
        ------
        ValueError
            If ``reference`` is not strictly positive.
        """
        if reference <= 0:
            raise ValueError(f"a fill price needs a positive reference, got {reference}")
        drag = self.half_spread + self.slippage_rate
        return reference * (1.0 + drag) if side is Side.BUY else reference * (1.0 - drag)

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
        if traded_value <= 0:
            return 0.0
        return max(traded_value * self.commission_rate, self.minimum_commission)
