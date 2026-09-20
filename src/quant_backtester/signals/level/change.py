"""Change of a published level over a number of available observations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from quant_backtester.data.instruments import DataType
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
class LevelChangeSignal(Signal):
    """``L_t - L_{t-k}``: how far a published series has moved, in its own units.

    Attributes
    ----------
    signal_id : str
        Stable name, e.g. ``"us10y_change_20o"``.
    lookback_observations : int
        ``k``: how many observations back to compare against. The window holds
        ``k + 1`` values.
    max_age_sessions : int
        Largest accepted age of the freshest observation, in sessions of the
        reference calendar. A macro series released with a lag is older than a
        close on the day it is decided on, and that lag is declared rather than
        discovered.

    Raises
    ------
    ValueError
        If ``lookback_observations`` is not a positive integer, or
        ``max_age_sessions`` is not a non-negative one.
    KeyError
        If an instrument is not registered.

    Notes
    -----
    A difference, not a return, and that is the whole point of the module. A
    yield of 4.20 that becomes 4.45 has moved twenty-five basis points; calling
    that ``+5.95%`` says something true about the number and nothing true about
    the market. Worse, a rate that crosses zero - Bunds did, for years - makes
    the ratio explode or change sign while the move itself is unremarkable.

    The number is therefore in the series' own units and is **not comparable
    across instruments**: ranking a yield change against an FX change would be
    adding basis points to cents. Standardise first
    (:class:`~quant_backtester.signals.level.zscore.LevelZScoreSignal`) if two
    series have to be compared.

    The window is counted in observations, because a published series has no
    venue sessions to count. Twenty observations of a daily rate may span
    twenty-six calendar days across a holiday week, and that is what the series
    is: the diagnostics carry the dates the window actually covered, so a
    result can always be read back against the span it was computed on.
    """

    signal_id: str
    lookback_observations: int
    max_age_sessions: int = 1

    def __post_init__(self) -> None:
        """Reject a configuration that cannot describe a change."""
        require_positive_int(self.lookback_observations, "lookback_observations")
        require_non_negative_int(self.max_age_sessions, "max_age_sessions")

    def definition(self) -> Mapping[str, object]:
        """Return every parameter that changes the number."""
        return {
            "type": "LevelChangeSignal",
            "lookback_observations": self.lookback_observations,
            "max_age_sessions": self.max_age_sessions,
            "window_mode": WindowMode.AVAILABLE_OBSERVATIONS.value,
            "unit": SignalUnit.SERIES_UNITS.value,
        }

    def compute(self, context: SignalContext, instrument_ids: Sequence[str]) -> SignalResult:
        """Compute each instrument's change over the lookback."""
        require_published(context, instrument_ids, type(self).__name__)
        return self.compute_window(
            context,
            instrument_ids,
            spec=WindowSpec(self.lookback_observations + 1, WindowMode.AVAILABLE_OBSERVATIONS),
            bar_field=BarField.CLOSE,
            basis=PriceBasis.RAW,
            max_age_sessions=self.max_age_sessions,
            formula=_change,
        )


def require_published(
    context: SignalContext, instrument_ids: Sequence[str], signal_type: str
) -> None:
    """Raise unless every instrument is a published series.

    Parameters
    ----------
    context : SignalContext
        Environment of the decision, for the registry.
    instrument_ids : Sequence[str]
        Instruments the signal was asked about.
    signal_type : str
        Name of the signal, quoted in the message.

    Raises
    ------
    ValueError
        If one of them is a bars instrument. A fund has a venue calendar, so a
        window over it must be counted in sessions in a row; counted in
        observations it would quietly accept twenty prices spanning twenty-six
        sessions, which is the one mistake this layer exists to prevent. Asking
        a level signal about a fund is a wiring mistake, so it stops the run
        rather than becoming a status.
    KeyError
        If an instrument is not registered.
    """
    for instrument_id in instrument_ids:
        instrument = context.instruments.get(instrument_id)
        if instrument.data_type is DataType.BAR:
            raise ValueError(
                f"{signal_type} reads published series; {instrument_id} is a "
                f"{instrument.data_type.value} instrument with a venue calendar, and a window "
                f"over it must be counted in sessions"
            )


def _change(window: LoadedWindow) -> float:
    """Return ``last - first``, in the units the series is published in."""
    return window.last - window.first
