"""Acquire SA17's inputs through the existing data pipeline.

This is a coverage study, not a backtest or a frozen strategy universe. Network
I/O remains in data/sources; MarketDataUpdater owns archival, normalization,
validation, revisions and publication to clean/. No prices are fabricated,
forward-filled, converted to another currency, or substituted for one another.

What is fetched, by role (:data:`ROLES`):

- the ten EUR sector funds declared in research/SA17/source_instruments.toml;
- the market factor, the S&P 500 total-return index in USD (``SP500TR``);
- the EUR monetary fund (XEON) and the ECB EUR/USD reference rate, under their
  existing project declarations;
- the funds of the external references (SA16_it2, its fixed C1 control and
  Nasdaq held), under the SA15 declarations SA16 used.

The store's registry concatenates :data:`REGISTRY_PARTS`, so a fund carries the
same identifier and declaration here as in the earlier stores.

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
from quant_backtester.data.instruments import DataType, Instrument, InstrumentRegistry
from quant_backtester.data.known_gaps import KnownGaps
from quant_backtester.data.normalizer import NORMALIZERS
from quant_backtester.data.repository import MarketDataRepository
from quant_backtester.data.revisions import AcceptedRevisions
from quant_backtester.data.schemas import CheckStatus
from quant_backtester.data.sources.ecb import EcbSource
from quant_backtester.data.sources.yahoo import YahooSource
from quant_backtester.data.updater import MarketDataUpdater

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PARTS = (
    Path("market_data/metadata/instruments.toml"),
    Path("research/SA15_GPT-6.1/instruments.toml"),
    Path("research/SA15_GPT-6.1/round4/instruments.toml"),
    Path("research/SA17/source_instruments.toml"),
)
STORE = ROOT / "runs" / "sa17_store"
CUTOFF = date(2026, 10, 30)
# The project's common archive start; every SA17 month end is later (the
# first sector listing is 2015-07-08). A later declared first session wins.
REQUEST_START = date(2014, 1, 2)
# As in SA16: the 2014-2017 Xetra-Gold archive holds two invalid bars, which
# refuse the whole series. SA16_it2 was run on gold from 2018-01-02.
ARCHIVE_STARTS = {"ETF_GOLD": date(2018, 1, 2)}
SECTOR_IDS = (
    "SA17_ETF_ENERGY",
    "SA17_ETF_MATERIALS",
    "SA17_ETF_INDUSTRIALS",
    "SA17_ETF_CONSUMER_DISCRETIONARY",
    "SA17_ETF_CONSUMER_STAPLES",
    "SA17_ETF_HEALTH_CARE",
    "SA17_ETF_FINANCIALS",
    "SA17_ETF_TECHNOLOGY",
    "SA17_ETF_COMMUNICATION",
    "SA17_ETF_UTILITIES",
)
ROLES: dict[str, str] = {
    **dict.fromkeys(SECTOR_IDS, "SECTOR_FUND"),
    "SP500TR": "MARKET_FACTOR",
    "ETF_MONETARY_EUR": "MONETARY_FUND",
    "ECB_EURUSD": "EUR_USD_REFERENCE_RATE",
    "ETF_US_TECH": "EXTERNAL_REFERENCE",
    "ETF_GOLD": "EXTERNAL_REFERENCE",
    "ETF_NASDAQ": "EXTERNAL_REFERENCE",
}
INSTRUMENT_IDS = tuple(ROLES)


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


def combined_registry(root: Path = ROOT) -> str:
    """Return the store registry: every part of :data:`REGISTRY_PARTS`, in order.

    Each part is read in text mode, so a Windows checkout (CRLF) and a POSIX
    one give the same text, with LF line ends.
    """
    return "\n".join((root / part).read_text(encoding="utf-8") for part in REGISTRY_PARTS)


def check_registry(root: Path = ROOT) -> InstrumentRegistry:
    """Parse every part, refuse an identifier declared twice or one not declared.

    Raises
    ------
    ValueError
        If a part is malformed, or two parts declare the same identifier.
    KeyError
        If an instrument of :data:`INSTRUMENT_IDS` is declared by no part.
    """
    instruments = [
        instrument
        for part in REGISTRY_PARTS
        for instrument in InstrumentRegistry.from_toml(root / part).list_all()
    ]
    registry = InstrumentRegistry(instruments)
    for instrument_id in INSTRUMENT_IDS:
        registry.get(instrument_id)
    return registry


def prepare_store(store: Path, root: Path = ROOT) -> Path:
    """Copy the combined registry and project policies once, then pin them.

    Parameters
    ----------
    store : Path
        Isolated runs/sa17_* directory; an existing unpinned directory is refused.
    root : Path
        Project root, injectable for offline tests.
    """
    store = require_isolated_store(store, root)
    source_metadata = root / "market_data" / "metadata"
    check_registry(root)
    combined = combined_registry(root)
    expected = metadata_manifest(source_metadata)
    expected["instruments.toml"] = hashlib.sha256(combined.encode("utf-8")).hexdigest()
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
    (metadata / "instruments.toml").write_text(combined, encoding="utf-8", newline="\n")
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
        sources={"YAHOO": YahooSource(), "ECB": EcbSource()},
        normalizers=dict(NORMALIZERS),
        accepted_revisions=AcceptedRevisions.from_toml(metadata / "accepted_revisions.toml"),
        action_corrections=ActionCorrections.from_toml(metadata / "corporate_actions.toml"),
        bar_corrections=BarCorrections.from_toml(metadata / "bar_corrections.toml"),
        cross_check_policy=CrossCheckPolicy.from_toml(metadata / "crosscheck.toml"),
        known_gaps=KnownGaps.from_toml(metadata / "known_gaps.toml"),
        conflict_reviews=ConflictReviews.from_toml(metadata / "conflict_reviews.toml"),
    )


def request_start(instrument: Instrument) -> date:
    """Return the first date fetched: the archive start, unless declared later."""
    starts = [REQUEST_START, ARCHIVE_STARTS.get(instrument.id, REQUEST_START)]
    if instrument.first_session is not None:
        starts.append(instrument.first_session)
    return max(starts)


def coverage_rows(store: Path, instrument_ids: Sequence[str]) -> list[dict[str, object]]:
    """Describe coverage over each instrument's full requested range, gaps included.

    Everything is bounded by :data:`CUTOFF`, never by today's date: the same
    store gives the same report whenever it is written. A bar series is
    compared with its venue's sessions. A level series has no venue calendar
    here (the ECB publishes on TARGET days, which are not modelled), so its
    missing days are not computed and are reported as ``None``.
    """
    repository = MarketDataRepository(store)
    rows: list[dict[str, object]] = []
    with repository.reading():
        registry = InstrumentRegistry.from_toml(store / "metadata" / "instruments.toml")
        calendars = CalendarRegistry.from_directory(store / "metadata" / "calendars")
        for instrument_id in instrument_ids:
            instrument = registry.get(instrument_id)
            first = request_start(instrument)
            missing: list[str] | None
            contested: list[str]
            if instrument.data_type is DataType.BAR:
                assert instrument.calendar_id is not None
                frame = repository.load_checked_bars(instrument_id, start=first, end=CUTOFF)
                observed = set(frame["session_date"])
                expected = {
                    session.session_date
                    for session in calendars.get(instrument.calendar_id).sessions(first, CUTOFF)
                }
                missing = [day.isoformat() for day in sorted(expected - observed)]
                conflicts = frame.loc[
                    frame["check_status"] == CheckStatus.CONFLICT.value, "session_date"
                ]
                contested = [day.isoformat() for day in sorted(conflicts)]
            else:
                frame = repository.load_levels(instrument_id, start=first, end=CUTOFF)
                observed = set(frame["observation_date"])
                missing = None
                contested = []
            fetches = sum(
                len(repository.list_raw_fetches(instrument_id, source))
                for source in instrument.sources
            )
            rows.append(
                {
                    "instrument_id": instrument_id,
                    "role": ROLES.get(instrument_id),
                    "symbol": instrument.source_symbol,
                    "requested_start": first.isoformat(),
                    "requested_end": CUTOFF.isoformat(),
                    "clean_rows": len(frame),
                    "stored_from": min(observed).isoformat() if observed else None,
                    "stored_until": max(observed).isoformat() if observed else None,
                    "missing_sessions": missing,
                    "contested_sessions": contested,
                    "raw_fetches": fetches,
                    "usable_for_sa17": False,
                    "reason": "Acquired, not admitted: the SA17 protocol is not frozen",
                }
            )
    return rows


def main() -> int:
    """Acquire or replay data and write a new evidence file for every invocation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, default=STORE)
    parser.add_argument("--only", nargs="+", choices=INSTRUMENT_IDS)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--coverage-only", action="store_true")
    mode.add_argument("--rebuild", action="store_true")
    arguments = parser.parse_args()
    store = prepare_store(arguments.store)
    updater = build_updater(store)
    registry = InstrumentRegistry.from_toml(store / "metadata" / "instruments.toml")
    selected = tuple(dict.fromkeys(arguments.only or INSTRUMENT_IDS))
    outcomes: list[dict[str, object]] = []
    failed = False
    if not arguments.coverage_only:
        for instrument_id in selected:
            instrument = registry.get(instrument_id)
            try:
                report = (
                    updater.rebuild_clean(instrument_id)
                    if arguments.rebuild
                    else updater.download(instrument_id, request_start(instrument), CUTOFF)
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
            print(
                f"{instrument_id}: {status}; {len(report.errors)} errors, "
                f"{len(report.warnings)} warnings",
                flush=True,
            )
            for issue in report.errors:
                print(f"  {issue.code} {issue.observation_date}: {issue.message}", flush=True)
    rows = coverage_rows(store, selected)
    for row in rows:
        missing = row["missing_sessions"]
        print(
            f"{row['instrument_id']}: {row['clean_rows']} rows, "
            f"{row['stored_from']} to {row['stored_until']}, "
            f"missing={len(missing) if isinstance(missing, list) else 'n/a'}",
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
