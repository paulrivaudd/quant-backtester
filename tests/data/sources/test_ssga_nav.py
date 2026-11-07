import hashlib
import io
import zipfile
from datetime import UTC, date, datetime
from xml.sax.saxutils import escape

import pytest

from quant_backtester.data.sources.base import ProviderResponseError
from quant_backtester.data.sources.ssga_nav import SsgaNavSource, parse_nav_workbook

ISIN = "IE00BKWQ0D84"


def workbook(*, isin=ISIN, currency="USD", values=None, formula=False, header="NAV"):
    rows = [
        ["Fund Name:", "Synthetic fund"],
        ["ISIN:", isin],
        ["NAV Currency:", currency],
        ["Report Date:", "06-Nov-2026"],
        [],
        ["Date", header, "Shares Outstanding", "Total Net Assets"],
        *(values if values is not None else [["05-Nov-2026", "101.25", "100", "10125"]]),
    ]
    xml_rows = []
    for number, row in enumerate(rows, 1):
        cells = []
        for column, value in zip("ABCD", row, strict=False):
            f = "<f>1+1</f>" if formula and number == 7 and column == "B" else ""
            cells.append(
                f'<c r="{column}{number}" t="inlineStr">{f}<is><t>{escape(value)}</t></is></c>'
            )
        xml_rows.append(f'<row r="{number}">{"".join(cells)}</row>')
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns="{ns}"><sheets><sheet name="navhist"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            f'<worksheet xmlns="{ns}"><sheetData>{"".join(xml_rows)}</sheetData></worksheet>',
        )
    return buffer.getvalue()


def test_workbook_preserves_original_values_and_bytes():
    payload = workbook()
    book = parse_nav_workbook(payload, isin=ISIN)
    assert book.isin == ISIN
    assert book.currency == "USD"
    assert book.report_date == date(2026, 11, 6)
    assert book.frame.iloc[0]["NAV"] == "101.25"
    assert book.payload == payload
    assert book.sha256 == hashlib.sha256(payload).hexdigest()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"isin": "IE00WRONG000"},
        {"currency": "EUR"},
        {"formula": True},
        {"header": "Close"},
        {"values": []},
        {"values": [["05-Nov-2026", "1", "1", "1"]] * 2},
        {"values": [["07-Nov-2026", "1", "1", "1"]]},
        {"values": [["bad-date", "1", "1", "1"]]},
        {"values": [["05-Nov-2026", "1"]]},
    ],
)
def test_rejects_identity_schema_formula_and_dates(kwargs):
    with pytest.raises(ProviderResponseError):
        parse_nav_workbook(workbook(**kwargs), isin=ISIN)


@pytest.mark.parametrize("value", ["0", "-1", "NaN", "inf", "-inf", "oops", ""])
def test_rejects_bad_nav(value):
    with pytest.raises(ProviderResponseError):
        parse_nav_workbook(workbook(values=[["05-Nov-2026", value, "1", "1"]]), isin=ISIN)


@pytest.mark.parametrize("payload", [b"not a zip", b"<html>error</html>"])
def test_rejects_malformed_workbook(payload):
    with pytest.raises(ProviderResponseError):
        parse_nav_workbook(payload, isin=ISIN)


def test_fetch_uses_injected_transport():
    urls = []
    payload = workbook()

    def fetch(url) -> bytes:
        urls.append(url)
        return payload

    source = SsgaNavSource(clock=lambda: datetime(2026, 11, 7, tzinfo=UTC), fetch_bytes=fetch)
    assert source.fetch(ISIN, "zpde-gy").payload == payload
    assert urls == [
        "https://www.ssga.com/library-content/products/fund-data/etfs/emea/"
        "navhist-emea-en-zpde-gy.xlsx"
    ]


@pytest.mark.parametrize(("isin", "ticker"), [("bad", "zpde-gy"), (ISIN, "../evil")])
def test_invalid_identifiers_never_fetch(isin, ticker):
    def fetch(url) -> bytes:
        pytest.fail("invalid identity reached transport")

    with pytest.raises(ValueError):
        SsgaNavSource(fetch_bytes=fetch).fetch(isin, ticker)
