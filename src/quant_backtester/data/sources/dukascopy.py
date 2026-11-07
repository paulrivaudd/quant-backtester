"""Dukascopy minute bars: a currency rate read at a stated instant, from a free feed.

SA17 converts USD fund NAVs into EUR with the rate at the moment the NAVs were
priced: the US close, which the XNYS calendar gives for each session (16:00
New York, 13:00 on a half day). Daily reference rates are taken at other
instants (ECB at 14:15 CET, WM at 16:00 London), so a minute feed is read
instead. Dukascopy publishes, without an account, LZMA-compressed files of
bars per pair and side (bid or ask): one file of minute bars per day, and one
file of hourly bars per month. The close of the hour ending at 16:00 New York
is the close of the minute ending then: both are the last quote before it.

What a record is
----------------
Each record is 24 bytes, big-endian: the bar's start in seconds after 00:00 UTC
of the file's first day (the day, or the first of the month), then open, close,
low and high as integers in units of the pair's point (1e-5 for EURUSD), then
the volume as a float. The month in a file's address counts from zero.

Revision and availability
-------------------------
The feed is a snapshot of quotes, not a fixing, and its history may be
rebuilt by the provider without notice: a retrieval proves what was served
that day, not what was knowable earlier. A rate read at an instant describes
that instant; it was available then, as quotes are.

Network I/O happens only in :class:`DukascopySource`, which sends a plain
client name: the feed refuses Python's default one with HTTP 429.
"""

from __future__ import annotations

import calendar
import hashlib
import lzma
import math
import struct
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import Enum

from quant_backtester.data.sources.base import (
    ProviderResponseError,
    http_get_bytes,
    utc_now,
)

DATAFEED = "https://datafeed.dukascopy.com/datafeed"
CLIENT_NAME = "quant-backtester research client"
RECORD = struct.Struct(">IIIIIf")
POINTS = {"EURUSD": 100_000}
"""Integer units per unit of price, by supported pair."""

SECONDS_PER_DAY = 86_400


class Side(Enum):
    """Which quotes a file holds."""

    BID = "BID"
    ASK = "ASK"


@dataclass(frozen=True, slots=True)
class QuoteBar:
    """One bar of quotes, prices in units of the quote currency.

    Attributes
    ----------
    start_utc : datetime
        Aware UTC start of the bar.
    length : timedelta
        One minute or one hour; the bar ends at ``start_utc + length``.
    open, close, low, high : float
        Quotes over the bar; ``close`` is the last quote before its end.
    volume : float
        As the feed reports it. Zero marks a bar without a tick, which the
        feed fills with the previous close: not a quote of its own.
    """

    start_utc: datetime
    length: timedelta
    open: float
    close: float
    low: float
    high: float
    volume: float


@dataclass(frozen=True, slots=True)
class DukascopyDownload:
    """The exact bytes of one file, with where and when they came from.

    ``day`` is the file's first day: the day of a minute file, the first of
    the month of an hourly one.
    """

    pair: str
    day: date
    side: Side
    url: str
    payload: bytes
    sha256: str
    retrieved_at_utc: datetime


@dataclass(frozen=True, slots=True)
class RateObservation:
    """A mid rate read at an instant.

    Attributes
    ----------
    instant_utc : datetime
        The instant asked for.
    rate : float
        Mean of the bid and ask closes of the bar used, in quote currency per
        unit of base currency (USD per EUR for EURUSD).
    bid, ask : float
        The two closes.
    bar_end_utc : datetime
        End of the bar used: the instant itself, or up to the allowed
        staleness before it.
    """

    instant_utc: datetime
    rate: float
    bid: float
    ask: float
    bar_end_utc: datetime

    @property
    def staleness(self) -> timedelta:
        """Return how long before the instant the bar used ended."""
        return self.instant_utc - self.bar_end_utc


def _require_pair(pair: str) -> int:
    """Return the pair's points per unit, refusing an unsupported pair."""
    if pair not in POINTS:
        raise ValueError(f"unsupported pair {pair!r}; supported: {sorted(POINTS)}")
    return POINTS[pair]


def day_url(pair: str, day: date, side: Side) -> str:
    """Return the address of a day's minute bars; the feed counts months from zero."""
    _require_pair(pair)
    return (
        f"{DATAFEED}/{pair}/{day.year:04d}/{day.month - 1:02d}/{day.day:02d}/"
        f"{side.value}_candles_min_1.bi5"
    )


def month_hours_url(pair: str, year: int, month: int, side: Side) -> str:
    """Return the address of a month's hourly bars; the feed counts months from zero."""
    _require_pair(pair)
    return f"{DATAFEED}/{pair}/{year:04d}/{month - 1:02d}/{side.value}_candles_hour_1.bi5"


def _fetch_with_client_name(url: str) -> bytes:
    """Fetch with a plain client name, which the feed accepts."""
    return http_get_bytes(url, headers={"User-Agent": CLIENT_NAME})


class DukascopySource:
    """Fetch one day's minute bars, as exact bytes.

    Parameters
    ----------
    clock : Callable[[], datetime]
        Returns the aware UTC retrieval instant.
    fetch_bytes : Callable[[str], bytes]
        Fetches an address; by default over HTTPS with a plain client name.
        Tests inject a transport.
    """

    source_id = "DUKASCOPY"

    def __init__(
        self,
        clock: Callable[[], datetime] = utc_now,
        fetch_bytes: Callable[[str], bytes] = _fetch_with_client_name,
    ) -> None:
        self._clock = clock
        self._fetch_bytes = fetch_bytes

    def fetch_day(self, pair: str, day: date, side: Side) -> DukascopyDownload:
        """Download one day's file of minute bars for one side.

        Raises
        ------
        ValueError
            If the pair is not supported; nothing is fetched.
        ProviderError
            If the transport fails, as for any other download.
        """
        return self._download(pair, day, side, day_url(pair, day, side))

    def fetch_month_hours(self, pair: str, year: int, month: int, side: Side) -> DukascopyDownload:
        """Download one month's file of hourly bars for one side.

        Raises
        ------
        ValueError
            If the pair is not supported; nothing is fetched.
        ProviderError
            If the transport fails.
        """
        url = month_hours_url(pair, year, month, side)
        return self._download(pair, date(year, month, 1), side, url)

    def _download(self, pair: str, day: date, side: Side, url: str) -> DukascopyDownload:
        """Fetch an address and keep its exact bytes with their provenance."""
        retrieved = self._clock()
        payload = self._fetch_bytes(url)
        return DukascopyDownload(
            pair=pair,
            day=day,
            side=side,
            url=url,
            payload=payload,
            sha256=hashlib.sha256(payload).hexdigest(),
            retrieved_at_utc=retrieved,
        )


def parse_minute_bars(payload: bytes, pair: str, day: date) -> tuple[QuoteBar, ...]:
    """Decode one day's file of minute bars, oldest first.

    Parameters
    ----------
    payload : bytes
        The file as served: LZMA-compressed records, or empty for a day
        without quotes.
    pair : str
        The pair, which fixes the price unit.
    day : date
        The UTC day the file describes.

    Returns
    -------
    tuple[QuoteBar, ...]
        The bars; none for an empty file.

    Raises
    ------
    ProviderResponseError
        If the file does not decompress, is not a whole number of records, or
        a record is not a minute of that day with positive, ordered prices.
    """
    return _parse(payload, pair, day, timedelta(minutes=1), timedelta(days=1))


def parse_hour_bars(payload: bytes, pair: str, year: int, month: int) -> tuple[QuoteBar, ...]:
    """Decode one month's file of hourly bars, oldest first.

    Raises
    ------
    ProviderResponseError
        As :func:`parse_minute_bars`, for hours of that month.
    """
    days = calendar.monthrange(year, month)[1]
    return _parse(payload, pair, date(year, month, 1), timedelta(hours=1), timedelta(days=days))


def _parse(
    payload: bytes, pair: str, first: date, length: timedelta, span: timedelta
) -> tuple[QuoteBar, ...]:
    """Decode bars of ``length`` starting within ``span`` after ``first``, 00:00 UTC."""
    points = _require_pair(pair)
    if not payload:
        return ()
    try:
        data = lzma.decompress(payload)
    except lzma.LZMAError as error:
        raise ProviderResponseError(f"{pair} {first}: not an LZMA file") from error
    if len(data) % RECORD.size:
        raise ProviderResponseError(f"{pair} {first}: {len(data)} bytes is not whole records")
    origin = datetime.combine(first, time(0, 0), UTC)
    step = int(length.total_seconds())
    limit = int(span.total_seconds())
    bars: list[QuoteBar] = []
    previous = -1
    for offset in range(0, len(data), RECORD.size):
        seconds, opened, closed, low, high, volume = RECORD.unpack_from(data, offset)
        if seconds % step or seconds >= limit or seconds <= previous:
            raise ProviderResponseError(f"{pair} {first}: bar at {seconds}s is out of order")
        if min(opened, closed, low, high) <= 0 or not low <= min(opened, closed):
            raise ProviderResponseError(f"{pair} {first}: bar at {seconds}s has invalid prices")
        if not max(opened, closed) <= high or not math.isfinite(volume):
            raise ProviderResponseError(f"{pair} {first}: bar at {seconds}s has invalid prices")
        previous = seconds
        bars.append(
            QuoteBar(
                start_utc=origin + timedelta(seconds=seconds),
                length=length,
                open=opened / points,
                close=closed / points,
                low=low / points,
                high=high / points,
                volume=float(volume),
            )
        )
    return tuple(bars)


def rate_at(
    bid: Sequence[QuoteBar],
    ask: Sequence[QuoteBar],
    instant_utc: datetime,
    max_staleness: timedelta,
) -> RateObservation | None:
    """Read the mid rate at an instant from the bars that end at or just before it.

    Parameters
    ----------
    bid, ask : Sequence[QuoteBar]
        Bars of each side, of one length, covering the instant.
    instant_utc : datetime
        Aware UTC instant to read the rate at.
    max_staleness : timedelta
        How long before the instant the bar used may end. The bar ending at
        the instant is used when both sides have it; otherwise the latest bar
        both sides share that ends within this delay. A bar without a tick on
        either side (zero volume) is skipped: the feed fills it with an
        earlier close, which would pass for a quote at its end.

    Returns
    -------
    RateObservation | None
        The mid of the two closes, or ``None`` when no shared bar ends within
        the delay: a missing observation, never filled from further back.

    Raises
    ------
    ValueError
        If the instant is naive or the delay is negative.
    """
    if instant_utc.tzinfo is None or instant_utc.utcoffset() != timedelta(0):
        raise ValueError("instant_utc must be aware UTC")
    if max_staleness < timedelta(0):
        raise ValueError("max_staleness must not be negative")
    asks = {bar.start_utc: bar for bar in ask}
    best: tuple[QuoteBar, QuoteBar] | None = None
    for bar in bid:
        end = bar.start_utc + bar.length
        if end > instant_utc or instant_utc - end > max_staleness or bar.start_utc not in asks:
            continue
        if bar.volume <= 0.0 or asks[bar.start_utc].volume <= 0.0:
            continue
        if best is None or bar.start_utc > best[0].start_utc:
            best = (bar, asks[bar.start_utc])
    if best is None:
        return None
    bid_bar, ask_bar = best
    if ask_bar.close < bid_bar.close:
        raise ProviderResponseError(f"crossed quotes at {bid_bar.start_utc}: ask below bid")
    return RateObservation(
        instant_utc=instant_utc,
        rate=(bid_bar.close + ask_bar.close) / 2.0,
        bid=bid_bar.close,
        ask=ask_bar.close,
        bar_end_utc=bid_bar.start_utc + bid_bar.length,
    )
