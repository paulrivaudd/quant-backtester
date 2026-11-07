"""Acquire EUR/USD at the US close for SA17's risk inputs, from Dukascopy bars.

Admission gate 2d of ``research/SA17/protocol.md``: the USD NAVs are priced at
the US close, so converting them to EUR needs the rate at that instant, not a
fixing taken hours earlier. The owner chose Dukascopy on 2026-11-07
(``research/SA17/admission.md``). The close of each session is the XNYS
calendar's: 16:00 New York, or 13:00 on a half day.

Run from the repository root::

    uv run python scripts/SA17_acquire_fx.py fetch --archive runs/sa17_fx_20261107
    uv run python scripts/SA17_acquire_fx.py verify --archive runs/sa17_fx_20261107
    uv run python scripts/SA17_acquire_fx.py build --archive runs/sa17_fx_20261107

``fetch`` downloads the bid and ask files of hourly bars of every month from
July 2015 to October 2026, through ``data/sources/dukascopy.py``: about 270
requests, one at a time, five seconds apart. ``verify`` downloads the minute
files of a seeded random sample of 24 sessions. Both are resumable: an archived
file is never fetched or written again. Each file is recorded in
``manifest.jsonl`` (address, hash, retrieval instant) before it is moved into
place, so an interrupted run leaves either a complete, recorded file or none.
After a refusal for too many requests the run waits five minutes once; a
second refusal anywhere in the run stops it, to be resumed later.

``build`` reads only the archive and fails unless every sampled session's
hourly rate equals its minute rate. It writes ``derived/eurusd_us_close.parquet``
(one row per XNYS session: the mid of the bid and ask closes of the last bar
with ticks ending at the session close, at most five minutes before it) and
``derived/coverage.json``. The table is an audit product of the archive; the
executable study ingests it into its store as a non-tradable LEVEL series.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from quant_backtester.data.calendars import CalendarRegistry, Session, TradingCalendar
from quant_backtester.data.sources.base import ProviderRateLimited, ProviderUnavailable
from quant_backtester.data.sources.dukascopy import (
    DukascopyDownload,
    DukascopySource,
    QuoteBar,
    Side,
    parse_hour_bars,
    parse_minute_bars,
    rate_at,
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
TOLERANCE = 1e-9
"""Hourly and minute rates are the same quotes: they must agree to rounding."""


class RunStopped(RuntimeError):
    """Raised when the provider refuses a second time in one run."""


@dataclass
class Throttle:
    """What the run has been told by the provider so far."""

    refused: bool = False


def xnys() -> TradingCalendar:
    """Return the project's XNYS calendar, which gives each session's close."""
    calendars = CalendarRegistry.from_directory(ROOT / "market_data" / "metadata" / "calendars")
    return calendars.get("XNYS")


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


def sample(sessions: Sequence[Session]) -> list[Session]:
    """Return the seeded random sample of sessions the verification reads.

    Drawn from the full declared range whatever range a command is given, so
    ``verify`` and ``build`` always mean the same days.
    """
    return sorted(
        random.Random(SAMPLE_SEED).sample(list(sessions), SAMPLE_SIZE),
        key=lambda session: session.session_date,
    )


def store(
    archive: Path,
    path: Path,
    download: Callable[[], DukascopyDownload],
    kind: str,
    throttle: Throttle,
) -> bool:
    """Fetch one file unless archived; record it, then move it into place.

    Returns
    -------
    bool
        Whether a file was written.

    Raises
    ------
    RunStopped
        On the run's second refusal for too many requests.
    """
    if path.exists():
        return False
    result = None
    for attempt in range(4):
        try:
            result = download()
            break
        except ProviderRateLimited as error:
            if throttle.refused:
                raise RunStopped(f"refused twice; resume later ({path.name})") from error
            throttle.refused = True
            time.sleep(RATE_LIMIT_WAIT_SECONDS)
        except ProviderUnavailable:
            time.sleep(30 * (attempt + 1))
    if result is None:
        print(f"gave up on {path.name} for this run", file=sys.stderr)
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".part")
    partial.write_bytes(result.payload)
    # Recorded before it is moved into place: an interruption leaves a
    # recorded hash and no file, which the next run fetches again (the latest
    # record of a file is the one kept), never a file nobody recorded.
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
        manifest.flush()
        os.fsync(manifest.fileno())
    os.replace(partial, path)
    time.sleep(PAUSE_SECONDS)
    return True


def fetch(archive: Path) -> int:
    """Download every missing monthly hourly file of the range."""
    archive.mkdir(parents=True, exist_ok=True)
    source, throttle, written = DukascopySource(), Throttle(), 0
    for year, month in months(START, END):
        for side in Side:
            written += store(
                archive,
                hours_path(archive, year, month, side),
                lambda y=year, m=month, s=side: source.fetch_month_hours(PAIR, y, m, s),
                "hours",
                throttle,
            )
    return written


def fetch_sample(archive: Path) -> int:
    """Download the minute files of the verification sample."""
    source, throttle, written = DukascopySource(), Throttle(), 0
    for session in sample(xnys().sessions(START, END)):
        for side in Side:
            written += store(
                archive,
                minutes_path(archive, session.session_date, side),
                lambda d=session.session_date, s=side: source.fetch_day(PAIR, d, s),
                "minutes",
                throttle,
            )
    return written


def read_manifest(archive: Path) -> dict[str, str]:
    """Return the latest recorded hash of every archived file."""
    recorded: dict[str, str] = {}
    with (archive / "manifest.jsonl").open(encoding="utf-8") as manifest:
        for line in manifest:
            entry = json.loads(line)
            recorded[entry["file"]] = entry["sha256"]
    return recorded


def checked(archive: Path, path: Path, recorded: Mapping[str, str]) -> bytes:
    """Return an archived file's bytes, refused unless the manifest records them."""
    key = str(path.relative_to(archive))
    if key not in recorded:
        raise ValueError(f"{key} is in the archive but not in its manifest")
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != recorded[key]:
        raise ValueError(f"{key} does not hash to its manifest entry")
    return payload


def build(archive: Path) -> dict[str, Any]:
    """Read the rate at every session's close from the archived files.

    Raises
    ------
    ValueError
        If a file is unrecorded or altered, or the verification compared
        fewer than the whole sample or found a difference.
    """
    recorded = read_manifest(archive)
    calendar = xnys()
    sessions = calendar.sessions(START, END)
    hours: dict[tuple[int, int], dict[Side, tuple[QuoteBar, ...]]] = {}
    for year, month in months(START, END):
        paths = {side: hours_path(archive, year, month, side) for side in Side}
        if all(path.exists() for path in paths.values()):
            hours[(year, month)] = {
                side: parse_hour_bars(checked(archive, path, recorded), PAIR, year, month)
                for side, path in paths.items()
            }
    rows = []
    missing: list[str] = []
    without_rate: list[str] = []
    for session in sessions:
        day = session.session_date
        bars = hours.get((day.year, day.month))
        if bars is None:
            missing.append(day.isoformat())
            continue
        observed = rate_at(bars[Side.BID], bars[Side.ASK], session.close_utc, MAX_STALENESS)
        if observed is None:
            without_rate.append(day.isoformat())
            continue
        rows.append(
            {
                "observation_date": day,
                "instant_utc": observed.instant_utc,
                "usd_per_eur": observed.rate,
                "bid": observed.bid,
                "ask": observed.ask,
                "bar_end_utc": observed.bar_end_utc,
            }
        )
    by_day = {row["observation_date"]: row["usd_per_eur"] for row in rows}
    comparisons = []
    for session in sample(sessions):
        day = session.session_date
        paths = {side: minutes_path(archive, day, side) for side in Side}
        minute = None
        if all(path.exists() for path in paths.values()):
            bid = parse_minute_bars(checked(archive, paths[Side.BID], recorded), PAIR, day)
            ask = parse_minute_bars(checked(archive, paths[Side.ASK], recorded), PAIR, day)
            minute = rate_at(bid, ask, session.close_utc, MAX_STALENESS)
        hourly = by_day.get(day)
        comparisons.append(
            {
                "date": day.isoformat(),
                "close_utc": session.close_utc.isoformat(),
                "hourly": hourly,
                "minute": None if minute is None else minute.rate,
                "minute_staleness_seconds": None
                if minute is None
                else int(minute.staleness.total_seconds()),
                "agree": hourly is not None
                and minute is not None
                and abs(hourly - minute.rate) <= TOLERANCE,
            }
        )
    failed = [item["date"] for item in comparisons if not item["agree"]]
    if failed:
        raise ValueError(
            f"verification failed on {len(failed)} of {SAMPLE_SIZE} sampled sessions "
            f"(not compared, or hourly and minute rates differ): {failed[:5]}; "
            "run verify, or look at the feed before using the table"
        )
    derived = archive / "derived"
    derived.mkdir(exist_ok=True)
    table = derived / "eurusd_us_close.parquet"
    pd.DataFrame(rows).to_parquet(table, index=False)
    coverage = {
        "pair": PAIR,
        "quote": "USD per EUR, mid of bid and ask closes",
        "source": "DUKASCOPY hourly bars, one file per month and side",
        "instant": "each XNYS session's close (16:00 New York, 13:00 on a half day)",
        "max_staleness_seconds": int(MAX_STALENESS.total_seconds()),
        "range": [START.isoformat(), END.isoformat()],
        "sessions": len(sessions),
        "rates": len(rows),
        "half_day_rates": sum(
            1 for row in rows if row["observation_date"] in calendar.early_closes
        ),
        "missing_months": sorted({day[:7] for day in missing}),
        "without_rate": without_rate,
        "verification": {
            "seed": SAMPLE_SEED,
            "sample": SAMPLE_SIZE,
            "tolerance": TOLERANCE,
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
    parsed = parser.parse_args(arguments)
    archive = parsed.archive if parsed.archive.is_absolute() else ROOT / parsed.archive
    if archive.resolve().parent != (ROOT / "runs").resolve() or not archive.name.startswith(
        "sa17_fx_"
    ):
        raise ValueError("use a runs/sa17_fx_* directory")
    try:
        if parsed.action == "fetch":
            print(f"written {fetch(archive)} files")
        elif parsed.action == "verify":
            print(f"written {fetch_sample(archive)} files")
        else:
            coverage = build(archive)
            print(
                f"{coverage['rates']} rates of {coverage['sessions']} sessions; "
                f"missing months {coverage['missing_months']}; "
                f"{len(coverage['without_rate'])} without a rate; verification passed"
            )
    except RunStopped as stop:
        print(f"stopped: {stop}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
