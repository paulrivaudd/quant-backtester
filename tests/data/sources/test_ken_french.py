from __future__ import annotations

import hashlib
import io
from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime
from zipfile import ZipFile

import pytest

from quant_backtester.data.sources.base import ProviderResponseError, ProviderUnavailable
from quant_backtester.data.sources.ken_french import (
    BASE_URL,
    KenFrenchDataset,
    KenFrenchSource,
    normalize_monthly_returns,
)

NOW = datetime(2026, 11, 7, tzinfo=UTC)
JULY = date(1926, 7, 1)
AUGUST = date(1926, 8, 1)
INDUSTRY = KenFrenchDataset.INDUSTRY_10


def zipped(text, dataset=INDUSTRY, member=None):
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr(member or f"{dataset.value}.csv", text)
    return buffer.getvalue()


def industry_text(count=10, months=("192607", "192608")):
    header = "," + ",".join(f"I{i}" for i in range(count)) + "\n"
    rows = "".join(month + ", 2.50,-99.99,-999" + ",1" * (count - 3) + "\n" for month in months)
    return (
        "Synthetic official layout\n\nAverage Value Weighted Returns -- Monthly\n"
        + header
        + rows
        + "\nAverage Equal Weighted Returns -- Monthly\n"
        + header
        + "192607"
        + ",99" * count
        + "\n\nAverage Value Weighted Returns -- Annual\n"
        + header
        + "1926"
        + ",88" * count
        + "\n"
    )


def download(payload, dataset=INDUSTRY, start=JULY, end=AUGUST):
    return KenFrenchSource(clock=lambda: NOW, fetch_bytes=lambda _: payload).download(
        dataset, start, end
    )


@pytest.mark.parametrize("dataset,count", [(INDUSTRY, 10), (KenFrenchDataset.INDUSTRY_49, 49)])
def test_industry_snapshot_and_explicit_normalization(dataset, count):
    payload = zipped(industry_text(count), dataset)
    calls = []

    def fetch(url) -> bytes:
        calls.append(url)
        return payload

    raw = KenFrenchSource(clock=lambda: NOW, fetch_bytes=fetch).download(dataset, JULY, AUGUST)
    assert calls == [f"{BASE_URL}{dataset.value}_CSV.zip"]
    assert raw.payload == payload
    assert raw.sha256 == hashlib.sha256(payload).hexdigest()
    assert raw.retrieved_at_utc == NOW
    assert raw.fetch_id == "20261107T000000Z"
    assert (raw.currency, raw.frequency, raw.units, raw.revision_policy) == (
        "USD",
        "monthly",
        "percent",
        "RESTATED",
    )
    assert raw.rows[0][1:4] == (" 2.50", "-99.99", "-999")
    result = normalize_monthly_returns(raw)
    assert result.months == (JULY, AUGUST)
    assert result.values[0][:4] == (0.025, None, None, 0.01)
    assert len(result.columns) == count
    assert result.raw is raw
    assert raw.rows[0][1] == " 2.50"
    with pytest.raises(FrozenInstanceError):
        raw.units = "fraction"


def test_market_is_excess_plus_rf_and_missing_propagates():
    dataset = KenFrenchDataset.FACTORS
    text = (
        "Preamble\n\n,Mkt-RF,SMB,HML,RF\n192607,2.96,-2.56,-2.43,0.22\n"
        "192608,-99.99,1,2,0.25\n192609,1,2,3,-999\n\n"
        " Annual Factors: January-December\n,Mkt-RF,SMB,HML,RF\n1926,99,99,99,99\n"
    )
    raw = download(zipped(text, dataset), dataset, end=date(1926, 9, 1))
    result = normalize_monthly_returns(raw)
    assert result.columns == ("Mkt-RF", "SMB", "HML", "RF", "Mkt")
    assert result.values[0][-1] == pytest.approx(0.0318)
    assert result.values[1][-1] is None
    assert result.values[2][-1] is None


@pytest.mark.parametrize(
    "months",
    [(), ("192607", "192607"), ("192607", "192609"), ("192608", "192607"), ("192613",), ("1926",)],
)
def test_invalid_months_rejected(months):
    with pytest.raises(ProviderResponseError):
        download(zipped(industry_text(months=months)))


@pytest.mark.parametrize("value", ["NaN", "inf", "garbage", ""])
def test_bad_values_rejected(value):
    with pytest.raises(ProviderResponseError):
        download(zipped(industry_text().replace(" 2.50", value)))


@pytest.mark.parametrize(
    "change",
    [
        lambda text: text.replace("Average Value Weighted Returns -- Monthly", "Wrong section"),
        lambda text: text.replace("I1,", "I0,"),
        lambda text: text.replace("192607, 2.50,", "192607,"),
        lambda text: text + text,
    ],
)
def test_wrong_or_ambiguous_section_and_schema(change):
    with pytest.raises(ProviderResponseError):
        download(zipped(change(industry_text())))


@pytest.mark.parametrize("payload", [b"not a zip", zipped(industry_text(), member="wrong.csv")])
def test_bad_archive(payload):
    with pytest.raises(ProviderResponseError):
        download(payload)


def test_range_is_explicit_and_future_values_do_not_change_selected_returns():
    raw = download(zipped(industry_text()), end=JULY)
    changed = industry_text().replace("192608, 2.50", "192608, 90.00")
    later = download(zipped(changed), end=JULY)
    assert normalize_monthly_returns(raw).values == normalize_monthly_returns(later).values
    assert normalize_monthly_returns(raw).months == (JULY,)
    assert len(raw.rows) == 2
    with pytest.raises(ProviderResponseError, match="range"):
        download(zipped(industry_text()), start=date(1926, 6, 1))


@pytest.mark.parametrize(
    "dataset,start,end,clock",
    [
        ("10_Industry_Portfolios", JULY, AUGUST, NOW),
        (INDUSTRY, AUGUST, JULY, NOW),
        (INDUSTRY, date(1926, 7, 2), AUGUST, NOW),
        (INDUSTRY, JULY, AUGUST, datetime(2026, 11, 7)),
    ],
)
def test_bad_request_fails_before_fetch(dataset, start, end, clock):
    def fetch(url) -> bytes:
        pytest.fail("Unexpected fetch")

    with pytest.raises(ValueError):
        KenFrenchSource(clock=lambda: clock, fetch_bytes=fetch).download(dataset, start, end)


def test_transport_failure_propagates():
    def fetch(url) -> bytes:
        raise ProviderUnavailable("offline")

    with pytest.raises(ProviderUnavailable):
        KenFrenchSource(clock=lambda: NOW, fetch_bytes=fetch).download(INDUSTRY, JULY, AUGUST)
