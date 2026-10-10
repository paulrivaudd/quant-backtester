"""The path of a window: cumulative log return, cumulative relative turnover, session time.

For a decision at the evening of session ``t``, the window read is the last
``steps + volume_reference_sessions`` sessions - 120 with the defaults - of raw
closes, volumes and adjusted closes, all three through one reader fixed at
that instant. The last ``steps + 1`` closes make the path; the first
``volume_reference_sessions`` sessions give the reference the activity is
measured against. The two share one session: the last of the reference is the
path's first point, whose close starts the path and whose activity belongs to
the reference only.

With ``Q_s = raw close_s * volume_s`` a proxy of the amount traded and ``M_t``
the median of ``Q`` over the sessions *preceding* the window described, the
points ``k = 0 .. steps`` are

    P_k = price_scale * log(adjusted_{t-steps+k} / adjusted_{t-steps})
    U_k = (1 / steps) * sum_{j=1..k} Q_{t-steps+j} / M_t,        U_0 = 0
    T_k = k / steps

so ``P`` is a cumulative log return in percentage points - not a sum of price
levels - ``U`` an unsigned relative activity whose last value compares the
recent sessions with the ones before them, and ``T`` counts sessions, not
calendar days. The three move together, linearly, between two points.

**Units and availability.** Prices in the instrument's currency, volumes in
units, both as known at the decision; a volume is known at its session's
close, never at its open. ``Q`` multiplies the *raw* close by the *raw*
volume, which stays coherent through a split; it is not the exact amount
traded. Adjusted closes are restated when a corporate action becomes known.

A volume of zero that was observed stays zero. A volume that is absent makes
the window unusable. Nothing is filled, and nothing is replaced by one.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np
from numpy.typing import NDArray

from quant_backtester.data.schemas import BarField
from quant_backtester.numbers import require_finite_positive
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.types import (
    PriceBasis,
    SignalStatus,
    WindowSpec,
    require_non_negative_int,
    require_positive_int,
)
from quant_backtester.signals.windows import load_window

ZERO_VOLUME_REFERENCE = "ZERO_VOLUME_REFERENCE"
"""The median activity of the reference sessions is zero: nothing to divide by."""

NO_ACTIVITY = "NO_ACTIVITY"
"""No session of the window described traded at all."""

NON_FINITE_PATH = "NON_FINITE_PATH"
"""A point of the path is not a finite number."""

MISALIGNED_SERIES = "MISALIGNED_SERIES"
"""The closes, the volumes and the adjusted closes do not hold the same sessions."""

INVALID_PRICE_OR_VOLUME = "INVALID_PRICE_OR_VOLUME"
"""A price is not finite and positive, or a volume is not finite and non-negative."""

CLASSICAL_NAMES = (
    "log_return_20",
    "log_return_60",
    "price_over_ma20",
    "price_over_ma60",
    "volatility_20",
    "volatility_60",
    "relative_activity_20",
    "relative_activity_60",
    "relative_activity_last",
)
"""The nine classical indicators of the control, in the order they are returned."""


class UnusablePath(Exception):
    """Raised when valid inputs still give no path: a reference of zero, no activity.

    Attributes
    ----------
    reason : str
        One of :data:`ZERO_VOLUME_REFERENCE`, :data:`NO_ACTIVITY` or
        :data:`NON_FINITE_PATH`.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class SignaturePathConfig:
    """Every convention of the path. Nothing is defaulted.

    Attributes
    ----------
    steps : int
        Increments described: the path holds ``steps + 1`` points.
    volume_reference_sessions : int
        Sessions before the window whose median activity is the reference.
    price_scale : float
        What a cumulative log return is multiplied by: 100 for percentage points.
    use_volume : bool
        ``False`` for the control without the volume channel: ``U`` is then
        zero at every point, and the inputs are still required as usual.
    max_age_sessions : int
        Largest accepted age of the freshest bar.

    Raises
    ------
    ValueError
        If a count is not a positive integer or the scale is not positive.
    """

    steps: int
    volume_reference_sessions: int
    price_scale: float
    use_volume: bool
    max_age_sessions: int

    def __post_init__(self) -> None:
        """Reject a path that cannot be built."""
        require_positive_int(self.steps, "steps")
        require_positive_int(self.volume_reference_sessions, "volume_reference_sessions")
        require_non_negative_int(self.max_age_sessions, "max_age_sessions")
        require_finite_positive(self.price_scale, "price_scale")
        if not isinstance(self.use_volume, bool):
            raise ValueError(f"use_volume must be True or False, got {self.use_volume!r}")

    @property
    def required_history_sessions(self) -> int:
        """Return the sessions one path needs: the window and its reference."""
        return self.steps + self.volume_reference_sessions

    def definition(self) -> dict[str, object]:
        """Return the conventions of the path, serialisable."""
        return {
            "steps": self.steps,
            "points": self.steps + 1,
            "volume_reference_sessions": self.volume_reference_sessions,
            "required_history_sessions": self.required_history_sessions,
            "coordinates": ["cum_log_price_pct", "cum_relative_turnover", "session_time"],
            "price_scale": self.price_scale,
            "price": "ADJUSTED close, as known at the decision",
            "volume_proxy": "RAW_CLOSE_TIMES_RAW_VOLUME",
            "volume_reference": "MEDIAN_PRECEDING_SESSIONS",
            "volume_divisor_steps": self.steps,
            "use_volume": self.use_volume,
            "time_axis": "SESSION_INDEX",
            "interpolation": "PIECEWISE_LINEAR",
            "max_age_sessions": self.max_age_sessions,
        }


@dataclass(frozen=True, slots=True)
class PathInputs:
    """The three series a path is built from, or the reason there are none.

    Attributes
    ----------
    status : SignalStatus
        ``OK`` when the three windows were served, hold the same sessions and
        only valid numbers.
    dates : tuple[date, ...]
        The sessions read, oldest first.
    adjusted_closes, raw_closes, volumes : tuple[float, ...]
        The values, aligned with ``dates``; empty on a refused window.
    age_sessions : int | None
        Age of the freshest bar.
    reason : str | None
        What was wrong, beyond the status.
    """

    status: SignalStatus
    dates: tuple[date, ...] = ()
    adjusted_closes: tuple[float, ...] = ()
    raw_closes: tuple[float, ...] = ()
    volumes: tuple[float, ...] = ()
    age_sessions: int | None = None
    reason: str | None = None

    @property
    def zero_volume_sessions(self) -> int:
        """Return how many sessions traded nothing: observed zeros, kept as zeros."""
        return sum(1 for volume in self.volumes if volume == 0.0)


def load_path_inputs(
    context: SignalContext, instrument_id: str, config: SignaturePathConfig
) -> PathInputs:
    """Return the closes, volumes and adjusted closes of one window, checked.

    Parameters
    ----------
    context : SignalContext
        Environment of the decision: every series comes from its reader.
    instrument_id : str
        A bars instrument.
    config : SignaturePathConfig
        Gives the length of the window and the accepted age.

    Returns
    -------
    PathInputs
        ``OK`` with the three series over ``required_history_sessions``
        consecutive sessions; otherwise the status of the first window that
        was refused, ``MISSING_INPUT`` when the three do not hold the same
        sessions, ``INVALID_INPUT`` when a price is not finite and strictly
        positive or a volume not finite and non-negative. An observed volume
        of zero is valid.
    """
    spec = WindowSpec(config.required_history_sessions)
    loaded = [
        load_window(
            context,
            instrument_id,
            spec=spec,
            bar_field=bar_field,
            basis=basis,
            max_age_sessions=config.max_age_sessions,
        )
        for bar_field, basis in (
            (BarField.CLOSE, PriceBasis.RAW),
            (BarField.VOLUME, PriceBasis.RAW),
            (BarField.CLOSE, PriceBasis.ADJUSTED),
        )
    ]
    for window in loaded:
        if window.status is not SignalStatus.OK:
            return PathInputs(window.status, dates=window.dates, age_sessions=window.age_sessions)
    raw, volumes, adjusted = loaded
    if not raw.dates == volumes.dates == adjusted.dates:
        return PathInputs(
            SignalStatus.MISSING_INPUT,
            dates=raw.dates,
            age_sessions=raw.age_sessions,
            reason=MISALIGNED_SERIES,
        )
    prices_valid = all(
        math.isfinite(price) and price > 0.0 for price in (*raw.points, *adjusted.points)
    )
    volumes_valid = all(math.isfinite(volume) and volume >= 0.0 for volume in volumes.points)
    if not (prices_valid and volumes_valid):
        return PathInputs(
            SignalStatus.INVALID_INPUT,
            dates=raw.dates,
            age_sessions=raw.age_sessions,
            reason=INVALID_PRICE_OR_VOLUME,
        )
    return PathInputs(
        SignalStatus.OK,
        dates=raw.dates,
        adjusted_closes=adjusted.points,
        raw_closes=raw.points,
        volumes=volumes.points,
        age_sessions=raw.age_sessions,
    )


def _checked(
    adjusted_closes: Sequence[float],
    raw_closes: Sequence[float],
    volumes: Sequence[float],
    config: SignaturePathConfig,
) -> tuple[NDArray[np.float64], NDArray[np.float64], float]:
    """Return the adjusted closes, the activity and its reference, the inputs validated.

    Raises
    ------
    ValueError
        If the three series are not exactly ``required_history_sessions`` long
        or hold a number a path cannot be made of: a caller's error.
    UnusablePath
        If the reference activity is zero.
    """
    needed = config.required_history_sessions
    adjusted = np.asarray(adjusted_closes, dtype=np.float64)
    raw = np.asarray(raw_closes, dtype=np.float64)
    traded = np.asarray(volumes, dtype=np.float64)
    if not adjusted.shape == raw.shape == traded.shape == (needed,):
        raise ValueError(f"a path is built from three series of {needed} sessions each")
    if not (np.isfinite(adjusted).all() and np.isfinite(raw).all() and np.isfinite(traded).all()):
        raise ValueError("a path is built from finite numbers")
    if bool((adjusted <= 0.0).any()) or bool((raw <= 0.0).any()) or bool((traded < 0.0).any()):
        raise ValueError("a path is built from positive prices and non-negative volumes")
    activity = raw * traded
    reference = float(np.median(activity[: config.volume_reference_sessions]))
    if not reference > 0.0:
        raise UnusablePath(ZERO_VOLUME_REFERENCE)
    return adjusted, activity, reference


def build_signature_path(
    adjusted_closes: Sequence[float],
    raw_closes: Sequence[float],
    volumes: Sequence[float],
    config: SignaturePathConfig,
) -> NDArray[np.float64]:
    """Return the ``steps + 1`` points ``(P, U, T)`` of one window.

    Parameters
    ----------
    adjusted_closes, raw_closes, volumes : Sequence[float]
        ``required_history_sessions`` values each, oldest first, as known at
        the decision: the reference sessions, then the ``steps`` described.
    config : SignaturePathConfig
        The conventions of the path.

    Returns
    -------
    numpy.ndarray
        Shape ``(steps + 1, 3)``, C-contiguous ``float64``, starting at the
        origin: cumulative log return times ``price_scale``, cumulative
        relative activity divided by ``steps`` (zero throughout without the
        volume channel), and ``k / steps``.

    Raises
    ------
    ValueError
        If the inputs are not what a path is built from.
    UnusablePath
        If the reference activity is zero, no session of the window traded,
        or a point is not finite.
    """
    adjusted, activity, reference = _checked(adjusted_closes, raw_closes, volumes, config)
    steps = config.steps
    described = adjusted[-(steps + 1) :]
    price = config.price_scale * np.log(described / described[0])
    recent = activity[-steps:]
    if not float(recent.sum()) > 0.0:
        raise UnusablePath(NO_ACTIVITY)
    turnover = np.concatenate([[0.0], np.cumsum(recent / reference) / steps])
    if not config.use_volume:
        turnover = np.zeros(steps + 1)
    path = np.ascontiguousarray(
        np.column_stack([price, turnover, np.linspace(0.0, 1.0, steps + 1)]), dtype=np.float64
    )
    if not np.isfinite(path).all():
        raise UnusablePath(NON_FINITE_PATH)
    return path


def raw_trajectory(
    adjusted_closes: Sequence[float],
    raw_closes: Sequence[float],
    volumes: Sequence[float],
    config: SignaturePathConfig,
) -> NDArray[np.float64]:
    """Return the increments the path is made of: ``steps`` returns, then ``steps`` activities.

    The control that reads the whole sequence: ``price_scale * log return`` of
    each described session, in order, then ``Q / M`` of each, with the same
    reference ``M`` as the path. No price level is among them.

    Raises
    ------
    ValueError, UnusablePath
        As for :func:`build_signature_path`.
    """
    adjusted, activity, reference = _checked(adjusted_closes, raw_closes, volumes, config)
    steps = config.steps
    described = adjusted[-(steps + 1) :]
    recent = activity[-steps:]
    if not float(recent.sum()) > 0.0:
        raise UnusablePath(NO_ACTIVITY)
    returns = config.price_scale * np.log(described[1:] / described[:-1])
    values = np.concatenate([returns, recent / reference])
    if not np.isfinite(values).all():
        raise UnusablePath(NON_FINITE_PATH)
    return values


def classical_indicators(
    adjusted_closes: Sequence[float],
    raw_closes: Sequence[float],
    volumes: Sequence[float],
    config: SignaturePathConfig,
) -> NDArray[np.float64]:
    """Return the nine classical indicators of :data:`CLASSICAL_NAMES`, at the same instant.

    Cumulative log returns over 20 and 60 sessions and the close over its 20-
    and 60-session averages less one, all on adjusted closes and times
    ``price_scale``; sample standard deviations of 20 and 60 daily log returns
    times ``price_scale`` (not annualised); the mean relative activity ``Q /
    M`` over 20 and 60 sessions and that of the last session, with the same
    reference ``M`` as the path.

    Raises
    ------
    ValueError
        If the inputs are not what a path is built from, or the window
        describes fewer than 60 sessions.
    UnusablePath
        As for :func:`build_signature_path`.
    """
    adjusted, activity, reference = _checked(adjusted_closes, raw_closes, volumes, config)
    if config.steps < 60:
        raise ValueError("the classical indicators need 60 described sessions")
    recent = activity[-config.steps :]
    if not float(recent.sum()) > 0.0:
        raise UnusablePath(NO_ACTIVITY)
    scale = config.price_scale
    returns = np.log(adjusted[1:] / adjusted[:-1])
    relative = activity / reference
    values = np.array(
        [
            scale * math.log(adjusted[-1] / adjusted[-21]),
            scale * math.log(adjusted[-1] / adjusted[-61]),
            scale * (adjusted[-1] / float(adjusted[-20:].mean()) - 1.0),
            scale * (adjusted[-1] / float(adjusted[-60:].mean()) - 1.0),
            scale * float(np.std(returns[-20:], ddof=1)),
            scale * float(np.std(returns[-60:], ddof=1)),
            float(relative[-20:].mean()),
            float(relative[-60:].mean()),
            float(relative[-1]),
        ],
        dtype=np.float64,
    )
    if not np.isfinite(values).all():
        raise UnusablePath(NON_FINITE_PATH)
    return values
