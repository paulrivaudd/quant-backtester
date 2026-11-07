"""Inventory an existing store for SA17 without calculating strategy returns.

Run on POSIX with the project's Python environment. This reads the local store
under its shared lock and records its digest, available dates, missing sessions
inside each observed bar range, and corporate-action counts. Date coverage is
not a claim of point-in-time availability or suitability for SA17. In particular,
this does not certify total returns, sector mappings, or historical listings.

The output is deterministic for the same store and script. An output file must
not already exist; rerunning an audit must not replace dated evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from quant_backtester.data.calendars import CalendarRegistry, TradingCalendar
from quant_backtester.data.instruments import DataType, InstrumentRegistry
from quant_backtester.data.repository import MarketDataRepository


def date_coverage(dates: Sequence[date], calendar: TradingCalendar | None) -> dict[str, object]:
    """Describe observed dates, without extending their range or filling gaps.

    Parameters
    ----------
    dates : Sequence[date]
        Stored session dates (or observation dates for a published level).
    calendar : TradingCalendar | None
        Declared venue calendar for bars; None for published levels. Calendar
        coverage errors propagate rather than inventing sessions.
    """
    observed = sorted(set(dates))
    result: dict[str, object] = {
        "rows": len(dates),
        "unique_dates": len(observed),
        "first_observation": observed[0].isoformat() if observed else None,
        "last_observation": observed[-1].isoformat() if observed else None,
        "missing_sessions_within_observed_range": None,
        "non_session_dates": None,
    }
    if observed and calendar is not None:
        expected = {s.session_date for s in calendar.sessions(observed[0], observed[-1])}
        result["missing_sessions_within_observed_range"] = [
            day.isoformat() for day in sorted(expected - set(observed))
        ]
        result["non_session_dates"] = [day.isoformat() for day in sorted(set(observed) - expected)]
    return result


def inventory(store: Path) -> dict[str, object]:
    """Read coverage and provenance, without evaluating a strategy.

    Parameters
    ----------
    store : Path
        Existing market data root. As for other repository readers, opening it
        may recover an interrupted store transaction before acquiring the lock.
    """
    repository = MarketDataRepository(store)
    with repository.reading() as state:
        instruments = InstrumentRegistry.from_toml(store / "metadata" / "instruments.toml")
        calendars = CalendarRegistry.from_directory(store / "metadata" / "calendars")
        rows: list[dict[str, object]] = []
        for instrument in sorted(instruments, key=lambda item: item.id):
            if instrument.data_type == DataType.BAR:
                frame = repository.load_bars(instrument.id)
                dates = frame["session_date"].tolist()
                assert instrument.calendar_id is not None
                calendar = calendars.get(instrument.calendar_id)
            else:
                frame = repository.load_levels(instrument.id)
                dates = frame["observation_date"].tolist()
                calendar = None
            actions = repository.load_corporate_actions(instrument.id)
            rows.append(
                {
                    "id": instrument.id,
                    "name": instrument.name,
                    "symbol": instrument.source_symbol,
                    "currency": instrument.currency,
                    "data_type": instrument.data_type.value,
                    "tradable": instrument.tradable,
                    "declared_first_session": (
                        instrument.first_session.isoformat() if instrument.first_session else None
                    ),
                    "calendar": instrument.calendar_id,
                    "history_basis": (
                        instrument.history_basis.value if instrument.history_basis else None
                    ),
                    "coverage": date_coverage(dates, calendar),
                    "corporate_actions": {
                        str(kind): int(count)
                        for kind, count in sorted(actions["action_type"].value_counts().items())
                    },
                }
            )
        return {
            "schema_version": 1,
            "purpose": "LOCAL_COVERAGE_ONLY_NOT_RESEARCH_READINESS",
            "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "store_digest": state.digest,
            "files_sha256": dict(state.files),
            "calendars": {
                calendar.calendar_id: {
                    "covered_from": calendar.covered_from.isoformat(),
                    "covered_until": calendar.covered_until.isoformat(),
                }
                for calendar in sorted(calendars, key=lambda item: item.calendar_id)
            },
            "instruments": rows,
        }


def main() -> int:
    """Write a deterministic inventory, refusing to overwrite earlier evidence."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    if arguments.output is not None and arguments.output.exists():
        parser.error(f"Audit output already exists: {arguments.output}")
    report = json.dumps(inventory(arguments.store), indent=2, sort_keys=True) + "\n"
    if arguments.output is None:
        print(report, end="")
    else:
        with arguments.output.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
