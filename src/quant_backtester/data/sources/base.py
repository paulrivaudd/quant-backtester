"""Common contract and shared helpers for every data source."""

from __future__ import annotations

import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Protocol

import pandas as pd

from quant_backtester.data.instruments import Instrument


class ProviderError(Exception):
    """A provider failed to serve what was asked of it.

    Every adapter raises one of these, and nothing else, when the fault lies
    with the provider. That is the whole point of the family: a missing second
    opinion is degraded into a warning and the ingestion carries on, while a
    ``TypeError`` or an ``AttributeError`` - a bug in our own parsing - keeps
    travelling up and stops the run. Catching every exception made the two
    indistinguishable, and a broken adapter looked exactly like a provider
    being down.
    """


class ProviderUnavailable(ProviderError):
    """The provider could not answer: down, unreachable, or timing out."""


class ProviderRateLimited(ProviderUnavailable):
    """The provider refused to answer this soon. A retry later may work."""


class ProviderResponseError(ProviderError):
    """The provider answered something this adapter cannot read.

    An HTML error page where a CSV was expected, a body echoing another series,
    a header that moved. The response is evidence, not data.
    """


class ProviderRangeUnavailable(ProviderError):
    """The provider does not hold the whole requested range.

    Not a failure of the provider, and not a reason to lose it: Euronext keeps
    a rolling window of about two years and simply has nothing older. Asking it
    for 2018 must cost the sessions of 2018 only, not the cross-check of every
    session since.

    Parameters
    ----------
    message : str
        What was asked and what was served.
    available_from : date | None
        Earliest date the provider turned out to hold, when its answer says so.
        The caller retries from there rather than giving the source up.

    Attributes
    ----------
    available_from : date | None
        As above.
    """

    def __init__(self, message: str, *, available_from: date | None = None) -> None:
        super().__init__(message)
        self.available_from = available_from


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

    def available_from(self, instrument: Instrument) -> date | None:
        """Return the earliest date this provider can serve for ``instrument``.

        Parameters
        ----------
        instrument : Instrument
            Instrument concerned; a window may depend on it.

        Returns
        -------
        date | None
            ``None`` when the provider has no such limit. Declared rather than
            discovered so an ordinary update does not have to fail once to find
            out - the failure remains the safety net when a window moves.
        """
        ...

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
    if retrieved_at_utc.tzinfo is None:
        raise ValueError(f"retrieved_at_utc must be timezone-aware, got {retrieved_at_utc!r}")
    # The offset alone is not enough: Europe/London is +00:00 in winter only.
    if retrieved_at_utc.utcoffset() != timedelta(0) or retrieved_at_utc.tzname() != "UTC":
        raise ValueError(f"retrieved_at_utc must be UTC, got {retrieved_at_utc.tzinfo!r}")
    return retrieved_at_utc.strftime("%Y%m%dT%H%M%SZ")


def utc_now() -> datetime:
    """Return the current timezone-aware UTC instant.

    The default ``clock`` of every adapter and the only wall-clock read of the
    sources package. Tests inject a fixed clock instead.

    Returns
    -------
    datetime
        Wall-clock instant whose ``tzinfo`` is UTC.
    """
    return datetime.now(UTC)


HTTP_TOO_MANY_REQUESTS = 429
"""Status a provider answers when it refuses to be asked this often."""

HTTP_SERVER_ERROR = 500
"""First status that means the provider, not the request, is at fault."""

HTTP_TIMEOUT_SECONDS = 120.0
"""Socket timeout of :func:`http_get_text`, in seconds. Infrastructure, not research.

Generous because a first ingestion asks for a whole history in one request: the
ECB needs well over thirty seconds to serve the daily euro reference rates since
1999, and timing out there leaves the series unfetchable rather than slow.
"""


def http_get_text(url: str) -> str:
    """Return the body of an HTTP GET on ``url``, decoded as UTF-8.

    The default ``fetch_text`` of the HTTP-based adapters. Tests inject a fake
    instead, so they never hit the network.

    Parameters
    ----------
    url : str
        Absolute ``https`` URL.

    Returns
    -------
    str
        Response body.

    Raises
    ------
    ProviderRateLimited
        If the server answers 429.
    ProviderUnavailable
        If the server answers 5xx, or could not be reached at all.
    ProviderResponseError
        If the server answers any other error status.

    Notes
    -----
    Every failure here is the provider's, so every one of them is translated
    into the :class:`ProviderError` family. The underlying ``HTTPError`` or
    ``URLError`` stays chained as the cause, and its response is closed before
    it propagates: left to the garbage collector, the socket surfaces as a
    ``ResourceWarning``, which the test suite treats as an error.

    The distinction the layers above act on is between a provider that cannot
    answer and one that answers something unreadable. The first is transient and
    costs a cross-check; the second means a symbol or a format moved, and has to
    be looked at rather than absorbed.
    """
    try:
        with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT_SECONDS) as response:
            body: bytes = response.read()
    except urllib.error.HTTPError as error:
        error.close()
        if error.code == HTTP_TOO_MANY_REQUESTS:
            raise ProviderRateLimited(f"HTTP {error.code} on {url}") from error
        if error.code >= HTTP_SERVER_ERROR:
            raise ProviderUnavailable(f"HTTP {error.code} on {url}") from error
        raise ProviderResponseError(f"HTTP {error.code} on {url}") from error
    except urllib.error.URLError as error:
        raise ProviderUnavailable(f"{url} could not be reached: {error.reason}") from error
    except TimeoutError as error:
        raise ProviderUnavailable(f"{url} timed out after {HTTP_TIMEOUT_SECONDS}s") from error
    return body.decode("utf-8")
