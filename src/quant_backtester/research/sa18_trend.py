"""SA18: one asset held while its level is above its moving average, bills otherwise.

The study ``research/SA18/trend_long_history.md`` freezes: Faber's (2007)
monthly timing rule on the growth portfolio of SA16's long-history tests, in
US dollars, on research series rather than funds.

Every input is ``RESTATED``, labelled by the month it describes. A decision
at the end of month *t* reads the levels of months up to *t* and sets what is
held over month *t+1*; nothing here reads a later month. The book is not
tradable and its costs are a declared hypothesis.

The functions are pure and perform no I/O; the script hands them parsed data.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class SwitchMonth:
    """One held month of a book that is wholly in an asset or wholly in bills.

    Attributes
    ----------
    month : date
        The month held, as its first day.
    invested : bool
        Whether the asset was held over the month; bills otherwise.
    traded : bool
        Whether the book switched before the month.
    gross : float
        The month's return before costs, as a fraction.
    net : float
        The month's return after the switch's cost.
    """

    month: date
    invested: bool
    traded: bool
    gross: float
    net: float


def levels(changes: Sequence[float]) -> list[float]:
    """Return the compounded level at the end of each period, from a base of one.

    Parameters
    ----------
    changes : Sequence[float]
        Fractional changes of consecutive periods, each finite and above -1.

    Returns
    -------
    list[float]
        ``levels[t]`` is the product of ``1 + change`` up to period ``t``
        included: what is known at the end of ``t``.
    """
    level, result = 1.0, []
    for change in changes:
        if not math.isfinite(change) or change <= -1.0:
            raise ValueError("a change must be finite and above -1")
        level *= 1.0 + change
        result.append(level)
    return result


def above_average(values: Sequence[float], window: int) -> list[bool | None]:
    """Return, per period, whether the level is strictly above its trailing average.

    Parameters
    ----------
    values : Sequence[float]
        Period-end levels, in order.
    window : int
        Number of period-end levels averaged, the current one included; at
        least two.

    Returns
    -------
    list[bool | None]
        At ``t``: ``values[t] > mean(values[t - window + 1 : t + 1])``, known
        at the end of ``t``. ``None`` while fewer than ``window`` levels
        exist. A level equal to its average is not above it.
    """
    if window < 2:
        raise ValueError("the average takes at least two levels")
    result: list[bool | None] = []
    for position, value in enumerate(values):
        if position + 1 < window:
            result.append(None)
            continue
        mean = math.fsum(values[position + 1 - window : position + 1]) / window
        result.append(value > mean)
    return result


def run_switch_book(
    months: Sequence[date],
    asset: Sequence[float],
    risk_free: Sequence[float],
    signal: Sequence[bool | None],
    first_holding: date,
    last_holding: date,
    cost_rate: float,
) -> list[SwitchMonth]:
    """Hold the asset over each month whose previous month-end signal is on, bills otherwise.

    The four sequences are aligned on ``months``. The position held over the
    month at ``p`` is ``signal[p - 1]``: decided at the end of the month
    before, from levels up to it. The first month's position is taken at no
    cost, as a book bought and held is. Each later switch trades the whole
    book once and costs ``cost_rate`` of it, taken from that month's return.

    Parameters
    ----------
    months : Sequence[date]
        First days of consecutive months.
    asset : Sequence[float]
        The asset's total return over each month, as a fraction.
    risk_free : Sequence[float]
        The one-month bill's return over each month.
    signal : Sequence[bool | None]
        Per month, what its month-end says to hold over the next one.
    first_holding, last_holding : date
        First and last months held, inclusive.
    cost_rate : float
        One-way cost, as a fraction of traded value.

    Returns
    -------
    list[SwitchMonth]
        One record per held month.

    Raises
    ------
    ValueError
        If the sequences are not aligned, a holding month is not among
        ``months`` or is out of order, or a held month has no signal before
        it.
    """
    count = len(months)
    if not (len(asset) == len(risk_free) == len(signal) == count):
        raise ValueError("the series do not cover the same months")
    try:
        start, stop = months.index(first_holding), months.index(last_holding)
    except ValueError as error:
        raise ValueError("a holding month is not a month of the series") from error
    if start > stop:
        raise ValueError("the first holding month is after the last")
    if start == 0:
        raise ValueError(f"{first_holding:%Y-%m} has no month before it to decide on")
    held: bool | None = None
    book = []
    for position in range(start, stop + 1):
        wanted = signal[position - 1]
        if wanted is None:
            raise ValueError(f"{months[position]:%Y-%m} has no signal at the month-end before it")
        traded = held is not None and wanted != held
        held = wanted
        gross = asset[position] if held else risk_free[position]
        net = (1.0 - cost_rate) * (1.0 + gross) - 1.0 if traded else gross
        book.append(SwitchMonth(months[position], held, traded, gross, net))
    return book
