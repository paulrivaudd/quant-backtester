"""Exercise 3: the tests of MovingAverageEntryExitETF and of its run script.

The market is the one of ``tests/conftest.py``: the synthetic XPAR calendar of
2026 and the ETF ``ETF_EU``. The fund is bought above its three-session average
and sold below its five-session one, and each case is five closes ending on the
decision day, so everything is checked by hand:

====================  =====  ======  ======  ==============================
last five closes      close  MA3     MA5     the close is
====================  =====  ======  ======  ==============================
100 100 100 100 110   110    103.33  102     above both
100 100 100 100  90    90     96.67   98     below both
120 120  90  90 100   100     93.33  104     above the entry, below the exit
 80  80 110 110 100   100    106.67   96     below the entry, above the exit
100 100 100 100 100   100    100     100     on both lines
====================  =====  ======  ======  ==============================

Nothing touches the network.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, time
from pathlib import Path
from types import ModuleType
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.backtest.runner import StrategyResult, StrategyRunner
from quant_backtester.data.calendars import TradingCalendar
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.data.schemas import BarField
from quant_backtester.demo import demo_runner
from quant_backtester.portfolio.state import PortfolioState
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.engine import SignalEngine, SignalRequest
from quant_backtester.signals.price.trend import MovingAverageTrendSignal
from quant_backtester.signals.types import PriceBasis
from quant_backtester.strategies.base import Strategy
from quant_backtester.strategies.examples.moving_average_entry_exit import (
    MovingAverageEntryExitETF,
)

FIRST_DAY = date(2026, 11, 2)
"""The first session the fund has a close on."""

DECISION_DAY = date(2026, 11, 30)
"""A Monday with four weeks of XPAR sessions behind it."""

DECISION = datetime.combine(DECISION_DAY, time(23, 0), tzinfo=ZoneInfo("Europe/Paris"))
"""After the Paris close of the decision day: its close is knowable."""

REPOSITORY = Path(__file__).resolve().parents[2]
"""The root of the checkout: the script lives there."""

ABOVE_BOTH = (100.0, 100.0, 100.0, 100.0, 110.0)
BELOW_BOTH = (100.0, 100.0, 100.0, 100.0, 90.0)
REBOUND = (120.0, 120.0, 90.0, 90.0, 100.0)
"""Above the entry average and still below the exit one: the close after a fall."""
DIP = (80.0, 80.0, 110.0, 110.0, 100.0)
"""Below the entry average and still above the exit one: the dip the rule sits through."""
ON_BOTH = (100.0, 100.0, 100.0, 100.0, 100.0)

MarketBuilder = Callable[..., MarketDataReader]
BarsBuilder = Callable[..., pd.DataFrame]
ContextBuilder = Callable[[MarketDataReader, datetime], SignalContext]
DecisionBuilder = Callable[..., StrategyContext]
BookBuilder = Callable[..., PortfolioState]


def history(
    xpar: TradingCalendar, tail: Sequence[float], *, first: date = FIRST_DAY
) -> dict[date, float]:
    """Return a close of 100 per XPAR session, then ``tail`` on the last sessions."""
    days = [day.session_date for day in xpar.sessions(first, DECISION_DAY)]
    closes = {day: 100.0 for day in days}
    closes.update(zip(days[-len(tail) :], tail, strict=True))
    return closes


def on_etf_eu() -> MovingAverageEntryExitETF:
    """Return the strategy on the synthetic market's Paris ETF: in above MA3, out below MA5."""
    return MovingAverageEntryExitETF(instrument_id="ETF_EU", entry_sessions=3, exit_sessions=5)


@pytest.fixture
def decide(
    make_market: MarketBuilder,
    make_bars: BarsBuilder,
    xpar: TradingCalendar,
    make_context: ContextBuilder,
    make_decision: DecisionBuilder,
    make_book: BookBuilder,
) -> Callable[..., TargetAllocation]:
    """Return what the strategy decides on given closes, from cash or holding the fund."""

    def run(closes: Mapping[date, float], *, held: bool) -> TargetAllocation:
        rule = on_etf_eu()
        market = make_market({"ETF_EU": make_bars("ETF_EU", xpar, closes)})
        context = make_context(market, DECISION)
        requests = [
            item.resolved(DECISION.date()) if isinstance(item, SignalRequest) else item
            for item in rule.required_signals()
        ]
        snapshot = SignalEngine().compute(context, requests, ["ETF_EU"])
        # A book that is the fund and nothing else, or cash and nothing else.
        book = make_book(0.0, {"ETF_EU": 10.0}) if held else make_book(10_000.0)
        prices = {"ETF_EU": closes[DECISION_DAY]} if held else {}
        return rule.decide(
            make_decision(context, snapshot, universe=("ETF_EU",), holdings=book, prices=prices)
        )

    return run


def load_script() -> ModuleType:
    """Import ``scripts/run_moving_average_entry_exit_exercise.py`` by its path.

    The script imports the golden cross one beside it by name, as it does when
    it is run, so its folder is put on the path first.
    """
    scripts = REPOSITORY / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    path = scripts / "run_moving_average_entry_exit_exercise.py"
    spec = importlib.util.spec_from_file_location("run_moving_average_entry_exit_exercise", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- the signals and the contract ------------------------------------------------------


def test_the_two_signals_are_the_existing_distance_to_an_average() -> None:
    strategy = MovingAverageEntryExitETF()
    entry, leave = strategy.entry_signal(), strategy.exit_signal()
    assert isinstance(entry, MovingAverageTrendSignal)
    assert isinstance(leave, MovingAverageTrendSignal)
    assert (entry.signal_id, entry.window_sessions) == ("price_over_ma50", 50)
    assert (leave.signal_id, leave.window_sessions) == ("price_over_ma100", 100)
    for signal in (entry, leave):
        assert signal.price_basis is PriceBasis.ADJUSTED
        assert signal.bar_field is BarField.CLOSE


def test_the_contract_of_the_class() -> None:
    strategy = MovingAverageEntryExitETF()
    assert isinstance(strategy, Strategy)
    assert strategy.instrument_id == "ETF_WORLD"
    assert (strategy.entry_sessions, strategy.exit_sessions) == (50, 100)
    assert strategy.strategy_id == "moving_average_entry_exit_etf"
    with pytest.raises(dataclasses.FrozenInstanceError):
        strategy.exit_sessions = 200  # type: ignore[misc]


def test_both_signals_are_asked_for_the_studied_etf_only() -> None:
    strategy = MovingAverageEntryExitETF()
    declared = list(strategy.required_signals())
    assert [request.signal for request in declared if isinstance(request, SignalRequest)] == [
        strategy.entry_signal(),
        strategy.exit_signal(),
    ]
    for request in declared:
        assert isinstance(request, SignalRequest)
        assert list(request.names() or ()) == ["ETF_WORLD"]


@pytest.mark.parametrize(
    "parameters",
    [{"entry_sessions": 20}, {"exit_sessions": 200}],
    ids=["entry", "exit"],
)
def test_every_parameter_enters_the_definition(parameters: dict[str, object]) -> None:
    changed = MovingAverageEntryExitETF(**parameters)  # type: ignore[arg-type]
    assert changed.fingerprint() != MovingAverageEntryExitETF().fingerprint()


@pytest.mark.parametrize(
    "parameters",
    [{"instrument_id": ""}, {"entry_sessions": 1}, {"exit_sessions": 0}, {"entry_sessions": 100}],
    ids=["empty-instrument", "entry-of-one-price", "exit-of-no-price", "one-average-for-both"],
)
def test_an_impossible_configuration_is_refused(parameters: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        MovingAverageEntryExitETF(**parameters)  # type: ignore[arg-type]


# --- the decision ----------------------------------------------------------------------


def test_a_close_above_both_averages_is_bought(
    decide: Callable[..., TargetAllocation], xpar: TradingCalendar
) -> None:
    allocation = decide(history(xpar, ABOVE_BOTH), held=False)
    assert dict(allocation.weights) == {"ETF_EU": 1.0}
    assert not allocation.hold_positions


def test_a_fund_already_bought_is_not_bought_again(
    decide: Callable[..., TargetAllocation], xpar: TradingCalendar
) -> None:
    """Still above the next evening: a restated 100% would trade the overnight drift."""
    allocation = decide(history(xpar, ABOVE_BOTH), held=True)
    assert dict(allocation.weights) == {"ETF_EU": 1.0}
    assert allocation.hold_positions


def test_a_close_below_the_exit_average_is_sold(
    decide: Callable[..., TargetAllocation], xpar: TradingCalendar
) -> None:
    allocation = decide(history(xpar, BELOW_BOTH), held=True)
    assert dict(allocation.weights) == {}
    assert not allocation.hold_positions


def test_a_dip_under_the_entry_average_alone_is_sat_through(
    decide: Callable[..., TargetAllocation], xpar: TradingCalendar
) -> None:
    """What the rule is for: 100 is under its MA3 of 106.67 and above its MA5 of 96."""
    allocation = decide(history(xpar, DIP), held=True)
    assert dict(allocation.weights) == {"ETF_EU": 1.0}
    assert allocation.hold_positions


def test_a_dip_under_the_entry_average_buys_nothing(
    decide: Callable[..., TargetAllocation], xpar: TradingCalendar
) -> None:
    allocation = decide(history(xpar, DIP), held=False)
    assert dict(allocation.weights) == {}
    assert allocation.hold_positions


@pytest.mark.parametrize("held", [True, False], ids=["holding", "in-cash"])
def test_the_sale_comes_first_when_the_two_averages_disagree(
    decide: Callable[..., TargetAllocation], xpar: TradingCalendar, held: bool
) -> None:
    """100 is above its MA3 of 93.33 and below its MA5 of 104: sold, and not bought back."""
    allocation = decide(history(xpar, REBOUND), held=held)
    assert dict(allocation.weights) == {}
    assert not allocation.hold_positions


@pytest.mark.parametrize("held", [True, False], ids=["holding", "in-cash"])
def test_a_close_exactly_on_both_lines_has_passed_neither(
    decide: Callable[..., TargetAllocation], xpar: TradingCalendar, held: bool
) -> None:
    allocation = decide(history(xpar, ON_BOTH), held=held)
    assert dict(allocation.weights) == ({"ETF_EU": 1.0} if held else {})
    assert allocation.hold_positions


@pytest.mark.parametrize(
    ("tail", "held"), [(BELOW_BOTH, True), (ABOVE_BOTH, False)], ids=["holding", "in-cash"]
)
def test_too_short_a_history_keeps_the_book_and_is_not_an_error(
    decide: Callable[..., TargetAllocation],
    xpar: TradingCalendar,
    tail: tuple[float, ...],
    held: bool,
) -> None:
    """Four sessions: the entry average exists, the exit one does not, so no order."""
    short = history(xpar, tail[1:], first=date(2026, 11, 25))
    assert len(short) == 4
    allocation = decide(short, held=held)
    assert dict(allocation.weights) == ({"ETF_EU": 1.0} if held else {})
    assert allocation.hold_positions


def test_a_missing_session_in_the_exit_window_keeps_the_book(
    decide: Callable[..., TargetAllocation], xpar: TradingCalendar
) -> None:
    """The boundary case: a hole inside the five sessions is not bridged by an older close."""
    closes = history(xpar, BELOW_BOTH)
    del closes[date(2026, 11, 24)]
    allocation = decide(closes, held=True)
    assert dict(allocation.weights) == {"ETF_EU": 1.0}
    assert allocation.hold_positions


def test_a_price_after_the_decision_changes_nothing(
    decide: Callable[..., TargetAllocation], xpar: TradingCalendar
) -> None:
    """The look-ahead guard: a crash the next day cannot undo today's purchase."""
    closes = history(xpar, ABOVE_BOTH)
    first = decide(closes, held=False)
    second = decide(closes | {date(2026, 12, 1): 1.0}, held=False)
    assert dict(first.weights) == dict(second.weights) == {"ETF_EU": 1.0}
    assert first.hold_positions == second.hold_positions


def test_the_strategy_is_exported_by_the_package() -> None:
    import quant_backtester.strategies as strategies

    assert strategies.MovingAverageEntryExitETF is MovingAverageEntryExitETF


# --- a whole run, on the offline synthetic market ----------------------------------------

DEMO_SEED = 20240101
"""Seed of the synthetic market the run and the script's output are tested on."""

DEMO_STRATEGY = MovingAverageEntryExitETF(
    instrument_id="FUND_A", entry_sessions=5, exit_sessions=10
)
"""The strategy on the demo market: lengths its two years of history can serve."""

DEMO_PERIOD = ("2025-01-02", "2025-12-31")
"""The measured year of the demo market; 2024 is the warm-up."""


@pytest.fixture(scope="module")
def demo(tmp_path_factory: pytest.TempPathFactory) -> StrategyRunner:
    """Return a runner over the offline synthetic market."""
    return demo_runner(tmp_path_factory.mktemp("entry_exit") / "store", seed=DEMO_SEED)


@pytest.fixture(scope="module")
def demo_result(demo: StrategyRunner) -> StrategyResult:
    """Return one finished run of the strategy on the synthetic market."""
    return demo.run(DEMO_STRATEGY, ("FUND_A",), *DEMO_PERIOD)


def test_a_run_trades_only_on_the_session_after_an_average_was_passed(
    demo_result: StrategyResult,
) -> None:
    """Every fill, recomputed with a naive loop over the closes the run could see."""
    reader = demo_result.reader.at(demo_result.records()[-1].valuation_time)
    closes = reader.adjusted_history("FUND_A", end=demo_result.end)
    days: list[date] = [load_script().session_date(day) for day in closes.index]
    values = [float(value) for value in closes]
    held = False
    expected: list[tuple[date, str]] = []
    for index in range(9, len(days) - 1):
        if days[index] < demo_result.start:
            continue
        entry = sum(values[index - 4 : index + 1]) / 5
        leave = sum(values[index - 9 : index + 1]) / 10
        tomorrow = days[index + 1]
        if values[index] < leave:
            if held:
                held = False
                expected.append((tomorrow, "SELL"))
        elif values[index] > entry and not held:
            held = True
            expected.append((tomorrow, "BUY"))
    fills = demo_result.fills()
    assert len(expected) >= 4
    assert list(zip(fills["session_date"], fills["side"], strict=True)) == expected


# --- the script --------------------------------------------------------------------------


def test_the_script_declares_the_strategy_of_the_exercise() -> None:
    script = load_script()
    strategy = script.STRATEGY
    assert strategy == MovingAverageEntryExitETF(
        instrument_id="ETF_WORLD", entry_sessions=50, exit_sessions=100
    )
    assert script.UNIVERSE == ("ETF_WORLD",)
    assert script.PERIOD == ("2019-04-01", "2026-09-17")


def test_the_three_figures_are_saved_and_the_directory_created(
    demo_result: StrategyResult, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import matplotlib.pyplot as plt

    def refuse() -> None:
        raise AssertionError("a script saves a figure, it does not show it")

    monkeypatch.setattr(plt, "show", refuse)
    directory = tmp_path / "not" / "there" / "yet"
    load_script().save_figures(demo_result, directory, DEMO_STRATEGY)
    saved = sorted(path.name for path in directory.iterdir())
    assert saved == ["drawdown.png", "equity.png", "moving_averages.png"]
    for path in directory.iterdir():
        assert path.read_bytes().startswith(b"\x89PNG")


def test_main_runs_the_declared_strategy_prints_it_and_saves_its_figures(
    demo: StrategyRunner,
    demo_result: StrategyResult,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The real store is not committed: main is wired onto the synthetic market."""
    script = load_script()
    monkeypatch.setattr(script, "build_runner", lambda root: demo)
    monkeypatch.setattr(script, "STRATEGY", DEMO_STRATEGY)
    monkeypatch.setattr(script, "UNIVERSE", ("FUND_A",))
    monkeypatch.setattr(script, "PERIOD", DEMO_PERIOD)
    output = tmp_path / "figures"

    assert script.main(["--output", str(output)]) == 0

    printed = capsys.readouterr().out
    assert f"run_id       {demo_result.run_id}" in printed
    assert f"== fills: {len(demo_result.fills())} rows ==" in printed
    assert (output / "moving_averages.png").is_file()


def test_a_run_that_never_held_the_fund_still_saves_its_figures(
    demo: StrategyRunner, tmp_path: Path
) -> None:
    """Audit 13, C02: a run that stayed in cash has no weight column, and is still drawn.

    The average is longer than the whole history, so the signal is never
    computable, no order is sent, and the weights table has no instrument.
    """
    strategy = dataclasses.replace(DEMO_STRATEGY, entry_sessions=600, exit_sessions=700)
    result = demo.run(strategy, ("FUND_A",), *DEMO_PERIOD)
    assert len(result.fills()) == 0
    assert "FUND_A" not in result.weights().columns

    load_script().save_figures(result, tmp_path / "cash", strategy)

    assert sorted(path.name for path in (tmp_path / "cash").iterdir()) == [
        "drawdown.png",
        "equity.png",
        "moving_averages.png",
    ]
