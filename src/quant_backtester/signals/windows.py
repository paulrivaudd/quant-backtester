"""Loading a window, and refusing one that is not what it claims to be.

This is the only place that turns "the last N sessions" into actual numbers, and
it is centralised for one reason: the reader drops a session it cannot serve
rather than returning a ``NaN``, so ``history().tail(20)`` means *twenty
observations*, which may span twenty-six sessions. Every signal computed on such
a window would be measuring something other than what its name says.

Nothing here repairs a window. No forward fill, no interpolation, no dropping of
an inconvenient point. A missing session is information about the quality of the
input, and the layers above decide what to do about it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

from quant_backtester.data.instruments import DataType, Instrument
from quant_backtester.data.reader import ObservationStatus
from quant_backtester.data.schemas import BarField
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.types import (
    PriceBasis,
    SignalStatus,
    WindowMode,
    WindowSpec,
    require_non_negative_int,
)

_STATUS_OF_OBSERVATION = {
    ObservationStatus.NOT_LISTED: SignalStatus.NOT_LISTED,
    ObservationStatus.MISSING: SignalStatus.MISSING_INPUT,
}
"""How the reader's verdict on the latest observation becomes a signal's."""


@dataclass(frozen=True, slots=True)
class LoadedWindow:
    """The outcome of asking for a window: the points, or why there are none.

    Attributes
    ----------
    status : SignalStatus
        ``OK`` when the window is what was asked for. Anything else explains
        what was missing.
    points : tuple[float, ...]
        The observations, oldest first. On a refused window these are what
        there was: seventeen observations where twenty-one were wanted, or the
        twenty-one that turned out to span twenty-six sessions. A signal never
        computes on them - the status decides that - but a diagnostic saying
        only "not enough history" is a diagnostic nobody can act on.
    dates : tuple[date, ...]
        Their observation dates, aligned with ``points``.
    age_sessions : int | None
        Sessions of the reference calendar between the last observation and the
        decision. ``0`` means the value belongs to the session being decided on.
    """

    status: SignalStatus
    points: tuple[float, ...] = ()
    dates: tuple[date, ...] = ()
    age_sessions: int | None = None

    @property
    def last(self) -> float:
        """Return the most recent observation of an ``OK`` window."""
        return self.points[-1]

    @property
    def first(self) -> float:
        """Return the oldest observation of an ``OK`` window."""
        return self.points[0]


def load_window(
    context: SignalContext,
    instrument_id: str,
    *,
    spec: WindowSpec,
    bar_field: BarField,
    basis: PriceBasis,
    max_age_sessions: int,
) -> LoadedWindow:
    """Return the window a signal asked for, or the reason it cannot have it.

    Parameters
    ----------
    context : SignalContext
        Environment of the decision.
    instrument_id : str
        Instrument to read.
    spec : WindowSpec
        How many observations, counted in which sense.
    bar_field : BarField
        Field to read, for a bars instrument.
    basis : PriceBasis
        Raw prices, or prices adjusted for the actions known now.
    max_age_sessions : int
        Largest age of the most recent observation this signal accepts,
        counted on the engine's reference calendar - the one that makes a US
        close and a Paris close comparable on a day one venue was shut.

    Returns
    -------
    LoadedWindow
        ``OK`` and the points, or a status saying what was wrong.

    Raises
    ------
    KeyError
        If the instrument is not registered.
    ValueError
        If ``max_age_sessions`` is not a non-negative whole number of sessions,
        if consecutive sessions are asked of a published series, which has no
        venue calendar to count them on, or if a bars instrument declares no
        calendar. All configuration mistakes, so they stop the run rather than
        become a status.

    Notes
    -----
    The order matters and follows what a reader of the result would ask. Does
    the instrument exist? Is the latest value there, and recent enough? Is
    there enough history? Is that history really consecutive? Each question is
    only worth asking once the one before it is answered.
    """
    # Checked here and not only in the signals that call it: this function is
    # the contract of a window, and a future signal that does not use the usual
    # helpers must not be able to step around it. A threshold of 0.5 compares
    # like zero and True counts as one session, so either would quietly mean
    # something other than what was written.
    require_non_negative_int(max_age_sessions, "max_age_sessions")
    instrument = context.instruments.get(instrument_id)
    if spec.mode is WindowMode.CONSECUTIVE_SESSIONS and instrument.data_type is not DataType.BAR:
        raise ValueError(
            f"{instrument_id} is a {instrument.data_type.value} series and holds no venue "
            f"sessions; ask for {WindowMode.AVAILABLE_OBSERVATIONS.value}"
        )

    latest = context.market.values([instrument_id], bar_field).loc[instrument_id]
    observed = latest["status"]
    refused = _STATUS_OF_OBSERVATION.get(observed)
    if refused is not None:
        return LoadedWindow(status=refused)
    age = int(latest["age_sessions"])
    if age > max_age_sessions:
        return LoadedWindow(status=SignalStatus.STALE_INPUT, age_sessions=age)

    series = context.series(instrument_id, bar_field, basis)
    window = series.iloc[-spec.observations :]
    dates = tuple(window.index)
    points = tuple(float(value) for value in window.to_numpy(dtype="float64"))
    if len(series) < spec.observations:
        return LoadedWindow(
            status=SignalStatus.INSUFFICIENT_HISTORY,
            points=points,
            dates=dates,
            age_sessions=age,
        )

    if spec.mode is WindowMode.CONSECUTIVE_SESSIONS and not _is_consecutive(
        context, instrument, dates
    ):
        return LoadedWindow(
            status=SignalStatus.NON_CONSECUTIVE_HISTORY,
            points=points,
            dates=dates,
            age_sessions=age,
        )
    return LoadedWindow(status=SignalStatus.OK, points=points, dates=dates, age_sessions=age)


def _is_consecutive(
    context: SignalContext, instrument: Instrument, dates: tuple[date, ...]
) -> bool:
    """Return whether ``dates`` are exactly the venue's sessions over their span.

    Parameters
    ----------
    context : SignalContext
        Environment of the decision, for the calendars.
    instrument : Instrument
        Instrument the dates belong to.
    dates : tuple[date, ...]
        Observation dates of the window, oldest first.

    Returns
    -------
    bool
        ``True`` when the venue held a session on every day between the first
        and the last, and the window holds all of them. A weekend is not a gap;
        a Tuesday the venue traded and the series does not hold is.

    Raises
    ------
    ValueError
        If the instrument declares no calendar.
    """
    if instrument.calendar_id is None:
        raise ValueError(f"{instrument.id} is a BAR instrument and declares no calendar")
    calendar = context.calendars.get(instrument.calendar_id)
    expected = [session.session_date for session in calendar.sessions(dates[0], dates[-1])]
    return expected == list(dates)


def returns_of(window: LoadedWindow, *, logarithmic: bool) -> list[float]:
    """Return the successive returns of a window's prices.

    Parameters
    ----------
    window : LoadedWindow
        An ``OK`` window of prices, oldest first.
    logarithmic : bool
        ``True`` for ``ln(P_t / P_{t-1})``, ``False`` for ``P_t / P_{t-1} - 1``.

    Returns
    -------
    list[float]
        One fewer value than the window holds.

    Raises
    ------
    ValueError
        If a price is not strictly positive: a ratio of prices has no meaning
        then, and the caller turns this into ``INVALID_INPUT`` rather than
        letting a ``-inf`` travel into a standard deviation.
    """
    points = window.points
    if any(point <= 0 for point in points):
        raise ValueError("a price series must be strictly positive to take returns of it")
    if logarithmic:
        return [math.log(points[index] / points[index - 1]) for index in range(1, len(points))]
    return [points[index] / points[index - 1] - 1.0 for index in range(1, len(points))]
