"""A published gauge that spiked and has since come down from its peak."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from quant_backtester.data.schemas import BarField
from quant_backtester.numbers import require_finite_positive
from quant_backtester.signals.base import Signal, SignalResult
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.level.change import require_published
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
class VixReliefSignal(Signal):
    """``1`` when the window's peak was a panic and the latest level is well below it.

    Attributes
    ----------
    signal_id : str
        Stable name, e.g. ``"vix_relief_20o"``.
    window_observations : int
        How many published observations the peak is taken over, the freshest
        one included.
    peak_minimum : float
        The peak counts as a panic at or above this level, in the units the
        series is published in: ``30`` for a volatility index, never ``0.30``.
    relief_ratio : float
        The latest level is a relief at or below this fraction of the peak.
    max_age_sessions : int
        Largest accepted age of the freshest observation, in sessions of the
        reference calendar.

    Raises
    ------
    ValueError
        If the window holds fewer than two observations, the threshold is not
        a finite positive level, the ratio is not in ``(0, 1]`` or the age is
        not a non-negative integer.
    KeyError
        If an instrument is not registered.

    Notes
    -----
    ``relief = (peak >= peak_minimum) and (last <= relief_ratio * peak)``. A
    state, not a strength: the value is ``1.0`` or ``0.0``. The peak leaves the
    window by itself once it is ``window_observations`` old, and the state ends
    with it.

    The window is counted in observations available at the decision, as for
    every published series: nothing is filled, and a value published after the
    decision is not in it.
    """

    signal_id: str
    window_observations: int
    peak_minimum: float
    relief_ratio: float
    max_age_sessions: int = 1

    def __post_init__(self) -> None:
        """Reject a configuration that cannot describe a peak and a relief."""
        require_positive_int(self.window_observations, "window_observations")
        if self.window_observations < 2:
            raise ValueError(
                f"window_observations must be at least 2, got {self.window_observations}: "
                f"one observation is its own peak"
            )
        require_finite_positive(self.peak_minimum, "peak_minimum")
        require_finite_positive(self.relief_ratio, "relief_ratio")
        if self.relief_ratio > 1.0:
            raise ValueError(f"relief_ratio must be at most 1, got {self.relief_ratio}")
        require_non_negative_int(self.max_age_sessions, "max_age_sessions")

    def definition(self) -> Mapping[str, object]:
        """Return every parameter that changes the number."""
        return {
            "type": "VixReliefSignal",
            "window_observations": self.window_observations,
            "includes_latest_observation": True,
            "peak_minimum": self.peak_minimum,
            "relief_ratio": self.relief_ratio,
            "price_basis": PriceBasis.RAW.value,
            "max_age_sessions": self.max_age_sessions,
            "window_mode": WindowMode.AVAILABLE_OBSERVATIONS.value,
            "unit": SignalUnit.BINARY.value,
        }

    def compute(self, context: SignalContext, instrument_ids: Sequence[str]) -> SignalResult:
        """Compute, for each published series, whether it is in a relief."""
        require_published(context, instrument_ids, type(self).__name__)
        return self.compute_window(
            context,
            instrument_ids,
            spec=WindowSpec(self.window_observations, WindowMode.AVAILABLE_OBSERVATIONS),
            bar_field=BarField.CLOSE,
            basis=PriceBasis.RAW,
            max_age_sessions=self.max_age_sessions,
            formula=self._relief,
        )

    def _relief(self, window: LoadedWindow) -> float:
        """Return ``1.0`` when the peak was a panic and the latest level left it behind."""
        peak = max(window.points)
        relieved = peak >= self.peak_minimum and window.last <= self.relief_ratio * peak
        return 1.0 if relieved else 0.0
