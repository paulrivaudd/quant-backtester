"""Warn when a committed trading calendar is about to run out.

A calendar covers a declared period and raises outside it, which is the right
behaviour - inventing sessions past the end of a holiday list is how a backtest
quietly trades on Christmas. The cost is that the pipeline stops the day the
period ends.

This is an operational check, not a test. A ``pytest`` assertion on the wall
clock would turn red one morning with no code having changed, and the suite is
deterministic and offline on purpose. Run it from CI or by hand::

    uv run python scripts/check_calendar_coverage.py
    uv run python scripts/check_calendar_coverage.py --days 180

It exits non-zero when a calendar has less than ``--days`` left, so a scheduled
job can fail on it. The fix is to extend the horizon by about a year with
``scripts/generate_calendars.py`` and review the diff.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from quant_backtester.data.calendars import CalendarRegistry

CALENDARS_DIR = Path(__file__).resolve().parents[1] / "market_data" / "metadata" / "calendars"
"""Where the committed calendar files live."""

DEFAULT_MARGIN_DAYS = 90
"""Warn this far ahead: enough to extend and review a diff without hurrying."""


def main() -> int:
    """Report each calendar's remaining coverage, and fail if any is short."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_MARGIN_DAYS,
        help=f"fail below this many days of coverage (default {DEFAULT_MARGIN_DAYS})",
    )
    arguments = parser.parse_args()

    today = datetime.now(UTC).date()
    short = False
    for calendar in CalendarRegistry.from_directory(CALENDARS_DIR):
        left = (calendar.covered_until - today).days
        verdict = "OK" if left >= arguments.days else "EXTEND"
        if left < arguments.days:
            short = True
        print(
            f"{calendar.calendar_id:<6} covered until {calendar.covered_until}  "
            f"{left:>5}d  {verdict}"
        )
    if short:
        print("\nRun: uv run python scripts/generate_calendars.py, then review the diff.")
    return 1 if short else 0


if __name__ == "__main__":
    raise SystemExit(main())
