"""A recent fall, measured in the volatility the fund had before it fell."""

from __future__ import annotations

import math
import statistics
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
from quant_backtester.signals.windows import LoadedWindow, returns_of


@dataclass(frozen=True, slots=True)
class NormalizedPullbackSignal(Signal):
    """``-ln(P_t / P_{t-k}) / (s * sqrt(k))``: a ``k``-session fall in earlier standard deviations.

    Attributes
    ----------
    signal_id : str
        Stable name, e.g. ``"pullback_5s_over_60r"``.
    reference_returns : int
        ``n``, the number of daily log returns the standard deviation ``s`` is
        taken over. They end ``k`` sessions before the decision.
    recent_sessions : int
        ``k``, the length of the move measured, in sessions.
    price_basis : PriceBasis
        ``ADJUSTED`` or ``RAW``, said explicitly.
    bar_field : BarField
        Field to read.
    max_age_sessions : int
        Largest accepted age of the freshest price.

    Raises
    ------
    ValueError
        If ``reference_returns`` is below two - one return has no spread - or a
        parameter is not a sensible count.

    Notes
    -----
    The window holds ``n + k + 1`` consecutive closes: ``n`` reference returns,
    then ``k`` recent ones. The standard deviation is the sample one
    (``ddof=1``), per session and not annualised, and it is estimated
    **before** the move it measures: a shock that entered its own yardstick
    would look smaller the larger it was.

    Positive after a fall, negative after a rise. A reference window that did
    not move at all has no spread to divide by, and comes back
    ``INVALID_INPUT``.
    """

    signal_id: str
    reference_returns: int
    recent_sessions: int
    price_basis: PriceBasis
    bar_field: BarField = BarField.CLOSE
    max_age_sessions: int = 1

    def __post_init__(self) -> None:
        """Reject a configuration that cannot describe a normalised move."""
        require_positive_int(self.reference_returns, "reference_returns")
        require_positive_int(self.recent_sessions, "recent_sessions")
        require_non_negative_int(self.max_age_sessions, "max_age_sessions")
        if self.reference_returns < 2:
            raise ValueError(
                f"reference_returns must be at least 2 to have a spread, got "
                f"{self.reference_returns}"
            )

    def definition(self) -> Mapping[str, object]:
        """Return every parameter that changes the number."""
        return {
            "type": "NormalizedPullbackSignal",
            "reference_returns": self.reference_returns,
            "recent_sessions": self.recent_sessions,
            "reference_ends_before_recent": True,
            "ddof": 1,
            "bar_field": self.bar_field.value,
            "price_basis": self.price_basis.value,
            "max_age_sessions": self.max_age_sessions,
            "window_mode": WindowMode.CONSECUTIVE_SESSIONS.value,
            "unit": SignalUnit.ZSCORE.value,
        }

    def compute(self, context: SignalContext, instrument_ids: Sequence[str]) -> SignalResult:
        """Compute each instrument's recent fall in its earlier standard deviations."""
        return self.compute_window(
            context,
            instrument_ids,
            spec=WindowSpec(self.reference_returns + self.recent_sessions + 1),
            bar_field=self.bar_field,
            basis=self.price_basis,
            max_age_sessions=self.max_age_sessions,
            formula=self._pullback,
        )

    def _pullback(self, window: LoadedWindow) -> float | None:
        """Return the normalised fall, or ``None`` without positive prices or a spread."""
        if any(point <= 0 for point in window.points):
            return None
        reference = returns_of(window, logarithmic=True)[: self.reference_returns]
        spread = statistics.stdev(reference)
        if spread == 0.0:
            return None
        move = math.log(window.last / window.points[-1 - self.recent_sessions])
        return -move / (spread * math.sqrt(self.recent_sessions))
