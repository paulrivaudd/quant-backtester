"""Normalizer: availability stamping and provider frames -> canonical schemas.

Normalisation is a pure function of (raw frame, instrument, calendar): no clock,
no filesystem, no network. The calendars are the synthetic 2026 fixtures of
``conftest.py``, so every expected instant below can be checked by hand.
"""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pytest

from quant_backtester.data.calendars import CalendarCoverageError, CalendarRegistry, TradingCalendar
from quant_backtester.data.crosscheck import CrossCheckPolicy, cross_check_bars
from quant_backtester.data.instruments import (
    AssetType,
    DataType,
    Instrument,
    InstrumentRegistry,
    PublicationRule,
)
from quant_backtester.data.normalizer import (
    NORMALIZERS,
    AlfredNormalizer,
    EcbNormalizer,
    EuronextNormalizer,
    FredNormalizer,
    NormalizedData,
    YahooNormalizer,
    bar_availability,
    get_normalizer,
)
from quant_backtester.data.schemas import BARS_SCHEMA, CORPORATE_ACTIONS_SCHEMA, LEVELS_SCHEMA
from quant_backtester.data.sources.base import RawDownload
from quant_backtester.data.sources.yahoo import YahooSource


def utc(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    """Return a UTC-aware instant."""
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


# --- 5.1 bar_availability: behaviour ------------------------------------------


@pytest.mark.parametrize(
    ("calendar_name", "day", "expected"),
    [
        # New York 09:30-16:00: EST (UTC-5) in January, EDT (UTC-4) in September.
        ("xnys", date(2026, 1, 15), (utc(2026, 1, 15, 14, 30), utc(2026, 1, 15, 21, 0))),
        ("xnys", date(2026, 9, 10), (utc(2026, 9, 10, 13, 30), utc(2026, 9, 10, 20, 0))),
        # 12 March: the US switched on 8 March, Europe only on 29 March.
        ("xnys", date(2026, 3, 12), (utc(2026, 3, 12, 13, 30), utc(2026, 3, 12, 20, 0))),
        ("xpar", date(2026, 3, 12), (utc(2026, 3, 12, 8, 0), utc(2026, 3, 12, 16, 30))),
        # Half days: 13:00 EST in New York, 14:05 CET in Paris.
        ("xnys", date(2026, 11, 27), (utc(2026, 11, 27, 14, 30), utc(2026, 11, 27, 18, 0))),
        ("xpar", date(2026, 12, 24), (utc(2026, 12, 24, 8, 0), utc(2026, 12, 24, 13, 5))),
        # Easter Monday: Paris is closed, New York trades.
        ("xnys", date(2026, 4, 6), (utc(2026, 4, 6, 13, 30), utc(2026, 4, 6, 20, 0))),
    ],
    ids=[
        "xnys-winter",
        "xnys-summer",
        "xnys-dst-gap",
        "xpar-dst-gap",
        "xnys-half-day",
        "xpar-half-day",
        "xnys-easter-monday",
    ],
)
def test_bar_availability_returns_the_session_open_and_close_in_utc(
    request: pytest.FixtureRequest,
    calendar_name: str,
    day: date,
    expected: tuple[datetime, datetime],
) -> None:
    calendar: TradingCalendar = request.getfixturevalue(calendar_name)
    assert bar_availability(day, calendar) == expected


def test_bar_availability_instants_are_utc_aware_and_ordered(xnys: TradingCalendar) -> None:
    open_at, close_at = bar_availability(date(2026, 9, 10), xnys)
    assert open_at.tzinfo is UTC
    assert close_at.tzinfo is UTC
    assert open_at < close_at


def test_bar_availability_half_day_is_shorter_than_a_regular_session(
    xnys: TradingCalendar,
) -> None:
    regular_open, regular_close = bar_availability(date(2026, 11, 25), xnys)
    half_open, half_close = bar_availability(date(2026, 11, 27), xnys)
    assert regular_close - regular_open == timedelta(hours=6, minutes=30)
    assert half_close - half_open == timedelta(hours=3, minutes=30)


# --- 5.1 bar_availability: boundaries -----------------------------------------


@pytest.mark.parametrize(
    ("calendar_name", "day"),
    [
        ("xnys", date(2026, 9, 7)),
        ("xpar", date(2026, 4, 6)),
        ("xnys", date(2026, 11, 1)),
    ],
    ids=["xnys-labor-day", "xpar-easter-monday", "sunday"],
)
def test_bar_availability_rejects_a_day_without_session(
    request: pytest.FixtureRequest, calendar_name: str, day: date
) -> None:
    calendar: TradingCalendar = request.getfixturevalue(calendar_name)
    with pytest.raises(ValueError, match=calendar.calendar_id) as raised:
        bar_availability(day, calendar)
    assert day.isoformat() in str(raised.value)


def test_bar_availability_outside_coverage_is_a_coverage_error_not_a_closed_day(
    xnys: TradingCalendar,
) -> None:
    # "The calendar cannot tell" and "the venue was closed" must stay distinct.
    with pytest.raises(CalendarCoverageError) as raised:
        bar_availability(date(2025, 12, 31), xnys)
    assert not isinstance(raised.value, ValueError)


def test_bar_availability_rejects_a_datetime(xnys: TradingCalendar) -> None:
    with pytest.raises(TypeError):
        bar_availability(datetime(2026, 9, 10, 20, 0, tzinfo=UTC), xnys)


# --- 5.1 bar_availability: look-ahead guards ----------------------------------


def test_bar_availability_matches_every_session_and_never_leaks_the_close(
    xnys: TradingCalendar,
) -> None:
    sessions = xnys.sessions(date(2026, 1, 1), date(2026, 12, 31))
    assert sessions
    for session in sessions:
        open_at, close_at = bar_availability(session.session_date, xnys)
        assert (open_at, close_at) == (session.open_utc, session.close_utc)
        assert close_at > open_at


def nyse_2026(
    extra_holidays: frozenset[date] = frozenset(),
    extra_early_closes: dict[date, time] | None = None,
) -> TradingCalendar:
    """Return the ``xnys`` fixture calendar, optionally with more December events."""
    return TradingCalendar(
        calendar_id="XNYS",
        timezone="America/New_York",
        regular_open=time(9, 30),
        regular_close=time(16, 0),
        holidays=frozenset(
            {date(2026, 1, 19), date(2026, 9, 7), date(2026, 11, 26), date(2026, 12, 25)}
        )
        | extra_holidays,
        early_closes={date(2026, 11, 27): time(13, 0), date(2026, 12, 24): time(13, 0)}
        | (extra_early_closes or {}),
        covered_from=date(2026, 1, 1),
        covered_until=date(2026, 12, 31),
    )


def test_bar_availability_ignores_calendar_events_after_the_session() -> None:
    baseline = nyse_2026()
    with_later_events = nyse_2026(
        extra_holidays=frozenset({date(2026, 12, 31)}),
        extra_early_closes={date(2026, 12, 30): time(13, 0)},
    )
    day = date(2026, 9, 10)
    assert bar_availability(day, with_later_events) == bar_availability(day, baseline)


# --- 5.2 YahooNormalizer: builders ----------------------------------------------

FETCH_ID = "20261231T230311Z"
RETRIEVED_AT = datetime(2026, 12, 31, 23, 3, 11, tzinfo=UTC)
"""Fetch instant of every download below: after the last session of the fixture year.

The normalizer refuses a row that was not public yet when the fetch ran, so a
test about availability stamping must download after the data existed. Dating
the fetch at the end of 2026 keeps every fixture date published and leaves the
guard itself to the tests that exercise it."""
NORMALIZER = YahooNormalizer()


@pytest.fixture
def spy_etf() -> Instrument:
    """Return a tradable NYSE ETF."""
    return Instrument(
        id="US_SPY",
        name="SPDR S&P 500 ETF",
        asset_type=AssetType.ETF,
        data_type=DataType.BAR,
        currency="USD",
        primary_source="YAHOO",
        source_symbol="SPY",
        tradable=True,
        calendar_id="XNYS",
    )


@pytest.fixture
def cw8() -> Instrument:
    """Return the Paris-listed MSCI World ETF declared in ``instruments.toml``."""
    return Instrument(
        id="ETF_WORLD",
        name="Amundi MSCI World (PEA)",
        asset_type=AssetType.ETF,
        data_type=DataType.BAR,
        currency="EUR",
        primary_source="YAHOO",
        source_symbol="CW8.PA",
        tradable=True,
        calendar_id="XPAR",
    )


def yahoo_bars(
    days: list[str],
    timezone: str | None = "America/New_York",
    convert_to: str | None = None,
) -> pd.DataFrame:
    """Return a raw Yahoo ``history`` frame, one midnight-stamped row per day.

    Prices rise by 1 per row so each row is recognisable. ``convert_to`` re-expresses
    the index in another zone, the way a provider could hand it over in UTC.
    """
    index = pd.DatetimeIndex([pd.Timestamp(day) for day in days], name="Date")
    if timezone is not None:
        index = index.tz_localize(timezone)
    if convert_to is not None:
        index = index.tz_convert(convert_to)
    offsets = [float(position) for position in range(len(days))]
    return pd.DataFrame(
        {
            "Open": [100.0 + offset for offset in offsets],
            "High": [110.0 + offset for offset in offsets],
            "Low": [90.0 + offset for offset in offsets],
            "Close": [105.0 + offset for offset in offsets],
            "Adj Close": [104.0 + offset for offset in offsets],
            "Volume": [1_000_000 + position for position in range(len(days))],
        },
        index=index,
    )


def yahoo_actions(rows: list[tuple[str, float, float]]) -> pd.DataFrame:
    """Return a raw Yahoo ``actions`` frame from ``(ex_date, dividend, split)`` rows."""
    index = pd.DatetimeIndex([pd.Timestamp(day) for day, _, _ in rows], name="Date")
    return pd.DataFrame(
        {
            "Dividends": [dividend for _, dividend, _ in rows],
            "Stock Splits": [split for _, _, split in rows],
        },
        index=index.tz_localize("America/New_York"),
    )


def bars_download(
    frame: pd.DataFrame,
    instrument_id: str = "US_SPY",
    source: str = "YAHOO",
    retrieved_at: datetime = RETRIEVED_AT,
) -> RawDownload:
    """Wrap a raw bars frame the way ``YahooSource.download`` does."""
    return RawDownload(
        instrument_id=instrument_id,
        source=source,
        fetch_id=FETCH_ID,
        retrieved_at_utc=retrieved_at,
        frame=frame,
        request={
            "symbol": "SPY",
            "start": "2026-01-01",
            "end_inclusive": "2026-12-31",
            "interval": "1d",
            "auto_adjust": False,
            "actions": False,
        },
    )


def actions_download(
    frame: pd.DataFrame, start: str = "2026-01-01", end: str = "2026-12-31"
) -> RawDownload:
    """Wrap a raw actions frame the way ``YahooSource.download_corporate_actions`` does."""
    return RawDownload(
        instrument_id="US_SPY",
        source="YAHOO",
        fetch_id=FETCH_ID,
        retrieved_at_utc=RETRIEVED_AT,
        frame=frame,
        request={
            "symbol": "SPY",
            "endpoint": "actions",
            "period": "max",
            "start": start,
            "end_inclusive": end,
        },
    )


def bars_of(result: NormalizedData) -> pd.DataFrame:
    """Return the bars of a result that must hold bars only."""
    assert result.bars is not None
    assert result.levels is None
    assert result.corporate_actions is None
    return result.bars


def actions_of(result: NormalizedData) -> pd.DataFrame:
    """Return the actions of a result that must hold corporate actions only."""
    assert result.corporate_actions is not None
    assert result.bars is None
    assert result.levels is None
    return result.corporate_actions


# --- 5.2 bars: behaviour ------------------------------------------------------


def test_yahoo_bars_have_canonical_columns_and_drop_adj_close(
    spy_etf: Instrument, xnys: TradingCalendar
) -> None:
    raw = yahoo_bars(["2026-09-10", "2026-09-11"])
    bars = bars_of(NORMALIZER.normalize(spy_etf, bars_download(raw), xnys))
    assert list(bars.columns) == BARS_SCHEMA.names
    assert "adj_close" not in bars.columns
    assert bars["open"].tolist() == [100.0, 101.0]
    assert bars["high"].tolist() == [110.0, 111.0]
    assert bars["low"].tolist() == [90.0, 91.0]
    assert bars["close"].tolist() == [105.0, 106.0]


def test_yahoo_bars_new_york_midnight_index_keeps_the_session_date(
    spy_etf: Instrument, xnys: TradingCalendar
) -> None:
    raw = yahoo_bars(["2026-09-10", "2026-09-11"])
    bars = bars_of(NORMALIZER.normalize(spy_etf, bars_download(raw), xnys))
    assert bars["session_date"].tolist() == [date(2026, 9, 10), date(2026, 9, 11)]


def test_yahoo_bars_paris_index_given_in_utc_uses_the_venue_date(
    cw8: Instrument, xpar: TradingCalendar
) -> None:
    raw = yahoo_bars(["2026-09-10", "2026-09-11"], timezone="Europe/Paris", convert_to="UTC")
    # The trap: read in UTC, Paris midnight is still the previous day.
    assert pd.Timestamp(str(raw.index[0])).date() == date(2026, 9, 9)
    download = bars_download(raw, instrument_id="ETF_WORLD")
    bars = bars_of(NORMALIZER.normalize(cw8, download, xpar))
    assert bars["session_date"].tolist() == [date(2026, 9, 10), date(2026, 9, 11)]


def test_yahoo_bars_naive_index_is_read_as_local_dates(
    spy_etf: Instrument, xnys: TradingCalendar
) -> None:
    raw = yahoo_bars(["2026-09-10", "2026-09-11"], timezone=None)
    bars = bars_of(NORMALIZER.normalize(spy_etf, bars_download(raw), xnys))
    assert bars["session_date"].tolist() == [date(2026, 9, 10), date(2026, 9, 11)]


def test_yahoo_bars_open_and_close_availability_come_from_the_session(
    spy_etf: Instrument, xnys: TradingCalendar
) -> None:
    raw = yahoo_bars(["2026-09-10", "2026-09-11"])
    bars = bars_of(NORMALIZER.normalize(spy_etf, bars_download(raw), xnys))
    assert bars["open_available_at_utc"].tolist() == [
        utc(2026, 9, 10, 13, 30),
        utc(2026, 9, 11, 13, 30),
    ]
    assert bars["close_available_at_utc"].tolist() == [
        utc(2026, 9, 10, 20, 0),
        utc(2026, 9, 11, 20, 0),
    ]


def test_yahoo_bars_half_day_close_is_available_at_the_early_close(
    spy_etf: Instrument, xnys: TradingCalendar
) -> None:
    raw = yahoo_bars(["2026-11-27"])
    bars = bars_of(NORMALIZER.normalize(spy_etf, bars_download(raw), xnys))
    assert bars["open_available_at_utc"].tolist() == [utc(2026, 11, 27, 14, 30)]
    assert bars["close_available_at_utc"].tolist() == [utc(2026, 11, 27, 18, 0)]


def test_yahoo_bars_volume_is_float_and_lineage_is_on_every_row(
    spy_etf: Instrument, xnys: TradingCalendar
) -> None:
    raw = yahoo_bars(["2026-09-10", "2026-09-11"])
    bars = bars_of(NORMALIZER.normalize(spy_etf, bars_download(raw), xnys))
    assert bars["volume"].dtype == "float64"
    assert bars["volume"].tolist() == [1_000_000.0, 1_000_001.0]
    assert set(bars["instrument_id"]) == {"US_SPY"}
    assert set(bars["source"]) == {"YAHOO"}
    assert set(bars["source_fetch_id"]) == {FETCH_ID}


def test_yahoo_bars_convert_to_the_arrow_schema(spy_etf: Instrument, xnys: TradingCalendar) -> None:
    raw = yahoo_bars(["2026-09-10", "2026-09-11"])
    bars = bars_of(NORMALIZER.normalize(spy_etf, bars_download(raw), xnys))
    table = pa.Table.from_pandas(bars, schema=BARS_SCHEMA, preserve_index=False)
    assert table.num_rows == 2


def test_yahoo_bars_leave_the_raw_frame_untouched(
    spy_etf: Instrument, xnys: TradingCalendar
) -> None:
    raw = yahoo_bars(["2026-09-10", "2026-09-11"])
    before = raw.copy()
    NORMALIZER.normalize(spy_etf, bars_download(raw), xnys)
    pd.testing.assert_frame_equal(raw, before)


def test_yahoo_bars_keep_a_missing_price_as_nan(spy_etf: Instrument, xnys: TradingCalendar) -> None:
    raw = yahoo_bars(["2026-09-10", "2026-09-11"])
    raw["Open"] = [float("nan"), 101.0]
    bars = bars_of(NORMALIZER.normalize(spy_etf, bars_download(raw), xnys))
    assert math.isnan(bars["open"].tolist()[0])
    # Prices are nullable in the schema: judging the gap is the validator's job.
    assert pa.Table.from_pandas(bars, schema=BARS_SCHEMA, preserve_index=False).num_rows == 2


# --- 5.2 bars: boundaries -----------------------------------------------------


def test_yahoo_bars_empty_frame_gives_an_empty_canonical_frame(
    spy_etf: Instrument, xnys: TradingCalendar
) -> None:
    bars = bars_of(NORMALIZER.normalize(spy_etf, bars_download(yahoo_bars([])), xnys))
    assert bars.empty
    assert list(bars.columns) == BARS_SCHEMA.names
    assert pa.Table.from_pandas(bars, schema=BARS_SCHEMA, preserve_index=False).num_rows == 0


def test_yahoo_bars_single_row(spy_etf: Instrument, xnys: TradingCalendar) -> None:
    bars = bars_of(NORMALIZER.normalize(spy_etf, bars_download(yahoo_bars(["2026-09-10"])), xnys))
    assert len(bars) == 1
    assert bars["session_date"].tolist() == [date(2026, 9, 10)]


def test_yahoo_bars_on_a_holiday_are_dropped_and_named(
    spy_etf: Instrument, xnys: TradingCalendar
) -> None:
    """A bar on a day the venue was shut has no instant at which it was knowable.

    It cannot be stored, so it is dropped - and named, because Yahoo really
    sends them: one for CW8 on 2019-12-25, a Christmas Euronext was closed.
    Raising instead used to take the whole instrument down with it, its thirty
    good years included.
    """
    raw = yahoo_bars(["2026-09-04", "2026-09-07"])  # Labor Day

    normalized = NORMALIZER.normalize(spy_etf, bars_download(raw), xnys)

    assert normalized.bars is not None
    assert normalized.bars["session_date"].tolist() == [date(2026, 9, 4)]
    assert normalized.rejected.non_session == (date(2026, 9, 7),)


def test_yahoo_bars_outside_calendar_coverage_raise_a_coverage_error(
    spy_etf: Instrument, xnys: TradingCalendar
) -> None:
    raw = yahoo_bars(["2025-12-31"])
    with pytest.raises(CalendarCoverageError):
        NORMALIZER.normalize(spy_etf, bars_download(raw), xnys)


def test_yahoo_bars_repeated_session_raises(spy_etf: Instrument, xnys: TradingCalendar) -> None:
    raw = yahoo_bars(["2026-09-10", "2026-09-10"])
    with pytest.raises(ValueError, match="2026-09-10"):
        NORMALIZER.normalize(spy_etf, bars_download(raw), xnys)


def test_yahoo_bars_missing_column_raises(spy_etf: Instrument, xnys: TradingCalendar) -> None:
    raw = yahoo_bars(["2026-09-10"]).drop(columns=["Volume"])
    with pytest.raises(ValueError, match="Volume"):
        NORMALIZER.normalize(spy_etf, bars_download(raw), xnys)


def test_yahoo_bars_non_datetime_index_raises(spy_etf: Instrument, xnys: TradingCalendar) -> None:
    raw = yahoo_bars(["2026-09-10"]).reset_index(drop=True)
    with pytest.raises(ValueError, match="DatetimeIndex"):
        NORMALIZER.normalize(spy_etf, bars_download(raw), xnys)


def test_yahoo_bars_missing_timestamp_raises(spy_etf: Instrument, xnys: TradingCalendar) -> None:
    raw = yahoo_bars(["2026-09-10"], timezone=None)
    raw.index = pd.DatetimeIndex([pd.NaT], name="Date")
    with pytest.raises(ValueError, match="missing timestamp"):
        NORMALIZER.normalize(spy_etf, bars_download(raw), xnys)


# --- 5.2 normalize: inconsistent calls ----------------------------------------


def test_yahoo_normalize_requires_a_calendar(spy_etf: Instrument) -> None:
    with pytest.raises(ValueError, match="calendar"):
        NORMALIZER.normalize(spy_etf, bars_download(yahoo_bars(["2026-09-10"])))


def test_yahoo_normalize_rejects_another_source(spy_etf: Instrument, xnys: TradingCalendar) -> None:
    download = bars_download(yahoo_bars(["2026-09-10"]), source="FRED")
    with pytest.raises(ValueError, match="FRED"):
        NORMALIZER.normalize(spy_etf, download, xnys)


def test_yahoo_normalize_rejects_another_instrument(
    spy_etf: Instrument, xnys: TradingCalendar
) -> None:
    download = bars_download(yahoo_bars(["2026-09-10"]), instrument_id="ETF_WORLD")
    with pytest.raises(ValueError, match="ETF_WORLD"):
        NORMALIZER.normalize(spy_etf, download, xnys)


def test_yahoo_normalize_rejects_a_level_instrument(xnys: TradingCalendar) -> None:
    level = Instrument(
        id="US_SPY",
        name="Not a bar",
        asset_type=AssetType.RATE,
        data_type=DataType.LEVEL,
        currency="NA",
        primary_source="YAHOO",
        source_symbol="SPY",
        tradable=False,
        publication_rule=PublicationRule(publication_time=time(16, 0), timezone="America/New_York"),
    )
    with pytest.raises(ValueError, match="LEVEL"):
        NORMALIZER.normalize(level, bars_download(yahoo_bars(["2026-09-10"])), xnys)


# --- 5.2 corporate actions ----------------------------------------------------


def test_yahoo_actions_download_fills_corporate_actions_only(
    spy_etf: Instrument, xnys: TradingCalendar
) -> None:
    raw = yahoo_actions([("2026-06-10", 0.0, 4.0)])
    actions = actions_of(NORMALIZER.normalize(spy_etf, actions_download(raw), xnys))
    assert list(actions.columns) == CORPORATE_ACTIONS_SCHEMA.names


def test_yahoo_actions_split_and_dividend_on_one_day_become_two_rows(
    spy_etf: Instrument, xnys: TradingCalendar
) -> None:
    raw = yahoo_actions([("2026-06-10", 1.74, 4.0)])
    actions = actions_of(NORMALIZER.normalize(spy_etf, actions_download(raw), xnys))
    assert actions["action_type"].tolist() == ["DIVIDEND", "SPLIT"]
    assert actions["value"].tolist() == [1.74, 4.0]
    assert actions["ex_date"].tolist() == [date(2026, 6, 10), date(2026, 6, 10)]


def test_yahoo_actions_zero_means_no_event(spy_etf: Instrument, xnys: TradingCalendar) -> None:
    raw = yahoo_actions([("2026-03-20", 0.0, 0.0), ("2026-06-10", 0.0, 4.0)])
    actions = actions_of(NORMALIZER.normalize(spy_etf, actions_download(raw), xnys))
    assert actions["action_type"].tolist() == ["SPLIT"]
    assert actions["ex_date"].tolist() == [date(2026, 6, 10)]


def test_yahoo_actions_row_without_event_on_a_holiday_is_ignored(
    spy_etf: Instrument, xnys: TradingCalendar
) -> None:
    raw = yahoo_actions([("2026-09-07", 0.0, 0.0)])
    actions = actions_of(NORMALIZER.normalize(spy_etf, actions_download(raw), xnys))
    assert actions.empty


def test_yahoo_actions_are_filtered_to_the_requested_range_before_any_calendar_lookup(
    spy_etf: Instrument, xnys: TradingCalendar
) -> None:
    # 2025 and 2027 lie outside the calendar coverage: filtering first avoids the error.
    raw = yahoo_actions(
        [("2025-12-19", 1.74, 0.0), ("2026-03-20", 1.76, 0.0), ("2027-01-15", 1.80, 0.0)]
    )
    actions = actions_of(NORMALIZER.normalize(spy_etf, actions_download(raw), xnys))
    assert actions["ex_date"].tolist() == [date(2026, 3, 20)]


def test_yahoo_actions_range_bounds_are_inclusive(
    spy_etf: Instrument, xnys: TradingCalendar
) -> None:
    raw = yahoo_actions(
        [("2026-03-19", 1.0, 0.0), ("2026-03-20", 2.0, 0.0), ("2026-03-23", 3.0, 0.0)]
    )
    download = actions_download(raw, start="2026-03-19", end="2026-03-20")
    actions = actions_of(NORMALIZER.normalize(spy_etf, download, xnys))
    assert actions["value"].tolist() == [1.0, 2.0]


def test_yahoo_actions_become_available_at_the_ex_date_open(
    spy_etf: Instrument, xnys: TradingCalendar
) -> None:
    """An action is knowable at the first price it affects, not a session later.

    The raw open of an ex-date is already post-split and ex-dividend. Stamped at
    the close, a 4-for-1 split would show a strategy executing at that open a
    -75% gap that never happened - and this project executes at the open.

    27 November is a half day closing 13:00 ET, and its open is unmoved: the
    early close is exactly the kind of detail an availability anchored on the
    close would drag in for no reason.
    """
    raw = yahoo_actions([("2026-06-10", 0.0, 4.0), ("2026-11-27", 1.5, 0.0)])
    actions = actions_of(NORMALIZER.normalize(spy_etf, actions_download(raw), xnys))
    assert actions["available_at_utc"].tolist() == [
        utc(2026, 6, 10, 13, 30),
        utc(2026, 11, 27, 14, 30),
    ]


def test_yahoo_actions_convert_to_the_arrow_schema_with_lineage(
    spy_etf: Instrument, xnys: TradingCalendar
) -> None:
    raw = yahoo_actions([("2026-06-10", 1.74, 4.0)])
    actions = actions_of(NORMALIZER.normalize(spy_etf, actions_download(raw), xnys))
    table = pa.Table.from_pandas(actions, schema=CORPORATE_ACTIONS_SCHEMA, preserve_index=False)
    assert table.num_rows == 2
    assert set(actions["instrument_id"]) == {"US_SPY"}
    assert set(actions["source"]) == {"YAHOO"}
    assert set(actions["source_fetch_id"]) == {FETCH_ID}


def test_yahoo_actions_empty_frame_gives_an_empty_canonical_frame(
    spy_etf: Instrument, xnys: TradingCalendar
) -> None:
    actions = actions_of(NORMALIZER.normalize(spy_etf, actions_download(pd.DataFrame()), xnys))
    assert actions.empty
    assert list(actions.columns) == CORPORATE_ACTIONS_SCHEMA.names


def test_yahoo_actions_without_event_in_range_give_an_empty_canonical_frame(
    spy_etf: Instrument, xnys: TradingCalendar
) -> None:
    raw = yahoo_actions([("2025-12-19", 1.74, 0.0)])
    actions = actions_of(NORMALIZER.normalize(spy_etf, actions_download(raw), xnys))
    assert actions.empty
    assert list(actions.columns) == CORPORATE_ACTIONS_SCHEMA.names
    table = pa.Table.from_pandas(actions, schema=CORPORATE_ACTIONS_SCHEMA, preserve_index=False)
    assert table.num_rows == 0


def test_yahoo_actions_on_a_closed_ex_date_are_dropped_and_named(
    spy_etf: Instrument, xnys: TradingCalendar
) -> None:
    """No session means no open for the action to be knowable at."""
    raw = yahoo_actions([("2026-09-07", 1.74, 0.0)])

    normalized = NORMALIZER.normalize(spy_etf, actions_download(raw), xnys)

    assert normalized.corporate_actions is not None
    assert normalized.corporate_actions.empty
    assert normalized.rejected.non_session == (date(2026, 9, 7),)


@pytest.mark.parametrize(
    ("dividend", "split", "column"),
    [(-1.0, 0.0, "Dividends"), (0.0, float("nan"), "Stock Splits")],
    ids=["negative-dividend", "missing-split"],
)
def test_yahoo_actions_reject_a_negative_or_missing_value(
    spy_etf: Instrument, xnys: TradingCalendar, dividend: float, split: float, column: str
) -> None:
    raw = yahoo_actions([("2026-06-10", dividend, split)])
    with pytest.raises(ValueError, match=column):
        NORMALIZER.normalize(spy_etf, actions_download(raw), xnys)


def test_yahoo_actions_without_a_split_column_keep_the_dividends(
    spy_etf: Instrument, xnys: TradingCalendar
) -> None:
    # SPY never split, and Yahoo sends its actions with a Dividends column only.
    raw = yahoo_actions([("2026-03-20", 1.74, 0.0), ("2026-06-19", 1.76, 0.0)]).drop(
        columns=["Stock Splits"]
    )
    actions = actions_of(NORMALIZER.normalize(spy_etf, actions_download(raw), xnys))
    assert actions["action_type"].tolist() == ["DIVIDEND", "DIVIDEND"]
    assert actions["value"].tolist() == [1.74, 1.76]


def test_yahoo_actions_without_a_dividend_column_keep_the_splits(
    spy_etf: Instrument, xnys: TradingCalendar
) -> None:
    raw = yahoo_actions([("2026-06-10", 0.0, 4.0)]).drop(columns=["Dividends"])
    actions = actions_of(NORMALIZER.normalize(spy_etf, actions_download(raw), xnys))
    assert actions["action_type"].tolist() == ["SPLIT"]
    assert actions["value"].tolist() == [4.0]


def test_yahoo_actions_without_any_action_column_raise(
    spy_etf: Instrument, xnys: TradingCalendar
) -> None:
    raw = yahoo_actions([("2026-06-10", 1.0, 0.0)]).rename(
        columns={"Dividends": "Capital Gains", "Stock Splits": "Other"}
    )
    with pytest.raises(ValueError, match="none of the columns"):
        NORMALIZER.normalize(spy_etf, actions_download(raw), xnys)


COMMITTED_CALENDARS = Path(__file__).resolve().parents[2] / "market_data" / "metadata" / "calendars"


@pytest.mark.network
def test_yahoo_actions_live_spy_has_no_split_column_and_normalizes(spy_etf: Instrument) -> None:
    xnys = CalendarRegistry.from_directory(COMMITTED_CALENDARS).get("XNYS")
    raw = YahooSource().download_corporate_actions(spy_etf, date(2024, 1, 1), date(2024, 12, 31))
    assert raw is not None
    assert "Stock Splits" not in raw.frame.columns
    actions = actions_of(NORMALIZER.normalize(spy_etf, raw, xnys))
    # Four quarterly ex-dates in 2024, and nothing else.
    assert actions["action_type"].tolist() == ["DIVIDEND"] * 4


@pytest.mark.network
def test_yahoo_actions_live_ge_dividends_survive_a_reverse_split_and_two_spin_offs() -> None:
    xnys = CalendarRegistry.from_directory(COMMITTED_CALENDARS).get("XNYS")
    ge = Instrument(
        id="US_GE",
        name="General Electric",
        asset_type=AssetType.EQUITY,
        data_type=DataType.BAR,
        currency="USD",
        primary_source="YAHOO",
        source_symbol="GE",
        tradable=True,
        calendar_id="XNYS",
    )
    raw = YahooSource().download_corporate_actions(ge, date(2021, 6, 1), date(2022, 12, 31))
    assert raw is not None
    actions = actions_of(NORMALIZER.normalize(ge, raw, xnys))
    paid = {
        ex_date: value
        for ex_date, action_type, value in zip(
            actions["ex_date"], actions["action_type"], actions["value"], strict=True
        )
        if action_type == "DIVIDEND"
    }
    # Yahoo serves 0.049841 for both: divided by 0.125, 1.281 and 1.253 in turn.
    # GE actually paid 1 cent before its 1-for-8 reverse split and 8 cents after it.
    assert paid[date(2021, 6, 25)] == pytest.approx(0.01, rel=1e-3)
    assert paid[date(2022, 12, 14)] == pytest.approx(0.08, rel=1e-3)


def test_yahoo_actions_without_requested_range_raise(
    spy_etf: Instrument, xnys: TradingCalendar
) -> None:
    raw = yahoo_actions([("2026-06-10", 0.0, 4.0)])
    download = RawDownload(
        instrument_id="US_SPY",
        source="YAHOO",
        fetch_id=FETCH_ID,
        retrieved_at_utc=RETRIEVED_AT,
        frame=raw,
        request={"symbol": "SPY", "endpoint": "actions", "period": "max"},
    )
    with pytest.raises(ValueError, match="start"):
        NORMALIZER.normalize(spy_etf, download, xnys)


# --- 5.2 look-ahead guards ----------------------------------------------------


def test_yahoo_bars_a_later_session_does_not_change_earlier_rows(
    spy_etf: Instrument, xnys: TradingCalendar
) -> None:
    baseline_raw = yahoo_bars(["2026-09-10", "2026-09-11"])
    baseline = bars_of(NORMALIZER.normalize(spy_etf, bars_download(baseline_raw), xnys))
    extended_raw = yahoo_bars(["2026-09-10", "2026-09-11", "2026-09-14"])
    extended_raw["Close"] = [105.0, 106.0, 1_000_000.0]
    extended = bars_of(NORMALIZER.normalize(spy_etf, bars_download(extended_raw), xnys))
    pd.testing.assert_frame_equal(extended.head(2), baseline)


def test_yahoo_actions_a_later_event_does_not_change_earlier_rows(
    spy_etf: Instrument, xnys: TradingCalendar
) -> None:
    baseline_raw = yahoo_actions([("2026-06-10", 0.0, 4.0)])
    baseline = actions_of(NORMALIZER.normalize(spy_etf, actions_download(baseline_raw), xnys))
    extended_raw = yahoo_actions([("2026-06-10", 0.0, 4.0), ("2026-12-15", 9.99, 0.0)])
    extended = actions_of(NORMALIZER.normalize(spy_etf, actions_download(extended_raw), xnys))
    pd.testing.assert_frame_equal(extended.head(1), baseline)


# --- Yahoo dividends: served divided by every later split ---------------------


def test_yahoo_dividend_is_multiplied_back_by_a_later_split(
    spy_etf: Instrument, xnys: TradingCalendar
) -> None:
    # AAPL-like: 0.77 paid in March, served as 0.1925 after a 4-for-1 split in June.
    raw = yahoo_actions([("2026-03-20", 0.1925, 0.0), ("2026-06-10", 0.0, 4.0)])
    actions = actions_of(NORMALIZER.normalize(spy_etf, actions_download(raw), xnys))
    assert actions["action_type"].tolist() == ["DIVIDEND", "SPLIT"]
    assert actions["value"].tolist() == pytest.approx([0.77, 4.0])


def test_yahoo_dividend_is_the_same_whichever_side_of_the_split_it_was_fetched(
    spy_etf: Instrument, xnys: TradingCalendar
) -> None:
    fetched_before_split = yahoo_actions([("2026-03-20", 0.77, 0.0)])
    fetched_after_split = yahoo_actions([("2026-03-20", 0.1925, 0.0), ("2026-06-10", 0.0, 4.0)])
    earlier = actions_of(
        NORMALIZER.normalize(
            spy_etf, actions_download(fetched_before_split, end="2026-05-29"), xnys
        )
    )
    later = actions_of(
        NORMALIZER.normalize(spy_etf, actions_download(fetched_after_split, end="2026-05-29"), xnys)
    )
    pd.testing.assert_frame_equal(later, earlier)


def test_yahoo_dividend_is_multiplied_by_every_later_split(
    spy_etf: Instrument, xnys: TradingCalendar
) -> None:
    raw = yahoo_actions(
        [("2026-03-20", 0.25, 0.0), ("2026-06-10", 0.0, 2.0), ("2026-09-10", 0.0, 7.0)]
    )
    actions = actions_of(NORMALIZER.normalize(spy_etf, actions_download(raw), xnys))
    assert actions["value"].tolist()[0] == pytest.approx(3.5)


def test_yahoo_dividend_is_not_scaled_by_an_earlier_or_same_day_split(
    spy_etf: Instrument, xnys: TradingCalendar
) -> None:
    raw = yahoo_actions(
        [("2026-03-20", 0.0, 4.0), ("2026-06-10", 1.5, 2.0), ("2026-09-10", 0.5, 0.0)]
    )
    actions = actions_of(NORMALIZER.normalize(spy_etf, actions_download(raw), xnys))
    dividends = [
        value
        for action_type, value in zip(actions["action_type"], actions["value"], strict=True)
        if action_type == "DIVIDEND"
    ]
    assert dividends == [1.5, 0.5]


def test_yahoo_actions_invalid_value_outside_the_range_still_raises(
    spy_etf: Instrument, xnys: TradingCalendar
) -> None:
    # A later split scales every earlier dividend, so every row must be sound.
    raw = yahoo_actions([("2026-03-20", 1.0, 0.0), ("2026-12-15", 0.0, float("nan"))])
    with pytest.raises(ValueError, match="Stock Splits"):
        NORMALIZER.normalize(spy_etf, actions_download(raw, end="2026-06-30"), xnys)


# --- Euronext bars ------------------------------------------------------------

EURONEXT_NORMALIZER = EuronextNormalizer()

EURONEXT_COLUMNS = [
    "Date",
    "Open",
    "High",
    "Low",
    "Last",
    "Close",
    "Number of Shares",
    "Number of Trades",
    "Turnover",
    "unnamed_9",
]
"""Columns of a raw Euronext download, as the adapter keeps them."""


def euronext_row(
    day: str, open_: str = "570.0", close: str = "571.0", shares: str = "3839"
) -> list[str]:
    """Return one raw Euronext row, every cell a string."""
    return [day, open_, "572.0", "569.0", close, close, shares, "873", "2184331", "568.98"]


def euronext_download(
    rows: list[list[str]], instrument_id: str = "ETF_WORLD", source: str = "EURONEXT"
) -> RawDownload:
    """Wrap raw Euronext rows the way ``EuronextSource.download`` does."""
    return RawDownload(
        instrument_id=instrument_id,
        source=source,
        fetch_id=FETCH_ID,
        retrieved_at_utc=RETRIEVED_AT,
        frame=pd.DataFrame(rows, columns=EURONEXT_COLUMNS),
        request={"isin": "LU1681043599", "mic": "XPAR", "start": "2026-01-01"},
    )


def test_euronext_bars_are_canonical_and_oldest_first(
    cw8: Instrument, xpar: TradingCalendar
) -> None:
    rows = [
        euronext_row("11/09/2026", open_="571.5", close="572.5", shares="13290"),
        euronext_row("10/09/2026", open_="570.0", close="571.0", shares="3839"),
    ]
    bars = bars_of(EURONEXT_NORMALIZER.normalize(cw8, euronext_download(rows), xpar))
    assert list(bars.columns) == BARS_SCHEMA.names
    assert bars["session_date"].tolist() == [date(2026, 9, 10), date(2026, 9, 11)]
    assert bars["open"].tolist() == [570.0, 571.5]
    assert bars["close"].tolist() == [571.0, 572.5]
    assert bars["volume"].tolist() == [3839.0, 13290.0]
    assert set(bars["source"]) == {"EURONEXT"}
    assert set(bars["source_fetch_id"]) == {FETCH_ID}


def test_euronext_bars_availability_follows_paris_summer_and_half_days(
    cw8: Instrument, xpar: TradingCalendar
) -> None:
    rows = [euronext_row("24/12/2026"), euronext_row("10/09/2026")]
    bars = bars_of(EURONEXT_NORMALIZER.normalize(cw8, euronext_download(rows), xpar))
    # 09:00-17:30 CEST in September; 14:05 CET close on Christmas Eve.
    assert bars["open_available_at_utc"].tolist() == [
        utc(2026, 9, 10, 7, 0),
        utc(2026, 12, 24, 8, 0),
    ]
    assert bars["close_available_at_utc"].tolist() == [
        utc(2026, 9, 10, 15, 30),
        utc(2026, 12, 24, 13, 5),
    ]


def test_euronext_bars_empty_cell_is_nan_and_converts_to_the_schema(
    cw8: Instrument, xpar: TradingCalendar
) -> None:
    rows = [euronext_row("10/09/2026", open_="")]
    bars = bars_of(EURONEXT_NORMALIZER.normalize(cw8, euronext_download(rows), xpar))
    assert math.isnan(bars["open"].tolist()[0])
    assert pa.Table.from_pandas(bars, schema=BARS_SCHEMA, preserve_index=False).num_rows == 1


def test_euronext_bars_leave_the_raw_frame_untouched(
    cw8: Instrument, xpar: TradingCalendar
) -> None:
    download = euronext_download([euronext_row("11/09/2026"), euronext_row("10/09/2026")])
    before = download.frame.copy()
    EURONEXT_NORMALIZER.normalize(cw8, download, xpar)
    pd.testing.assert_frame_equal(download.frame, before)


def test_euronext_bars_empty_download_gives_an_empty_canonical_frame(
    cw8: Instrument, xpar: TradingCalendar
) -> None:
    bars = bars_of(EURONEXT_NORMALIZER.normalize(cw8, euronext_download([]), xpar))
    assert bars.empty
    assert list(bars.columns) == BARS_SCHEMA.names


@pytest.mark.parametrize("cell", ["-", "nan", "inf", "570,5"], ids=["dash", "nan", "inf", "comma"])
def test_euronext_bars_reject_a_cell_that_is_not_a_finite_number(
    cw8: Instrument, xpar: TradingCalendar, cell: str
) -> None:
    with pytest.raises(ValueError, match="Open"):
        EURONEXT_NORMALIZER.normalize(
            cw8, euronext_download([euronext_row("10/09/2026", open_=cell)]), xpar
        )


def test_euronext_bars_reject_a_date_that_is_not_day_first(
    cw8: Instrument, xpar: TradingCalendar
) -> None:
    with pytest.raises(ValueError, match="dd/mm/yyyy"):
        EURONEXT_NORMALIZER.normalize(cw8, euronext_download([euronext_row("2026-09-10")]), xpar)


def test_euronext_bars_missing_column_raises(cw8: Instrument, xpar: TradingCalendar) -> None:
    download = euronext_download([euronext_row("10/09/2026")])
    broken = RawDownload(
        instrument_id=download.instrument_id,
        source=download.source,
        fetch_id=download.fetch_id,
        retrieved_at_utc=download.retrieved_at_utc,
        frame=download.frame.drop(columns=["Number of Shares"]),
        request=download.request,
    )
    with pytest.raises(ValueError, match="Number of Shares"):
        EURONEXT_NORMALIZER.normalize(cw8, broken, xpar)


def test_euronext_bars_on_a_holiday_are_dropped_and_named(
    cw8: Instrument, xpar: TradingCalendar
) -> None:
    """Same rule for the exchange's own export, where it should never happen."""
    rows = [euronext_row("07/04/2026"), euronext_row("06/04/2026")]  # Easter Monday

    normalized = EURONEXT_NORMALIZER.normalize(cw8, euronext_download(rows), xpar)

    assert normalized.bars is not None
    assert normalized.bars["session_date"].tolist() == [date(2026, 4, 7)]
    assert normalized.rejected.non_session == (date(2026, 4, 6),)


def test_euronext_bars_repeated_session_raises(cw8: Instrument, xpar: TradingCalendar) -> None:
    rows = [euronext_row("10/09/2026"), euronext_row("10/09/2026")]
    with pytest.raises(ValueError, match="2026-09-10"):
        EURONEXT_NORMALIZER.normalize(cw8, euronext_download(rows), xpar)


def test_euronext_bars_outside_calendar_coverage_raise_a_coverage_error(
    cw8: Instrument, xpar: TradingCalendar
) -> None:
    with pytest.raises(CalendarCoverageError):
        EURONEXT_NORMALIZER.normalize(cw8, euronext_download([euronext_row("31/12/2025")]), xpar)


def test_euronext_normalize_requires_a_calendar_and_its_own_source(
    cw8: Instrument, xpar: TradingCalendar
) -> None:
    download = euronext_download([euronext_row("10/09/2026")])
    with pytest.raises(ValueError, match="calendar"):
        EURONEXT_NORMALIZER.normalize(cw8, download)
    with pytest.raises(ValueError, match="YAHOO"):
        EURONEXT_NORMALIZER.normalize(
            cw8, euronext_download([euronext_row("10/09/2026")], source="YAHOO"), xpar
        )


def test_euronext_bars_a_later_session_does_not_change_earlier_rows(
    cw8: Instrument, xpar: TradingCalendar
) -> None:
    baseline_rows = [euronext_row("11/09/2026"), euronext_row("10/09/2026")]
    baseline = bars_of(EURONEXT_NORMALIZER.normalize(cw8, euronext_download(baseline_rows), xpar))
    extended_rows = [euronext_row("14/09/2026", close="9999.0"), *baseline_rows]
    extended = bars_of(EURONEXT_NORMALIZER.normalize(cw8, euronext_download(extended_rows), xpar))
    pd.testing.assert_frame_equal(extended.head(2), baseline)


def test_yahoo_and_euronext_bars_of_one_session_cross_check_as_confirmed(
    cw8: Instrument, xpar: TradingCalendar
) -> None:
    yahoo_raw = yahoo_bars(["2026-09-10"], timezone="Europe/Paris")
    yahoo = bars_of(
        NORMALIZER.normalize(cw8, bars_download(yahoo_raw, instrument_id="ETF_WORLD"), xpar)
    )
    row = ["10/09/2026", "100.0", "110.0", "90.0", "105.0", "105.0", "1000000", "1", "1", "1"]
    euronext = bars_of(EURONEXT_NORMALIZER.normalize(cw8, euronext_download([row]), xpar))
    policy = CrossCheckPolicy(price_rel_tolerance=1e-6, volume_rel_tolerance=0.0)
    checked = cross_check_bars("ETF_WORLD", {"YAHOO": yahoo, "EURONEXT": euronext}, "YAHOO", policy)
    assert checked["check_status"].tolist() == ["CONFIRMED"]


# --- 5.3 FRED levels ----------------------------------------------------------

FRED_NORMALIZER = FredNormalizer()


@pytest.fixture
def dgs10() -> Instrument:
    """Return the US 10-year yield, published at 16:15 New York the same day."""
    return Instrument(
        id="US10Y",
        name="US 10-year Treasury constant maturity rate",
        asset_type=AssetType.RATE,
        data_type=DataType.LEVEL,
        currency="NA",
        primary_source="FRED",
        source_symbol="DGS10",
        tradable=False,
        publication_rule=PublicationRule(
            publication_time=time(16, 15), timezone="America/New_York"
        ),
    )


def fred_download(
    rows: list[tuple[str, str]],
    value_column: str = "DGS10",
    source: str = "FRED",
    retrieved_at: datetime = RETRIEVED_AT,
) -> RawDownload:
    """Wrap raw ``fredgraph.csv`` rows the way ``FredSource.download`` does."""
    return RawDownload(
        instrument_id="US10Y",
        source=source,
        fetch_id=FETCH_ID,
        retrieved_at_utc=retrieved_at,
        frame=pd.DataFrame(rows, columns=["observation_date", value_column], dtype=str),
        request={"series_id": "DGS10", "start": "2024-12-23", "end_inclusive": "2024-12-27"},
    )


def levels_of(result: NormalizedData) -> pd.DataFrame:
    """Return the levels of a result that must hold levels only."""
    assert result.levels is not None
    assert result.bars is None
    assert result.corporate_actions is None
    return result.levels


CHRISTMAS_2024 = [
    ("2024-12-23", "4.59"),
    ("2024-12-24", "4.59"),
    ("2024-12-25", ""),
    ("2024-12-26", "."),
    ("2024-12-27", "4.62"),
]
"""DGS10 around Christmas 2024: an empty holiday, and a legacy ``"."``."""


def test_fred_levels_drop_missing_observations_instead_of_storing_nan(dgs10: Instrument) -> None:
    levels = levels_of(FRED_NORMALIZER.normalize(dgs10, fred_download(CHRISTMAS_2024)))
    assert list(levels.columns) == LEVELS_SCHEMA.names
    assert levels["observation_date"].tolist() == [
        date(2024, 12, 23),
        date(2024, 12, 24),
        date(2024, 12, 27),
    ]
    assert levels["value"].tolist() == [4.59, 4.59, 4.62]
    assert set(levels["source"]) == {"FRED"}
    assert set(levels["source_fetch_id"]) == {FETCH_ID}


def test_fred_levels_are_available_by_the_publication_rule_in_every_season(
    dgs10: Instrument,
) -> None:
    rows = [("2024-12-23", "4.59"), ("2024-07-01", "4.47")]
    levels = levels_of(FRED_NORMALIZER.normalize(dgs10, fred_download(rows)))
    # Sorted by date; 16:15 New York is 20:15Z in July (EDT), 21:15Z in December (EST).
    assert levels["observation_date"].tolist() == [date(2024, 7, 1), date(2024, 12, 23)]
    assert levels["available_at_utc"].tolist() == [
        utc(2024, 7, 1, 20, 15),
        utc(2024, 12, 23, 21, 15),
    ]


def test_fred_levels_publication_lag_delays_availability(dgs10: Instrument, xnys) -> None:
    """A lag of one session skips Christmas and the weekend behind it.

    24 December 2026 is a session (a half day), the 25th is a holiday and the
    26th and 27th are the weekend, so the value observed on the 24th is public
    on Monday the 28th - not on the 25th, when nothing was published.
    """
    next_session = PublicationRule(
        publication_time=time(16, 15),
        timezone="America/New_York",
        lag_sessions=1,
        calendar_id="XNYS",
    )
    lagged = Instrument(
        id=dgs10.id,
        name=dgs10.name,
        asset_type=dgs10.asset_type,
        data_type=dgs10.data_type,
        currency=dgs10.currency,
        primary_source=dgs10.primary_source,
        source_symbol=dgs10.source_symbol,
        tradable=dgs10.tradable,
        publication_rule=next_session,
    )
    levels = levels_of(
        FRED_NORMALIZER.normalize(lagged, fred_download([("2026-12-24", "4.59")]), xnys)
    )
    assert levels["available_at_utc"].tolist() == [utc(2026, 12, 28, 21, 15)]


def test_fred_levels_convert_to_the_arrow_schema(dgs10: Instrument) -> None:
    levels = levels_of(FRED_NORMALIZER.normalize(dgs10, fred_download(CHRISTMAS_2024)))
    assert pa.Table.from_pandas(levels, schema=LEVELS_SCHEMA, preserve_index=False).num_rows == 3


@pytest.mark.parametrize(
    "rows",
    [[], [("2024-12-25", ""), ("2024-12-26", ".")]],
    ids=["header-only", "only-missing-days"],
)
def test_fred_levels_without_observation_give_an_empty_canonical_frame(
    dgs10: Instrument, rows: list[tuple[str, str]]
) -> None:
    levels = levels_of(FRED_NORMALIZER.normalize(dgs10, fred_download(rows)))
    assert levels.empty
    assert list(levels.columns) == LEVELS_SCHEMA.names


@pytest.mark.parametrize("cell", ["N/A", "nan", "inf", "4,59"], ids=["na", "nan", "inf", "comma"])
def test_fred_levels_reject_a_value_that_is_not_a_finite_number(
    dgs10: Instrument, cell: str
) -> None:
    with pytest.raises(ValueError, match="DGS10"):
        FRED_NORMALIZER.normalize(dgs10, fred_download([("2024-12-23", cell)]))


def test_fred_levels_reject_a_date_that_is_not_iso(dgs10: Instrument) -> None:
    with pytest.raises(ValueError, match="ISO date"):
        FRED_NORMALIZER.normalize(dgs10, fred_download([("23/12/2024", "4.59")]))


def test_fred_levels_reject_a_repeated_date_even_when_missing(dgs10: Instrument) -> None:
    rows = [("2024-12-23", "4.59"), ("2024-12-23", "")]
    with pytest.raises(ValueError, match="repeats"):
        FRED_NORMALIZER.normalize(dgs10, fred_download(rows))


def test_fred_levels_require_the_series_column(dgs10: Instrument) -> None:
    with pytest.raises(ValueError, match="DGS10"):
        FRED_NORMALIZER.normalize(dgs10, fred_download(CHRISTMAS_2024, value_column="DGS2"))


def test_fred_normalize_rejects_a_bar_instrument_and_another_source(
    dgs10: Instrument, spy_etf: Instrument
) -> None:
    bar_download = RawDownload(
        instrument_id="US_SPY",
        source="FRED",
        fetch_id=FETCH_ID,
        retrieved_at_utc=RETRIEVED_AT,
        frame=pd.DataFrame(),
        request={},
    )
    with pytest.raises(ValueError, match="LEVEL"):
        FRED_NORMALIZER.normalize(spy_etf, bar_download)
    with pytest.raises(ValueError, match="ECB"):
        FRED_NORMALIZER.normalize(dgs10, fred_download(CHRISTMAS_2024, source="ECB"))


def test_fred_levels_ignore_any_calendar(dgs10: Instrument, xnys: TradingCalendar) -> None:
    without = levels_of(FRED_NORMALIZER.normalize(dgs10, fred_download(CHRISTMAS_2024)))
    with_calendar = levels_of(FRED_NORMALIZER.normalize(dgs10, fred_download(CHRISTMAS_2024), xnys))
    pd.testing.assert_frame_equal(with_calendar, without)


def test_fred_levels_a_later_observation_does_not_change_earlier_rows(dgs10: Instrument) -> None:
    baseline = levels_of(FRED_NORMALIZER.normalize(dgs10, fred_download(CHRISTMAS_2024)))
    extended_rows = [*CHRISTMAS_2024, ("2024-12-30", "99.0")]
    extended = levels_of(FRED_NORMALIZER.normalize(dgs10, fred_download(extended_rows)))
    pd.testing.assert_frame_equal(extended.head(3), baseline)


# --- 5.4 ECB levels -----------------------------------------------------------

ECB_NORMALIZER = EcbNormalizer()

EURUSD_KEY = "EXR.D.USD.EUR.SP00.A"


@pytest.fixture
def eurusd() -> Instrument:
    """Return the ECB EUR/USD reference rate, published at 16:00 Paris the same day."""
    return Instrument(
        id="ECB_EURUSD",
        name="ECB euro reference exchange rate, USD",
        asset_type=AssetType.FX,
        data_type=DataType.LEVEL,
        currency="USD",
        primary_source="ECB",
        source_symbol=EURUSD_KEY,
        tradable=False,
        publication_rule=PublicationRule(publication_time=time(16, 0), timezone="Europe/Paris"),
    )


def ecb_download(rows: list[tuple[str, str, str]], source: str = "ECB") -> RawDownload:
    """Wrap raw ``csvdata`` rows of ``(KEY, TIME_PERIOD, OBS_VALUE)``."""
    frame = pd.DataFrame(
        [(key, "D", day, value, "A") for key, day, value in rows],
        columns=["KEY", "FREQ", "TIME_PERIOD", "OBS_VALUE", "OBS_STATUS"],
        dtype=str,
    )
    return RawDownload(
        instrument_id="ECB_EURUSD",
        source=source,
        fetch_id=FETCH_ID,
        retrieved_at_utc=RETRIEVED_AT,
        frame=frame,
        request={"flow": "EXR", "series_key": "D.USD.EUR.SP00.A"},
    )


def test_ecb_levels_keep_the_published_quote_without_inverting_it(eurusd: Instrument) -> None:
    rows = [(EURUSD_KEY, "2024-12-24", "1.0395"), (EURUSD_KEY, "2024-12-23", "1.0393")]
    levels = levels_of(ECB_NORMALIZER.normalize(eurusd, ecb_download(rows)))
    assert list(levels.columns) == LEVELS_SCHEMA.names
    assert levels["observation_date"].tolist() == [date(2024, 12, 23), date(2024, 12, 24)]
    # USD per euro, as the ECB publishes it: 1.0393, never 0.9622.
    assert levels["value"].tolist() == [1.0393, 1.0395]
    assert set(levels["source"]) == {"ECB"}


def test_ecb_levels_are_available_at_sixteen_paris_in_every_season(eurusd: Instrument) -> None:
    rows = [(EURUSD_KEY, "2024-12-23", "1.0393"), (EURUSD_KEY, "2024-07-01", "1.0746")]
    levels = levels_of(ECB_NORMALIZER.normalize(eurusd, ecb_download(rows)))
    assert levels["available_at_utc"].tolist() == [
        utc(2024, 7, 1, 14, 0),
        utc(2024, 12, 23, 15, 0),
    ]


def test_ecb_levels_drop_missing_observations(eurusd: Instrument) -> None:
    rows = [
        (EURUSD_KEY, "2024-12-23", "1.0393"),
        (EURUSD_KEY, "2024-12-24", ""),
        (EURUSD_KEY, "2024-12-27", "NaN"),
    ]
    levels = levels_of(ECB_NORMALIZER.normalize(eurusd, ecb_download(rows)))
    assert levels["observation_date"].tolist() == [date(2024, 12, 23)]


def test_ecb_levels_convert_to_the_arrow_schema(eurusd: Instrument) -> None:
    rows = [(EURUSD_KEY, "2024-12-23", "1.0393"), (EURUSD_KEY, "2024-12-24", "1.0395")]
    levels = levels_of(ECB_NORMALIZER.normalize(eurusd, ecb_download(rows)))
    assert pa.Table.from_pandas(levels, schema=LEVELS_SCHEMA, preserve_index=False).num_rows == 2


def test_ecb_levels_empty_answer_gives_an_empty_canonical_frame(eurusd: Instrument) -> None:
    # A weekend: the ECB answers with an empty body, which the adapter keeps column-less.
    empty = RawDownload(
        instrument_id="ECB_EURUSD",
        source="ECB",
        fetch_id=FETCH_ID,
        retrieved_at_utc=RETRIEVED_AT,
        frame=pd.DataFrame(),
        request={},
    )
    levels = levels_of(ECB_NORMALIZER.normalize(eurusd, empty))
    assert levels.empty
    assert list(levels.columns) == LEVELS_SCHEMA.names


def test_ecb_levels_reject_another_series(eurusd: Instrument) -> None:
    rows = [(EURUSD_KEY, "2024-12-23", "1.0393"), ("EXR.D.GBP.EUR.SP00.A", "2024-12-23", "0.83")]
    with pytest.raises(ValueError, match=r"EXR\.D\.GBP\.EUR\.SP00\.A"):
        ECB_NORMALIZER.normalize(eurusd, ecb_download(rows))


@pytest.mark.parametrize(
    ("rows", "match"),
    [
        ([(EURUSD_KEY, "2024-12-23", "1,0393")], "OBS_VALUE"),
        ([(EURUSD_KEY, "23/12/2024", "1.0393")], "ISO date"),
        ([(EURUSD_KEY, "2024-12-23", "1.0393"), (EURUSD_KEY, "2024-12-23", "1.0400")], "repeats"),
    ],
    ids=["comma-decimal", "day-first-date", "repeated-date"],
)
def test_ecb_levels_reject_a_malformed_row(
    eurusd: Instrument, rows: list[tuple[str, str, str]], match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        ECB_NORMALIZER.normalize(eurusd, ecb_download(rows))


def test_ecb_levels_require_the_value_column(eurusd: Instrument) -> None:
    download = ecb_download([(EURUSD_KEY, "2024-12-23", "1.0393")])
    broken = RawDownload(
        instrument_id=download.instrument_id,
        source=download.source,
        fetch_id=download.fetch_id,
        retrieved_at_utc=download.retrieved_at_utc,
        frame=download.frame.drop(columns=["OBS_VALUE"]),
        request=download.request,
    )
    with pytest.raises(ValueError, match="OBS_VALUE"):
        ECB_NORMALIZER.normalize(eurusd, broken)


def test_ecb_normalize_rejects_another_source(eurusd: Instrument) -> None:
    with pytest.raises(ValueError, match="FRED"):
        ECB_NORMALIZER.normalize(eurusd, ecb_download([], source="FRED"))


# --- 5.5 get_normalizer -------------------------------------------------------


@pytest.mark.parametrize(
    ("source_id", "expected_type"),
    [
        ("YAHOO", YahooNormalizer),
        ("EURONEXT", EuronextNormalizer),
        ("FRED", FredNormalizer),
        ("ECB", EcbNormalizer),
    ],
)
def test_get_normalizer_returns_the_normalizer_of_each_source(
    source_id: str, expected_type: type
) -> None:
    normalizer = get_normalizer(source_id)
    assert isinstance(normalizer, expected_type)
    assert normalizer.source_id == source_id


def test_get_normalizer_returns_the_same_stateless_instance() -> None:
    assert get_normalizer("FRED") is get_normalizer("FRED")


def test_get_normalizer_of_an_unknown_source_lists_the_known_ones() -> None:
    with pytest.raises(KeyError, match="EURONEXT") as raised:
        get_normalizer("STOOQ")
    assert "STOOQ" in str(raised.value)


def test_every_source_of_the_committed_registry_has_a_normalizer() -> None:
    committed = (
        Path(__file__).resolve().parents[2] / "market_data" / "metadata" / "instruments.toml"
    )
    sources = {
        source
        for instrument in InstrumentRegistry.from_toml(committed)
        for source in instrument.sources
    }
    assert sources <= set(NORMALIZERS)
    assert "EURONEXT" in sources


# --- Rows a normalizer refuses to store ---------------------------------------
#
# Three reasons, all of them a drop plus a name, never a silent keep: outside
# the listing window, on a day the venue was shut, or not yet public when the
# fetch ran. The last one is what froze an intraday SP500 bar on 18 September
# 2026, and it is the one the replay of an archive has to keep applying.


def test_a_bar_of_a_session_still_running_is_dropped_and_named(
    spy_etf: Instrument, xnys: TradingCalendar
) -> None:
    """New York closes at 20:00 UTC in September; at 17:00 the bar is provisional."""
    download = bars_download(
        yahoo_bars(["2026-09-09", "2026-09-10"]), retrieved_at=utc(2026, 9, 10, 17, 0)
    )

    normalized = NORMALIZER.normalize(spy_etf, download, xnys)

    assert normalized.bars is not None
    assert normalized.bars["session_date"].tolist() == [date(2026, 9, 9)]
    assert normalized.rejected.unpublished == (date(2026, 9, 10),)


def test_a_bar_is_kept_from_the_closing_auction_on(
    spy_etf: Instrument, xnys: TradingCalendar
) -> None:
    """The close is available at the close, here as everywhere else."""
    download = bars_download(yahoo_bars(["2026-09-10"]), retrieved_at=utc(2026, 9, 10, 20, 0))

    normalized = NORMALIZER.normalize(spy_etf, download, xnys)

    assert normalized.bars is not None
    assert normalized.bars["session_date"].tolist() == [date(2026, 9, 10)]
    assert not normalized.rejected


def test_a_bar_before_the_listing_window_is_dropped_and_named(
    spy_etf: Instrument, xnys: TradingCalendar
) -> None:
    """A provider serves a value before a fund lists; the market never made it.

    Yahoo gives CW8 74 flat net asset values from 2018-01-02 to 2018-04-17,
    before it traded. Stored as bars they are prices nobody could have got.
    """
    listed = replace(spy_etf, first_session=date(2026, 9, 10))
    download = bars_download(yahoo_bars(["2026-09-09", "2026-09-10"]))

    normalized = NORMALIZER.normalize(listed, download, xnys)

    assert normalized.bars is not None
    assert normalized.bars["session_date"].tolist() == [date(2026, 9, 10)]
    assert normalized.rejected.unlisted == (date(2026, 9, 9),)


def test_a_level_not_yet_released_is_dropped_and_named(dgs10: Instrument) -> None:
    """DGS10 is published at 16:15 New York: at 15:00 the file may already show it."""
    download = fred_download(
        [("2026-09-09", "4.10"), ("2026-09-10", "4.12")],
        retrieved_at=utc(2026, 9, 10, 19, 0),
    )

    normalized = FRED_NORMALIZER.normalize(dgs10, download)

    assert levels_of(normalized)["observation_date"].tolist() == [date(2026, 9, 9)]
    assert normalized.rejected.unpublished == (date(2026, 9, 10),)


def test_a_level_before_the_listing_window_is_dropped_and_named(dgs10: Instrument) -> None:
    """A series that did not exist yet cannot have been published either."""
    listed = replace(dgs10, first_session=date(2026, 9, 10))
    download = fred_download([("2026-09-09", "4.10"), ("2026-09-10", "4.12")])

    normalized = FRED_NORMALIZER.normalize(listed, download)

    assert levels_of(normalized)["observation_date"].tolist() == [date(2026, 9, 10)]
    assert normalized.rejected.unlisted == (date(2026, 9, 9),)


def test_an_action_not_yet_effective_is_dropped_and_named(
    spy_etf: Instrument, xnys: TradingCalendar
) -> None:
    """An announced dividend is not an event a decision may adjust prices for."""
    download = actions_download(
        yahoo_actions([("2026-09-10", 1.5, 0.0)]), start="2026-01-01", end="2026-12-31"
    )
    download = replace(download, retrieved_at_utc=utc(2026, 9, 9, 21, 0))

    normalized = NORMALIZER.normalize(spy_etf, download, xnys)

    assert normalized.corporate_actions is not None
    assert normalized.corporate_actions.empty
    assert normalized.rejected.unpublished == (date(2026, 9, 10),)


# --- ALFRED: the same file, with the vintage in the column name ---------------

ALFRED_NORMALIZER = AlfredNormalizer()


@pytest.fixture
def gdp() -> Instrument:
    """Return US GDP pinned to the vintage of 31 January 2020."""
    return Instrument(
        id="US_GDP",
        name="US gross domestic product",
        asset_type=AssetType.RATE,
        data_type=DataType.LEVEL,
        currency="NA",
        primary_source="ALFRED",
        source_symbol="GDP",
        tradable=False,
        publication_rule=PublicationRule(publication_time=time(8, 30), timezone="America/New_York"),
        vintage_date=date(2020, 1, 31),
    )


def alfred_download(rows: list[tuple[str, str]], value_column: str = "GDP_20200131") -> RawDownload:
    """Wrap raw ``alfredgraph.csv`` rows the way ``AlfredSource.download`` does."""
    return RawDownload(
        instrument_id="US_GDP",
        source="ALFRED",
        fetch_id=FETCH_ID,
        retrieved_at_utc=RETRIEVED_AT,
        frame=pd.DataFrame(rows, columns=["observation_date", value_column], dtype=str),
        request={"series_id": "GDP", "vintage_date": "2020-01-31"},
    )


def test_alfred_levels_are_read_from_the_vintage_column(gdp: Instrument) -> None:
    """The column carries the vintage, because one export can hold several."""
    download = alfred_download([("2019-01-01", "21098.827"), ("2019-04-01", "21340.267")])

    levels = levels_of(ALFRED_NORMALIZER.normalize(gdp, download))

    assert levels["observation_date"].tolist() == [date(2019, 1, 1), date(2019, 4, 1)]
    assert levels["value"].tolist() == [21098.827, 21340.267]
    assert levels["source"].tolist() == ["ALFRED", "ALFRED"]


def test_alfred_levels_refuse_another_vintage_than_the_one_declared(gdp: Instrument) -> None:
    """A raw archive that does not say what it holds is not an archive.

    The file is the June 2021 vintage and the instrument is pinned to January
    2020. Read leniently - "take whichever value column is there" - the run
    would silently use numbers from a restatement nobody declared.
    """
    download = alfred_download([("2019-01-01", "21115.309")], value_column="GDP_20210630")

    with pytest.raises(ValueError, match="GDP_20200131"):
        ALFRED_NORMALIZER.normalize(gdp, download)


def test_alfred_levels_refuse_a_series_with_no_vintage(gdp: Instrument) -> None:
    """Without one there is nothing to read the column name from."""
    unpinned = replace(gdp, vintage_date=None)
    download = alfred_download([("2019-01-01", "21098.827")])

    with pytest.raises(ValueError, match="declares no vintage_date"):
        ALFRED_NORMALIZER.normalize(unpinned, download)


def test_alfred_levels_of_an_empty_vintage_are_empty(gdp: Instrument) -> None:
    """A vintage older than the series: nothing had been published yet."""
    download = alfred_download([])

    levels = levels_of(ALFRED_NORMALIZER.normalize(gdp, download))

    assert levels.empty
