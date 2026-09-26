"""Fetch every committed instrument into the local market data tree.

Run it from the repository root::

    uv run python scripts/update_market_data.py            # extend every series
    uv run python scripts/update_market_data.py --rebuild  # replay raw/ into clean/
    uv run python scripts/update_market_data.py --only SP500
    uv run python scripts/update_market_data.py --archive --only ETF_WORLD
    uv run python scripts/update_market_data.py --coverage # what the store is missing

``--archive`` fetches an instrument's whole declared history rather than
extending it. It is the command to run for a name that may be delisted: once a
provider stops serving it, nobody can go back for its prices, and a universe
dated correctly is of no use without them.

The tree it writes lives under ``market_data/``: ``metadata/`` is committed,
``raw/``, ``clean/`` and ``validation/`` are not. Everything the pipeline needs
to decide is in the metadata, so the same command on the same archive rebuilds
the same clean layer.

This is the only place in the project that touches the network on purpose, and
it never runs from a test.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from quant_backtester.data.bar_corrections import BarCorrections
from quant_backtester.data.calendars import CalendarRegistry
from quant_backtester.data.corporate_actions import ActionCorrections
from quant_backtester.data.crosscheck import CrossCheckPolicy
from quant_backtester.data.instruments import InstrumentRegistry
from quant_backtester.data.normalizer import NORMALIZERS
from quant_backtester.data.repository import MarketDataRepository
from quant_backtester.data.revisions import AcceptedRevisions
from quant_backtester.data.sources.alfred import AlfredSource
from quant_backtester.data.sources.ecb import EcbSource
from quant_backtester.data.sources.euronext import EuronextSource
from quant_backtester.data.sources.fred import FredSource
from quant_backtester.data.sources.yahoo import YahooSource
from quant_backtester.data.updater import HistoryCoverage, MarketDataUpdater
from quant_backtester.data.validator import Severity, ValidationReport

ROOT = Path(__file__).resolve().parents[1] / "market_data"
"""Repository root: the committed metadata and the local data next to it."""

SOURCES = {
    "YAHOO": YahooSource,
    "FRED": FredSource,
    "ALFRED": AlfredSource,
    "ECB": EcbSource,
    "EURONEXT": EuronextSource,
}
"""Adapter per source identifier, built on demand.

``ALFRED`` serves a published series as it stood on a chosen day. An instrument
declaring it also declares the ``vintage_date`` it is pinned to, and the
adapter refuses to fetch without one: a vintage left unsaid is the restated
series again, under another name."""


def build_updater(root: Path) -> MarketDataUpdater:
    """Wire an updater onto the committed configuration.

    Parameters
    ----------
    root : Path
        Market data root holding ``metadata/``.

    Returns
    -------
    MarketDataUpdater
        Ready to fetch, with every reviewed decision loaded.
    """
    metadata = root / "metadata"
    return MarketDataUpdater(
        repository=MarketDataRepository(root),
        instruments=InstrumentRegistry.from_toml(metadata / "instruments.toml"),
        calendars=CalendarRegistry.from_directory(metadata / "calendars"),
        sources={name: source() for name, source in SOURCES.items()},
        normalizers=dict(NORMALIZERS),
        accepted_revisions=AcceptedRevisions.from_toml(metadata / "accepted_revisions.toml"),
        action_corrections=ActionCorrections.from_toml(metadata / "corporate_actions.toml"),
        bar_corrections=BarCorrections.from_toml(metadata / "bar_corrections.toml"),
        cross_check_policy=CrossCheckPolicy.from_toml(metadata / "crosscheck.toml"),
    )


def report_line(instrument_id: str, report: ValidationReport) -> str:
    """Return one readable line summarising a report."""
    errors = len(report.errors)
    warnings = len(report.warnings)
    verdict = "written" if report.valid else "REFUSED"
    return f"{instrument_id:<12} {verdict:<8} {errors} error(s), {warnings} warning(s)"


def coverage_line(coverage: HistoryCoverage) -> str:
    """Return one readable line saying what is missing of a declared history."""
    span = (
        f"{coverage.stored_from} -> {coverage.stored_until}"
        if coverage.stored_from is not None
        else "nothing stored"
    )
    ends = [
        f"{label} {window[0]} -> {window[1]}"
        for label, window in (
            ("before", coverage.missing_head),
            ("after", coverage.missing_tail),
        )
        if window is not None
    ]
    if coverage.missing_sessions is None:
        # A published series: only its ends can be checked, and the line says so.
        gaps = "ends covered (inside not checked)" if not ends else "MISSING " + ", ".join(ends)
    else:
        inside = [
            day
            for day in coverage.missing_sessions
            if coverage.stored_from is not None
            and coverage.stored_until is not None
            and coverage.stored_from < day < coverage.stored_until
        ]
        parts = ends + ([f"{len(inside)} session(s) inside"] if inside else [])
        gaps = "complete" if not parts else "MISSING " + ", ".join(parts)
        if coverage.contested_sessions:
            gaps += f", {len(coverage.contested_sessions)} contested"
    return f"{coverage.instrument_id:<14} {span:<26} {coverage.raw_fetches:>3} fetch(es)  {gaps}"


def main() -> int:
    """Run the update or the rebuild, and return a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="replay the raw archive into clean/ instead of fetching",
    )
    parser.add_argument(
        "--archive",
        action="store_true",
        help="fetch the whole declared history instead of extending the series",
    )
    parser.add_argument(
        "--coverage",
        action="store_true",
        help="report what the store holds of each declared history, and fetch nothing",
    )
    parser.add_argument("--only", metavar="ID", help="restrict to one instrument")
    arguments = parser.parse_args()
    if arguments.rebuild and arguments.archive:
        parser.error("--rebuild replays the archive and --archive extends it; pick one")

    for subdirectory in ("raw", "clean", "validation"):
        (ROOT / subdirectory).mkdir(parents=True, exist_ok=True)

    updater = build_updater(ROOT)
    registry = InstrumentRegistry.from_toml(ROOT / "metadata" / "instruments.toml")
    instruments = [registry.get(arguments.only)] if arguments.only else registry.list_all()

    if arguments.coverage:
        for instrument in instruments:
            print(coverage_line(updater.history_coverage(instrument.id)))
        return 0

    failed = False
    for instrument in instruments:
        try:
            if arguments.rebuild:
                report = updater.rebuild_clean(instrument.id)
            elif arguments.archive:
                report = updater.archive_history(instrument.id)
            else:
                report = updater.update(instrument.id)
        except Exception as error:  # the next instrument must still run
            print(f"{instrument.id:<12} RAISED   {type(error).__name__}: {error}")
            failed = True
            continue
        print(report_line(instrument.id, report))
        for issue in report.issues:
            if issue.severity is Severity.ERROR:
                print(f"    ERROR {issue.code} {issue.observation_date}: {issue.message}")
        failed = failed or not report.valid
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
