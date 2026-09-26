"""Moving averages: a price against its own average, and two averages against each other."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from quant_backtester.data.schemas import BarField
from quant_backtester.signals.base import Signal, SignalResult
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.types import (
    PriceBasis,
    SignalUnit,
    WindowMode,
    WindowSpec,
    require_non_negative_int,
    require_positive_int,
)
from quant_backtester.signals.windows import LoadedWindow


@dataclass(frozen=True, slots=True)
class MovingAverageTrendSignal(Signal):
    """``P_t / MA_N(t) - 1``: how far above its own average a price sits.

    Attributes
    ----------
    signal_id : str
        Stable name, e.g. ``"trend_ma200"``.
    window_sessions : int
        ``N``, the number of prices averaged, the latest included.
    price_basis : PriceBasis
        ``RAW`` is the usual choice here: the question is about the quoted
        level a chart shows, not about a reinvested one. Said explicitly all
        the same.
    bar_field : BarField
        Field to read.
    max_age_sessions : int
        Largest accepted age of the freshest price.

    Raises
    ------
    ValueError
        If ``window_sessions`` is below two - an average of one price is that
        price, and the distance to it is always zero.

    Notes
    -----
    A positive value means the price is above its average. It does not mean
    buy: what to do about a trend belongs to the strategy.
    """

    signal_id: str
    window_sessions: int
    price_basis: PriceBasis
    bar_field: BarField = BarField.CLOSE
    max_age_sessions: int = 1

    def __post_init__(self) -> None:
        """Reject a configuration that cannot describe an average."""
        require_positive_int(self.window_sessions, "window_sessions")
        require_non_negative_int(self.max_age_sessions, "max_age_sessions")
        if self.window_sessions < 2:
            raise ValueError(
                f"window_sessions must be at least 2, got {self.window_sessions}: the "
                f"distance from a price to itself is always zero"
            )

    def definition(self) -> Mapping[str, object]:
        """Return every parameter that changes the number."""
        return {
            "type": "MovingAverageTrendSignal",
            "window_sessions": self.window_sessions,
            "bar_field": self.bar_field.value,
            "price_basis": self.price_basis.value,
            "max_age_sessions": self.max_age_sessions,
            "window_mode": WindowMode.CONSECUTIVE_SESSIONS.value,
            "unit": SignalUnit.FRACTION.value,
        }

    def compute(self, context: SignalContext, instrument_ids: Sequence[str]) -> SignalResult:
        """Compute each instrument's distance to its moving average."""
        return self.compute_window(
            context,
            instrument_ids,
            spec=WindowSpec(self.window_sessions),
            bar_field=self.bar_field,
            basis=self.price_basis,
            max_age_sessions=self.max_age_sessions,
            formula=_distance_to_average,
        )


def _distance_to_average(window: LoadedWindow) -> float | None:
    """Return ``last / mean - 1``, or ``None`` when the average is not positive."""
    average = sum(window.points) / len(window.points)
    if average <= 0:
        return None
    return window.last / average - 1.0


@dataclass(frozen=True, slots=True)
class MovingAverageCrossSignal(Signal):
    """``MA_a(t) / MA_b(t) - 1``: how far one moving average sits above another.

    Attributes
    ----------
    signal_id : str
        Stable name, e.g. ``"ma50_over_ma20"``.
    first_sessions : int
        ``a``, the number of prices in the average on top of the fraction.
    second_sessions : int
        ``b``, the number of prices in the average it is compared with.
    price_basis : PriceBasis
        ``ADJUSTED`` is the usual choice: a dividend paid inside the longer
        window lowers every later price and not the earlier ones, so on raw
        prices the short average falls below the long one for a reason that
        is not a trend. Said explicitly all the same.
    bar_field : BarField
        Field to read.
    max_age_sessions : int
        Largest accepted age of the freshest price.

    Raises
    ------
    ValueError
        If either average holds fewer than two prices, or if both hold the
        same number - an average against itself is always zero.

    Notes
    -----
    Positive when the first average is above the second. Which is the short
    one is a parameter, not a convention: the classic "golden cross" is the
    20-session average above the 50-session one, ``first_sessions=20,
    second_sessions=50``, and the reverse order measures the opposite.

    Both averages end at the same price, the latest, and are taken over one
    window of ``max(a, b)`` consecutive sessions: the shorter average is the
    tail of the longer window. A session missing inside the longer window
    therefore refuses both, rather than letting the short one be computed
    over a span the long one could not vouch for.
    """

    signal_id: str
    first_sessions: int
    second_sessions: int
    price_basis: PriceBasis
    bar_field: BarField = BarField.CLOSE
    max_age_sessions: int = 1

    def __post_init__(self) -> None:
        """Reject a configuration that cannot describe two different averages."""
        require_positive_int(self.first_sessions, "first_sessions")
        require_positive_int(self.second_sessions, "second_sessions")
        require_non_negative_int(self.max_age_sessions, "max_age_sessions")
        for name in ("first_sessions", "second_sessions"):
            if getattr(self, name) < 2:
                raise ValueError(
                    f"{name} must be at least 2, got {getattr(self, name)}: an average of "
                    f"one price is that price"
                )
        if self.first_sessions == self.second_sessions:
            raise ValueError(
                f"first_sessions and second_sessions are both {self.first_sessions}: an "
                f"average compared with itself is always zero"
            )

    def definition(self) -> Mapping[str, object]:
        """Return every parameter that changes the number."""
        return {
            "type": "MovingAverageCrossSignal",
            "first_sessions": self.first_sessions,
            "second_sessions": self.second_sessions,
            "bar_field": self.bar_field.value,
            "price_basis": self.price_basis.value,
            "max_age_sessions": self.max_age_sessions,
            "window_mode": WindowMode.CONSECUTIVE_SESSIONS.value,
            "unit": SignalUnit.FRACTION.value,
        }

    def compute(self, context: SignalContext, instrument_ids: Sequence[str]) -> SignalResult:
        """Compute, for each instrument, the first average relative to the second."""
        return self.compute_window(
            context,
            instrument_ids,
            spec=WindowSpec(max(self.first_sessions, self.second_sessions)),
            bar_field=self.bar_field,
            basis=self.price_basis,
            max_age_sessions=self.max_age_sessions,
            formula=self._ratio_of_averages,
        )

    def _ratio_of_averages(self, window: LoadedWindow) -> float | None:
        """Return ``MA_a / MA_b - 1`` over the window's tail, or ``None`` below a positive base."""
        first = _average_of_last(window.points, self.first_sessions)
        second = _average_of_last(window.points, self.second_sessions)
        if second <= 0:
            return None
        return first / second - 1.0


def _average_of_last(points: Sequence[float], count: int) -> float:
    """Return the plain mean of the ``count`` most recent points."""
    tail = points[-count:]
    return sum(tail) / len(tail)
