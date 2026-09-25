"""Quantities in the units a venue deals in, rounded the one safe way.

A retail order book takes 123 shares of an ETF or 124, never 123.47. A
backtest that buys fractions allocates its capital perfectly, and that small,
systematic optimism turns into a return the account never sees. So wherever an
instrument declares a ``quantity_step``, an order is a whole number of lots,
**rounded down**:

- a purchase never buys more than the target asked for, because the cash for
  the extra units was never set aside;
- a sale never sells more than the target calls for, so what remains is within
  a lot of it;
- a target within a lot of what is held is no order at all. It is the trade
  that is rounded, not the target position: a target recomputed every morning
  drifts by a fraction of a share, and rounding it as a position would sell a
  lot whenever it drifted just under one - a book asked to keep what it holds
  would sell itself away, a commission at a time.

Lots are counted as integers and turned back into units at the end, so a
hundred whole shares are a hundred and not 99.999999999999986, and a position
closed in full closes to exactly zero.
"""

from __future__ import annotations

import math
from typing import Final

from quant_backtester.numbers import require_finite_non_negative, require_finite_positive

LOT_TOLERANCE: Final[float] = 1e-9
"""Fraction of a lot below which a quantity is floating-point dust.

``300.09 / 100.03`` is ``2.9999999999999996`` rather than ``3``, and rounding
that down would buy two shares where the arithmetic meant three. A billionth
of a lot is far above that error and far below any quantity anyone trades, so
it absorbs representation error and nothing else - and the cash is checked
exactly afterwards, so it can never buy a unit the book cannot pay for.
"""


def whole_lots(quantity: float, step: float) -> int:
    """Return how many whole lots ``quantity`` holds, rounded down.

    Parameters
    ----------
    quantity : float
        Units, zero or more.
    step : float
        Lot size, positive.

    Returns
    -------
    int
        The largest number of lots whose units do not exceed ``quantity``,
        once floating-point dust is set aside.

    Raises
    ------
    ValueError
        If the quantity is negative or the step is not positive.
    """
    require_finite_non_negative(quantity, "quantity")
    require_finite_positive(step, "step")
    return math.floor(quantity / step + LOT_TOLERANCE)


def round_down_to_lot(quantity: float, step: float | None) -> float:
    """Return the largest dealable quantity at or below ``quantity``.

    Parameters
    ----------
    quantity : float
        Units wanted, zero or more.
    step : float | None
        Lot size, or ``None`` for an instrument dealt in fractions.

    Returns
    -------
    float
        ``quantity`` itself when there is no step, and a whole number of lots
        otherwise. Never more than was wanted.
    """
    require_finite_non_negative(quantity, "quantity")
    if step is None:
        return quantity
    return whole_lots(quantity, step) * step


def is_whole_lots(quantity: float, step: float | None) -> bool:
    """Return whether ``quantity`` is a whole number of lots.

    Parameters
    ----------
    quantity : float
        Units, zero or more.
    step : float | None
        Lot size, or ``None`` for an instrument dealt in fractions, for which
        every quantity is whole.

    Returns
    -------
    bool
        ``True`` when the quantity is within :data:`LOT_TOLERANCE` of a lot
        boundary.
    """
    require_finite_non_negative(quantity, "quantity")
    if step is None:
        return True
    lots = quantity / step
    return abs(lots - round(lots)) <= LOT_TOLERANCE


def target_quantity(value: float, price: float, step: float | None) -> float:
    """Return the dealable quantity ``value`` is worth at ``price``, rounded down.

    Parameters
    ----------
    value : float
        Currency units to hold, zero or more.
    price : float
        Price per unit, positive.
    step : float | None
        Lot size, or ``None`` for fractions.

    Returns
    -------
    float
        ``floor(value / price / step) * step`` - never a unit more than the
        value pays for.
    """
    require_finite_non_negative(value, "value")
    require_finite_positive(price, "price")
    return round_down_to_lot(value / price, step)
