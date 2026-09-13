"""Instrument registry: availability arithmetic and registry invariants.

Everything here is offline and independent of the wall clock. The dates are not
decorative: each one sits on a boundary that a naive implementation gets wrong -
a DST transition, a fixed UTC offset, a month or year rollover.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from quant_backtester.data.calendars import CalendarRegistry
from quant_backtester.data.instruments import (
    AssetType,
    CheckSource,
    DataType,
    Instrument,
    InstrumentRegistry,
    PublicationRule,
)

FRED_US10Y = PublicationRule(publication_time=time(16, 15), timezone="America/New_York")
"""FRED publishes DGS10 at 16:15 New York wall clock, for the same day."""

ECB_FX = PublicationRule(publication_time=time(16, 0), timezone="Europe/Paris")
"""ECB reference rates, 16:00 Paris wall clock, same day."""

NEXT_DAY = PublicationRule(publication_time=time(16, 15), timezone="America/New_York", lag_days=1)
"""Same release time, published the following calendar day."""


def make_instrument(**overrides: object) -> Instrument:
    """Build a valid BAR instrument, with the fields under test overridden.

    Defaults are deliberately a *valid* instrument: each test then changes the
    one field it is about, so a failure points at that field and nothing else.
    """
    # Typed ``Any`` so a test can override a field with a deliberately wrong value.
    fields: dict[str, Any] = {
        "id": "TEST",
        "name": "Test instrument",
        "asset_type": AssetType.ETF,
        "data_type": DataType.BAR,
        "currency": "EUR",
        "primary_source": "YAHOO",
        "source_symbol": "TEST",
        "tradable": True,
        "calendar_id": "XPAR",
    }
    fields.update(overrides)
    return Instrument(**fields)


LEVEL_FIELDS = {
    "asset_type": AssetType.RATE,
    "data_type": DataType.LEVEL,
    "calendar_id": None,
    "publication_rule": ECB_FX,
}
"""Overrides turning the default BAR into a valid LEVEL."""


def test_availability_is_utc_aware():
    """The returned instant is timezone-aware and expressed in UTC.

    A naive datetime here would silently be read as local time by every consumer
    downstream, and the reader filters on this exact value.
    """
    available_at = ECB_FX.available_at(date(2024, 1, 8))

    assert available_at.tzinfo is not None
    assert available_at.utcoffset() == timedelta(0)


def test_same_day_publication_is_the_local_release_time():
    """16:00 Paris on 8 January 2024 is 15:00 UTC: hand-checkable, CET is UTC+1."""
    assert ECB_FX.available_at(date(2024, 1, 8)) == datetime(2024, 1, 8, 15, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("rule", "observation_date", "expected"),
    [
        # Same wall clock, two different UTC instants: the offset is not a constant.
        (FRED_US10Y, date(2024, 1, 10), datetime(2024, 1, 10, 21, 15, tzinfo=UTC)),  # EST
        (FRED_US10Y, date(2024, 3, 14), datetime(2024, 3, 14, 20, 15, tzinfo=UTC)),  # EDT
        (ECB_FX, date(2024, 1, 8), datetime(2024, 1, 8, 15, 0, tzinfo=UTC)),  # CET
        (ECB_FX, date(2024, 7, 1), datetime(2024, 7, 1, 14, 0, tzinfo=UTC)),  # CEST
    ],
)
def test_release_time_is_a_wall_clock_that_moves_with_dst(rule, observation_date, expected):
    """The release time is local, so its UTC instant shifts by an hour across DST.

    This is the test a fixed UTC offset fails, and it fails it silently: it would
    be right in winter and an hour early from March to November.
    """
    assert rule.available_at(observation_date) == expected


def test_lag_applies_to_the_date_not_to_the_instant():
    """A lag crossing a DST switch adds a calendar day, not 24 hours.

    9 March 2024 + one day is the 10th, the day the US moves to EDT. Publication
    is still at 16:15 local, so the UTC instant is 20:15 - not the 21:15 that
    adding 24 hours to the previous day's instant would give.
    """
    assert NEXT_DAY.available_at(date(2024, 3, 9)) == datetime(2024, 3, 10, 20, 15, tzinfo=UTC)


@pytest.mark.parametrize(
    ("observation_date", "expected"),
    [
        (date(2024, 2, 29), datetime(2024, 3, 1, 21, 15, tzinfo=UTC)),  # leap day to March
        (date(2024, 12, 31), datetime(2025, 1, 1, 21, 15, tzinfo=UTC)),  # year rollover
    ],
)
def test_lag_crosses_month_and_year_boundaries(observation_date, expected):
    """Date arithmetic, not string manipulation: the rollovers are handled."""
    assert NEXT_DAY.available_at(observation_date) == expected


def test_lag_days_counts_calendar_days_not_business_days():
    """A Friday observation with a one-day lag lands on the Saturday.

    Documented limitation rather than a bug: ``lag_days`` is calendar days by
    definition. A publisher releasing "the next business day" cannot be modelled
    by this field, and must not be approximated with it.
    """
    friday = date(2024, 3, 8)

    available_at = NEXT_DAY.available_at(friday)

    assert available_at.astimezone(ZoneInfo("America/New_York")).date() == date(2024, 3, 9)
    assert available_at == datetime(2024, 3, 9, 21, 15, tzinfo=UTC)


@pytest.mark.parametrize("rule", [FRED_US10Y, ECB_FX, NEXT_DAY])
@pytest.mark.parametrize(
    "observation_date", [date(2024, 1, 10), date(2024, 3, 9), date(2024, 7, 1)]
)
def test_availability_never_precedes_the_observed_day(rule, observation_date):
    """The look-ahead guard: a value describing day *d* is never public before *d* begins.

    Availability moving earlier than the day it describes is the shape of the bug
    that lets a strategy read a value it could not have had.
    """
    day_starts = datetime.combine(observation_date, time(0, 0), tzinfo=ZoneInfo(rule.timezone))

    assert rule.available_at(observation_date) >= day_starts


def test_rule_is_immutable():
    """The rule is configuration: it must not be mutated at runtime."""
    with pytest.raises(FrozenInstanceError):
        ECB_FX.publication_time = time(9, 0)  # type: ignore[misc]


def test_valid_instruments_are_accepted():
    """The two well-formed shapes construct: BAR with a calendar, LEVEL with a rule."""
    assert make_instrument().calendar_id == "XPAR"
    assert make_instrument(**LEVEL_FIELDS).publication_rule is ECB_FX


def test_bar_without_calendar_is_rejected():
    """A BAR instrument with no ``calendar_id`` cannot produce an availability."""
    with pytest.raises(ValueError, match="calendar_id") as excinfo:
        make_instrument(calendar_id=None)

    assert "TEST" in str(excinfo.value)


def test_level_without_publication_rule_is_rejected():
    """A LEVEL instrument with no ``publication_rule`` cannot produce one either."""
    with pytest.raises(ValueError, match="publication_rule") as excinfo:
        make_instrument(**(LEVEL_FIELDS | {"publication_rule": None}))

    assert "TEST" in str(excinfo.value)


@pytest.mark.parametrize(
    ("overrides", "offending_field"),
    [
        ({"publication_rule": ECB_FX}, "publication_rule"),
        (LEVEL_FIELDS | {"calendar_id": "XPAR"}, "calendar_id"),
    ],
    ids=["bar_carrying_a_publication_rule", "level_carrying_a_calendar"],
)
def test_instrument_carrying_the_other_kind_field_is_rejected(overrides, offending_field):
    """A BAR with a ``publication_rule``, or a LEVEL with a ``calendar_id``, is a config error.

    This is the half that a "required fields are present" check misses: both
    instruments below have everything they need, plus something they must not
    have. It is the shape a half-edited TOML entry takes.
    """
    with pytest.raises(ValueError, match=offending_field):
        make_instrument(**overrides)


DELISTED = {"first_session": date(1993, 1, 29), "last_session": date(2020, 6, 30)}
"""Overrides for an instrument with both bounds closed."""


@pytest.mark.parametrize(
    ("on", "expected"),
    [
        (date(1993, 1, 28), False),  # the day before the first session
        (date(1993, 1, 29), True),  # the first session itself: inclusive
        (date(2005, 7, 14), True),  # well inside
        (date(2020, 6, 30), True),  # the last session itself: still listed
        (date(2020, 7, 1), False),  # the day after: gone
    ],
    ids=["before", "first_bound", "inside", "last_bound", "after"],
)
def test_is_listed_bounds_are_inclusive(on, expected):
    """``first_session`` and ``last_session`` are inclusive.

    The two boundary days are the point of this test. Off by one on the last
    session silently drops a delisted instrument's final day - a day on which
    positions still had to be closed.
    """
    assert make_instrument(**DELISTED).is_listed(on) is expected


@pytest.mark.parametrize(
    ("bounds", "on", "expected"),
    [
        # Still listed: no upper bound, so any later date is listed.
        ({"first_session": date(1993, 1, 29)}, date(1993, 1, 28), False),
        ({"first_session": date(1993, 1, 29)}, date(2099, 1, 1), True),
        # Listed since forever, delisted at some point.
        ({"last_session": date(2020, 6, 30)}, date(1900, 1, 1), True),
        ({"last_session": date(2020, 6, 30)}, date(2020, 7, 1), False),
        # Both open: no date can be outside.
        ({}, date(1900, 1, 1), True),
        ({}, date(2099, 1, 1), True),
    ],
    ids=[
        "first_only_before",
        "first_only_after",
        "last_only_before",
        "last_only_after",
        "unbounded_past",
        "unbounded_future",
    ],
)
def test_is_listed_treats_none_as_an_open_bound(bounds, on, expected):
    """``None`` means "no bound", never "unknown".

    An implementation reading ``None`` as a missing value would have to guess,
    and guessing here turns "the ETF did not exist yet" into a data hole.
    """
    assert make_instrument(**bounds).is_listed(on) is expected


def test_registry_accepts_distinct_instruments():
    """A registry over distinct ids constructs without complaining.

    Deliberately asserts nothing about the internals: what the registry holds is
    observable through ``get`` and ``list_all``, and is checked by their own
    tests. Reaching into ``_instruments`` here would make this test rewrite
    itself the day the storage changes.
    """
    registry = InstrumentRegistry(
        [make_instrument(id="SPY"), make_instrument(id="IWM"), make_instrument(id="QQQ")]
    )

    assert isinstance(registry, InstrumentRegistry)


def test_duplicate_ids_are_a_configuration_error():
    """Two instruments sharing an id must fail loudly at registry construction.

    A dict keyed by id silently keeps the last one, which is the worst possible
    outcome: the backtest runs, on a universe quietly one instrument short, and
    nothing in the output says so. The duplicated id must be named - the reader
    of the error is looking for a line in a TOML file.
    """
    duplicated = [
        make_instrument(id="SPY", name="S&P 500 ETF"),
        make_instrument(id="IWM"),
        make_instrument(id="SPY", name="Copy-pasted entry"),
    ]

    with pytest.raises(ValueError, match="SPY") as excinfo:
        InstrumentRegistry(duplicated)

    assert "IWM" not in str(excinfo.value)


SAMPLE_TOML = """
[[instrument]]
id = "SP500"
name = "S&P 500"
asset_type = "INDEX"
data_type = "BAR"
currency = "USD"
primary_source = "YAHOO"
source_symbol = "^GSPC"
calendar_id = "XNYS"
tradable = false
first_session = 1990-01-02

[[instrument]]
id = "US10Y"
name = "US 10-year Treasury constant maturity rate"
asset_type = "RATE"
data_type = "LEVEL"
currency = "NA"
primary_source = "FRED"
source_symbol = "DGS10"
tradable = false
first_session = 1990-01-02

  [instrument.publication_rule]
  publication_time = "16:15:00"
  timezone = "America/New_York"
  lag_days = 0
"""
"""A two-entry config: one BAR, one LEVEL. Synthetic, so the committed registry
can grow without breaking these tests."""


def write_toml(tmp_path, content: str) -> Path:
    """Write ``content`` to a TOML file under ``tmp_path`` and return its path."""
    path = tmp_path / "instruments.toml"
    path.write_text(content, encoding="utf-8")
    return path


def test_from_toml_reads_dates_enums_and_publication_rules(tmp_path):
    """The TOML round-trips into instruments, enums and rules included.

    TOML hands back strings and dicts; the registry must hand back enum members,
    a ``date`` and a ``PublicationRule``. The dataclass type-checks none of this,
    so a string left unconverted travels silently until something uses it.
    """
    registry = InstrumentRegistry.from_toml(write_toml(tmp_path, SAMPLE_TOML))
    bar = registry.get("SP500")
    level = registry.get("US10Y")

    assert bar.asset_type is AssetType.INDEX
    assert bar.data_type is DataType.BAR
    assert bar.first_session == date(1990, 1, 2)
    assert bar.publication_rule is None

    assert isinstance(level.publication_rule, PublicationRule)
    assert level.publication_rule.publication_time == time(16, 15)
    assert level.calendar_id is None


def test_from_toml_produces_a_usable_publication_rule(tmp_path):
    """The loaded rule computes an availability, end to end.

    The regression this pins: ``publication_time`` left as the string
    ``"16:15:00"`` builds a ``PublicationRule`` without complaint, and only fails
    later inside ``available_at`` - far from the line that caused it.
    """
    registry = InstrumentRegistry.from_toml(write_toml(tmp_path, SAMPLE_TOML))

    rule = registry.get("US10Y").publication_rule

    assert rule is not None
    available_at = rule.available_at(date(2024, 3, 14))

    assert available_at == datetime(2024, 3, 14, 20, 15, tzinfo=UTC)


def test_from_toml_rejects_an_unknown_key(tmp_path):
    """A typo in the config fails loudly rather than being silently ignored.

    ``tradble`` instead of ``tradable`` would leave the instrument on its default
    and quietly put a non-tradable series into the execution universe. The error
    must name both the offending key and the entry it sits in.
    """
    typo = SAMPLE_TOML.replace("tradable = false", "tradble = false", 1)

    with pytest.raises(ValueError, match="tradble") as excinfo:
        InstrumentRegistry.from_toml(write_toml(tmp_path, typo))

    assert "SP500" in str(excinfo.value)


def test_from_toml_rejects_an_unknown_key_in_the_publication_rule(tmp_path):
    """A typo inside the sub-table is look-ahead bias, so it must fail too.

    This is the sharper half of the unknown-key check. ``lag_days`` carries a
    default of zero, so ``lag_dayz = 1`` builds a rule without complaint and
    publishes a D+1 series on D - the strategy then reads a value that did not
    exist yet. The top-level check alone does not see it: the sub-table is a
    nested dict, and ``publication_rule`` is itself a legitimate key.
    """
    typo = SAMPLE_TOML.replace("lag_days = 0", "lag_dayz = 1", 1)

    with pytest.raises(ValueError, match="lag_dayz") as excinfo:
        InstrumentRegistry.from_toml(write_toml(tmp_path, typo))

    assert "US10Y" in str(excinfo.value)
    assert "publication_rule" in str(excinfo.value)


def test_from_toml_names_the_entry_missing_a_required_key(tmp_path):
    """A missing key names the entry and the file, not just the key.

    ``tomllib`` returns a plain dict, so indexing it straight would raise
    ``KeyError('name')`` - true, and useless: the registry holds several entries
    and the reader of the error is looking for one line in one TOML file.
    """
    without_name = SAMPLE_TOML.replace('name = "S&P 500"\n', "", 1)

    with pytest.raises(ValueError, match="name") as excinfo:
        InstrumentRegistry.from_toml(write_toml(tmp_path, without_name))

    assert "SP500" in str(excinfo.value)


def test_from_toml_rejects_a_file_declaring_no_instrument(tmp_path):
    """An empty or mistyped config is an error, never an empty universe.

    A registry of zero instruments would let the whole pipeline run and produce
    an empty result, with nothing saying the config was never read.
    """
    with pytest.raises(ValueError, match="instrument"):
        InstrumentRegistry.from_toml(write_toml(tmp_path, "[calendar]\nid = 'XNYS'\n"))


def test_from_toml_rejects_a_session_bound_that_is_not_a_plain_date(tmp_path):
    """``first_session`` written as a TOML datetime is refused at load time.

    ``datetime`` is a subclass of ``date``, so an ``isinstance`` check passes and
    the value travels until ``is_listed`` compares it to a real date and raises a
    ``TypeError`` - far from the config line that caused it.
    """
    as_datetime = SAMPLE_TOML.replace(
        "first_session = 1990-01-02", "first_session = 1990-01-02T00:00:00Z", 1
    )

    with pytest.raises(ValueError, match="first_session") as excinfo:
        InstrumentRegistry.from_toml(write_toml(tmp_path, as_datetime))

    assert "SP500" in str(excinfo.value)


def test_from_toml_accepts_the_native_toml_local_time(tmp_path):
    """``publication_time = 16:15:00`` unquoted is a TOML local time, and is valid.

    Both spellings must reach the same instant: the unquoted one is what a reader
    of the TOML spec writes naturally, and refusing it with a ``TypeError`` from
    inside the loader would name neither the file nor the instrument.
    """
    unquoted = SAMPLE_TOML.replace(
        'publication_time = "16:15:00"', "publication_time = 16:15:00", 1
    )

    registry = InstrumentRegistry.from_toml(write_toml(tmp_path, unquoted))
    rule = registry.get("US10Y").publication_rule

    assert rule is not None
    assert rule.publication_time == time(16, 15)


# --- check sources ------------------------------------------------------------

EURONEXT_CW8 = CheckSource(source="EURONEXT", source_symbol="LU1681043599-XPAR")
"""The committed second opinion on CW8: Euronext, under its ISIN."""


def test_an_instrument_has_no_check_source_by_default() -> None:
    """A single-source series needs no extra configuration."""
    instrument = make_instrument()

    assert instrument.check_sources == ()
    assert instrument.sources == ("YAHOO",)


def test_sources_list_the_primary_first_then_check_sources_in_order() -> None:
    """The order is the declared one, so downloads and reports are reproducible."""
    stooq = CheckSource(source="STOOQ", source_symbol="CW8")
    instrument = make_instrument(check_sources=(EURONEXT_CW8, stooq))

    assert instrument.sources == ("YAHOO", "EURONEXT", "STOOQ")


def test_for_source_of_the_primary_is_the_instrument_itself() -> None:
    """Asking for the primary source changes nothing."""
    instrument = make_instrument(check_sources=(EURONEXT_CW8,))

    assert instrument.for_source("YAHOO") is instrument


def test_for_source_of_a_check_source_swaps_source_and_symbol_only() -> None:
    """The adapter sees its own symbol; the download still lands under the same id."""
    instrument = make_instrument(id="ETF_WORLD", check_sources=(EURONEXT_CW8,))

    seen = instrument.for_source("EURONEXT")

    assert (seen.primary_source, seen.source_symbol) == ("EURONEXT", "LU1681043599-XPAR")
    assert seen.check_sources == ()
    assert (seen.id, seen.calendar_id, seen.asset_type) == ("ETF_WORLD", "XPAR", AssetType.ETF)


def test_for_source_of_an_unknown_source_raises_key_error() -> None:
    """A source the instrument does not declare is a lookup miss, named in the message."""
    with pytest.raises(KeyError, match="FRED"):
        make_instrument(check_sources=(EURONEXT_CW8,)).for_source("FRED")


@pytest.mark.parametrize(
    "check_sources",
    [
        (CheckSource(source="YAHOO", source_symbol="CW8.PA"),),
        (EURONEXT_CW8, CheckSource(source="EURONEXT", source_symbol="CW8")),
    ],
    ids=["primary-repeated", "check-source-repeated"],
)
def test_a_source_listed_twice_is_rejected(check_sources: tuple[CheckSource, ...]) -> None:
    """Comparing a provider with itself would confirm anything."""
    with pytest.raises(ValueError, match="more than once"):
        make_instrument(check_sources=check_sources)


def test_a_level_cannot_be_cross_checked() -> None:
    """Only bars are compared across sources."""
    with pytest.raises(ValueError, match="LEVEL"):
        make_instrument(**LEVEL_FIELDS, check_sources=(EURONEXT_CW8,))


def test_check_sources_must_be_a_tuple_of_check_sources() -> None:
    """A list would make the frozen instrument mutable through its field."""
    with pytest.raises(ValueError, match="tuple of CheckSource"):
        make_instrument(check_sources=[EURONEXT_CW8])


CHECKED_TOML = """
[[instrument]]
id = "ETF_WORLD"
name = "Amundi MSCI World (PEA)"
asset_type = "ETF"
data_type = "BAR"
currency = "EUR"
primary_source = "YAHOO"
source_symbol = "CW8.PA"
calendar_id = "XPAR"
tradable = true

  [[instrument.check_sources]]
  source = "EURONEXT"
  source_symbol = "LU1681043599-XPAR"
"""
"""One cross-checked BAR, as ``instruments.toml`` declares CW8."""


def test_from_toml_reads_check_sources(tmp_path: Path) -> None:
    """An array of tables becomes a tuple of ``CheckSource``."""
    registry = InstrumentRegistry.from_toml(write_toml(tmp_path, CHECKED_TOML))

    assert registry.get("ETF_WORLD").check_sources == (EURONEXT_CW8,)


def test_from_toml_rejects_an_unknown_key_in_a_check_source(tmp_path: Path) -> None:
    """A typo in a check source fails loudly, naming the entry."""
    typo = CHECKED_TOML.replace('source_symbol = "LU', 'symbol = "LU', 1)

    with pytest.raises(ValueError, match="symbol") as excinfo:
        InstrumentRegistry.from_toml(write_toml(tmp_path, typo))

    assert "ETF_WORLD" in str(excinfo.value)


def test_from_toml_names_a_check_source_missing_its_symbol(tmp_path: Path) -> None:
    """Each check source needs its own symbol: none is inherited from the primary."""
    without_symbol = CHECKED_TOML.replace('  source_symbol = "LU1681043599-XPAR"\n', "", 1)

    with pytest.raises(ValueError, match="source_symbol") as excinfo:
        InstrumentRegistry.from_toml(write_toml(tmp_path, without_symbol))

    assert "check_sources[0]" in str(excinfo.value)


def test_from_toml_rejects_check_sources_that_are_not_tables(tmp_path: Path) -> None:
    """``check_sources = "EURONEXT"`` is not a shorthand: it would lose the symbol."""
    flat = CHECKED_TOML.split("  [[instrument.check_sources]]")[0] + 'check_sources = "EURONEXT"\n'

    with pytest.raises(ValueError, match="array"):
        InstrumentRegistry.from_toml(write_toml(tmp_path, flat))


COMMITTED_INSTRUMENTS = (
    Path(__file__).resolve().parents[2] / "market_data" / "metadata" / "instruments.toml"
)
"""The registry a backtest actually runs on.

Deliberately the real file rather than a fixture: the synthetic ``SAMPLE_TOML``
above pins the loader's behaviour, and nothing else would notice the day the
committed config itself stops parsing. Offline and deterministic - it is a
committed file, and editing it is a reviewed change by construction.
"""


def test_the_committed_registry_loads():
    """The committed config parses, and every entry satisfies its own invariants.

    ``__post_init__`` runs on each entry, so this also pins that no committed
    instrument is a BAR without a calendar or a LEVEL without a rule.
    """
    registry = InstrumentRegistry.from_toml(COMMITTED_INSTRUMENTS)

    assert len(registry) > 0
    assert [instrument.id for instrument in registry] == sorted(i.id for i in registry)


def test_every_committed_bar_points_at_an_existing_calendar():
    """A ``calendar_id`` with no calendar file is a config error waiting to happen.

    The registry cannot check this itself - calendars live in their own files -
    so the consistency between the two committed configs is pinned here.
    """
    calendars = COMMITTED_INSTRUMENTS.parent / "calendars"
    registry = InstrumentRegistry.from_toml(COMMITTED_INSTRUMENTS)

    missing = [
        instrument.id
        for instrument in registry
        if instrument.calendar_id is not None
        and not (calendars / f"{instrument.calendar_id}.toml").exists()
    ]

    assert missing == []


def test_committed_calendars_cover_every_instrument_from_its_first_session():
    """A backtest can start on any instrument's first session without leaving its calendar.

    The committed calendars once listed 2026 alone while SP500 started in 1990,
    so every earlier holiday read as a session. Calendars now raise outside their
    covered period; this pins that the committed period reaches back far enough.
    """
    calendars = CalendarRegistry.from_directory(COMMITTED_INSTRUMENTS.parent / "calendars")
    uncovered = []
    for instrument in InstrumentRegistry.from_toml(COMMITTED_INSTRUMENTS):
        if instrument.calendar_id is None:
            continue
        covered_from = calendars.get(instrument.calendar_id).covered_from
        if instrument.first_session is None or instrument.first_session < covered_from:
            uncovered.append((instrument.id, instrument.first_session, covered_from))

    assert uncovered == []


INSERTION_ORDER = ["VIX", "ETF_WORLD", "AAA_FIRST", "US10Y"]
"""Deliberately not alphabetical: a registry that returns insertion order would
pass an ordering test built on an already-sorted fixture."""


@pytest.fixture
def registry() -> InstrumentRegistry:
    """Return a four-instrument registry spanning both sources and both kinds."""
    return InstrumentRegistry(
        [
            make_instrument(id="VIX", tradable=False, primary_source="YAHOO"),
            make_instrument(id="ETF_WORLD", tradable=True, primary_source="YAHOO"),
            make_instrument(id="AAA_FIRST", tradable=True, primary_source="YAHOO"),
            make_instrument(id="US10Y", tradable=False, primary_source="FRED", **LEVEL_FIELDS),
        ]
    )


def test_get_returns_the_registered_instrument(registry):
    """``get`` hands back the instrument carrying that id."""
    assert registry.get("VIX").id == "VIX"


def test_get_raises_keyerror_on_unknown_id(registry):
    """An unknown id is a ``KeyError``, never a ``None`` travelling downstream.

    A ``None`` returned here would surface as an ``AttributeError`` somewhere in
    a strategy, with nothing left to say which id was missing.
    """
    with pytest.raises(KeyError, match="NOT_A_REAL_ID"):
        registry.get("NOT_A_REAL_ID")


def test_list_all_is_ordered_by_id(registry):
    """A stable order keeps file writes, and therefore diffs, reproducible.

    The fixture is inserted out of order on purpose: returning the dict's own
    order would look correct until someone reorders the TOML file.
    """
    ids = [instrument.id for instrument in registry.list_all()]

    assert ids == ["AAA_FIRST", "ETF_WORLD", "US10Y", "VIX"]
    assert ids != INSERTION_ORDER


def test_list_tradable_excludes_signal_only_instruments(registry):
    """VIX and US10Y are readable but never tradable."""
    tradable = [instrument.id for instrument in registry.list_tradable()]

    assert tradable == ["AAA_FIRST", "ETF_WORLD"]
    assert all(instrument.tradable for instrument in registry.list_tradable())


def test_list_by_source_groups_downloads(registry):
    """Instruments are grouped by source so downloads can be batched per provider."""
    assert [i.id for i in registry.list_by_source("YAHOO")] == ["AAA_FIRST", "ETF_WORLD", "VIX"]
    assert [i.id for i in registry.list_by_source("FRED")] == ["US10Y"]


def test_list_by_source_returns_empty_for_an_unused_source(registry):
    """An unknown source is an empty list, not an error: nothing to download.

    ``"YAHO"`` is a prefix of ``"YAHOO"`` and must still match nothing: the
    comparison is an equality, not a substring test. Provider identifiers do
    overlap in practice - a ``YAHOO`` and a ``YAHOO_V2`` adapter would silently
    share instruments under a looser rule.
    """
    assert registry.list_by_source("BLOOMBERG") == []
    assert registry.list_by_source("YAHO") == []
    assert registry.list_by_source("YAHOO_V2") == []


def test_filters_keep_the_order_of_list_all(registry):
    """Every listing agrees on one order, because they all derive from ``list_all``."""
    reference = [i.id for i in registry.list_all()]
    tradable = [i.id for i in registry.list_tradable()]

    assert tradable == [i for i in reference if i in tradable]


def test_registry_supports_len_iteration_and_contains(registry):
    """Iteration follows id order, like :meth:`list_all`."""
    assert len(registry) == 4
    assert [instrument.id for instrument in registry] == [i.id for i in registry.list_all()]
    assert "VIX" in registry
    assert "NOT_A_REAL_ID" not in registry
