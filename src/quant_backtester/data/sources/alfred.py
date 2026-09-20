"""ALFRED adapter: a published series as it was known on a given day.

FRED serves the latest vintage of every observation. For a daily market rate
that is harmless - nobody restates what the ten-year traded at. For a macro
aggregate it is look-ahead bias of the purest kind: US GDP for the first
quarter of 2019 was 21 098.827 to anyone reading in January 2020, and
21 115.309 to anyone reading in June 2021. A backtest deciding in 2019 on the
second number is deciding on information that did not exist, and a backtest
re-run next year gets different numbers again from the same code.

ALFRED serves the archive: the series as it stood on a chosen vintage date. The
vintage is declared on the instrument, in committed configuration, so the same
code plus the same config fetches the same numbers for ever - which is the
reproducibility rule applied to a source that would otherwise move under it.

Provider quirks, checked against the live endpoint on 2026-09-20:

- The endpoint is ``alfredgraph.csv``, and its value column carries the vintage:
  ``observation_date,GDP_20200131``.
- ``cosd`` and ``coed`` are inclusive, as on FRED.
- An unknown series id is an HTTP 404.
- A vintage older than the series itself answers with an **empty body**, not a
  header with no rows. That is a legitimate answer - nothing was published
  yet - and it becomes an empty frame rather than an error.

An instrument declares the vintages it wants and how they are read: one pinned
for the whole run, or every one of them, so that each decision can be given the
series as it stood that day. Several vintages come back in a single export -
``id=GDP,GDP&cosd=...,...&coed=...,...&vintage_date=2020-01-31,2021-06-30``
answers with one column per vintage, and the parameters are positional, so the
range has to be repeated as many times as the series is asked for. Sending the
vintages as a single comma-separated list with one ``id`` silently serves the
first of them, which is the kind of provider quirk that turns into a backtest
reading one vintage while believing it read four.
"""

from __future__ import annotations

import io
import urllib.parse
from collections.abc import Callable, Sequence
from datetime import date, datetime

import pandas as pd

from quant_backtester.data.instruments import Instrument
from quant_backtester.data.sources.base import (
    RawDownload,
    http_get_text,
    make_fetch_id,
    utc_now,
)

ALFRED_CSV_URL = "https://alfred.stlouisfed.org/graph/alfredgraph.csv"
"""Public ALFRED graph export: no API key, ``cosd`` and ``coed`` both inclusive."""

ALFRED_DATE_COLUMN = "observation_date"
"""First header field of every ALFRED graph CSV."""


def vintage_column(source_symbol: str, vintage_date: date) -> str:
    """Return the value column ALFRED names a vintage with.

    Parameters
    ----------
    source_symbol : str
        The series id, e.g. ``"GDP"``.
    vintage_date : date
        The vintage asked for.

    Returns
    -------
    str
        ``"GDP_20200131"``. The vintage is in the column name rather than in a
        row, which is the provider's way of letting one file hold several of
        them - and the reason a normalizer cannot simply look for the series id.
    """
    return f"{source_symbol}_{vintage_date.strftime('%Y%m%d')}"


class AlfredSource:
    """Download a pinned vintage of a published series.

    Parameters
    ----------
    clock : Callable[[], datetime]
        Returns the timezone-aware UTC instant of a download. Injected so tests
        never depend on the wall clock.
    fetch_text : Callable[[str], str]
        Performs the HTTP GET and returns the body. Injected so tests never hit
        the network.
    """

    source_id = "ALFRED"

    def __init__(
        self,
        clock: Callable[[], datetime] = utc_now,
        fetch_text: Callable[[str], str] = http_get_text,
    ) -> None:
        self._clock = clock
        self._fetch_text = fetch_text

    def available_from(self, instrument: Instrument) -> None:
        """Return ``None``: the archive serves its whole history.

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
        """Fetch one series as it stood on the instrument's vintage date.

        Parameters
        ----------
        instrument : Instrument
            Instrument to fetch. ``source_symbol`` is the series id and
            ``vintage_dates`` are the days the series is read as of.
        start, end : date
            Inclusive requested range, sent unchanged as ``cosd``/``coed``.

        Returns
        -------
        RawDownload
            Provider response with its original ``observation_date`` and one
            ``<series id>_<vintage>`` column per vintage, every cell kept as
            the string ALFRED sent. The request records the vintages, so the
            raw archive says which ones it holds.

        Raises
        ------
        ValueError
            If the instrument declares no vintage, if one is later than the day
            of the download - a restatement that has not happened yet cannot be
            read - if ``start`` is after ``end``, or if the body is neither
            empty nor an ALFRED series CSV.
        urllib.error.HTTPError
            If ALFRED answers with an HTTP error status, e.g. 404 for an
            unknown series id.
        """
        if start > end:
            raise ValueError(f"start {start} is after end {end}")
        vintages = tuple(instrument.vintage_dates)
        if not vintages:
            raise ValueError(
                f"{instrument.id} is served by ALFRED and declares no vintage_dates; a vintage "
                f"left unsaid is the restated series again, under another name"
            )
        # Read the clock once, before the call: a non-UTC clock fails before any I/O.
        retrieved_at_utc = self._clock()
        ahead = [day for day in vintages if day > retrieved_at_utc.date()]
        if ahead:
            raise ValueError(
                f"{instrument.id} asks for the vintage(s) "
                f"{', '.join(day.isoformat() for day in sorted(ahead))}, which are after "
                f"{retrieved_at_utc.date()}: those restatements have not happened yet"
            )
        asked = sorted(vintages)
        columns = [vintage_column(instrument.source_symbol, day) for day in asked]
        # Positional parameters: one id, one cosd and one coed per vintage. One
        # id with a list of vintages answers with the first of them only.
        query = urllib.parse.urlencode(
            {
                "id": ",".join([instrument.source_symbol] * len(asked)),
                "cosd": ",".join([start.isoformat()] * len(asked)),
                "coed": ",".join([end.isoformat()] * len(asked)),
                "vintage_date": ",".join(day.isoformat() for day in asked),
            }
        )
        url = f"{ALFRED_CSV_URL}?{query}"
        request: dict[str, object] = {
            "series_id": instrument.source_symbol,
            "endpoint": "alfredgraph.csv",
            "url": url,
            "start": start.isoformat(),
            "end_inclusive": end.isoformat(),
            "vintage_dates": [day.isoformat() for day in asked],
            "value_columns": columns,
            # pandas parses the CSV, so its version explains the frame's dtypes.
            "pandas_version": pd.__version__,
        }
        fetch_id = make_fetch_id(retrieved_at_utc)
        text = self._fetch_text(url)
        frame = self._frame_of(text, instrument, columns)
        return RawDownload(
            instrument_id=instrument.id,
            source=self.source_id,
            fetch_id=fetch_id,
            retrieved_at_utc=retrieved_at_utc,
            frame=frame,
            request=request,
        )

    @staticmethod
    def _frame_of(text: str, instrument: Instrument, columns: Sequence[str]) -> pd.DataFrame:
        """Return the body as a frame, empty when the vintage predates the series.

        Notes
        -----
        The CSV is read with ``dtype=str`` and ``keep_default_na=False`` so an
        empty field stays exactly as sent: turning it into a missing value is
        the normalizer's decision, not the raw archive's.
        """
        if not text.strip():
            # A vintage older than the series: nothing had been published, and
            # that is an answer rather than a failure.
            empty: dict[str, list[str]] = {ALFRED_DATE_COLUMN: []}
            empty.update({column: [] for column in columns})
            return pd.DataFrame(empty, dtype=str)
        if not text.startswith(f"{ALFRED_DATE_COLUMN},"):
            raise ValueError(
                f"ALFRED answer for {instrument.source_symbol} is not a series CSV: {text[:100]!r}"
            )
        return pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)

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
        """
        return None
