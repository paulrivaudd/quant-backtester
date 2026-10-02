"""Exercice « Moving-Average Crossover » : les tests de GoldenCrossETF et du runner.

Chaque test commence par ``pytest.skip("Exercice MA …")``. Retirez cette ligne
quand la partie vérifiée est écrite, puis :

    uv run pytest tests/strategies/test_golden_cross_etf.py

Le marché est celui de ``tests/conftest.py`` : le calendrier XPAR synthétique
de 2026 et l'ETF ``ETF_EU``, coté depuis le 5 janvier 2026. Une série qui monte
d'un euro par séance a sa moyenne 50 au-dessus de sa moyenne 200 ; une série
qui baisse, au-dessous ; une série plate donne un signal exactement nul. Tout
se vérifie à la main, et rien ne touche au réseau.
"""

from __future__ import annotations

import dataclasses
import importlib.util
from collections.abc import Callable
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
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.engine import SignalEngine, SignalRequest
from quant_backtester.signals.price.trend import MovingAverageCrossSignal
from quant_backtester.signals.types import PriceBasis
from quant_backtester.strategies.base import Strategy
from quant_backtester.strategies.examples.golden_cross_etf import GoldenCrossETF

DECISION_DAY = date(2026, 11, 30)
"""A Monday with more than two hundred XPAR sessions of history behind it."""

DECISION = datetime.combine(DECISION_DAY, time(23, 0), tzinfo=ZoneInfo("Europe/Paris"))
"""After the Paris close of the decision day: its close is knowable."""

REPOSITORY = Path(__file__).resolve().parents[2]
"""The root of the checkout: the script and the committed metadata live there."""


def history(xpar: TradingCalendar, step: float, until: date = DECISION_DAY) -> dict[date, float]:
    """Return a close per XPAR session from 5 January 2026, moving by ``step`` a session."""
    days = [day.session_date for day in xpar.sessions(date(2026, 1, 5), until)]
    return {day: 500.0 + step * index for index, day in enumerate(days)}


def decide(
    strategy: GoldenCrossETF,
    market: MarketDataReader,
    make_context: Callable[[MarketDataReader, datetime], SignalContext],
    make_decision: Callable[..., StrategyContext],
    at: datetime = DECISION,
) -> TargetAllocation:
    """Compute the strategy's declared signals at ``at``, then let it decide."""
    context = make_context(market, at)
    requests = [
        item.resolved(at.date()) if isinstance(item, SignalRequest) else item
        for item in strategy.required_signals()
    ]
    snapshot = SignalEngine().compute(context, requests, ["ETF_EU"])
    return strategy.decide(make_decision(context, snapshot, universe=("ETF_EU",)))


def on_etf_eu() -> GoldenCrossETF:
    """Return the strategy on the synthetic market's Paris ETF."""
    return GoldenCrossETF(instrument_id="ETF_EU")


def load_script() -> ModuleType:
    """Import ``scripts/run_golden_cross_exercise.py`` by its path."""
    path = REPOSITORY / "scripts" / "run_golden_cross_exercise.py"
    spec = importlib.util.spec_from_file_location("run_golden_cross_exercise", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- 2.1 le signal -------------------------------------------------------------------


def test_2_1_the_signal_is_the_existing_cross_configured_as_asked() -> None:
    signal = GoldenCrossETF().signal()
    assert isinstance(signal, MovingAverageCrossSignal)
    assert signal.signal_id == "ma50_over_ma200"
    assert (signal.first_sessions, signal.second_sessions) == (50, 200)
    assert signal.price_basis is PriceBasis.ADJUSTED
    assert signal.bar_field is BarField.CLOSE


# --- 3.1 le contrat --------------------------------------------------------------------


def test_3_1_the_contract_of_the_class() -> None:
    strategy = GoldenCrossETF()
    assert isinstance(strategy, Strategy)
    assert strategy.instrument_id == "ETF_WORLD"
    assert (strategy.fast_sessions, strategy.slow_sessions) == (50, 200)
    assert strategy.strategy_id == "golden_cross_etf"
    with pytest.raises(dataclasses.FrozenInstanceError):
        strategy.fast_sessions = 20  # type: ignore[misc]


def test_3_1_the_signal_is_asked_for_the_studied_etf_only() -> None:
    strategy = GoldenCrossETF()
    declared = list(strategy.required_signals())
    assert len(declared) == 1
    request = declared[0]
    assert isinstance(request, SignalRequest)
    assert request.signal == strategy.signal()
    assert list(request.names() or ()) == ["ETF_WORLD"]


def test_3_1_the_parameters_enter_the_definition() -> None:
    assert GoldenCrossETF().fingerprint() != GoldenCrossETF(slow_sessions=150).fingerprint()


@pytest.mark.parametrize(
    "parameters",
    [{"instrument_id": ""}, {"fast_sessions": 200}, {"fast_sessions": 1}],
    ids=["empty-instrument", "equal-lengths", "too-short"],
)
def test_3_1_an_impossible_configuration_is_refused(parameters: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        GoldenCrossETF(**parameters)  # type: ignore[arg-type]


# --- 3.2 la décision ---------------------------------------------------------------------


def test_3_2_a_rising_etf_is_held_in_full(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    xpar: TradingCalendar,
    make_context: Callable[[MarketDataReader, datetime], SignalContext],
    make_decision: Callable[..., StrategyContext],
) -> None:
    market = make_market({"ETF_EU": make_bars("ETF_EU", xpar, history(xpar, +1.0))})
    allocation = decide(on_etf_eu(), market, make_context, make_decision)
    assert dict(allocation.weights) == {"ETF_EU": 1.0}


def test_3_2_a_falling_etf_is_not_held(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    xpar: TradingCalendar,
    make_context: Callable[[MarketDataReader, datetime], SignalContext],
    make_decision: Callable[..., StrategyContext],
) -> None:
    market = make_market({"ETF_EU": make_bars("ETF_EU", xpar, history(xpar, -1.0))})
    allocation = decide(on_etf_eu(), market, make_context, make_decision)
    assert dict(allocation.weights) == {}


def test_3_2_a_signal_of_exactly_zero_is_cash(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    xpar: TradingCalendar,
    make_context: Callable[[MarketDataReader, datetime], SignalContext],
    make_decision: Callable[..., StrategyContext],
) -> None:
    """Flat prices: both averages equal, the signal is 0, and 0 is not > 0."""
    market = make_market({"ETF_EU": make_bars("ETF_EU", xpar, history(xpar, 0.0))})
    allocation = decide(on_etf_eu(), market, make_context, make_decision)
    assert dict(allocation.weights) == {}


def test_3_2_too_short_a_history_is_cash_and_not_an_error(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    xpar: TradingCalendar,
    make_context: Callable[[MarketDataReader, datetime], SignalContext],
    make_decision: Callable[..., StrategyContext],
) -> None:
    """A rising series of fewer than 200 sessions: no MA200, so no position."""
    short = {day: price for day, price in history(xpar, +1.0).items() if day >= date(2026, 6, 1)}
    market = make_market({"ETF_EU": make_bars("ETF_EU", xpar, short)})
    allocation = decide(on_etf_eu(), market, make_context, make_decision)
    assert dict(allocation.weights) == {}


def test_3_2_a_price_after_the_decision_changes_nothing(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    xpar: TradingCalendar,
    make_context: Callable[[MarketDataReader, datetime], SignalContext],
    make_decision: Callable[..., StrategyContext],
) -> None:
    """The look-ahead guard: a crash the next day cannot move today's decision."""
    closes = history(xpar, +1.0, until=date(2026, 12, 1))
    before = make_market({"ETF_EU": make_bars("ETF_EU", xpar, closes)})
    first = decide(on_etf_eu(), before, make_context, make_decision)
    closes[date(2026, 12, 1)] = 1.0
    after = make_market({"ETF_EU": make_bars("ETF_EU", xpar, closes)})
    second = decide(on_etf_eu(), after, make_context, make_decision)
    assert dict(first.weights) == dict(second.weights) == {"ETF_EU": 1.0}


# --- 3.3 l'export ------------------------------------------------------------------------


def test_3_3_the_strategy_is_exported_by_the_package() -> None:
    """Once exported, add it to ``runnable`` in ``test_examples.py`` too."""
    import quant_backtester.strategies as strategies

    assert strategies.GoldenCrossETF is GoldenCrossETF  # type: ignore[attr-defined]


# --- 4 le runner -------------------------------------------------------------------------


def test_4_the_runner_declares_every_assumption_of_the_exercise() -> None:
    runner = load_script().build_runner(REPOSITORY / "market_data")
    assert runner.reference_calendar_id == "XPAR"
    assert runner.base_currency == "EUR"
    assert runner.initial_cash == 100_000.0
    costs = runner.execution.costs
    assert (costs.commission_rate, costs.minimum_commission) == (0.0005, 1.0)
    assert (costs.half_spread_rate, costs.slippage_rate) == (0.0002, 0.0001)
    assert runner.execution.minimum_trade_value == 500.0
    assert (runner.analytics.sessions_per_year, runner.analytics.risk_free_rate) == (255, 0.02)
    assert runner.benchmark is not None
    assert runner.benchmark.instrument_id == "ETF_WORLD"  # type: ignore[union-attr]


# --- 4.2 et 5 lancer, lire, dessiner -----------------------------------------------------

DEMO_SEED = 20240101
"""Seed of the synthetic market the script's output is tested on."""

DEMO_STRATEGY = GoldenCrossETF(instrument_id="FUND_A", fast_sessions=5, slow_sessions=20)
"""The strategy on the demo market: lengths its two years of history can serve."""

DEMO_PERIOD = ("2025-01-02", "2025-12-31")
"""The measured year of the demo market; 2024 is the warm-up."""


@pytest.fixture(scope="module")
def demo(tmp_path_factory: pytest.TempPathFactory) -> StrategyRunner:
    """Return a runner over the offline synthetic market."""
    return demo_runner(tmp_path_factory.mktemp("golden_cross") / "store", seed=DEMO_SEED)


@pytest.fixture(scope="module")
def demo_result(demo: StrategyRunner) -> StrategyResult:
    """Return one finished run of the strategy on the synthetic market."""
    return demo.run(DEMO_STRATEGY, ("FUND_A",), *DEMO_PERIOD)


def test_5_the_printout_identifies_the_run_and_shows_every_table(
    demo_result: StrategyResult, capsys: pytest.CaptureFixture[str]
) -> None:
    load_script().print_run(demo_result)
    printed = capsys.readouterr().out
    assert f"run_id       {demo_result.run_id}" in printed
    assert f"fingerprint  {demo_result.fingerprint}" in printed
    assert f"period       {demo_result.start} to {demo_result.end}" in printed
    assert demo_result.report().render() in printed
    assert demo_result.compare().render() in printed
    for table in ("orders", "fills", "rejects", "weights", "costs"):
        assert f"== {table}: {len(getattr(demo_result, table)())} rows ==" in printed


def test_5_a_long_table_is_cut_and_an_empty_one_says_so(
    demo_result: StrategyResult, capsys: pytest.CaptureFixture[str]
) -> None:
    """One row per session would bury the report; no row at all must not print a header."""
    script = load_script()
    assert len(demo_result.weights()) > script.TABLE_ROWS
    script.print_run(demo_result)
    printed = capsys.readouterr().out
    weights = printed.split("== weights:")[1].split("== costs:")[0]
    assert len(weights.splitlines()) < len(demo_result.weights())
    assert len(demo_result.rejects()) > 0 or "(none)" in printed


def test_5_the_two_figures_are_saved_and_the_directory_created(
    demo_result: StrategyResult, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import matplotlib.pyplot as plt

    def refuse() -> None:
        raise AssertionError("a script saves a figure, it does not show it")

    monkeypatch.setattr(plt, "show", refuse)
    directory = tmp_path / "not" / "there" / "yet"
    load_script().save_figures(demo_result, directory)
    assert sorted(path.name for path in directory.iterdir()) == ["drawdown.png", "equity.png"]
    for path in directory.iterdir():
        assert path.read_bytes().startswith(b"\x89PNG")


def test_4_2_main_runs_the_declared_strategy_prints_it_and_saves_its_figures(
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
    assert (output / "equity.png").is_file()
    assert (output / "drawdown.png").is_file()


def test_4_2_the_script_declares_the_strategy_of_the_exercise() -> None:
    script = load_script()
    strategy = script.STRATEGY
    assert strategy == GoldenCrossETF(
        instrument_id="ETF_WORLD", fast_sessions=50, slow_sessions=200
    )
    assert script.UNIVERSE == ("ETF_WORLD",)
    assert script.PERIOD == ("2019-04-01", "2026-09-17")
