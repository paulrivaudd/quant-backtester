"""FRED adapter: the URL sent and the CSV kept exactly as published.

The HTTP GET is injected, so the routine tests are offline and never read the
wall clock. The ``network`` tests check the live endpoint: one known series,
one unknown.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time
from email.message import Message
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import pandas as pd
import pytest

from quant_backtester.data.instruments import AssetType, DataType, Instrument, PublicationRule
from quant_backtester.data.sources.fred import FredSource

RETRIEVED_AT = datetime(2026, 9, 12, 21, 3, 11, tzinfo=UTC)

DGS10_CHRISTMAS_2024 = (
    "observation_date,DGS10\n"
    "2024-12-23,4.59\n"
    "2024-12-24,4.59\n"
    "2024-12-25,\n"
    "2024-12-26,4.58\n"
    "2024-12-27,4.62\n"
)
"""Verbatim FRED answer for DGS10, 23-27 December 2024: Christmas is empty."""


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
    """Return a fake HTTP GET answering with the Christmas 2024 DGS10 extract."""
    return FakeHttp(body=DGS10_CHRISTMAS_2024)


@pytest.fixture
def dgs10() -> Instrument:
    """Return the US 10-year Treasury yield, a LEVEL published the next day."""
    return Instrument(
        id="US10Y",
        name="US 10-year Treasury constant maturity yield",
        asset_type=AssetType.RATE,
        data_type=DataType.LEVEL,
        currency="NA",
        primary_source="FRED",
        source_symbol="DGS10",
        tradable=False,
        publication_rule=PublicationRule(
            publication_time=time(16, 15), timezone="America/New_York", lag_days=1
        ),
    )


@pytest.fixture
def source(http: FakeHttp) -> FredSource:
    """Return an adapter with a fixed clock and the fake HTTP GET."""
    return FredSource(clock=lambda: RETRIEVED_AT, fetch_text=http.get)


def only_url(http: FakeHttp) -> str:
    assert len(http.urls) == 1
    return http.urls[0]


def test_download_calls_the_public_csv_endpoint(
    http: FakeHttp, dgs10: Instrument, source: FredSource
) -> None:
    source.download(dgs10, date(2024, 12, 23), date(2024, 12, 27))
    parts = urlsplit(only_url(http))
    assert (parts.scheme, parts.netloc, parts.path) == (
        "https",
        "fred.stlouisfed.org",
        "/graph/fredgraph.csv",
    )


def test_download_sends_the_series_id_and_both_bounds_unshifted(
    http: FakeHttp, dgs10: Instrument, source: FredSource
) -> None:
    source.download(dgs10, date(2024, 12, 23), date(2024, 12, 27))
    assert parse_qs(urlsplit(only_url(http)).query) == {
        "id": ["DGS10"],
        "cosd": ["2024-12-23"],
        "coed": ["2024-12-27"],
    }


def test_download_single_day_range_sends_the_same_day_twice(
    http: FakeHttp, dgs10: Instrument, source: FredSource
) -> None:
    source.download(dgs10, date(2024, 12, 24), date(2024, 12, 24))
    query = parse_qs(urlsplit(only_url(http)).query)
    assert query["cosd"] == query["coed"] == ["2024-12-24"]


def test_download_keeps_the_original_column_names(dgs10: Instrument, source: FredSource) -> None:
    result = source.download(dgs10, date(2024, 12, 23), date(2024, 12, 27))
    assert list(result.frame.columns) == ["observation_date", "DGS10"]


def test_download_keeps_every_cell_as_the_published_string(
    dgs10: Instrument, source: FredSource
) -> None:
    result = source.download(dgs10, date(2024, 12, 23), date(2024, 12, 27))
    assert result.frame["observation_date"].tolist() == [
        "2024-12-23",
        "2024-12-24",
        "2024-12-25",
        "2024-12-26",
        "2024-12-27",
    ]
    # "4.59" rather than 4.59, and Christmas empty rather than NaN.
    assert result.frame["DGS10"].tolist() == ["4.59", "4.59", "", "4.58", "4.62"]


def test_download_keeps_a_legacy_dot_as_a_dot(http: FakeHttp, dgs10: Instrument) -> None:
    http.body = "observation_date,DGS10\n2024-12-24,4.59\n2024-12-25,.\n"
    result = FredSource(clock=lambda: RETRIEVED_AT, fetch_text=http.get).download(
        dgs10, date(2024, 12, 24), date(2024, 12, 25)
    )
    assert result.frame["DGS10"].tolist() == ["4.59", "."]


def test_download_header_only_gives_an_empty_frame_with_columns(
    http: FakeHttp, dgs10: Instrument, source: FredSource
) -> None:
    http.body = "observation_date,DGS10\n"
    result = source.download(dgs10, date(2024, 12, 28), date(2024, 12, 29))
    assert result.frame.empty
    assert list(result.frame.columns) == ["observation_date", "DGS10"]


@pytest.mark.parametrize(
    "body",
    [
        "<!DOCTYPE html><html><body>Series not found</body></html>",
        "",
        "DATE,DGS10\n2024-12-23,4.59\n",
    ],
    ids=["html-error-page", "empty-body", "renamed-date-column"],
)
def test_download_rejects_a_body_that_is_not_a_fred_series_csv(
    http: FakeHttp, dgs10: Instrument, source: FredSource, body: str
) -> None:
    http.body = body
    with pytest.raises(ValueError, match="DGS10"):
        source.download(dgs10, date(2024, 12, 23), date(2024, 12, 27))


def test_download_labels_the_result_and_takes_timestamps_from_the_clock(
    dgs10: Instrument, source: FredSource
) -> None:
    result = source.download(dgs10, date(2024, 12, 23), date(2024, 12, 27))
    assert result.instrument_id == "US10Y"
    assert result.source == "FRED"
    assert result.retrieved_at_utc == RETRIEVED_AT
    assert result.fetch_id == "20260912T210311Z"


def test_download_records_a_json_ready_request(
    http: FakeHttp, dgs10: Instrument, source: FredSource
) -> None:
    result = source.download(dgs10, date(2024, 12, 23), date(2024, 12, 27))
    assert result.request == {
        "series_id": "DGS10",
        "endpoint": "fredgraph.csv",
        "url": only_url(http),
        "start": "2024-12-23",
        "end_inclusive": "2024-12-27",
        "pandas_version": pd.__version__,
    }


def test_download_rejects_start_after_end_without_any_http(
    http: FakeHttp, dgs10: Instrument, source: FredSource
) -> None:
    with pytest.raises(ValueError):
        source.download(dgs10, date(2024, 12, 27), date(2024, 12, 23))
    assert http.urls == []


def test_download_rejects_a_non_utc_clock_without_any_http(
    http: FakeHttp, dgs10: Instrument
) -> None:
    naive = FredSource(clock=lambda: datetime(2026, 9, 12, 21, 3, 11), fetch_text=http.get)
    with pytest.raises(ValueError):
        naive.download(dgs10, date(2024, 12, 23), date(2024, 12, 27))
    assert http.urls == []


def test_download_lets_an_http_error_propagate(dgs10: Instrument) -> None:
    def not_found(url: str) -> str:
        raise HTTPError(url, 404, "Not Found", Message(), None)

    # An unknown series id is a 404: it must surface, never become an empty frame.
    with pytest.raises(HTTPError):
        FredSource(clock=lambda: RETRIEVED_AT, fetch_text=not_found).download(
            dgs10, date(2024, 12, 23), date(2024, 12, 27)
        )


@pytest.mark.network
def test_download_live_dgs10_christmas_2024(dgs10: Instrument) -> None:
    result = FredSource().download(dgs10, date(2024, 12, 23), date(2024, 12, 27))
    assert list(result.frame.columns) == ["observation_date", "DGS10"]
    assert result.frame["observation_date"].tolist()[0] == "2024-12-23"
    assert result.frame["observation_date"].tolist()[-1] == "2024-12-27"
    christmas = result.frame[result.frame["observation_date"] == "2024-12-25"]
    # Empty today; accept the legacy "." too so a format rollback is not a failure.
    assert christmas["DGS10"].tolist() in ([""], ["."])
    assert result.retrieved_at_utc.tzinfo is UTC


@pytest.mark.network
def test_download_live_unknown_series_raises_http_404(dgs10: Instrument) -> None:
    unknown = replace(dgs10, id="UNKNOWN", source_symbol="NOT_A_SERIES_XYZ")
    # http_get_text closes the error's response itself: no socket may leak here.
    with pytest.raises(HTTPError) as raised:
        FredSource().download(unknown, date(2024, 12, 23), date(2024, 12, 27))
    assert raised.value.code == 404


def test_corporate_actions_is_always_none_without_any_http(
    http: FakeHttp, dgs10: Instrument, source: FredSource
) -> None:
    assert source.download_corporate_actions(dgs10, date(2024, 12, 23), date(2024, 12, 27)) is None
    # The range is ignored, even inverted.
    assert source.download_corporate_actions(dgs10, date(2024, 12, 27), date(2024, 12, 23)) is None
    assert http.urls == []
