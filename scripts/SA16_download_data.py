"""Build the isolated SA16 data store through the project's data pipeline.

Run under WSL/POSIX from the repository root (the store lock needs ``fcntl``)::

    uv run python scripts/SA16_download_data.py
    uv run python scripts/SA16_download_data.py --only NDX VIX3M
    uv run python scripts/SA16_download_data.py --coverage-only

Only ``runs/sa16_store`` (or ``--store``) is written. Its registry is the
project registry followed by the SA15 additions and the SA16 signal-only
series, so the funds traded by SA15 and SA16 are fetched, normalised and
validated by the same code. The production ``market_data/`` and the SA15
stores are not touched. The research end is frozen at 2026-10-30, the last
complete session before the study started; histories are restated provider
snapshots retrieved on the day the script runs, not point-in-time vintages.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from dataclasses import asdict
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any

from quant_backtester.data.bar_corrections import BarCorrections
from quant_backtester.data.calendars import CalendarRegistry
from quant_backtester.data.conflict_reviews import ConflictReviews
from quant_backtester.data.corporate_actions import ActionCorrections
from quant_backtester.data.crosscheck import CrossCheckPolicy
from quant_backtester.data.instruments import DataType, InstrumentRegistry
from quant_backtester.data.known_gaps import KnownGaps
from quant_backtester.data.normalizer import NORMALIZERS
from quant_backtester.data.repository import MarketDataRepository
from quant_backtester.data.revisions import AcceptedRevisions
from quant_backtester.data.sources.ecb import EcbSource
from quant_backtester.data.sources.euronext import EuronextSource
from quant_backtester.data.sources.fred import FredSource
from quant_backtester.data.sources.yahoo import YahooSource
from quant_backtester.data.updater import MarketDataUpdater

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "runs" / "sa16_store"
REGISTRY_PARTS = (
    ROOT / "market_data" / "metadata" / "instruments.toml",
    ROOT / "research" / "SA15_GPT-6.1" / "instruments.toml",
    ROOT / "research" / "SA15_GPT-6.1" / "round4" / "instruments.toml",
    ROOT / "research" / "SA16" / "instruments.toml",
)
STUDY_START = date(2014, 1, 2)
STUDY_END = date(2026, 10, 30)
INSTRUMENT_IDS = (
    # traded funds: the SA15 universe, unchanged
    "ETF_NASDAQ",
    "ETF_US_TECH",
    "ETF_SP500_PEA",
    "ETF_WORLD",
    "ETF_EMERGING",
    "ETF_GOLD",
    "ETF_EURO_GOV",
    "ETF_COMMODITY",
    "ETF_MONETARY_EUR",
    "ETF_WORLD_HEALTH",
    "ETF_WORLD_UTILITIES",
    # information only
    "SP500",
    "VIX",
    "US10Y",
    "ECB_EURUSD",
    "NDX",
    "GLD_US",
    "HYG_US",
    "IEF_US",
    "VIX3M",
)
# The archive starts SA15 declared, kept so that the same funds carry the same
# bars: the 2014-2017 gold archive holds two invalid bars, and the three R4
# sector funds were archived from 2017.
ARCHIVE_STARTS = {
    "ETF_GOLD": date(2018, 1, 2),
    "ETF_US_TECH": date(2017, 1, 2),
    "ETF_WORLD_HEALTH": date(2017, 1, 2),
    "ETF_WORLD_UTILITIES": date(2017, 1, 2),
}


def combined_registry() -> str:
    """Return the store registry: every declared part, in a fixed order."""
    return "\n".join(path.read_text(encoding="utf-8") for path in REGISTRY_PARTS)


def metadata_manifest(metadata: Path) -> dict[str, str]:
    """Hash every metadata file of the store, by relative path."""
    return {
        path.relative_to(metadata).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(metadata.rglob("*"))
        if path.is_file()
    }


def prepare_store(store: Path) -> None:
    """Copy the reviewed metadata once, then refuse any silent change to it.

    Raises
    ------
    ValueError
        If the store's registry or metadata no longer match their sources.
    """
    metadata = store / "metadata"
    combined = combined_registry()
    if not metadata.exists():
        shutil.copytree(ROOT / "market_data" / "metadata", metadata)
        (metadata / "instruments.toml").write_text(combined, encoding="utf-8")
    elif (metadata / "instruments.toml").read_text(encoding="utf-8") != combined:
        raise ValueError(
            "the store registry differs from its declared parts; build a new store "
            "rather than rewriting the metadata an archive was made under"
        )
    InstrumentRegistry.from_toml(metadata / "instruments.toml")
    manifest = metadata_manifest(metadata)
    manifest_path = store / "metadata_sha256.json"
    if manifest_path.exists() and json.loads(manifest_path.read_text()) != manifest:
        raise ValueError("the store metadata changed since the previous invocation")
    if not manifest_path.exists():
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")


def build_updater(store: Path, end: date) -> MarketDataUpdater:
    """Wire the project's providers, normalisers, validators and reviews.

    Parameters
    ----------
    store : Path
        Root of the isolated store.
    end : date
        Last research date; the clock is 23:59 UTC that day, after every close.
    """
    metadata = store / "metadata"
    return MarketDataUpdater(
        repository=MarketDataRepository(store),
        instruments=InstrumentRegistry.from_toml(metadata / "instruments.toml"),
        calendars=CalendarRegistry.from_directory(metadata / "calendars"),
        sources={
            "YAHOO": YahooSource(),
            "FRED": FredSource(),
            "ECB": EcbSource(),
            "EURONEXT": EuronextSource(),
        },
        normalizers=dict(NORMALIZERS),
        accepted_revisions=AcceptedRevisions.from_toml(metadata / "accepted_revisions.toml"),
        action_corrections=ActionCorrections.from_toml(metadata / "corporate_actions.toml"),
        bar_corrections=BarCorrections.from_toml(metadata / "bar_corrections.toml"),
        cross_check_policy=CrossCheckPolicy.from_toml(metadata / "crosscheck.toml"),
        known_gaps=KnownGaps.from_toml(metadata / "known_gaps.toml"),
        conflict_reviews=ConflictReviews.from_toml(metadata / "conflict_reviews.toml"),
        clock=lambda: datetime.combine(end, time(23, 59), tzinfo=UTC),
    )


def archive_start(instrument_id: str, requested: date, first_session: date | None) -> date:
    """Return the first date fetched for one instrument."""
    return max(requested, first_session or requested, ARCHIVE_STARTS.get(instrument_id, requested))


def coverage_rows(
    store: Path, updater: MarketDataUpdater, ids: tuple[str, ...], start: date, end: date
) -> list[dict[str, Any]]:
    """Describe the clean coverage of each instrument, gaps listed by kind."""
    registry = InstrumentRegistry.from_toml(store / "metadata" / "instruments.toml")
    repository = MarketDataRepository(store)
    rows = []
    for instrument_id in ids:
        instrument = registry.get(instrument_id)
        coverage = updater.history_coverage(instrument_id)
        since = archive_start(instrument_id, start, instrument.first_session)
        bars = instrument.data_type is DataType.BAR
        frame = (
            repository.load_checked_bars(instrument_id)
            if bars
            else repository.load_levels(instrument_id)
        )
        key = "session_date" if bars else "observation_date"
        if not frame.empty:
            frame = frame.loc[(frame[key] >= since) & (frame[key] <= end)]
        rows.append(
            {
                "instrument_id": instrument_id,
                "symbol": instrument.source_symbol,
                "requested_start": since,
                "requested_end": end,
                "clean_rows": len(frame),
                "stored_from": None if frame.empty else min(frame[key]),
                "stored_until": None if frame.empty else max(frame[key]),
                "raw_fetches": coverage.raw_fetches,
                "unreviewed_missing_sessions": [
                    day for day in coverage.unexplained_sessions or () if since <= day <= end
                ],
                "contested_sessions": [
                    day for day in coverage.contested_sessions or () if since <= day <= end
                ],
                "reviewed_gap_sessions": [
                    day for day in coverage.known_gaps if since <= day <= end
                ],
            }
        )
    return rows


def main() -> int:
    """Download the declared window and write the evidence of what was stored."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, default=STORE)
    parser.add_argument("--only", nargs="+", choices=INSTRUMENT_IDS)
    parser.add_argument("--coverage-only", action="store_true")
    arguments = parser.parse_args()
    store = arguments.store.resolve()
    prepare_store(store)
    updater = build_updater(store, STUDY_END)
    registry = InstrumentRegistry.from_toml(store / "metadata" / "instruments.toml")
    selected = tuple(arguments.only or INSTRUMENT_IDS)
    outcomes: list[dict[str, Any]] = []
    failed = False
    if not arguments.coverage_only:
        for instrument_id in selected:
            instrument = registry.get(instrument_id)
            start = archive_start(instrument_id, STUDY_START, instrument.first_session)
            try:
                report = updater.download(instrument_id, start, STUDY_END)
            except Exception as exc:  # recorded and reported, never swallowed
                failed = True
                outcomes.append({"instrument_id": instrument_id, "exception": repr(exc)})
                print(f"{instrument_id:<20} RAISED {type(exc).__name__}: {exc}", flush=True)
                continue
            failed = failed or not report.valid
            outcomes.append(
                {
                    "instrument_id": instrument_id,
                    "valid": report.valid,
                    "errors": len(report.errors),
                    "warnings": len(report.warnings),
                    "issues": [
                        {**asdict(issue), "severity": issue.severity.value}
                        for issue in report.issues
                    ],
                }
            )
            print(
                f"{instrument_id:<20} {'WRITTEN' if report.valid else 'REFUSED':<8} "
                f"{len(report.errors)} error(s), {len(report.warnings)} warning(s)",
                flush=True,
            )
            for issue in report.errors:
                print(f"  ERROR {issue.code} {issue.observation_date}: {issue.message}", flush=True)
    rows = coverage_rows(store, updater, selected, STUDY_START, STUDY_END)
    for row in rows:
        print(
            f"{row['instrument_id']:<20} {row['clean_rows']:>5} rows "
            f"{row['stored_from']} -> {row['stored_until']}; "
            f"missing={len(row['unreviewed_missing_sessions'])} "
            f"contested={len(row['contested_sessions'])} "
            f"reviewed={len(row['reviewed_gap_sessions'])}",
            flush=True,
        )
    evidence = {
        "study_start": STUDY_START,
        "study_end": STUDY_END,
        "retrieved_at": datetime.now(UTC).isoformat(),
        "retrieval_note": "restated provider snapshots downloaded now, not vintages",
        "outcomes": outcomes,
        "coverage": rows,
    }
    folder = store / "reports"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"download_{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}.json"
    path.write_text(json.dumps(evidence, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"evidence: {path}", flush=True)
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
