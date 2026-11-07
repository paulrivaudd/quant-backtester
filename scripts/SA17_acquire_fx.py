"""Acquire EUR/USD at the US close for SA17's risk inputs, from Dukascopy bars.

Admission gate 2d of ``research/SA17/protocol.md``: the USD NAVs are priced at
the US close, so converting them to EUR needs the rate at 16:00 New York, not a
fixing taken hours earlier. The owner chose Dukascopy on 2026-11-07
(``research/SA17/admission.md``).

Run from the repository root::

    uv run python scripts/SA17_acquire_fx.py fetch --archive runs/sa17_fx_20261107
    uv run python scripts/SA17_acquire_fx.py verify --archive runs/sa17_fx_20261107
    uv run python scripts/SA17_acquire_fx.py build --archive runs/sa17_fx_20261107

``fetch`` downloads the bid and ask files of hourly bars of every month in the
range, through the adapter in ``data/sources/dukascopy.py``: about 270
requests, one at a time, five seconds apart. After a refusal for too many
requests it waits five minutes once; a second refusal stops the run, which a
later run resumes. ``verify`` downloads the minute files of a
seeded random sample of sessions and checks that the hour ending at 16:00 New
York closes on the same quotes as the minute ending then. Both write each file
once and never rewrite it; run again, they fetch only what is missing.
``manifest.jsonl`` records each file's address, hash and retrieval instant.

``build`` reads only the archive. It writes ``derived/eurusd_us_close.csv``: one
row per XNYS session, the mid of the bid and ask closes of the hour ending at
16:00 New York, or nothing when that hour is missing. It also writes
``derived/coverage.json``, with the verification's result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import time
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from quant_backtester.data.calendars import CalendarRegistry
from quant_backtester.data.sources.base import ProviderRateLimited, ProviderUnavailable
from quant_backtester.data.sources.dukascopy import (
    DukascopyDownload,
    DukascopySource,
    QuoteBar,
    Side,
    parse_hour_bars,
    parse_minute_bars,
    rate_at,
    us_close_utc,
)

ROOT = Path(__file__).resolve().parents[1]
PAIR = "EURUSD"
START = date(2015, 7, 1)
END = date(2026, 10, 30)
PAUSE_SECONDS = 5.0
RATE_LIMIT_WAIT_SECONDS = 300
MAX_STALENESS = timedelta(minutes=5)
SAMPLE_SEED = 20261107
SAMPLE_SIZE = 24


def sessions(start: date, end: date) -> list[date]:
    """Return the XNYS sessions of the project's calendar between two dates."""
    calendars = CalendarRegistry.from_directory(ROOT / "market_data" / "metadata" / "calendars")
    return [session.session_date for session in calendars.get("XNYS").sessions(start, end)]


def months(start: date, end: date) -> list[tuple[int, int]]:
    """Return every (year, month) from ``start``'s month to ``end``'s."""
    first, last = start.year * 12 + start.month - 1, end.year * 12 + end.month - 1
    return [(ordinal // 12, ordinal % 12 + 1) for ordinal in range(first, last + 1)]


def hours_path(archive: Path, year: int, month: int, side: Side) -> Path:
    """Return where one month's hourly file of one side is archived."""
    return archive / "raw" / "hours" / side.value / f"{year:04d}-{month:02d}.bi5"


def minutes_path(archive: Path, day: date, side: Side) -> Path:
    """Return where one day's minute file of one side is archived."""
    return archive / "raw" / "minutes" / side.value / f"{day.isoformat()}.bi5"


def sample(start: date, end: date) -> list[date]:
    """Return the seeded random sample of sessions the verification reads."""
    days = sessions(start, end)
    return sorted(random.Random(SAMPLE_SEED).sample(days, SAMPLE_SIZE))


def store(archive: Path, path: Path, download: Callable[[], DukascopyDownload], kind: str) -> bool:
    """Fetch one file unless archived, write it once, record it; return whether written."""
    if path.exists():
        return False
    result = None
    limited = False
    for attempt in range(4):
        try:
            result = download()
            break
        except ProviderRateLimited:
            # Wait once; a second refusal ends the run rather than press a
            # provider that has asked us to stop. Run again later to resume.
            if limited:
                raise
            limited = True
            time.sleep(RATE_LIMIT_WAIT_SECONDS)
        except ProviderUnavailable:
            time.sleep(30 * (attempt + 1))
    if result is None:
        print(f"gave up on {path.name}", file=sys.stderr)
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:  # written once, never replaced
        stream.write(result.payload)
    with (archive / "manifest.jsonl").open("a", encoding="utf-8") as manifest:
        manifest.write(
            json.dumps(
                {
                    "kind": kind,
                    "file": str(path.relative_to(archive)),
                    "url": result.url,
                    "sha256": result.sha256,
                    "bytes": len(result.payload),
                    "retrieved_at_utc": result.retrieved_at_utc.isoformat(),
                }
            )
            + "\n"
        )
    time.sleep(PAUSE_SECONDS)
    return True


def fetch(archive: Path, start: date, end: date) -> int:
    """Download every missing monthly hourly file of the range."""
    archive.mkdir(parents=True, exist_ok=True)
    source = DukascopySource()
    written = 0
    for year, month in months(start, end):
        for side in Side:
            written += store(
                archive,
                hours_path(archive, year, month, side),
                lambda y=year, m=month, s=side: source.fetch_month_hours(PAIR, y, m, s),
                "hours",
            )
    return written


def fetch_sample(archive: Path, start: date, end: date) -> int:
    """Download the minute files of the verification sample."""
    source = DukascopySource()
    written = 0
    for day in sample(start, end):
        for side in Side:
            written += store(
                archive,
                minutes_path(archive, day, side),
                lambda d=day, s=side: source.fetch_day(PAIR, d, s),
                "minutes",
            )
    return written


def checked(archive: Path, path: Path, recorded: dict[str, str]) -> bytes:
    """Return an archived file's bytes, refused if they differ from the manifest."""
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != recorded[str(path.relative_to(archive))]:
        raise ValueError(f"{path} does not hash to its manifest entry")
    return payload


def build(archive: Path, start: date, end: date) -> dict[str, Any]:
    """Read the rate at the US close of every session from the archived files."""
    recorded: dict[str, str] = {}
    with (archive / "manifest.jsonl").open(encoding="utf-8") as manifest:
        for line in manifest:
            entry = json.loads(line)
            recorded[entry["file"]] = entry["sha256"]
    hours: dict[tuple[int, int], dict[Side, tuple[QuoteBar, ...]]] = {}
    for year, month in months(start, end):
        paths = {side: hours_path(archive, year, month, side) for side in Side}
        if all(path.exists() for path in paths.values()):
            hours[(year, month)] = {
                side: parse_hour_bars(checked(archive, path, recorded), PAIR, year, month)
                for side, path in paths.items()
            }
    rows = []
    missing_months: set[str] = set()
    without_rate: list[str] = []
    for day in sessions(start, end):
        bars = hours.get((day.year, day.month))
        if bars is None:
            missing_months.add(f"{day.year:04d}-{day.month:02d}")
            continue
        observed = rate_at(bars[Side.BID], bars[Side.ASK], us_close_utc(day), MAX_STALENESS)
        if observed is None:
            without_rate.append(day.isoformat())
            continue
        rows.append(
            {
                "date": day.isoformat(),
                "instant_utc": observed.instant_utc.isoformat(),
                "usd_per_eur": observed.rate,
                "bid": observed.bid,
                "ask": observed.ask,
            }
        )
    by_day = {row["date"]: row["usd_per_eur"] for row in rows}
    comparisons = []
    for day in sample(start, end):
        paths = {side: minutes_path(archive, day, side) for side in Side}
        if not all(path.exists() for path in paths.values()) or day.isoformat() not in by_day:
            continue
        bid = parse_minute_bars(checked(archive, paths[Side.BID], recorded), PAIR, day)
        ask = parse_minute_bars(checked(archive, paths[Side.ASK], recorded), PAIR, day)
        minute = rate_at(bid, ask, us_close_utc(day), MAX_STALENESS)
        comparisons.append(
            {
                "date": day.isoformat(),
                "hourly": by_day[day.isoformat()],
                "minute": None if minute is None else minute.rate,
                "minute_staleness_seconds": None
                if minute is None
                else int(minute.staleness.total_seconds()),
            }
        )
    derived = archive / "derived"
    derived.mkdir(exist_ok=True)
    table = derived / "eurusd_us_close.csv"
    pd.DataFrame(rows).to_csv(table, index=False)
    differences = [
        abs(item["hourly"] - item["minute"]) for item in comparisons if item["minute"] is not None
    ]
    coverage = {
        "pair": PAIR,
        "quote": "USD per EUR, mid of bid and ask closes",
        "source": "DUKASCOPY hourly bars, one file per month and side",
        "instant": "16:00 America/New_York on each XNYS session: the hour ending then",
        "range": [start.isoformat(), end.isoformat()],
        "sessions": len(rows)
        + len(without_rate)
        + sum(
            1 for day in sessions(start, end) if f"{day.year:04d}-{day.month:02d}" in missing_months
        ),
        "rates": len(rows),
        "missing_months": sorted(missing_months),
        "without_rate": without_rate,
        "verification": {
            "seed": SAMPLE_SEED,
            "sample": SAMPLE_SIZE,
            "compared": len(differences),
            "max_abs_difference": max(differences) if differences else None,
            "days": comparisons,
        },
        "table_sha256": hashlib.sha256(table.read_bytes()).hexdigest(),
        "history_basis": "SNAPSHOT_UNVERIFIED: a retrieval, not a historical vintage",
    }
    (derived / "coverage.json").write_text(json.dumps(coverage, indent=2) + "\n", encoding="utf-8")
    return coverage


def main(arguments: list[str] | None = None) -> int:
    """Fetch, verify or build from the command line."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("action", choices=("fetch", "verify", "build"))
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--start", type=date.fromisoformat, default=START)
    parser.add_argument("--end", type=date.fromisoformat, default=END)
    parsed = parser.parse_args(arguments)
    archive = parsed.archive if parsed.archive.is_absolute() else ROOT / parsed.archive
    if archive.resolve().parent != (ROOT / "runs").resolve() or not archive.name.startswith(
        "sa17_fx_"
    ):
        raise ValueError("use a runs/sa17_fx_* directory")
    if parsed.action == "fetch":
        print(f"written {fetch(archive, parsed.start, parsed.end)} files")
    elif parsed.action == "verify":
        print(f"written {fetch_sample(archive, parsed.start, parsed.end)} files")
    else:
        coverage = build(archive, parsed.start, parsed.end)
        check = coverage["verification"]
        print(
            f"{coverage['rates']} rates of {coverage['sessions']} sessions; "
            f"missing months {coverage['missing_months']}; "
            f"{len(coverage['without_rate'])} without a rate; "
            f"verification {check['compared']} days, max difference {check['max_abs_difference']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
