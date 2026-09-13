"""Euronext adapter, via the historical price export of live.euronext.com.

Provider quirks, all handled here and never leaked downstream (checked against
the live endpoint on 2026-09-13):

- ``instrument.source_symbol`` is ``<ISIN>-<MIC>``, e.g. ``"LU1681043599-XPAR"``.
- Prices are the exchange's own and raw: no split or dividend adjustment. The
  ``adjusted`` query parameter changes nothing (TotalEnergies around its
  2 January 2025 ex-date is identical with ``N``, ``Y`` and empty).
- The CSV opens with three preamble lines (a title, the requested period, the
  ISIN) before a ``;``-separated header. Dates are ``dd/mm/yyyy`` whatever
  ``date_form`` asks for, rows come newest first, and every data row carries one
  more field than the header names: the day's VWAP (turnover over shares).
- Only about two years are served. A request reaching further back is cut to
  that window without any error, and an unknown ISIN answers 200 with no row,
  exactly like a weekend. Both are detected here and raised.
- This export carries no corporate actions.

Terms of use: Euronext restricts downloading its content without written
permission. This adapter serves personal, non-redistributed research: nothing it
fetches is committed (``raw/`` is git-ignored).

Euronext serves the current state of its history; ``raw/`` keeps what we saw.
"""

from __future__ import annotations

import csv
import re
import urllib.parse
from collections.abc import Callable
from datetime import date, datetime, timedelta

import pandas as pd

from quant_backtester.data.instruments import Instrument
from quant_backtester.data.sources.base import (
    RawDownload,
    http_get_text,
    make_fetch_id,
    utc_now,
)

EURONEXT_DOWNLOAD_URL = "https://live.euronext.com/en/ajax/AwlHistoricalPrice/getFullDownloadAjax"
"""Historical price export of live.euronext.com: no API key, both dates inclusive."""

EURONEXT_TITLE = '"Historical Data"'
"""First line of every export."""

EURONEXT_HEADER_PREFIX: tuple[str, ...] = ("Date", "Open", "High", "Low", "Last", "Close")
"""Leading header fields every export must carry."""

EURONEXT_DATE_FORMAT = "%d/%m/%Y"
"""Date format of the export, whatever ``date_form`` requests."""

EURONEXT_SYMBOL = re.compile(r"^(?P<isin>[A-Z]{2}[A-Z0-9]{9}[0-9])-(?P<mic>[A-Z]{4})$")
"""``<ISIN>-<MIC>``: a 12-character ISIN and a 4-letter market identifier code."""

SESSION_FREE_SPAN = timedelta(days=7)
"""No Euronext venue closes for a week: seven days without a row is not a holiday."""


def split_euronext_symbol(source_symbol: str) -> tuple[str, str]:
    """Split a Euronext symbol into its ISIN and market identifier code.

    Parameters
    ----------
    source_symbol : str
        ``<ISIN>-<MIC>``, e.g. ``"LU1681043599-XPAR"``.

    Returns
    -------
    tuple[str, str]
        ``(isin, mic)``, e.g. ``("LU1681043599", "XPAR")``.

    Raises
    ------
    ValueError
        If the symbol does not have that shape.
    """
    match = EURONEXT_SYMBOL.match(source_symbol)
    if match is None:
        raise ValueError(f"Euronext symbol must be '<ISIN>-<MIC>', got {source_symbol!r}")
    return match["isin"], match["mic"]


def parse_euronext_csv(text: str, isin: str) -> pd.DataFrame:
    """Parse a Euronext export into a frame of strings, columns as published.

    Parameters
    ----------
    text : str
        Body of the export, byte order mark included or not.
    isin : str
        ISIN requested, which the export must echo.

    Returns
    -------
    pd.DataFrame
        One row per session as the exchange sent it, newest first, every cell a
        string. Fields beyond the named header are kept as ``unnamed_<position>``.
        With no row, the frame carries the header columns only.

    Raises
    ------
    ValueError
        If the body is not a Euronext export, echoes another ISIN, lacks the
        expected header, or holds rows of uneven or too short width.
    """
    lines = text.lstrip("﻿").splitlines()
    if len(lines) < 4 or lines[0].strip() != EURONEXT_TITLE:
        raise ValueError(f"Euronext answer for {isin} is not a price export: {text[:100]!r}")
    if lines[2].strip() != isin:
        raise ValueError(f"Euronext answer for {isin} describes {lines[2].strip()!r}")
    header = next(csv.reader([lines[3]], delimiter=";"))
    if tuple(header[: len(EURONEXT_HEADER_PREFIX)]) != EURONEXT_HEADER_PREFIX:
        raise ValueError(f"Euronext answer for {isin} has an unexpected header: {lines[3]!r}")
    rows = [next(csv.reader([line], delimiter=";")) for line in lines[4:] if line.strip()]
    if not rows:
        return pd.DataFrame(columns=header)
    widths = sorted({len(row) for row in rows})
    if len(widths) > 1 or widths[0] < len(header):
        raise ValueError(f"Euronext answer for {isin} has rows of width {widths}")
    columns = header + [f"unnamed_{position}" for position in range(len(header), widths[0])]
    return pd.DataFrame(rows, columns=columns)


def _require_served_range(
    frame: pd.DataFrame, instrument: Instrument, start: date, end: date, retrieved_on: date
) -> None:
    """Raise when Euronext silently served less than was requested.

    The expected span runs from ``start`` (or the first session, if later) to
    ``end`` (or the last session, or the retrieval day, if earlier). A week of it
    without a row at the start means an unknown ISIN or a request older than the
    two-year window; the end is not checked, since the latest session may not be
    published yet.

    Parameters
    ----------
    frame : pd.DataFrame
        Parsed export.
    instrument : Instrument
        Instrument requested, for its listing bounds.
    start, end : date
        Inclusive requested range.
    retrieved_on : date
        UTC day of the download.

    Raises
    ------
    ValueError
        If the first row, or the absence of any, leaves a week of the expected
        span uncovered, or if a date is not ``dd/mm/yyyy``.
    """
    expected_start = start
    if instrument.first_session is not None:
        expected_start = max(expected_start, instrument.first_session)
    expected_end = min(end, retrieved_on)
    if instrument.last_session is not None:
        expected_end = min(expected_end, instrument.last_session)
    if expected_end < expected_start:
        return
    if frame.empty:
        # expected_end - expected_start >= 6 days means seven calendar days.
        if expected_end - expected_start >= SESSION_FREE_SPAN - timedelta(days=1):
            raise ValueError(
                f"Euronext served no row for {instrument.source_symbol} from {expected_start} "
                f"to {expected_end}: unknown ISIN, or older than its two-year window"
            )
        return
    first = min(
        datetime.strptime(str(value), EURONEXT_DATE_FORMAT).date() for value in frame["Date"]
    )
    if first - expected_start >= SESSION_FREE_SPAN:
        raise ValueError(
            f"Euronext served {instrument.source_symbol} only from {first}, not from "
            f"{expected_start}: the request is older than its two-year window"
        )


class EuronextSource:
    """Download raw daily bars from the Euronext historical price export.

    Parameters
    ----------
    clock : Callable[[], datetime]
        Returns the timezone-aware UTC instant of a download. Injected so tests
        never depend on the wall clock.
    fetch_text : Callable[[str], str]
        Performs the HTTP GET and returns the body. Injected so tests never hit
        the network.
    """

    source_id = "EURONEXT"

    def __init__(
        self,
        clock: Callable[[], datetime] = utc_now,
        fetch_text: Callable[[str], str] = http_get_text,
    ) -> None:
        self._clock = clock
        self._fetch_text = fetch_text

    def download(self, instrument: Instrument, start: date, end: date) -> RawDownload:
        """Fetch daily bars.

        Parameters
        ----------
        instrument : Instrument
            Instrument to fetch; ``instrument.source_symbol`` is ``<ISIN>-<MIC>``.
        start, end : date
            Inclusive requested range, sent unchanged.

        Returns
        -------
        RawDownload
            The export's rows with their original columns, every cell a string.

        Raises
        ------
        ValueError
            If ``start`` is after ``end``, the symbol is malformed, the clock is
            not UTC, the body is not a Euronext export, or less than the
            requested range was served (see :func:`_require_served_range`).
        urllib.error.HTTPError
            If Euronext answers with an HTTP error status.
        """
        if start > end:
            raise ValueError(f"start {start} is after end {end}")
        isin, mic = split_euronext_symbol(instrument.source_symbol)
        query = urllib.parse.urlencode(
            {
                "format": "csv",
                "decimal_separator": ".",
                "date_form": "d/m/Y",
                "op": "",
                "adjusted": "",
                "base100": "",
                "startdate": start.isoformat(),
                "enddate": end.isoformat(),
            }
        )
        url = f"{EURONEXT_DOWNLOAD_URL}/{isin}-{mic}?{query}"
        request: dict[str, object] = {
            "isin": isin,
            "mic": mic,
            "url": url,
            "start": start.isoformat(),
            "end_inclusive": end.isoformat(),
            # pandas builds the frame, so its version explains the frame's dtypes.
            "pandas_version": pd.__version__,
        }
        # Read the clock once, before the call: a non-UTC clock fails before any I/O.
        retrieved_at_utc = self._clock()
        fetch_id = make_fetch_id(retrieved_at_utc)
        frame = parse_euronext_csv(self._fetch_text(url), isin)
        _require_served_range(frame, instrument, start, end, retrieved_at_utc.date())
        return RawDownload(
            instrument_id=instrument.id,
            source=self.source_id,
            fetch_id=fetch_id,
            retrieved_at_utc=retrieved_at_utc,
            frame=frame,
            request=request,
        )

    def download_corporate_actions(
        self, instrument: Instrument, start: date, end: date
    ) -> RawDownload | None:
        """Return ``None``: the Euronext export carries no corporate actions.

        Parameters
        ----------
        instrument : Instrument
            Ignored.
        start, end : date
            Ignored.

        Returns
        -------
        RawDownload | None
            Always ``None``.
        """
        return None
