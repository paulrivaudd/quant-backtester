"""The signals the rules read, built one way, and how a strategy reads them.

Every price signal here is taken on adjusted closes, over consecutive sessions,
with a freshest close that belongs to the session being decided
(``max_age_sessions=0``). Volatilities are sample standard deviations of log
returns scaled by ``sqrt(252)``. Stating that once is what lets two rules that
ask for "the sixty-return volatility" share one signal, and what lets the
ensemble declare the union of what its rules read.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Final

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.signals.base import Signal
from quant_backtester.signals.cross_asset.relative_residual import RelativeResidualSignal
from quant_backtester.signals.engine import SignalRequest
from quant_backtester.signals.level.vix_relief import VixReliefSignal
from quant_backtester.signals.price.momentum import MomentumSignal
from quant_backtester.signals.price.normalized_pullback import NormalizedPullbackSignal
from quant_backtester.signals.price.trend import MovingAverageCrossSignal, MovingAverageTrendSignal
from quant_backtester.signals.risk.volatility import RealizedVolatilitySignal
from quant_backtester.signals.types import PriceBasis, SignalStatus

ANNUALIZATION: Final[int] = 252
"""Sessions per year every volatility and carry of these rules is scaled by."""

PRICE_MAX_AGE_SESSIONS: Final[int] = 0
"""A fund's freshest close must be the close of the session being decided."""


def price_over_average(window_sessions: int, signal_id: str | None = None) -> Signal:
    """Return ``P_t / MA_N(t) - 1`` on adjusted closes."""
    return MovingAverageTrendSignal(
        signal_id=signal_id or f"price_over_ma{window_sessions}",
        window_sessions=window_sessions,
        price_basis=PriceBasis.ADJUSTED,
        max_age_sessions=PRICE_MAX_AGE_SESSIONS,
    )


def average_cross(fast_sessions: int, slow_sessions: int) -> Signal:
    """Return ``MA_fast / MA_slow - 1`` on adjusted closes."""
    return MovingAverageCrossSignal(
        signal_id=f"ma{fast_sessions}_over_ma{slow_sessions}",
        first_sessions=fast_sessions,
        second_sessions=slow_sessions,
        price_basis=PriceBasis.ADJUSTED,
        max_age_sessions=PRICE_MAX_AGE_SESSIONS,
    )


def momentum(lookback_sessions: int, skip_recent_sessions: int) -> Signal:
    """Return ``P_{t-S} / P_{t-L} - 1`` on adjusted closes; ``L`` includes the skip."""
    return MomentumSignal(
        signal_id=f"momentum_{lookback_sessions}s_skip{skip_recent_sessions}",
        lookback_sessions=lookback_sessions,
        skip_recent_sessions=skip_recent_sessions,
        price_basis=PriceBasis.ADJUSTED,
        max_age_sessions=PRICE_MAX_AGE_SESSIONS,
    )


def volatility(window_returns: int) -> Signal:
    """Return the annualised sample volatility of ``window_returns`` log returns."""
    return RealizedVolatilitySignal(
        signal_id=f"volatility_{window_returns}r",
        window_returns=window_returns,
        price_basis=PriceBasis.ADJUSTED,
        annualization=ANNUALIZATION,
        logarithmic=True,
        ddof=1,
        max_age_sessions=PRICE_MAX_AGE_SESSIONS,
    )


def pullback(reference_returns: int, recent_sessions: int) -> Signal:
    """Return the recent fall in the standard deviations of the returns before it."""
    return NormalizedPullbackSignal(
        signal_id=f"pullback_{recent_sessions}s_over_{reference_returns}r",
        reference_returns=reference_returns,
        recent_sessions=recent_sessions,
        price_basis=PriceBasis.ADJUSTED,
        max_age_sessions=PRICE_MAX_AGE_SESSIONS,
    )


def relative_residual(
    reference_id: str, estimation_returns: int, recent_returns: int, minimum_r_squared: float
) -> Signal:
    """Return a fund's normalised recent residual against ``reference_id``."""
    return RelativeResidualSignal(
        signal_id=f"residual_vs_{reference_id.lower()}_{estimation_returns}r_{recent_returns}r",
        reference_id=reference_id,
        estimation_returns=estimation_returns,
        recent_returns=recent_returns,
        minimum_r_squared=minimum_r_squared,
        price_basis=PriceBasis.ADJUSTED,
        max_age_sessions=PRICE_MAX_AGE_SESSIONS,
    )


def gauge_relief(
    window_observations: int, peak_minimum: float, relief_ratio: float, max_age_sessions: int
) -> Signal:
    """Return whether a published gauge has left a panic peak behind."""
    return VixReliefSignal(
        signal_id=f"relief_{window_observations}o",
        window_observations=window_observations,
        peak_minimum=peak_minimum,
        relief_ratio=relief_ratio,
        max_age_sessions=max_age_sessions,
    )


def merged_requests(requests: Iterable[SignalRequest]) -> tuple[SignalRequest, ...]:
    """Return one request per signal, over every instrument it was asked for.

    Parameters
    ----------
    requests : Iterable[SignalRequest]
        Requests over fixed lists of names, possibly naming a signal twice.

    Returns
    -------
    tuple[SignalRequest, ...]
        In order of first appearance, each instrument once.

    Raises
    ------
    ValueError
        If two different signals share an id - one would hide the other - or a
        request carries no fixed list of names.
    """
    signals: dict[str, Signal] = {}
    names: dict[str, list[str]] = {}
    for request in requests:
        signal_id = request.signal.signal_id
        known = signals.setdefault(signal_id, request.signal)
        if known != request.signal:
            raise ValueError(f"two different signals are both named {signal_id!r}")
        instruments = request.names()
        if instruments is None:
            raise ValueError(f"{signal_id} is requested without its instruments")
        merged = names.setdefault(signal_id, [])
        merged.extend(name for name in instruments if name not in merged)
    return tuple(
        SignalRequest(signal=signal, instruments=tuple(names[signal_id]))
        for signal_id, signal in signals.items()
    )


class SignalReader:
    """Reads signal values off one decision, and remembers the ones it could not.

    Parameters
    ----------
    ctx : StrategyContext
        The decision being taken.

    Notes
    -----
    A rule takes ``None`` for an input that has no value; the status that
    explains it is kept here, by instrument, so that a target left empty can
    say why. An instrument refused for several signals keeps the first reason.

    The instruments that *were* read are kept too: a rule that read its fund
    and answered cash did not lack anything to choose from, and the record of
    the decision has to be able to say so (audit 13, C04).
    """

    def __init__(self, ctx: StrategyContext) -> None:
        self._ctx = ctx
        self._unusable: dict[str, SignalStatus] = {}
        self._read: set[str] = set()

    def value(self, signal: Signal, instrument_id: str) -> float | None:
        """Return one signal's value for one instrument, ``None`` when it has none."""
        status = self._ctx.signal_status(signal.signal_id, instrument_id)
        if status is not SignalStatus.OK:
            self._unusable.setdefault(instrument_id, status)
            return None
        self._read.add(instrument_id)
        return self._ctx.signal_value_or_none(signal.signal_id, instrument_id)

    @property
    def unusable(self) -> Mapping[str, SignalStatus]:
        """Return why each instrument that could not be read could not."""
        return dict(self._unusable)

    @property
    def readable(self) -> int:
        """Return how many instruments the book may hold had every signal read usable.

        A gauge that is read and never held is not counted: it is not
        something the decision chooses among.
        """
        return len((self._read - set(self._unusable)) & set(self._ctx.universe))
