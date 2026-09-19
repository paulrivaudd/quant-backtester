"""Print the ``[[revision]]`` entry accepting one detected revision.

A decision names the exact transition it approves, and the two values have to
match what was detected to the last bit. A float copied by hand from a report
rarely does, so the entry is generated from the row that recorded it::

    uv run python scripts/accept_revision.py SP500 2026-09-10 close
    uv run python scripts/accept_revision.py US10Y 2026-09-09 value --table levels

The output goes into ``market_data/metadata/accepted_revisions.toml``, where the
reason is filled in by whoever reviewed the correction. Nothing is written here:
accepting a revision changes numbers already produced, so it belongs in a diff
someone reads.
"""

from __future__ import annotations

import argparse
import math
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1] / "market_data"
"""Market data root holding ``clean/revisions.parquet``."""


def toml_value(value: float) -> str:
    """Return a value as TOML, round-tripping exactly.

    Parameters
    ----------
    value : float
        Value as stored or as refetched.

    Returns
    -------
    str
        ``repr`` of the float, or ``nan`` for a value the provider did not
        publish. Both are read back as the same float by ``tomllib``.
    """
    return "nan" if math.isnan(value) else repr(float(value))


def entry(row: Mapping[str, Any], table: str) -> str:
    """Return the TOML table accepting the revision ``row`` recorded.

    Parameters
    ----------
    row : Mapping[str, Any]
        One record of ``clean/revisions.parquet``.
    table : str
        ``"bars"`` or ``"levels"``.

    Returns
    -------
    str
        A ``[[revision]]`` table, its reason left to fill in.
    """
    return "\n".join(
        [
            "[[revision]]",
            f'instrument_id = "{row["instrument_id"]}"',
            f'table = "{table}"',
            f"observation_date = {row['observation_date']}",
            f'field = "{row["field"]}"',
            f"old_value = {toml_value(float(row['old_value']))}",
            f"new_value = {toml_value(float(row['new_value']))}",
            'reason = "TODO: why this correction was accepted, and what it was checked against."',
        ]
    )


def main() -> int:
    """Find the revision and print its entry, or say why it cannot be found."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("instrument_id")
    parser.add_argument("observation_date", type=date.fromisoformat)
    parser.add_argument("field")
    parser.add_argument("--table", default="bars", choices=["bars", "levels"])
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
    if found.empty:
        print(
            f"No revision of {arguments.instrument_id} {arguments.table}.{arguments.field} "
            f"on {arguments.observation_date} was ever detected."
        )
        return 1
    # Several refetches may have moved the same field; the last one is the
    # correction on the table today, and the only one worth reviewing.
    records: list[dict[str, Any]] = found.to_dict("records")  # type: ignore[assignment]
    latest = max(records, key=lambda record: record["detected_at_utc"])
    if len(found) > 1:
        print(f"# {len(found)} revisions of this field were detected; this is the latest.")
    print(entry(latest, arguments.table))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
