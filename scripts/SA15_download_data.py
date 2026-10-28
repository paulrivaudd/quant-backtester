"""Archive the isolated SA15 data store through the project's trusted pipeline.

Run from the repository root under WSL/POSIX, using the existing environment::

    .venv/bin/python scripts/SA15_download_data.py
    .venv/bin/python scripts/SA15_download_data.py --coverage-only
    .venv/bin/python scripts/SA15_download_data.py --only ETF_GOLD

The default end is deliberately frozen at 2026-10-09 for the research study.
An explicit --end can archive a later available date, but cannot change which
observations a strategy's decision timestamp is allowed to read. Raw downloads
are immutable; rejected bars are archived and reported, never repaired here.
The gold clean series starts explicitly in 2018, because two invalid 2017
bars made the complete 2014 archive unusable; the rejected archive is retained.
Only runs/sa15_gpt61_store is written. The production market_data metadata,
existing result files, dependency environment and lockfile are unchanged.
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

PROJECT = Path(__file__).resolve().parents[1]
STORE = PROJECT / "runs" / "sa15_gpt61_store"
EXTRA_INSTRUMENTS = PROJECT / "research" / "SA15_GPT-6.1" / "instruments.toml"
DEFAULT_IDS = (
    "ETF_SP500_PEA",
    "ETF_WORLD",
    "ETF_MONETARY_EUR",
    "ETF_NASDAQ",
    "ETF_EMERGING",
    "ETF_GOLD",
    "ETF_EURO_GOV",
    "ETF_COMMODITY",
    "SP500",
    "VIX",
    "US10Y",
)

# Agreed before any strategy test: keep the rejected 2014 gold archive, but
# only ingest its valid 2018-onward segment. This never changes a price.
ARCHIVE_START_OVERRIDES = {"ETF_GOLD": date(2018, 1, 2)}


def prepare_store() -> None:
    """Copy reviewed metadata once and reject silent later configuration changes."""
    baseline = PROJECT / "market_data" / "metadata"
    metadata = STORE / "metadata"
    combined = (baseline / "instruments.toml").read_text() + "\n" + EXTRA_INSTRUMENTS.read_text()
    if not metadata.exists():
        shutil.copytree(baseline, metadata)
        (metadata / "instruments.toml").write_text(combined)
    elif (metadata / "instruments.toml").read_text() != combined:
        raise ValueError(
            "Isolated registry differs from its source configuration; review the "
            "metadata change explicitly before reusing this archived data store"
        )
    InstrumentRegistry.from_toml(metadata / "instruments.toml")
    manifest = {
        str(path.relative_to(metadata)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(metadata.rglob("*"))
        if path.is_file()
    }
    manifest_path = STORE / "metadata_sha256.json"
    if manifest_path.exists() and json.loads(manifest_path.read_text()) != manifest:
        raise ValueError("Isolated metadata snapshot changed since the previous invocation")
    if not manifest_path.exists():
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")


def build_updater(end: date) -> MarketDataUpdater:
    """Wire existing providers, normalizers, validators and reviewed corrections.

    Parameters
    ----------
    end : date
        Last UTC research date. Coverage is measured after every market close
        on this date; provider retrieval timestamps remain the actual timestamps.
    """
    metadata = STORE / "metadata"
    return MarketDataUpdater(
        repository=MarketDataRepository(STORE),
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


def coverage_rows(
    updater: MarketDataUpdater, instrument_ids: tuple[str, ...], start: date, end: date
) -> list[dict[str, Any]]:
    """Return actual clean coverage, separating unavailable and contested sessions."""
    registry = InstrumentRegistry.from_toml(STORE / "metadata" / "instruments.toml")
    repository = MarketDataRepository(STORE)
    rows = []
    for instrument_id in instrument_ids:
        instrument = registry.get(instrument_id)
        coverage = updater.history_coverage(instrument_id)
        since = max(
            start,
            instrument.first_session or start,
            ARCHIVE_START_OVERRIDES.get(instrument_id, start),
        )
        missing = [day for day in coverage.unexplained_sessions or () if since <= day <= end]
        contested = [day for day in coverage.contested_sessions or () if since <= day <= end]
        frame = (
            repository.load_checked_bars(instrument_id)
            if instrument.data_type is DataType.BAR
            else repository.load_levels(instrument_id)
        )
        key = "session_date" if instrument.data_type is DataType.BAR else "observation_date"
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
                "unreviewed_missing_sessions": missing,
                "contested_sessions": contested,
                "reviewed_gap_sessions": [
                    day for day in coverage.known_gaps if since <= day <= end
                ],
            }
        )
    return rows


def main() -> int:
    """Download the declared study window and write readable validation evidence."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, default=date(2014, 1, 2))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2026, 10, 9))
    parser.add_argument("--only", nargs="+", choices=DEFAULT_IDS)
    parser.add_argument("--coverage-only", action="store_true")
    arguments = parser.parse_args()
    if arguments.start > arguments.end:
        parser.error("--start must not follow --end")
    prepare_store()
    updater = build_updater(arguments.end)
    registry = InstrumentRegistry.from_toml(STORE / "metadata" / "instruments.toml")
    selected = tuple(arguments.only or DEFAULT_IDS)
    outcomes = []
    failed = False
    if not arguments.coverage_only:
        for instrument_id in selected:
            instrument = registry.get(instrument_id)
            start = max(
                arguments.start,
                instrument.first_session or arguments.start,
                ARCHIVE_START_OVERRIDES.get(instrument_id, arguments.start),
            )
            try:
                report = updater.download(instrument_id, start, arguments.end)
                record = {
                    "instrument_id": instrument_id,
                    "valid": report.valid,
                    "errors": len(report.errors),
                    "warnings": len(report.warnings),
                    "issues": [
                        {**asdict(issue), "severity": issue.severity.value}
                        for issue in report.issues
                    ],
                }
                failed = failed or not report.valid
                print(
                    f"{instrument_id:<20} {'WRITTEN' if report.valid else 'REFUSED':<8} "
                    f"{len(report.errors)} error(s), {len(report.warnings)} warning(s)",
                    flush=True,
                )
                for issue in report.errors:
                    print(
                        f"  ERROR {issue.code} {issue.observation_date}: {issue.message}",
                        flush=True,
                    )
            except Exception as exc:
                failed = True
                record = {"instrument_id": instrument_id, "exception": repr(exc)}
                print(f"{instrument_id:<20} RAISED {type(exc).__name__}: {exc}", flush=True)
            outcomes.append(record)
    rows = coverage_rows(updater, selected, arguments.start, arguments.end)
    for row in rows:
        print(
            f"{row['instrument_id']:<20} {row['clean_rows']:>4} rows "
            f"{row['stored_from']} -> {row['stored_until']}; "
            f"missing={len(row['unreviewed_missing_sessions'])}, "
            f"contested={len(row['contested_sessions'])}",
            flush=True,
        )
    report = {
        "study_start": arguments.start,
        "study_end": arguments.end,
        "retrieval_note": (
            "Historical provider snapshots downloaded now; not point-in-time vintages"
        ),
        "outcomes": outcomes,
        "coverage": rows,
    }
    report_directory = STORE / "reports"
    report_directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    report_path = report_directory / f"download_{timestamp}.json"
    report_path.write_text(json.dumps(report, indent=2, default=str) + "\n")
    print(f"Evidence: {report_path.relative_to(PROJECT)}", flush=True)
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
