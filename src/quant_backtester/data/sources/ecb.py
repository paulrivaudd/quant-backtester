"""ECB adapter, for the euro foreign exchange reference rates.

Provider quirks, all handled here and never leaked downstream (checked against
the live ECB Data Portal API on 2026-09-13):

- ``instrument.source_symbol`` is ``<dataflow>.<series key>``, e.g.
  ``"EXR.D.USD.EUR.SP00.A"``; the API wants the two as separate path segments.
- ``format=csvdata`` returns one row per observation carrying every SDMX
  attribute: ``KEY``, ``TIME_PERIOD``, ``OBS_VALUE``, ``OBS_STATUS``, ``TITLE``...
  All are kept, as the strings the ECB sent.
- ``startPeriod`` and ``endPeriod`` are both inclusive.
- A TARGET holiday (25 and 26 December) has no row at all, not an empty value.
- A range without any observation (a weekend) is HTTP 200 with an empty body;
  an unknown series or dataflow is HTTP 404.
- The rate is quoted in units of foreign currency per euro (USD per EUR).

The API serves only the current vintage of a series: ``raw/`` is what keeps the
record of what we saw on each fetch.
"""

from __future__ import annotations

import io
import urllib.parse
from collections.abc import Callable
from datetime import date, datetime

import pandas as pd

from quant_backtester.data.instruments import Instrument
from quant_backtester.data.sources.base import (
    RawDownload,
    http_get_text,
    make_fetch_id,
    utc_now,
)

ECB_DATA_URL = "https://data-api.ecb.europa.eu/service/data"
"""ECB Data Portal SDMX REST data endpoint: no API key, both period bounds inclusive."""

ECB_KEY_COLUMN = "KEY"
"""First header field of every ``format=csvdata`` answer."""


def split_ecb_symbol(source_symbol: str) -> tuple[str, str]:
    """Split an ECB symbol into its dataflow and series key.

    Parameters
    ----------
    source_symbol : str
        ``<dataflow>.<series key>``, e.g. ``"EXR.D.USD.EUR.SP00.A"``.

    Returns
    -------
    tuple[str, str]
        ``(dataflow, series_key)``, e.g. ``("EXR", "D.USD.EUR.SP00.A")``.

    Raises
    ------
    ValueError
        If either part is missing.
    """
    flow, dot, series_key = source_symbol.partition(".")
    if not dot or not flow or not series_key:
        raise ValueError(f"ECB symbol must be '<dataflow>.<series key>', got {source_symbol!r}")
    return flow, series_key


class EcbSource:
    """Download ECB reference rates (levels only).

    The ECB publishes its reference rates once a day, around 16:00 CET, for the
    same day. That release time is the instrument's ``PublicationRule``; it is
    not an exchange close and must not be derived from a calendar.

    Parameters
    ----------
    clock : Callable[[], datetime]
        Returns the timezone-aware UTC instant of a download. Injected so tests
        never depend on the wall clock.
    fetch_text : Callable[[str], str]
        Performs the HTTP GET and returns the body. Injected so tests never hit
        the network.
    """

    source_id = "ECB"

    def __init__(
        self,
        clock: Callable[[], datetime] = utc_now,
        fetch_text: Callable[[str], str] = http_get_text,
    ) -> None:
        self._clock = clock
        self._fetch_text = fetch_text

    def available_from(self, instrument: Instrument) -> None:
        """Return ``None``: this provider serves its whole history.

        Parameters
        ----------
        instrument : Instrument
            Ignored.

        Returns
        -------
        None
            No window to work around.
        """
        return None

    def download(self, instrument: Instrument, start: date, end: date) -> RawDownload:
        """Fetch one reference series from the ECB data portal.

        Parameters
        ----------
        instrument : Instrument
            Instrument to fetch; ``instrument.source_symbol`` is
            ``<dataflow>.<series key>``.
        start, end : date
            Inclusive requested range, sent unchanged as
            ``startPeriod``/``endPeriod``.

        Returns
        -------
        RawDownload
            Provider response with its original SDMX columns, every cell kept as
            the string the ECB sent. An empty frame, without columns, when the
            range holds no observation.

        Raises
        ------
        ValueError
            If ``start`` is after ``end``, if the symbol is malformed, if the
            clock is not UTC, or if a non-empty body is not an ECB CSV.
        urllib.error.HTTPError
            If the ECB answers with an HTTP error status, e.g. 404 for an unknown
            series.

        Notes
        -----
        Exercice 4.6 (facile).
        """
        if start > end:
            raise ValueError(f"start {start} is after end {end}")
        flow, series_key = split_ecb_symbol(instrument.source_symbol)
        query = urllib.parse.urlencode(
            {"startPeriod": start.isoformat(), "endPeriod": end.isoformat(), "format": "csvdata"}
        )
        url = f"{ECB_DATA_URL}/{urllib.parse.quote(flow)}/{urllib.parse.quote(series_key)}?{query}"
        request: dict[str, object] = {
            "flow": flow,
            "series_key": series_key,
            "format": "csvdata",
            "url": url,
            "start": start.isoformat(),
            "end_inclusive": end.isoformat(),
            # pandas parses the CSV, so its version explains the frame's dtypes.
            "pandas_version": pd.__version__,
        }
        # Read the clock once, before the call: a non-UTC clock fails before any I/O.
        retrieved_at_utc = self._clock()
        fetch_id = make_fetch_id(retrieved_at_utc)
        text = self._fetch_text(url)
        if not text.strip():
            # A range without any observation (a weekend, a TARGET holiday) is an
            # empty 200 answer: nothing to parse, and nothing is wrong.
            frame = pd.DataFrame()
        elif text.startswith(f"{ECB_KEY_COLUMN},"):
            frame = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
        else:
            raise ValueError(
                f"ECB answer for {instrument.source_symbol} is not a series CSV: {text[:100]!r}"
            )
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
        """Return ``None``: a reference rate has no corporate actions.

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

        Notes
        -----
        Exercice 4.7 (trivial).
        """
        return None
