"""Run the reference experiments, and print what each of them did.

Every figure the README cites comes out of this script, from a suite with a
name - so a number in the documentation can always be traced back to a command
and the code that produced it. Run it from the repository root, once the local
store is filled::

    uv run python scripts/run_baselines.py                      # the baselines table
    uv run python scripts/run_baselines.py --suite readme       # the README's own runs
    uv run python scripts/run_baselines.py --suite all --records out/
    uv run python scripts/run_baselines.py --period 2024-01-02:2026-09-17

The ``baselines`` suite runs four strategies, each testing one more piece of
the chain than the last:

- ``buy_and_hold`` buys the world fund once and keeps it - execution, costs,
  whole shares and the cash they leave;
- ``equal_weight`` restates half and half at the end of every month - turnover,
  several orders, the sale that pays for the purchase;
- ``momentum_rotation`` holds the fund with the better sixty-session momentum -
  signals, the strategy, the portfolio and execution together;
- ``momentum_vix`` does the same, and stands aside while the VIX is more than
  one and a half standard deviations above its sixty-observation mean - a gauge
  that is read and never held.

The ``readme`` suite runs what the README prints: the reference rotation with
its full report and its comparison with the world fund, and buy and hold
against the equal weight over the same period.

Every run records what it was made with - the configuration, the fingerprint of
the strategy and the state of this checkout - and ``--records`` writes each
run's sessions, orders, fills, rejects and holdings to CSV, every float written
so that it reads back to the same bits: two versions of the code can be
compared run for run, not only on the totals.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from quant_backtester.analytics.config import AnalyticsConfig
from quant_backtester.backtest.runner import StrategyResult, StrategyRunner
from quant_backtester.backtest.schedule import DecisionSchedule, EverySession, Monthly
from quant_backtester.data.calendars import CalendarRegistry
from quant_backtester.data.instruments import InstrumentRegistry
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.data.repository import MarketDataRepository
from quant_backtester.data.universes import UniverseRegistry
from quant_backtester.execution.costs import CostModel
from quant_backtester.execution.model import ExecutionModel
from quant_backtester.provenance import git_source_state
from quant_backtester.research.archive import keep
from quant_backtester.research.registry import ExperimentRegistry, record_of
from quant_backtester.strategies.base import Strategy
from quant_backtester.strategies.examples import (
    BuyAndHold,
    EqualWeightRebalance,
    MomentumRotation,
    MomentumVix,
)

REPOSITORY = Path(__file__).resolve().parents[1]
"""The checkout this script runs from: its code, and its market data store."""

STORE = REPOSITORY / "market_data"
"""The committed metadata and the local data next to it."""

REGISTRY = REPOSITORY / "research" / "registry.jsonl"
"""The experiment register, committed with the code."""

UNIVERSE = "ROTATION_2"
"""The two PEA funds every experiment chooses among."""

BENCHMARK = "ETF_WORLD"
"""What every run is measured against: simply holding the world fund."""

INITIAL_CASH = 100_000.0
"""What every run starts with, in euros."""

EXECUTION = ExecutionModel(
    costs=CostModel(
        commission_rate=0.0005,
        minimum_commission=1.0,
        half_spread_rate=0.0002,
        slippage_rate=0.0001,
    ),
    minimum_trade_value=500.0,
)
"""Five basis points of commission with a one-euro floor, two of half spread and
one of slippage, and no order below five hundred euros: a retail broker on a
liquid Paris ETF, stated rather than assumed."""

ANALYTICS = AnalyticsConfig(sessions_per_year=255, risk_free_rate=0.02)
"""The annualisation every figure is computed under."""

PERIODS: tuple[tuple[str, str], ...] = (
    ("2018-07-16", "2026-09-17"),
    ("2019-01-02", "2021-12-31"),
    ("2022-01-03", "2023-12-29"),
    ("2024-01-02", "2026-09-17"),
)
"""The whole history both funds share once a sixty-session window exists, and
three regimes inside it: a long rise with a crash in it, a fall and its
recovery, and the recent run."""

README_PERIOD: tuple[str, str] = ("2025-01-02", "2026-09-17")
"""The period of the README's reference run."""

BOTH_FUNDS = ("ETF_SP500_PEA", "ETF_WORLD")
"""The two members of the universe, in instrument order."""


@dataclass(frozen=True, slots=True)
class Baseline:
    """One strategy, and the calendar it is asked on."""

    label: str
    strategy: Strategy
    schedule: DecisionSchedule


BASELINES: tuple[Baseline, ...] = (
    Baseline("buy_and_hold", BuyAndHold(instruments=("ETF_WORLD",)), EverySession()),
    Baseline("equal_weight", EqualWeightRebalance(instruments=BOTH_FUNDS), Monthly()),
    Baseline("momentum_rotation", MomentumRotation(lookback_sessions=60, top_n=1), EverySession()),
    Baseline("momentum_vix", MomentumVix(top_n=1), EverySession()),
)
"""The four baselines, from the simplest to the one that reads the most."""

REFERENCE = Baseline(
    "reference_rotation", MomentumRotation(lookback_sessions=60, top_n=1), EverySession()
)
"""The README's reference run: the rotation between the two funds, every session."""

HOLD_AGAINST_REBALANCE: tuple[Baseline, ...] = (
    Baseline("buy_and_hold_both", BuyAndHold(instruments=BOTH_FUNDS), EverySession()),
    Baseline("equal_weight_daily", EqualWeightRebalance(instruments=BOTH_FUNDS), EverySession()),
)
"""The README's two baselines on both funds: keep what was bought, or restate it."""


def runner() -> StrategyRunner:
    """Return a runner over the local store, recording the state of this checkout."""
    instruments = InstrumentRegistry.from_toml(STORE / "metadata" / "instruments.toml")
    calendars = CalendarRegistry.from_directory(STORE / "metadata" / "calendars")
    return StrategyRunner(
        reader=MarketDataReader(
            repository=MarketDataRepository(STORE),
            instruments=instruments,
            calendars=calendars,
            reference_calendar_id="XPAR",
        ),
        calendars=calendars,
        reference_calendar_id="XPAR",
        base_currency="EUR",
        analytics=ANALYTICS,
        execution=EXECUTION,
        universes=UniverseRegistry.from_toml(STORE / "metadata" / "universes.toml", instruments),
        initial_cash=INITIAL_CASH,
        source=git_source_state(REPOSITORY),
        benchmark=BENCHMARK,
        lockfile=REPOSITORY / "uv.lock",
    )


def percent(value: float | None) -> str:
    """Return a fraction as a percentage, or a dash when there is none."""
    return "-" if value is None else f"{value:.2%}"


def number(value: float | None) -> str:
    """Return a ratio with two decimals, or a dash when there is none."""
    return "-" if value is None else f"{value:.2f}"


HEADER = (
    f"{'strategy':<20}{'period':<25}{'net':>9}{'gross':>9}{'a year':>9}"
    f"{'sharpe':>8}{'max dd':>9}{'costs':>10}{'rebal.':>8}{'fills':>7}{'rejects':>9}"
    f"{'est.':>6}{'vs world':>10}"
)
"""The columns of the table, laid out for a terminal.

``rebal.`` counts the sessions on which something was bought or sold and
``fills`` the orders done on them: one session can fill two orders, so neither
is "trades" (audit A17). ``rejects`` is every refused or cut order, broken down
by reason on the line below - a ``BELOW_MINIMUM_TRADE`` is the declared policy
at work, not a failure.
"""


def row(label: str, result: StrategyResult) -> str:
    """Return one line of the table for a finished run, and its rejects by reason."""
    report = result.report()
    net = report.net
    comparison = result.compare()
    line = (
        f"{label:<20}{f'{result.start} {result.end}':<25}"
        f"{percent(net.total_return):>9}{percent(report.gross.total_return):>9}"
        f"{percent(net.annualised_return):>9}{number(net.sharpe_ratio):>8}"
        f"{percent(net.drawdown.depth):>9}{report.costs.total:>10,.0f}"
        f"{report.costs.rebalancings:>8}{report.quality.fills:>7}{report.quality.rejects:>9}"
        f"{report.quality.estimated_valuations:>6}{percent(comparison.excess_return):>10}"
    )
    reasons = ", ".join(
        f"{reason} {count}" for reason, count in report.quality.rejects_by_reason.items()
    )
    return f"{line}\n{'':<20}rejects: {reasons}" if reasons else line


def write_records(result: StrategyResult, directory: Path, name: str) -> None:
    """Write one run's sessions, orders, fills, rejects and holdings to CSV.

    Every float is written with seventeen significant digits, which is enough
    for it to read back to exactly the same double: the files are for comparing
    two versions of the code bit for bit, not for reading.
    """
    directory.mkdir(parents=True, exist_ok=True)
    views = {
        "sessions": result.frame(),
        "orders": result.orders(),
        "fills": result.fills(),
        "rejects": result.rejects(),
        "holdings": result.holdings(),
    }
    for view, frame in views.items():
        frame.to_csv(directory / f"{name}_{view}.csv", float_format="%.17g")


@dataclass(frozen=True, slots=True)
class Keeping:
    """Where each finished run goes besides the terminal.

    Attributes
    ----------
    records : Path | None
        Directory for each run's CSVs, or ``None``.
    kept : Path | None
        Directory each run is kept in whole - sessions, curves, report, and a
        copy of the store it read - so it reads back and recomputes without
        the live store; or ``None``.
    registry : ExperimentRegistry | None
        The experiment register each run is appended to, or ``None``. Every
        run is registered under its label as the hypothesis, so the register
        counts every variant the suites have run.
    """

    records: Path | None = None
    registry: ExperimentRegistry | None = None
    kept: Path | None = None

    def keep(self, result: StrategyResult, name: str, hypothesis: str) -> None:
        """Write a run's records, keep it whole, and register it, as asked."""
        if self.records is not None:
            write_records(result, self.records, name)
        if self.kept is not None:
            keep(result, self.kept / name, store=MarketDataRepository(STORE))
        if self.registry is not None:
            self.registry.register(
                record_of(
                    result,
                    experiment_id=name,
                    hypothesis=hypothesis,
                    recorded_at=datetime.now(UTC),
                )
            )


def run_baselines(
    runs: StrategyRunner, periods: Sequence[tuple[str, str]], keeping: Keeping
) -> None:
    """Run every baseline over every period, and print the table."""
    print(HEADER)
    for start, end in periods:
        for baseline in BASELINES:
            result = runs.run(baseline.strategy, UNIVERSE, start, end, schedule=baseline.schedule)
            print(row(baseline.label, result), flush=True)
            keeping.keep(result, f"baselines_{baseline.label}_{start}_{end}", baseline.label)
        print()


def run_readme(runs: StrategyRunner, keeping: Keeping) -> None:
    """Run what the README prints: the reference run in full, and the two baselines."""
    start, end = README_PERIOD
    reference = runs.run(REFERENCE.strategy, UNIVERSE, start, end, schedule=REFERENCE.schedule)
    print(f"== {REFERENCE.label}  {start} {end}")
    print(reference.report().render())
    print()
    print(reference.compare().render())
    print(flush=True)
    keeping.keep(reference, f"readme_{REFERENCE.label}_{start}_{end}", REFERENCE.label)
    print(f"== buy and hold against a daily equal weight, both funds  {start} {end}")
    print(HEADER)
    for baseline in HOLD_AGAINST_REBALANCE:
        result = runs.run(baseline.strategy, UNIVERSE, start, end, schedule=baseline.schedule)
        print(row(baseline.label, result), flush=True)
        keeping.keep(result, f"readme_{baseline.label}_{start}_{end}", baseline.label)
    print()


def parse_period(text: str) -> tuple[str, str]:
    """Return a ``START:END`` period as two ISO dates, refusing anything else.

    Raises
    ------
    ValueError
        If the text is not two ISO dates separated by a colon.
    """
    start, _, end = text.partition(":")
    date.fromisoformat(start)
    date.fromisoformat(end)
    return start, end


def main() -> None:
    """Run the suites asked for, and print what they did."""
    parser = argparse.ArgumentParser(description="Run the reference experiments.")
    parser.add_argument(
        "--suite",
        choices=("baselines", "readme", "all"),
        default="baselines",
        help="which experiments to run; the baselines table by default",
    )
    parser.add_argument(
        "--period",
        action="append",
        metavar="START:END",
        help="a period for the baselines instead of the default ones; may be repeated",
    )
    parser.add_argument(
        "--records",
        type=Path,
        metavar="DIR",
        help="write every run's sessions, orders, fills, rejects and holdings there",
    )
    parser.add_argument(
        "--keep",
        type=Path,
        metavar="DIR",
        help="keep every run whole there, with a copy of the store it read",
    )
    parser.add_argument(
        "--register",
        action="store_true",
        help="append every run to research/registry.jsonl (committed code only)",
    )
    arguments = parser.parse_args()
    keeping = Keeping(
        records=arguments.records,
        registry=ExperimentRegistry(REGISTRY) if arguments.register else None,
        kept=arguments.keep,
    )
    periods = [parse_period(item) for item in arguments.period or []] or list(PERIODS)
    runs = runner()
    source = runs.source.definition()
    print(f"source    {source['source_state']} {source['git_commit']}")
    print(f"costs     {EXECUTION.costs.definition()}")
    print(f"minimum   {EXECUTION.minimum_trade_value} per order")
    print(f"cash      {INITIAL_CASH:,.0f} EUR in {UNIVERSE}, measured against {BENCHMARK}")
    print(
        f"analytics {ANALYTICS.sessions_per_year} sessions a year, "
        f"risk-free {ANALYTICS.risk_free_rate}"
    )
    print()
    if arguments.suite in ("readme", "all"):
        run_readme(runs, keeping)
    if arguments.suite in ("baselines", "all"):
        run_baselines(runs, periods, keeping)


if __name__ == "__main__":
    main()
