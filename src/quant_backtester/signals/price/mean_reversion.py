"""The opposite bet to momentum: what went down comes back."""

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
class MeanReversionSignal(Signal):
    """``-(P_t / P_{t-k} - 1)``: the recent move, with its sign turned round.

    Attributes
    ----------
    signal_id : str
        Stable name, e.g. ``"reversion_5d"``.
    lookback_sessions : int
        ``k``: how many sessions the move spans. Short, usually - the effect
        this signal bets on lives over days, where a momentum lives over
        months, and the two are the same arithmetic pointing opposite ways.
    price_basis : PriceBasis
        ``ADJUSTED`` or ``RAW``, said explicitly.
    bar_field : BarField
        Field to read.
    max_age_sessions : int
        Largest accepted age of the freshest price.

    Raises
    ------
    ValueError
        If ``lookback_sessions`` is not a positive integer, or
        ``max_age_sessions`` is negative.

    Notes
    -----
    Deliberately not divided by a volatility. Dividing it makes a different
    quantity - a move measured in standard deviations rather than in percent -
    and that belongs in a signal of its own rather than behind a flag here: an
    id that keeps its name must keep its meaning.

    Nor is it a ``ReturnSignal`` with a minus sign in the strategy. The sign
    belongs to the hypothesis, and putting it here is what lets the strategy
    stay a rule about ranks rather than about directions.
    """

    signal_id: str
    lookback_sessions: int
    price_basis: PriceBasis
    bar_field: BarField = BarField.CLOSE
    max_age_sessions: int = 1

    def __post_init__(self) -> None:
        """Reject a configuration that cannot describe a move."""
        require_positive_int(self.lookback_sessions, "lookback_sessions")
        require_non_negative_int(self.max_age_sessions, "max_age_sessions")

    def definition(self) -> Mapping[str, object]:
        """Return every parameter that changes the number."""
        return {
            "type": "MeanReversionSignal",
            "lookback_sessions": self.lookback_sessions,
            "bar_field": self.bar_field.value,
            "price_basis": self.price_basis.value,
            "max_age_sessions": self.max_age_sessions,
            "window_mode": WindowMode.CONSECUTIVE_SESSIONS.value,
            "unit": SignalUnit.FRACTION.value,
        }

    def compute(self, context: SignalContext, instrument_ids: Sequence[str]) -> SignalResult:
        """Compute the reversed return of each instrument over the lookback."""
        return self.compute_window(
            context,
            instrument_ids,
            spec=WindowSpec(self.lookback_sessions + 1),
            bar_field=self.bar_field,
            basis=self.price_basis,
            max_age_sessions=self.max_age_sessions,
            formula=_reversed_return,
        )


def _reversed_return(window: LoadedWindow) -> float | None:
    """Return ``-(last / first - 1)``, or ``None`` when the base is not positive."""
    if window.first <= 0:
        return None
    return -(window.last / window.first - 1.0)
