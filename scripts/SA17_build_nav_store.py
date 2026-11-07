"""Build a NEW retrieval-dated NAV store from the immutable issuer archive.

No network and no backtest. Rows are not admitted to historical decisions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tomllib
from datetime import date, datetime
from pathlib import Path

from quant_backtester.data.bar_corrections import BarCorrections
from quant_backtester.data.calendars import CalendarRegistry
from quant_backtester.data.conflict_reviews import ConflictReviews
from quant_backtester.data.corporate_actions import ActionCorrections
from quant_backtester.data.crosscheck import CrossCheckPolicy
from quant_backtester.data.instruments import InstrumentRegistry
from quant_backtester.data.known_gaps import KnownGaps
from quant_backtester.data.normalizer import NORMALIZERS
from quant_backtester.data.repository import MarketDataRepository
from quant_backtester.data.revisions import AcceptedRevisions
from quant_backtester.data.sources.ssga_nav import SsgaNavSource, nav_date, parse_nav_workbook
from quant_backtester.data.updater import MarketDataUpdater

ROOT = Path(__file__).resolve().parents[1]


def build(archive: Path, store: Path) -> None:
    """Replay exact archive bytes through the framework validation pipeline."""
    if store.resolve().parent != ROOT / "runs" or not store.name.startswith("sa17_"):
        raise ValueError("Use a new runs/sa17_* directory")
    store.mkdir(exist_ok=False)
    metadata = store / "metadata"
    shutil.copytree(ROOT / "market_data/metadata", metadata)
    records = json.loads((archive / "coverage.json").read_text())
    instruments = tomllib.loads((ROOT / "research/SA17/source_instruments.toml").read_text())[
        "instrument"
    ][:10]
    blocks = []
    for record, fund in zip(records, instruments, strict=True):
        expected_ticker = fund["source_symbol"].split(".")[0].lower() + "-gy"
        if record["ticker"] != expected_ticker:
            raise ValueError("Archive order/identity does not match the instrument registry")
        blocks.append(f'''[[instrument]]
id = "{fund["id"].replace("ETF_", "NAV_")}"
name = "Official USD NAV {record["isin"]}"
asset_type = "ETF"
data_type = "LEVEL"
currency = "USD"
primary_source = "SSGA_NAV"
source_symbol = "{record["isin"]}:{record["ticker"]}"
tradable = false
first_session = {record["first_observation"]}
distribution_policy = "ACCUMULATING"
history_basis = "RESTATED"
history_note = """
Current issuer NAV history; historical publication and revisions unverified.
Retrieval floor prevents historical decisions. Never execution prices.
"""
[instrument.publication_rule]
# Structural LEVEL requirement only; NOT an assertion of midnight publication.
# Its explicit retrieval floor is enforced by normalizer and validator.
publication_time = "00:00:00"
timezone = "UTC"
not_before_utc = {record["retrieved_at_utc"].replace("+00:00", "Z")}
''')
    registry_text = "\n".join(blocks)
    (metadata / "instruments.toml").write_text(registry_text)
    registry = InstrumentRegistry.from_toml(metadata / "instruments.toml")
    calendars = CalendarRegistry.from_directory(metadata / "calendars")
    repository = MarketDataRepository(store)
    evidence = []
    for record, fund in zip(records, instruments, strict=True):
        instrument_id = fund["id"].replace("ETF_", "NAV_")
        payload = (archive / "raw" / f"{record['ticker']}.xlsx").read_bytes()
        if hashlib.sha256(payload).hexdigest() != record["sha256"]:
            raise ValueError("Archive bytes changed")
        fetched = datetime.fromisoformat(record["retrieved_at_utc"])
        source = SsgaNavSource(clock=lambda t=fetched: t, fetch_bytes=lambda url, p=payload: p)
        updater = MarketDataUpdater(
            repository=repository,
            instruments=registry,
            calendars=calendars,
            sources={"SSGA_NAV": source},
            normalizers=dict(NORMALIZERS),
            accepted_revisions=AcceptedRevisions.from_toml(metadata / "accepted_revisions.toml"),
            action_corrections=ActionCorrections.from_toml(metadata / "corporate_actions.toml"),
            bar_corrections=BarCorrections.from_toml(metadata / "bar_corrections.toml"),
            cross_check_policy=CrossCheckPolicy.from_toml(metadata / "crosscheck.toml"),
            known_gaps=KnownGaps.from_toml(metadata / "known_gaps.toml"),
            conflict_reviews=ConflictReviews.from_toml(metadata / "conflict_reviews.toml"),
        )
        first = date.fromisoformat(record["first_observation"])
        end = date(2026, 10, 30)
        report = updater.download(instrument_id, first, end)
        if not report.valid:
            codes = sorted({issue.code for issue in report.issues})
            raise ValueError(f"NAV validation failed: {instrument_id}: {codes}")
        book = parse_nav_workbook(payload, isin=record["isin"])
        observed = {nav_date(v) for v in book.frame["Date"]}
        expected = {s.session_date for s in calendars.get("XNYS").sessions(first, end)}
        evidence.append(
            {
                "id": instrument_id,
                "validated": report.valid,
                "missing_xnys_sessions": [str(d) for d in sorted(expected - observed)],
                "extra_non_xnys_dates": [
                    str(d) for d in sorted(observed - expected) if first <= d <= end
                ],
                "known_xetra_gaps_present": all(
                    d in observed for d in (date(2025, 10, 24), date(2026, 3, 6))
                ),
                "historical_decisions_admitted": False,
            }
        )
    (store / "coverage.json").write_text(json.dumps(evidence, indent=2) + "\n")
    hashes = {
        str(p.relative_to(store)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(metadata.rglob("*"))
        if p.is_file()
    }
    (store / "metadata_sha256.json").write_text(json.dumps(hashes, indent=2) + "\n")
    for row in evidence:
        print(
            f"{row['id']}: validated; {len(row['missing_xnys_sessions'])} XNYS gaps; "
            f"two Yahoo gaps covered={row['known_xetra_gaps_present']}"
        )


def main() -> None:
    """Require explicit archive and a fresh destination."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--store", type=Path, required=True)
    args = parser.parse_args()
    build(args.archive, args.store)


if __name__ == "__main__":
    main()
