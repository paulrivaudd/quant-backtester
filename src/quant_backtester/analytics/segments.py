"""Where in the day a fund earns its return: the session, or the night before it.

A close-to-close return is two returns multiplied together. The **night** runs
from the close of the previous expected session to the open of this one; the
**day** runs from that open to the close. For a fund listed in Paris that holds
American shares the night is not idle: Paris closes at 17:35 local time and New
York trades until 22:00, so the afternoon of Wall Street is paid at the next
Paris open.

Everything here is a description of a finished history. Nothing is a signal:
the segments of a session are known only once it has closed, and these
functions are never handed to a decision. Prices are read at their two ends
and nowhere else, so a segment uses no value later than its own close.

All returns are simple fractions (``0.01`` is one percent), never percentages.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import pandas as pd

NIGHT = "night"
"""Close of the previous expected session to the open of this one."""

DAY = "day"
"""Open of the session to its close."""


@dataclass(frozen=True, slots=True)
class SegmentSummary:
    """What the two segments added up to over a window.

    Attributes
    ----------
    sessions : int
        Sessions the window could serve, each with a night and a day.
    night_log_return, day_log_return : float
        Sum of the log returns of each segment. They add up to the log return
        of the fund held throughout.
    night_share : float | None
        ``night_log_return`` over their sum, ``None`` when the sum is zero. It
        is above 1 when the day lost money and below 0 when the night did.
    difference_t : float | None
        The mean of ``night - day`` log returns over its standard error, each
        session taken as one independent draw. ``None`` under two sessions or
        when the differences do not vary. Serial correlation is ignored, so
        this flatters a persistent effect.
    """

    sessions: int
    night_log_return: float
    day_log_return: float
    night_share: float | None
    difference_t: float | None


def _price(series: pd.Series, day: date, name: str) -> float:  # type: ignore[type-arg]
    """Return one price, refused unless it is finite and strictly positive."""
    value = float(series.loc[day])
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(f"{name} on {day} is {value!r}: a price is finite and positive")
    return value


def segment_returns(
    opens: pd.Series,  # type: ignore[type-arg]
    closes: pd.Series,  # type: ignore[type-arg]
    adjusted_closes: pd.Series,  # type: ignore[type-arg]
    sessions: Sequence[date],
) -> pd.DataFrame:
    """Split each close-to-close return into its night and its day.

    Parameters
    ----------
    opens, closes : pd.Series
        Raw opening and closing prices, indexed by session date, each known at
        its own auction.
    adjusted_closes : pd.Series
        Closes with the corporate actions taken out, indexed by session date.
        Only their ratios are read.
    sessions : Sequence[date]
        The expected sessions of the window, in order, from the calendar of the
        venue. They say which close is "the one before".

    Returns
    -------
    pd.DataFrame
        Columns ``night`` and ``day``, one row per session that could be
        served: its open, its close and its adjusted close are present, and so
        is the adjusted close of the expected session just before it. A session
        that cannot be served is absent, not a ``NaN``: a night measured across
        a missing session would be two nights and a day. The first expected
        session has no night and is never served.

    Raises
    ------
    ValueError
        If a price read is not finite and strictly positive.

    Notes
    -----
    The day is ``close / open - 1`` on raw prices, both of one session and so
    of one basis. The night is what is left of the adjusted close-to-close
    return once the day is taken out, so a split or a dividend on the ex-date
    is not read as an overnight move.
    """
    kept: list[date] = []
    nights: list[float] = []
    days: list[float] = []
    for position in range(1, len(sessions)):
        previous, current = sessions[position - 1], sessions[position]
        served = (
            current in opens.index
            and current in closes.index
            and current in adjusted_closes.index
            and previous in adjusted_closes.index
        )
        if not served:
            continue
        day = _price(closes, current, "close") / _price(opens, current, "open")
        whole = _price(adjusted_closes, current, "adjusted close") / _price(
            adjusted_closes, previous, "adjusted close"
        )
        kept.append(current)
        nights.append(whole / day - 1.0)
        days.append(day - 1.0)
    return pd.DataFrame(
        {NIGHT: nights, DAY: days},
        index=pd.Index(kept, dtype="object", name="session_date"),
        dtype="float64",
    )


def segment_summary(returns: pd.DataFrame) -> SegmentSummary:
    """Add up what each segment earned over a window.

    Parameters
    ----------
    returns : pd.DataFrame
        The result of :func:`segment_returns`.

    Returns
    -------
    SegmentSummary
        The log return of each segment, the share of the night, and how far
        the mean difference between them stands from zero.
    """
    night_logs = [math.log1p(float(value)) for value in returns[NIGHT]]
    day_logs = [math.log1p(float(value)) for value in returns[DAY]]
    night, day = math.fsum(night_logs), math.fsum(day_logs)
    count = len(night_logs)
    difference_t: float | None = None
    if count >= 2:
        differences = [a - b for a, b in zip(night_logs, day_logs, strict=True)]
        mean = math.fsum(differences) / count
        variance = math.fsum((value - mean) ** 2 for value in differences) / (count - 1)
        if variance > 0.0:
            difference_t = mean / math.sqrt(variance / count)
    return SegmentSummary(
        sessions=count,
        night_log_return=night,
        day_log_return=day,
        night_share=night / (night + day) if night + day != 0.0 else None,
        difference_t=difference_t,
    )


HOLD = "hold"
"""Bought once at the first close before the window and never touched."""

BOOK_COLUMNS = (HOLD, "night_gross", "night_net", "day_gross", "day_net")
"""The books of :func:`segment_books`, in the order of its columns."""


def segment_books(returns: pd.DataFrame, *, initial: float, cost_rate: float) -> pd.DataFrame:
    """Return what holding the fund on one segment only would have been worth.

    Parameters
    ----------
    returns : pd.DataFrame
        The result of :func:`segment_returns`.
    initial : float
        Capital of each book before its first trade, in the currency of the
        fund. Strictly positive.
    cost_rate : float
        What one leg costs, as a fraction of the amount traded: commission,
        half spread and slippage added together. In ``[0, 1)``.

    Returns
    -------
    pd.DataFrame
        One row per session, valued after its close, and five books:
        ``hold`` buys once and pays one leg; ``night_gross`` and ``night_net``
        buy at every close and sell at the next open; ``day_gross`` and
        ``day_net`` buy at every open and sell at the close. A gross book pays
        the price on the screen, a net one pays ``cost_rate`` on both legs of
        every segment.

    Raises
    ------
    ValueError
        If ``initial`` is not strictly positive or ``cost_rate`` is outside
        ``[0, 1)``.

    Notes
    -----
    Each book is fully invested on its segment and in cash, at no interest, on
    the other. Shares are fractional and there is no minimum commission: a
    floor per order would only make the net books worse. The books are
    compounded in an explicit loop, session by session.
    """
    if not math.isfinite(initial) or initial <= 0.0:
        raise ValueError(f"initial must be a positive amount, got {initial!r}")
    if not math.isfinite(cost_rate) or not 0.0 <= cost_rate < 1.0:
        raise ValueError(f"cost_rate is a fraction in [0, 1), got {cost_rate!r}")
    round_trip = (1.0 - cost_rate) / (1.0 + cost_rate)
    hold = initial / (1.0 + cost_rate)
    night_gross = night_net = day_gross = day_net = initial
    rows: list[tuple[float, float, float, float, float]] = []
    for night, day in zip(returns[NIGHT], returns[DAY], strict=True):
        hold *= (1.0 + float(night)) * (1.0 + float(day))
        night_gross *= 1.0 + float(night)
        night_net *= (1.0 + float(night)) * round_trip
        day_gross *= 1.0 + float(day)
        day_net *= (1.0 + float(day)) * round_trip
        rows.append((hold, night_gross, night_net, day_gross, day_net))
    return pd.DataFrame(rows, columns=list(BOOK_COLUMNS), index=returns.index, dtype="float64")
