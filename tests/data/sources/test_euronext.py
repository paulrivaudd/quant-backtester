"""Euronext adapter: the URL sent, the export kept as published, the silent gaps raised.

The HTTP GET is injected, so the routine tests are offline and never read the
wall clock. The ``network`` tests check the live endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from email.message import Message
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import pandas as pd
import pytest

from quant_backtester.data.instruments import AssetType, DataType, Instrument
from quant_backtester.data.sources.base import (
    ProviderRangeUnavailable,
    ProviderResponseError,
)
from quant_backtester.data.sources.euronext import (
    EURONEXT_WINDOW,
    EuronextSource,
    parse_euronext_csv,
    split_euronext_symbol,
)

RETRIEVED_AT = datetime(2026, 9, 12, 21, 3, 11, tzinfo=UTC)

CW8_HEADER = 'Date;Open;High;Low;Last;Close;"Number of Shares";"Number of Trades";Turnover'

CW8_EXPORT = (
    '﻿"Historical Data"\n'
    '"From 2024-12-27 to 2024-12-31"\n'
    "LU1681043599\n"
    f"{CW8_HEADER}\n"
    "31/12/2024;567.8383;571.00;567.0441;570.449;570.449;3839;873;2184331;568.984478\n"
    "30/12/2024;570.9109;572.3722;565.3737;570.0639;570.0639;13290;1987;7566539;569.3408\n"
    "27/12/2024;575.938;576.5415;570.00;572.4967;572.4967;13175;1876;7569202;574.512466\n"
)
"""Verbatim Euronext export for CW8, 27-31 December 2024: byte order mark, three
preamble lines, newest first, and one more field per row than the header names."""

EMPTY_EXPORT = f'﻿"Historical Data"\n"From 2024-12-28 to 2024-12-29"\nLU1681043599\n{CW8_HEADER}\n'
"""Verbatim answer for a weekend - and, identically, for an unknown ISIN."""


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
    """Return a fake HTTP GET answering with the CW8 export."""
    return FakeHttp(body=CW8_EXPORT)


@pytest.fixture
def cw8() -> Instrument:
    """Return CW8 as Euronext sees it: listed since 2018, symbol ``<ISIN>-<MIC>``."""
    return Instrument(
        id="ETF_WORLD",
        name="Amundi MSCI World (PEA)",
        asset_type=AssetType.ETF,
        data_type=DataType.BAR,
        currency="EUR",
        primary_source="EURONEXT",
        source_symbol="LU1681043599-XPAR",
        tradable=True,
        calendar_id="XPAR",
        first_session=date(2018, 1, 2),
    )


@pytest.fixture
def source(http: FakeHttp) -> EuronextSource:
    """Return an adapter with a fixed clock and the fake HTTP GET."""
    return EuronextSource(clock=lambda: RETRIEVED_AT, fetch_text=http.get)


def only_url(http: FakeHttp) -> str:
    assert len(http.urls) == 1
    return http.urls[0]


# --- symbol -------------------------------------------------------------------


def test_split_euronext_symbol_separates_isin_and_mic() -> None:
    assert split_euronext_symbol("LU1681043599-XPAR") == ("LU1681043599", "XPAR")


@pytest.mark.parametrize(
    "symbol",
    ["CW8.PA", "LU1681043599", "LU1681043599-XPA", "lu1681043599-xpar", "LU168104359-XPAR", ""],
    ids=["yahoo-symbol", "no-mic", "short-mic", "lowercase", "short-isin", "empty"],
)
def test_split_euronext_symbol_rejects_another_shape(symbol: str) -> None:
    with pytest.raises(ValueError):
        split_euronext_symbol(symbol)


# --- request ------------------------------------------------------------------


def test_download_calls_the_isin_mic_export_path(
    http: FakeHttp, cw8: Instrument, source: EuronextSource
) -> None:
    source.download(cw8, date(2024, 12, 27), date(2024, 12, 31))
    parts = urlsplit(only_url(http))
    assert (parts.scheme, parts.netloc, parts.path) == (
        "https",
        "live.euronext.com",
        "/en/ajax/AwlHistoricalPrice/getFullDownloadAjax/LU1681043599-XPAR",
    )


def test_download_sends_both_dates_unshifted_and_asks_for_raw_csv(
    http: FakeHttp, cw8: Instrument, source: EuronextSource
) -> None:
    source.download(cw8, date(2024, 12, 27), date(2024, 12, 31))
    assert parse_qs(urlsplit(only_url(http)).query, keep_blank_values=True) == {
        "format": ["csv"],
        "decimal_separator": ["."],
        "date_form": ["d/m/Y"],
        "op": [""],
        "adjusted": [""],
        "base100": [""],
        "startdate": ["2024-12-27"],
        "enddate": ["2024-12-31"],
    }


def test_download_records_a_json_ready_request(
    http: FakeHttp, cw8: Instrument, source: EuronextSource
) -> None:
    result = source.download(cw8, date(2024, 12, 27), date(2024, 12, 31))
    assert result.request == {
        "isin": "LU1681043599",
        "mic": "XPAR",
        "url": only_url(http),
        "start": "2024-12-27",
        "end_inclusive": "2024-12-31",
        "pandas_version": pd.__version__,
    }


def test_download_labels_the_result_and_takes_timestamps_from_the_clock(
    cw8: Instrument, source: EuronextSource
) -> None:
    result = source.download(cw8, date(2024, 12, 27), date(2024, 12, 31))
    assert result.instrument_id == "ETF_WORLD"
    assert result.source == "EURONEXT"
    assert result.retrieved_at_utc == RETRIEVED_AT
    assert result.fetch_id == "20260912T210311Z"


# --- export kept as published -------------------------------------------------


def test_download_keeps_the_published_columns_and_names_the_extra_field(
    cw8: Instrument, source: EuronextSource
) -> None:
    result = source.download(cw8, date(2024, 12, 27), date(2024, 12, 31))
    assert list(result.frame.columns) == [
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


def test_download_keeps_rows_newest_first_and_cells_as_strings(
    cw8: Instrument, source: EuronextSource
) -> None:
    result = source.download(cw8, date(2024, 12, 27), date(2024, 12, 31))
    assert result.frame["Date"].tolist() == ["31/12/2024", "30/12/2024", "27/12/2024"]
    assert result.frame["Open"].tolist() == ["567.8383", "570.9109", "575.938"]
    assert result.frame["Number of Shares"].tolist() == ["3839", "13290", "13175"]


def test_parse_accepts_the_export_without_its_byte_order_mark() -> None:
    frame = parse_euronext_csv(CW8_EXPORT.lstrip("﻿"), "LU1681043599")
    assert len(frame) == 3


def test_download_weekend_gives_an_empty_frame_with_the_header(
    http: FakeHttp, cw8: Instrument, source: EuronextSource
) -> None:
    http.body = EMPTY_EXPORT
    result = source.download(cw8, date(2024, 12, 28), date(2024, 12, 29))
    assert result.frame.empty
    assert list(result.frame.columns)[:6] == ["Date", "Open", "High", "Low", "Last", "Close"]


@pytest.mark.parametrize(
    ("body", "match"),
    [
        ("<!DOCTYPE html><html>Maintenance</html>", "not a price export"),
        ("", "not a price export"),
        (CW8_EXPORT.replace("LU1681043599\n", "FR0000120271\n", 1), "FR0000120271"),
        (CW8_EXPORT.replace("Date;Open;High", "Day;Open;High", 1), "unexpected header"),
        (CW8_EXPORT.replace(";568.984478\n", "\n", 1), "width"),
        (CW8_EXPORT.replace("27/12/2024;575.938;", "27/12/2024;", 1), "width"),
    ],
    ids=[
        "html-page",
        "empty-body",
        "other-isin",
        "renamed-header",
        "uneven-rows",
        "row-shorter-than-header",
    ],
)
def test_download_rejects_a_body_that_is_not_the_requested_export(
    http: FakeHttp, cw8: Instrument, source: EuronextSource, body: str, match: str
) -> None:
    http.body = body
    # A body this adapter cannot read is the provider's format, not our bug, and
    # not a transient outage either: it has to be looked at, never absorbed.
    with pytest.raises((ProviderResponseError, ValueError), match=match):
        source.download(cw8, date(2024, 12, 27), date(2024, 12, 31))


# --- silent gaps --------------------------------------------------------------


def test_download_no_row_over_a_week_is_an_unknown_isin_or_out_of_window(
    http: FakeHttp, cw8: Instrument, source: EuronextSource
) -> None:
    http.body = EMPTY_EXPORT
    with pytest.raises(ProviderResponseError, match="ISIN is unknown"):
        source.download(cw8, date(2024, 12, 20), date(2024, 12, 31))


def test_download_no_row_over_six_days_is_accepted(
    http: FakeHttp, cw8: Instrument, source: EuronextSource
) -> None:
    # 24 to 29 December 2024 holds sessions in reality, but six days is still short
    # of the week no Euronext venue ever closes for: the adapter cannot tell.
    http.body = EMPTY_EXPORT
    result = source.download(cw8, date(2024, 12, 24), date(2024, 12, 29))
    assert result.frame.empty


def test_download_cut_to_the_two_year_window_raises(
    cw8: Instrument, source: EuronextSource
) -> None:
    with pytest.raises(ProviderRangeUnavailable, match="two-year window") as raised:
        source.download(cw8, date(2018, 1, 1), date(2024, 12, 31))
    # The listing date, not the requested start, is what was expected.
    assert "2018-01-02" in str(raised.value)
    # And the date it did serve from, so the caller retries instead of giving up.
    assert raised.value.available_from == date(2024, 12, 27)


def test_download_first_row_within_a_week_of_the_start_is_accepted(
    cw8: Instrument, source: EuronextSource
) -> None:
    # Requested from Monday 23rd: the export starts on the 27th, four days later.
    result = source.download(cw8, date(2024, 12, 23), date(2024, 12, 31))
    assert len(result.frame) == 3


def test_download_before_the_first_session_expects_rows_from_the_listing(
    cw8: Instrument, source: EuronextSource
) -> None:
    recently_listed = replace(cw8, first_session=date(2024, 12, 27))
    result = source.download(recently_listed, date(2024, 1, 1), date(2024, 12, 31))
    assert len(result.frame) == 3


def test_download_after_the_last_session_expects_nothing(
    http: FakeHttp, cw8: Instrument, source: EuronextSource
) -> None:
    delisted = replace(cw8, last_session=date(2023, 6, 30))
    http.body = EMPTY_EXPORT
    result = source.download(delisted, date(2024, 1, 1), date(2024, 12, 31))
    assert result.frame.empty


def test_download_end_in_the_future_is_measured_up_to_the_retrieval_day(
    http: FakeHttp, cw8: Instrument
) -> None:
    # Retrieved on 29 December: the three days after it cannot hold a row yet.
    http.body = EMPTY_EXPORT
    early = EuronextSource(
        clock=lambda: datetime(2024, 12, 29, 12, 0, tzinfo=UTC), fetch_text=http.get
    )
    result = early.download(cw8, date(2024, 12, 28), date(2025, 1, 3))
    assert result.frame.empty


# --- refusals without any HTTP ------------------------------------------------


def test_download_rejects_start_after_end_without_any_http(
    http: FakeHttp, cw8: Instrument, source: EuronextSource
) -> None:
    with pytest.raises(ValueError):
        source.download(cw8, date(2024, 12, 31), date(2024, 12, 27))
    assert http.urls == []


def test_download_rejects_a_yahoo_symbol_without_any_http(
    http: FakeHttp, cw8: Instrument, source: EuronextSource
) -> None:
    with pytest.raises(ValueError, match=r"CW8\.PA"):
        source.download(
            replace(cw8, source_symbol="CW8.PA"), date(2024, 12, 27), date(2024, 12, 31)
        )
    assert http.urls == []


def test_download_rejects_a_non_utc_clock_without_any_http(http: FakeHttp, cw8: Instrument) -> None:
    naive = EuronextSource(clock=lambda: datetime(2026, 9, 12, 21, 3, 11), fetch_text=http.get)
    with pytest.raises(ValueError):
        naive.download(cw8, date(2024, 12, 27), date(2024, 12, 31))
    assert http.urls == []


def test_download_lets_an_http_error_propagate(cw8: Instrument) -> None:
    def unavailable(url: str) -> str:
        raise HTTPError(url, 503, "Service Unavailable", Message(), None)

    with pytest.raises(HTTPError):
        EuronextSource(clock=lambda: RETRIEVED_AT, fetch_text=unavailable).download(
            cw8, date(2024, 12, 27), date(2024, 12, 31)
        )


def test_corporate_actions_is_always_none_without_any_http(
    http: FakeHttp, cw8: Instrument, source: EuronextSource
) -> None:
    assert source.download_corporate_actions(cw8, date(2024, 12, 27), date(2024, 12, 31)) is None
    assert http.urls == []


# --- live endpoint ------------------------------------------------------------


@pytest.mark.network
def test_download_live_cw8_last_month_matches_the_export_shape(cw8: Instrument) -> None:
    # Euronext serves a rolling two-year window: a fixed date range would expire.
    end = datetime.now(UTC).date()
    result = EuronextSource().download(cw8, end - timedelta(days=30), end)
    assert list(result.frame.columns)[:9] == [
        "Date",
        "Open",
        "High",
        "Low",
        "Last",
        "Close",
        "Number of Shares",
        "Number of Trades",
        "Turnover",
    ]
    assert len(result.frame) >= 15


@pytest.mark.network
def test_download_live_unknown_isin_raises(cw8: Instrument) -> None:
    unknown = replace(cw8, source_symbol="XX0000000000-XPAR")
    end = datetime.now(UTC).date()
    with pytest.raises(ProviderResponseError, match="ISIN is unknown"):
        EuronextSource().download(unknown, end - timedelta(days=30), end)


@pytest.mark.network
def test_download_live_request_older_than_the_window_raises(cw8: Instrument) -> None:
    with pytest.raises(ProviderRangeUnavailable, match="two-year window") as raised:
        EuronextSource().download(cw8, date(2018, 1, 2), date(2018, 3, 1))
    # It names where its window starts, so a caller can ask again from there.
    assert raised.value.available_from is not None


def test_available_from_declares_the_rolling_window(
    cw8: Instrument, source: EuronextSource
) -> None:
    """Declared so an ordinary request is cut to it instead of failing on it."""
    assert source.available_from(cw8) == RETRIEVED_AT.date() - EURONEXT_WINDOW
