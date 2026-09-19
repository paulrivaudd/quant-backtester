"""Print the ``[[revision]]`` entry accepting one detected revision.

A decision names the source and the exact transition it approves, and all of
them have to match what was detected to the last bit. A float copied by hand
from a report rarely does, so the entry is generated from the row that recorded
it::

    uv run python scripts/accept_revision.py SP500 2026-09-18 close
    uv run python scripts/accept_revision.py US10Y 2026-09-09 value --table levels
    uv run python scripts/accept_revision.py ETF_WORLD 2025-10-24 close --source EURONEXT

``--source`` is only needed when two providers revised the same field of the
same date: each has a canonical series of its own, so accepting a correction on
one says nothing about the other.

The output goes into ``market_data/metadata/accepted_revisions.toml``, where the
reason replaces the placeholder. Nothing is written here: accepting a revision
changes numbers already produced, so it belongs in a diff someone reads.
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from quant_backtester.data.revisions import AcceptedRevision

ROOT = Path(__file__).resolve().parents[1] / "market_data"
"""Market data root holding ``clean/revisions.parquet``."""

PLACEHOLDER = "TODO: why this correction was accepted, and what it was checked against."
"""Reason to replace before committing. A decision without one cannot be re-examined."""


def main() -> int:
    """Find the revision and print its entry, or say why it cannot be found."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("instrument_id")
    parser.add_argument("observation_date", type=date.fromisoformat)
    parser.add_argument("field")
    parser.add_argument("--table", default="bars", choices=["bars", "levels"])
    parser.add_argument(
        "--source",
        help="provider, when more than one revised the same field of the same date",
    )
    arguments = parser.parse_args()

    path = ROOT / "clean" / "revisions.parquet"
    if not path.exists():
        print(f"No revision log at {path}")
        return 1
    log = pd.read_parquet(path)
    found = log[
        (log["instrument_id"] == arguments.instrument_id)
        & (log["observation_date"] == arguments.observation_date)
        & (log["field"] == arguments.field)
        & (log["table"] == arguments.table)
    ]
    if arguments.source is not None:
        found = found.loc[found["source"] == arguments.source]
    what = (
        f"{arguments.instrument_id} {arguments.table}.{arguments.field} "
        f"on {arguments.observation_date}"
    )
    if found.empty:
        print(f"No revision of {what} was ever detected.")
        return 1
    records: list[dict[str, Any]] = found.to_dict("records")  # type: ignore[assignment]
    sources = sorted({str(record["source"]) for record in records})
    if len(sources) > 1:
        print(f"{what} was revised by {', '.join(sources)}; pick one with --source.")
        return 1
    # Several refetches may have moved the same field; the last one is the
    # correction on the table today, and the only one worth reviewing.
    latest = max(records, key=lambda record: record["detected_at_utc"])
    if len(records) > 1:
        print(f"# {len(records)} revisions of this field were detected; this is the latest.")
    print(AcceptedRevision.from_detected(latest, PLACEHOLDER).to_toml())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
