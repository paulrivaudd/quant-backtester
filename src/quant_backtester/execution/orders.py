"""What is sent to the market: an instrument, a direction, a quantity, an instant.

An order is deliberately small. It carries no price - the price belongs to the
fill, which is what the market did with the order - and no weight - the weight
belongs to the target, which is what the strategy wanted. Keeping the three
apart is what lets a record say, for one line of one rebalancing, what was
wanted, what was sent and what was done, and see where they differ.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from quant_backtester.numbers import require_finite_positive
from quant_backtester.signals.types import require_identifier


class Side(Enum):
    """Which way a trade goes, and therefore which way its costs point.

    There is no short side. Selling is only ever selling what is held: a sale
    below zero would be a borrow nobody granted.
    """

    BUY = "BUY"
    """Pays the offer: the fill is above the market price."""

    SELL = "SELL"
    """Hits the bid: the fill is below it."""


@dataclass(frozen=True, slots=True)
class Order:
    """An instruction to trade one instrument at one instant.

    Attributes
    ----------
    instrument_id : str
        What to trade.
    side : Side
        Which way.
    quantity : float
        Units, always positive; ``side`` carries the direction. A whole number
        of lots where the instrument declares a lot size.
    submitted_at : datetime
        When the order was sent - just after the opening auction it is sized
        against. Timezone-aware.

    Raises
    ------
    ValueError
        If the quantity is not a finite positive number, or the instant is
        naive. An order of no units is not an order, and the layer that built
        one has a bug rather than a trade to record.
    """

    instrument_id: str
    side: Side
    quantity: float
    submitted_at: datetime

    def __post_init__(self) -> None:
        """Reject an order that could not be sent."""
        require_identifier(self.instrument_id, "instrument_id")
        if not isinstance(self.side, Side):
            raise ValueError(f"side must be a Side, got {self.side!r}")
        require_finite_positive(self.quantity, f"the quantity of the order in {self.instrument_id}")
        if not isinstance(self.submitted_at, datetime) or self.submitted_at.tzinfo is None:
            raise ValueError(
                f"submitted_at must be a timezone-aware datetime, got {self.submitted_at!r}"
            )

    @property
    def signed_quantity(self) -> float:
        """Return the quantity with its direction: positive to buy, negative to sell."""
        return self.quantity if self.side is Side.BUY else -self.quantity

    def is_whole_lots(self, step: float | None) -> bool:
        """Return whether the quantity is a whole number of lots of ``step``.

        Parameters
        ----------
        step : float | None
            The instrument's lot size, or ``None`` when it deals in fractions.

        Returns
        -------
        bool
            ``True`` for any quantity when there is no step.
        """
        if step is None:
            return True
        lots = self.quantity / step
        return math.isclose(lots, round(lots), rel_tol=0.0, abs_tol=1e-9)
