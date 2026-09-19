"""Momentum: a return that may stop short of the present."""

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
class MomentumSignal(Signal):
    """``P_{t-S} / P_{t-L} - 1``: the move over ``L`` sessions, last ``S`` ignored.

    Attributes
    ----------
    signal_id : str
        Stable name, e.g. ``"momentum_252d_skip20"``.
    lookback_sessions : int
        ``L``, how far back the move is measured from.
    skip_recent_sessions : int
        ``S``, how many of the most recent sessions are left out. ``0`` makes
        this the same number as a return over ``L``; it is a different signal
        all the same, and the parameter is here from the start so that turning
        it on later does not silently change what an existing id means.
    price_basis : PriceBasis
        ``TOTAL_RETURN`` or ``RAW``, said explicitly.
    bar_field : BarField
        Field to read.
    max_age_sessions : int
        Largest accepted age of the freshest price.

    Raises
    ------
    ValueError
        If ``skip_recent_sessions`` is not strictly below ``lookback_sessions``,
        or a parameter is not a sensible count.

    Notes
    -----
    Skipping the last few sessions is the usual way of measuring a twelve-month
    momentum without the one-month reversal inside it. The window still spans
    ``L + 1`` prices: the ones being compared are the first and the one ``S``
    from the end.
    """

    signal_id: str
    lookback_sessions: int
    price_basis: PriceBasis
    skip_recent_sessions: int = 0
    bar_field: BarField = BarField.CLOSE
    max_age_sessions: int = 1

    def __post_init__(self) -> None:
        """Reject a configuration that cannot describe a momentum."""
        require_positive_int(self.lookback_sessions, "lookback_sessions")
        require_non_negative_int(self.skip_recent_sessions, "skip_recent_sessions")
        require_non_negative_int(self.max_age_sessions, "max_age_sessions")
        if self.skip_recent_sessions >= self.lookback_sessions:
            raise ValueError(
                f"skip_recent_sessions ({self.skip_recent_sessions}) must be below "
                f"lookback_sessions ({self.lookback_sessions}), or there is nothing left to "
                f"measure"
            )

    def definition(self) -> Mapping[str, object]:
        """Return every parameter that changes the number."""
        return {
            "type": "MomentumSignal",
            "lookback_sessions": self.lookback_sessions,
            "skip_recent_sessions": self.skip_recent_sessions,
            "bar_field": self.bar_field.value,
            "price_basis": self.price_basis.value,
            "max_age_sessions": self.max_age_sessions,
            "window_mode": WindowMode.CONSECUTIVE_SESSIONS.value,
            "unit": SignalUnit.FRACTION.value,
        }

    def compute(self, context: SignalContext, instrument_ids: Sequence[str]) -> SignalResult:
        """Compute the momentum of each instrument."""
        return self.compute_window(
            context,
            instrument_ids,
            spec=WindowSpec(self.lookback_sessions + 1),
            bar_field=self.bar_field,
            basis=self.price_basis,
            max_age_sessions=self.max_age_sessions,
            formula=self._momentum,
        )

    def _momentum(self, window: LoadedWindow) -> float | None:
        """Return the move between the oldest price and the one before the skip."""
        base = window.first
        if base <= 0:
            return None
        end = window.points[len(window.points) - 1 - self.skip_recent_sessions]
        return end / base - 1.0
