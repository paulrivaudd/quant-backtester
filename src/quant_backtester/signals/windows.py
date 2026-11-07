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

import calendar
import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import cast
from zoneinfo import ZoneInfo

import pandas as pd

from quant_backtester.data.calendars import TradingCalendar
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
    require_positive_int,
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


MONTH_END_SAMPLING = "VENUE_LAST_SESSION_ON_OR_BEFORE_MONTH_END"
"""How :func:`load_month_end_window` reads a month end on a venue, for definitions."""

MONTH_END_WINDOW_MODE = "EXPECTED_MONTH_END_SESSIONS"
"""The window contract of :func:`load_month_end_window`: every month-end session
the venue held must be there; sessions inside a month are not read."""


def month_end_anchors(decided: date, months: int) -> tuple[date, ...]:
    """Return the day each month of a monthly window ends on, oldest first.

    Parameters
    ----------
    decided : date
        The day being decided, as the reference calendar dates the decision
        instant. It ends the latest month of the window, which is therefore
        the month to date.
    months : int
        Number of monthly returns the window holds.

    Returns
    -------
    tuple[date, ...]
        ``months + 1`` days: the last calendar day of each of the ``months``
        months before the decision's month, then ``decided`` itself.

    Raises
    ------
    ValueError
        If ``months`` is not a positive integer.
    """
    require_positive_int(months, "months")
    position = decided.year * 12 + decided.month - 1
    anchors = []
    for back in range(months, 0, -1):
        year, index = divmod(position - back, 12)
        anchors.append(date(year, index + 1, calendar.monthrange(year, index + 1)[1]))
    return (*anchors, decided)


def completed_month_cutoff(context: SignalContext) -> date:
    """Return the last calendar day before the decision's reference month.

    Parameters
    ----------
    context : SignalContext
        Environment of the decision. Its timezone-aware instant is dated on
        the reader's reference calendar, in that calendar's timezone.

    Returns
    -------
    date
        The last calendar day of the month before the decision's: a calendar
        date, not necessarily a session. A window ends at the observation
        calendar's last session on or before it.
    """
    reference = context.calendars.get(context.market.reference_calendar_id)
    day = context.as_of.astimezone(ZoneInfo(reference.timezone)).date()
    return day.replace(day=1) - timedelta(days=1)


def require_previous_month_cutoff(
    context: SignalContext, cutoff: date, venue: TradingCalendar
) -> date:
    """Return a fixed cutoff of a completed-months signal, refused unless it ends the month before.

    Parameters
    ----------
    context : SignalContext
        Environment of the decision; its instant is dated on the reader's
        reference calendar.
    cutoff : date
        The last observation date the signal was configured with, a date of
        ``venue``.
    venue : TradingCalendar
        The observation calendar: the window ends at its last session on or
        before ``cutoff``.

    Returns
    -------
    date
        ``cutoff`` itself.

    Raises
    ------
    ValueError
        If the cutoff is after the decision's day, or if the last session on
        or before it is not the last session of the month preceding the
        decision's month. A signal reading completed months reads that month,
        whole, and no other: a session of the decision's own month is a
        partial month; an earlier session of the month before (15 September,
        decided on 30 October) ends the window on a partial month too, read as
        if it were complete; and an older one is a window that a fixed date -
        the same at every decision of a run - would hand every later decision,
        each reporting a fresh, valid number. A cutoff falling after that last
        session but before the next month's first (31 October, a Saturday, or
        1 November, a Sunday) ends on it and is accepted.

    Notes
    -----
    Only for completed-months signals. A signal reading up to an arbitrary
    fixed date, for an analysis of one past window, keeps the loader's own
    contract: a completed month may be read long after its end.
    """
    reference = context.calendars.get(context.market.reference_calendar_id)
    decided = context.as_of.astimezone(ZoneInfo(reference.timezone)).date()
    if cutoff > decided:
        raise ValueError(f"observation_cutoff {cutoff} must not be after the decision on {decided}")
    last = (venue.session(cutoff) or venue.previous_session(cutoff)).session_date
    previous = completed_month_cutoff(context)
    # The month alone is not enough: a mid-month session of the month before
    # would end the window on a partial month, scored as a completed one.
    expected = (venue.session(previous) or venue.previous_session(previous)).session_date
    if last != expected:
        raise ValueError(
            f"observation_cutoff {cutoff} ends on the {venue.calendar_id} session of {last}, "
            f"not on {expected}, the last session of {previous:%Y-%m}, the month before the "
            f"decision on {decided}: a completed-months signal reads that month whole, and a "
            "fixed date reused across a run would freeze every later window"
        )
    return cutoff


def load_dated_window(
    context: SignalContext,
    instrument_id: str,
    *,
    dates: tuple[date, ...],
    basis: PriceBasis,
    nav: bool = False,
) -> LoadedWindow:
    """Read exact observation dates from PIT history, without filling holes.

    Parameters
    ----------
    context : SignalContext
        Environment of the decision: the reader serves what was available at
        its timezone-aware instant, and nothing published after it.
    instrument_id : str
        A registered instrument. A LEVEL series is read raw.
    dates : tuple[date, ...]
        The expected observation dates, oldest first, as dates of the
        observation calendar. Not empty.
    basis : PriceBasis
        Basis of a bars instrument's closes; ignored for a LEVEL series.
    nav : bool
        Also require each date's 22:15 Europe/Dublin valuation to precede the
        decision instant.

    Returns
    -------
    LoadedWindow
        The values found on ``dates``, oldest first, in the instrument's
        currency. ``OK`` only when every date is served, known at the decision
        and finite and positive. Otherwise, in the order they are asked:
        ``NOT_LISTED`` (listed after the latest date, or delisted before it),
        ``INSUFFICIENT_HISTORY`` (listed after the oldest),
        ``MISSING_INPUT`` (a date not served, or not yet known),
        ``INVALID_INPUT`` (a value not finite and positive).

    Notes
    -----
    LEVEL inputs are levels, never adjusted OHLC. For NAV, 22:15 Dublin
    valuation is only a lower bound: publication must independently be
    established by the upstream reader's availability timestamps.
    """
    instrument = context.instruments.get(instrument_id)
    series = context.series(
        instrument_id,
        BarField.CLOSE,
        PriceBasis.RAW if instrument.data_type is DataType.LEVEL else basis,
    )
    # The reader's index contract is observation dates; pandas stubs also allow ints.
    present = set(cast(list[date], series.index.tolist()))

    def visible(day: date) -> bool:
        """Return whether ``day`` is served, not after the decision, and valued before it."""
        if day not in present or day > context.as_of.date():
            return False
        return not nav or (
            datetime.combine(day, time(22, 15), ZoneInfo("Europe/Dublin")) < context.as_of
        )

    # Only the dates asked for are judged: the history around them changes nothing.
    held = tuple(day for day in dates if visible(day))
    points = tuple(float(series.loc[day]) for day in held)
    if instrument.first_session is not None and instrument.first_session > dates[-1]:
        status = SignalStatus.NOT_LISTED
    elif instrument.last_session is not None and instrument.last_session < dates[-1]:
        # Delisted before the latest date asked for: not a hole in its history
        # but a fund that no longer exists, as the reader says of it.
        status = SignalStatus.NOT_LISTED
    elif instrument.first_session is not None and instrument.first_session > dates[0]:
        status = SignalStatus.INSUFFICIENT_HISTORY
    elif len(held) != len(dates):
        status = SignalStatus.MISSING_INPUT
    elif any(not math.isfinite(value) or value <= 0 for value in points):
        status = SignalStatus.INVALID_INPUT
    else:
        status = SignalStatus.OK
    return LoadedWindow(status=status, points=points, dates=held)


def load_month_end_window(
    context: SignalContext,
    instrument_id: str,
    *,
    months: int,
    basis: PriceBasis,
    max_age_sessions: int,
    observation_cutoff: date | None = None,
    observation_calendar_id: str | None = None,
    nav: bool = False,
) -> LoadedWindow:
    """Return a fund's closes at the ``months + 1`` month ends ending at the decision.

    Parameters
    ----------
    context : SignalContext
        Environment of the decision. The month grid is fixed by its instant,
        dated on the reader's reference calendar, so every fund of one
        decision shares it.
    instrument_id : str
        A bars instrument with a venue calendar.
    months : int
        Number of monthly returns wanted.
    basis : PriceBasis
        Raw closes, or closes adjusted for the actions known at the decision.
    max_age_sessions : int
        Largest age of the freshest close, in sessions of the reference
        calendar. It must also belong to the decision's month.
    observation_cutoff : date | None
        Explicit final observation date. Availability is still checked at
        the actual decision, so a completed month can be read after its end.
        In this mode freshness is enforced by exact expected dates, rather
        than the age of a newer, unrelated observation at the decision.
    observation_calendar_id : str | None
        Expected observation calendar; mandatory for LEVEL month ends.
        BAR inputs must declare the same calendar. No missing endpoint is
        replaced by an earlier available observation.
    nav : bool
        Also enforce the 22:15 Europe/Dublin valuation lower bound.

    Returns
    -------
    LoadedWindow
        ``OK`` with the closes, oldest first, dated by the venue session each
        month end fell on; the latest is the freshest close at the decision.
        Otherwise, in the order they are asked: ``NOT_LISTED`` before the
        listing; ``INSUFFICIENT_HISTORY`` when the history does not reach the
        oldest month end, whatever the state of the latest close;
        ``MISSING_INPUT`` for a latest session with no close; ``STALE_INPUT``
        for a freshest close older than allowed or from a month already
        closed; ``MISSING_INPUT`` when a month-end session the venue held has
        no close.

    Raises
    ------
    ValueError
        If the instrument is a published series or declares no calendar, if
        a bars instrument is asked for the month ends of another calendar than
        its own or a declared subset of it, or ``max_age_sessions`` is not a
        non-negative integer:
        configuration mistakes, which stop the run.
    KeyError
        If the instrument is not registered.

    Notes
    -----
    A month ends at the venue's last session on or before its last calendar
    day (:data:`MONTH_END_SAMPLING`); a month end the provider did not serve
    is never replaced by the session before it. A hole inside a month is not
    read and changes nothing (:data:`MONTH_END_WINDOW_MODE`).

    Whether the fund is old enough is asked before whether its latest close
    is fresh: a fund that could not be eligible anyway is not a failure of
    the decision because its newest bar is late. A refused window keeps the
    month-end closes it did find.
    """
    require_non_negative_int(max_age_sessions, "max_age_sessions")
    instrument = context.instruments.get(instrument_id)
    if observation_cutoff is not None or observation_calendar_id is not None:
        reference = context.calendars.get(context.market.reference_calendar_id)
        decided = context.as_of.astimezone(ZoneInfo(reference.timezone)).date()
        cutoff = observation_cutoff or decided
        if cutoff > decided:
            raise ValueError("observation_cutoff must not be after the decision")
        calendar_id = observation_calendar_id or instrument.calendar_id
        if calendar_id is None:
            raise ValueError("LEVEL month ends require an explicit observation calendar")
        venue = context.calendars.get(calendar_id)
        # A bars instrument is read on its own venue's sessions, or on a
        # calendar declared - and checked by the registry - to be a subset of
        # them: XNYS sessions on which London is open too.
        if (
            instrument.data_type is DataType.BAR
            and instrument.calendar_id != calendar_id
            and venue.subset_of != instrument.calendar_id
        ):
            raise ValueError(
                f"{instrument_id} trades on {instrument.calendar_id} and is asked for month "
                f"ends of {calendar_id}: a configuration mistake, not a market situation"
            )
        # The window ends at the last session on or before the cutoff, and the
        # month grid is that session's. Anchored on the cutoff itself, a cutoff
        # falling before its month's first session (1 January, a Saturday 1st)
        # would end on the previous month end a second time: one month short,
        # and a flat month nobody observed.
        last = (venue.session(cutoff) or venue.previous_session(cutoff)).session_date
        anchors = month_end_anchors(last, months)
        if instrument.first_session is not None and instrument.first_session > last:
            return LoadedWindow(status=SignalStatus.NOT_LISTED)
        if instrument.first_session is not None and instrument.first_session > anchors[0]:
            return LoadedWindow(status=SignalStatus.INSUFFICIENT_HISTORY)
        dates = tuple(
            (venue.session(day) or venue.previous_session(day)).session_date for day in anchors
        )
        if len(set(dates)) != len(dates):
            raise ValueError(
                f"{calendar_id} holds no session in a month of the window ending {last}; "
                "its month ends cannot describe a monthly window"
            )
        return load_dated_window(context, instrument_id, dates=dates, basis=basis, nav=nav)
    if instrument.data_type is not DataType.BAR:
        raise ValueError(
            f"{instrument_id} is a {instrument.data_type.value} series and holds no venue "
            "month ends"
        )
    if instrument.calendar_id is None:
        raise ValueError(f"{instrument_id} is a BAR instrument and declares no calendar")

    latest = context.market.values([instrument_id], BarField.CLOSE).loc[instrument_id]
    if latest["status"] is ObservationStatus.NOT_LISTED:
        return LoadedWindow(status=SignalStatus.NOT_LISTED)
    age = None if pd.isna(latest["age_sessions"]) else int(latest["age_sessions"])
    reference = context.calendars.get(context.market.reference_calendar_id)
    decided = context.as_of.astimezone(ZoneInfo(reference.timezone)).date()
    anchors = month_end_anchors(decided, months)
    series = context.series(instrument_id, BarField.CLOSE, basis)
    observed: tuple[date, ...] = tuple(series.index)
    present = set(observed)
    venue = context.calendars.get(instrument.calendar_id)

    def month_ends(since: date) -> list[date]:
        """Return the venue's month-end sessions of the window, from ``since`` on."""
        ends = []
        for anchor in anchors[:-1]:
            if anchor >= since:  # the venue calendar need not reach before the history
                session = venue.session(anchor) or venue.previous_session(anchor)
                ends.append(session.session_date)
        return ends

    if not observed or observed[0] > anchors[0]:
        found = [day for day in month_ends(observed[0]) if day in present] if observed else []
        return LoadedWindow(
            status=SignalStatus.INSUFFICIENT_HISTORY,
            points=tuple(float(series.loc[day]) for day in found),
            dates=tuple(found),
            age_sessions=age,
        )
    refused = _STATUS_OF_OBSERVATION.get(latest["status"])
    if refused is not None or age is None:
        return LoadedWindow(status=refused or SignalStatus.MISSING_INPUT)
    freshest = observed[-1]
    if age > max_age_sessions or freshest <= anchors[-2]:
        # Too old in sessions, or from a month already closed: the decision's
        # month would have no return of its own.
        return LoadedWindow(status=SignalStatus.STALE_INPUT, age_sessions=age)
    ends = [*month_ends(observed[0]), freshest]
    held = [day for day in ends if day in present]
    points = tuple(float(series.loc[day]) for day in held)
    status = SignalStatus.OK if len(held) == len(ends) else SignalStatus.MISSING_INPUT
    return LoadedWindow(status=status, points=points, dates=tuple(held), age_sessions=age)


ADJUSTED_OPEN_CONSTRUCTION = "RAW_OPEN_TIMES_PIT_CLOSE_ADJUSTMENT_V1"
"""How an adjusted open is built: the raw open of a session times the ratio of
its adjusted close to its raw close, all three as known at the decision. A
name for metadata, not a price basis of its own."""


def load_adjusted_open_window(
    context: SignalContext,
    instrument_id: str,
    *,
    spec: WindowSpec,
    max_age_sessions: int,
) -> LoadedWindow:
    """Return a window of opens adjusted for the corporate actions known at the decision.

    Parameters
    ----------
    context : SignalContext
        Environment of the decision: every series is read through it, so all
        three come from one reader fixed at one instant.
    instrument_id : str
        A bars instrument.
    spec : WindowSpec
        How many sessions, counted in which sense.
    max_age_sessions : int
        Largest accepted age of the freshest bar, on the reference calendar.

    Returns
    -------
    LoadedWindow
        ``OK`` with, for each session ``s``, ``open_s * adjusted_close_s /
        raw_close_s``; or the status of the first of the three windows - raw
        opens, raw closes, adjusted closes - that is refused. Windows that do
        not hold the same dates give ``MISSING_INPUT``; a price that is not
        finite and strictly positive gives ``INVALID_INPUT``. A refused window
        keeps its dates and no points.

    Notes
    -----
    The adjustment factor is the reader's own, taken at the decision instant:
    a split not known yet is not in it, and a later restatement is not
    reconstructed. Nothing is filled, interpolated or dropped. The raw fields
    follow the reader's selection of source and revision; an adjusted *open*
    is not a total-return wealth, and the construction is named
    :data:`ADJUSTED_OPEN_CONSTRUCTION` in the definition of whatever uses it.
    """
    loaded = [
        load_window(
            context,
            instrument_id,
            spec=spec,
            bar_field=bar_field,
            basis=basis,
            max_age_sessions=max_age_sessions,
        )
        for bar_field, basis in (
            (BarField.OPEN, PriceBasis.RAW),
            (BarField.CLOSE, PriceBasis.RAW),
            (BarField.CLOSE, PriceBasis.ADJUSTED),
        )
    ]
    for window in loaded:
        if window.status is not SignalStatus.OK:
            return LoadedWindow(
                status=window.status, dates=window.dates, age_sessions=window.age_sessions
            )
    opens, closes, adjusted = loaded
    if not opens.dates == closes.dates == adjusted.dates:
        return LoadedWindow(
            status=SignalStatus.MISSING_INPUT, dates=opens.dates, age_sessions=opens.age_sessions
        )
    prices = (*opens.points, *closes.points, *adjusted.points)
    if any(not math.isfinite(price) or price <= 0.0 for price in prices):
        return LoadedWindow(
            status=SignalStatus.INVALID_INPUT, dates=opens.dates, age_sessions=opens.age_sessions
        )
    points = tuple(
        raw_open * adjusted_close / raw_close
        for raw_open, raw_close, adjusted_close in zip(
            opens.points, closes.points, adjusted.points, strict=True
        )
    )
    return LoadedWindow(
        status=SignalStatus.OK, points=points, dates=opens.dates, age_sessions=opens.age_sessions
    )


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
