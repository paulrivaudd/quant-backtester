"""Trading calendars: sessions, real opening and closing instants.

A calendar is data, never an assumption. It is what turns a ``session_date``
label into the two UTC instants that gate availability: the opening auction and
the closing auction. Everything downstream depends on it being right, which is
why it is the first thing to implement and the easiest to test offline.

Half days are part of the calendar, not an exception to it: NYSE closes at 13:00
ET the day after Thanksgiving and on 24 December, and Euronext Paris has its own
early closes. A fixed close time would mis-stamp exactly those sessions.
"""

from __future__ import annotations

import tomllib
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MAX_CLOSED_DAYS = 14
"""Longest run of consecutive closed days searched before giving up.

A weekend plus a holiday week is well under it; running past it means the
holiday list does not cover the date, not that the venue is shut.
"""


class CalendarCoverageError(LookupError):
    """A date outside the period a calendar's holiday list is complete for.

    Outside that period the calendar has no data. Answering "open" on every
    weekday would invent sessions on real holidays - 11 September 2001, Christmas
    2016 - and nothing downstream would notice.
    """


def _require_date(day: object, calendar_id: str, method: str) -> None:
    """Raise ``TypeError`` unless ``day`` is exactly a ``date``, not a ``datetime``."""
    if type(day) is not date:
        raise TypeError(f"{calendar_id}: {method} expects a date, got {day!r}")


@dataclass(frozen=True, slots=True)
class Session:
    """One trading session, with its real boundaries in UTC.

    Attributes
    ----------
    session_date : date
        Exchange-local calendar day. A label, not an instant - which is why it
        carries no timezone.
    open_utc : datetime
        Timezone-aware UTC instant of the opening auction.
    close_utc : datetime
        Timezone-aware UTC instant of the closing auction.
    is_half_day : bool
        Whether the session closed early.
    """

    session_date: date
    open_utc: datetime
    close_utc: datetime
    is_half_day: bool


CALENDAR_KEYS = frozenset(
    {
        "calendar_id",
        "timezone",
        "regular_open",
        "regular_close",
        "covered_from",
        "covered_until",
        "holidays",
        "early_closes",
    }
)
"""Keys a calendar TOML file must carry, and the only ones it may carry."""


def _as_local_time(value: object, key: str, path: Path) -> time:
    """Return a local wall-clock time from either TOML spelling.

    Parameters
    ----------
    value : object
        Value parsed from TOML: a native local time (``09:30:00``) or a string
        (``"09:30:00"``).
    key : str
        Name of the setting, quoted in the error message.
    path : Path
        File the value was read from.

    Returns
    -------
    time
        The naive exchange-local time.

    Raises
    ------
    ValueError
        If the value is neither. ``time.fromisoformat`` alone would raise a
        ``TypeError`` on a native time or an integer, naming neither the key nor
        the file.
    """
    if isinstance(value, time):
        return value
    message = f"{path} has {key} = {value!r}; expected a local time such as 09:30:00"
    if not isinstance(value, str):
        raise ValueError(message)
    try:
        return time.fromisoformat(value)
    except ValueError:
        raise ValueError(message) from None


class TradingCalendar:
    """Sessions and their boundaries for one venue.

    Parameters
    ----------
    calendar_id : str
        MIC-style identifier, e.g. ``"XNYS"`` or ``"XPAR"``.
    timezone : str
        IANA zone of the venue, e.g. ``"America/New_York"``. The UTC offset of a
        session is derived from it per date, never hard-coded.
    regular_open : time
        Local opening time on a regular session.
    regular_close : time
        Local closing time on a regular session.
    holidays : frozenset[date]
        Weekdays on which the venue is closed.
    early_closes : Mapping[date, time]
        Sessions closing before ``regular_close``, with their local close time.
    covered_from, covered_until : date
        Inclusive period for which ``holidays`` and ``early_closes`` are
        complete. Every holiday and early close lies inside it, and any date
        outside it raises :class:`CalendarCoverageError` instead of being
        assumed a regular weekday.
    """

    def __init__(
        self,
        calendar_id: str,
        timezone: str,
        regular_open: time,
        regular_close: time,
        holidays: frozenset[date],
        early_closes: Mapping[date, time],
        covered_from: date,
        covered_until: date,
    ) -> None:
        self._calendar_id = calendar_id
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"{calendar_id}: unknown timezone {timezone!r}") from None
        if regular_open.tzinfo is not None or regular_close.tzinfo is not None:
            raise ValueError(
                f"{calendar_id}: regular_open and regular_close must be naive local times"
            )
        if regular_open >= regular_close:
            raise ValueError(f"{calendar_id}: regular_open must be before regular_close")
        for name, bound in (("covered_from", covered_from), ("covered_until", covered_until)):
            if type(bound) is not date:
                raise ValueError(f"{calendar_id}: {name} {bound!r} is not a date")
        if covered_from > covered_until:
            raise ValueError(
                f"{calendar_id}: covered_from {covered_from} is after covered_until {covered_until}"
            )
        for day in holidays:
            if type(day) is not date:
                raise ValueError(f"{calendar_id}: holiday {day} is not a date")
            if day.weekday() >= 5:
                raise ValueError(f"{calendar_id}: holiday {day} falls on a weekend")
            if not covered_from <= day <= covered_until:
                raise ValueError(f"{calendar_id}: holiday {day} is outside the covered period")
        for day, close in early_closes.items():
            if type(day) is not date:
                raise ValueError(f"{calendar_id}: early close {day} is not a date")
            if not covered_from <= day <= covered_until:
                raise ValueError(f"{calendar_id}: early close {day} is outside the covered period")
            if not regular_open < close < regular_close:
                raise ValueError(
                    f"{calendar_id}: early close on {day} at {close} is outside the regular session"
                )
            if day in holidays:
                raise ValueError(f"{calendar_id}: early close on {day} is also a holiday")
            if day.weekday() >= 5:
                raise ValueError(f"{calendar_id}: early close on {day} falls on a weekend")
        self._timezone = timezone
        self._regular_open = regular_open
        self._regular_close = regular_close
        # Copies: a caller mutating its own set or dict afterwards must not rewrite history.
        self._holidays = frozenset(holidays)
        self._early_closes = dict(early_closes)
        self._covered_from = covered_from
        self._covered_until = covered_until

    def definition(self) -> dict[str, object]:
        """Return everything the calendar says, in a canonical, serialisable form.

        Returns
        -------
        dict[str, object]
            Its id, timezone, regular hours, holidays and early closes (sorted)
            and its coverage, as ISO strings. Two calendars with one id and a
            different holiday have different definitions - which is what lets
            a run that was handed one in memory be told apart from a run
            handed the other (audit R07).
        """
        return {
            "calendar_id": self._calendar_id,
            "timezone": self._timezone,
            "regular_open": self._regular_open.isoformat(),
            "regular_close": self._regular_close.isoformat(),
            "holidays": sorted(day.isoformat() for day in self._holidays),
            "early_closes": {
                day.isoformat(): at.isoformat() for day, at in sorted(self._early_closes.items())
            },
            "covered_from": self._covered_from.isoformat(),
            "covered_until": self._covered_until.isoformat(),
        }

    @classmethod
    def from_toml(cls, path: Path) -> TradingCalendar:
        """Load a calendar from a committed TOML file.

        Parameters
        ----------
        path : Path
            File holding the venue settings, its holiday list and its early
            closes.

        Returns
        -------
        TradingCalendar
            The loaded calendar.

        Notes
        -----
        Exercice 2.2 (facile). Le fichier est de la donnee committee : ne derive
        jamais les feries par une regle ("4e jeudi de novembre"), la liste est
        plus courte a maintenir qu'a debuguer.
        """
        with path.open("rb") as fh:
            raw = tomllib.load(fh)
        # A typo such as `utc_offset` must fail, not be silently ignored.
        unknown = set(raw) - CALENDAR_KEYS
        if unknown:
            raise ValueError(f"{path} has unknown key(s): {', '.join(sorted(unknown))}")
        missing = CALENDAR_KEYS - set(raw)
        if missing:
            raise ValueError(f"{path} is missing required key(s): {', '.join(sorted(missing))}")
        # TOML keys are always strings, even when they look like dates: convert both sides.
        early_closes = {}
        for day, close in raw["early_closes"].items():
            early_closes[date.fromisoformat(day)] = _as_local_time(
                close, f"early_closes.{day}", path
            )
        return cls(
            calendar_id=raw["calendar_id"],
            timezone=raw["timezone"],
            regular_open=_as_local_time(raw["regular_open"], "regular_open", path),
            regular_close=_as_local_time(raw["regular_close"], "regular_close", path),
            holidays=frozenset(raw["holidays"]),
            early_closes=early_closes,
            covered_from=raw["covered_from"],
            covered_until=raw["covered_until"],
        )

    @property
    def calendar_id(self) -> str:
        """Return the venue identifier."""
        return self._calendar_id

    @property
    def timezone(self) -> str:
        """Return the IANA zone of the venue, e.g. ``"America/New_York"``."""
        return self._timezone

    @property
    def covered_from(self) -> date:
        """Return the first day the holiday list is complete for."""
        return self._covered_from

    @property
    def covered_until(self) -> date:
        """Return the last day the holiday list is complete for."""
        return self._covered_until

    def is_open(self, day: date) -> bool:
        """Return whether the venue trades on ``day``.

        Parameters
        ----------
        day : date
            Calendar day to test.

        Returns
        -------
        bool
            ``False`` on weekends and holidays. A half day is open.

        Raises
        ------
        TypeError
            If ``day`` is a ``datetime``. It subclasses ``date`` but never equals
            one, so it would slip past the holiday set and report a closed day
            as open.
        CalendarCoverageError
            If ``day`` is outside the covered period, weekends included. Every
            other method goes through this one, so none of them can answer for a
            date the holiday list does not cover.

        Notes
        -----
        Exercice 2.3 (facile).
        """
        if type(day) is not date:
            raise TypeError(f"{self._calendar_id}: is_open expects a date, got {day!r}")
        if not self._covered_from <= day <= self._covered_until:
            raise CalendarCoverageError(
                f"{self._calendar_id}: {day} is outside the covered period "
                f"{self._covered_from} to {self._covered_until}; extend {self._calendar_id}.toml"
            )
        if day.weekday() >= 5:
            return False
        return day not in self._holidays

    def session(self, day: date) -> Session | None:
        """Return the session held on ``day``, if any.

        Parameters
        ----------
        day : date
            Calendar day to look up.

        Returns
        -------
        Session | None
            ``None`` if the venue is closed that day.

        Raises
        ------
        TypeError
            If ``day`` is a ``datetime``, for the same reason as :meth:`is_open`.

        Notes
        -----
        Exercice 2.4 (le coeur du module, moyen). Construis les instants avec
        ``datetime(..., tzinfo=ZoneInfo(self._timezone))`` puis ``.astimezone(UTC)``.
        Les trois dates a verifier a la main, qui cassent toute implementation
        naive :

        - 27 novembre 2026, XNYS : demi-seance, cloture 13:00 ET.
        - 12 mars 2026, XNYS vs XPAR : les Etats-Unis sont deja a l'heure d'ete,
          l'Europe non. L'ecart entre les deux clotures n'est pas celui de juin.
        - 6 avril 2026 (lundi de Paques), XPAR ferme et XNYS ouvert : deux
          calendriers desalignes. Le 1er novembre 2026 est un dimanche.

        The UTC offset is resolved per date by the zone, never stored. Opening and
        closing times sit far from the small-hours DST switch, so no local time
        here is skipped or repeated.
        """
        if type(day) is not date:
            raise TypeError(f"{self._calendar_id}: session expects a date, got {day!r}")
        if not self.is_open(day):
            return None
        zone = ZoneInfo(self._timezone)
        close = self._early_closes.get(day, self._regular_close)
        return Session(
            session_date=day,
            open_utc=datetime.combine(day, self._regular_open, tzinfo=zone).astimezone(UTC),
            close_utc=datetime.combine(day, close, tzinfo=zone).astimezone(UTC),
            is_half_day=day in self._early_closes,
        )

    def sessions(self, start: date, end: date) -> list[Session]:
        """Return every session in ``[start, end]``, inclusive.

        Parameters
        ----------
        start, end : date
            Inclusive bounds.

        Returns
        -------
        list[Session]
            Sessions in chronological order; empty if none.

        Raises
        ------
        TypeError
            If either bound is a ``datetime``.
        ValueError
            If ``start`` is after ``end``: inverted bounds are a caller bug, not
            an empty range.

        Notes
        -----
        Exercice 2.5 (facile).
        """
        _require_date(start, self._calendar_id, "sessions")
        _require_date(end, self._calendar_id, "sessions")
        if start > end:
            raise ValueError(f"{self._calendar_id}: sessions start {start} is after end {end}")
        result = []
        day = start
        while day <= end:
            session = self.session(day)
            if session is not None:
                result.append(session)
            day += timedelta(days=1)
        return result

    def next_session(self, after: date) -> Session:
        """Return the first session strictly after ``after``.

        Parameters
        ----------
        after : date
            Exclusive lower bound.

        Returns
        -------
        Session
            The next session.

        Raises
        ------
        TypeError
            If ``after`` is a ``datetime``.
        LookupError
            If no session is found within ``MAX_CLOSED_DAYS`` days. The calendar
            cannot tell where its holiday list ends, so a long closed run means
            the data is missing rather than the venue shut.

        Notes
        -----
        Exercice 2.6 (facile). C'est cette methode qui materialise
        "signal le soir de t -> execution a l'ouverture de t+1" : borne
        explicitement le nombre de jours explores et leve plutot que de boucler
        sans fin si la liste de feries s'arrete.
        """
        _require_date(after, self._calendar_id, "next_session")
        return self._scan(after, timedelta(days=1))

    def previous_session(self, before: date) -> Session:
        """Return the last session strictly before ``before``.

        Parameters
        ----------
        before : date
            Exclusive upper bound.

        Returns
        -------
        Session
            The previous session.

        Raises
        ------
        TypeError
            If ``before`` is a ``datetime``.
        LookupError
            If no session is found within ``MAX_CLOSED_DAYS`` days, as in
            :meth:`next_session`.

        Notes
        -----
        Exercice 2.7 (facile).
        """
        _require_date(before, self._calendar_id, "previous_session")
        return self._scan(before, timedelta(days=-1))

    def _scan(self, origin: date, step: timedelta) -> Session:
        """Return the first session met stepping from ``origin``, ``origin`` excluded."""
        day = origin
        for _ in range(MAX_CLOSED_DAYS):
            day += step
            session = self.session(day)
            if session is not None:
                return session
        raise LookupError(
            f"{self._calendar_id}: no session within {MAX_CLOSED_DAYS} days of {origin}"
        )

    def sessions_between(self, start: date, end: date) -> int:
        """Count the sessions in ``(start, end]``.

        Parameters
        ----------
        start : date
            Exclusive lower bound.
        end : date
            Inclusive upper bound.

        Returns
        -------
        int
            Number of sessions, used to express staleness in sessions rather
            than in calendar days.

        Raises
        ------
        TypeError
            If either bound is a ``datetime``.
        ValueError
            If ``start`` is after ``end``.

        Notes
        -----
        Exercice 2.8 (facile). "Vieux de 3 jours" ne veut rien dire un lundi ;
        "vieux d'une seance" est sans ambiguite.
        """
        _require_date(start, self._calendar_id, "sessions_between")
        _require_date(end, self._calendar_id, "sessions_between")
        if start > end:
            raise ValueError(
                f"{self._calendar_id}: sessions_between start {start} is after end {end}"
            )
        if start == end:
            return 0
        return len(self.sessions(start + timedelta(days=1), end))


class CalendarRegistry:
    """Collection of calendars, keyed by ``calendar_id``.

    Parameters
    ----------
    calendars : Sequence[TradingCalendar]
        Calendars to index.

    Raises
    ------
    ValueError
        If two calendars share an id: the second would silently replace the
        first.
    """

    def __init__(self, calendars: Sequence[TradingCalendar]) -> None:
        self._calendars: dict[str, TradingCalendar] = {}
        for calendar in calendars:
            if calendar.calendar_id in self._calendars:
                raise ValueError(f"duplicate calendar id {calendar.calendar_id!r}")
            self._calendars[calendar.calendar_id] = calendar

    @classmethod
    def from_directory(cls, directory: Path) -> CalendarRegistry:
        """Load every ``*.toml`` calendar found in ``directory``.

        Parameters
        ----------
        directory : Path
            Folder holding one file per venue.

        Returns
        -------
        CalendarRegistry
            Registry of the loaded calendars.

        Raises
        ------
        ValueError
            If the folder holds no calendar: a wrong path must not yield an
            empty registry that fails later on the first lookup.

        Notes
        -----
        Exercice 2.10 (facile).
        """
        paths = sorted(directory.glob("*.toml"))
        if not paths:
            raise ValueError(f"no calendar (*.toml) found in {directory}")
        return cls([TradingCalendar.from_toml(path) for path in paths])

    def get(self, calendar_id: str) -> TradingCalendar:
        """Return one calendar.

        Parameters
        ----------
        calendar_id : str
            Venue identifier.

        Returns
        -------
        TradingCalendar
            The registered calendar.

        Raises
        ------
        KeyError
            If the venue is unknown.

        Notes
        -----
        Exercice 2.11 (facile).
        """
        try:
            return self._calendars[calendar_id]
        except KeyError:
            known = ", ".join(sorted(self._calendars))
            raise KeyError(f"unknown calendar {calendar_id!r}; known: {known}") from None

    def __iter__(self) -> Iterator[TradingCalendar]:
        """Iterate over calendars in id order."""
        return iter([self._calendars[key] for key in sorted(self._calendars)])
