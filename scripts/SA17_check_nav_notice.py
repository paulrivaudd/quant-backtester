"""Acquire or replay one LSE NAV notice and compare explicit issuer observations.

Network I/O is delegated to LseNavSource. Every run requires a new archive;
--replay reads an existing notice and preserves its original retrieval instant.
No trading calendar expansion, historical publication inference or performance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tomllib
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from quant_backtester.data.sources.base import ProviderResponseError
from quant_backtester.data.sources.lse_nav import (
    NAV_TOLERANCE,
    LseNavSource,
    NavIdentity,
    parse_lse_notice,
)
from quant_backtester.data.sources.ssga_nav import nav_date, parse_nav_workbook

ROOT = Path(__file__).resolve().parents[1]
NOTICE_URL = (
    "https://www.londonstockexchange.com/en/news/article/net-asset-value-s/fec6-0e-4b-b8-87-40e8b9"
)
SECTORS = {
    "IE00BWBXM492": "ENERGY",
    "IE00BWBXM831": "MATERIALS",
    "IE00BWBXM724": "INDUSTRIALS",
    "IE00BWBXM278": "CONSUMER DISCRETIONARY",
    "IE00BWBXM385": "CONSUMER STAPLES",
    "IE00BWBXM617": "HEALTH CARE",
    "IE00BWBXM500": "FINANCIALS",
    "IE00BWBXM948": "TECHNOLOGY",
    "IE00BFWFPX50": "Communication Services",
    "IE00BWBXMB69": "UTILITIES",
}


def _write(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, default=str, sort_keys=True)
        stream.write("\n")


def registry_identities(registry: Path) -> tuple[NavIdentity, ...]:
    """Resolve internal IDs from the USD NAV registry, never from sector spelling."""
    entries = tomllib.loads(registry.read_text(encoding="utf-8"))["instrument"]
    identities = []
    for item in entries:
        isin = item["source_symbol"].partition(":")[0]
        if isin not in SECTORS:
            continue
        if (
            item["currency"] != "USD"
            or item["data_type"] != "LEVEL"
            or item["tradable"]
            or item["primary_source"] != "SSGA_NAV"
        ):
            raise ValueError("Expected nontradable issuer USD NAV registry entries")
        suffix = " Select Sector" if isin == "IE00BFWFPX50" else " SELECT SECTOR"
        name = f"State Street SPDR S&P U.S. {SECTORS[isin]}{suffix} UCITS ETF (Acc)"
        identities.append(NavIdentity(item["id"], isin, name))
    if (
        len(identities) != 10
        or {item.isin for item in identities} != set(SECTORS)
        or len({item.instrument_id for item in identities}) != 10
    ):
        raise ValueError("Expected ten unique registry NAV identities")
    return tuple(identities)


def check_notice(
    archive: Path,
    primary_archive: Path,
    registry: Path,
    *,
    replay: Path | None = None,
    url: str = NOTICE_URL,
    source: LseNavSource | None = None,
) -> dict[str, object]:
    """Write new immutable notice evidence and refuse conflicting overlap values.

    Missing issuer dates are reported as explicit secondary-only observations,
    not synthesized into the primary history. Existing stores are never edited.
    Replay checks the original payload hash and retains original retrieval time.
    """
    archive.mkdir(parents=True, exist_ok=False)
    identities = registry_identities(registry)
    if replay is not None:
        acquisition = json.loads((replay / "acquisition.json").read_text(encoding="utf-8"))
        payload = (replay / "notice.html").read_bytes()
        if hashlib.sha256(payload).hexdigest() != acquisition["sha256"]:
            raise ProviderResponseError("Replay notice hash mismatch")
        notice = parse_lse_notice(
            payload,
            url=acquisition["url"],
            retrieved_at_utc=datetime.fromisoformat(acquisition["retrieved_at_utc"]),
            identities=identities,
        )
    else:
        notice = (source or LseNavSource()).download(url, identities)
    with (archive / "notice.html").open("xb") as stream:
        stream.write(notice.payload)
    _write(
        archive / "acquisition.json",
        {
            **asdict(notice.provenance),
            "status": "downloaded_validated",
            "replayed_from": str(replay) if replay is not None else None,
        },
    )
    _write(archive / "canonical_rows.json", [asdict(row) for row in notice.rows])
    _write(archive / "identity_mapping.json", [asdict(item) for item in identities])
    manifest_bytes = (primary_archive / "manifest.json").read_bytes()
    funds = json.loads(manifest_bytes)["funds"]
    by_isin = {fund["isin"]: fund for fund in funds}
    if len(by_isin) != len(funds):
        raise ProviderResponseError("Duplicate issuer manifest identity")
    comparisons = []
    for row in notice.rows:
        fund = by_isin[row.isin]
        # Resolve within the existing archive; never trust a manifest path traversal.
        raw_root = (primary_archive / "raw").resolve()
        path = (raw_root / f"{fund['ticker']}.xlsx").resolve()
        if not path.is_relative_to(raw_root):
            raise ValueError("Issuer workbook path escapes raw archive")
        book = parse_nav_workbook(path.read_bytes(), isin=row.isin)
        if book.sha256 != fund["sha256"]:
            raise ProviderResponseError("Issuer workbook hash mismatch")
        values = [
            value
            for day, value in zip(book.frame["Date"], book.frame["NAV"], strict=True)
            if nav_date(day) == row.observation_date
        ]
        if len(values) > 1:
            raise ProviderResponseError("Duplicate issuer date")
        difference = abs(Decimal(values[0]) - row.value) if values else None
        status = (
            "SECONDARY_ONLY"
            if difference is None
            else "MATCH"
            if difference <= NAV_TOLERANCE
            else "CONFLICT"
        )
        comparisons.append(
            {
                "instrument_id": row.instrument_id,
                "isin": row.isin,
                "observation_date": row.observation_date,
                "primary_nav": values[0] if values else None,
                "rns_nav": row.value,
                "absolute_difference": difference,
                "status": status,
                "primary_sha256": book.sha256,
            }
        )
    conflicts = sum(item["status"] == "CONFLICT" for item in comparisons)
    result = {
        "status": "CONFLICT_REFUSED" if conflicts else "VALIDATED_NOT_ADMITTED",
        "validated_funds": len(notice.rows),
        "comparisons": comparisons,
        "raw_sha256": notice.provenance.sha256,
        "published_at_utc": notice.provenance.published_at_utc,
        "published_at_london": notice.published_at_london,
        "absolute_tolerance_usd": NAV_TOLERANCE,
        "registry_sha256": hashlib.sha256(registry.read_bytes()).hexdigest(),
        "primary_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "economic_independence": False,
        "historical_publication_evidence": False,
        "scope": "One notice only; exact publication is not full-history publication evidence.",
        "calendar_policy": "Only explicit valuations; no XNYS reindexing or invented holiday NAVs.",
        "replayed_from": str(replay) if replay is not None else None,
        "mapping_note": "Internal IDs come from the supplied NAV registry. The original "
        "archive's SA17_NAV_COMMUNICATION_SERVICES maps to SA17_NAV_COMMUNICATION.",
    }
    _write(archive / "validation.json", result)
    if conflicts:
        raise ProviderResponseError("NAV conflicts refused; see new archive validation.json")
    return result


def main() -> None:
    """Acquire or replay using explicit input paths and a new output directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--primary-archive", type=Path, required=True)
    parser.add_argument(
        "--registry", type=Path, default=ROOT / "research/SA17/nav_instruments.toml"
    )
    choice = parser.add_mutually_exclusive_group()
    choice.add_argument("--replay", type=Path)
    choice.add_argument("--url", default=NOTICE_URL)
    args = parser.parse_args()
    result = check_notice(
        args.archive, args.primary_archive, args.registry, replay=args.replay, url=args.url
    )
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
