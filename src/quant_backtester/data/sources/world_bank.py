"""World Bank Commodity Price Data ("Pink Sheet"): one monthly price series.

The workbook ``CMO-Historical-Data-Monthly.xlsx`` holds monthly prices in
nominal US dollars since 1960. This adapter fetches it, keeps the exact bytes
and reads one column of its ``Monthly Prices`` sheet.

**Each value is the average of a month, not a price at its end.** A month's
label says which month the average describes; the average is complete only
once the month has ended, and the workbook is published after that, at a date
the file does not give per row. The series is ``RESTATED``: a retrieval, not a
historical vintage. A change computed between two monthly averages is not the
return of a holding from one month end to the next: it runs from the middle of
one month to the middle of the following one, and its variance is smaller
than that of month-end changes (Working, 1960, *Econometrica* 28: about two
thirds of it for a random walk).

The workbook is read with the standard library, as the State Street
workbooks are: cached scalar cells only, no formula, no repair.
"""

from __future__ import annotations

import hashlib
import io
import math
import re
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from xml.etree import ElementTree as ET

from quant_backtester.data.sources.base import (
    ProviderResponseError,
    http_get_bytes,
    make_fetch_id,
    utc_now,
)

PINK_SHEET_MONTHLY_URL = (
    "https://thedocs.worldbank.org/en/doc/5d903e848db1d1b83e0ec8f744e55570-0350012021/"
    "related/CMO-Historical-Data-Monthly.xlsx"
)
"""The monthly historical workbook, as linked from the Commodity Markets page."""

CLIENT_NAME = "quant-backtester research client"
"""The client name sent: the document server answers 403 to the library's default one.

A plain name, as for Dukascopy; it does not imitate a browser.
"""

SHEET = "Monthly Prices"
MAX_UNPACKED_BYTES = 50_000_000

_NS = {
    "s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "p": "http://schemas.openxmlformats.org/package/2006/relationships",
}
_MONTH = re.compile(r"([0-9]{4})M(0[1-9]|1[0-2])")


@dataclass(frozen=True, slots=True)
class PinkSheetSeries:
    """One monthly-average price series and the exact workbook it was read from.

    Attributes
    ----------
    name : str
        The column's name in the workbook, e.g. ``"Gold"``.
    unit : str
        The unit printed under it, e.g. ``"($/troy oz)"``: nominal US dollars.
    months : tuple[date, ...]
        The first day of each month, consecutive: the month an average
        describes, not the instant it was known.
    values : tuple[float, ...]
        The monthly averages, finite and positive.
    updated : str
        The workbook's own "Updated on" line, as printed.
    payload : bytes
        The exact bytes served.
    sha256 : str
        Their digest.
    url : str
        Where they were fetched.
    retrieved_at_utc : datetime
        Aware UTC retrieval instant: provenance, not availability.
    fetch_id : str
        Identifier of the retrieval.
    revision_policy : str
        Always ``RESTATED``.
    """

    name: str
    unit: str
    months: tuple[date, ...]
    values: tuple[float, ...]
    updated: str
    payload: bytes
    sha256: str
    url: str
    retrieved_at_utc: datetime
    fetch_id: str
    revision_policy: str = "RESTATED"
    source: str = "WORLD_BANK_PINK_SHEET"
    frequency: str = "monthly average"


def fetch_workbook(url: str) -> bytes:
    """Fetch the workbook under :data:`CLIENT_NAME`."""
    return http_get_bytes(url, headers={"User-Agent": CLIENT_NAME})


def _cells(row: ET.Element, strings: list[str]) -> dict[str, str]:
    """Return a row's cells by column letters, refusing formulas and unknown types."""
    cells: dict[str, str] = {}
    for cell in row.findall("s:c", _NS):
        if cell.find("s:f", _NS) is not None:
            raise ProviderResponseError("Formula in the Pink Sheet workbook")
        column = re.sub(r"[0-9]", "", cell.attrib["r"])
        kind = cell.get("t", "n")
        value = cell.findtext("s:v", "", _NS)
        if kind == "s":
            value = strings[int(value)]
        elif kind == "inlineStr":
            inline = cell.find("s:is", _NS)
            value = "" if inline is None else "".join(inline.itertext())
        elif kind not in ("n", "str"):
            raise ProviderResponseError(f"Unsupported Pink Sheet cell type {kind}")
        cells[column] = value.strip()
    return cells


def _sheet_rows(payload: bytes) -> list[dict[str, str]]:
    """Return the rows of the ``Monthly Prices`` sheet."""
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            if sum(info.file_size for info in archive.infolist()) > MAX_UNPACKED_BYTES:
                raise ProviderResponseError("Pink Sheet workbook is unexpectedly large")
            workbook = ET.fromstring(archive.read("xl/workbook.xml"))
            sheets = [
                sheet
                for sheet in workbook.findall("s:sheets/s:sheet", _NS)
                if sheet.get("name") == SHEET
            ]
            if len(sheets) != 1:
                raise ProviderResponseError(f"Expected one {SHEET!r} worksheet")
            relation = sheets[0].attrib[f"{{{_NS['r']}}}id"]
            relations = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
            targets = [
                item.attrib["Target"]
                for item in relations.findall("p:Relationship", _NS)
                if item.get("Id") == relation
            ]
            if len(targets) != 1:
                raise ProviderResponseError("Ambiguous Pink Sheet worksheet relation")
            member = targets[0].lstrip("/")
            member = member if member.startswith("xl/") else f"xl/{member}"
            strings: list[str] = []
            if "xl/sharedStrings.xml" in archive.namelist():
                root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
                strings = ["".join(item.itertext()) for item in root]
            sheet = ET.fromstring(archive.read(member))
            return [_cells(row, strings) for row in sheet.findall("s:sheetData/s:row", _NS)]
    except (zipfile.BadZipFile, KeyError, IndexError, ValueError, ET.ParseError) as error:
        raise ProviderResponseError("Malformed Pink Sheet workbook") from error


def parse_pink_sheet_monthly(
    payload: bytes, name: str, unit: str
) -> tuple[tuple[date, ...], tuple[float, ...], str]:
    """Read one column of the monthly price sheet.

    Parameters
    ----------
    payload : bytes
        The exact workbook bytes.
    name : str
        The column's header, e.g. ``"Gold"``.
    unit : str
        The unit expected under it, e.g. ``"($/troy oz)"``; a changed unit is
        refused rather than read as the same series.

    Returns
    -------
    tuple[tuple[date, ...], tuple[float, ...], str]
        The months (first day of each), their averages in nominal US dollars,
        and the workbook's "Updated on" line.

    Raises
    ------
    ProviderResponseError
        If the workbook is malformed, the column is absent or repeated, its
        unit differs, a month is missing or repeated, or a value is not a
        finite positive number.
    """
    rows = _sheet_rows(payload)
    headers = [
        (index, column)
        for index, row in enumerate(rows)
        for column, value in row.items()
        if value == name
    ]
    if len(headers) != 1:
        raise ProviderResponseError(f"Expected one {name!r} column in the Pink Sheet")
    index, column = headers[0]
    if index + 1 >= len(rows) or rows[index + 1].get(column) != unit:
        raise ProviderResponseError(f"The unit of {name!r} is not {unit!r}")
    updated = next(
        (row["A"] for row in rows[:index] if row.get("A", "").startswith("Updated on")), ""
    )
    if not updated:
        raise ProviderResponseError("The Pink Sheet does not say when it was updated")
    months: list[date] = []
    values: list[float] = []
    for row in rows[index + 2 :]:
        match = _MONTH.fullmatch(row.get("A", ""))
        if match is None:
            if months:
                raise ProviderResponseError(f"Unexpected row after {months[-1]:%Y-%m}")
            continue
        month = date(int(match.group(1)), int(match.group(2)), 1)
        if months and (month.year * 12 + month.month) != (
            months[-1].year * 12 + months[-1].month + 1
        ):
            raise ProviderResponseError(f"Month gap or repeat at {month:%Y-%m}")
        try:
            value = float(row.get(column, ""))
        except ValueError as error:
            raise ProviderResponseError(f"No {name} price for {month:%Y-%m}") from error
        if not math.isfinite(value) or value <= 0.0:
            raise ProviderResponseError(f"Invalid {name} price for {month:%Y-%m}")
        months.append(month)
        values.append(value)
    if not months:
        raise ProviderResponseError(f"No monthly {name} price in the Pink Sheet")
    return tuple(months), tuple(values), updated


class WorldBankPinkSheetSource:
    """Fetch the monthly Pink Sheet workbook with injected transport and UTC clock.

    Parameters
    ----------
    clock : Callable[[], datetime]
        Returns an aware UTC retrieval instant.
    fetch_bytes : Callable[[str], bytes]
        Fetches a URL as bytes; :func:`fetch_workbook` by default.
    """

    source_id = "WORLD_BANK_PINK_SHEET"

    def __init__(
        self,
        clock: Callable[[], datetime] = utc_now,
        fetch_bytes: Callable[[str], bytes] = fetch_workbook,
    ) -> None:
        self._clock = clock
        self._fetch_bytes = fetch_bytes

    def download(self, name: str, unit: str) -> PinkSheetSeries:
        """Retrieve the workbook and read one monthly-average series from it.

        Parameters
        ----------
        name : str
            The column's header, e.g. ``"Gold"``.
        unit : str
            The unit expected under it.

        Returns
        -------
        PinkSheetSeries
            The whole published history of the series, with the exact bytes.

        Raises
        ------
        ProviderResponseError
            If the workbook cannot be read as :func:`parse_pink_sheet_monthly`
            requires.
        """
        retrieved = self._clock()
        fetch_id = make_fetch_id(retrieved)
        payload = self._fetch_bytes(PINK_SHEET_MONTHLY_URL)
        months, values, updated = parse_pink_sheet_monthly(payload, name, unit)
        return PinkSheetSeries(
            name=name,
            unit=unit,
            months=months,
            values=values,
            updated=updated,
            payload=payload,
            sha256=hashlib.sha256(payload).hexdigest(),
            url=PINK_SHEET_MONTHLY_URL,
            retrieved_at_utc=retrieved,
            fetch_id=fetch_id,
        )
