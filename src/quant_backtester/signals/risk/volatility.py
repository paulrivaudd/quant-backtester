"""Realised volatility of daily returns, annualised."""

from __future__ import annotations

import math
import statistics
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
from quant_backtester.signals.windows import LoadedWindow, returns_of


@dataclass(frozen=True, slots=True)
class RealizedVolatilitySignal(Signal):
    """Standard deviation of ``N`` daily returns, scaled to a year.

    Attributes
    ----------
    signal_id : str
        Stable name, e.g. ``"volatility_20d"``.
    window_returns : int
        ``N``, the number of returns measured. The window holds ``N + 1``
        prices: forgetting that is how a "twenty-day" volatility ends up
        computed on nineteen returns.
    annualization : int
        Periods per year the daily figure is scaled by, as
        ``sqrt(annualization)``. Usually 252, and a parameter because it is a
        convention rather than a fact.
    logarithmic : bool
        ``True`` for ``ln(P_t / P_{t-1})``, which is the usual choice and makes
        the returns additive.
    ddof : int
        Degrees of freedom removed from the variance. ``1`` for the sample
        estimate.
    price_basis : PriceBasis
        ``TOTAL_RETURN`` or ``RAW``, said explicitly.
    bar_field : BarField
        Field to read.
    max_age_sessions : int
        Largest accepted age of the freshest price.

    Raises
    ------
    ValueError
        If the window holds fewer returns than the degrees of freedom removed,
        or a parameter is not a sensible count.
    """

    signal_id: str
    window_returns: int
    price_basis: PriceBasis
    annualization: int = 252
    logarithmic: bool = True
    ddof: int = 1
    bar_field: BarField = BarField.CLOSE
    max_age_sessions: int = 1

    def __post_init__(self) -> None:
        """Reject a configuration that cannot describe a standard deviation."""
        require_positive_int(self.window_returns, "window_returns")
        require_positive_int(self.annualization, "annualization")
        require_non_negative_int(self.ddof, "ddof")
        require_non_negative_int(self.max_age_sessions, "max_age_sessions")
        if self.window_returns <= self.ddof:
            raise ValueError(
                f"window_returns ({self.window_returns}) must exceed ddof ({self.ddof}), "
                f"or the variance has no degrees of freedom left"
            )

    def definition(self) -> Mapping[str, object]:
        """Return every parameter that changes the number."""
        return {
            "type": "RealizedVolatilitySignal",
            "window_returns": self.window_returns,
            "annualization": self.annualization,
            "logarithmic": self.logarithmic,
            "ddof": self.ddof,
            "bar_field": self.bar_field.value,
            "price_basis": self.price_basis.value,
            "max_age_sessions": self.max_age_sessions,
            "window_mode": WindowMode.CONSECUTIVE_SESSIONS.value,
            "unit": SignalUnit.ANNUALIZED_VOLATILITY.value,
        }

    def compute(self, context: SignalContext, instrument_ids: Sequence[str]) -> SignalResult:
        """Compute each instrument's annualised realised volatility."""
        return self.compute_window(
            context,
            instrument_ids,
            spec=WindowSpec(self.window_returns + 1),
            bar_field=self.bar_field,
            basis=self.price_basis,
            max_age_sessions=self.max_age_sessions,
            formula=self._volatility,
        )

    def _volatility(self, window: LoadedWindow) -> float | None:
        """Return the annualised standard deviation of the window's returns."""
        if any(point <= 0 for point in window.points):
            # A ratio of prices, and a logarithm of it, mean nothing here.
            return None
        returns = returns_of(window, logarithmic=self.logarithmic)
        deviation = statistics.stdev(returns) if self.ddof == 1 else _stdev(returns, self.ddof)
        return deviation * math.sqrt(self.annualization)


def _stdev(returns: Sequence[float], ddof: int) -> float:
    """Return the standard deviation of ``returns`` with ``ddof`` removed.

    ``statistics`` offers the sample and the population estimates only, so any
    other degrees of freedom are computed here rather than approximated.
    """
    mean = sum(returns) / len(returns)
    squares = sum((value - mean) ** 2 for value in returns)
    return math.sqrt(squares / (len(returns) - ddof))
