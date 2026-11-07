"""State Street official USD NAV workbooks, never exchange prices.

The dated workbook contains no historical publication timestamps. Retrieval
is evidence of availability now, not at the US close of the observation day.
The adapter therefore does not invent a historical publication rule. Exact
bytes and the response hash are exposed for immutable acquisition archives.
"""

from __future__ import annotations

import hashlib
import io
import math
import re
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd

from quant_backtester.data.instruments import DataType, Instrument
from quant_backtester.data.sources.base import (
    ProviderResponseError,
    RawDownload,
    http_get_bytes,
    make_fetch_id,
    utc_now,
)

SSGA_SITE = "https://www.ssga.com"
NAV_ROOT = f"{SSGA_SITE}/library-content/products/fund-data/etfs/emea"
_NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_MONTHS = {
    m: n
    for n, m in enumerate(
        ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1
    )
}


def nav_date(value: str) -> date:
    """Parse the issuer's English dates without depending on the host locale.

    Parameters
    ----------
    value : str
        A date as the workbook prints it, such as ``"06-Nov-2026"``.

    Returns
    -------
    date
        The valuation date the row describes: not the day the NAV was
        published, which the workbook does not state.

    Raises
    ------
    ProviderResponseError
        If the text is not a ``DD-Mon-YYYY`` date with an English month.
    """
    try:
        day, month, year = value.split("-")
        return date(int(year), _MONTHS[month], int(day))
    except (ValueError, KeyError) as error:
        raise ProviderResponseError(f"Invalid State Street date: {value!r}") from error


@dataclass(frozen=True)
class NavWorkbook:
    """Validated identity, original string-valued rows and exact issuer bytes."""

    isin: str
    currency: str
    report_date: date
    fund_name: str
    frame: pd.DataFrame
    payload: bytes

    @property
    def sha256(self) -> str:
        """Return the exact response's content hash."""
        return hashlib.sha256(self.payload).hexdigest()


def parse_nav_workbook(payload: bytes, *, isin: str) -> NavWorkbook:
    """Read the issuer's navhist sheet and reject identity/schema/value changes.

    Parameters
    ----------
    payload : bytes
        The exact XLSX bytes the issuer served.
    isin : str
        The fund the workbook must describe.

    Returns
    -------
    NavWorkbook
        The fund's identity and report date, the original string-valued rows
        (dates as printed, NAV per share in USD) and the exact bytes. Rows
        carry valuation dates only, no publication instant.

    Raises
    ------
    ProviderResponseError
        If the workbook is malformed or unpacks to more than 25 MB, describes
        another fund or a currency other than USD, its header or footer
        changed, a cell is a formula, a date repeats or follows the report
        date, or a NAV is not finite and positive.

    Notes
    -----
    This deliberately supports only the observed plain-text date format and
    cached scalar cells. Formula cells, duplicate dates, nonpositive NAVs,
    unknown columns and another fund/currency are errors, never repairs.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            if sum(i.file_size for i in archive.infolist()) > 25_000_000:
                raise ProviderResponseError("NAV workbook is unexpectedly large")
            workbook = ET.fromstring(archive.read("xl/workbook.xml"))
            sheets = workbook.findall("s:sheets/s:sheet", _NS)
            if len(sheets) != 1 or sheets[0].get("name") != "navhist":
                raise ProviderResponseError("Expected one navhist worksheet")
            strings = []
            if "xl/sharedStrings.xml" in archive.namelist():
                root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
                strings = ["".join(si.itertext()) for si in root]
            root = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
            rows: list[dict[str, str]] = []
            for row in root.findall("s:sheetData/s:row", _NS):
                cells: dict[str, str] = {}
                for cell in row.findall("s:c", _NS):
                    if cell.find("s:f", _NS) is not None:
                        raise ProviderResponseError("Formula in NAV workbook")
                    column = re.sub(r"\d", "", cell.attrib["r"])
                    kind = cell.get("t", "n")
                    value = cell.findtext("s:v", "", _NS)
                    if kind == "s":
                        value = strings[int(value)]
                    elif kind == "inlineStr":
                        inline = cell.find("s:is", _NS)
                        if inline is None:
                            raise ProviderResponseError("Missing inline NAV cell value")
                        value = "".join(inline.itertext())
                    elif kind not in ("n", "str"):
                        raise ProviderResponseError(f"Unsupported NAV cell type {kind}")
                    cells[column] = value
                rows.append(cells)
    except (zipfile.BadZipFile, KeyError, IndexError, ValueError, ET.ParseError) as error:
        raise ProviderResponseError("Malformed State Street NAV workbook") from error
    metadata = {r.get("A"): r.get("B") for r in rows[:5] if r}
    if metadata.get("ISIN:") != isin or metadata.get("NAV Currency:") != "USD":
        raise ProviderResponseError("NAV identity or currency differs from the requested USD fund")
    fund_name = metadata.get("Fund Name:")
    report_text = metadata.get("Report Date:")
    if not fund_name or not report_text:
        raise ProviderResponseError("NAV workbook lacks report identity")
    header = {"A": "Date", "B": "NAV", "C": "Shares Outstanding", "D": "Total Net Assets"}
    if len(rows) < 7 or rows[5] != header:
        raise ProviderResponseError("NAV workbook header changed")
    report_date = nav_date(report_text)
    seen: set[date] = set()
    values = []
    footer = False
    for row in rows[6:]:
        if not row:
            continue
        if set(row) == {"A"} and row["A"].startswith("Marketing communication"):
            footer = True
            continue
        if footer:
            raise ProviderResponseError("Unexpected row after NAV legal footer")
        if set(row) != set(header):
            raise ProviderResponseError("Incomplete or additional NAV columns")
        day = nav_date(row["A"])
        if day in seen or day > report_date:
            raise ProviderResponseError("Duplicate NAV date or observation after report date")
        seen.add(day)
        try:
            value = float(row["B"])
        except ValueError as error:
            raise ProviderResponseError("Nonnumeric NAV") from error
        if not math.isfinite(value) or value <= 0:
            raise ProviderResponseError("NAV must be finite and positive")
        values.append({header[k]: row[k] for k in header})
    if not values:
        raise ProviderResponseError("Empty NAV history")
    return NavWorkbook(isin, "USD", report_date, fund_name, pd.DataFrame(values), payload)


class SsgaNavSource:
    """Fetch official accumulating-fund NAVs using ``ISIN:ticker-gy`` symbols.

    Inputs are nontradable USD LEVEL instruments. No exchange OHLC, volume,
    dividend payment or publication timestamp is manufactured from NAVs.
    """

    source_id = "SSGA_NAV"

    def __init__(
        self,
        clock: Callable[[], datetime] = utc_now,
        fetch_bytes: Callable[[str], bytes] = http_get_bytes,
    ) -> None:
        self._clock = clock
        self._fetch_bytes = fetch_bytes

    def fetch(self, isin: str, ticker: str) -> NavWorkbook:
        """Download and validate one full official history, retaining exact bytes."""
        if not re.fullmatch(r"IE[0-9A-Z]{10}", isin):
            raise ValueError("Expected Irish ISIN")
        if not re.fullmatch(r"[a-z0-9]+-gy", ticker):
            raise ValueError("Expected issuer ticker slug such as zpde-gy")
        return parse_nav_workbook(
            self._fetch_bytes(f"{NAV_ROOT}/navhist-emea-en-{ticker}.xlsx"), isin=isin
        )

    def fetch_document(self, url: str) -> bytes:
        """Download one issuer document - a fund page or a supplement PDF - as exact bytes.

        Parameters
        ----------
        url : str
            An ``https://www.ssga.com/`` address, absolute or site-relative
            (``/library-content/...``), as the issuer's pages link them.

        Returns
        -------
        bytes
            The response, unaltered, for an acquisition archive. Nothing is
            parsed here: the page text and its links are evidence, not data.

        Raises
        ------
        ValueError
            If the address is not on the issuer's site; nothing is fetched.
        ProviderError
            If the transport fails, as for any other download.

        Notes
        -----
        The one network path for SA17's sourcing evidence, so that a script
        archiving it performs no I/O of its own and a test can replay it with
        an injected transport.
        """
        absolute = f"{SSGA_SITE}{url}" if url.startswith("/") else url
        if not absolute.startswith(f"{SSGA_SITE}/"):
            raise ValueError(f"Expected a State Street address, got {url!r}")
        return self._fetch_bytes(absolute)

    def available_from(self, instrument: Instrument) -> date | None:
        """Return the declared inception; actual coverage is audited after download."""
        return instrument.first_session

    def download(self, instrument: Instrument, start: date, end: date) -> RawDownload:
        """Fetch original rows; range filtering belongs to normalization."""
        if instrument.data_type is not DataType.LEVEL or instrument.tradable:
            raise ValueError("NAV is a nontradable LEVEL, never an execution price")
        if instrument.currency != "USD" or start > end:
            raise ValueError("Expected USD NAV and an ordered date range")
        isin, separator, ticker = instrument.source_symbol.partition(":")
        if not separator:
            raise ValueError("Expected ISIN:ticker-gy")
        book = self.fetch(isin, ticker)
        now = self._clock()
        return RawDownload(
            instrument.id,
            self.source_id,
            make_fetch_id(now),
            now,
            book.frame,
            {
                "start": start.isoformat(),
                "end_inclusive": end.isoformat(),
                "isin": isin,
                "currency": book.currency,
                "report_date": book.report_date.isoformat(),
                "sha256": book.sha256,
                "historical_publication": "UNKNOWN",
                "url": f"{NAV_ROOT}/navhist-emea-en-{ticker}.xlsx",
            },
        )

    def download_corporate_actions(self, instrument: Instrument, start: date, end: date) -> None:
        """Return no action feed; this does not certify an absence of fund splits."""
        return None
