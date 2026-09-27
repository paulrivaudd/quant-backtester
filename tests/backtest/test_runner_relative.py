"""Alpha, beta and information ratio as a run reports them, end to end.

The demo market gives a whole year of sessions, real costs and a declared
benchmark, so every relative figure is defined and the gross and net books
differ. What is checked is the wiring: the figures come from the one
computation, over every session of the run, and asking for them changes
nothing the engine produced.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from quant_backtester.analytics.curves import Book
from quant_backtester.analytics.relative import STATISTICS, RelativePerformanceStats
from quant_backtester.backtest.runner import StrategyResult, StrategyRunner
from quant_backtester.demo import demo_runner
from quant_backtester.execution.costs import CostModel
from quant_backtester.execution.model import ExecutionModel
from quant_backtester.strategies.examples import MomentumRotation

SEED = 20240101
PERIOD = ("2025-01-02", "2025-12-31")
UNIVERSE = ("FUND_A", "FUND_B")


def rotate(runner: StrategyRunner) -> StrategyResult:
    """Run a rotation that trades, so costs separate the two books."""
    return runner.run(MomentumRotation(lookback_sessions=20, top_n=1), UNIVERSE, *PERIOD)


@pytest.fixture(scope="module")
def runner(tmp_path_factory: pytest.TempPathFactory) -> StrategyRunner:
    """Return the demo runner, FUND_A declared as the benchmark.

    Shared by the module: a run and its result are immutable, and building the
    store and walking a year once per test would double the suite's time.
    """
    return demo_runner(tmp_path_factory.mktemp("relative") / "store", seed=SEED)


@pytest.fixture(scope="module")
def result(runner: StrategyRunner) -> StrategyResult:
    """Return the rotation, measured against the declared benchmark."""
    return rotate(runner)


@pytest.fixture(scope="module")
def bare(runner: StrategyRunner) -> StrategyResult:
    """Return the same rotation with no benchmark declared."""
    return rotate(replace(runner, benchmark=None))


def test_i01_a_declared_benchmark_puts_both_books_in_the_report(result: StrategyResult) -> None:
    report = result.report()
    assert report.gross_comparison is not None and report.net_comparison is not None
    assert report.net_comparison.book is Book.NET
    assert report.gross_comparison.book is Book.GROSS
    frame = report.relative_frame()
    assert list(frame.columns) == ["gross", "net"]
    assert list(frame.index) == list(STATISTICS)
    assert frame.notna().all().all()
    text = report.render()
    assert "relative to FUND_A (TOTAL_RETURN), 2025-01-02 to 2025-12-31" in text
    assert "255 valuations, 254 returns, 255 sessions/year, risk-free 2.00%" in text


def test_i02_i11_without_a_benchmark_the_absolute_report_is_unchanged(
    result: StrategyResult, bare: StrategyResult
) -> None:
    with_benchmark = result.report()
    without = bare.report()
    assert without.gross_comparison is None and without.net_comparison is None
    assert without.relative_frame().isna().all().all()
    assert list(without.relative_frame().index) == list(STATISTICS)
    assert "relative to a benchmark: none configured" in without.render()
    pd.testing.assert_frame_equal(without.as_frame(), with_benchmark.as_frame())


def test_i03_gross_and_net_are_computed_apart_and_agree_without_costs(
    runner: StrategyRunner, result: StrategyResult
) -> None:
    costly = result.report().relative_frame()
    assert not costly["gross"].equals(costly["net"])
    free = replace(runner, execution=ExecutionModel(costs=CostModel()))
    frame = rotate(free).report().relative_frame()
    pd.testing.assert_series_equal(frame["gross"], frame["net"], check_names=False)


def test_i04_compare_and_the_report_give_the_same_figures(result: StrategyResult) -> None:
    report = result.report()
    assert report.net_comparison is not None and report.gross_comparison is not None
    assert result.compare().relative == report.net_comparison.relative
    assert result.compare(book=Book.GROSS).relative == report.gross_comparison.relative
    assert result.compare().book is Book.NET
    other = result.compare(benchmark="FUND_B")
    assert other.label == "FUND_B" and other.relative is not None
    assert other.relative != report.net_comparison.relative


def test_i05_an_exploratory_report_leaves_the_kept_one_alone(result: StrategyResult) -> None:
    run_id, kept = result.run_id, result.report()
    explored = result.report(benchmark="FUND_B")
    assert explored is not kept
    assert explored.net_comparison is not None and explored.net_comparison.label == "FUND_B"
    assert result.report() is kept
    assert kept.net_comparison is not None and kept.net_comparison.label == "FUND_A"
    assert result.run_id == run_id
    assert result.configuration["benchmark"]["instrument_id"] == "FUND_A"  # type: ignore[index]


def test_i08_the_relative_figures_use_the_benchmark_curve_itself(result: StrategyResult) -> None:
    direct = RelativePerformanceStats.from_equity(
        result.equity(Book.NET), result.benchmark().equity, result.analytics_config
    )
    assert result.compare().relative == direct


def test_i10_the_report_prints_percentages_numbers_and_no_nan(result: StrategyResult) -> None:
    text = result.report().render()
    lines = {line.split("  ")[0]: line for line in text.splitlines()}
    assert lines["regression alpha, a year"].rstrip().endswith("%")
    assert lines["tracking error, a year"].rstrip().endswith("%")
    assert "%" not in lines["beta"] and "%" not in lines["information ratio"]
    assert "alpha per session" not in text
    assert not re.search(r"\b(nan|inf)\b", text)


def test_i12_the_definition_of_a_run_s_figures_is_strict_json(result: StrategyResult) -> None:
    relative = result.compare().relative
    assert relative is not None
    record = json.loads(json.dumps(relative.definition(), allow_nan=False))
    assert record["sessions"] == 255 and record["observations"] == 254


def test_i13_asking_for_relative_figures_changes_nothing_the_engine_did(
    result: StrategyResult, bare: StrategyResult
) -> None:
    pd.testing.assert_frame_equal(result.frame(), bare.frame())
    pd.testing.assert_frame_equal(result.fills(), bare.fills())
    pd.testing.assert_series_equal(result.equity(), bare.equity())


def test_i12_the_export_carries_the_figures_and_what_they_are_read_with(
    result: StrategyResult, tmp_path: Path
) -> None:
    frame = result.relative_records()
    assert list(frame["statistic"]) == list(STATISTICS)
    net = result.compare().relative
    assert net is not None
    assert list(frame["net"]) == [getattr(net, name) for name in STATISTICS]
    first = frame.iloc[0]
    assert first["run_id"] == result.run_id and first["base_currency"] == "EUR"
    assert (first["benchmark_id"], first["benchmark_basis"]) == ("FUND_A", "TOTAL_RETURN")
    assert (first["sessions"], first["observations"]) == (255, 254)
    assert json.loads(first["net_diagnostics"]) == []
    path = tmp_path / "relative.csv"
    frame.to_csv(path, index=False, float_format="%.17g")
    back = pd.read_csv(path, float_precision="round_trip")
    assert list(back["net"]) == list(frame["net"])


def test_i14_without_a_benchmark_the_export_says_why_and_still_writes(
    bare: StrategyResult,
) -> None:
    frame = bare.relative_records()
    assert bool(frame["gross"].isna().all()) and bool(frame["net"].isna().all())
    assert json.loads(frame.iloc[0]["net_diagnostics"]) == ["benchmark_not_configured"]
    assert frame.iloc[0]["benchmark_id"] is None
