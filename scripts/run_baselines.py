"""Run the reference baselines over several periods, and print what each of them did.

Run it from the repository root, once the local store is filled::

    uv run python scripts/run_baselines.py
    uv run python scripts/run_baselines.py --period 2024-01-02:2026-09-17

Four strategies, each testing one more piece of the chain than the last:

- ``buy_and_hold`` buys the world fund once and never rebalances - execution,
  costs, whole shares and the cash they leave;
- ``equal_weight`` restates half and half at the end of every month - turnover,
  several orders, the sale that pays for the purchase;
- ``momentum_rotation`` holds the fund with the better sixty-session momentum -
  signals, the strategy, the portfolio and execution together;
- ``momentum_vix`` does the same, and stands aside while the VIX is more than
  one and a half standard deviations above its sixty-observation mean - a gauge
  that is read and never held.

Every run records what it was made with - the configuration, the fingerprint
of the strategy and the state of this checkout - so a line of the table can be
traced back to the code and the settings that produced it. The costs are the
same for all four and declared below, where they can be argued with.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
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

UNIVERSE = "ROTATION_2"
"""The two PEA funds every baseline chooses among."""

BENCHMARK = "ETF_WORLD"
"""What every run is measured against: simply holding the world fund."""

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
"""The annualisation every figure of the table is computed under."""

PERIODS: tuple[tuple[str, str], ...] = (
    ("2018-07-16", "2026-09-17"),
    ("2019-01-02", "2021-12-31"),
    ("2022-01-03", "2023-12-29"),
    ("2024-01-02", "2026-09-17"),
)
"""The whole history both funds share once a sixty-session window exists, and
three regimes inside it: a long rise with a crash in it, a fall and its
recovery, and the recent run."""


@dataclass(frozen=True, slots=True)
class Baseline:
    """One strategy, and the calendar it is asked on."""

    label: str
    strategy: Strategy
    schedule: DecisionSchedule


BASELINES: tuple[Baseline, ...] = (
    Baseline("buy_and_hold", BuyAndHold(instruments=("ETF_WORLD",)), EverySession()),
    Baseline(
        "equal_weight",
        EqualWeightRebalance(instruments=("ETF_SP500_PEA", "ETF_WORLD")),
        Monthly(),
    ),
    Baseline("momentum_rotation", MomentumRotation(lookback_sessions=60, top_n=1), EverySession()),
    Baseline("momentum_vix", MomentumVix(top_n=1), EverySession()),
)
"""The four baselines, from the simplest to the one that reads the most."""


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
        initial_cash=100_000.0,
        source=git_source_state(REPOSITORY),
        benchmark=BENCHMARK,
    )


def percent(value: float | None) -> str:
    """Return a fraction as a percentage, or a dash when there is none."""
    return "-" if value is None else f"{value:.2%}"


def number(value: float | None) -> str:
    """Return a ratio with two decimals, or a dash when there is none."""
    return "-" if value is None else f"{value:.2f}"


HEADER = (
    f"{'strategy':<20}{'period':<25}{'net':>9}{'gross':>9}{'a year':>9}"
    f"{'sharpe':>8}{'max dd':>9}{'costs':>10}{'trades':>8}{'rejects':>9}"
    f"{'est.':>6}{'vs world':>10}"
)
"""The columns of the table, laid out for a terminal."""


def row(label: str, result: StrategyResult) -> str:
    """Return one line of the table for a finished run."""
    report = result.report()
    net = report.net
    comparison = result.compare()
    return (
        f"{label:<20}{f'{result.start} {result.end}':<25}"
        f"{percent(net.total_return):>9}{percent(report.gross.total_return):>9}"
        f"{percent(net.annualised_return):>9}{number(net.sharpe_ratio):>8}"
        f"{percent(net.drawdown.depth):>9}{report.costs.total:>10,.0f}"
        f"{report.costs.rebalancings:>8}{report.quality.rejects:>9}"
        f"{report.quality.estimated_valuations:>6}{percent(comparison.excess_return):>10}"
    )


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
    """Run every baseline over every period, and print the table."""
    parser = argparse.ArgumentParser(description="Run the baselines over several periods.")
    parser.add_argument(
        "--period",
        action="append",
        metavar="START:END",
        help="a period to run over instead of the default ones; may be repeated",
    )
    arguments = parser.parse_args()
    periods = [parse_period(item) for item in arguments.period or []] or list(PERIODS)
    runs = runner()
    source = runs.source.definition()
    print(f"source {source['source_state']} {source['git_commit']}")
    print(f"costs  {EXECUTION.costs.definition()}")
    print(f"minimum trade value {EXECUTION.minimum_trade_value}")
    print()
    print(HEADER)
    for start, end in periods:
        for baseline in BASELINES:
            result = runs.run(baseline.strategy, UNIVERSE, start, end, schedule=baseline.schedule)
            print(row(baseline.label, result), flush=True)
        print()


if __name__ == "__main__":
    main()
