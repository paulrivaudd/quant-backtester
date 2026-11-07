from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta

import pandas as pd
import pyarrow as pa
import pytest

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
