"""Common contract for every data source."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

import pandas as pd

from quant_backtester.data.instruments import Instrument


@dataclass(frozen=True, slots=True)
class RawDownload:
    """One immutable provider response.

    Attributes
    ----------
    instrument_id : str
        Internal identifier of the instrument requested.
    source : str
        Source identifier, e.g. ``"YAHOO"``.
    fetch_id : str
        Compact UTC timestamp of the fetch, e.g. ``"20260912T210311Z"``. It is
        both the file name under ``raw/`` and the lineage key copied into every
        clean row.
    retrieved_at_utc : datetime
        Timezone-aware UTC instant of the download.
    frame : pd.DataFrame
        Exactly what the provider returned: original column names, original
        dtypes, nothing renamed, nothing dropped.
    request : Mapping[str, object]
        Parameters sent to the provider, plus its library version. Written to
        the manifest so the response can be explained years later.
    """

    instrument_id: str
    source: str
    fetch_id: str
    retrieved_at_utc: datetime
    frame: pd.DataFrame
    request: Mapping[str, object]


class DataSource(Protocol):
    """Uniform download interface.

    An implementation knows one provider's API and nothing about Parquet,
    calendars or the canonical schema.
    """

    source_id: str

    def download(self, instrument: Instrument, start: date, end: date) -> RawDownload:
        """Fetch observations for one instrument.

        Parameters
        ----------
        instrument : Instrument
            Instrument to fetch; the adapter uses ``instrument.source_symbol``.
        start, end : date
            Inclusive requested range.

        Returns
        -------
        RawDownload
            The provider response, unmodified.
        """
        ...

    def download_corporate_actions(
        self, instrument: Instrument, start: date, end: date
    ) -> RawDownload | None:
        """Fetch splits and dividends, when the provider exposes them.

        Parameters
        ----------
        instrument : Instrument
            Instrument to fetch.
        start, end : date
            Inclusive requested range.

        Returns
        -------
        RawDownload | None
            ``None`` when the provider has no corporate action feed.
        """
        ...


def make_fetch_id(retrieved_at_utc: datetime) -> str:
    """Format a UTC instant as a filesystem-safe fetch identifier.

    Parameters
    ----------
    retrieved_at_utc : datetime
        Timezone-aware UTC instant.

    Returns
    -------
    str
        ``"YYYYMMDDTHHMMSSZ"``.

    Raises
    ------
    ValueError
        If ``retrieved_at_utc`` is naive or not UTC.

    Notes
    -----
    Exercice 4.1 (facile). Ce format trie lexicographiquement dans le meme ordre
    que chronologiquement - c'est ce qui rend ``sorted(os.listdir(...))``
    utilisable pour rejouer les snapshots dans l'ordre.
    """
    raise NotImplementedError("Exercice 4.1")
