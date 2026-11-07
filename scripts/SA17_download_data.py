"""Acquire SA17's verified EUR listings through the existing data pipeline.

This is a coverage study, not a backtest or a frozen strategy universe. Network
I/O remains in data/sources; MarketDataUpdater owns archival, normalization,
validation, revisions and publication to clean/. No prices are fabricated,
forward-filled, converted to USD, or substituted for total-return indices.

The cutoff remains 2026-10-30, as in the original SA17 proposal. Provider
snapshots are retrieved now, not historical vintages. Only isolated directories
named runs/sa17_* are accepted; earlier studies and market_data are protected.

Examples (from the repository root, in the POSIX Python 3.12 environment)::

    uv run python scripts/SA17_download_data.py --coverage-only
    uv run python scripts/SA17_download_data.py --only SA17_ETF_ENERGY
    uv run python scripts/SA17_download_data.py
    uv run python scripts/SA17_download_data.py --rebuild
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, date, datetime
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
from quant_backtester.data.schemas import CheckStatus
from quant_backtester.data.sources.yahoo import YahooSource
from quant_backtester.data.updater import MarketDataUpdater

ROOT = Path(__file__).resolve().parents[1]
SOURCE_REGISTRY = ROOT / "research" / "SA17" / "source_instruments.toml"
STORE = ROOT / "runs" / "sa17_store"
CUTOFF = date(2026, 10, 30)


def require_isolated_store(store: Path, root: Path = ROOT) -> Path:
    """Resolve and restrict writes to a direct runs/sa17_* child of the project."""
    resolved = store.resolve()
    runs = root.resolve() / "runs"
    if resolved.parent != runs or not resolved.name.startswith("sa17_"):
        raise ValueError(f"SA17 requires an isolated {runs}/sa17_* store, got {resolved}")
    return resolved


def metadata_manifest(metadata: Path) -> dict[str, str]:
    """Hash every metadata file, with portable relative paths."""
    return {
        path.relative_to(metadata).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(metadata.rglob("*"))
        if path.is_file()
    }


def prepare_store(store: Path, root: Path = ROOT) -> Path:
    """Copy the acquisition registry and project policies once, then pin them.

    Parameters
    ----------
    store : Path
        Isolated runs/sa17_* directory; an existing unpinned directory is refused.
    root : Path
        Project root, injectable for offline tests.
    """
    store = require_isolated_store(store, root)
    source_metadata = root / "market_data" / "metadata"
    registry_path = root / "research" / "SA17" / "source_instruments.toml"
    InstrumentRegistry.from_toml(registry_path)
    expected = metadata_manifest(source_metadata)
    expected["instruments.toml"] = hashlib.sha256(registry_path.read_bytes()).hexdigest()
    pin = store / "metadata_sha256.json"
    if store.exists():
        if not pin.is_file():
            raise ValueError("Existing SA17 store is unpinned; use a new isolated store")
        recorded = json.loads(pin.read_text(encoding="utf-8"))
        if recorded != expected or metadata_manifest(store / "metadata") != expected:
            raise ValueError("SA17 metadata changed; preserve this archive and use a new store")
        return store
    metadata = store / "metadata"
    shutil.copytree(source_metadata, metadata)
    shutil.copyfile(registry_path, metadata / "instruments.toml")
    with pin.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(expected, indent=2, sort_keys=True) + "\n")
    return store


def build_updater(store: Path) -> MarketDataUpdater:
    """Compose existing providers, normalizers and all committed data policies."""
    metadata = store / "metadata"
    return MarketDataUpdater(
        repository=MarketDataRepository(store),
        instruments=InstrumentRegistry.from_toml(metadata / "instruments.toml"),
        calendars=CalendarRegistry.from_directory(metadata / "calendars"),
        sources={"YAHOO": YahooSource()},
        normalizers=dict(NORMALIZERS),
        accepted_revisions=AcceptedRevisions.from_toml(metadata / "accepted_revisions.toml"),
        action_corrections=ActionCorrections.from_toml(metadata / "corporate_actions.toml"),
        bar_corrections=BarCorrections.from_toml(metadata / "bar_corrections.toml"),
        cross_check_policy=CrossCheckPolicy.from_toml(metadata / "crosscheck.toml"),
        known_gaps=KnownGaps.from_toml(metadata / "known_gaps.toml"),
        conflict_reviews=ConflictReviews.from_toml(metadata / "conflict_reviews.toml"),
    )


def coverage_rows(store: Path, instrument_ids: Sequence[str]) -> list[dict[str, object]]:
    """Describe coverage over each listing's full requested range, gaps included.

    Everything is bounded by :data:`CUTOFF`, never by today's date: the same
    store gives the same report whenever it is written.
    """
    repository = MarketDataRepository(store)
    rows: list[dict[str, object]] = []
    with repository.reading():
        registry = InstrumentRegistry.from_toml(store / "metadata" / "instruments.toml")
        calendars = CalendarRegistry.from_directory(store / "metadata" / "calendars")
        for instrument_id in instrument_ids:
            instrument = registry.get(instrument_id)
            assert instrument.first_session is not None and instrument.calendar_id is not None
            first = instrument.first_session
            frame = repository.load_checked_bars(instrument_id, start=first, end=CUTOFF)
            observed = set(frame["session_date"])
            expected = {
                session.session_date
                for session in calendars.get(instrument.calendar_id).sessions(first, CUTOFF)
            }
            contested = frame.loc[
                frame["check_status"] == CheckStatus.CONFLICT.value, "session_date"
            ]
            fetches = sum(
                len(repository.list_raw_fetches(instrument_id, source))
                for source in instrument.sources
            )
            rows.append(
                {
                    "instrument_id": instrument_id,
                    "symbol": instrument.source_symbol,
                    "requested_start": first.isoformat(),
                    "requested_end": CUTOFF.isoformat(),
                    "clean_rows": len(frame),
                    "stored_from": min(observed).isoformat() if observed else None,
                    "stored_until": max(observed).isoformat() if observed else None,
                    "missing_sessions": [day.isoformat() for day in sorted(expected - observed)],
                    "contested_sessions": [day.isoformat() for day in sorted(contested)],
                    "raw_fetches": fetches,
                    "usable_for_sa17": False,
                    "reason": "Acquisition pool only; USD signal and historical universe unaudited",
                }
            )
    return rows


def main() -> int:
    """Acquire or replay data and write a new evidence file for every invocation."""
    registry = InstrumentRegistry.from_toml(SOURCE_REGISTRY)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, default=STORE)
    parser.add_argument("--only", nargs="+", choices=[instrument.id for instrument in registry])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--coverage-only", action="store_true")
    mode.add_argument("--rebuild", action="store_true")
    arguments = parser.parse_args()
    store = prepare_store(arguments.store)
    updater = build_updater(store)
    selected = tuple(dict.fromkeys(arguments.only or [instrument.id for instrument in registry]))
    outcomes: list[dict[str, object]] = []
    failed = False
    if not arguments.coverage_only:
        for instrument_id in selected:
            instrument = registry.get(instrument_id)
            assert instrument.first_session is not None
            try:
                report = (
                    updater.rebuild_clean(instrument_id)
                    if arguments.rebuild
                    else updater.download(instrument_id, instrument.first_session, CUTOFF)
                )
            except Exception as exc:  # preserve failures in evidence; return nonzero
                failed = True
                outcomes.append({"instrument_id": instrument_id, "exception": repr(exc)})
                print(f"{instrument_id}: FAILED {type(exc).__name__}: {exc}", flush=True)
                continue
            failed |= not report.valid
            outcomes.append(
                {
                    "instrument_id": instrument_id,
                    "valid": report.valid,
                    "issues": [
                        {**asdict(issue), "severity": issue.severity.value}
                        for issue in report.issues
                    ],
                }
            )
            status = "VALIDATED" if report.valid else "REFUSED"
            print(f"{instrument_id}: {status}; {len(report.errors)} errors", flush=True)
            for issue in report.errors:
                print(f"  {issue.code} {issue.observation_date}: {issue.message}", flush=True)
    rows = coverage_rows(store, selected)
    for row in rows:
        print(
            f"{row['instrument_id']}: {row['clean_rows']} rows, "
            f"{row['stored_from']} to {row['stored_until']}",
            flush=True,
        )
    repository = MarketDataRepository(store)
    with repository.reading() as state:
        digest = state.digest
    mode = "coverage" if arguments.coverage_only else "rebuild" if arguments.rebuild else "fetch"
    evidence = {
        "cutoff": CUTOFF.isoformat(),
        "created_at_utc": datetime.now(UTC).isoformat(),
        "mode": mode,
        "research_status": "NOT_TESTED",
        "store_digest": digest,
        "outcomes": outcomes,
        "coverage": rows,
    }
    folder = store / "reports"
    folder.mkdir(exist_ok=True)
    path = folder / f"acquisition_{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}.json"
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(evidence, indent=2, default=str) + "\n")
    print(f"Evidence: {path}", flush=True)
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
