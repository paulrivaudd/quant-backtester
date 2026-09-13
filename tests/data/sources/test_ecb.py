"""ECB adapter: the URL sent and the SDMX CSV kept exactly as published.

The HTTP GET is injected, so the routine tests are offline and never read the
wall clock. The ``network`` tests check the live endpoint: a range with a TARGET
holiday, a weekend and an unknown series.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time
from email.message import Message
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import pandas as pd
import pytest

from quant_backtester.data.instruments import AssetType, DataType, Instrument, PublicationRule
from quant_backtester.data.sources.ecb import EcbSource, split_ecb_symbol

RETRIEVED_AT = datetime(2026, 9, 12, 21, 3, 11, tzinfo=UTC)

EURUSD_CHRISTMAS_2024 = (
    "KEY,FREQ,CURRENCY,CURRENCY_DENOM,EXR_TYPE,EXR_SUFFIX,TIME_PERIOD,OBS_VALUE,"
    "OBS_STATUS,TITLE_COMPL\n"
    'EXR.D.USD.EUR.SP00.A,D,USD,EUR,SP00,A,2024-12-23,1.0393,A,"ECB reference, US dollar/Euro"\n'
    'EXR.D.USD.EUR.SP00.A,D,USD,EUR,SP00,A,2024-12-24,1.0395,A,"ECB reference, US dollar/Euro"\n'
    'EXR.D.USD.EUR.SP00.A,D,USD,EUR,SP00,A,2024-12-27,1.0435,A,"ECB reference, US dollar/Euro"\n'
)
"""ECB answer for USD, 23-27 December 2024, trimmed to ten of its 32 columns.

25 and 26 December are TARGET holidays: they have no row. ``TITLE_COMPL`` holds a
quoted comma, as the real answer does.
"""


@dataclass
class FakeHttp:
    """Stand-in for the HTTP GET: records requested URLs, returns a fixed body."""

    body: str
    urls: list[str] = field(default_factory=list)

    def get(self, url: str) -> str:
        """Record ``url`` and return the fixed body."""
        self.urls.append(url)
        return self.body


@pytest.fixture
def http() -> FakeHttp:
    """Return a fake HTTP GET answering with the Christmas 2024 EUR/USD extract."""
    return FakeHttp(body=EURUSD_CHRISTMAS_2024)


@pytest.fixture
def eurusd() -> Instrument:
    """Return the ECB EUR/USD reference rate, as declared in ``instruments.toml``."""
    return Instrument(
        id="ECB_EURUSD",
        name="ECB euro reference exchange rate, USD",
        asset_type=AssetType.FX,
        data_type=DataType.LEVEL,
        currency="USD",
        primary_source="ECB",
        source_symbol="EXR.D.USD.EUR.SP00.A",
        tradable=False,
        publication_rule=PublicationRule(publication_time=time(16, 0), timezone="Europe/Paris"),
    )


@pytest.fixture
def source(http: FakeHttp) -> EcbSource:
    """Return an adapter with a fixed clock and the fake HTTP GET."""
    return EcbSource(clock=lambda: RETRIEVED_AT, fetch_text=http.get)


def only_url(http: FakeHttp) -> str:
    assert len(http.urls) == 1
    return http.urls[0]


def test_split_ecb_symbol_separates_dataflow_and_series_key() -> None:
    assert split_ecb_symbol("EXR.D.USD.EUR.SP00.A") == ("EXR", "D.USD.EUR.SP00.A")


@pytest.mark.parametrize(
    "symbol",
    ["EXR", ".D.USD.EUR.SP00.A", "EXR.", ""],
    ids=["no-dot", "no-dataflow", "no-series-key", "empty"],
)
def test_split_ecb_symbol_rejects_a_missing_part(symbol: str) -> None:
    with pytest.raises(ValueError):
        split_ecb_symbol(symbol)


def test_download_calls_the_dataflow_and_series_key_path(
    http: FakeHttp, eurusd: Instrument, source: EcbSource
) -> None:
    source.download(eurusd, date(2024, 12, 23), date(2024, 12, 27))
    parts = urlsplit(only_url(http))
    assert (parts.scheme, parts.netloc, parts.path) == (
        "https",
        "data-api.ecb.europa.eu",
        "/service/data/EXR/D.USD.EUR.SP00.A",
    )


def test_download_sends_both_bounds_unshifted_and_asks_for_csv(
    http: FakeHttp, eurusd: Instrument, source: EcbSource
) -> None:
    source.download(eurusd, date(2024, 12, 23), date(2024, 12, 27))
    assert parse_qs(urlsplit(only_url(http)).query) == {
        "startPeriod": ["2024-12-23"],
        "endPeriod": ["2024-12-27"],
        "format": ["csvdata"],
    }


def test_download_single_day_range_sends_the_same_day_twice(
    http: FakeHttp, eurusd: Instrument, source: EcbSource
) -> None:
    source.download(eurusd, date(2024, 12, 24), date(2024, 12, 24))
    query = parse_qs(urlsplit(only_url(http)).query)
    assert query["startPeriod"] == query["endPeriod"] == ["2024-12-24"]


def test_download_keeps_the_original_sdmx_columns(eurusd: Instrument, source: EcbSource) -> None:
    result = source.download(eurusd, date(2024, 12, 23), date(2024, 12, 27))
    assert list(result.frame.columns) == [
        "KEY",
        "FREQ",
        "CURRENCY",
        "CURRENCY_DENOM",
        "EXR_TYPE",
        "EXR_SUFFIX",
        "TIME_PERIOD",
        "OBS_VALUE",
        "OBS_STATUS",
        "TITLE_COMPL",
    ]


def test_download_keeps_every_cell_as_the_published_string(
    eurusd: Instrument, source: EcbSource
) -> None:
    result = source.download(eurusd, date(2024, 12, 23), date(2024, 12, 27))
    assert result.frame["OBS_VALUE"].tolist() == ["1.0393", "1.0395", "1.0435"]
    # The quoted comma is one field, not two.
    assert result.frame["TITLE_COMPL"].tolist()[0] == "ECB reference, US dollar/Euro"


def test_download_does_not_invent_rows_for_target_holidays(
    eurusd: Instrument, source: EcbSource
) -> None:
    result = source.download(eurusd, date(2024, 12, 23), date(2024, 12, 27))
    assert result.frame["TIME_PERIOD"].tolist() == ["2024-12-23", "2024-12-24", "2024-12-27"]


@pytest.mark.parametrize("body", ["", "\n", "  \r\n"], ids=["empty", "newline", "blank"])
def test_download_empty_answer_gives_an_empty_frame(
    http: FakeHttp, eurusd: Instrument, source: EcbSource, body: str
) -> None:
    # A weekend or a holiday only: the ECB answers 200 with nothing in the body.
    http.body = body
    result = source.download(eurusd, date(2024, 12, 28), date(2024, 12, 29))
    assert result.frame.empty
    assert result.fetch_id == "20260912T210311Z"


@pytest.mark.parametrize(
    "body",
    [
        "<!DOCTYPE html><html><body>Maintenance</body></html>",
        '{"title":"Not Found","status":404}',
        "TIME_PERIOD,OBS_VALUE\n2024-12-23,1.0393\n",
    ],
    ids=["html-page", "problem-json", "missing-key-column"],
)
def test_download_rejects_a_body_that_is_not_an_ecb_csv(
    http: FakeHttp, eurusd: Instrument, source: EcbSource, body: str
) -> None:
    http.body = body
    with pytest.raises(ValueError, match=re.escape("EXR.D.USD.EUR.SP00.A")):
        source.download(eurusd, date(2024, 12, 23), date(2024, 12, 27))


def test_download_labels_the_result_and_takes_timestamps_from_the_clock(
    eurusd: Instrument, source: EcbSource
) -> None:
    result = source.download(eurusd, date(2024, 12, 23), date(2024, 12, 27))
    assert result.instrument_id == "ECB_EURUSD"
    assert result.source == "ECB"
    assert result.retrieved_at_utc == RETRIEVED_AT
    assert result.fetch_id == "20260912T210311Z"


def test_download_records_a_json_ready_request(
    http: FakeHttp, eurusd: Instrument, source: EcbSource
) -> None:
    result = source.download(eurusd, date(2024, 12, 23), date(2024, 12, 27))
    assert result.request == {
        "flow": "EXR",
        "series_key": "D.USD.EUR.SP00.A",
        "format": "csvdata",
        "url": only_url(http),
        "start": "2024-12-23",
        "end_inclusive": "2024-12-27",
        "pandas_version": pd.__version__,
    }


def test_download_rejects_start_after_end_without_any_http(
    http: FakeHttp, eurusd: Instrument, source: EcbSource
) -> None:
    with pytest.raises(ValueError):
        source.download(eurusd, date(2024, 12, 27), date(2024, 12, 23))
    assert http.urls == []


def test_download_rejects_a_malformed_symbol_without_any_http(
    http: FakeHttp, eurusd: Instrument, source: EcbSource
) -> None:
    malformed = replace(eurusd, source_symbol="EURUSD")
    with pytest.raises(ValueError, match="EURUSD"):
        source.download(malformed, date(2024, 12, 23), date(2024, 12, 27))
    assert http.urls == []


def test_download_rejects_a_non_utc_clock_without_any_http(
    http: FakeHttp, eurusd: Instrument
) -> None:
    naive = EcbSource(clock=lambda: datetime(2026, 9, 12, 21, 3, 11), fetch_text=http.get)
    with pytest.raises(ValueError):
        naive.download(eurusd, date(2024, 12, 23), date(2024, 12, 27))
    assert http.urls == []


def test_download_lets_an_http_error_propagate(eurusd: Instrument) -> None:
    def not_found(url: str) -> str:
        raise HTTPError(url, 404, "Not Found", Message(), None)

    # An unknown series is a 404: it must surface, never become an empty frame.
    with pytest.raises(HTTPError):
        EcbSource(clock=lambda: RETRIEVED_AT, fetch_text=not_found).download(
            eurusd, date(2024, 12, 23), date(2024, 12, 27)
        )


def test_corporate_actions_is_always_none_without_any_http(
    http: FakeHttp, eurusd: Instrument, source: EcbSource
) -> None:
    assert source.download_corporate_actions(eurusd, date(2024, 12, 23), date(2024, 12, 27)) is None
    # The range is ignored, even inverted.
    assert source.download_corporate_actions(eurusd, date(2024, 12, 27), date(2024, 12, 23)) is None
    assert http.urls == []


@pytest.mark.network
def test_download_live_eurusd_christmas_2024(eurusd: Instrument) -> None:
    result = EcbSource().download(eurusd, date(2024, 12, 23), date(2024, 12, 27))
    assert {"KEY", "TIME_PERIOD", "OBS_VALUE"} <= set(result.frame.columns)
    assert result.frame["TIME_PERIOD"].tolist() == ["2024-12-23", "2024-12-24", "2024-12-27"]
    assert result.frame["OBS_VALUE"].tolist()[0] == "1.0393"


@pytest.mark.network
def test_download_live_weekend_gives_an_empty_frame(eurusd: Instrument) -> None:
    result = EcbSource().download(eurusd, date(2024, 12, 28), date(2024, 12, 29))
    assert result.frame.empty


@pytest.mark.network
def test_download_live_unknown_series_raises_http_404(eurusd: Instrument) -> None:
    unknown = replace(eurusd, id="UNKNOWN", source_symbol="EXR.D.XXX.EUR.SP00.A")
    with pytest.raises(HTTPError) as raised:
        EcbSource().download(unknown, date(2024, 12, 23), date(2024, 12, 27))
    assert raised.value.code == 404
