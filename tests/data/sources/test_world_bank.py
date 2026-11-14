"""Tests of the World Bank Pink Sheet adapter, on workbooks built in memory."""

from __future__ import annotations

import hashlib
import io
from datetime import UTC, date, datetime
from zipfile import ZipFile

import pytest

from quant_backtester.data.sources import world_bank
from quant_backtester.data.sources.base import ProviderResponseError
from quant_backtester.data.sources.world_bank import (
    PINK_SHEET_MONTHLY_URL,
    WorldBankPinkSheetSource,
    parse_pink_sheet_monthly,
)

NOW = datetime(2026, 11, 14, tzinfo=UTC)
UNIT = "($/troy oz)"
MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE = "http://schemas.openxmlformats.org/package/2006/relationships"


def cell(reference: str, value: object, formula: bool = False) -> str:
    if formula:
        return f'<c r="{reference}"><f>1+1</f><v>{value}</v></c>'
    if isinstance(value, str):
        return f'<c r="{reference}" t="inlineStr"><is><t>{value}</t></is></c>'
    return f'<c r="{reference}"><v>{value}</v></c>'


def workbook(
    prices: dict[str, object] | None = None,
    unit: str = UNIT,
    sheet: str = "Monthly Prices",
    extra_gold: bool = False,
    formula: bool = False,
    updated: str = "Updated on January 03, 2025",
) -> bytes:
    """Build a workbook laid out as the Pink Sheet: oil in B, gold in C."""
    prices = {"1960M01": 35.27, "1960M02": 35.5, "1960M03": 36.0} if prices is None else prices
    rows = [
        [cell("A1", "World Bank Commodity Price Data (The Pink Sheet)")],
        [cell("A2", updated)] if updated else [],
        [cell("B3", "Crude oil, average"), cell("C3", "Gold")]
        + ([cell("D3", "Gold")] if extra_gold else []),
        [cell("B4", "($/bbl)"), cell("C4", unit)],
    ]
    for index, (month, price) in enumerate(prices.items(), start=5):
        rows.append(
            [cell(f"A{index}", month), cell(f"B{index}", 1.63), cell(f"C{index}", price, formula)]
        )
    data = "".join(f'<row r="{i}">{"".join(cells)}</row>' for i, cells in enumerate(rows, 1))
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns="{MAIN}" xmlns:r="{REL}"><sheets>'
            '<sheet name="AFOSHEET" sheetId="1" r:id="rId1"/>'
            f'<sheet name="{sheet}" sheetId="2" r:id="rId2"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            f'<Relationships xmlns="{PACKAGE}">'
            '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Target="worksheets/sheet2.xml"/></Relationships>',
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml", f'<worksheet xmlns="{MAIN}"><sheetData/></worksheet>'
        )
        archive.writestr(
            "xl/worksheets/sheet2.xml",
            f'<worksheet xmlns="{MAIN}"><sheetData>{data}</sheetData></worksheet>',
        )
    return buffer.getvalue()


def test_the_gold_column_is_read_with_its_months_and_the_update_line() -> None:
    months, values, updated = parse_pink_sheet_monthly(workbook(), "Gold", UNIT)
    assert months == (date(1960, 1, 1), date(1960, 2, 1), date(1960, 3, 1))
    assert values == (35.27, 35.5, 36.0)
    assert updated == "Updated on January 03, 2025"


def test_another_column_is_not_read_in_its_place() -> None:
    _, values, _ = parse_pink_sheet_monthly(workbook(), "Crude oil, average", "($/bbl)")
    assert values == (1.63, 1.63, 1.63)


def test_a_single_month_is_a_series() -> None:
    months, values, _ = parse_pink_sheet_monthly(workbook({"1975M01": 176.27}), "Gold", UNIT)
    assert months == (date(1975, 1, 1),)
    assert values == (176.27,)


def test_a_month_added_later_does_not_change_the_months_before_it() -> None:
    """The look-ahead guard: a longer file gives the same earlier values."""
    short = parse_pink_sheet_monthly(workbook(), "Gold", UNIT)
    longer = parse_pink_sheet_monthly(
        workbook({"1960M01": 35.27, "1960M02": 35.5, "1960M03": 36.0, "1960M04": 99.0}),
        "Gold",
        UNIT,
    )
    assert longer[0][:3] == short[0]
    assert longer[1][:3] == short[1]


@pytest.mark.parametrize(
    "payload",
    [
        workbook(unit="($/kg)"),
        workbook(sheet="Monthly Indices"),
        workbook(extra_gold=True),
        workbook(formula=True),
        workbook(updated=""),
        workbook({}),
        workbook({"1960M01": 35.27, "1960M03": 36.0}),
        workbook({"1960M02": 35.27, "1960M01": 36.0}),
        workbook({"1960M01": 0.0}),
        workbook({"1960M01": "…"}),
        workbook({"1960M01": "nan"}),
        b"not a workbook",
    ],
)
def test_a_workbook_that_is_not_the_expected_one_is_refused(payload: bytes) -> None:
    with pytest.raises(ProviderResponseError):
        parse_pink_sheet_monthly(payload, "Gold", UNIT)


def test_an_absent_column_is_refused() -> None:
    with pytest.raises(ProviderResponseError, match="Silver"):
        parse_pink_sheet_monthly(workbook(), "Silver", UNIT)


def test_the_source_keeps_the_exact_bytes_and_their_provenance() -> None:
    payload = workbook()
    calls: list[str] = []

    def fetch(url: str) -> bytes:
        calls.append(url)
        return payload

    series = WorldBankPinkSheetSource(clock=lambda: NOW, fetch_bytes=fetch).download("Gold", UNIT)
    assert calls == [PINK_SHEET_MONTHLY_URL]
    assert series.payload == payload
    assert series.sha256 == hashlib.sha256(payload).hexdigest()
    assert series.retrieved_at_utc == NOW
    assert series.revision_policy == "RESTATED"
    assert series.frequency == "monthly average"
    assert series.values == (35.27, 35.5, 36.0)


def test_the_workbook_is_asked_for_under_a_plain_client_name(monkeypatch) -> None:
    """The document server answers 403 to the library's default client name."""
    seen: dict[str, object] = {}

    def fake(url: str, *, headers: dict[str, str] | None = None) -> bytes:
        seen.update(url=url, headers=headers)
        return b"payload"

    monkeypatch.setattr(world_bank, "http_get_bytes", fake)
    assert world_bank.fetch_workbook("https://example.test/file.xlsx") == b"payload"
    assert seen == {
        "url": "https://example.test/file.xlsx",
        "headers": {"User-Agent": "quant-backtester research client"},
    }
