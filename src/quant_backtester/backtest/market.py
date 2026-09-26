"""The market as a strategy may consult it: one instant, and no way off it.

A strategy used to receive signals and nothing else. That is the right default -
a transformation worth reusing belongs in ``signals`` - and it is too strict for
the simple rules a decision is actually made of: *if the VIX is above thirty,
stand aside*, *if the ten-year yield is above five percent, halve the position*.
Requiring a new ``Signal`` class for each of those makes the framework harder to
use without making anything safer.

So a strategy is given this façade. It holds the point-in-time reader of the
decision and exposes two things: the latest value of a series, and a window of
it. What it does not expose is the reader itself, or any method taking an
instant - there is no expression a strategy can write that reads tomorrow.

Two rules keep the shortcut honest:

- **staleness is never hidden.** A value comes back as a
  :class:`MarketObservation` carrying its status, its observation date and its
  age in sessions. A strategy that wants a plain number asks for one and says
  how old it may be;
- **the window logic is not reimplemented.** A history goes through the same
  loader every signal uses, so twenty observations that span twenty-six
  sessions are refused here exactly as they are there.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd

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
from quant_backtester.signals.windows import load_window


class UnavailableMarketData(LookupError):
    """Raised when a strategy required a number the market could not give it.

    A separate type because the two cases are handled differently: a strategy
    that asks for a value it can do without reads the status and decides, and
    one that cannot do without it stops the run rather than deciding on a
    price nobody had.
    """


@dataclass(frozen=True, slots=True)
class MarketObservation:
    """The latest value of one series at one decision instant, with its provenance.

    Attributes
    ----------
    instrument_id : str
        Instrument read.
    value : float | None
        The number, or ``None`` when there is none to give.
    status : ObservationStatus
        ``OK`` for a value of the session being decided on, ``STALE`` for one
        from an earlier session, ``MISSING`` for a hole, ``NOT_LISTED`` for an
        instrument that did not exist yet.
    observation_date : date | None
        The session or observation date the value describes.
    available_at : datetime | None
        When it became knowable.
    age_sessions : int | None
        Sessions of the reference calendar between that date and the decision.
        ``0`` for a value of the session itself.

    Notes
    -----
    Deliberately not a ``float``. ``ctx.market.price("SP500")`` returning the
    last known close would let a European strategy trade on a number two
    sessions old without anything in the code saying so, and the backtest would
    read as though the price had been there all along.
    """

    instrument_id: str
    value: float | None
    status: ObservationStatus
    observation_date: date | None = None
    available_at: datetime | None = None
    age_sessions: int | None = None

    def usable(self, max_age_sessions: int = 0) -> bool:
        """Return whether this value may be used, given how old it may be.

        Parameters
        ----------
        max_age_sessions : int
            Largest age accepted, in sessions of the reference calendar.
            ``0`` - the default - accepts only a value of the session being
            decided on.

        Returns
        -------
        bool
            ``True`` when there is a number and it is fresh enough.

        Raises
        ------
        ValueError
            If ``max_age_sessions`` is not a whole number of zero or more. An
            age is counted in sessions, so half of one is a parameter written
            wrong rather than a tolerance; ``True`` would silently mean one.
        """
        require_non_negative_int(max_age_sessions, "max_age_sessions")
        if self.value is None or self.age_sessions is None:
            return False
        return self.age_sessions <= max_age_sessions

    def require(self, max_age_sessions: int = 0) -> float:
        """Return the number, or refuse to give one.

        Parameters
        ----------
        max_age_sessions : int
            Largest age accepted, in sessions.

        Returns
        -------
        float
            The value.

        Raises
        ------
        UnavailableMarketData
            If there is no value, or it is older than allowed. A strategy that
            writes ``require`` has said it cannot decide without this number;
            the alternative - a silent ``NaN`` - makes every later comparison
            false and the strategy looks as though it chose to stand aside.
        """
        if self.value is None:
            raise UnavailableMarketData(
                f"{self.instrument_id} has no value at this decision: {self.status.value}"
            )
        if not self.usable(max_age_sessions):
            raise UnavailableMarketData(
                f"{self.instrument_id} was last observed on {self.observation_date}, "
                f"{self.age_sessions} session(s) ago, and at most {max_age_sessions} "
                "was allowed"
            )
        return self.value


@dataclass(frozen=True, slots=True)
class MarketWindow:
    """A window of one series, or the reason it is not the one that was asked for.

    Attributes
    ----------
    instrument_id : str
        Instrument read.
    status : SignalStatus
        ``OK`` when the window is what was asked for; otherwise what was
        missing - no history, a session with no price in it, a last value too
        old.
    values : tuple[float, ...]
        The observations, oldest first. On a refused window, what there was:
        a diagnostic saying only "not enough history" is one nobody can act on.
    dates : tuple[date, ...]
        Their observation dates, aligned with ``values``.
    age_sessions : int | None
        Sessions between the last observation and the decision.

    Notes
    -----
    The same object a signal works with, under another name, and produced by
    the same loader. A strategy asking for twenty observations of a fund gets
    twenty consecutive sessions or a refusal, never twenty points spanning
    twenty-six sessions.
    """

    instrument_id: str
    status: SignalStatus
    values: tuple[float, ...] = ()
    dates: tuple[date, ...] = ()
    age_sessions: int | None = None

    @property
    def ok(self) -> bool:
        """Return whether the window is usable."""
        return self.status is SignalStatus.OK

    @property
    def observations_used(self) -> int:
        """Return how many observations the window holds."""
        return len(self.values)

    @property
    def last(self) -> float:
        """Return the most recent observation.

        Raises
        ------
        UnavailableMarketData
            If the window was refused, or holds nothing.
        """
        if not self.ok or not self.values:
            raise UnavailableMarketData(
                f"the window of {self.instrument_id} is not usable: {self.status.value}"
            )
        return self.values[-1]


class StrategyMarketView:
    """What a strategy may read of the market, at the instant it is deciding.

    Parameters
    ----------
    context : SignalContext
        The environment of the decision - the point-in-time reader, the
        registry and the calendars. Taken and then **hidden**: it is held
        under a mangled private name, and no attribute, property or method of
        this class hands it back.

    Notes
    -----
    Hidden rather than merely undocumented, and the difference matters. While
    it was a public field, a strategy could write::

        ctx.market.context.market.history("ETF_WORLD").tail(20)

    and get twenty *observations*, which may span twenty-six sessions - the one
    mistake :meth:`history` goes through the window loader to make impossible.
    The reader is already fixed at the decision instant, so this was never a
    way of reading tomorrow; it was a way around the window contract, which is
    the other half of what this façade exists for.

    Built from the same context the signals were computed against, so the
    values a strategy reads and the numbers its signals produced come from one
    reader, fixed at one instant. Sharing it also shares its cache: a fund's
    closes are read once per decision whether a signal or a strategy asks.
    """

    __slots__ = ("__context", "__read")

    def __init__(self, context: SignalContext, read: set[str] | None = None) -> None:
        self.__context = context
        # Every instrument this view is asked about is noted, so a run can
        # say what the history of each series it read is - including those
        # no signal declared (audit N08, decision D23).
        self.__read: set[str] = set() if read is None else read

    def __repr__(self) -> str:
        """Return a representation that names the instant and nothing else."""
        return f"StrategyMarketView(as_of={self.as_of.isoformat()})"

    @property
    def as_of(self) -> datetime:
        """Return the decision instant this view is fixed at."""
        return self.__context.as_of

    def value(self, instrument_id: str, field: BarField = BarField.CLOSE) -> MarketObservation:
        """Return the latest knowable value of one series.

        Parameters
        ----------
        instrument_id : str
            Instrument to read.
        field : BarField
            Field to read, for a bars instrument; ignored for a published
            series, which has one value per observation.

        Returns
        -------
        MarketObservation
            The value and everything needed to judge it: its status, the date
            it describes and how many sessions old it is.

        Raises
        ------
        KeyError
            If the instrument is not registered. A name nobody declared is a
            configuration mistake, not an empty reading.
        """
        self.__context.instruments.get(instrument_id)
        self.__read.add(instrument_id)
        frame = self.__context.market.values([instrument_id], field)
        row = frame.iloc[0]
        value = row["value"]
        age = row["age_sessions"]
        published = row["available_at_utc"]
        # The reader spells "there is none" as NaN, pd.NA or NaT depending on
        # the column's dtype; pd.isna is the one test that answers for all of
        # them - ``age != age`` on a nullable integer raised (audit A04). A
        # strategy is handed None, never a missing marker to compare.
        return MarketObservation(
            instrument_id=instrument_id,
            value=None if pd.isna(value) else float(value),
            status=row["status"],
            observation_date=None if pd.isna(row["observation_date"]) else row["observation_date"],
            available_at=None if pd.isna(published) else published.to_pydatetime(),
            age_sessions=None if pd.isna(age) else int(age),
        )

    def history(
        self,
        instrument_id: str,
        observations: int,
        *,
        field: BarField = BarField.CLOSE,
        basis: PriceBasis = PriceBasis.RAW,
        mode: WindowMode = WindowMode.CONSECUTIVE_SESSIONS,
        max_age_sessions: int = 0,
    ) -> MarketWindow:
        """Return a window of one series, or the reason it cannot be had.

        Parameters
        ----------
        instrument_id : str
            Instrument to read.
        observations : int
            How many points are wanted.
        field : BarField
            Field to read, for a bars instrument.
        basis : PriceBasis
            Raw quoted prices, or prices adjusted for the actions known now.
        mode : WindowMode
            ``CONSECUTIVE_SESSIONS`` asks for N sessions in a row and refuses a
            window with a hole in it; ``AVAILABLE_OBSERVATIONS`` asks for N
            points whenever they were published, which is what a released
            series needs.
        max_age_sessions : int
            Largest age the last observation may have.

        Returns
        -------
        MarketWindow
            The points, or the status saying what was missing.

        Raises
        ------
        ValueError
            If the parameters do not describe a window: a count of zero,
            consecutive sessions asked of a published series, and so on.
        KeyError
            If the instrument is not registered.

        Notes
        -----
        This goes through the loader every signal uses rather than through
        ``history().tail(n)``. The reader drops a session it cannot serve
        instead of returning a ``NaN``, so the tail of a series is a count of
        *points*, and twenty of them can span twenty-six sessions - which is
        not the window anybody asking for twenty sessions meant.
        """
        require_positive_int(observations, "observations")
        self.__read.add(instrument_id)
        loaded = load_window(
            self.__context,
            instrument_id,
            spec=WindowSpec(observations=observations, mode=mode),
            bar_field=field,
            basis=basis,
            max_age_sessions=max_age_sessions,
        )
        return MarketWindow(
            instrument_id=instrument_id,
            status=loaded.status,
            values=loaded.points,
            dates=loaded.dates,
            age_sessions=loaded.age_sessions,
        )

    def values(
        self, instrument_ids: Sequence[str], field: BarField = BarField.CLOSE
    ) -> dict[str, MarketObservation]:
        """Return the latest value of several series, keyed by instrument.

        Parameters
        ----------
        instrument_ids : Sequence[str]
            Instruments to read.
        field : BarField
            Field to read.

        Returns
        -------
        dict[str, MarketObservation]
            One entry per instrument asked for, in the order asked.
        """
        return {name: self.value(name, field) for name in instrument_ids}
