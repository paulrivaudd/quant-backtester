"""Point-in-time reading: the three decisive tests, and the cases around them.

The three that decide whether this layer can be trusted are field masking, the
look-ahead guard and NOT_LISTED against MISSING; the rest pin the boundaries.

Everything is synthetic and offline. The calendars come from ``conftest.py`` and
cover 2026 only, which is enough: every situation that breaks a reader - a venue
closed while another trades, a half day, a field published hours after its row,
a split arriving after the decision - happens in that year.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from quant_backtester.data.calendars import CalendarRegistry, TradingCalendar
from quant_backtester.data.instruments import (
    AssetType,
    DataType,
    Instrument,
    InstrumentRegistry,
    PublicationRule,
)
from quant_backtester.data.normalizer import bar_availability
from quant_backtester.data.reader import (
    VALUES_COLUMNS,
    MarketDataReader,
    ObservationStatus,
    PointInTimeReader,
)
from quant_backtester.data.repository import MarketDataRepository
from quant_backtester.data.schemas import (
    AVAILABILITY_COLUMN,
    CHECKED_BARS_SCHEMA,
    CORPORATE_ACTIONS_SCHEMA,
    LEVELS_SCHEMA,
    ActionType,
    BarField,
    CheckStatus,
)

PARIS = ZoneInfo("Europe/Paris")
NEW_YORK = ZoneInfo("America/New_York")

MONDAY = date(2026, 3, 9)
TUESDAY = date(2026, 3, 10)
WEDNESDAY = date(2026, 3, 11)
THURSDAY = date(2026, 3, 12)
"""Four ordinary sessions, open in Paris and in New York alike."""

RATE_RULE = PublicationRule(publication_time=time(16, 15), timezone="America/New_York")
"""US10Y-like release: 16:15 New York, same day."""


def paris(day: date, hour: int, minute: int = 0) -> datetime:
    """Return a Paris wall-clock instant, timezone-aware."""
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=PARIS)


ALL_BAR_FIELDS = ",".join(sorted(field.value for field in BarField))
"""Every field of a bar, as the cross-check spells an unconfirmed set."""


def checked_bars(
    instrument_id: str,
    calendar: TradingCalendar,
    closes: Sequence[tuple[date, float]],
    *,
    opens: Mapping[date, float] | None = None,
    conflicts: Mapping[date, Sequence[BarField]] | None = None,
) -> pd.DataFrame:
    """Build a checked bars frame, availability stamped by the calendar.

    Parameters
    ----------
    instrument_id : str
        Instrument the bars describe.
    calendar : TradingCalendar
        Venue calendar, used for the two availability instants.
    closes : Sequence[tuple[date, float]]
        ``(session_date, close)`` pairs, chronological. A ``NaN`` close is a
        stored row whose value is absent.
    opens : Mapping[date, float] | None
        Opens, defaulting to the close of the session.
    conflicts : Mapping[date, Sequence[BarField]] | None
        Fields two sources disagreed on, per session. A session with none is
        single-sourced, as most of the registry is; a session with some was
        cross-checked against Euronext.

    Returns
    -------
    pd.DataFrame
        Frame matching ``CHECKED_BARS_SCHEMA``.
    """
    rows = []
    for session_date, close in closes:
        open_available, close_available = bar_availability(session_date, calendar)
        contested = sorted(field.value for field in (conflicts or {}).get(session_date, ()))
        status = CheckStatus.CONFLICT if contested else CheckStatus.SINGLE_SOURCE
        rows.append(
            {
                "instrument_id": instrument_id,
                "session_date": session_date,
                "open": (opens or {}).get(session_date, close),
                "high": close,
                "low": close,
                "close": close,
                "volume": 1_000.0,
                "open_available_at_utc": pd.Timestamp(open_available),
                "close_available_at_utc": pd.Timestamp(close_available),
                "source": "YAHOO",
                "source_fetch_id": "20260401T000000Z-aaaaaaaa",
                "check_status": status.value,
                "checked_sources": "EURONEXT,YAHOO" if contested else "YAHOO",
                "checked_fetch_ids": "YAHOO:20260401T000000Z-aaaaaaaa",
                "conflicting_fields": ",".join(contested),
                "unconfirmed_fields": "" if contested else ALL_BAR_FIELDS,
                "max_price_rel_diff": 1e-3 if contested else float("nan"),
                "max_volume_rel_diff": float("nan"),
            }
        )
    frame = pd.DataFrame(rows, columns=list(CHECKED_BARS_SCHEMA.names))
    for column in ("open_available_at_utc", "close_available_at_utc"):
        frame[column] = frame[column].astype("datetime64[us, UTC]")
    return frame


def levels(
    instrument_id: str, rule: PublicationRule, values: Sequence[tuple[date, float]]
) -> pd.DataFrame:
    """Build a levels frame whose availability follows ``rule``."""
    frame = pd.DataFrame(
        [
            {
                "instrument_id": instrument_id,
                "observation_date": observation_date,
                "value": value,
                "available_at_utc": pd.Timestamp(rule.available_at(observation_date)),
                "source": "FRED",
                "source_fetch_id": "20260401T000000Z-bbbbbbbb",
            }
            for observation_date, value in values
        ],
        columns=list(LEVELS_SCHEMA.names),
    )
    frame["available_at_utc"] = frame["available_at_utc"].astype("datetime64[us, UTC]")
    return frame


def corporate_actions(
    rows: Sequence[tuple[str, ActionType, date, float, datetime]],
) -> pd.DataFrame:
    """Build a corporate actions frame from ``(id, type, ex_date, value, available)``."""
    frame = pd.DataFrame(
        [
            {
                "instrument_id": instrument_id,
                "action_type": action_type.value,
                "ex_date": ex_date,
                "value": value,
                "available_at_utc": pd.Timestamp(available_at),
                "source": "YAHOO",
                "source_fetch_id": "20260401T000000Z-cccccccc",
            }
            for instrument_id, action_type, ex_date, value, available_at in rows
        ],
        columns=list(CORPORATE_ACTIONS_SCHEMA.names),
    )
    frame["available_at_utc"] = frame["available_at_utc"].astype("datetime64[us, UTC]")
    return frame


@pytest.fixture
def calendars(xnys: TradingCalendar, xpar: TradingCalendar) -> CalendarRegistry:
    """Return the two venue calendars of the tests."""
    return CalendarRegistry([xnys, xpar])


@pytest.fixture
def instruments() -> InstrumentRegistry:
    """Return one instrument per situation the reader must tell apart."""
    return InstrumentRegistry(
        [
            Instrument(
                id="ETF_EU",
                name="Paris ETF",
                asset_type=AssetType.ETF,
                data_type=DataType.BAR,
                currency="EUR",
                primary_source="YAHOO",
                source_symbol="CW8.PA",
                tradable=True,
                calendar_id="XPAR",
                first_session=date(2026, 1, 5),
            ),
            Instrument(
                id="IDX_US",
                name="US index",
                asset_type=AssetType.INDEX,
                data_type=DataType.BAR,
                currency="USD",
                primary_source="YAHOO",
                source_symbol="^GSPC",
                tradable=False,
                calendar_id="XNYS",
                first_session=date(2026, 1, 2),
            ),
            Instrument(
                id="EQ_US",
                name="US equity",
                asset_type=AssetType.EQUITY,
                data_type=DataType.BAR,
                currency="USD",
                primary_source="YAHOO",
                source_symbol="AAPL",
                tradable=True,
                calendar_id="XNYS",
                first_session=date(2026, 1, 2),
            ),
            Instrument(
                id="ETF_LATE",
                name="ETF launched in June",
                asset_type=AssetType.ETF,
                data_type=DataType.BAR,
                currency="EUR",
                primary_source="YAHOO",
                source_symbol="LATE.PA",
                tradable=True,
                calendar_id="XPAR",
                first_session=date(2026, 6, 1),
            ),
            Instrument(
                id="ETF_GONE",
                name="Delisted ETF",
                asset_type=AssetType.ETF,
                data_type=DataType.BAR,
                currency="EUR",
                primary_source="YAHOO",
                source_symbol="GONE.PA",
                tradable=True,
                calendar_id="XPAR",
                first_session=date(2026, 1, 5),
                last_session=date(2026, 2, 27),
            ),
            Instrument(
                id="RATE_US",
                name="US 10-year rate",
                asset_type=AssetType.RATE,
                data_type=DataType.LEVEL,
                currency="NA",
                primary_source="FRED",
                source_symbol="DGS10",
                tradable=False,
                publication_rule=RATE_RULE,
                first_session=date(2026, 1, 2),
            ),
        ]
    )


@pytest.fixture
def repository(market_root) -> MarketDataRepository:
    """Return an empty repository on a temporary tree."""
    return MarketDataRepository(market_root)


@pytest.fixture
def reader(
    repository: MarketDataRepository,
    instruments: InstrumentRegistry,
    calendars: CalendarRegistry,
) -> MarketDataReader:
    """Return a reader whose decisions are dated by the Paris calendar."""
    return MarketDataReader(repository, instruments, calendars, reference_calendar_id="XPAR")


@pytest.fixture
def stocked(repository: MarketDataRepository, xnys: TradingCalendar, xpar: TradingCalendar) -> None:
    """Store three ordinary sessions for the Paris ETF, the US index and the rate."""
    repository.save_checked_bars(
        "ETF_EU",
        checked_bars(
            "ETF_EU",
            xpar,
            [(MONDAY, 100.0), (TUESDAY, 101.0), (WEDNESDAY, 102.0)],
            opens={MONDAY: 99.0, TUESDAY: 100.5, WEDNESDAY: 101.5},
        ),
    )
    repository.save_checked_bars(
        "IDX_US",
        checked_bars("IDX_US", xnys, [(MONDAY, 5_000.0), (TUESDAY, 5_010.0), (WEDNESDAY, 5_020.0)]),
    )
    repository.save_levels(
        "RATE_US", levels("RATE_US", RATE_RULE, [(MONDAY, 4.1), (TUESDAY, 4.2), (WEDNESDAY, 4.3)])
    )


# ---------------------------------------------------------------------------
# Exercice 8.1 - construction
# ---------------------------------------------------------------------------


def test_naive_as_of_is_rejected(reader: MarketDataReader) -> None:
    """A naive decision instant raises rather than being assumed to be UTC."""
    with pytest.raises(ValueError, match="timezone-aware"):
        reader.at(datetime(2026, 3, 10, 23, 0))


def test_as_of_is_normalised_to_utc(reader: MarketDataReader) -> None:
    """A Paris instant is kept, expressed in UTC."""
    pit = reader.at(paris(TUESDAY, 23, 0))
    assert pit.as_of == datetime(2026, 3, 10, 22, 0, tzinfo=UTC)
    assert pit.as_of.tzinfo is UTC


def test_unknown_reference_calendar_is_rejected(
    repository: MarketDataRepository,
    instruments: InstrumentRegistry,
    calendars: CalendarRegistry,
) -> None:
    """The reference calendar is resolved when the reader is built, not later."""
    with pytest.raises(KeyError, match="XTKS"):
        MarketDataReader(repository, instruments, calendars, reference_calendar_id="XTKS")


def test_reference_calendar_is_carried_to_the_point_in_time_reader(
    reader: MarketDataReader,
) -> None:
    """Every reader built by `at` counts staleness on the same calendar."""
    assert reader.reference_calendar_id == "XPAR"
    assert reader.at(paris(TUESDAY, 23, 0)).reference_calendar_id == "XPAR"


# ---------------------------------------------------------------------------
# Exercice 8.2 - history
# ---------------------------------------------------------------------------


def test_field_masking_follows_the_session(reader: MarketDataReader, stocked: None) -> None:
    """Availability is carried by the field, not by the row.

    At 23:00 Paris on day t, the reader exposes the close of t and refuses the
    open of t+1. At 09:01 on day t+1 it exposes the open of t+1 and refuses the
    close of t+1.

    This is what makes the engine's two readers per day legitimate: the strategy
    gets the decision one and never holds an object able to show it its own fill
    price.
    """
    decision = reader.at(paris(TUESDAY, 23, 0))
    assert list(decision.history("ETF_EU", BarField.CLOSE).index) == [MONDAY, TUESDAY]
    assert list(decision.history("ETF_EU", BarField.OPEN).index) == [MONDAY, TUESDAY]

    execution = reader.at(paris(WEDNESDAY, 9, 1))
    assert list(execution.history("ETF_EU", BarField.OPEN).index) == [MONDAY, TUESDAY, WEDNESDAY]
    assert execution.history("ETF_EU", BarField.OPEN).iloc[-1] == 101.5
    assert list(execution.history("ETF_EU", BarField.CLOSE).index) == [MONDAY, TUESDAY]


def test_history_is_named_and_indexed(reader: MarketDataReader, stocked: None) -> None:
    """The series carries the field name and an `observation_date` index."""
    series = reader.at(paris(TUESDAY, 23, 0)).history("ETF_EU", BarField.CLOSE)
    assert series.name == "close"
    assert series.index.name == "observation_date"
    assert series.dtype == "float64"
    assert list(series) == [100.0, 101.0]


def test_history_bounds_are_inclusive(reader: MarketDataReader, stocked: None) -> None:
    """`start` and `end` cut on the session date, both ends included."""
    pit = reader.at(paris(WEDNESDAY, 23, 0))
    assert list(pit.history("ETF_EU", start=TUESDAY).index) == [TUESDAY, WEDNESDAY]
    assert list(pit.history("ETF_EU", end=TUESDAY).index) == [MONDAY, TUESDAY]
    assert list(pit.history("ETF_EU", start=TUESDAY, end=TUESDAY).index) == [TUESDAY]


def test_history_of_a_level_uses_the_publication_rule(
    reader: MarketDataReader, stocked: None
) -> None:
    """A LEVEL is gated by its release instant, and ignores the bar field."""
    before_release = reader.at(datetime(2026, 3, 10, 20, 0, tzinfo=UTC))
    assert list(before_release.history("RATE_US").index) == [MONDAY]
    after_release = reader.at(datetime(2026, 3, 10, 20, 30, tzinfo=UTC))
    assert list(after_release.history("RATE_US").index) == [MONDAY, TUESDAY]
    assert after_release.history("RATE_US", BarField.OPEN).name == "value"


def test_history_skips_a_session_contested_on_that_field(
    reader: MarketDataReader, repository: MarketDataRepository, xpar: TradingCalendar
) -> None:
    """Two sources disagreeing on the close leave no close to serve."""
    repository.save_checked_bars(
        "ETF_EU",
        checked_bars(
            "ETF_EU",
            xpar,
            [(MONDAY, 100.0), (TUESDAY, 101.0), (WEDNESDAY, 102.0)],
            conflicts={TUESDAY: [BarField.CLOSE]},
        ),
    )
    series = reader.at(paris(WEDNESDAY, 23, 0)).history("ETF_EU", BarField.CLOSE)
    assert list(series.index) == [MONDAY, WEDNESDAY]


def test_history_keeps_a_session_contested_on_another_field(
    reader: MarketDataReader, repository: MarketDataRepository, xpar: TradingCalendar
) -> None:
    """The real CW8 case: the two sources differ on the low, not on the close.

    Withholding the close because of the low hides a number both providers
    agree on, behind one they do not.
    """
    repository.save_checked_bars(
        "ETF_EU",
        checked_bars(
            "ETF_EU",
            xpar,
            [(MONDAY, 100.0), (TUESDAY, 101.0), (WEDNESDAY, 102.0)],
            conflicts={TUESDAY: [BarField.LOW]},
        ),
    )
    pit = reader.at(paris(WEDNESDAY, 23, 0))
    assert list(pit.history("ETF_EU", BarField.CLOSE).index) == [MONDAY, TUESDAY, WEDNESDAY]
    assert list(pit.history("ETF_EU", BarField.LOW).index) == [MONDAY, WEDNESDAY]


def test_history_skips_a_stored_row_without_a_value(
    reader: MarketDataReader, repository: MarketDataRepository, xpar: TradingCalendar
) -> None:
    """An absent value is a shorter series, never a NaN that propagates."""
    repository.save_checked_bars(
        "ETF_EU",
        checked_bars("ETF_EU", xpar, [(MONDAY, 100.0), (TUESDAY, float("nan"))]),
    )
    series = reader.at(paris(TUESDAY, 23, 0)).history("ETF_EU")
    assert list(series.index) == [MONDAY]
    assert not series.isna().any()


def test_history_is_empty_when_nothing_is_stored(reader: MarketDataReader) -> None:
    """An instrument with no file gives an empty float series, not a KeyError."""
    series = reader.at(paris(TUESDAY, 23, 0)).history("ETF_EU")
    assert series.empty
    assert series.dtype == "float64"
    assert series.index.name == "observation_date"


def test_history_of_an_unknown_instrument_raises(reader: MarketDataReader) -> None:
    """An unregistered id is a caller bug, not an empty series."""
    with pytest.raises(KeyError):
        reader.at(paris(TUESDAY, 23, 0)).history("NOPE")


# ---------------------------------------------------------------------------
# Exercice 8.3 - values
# ---------------------------------------------------------------------------


def test_values_reports_the_latest_knowable_value(reader: MarketDataReader, stocked: None) -> None:
    """Fresh values carry age zero and OK, with their availability instant."""
    frame = reader.at(paris(WEDNESDAY, 23, 0)).values(["ETF_EU", "IDX_US"])
    assert list(frame.columns) == list(VALUES_COLUMNS)
    assert frame.index.name == "instrument_id"
    assert frame.loc["ETF_EU", "value"] == 102.0
    assert frame.loc["ETF_EU", "observation_date"] == WEDNESDAY
    assert frame.loc["ETF_EU", "age_sessions"] == 0
    assert frame.loc["ETF_EU", "status"] is ObservationStatus.OK
    assert frame.loc["ETF_EU", "available_at_utc"] == pd.Timestamp(
        datetime(2026, 3, 11, 17, 30, tzinfo=PARIS)
    )
    assert frame.loc["IDX_US", "status"] is ObservationStatus.OK


def test_stale_value_reports_its_age(
    reader: MarketDataReader,
    repository: MarketDataRepository,
    xnys: TradingCalendar,
    xpar: TradingCalendar,
) -> None:
    """A US close read on a day NYSE was closed is STALE with age_sessions >= 1.

    Thanksgiving 2026 falls on 26 November: New York is shut, Paris trades. The
    strategy deciding that evening must see that the US number is a day old.
    """
    wednesday, thursday = date(2026, 11, 25), date(2026, 11, 26)
    repository.save_checked_bars("IDX_US", checked_bars("IDX_US", xnys, [(wednesday, 5_000.0)]))
    repository.save_checked_bars(
        "ETF_EU",
        checked_bars("ETF_EU", xpar, [(wednesday, 100.0), (thursday, 101.0)]),
    )
    frame = reader.at(paris(thursday, 23, 0)).values(["IDX_US", "ETF_EU"])
    assert frame.loc["IDX_US", "observation_date"] == wednesday
    assert frame.loc["IDX_US", "age_sessions"] == 1
    assert frame.loc["IDX_US", "status"] is ObservationStatus.STALE
    assert frame.loc["ETF_EU", "age_sessions"] == 0
    assert frame.loc["ETF_EU", "status"] is ObservationStatus.OK


def test_age_is_counted_on_the_reference_calendar_not_the_venue(
    reader: MarketDataReader, repository: MarketDataRepository, xnys: TradingCalendar
) -> None:
    """Counted at its own venue, a stale US close would look perfectly fresh.

    New York's previous session *is* 25 November, so an age counted on XNYS
    would be zero and the strategy would believe it holds the day's price.
    """
    wednesday, thursday = date(2026, 11, 25), date(2026, 11, 26)
    repository.save_checked_bars("IDX_US", checked_bars("IDX_US", xnys, [(wednesday, 5_000.0)]))
    pit = reader.at(paris(thursday, 23, 0))
    assert pit.values(["IDX_US"]).loc["IDX_US", "age_sessions"] == 1
    assert xnys.sessions_between(wednesday, thursday) == 0


def test_a_session_the_reference_venue_did_not_hold_is_not_negative_age(
    reader: MarketDataReader, repository: MarketDataRepository, xnys: TradingCalendar
) -> None:
    """Easter Monday: Paris is shut, New York trades and publishes a close.

    The value is more recent than the session dating the decision, which is not
    a reason to report a negative age - it is fresh.
    """
    easter_monday = date(2026, 4, 6)
    repository.save_checked_bars("IDX_US", checked_bars("IDX_US", xnys, [(easter_monday, 5_000.0)]))
    frame = reader.at(paris(easter_monday, 23, 0)).values(["IDX_US"])
    assert frame.loc["IDX_US", "observation_date"] == easter_monday
    assert frame.loc["IDX_US", "age_sessions"] == 0
    assert frame.loc["IDX_US", "status"] is ObservationStatus.OK


def test_not_listed_is_distinct_from_missing(
    reader: MarketDataReader, repository: MarketDataRepository, xpar: TradingCalendar
) -> None:
    """Before its first session an instrument is NOT_LISTED, never MISSING.

    An ETF launched later read at an earlier decision instant must be excluded
    from the universe, not reported as a data hole - and a genuine hole must not
    be excluded as if it had never been listed.
    """
    repository.save_checked_bars("ETF_EU", checked_bars("ETF_EU", xpar, [(MONDAY, 100.0)]))
    frame = reader.at(paris(TUESDAY, 23, 0)).values(["ETF_LATE", "ETF_EU"])

    assert frame.loc["ETF_LATE", "status"] is ObservationStatus.NOT_LISTED
    assert pd.isna(frame.loc["ETF_LATE", "value"])
    assert pd.isna(frame.loc["ETF_LATE", "age_sessions"])

    # Paris held a session on Tuesday and its close is due: the gap is a hole.
    assert frame.loc["ETF_EU", "status"] is ObservationStatus.MISSING
    assert pd.isna(frame.loc["ETF_EU", "value"])
    assert pd.isna(frame.loc["ETF_EU", "observation_date"])


def test_a_delisted_instrument_is_not_listed(
    reader: MarketDataReader, repository: MarketDataRepository, xpar: TradingCalendar
) -> None:
    """After its last session an instrument leaves the universe, values and all."""
    last = date(2026, 2, 27)
    repository.save_checked_bars("ETF_GONE", checked_bars("ETF_GONE", xpar, [(last, 100.0)]))
    frame = reader.at(paris(TUESDAY, 23, 0)).values(["ETF_GONE"])
    assert frame.loc["ETF_GONE", "status"] is ObservationStatus.NOT_LISTED
    assert pd.isna(frame.loc["ETF_GONE", "value"])


def test_a_contested_latest_value_is_a_hole(
    reader: MarketDataReader, repository: MarketDataRepository, xpar: TradingCalendar
) -> None:
    """A contested close on the due session is MISSING, not the previous one served on."""
    repository.save_checked_bars(
        "ETF_EU",
        checked_bars(
            "ETF_EU",
            xpar,
            [(MONDAY, 100.0), (TUESDAY, 101.0)],
            conflicts={TUESDAY: [BarField.CLOSE]},
        ),
    )
    frame = reader.at(paris(TUESDAY, 23, 0)).values(["ETF_EU"])
    assert frame.loc["ETF_EU", "status"] is ObservationStatus.MISSING
    assert pd.isna(frame.loc["ETF_EU", "value"])


def test_a_conflict_on_another_field_leaves_this_one_alone(
    reader: MarketDataReader, repository: MarketDataRepository, xpar: TradingCalendar
) -> None:
    """The universe does not lose an instrument because its low is disputed."""
    repository.save_checked_bars(
        "ETF_EU",
        checked_bars(
            "ETF_EU",
            xpar,
            [(MONDAY, 100.0), (TUESDAY, 101.0)],
            conflicts={TUESDAY: [BarField.LOW]},
        ),
    )
    frame = reader.at(paris(TUESDAY, 23, 0)).values(["ETF_EU"])
    assert frame.loc["ETF_EU", "status"] is ObservationStatus.OK
    assert frame.loc["ETF_EU", "value"] == 101.0


def test_a_listed_instrument_with_no_session_due_is_not_listed(
    reader: MarketDataReader, repository: MarketDataRepository, xpar: TradingCalendar
) -> None:
    """Listed today but read before its first close: nothing is owed, nothing missing."""
    first = date(2026, 1, 5)
    repository.save_checked_bars("ETF_EU", checked_bars("ETF_EU", xpar, [(first, 100.0)]))
    frame = reader.at(paris(first, 10, 0)).values(["ETF_EU"])
    assert frame.loc["ETF_EU", "status"] is ObservationStatus.NOT_LISTED


def test_a_level_ages_in_reference_sessions(reader: MarketDataReader, stocked: None) -> None:
    """A rate published at 16:15 New York is a session old until it lands."""
    before_release = reader.at(datetime(2026, 3, 10, 20, 0, tzinfo=UTC)).values(["RATE_US"])
    assert before_release.loc["RATE_US", "observation_date"] == MONDAY
    assert before_release.loc["RATE_US", "age_sessions"] == 1
    assert before_release.loc["RATE_US", "status"] is ObservationStatus.STALE

    after_release = reader.at(datetime(2026, 3, 10, 20, 30, tzinfo=UTC)).values(["RATE_US"])
    assert after_release.loc["RATE_US", "observation_date"] == TUESDAY
    assert after_release.loc["RATE_US", "age_sessions"] == 0


def test_a_level_with_nothing_published_is_missing(reader: MarketDataReader) -> None:
    """A LEVEL has no calendar, so a listed one with no value at all is a hole."""
    frame = reader.at(paris(TUESDAY, 23, 0)).values(["RATE_US"])
    assert frame.loc["RATE_US", "status"] is ObservationStatus.MISSING


def test_values_column_dtypes_are_stable(reader: MarketDataReader, stocked: None) -> None:
    """The frame's dtypes do not depend on which statuses it happens to hold."""
    frame = reader.at(paris(WEDNESDAY, 23, 0)).values(["ETF_EU", "ETF_LATE"])
    assert frame["value"].dtype == "float64"
    assert frame["age_sessions"].dtype == "Int64"
    assert str(frame["available_at_utc"].dtype) == "datetime64[us, UTC]"
    assert pd.isna(frame.loc["ETF_LATE", "available_at_utc"])


def test_values_of_no_instrument_is_an_empty_frame(reader: MarketDataReader) -> None:
    """An empty universe gives an empty frame with the right columns."""
    frame = reader.at(paris(TUESDAY, 23, 0)).values([])
    assert frame.empty
    assert list(frame.columns) == list(VALUES_COLUMNS)
    assert frame["age_sessions"].dtype == "Int64"


def test_values_rejects_a_duplicate_instrument(reader: MarketDataReader, stocked: None) -> None:
    """A repeated id would silently give one universe member two rows."""
    with pytest.raises(ValueError, match="duplicate"):
        reader.at(paris(TUESDAY, 23, 0)).values(["ETF_EU", "ETF_EU"])


def test_values_follows_the_requested_field(reader: MarketDataReader, stocked: None) -> None:
    """Asking for the open at 09:01 gives the day's open, not yesterday's close."""
    frame = reader.at(paris(WEDNESDAY, 9, 1)).values(["ETF_EU"], BarField.OPEN)
    assert frame.loc["ETF_EU", "value"] == 101.5
    assert frame.loc["ETF_EU", "observation_date"] == WEDNESDAY
    assert frame.loc["ETF_EU", "status"] is ObservationStatus.OK


# -- observations: the same rule, one typed object per instrument ------------------


def test_observations_say_what_values_says_one_instrument_at_a_time(
    reader: MarketDataReader, stocked: None
) -> None:
    """The typed twin of the frame: same value, date, instant, age and status."""
    pit = reader.at(paris(WEDNESDAY, 23, 0))
    frame = pit.values(["ETF_EU", "IDX_US"])

    observed = pit.observations(["ETF_EU", "IDX_US"])

    assert list(observed) == ["ETF_EU", "IDX_US"]
    for name, observation in observed.items():
        assert observation.instrument_id == name
        assert observation.value == frame.loc[name, "value"]
        assert observation.observation_date == frame.loc[name, "observation_date"]
        assert observation.age_sessions == frame.loc[name, "age_sessions"]
        assert observation.status is frame.loc[name, "status"]
        assert observation.available_at == frame.loc[name, "available_at_utc"].to_pydatetime()
        assert observation.is_current


def test_an_observation_that_has_no_number_carries_none_rather_than_nan(
    reader: MarketDataReader, repository: MarketDataRepository, xpar: TradingCalendar
) -> None:
    """A hole and an instrument that does not exist yet have no value, and say so plainly."""
    repository.save_checked_bars("ETF_EU", checked_bars("ETF_EU", xpar, [(MONDAY, 100.0)]))

    observed = reader.at(paris(TUESDAY, 23, 0)).observations(["ETF_LATE", "ETF_EU"])

    assert observed["ETF_LATE"].status is ObservationStatus.NOT_LISTED
    assert observed["ETF_LATE"].value is None
    assert observed["ETF_EU"].status is ObservationStatus.MISSING
    assert observed["ETF_EU"].value is None
    assert observed["ETF_EU"].available_at is None
    assert not observed["ETF_EU"].is_current


def test_an_observation_follows_the_requested_field(
    reader: MarketDataReader, stocked: None
) -> None:
    """The open at 09:01 is the day's open, with the instant it became knowable."""
    observed = reader.at(paris(WEDNESDAY, 9, 1)).observations(["ETF_EU"], BarField.OPEN)

    opening = observed["ETF_EU"]
    assert opening.value == 101.5
    assert opening.observation_date == WEDNESDAY
    assert opening.available_at is not None
    assert opening.available_at <= paris(WEDNESDAY, 9, 1)


def test_observations_of_nothing_is_nothing(reader: MarketDataReader) -> None:
    """No instrument asked, no instrument answered."""
    assert reader.at(paris(TUESDAY, 23, 0)).observations([]) == {}


def test_observations_refuse_a_duplicate_instrument(
    reader: MarketDataReader, stocked: None
) -> None:
    """One observation for two universe members would be read twice."""
    with pytest.raises(ValueError, match="duplicate"):
        reader.at(paris(TUESDAY, 23, 0)).observations(["ETF_EU", "ETF_EU"])


# ---------------------------------------------------------------------------
# Exercice 8.4 - corporate actions
# ---------------------------------------------------------------------------


def test_corporate_actions_are_filtered_and_ordered(
    reader: MarketDataReader, repository: MarketDataRepository, xnys: TradingCalendar
) -> None:
    """Only actions already knowable, in ex-date order."""
    repository.save_corporate_actions(
        corporate_actions(
            [
                ("EQ_US", ActionType.DIVIDEND, TUESDAY, 0.5, paris(TUESDAY, 22, 0)),
                ("EQ_US", ActionType.SPLIT, THURSDAY, 4.0, paris(THURSDAY, 22, 0)),
                ("IDX_US", ActionType.DIVIDEND, MONDAY, 0.1, paris(MONDAY, 22, 0)),
            ]
        )
    )
    actions = reader.at(paris(WEDNESDAY, 23, 0)).corporate_actions("EQ_US")
    assert list(actions["ex_date"]) == [TUESDAY]
    assert list(actions["action_type"]) == ["DIVIDEND"]


def test_corporate_actions_of_an_instrument_without_any(reader: MarketDataReader) -> None:
    """No file at all still gives a frame with the right columns."""
    actions = reader.at(paris(TUESDAY, 23, 0)).corporate_actions("EQ_US")
    assert actions.empty
    assert list(actions.columns) == list(CORPORATE_ACTIONS_SCHEMA.names)


# ---------------------------------------------------------------------------
# Exercice 8.5 - adjusted series
# ---------------------------------------------------------------------------


@pytest.fixture
def split_series(repository: MarketDataRepository, xnys: TradingCalendar) -> None:
    """Store a flat 100 series that splits 4:1 on Wednesday, quoting 25 after.

    The raw series is economically flat: 100 before the split, 25 from the
    ex-date on. The action is knowable at the ex-date open, as the schema says -
    the same instant as the first price it affects.
    """
    repository.save_checked_bars(
        "EQ_US",
        checked_bars(
            "EQ_US",
            xnys,
            [(MONDAY, 100.0), (TUESDAY, 100.0), (WEDNESDAY, 25.0), (THURSDAY, 25.0)],
        ),
    )
    repository.save_corporate_actions(
        corporate_actions(
            [
                (
                    "EQ_US",
                    ActionType.SPLIT,
                    WEDNESDAY,
                    4.0,
                    datetime(2026, 3, 11, 9, 30, tzinfo=NEW_YORK),
                )
            ]
        )
    )


def test_adjusted_series_is_flat_across_a_split(
    reader: MarketDataReader, split_series: None
) -> None:
    """A flat series at 100 with a 4:1 split adjusts to a flat series at 25.

    No return jump on the ex-date. If one appears, the adjustment factor is
    applied on the wrong side of the boundary.
    """
    adjusted = reader.at(paris(THURSDAY, 23, 0)).adjusted_history("EQ_US")
    assert list(adjusted) == [25.0, 25.0, 25.0, 25.0]
    assert adjusted.name == "adjusted_close"
    assert list(adjusted.index) == [MONDAY, TUESDAY, WEDNESDAY, THURSDAY]


def test_future_data_does_not_change_the_past(
    reader: MarketDataReader,
    repository: MarketDataRepository,
    xnys: TradingCalendar,
    split_series: None,
) -> None:
    """The look-ahead guard.

    Build a series, read it through a reader frozen at ``as_of``, keep the
    result. Then append bars *and a 4:1 split* dated after ``as_of``, and read
    again through a reader at the same instant. The two results must be
    identical, byte for byte.

    The split is the part that matters: it is the one event able to rewrite a
    past series retroactively, and the reason ``adj_close`` is not stored.
    """
    as_of = paris(TUESDAY, 23, 0)
    before = reader.at(as_of).adjusted_history("EQ_US")
    # The split of Wednesday is already stored, and already invisible here.
    assert list(before) == [100.0, 100.0]

    repository.save_checked_bars(
        "EQ_US",
        checked_bars(
            "EQ_US",
            xnys,
            [
                (MONDAY, 100.0),
                (TUESDAY, 100.0),
                (WEDNESDAY, 25.0),
                (THURSDAY, 25.0),
                (date(2026, 3, 13), 26.0),
            ],
        ),
    )
    repository.save_corporate_actions(
        corporate_actions(
            [
                (
                    "EQ_US",
                    ActionType.SPLIT,
                    WEDNESDAY,
                    4.0,
                    datetime(2026, 3, 11, 9, 30, tzinfo=NEW_YORK),
                ),
                (
                    "EQ_US",
                    ActionType.SPLIT,
                    date(2026, 3, 13),
                    2.0,
                    datetime(2026, 3, 13, 9, 30, tzinfo=NEW_YORK),
                ),
            ]
        )
    )
    after = reader.at(as_of).adjusted_history("EQ_US")
    pd.testing.assert_series_equal(before, after)


def test_a_dividend_adjusts_earlier_prices_only(
    reader: MarketDataReader, repository: MarketDataRepository, xnys: TradingCalendar
) -> None:
    """A 2.00 dividend on a 100.00 close scales every earlier price by 0.98."""
    repository.save_checked_bars(
        "EQ_US",
        checked_bars("EQ_US", xnys, [(MONDAY, 100.0), (TUESDAY, 100.0), (WEDNESDAY, 98.0)]),
    )
    repository.save_corporate_actions(
        corporate_actions(
            [
                (
                    "EQ_US",
                    ActionType.DIVIDEND,
                    WEDNESDAY,
                    2.0,
                    datetime(2026, 3, 11, 9, 30, tzinfo=NEW_YORK),
                )
            ]
        )
    )
    adjusted = reader.at(paris(WEDNESDAY, 23, 0)).adjusted_history("EQ_US")
    assert list(adjusted) == [98.0, 98.0, 98.0]


def test_the_adjusted_series_is_a_price_not_a_reinvested_wealth(
    reader: MarketDataReader, repository: MarketDataRepository, xnys: TradingCalendar
) -> None:
    """The convention of audit A08, written down so nobody takes it for another.

    100 then 110 with a 10 dividend: the adjusted series earns 110 / 90 - 1,
    because its factor ``1 - D / C_prev`` is known at the ex-date's open. A
    holder reinvesting at the close earns (110 + 10) / 100 - 1 = 20%; that is
    the benchmark's TOTAL_RETURN, not this.
    """
    repository.save_checked_bars(
        "EQ_US", checked_bars("EQ_US", xnys, [(MONDAY, 100.0), (TUESDAY, 110.0)])
    )
    repository.save_corporate_actions(
        corporate_actions(
            [
                (
                    "EQ_US",
                    ActionType.DIVIDEND,
                    TUESDAY,
                    10.0,
                    datetime(2026, 3, 10, 9, 30, tzinfo=NEW_YORK),
                )
            ]
        )
    )
    adjusted = reader.at(paris(TUESDAY, 23, 0)).adjusted_history("EQ_US")

    assert adjusted.iloc[1] / adjusted.iloc[0] - 1 == pytest.approx(110.0 / 90.0 - 1)
    assert adjusted.iloc[1] / adjusted.iloc[0] - 1 != pytest.approx(0.20)


def test_no_fake_gap_between_the_adjusted_close_and_the_ex_date_open(
    reader: MarketDataReader, repository: MarketDataRepository, split_series: None
) -> None:
    """The reader that executes at the open sees the split and the price together.

    This is what the ex-date open availability buys. At 09:31 New York on the
    ex-date the strategy holds an adjusted history ending at 25 the day before
    and an open of 25 - a flat move. With the action stamped at the close
    instead, the history would still end at 100 and the very same open would
    read as a 75% collapse.
    """
    execution = reader.at(datetime(2026, 3, 11, 9, 31, tzinfo=NEW_YORK))

    assert list(execution.corporate_actions("EQ_US")["ex_date"]) == [WEDNESDAY]
    adjusted = execution.adjusted_history("EQ_US")
    assert list(adjusted.index) == [MONDAY, TUESDAY]
    assert list(adjusted) == [25.0, 25.0]
    open_price = execution.history("EQ_US", BarField.OPEN).iloc[-1]
    assert open_price == 25.0
    assert adjusted.iloc[-1] == open_price

    # The evening before, neither the action nor the adjustment exists yet.
    decision = reader.at(paris(TUESDAY, 23, 0))
    assert decision.corporate_actions("EQ_US").empty
    assert list(decision.adjusted_history("EQ_US")) == [100.0, 100.0]


def test_adjustment_happens_before_the_window_is_cut(
    reader: MarketDataReader, split_series: None
) -> None:
    """Asking for one session does not change what the factors were built from."""
    pit = reader.at(paris(THURSDAY, 23, 0))
    windowed = pit.adjusted_history("EQ_US", start=MONDAY, end=TUESDAY)
    assert list(windowed.index) == [MONDAY, TUESDAY]
    assert list(windowed) == [25.0, 25.0]


def test_adjusted_history_refuses_a_level(reader: MarketDataReader, stocked: None) -> None:
    """Adjusting a published rate for corporate actions is meaningless."""
    with pytest.raises(ValueError, match="BAR"):
        reader.at(paris(TUESDAY, 23, 0)).adjusted_history("RATE_US")


def test_a_dividend_larger_than_the_close_is_refused(
    reader: MarketDataReader, repository: MarketDataRepository, xnys: TradingCalendar
) -> None:
    """A factor at or below zero would flip the sign of the whole history."""
    repository.save_checked_bars(
        "EQ_US", checked_bars("EQ_US", xnys, [(MONDAY, 10.0), (TUESDAY, 5.0)])
    )
    repository.save_corporate_actions(
        corporate_actions(
            [
                (
                    "EQ_US",
                    ActionType.DIVIDEND,
                    TUESDAY,
                    20.0,
                    datetime(2026, 3, 10, 9, 30, tzinfo=NEW_YORK),
                )
            ]
        )
    )
    with pytest.raises(ValueError, match="not smaller than"):
        reader.at(paris(TUESDAY, 23, 0)).adjusted_history("EQ_US")


def test_a_non_positive_split_ratio_is_refused(
    reader: MarketDataReader, repository: MarketDataRepository, xnys: TradingCalendar
) -> None:
    """A zero ratio would divide every earlier price by zero."""
    repository.save_checked_bars(
        "EQ_US", checked_bars("EQ_US", xnys, [(MONDAY, 10.0), (TUESDAY, 10.0)])
    )
    repository.save_corporate_actions(
        corporate_actions(
            [
                (
                    "EQ_US",
                    ActionType.SPLIT,
                    TUESDAY,
                    0.0,
                    datetime(2026, 3, 10, 9, 30, tzinfo=NEW_YORK),
                )
            ]
        )
    )
    with pytest.raises(ValueError, match="strictly positive"):
        reader.at(paris(TUESDAY, 23, 0)).adjusted_history("EQ_US")


# ---------------------------------------------------------------------------
# Exercices 8.6 and 8.7 - the entry point
# ---------------------------------------------------------------------------


def test_at_returns_a_reader_bound_to_the_instant(reader: MarketDataReader) -> None:
    """`at` is the only method the engine uses to reach the data."""
    pit = reader.at(paris(TUESDAY, 23, 0))
    assert isinstance(pit, PointInTimeReader)
    assert pit.as_of == datetime(2026, 3, 10, 22, 0, tzinfo=UTC)


def test_latest_reads_the_wall_clock(reader: MarketDataReader) -> None:
    """`latest` is bound to now, in UTC - and only exists off the strategy's object."""
    before = datetime.now(UTC)
    pit = reader.latest()
    after = datetime.now(UTC)
    assert before <= pit.as_of <= after
    assert not hasattr(pit, "latest")


def test_the_registry_is_reachable_from_the_reader(
    reader: MarketDataReader, instruments: InstrumentRegistry
) -> None:
    """The engine needs the universe, and gets it without a second wiring."""
    assert reader.instruments is instruments


# -- the vectorised contested mask, held to the naive rule --------------------------------


@pytest.mark.parametrize("field", list(BarField), ids=lambda field: field.value)
def test_the_vectorised_mask_agrees_with_the_naive_rule_cell_by_cell(field: BarField) -> None:
    """The reader filters with a regular expression; the rule it implements is the loop.

    Every awkward cell a cross-check or a hand edit could leave: empty, missing,
    one field, several, a name that only starts like a field, a space after a
    comma, a field twice.
    """
    from quant_backtester.data.reader import _contested, _is_contested

    cells = [
        "",
        None,
        float("nan"),
        "close",
        "low",
        "close,low",
        "high,low,open",
        "closed",
        "open_interest",
        "low, close",
        " close",
        "close,close",
        "volume",
        "open,close,high,low,volume",
    ]
    series = pd.Series(cells, dtype="object")

    vectorised = list(_contested(series, field))
    naive = [_is_contested(cell, field) for cell in cells]

    assert vectorised == naive


def test_the_vectorised_mask_handles_the_stored_string_dtype() -> None:
    """The column comes back from Parquet as strings, not objects; the answer is the same."""
    from quant_backtester.data.reader import _contested

    stored = pd.Series(["", "close", "low,open"], dtype="str")

    assert list(_contested(stored, BarField.LOW)) == [False, False, True]


# --- a series prepared once per file version (lot 6) ------------------------------


def _naive_history(
    repository: MarketDataRepository,
    instrument_id: str,
    field: BarField,
    as_of: datetime,
    start: date | None,
    end: date | None,
) -> list[tuple[date, float]]:
    """Return what the reader must serve, computed row by row with no cache at all."""
    rows = []
    for row in repository.load_checked_bars(instrument_id).to_dict("records"):
        day = row["session_date"]
        if (start is not None and day < start) or (end is not None and day > end):
            continue
        if field.value in str(row["conflicting_fields"]).split(","):
            continue
        value = row[field.value]
        available = row[AVAILABILITY_COLUMN[field]]
        if value != value or available > as_of:
            continue
        rows.append((day, float(value)))
    return sorted(rows, key=lambda item: item[0])


@pytest.mark.parametrize("field", [BarField.OPEN, BarField.CLOSE])
def test_the_prepared_series_serves_what_a_row_by_row_reading_would(
    reader: MarketDataReader,
    repository: MarketDataRepository,
    xnys: TradingCalendar,
    field: BarField,
) -> None:
    """Every instant, every bound, contested fields and a missing value included."""
    closes = [(MONDAY, 100.0), (TUESDAY, 101.0), (WEDNESDAY, 102.0), (THURSDAY, 103.0)]
    repository.save_checked_bars(
        "EQ_US",
        checked_bars(
            "EQ_US",
            xnys,
            closes,
            opens={TUESDAY: float("nan")},
            conflicts={WEDNESDAY: (BarField.CLOSE,)},
        ),
    )
    instants = [
        paris(day, hour) for day in (MONDAY, TUESDAY, WEDNESDAY, THURSDAY) for hour in (10, 23)
    ]
    bounds = [(None, None), (TUESDAY, None), (None, WEDNESDAY), (TUESDAY, WEDNESDAY)]
    for as_of in instants:
        for start, end in bounds:
            served = reader.at(as_of).history("EQ_US", field, start=start, end=end)
            expected = _naive_history(repository, "EQ_US", field, as_of, start, end)
            assert list(zip(served.index, served, strict=True)) == expected, (as_of, start, end)


def test_a_new_version_of_the_file_is_read_again(
    reader: MarketDataReader, repository: MarketDataRepository, xnys: TradingCalendar
) -> None:
    """The cache is keyed on the file's version: a promotion is never served stale."""
    repository.save_checked_bars("EQ_US", checked_bars("EQ_US", xnys, [(MONDAY, 100.0)]))
    evening = paris(TUESDAY, 23)
    assert list(reader.at(evening).history("EQ_US")) == [100.0]

    repository.save_checked_bars(
        "EQ_US", checked_bars("EQ_US", xnys, [(MONDAY, 100.0), (TUESDAY, 150.0)])
    )

    assert list(reader.at(evening).history("EQ_US")) == [100.0, 150.0]


def test_a_long_lived_reader_keeps_one_prepared_copy_per_series(
    reader: MarketDataReader, repository: MarketDataRepository, xnys: TradingCalendar
) -> None:
    """Audit N09: twenty promotions left twenty prepared versions of one series."""
    evening = paris(THURSDAY, 23)
    for step in range(20):
        repository.save_checked_bars(
            "EQ_US", checked_bars("EQ_US", xnys, [(MONDAY, 100.0 + step), (TUESDAY, 101.0)])
        )
        assert list(reader.at(evening).history("EQ_US")) == [100.0 + step, 101.0]

    assert len(reader._prepared) == 1
