"""Exercise 2: the tests of MovingAverageBandETF and of its run script.

The market is the one of ``tests/conftest.py``: the synthetic XPAR calendar of
2026 and the ETF ``ETF_EU``. The fund closes at 100 on every session of
November 2026 but the last, and the average is taken over five sessions, so
everything is checked by hand: a last close of 80 has an average of 96 and sits
at 83% of it, a last close of 125 has an average of 105 and sits at 119% of it,
and a last close of 105 sits at 104% of its average of 101. Most decisions are
tested with a band, sold below 90% and bought above 110%, so that the three
cases - below, inside, above - are three different closes. Nothing touches the
network.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import sys
from collections.abc import Callable, Mapping
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
from quant_backtester.strategies.examples.moving_average_band import MovingAverageBandETF

FIRST_DAY = date(2026, 11, 2)
"""The first session the fund has a close on."""

DECISION_DAY = date(2026, 11, 30)
"""A Monday with four weeks of XPAR sessions behind it."""

DECISION = datetime.combine(DECISION_DAY, time(23, 0), tzinfo=ZoneInfo("Europe/Paris"))
"""After the Paris close of the decision day: its close is knowable."""

REPOSITORY = Path(__file__).resolve().parents[2]
"""The root of the checkout: the script lives there."""

LOW, MIDDLE, HIGH = 80.0, 105.0, 125.0
"""Last closes at 83%, 104% and 119% of their five-session average."""

MarketBuilder = Callable[..., MarketDataReader]
BarsBuilder = Callable[..., pd.DataFrame]
ContextBuilder = Callable[[MarketDataReader, datetime], SignalContext]
DecisionBuilder = Callable[..., StrategyContext]
BookBuilder = Callable[..., PortfolioState]


def history(
    xpar: TradingCalendar, last: float, *, first: date = FIRST_DAY, until: date = DECISION_DAY
) -> dict[date, float]:
    """Return a close of 100 per XPAR session, and ``last`` on the final one."""
    days = [day.session_date for day in xpar.sessions(first, until)]
    return {day: 100.0 for day in days[:-1]} | {days[-1]: last}


def on_etf_eu() -> MovingAverageBandETF:
    """Return the strategy on the synthetic market's Paris ETF: five sessions, 90% and 110%."""
    return MovingAverageBandETF(
        instrument_id="ETF_EU", window_sessions=5, sell_below=0.90, buy_above=1.10
    )


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

    def run(
        closes: Mapping[date, float],
        *,
        held: bool,
        strategy: MovingAverageBandETF | None = None,
    ) -> TargetAllocation:
        rule = on_etf_eu() if strategy is None else strategy
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
    """Import ``scripts/run_moving_average_band_exercise.py`` by its path.

    The script imports the golden cross one beside it by name, as it does when
    it is run, so its folder is put on the path first.
    """
    scripts = REPOSITORY / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    path = scripts / "run_moving_average_band_exercise.py"
    spec = importlib.util.spec_from_file_location("run_moving_average_band_exercise", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- the signal and the contract -------------------------------------------------------


def test_the_signal_is_the_existing_distance_to_the_average() -> None:
    signal = MovingAverageBandETF().signal()
    assert isinstance(signal, MovingAverageTrendSignal)
    assert signal.signal_id == "price_over_ma50"
    assert signal.window_sessions == 50
    assert signal.price_basis is PriceBasis.ADJUSTED
    assert signal.bar_field is BarField.CLOSE


def test_the_contract_of_the_class() -> None:
    strategy = MovingAverageBandETF()
    assert isinstance(strategy, Strategy)
    assert strategy.instrument_id == "ETF_WORLD"
    assert strategy.window_sessions == 50
    assert (strategy.sell_below, strategy.buy_above) == (1.0, 1.0)
    assert strategy.strategy_id == "moving_average_band_etf"
    with pytest.raises(dataclasses.FrozenInstanceError):
        strategy.buy_above = 1.05  # type: ignore[misc]


def test_the_signal_is_asked_for_the_studied_etf_only() -> None:
    strategy = MovingAverageBandETF()
    declared = list(strategy.required_signals())
    assert len(declared) == 1
    request = declared[0]
    assert isinstance(request, SignalRequest)
    assert request.signal == strategy.signal()
    assert list(request.names() or ()) == ["ETF_WORLD"]


@pytest.mark.parametrize(
    "parameters",
    [{"window_sessions": 100}, {"buy_above": 1.05}, {"sell_below": 0.95}],
    ids=["window", "buy-level", "sell-level"],
)
def test_every_parameter_enters_the_definition(parameters: dict[str, object]) -> None:
    changed = MovingAverageBandETF(**parameters)  # type: ignore[arg-type]
    assert changed.fingerprint() != MovingAverageBandETF().fingerprint()


@pytest.mark.parametrize(
    "parameters",
    [
        {"instrument_id": ""},
        {"window_sessions": 1},
        {"sell_below": 0.0},
        {"buy_above": float("nan")},
        {"buy_above": float("inf")},
        {"sell_below": True},
        {"sell_below": 1.20},
    ],
    ids=[
        "empty-instrument",
        "average-of-one-price",
        "sell-at-zero",
        "buy-at-nan",
        "buy-at-infinity",
        "a-boolean-level",
        "levels-crossed",
    ],
)
def test_an_impossible_configuration_is_refused(parameters: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        MovingAverageBandETF(**parameters)  # type: ignore[arg-type]


# --- the decision ----------------------------------------------------------------------


def test_a_close_far_above_its_average_is_bought(
    decide: Callable[..., TargetAllocation], xpar: TradingCalendar
) -> None:
    """125 against an average of 105 is 119% of it: bought in full, with an order."""
    allocation = decide(history(xpar, HIGH), held=False)
    assert dict(allocation.weights) == {"ETF_EU": 1.0}
    assert not allocation.hold_positions


def test_a_close_far_below_its_average_is_sold(
    decide: Callable[..., TargetAllocation], xpar: TradingCalendar
) -> None:
    """80 against an average of 96 is 83% of it: sold in full, with an order."""
    allocation = decide(history(xpar, LOW), held=True)
    assert dict(allocation.weights) == {}
    assert not allocation.hold_positions


def test_between_the_levels_a_held_fund_is_kept_without_an_order(
    decide: Callable[..., TargetAllocation], xpar: TradingCalendar
) -> None:
    allocation = decide(history(xpar, MIDDLE), held=True)
    assert dict(allocation.weights) == {"ETF_EU": 1.0}
    assert allocation.hold_positions


def test_between_the_levels_cash_stays_cash(
    decide: Callable[..., TargetAllocation], xpar: TradingCalendar
) -> None:
    """104% of the average is above it and inside the band: nothing is bought yet."""
    allocation = decide(history(xpar, MIDDLE), held=False)
    assert dict(allocation.weights) == {}
    assert allocation.hold_positions


def test_a_fund_already_bought_is_not_bought_again(
    decide: Callable[..., TargetAllocation], xpar: TradingCalendar
) -> None:
    """Still high the next evening: a restated 100% would trade the overnight drift."""
    allocation = decide(history(xpar, HIGH), held=True)
    assert dict(allocation.weights) == {"ETF_EU": 1.0}
    assert allocation.hold_positions


def test_a_low_close_with_nothing_to_sell_is_cash(
    decide: Callable[..., TargetAllocation], xpar: TradingCalendar
) -> None:
    allocation = decide(history(xpar, LOW), held=False)
    assert dict(allocation.weights) == {}


def test_a_close_exactly_on_a_level_has_not_passed_it(
    decide: Callable[..., TargetAllocation], xpar: TradingCalendar
) -> None:
    """Passing a level is strict: the levels are the signal's own number, to the bit."""
    low_ratio = 1.0 + (LOW / 96.0 - 1.0)
    high_ratio = 1.0 + (HIGH / 105.0 - 1.0)
    sells = dataclasses.replace(on_etf_eu(), sell_below=low_ratio)
    buys = dataclasses.replace(on_etf_eu(), buy_above=high_ratio)
    kept = decide(history(xpar, LOW), held=True, strategy=sells)
    waiting = decide(history(xpar, HIGH), held=False, strategy=buys)
    assert dict(kept.weights) == {"ETF_EU": 1.0} and kept.hold_positions
    assert dict(waiting.weights) == {} and waiting.hold_positions


def test_two_equal_levels_are_the_average_itself(
    decide: Callable[..., TargetAllocation], xpar: TradingCalendar
) -> None:
    """The default: held above the average, sold below it, kept exactly on it."""
    line = MovingAverageBandETF(instrument_id="ETF_EU", window_sessions=5)
    bought = decide(history(xpar, 101.0), held=False, strategy=line)
    sold = decide(history(xpar, 99.0), held=True, strategy=line)
    on_it = decide(history(xpar, 100.0), held=True, strategy=line)
    assert dict(bought.weights) == {"ETF_EU": 1.0} and not bought.hold_positions
    assert dict(sold.weights) == {} and not sold.hold_positions
    assert dict(on_it.weights) == {"ETF_EU": 1.0} and on_it.hold_positions


@pytest.mark.parametrize("held", [True, False], ids=["holding", "in-cash"])
def test_too_short_a_history_keeps_the_book_and_is_not_an_error(
    decide: Callable[..., TargetAllocation], xpar: TradingCalendar, held: bool
) -> None:
    """Four sessions for an average of five: no level was seen crossed, so no order."""
    short = history(xpar, LOW if held else HIGH, first=date(2026, 11, 25))
    assert len(short) == 4
    allocation = decide(short, held=held)
    assert dict(allocation.weights) == ({"ETF_EU": 1.0} if held else {})
    assert allocation.hold_positions


def test_a_missing_session_in_the_window_keeps_the_book(
    decide: Callable[..., TargetAllocation], xpar: TradingCalendar
) -> None:
    """The boundary case: a hole inside the five sessions is not bridged by an older close."""
    closes = history(xpar, LOW)
    del closes[date(2026, 11, 26)]
    allocation = decide(closes, held=True)
    assert dict(allocation.weights) == {"ETF_EU": 1.0}
    assert allocation.hold_positions


def test_a_price_after_the_decision_changes_nothing(
    decide: Callable[..., TargetAllocation], xpar: TradingCalendar
) -> None:
    """The look-ahead guard: a crash the next day cannot undo today's purchase."""
    closes = history(xpar, HIGH)
    first = decide(closes, held=False)
    second = decide(closes | {date(2026, 12, 1): 1.0}, held=False)
    assert dict(first.weights) == dict(second.weights) == {"ETF_EU": 1.0}
    assert first.hold_positions == second.hold_positions


def test_the_strategy_is_exported_by_the_package() -> None:
    import quant_backtester.strategies as strategies

    assert strategies.MovingAverageBandETF is MovingAverageBandETF


# --- a whole run, on the offline synthetic market ----------------------------------------

DEMO_SEED = 20240101
"""Seed of the synthetic market the run and the script's output are tested on."""

DEMO_STRATEGY = MovingAverageBandETF(
    instrument_id="FUND_A", window_sessions=5, sell_below=0.99, buy_above=1.01
)
"""The strategy on the demo market: levels its daily moves reach several times a year."""

DEMO_PERIOD = ("2025-01-02", "2025-12-31")
"""The measured year of the demo market; 2024 is the warm-up."""


@pytest.fixture(scope="module")
def demo(tmp_path_factory: pytest.TempPathFactory) -> StrategyRunner:
    """Return a runner over the offline synthetic market."""
    return demo_runner(tmp_path_factory.mktemp("moving_average_band") / "store", seed=DEMO_SEED)


@pytest.fixture(scope="module")
def demo_result(demo: StrategyRunner) -> StrategyResult:
    """Return one finished run of the strategy on the synthetic market."""
    return demo.run(DEMO_STRATEGY, ("FUND_A",), *DEMO_PERIOD)


def test_a_run_starts_in_cash_and_alternates_buys_and_sells(demo_result: StrategyResult) -> None:
    """The memory of the rule is the book: never two buys or two sells in a row."""
    sides = list(demo_result.fills()["side"])
    assert len(sides) >= 3
    assert sides == [("BUY", "SELL")[index % 2] for index in range(len(sides))]


def test_a_run_trades_only_on_the_session_after_a_level_was_passed(
    demo_result: StrategyResult,
) -> None:
    """Every fill, recomputed with a naive loop over the closes the run could see."""
    reader = demo_result.reader.at(demo_result.records()[-1].valuation_time)
    closes = reader.adjusted_history("FUND_A", end=demo_result.end)
    days: list[date] = [load_script().session_date(day) for day in closes.index]
    values = [float(value) for value in closes]
    held = False
    expected: list[tuple[date, str]] = []
    for index in range(4, len(days) - 1):
        ratio = values[index] / (sum(values[index - 4 : index + 1]) / 5)
        tomorrow = days[index + 1]
        if days[index] < demo_result.start:
            continue
        if ratio < DEMO_STRATEGY.sell_below and held:
            held = False
            expected.append((tomorrow, "SELL"))
        elif ratio > DEMO_STRATEGY.buy_above and not held:
            held = True
            expected.append((tomorrow, "BUY"))
    fills = demo_result.fills()
    assert list(zip(fills["session_date"], fills["side"], strict=True)) == expected


# --- the script --------------------------------------------------------------------------


def test_the_script_declares_the_strategy_of_the_exercise() -> None:
    script = load_script()
    strategy = script.STRATEGY
    assert strategy == MovingAverageBandETF(
        instrument_id="ETF_WORLD", window_sessions=50, sell_below=1.0, buy_above=1.0
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
    assert saved == ["drawdown.png", "equity.png", "moving_average_band.png"]
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
    assert (output / "moving_average_band.png").is_file()


# --- the figure of the levels ------------------------------------------------------------

FIVE_DAYS = [date(2026, 1, day) for day in (5, 6, 7, 8, 9)]
"""Five consecutive sessions, Monday to Friday."""


def closes_on(days: list[date], values: list[float]) -> pd.Series:  # type: ignore[type-arg]
    """Return closes indexed by session date, as the reader hands them over."""
    return pd.Series(values, index=pd.Index(days, name="observation_date"), name="adjusted_close")


def test_the_levels_are_multiples_of_the_plain_mean_of_the_last_closes() -> None:
    """Closes 10 to 50: MA2 is 15, 25, 35, 45, and the levels are half and twice it."""
    closes = closes_on(FIVE_DAYS, [10.0, 20.0, 30.0, 40.0, 50.0])
    frame = load_script().band_levels(closes, FIVE_DAYS, 2, 0.5, 2.0)
    assert list(frame.index) == FIVE_DAYS
    assert list(frame["close"]) == [10.0, 20.0, 30.0, 40.0, 50.0]
    assert list(frame["average"].iloc[1:]) == [15.0, 25.0, 35.0, 45.0]
    assert list(frame["sell_level"].iloc[1:]) == [7.5, 12.5, 17.5, 22.5]
    assert list(frame["buy_level"].iloc[1:]) == [30.0, 50.0, 70.0, 90.0]
    assert frame[["average", "buy_level", "sell_level"]].iloc[0].isna().all()


def test_a_level_is_not_drawn_over_a_missing_session() -> None:
    """Wednesday has no close: no window holding it has an average, as for the signal."""
    days = [day for day in FIVE_DAYS if day != date(2026, 1, 7)]
    closes = closes_on(days, [10.0, 20.0, 40.0, 50.0])
    frame = load_script().band_levels(closes, FIVE_DAYS, 2, 0.5, 2.0)
    for column in ("average", "buy_level", "sell_level"):
        assert list(frame[column].isna()) == [True, False, True, True, False]
    assert frame.loc[date(2026, 1, 9), "average"] == 45.0


def test_a_later_close_changes_no_earlier_level() -> None:
    """The look-ahead guard: Friday's close, whatever it is, moves nothing before Friday."""
    script = load_script()
    calm = script.band_levels(
        closes_on(FIVE_DAYS, [10.0, 20.0, 30.0, 40.0, 50.0]), FIVE_DAYS, 2, 0.5, 2.0
    )
    crash = script.band_levels(
        closes_on(FIVE_DAYS, [10.0, 20.0, 30.0, 40.0, 1.0]), FIVE_DAYS, 2, 0.5, 2.0
    )
    pd.testing.assert_frame_equal(calm.iloc[:4], crash.iloc[:4])
    assert calm.loc[FIVE_DAYS[4], "buy_level"] != crash.loc[FIVE_DAYS[4], "buy_level"]


def test_the_figure_shows_the_price_its_average_both_levels_and_the_trades() -> None:
    script = load_script()
    strategy = MovingAverageBandETF(window_sessions=2, sell_below=0.5, buy_above=2.0)
    frame = script.band_levels(
        closes_on(FIVE_DAYS, [10.0, 20.0, 30.0, 40.0, 50.0]), FIVE_DAYS, 2, 0.5, 2.0
    )
    fills = pd.DataFrame({"session_date": [FIVE_DAYS[2], FIVE_DAYS[4]], "side": ["BUY", "SELL"]})
    figure = script.band_figure(
        frame, {FIVE_DAYS[2], FIVE_DAYS[3]}, fills, strategy=strategy, title="a title"
    )
    axes = figure.axes[0]
    assert axes.get_title() == "a title"
    labels = axes.get_legend_handles_labels()[1]
    assert labels == [
        "invested",
        "close",
        "MA2",
        "buy above 200% of MA2",
        "sell below 50% of MA2",
        "buy",
        "sell",
    ]
    buys, sells = axes.collections[1], axes.collections[2]
    assert [point[1] for point in buys.get_offsets()] == [30.0]
    assert [point[1] for point in sells.get_offsets()] == [50.0]


def test_a_level_that_is_the_average_itself_is_not_drawn_twice() -> None:
    script = load_script()
    frame = script.band_levels(
        closes_on(FIVE_DAYS, [10.0, 20.0, 30.0, 40.0, 50.0]), FIVE_DAYS, 2, 1.0, 1.0
    )
    fills = pd.DataFrame({"session_date": [], "side": []})
    figure = script.band_figure(
        frame, set(), fills, strategy=MovingAverageBandETF(window_sessions=2), title="a line"
    )
    labels = figure.axes[0].get_legend_handles_labels()[1]
    assert labels == ["invested", "close", "MA2", "buy", "sell"]


def test_a_figure_of_no_session_is_refused() -> None:
    script = load_script()
    empty = script.band_levels(closes_on([], []), [], 2, 0.5, 2.0)
    fills = pd.DataFrame({"session_date": [], "side": []})
    with pytest.raises(ValueError, match="nothing to draw"):
        script.band_figure(empty, set(), fills, strategy=MovingAverageBandETF(), title="empty")
