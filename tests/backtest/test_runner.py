"""The façade a user runs a strategy through, and what it records.

Three things are worth testing here and nothing else is: the bounds of a run
are read as sessions, the data before the start stays visible to the signals,
and the configuration the numbers depend on is carried in the result rather
than remembered by whoever ran it.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, time
from pathlib import Path

import pandas as pd
import pytest

from quant_backtester.analytics.config import AnalyticsConfig
from quant_backtester.analytics.curves import Book
from quant_backtester.backtest.context import StrategyContext
from quant_backtester.backtest.runner import StoreChanged, StrategyRunner
from quant_backtester.backtest.schedule import EveryNSessions
from quant_backtester.backtest.timetable import BacktestTimetable
from quant_backtester.data.calendars import CalendarRegistry, TradingCalendar
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.data.repository import MarketDataRepository, StoreBusy
from quant_backtester.data.universes import Membership, StaticUniverse, Universe
from quant_backtester.execution.costs import CostModel
from quant_backtester.execution.model import ExecutionModel
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.provenance import SourceState, SourceStatus
from quant_backtester.strategies.examples import BuyAndHold, MomentumSingleAsset
from quant_backtester.strategies.functional import FunctionalStrategy

PARIS = BacktestTimetable(
    decision_time=time(23, 0), execution_time=time(9, 1), valuation_time=time(23, 0)
)
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

    recorded = result.configuration["universe"]
    assert recorded["type"] == "Universe"  # type: ignore[index]
    assert recorded["id"] == "LEAVER"  # type: ignore[index]
    # The memberships, not the names of today: a dated universe answers a
    # different list on every session, so only the windows identify it.
    assert recorded["memberships"][1]["until"] == "2026-09-10"  # type: ignore[index]


def test_a_static_universe_records_its_members(runner: StrategyRunner) -> None:
    """A list of names has no id, and its members are what identifies it.

    Recording ``None`` made two runs over two completely different books look
    like the same experiment - which is exactly what the configuration exists
    to prevent.
    """
    result = runner.run(
        BuyAndHold(instruments=("ETF_EU",)),
        StaticUniverse(("ETF_EU",)),
        "2026-09-09",
        "2026-09-14",
    )

    recorded = result.configuration["universe"]
    assert recorded["type"] == "StaticUniverse"  # type: ignore[index]
    assert list(recorded["members"]) == ["ETF_EU"]  # type: ignore[index]


def test_two_static_universes_are_not_one_experiment(runner: StrategyRunner) -> None:
    """The point of recording the members rather than their absence."""
    first = runner.run(BuyAndHold(instruments=("ETF_EU",)), ["ETF_EU"], "2026-09-09", "2026-09-14")
    second = runner.run(
        BuyAndHold(instruments=("ETF_OTHER",)), ["ETF_OTHER"], "2026-09-09", "2026-09-14"
    )

    assert first.configuration["universe"] != second.configuration["universe"]


def test_the_result_records_what_the_numbers_depend_on(runner: StrategyRunner) -> None:
    """A Sharpe ratio without its period, costs and calendar is not a result."""
    result = runner.run(BuyAndHold(instruments=("ETF_EU",)), ["ETF_EU"], "2026-09-09", "2026-09-14")

    configuration = result.configuration
    assert configuration["reference_calendar"] == "XPAR"
    assert configuration["base_currency"] == "EUR"
    assert configuration["initial_cash"] == pytest.approx(10_000.0)
    assert configuration["schedule"] == {"type": "EverySession", "parameters": {}}
    costs = configuration["execution"]["costs"]  # type: ignore[index]
    assert costs["commission_rate"] == pytest.approx(0.001)  # type: ignore[index]
    assert configuration["timetable"]["decision_time"] == "23:00:00"  # type: ignore[index]
    assert configuration["timetable"]["execution"] == {  # type: ignore[index]
        "field": "open",
        "session_offset": 1,
    }
    assert configuration["analytics"] == {
        "sessions_per_year": 255,
        "risk_free_rate": runner.analytics.risk_free_rate,
        "minimum_sessions": runner.analytics.minimum_sessions,
    }
    assert configuration["portfolio"]["limits"]["long_only"] is True  # type: ignore[index]
    assert configuration["quantity_steps"] == {"ETF_EU": None}
    assert configuration["requested_start"] == "2026-09-09"
    assert configuration["benchmark"] is None


def test_the_result_records_the_strategy_itself(runner: StrategyRunner) -> None:
    """Two experiments are told apart by their fingerprints, not by their names."""
    result = runner.run(BuyAndHold(instruments=("ETF_EU",)), ["ETF_EU"], "2026-09-09", "2026-09-14")
    other = runner.run(
        BuyAndHold(instruments=("ETF_OTHER",)), ["ETF_OTHER"], "2026-09-09", "2026-09-14"
    )

    assert result.definition["parameters"]["instruments"] == ("ETF_EU",)  # type: ignore[index]
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

    assert result.configuration["schedule"] == {
        "type": "EveryNSessions",
        "parameters": {"n": 5},
    }
    assert sum(1 for record in result.backtest.records if record.decided) == 2


def test_two_frequencies_are_two_experiments(runner: StrategyRunner) -> None:
    """Rebalancing every five sessions and every twenty are not the same strategy."""
    strategy = BuyAndHold(instruments=("ETF_EU",))
    often = runner.run(strategy, ["ETF_EU"], "2026-09-01", "2026-09-14", schedule=EveryNSessions(2))
    rarely = runner.run(
        strategy, ["ETF_EU"], "2026-09-01", "2026-09-14", schedule=EveryNSessions(5)
    )

    assert often.configuration["schedule"] != rarely.configuration["schedule"]


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
    from quant_backtester.backtest.config import BacktestConfig
    from quant_backtester.backtest.engine import BacktestEngine
    from quant_backtester.backtest.schedule import EverySession

    strategy = MomentumSingleAsset(instrument_id="ETF_EU", lookback_sessions=5)
    engine = BacktestEngine(
        reader=runner.reader,
        calendars=calendars,
        strategy=strategy,
        universe=("ETF_EU",),
        config=BacktestConfig(
            start=date(2026, 9, 9),
            end=date(2026, 9, 14),
            initial_cash=10_000.0,
            base_currency="EUR",
            reference_calendar="XPAR",
            schedule=EverySession(),
            timetable=PARIS,
        ),
        execution=runner.execution,
    )

    directly = engine.run()
    through = runner.run(strategy, ["ETF_EU"], "2026-09-09", "2026-09-14")

    assert through.backtest.records == directly.records


def test_a_strategy_that_changes_while_it_decides_is_refused(
    runner: StrategyRunner,
) -> None:
    """The definition recorded has to be the one that produced the numbers.

    A strategy holds no state between decisions - everything path-dependent
    comes from the context. One that kept a counter would be filed under a
    definition describing its last decision rather than all of them, and the
    result could not be reproduced from itself.
    """
    from quant_backtester.backtest.runner import StrategyMutated
    from quant_backtester.strategies.base import Strategy

    class Drifting(Strategy):
        strategy_id = "drifting"

        def __init__(self) -> None:
            self.lookback = 1

        def parameters(self) -> dict[str, object]:
            return {"lookback": self.lookback}

        def decide(self, ctx: StrategyContext) -> TargetAllocation:
            self.lookback += 1
            return ctx.cash()

    with pytest.raises(StrategyMutated, match="not the one it was"):
        runner.run(Drifting(), ["ETF_EU"], "2026-09-09", "2026-09-14")


def test_the_signals_of_a_run_are_asked_for_once(runner: StrategyRunner) -> None:
    """The declaration that ran is the declaration the result records."""
    from quant_backtester.strategies.base import Strategy

    asked: list[int] = []

    class Counting(Strategy):
        strategy_id = "counting"

        def required_signals(self) -> tuple[()]:
            asked.append(1)
            return ()

        def decide(self, ctx: StrategyContext) -> TargetAllocation:
            return ctx.cash()

    result = runner.run(Counting(), ["ETF_EU"], "2026-09-01", "2026-09-14")

    # Once for the run itself; the rest are the definition and the fingerprint,
    # which are taken twice - before and after - to catch a strategy that moved.
    decisions = len(result.backtest.records)
    assert len(asked) < decisions


def test_the_record_of_a_run_cannot_be_edited_afterwards(
    runner: StrategyRunner,
) -> None:
    """A record of an experiment that can be rewritten is a record of nothing."""
    result = runner.run(BuyAndHold(instruments=("ETF_EU",)), ["ETF_EU"], "2026-09-09", "2026-09-14")

    with pytest.raises(TypeError):
        result.configuration["initial_cash"] = 1.0  # type: ignore[index]
    with pytest.raises(TypeError):
        result.configuration["execution"]["costs"]["commission_rate"] = 0.0  # type: ignore[index]
    with pytest.raises(TypeError):
        result.definition["parameters"]["instruments"] = ()  # type: ignore[index]


def test_the_code_that_produced_a_result_is_recorded_when_it_is_given(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    calendars: CalendarRegistry,
    xpar: TradingCalendar,
    prices: Callable[..., dict[date, float]],
) -> None:
    """A fingerprint hashes a configuration, never the source that read it.

    Editing a ``decide`` in place leaves the fingerprint alone, so only this
    field can say that two runs were not the same code. It is given rather than
    guessed at: a library shelling out to git answers wrongly from a notebook
    outside the repository, and a wrong provenance is worse than none.
    """
    commit = "9b15c93" + "0" * 33
    market = make_market({"ETF_EU": make_bars("ETF_EU", xpar, prices(100.0, 1.0))})
    runner = StrategyRunner(
        reader=market,
        calendars=calendars,
        reference_calendar_id="XPAR",
        base_currency="EUR",
        analytics=CONFIG,
        execution=ExecutionModel(costs=CostModel()),
        initial_cash=10_000.0,
        timetable=PARIS,
        source=SourceState(SourceStatus.DIRTY, commit),
    )

    result = runner.run(BuyAndHold(instruments=("ETF_EU",)), ["ETF_EU"], "2026-09-09", "2026-09-14")

    assert result.configuration["source"] == {
        "git_commit": commit,
        "dirty": True,
        "source_state": "DIRTY",
    }
    assert result.source.git_commit == commit
    assert result.backtest.code_version == commit


def test_a_run_that_recorded_no_code_version_says_so(runner: StrategyRunner) -> None:
    """Nobody said, and the record says that rather than guessing."""
    result = runner.run(BuyAndHold(instruments=("ETF_EU",)), ["ETF_EU"], "2026-09-09", "2026-09-14")

    assert result.configuration["source"] == {
        "git_commit": None,
        "dirty": None,
        "source_state": "UNRECORDED",
    }


def test_a_runner_without_a_cost_model_cannot_be_built(
    runner: StrategyRunner,
) -> None:
    """Free trading by default would be a return no account could have had."""
    with pytest.raises(ValueError, match="ExecutionModel"):
        StrategyRunner(
            reader=runner.reader,
            calendars=runner.calendars,
            reference_calendar_id="XPAR",
            base_currency="EUR",
            analytics=CONFIG,
            execution=None,  # type: ignore[arg-type]
        )


def test_a_runner_reading_ages_on_another_calendar_is_refused(runner: StrategyRunner) -> None:
    """The reader and the runs must count sessions on the same calendar."""
    with pytest.raises(ValueError, match="counts ages on XPAR"):
        StrategyRunner(
            reader=runner.reader,
            calendars=runner.calendars,
            reference_calendar_id="XNYS",
            base_currency="EUR",
            analytics=CONFIG,
            execution=runner.execution,
        )


def with_benchmark(runner: StrategyRunner, benchmark: str) -> StrategyRunner:
    """Return the same runner with a benchmark declared."""
    return StrategyRunner(
        reader=runner.reader,
        calendars=runner.calendars,
        reference_calendar_id="XPAR",
        base_currency="EUR",
        analytics=CONFIG,
        execution=runner.execution,
        initial_cash=10_000.0,
        timetable=PARIS,
        benchmark=benchmark,
    )


def test_a_declared_benchmark_is_recorded_and_used_by_default(runner: StrategyRunner) -> None:
    """What a run is measured against is part of what it was, not an afterthought."""
    declared = with_benchmark(runner, "ETF_OTHER")

    strategy = BuyAndHold(instruments=("ETF_EU",))
    result = declared.run(strategy, ["ETF_EU"], "2026-09-09", "2026-09-14")

    assert result.configuration["benchmark"] == {
        "instrument_id": "ETF_OTHER",
        "basis": "TOTAL_RETURN",
        "label": None,
    }
    assert result.compare().label == "ETF_OTHER"
    assert result.benchmark().spec.instrument_id == "ETF_OTHER"


def test_comparing_with_nothing_declared_and_nothing_given_is_refused(
    runner: StrategyRunner,
) -> None:
    """There is no default yardstick; one is named or declared."""
    result = runner.run(BuyAndHold(instruments=("ETF_EU",)), ["ETF_EU"], "2026-09-09", "2026-09-14")

    with pytest.raises(ValueError, match="no benchmark"):
        result.compare()


def test_a_benchmark_in_another_currency_is_refused_when_declared(runner: StrategyRunner) -> None:
    """Refused where it is written down, not on the first comparison weeks later."""
    from quant_backtester.analytics.comparison import BenchmarkCurrencyMismatch

    with pytest.raises(BenchmarkCurrencyMismatch):
        with_benchmark(runner, "IDX_US")


def test_a_benchmark_the_registry_does_not_know_is_refused(runner: StrategyRunner) -> None:
    """A typo in a benchmark id is caught before any run."""
    with pytest.raises(ValueError, match="not in the registry"):
        with_benchmark(runner, "NOPE")


def test_the_result_hands_back_every_view_of_the_run(runner: StrategyRunner) -> None:
    """Records, fills, orders, rejects, holdings, weights and costs, all from one source."""
    result = runner.run(BuyAndHold(instruments=("ETF_EU",)), ["ETF_EU"], "2026-09-09", "2026-09-14")

    assert result.records() is result.backtest.records
    assert list(result.fills()["instrument_id"]) == ["ETF_EU"]
    # A whole book costs a commission more than the book: the purchase is cut
    # to what the cash can carry, and the cut is on the record.
    assert list(result.orders()["status"]) == ["PARTIALLY_FILLED"]
    assert list(result.rejects()["reason"]) == ["INSUFFICIENT_CASH"]
    assert list(result.holdings().columns) == ["ETF_EU", "cash"]
    assert list(result.weights().columns) == ["ETF_EU"]
    assert list(result.target_weights().columns) == ["ETF_EU"]
    assert result.costs()["total_cost"].sum() == pytest.approx(result.backtest.total_cost)


# --- a finished run does not move when the store does (audit A05) ------------------


def test_a_revision_after_the_run_changes_neither_its_benchmark_nor_its_records(
    runner: StrategyRunner,
    repository: MarketDataRepository,
    make_bars: Callable[..., pd.DataFrame],
    xpar: TradingCalendar,
    prices: Callable[..., dict[date, float]],
    sessions: tuple[date, ...],
) -> None:
    """A close revised from 227 to 999 used to move a finished run's comparison.

    The declared benchmark was valued during the run and is kept. Any other
    benchmark would have to be read now, from a store that is no longer the
    one the run read, and is refused.
    """
    declared = with_benchmark(runner, "ETF_OTHER")
    result = declared.run(
        BuyAndHold(instruments=("ETF_EU",)), ["ETF_EU"], sessions[0], sessions[-1]
    )
    curve = list(result.benchmark().equity)
    compared = result.compare().benchmark.total_return
    records = result.frame()

    revised = prices(200.0, 3.0)
    revised[sessions[-1]] = 999.0
    repository.save_checked_bars("ETF_OTHER", make_bars("ETF_OTHER", xpar, revised))

    assert list(result.benchmark().equity) == curve
    assert result.compare().benchmark.total_return == compared
    pd.testing.assert_frame_equal(result.frame(), records)
    with pytest.raises(StoreChanged, match="no longer holds"):
        result.benchmark("ETF_EU")


def test_another_benchmark_is_valued_while_the_store_is_unchanged(runner: StrategyRunner) -> None:
    result = runner.run(BuyAndHold(instruments=("ETF_EU",)), ["ETF_EU"], "2026-09-09", "2026-09-14")

    assert len(result.benchmark("ETF_OTHER").equity) == len(result.records())


def test_the_run_id_names_the_data_as_well_as_the_question(
    runner: StrategyRunner,
    repository: MarketDataRepository,
    make_bars: Callable[..., pd.DataFrame],
    xpar: TradingCalendar,
    prices: Callable[..., dict[date, float]],
) -> None:
    """Same strategy, same code, other data: same fingerprint, another run."""
    strategy = BuyAndHold(instruments=("ETF_EU",))
    first = runner.run(strategy, ["ETF_EU"], "2026-09-09", "2026-09-14")
    again = runner.run(strategy, ["ETF_EU"], "2026-09-09", "2026-09-14")
    repository.save_checked_bars("ETF_OTHER", make_bars("ETF_OTHER", xpar, prices(300.0, 1.0)))
    later = runner.run(strategy, ["ETF_EU"], "2026-09-09", "2026-09-14")

    assert first.run_id == again.run_id
    assert first.fingerprint == later.fingerprint
    assert first.run_id != later.run_id
    assert first.configuration["data_state"] != later.configuration["data_state"]
    assert first.data_state.files != later.data_state.files


def _writes_while_deciding(ctx: StrategyContext) -> TargetAllocation:
    """Try to promote data mid-run, standing for another process."""
    MarketDataRepository(_STORE[0]).append_revisions(pd.DataFrame())
    return ctx.cash()


_STORE: list[Path] = []


def test_nothing_is_promoted_while_a_run_reads_the_store(
    runner: StrategyRunner, repository: MarketDataRepository
) -> None:
    """The run holds the store: a writer during it is refused, not interleaved."""
    from quant_backtester.strategies.functional import FunctionalStrategy

    _STORE[:] = [repository.root]
    writer = FunctionalStrategy(strategy_id="writer", decision=_writes_while_deciding)

    with pytest.raises(StoreBusy):
        runner.run(writer, ["ETF_EU"], "2026-09-09", "2026-09-14")


def test_a_basket_whose_first_purchase_was_partial_is_completed_then_kept(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    calendars: CalendarRegistry,
    xpar: TradingCalendar,
    prices: Callable[..., dict[date, float]],
) -> None:
    """Audit A07, end to end.

    ETF_OTHER has no opening price on 10 September, so the first execution
    buys ETF_EU alone. The next one buys ETF_OTHER with the cash left; after
    that nothing is traded, and ETF_EU was never touched again.
    """
    from quant_backtester.data.schemas import BarField

    market = make_market(
        {
            "ETF_EU": make_bars("ETF_EU", xpar, prices(100.0, 1.0)),
            "ETF_OTHER": make_bars(
                "ETF_OTHER",
                xpar,
                prices(200.0, 3.0),
                contested={date(2026, 9, 10): (BarField.OPEN,)},
            ),
        }
    )
    free = StrategyRunner(
        reader=market,
        calendars=calendars,
        reference_calendar_id="XPAR",
        base_currency="EUR",
        analytics=CONFIG,
        initial_cash=10_000.0,
        execution=ExecutionModel(costs=CostModel()),
        timetable=PARIS,
    )

    result = free.run(
        BuyAndHold(instruments=("ETF_EU", "ETF_OTHER")),
        ["ETF_EU", "ETF_OTHER"],
        "2026-09-09",
        "2026-09-14",
    )

    fills = result.fills()
    assert list(zip(fills["session_date"], fills["instrument_id"], strict=True)) == [
        (date(2026, 9, 10), "ETF_EU"),
        (date(2026, 9, 11), "ETF_OTHER"),
    ]
    holdings = result.holdings()
    assert holdings["ETF_EU"].tolist()[1:] == [holdings["ETF_EU"].iloc[1]] * 3
    assert holdings["ETF_OTHER"].tolist() == [0.0, 0.0] + [holdings["ETF_OTHER"].iloc[2]] * 2
    assert holdings["cash"].iloc[-1] < 0.01 * result.equity().iloc[-1]


def _keeps_what_it_does_not_hold(ctx: StrategyContext) -> TargetAllocation:
    """Claim to keep a line the book does not have."""
    return TargetAllocation(as_of=ctx.as_of, weights={"ETF_EU": 0.3}, kept=frozenset({"ETF_EU"}))


def test_a_kept_line_must_be_recorded_at_the_book_weight(runner: StrategyRunner) -> None:
    """Keeping is a statement about the book, and the engine checks it."""
    from quant_backtester.strategies.functional import FunctionalStrategy

    liar = FunctionalStrategy(strategy_id="liar", decision=_keeps_what_it_does_not_hold)

    with pytest.raises(ValueError, match="not the book's"):
        runner.run(liar, ["ETF_EU"], "2026-09-09", "2026-09-14")


def _counter_strategy() -> FunctionalStrategy:
    """Return a strategy that breaks the contract: it invests on every third call."""
    calls = [0]

    def every_third(ctx: StrategyContext) -> TargetAllocation:
        calls[0] += 1
        return ctx.equal_weight(["ETF_EU"]) if calls[0] % 3 == 0 else ctx.cash()

    return FunctionalStrategy(strategy_id="every_third", decision=every_third)


def test_the_mutation_guard_sees_the_definition_and_not_a_closure(
    runner: StrategyRunner,
) -> None:
    """Audit A14: what the guard does not prove, written down as a test.

    The same object run twice decides differently - its closure counted - and
    the fingerprint and the guard see nothing. A fresh object per run is what
    brings the runs back together, which is the check the contract asks for.
    """
    reused = _counter_strategy()
    first = runner.run(reused, ["ETF_EU"], "2026-09-07", "2026-09-11")
    second = runner.run(reused, ["ETF_EU"], "2026-09-07", "2026-09-11")
    fresh = runner.run(_counter_strategy(), ["ETF_EU"], "2026-09-07", "2026-09-11")

    assert first.fingerprint == second.fingerprint
    assert not first.holdings().equals(second.holdings())
    assert first.holdings().equals(fresh.holdings())


def test_two_fills_on_one_session_are_one_rebalancing_and_two_fills(
    runner: StrategyRunner,
) -> None:
    """Audit A17: the table's ``trades`` counted sessions, and a session can fill two orders."""
    result = runner.run(
        BuyAndHold(instruments=("ETF_EU", "ETF_OTHER")),
        ["ETF_EU", "ETF_OTHER"],
        "2026-09-09",
        "2026-09-14",
    )
    report = result.report()

    assert len(result.fills()) == 2
    assert report.quality.fills == 2
    assert report.costs.rebalancings == 1


def test_a_report_states_the_model_it_was_produced_under(runner: StrategyRunner) -> None:
    """Audit section 5: fills, gross, cash, limits and a decision's life, said in the report."""
    result = runner.run(BuyAndHold(instruments=("ETF_EU",)), ["ETF_EU"], "2026-09-09", "2026-09-14")

    rendered = result.report().render()

    assert "OPEN_AUCTION_NOTIONAL" in rendered
    assert "not a separate cost-free run" in rendered
    assert "target weights, before costs" in rendered
    assert "one execution" in rendered
    assert result.configuration["decision_lifetime"] == "one execution"


def test_a_limit_caps_the_target_and_the_report_shows_the_weight_held(
    runner: StrategyRunner,
) -> None:
    """Decision D6: capped at 50% before a 1% commission, the position ends above it."""
    from dataclasses import replace as replaced

    from quant_backtester.portfolio.limits import PortfolioLimits

    capped = replaced(
        runner,
        limits=PortfolioLimits(max_weight_per_instrument=0.5),
        execution=ExecutionModel(costs=CostModel(commission_rate=0.01)),
    )
    result = capped.run(BuyAndHold(instruments=("ETF_EU",)), ["ETF_EU"], "2026-09-09", "2026-09-10")

    held = result.report().quality.max_realised_weight
    assert held is not None
    assert held > 0.5
    assert "largest weight held" in result.report().render()


def test_a_basket_is_completed_with_the_cash_there_is_at_the_open(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    calendars: CalendarRegistry,
    xpar: TradingCalendar,
) -> None:
    """Audit R05: the completion was a share of equity fixed at the close.

    ETF_EU is bought, 50 at 100; ETF_OTHER's open is contested. Overnight
    ETF_EU halves. Half of the new equity (7 500) is 3 750, and 1 250 of the
    cash stayed idle for good; bought with the cash there is, ETF_OTHER gets
    50 at 100 and the cash is spent.
    """
    from quant_backtester.data.schemas import BarField

    days = (date(2026, 9, 9), date(2026, 9, 10), date(2026, 9, 11), date(2026, 9, 14))
    market = make_market(
        {
            "ETF_EU": make_bars(
                "ETF_EU", xpar, dict(zip(days, (100.0, 100.0, 50.0, 50.0), strict=True))
            ),
            "ETF_OTHER": make_bars(
                "ETF_OTHER",
                xpar,
                dict.fromkeys(days, 100.0),
                contested={days[1]: (BarField.OPEN,)},
            ),
        }
    )
    free = StrategyRunner(
        reader=market,
        calendars=calendars,
        reference_calendar_id="XPAR",
        base_currency="EUR",
        analytics=CONFIG,
        initial_cash=10_000.0,
        execution=ExecutionModel(costs=CostModel()),
        timetable=PARIS,
    )

    result = free.run(
        BuyAndHold(instruments=("ETF_EU", "ETF_OTHER")), ["ETF_EU", "ETF_OTHER"], days[0], days[-1]
    )

    holdings = result.holdings()
    assert holdings["ETF_EU"].iloc[-1] == pytest.approx(50.0)
    assert holdings["ETF_OTHER"].iloc[-1] == pytest.approx(50.0)
    assert holdings["cash"].iloc[-1] == pytest.approx(0.0, abs=1e-9)


def test_a_cash_purchase_leaves_room_for_its_commission(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    calendars: CalendarRegistry,
    xpar: TradingCalendar,
) -> None:
    """Sized net of the commission, the completion is not cut for want of cash."""
    from quant_backtester.data.schemas import BarField

    days = (date(2026, 9, 9), date(2026, 9, 10), date(2026, 9, 11), date(2026, 9, 14))
    market = make_market(
        {
            "ETF_EU": make_bars("ETF_EU", xpar, dict.fromkeys(days, 100.0)),
            "ETF_OTHER": make_bars(
                "ETF_OTHER",
                xpar,
                dict.fromkeys(days, 100.0),
                contested={days[1]: (BarField.OPEN,)},
            ),
        }
    )
    charged = StrategyRunner(
        reader=market,
        calendars=calendars,
        reference_calendar_id="XPAR",
        base_currency="EUR",
        analytics=CONFIG,
        initial_cash=10_000.0,
        execution=ExecutionModel(costs=CostModel(commission_rate=0.01, minimum_commission=2.0)),
        timetable=PARIS,
    )

    result = charged.run(
        BuyAndHold(instruments=("ETF_EU", "ETF_OTHER")), ["ETF_EU", "ETF_OTHER"], days[0], days[-1]
    )

    rejects = result.rejects()
    cut = rejects.loc[rejects["reason"] == "INSUFFICIENT_CASH", "instrument_id"]
    assert "ETF_OTHER" not in set(cut)
    assert result.holdings()["cash"].iloc[-1] == pytest.approx(0.0, abs=1e-6)


def test_what_a_caller_does_to_a_benchmark_it_was_handed_changes_nothing_kept(
    runner: StrategyRunner,
) -> None:
    """Audit R06: rewriting the series a result returned rewrote the result."""
    declared = with_benchmark(runner, "ETF_OTHER")
    result = declared.run(
        BuyAndHold(instruments=("ETF_EU",)), ["ETF_EU"], "2026-09-09", "2026-09-14"
    )
    before = result.compare().benchmark.total_return

    handed = result.benchmark().equity
    handed.iloc[-1] = 99_999.0
    kept = result.benchmark_curve
    assert kept is not None
    through_the_field = kept.equity
    through_the_field.iloc[-1] = 99_999.0

    assert result.compare().benchmark.total_return == before
    assert result.benchmark().equity.iloc[-1] != 99_999.0


def test_a_calendar_handed_over_in_memory_is_part_of_the_run_id(
    runner: StrategyRunner, xpar: TradingCalendar, xnys: TradingCalendar
) -> None:
    """Audit R07: one id, ``XPAR``, and one more holiday made no difference to ``run_id``.

    The holiday added here is outside the run, so the records are the same and
    the calendars are not: the identity follows the inputs, not the outputs.
    """
    from dataclasses import replace as replaced
    from datetime import time as clock

    stated = xpar.definition()
    holidays = [date.fromisoformat(str(day)) for day in stated["holidays"]]  # type: ignore[union-attr]
    early = stated["early_closes"]
    assert isinstance(early, dict)
    shifted = TradingCalendar(
        calendar_id="XPAR",
        timezone=str(stated["timezone"]),
        regular_open=clock.fromisoformat(str(stated["regular_open"])),
        regular_close=clock.fromisoformat(str(stated["regular_close"])),
        holidays=frozenset({*holidays, date(2026, 11, 11)}),
        early_closes={
            date.fromisoformat(day): clock.fromisoformat(at) for day, at in early.items()
        },
        covered_from=xpar.covered_from,
        covered_until=xpar.covered_until,
    )
    other = replaced(runner, calendars=CalendarRegistry([xnys, shifted]))
    strategy = BuyAndHold(instruments=("ETF_EU",))

    first = runner.run(strategy, ["ETF_EU"], "2026-09-09", "2026-09-14")
    second = other.run(strategy, ["ETF_EU"], "2026-09-09", "2026-09-14")

    pd.testing.assert_frame_equal(first.frame(), second.frame())
    assert first.run_id != second.run_id
    assert first.configuration["inputs"] != second.configuration["inputs"]


def test_an_instrument_edited_in_memory_is_part_of_the_run_id(
    runner: StrategyRunner, repository: MarketDataRepository
) -> None:
    from dataclasses import replace as replaced

    from quant_backtester.data.instruments import InstrumentRegistry

    registry = runner.reader.instruments
    edited = InstrumentRegistry(
        [
            replaced(instrument, name=instrument.name + " (edited)")
            if instrument.id == "ETF_OTHER"
            else instrument
            for instrument in registry
        ]
    )
    reader = MarketDataReader(
        repository=repository,
        instruments=edited,
        calendars=runner.reader.calendars,
        reference_calendar_id="XPAR",
    )
    strategy = BuyAndHold(instruments=("ETF_EU",))

    first = runner.run(strategy, ["ETF_EU"], "2026-09-09", "2026-09-14")
    second = replaced(runner, reader=reader).run(strategy, ["ETF_EU"], "2026-09-09", "2026-09-14")

    assert first.run_id != second.run_id


def test_a_report_names_the_history_basis_of_what_the_run_read(runner: StrategyRunner) -> None:
    """Section 7.3: a RESTATED series read by a signal is a look-ahead to name, not to bury."""
    result = runner.run(BuyAndHold(instruments=("ETF_EU",)), ["ETF_EU"], "2026-09-09", "2026-09-14")

    assert result.configuration["history_basis"] == {"ETF_EU": None}
    assert "history read: UNDECLARED ETF_EU" in result.report().render()


def _stays_in_cash(ctx: StrategyContext) -> TargetAllocation:
    """Hold nothing, whatever the session."""
    return ctx.cash()


def test_a_run_may_end_on_the_last_session_its_calendar_covers(
    runner: StrategyRunner,
) -> None:
    """Audit R10: every run asked the calendar for the session after its end, and raised."""
    cash = FunctionalStrategy(strategy_id="cash", decision=_stays_in_cash)

    result = runner.run(cash, [], "2026-12-30", "2026-12-31")

    assert [record.session_date for record in result.records()] == [
        date(2026, 12, 30),
        date(2026, 12, 31),
    ]


def _reads_a_rate(ctx: StrategyContext) -> TargetAllocation:
    """Invest in ETF_EU when a rate the strategy reads directly is positive."""
    rate = ctx.market.value("RATE_US")
    if rate.value is not None and rate.value > 0.0:
        return ctx.weights({"ETF_EU": 0.5})
    return ctx.cash()


def test_a_series_read_through_the_market_view_is_named_in_the_report(
    runner: StrategyRunner,
) -> None:
    """Audit N08: a rate read by ctx.market decided the book and was absent from the report."""
    reading = FunctionalStrategy(strategy_id="rate_reader", decision=_reads_a_rate)

    result = runner.run(reading, ["ETF_EU"], "2026-09-09", "2026-09-14")

    assert "RATE_US" in result.configuration["history_basis"]  # type: ignore[operator]
    assert "RATE_US" in result.report().render()
