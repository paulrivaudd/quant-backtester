"""Tests of the normalizer of the Dukascopy US-close rate table."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, time

import pandas as pd
import pytest

from quant_backtester.data.instruments import AssetType, DataType, Instrument, PublicationRule
from quant_backtester.data.normalizer import DukascopyUsCloseNormalizer, get_normalizer
from quant_backtester.data.schemas import LEVELS_SCHEMA
from quant_backtester.data.sources.base import RawDownload
from quant_backtester.data.validator import validate_levels


@pytest.fixture
def instrument() -> Instrument:
    return Instrument(
        id="FX",
        name="EUR/USD at the US close",
        asset_type=AssetType.FX,
        data_type=DataType.LEVEL,
        currency="USD",
        primary_source="DUKASCOPY",
        source_symbol="EURUSD",
        tradable=False,
        publication_rule=PublicationRule(publication_time=time(16), timezone="America/New_York"),
    )


def table() -> pd.DataFrame:
    """Two sessions: a full day (16:00 New York, 21:00 UTC) and a half day (13:00, 18:00 UTC)."""
    return pd.DataFrame(
        {
            "observation_date": [date(2025, 11, 26), date(2025, 11, 28)],
            "instant_utc": [
                pd.Timestamp("2025-11-26T21:00:00Z"),
                pd.Timestamp("2025-11-28T18:00:00Z"),
            ],
            "usd_per_eur": [1.15995, 1.16005],
            "bid": [1.1599, 1.1600],
            "ask": [1.1600, 1.1601],
            "bar_end_utc": [
                pd.Timestamp("2025-11-26T21:00:00Z"),
                pd.Timestamp("2025-11-28T18:00:00Z"),
            ],
        }
    )


@pytest.fixture
def download() -> RawDownload:
    return RawDownload(
        "FX",
        "DUKASCOPY",
        "20261108T120000Z",
        datetime(2026, 11, 8, 12, tzinfo=UTC),
        table(),
        {"pair": "EURUSD", "quote": "USD_PER_EUR"},
    )


def test_rates_are_kept_as_quoted_and_released_at_the_rule(instrument, download):
    result = DukascopyUsCloseNormalizer().normalize(instrument, download)
    levels = result.levels
    assert levels is not None
    assert levels.columns.tolist() == LEVELS_SCHEMA.names
    assert levels.observation_date.tolist() == [date(2025, 11, 26), date(2025, 11, 28)]
    assert levels.value.tolist() == [1.15995, 1.16005]
    # 16:00 New York is 21:00 UTC in November, half day included.
    assert levels.available_at_utc.tolist() == [
        pd.Timestamp("2025-11-26T21:00:00Z"),
        pd.Timestamp("2025-11-28T21:00:00Z"),
    ]
    assert validate_levels(instrument, levels).valid


def test_a_rate_after_the_fetch_is_not_published(instrument, download):
    early = replace(download, retrieved_at_utc=datetime(2025, 11, 27, tzinfo=UTC))
    result = DukascopyUsCloseNormalizer().normalize(instrument, early)
    assert result.levels is not None
    assert result.levels.observation_date.tolist() == [date(2025, 11, 26)]
    assert result.rejected.unpublished == (date(2025, 11, 28),)


def test_an_empty_table_keeps_the_schema(instrument, download):
    empty = replace(download, frame=table().iloc[:0])
    levels = DukascopyUsCloseNormalizer().normalize(instrument, empty).levels
    assert levels is not None
    assert levels.empty
    assert levels.columns.tolist() == LEVELS_SCHEMA.names


@pytest.mark.parametrize(
    ("column", "value", "message"),
    [
        ("usd_per_eur", 1.1601, "mid"),
        ("ask", 1.1598, "not a quote"),
        ("bid", 0.0, "not a quote"),
        ("bid", float("nan"), "bid"),
        ("bar_end_utc", pd.Timestamp("2025-11-26T21:01:00Z"), "after"),
        ("instant_utc", pd.Timestamp("2025-11-27T06:00:00Z"), "another day"),
    ],
)
def test_refuses_a_row_that_is_not_a_quote_at_its_close(
    instrument, download, column, value, message
):
    frame = table()
    frame[column] = frame[column].astype(object)
    frame.loc[0, column] = value
    if column == "instant_utc":
        frame.loc[0, "bar_end_utc"] = value
    with pytest.raises(ValueError, match=message):
        DukascopyUsCloseNormalizer().normalize(instrument, replace(download, frame=frame))


def test_refuses_a_rule_releasing_a_rate_before_it_was_seen(instrument, download):
    rule = replace(instrument.publication_rule, publication_time=time(15, 59))
    with pytest.raises(ValueError, match="before"):
        DukascopyUsCloseNormalizer().normalize(replace(instrument, publication_rule=rule), download)


def test_refuses_repeated_dates_and_changed_schema(instrument, download):
    repeated = pd.concat([table().iloc[:1], table().iloc[:1]], ignore_index=True)
    with pytest.raises(ValueError, match="repeats"):
        DukascopyUsCloseNormalizer().normalize(instrument, replace(download, frame=repeated))
    with pytest.raises(ValueError, match="schema"):
        DukascopyUsCloseNormalizer().normalize(
            instrument, replace(download, frame=table().assign(extra=1))
        )


@pytest.mark.parametrize(
    "changes",
    [{"asset_type": AssetType.ETF}, {"tradable": True}, {"currency": "EUR"}],
)
def test_refuses_another_instrument(instrument, download, changes):
    with pytest.raises(ValueError, match="USD-per-EUR"):
        DukascopyUsCloseNormalizer().normalize(replace(instrument, **changes), download)


@pytest.mark.parametrize("request_", [{"pair": "GBPUSD"}, {"quote": "EUR_PER_USD"}])
def test_refuses_another_series(instrument, download, request_):
    raw = replace(download, request=download.request | request_)
    with pytest.raises(ValueError, match="USD-per-EUR"):
        DukascopyUsCloseNormalizer().normalize(instrument, raw)


def test_refuses_another_source(instrument, download):
    with pytest.raises(ValueError):
        DukascopyUsCloseNormalizer().normalize(instrument, replace(download, source="ECB"))


def test_it_is_not_registered_since_no_live_adapter_serves_the_table() -> None:
    with pytest.raises(KeyError):
        get_normalizer("DUKASCOPY")
