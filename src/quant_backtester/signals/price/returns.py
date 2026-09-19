"""Return over a fixed number of sessions."""

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
class ReturnSignal(Signal):
    """``P_t / P_{t-k} - 1`` over ``k`` sessions.

    Attributes
    ----------
    signal_id : str
        Stable name, e.g. ``"return_20d"``.
    lookback_sessions : int
        ``k``: how many sessions the return spans. The window therefore holds
        ``k + 1`` prices, which is the off-by-one worth being explicit about.
    bar_field : BarField
        Field to read.
    price_basis : PriceBasis
        ``TOTAL_RETURN`` counts distributions as reinvested, ``RAW`` does not.
        There is no default: an ETF paying 2% a year is not falling 2% a year,
        and which of the two is meant has to be said.
    max_age_sessions : int
        Largest accepted age of the freshest price, in sessions of the
        reference calendar.

    Raises
    ------
    ValueError
        If ``lookback_sessions`` is not a positive integer, or
        ``max_age_sessions`` is negative. Configuration mistakes, so they stop
        the run rather than become a status.
    """

    signal_id: str
    lookback_sessions: int
    price_basis: PriceBasis
    bar_field: BarField = BarField.CLOSE
    max_age_sessions: int = 1

    def __post_init__(self) -> None:
        """Reject a configuration that cannot describe a return."""
        require_positive_int(self.lookback_sessions, "lookback_sessions")
        require_non_negative_int(self.max_age_sessions, "max_age_sessions")

    def definition(self) -> Mapping[str, object]:
        """Return every parameter that changes the number."""
        return {
            "type": "ReturnSignal",
            "lookback_sessions": self.lookback_sessions,
            "bar_field": self.bar_field.value,
            "price_basis": self.price_basis.value,
            "max_age_sessions": self.max_age_sessions,
            "window_mode": WindowMode.CONSECUTIVE_SESSIONS.value,
            "unit": SignalUnit.FRACTION.value,
        }

    def compute(self, context: SignalContext, instrument_ids: Sequence[str]) -> SignalResult:
        """Compute the return of each instrument over the lookback."""
        return self.compute_window(
            context,
            instrument_ids,
            spec=WindowSpec(self.lookback_sessions + 1),
            bar_field=self.bar_field,
            basis=self.price_basis,
            max_age_sessions=self.max_age_sessions,
            formula=_simple_return,
        )


def _simple_return(window: LoadedWindow) -> float | None:
    """Return ``last / first - 1``, or ``None`` when the base is not positive."""
    if window.first <= 0:
        return None
    return window.last / window.first - 1.0
