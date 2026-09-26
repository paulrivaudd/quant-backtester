"""The vocabulary every signal is described with.

Nothing here computes anything. These are the words a signal uses to say what it
needs and what it produced, and they exist so that none of it is implicit: which
window it asked for, on which prices, how old an input it tolerates, what its
number means, and - when there is no number - why.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class WindowMode(Enum):
    """What "a window of N" is counted in."""

    CONSECUTIVE_SESSIONS = "CONSECUTIVE_SESSIONS"
    """N sessions the venue actually held, with none of them missing.

    The reader drops a session it cannot serve rather than returning a ``NaN``,
    so the last N observations may span N + 3 sessions. For a momentum, a
    volatility or a drawdown that is not the same quantity, and this mode makes
    the difference refuse to pass silently.
    """

    AVAILABLE_OBSERVATIONS = "AVAILABLE_OBSERVATIONS"
    """N observations, whenever they happened.

    What a published series wants: the last N prints of an indicator, spread
    over as many sessions as the publisher took. It has to be asked for.
    """


class PriceBasis(Enum):
    """Which price series a signal reads."""

    RAW = "RAW"
    """Quoted prices, as the venue made them. What a moving-average distance is
    about: the level a chart shows, not a reinvested one."""

    ADJUSTED = "ADJUSTED"
    """Closes adjusted backwards for the corporate actions known at the decision
    instant. What a momentum is about: an ETF paying 2% a year is not falling
    2% a year.

    It is an adjusted *price*, not a total-return wealth: a dividend ``D``
    multiplies every earlier close by ``1 - D / C_prev``, a factor known at the
    ex-date's open, so the ex-date's return reads ``C_ex / (C_prev - D) - 1``
    rather than the ``(C_ex + D) / C_prev - 1`` of a holder reinvesting at the
    close (audit A08). A signal needs the first - the second waits for a close
    it has not seen - and a benchmark is valued with the second, by
    :class:`quant_backtester.analytics.comparison.BenchmarkBasis`. Named
    ``TOTAL_RETURN`` until 2026-09-26."""


class SignalUnit(Enum):
    """What a signal's number means, so nobody has to guess from its size."""

    FRACTION = "FRACTION"
    """A decimal fraction: ``0.12`` is 12%, never ``12``."""

    ANNUALIZED_VOLATILITY = "ANNUALIZED_VOLATILITY"
    """A standard deviation scaled to a year, also a decimal fraction."""

    ZSCORE = "ZSCORE"
    """Standard deviations from a rolling, strictly past mean."""

    SERIES_UNITS = "SERIES_UNITS"
    """Whatever the series itself is quoted in: percentage points for a yield,
    dollars per euro for a rate, index points for a volatility index. Not
    comparable across instruments, and not a fraction - a change of ``0.25`` on
    a ten-year yield is twenty-five basis points, not twenty-five percent."""

    RANK = "RANK"
    """Position within a cross-section, normalised to ``[0, 1]``."""

    BINARY = "BINARY"
    """``0.0`` or ``1.0``. A state, not a strength."""


class SignalStatus(Enum):
    """Why a signal has the value it has - or why it has none.

    A signal returns a status beside every number, because the four ways of
    having no number are four different things and collapsing them into ``NaN``
    is how a backtest ends up with a performance curve nobody can explain.
    """

    OK = "OK"
    """Computed, and usable."""

    NOT_LISTED = "NOT_LISTED"
    """The instrument did not exist at this date. Not a data problem: the
    strategy drops it from its universe."""

    MISSING_INPUT = "MISSING_INPUT"
    """An observation that should exist is absent, or two sources contest it.
    A hole in the data, and it should be loud."""

    STALE_INPUT = "STALE_INPUT"
    """The last observation exists but is older than this signal allows. A US
    close read on a day New York was shut, when the signal wanted today's."""

    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    """The instrument exists but has not lived long enough for the window.
    Ordinary for a fund that listed last year."""

    NON_CONSECUTIVE_HISTORY = "NON_CONSECUTIVE_HISTORY"
    """Enough observations, but a session the venue held is missing between
    them. The window would span more time than it was asked for."""

    INSUFFICIENT_CROSS_SECTION = "INSUFFICIENT_CROSS_SECTION"
    """Too few instruments had a usable signal to compare them with each other.

    Not the same thing as the formula failing: nothing was wrong with this
    instrument's own number, there was simply nobody to rank it against. A
    strategy that holds the top of a ranking wants to tell "the universe was
    too thin today" from "this name's arithmetic broke"."""

    INVALID_INPUT = "INVALID_INPUT"
    """The formula cannot be evaluated on these numbers: a zero denominator, a
    non-positive price where a ratio is taken."""


def require_positive_int(value: int, name: str) -> None:
    """Raise unless ``value`` is a positive integer.

    Parameters
    ----------
    value : int
        Parameter to check.
    name : str
        Its name, quoted in the message.

    Raises
    ------
    ValueError
        If it is not. A window of zero or of ``"20"`` is a configuration
        mistake, and it stops the run rather than producing a status: no
        instrument would have been computed correctly either.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer, got {value!r}")


def require_non_negative_int(value: int, name: str) -> None:
    """Raise unless ``value`` is a non-negative integer.

    Parameters
    ----------
    value : int
        Parameter to check.
    name : str
        Its name, quoted in the message.

    Raises
    ------
    ValueError
        If it is not. ``True`` counts as an integer to Python and would mean
        one session; ``0.5`` compares like zero. Both are a parameter written
        wrong, and neither should quietly mean something else.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer, got {value!r}")


def require_identifier(value: str, name: str) -> None:
    """Raise unless ``value`` is a name something can be called by.

    Parameters
    ----------
    value : str
        Identifier to check.
    name : str
        Its name, quoted in the message.

    Raises
    ------
    ValueError
        If it is not a string, or holds nothing but spaces. An empty id makes
        a log, a report and a snapshot key unreadable, and the snapshot would
        happily hold one.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty name, got {value!r}")


@dataclass(frozen=True, slots=True)
class WindowSpec:
    """How many points a computation needs, and in which sense.

    Attributes
    ----------
    observations : int
        Exact number of points the formula consumes. Prices, not returns: a
        volatility of 20 daily returns asks for 21 observations, and confusing
        the two is an off-by-one nobody notices in the output.
    mode : WindowMode
        What the count is in.

    Raises
    ------
    ValueError
        If fewer than two observations are asked for - one point is not a
        window, and every formula here needs at least two - or if ``mode`` is
        not a :class:`WindowMode`.

    Notes
    -----
    The mode is checked at runtime although it is typed, and that check is not
    ceremony. The code that acts on it asks ``mode is
    WindowMode.CONSECUTIVE_SESSIONS``; the string ``"CONSECUTIVE_SESSIONS"`` is
    not that object, so passing one would leave both the continuity check and
    the refusal of a published series switched off, and a signal would quietly
    measure something other than what it asked for. That is the exact failure
    this module exists to make impossible, so it cannot be left to a type
    checker nobody has to run.
    """

    observations: int
    mode: WindowMode = WindowMode.CONSECUTIVE_SESSIONS

    def __post_init__(self) -> None:
        """Reject a window that cannot describe anything."""
        if isinstance(self.observations, bool) or not isinstance(self.observations, int):
            raise ValueError(f"observations must be an int, got {self.observations!r}")
        if self.observations < 2:
            raise ValueError(f"A window needs at least 2 observations, got {self.observations}")
        if not isinstance(self.mode, WindowMode):
            raise ValueError(
                f"mode must be a WindowMode, got {self.mode!r}; a string that reads like one "
                f"would switch the window's checks off instead of turning them on"
            )
