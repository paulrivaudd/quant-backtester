from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta

import pandas as pd
import pyarrow as pa
import pytest

from quant_backtester.data.calendars import TradingCalendar
from quant_backtester.data.instruments import AssetType, DataType, Instrument, PublicationRule
from quant_backtester.data.normalizer import SsgaNavNormalizer, get_normalizer
from quant_backtester.data.schemas import LEVELS_SCHEMA
from quant_backtester.data.sources.base import RawDownload
from quant_backtester.data.sources.ssga_nav import SsgaNavSource
from quant_backtester.data.validator import validate_levels


@pytest.fixture
def instrument():
    return Instrument(
        id="NAV",
        name="NAV",
        asset_type=AssetType.ETF,
        data_type=DataType.LEVEL,
        currency="USD",
        primary_source="SSGA_NAV",
        source_symbol="IE00BKWQ0D84:zpde-gy",
        tradable=False,
        publication_rule=PublicationRule(
            publication_time=time(0),
            timezone="UTC",
            not_before_utc=datetime(2026, 11, 7, 12, tzinfo=UTC),
        ),
    )


@pytest.fixture
def download():
    return RawDownload(
        "NAV",
        "SSGA_NAV",
        "fetch",
        datetime(2026, 11, 7, 12, tzinfo=UTC),
        pd.DataFrame(
            {
                "Date": ["06-Nov-2026", "05-Nov-2026", "04-Nov-2026"],
                "NAV": ["103", "102", "101"],
                "Shares Outstanding": ["1"] * 3,
                "Total Net Assets": ["1"] * 3,
            }
        ),
        {
            "isin": "IE00BKWQ0D84",
            "currency": "USD",
            "report_date": "2026-11-06",
            "start": "2026-11-05",
            "end_inclusive": "2026-11-06",
        },
    )


def test_retrieval_only_availability_schema_range_and_lineage(instrument, download):
    normalizer = get_normalizer("SSGA_NAV")
    assert isinstance(normalizer, SsgaNavNormalizer)
    result = normalizer.normalize(instrument, download)
    assert result.bars is result.corporate_actions is result.vintages is None
    levels = result.levels
    assert levels is not None
    assert levels.columns.tolist() == LEVELS_SCHEMA.names
    assert levels.observation_date.tolist() == [date(2026, 11, 5), date(2026, 11, 6)]
    assert levels.value.tolist() == [102.0, 103.0]
    assert levels.source.tolist() == ["SSGA_NAV"] * 2
    assert levels.source_fetch_id.tolist() == ["fetch"] * 2
    assert (levels.available_at_utc == download.retrieved_at_utc).all()
    before_fetch = download.retrieved_at_utc - timedelta(microseconds=1)
    assert not (levels.available_at_utc <= before_fetch).any()
    pa.Table.from_pandas(levels, schema=LEVELS_SCHEMA, preserve_index=False).validate(full=True)
    pd.testing.assert_frame_equal(levels, normalizer.normalize(instrument, download).levels)


@pytest.mark.parametrize(
    "metadata",
    [
        {"isin": "other"},
        {"currency": "EUR"},
        {"report_date": "2026-11-08"},
        {"start": "2026-11-07"},
        {"end_inclusive": None},
    ],
)
def test_rejects_bad_metadata(instrument, download, metadata):
    with pytest.raises(ValueError):
        SsgaNavNormalizer().normalize(
            instrument, replace(download, request=download.request | metadata)
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"source": "YAHOO"},
        {"instrument_id": "OTHER"},
        {"retrieved_at_utc": datetime(2026, 11, 7)},
    ],
)
def test_rejects_wrong_download(instrument, download, changes):
    with pytest.raises(ValueError):
        SsgaNavNormalizer().normalize(instrument, replace(download, **changes))


@pytest.mark.parametrize("changes", [{"currency": "EUR"}, {"tradable": True}])
def test_rejects_wrong_instrument(instrument, download, changes):
    with pytest.raises(ValueError):
        SsgaNavNormalizer().normalize(replace(instrument, **changes), download)


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("Date", "08-Nov-2026"),
        ("Date", "05-Nov-2026"),
        ("NAV", "0"),
        ("NAV", "NaN"),
        ("NAV", "inf"),
        ("NAV", "bad"),
    ],
)
def test_rejects_bad_rows_even_outside_requested_range(instrument, download, column, value):
    frame = download.frame.copy()
    frame.loc[2, column] = value
    with pytest.raises(ValueError):
        SsgaNavNormalizer().normalize(instrument, replace(download, frame=frame))


def test_rejects_extra_columns(instrument, download):
    with pytest.raises(ValueError, match="schema"):
        SsgaNavNormalizer().normalize(
            instrument, replace(download, frame=download.frame.assign(Close=1))
        )


def test_empty_range_keeps_schema(instrument, download):
    raw = replace(
        download, request=download.request | {"start": "2026-11-07", "end_inclusive": "2026-11-07"}
    )
    levels = SsgaNavNormalizer().normalize(instrument, raw).levels
    assert levels is not None
    assert levels.empty
    assert levels.columns.tolist() == LEVELS_SCHEMA.names


def test_source_download_to_normalizer(instrument):
    from tests.data.sources.test_ssga_nav import workbook

    now = datetime(2026, 11, 7, 12, tzinfo=UTC)
    source = SsgaNavSource(clock=lambda: now, fetch_bytes=lambda _: workbook())
    raw = source.download(instrument, date(2026, 11, 5), date(2026, 11, 6))
    assert raw.request["historical_publication"] == "UNKNOWN"
    assert source.download_corporate_actions(instrument, date.min, date.max) is None
    result = SsgaNavNormalizer().normalize(instrument, raw)
    assert result.levels is not None
    assert result.levels.value.tolist() == [101.25]
    assert result.levels.available_at_utc.tolist() == [now]


def test_pinned_floor_passes_validator_and_earlier_availability_fails(instrument, download):
    levels = SsgaNavNormalizer().normalize(instrument, download).levels
    assert levels is not None
    assert validate_levels(instrument, levels).valid
    early = levels.copy()
    early["available_at_utc"] -= timedelta(microseconds=1)
    report = validate_levels(instrument, early)
    assert not report.valid
    assert "AVAILABILITY_MISMATCH" in {issue.code for issue in report.issues}


@pytest.mark.parametrize("floor", [None, datetime(2026, 11, 6, tzinfo=UTC)])
def test_nav_requires_exact_retrieval_floor(instrument, download, floor):
    rule = replace(instrument.publication_rule, not_before_utc=floor)
    with pytest.raises(ValueError, match="not_before_utc"):
        SsgaNavNormalizer().normalize(replace(instrument, publication_rule=rule), download)


def test_later_schedule_is_unavailable_at_fetch(instrument, download):
    rule = replace(instrument.publication_rule, publication_time=time(23))
    raw = replace(
        download,
        frame=download.frame.iloc[:1].assign(Date="07-Nov-2026"),
        request=download.request | {"report_date": "2026-11-07", "end_inclusive": "2026-11-07"},
    )
    result = SsgaNavNormalizer().normalize(replace(instrument, publication_rule=rule), raw)
    assert result.levels is not None
    assert result.levels.empty
    assert result.rejected.unpublished == (date(2026, 11, 7),)


def _uk_calendar() -> TradingCalendar:
    """Return a London calendar on which 2026-11-06 (a Friday) is followed by 2026-11-09."""
    return TradingCalendar(
        calendar_id="XLON",
        timezone="Europe/London",
        regular_open=time(8),
        regular_close=time(16, 30),
        holidays=frozenset(),
        early_closes={},
        covered_from=date(2026, 11, 1),
        covered_until=date(2026, 11, 30),
    )


def _declared(instrument: Instrument) -> Instrument:
    """Return the instrument under SA17's declared rule: 23:00 Paris, one XLON session later."""
    rule = PublicationRule(
        publication_time=time(23),
        timezone="Europe/Paris",
        lag_sessions=1,
        calendar_id="XLON",
    )
    return replace(instrument, publication_rule=rule)


def test_declared_release_stamps_next_uk_business_day_at_23_paris(instrument, download):
    later = replace(download, retrieved_at_utc=datetime(2026, 11, 12, tzinfo=UTC))
    calendar = _uk_calendar()
    declared = _declared(instrument)
    result = SsgaNavNormalizer(declared_release=True).normalize(declared, later, calendar)
    levels = result.levels
    assert levels is not None
    assert levels.observation_date.tolist() == [date(2026, 11, 5), date(2026, 11, 6)]
    # Thursday's NAV on Friday 23:00 Paris (22:00 UTC); Friday's on Monday.
    assert levels.available_at_utc.tolist() == [
        pd.Timestamp("2026-11-06T22:00:00Z"),
        pd.Timestamp("2026-11-09T22:00:00Z"),
    ]
    assert validate_levels(declared, levels, calendar).valid


def test_declared_release_is_still_refused_before_it_happens(instrument, download):
    # Fetched on Friday at noon: Friday's NAV is due on Monday, Thursday's tonight.
    friday_noon = replace(download, retrieved_at_utc=datetime(2026, 11, 6, 12, tzinfo=UTC))
    result = SsgaNavNormalizer(declared_release=True).normalize(
        _declared(instrument), friday_noon, _uk_calendar()
    )
    assert result.levels is not None
    assert result.levels.empty
    assert result.rejected.unpublished == (date(2026, 11, 5), date(2026, 11, 6))


@pytest.mark.parametrize(
    "changes",
    [
        {"not_before_utc": datetime(2026, 11, 7, 12, tzinfo=UTC)},
        {"lag_sessions": 0, "calendar_id": None},
    ],
)
def test_declared_release_needs_a_lag_and_no_floor(instrument, download, changes):
    declared = _declared(instrument)
    assert declared.publication_rule is not None
    rule = replace(declared.publication_rule, **changes)
    with pytest.raises(ValueError, match="declared SSGA NAV release"):
        SsgaNavNormalizer(declared_release=True).normalize(
            replace(declared, publication_rule=rule), download, _uk_calendar()
        )


def test_the_registered_normalizer_never_accepts_a_declared_rule(instrument, download):
    with pytest.raises(ValueError, match="not_before_utc"):
        get_normalizer("SSGA_NAV").normalize(_declared(instrument), download, _uk_calendar())
    registered = get_normalizer("SSGA_NAV")
    assert isinstance(registered, SsgaNavNormalizer)
    assert registered.declared_release is False


def test_declared_release_flag_must_be_a_bool():
    with pytest.raises(ValueError, match="bool"):
        SsgaNavNormalizer(declared_release=1)  # type: ignore[arg-type]
