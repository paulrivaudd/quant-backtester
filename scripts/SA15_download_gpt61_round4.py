"""Clone the frozen SA15 store and archive three R4 sector ETFs separately.

Only the new store is written. Existing prices, raw snapshots and R1-R3
metadata stay unchanged. Provider calls run through the data-layer updater.
The three accumulating sector classes existed before the chosen 2017 archive.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path

import SA15_download_data as base

from quant_backtester.data.instruments import InstrumentRegistry

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = ROOT / "runs/sa15_gpt61_store"
STORE = ROOT / "runs/sa15_gpt61_r4_store"
EXTRA = ROOT / "research/SA15_GPT-6.1/round4/instruments.toml"
IDS = ("ETF_US_TECH", "ETF_WORLD_HEALTH", "ETF_WORLD_UTILITIES")


def prepare_store() -> None:
    """Copy the frozen origin once, then verify the new metadata snapshot."""
    combined = (ORIGIN / "metadata/instruments.toml").read_text(encoding="utf-8")
    combined += "\n" + EXTRA.read_text(encoding="utf-8")
    if not STORE.exists():
        shutil.copytree(ORIGIN, STORE)
        (STORE / "metadata/instruments.toml").write_text(combined, encoding="utf-8")
        manifest = {
            str(path.relative_to(STORE / "metadata")): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((STORE / "metadata").rglob("*"))
            if path.is_file()
        }
        (STORE / "metadata_sha256.json").write_text(json.dumps(manifest, indent=2) + "\n")
        (STORE / "r4_origin.json").write_text(
            json.dumps(
                {"origin": str(ORIGIN), "new_ids": IDS, "old_prices": "copied unchanged"}, indent=2
            )
            + "\n"
        )
    elif (STORE / "metadata/instruments.toml").read_text(encoding="utf-8") != combined:
        raise ValueError("R4 registry differs from its declared source; no silent metadata rewrite")
    InstrumentRegistry.from_toml(STORE / "metadata/instruments.toml")
    expected = json.loads((STORE / "metadata_sha256.json").read_text())
    actual = {
        str(path.relative_to(STORE / "metadata")): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((STORE / "metadata").rglob("*"))
        if path.is_file()
    }
    if actual != expected:
        raise ValueError("R4 metadata fingerprint differs")


def main() -> int:
    """Download new funds through normalizers and validators, preserving rejects."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage-only", action="store_true")
    args = parser.parse_args()
    prepare_store()
    base.STORE = STORE
    end = date(2026, 10, 9)
    start = date(2017, 1, 2)
    updater = base.build_updater(end)
    outcomes = []
    failed = False
    if not args.coverage_only:
        for instrument_id in IDS:
            try:
                report = updater.download(instrument_id, start, end)
                failed = failed or not report.valid
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
                print(
                    f"{instrument_id}: valid={report.valid}, errors={len(report.errors)}",
                    flush=True,
                )
                for issue in report.errors:
                    print(f"  {issue.code} {issue.observation_date}: {issue.message}", flush=True)
            except Exception as exc:
                failed = True
                outcomes.append({"instrument_id": instrument_id, "exception": repr(exc)})
                print(f"{instrument_id}: {exc!r}", flush=True)
    coverage = base.coverage_rows(updater, IDS, start, end)
    for row in coverage:
        print(
            f"{row['instrument_id']}: {row['clean_rows']} rows, "
            f"missing={len(row['unreviewed_missing_sessions'])}, "
            f"contested={len(row['contested_sessions'])}",
            flush=True,
        )
    evidence = (
        STORE
        / "reports"
        / ("r4_download_" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + ".json")
    )
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(
        json.dumps({"outcomes": outcomes, "coverage": coverage}, default=str, indent=2) + "\n"
    )
    print(f"Evidence: {evidence.relative_to(ROOT)}", flush=True)
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
