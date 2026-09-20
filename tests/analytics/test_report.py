"""The two books side by side, and one real run to check the layers meet.

Everything above this file works on curves written by hand. This one runs the
engine over the synthetic market, so that a change to what a record holds shows
up here rather than in a notebook six months later.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, time

import pytest

from quant_backtester.analytics.config import AnalyticsConfig
from quant_backtester.analytics.report import PerformanceReport
from quant_backtester.backtest.context import StrategyContext
from quant_backtester.backtest.engine import (
    BacktestEngine,
    BacktestResult,
    Strategy,
    Timetable,
)
from quant_backtester.data.calendars import CalendarRegistry
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.execution.costs import CostModel
from quant_backtester.execution.fills import ExecutionModel
from quant_backtester.portfolio.limits import PositionLimits
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.signals.price.returns import ReturnSignal
from quant_backtester.signals.types import PriceBasis

RunBuilder = Callable[..., BacktestResult]

CONFIG = AnalyticsConfig(sessions_per_year=255, risk_free_rate=0.0, minimum_sessions=3)

PARIS = Timetable(decision_time=time(23, 0), execution_time=time(9, 1), timezone="Europe/Paris")


@dataclass(frozen=True, slots=True)
class AlwaysHold(Strategy):
    """A strategy that always wants the same book, so the run is about the costs."""

    weights: Mapping[str, float]

    def decide(self, ctx: StrategyContext) -> TargetAllocation:
        """Return the fixed target, stamped at the decision instant."""
        return TargetAllocation(
            as_of=ctx.as_of,
            weights=dict(self.weights),
            selected=tuple(self.weights),
            considered=len(self.weights),
            skipped={},
        )


def report_of(result: BacktestResult) -> PerformanceReport:
    """Return the report of a run, under the test convention."""
    return PerformanceReport.of(result, CONFIG)


def test_every_statistic_is_given_twice(run: RunBuilder) -> None:
    """Gross and net, in two columns, because either alone is half an answer."""
    frame = report_of(run([100.0, 112.0], gross=[100.0, 117.0])).as_frame()

    assert list(frame.columns) == ["gross", "net"]
    assert frame.loc["total_return", "gross"] == pytest.approx(0.17)
    assert frame.loc["total_return", "net"] == pytest.approx(0.12)


def test_a_figure_the_run_cannot_support_is_not_invented(run: RunBuilder) -> None:
    """A run of two sessions has no volatility, and the frame says so."""
    frame = report_of(run([100.0, 112.0])).as_frame()

    assert math.isnan(float(frame.loc["annualised_volatility", "net"]))
    assert math.isnan(float(frame.loc["sharpe_ratio", "net"]))


def test_the_rendered_report_prints_a_dash_where_there_is_nothing(run: RunBuilder) -> None:
    """Not a zero, and not ``nan``: both of those read as measurements."""
    rendered = report_of(run([100.0, 112.0])).render()

    assert "annualised volatility" in rendered
    assert "-" in rendered
    assert "nan" not in rendered


def test_the_rendered_report_holds_the_four_blocks(run: RunBuilder) -> None:
    """Performance, costs, instruments, caveats: what a result is, and how to read it."""
    result = run(
        [100.0, 99.0, 112.0],
        gross=[100.0, 100.0, 117.0],
        commission=[0.0, 1.0, 0.0],
        market_cost=[0.0, 0.5, 0.0],
        traded_value=[0.0, 100.0, 0.0],
        priced_from_earlier=[(), (), ("ETF_EU",)],
    )

    rendered = report_of(result).render()

    assert "total return" in rendered
    assert "commission" in rendered
    assert "spread and slippage" in rendered
    assert "by instrument" in rendered
    assert "sessions valued on an older close" in rendered


def test_the_report_carries_the_conventions_it_was_built_with(run: RunBuilder) -> None:
    """A figure nobody can reproduce the convention of is not a result."""
    report = report_of(run([100.0, 101.0]))

    assert report.config is CONFIG
    assert "255 sessions/year" in report.render()


# --- one real run ------------------------------------------------------------


def engine_over(
    market: MarketDataReader,
    calendars: CalendarRegistry,
    execution: ExecutionModel,
    universe: Sequence[str] = ("ETF_EU",),
) -> BacktestEngine:
    """Wire an engine holding one instrument over the synthetic market."""
    return BacktestEngine(
        reader=market,
        calendars=calendars,
        reference_calendar_id="XPAR",
        signals=[
            ReturnSignal(signal_id="return_2d", lookback_sessions=2, price_basis=PriceBasis.RAW)
        ],
        strategy=AlwaysHold({instrument: 1.0 / len(universe) for instrument in universe}),
        universe=universe,
        initial_cash=10_000.0,
        base_currency="EUR",
        limits=PositionLimits(),
        execution=execution,
        timetable=PARIS,
    )


def test_a_real_run_reports_what_execution_took(
    market: MarketDataReader, calendars: CalendarRegistry, sessions: tuple[date, ...]
) -> None:
    """The layers meet: the engine's two books become two columns and a bill.

    The strategy buys once and holds, and the minimum trade value keeps it from
    chasing the few units of cash the costs leave behind - so the whole bill is
    the entry, and the report's drag is exactly the distance between the two
    books the engine kept.

    The entry is also cut to what the cash can carry: a target of the whole
    book costs a thousandth more than the book is worth, so the position ends a
    thousandth smaller and the run never borrows.
    """
    costly = ExecutionModel(
        costs=CostModel(commission_rate=0.001, half_spread=0.002), minimum_trade_value=100.0
    )
    result = engine_over(market, calendars, costly).run(sessions[-5], sessions[-1])

    report = PerformanceReport.of(result, CONFIG)

    assert report.costs.rebalancings == 1
    # The ten thousand pays for the stock and the fee together: a thousandth of
    # what is left after the fee is 9.99, not the 10.02 a full-size order would
    # have cost with money the book did not have.
    assert report.costs.commission == pytest.approx(10_000.0 / 1.001 * 0.001)
    assert report.costs.market_cost == pytest.approx(20.0, rel=1e-2)
    assert report.quality.unfunded_sessions == 1
    assert report.quality.sessions_on_borrowed_cash == 0
    assert report.costs.market_cost > 0.0
    assert report.net.total_return < report.gross.total_return
    assert report.costs.drag == pytest.approx(report.gross.total_return - report.net.total_return)


def test_a_free_run_has_no_drag_and_two_identical_columns(
    market: MarketDataReader, calendars: CalendarRegistry, sessions: tuple[date, ...]
) -> None:
    """With no cost model the two books are the same book, and the report says so."""
    result = engine_over(market, calendars, ExecutionModel()).run(sessions[-5], sessions[-1])

    report = PerformanceReport.of(result, CONFIG)
    frame = report.as_frame()

    assert report.costs.total == pytest.approx(0.0)
    assert report.costs.drag == pytest.approx(0.0)
    assert frame.loc["total_return", "gross"] == pytest.approx(frame.loc["total_return", "net"])


def test_the_same_run_reports_the_same_numbers_twice(
    market: MarketDataReader, calendars: CalendarRegistry, sessions: tuple[date, ...]
) -> None:
    """A report is a function of a finished run, and reproducible like one."""
    costly = ExecutionModel(costs=CostModel(commission_rate=0.001, half_spread=0.002))
    result = engine_over(market, calendars, costly).run(sessions[-5], sessions[-1])

    first = PerformanceReport.of(result, CONFIG)
    second = PerformanceReport.of(result, CONFIG)

    assert first == second
    assert first.render() == second.render()


def test_a_report_of_a_run_that_did_nothing_reads_as_nothing(run: RunBuilder) -> None:
    """Every figure absent, no cost, no caveat - and no exception."""
    report = report_of(run([]))

    rendered = report.render()

    assert report.costs.total == 0.0
    assert report.quality.sessions == 0
    assert "0 sessions" in rendered


def test_the_attribution_of_a_real_run_adds_up_to_the_run(
    market: MarketDataReader, calendars: CalendarRegistry, sessions: tuple[date, ...]
) -> None:
    """The two layers meeting: every instrument's share, against the equity itself.

    The engine values the book at closes it recorded, and the attribution reads
    those same closes rather than the store. If the two ever disagreed - a
    price re-read, a fill left out of a record - this residual is where it
    would show, which is why it is computed rather than assumed.
    """
    costly = ExecutionModel(
        costs=CostModel(commission_rate=0.001, half_spread=0.002), minimum_trade_value=100.0
    )
    result = engine_over(market, calendars, costly).run(sessions[-5], sessions[-1])

    report = PerformanceReport.of(result, CONFIG)

    moved = result.records[-1].equity - result.records[0].equity
    assert report.instruments.unexplained == pytest.approx(0.0, abs=1e-9)
    assert report.instruments.total_pnl == pytest.approx(moved)
    assert report.instruments.get("ETF_EU").sessions_held > 0
    # What the run paid, seen from the other side: the costs of one book and
    # the costs charged to its instruments are the same money.
    assert report.instruments.total_cost == pytest.approx(report.costs.total)
