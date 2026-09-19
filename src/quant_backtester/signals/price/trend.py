"""Distance between a price and its own moving average."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from quant_backtester.data.schemas import BarField
from quant_backtester.signals.base import (
    Signal,
    SignalResult,
    require_non_negative_int,
    require_positive_int,
)
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.types import (
    PriceBasis,
    SignalUnit,
    WindowMode,
    WindowSpec,
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
