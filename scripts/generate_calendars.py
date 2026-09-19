"""Generate the committed trading calendar files from ``exchange_calendars``.

The calendar files are data, not rules: holidays are listed date by date, never
derived at runtime. Listing 35 years of NYSE closures by hand is how mistakes get
in, so this script writes the lists once from ``exchange_calendars``, a
maintained dataset, and the TOML it produces is committed and reviewed as a diff.
Nothing outside this script imports the library.

Run it when a covered period is extended or the library publishes a correction::

    uv run python scripts/generate_calendars.py

Extend the horizon by about a year at a time, not ten. An exchange announces an
exceptional closure - a state funeral, a market holiday moved - months ahead,
not decades, so a calendar generated far into the future is a list of guesses
that nothing would ever contradict. ``scripts/check_calendar_coverage.py`` says
when the next extension is due.

A file is only written once it has been checked: loaded back through
``TradingCalendar.from_toml``, every session in the covered period must have the
same date, UTC open and UTC close as the library's schedule, and the venue must
fit the calendar model - one regular open time, no late open, no weekend
session, no close after the regular one.
"""

from __future__ import annotations

import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import exchange_calendars as xc

from quant_backtester.data.calendars import TradingCalendar

CALENDARS_DIR = Path(__file__).resolve().parents[1] / "market_data" / "metadata" / "calendars"
"""Where the committed calendar files live."""


@dataclass(frozen=True, slots=True)
class Venue:
    """One calendar to generate.

    Attributes
    ----------
    calendar_id : str
        MIC, both the ``exchange_calendars`` name and the file stem.
    title : str
        First comment line of the file.
    timezone : str
        IANA zone the library must agree on.
    covered_from, covered_until : date
        Inclusive period written to the file.
    coverage_note : str
        Why the period starts where it does, written above ``covered_from``.
    """

    calendar_id: str
    title: str
    timezone: str
    covered_from: date
    covered_until: date
    coverage_note: str


VENUES = (
    Venue(
        calendar_id="XNYS",
        title="NYSE trading calendar.",
        timezone="America/New_York",
        covered_from=date(1990, 1, 1),
        covered_until=date(2027, 12, 31),
        coverage_note="From 1990, the first session of the earliest NYSE instrument.",
    ),
    Venue(
        calendar_id="XPAR",
        title="Euronext Paris trading calendar.",
        timezone="Europe/Paris",
        covered_from=date(2002, 1, 1),
        covered_until=date(2027, 12, 31),
        coverage_note=(
            "From 2002, when Euronext harmonised the Paris holidays. The library also\n"
            "# models the earlier regime (Whit Monday, Bastille Day), but it has not been\n"
            "# checked against an independent source: extend only after checking it."
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class LibrarySession:
    """One session as ``exchange_calendars`` schedules it."""

    session_date: date
    open_utc: datetime
    close_utc: datetime


def library_sessions(venue: Venue) -> list[LibrarySession]:
    """Return the library's sessions over the venue's covered period.

    Parameters
    ----------
    venue : Venue
        Calendar to read.

    Returns
    -------
    list[LibrarySession]
        Sessions in chronological order, with timezone-aware UTC instants.

    Raises
    ------
    ValueError
        If the library uses another timezone than the one expected.
    """
    calendar = xc.get_calendar(
        venue.calendar_id,
        start=venue.covered_from.isoformat(),
        end=venue.covered_until.isoformat(),
    )
    if str(calendar.tz) != venue.timezone:
        raise ValueError(f"{venue.calendar_id}: library timezone {calendar.tz} != {venue.timezone}")
    schedule = calendar.schedule
    return [
        LibrarySession(
            session_date=label.date(),
            open_utc=schedule.at[label, "open"].to_pydatetime(),
            close_utc=schedule.at[label, "close"].to_pydatetime(),
        )
        for label in schedule.index
    ]


def build_toml(venue: Venue, sessions: list[LibrarySession]) -> str:
    """Render the calendar file for a venue.

    Parameters
    ----------
    venue : Venue
        Calendar to render.
    sessions : list[LibrarySession]
        The library's sessions over the covered period.

    Returns
    -------
    str
        TOML text, deterministic for a given library version.

    Raises
    ------
    ValueError
        If the venue does not fit the calendar model: several open times (a late
        open), a weekend session, or a close after the regular close.
    """
    zone = venue.timezone
    local_opens = Counter(s.open_utc.astimezone(ZoneInfo(zone)).time() for s in sessions)
    if len(local_opens) != 1:
        raise ValueError(f"{venue.calendar_id}: several open times {sorted(local_opens)}")
    (regular_open,) = local_opens
    local_closes = {s.session_date: s.close_utc.astimezone(ZoneInfo(zone)).time() for s in sessions}
    regular_close = Counter(local_closes.values()).most_common(1)[0][0]
    late = sorted(day for day, close in local_closes.items() if close > regular_close)
    if late:
        raise ValueError(f"{venue.calendar_id}: closes after {regular_close} on {late[:5]}")
    weekend = sorted(day for day in local_closes if day.weekday() >= 5)
    if weekend:
        raise ValueError(f"{venue.calendar_id}: weekend sessions on {weekend[:5]}")

    holidays = [
        day
        for day in _days(venue.covered_from, venue.covered_until)
        if day.weekday() < 5 and day not in local_closes
    ]
    early_closes = {day: close for day, close in local_closes.items() if close < regular_close}

    lines = [
        f"# {venue.title} Data, not a rule: holidays are listed, never derived.",
        "#",
        f"# Generated by scripts/generate_calendars.py from exchange_calendars {xc.__version__},",
        "# and checked session by session against it. Do not edit by hand: change the",
        "# script and regenerate, so the change shows up as a reviewed diff.",
        f'calendar_id = "{venue.calendar_id}"',
        f'timezone = "{zone}"',
        f'regular_open = "{regular_open.isoformat()}"',
        f'regular_close = "{regular_close.isoformat()}"',
        "",
        "# The lists below are complete for this period only. Any date outside it raises",
        "# CalendarCoverageError rather than being assumed a regular weekday.",
        f"# {venue.coverage_note}",
        f"covered_from = {venue.covered_from.isoformat()}",
        f"covered_until = {venue.covered_until.isoformat()}",
        "",
        "# Weekdays without a session: public holidays and exceptional closures.",
        "holidays = [",
        *(f"  {day.isoformat()}," for day in holidays),
        "]",
        "",
        "# Sessions closing early, with their local close time.",
        "[early_closes]",
        *(
            f'{day.isoformat()} = "{close.isoformat()}"'
            for day, close in sorted(early_closes.items())
        ),
    ]
    return "\n".join(lines) + "\n"


def check_against_library(path: Path, venue: Venue, sessions: list[LibrarySession]) -> None:
    """Check a rendered file session by session against the library.

    Parameters
    ----------
    path : Path
        Rendered calendar file.
    venue : Venue
        Calendar it was rendered for.
    sessions : list[LibrarySession]
        The library's sessions over the covered period.

    Raises
    ------
    ValueError
        On the first session whose date, UTC open or UTC close differs, or if
        the session counts differ.
    """
    calendar = TradingCalendar.from_toml(path)
    ours = calendar.sessions(venue.covered_from, venue.covered_until)
    if len(ours) != len(sessions):
        raise ValueError(f"{venue.calendar_id}: {len(ours)} sessions, library has {len(sessions)}")
    for mine, theirs in zip(ours, sessions, strict=True):
        if (mine.session_date, mine.open_utc, mine.close_utc) != (
            theirs.session_date,
            theirs.open_utc,
            theirs.close_utc,
        ):
            raise ValueError(
                f"{venue.calendar_id}: mismatch on {theirs.session_date}: {mine} vs {theirs}"
            )


def _days(start: date, end: date) -> list[date]:
    """Return every calendar day in ``[start, end]``."""
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def main() -> None:
    """Generate, check and write every venue's calendar file."""
    for venue in VENUES:
        sessions = library_sessions(venue)
        text = build_toml(venue, sessions)
        with tempfile.TemporaryDirectory() as scratch:
            candidate = Path(scratch) / f"{venue.calendar_id}.toml"
            candidate.write_text(text, encoding="utf-8")
            check_against_library(candidate, venue, sessions)
        target = CALENDARS_DIR / f"{venue.calendar_id}.toml"
        target.write_text(text, encoding="utf-8")
        print(f"{venue.calendar_id}: {len(sessions)} sessions checked, written to {target}")


if __name__ == "__main__":
    main()
