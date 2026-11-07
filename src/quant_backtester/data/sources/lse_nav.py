"""Dated issuer NAV announcements distributed by official LSE RNS.

RNS is a second distribution channel, not independent economic validation.
NAVs are USD levels, never exchange prices. Publication comes from the notice,
not the valuation date; the explicit UTC instant is also exposed in London
time. Historical notices may be corrected: retain exact bytes and provenance.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from quant_backtester.data.sources.base import (
    ProviderResponseError,
    http_get_bytes,
    make_fetch_id,
    utc_now,
)

NAV_HEADER = (
    "Fund",
    "Dealing Date",
    "ISIN Code",
    "Shares in Issue",
    "Fund Base Currency",
    "Net Assets Base Currency",
    "Class Local Currency",
    "Class Local Nav / Share",
)
NAV_TOLERANCE = Decimal("0.00005")
LONDON = ZoneInfo("Europe/London")


@dataclass(frozen=True, slots=True)
class NavIdentity:
    """Expected internal instrument, ISIN and exact issuer fund name."""

    instrument_id: str
    isin: str
    fund_name: str


@dataclass(frozen=True, slots=True)
class NavProvenance:
    """Immutable response identity and separate UTC retrieval/publication times."""

    source: str
    url: str
    sha256: str
    retrieved_at_utc: datetime
    published_at_utc: datetime


@dataclass(frozen=True, slots=True)
class NavRow:
    """Canonical nontradable USD NAV level with retained publication evidence."""

    instrument_id: str
    isin: str
    observation_date: date
    value: Decimal
    currency: str
    available_at_utc: datetime
    provenance: tuple[NavProvenance, ...]


@dataclass(frozen=True, slots=True)
class LseNavNotice:
    """Exact raw HTML, original table cells and canonical requested NAV rows."""

    payload: bytes
    provenance: NavProvenance
    raw_rows: tuple[tuple[str, ...], ...]
    rows: tuple[NavRow, ...]

    @property
    def published_at_london(self) -> datetime:
        """Return the explicit announcement instant in Europe/London."""
        return self.provenance.published_at_utc.astimezone(LONDON)


class _Html(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[tuple[str, ...]]] = []
        self.table: list[tuple[str, ...]] | None = None
        self.row: list[str] | None = None
        self.cell: list[str] | None = None
        self.publications: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if "data-article-published-time" in attributes:
            if attributes.get("data-article-type") != "RNS":
                raise ProviderResponseError("Expected an RNS announcement")
            self.publications.append(attributes["data-article-published-time"] or "")
        if tag == "table":
            if self.table is not None:
                raise ProviderResponseError("Nested NAV table")
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            if attributes.get("colspan", "1") != "1" or attributes.get("rowspan", "1") != "1":
                # Layout tables are permitted but cannot match the exact NAV header.
                self.row.append("[spanned cell]")
            self.cell = []

    def handle_data(self, data: str) -> None:
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self.cell is not None and self.row is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None and self.table is not None:
            self.table.append(tuple(self.row))
            self.row = None
        elif tag == "table" and self.table is not None:
            self.tables.append(self.table)
            self.table = None


def _url(url: str) -> None:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "www.londonstockexchange.com"
        or not parsed.path.startswith("/en/news/article/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Expected an official LSE announcement URL")


def _identities(identities: Sequence[NavIdentity]) -> dict[str, NavIdentity]:
    result = {item.isin: item for item in identities}
    if (
        not result
        or len(result) != len(identities)
        or len({item.instrument_id for item in identities}) != len(identities)
        or any(
            not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", item.isin)
            or not item.instrument_id
            or not item.fund_name
            for item in identities
        )
    ):
        raise ValueError("Expected unique, explicit fund identities")
    return result


def _positive(value: str) -> Decimal:
    if not re.fullmatch(r"(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]+)?", value):
        raise ProviderResponseError(f"Invalid NAV numeric cell: {value!r}")
    try:
        result = Decimal(value.replace(",", ""))
    except InvalidOperation as error:
        raise ProviderResponseError("Invalid NAV numeric cell") from error
    if not result.is_finite() or result <= 0:
        raise ProviderResponseError("NAV, shares and assets must be finite and positive")
    return result


def parse_lse_notice(
    payload: bytes, *, url: str, retrieved_at_utc: datetime, identities: Sequence[NavIdentity]
) -> LseNavNotice:
    """Parse an explicit archived notice with exact identity and USD checks.

    Supports the observed LSE ``var articleBody`` JavaScript string (decoded
    without executing code), or an HTML table already present in the page.
    Requires the RNS publication attribute; never substitutes retrieval time,
    search snippets, page creation metadata or the observation date.
    """
    _url(url)
    wanted = _identities(identities)
    make_fetch_id(retrieved_at_utc)
    try:
        text = payload.decode("utf-8-sig")
        page = _Html()
        page.feed(text)
        if len(page.publications) != 1:
            raise ProviderResponseError("Expected one explicit RNS publication timestamp")
        stamp = page.publications[0]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", stamp):
            raise ProviderResponseError("Publication must have explicit UTC timezone")
        published = datetime.fromisoformat(stamp).astimezone(UTC)
        if published > retrieved_at_utc:
            raise ProviderResponseError("Publication is after retrieval")
        bodies = re.findall(r'\bvar\s+articleBody\s*=\s*("(?:\\.|[^"\\])*")\s*;', text)
        if len(bodies) > 1:
            raise ProviderResponseError("Ambiguous announcement body")
        if bodies:
            encoded = re.sub(r"\\x([0-9A-Fa-f]{2})", r"\\u00\1", bodies[0])
            body = _Html()
            body.feed(json.loads(encoded))
            tables = body.tables
        else:
            tables = page.tables
    except (UnicodeError, ValueError) as error:
        raise ProviderResponseError("Malformed LSE announcement") from error
    matches = [table for table in tables if table and table[0] == NAV_HEADER]
    if len(matches) != 1 or len(matches[0]) < 2:
        raise ProviderResponseError("Expected one nonempty exact NAV table")
    provenance = NavProvenance(
        "LSE_RNS_NAV", url, hashlib.sha256(payload).hexdigest(), retrieved_at_utc, published
    )
    raw_rows = tuple(matches[0][1:])
    seen = set()
    rows = []
    for cells in raw_rows:
        if len(cells) != len(NAV_HEADER):
            raise ProviderResponseError("Incorrect NAV row width")
        fund, day, isin, shares, base_currency, assets, currency, nav = cells
        if isin not in wanted:
            continue
        identity = wanted[isin]
        if (
            isin in seen
            or fund != identity.fund_name
            or (base_currency, currency) != ("USD", "USD")
        ):
            raise ProviderResponseError("Duplicate fund, identity or USD currency mismatch")
        seen.add(isin)
        try:
            if not re.fullmatch(r"\d{2}/\d{2}/\d{4}", day):
                raise ValueError("date format")
            observation = datetime.strptime(day, "%d/%m/%Y").date()
        except ValueError as error:
            raise ProviderResponseError("Invalid valuation date") from error
        if observation > published.astimezone(LONDON).date():
            raise ProviderResponseError("Valuation date is after publication")
        _positive(shares)
        _positive(assets)
        rows.append(
            NavRow(
                identity.instrument_id,
                isin,
                observation,
                _positive(nav),
                "USD",
                published,
                (provenance,),
            )
        )
    if seen != set(wanted):
        raise ProviderResponseError("Notice does not contain every requested ISIN")
    return LseNavNotice(payload, provenance, raw_rows, tuple(rows))


class LseNavSource:
    """Fetch dated official notices with injected bytes transport and UTC clock."""

    source_id = "LSE_RNS_NAV"

    def __init__(
        self,
        clock: Callable[[], datetime] = utc_now,
        fetch_bytes: Callable[[str], bytes] = http_get_bytes,
    ) -> None:
        self._clock = clock
        self._fetch_bytes = fetch_bytes

    def download(self, url: str, identities: Sequence[NavIdentity]) -> LseNavNotice:
        """Download one explicit announcement; no search or history is fabricated."""
        _url(url)
        _identities(identities)
        now = self._clock()
        make_fetch_id(now)
        return parse_lse_notice(
            self._fetch_bytes(url), url=url, retrieved_at_utc=now, identities=identities
        )


def available_nav_rows(rows: Sequence[NavRow], as_of_utc: datetime) -> tuple[NavRow, ...]:
    """Exclude announcements not yet published at the aware UTC decision instant."""
    make_fetch_id(as_of_utc)
    return tuple(row for row in rows if row.available_at_utc <= as_of_utc)


@dataclass(frozen=True, slots=True)
class NavConflictReview:
    """Explicit review bound to both exact NAVs, a selected value and review time."""

    primary_value: Decimal
    secondary_value: Decimal
    choose_secondary: bool
    reviewed_at_utc: datetime


def reconcile_nav_rows(
    primary: Sequence[NavRow],
    secondary: Sequence[NavRow],
    *,
    as_of_utc: datetime,
    reviews: Mapping[tuple[str, date], NavConflictReview] | None = None,
) -> tuple[NavRow, ...]:
    """Fill primary gaps only and refuse unreviewed differences above USD 0.00005.

    Filter publication availability before comparison. Reviewed conflicts retain
    both provenances and the maximum input/review availability; they cannot make
    a secondary announcement usable before publication. Matching overlaps keep
    the original primary row. Neither outcome implies economic independence.
    """

    def index(rows: Sequence[NavRow]) -> dict[tuple[str, date], NavRow]:
        result = {}
        for row in available_nav_rows(rows, as_of_utc):
            make_fetch_id(row.available_at_utc)
            key = (row.instrument_id, row.observation_date)
            if row.currency != "USD" or not row.value.is_finite() or row.value <= 0:
                raise ProviderResponseError("Expected positive USD NAV")
            if key in result:
                raise ProviderResponseError("Duplicate NAV reconciliation key")
            result[key] = row
        return result

    merged = index(primary)
    for key, other in index(secondary).items():
        if key not in merged:
            merged[key] = other
            continue
        first = merged[key]
        if first.isin != other.isin:
            raise ProviderResponseError("Reconciliation identity mismatch")
        if abs(first.value - other.value) <= NAV_TOLERANCE:
            continue
        review = (reviews or {}).get(key)
        if review is None:
            raise ProviderResponseError(f"Unreviewed NAV conflict: {key}")
        make_fetch_id(review.reviewed_at_utc)
        if (review.primary_value, review.secondary_value) != (
            first.value,
            other.value,
        ) or review.reviewed_at_utc > as_of_utc:
            raise ProviderResponseError("NAV review is stale or not yet available")
        chosen = other if review.choose_secondary else first
        merged[key] = replace(
            chosen,
            available_at_utc=max(
                first.available_at_utc, other.available_at_utc, review.reviewed_at_utc
            ),
            provenance=first.provenance + other.provenance,
        )
    return tuple(merged[key] for key in sorted(merged))
