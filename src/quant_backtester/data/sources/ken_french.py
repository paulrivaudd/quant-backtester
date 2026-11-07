"""Ken French monthly USD research returns, RESTATED and not point-in-time.

Industry portfolios are value-weighted, dividend-included research returns,
not tradable ETF prices. Histories begin in July 1926. Retrieval time records
when this vintage was observed, never when historical returns were available.
ZIP and CSV parsing uses only the standard library. No daily bar interface is
provided: monthly returns must not be ingested as prices or published levels.
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from zipfile import BadZipFile, ZipFile

from quant_backtester.data.sources.base import (
    ProviderResponseError,
    http_get_bytes,
    make_fetch_id,
    utc_now,
)

BASE_URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
_INDUSTRY_SECTION = "Average Value Weighted Returns -- Monthly"


class KenFrenchDataset(Enum):
    """Allowlisted official monthly datasets; no annual or equal-weight option."""

    INDUSTRY_10 = "10_Industry_Portfolios"
    INDUSTRY_49 = "49_Industry_Portfolios"
    FACTORS = "F-F_Research_Data_Factors"


@dataclass(frozen=True, slots=True)
class KenFrenchDownload:
    """Immutable raw snapshot, including the exact ZIP and original CSV cells.

    Attributes
    ----------
    retrieved_at_utc : datetime
        Aware UTC retrieval instant, not historical publication time.
    rows : tuple
        Selected monthly rows, with YYYYMM followed by raw percent strings.
    start, end : date
        Inclusive month labels (first day of each month).
    revision_policy : str
        Always RESTATED; this download cannot establish historical knowledge.
    """

    dataset: KenFrenchDataset
    url: str
    member: str
    payload: bytes
    sha256: str
    retrieved_at_utc: datetime
    fetch_id: str
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    start: date
    end: date
    source: str = "KEN_FRENCH"
    revision_policy: str = "RESTATED"
    currency: str = "USD"
    frequency: str = "monthly"
    units: str = "percent"


@dataclass(frozen=True, slots=True)
class MonthlyReturns:
    """Fractional monthly returns; None represents a provider missing sentinel.

    Dates label months, not availability instants. ``Mkt`` is constructed as
    ``Mkt-RF + RF`` only when both inputs exist. The original snapshot carries
    provenance and must accompany these restated research observations.
    """

    raw: KenFrenchDownload
    columns: tuple[str, ...]
    months: tuple[date, ...]
    values: tuple[tuple[float | None, ...], ...]
    units: str = "fraction"


def _month(value: str) -> date:
    if not re.fullmatch(r"[0-9]{6}", value):
        raise ProviderResponseError(f"Invalid monthly date: {value!r}")
    try:
        return date(int(value[:4]), int(value[4:]), 1)
    except ValueError as error:
        raise ProviderResponseError(f"Invalid monthly date: {value!r}") from error


def _fraction(value: str) -> float | None:
    try:
        number = float(value)
    except ValueError as error:
        raise ProviderResponseError(f"Invalid return: {value!r}") from error
    if not math.isfinite(number):
        raise ProviderResponseError(f"Nonfinite return: {value!r}")
    return None if number in (-99.99, -999.0) else number / 100.0


def _parse(
    text: str, dataset: KenFrenchDataset
) -> tuple[tuple[str, ...], tuple[tuple[str, ...], ...]]:
    records = list(csv.reader(io.StringIO(text), strict=True))
    if dataset is KenFrenchDataset.FACTORS:
        headers = [
            i
            for i, row in enumerate(records)
            if tuple(cell.strip() for cell in row) == ("", "Mkt-RF", "SMB", "HML", "RF")
        ]
        # Annual tables repeat the same header: only the first is monthly.
        if not headers:
            raise ProviderResponseError("Missing monthly factor header")
        index = headers[0]
    else:
        sections = [
            i
            for i, row in enumerate(records)
            if len(row) == 1 and row[0].strip() == _INDUSTRY_SECTION
        ]
        if len(sections) != 1:
            raise ProviderResponseError("Expected one value-weighted monthly section")
        index = sections[0] + 1
        while index < len(records) and not any(cell.strip() for cell in records[index]):
            index += 1
    if index >= len(records):
        raise ProviderResponseError("Missing monthly header")
    header = tuple(cell.strip() for cell in records[index])
    expected = {
        KenFrenchDataset.INDUSTRY_10: 10,
        KenFrenchDataset.INDUSTRY_49: 49,
        KenFrenchDataset.FACTORS: 4,
    }[dataset]
    if (
        len(header) != expected + 1
        or header[0]
        or any(not cell for cell in header[1:])
        or len(set(header[1:])) != expected
    ):
        raise ProviderResponseError("Invalid monthly columns")
    rows = []
    previous = None
    for row in records[index + 1 :]:
        if not any(cell.strip() for cell in row):
            break
        if len(row) != len(header):
            raise ProviderResponseError("Invalid monthly row width")
        month = _month(row[0].strip())
        ordinal = month.year * 12 + month.month
        if previous is not None and ordinal != previous + 1:
            raise ProviderResponseError("Duplicate, unordered month or month gap")
        previous = ordinal
        for cell in row[1:]:
            _fraction(cell)
        rows.append(tuple(row))
    if not rows:
        raise ProviderResponseError("Empty monthly table")
    return header[1:], tuple(rows)


class KenFrenchSource:
    """Fetch allowlisted official ZIPs with injected transport and UTC clock.

    Parameters
    ----------
    clock : Callable
        Returns an aware UTC retrieval instant.
    fetch_bytes : Callable
        Fetches a URL as bytes; defaults to the shared HTTP helper.
    """

    source_id = "KEN_FRENCH"

    def __init__(
        self,
        clock: Callable[[], datetime] = utc_now,
        fetch_bytes: Callable[[str], bytes] = http_get_bytes,
    ) -> None:
        self._clock = clock
        self._fetch_bytes = fetch_bytes

    def download(self, dataset: KenFrenchDataset, start: date, end: date) -> KenFrenchDownload:
        """Retrieve a restated snapshot for inclusive first-of-month labels.

        The full selected table is retained and validated before normalization
        filters the requested range. No historical publication time is inferred.
        Missing boundary months are rejected, including pre-July-1926 requests.
        """
        if not isinstance(dataset, KenFrenchDataset):
            raise ValueError("dataset must be a KenFrenchDataset")
        if start > end or start.day != 1 or end.day != 1:
            raise ValueError("Expected ordered first-of-month bounds")
        retrieved = self._clock()
        fetch_id = make_fetch_id(retrieved)
        url = f"{BASE_URL}{dataset.value}_CSV.zip"
        payload = self._fetch_bytes(url)
        expected = f"{dataset.value}.csv"
        try:
            with ZipFile(io.BytesIO(payload)) as archive:
                members = [info for info in archive.infolist() if not info.is_dir()]
                if len(members) != 1 or members[0].filename.casefold() != expected.casefold():
                    raise ProviderResponseError("Unexpected or ambiguous ZIP member")
                member = members[0].filename
                text = archive.read(members[0]).decode("utf-8-sig")
            columns, rows = _parse(text, dataset)
        except (BadZipFile, UnicodeError, csv.Error, EOFError) as error:
            raise ProviderResponseError("Unreadable Ken French ZIP CSV") from error
        if start < _month(rows[0][0].strip()) or end > _month(rows[-1][0].strip()):
            raise ProviderResponseError("Requested monthly range is unavailable")
        return KenFrenchDownload(
            dataset,
            url,
            member,
            payload,
            hashlib.sha256(payload).hexdigest(),
            retrieved,
            fetch_id,
            columns,
            rows,
            start,
            end,
        )


def normalize_monthly_returns(raw: KenFrenchDownload) -> MonthlyReturns:
    """Convert raw percent returns to fractions without mutating the snapshot.

    Parameters
    ----------
    raw : KenFrenchDownload
        One downloaded table: monthly rows of percent returns, as published.

    Returns
    -------
    MonthlyReturns
        Fractions (``0.0123`` for 1.23%) for the months of the requested
        range, each labelled by its first day: a month, not the instant it
        became available. Missing sentinels are ``None``.

    Raises
    ------
    ProviderResponseError
        If a month label or a cell is not a number the library publishes.

    Notes
    -----
    Both -99.99 and -999 are missing, never extreme losses. Factor snapshots
    retain all factors and append the dividend-included USD market return Mkt.
    This operation does not make RESTATED data point-in-time safe.
    """
    months = []
    values = []
    factors = raw.dataset is KenFrenchDataset.FACTORS
    for row in raw.rows:
        month = _month(row[0].strip())
        if not raw.start <= month <= raw.end:
            continue
        converted = tuple(_fraction(cell) for cell in row[1:])
        if factors:
            excess, risk_free = converted[0], converted[3]
            market = None if excess is None or risk_free is None else excess + risk_free
            converted += (market,)
        months.append(month)
        values.append(converted)
    return MonthlyReturns(
        raw, raw.columns + (("Mkt",) if factors else ()), tuple(months), tuple(values)
    )
