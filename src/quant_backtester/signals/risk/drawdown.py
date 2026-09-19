"""How far a price sits below the highest point of its recent window."""

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
class CurrentDrawdownSignal(Signal):
    """``P_t / max(P_{t-N+1..t}) - 1``: the distance to the window's high.

    Attributes
    ----------
    signal_id : str
        Stable name, e.g. ``"drawdown_60d"``.
    window_sessions : int
        ``N``, the number of prices the high is taken over, the latest
        included.
    price_basis : PriceBasis
        ``TOTAL_RETURN`` or ``RAW``, said explicitly.
    bar_field : BarField
        Field to read.
    max_age_sessions : int
        Largest accepted age of the freshest price.

    Raises
    ------
    ValueError
        If ``window_sessions`` is below two.

    Notes
    -----
    The value is never positive: ``-0.12`` means twelve percent below the
    highest price of the window. It is not the maximum drawdown of a strategy,
    which is a property of an equity curve over a whole run, and it is not the
    all-time drawdown either - the window says which high is meant.
    """

    signal_id: str
    window_sessions: int
    price_basis: PriceBasis
    bar_field: BarField = BarField.CLOSE
    max_age_sessions: int = 1

    def __post_init__(self) -> None:
        """Reject a configuration that cannot describe a drawdown."""
        require_positive_int(self.window_sessions, "window_sessions")
        require_non_negative_int(self.max_age_sessions, "max_age_sessions")
        if self.window_sessions < 2:
            raise ValueError(
                f"window_sessions must be at least 2, got {self.window_sessions}: a price is "
                f"never below itself"
            )

    def definition(self) -> Mapping[str, object]:
        """Return every parameter that changes the number."""
        return {
            "type": "CurrentDrawdownSignal",
            "window_sessions": self.window_sessions,
            "bar_field": self.bar_field.value,
            "price_basis": self.price_basis.value,
            "max_age_sessions": self.max_age_sessions,
            "window_mode": WindowMode.CONSECUTIVE_SESSIONS.value,
            "unit": SignalUnit.FRACTION.value,
        }

    def compute(self, context: SignalContext, instrument_ids: Sequence[str]) -> SignalResult:
        """Compute each instrument's distance to its window high."""
        return self.compute_window(
            context,
            instrument_ids,
            spec=WindowSpec(self.window_sessions),
            bar_field=self.bar_field,
            basis=self.price_basis,
            max_age_sessions=self.max_age_sessions,
            formula=_current_drawdown,
        )


def _current_drawdown(window: LoadedWindow) -> float | None:
    """Return ``last / high - 1``, or ``None`` when the high is not positive."""
    high = max(window.points)
    if high <= 0:
        return None
    return window.last / high - 1.0
