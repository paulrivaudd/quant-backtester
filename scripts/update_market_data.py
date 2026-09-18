"""Fetch every committed instrument into the local market data tree.

Run it from the repository root::

    uv run python scripts/update_market_data.py            # extend every series
    uv run python scripts/update_market_data.py --rebuild  # replay raw/ into clean/
    uv run python scripts/update_market_data.py --only SP500

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

from quant_backtester.data.calendars import CalendarRegistry
from quant_backtester.data.corporate_actions import ActionCorrections
from quant_backtester.data.crosscheck import CrossCheckPolicy
from quant_backtester.data.instruments import InstrumentRegistry
from quant_backtester.data.normalizer import NORMALIZERS
from quant_backtester.data.repository import MarketDataRepository
from quant_backtester.data.revisions import AcceptedRevisions
from quant_backtester.data.sources.ecb import EcbSource
from quant_backtester.data.sources.euronext import EuronextSource
from quant_backtester.data.sources.fred import FredSource
from quant_backtester.data.sources.yahoo import YahooSource
from quant_backtester.data.updater import MarketDataUpdater
from quant_backtester.data.validator import Severity, ValidationReport

ROOT = Path(__file__).resolve().parents[1] / "market_data"
"""Repository root: the committed metadata and the local data next to it."""

SOURCES = {
    "YAHOO": YahooSource,
    "FRED": FredSource,
    "ECB": EcbSource,
    "EURONEXT": EuronextSource,
}
"""Adapter per source identifier, built on demand."""


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
        cross_check_policy=CrossCheckPolicy.from_toml(metadata / "crosscheck.toml"),
    )


def report_line(instrument_id: str, report: ValidationReport) -> str:
    """Return one readable line summarising a report."""
    errors = len(report.errors)
    warnings = len(report.warnings)
    verdict = "written" if report.valid else "REFUSED"
    return f"{instrument_id:<12} {verdict:<8} {errors} error(s), {warnings} warning(s)"


def main() -> int:
    """Run the update or the rebuild, and return a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="replay the raw archive into clean/ instead of fetching",
    )
    parser.add_argument("--only", metavar="ID", help="restrict to one instrument")
    arguments = parser.parse_args()

    for subdirectory in ("raw", "clean", "validation"):
        (ROOT / subdirectory).mkdir(parents=True, exist_ok=True)

    updater = build_updater(ROOT)
    registry = InstrumentRegistry.from_toml(ROOT / "metadata" / "instruments.toml")
    instruments = [registry.get(arguments.only)] if arguments.only else registry.list_all()

    failed = False
    for instrument in instruments:
        try:
            report = (
                updater.rebuild_clean(instrument.id)
                if arguments.rebuild
                else updater.update(instrument.id)
            )
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
