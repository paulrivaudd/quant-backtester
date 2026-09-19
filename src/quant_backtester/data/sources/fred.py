"""FRED adapter, via the public graph CSV export.

Provider quirks, all handled here and never leaked downstream (checked against
the live endpoint on 2026-09-13):

- The date column is ``observation_date``; older exports called it ``DATE``.
- A day without a value (a US holiday for ``DGS10``) is an empty field; older
  exports wrote ``"."``. Both are kept verbatim and interpreted only by the
  normalizer.
- ``cosd`` and ``coed`` are both inclusive, so unlike Yahoo no shift is needed.
- An unknown series id is an HTTP 404 with an HTML body.

FRED is a restated series, not a point-in-time one: the CSV shows the latest
vintage of every observation. A daily market rate such as ``DGS10`` is stable in
practice; a revised macro aggregate is not, and would need true vintages
(ALFRED) rather than this adapter.
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

FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
"""Public FRED graph export: no API key, ``cosd`` and ``coed`` both inclusive."""

FRED_DATE_COLUMN = "observation_date"
"""First header field of every FRED graph CSV."""


class FredSource:
    """Download published series from FRED (levels only).

    Parameters
    ----------
    clock : Callable[[], datetime]
        Returns the timezone-aware UTC instant of a download. Injected so tests
        never depend on the wall clock.
    fetch_text : Callable[[str], str]
        Performs the HTTP GET and returns the body. Injected so tests never hit
        the network.
    """

    source_id = "FRED"

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
        """Fetch one published series.

        Parameters
        ----------
        instrument : Instrument
            Instrument to fetch; ``instrument.source_symbol`` is the FRED series
            id, e.g. ``"DGS10"``.
        start, end : date
            Inclusive requested range, sent unchanged as ``cosd``/``coed``.

        Returns
        -------
        RawDownload
            Provider response with its original ``observation_date`` and
            ``<series id>`` columns, every cell kept as the string FRED sent.

        Raises
        ------
        ValueError
            If ``start`` is after ``end``, if the clock is not UTC, or if the
            body is not a FRED series CSV.
        urllib.error.HTTPError
            If FRED answers with an HTTP error status, e.g. 404 for an unknown
            series id.

        Notes
        -----
        Exercice 4.4 (facile). L'endpoint CSV public suffit et evite une
        dependance.

        The CSV is read with ``dtype=str`` and ``keep_default_na=False`` so an
        empty field or a ``"."`` stays exactly as sent: turning it into a
        missing value is the normalizer's decision, not the raw archive's.
        """
        if start > end:
            raise ValueError(f"start {start} is after end {end}")
        query = urllib.parse.urlencode(
            {"id": instrument.source_symbol, "cosd": start.isoformat(), "coed": end.isoformat()}
        )
        url = f"{FRED_CSV_URL}?{query}"
        request: dict[str, object] = {
            "series_id": instrument.source_symbol,
            "endpoint": "fredgraph.csv",
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
        # Check the header before parsing: an HTML error page or an empty body
        # would otherwise fail inside pandas with a far less useful message.
        if not text.startswith(f"{FRED_DATE_COLUMN},"):
            raise ValueError(
                f"FRED answer for {instrument.source_symbol} is not a series CSV: {text[:100]!r}"
            )
        frame = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
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
        """Return ``None``: a published series has no corporate actions.

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
        Exercice 4.5 (trivial).
        """
        return None
