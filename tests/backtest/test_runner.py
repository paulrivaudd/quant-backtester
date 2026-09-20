"""The façade a user runs a strategy through, and what it records.

Three things are worth testing here and nothing else is: the bounds of a run
are read as sessions, the data before the start stays visible to the signals,
and the configuration the numbers depend on is carried in the result rather
than remembered by whoever ran it.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, time

import pandas as pd
import pytest

from quant_backtester.analytics.config import AnalyticsConfig
from quant_backtester.analytics.curves import Book
from quant_backtester.backtest.engine import Timetable
from quant_backtester.backtest.runner import StrategyRunner
from quant_backtester.backtest.schedule import EveryNSessions
from quant_backtester.data.calendars import CalendarRegistry, TradingCalendar
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.data.universes import Membership, StaticUniverse, Universe
from quant_backtester.execution.costs import CostModel
from quant_backtester.execution.fills import ExecutionModel
from quant_backtester.strategies.examples import BuyAndHold, MomentumSingleAsset

PARIS = Timetable(decision_time=time(23, 0), execution_time=time(9, 1), timezone="Europe/Paris")
CONFIG = AnalyticsConfig(sessions_per_year=255, risk_free_rate=0.0)


@pytest.fixture
def runner(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    calendars: CalendarRegistry,
    xpar: TradingCalendar,
    prices: Callable[..., dict[date, float]],
) -> StrategyRunner:
    """Return a runner over the rising synthetic fund."""
    market = make_market(
        {
            "ETF_EU": make_bars("ETF_EU", xpar, prices(100.0, 1.0)),
            "ETF_OTHER": make_bars("ETF_OTHER", xpar, prices(200.0, 3.0)),
        }
    )
    return StrategyRunner(
        reader=market,
        calendars=calendars,
        reference_calendar_id="XPAR",
        base_currency="EUR",
        analytics=CONFIG,
        initial_cash=10_000.0,
        execution=ExecutionModel(costs=CostModel(commission_rate=0.001)),
        timetable=PARIS,
    )


def test_a_run_needs_four_arguments(runner: StrategyRunner) -> None:
    """A strategy, what it may hold, and the period to measure it over."""
    result = runner.run(BuyAndHold(instruments=("ETF_EU",)), ["ETF_EU"], "2026-09-09", "2026-09-14")

    assert result.strategy_id == "buy_and_hold"
    assert result.start == date(2026, 9, 9)
    assert result.end == date(2026, 9, 14)


def test_a_bound_that_is_not_a_session_moves_inwards(runner: StrategyRunner) -> None:
    """A Saturday is not a session, and a run that started on one would be a lie."""
    result = runner.run(BuyAndHold(instruments=("ETF_EU",)), ["ETF_EU"], "2026-09-05", "2026-09-13")

    assert result.start == date(2026, 9, 7)
    assert result.end == date(2026, 9, 11)


def test_a_period_holding_no_session_is_refused(runner: StrategyRunner) -> None:
    """A weekend is not a short run, it is no run at all."""
    with pytest.raises(ValueError, match="no session"):
        runner.run(BuyAndHold(instruments=("ETF_EU",)), ["ETF_EU"], "2026-09-05", "2026-09-06")


def test_an_inverted_period_is_refused(runner: StrategyRunner) -> None:
    """A caller bug, not an empty range."""
    with pytest.raises(ValueError, match="after end"):
        runner.run(BuyAndHold(instruments=("ETF_EU",)), ["ETF_EU"], "2026-09-11", "2026-09-09")


def test_a_bound_that_is_not_a_date_is_refused(runner: StrategyRunner) -> None:
    """An ISO string or a date; anything else is a typo with a plausible shape."""
    with pytest.raises(ValueError, match="ISO date"):
        runner.run(BuyAndHold(instruments=("ETF_EU",)), ["ETF_EU"], "last january", "2026-09-14")


def test_dates_are_accepted_as_well_as_strings(runner: StrategyRunner) -> None:
    """The string form is for notebooks; the date form is for code."""
    result = runner.run(
        BuyAndHold(instruments=("ETF_EU",)), ["ETF_EU"], date(2026, 9, 9), date(2026, 9, 14)
    )

    assert result.start == date(2026, 9, 9)


def test_the_signals_see_the_data_before_the_start(runner: StrategyRunner) -> None:
    """``start`` is where the performance starts, not where the data does.

    A five-session momentum run from the 10th reads the first week of
    September. Without that, every strategy would begin with a fortnight of
    artificial cash while its windows filled up.
    """
    strategy = MomentumSingleAsset(instrument_id="ETF_EU", lookback_sessions=5)

    result = runner.run(strategy, ["ETF_EU"], "2026-09-10", "2026-09-14")

    # Invested from the first decision: the window was already there.
    assert result.backtest.records[0].target_invested == pytest.approx(1.0)


def test_a_universe_named_by_id_needs_a_registry(runner: StrategyRunner) -> None:
    """Naming one with nowhere to look it up is a wiring mistake."""
    with pytest.raises(ValueError, match="no universe registry"):
        runner.run(BuyAndHold(instruments=("ETF_EU",)), "ROTATION_2", "2026-09-09", "2026-09-14")


def test_a_dated_universe_is_asked_by_session(runner: StrategyRunner) -> None:
    """The runner passes it through; the engine asks it one session at a time."""
    universe = Universe(
        universe_id="LEAVER",
        name="One fund leaves",
        memberships=(
            Membership("ETF_EU"),
            Membership("ETF_OTHER", until_date=date(2026, 9, 10)),
        ),
    )

    result = runner.run(BuyAndHold(instruments=("ETF_EU",)), universe, "2026-09-09", "2026-09-14")

    assert result.configuration["universe"] == "LEAVER"


def test_a_static_universe_records_no_id(runner: StrategyRunner) -> None:
    """A list of names is honest only for instruments that existed throughout."""
    result = runner.run(
        BuyAndHold(instruments=("ETF_EU",)),
        StaticUniverse(("ETF_EU",)),
        "2026-09-09",
        "2026-09-14",
    )

    assert result.configuration["universe"] is None


def test_the_result_records_what_the_numbers_depend_on(runner: StrategyRunner) -> None:
    """A Sharpe ratio without its period, costs and calendar is not a result."""
    result = runner.run(BuyAndHold(instruments=("ETF_EU",)), ["ETF_EU"], "2026-09-09", "2026-09-14")

    configuration = result.configuration
    assert configuration["reference_calendar"] == "XPAR"
    assert configuration["base_currency"] == "EUR"
    assert configuration["initial_cash"] == pytest.approx(10_000.0)
    assert configuration["schedule"] == "EverySession"
    assert configuration["costs"]["commission_rate"] == pytest.approx(0.001)  # type: ignore[index]
    assert configuration["timetable"]["decision_time"] == "23:00:00"  # type: ignore[index]
    assert configuration["analytics"]["sessions_per_year"] == 255  # type: ignore[index]


def test_the_result_records_the_strategy_itself(runner: StrategyRunner) -> None:
    """Two experiments are told apart by their fingerprints, not by their names."""
    result = runner.run(BuyAndHold(instruments=("ETF_EU",)), ["ETF_EU"], "2026-09-09", "2026-09-14")
    other = runner.run(
        BuyAndHold(instruments=("ETF_OTHER",)), ["ETF_OTHER"], "2026-09-09", "2026-09-14"
    )

    assert result.definition["parameters"]["instruments"] == ["ETF_EU"]  # type: ignore[index]
    assert result.fingerprint != other.fingerprint


def test_the_schedule_of_a_run_can_be_chosen_per_run(runner: StrategyRunner) -> None:
    """The same rule at two frequencies is two experiments, not two strategies."""
    result = runner.run(
        BuyAndHold(instruments=("ETF_EU",)),
        ["ETF_EU"],
        "2026-09-01",
        "2026-09-14",
        schedule=EveryNSessions(5),
    )

    assert result.configuration["schedule"] == "EveryNSessions"
    assert sum(1 for record in result.backtest.records if record.decided) == 2


def test_the_result_hands_back_the_report_and_the_curves(runner: StrategyRunner) -> None:
    """What a notebook asks of it, without reaching into the run."""
    result = runner.run(BuyAndHold(instruments=("ETF_EU",)), ["ETF_EU"], "2026-09-09", "2026-09-14")

    assert result.report() is result.analytics
    assert len(result.equity()) == len(result.backtest.records)
    assert len(result.equity(Book.GROSS)) == len(result.backtest.records)
    assert (result.drawdown() <= 0.0).all()
    assert list(result.frame().index) == [record.session_date for record in result.backtest.records]


def test_a_strategy_with_two_signals_of_one_id_never_runs(runner: StrategyRunner) -> None:
    """Checked before anything is computed, since one would hide the other."""
    from quant_backtester.signals.price.returns import ReturnSignal
    from quant_backtester.signals.types import PriceBasis
    from quant_backtester.strategies.functional import FunctionalStrategy

    signal = ReturnSignal(signal_id="r", lookback_sessions=2, price_basis=PriceBasis.RAW)

    with pytest.raises(ValueError, match="twice"):
        FunctionalStrategy(
            strategy_id="twice",
            decision=lambda ctx: ctx.cash(),
            signals=(signal, signal),
        )


def test_an_instant_the_calendar_does_not_cover_is_loud(
    runner: StrategyRunner,
) -> None:
    """Inventing sessions past the end of a holiday list is how a backtest trades on Christmas."""
    from quant_backtester.data.calendars import CalendarCoverageError

    with pytest.raises(CalendarCoverageError):
        runner.run(BuyAndHold(instruments=("ETF_EU",)), ["ETF_EU"], "2027-01-04", "2027-01-08")


def test_a_run_of_a_naive_datetime_bound_is_refused(runner: StrategyRunner) -> None:
    """A date, or a string that is one."""
    with pytest.raises(ValueError, match="must be a date"):
        runner.run(BuyAndHold(instruments=("ETF_EU",)), ["ETF_EU"], 20260909, "2026-09-14")  # type: ignore[arg-type]


def test_the_runner_produces_what_the_engine_produces(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    calendars: CalendarRegistry,
    xpar: TradingCalendar,
    prices: Callable[..., dict[date, float]],
    runner: StrategyRunner,
) -> None:
    """The façade is a façade: same strategy, same period, same numbers.

    If it ever stopped being one - a default applied here and not there, a
    session included on one side only - every result taken through it would be
    quietly incomparable with the low-level ones the tests of the engine use.
    """
    from quant_backtester.backtest.engine import BacktestEngine

    strategy = MomentumSingleAsset(instrument_id="ETF_EU", lookback_sessions=5)
    engine = BacktestEngine(
        reader=runner.reader,
        calendars=calendars,
        reference_calendar_id="XPAR",
        signals=(),
        strategy=strategy,
        universe=("ETF_EU",),
        initial_cash=10_000.0,
        base_currency="EUR",
        execution=runner.execution,
        timetable=PARIS,
    )

    directly = engine.run(date(2026, 9, 9), date(2026, 9, 14))
    through = runner.run(strategy, ["ETF_EU"], "2026-09-09", "2026-09-14")

    assert [record.equity for record in through.backtest.records] == [
        record.equity for record in directly.records
    ]
