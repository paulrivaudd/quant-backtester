"""Source contract helpers: fetch identifier, UTC clock and HTTP GET.

Offline: ``urlopen`` is replaced by a fake. Only ``utc_now`` reads the wall
clock, and its test checks the timezone, never the value.
"""

from __future__ import annotations

import io
import urllib.request
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from email.message import Message
from urllib.error import HTTPError, URLError
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from quant_backtester.data.normalizer import NORMALIZERS
from quant_backtester.data.sources.base import (
    HTTP_TIMEOUT_SECONDS,
    DataSource,
    ProviderError,
    ProviderRateLimited,
    ProviderResponseError,
    ProviderUnavailable,
    RawDownload,
    http_get_text,
    make_fetch_id,
    utc_now,
)
from quant_backtester.data.sources.ecb import EcbSource
from quant_backtester.data.sources.euronext import EuronextSource
from quant_backtester.data.sources.fred import FredSource
from quant_backtester.data.sources.yahoo import YahooSource


def test_make_fetch_id_formats_a_utc_instant() -> None:
    assert make_fetch_id(datetime(2026, 9, 12, 21, 3, 11, tzinfo=UTC)) == "20260912T210311Z"


def test_make_fetch_id_zero_pads_every_field() -> None:
    assert make_fetch_id(datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)) == "20260102T030405Z"


def test_make_fetch_id_truncates_sub_second_precision() -> None:
    instant = datetime(2026, 9, 12, 21, 3, 11, 999_999, tzinfo=UTC)
    assert make_fetch_id(instant) == "20260912T210311Z"


@pytest.mark.parametrize(
    "instant",
    [
        datetime(2026, 9, 12, 21, 3, 11, tzinfo=ZoneInfo("UTC")),
        datetime(2026, 9, 12, 21, 3, 11, tzinfo=timezone(timedelta(0))),
        pd.Timestamp("2026-09-12 21:03:11", tz="UTC"),
    ],
    ids=["zoneinfo-utc", "fixed-zero-offset", "pandas-timestamp"],
)
def test_make_fetch_id_accepts_every_utc_spelling(instant: datetime) -> None:
    assert make_fetch_id(instant) == "20260912T210311Z"


def test_make_fetch_id_sorts_lexicographically_in_chronological_order() -> None:
    instants = [
        datetime(2025, 12, 31, 23, 59, 59, tzinfo=UTC),
        datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        datetime(2026, 9, 30, 9, 59, 59, tzinfo=UTC),
        datetime(2026, 9, 30, 10, 0, 0, tzinfo=UTC),
        datetime(2026, 10, 1, 0, 0, 0, tzinfo=UTC),
    ]
    ids = [make_fetch_id(instant) for instant in reversed(instants)]
    assert sorted(ids) == [make_fetch_id(instant) for instant in instants]


def test_make_fetch_id_rejects_a_naive_datetime() -> None:
    with pytest.raises(ValueError):
        make_fetch_id(datetime(2026, 9, 12, 21, 3, 11))


def test_make_fetch_id_rejects_a_non_zero_offset() -> None:
    with pytest.raises(ValueError):
        make_fetch_id(datetime(2026, 9, 12, 23, 3, 11, tzinfo=timezone(timedelta(hours=2))))


@pytest.mark.parametrize(
    "month",
    [1, 7],
    ids=["winter-offset-zero", "summer-offset-one-hour"],
)
def test_make_fetch_id_rejects_a_local_zone_in_every_season(month: int) -> None:
    # Europe/London sits at +00:00 in winter: accepting it then would make the
    # same caller pass in January and fail in July.
    with pytest.raises(ValueError):
        make_fetch_id(datetime(2026, month, 15, 21, 3, 11, tzinfo=ZoneInfo("Europe/London")))


def test_utc_now_is_accepted_by_make_fetch_id() -> None:
    now = utc_now()
    assert now.tzinfo is UTC
    assert len(make_fetch_id(now)) == len("20260912T210311Z")


class FakeResponse:
    """Minimal stand-in for the context manager returned by ``urlopen``."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> FakeResponse:
        """Return the response itself."""
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Do nothing: there is no socket to close."""

    def read(self) -> bytes:
        """Return the whole body."""
        return self._body


def test_http_get_text_decodes_utf8_and_sets_the_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, float]] = []

    def fake_urlopen(url: str, timeout: float) -> FakeResponse:
        seen.append((url, timeout))
        return FakeResponse("series,taux €\n".encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert http_get_text("https://example.test/series.csv") == "series,taux €\n"
    assert seen == [("https://example.test/series.csv", HTTP_TIMEOUT_SECONDS)]


def test_http_get_text_empty_body_is_an_empty_string(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout: FakeResponse(b""))
    assert http_get_text("https://example.test/empty.csv") == ""


def test_http_get_text_closes_the_error_response_and_translates_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 404 is the provider answering something unusable, and the socket closes."""
    error_body = io.BytesIO(b"<html>Not Found</html>")

    def fake_urlopen(url: str, timeout: float) -> FakeResponse:
        raise HTTPError(url, 404, "Not Found", Message(), error_body)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(ProviderResponseError) as raised:
        http_get_text("https://example.test/missing.csv")
    assert isinstance(raised.value.__cause__, HTTPError)
    assert raised.value.__cause__.code == 404
    assert error_body.closed


@pytest.mark.parametrize(
    ("status", "expected"),
    [(429, ProviderRateLimited), (500, ProviderUnavailable), (503, ProviderUnavailable)],
)
def test_http_get_text_tells_a_busy_provider_from_a_broken_answer(
    monkeypatch: pytest.MonkeyPatch, status: int, expected: type[ProviderError]
) -> None:
    """Rate limiting and an outage are transient; an unreadable answer is not."""

    def fake_urlopen(url: str, timeout: float) -> FakeResponse:
        raise HTTPError(url, status, "", Message(), None)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(expected):
        http_get_text("https://example.test/series.csv")


def test_http_get_text_translates_an_unreachable_host(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(url: str, timeout: float) -> FakeResponse:
        raise URLError("name or service not known")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(ProviderUnavailable, match="could not be reached"):
        http_get_text("https://example.test/series.csv")


def test_raw_download_is_immutable() -> None:
    download = RawDownload(
        instrument_id="US10Y",
        source="FRED",
        fetch_id="20260912T210311Z",
        retrieved_at_utc=datetime(2026, 9, 12, 21, 3, 11, tzinfo=UTC),
        frame=pd.DataFrame(),
        request={},
    )
    with pytest.raises(FrozenInstanceError):
        download.fetch_id = "20260913T000000Z"  # type: ignore[misc]


ALL_SOURCES: tuple[DataSource, ...] = (YahooSource(), EuronextSource(), FredSource(), EcbSource())
"""Every adapter, typed as the protocol: pyright rejects one that breaks the contract."""


def test_every_source_exposes_both_download_methods() -> None:
    for source in ALL_SOURCES:
        assert callable(source.download)
        assert callable(source.download_corporate_actions)


def test_source_ids_are_unique_and_each_has_a_normalizer() -> None:
    source_ids = [source.source_id for source in ALL_SOURCES]
    assert len(set(source_ids)) == len(source_ids)
    assert sorted(source_ids) == sorted(NORMALIZERS)
