"""How far a published level sits from its own recent distribution."""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from quant_backtester.data.schemas import BarField
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
class LevelZScoreSignal(Signal):
    """``(L_t - mean) / stdev`` over the last ``n`` observations available.

    Attributes
    ----------
    signal_id : str
        Stable name, e.g. ``"vix_zscore_60o"``.
    window_observations : int
        ``n``: how many observations the mean and the spread are taken over,
        the freshest one included.
    max_age_sessions : int
        Largest accepted age of the freshest observation, in sessions of the
        reference calendar.

    Raises
    ------
    ValueError
        If ``window_observations`` is not an integer above one, or
        ``max_age_sessions`` is not a non-negative one.
    KeyError
        If an instrument is not registered.

    Notes
    -----
    This is what makes two published series comparable at all. A yield moves in
    basis points and an FX rate in cents, so their changes cannot be ranked
    against each other; how unusual each is against its own recent history can.

    **The freshest observation is part of the window it is measured against.**
    That is the reading "the VIX is at the top of its own last quarter", and it
    is the one a strategy acting on a level wants. The other convention -
    standardising against the observations strictly before it - measures the
    surprise of the release instead, is a different quantity, and would belong
    in a signal of its own rather than behind a flag here: an id that keeps its
    name must keep its meaning. With sixty observations the two differ by about
    one part in sixty, which is small and never zero.

    The mean and the spread are taken over the window and nothing else. No
    full-sample statistic, no expanding mean over everything the store happens
    to hold today: the decision point sees ``n`` observations, and both numbers
    are computed from exactly those.

    A window whose observations are all the same value has no spread, and a
    division by it is not a large z-score but an undefined one. It comes back
    ``INVALID_INPUT`` - the case does happen, on a policy rate that has not
    moved for a quarter.
    """

    signal_id: str
    window_observations: int
    max_age_sessions: int = 1

    def __post_init__(self) -> None:
        """Reject a configuration that cannot describe a distribution."""
        require_positive_int(self.window_observations, "window_observations")
        if self.window_observations < 2:
            raise ValueError(
                f"window_observations must be at least 2 to have a spread, got "
                f"{self.window_observations}"
            )
        require_non_negative_int(self.max_age_sessions, "max_age_sessions")

    def definition(self) -> Mapping[str, object]:
        """Return every parameter that changes the number."""
        return {
            "type": "LevelZScoreSignal",
            "window_observations": self.window_observations,
            "includes_latest_observation": True,
            "max_age_sessions": self.max_age_sessions,
            "window_mode": WindowMode.AVAILABLE_OBSERVATIONS.value,
            "unit": SignalUnit.ZSCORE.value,
        }

    def compute(self, context: SignalContext, instrument_ids: Sequence[str]) -> SignalResult:
        """Compute each instrument's standardised distance from its own mean."""
        require_published(context, instrument_ids, type(self).__name__)
        return self.compute_window(
            context,
            instrument_ids,
            spec=WindowSpec(self.window_observations, WindowMode.AVAILABLE_OBSERVATIONS),
            bar_field=BarField.CLOSE,
            basis=PriceBasis.RAW,
            max_age_sessions=self.max_age_sessions,
            formula=_zscore,
        )


def _zscore(window: LoadedWindow) -> float | None:
    """Return the last point's distance from the window's mean, in its spreads.

    Parameters
    ----------
    window : LoadedWindow
        An ``OK`` window of levels, oldest first.

    Returns
    -------
    float | None
        ``None`` when the window has no spread at all, which is a series that
        did not move rather than a value infinitely far from its mean.

    Notes
    -----
    The sample standard deviation, ``ddof=1``. A window of observations is a
    sample of a distribution nobody has seen the whole of, and dividing by
    ``n`` instead would report a spread slightly smaller than the one the data
    supports - and therefore a z-score slightly larger than it earned.
    """
    spread = statistics.stdev(window.points)
    if spread == 0.0:
        return None
    return (window.last - statistics.fmean(window.points)) / spread
