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

    TOTAL_RETURN = "TOTAL_RETURN"
    """Prices adjusted for the corporate actions known at the decision instant.
    What a momentum is about: an ETF paying 2% a year is not falling 2% a year."""


class SignalUnit(Enum):
    """What a signal's number means, so nobody has to guess from its size."""

    FRACTION = "FRACTION"
    """A decimal fraction: ``0.12`` is 12%, never ``12``."""

    ANNUALIZED_VOLATILITY = "ANNUALIZED_VOLATILITY"
    """A standard deviation scaled to a year, also a decimal fraction."""

    ZSCORE = "ZSCORE"
    """Standard deviations from a rolling, strictly past mean."""

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

    INVALID_INPUT = "INVALID_INPUT"
    """The formula cannot be evaluated on these numbers: a zero denominator, a
    non-positive price where a ratio is taken."""


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
        If fewer than two observations are asked for. One point is not a
        window, and every formula here needs at least two.
    """

    observations: int
    mode: WindowMode = WindowMode.CONSECUTIVE_SESSIONS

    def __post_init__(self) -> None:
        """Reject a window that cannot describe anything."""
        if isinstance(self.observations, bool) or not isinstance(self.observations, int):
            raise ValueError(f"observations must be an int, got {self.observations!r}")
        if self.observations < 2:
            raise ValueError(f"A window needs at least 2 observations, got {self.observations}")
