"""Dukascopy minute bars: addresses, decoding, and the rate at the US close. Offline."""

from __future__ import annotations

import hashlib
import lzma
import struct
import urllib.request
from datetime import UTC, date, datetime, timedelta

import pytest

from quant_backtester.data.sources import base
from quant_backtester.data.sources.base import ProviderResponseError
from quant_backtester.data.sources.dukascopy import (
    CLIENT_NAME,
    DukascopySource,
    QuoteBar,
    Side,
    day_url,
    month_hours_url,
    parse_hour_bars,
    parse_minute_bars,
    rate_at,
)

DAY = date(2024, 3, 6)
NOW = datetime(2026, 11, 7, 22, 0, tzinfo=UTC)


def packed(*records: tuple[int, int, int, int, int, float]) -> bytes:
    return lzma.compress(b"".join(struct.pack(">IIIIIf", *record) for record in records))


def bar(minute: int, close: float) -> QuoteBar:
    start = datetime(2024, 3, 6, tzinfo=UTC) + timedelta(minutes=minute)
    return QuoteBar(start, timedelta(minutes=1), close, close, close, close, 1.0)


def hour(day: int, hour_of_day: int, close: float) -> QuoteBar:
    start = datetime(2024, 3, day, hour_of_day, tzinfo=UTC)
    return QuoteBar(start, timedelta(hours=1), close, close, close, close, 1.0)


def test_the_address_counts_months_from_zero() -> None:
    assert day_url("EURUSD", DAY, Side.BID) == (
        "https://datafeed.dukascopy.com/datafeed/EURUSD/2024/02/06/BID_candles_min_1.bi5"
    )
    assert day_url("EURUSD", date(2015, 12, 31), Side.ASK).endswith(
        "/2015/11/31/ASK_candles_min_1.bi5"
    )
    with pytest.raises(ValueError, match="unsupported pair"):
        day_url("GBPJPY", DAY, Side.BID)


def test_a_download_keeps_the_exact_bytes_and_where_they_came_from() -> None:
    asked: list[str] = []
    payload = packed((0, 108554, 108555, 108552, 108556, 50.7))

    def serve(url: str) -> bytes:
        asked.append(url)
        return payload

    download = DukascopySource(clock=lambda: NOW, fetch_bytes=serve).fetch_day(
        "EURUSD", DAY, Side.BID
    )
    assert asked == [day_url("EURUSD", DAY, Side.BID)]
    assert download.payload == payload
    assert download.sha256 == hashlib.sha256(payload).hexdigest()
    assert download.retrieved_at_utc == NOW


def test_the_default_transport_sends_a_plain_client_name(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[object] = []

    class Response:
        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def read(self) -> bytes:
            return b""

    def fake_urlopen(target: object, timeout: float) -> Response:
        seen.append(target)
        return Response()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    DukascopySource(clock=lambda: NOW).fetch_day("EURUSD", DAY, Side.ASK)
    (request,) = seen
    assert isinstance(request, urllib.request.Request)
    assert request.get_header("User-agent") == CLIENT_NAME
    # Without headers the helper still passes the bare address, as before.
    base.http_get_bytes("https://example.org/x")
    assert seen[-1] == "https://example.org/x"


def test_records_decode_into_minutes_of_the_day_in_price_units() -> None:
    bars = parse_minute_bars(
        packed(
            (0, 108554, 108555, 108552, 108556, 50.5), (75540, 108991, 108990, 108986, 108994, 2.0)
        ),
        "EURUSD",
        DAY,
    )
    assert [b.start_utc for b in bars] == [
        datetime(2024, 3, 6, tzinfo=UTC),
        datetime(2024, 3, 6, 20, 59, tzinfo=UTC),
    ]
    assert bars[1].close == pytest.approx(1.08990)
    assert bars[0].high == pytest.approx(1.08556)


def test_an_empty_file_is_a_day_without_quotes() -> None:
    assert parse_minute_bars(b"", "EURUSD", DAY) == ()


@pytest.mark.parametrize(
    "payload",
    [
        b"not lzma",
        lzma.compress(b"\x00" * 23),
        packed((60, 1, 1, 1, 1, 1.0), (60, 1, 1, 1, 1, 1.0)),  # repeated minute
        packed((90, 1, 1, 1, 1, 1.0)),  # not on a minute
        packed((86_400, 1, 1, 1, 1, 1.0)),  # the next day
        packed((0, 0, 1, 0, 1, 1.0)),  # a zero price
        packed((0, 5, 5, 6, 7, 1.0)),  # low above the close
        packed((0, 5, 5, 4, 4, 1.0)),  # high below the close
    ],
)
def test_a_malformed_file_is_refused(payload: bytes) -> None:
    with pytest.raises(ProviderResponseError):
        parse_minute_bars(payload, "EURUSD", DAY)


def test_the_rate_is_the_mid_of_the_bar_ending_at_the_instant() -> None:
    at = datetime(2024, 3, 6, 21, 0, tzinfo=UTC)
    bid = [bar(1258, 1.0), bar(1259, 1.08990), bar(1260, 2.0)]  # 20:58, 20:59, 21:00
    ask = [bar(1258, 1.0), bar(1259, 1.08992), bar(1260, 2.0)]
    observed = rate_at(bid, ask, at, timedelta(minutes=5))
    assert observed is not None
    assert observed.rate == pytest.approx(1.08991)
    assert observed.bar_end_utc == at
    assert observed.staleness == timedelta(0)


def test_a_missing_last_bar_falls_back_within_the_delay_only() -> None:
    at = datetime(2024, 3, 6, 21, 0, tzinfo=UTC)
    bid, ask = [bar(1256, 1.1)], [bar(1256, 1.1002)]  # ends 20:57, three minutes before
    observed = rate_at(bid, ask, at, timedelta(minutes=5))
    assert observed is not None and observed.staleness == timedelta(minutes=3)
    assert rate_at(bid, ask, at, timedelta(minutes=2)) is None
    # A bar on one side only is not a quote.
    assert rate_at([bar(1259, 1.1)], [bar(1258, 1.1)], at, timedelta(seconds=30)) is None


def test_a_future_bar_is_never_read() -> None:
    at = datetime(2024, 3, 6, 21, 0, tzinfo=UTC)
    bid, ask = [bar(1260, 1.2)], [bar(1260, 1.2)]  # starts at the instant, ends after it
    assert rate_at(bid, ask, at, timedelta(minutes=5)) is None


def test_crossed_quotes_and_naive_instants_are_refused() -> None:
    at = datetime(2024, 3, 6, 21, 0, tzinfo=UTC)
    with pytest.raises(ProviderResponseError, match="crossed"):
        rate_at([bar(1259, 1.1)], [bar(1259, 1.0)], at, timedelta(minutes=1))
    with pytest.raises(ValueError, match="aware UTC"):
        rate_at([], [], datetime(2024, 3, 6, 21, 0), timedelta(minutes=1))


def test_the_monthly_hourly_file_address_and_its_hours() -> None:
    assert month_hours_url("EURUSD", 2024, 3, Side.BID) == (
        "https://datafeed.dukascopy.com/datafeed/EURUSD/2024/02/BID_candles_hour_1.bi5"
    )
    # 6 March, 20:00 UTC is 5 days and 20 hours after 1 March, 00:00 UTC.
    offset = (5 * 24 + 20) * 3600
    bars = parse_hour_bars(
        packed((0, 1, 1, 1, 1, 1.0), (offset, 108967, 108990, 108929, 108994, 1.0)),
        "EURUSD",
        2024,
        3,
    )
    assert bars[1].start_utc == datetime(2024, 3, 6, 20, tzinfo=UTC)
    assert bars[1].length == timedelta(hours=1)
    assert bars[1].close == pytest.approx(1.08990)
    with pytest.raises(ProviderResponseError, match="out of order"):
        parse_hour_bars(packed((31 * 86_400, 1, 1, 1, 1, 1.0)), "EURUSD", 2024, 3)  # 1 April
    with pytest.raises(ProviderResponseError, match="out of order"):
        parse_hour_bars(packed((60, 1, 1, 1, 1, 1.0)), "EURUSD", 2024, 3)  # not on the hour


def test_the_hour_ending_at_the_us_close_gives_its_rate_and_nothing_else_does() -> None:
    at = datetime(2024, 3, 6, 21, 0, tzinfo=UTC)
    observed = rate_at([hour(6, 20, 1.0899)], [hour(6, 20, 1.08992)], at, timedelta(minutes=5))
    assert observed is not None and observed.rate == pytest.approx(1.08991)
    assert observed.bar_end_utc == at
    # The hour before ends 60 minutes early: too stale, no rate.
    assert rate_at([hour(6, 19, 1.1)], [hour(6, 19, 1.1)], at, timedelta(minutes=5)) is None


def test_a_month_download_is_addressed_by_its_first_day() -> None:
    download = DukascopySource(clock=lambda: NOW, fetch_bytes=lambda url: b"").fetch_month_hours(
        "EURUSD", 2024, 3, Side.ASK
    )
    assert download.day == date(2024, 3, 1)
    assert download.url == month_hours_url("EURUSD", 2024, 3, Side.ASK)


def test_a_bar_without_a_tick_is_not_a_quote() -> None:
    # The feed fills an hour or minute without ticks with the previous close,
    # at zero volume: read as a quote, it would carry an old price to the
    # instant with no staleness.
    at = datetime(2024, 3, 6, 21, 0, tzinfo=UTC)
    filled = QuoteBar(at - timedelta(minutes=1), timedelta(minutes=1), 1.2, 1.2, 1.2, 1.2, 0.0)
    real = bar(1257, 1.1)  # ends 20:58, with volume
    observed = rate_at([real, filled], [bar(1257, 1.1002), filled], at, timedelta(minutes=5))
    assert observed is not None
    assert observed.rate == pytest.approx(1.1001)
    assert observed.staleness == timedelta(minutes=2)
    assert rate_at([filled], [filled], at, timedelta(minutes=5)) is None
