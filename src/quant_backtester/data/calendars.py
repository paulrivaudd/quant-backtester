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

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path


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
    """

    def __init__(
        self,
        calendar_id: str,
        timezone: str,
        regular_open: time,
        regular_close: time,
        holidays: frozenset[date],
        early_closes: Mapping[date, time],
    ) -> None:
        raise NotImplementedError("Exercice 2.1")

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
        raise NotImplementedError("Exercice 2.2")

    @property
    def calendar_id(self) -> str:
        """Return the venue identifier."""
        raise NotImplementedError("Exercice 2.1")

    def is_open(self, day: date) -> bool:
        """Return whether the venue trades on ``day``.

        Parameters
        ----------
        day : date
            Calendar day to test.

        Returns
        -------
        bool
            ``False`` on weekends and holidays.

        Notes
        -----
        Exercice 2.3 (facile).
        """
        raise NotImplementedError("Exercice 2.3")

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

        Notes
        -----
        Exercice 2.4 (le coeur du module, moyen). Construis les instants avec
        ``datetime(..., tzinfo=ZoneInfo(self.timezone))`` puis ``.astimezone(UTC)``.
        Les trois dates a verifier a la main, qui cassent toute implementation
        naive :

        - 27 novembre 2026, XNYS : demi-seance, cloture 13:00 ET.
        - 12 mars 2026, XNYS vs XPAR : les Etats-Unis sont deja a l'heure d'ete,
          l'Europe non. L'ecart entre les deux clotures n'est pas celui de juin.
        - 1er novembre, XPAR ferme et XNYS ouvert : deux calendriers desalignes.
        """
        raise NotImplementedError("Exercice 2.4")

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

        Notes
        -----
        Exercice 2.5 (facile).
        """
        raise NotImplementedError("Exercice 2.5")

    def next_session(self, after: date) -> Session | None:
        """Return the first session strictly after ``after``.

        Parameters
        ----------
        after : date
            Exclusive lower bound.

        Returns
        -------
        Session | None
            ``None`` if the calendar does not extend that far.

        Notes
        -----
        Exercice 2.6 (facile). C'est cette methode qui materialise
        "signal le soir de t -> execution a l'ouverture de t+1" : borne
        explicitement le nombre de jours explores et leve plutot que de boucler
        sans fin si la liste de feries s'arrete.
        """
        raise NotImplementedError("Exercice 2.6")

    def previous_session(self, before: date) -> Session | None:
        """Return the last session strictly before ``before``.

        Parameters
        ----------
        before : date
            Exclusive upper bound.

        Returns
        -------
        Session | None
            ``None`` if the calendar does not extend that far.

        Notes
        -----
        Exercice 2.7 (facile).
        """
        raise NotImplementedError("Exercice 2.7")

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

        Notes
        -----
        Exercice 2.8 (facile). "Vieux de 3 jours" ne veut rien dire un lundi ;
        "vieux d'une seance" est sans ambiguite.
        """
        raise NotImplementedError("Exercice 2.8")


class CalendarRegistry:
    """Collection of calendars, keyed by ``calendar_id``.

    Parameters
    ----------
    calendars : Sequence[TradingCalendar]
        Calendars to index.
    """

    def __init__(self, calendars: Sequence[TradingCalendar]) -> None:
        raise NotImplementedError("Exercice 2.9")

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

        Notes
        -----
        Exercice 2.10 (facile).
        """
        raise NotImplementedError("Exercice 2.10")

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
        raise NotImplementedError("Exercice 2.11")

    def __iter__(self) -> Iterator[TradingCalendar]:
        """Iterate over calendars in id order."""
        raise NotImplementedError("Exercice 2.11")
