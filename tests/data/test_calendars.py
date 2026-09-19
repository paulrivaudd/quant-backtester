"""Calendar behaviour on the dates that break naive implementations."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import pytest

from quant_backtester.data.calendars import (
    CalendarCoverageError,
    CalendarRegistry,
    TradingCalendar,
)


def make_calendar(**overrides: object) -> TradingCalendar:
    """Build a valid calendar, with the fields under test overridden.

    Defaults are deliberately a *valid* calendar: each test changes the one field
    it is about, so a failure points at that field and nothing else.
    """
    # Typed ``Any`` so a test can override a field with a deliberately wrong value.
    fields: dict[str, Any] = {
        "calendar_id": "XTST",
        "timezone": "America/New_York",
        "regular_open": time(9, 30),
        "regular_close": time(16, 0),
        "holidays": frozenset({date(2026, 11, 26)}),
        "early_closes": {date(2026, 11, 27): time(13, 0)},
        # Two years, so the look-ahead guards can declare a 2027 holiday.
        "covered_from": date(2026, 1, 1),
        "covered_until": date(2027, 12, 31),
    }
    fields.update(overrides)
    return TradingCalendar(**fields)


def test_valid_calendar_exposes_its_id():
    """The constructor accepts a valid configuration and exposes the venue id."""
    assert make_calendar().calendar_id == "XTST"


def test_valid_calendar_exposes_its_timezone():
    """The venue zone is exposed, so a normalizer can read provider dates locally."""
    assert make_calendar(timezone="Europe/Paris").timezone == "Europe/Paris"


def test_calendar_id_is_read_only():
    """The venue id cannot be reassigned after construction.

    Calendars are keyed by id in the registry: renaming one in place would
    silently desynchronise the index.
    """
    calendar = make_calendar()

    with pytest.raises(AttributeError):
        calendar.calendar_id = "XOTH"  # pyright: ignore[reportAttributeAccessIssue]


def test_unknown_timezone_fails_at_construction():
    """A typo in the zone must fail at load time, not on the first session lookup."""
    with pytest.raises(ValueError, match="XTST"):
        make_calendar(timezone="America/New_Yrok")


@pytest.mark.parametrize(
    ("regular_open", "regular_close"),
    [(time(16, 0), time(9, 30)), (time(9, 30), time(9, 30))],
    ids=["inverted", "empty"],
)
def test_regular_open_must_precede_regular_close(regular_open, regular_close):
    """A session with no positive duration is a configuration error."""
    with pytest.raises(ValueError, match="XTST"):
        make_calendar(regular_open=regular_open, regular_close=regular_close)


@pytest.mark.parametrize("field", ["regular_open", "regular_close"])
def test_session_times_must_be_naive_local_times(field):
    """Times are exchange wall clock; the zone comes from ``timezone`` only.

    An aware ``time`` would carry a fixed offset, which is exactly the DST bug the
    calendar exists to prevent.
    """
    aware = {"regular_open": time(9, 30, tzinfo=UTC), "regular_close": time(16, 0, tzinfo=UTC)}

    with pytest.raises(ValueError, match="XTST"):
        make_calendar(**{field: aware[field]})


@pytest.mark.parametrize(
    "close",
    [time(16, 0), time(17, 0), time(9, 30), time(8, 0)],
    ids=["regular", "after-regular", "at-open", "before-open"],
)
def test_early_close_must_fall_inside_the_regular_session(close):
    """An "early" close at or after the regular one, or before the open, is a typo."""
    with pytest.raises(ValueError, match="2026-11-27"):
        make_calendar(early_closes={date(2026, 11, 27): close})


def test_early_close_cannot_be_on_a_holiday():
    """A day cannot be both closed and a half day: one of the two lists is wrong."""
    with pytest.raises(ValueError, match="2026-11-26"):
        make_calendar(early_closes={date(2026, 11, 26): time(13, 0)})


@pytest.mark.parametrize(
    "field",
    ["holidays", "early_closes"],
)
def test_weekend_dates_are_rejected(field):
    """Holidays and early closes are weekdays by definition.

    4 July 2026 is a Saturday: listing it instead of the observed Friday 3 July
    leaves the venue open on a closed day.
    """
    saturday = date(2026, 7, 4)
    overrides = {
        "holidays": {"holidays": frozenset({saturday})},
        "early_closes": {"early_closes": {saturday: time(13, 0)}},
    }

    with pytest.raises(ValueError, match="2026-07-04"):
        make_calendar(**overrides[field])


@pytest.mark.parametrize("field", ["holidays", "early_closes"])
def test_datetimes_are_rejected_where_dates_are_expected(field):
    """A ``datetime`` is not accepted as a session date.

    ``datetime`` subclasses ``date``: an isinstance check alone lets it through,
    and it never compares equal to the ``date`` a lookup uses.
    """
    stamp = datetime(2026, 11, 26, tzinfo=UTC)
    overrides = {
        "holidays": {"holidays": frozenset({stamp})},
        "early_closes": {"early_closes": {stamp: time(13, 0)}},
    }

    with pytest.raises(ValueError, match="2026-11-26"):
        make_calendar(**overrides[field])


def test_mutating_the_input_mapping_does_not_change_the_calendar():
    """The calendar keeps its own copy of ``early_closes``.

    A caller mutating its dict afterwards must not rewrite history.
    """
    early_closes = {date(2026, 11, 27): time(13, 0)}
    calendar = make_calendar(early_closes=early_closes)

    early_closes[date(2026, 11, 27)] = time(10, 0)

    session = calendar.session(date(2026, 11, 27))

    assert session is not None
    assert session.close_utc == datetime(2026, 11, 27, 18, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2026, 11, 25), True),
        (date(2026, 11, 26), False),
        (date(2026, 11, 27), True),
        (date(2026, 11, 28), False),
        (date(2026, 11, 29), False),
        (date(2026, 11, 30), True),
    ],
    ids=["regular-wednesday", "holiday", "half-day", "saturday", "sunday", "next-monday"],
)
def test_is_open_on_a_hand_checkable_week(day, expected):
    """Thanksgiving week 2026: the holiday and the weekend close, the half day opens.

    A half day is still a session - it closes early, it does not stay shut.
    """
    assert make_calendar().is_open(day) is expected


def test_is_open_rejects_a_datetime():
    """``datetime(2026, 11, 26)`` never equals ``date(2026, 11, 26)``.

    A membership test against the holiday set would miss it and report
    Thanksgiving as open. ``datetime`` subclasses ``date``, so only an explicit
    check stops it.
    """
    with pytest.raises(TypeError, match="XTST"):
        make_calendar().is_open(datetime(2026, 11, 26, tzinfo=UTC))


def test_a_later_holiday_does_not_change_earlier_days():
    """Look-ahead guard: adding a 2027 holiday leaves every 2026 answer unchanged."""
    days = [date(2026, 11, day) for day in range(1, 31)]
    calendar = make_calendar()
    with_future = make_calendar(holidays=frozenset({date(2026, 11, 26), date(2027, 1, 1)}))

    assert [with_future.is_open(day) for day in days] == [calendar.is_open(day) for day in days]


@pytest.mark.parametrize(
    ("day", "xnys_open", "xpar_open"),
    [
        (date(2026, 4, 6), True, False),
        (date(2026, 11, 26), False, True),
    ],
    ids=["easter-monday", "thanksgiving"],
)
def test_committed_calendars_are_misaligned(day, xnys_open, xpar_open):
    """Easter Monday closes Paris only; Thanksgiving closes New York only.

    The canonical timeline is cross-market: a US-close signal executed at the next
    European open must not assume both venues share their closed days.
    """
    xnys = TradingCalendar.from_toml(COMMITTED_CALENDARS / "XNYS.toml")
    xpar = TradingCalendar.from_toml(COMMITTED_CALENDARS / "XPAR.toml")

    assert xnys.is_open(day) is xnys_open
    assert xpar.is_open(day) is xpar_open


SAMPLE_TOML = """\
calendar_id = "XTST"
timezone = "America/New_York"
regular_open = "09:30:00"
regular_close = "16:00:00"
covered_from = 2026-01-01
covered_until = 2026-12-31
holidays = [2026-11-26]

[early_closes]
2026-11-27 = "13:00:00"
"""
"""A one-holiday, one-half-day calendar. Synthetic, so the committed calendars
can grow without breaking these tests."""


def write_toml(tmp_path: Path, content: str) -> Path:
    """Write ``content`` to ``XTST.toml`` under ``tmp_path`` and return its path."""
    path = tmp_path / "XTST.toml"
    path.write_text(content, encoding="utf-8")
    return path


def test_from_toml_builds_the_calendar(tmp_path):
    """The TOML loads into a calendar.

    Loading at all is the check: TOML hands back the half-day key as the string
    ``"2026-11-27"`` and its close as ``"13:00:00"``, and the constructor refuses
    both. A loader that forgets either conversion fails here.
    """
    calendar = TradingCalendar.from_toml(write_toml(tmp_path, SAMPLE_TOML))

    assert calendar.calendar_id == "XTST"


def test_from_toml_reads_the_holidays(tmp_path):
    """A listed holiday is closed; the next weekday is open."""
    calendar = TradingCalendar.from_toml(write_toml(tmp_path, SAMPLE_TOML))

    assert not calendar.is_open(date(2026, 11, 26))
    assert calendar.is_open(date(2026, 11, 27))


def test_from_toml_reads_the_early_closes(tmp_path):
    """27 November 2026 closes at 13:00 New York, 18:00 UTC."""
    calendar = TradingCalendar.from_toml(write_toml(tmp_path, SAMPLE_TOML))

    session = calendar.session(date(2026, 11, 27))

    assert session is not None
    assert session.is_half_day
    assert session.close_utc == datetime(2026, 11, 27, 18, 0, tzinfo=UTC)


def test_from_toml_rejects_an_unknown_key(tmp_path):
    """A key the loader does not read fails loudly rather than being ignored.

    ``utc_offset = -5`` looks like it configures the venue and does nothing: the
    offset comes from ``timezone``, per date. Ignoring it would let the author
    believe a fixed offset is in force. The error names the key and the file.
    """
    # Inserted before [early_closes]: appended at the end it would land in that table.
    typo = SAMPLE_TOML.replace("holidays", "utc_offset = -5\nholidays", 1)

    with pytest.raises(ValueError, match="utc_offset") as excinfo:
        TradingCalendar.from_toml(write_toml(tmp_path, typo))

    assert "XTST.toml" in str(excinfo.value)


def test_from_toml_names_the_file_missing_a_required_key(tmp_path):
    """A missing key names the key and the file, not a bare ``KeyError``.

    ``tomllib`` returns a plain dict: indexing it straight raises
    ``KeyError('regular_close')``, which says nothing about which calendar file
    to go and fix.
    """
    without_close = SAMPLE_TOML.replace('regular_close = "16:00:00"\n', "", 1)

    with pytest.raises(ValueError, match="regular_close") as excinfo:
        TradingCalendar.from_toml(write_toml(tmp_path, without_close))

    assert "XTST.toml" in str(excinfo.value)


def test_from_toml_accepts_the_native_toml_local_time(tmp_path):
    """``regular_open = 09:30:00`` unquoted is a TOML local time, and is valid.

    It reaches the loader as a ``time``, not a string: ``time.fromisoformat`` on
    it raises a ``TypeError`` naming neither the file nor the key.
    """
    unquoted = SAMPLE_TOML.replace('regular_open = "09:30:00"', "regular_open = 09:30:00", 1)

    calendar = TradingCalendar.from_toml(write_toml(tmp_path, unquoted))

    assert calendar.calendar_id == "XTST"


def test_from_toml_rejects_a_time_that_is_not_a_time(tmp_path):
    """``regular_open = 930`` is refused with the key and the file, not a ``TypeError``."""
    as_integer = SAMPLE_TOML.replace('regular_open = "09:30:00"', "regular_open = 930", 1)

    with pytest.raises(ValueError, match="regular_open") as excinfo:
        TradingCalendar.from_toml(write_toml(tmp_path, as_integer))

    assert "XTST.toml" in str(excinfo.value)


COMMITTED_CALENDARS = Path(__file__).resolve().parents[2] / "market_data" / "metadata" / "calendars"
"""The calendars a backtest actually runs on.

Deliberately the real files: the synthetic ``SAMPLE_TOML`` above pins the loader,
and nothing else would notice the day a committed calendar stops parsing.
"""


def test_every_committed_calendar_loads_under_its_own_name():
    """Each committed file parses, and ``XNYS.toml`` declares ``calendar_id = "XNYS"``.

    Instruments find their calendar by file name, so a file whose id disagrees
    with its name would load one venue's sessions under another's id.
    """
    paths = sorted(COMMITTED_CALENDARS.glob("*.toml"))

    assert paths, f"no calendar found under {COMMITTED_CALENDARS}"
    for path in paths:
        assert TradingCalendar.from_toml(path).calendar_id == path.stem


def committed(calendar_id: str) -> TradingCalendar:
    """Load one committed calendar file."""
    return TradingCalendar.from_toml(COMMITTED_CALENDARS / f"{calendar_id}.toml")


def test_committed_calendars_cover_their_declared_periods():
    """NYSE from 1990, Paris from 2002, both through 2027; earlier Paris dates raise.

    The committed files once held 2026 alone while instruments started in 1990,
    and every earlier holiday read as a session.

    The end date is pinned rather than compared to today: a test that read the
    wall clock would turn red one morning with no code having changed. Whether
    the horizon is still far enough away is an operational question, and
    ``scripts/check_calendar_coverage.py`` is what answers it.
    """
    xnys, xpar = committed("XNYS"), committed("XPAR")

    assert (xnys.covered_from, xnys.covered_until) == (date(1990, 1, 1), date(2027, 12, 31))
    assert (xpar.covered_from, xpar.covered_until) == (date(2002, 1, 1), date(2027, 12, 31))
    with pytest.raises(CalendarCoverageError):
        xpar.is_open(date(2001, 7, 13))


@pytest.mark.parametrize(
    "day",
    [
        date(1994, 4, 27),
        date(2001, 9, 11),
        date(2001, 9, 14),
        date(2004, 6, 11),
        date(2007, 1, 2),
        date(2012, 10, 29),
        date(2012, 10, 30),
        date(2016, 12, 26),
        date(2018, 12, 5),
        date(2025, 1, 9),
    ],
    ids=[
        "nixon-mourning",
        "september-11",
        "september-14",
        "reagan-mourning",
        "ford-mourning",
        "sandy-day-1",
        "sandy-day-2",
        "christmas-observed-2016",
        "bush-mourning",
        "carter-mourning",
    ],
)
def test_committed_nyse_is_closed_on_historical_closures(day):
    """Closures no weekday rule derives - mournings, an attack, a hurricane - are listed.

    Each of these days read as a session in a calendar that stopped at 2026: a
    data gap reported where the market was shut, and an open price that never
    existed for the engine to fill at.
    """
    assert not committed("XNYS").is_open(day)


def test_committed_nyse_reopened_after_september_11():
    """Monday 17 September 2001 traded again: the closure lasted four sessions."""
    assert committed("XNYS").is_open(date(2001, 9, 17))


@pytest.mark.parametrize(
    ("year", "expected"),
    [(2001, 248), (2012, 250), (2016, 252)],
    ids=["2001-september-11", "2012-sandy", "2016-regular"],
)
def test_committed_nyse_session_counts(year, expected):
    """Whole years: 2001 lost four sessions to 11 September, 2012 two to Sandy."""
    sessions = committed("XNYS").sessions(date(year, 1, 1), date(year, 12, 31))

    assert len(sessions) == expected


@pytest.mark.parametrize(
    ("calendar_id", "day", "close_utc"),
    [
        ("XNYS", date(1990, 12, 24), datetime(1990, 12, 24, 19, 0, tzinfo=UTC)),
        ("XNYS", date(2019, 7, 3), datetime(2019, 7, 3, 17, 0, tzinfo=UTC)),
        ("XPAR", date(2018, 12, 24), datetime(2018, 12, 24, 13, 5, tzinfo=UTC)),
    ],
    ids=["nyse-1990-at-14h-est", "nyse-2019-at-13h-edt", "paris-2018-at-14h05-cet"],
)
def test_committed_half_days_close_at_their_historical_time(calendar_id, day, close_utc):
    """Early closes keep their own local time: NYSE closed at 14:00 in 1990, 13:00 later.

    A close stamped at the regular 16:00 would make that day's close look known
    three hours after it was.
    """
    session = committed(calendar_id).session(day)

    assert session is not None
    assert session.is_half_day
    assert session.close_utc == close_utc


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2018, 5, 1), False),
        (date(2018, 5, 8), True),
        (date(2025, 4, 18), False),
        (date(2025, 4, 21), False),
        (date(2025, 12, 26), False),
    ],
    ids=["labour-day", "victory-day-trades", "good-friday", "easter-monday", "boxing-day"],
)
def test_committed_paris_follows_euronext_not_french_public_holidays(day, expected):
    """Euronext closes on its own holidays, not on every French public holiday.

    8 May is a public holiday in France, yet Paris trades: deriving the venue's
    calendar from the country's would close it on a session day.
    """
    assert committed("XPAR").is_open(day) is expected


def test_regular_session_close_is_utc_aware(xnys):
    """A regular NYSE session closes at 16:00 ET, expressed in UTC.

    25 November 2026 is on EST (UTC-5): 09:30 and 16:00 New York are 14:30 and
    21:00 UTC. Equality alone would accept a New York-aware datetime for the same
    instant, so the offset is asserted separately.
    """
    session = xnys.session(date(2026, 11, 25))

    assert session.session_date == date(2026, 11, 25)
    assert session.open_utc.utcoffset() == timedelta(0)
    assert session.close_utc.utcoffset() == timedelta(0)
    assert session.open_utc == datetime(2026, 11, 25, 14, 30, tzinfo=UTC)
    assert session.close_utc == datetime(2026, 11, 25, 21, 0, tzinfo=UTC)
    assert not session.is_half_day


def test_half_day_closes_early(xnys):
    """27 November 2026 closes at 13:00 ET, not 16:00: 18:00 UTC. The open is unchanged."""
    session = xnys.session(date(2026, 11, 27))

    assert session.is_half_day
    assert session.open_utc == datetime(2026, 11, 27, 14, 30, tzinfo=UTC)
    assert session.close_utc == datetime(2026, 11, 27, 18, 0, tzinfo=UTC)


def test_half_day_close_keeps_its_minutes(xpar):
    """Euronext closes at 14:05 CET on 24 December 2026: 13:05 UTC, minutes kept."""
    session = xpar.session(date(2026, 12, 24))

    assert session.is_half_day
    assert session.close_utc == datetime(2026, 12, 24, 13, 5, tzinfo=UTC)


def test_us_and_eu_dst_transitions_are_misaligned(xnys, xpar):
    """Between the US and EU DST switches, the close gap is not the June one.

    The US moves on the second Sunday of March, Europe on the last. For those
    two weeks the NYSE close lands an hour earlier in Paris wall-clock terms
    than it does in June. A calendar that stores a fixed UTC offset gets this
    wrong, and it is silent when it does.

    12 March 2026: New York is on EDT (UTC-4), Paris still on CET (UTC+1), so
    NYSE closes 20:00 UTC and Euronext 16:30 UTC - 3h30 apart. 10 June 2026: both
    on summer time, 20:00 and 15:30 UTC - 4h30 apart.
    """

    def close_gap(day: date) -> timedelta:
        return xnys.session(day).close_utc - xpar.session(day).close_utc

    assert close_gap(date(2026, 3, 12)) == timedelta(hours=3, minutes=30)
    assert close_gap(date(2026, 6, 10)) == timedelta(hours=4, minutes=30)


def test_holiday_is_not_a_session(xpar):
    """A venue holiday yields no session, even on a weekday.

    Easter Monday, 6 April 2026, closes Euronext; the Tuesday after trades.
    """
    assert xpar.session(date(2026, 4, 6)) is None
    assert xpar.session(date(2026, 4, 7)) is not None


@pytest.mark.parametrize(
    ("day", "open_utc", "close_utc"),
    [
        (date(2026, 3, 6), datetime(2026, 3, 6, 14, 30), datetime(2026, 3, 6, 21, 0)),
        (date(2026, 3, 9), datetime(2026, 3, 9, 13, 30), datetime(2026, 3, 9, 20, 0)),
        (date(2026, 10, 30), datetime(2026, 10, 30, 13, 30), datetime(2026, 10, 30, 20, 0)),
        (date(2026, 11, 2), datetime(2026, 11, 2, 14, 30), datetime(2026, 11, 2, 21, 0)),
    ],
    ids=["before-spring-forward", "after-spring-forward", "before-fall-back", "after-fall-back"],
)
def test_session_instants_follow_new_york_dst(day, open_utc, close_utc):
    """The UTC instants move by one hour across each US switch (8 March, 1 November 2026).

    The local times never change; a fixed offset gets one side of each switch wrong.
    """
    session = make_calendar().session(day)

    assert session is not None
    assert session.open_utc == open_utc.replace(tzinfo=UTC)
    assert session.close_utc == close_utc.replace(tzinfo=UTC)


@pytest.mark.parametrize(
    "day",
    [date(2026, 11, 26), date(2026, 11, 28), date(2026, 11, 29)],
    ids=["holiday", "saturday", "sunday"],
)
def test_session_is_none_when_the_venue_is_closed(day):
    """No session on a holiday or a weekend."""
    assert make_calendar().session(day) is None


def test_session_exists_exactly_on_open_days():
    """``session`` and ``is_open`` agree on every day of 2026.

    Two methods answering the same question separately drift apart; this pins them
    together across weekends, the holiday and the half day.
    """
    calendar = make_calendar()
    days = [date(2026, 1, 1) + timedelta(days=offset) for offset in range(365)]

    assert [calendar.session(day) is not None for day in days] == [
        calendar.is_open(day) for day in days
    ]


def test_session_rejects_a_datetime():
    """A ``datetime`` is refused, as in ``is_open``: it never matches a listed day."""
    with pytest.raises(TypeError, match="XTST"):
        make_calendar().session(datetime(2026, 11, 26, tzinfo=UTC))


def test_a_later_early_close_does_not_change_earlier_sessions():
    """Look-ahead guard: declaring a 2027 half day leaves every 2026 session identical."""
    days = [date(2026, 1, 1) + timedelta(days=offset) for offset in range(365)]
    calendar = make_calendar()
    with_future = make_calendar(
        early_closes={date(2026, 11, 27): time(13, 0), date(2027, 11, 26): time(13, 0)}
    )

    assert [with_future.session(day) for day in days] == [calendar.session(day) for day in days]


def test_sessions_lists_open_days_in_order(xnys):
    """Thanksgiving week 2026: Wednesday, the half-day Friday, then Monday."""
    sessions = xnys.sessions(date(2026, 11, 25), date(2026, 11, 30))

    assert [s.session_date for s in sessions] == [
        date(2026, 11, 25),
        date(2026, 11, 27),
        date(2026, 11, 30),
    ]
    assert sessions[1].is_half_day


def test_sessions_bounds_are_inclusive(xnys):
    """A single open day as both bounds yields that one session."""
    day = date(2026, 11, 25)

    assert [s.session_date for s in xnys.sessions(day, day)] == [day]


def test_sessions_is_empty_when_nothing_trades(xnys):
    """Thanksgiving alone, or a weekend, holds no session."""
    assert xnys.sessions(date(2026, 11, 26), date(2026, 11, 26)) == []
    assert xnys.sessions(date(2026, 11, 28), date(2026, 11, 29)) == []


def test_sessions_rejects_inverted_bounds(xnys):
    """``start`` after ``end`` is a caller bug, not an empty range."""
    with pytest.raises(ValueError, match="XNYS"):
        xnys.sessions(date(2026, 11, 30), date(2026, 11, 25))


def test_sessions_matches_a_day_by_day_loop(xnys):
    """``sessions`` over 2026 equals calling ``session`` on each day."""
    days = [date(2026, 1, 1) + timedelta(days=offset) for offset in range(365)]
    expected = [s for s in (xnys.session(day) for day in days) if s is not None]

    assert xnys.sessions(date(2026, 1, 1), date(2026, 12, 31)) == expected


def test_next_session_skips_weekend_and_holiday(xnys):
    """The session after a Friday before a Monday holiday is the Tuesday.

    Friday 4 September 2026, Labor Day Monday 7 September: next is Tuesday 8.
    """
    assert xnys.next_session(date(2026, 9, 4)).session_date == date(2026, 9, 8)


def test_next_session_is_strictly_after(xnys):
    """From an open day, the next session is the following one, not the same day."""
    assert xnys.next_session(date(2026, 11, 25)).session_date == date(2026, 11, 27)


def test_next_session_across_markets(xnys, xpar):
    """US close Thursday 2 April 2026 -> next Paris open is Tuesday 7 April.

    Good Friday and Easter Monday close Euronext: "next bar" would be three days early.
    """
    us_close = xnys.session(date(2026, 4, 2)).close_utc
    eu_open = xpar.next_session(date(2026, 4, 2))

    assert eu_open.session_date == date(2026, 4, 7)
    assert eu_open.open_utc == datetime(2026, 4, 7, 7, 0, tzinfo=UTC)
    assert eu_open.open_utc > us_close


def test_previous_session_skips_weekend_and_holiday(xnys):
    """Before Tuesday 8 September 2026 comes Friday 4 September (Labor Day in between)."""
    assert xnys.previous_session(date(2026, 9, 8)).session_date == date(2026, 9, 4)


def test_previous_session_is_strictly_before(xnys):
    """From an open day, the previous session is an earlier one."""
    assert xnys.previous_session(date(2026, 11, 27)).session_date == date(2026, 11, 25)


@pytest.mark.parametrize("method", ["next_session", "previous_session"])
def test_neighbour_search_is_bounded(method):
    """A calendar closed for weeks raises instead of looping or wandering off.

    Every weekday of December 2026 is a holiday: the holiday list, not the venue,
    is what ran out.
    """
    december = frozenset(
        date(2026, 12, day) for day in range(1, 32) if date(2026, 12, day).weekday() < 5
    )
    calendar = make_calendar(holidays=december, early_closes={})

    with pytest.raises(LookupError, match="XTST"):
        getattr(calendar, method)(date(2026, 12, 15))


@pytest.mark.parametrize(
    "method", ["sessions", "next_session", "previous_session", "sessions_between"]
)
def test_range_methods_reject_a_datetime(xnys, method):
    """As in ``session``, a ``datetime`` is refused everywhere a date is expected."""
    stamp = datetime(2026, 11, 25, tzinfo=UTC)
    args = (stamp, date(2026, 11, 30)) if method in {"sessions", "sessions_between"} else (stamp,)

    with pytest.raises(TypeError, match="XNYS"):
        getattr(xnys, method)(*args)


def test_neighbours_ignore_later_holidays():
    """Look-ahead guard: a holiday after the answer does not move it."""
    calendar = make_calendar()
    with_future = make_calendar(holidays=frozenset({date(2026, 11, 26), date(2026, 12, 1)}))

    assert with_future.next_session(date(2026, 11, 25)) == calendar.next_session(date(2026, 11, 25))
    assert with_future.previous_session(date(2026, 11, 30)) == calendar.previous_session(
        date(2026, 11, 30)
    )


def test_staleness_is_counted_in_sessions_not_days(xnys):
    """Monday's value is one session old on Tuesday, not three days old.

    Friday's value is one session old on Monday 30 November 2026, across a weekend.
    """
    assert xnys.sessions_between(date(2026, 11, 30), date(2026, 12, 1)) == 1
    assert xnys.sessions_between(date(2026, 11, 27), date(2026, 11, 30)) == 1


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (date(2026, 11, 25), date(2026, 11, 25), 0),
        (date(2026, 11, 25), date(2026, 11, 26), 0),
        (date(2026, 11, 24), date(2026, 11, 25), 1),
        (date(2026, 11, 24), date(2026, 11, 30), 3),
    ],
    ids=["same-day", "holiday-end", "end-included", "start-excluded"],
)
def test_sessions_between_bounds(xnys, start, end, expected):
    """``(start, end]``: start excluded, end included, holidays not counted."""
    assert xnys.sessions_between(start, end) == expected


def test_sessions_between_rejects_inverted_bounds(xnys):
    """A negative staleness is a caller bug."""
    with pytest.raises(ValueError, match="XNYS"):
        xnys.sessions_between(date(2026, 12, 1), date(2026, 11, 30))


def test_registry_gets_by_id(xnys, xpar):
    """Each calendar is returned under its own id."""
    registry = CalendarRegistry([xpar, xnys])

    assert registry.get("XNYS") is xnys
    assert registry.get("XPAR") is xpar


def test_registry_iterates_in_id_order(xnys, xpar):
    """Iteration order is by id, not insertion: reproducible whatever the input order."""
    assert [c.calendar_id for c in CalendarRegistry([xpar, xnys])] == ["XNYS", "XPAR"]


def test_empty_registry_iterates_nothing():
    """An empty registry is valid and yields no calendar."""
    assert list(CalendarRegistry([])) == []


def test_registry_rejects_duplicate_ids(xnys):
    """A second calendar with the same id would silently replace the first."""
    with pytest.raises(ValueError, match="XNYS"):
        CalendarRegistry([xnys, xnys])


def test_registry_unknown_id_names_the_known_ones(xnys, xpar):
    """An unknown venue raises ``KeyError`` listing what is registered."""
    with pytest.raises(KeyError, match="XLON") as excinfo:
        CalendarRegistry([xnys, xpar]).get("XLON")

    assert "XNYS" in str(excinfo.value)


def test_registry_from_directory_loads_every_file(tmp_path):
    """Every ``*.toml`` is loaded; other files are ignored."""
    (tmp_path / "XTST.toml").write_text(SAMPLE_TOML, encoding="utf-8")
    (tmp_path / "XOTH.toml").write_text(SAMPLE_TOML.replace("XTST", "XOTH"), encoding="utf-8")
    (tmp_path / "README.md").write_text("not a calendar", encoding="utf-8")

    registry = CalendarRegistry.from_directory(tmp_path)

    assert [c.calendar_id for c in registry] == ["XOTH", "XTST"]


def test_registry_from_empty_directory_fails(tmp_path):
    """A wrong path must fail at load, not on the first lookup."""
    with pytest.raises(ValueError, match=str(tmp_path)):
        CalendarRegistry.from_directory(tmp_path)


def test_registry_loads_the_committed_calendars():
    """The real calendar folder yields XNYS and XPAR."""
    registry = CalendarRegistry.from_directory(COMMITTED_CALENDARS)

    assert [c.calendar_id for c in registry] == ["XNYS", "XPAR"]


# --- coverage: a calendar only answers for the period its holiday list covers --


def test_coverage_bounds_are_exposed():
    """The covered period is readable, so a caller can check it before a long run."""
    calendar = make_calendar()

    assert (calendar.covered_from, calendar.covered_until) == (date(2026, 1, 1), date(2027, 12, 31))


def test_coverage_error_is_a_lookup_error():
    """Callers already catching the bounded-search ``LookupError`` also catch this one."""
    assert issubclass(CalendarCoverageError, LookupError)


@pytest.mark.parametrize(
    "day",
    [date(2025, 12, 31), date(2025, 12, 27), date(2028, 1, 3)],
    ids=["weekday-before", "saturday-before", "weekday-after"],
)
@pytest.mark.parametrize("method", ["is_open", "session"])
def test_dates_outside_the_coverage_raise(method, day):
    """Outside its holiday list the calendar does not know, so it raises.

    The weekend case matters too: "closed on Saturday" is true, but answering it
    would let a scan walk out of the covered period one day at a time.
    """
    with pytest.raises(CalendarCoverageError, match="XTST"):
        getattr(make_calendar(), method)(day)


def test_coverage_bounds_are_inclusive():
    """The first and last covered days both answer normally."""
    calendar = make_calendar(
        covered_from=date(2026, 1, 5),
        covered_until=date(2026, 1, 9),
        holidays=frozenset(),
        early_closes={},
    )

    assert [calendar.is_open(date(2026, 1, day)) for day in range(5, 10)] == [True] * 5


def test_sessions_crossing_the_coverage_end_raise():
    """A range running past the covered period fails instead of being truncated or invented."""
    calendar = make_calendar(covered_until=date(2026, 12, 31))

    with pytest.raises(CalendarCoverageError, match="2027-01-01"):
        calendar.sessions(date(2026, 12, 28), date(2027, 1, 4))


@pytest.mark.parametrize(
    ("method", "day"),
    [("next_session", date(2026, 12, 31)), ("previous_session", date(2026, 1, 1))],
    ids=["next-after-the-end", "previous-before-the-start"],
)
def test_neighbour_search_stops_at_the_coverage_edge(method, day):
    """The session after the last covered day is unknown, not "the next weekday".

    Friday 1 January 2027 is a holiday everywhere; a calendar without data for it
    must not return it as the next session.
    """
    calendar = make_calendar(covered_until=date(2026, 12, 31))

    with pytest.raises(CalendarCoverageError, match="XTST"):
        getattr(calendar, method)(day)


@pytest.mark.parametrize(
    "overrides",
    [
        {"covered_from": date(2027, 1, 1), "covered_until": date(2026, 12, 31)},
        {"holidays": frozenset({date(2028, 1, 3)})},
        {"early_closes": {date(2025, 11, 28): time(13, 0)}},
        {"covered_from": datetime(2026, 1, 1, tzinfo=UTC)},
    ],
    ids=["inverted", "holiday-outside", "early-close-outside", "datetime-bound"],
)
def test_invalid_coverage_is_rejected(overrides):
    """A coverage that contradicts itself or the lists it describes is a config error."""
    with pytest.raises(ValueError, match="XTST"):
        make_calendar(**overrides)


def test_from_toml_reads_the_coverage(tmp_path):
    """``covered_from`` and ``covered_until`` are native TOML dates, read as such."""
    calendar = TradingCalendar.from_toml(write_toml(tmp_path, SAMPLE_TOML))

    assert (calendar.covered_from, calendar.covered_until) == (date(2026, 1, 1), date(2026, 12, 31))
    with pytest.raises(CalendarCoverageError):
        calendar.is_open(date(2027, 1, 4))


@pytest.mark.parametrize("key", ["covered_from", "covered_until"])
def test_from_toml_requires_the_coverage(tmp_path, key):
    """A calendar file without its covered period is refused, naming the key and the file."""
    without = "\n".join(line for line in SAMPLE_TOML.splitlines() if not line.startswith(key))

    with pytest.raises(ValueError, match=key) as excinfo:
        TradingCalendar.from_toml(write_toml(tmp_path, without))

    assert "XTST.toml" in str(excinfo.value)
