"""Extend the paper store: the SA16 study's store, followed forward day by day.

Run under WSL/POSIX from the repository root, before ``scripts/paper_trade.py``::

    uv run python scripts/paper_update_store.py

The first invocation copies the study's store (``runs/sa16_store``, built by
``scripts/SA16_download_data.py`` and frozen at 2026-10-30) to
``runs/paper_sa16_store``, so the paper books start on the very bars the
study was read on. Every invocation then extends each series to the last
observation entirely published at the wall clock: a session still trading is
never fetched. The study's store is never written.

The rules are the data pipeline's and are not relaxed here: stored values
win, a refetch that disagrees with history is logged and dropped, and nothing
is promoted while a validation error stands. An instrument refused today is
reported, the script exits non-zero, and the paper run waits: it logs no
session the store is incomplete for.

This is the only script of the paper run that touches the network.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from SA16_download_data import (  # noqa: E402
    INSTRUMENT_IDS,
    STUDY_END,
    build_updater,
    prepare_store,
)
from SA16_download_data import STORE as STUDY_STORE  # noqa: E402

from quant_backtester.data.updater import MarketDataUpdater  # noqa: E402

STORE = ROOT / "runs" / "paper_sa16_store"
SEEDED = ("metadata", "metadata_sha256.json", "raw", "clean", "validation")
"""What a store is made of. Its reports and its lock are its own."""


def seed_store(store: Path, seed: Path) -> bool:
    """Copy the study's store once; return whether it was copied now.

    Raises
    ------
    FileNotFoundError
        If neither store exists: the study's has to be built first.
    """
    if store.exists():
        return False
    if not (seed / "metadata_sha256.json").exists():
        raise FileNotFoundError(
            f"{seed} is not a built store; run scripts/SA16_download_data.py first"
        )
    partial = store.with_name(store.name + ".partial")
    if partial.exists():
        shutil.rmtree(partial)
    partial.mkdir(parents=True)
    for name in SEEDED:
        source = seed / name
        if source.is_dir():
            shutil.copytree(source, partial / name)
        elif source.exists():
            shutil.copy2(source, partial / name)
    partial.rename(store)
    return True


def update_store(updater: MarketDataUpdater, instruments: Sequence[str]) -> list[dict[str, Any]]:
    """Extend every series, one at a time, and return what happened to each.

    An instrument that raises or is refused does not stop the others: each
    outcome is recorded, never swallowed.
    """
    outcomes: list[dict[str, Any]] = []
    for instrument_id in instruments:
        try:
            report = updater.update(instrument_id)
        except Exception as exc:  # recorded and reported, never swallowed
            outcomes.append({"instrument_id": instrument_id, "exception": repr(exc)})
            print(f"{instrument_id:<20} RAISED {type(exc).__name__}: {exc}", flush=True)
            continue
        outcomes.append(
            {
                "instrument_id": instrument_id,
                "valid": report.valid,
                "errors": len(report.errors),
                "warnings": len(report.warnings),
                "issues": [
                    {**asdict(issue), "severity": issue.severity.value} for issue in report.issues
                ],
            }
        )
        print(
            f"{instrument_id:<20} {'EXTENDED' if report.valid else 'REFUSED':<8} "
            f"{len(report.errors)} error(s), {len(report.warnings)} warning(s)",
            flush=True,
        )
        for issue in report.errors:
            print(f"  ERROR {issue.code} {issue.observation_date}: {issue.message}", flush=True)
    return outcomes


def failed(outcomes: Sequence[dict[str, Any]]) -> bool:
    """Return whether an instrument raised or was refused."""
    return any("exception" in outcome or not outcome["valid"] for outcome in outcomes)


def main(arguments: Sequence[str] | None = None) -> int:
    """Seed the paper store if needed, extend it, and write what was done."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--store", type=Path, default=STORE)
    parser.add_argument("--seed", type=Path, default=STUDY_STORE)
    parser.add_argument("--only", nargs="+", choices=INSTRUMENT_IDS)
    parsed = parser.parse_args(arguments)
    store = parsed.store.resolve()
    if seed_store(store, parsed.seed.resolve()):
        print(f"seeded {store} from {parsed.seed}", flush=True)
    prepare_store(store)
    now = datetime.now(UTC)
    updater = build_updater(store, STUDY_END, clock=lambda: now)
    outcomes = update_store(updater, tuple(parsed.only or INSTRUMENT_IDS))
    folder = store / "reports"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"paper_update_{now.strftime('%Y%m%dT%H%M%S%fZ')}.json"
    evidence = {"updated_at": now.isoformat(), "outcomes": outcomes}
    path.write_text(json.dumps(evidence, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"evidence: {path}", flush=True)
    return int(failed(outcomes))


if __name__ == "__main__":
    raise SystemExit(main())
