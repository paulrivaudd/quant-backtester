"""One position, and what is known about how it was built.

A holding is a quantity of one instrument. It carries an average cost when the
run has one, because two books holding the same shares at different entry
prices are not in the same situation - a stop, a tax lot or a simple "am I up
on this" needs the number - and because a position that appeared from nowhere
is one nobody can audit.

What a holding is not is a valuation. What it is worth depends on a price, and
a price belongs to an instant, so the value is computed where the instant is
known and never cached here.
"""

from __future__ import annotations

from dataclasses import dataclass

from quant_backtester.numbers import require_finite_non_negative, require_finite_positive
from quant_backtester.signals.types import require_identifier


@dataclass(frozen=True, slots=True)
class Holding:
    """A position in one instrument.

    Attributes
    ----------
    instrument_id : str
        What is held.
    quantity : float
        Units held, never negative: nothing in this project borrows a
        security, charges a borrow fee or answers a margin call.
    average_cost : float | None
        Mean price paid per unit, costs included, over everything bought so
        far. ``None`` for a position whose history the run does not know -
        one it started with, say. A sale does not change it: selling half a
        position does not change what the other half cost.

    Raises
    ------
    ValueError
        If the quantity is not a finite number of zero or more, or the average
        cost is not a finite positive price.
    """

    instrument_id: str
    quantity: float
    average_cost: float | None = None

    def __post_init__(self) -> None:
        """Reject a position that could not exist."""
        require_identifier(self.instrument_id, "instrument_id")
        require_finite_non_negative(self.quantity, f"the quantity of {self.instrument_id}")
        if self.average_cost is not None:
            require_finite_positive(self.average_cost, f"the average cost of {self.instrument_id}")

    def value_at(self, price: float) -> float:
        """Return what this position is worth at one price.

        Parameters
        ----------
        price : float
            Price per unit, in the instrument's currency.

        Returns
        -------
        float
            The quantity times the price.

        Raises
        ------
        ValueError
            If the price is not a finite positive number. A ``NaN`` price
            values the position at ``NaN``, and the equity curve with it.
        """
        require_finite_positive(price, f"the price of {self.instrument_id}")
        return self.quantity * price

    def bought(self, quantity: float, price: float) -> Holding:
        """Return the position after buying more of it.

        Parameters
        ----------
        quantity : float
            Units added, positive.
        price : float
            Price paid per unit, costs included - what the cash actually went
            out at, not what the screen said.

        Returns
        -------
        Holding
            The larger position, with the average cost carried forward. An
            unknown average cost stays unknown: averaging a known price into
            an unknown one would invent a number.

        Raises
        ------
        ValueError
            If the quantity or the price is not a positive finite number.
        """
        require_finite_positive(quantity, "quantity")
        require_finite_positive(price, "price")
        if self.average_cost is None and self.quantity != 0.0:
            return Holding(self.instrument_id, self.quantity + quantity, None)
        paid = (self.average_cost or 0.0) * self.quantity + price * quantity
        total = self.quantity + quantity
        return Holding(self.instrument_id, total, paid / total)

    def sold(self, quantity: float) -> Holding:
        """Return the position after selling part of it.

        Parameters
        ----------
        quantity : float
            Units removed, positive and never more than are held.

        Returns
        -------
        Holding
            The smaller position, at the same average cost: what the remaining
            shares cost does not change because some others were sold.

        Raises
        ------
        ValueError
            If more is sold than is held. Nothing here goes short, so this is
            a mistake in the layer that sized the order rather than a position
            to create.
        """
        require_finite_positive(quantity, "quantity")
        if quantity > self.quantity:
            raise ValueError(
                f"{self.instrument_id}: selling {quantity} of {self.quantity} held would "
                "leave a short position, which nothing here finances"
            )
        return Holding(self.instrument_id, self.quantity - quantity, self.average_cost)
