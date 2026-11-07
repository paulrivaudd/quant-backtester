"""Offline synthetic RNS notices; no test reads the acquisition archive or network."""

from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from html import escape

import pytest

from quant_backtester.data.sources.base import ProviderResponseError, ProviderUnavailable
from quant_backtester.data.sources.lse_nav import (
    NAV_HEADER,
    LseNavSource,
    NavConflictReview,
    NavIdentity,
    available_nav_rows,
    parse_lse_notice,
    reconcile_nav_rows,
)

URL = "https://www.londonstockexchange.com/en/news/article/net-asset-value-s/test"
NOW = datetime(2026, 11, 7, tzinfo=UTC)
PUBLISHED = datetime(2026, 11, 6, 10, 20, 21, tzinfo=UTC)
IDENTITY = NavIdentity("ENERGY_NAV", "IE00BWBXM492", "Synthetic energy fund")
CELLS = (
    IDENTITY.fund_name,
    "05/11/2026",
    IDENTITY.isin,
    "18,950,000",
    "USD",
    "951449702.9",
    "USD",
    "50.2084",
)


def notice(rows=(CELLS,), *, stamp="2026-11-06T10:20:21Z", embedded=True, header=NAV_HEADER):
    table = (
        "<table>"
        + "".join(
            "<tr>"
            + "".join(f"<td><p><span>{escape(cell)}</span></p></td>" for cell in row)
            + "</tr>"
            for row in (header, *rows)
        )
        + "</table>"
    )
    body = (
        ("<script>var articleBody=" + json.dumps(table).replace("<", r"\x3C") + ";</script>")
        if embedded
        else table
    )
    return (
        f'<div data-article-type="RNS" data-article-published-time="{stamp}"></div>' + body
    ).encode()


def parse(payload=None):
    return parse_lse_notice(
        payload if payload is not None else notice(),
        url=URL,
        retrieved_at_utc=NOW,
        identities=[IDENTITY],
    )


@pytest.mark.parametrize("embedded", [True, False])
def test_exact_html_publication_and_raw_provenance(embedded):
    payload = notice(embedded=embedded)
    result = parse(payload)
    (row,) = result.rows
    assert row.value == Decimal("50.2084")
    assert row.currency == "USD"
    assert row.observation_date == date(2026, 11, 5)
    assert row.available_at_utc == PUBLISHED
    assert result.published_at_london.isoformat() == "2026-11-06T10:20:21+00:00"
    assert result.payload == payload
    assert result.raw_rows == (CELLS,)
    assert result.provenance.sha256 == hashlib.sha256(payload).hexdigest()
    assert result.provenance.retrieved_at_utc == NOW
    with pytest.raises(FrozenInstanceError):
        row.value = Decimal("1")


def test_london_summer_time_is_explicit():
    cells = list(CELLS)
    cells[1] = "01/07/2026"
    result = parse(notice([cells], stamp="2026-07-02T09:20:21Z"))
    assert result.published_at_london.hour == 10
    assert result.published_at_london.utcoffset() == timedelta(hours=1)


@pytest.mark.parametrize(
    "column,value",
    [
        (0, "Wrong fund"),
        (1, "07/11/2026"),
        (1, "2026-11-05"),
        (1, "31/11/2026"),
        (2, "IE00BWBXM948"),
        (3, "0"),
        (4, "EUR"),
        (5, "nan"),
        (6, "GBP"),
        (7, "inf"),
        (7, "0"),
        (7, "-5"),
        (7, "1,23.4"),
        (7, ""),
    ],
)
def test_identity_currency_date_and_numeric_rejections(column, value):
    cells = list(CELLS)
    cells[column] = value
    with pytest.raises(ProviderResponseError):
        parse(notice([cells]))


@pytest.mark.parametrize(
    "payload",
    [
        notice([]),
        notice([CELLS, CELLS]),
        notice([CELLS[:-1]]),
        notice(header=(*NAV_HEADER[:-1], "Price")),
        b"<html>Denied</html>",
        notice(stamp="2026-11-06T10:20:21"),
        notice(stamp="2026-11-08T10:20:21Z"),
        notice(stamp="invalid"),
        b"\xff",
        notice() + notice(),
    ],
)
def test_bad_schema_missing_or_ambiguous_publication(payload):
    with pytest.raises(ProviderResponseError):
        parse(payload)


def test_fetch_and_future_publication_guard():
    calls = []

    def fetch(url) -> bytes:
        calls.append(url)
        return notice()

    result = LseNavSource(clock=lambda: NOW, fetch_bytes=fetch).download(URL, [IDENTITY])
    assert calls == [URL]
    assert available_nav_rows(result.rows, PUBLISHED - timedelta(seconds=1)) == ()
    assert available_nav_rows(result.rows, PUBLISHED) == result.rows
    changed = replace(result.rows[0], value=Decimal("999"))
    assert available_nav_rows([changed], PUBLISHED - timedelta(seconds=1)) == ()
    with pytest.raises(ValueError):
        available_nav_rows(result.rows, datetime(2026, 11, 7))


def test_invalid_request_before_transport_and_provider_errors():
    def fetch(url) -> bytes:
        raise ProviderUnavailable("offline")

    source = LseNavSource(clock=lambda: NOW, fetch_bytes=fetch)
    with pytest.raises(ValueError):
        source.download("https://example.com/notice", [IDENTITY])
    with pytest.raises(ValueError):
        source.download(URL, [IDENTITY, IDENTITY])
    with pytest.raises(ProviderUnavailable):
        source.download(URL, [IDENTITY])


def test_reconcile_fills_gaps_keeps_primary_and_exact_tolerance():
    (row,) = parse().rows
    primary = replace(row, value=row.value + Decimal("0.00005"))
    gap = replace(row, observation_date=date(2026, 11, 4))
    assert reconcile_nav_rows([primary], [row, gap], as_of_utc=NOW) == (gap, primary)
    too_far = replace(primary, value=primary.value + Decimal("0.000001"))
    with pytest.raises(ProviderResponseError, match="conflict"):
        reconcile_nav_rows([too_far], [row], as_of_utc=NOW)
    future = replace(too_far, available_at_utc=NOW + timedelta(days=1))
    assert reconcile_nav_rows([row], [future], as_of_utc=NOW) == (row,)


def test_review_retains_both_availability_and_provenance():
    (row,) = parse().rows
    primary = replace(row, value=Decimal("51"), available_at_utc=PUBLISHED - timedelta(days=1))
    key = (row.instrument_id, row.observation_date)
    review = NavConflictReview(primary.value, row.value, False, NOW)
    (merged,) = reconcile_nav_rows([primary], [row], as_of_utc=NOW, reviews={key: review})
    assert merged.value == primary.value
    assert merged.available_at_utc == NOW
    assert merged.provenance == primary.provenance + row.provenance
    assert available_nav_rows([merged], PUBLISHED) == ()
    for bad in [
        replace(review, primary_value=Decimal("52")),
        replace(review, reviewed_at_utc=NOW + timedelta(seconds=1)),
    ]:
        with pytest.raises(ProviderResponseError):
            reconcile_nav_rows([primary], [row], as_of_utc=NOW, reviews={key: bad})


def test_reconcile_rejects_duplicate_identity_and_currency():
    (row,) = parse().rows
    for primary, secondary in [
        ([row, row], []),
        ([row], [replace(row, isin="wrong")]),
        ([], [replace(row, currency="EUR")]),
    ]:
        with pytest.raises(ProviderResponseError):
            reconcile_nav_rows(primary, secondary, as_of_utc=NOW)
