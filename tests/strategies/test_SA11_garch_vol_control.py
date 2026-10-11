"""SA11 and its EWMA control: what they declare, decide, refuse and record.

Decisions are taken on forecasts of written value (see ``conftest.py``); the
fit itself is tested in ``tests/signals/models/test_garch.py``. Both books are
then run through the engine on the offline demo market, with a window short
enough for its two years.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping

import pytest

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.backtest.runner import StrategyRunner
from quant_backtester.demo import demo_runner
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.signals.engine import SignalRequest
from quant_backtester.signals.models import garch
from quant_backtester.signals.models.garch import (
    EwmaVolatilitySignal,
    GarchVolatilitySignal,
    MissingDependency,
)
from quant_backtester.signals.types import SignalStatus
from quant_backtester.strategies import EwmaVolControl, GarchVolControl, RealizedVolControl
from quant_backtester.strategies.adaptive.rebalance import RuleStrategy
from quant_backtester.strategies.adaptive.rules import MISSING_INPUT, forecast_volatility_rule
from quant_backtester.strategies.catalogue import entry, entry_of

WORLD = "ETF_EU"
"""The synthetic market's stand-in for the fund."""

UNIVERSE = (WORLD, "ETF_OTHER")
SA11 = GarchVolControl(instrument_id=WORLD)
CONTROL = EwmaVolControl(instrument_id=WORLD)
FORECAST = ("garch11_t_vol_756r", WORLD)
EWMA = ("ewma94_vol_756r", WORLD)

Written = Mapping[tuple[str, str], float | SignalStatus]
Decide = Callable[..., TargetAllocation]


@pytest.fixture
def decide(written_decision: Callable[..., StrategyContext]) -> Decide:
    """Return what a strategy decides on a written forecast, from a given book."""

    def run(
        strategy: RuleStrategy, values: Written, held: Mapping[str, float] | None = None
    ) -> TargetAllocation:
        return strategy.decide(written_decision(strategy, values, universe=UNIVERSE, held=held))

    return run


# --- what is declared --------------------------------------------------------------------


def test_the_defaults_are_the_frozen_configuration_of_the_specification() -> None:
    strategy = GarchVolControl()

    assert strategy.strategy_id == "SA11_garch_vol_control"
    assert strategy.instrument_id == "ETF_WORLD"
    assert strategy.estimation_returns == 756
    assert (strategy.target_volatility, strategy.volatility_floor) == (0.12, 0.05)
    assert strategy.rebalance_band == 0.03
    assert (strategy.ewma_decay, strategy.ewma_seed_returns) == (0.94, 60)
    assert (strategy.max_iterations, strategy.ftol) == (1000, 1e-8)
    start = (
        strategy.initial_omega_share,
        strategy.initial_alpha,
        strategy.initial_beta,
        strategy.initial_nu,
    )
    assert start == (0.05, 0.05, 0.90, 8.0)
    # The band, the target and the floor are those of SA6, its comparator.
    reference = RealizedVolControl()
    assert strategy.target_volatility == reference.target_volatility
    assert strategy.volatility_floor == reference.volatility_floor
    assert strategy.rebalance_band == reference.rebalance_band


def test_the_forecast_is_asked_for_the_fund_only_on_757_adjusted_closes() -> None:
    (request,) = GarchVolControl().required_signals()

    assert isinstance(request, SignalRequest)
    assert request.names() == ("ETF_WORLD",)
    signal = request.signal
    assert isinstance(signal, GarchVolatilitySignal)
    assert signal.signal_id == "garch11_t_vol_756r"
    assert signal.window_spec().observations == 757
    definition = signal.definition_json()
    assert definition["price_basis"] == "ADJUSTED"
    assert definition["window_mode"] == "CONSECUTIVE_SESSIONS"
    assert definition["max_age_sessions"] == 0
    config = definition["config"]
    assert isinstance(config, dict)
    assert config["annualization"] == 252
    assert config["constant_return_tolerance"] == 1e-12


def test_the_parameters_and_the_estimated_model_are_two_different_things() -> None:
    """The definition describes the algorithm; a day's estimate never enters it."""
    assert GarchVolControl().fingerprint() == GarchVolControl().fingerprint()
    assert GarchVolControl().fingerprint() != GarchVolControl(ewma_decay=0.97).fingerprint()
    assert GarchVolControl().fingerprint() != GarchVolControl(estimation_returns=504).fingerprint()
    assert set(GarchVolControl().parameters()) >= {"estimation_returns", "target_volatility"}


def test_sa11_is_in_the_catalogue_and_its_control_is_not() -> None:
    item = entry("SA11")

    assert item.display_name == "SA11 - GARCH vol control"
    assert item.strategy_id == GarchVolControl().strategy_id
    assert item.slug == "sa11_garch_vol_control"
    assert item.load() is GarchVolControl
    assert entry_of(SA11) is item
    with pytest.raises(KeyError, match="not in the catalogue"):
        entry_of(CONTROL)


def test_the_control_reads_another_signal_under_a_research_identifier() -> None:
    (request,) = EwmaVolControl().required_signals()

    assert isinstance(request, SignalRequest)
    assert isinstance(request.signal, EwmaVolatilitySignal)
    assert request.signal.signal_id == "ewma94_vol_756r"
    assert request.signal.signal_id != GarchVolControl().forecast_signal().signal_id
    assert EwmaVolControl().strategy_id == "research_ewma94_vol_control"
    assert not EwmaVolControl().strategy_id.startswith("SA")
    control, studied = EwmaVolControl(), GarchVolControl()
    assert (control.target_volatility, control.volatility_floor, control.rebalance_band) == (
        studied.target_volatility,
        studied.volatility_floor,
        studied.rebalance_band,
    )
    assert (control.window_returns, control.decay, control.seed_returns) == (
        studied.estimation_returns,
        studied.ewma_decay,
        studied.ewma_seed_returns,
    )


# --- the allocation ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("volatility", "weight"),
    [(0.08, 1.0), (0.12, 1.0), (0.20, 0.6), (0.30, 0.4), (0.40, 0.3), (0.0, 1.0), (0.03, 1.0)],
)
def test_the_exposure_is_the_target_over_the_forecast_and_never_above_one(
    decide: Decide, volatility: float, weight: float
) -> None:
    for strategy, key in ((SA11, FORECAST), (CONTROL, EWMA)):
        allocation = decide(strategy, {key: volatility})

        assert not allocation.hold_positions
        assert allocation.weights[WORLD] == pytest.approx(weight)
        assert 0.0 < allocation.weights[WORLD] <= 1.0
        assert sum(allocation.weights.values()) <= 1.0


def test_the_rule_is_a_pure_function_with_a_floor() -> None:
    rule = forecast_volatility_rule(WORLD, 0.24, target_volatility=0.12, floor=0.05)
    floored = forecast_volatility_rule(WORLD, 0.01, target_volatility=0.04, floor=0.05)
    missing = forecast_volatility_rule(WORLD, None, target_volatility=0.12, floor=0.05)

    assert dict(rule.weights) == {WORLD: 0.5}
    assert rule.diagnostics["volatility"] == 0.24
    assert dict(floored.weights) == {WORLD: pytest.approx(0.8)}
    assert floored.diagnostics["volatility"] == 0.05
    assert dict(missing.weights) == {} and missing.reason == MISSING_INPUT


def test_a_gap_under_three_points_keeps_the_book_and_three_points_sends_the_target(
    decide: Decide,
) -> None:
    """The gap is to the weight held, not to yesterday's target."""
    kept = decide(SA11, {FORECAST: 0.20}, {WORLD: 0.571})
    sent = decide(SA11, {FORECAST: 0.20}, {WORLD: 0.57})

    assert kept.hold_positions
    assert not sent.hold_positions
    assert sent.weights[WORLD] == pytest.approx(0.6)


def test_a_usable_forecast_counts_one_fund_read(decide: Decide) -> None:
    """A fallback is a usable value too: the signal is ``OK`` and the fund was read."""
    allocation = decide(SA11, {FORECAST: 0.20})

    assert allocation.considered == 1
    assert dict(allocation.skipped) == {}


@pytest.mark.parametrize(
    "status",
    [
        SignalStatus.INSUFFICIENT_HISTORY,
        SignalStatus.NON_CONSECUTIVE_HISTORY,
        SignalStatus.STALE_INPUT,
        SignalStatus.MISSING_INPUT,
        SignalStatus.INVALID_INPUT,
    ],
)
def test_without_a_usable_forecast_the_book_goes_to_cash_whatever_the_band_says(
    decide: Decide, status: SignalStatus
) -> None:
    for strategy, key in ((SA11, FORECAST), (CONTROL, EWMA)):
        allocation = decide(strategy, {key: status}, {WORLD: 0.6})

        assert not allocation.hold_positions
        assert dict(allocation.weights) == {}
        assert allocation.considered == 0
        assert dict(allocation.skipped) == {WORLD: status}


@pytest.mark.parametrize(
    "build",
    [
        lambda: GarchVolControl(instrument_id=""),
        lambda: GarchVolControl(target_volatility=0.0),
        lambda: GarchVolControl(volatility_floor=float("nan")),
        lambda: GarchVolControl(rebalance_band=1.5),
        lambda: GarchVolControl(estimation_returns=60),
        lambda: GarchVolControl(initial_alpha=0.5, initial_beta=0.5),
        lambda: GarchVolControl(ewma_decay=1.0),
        lambda: EwmaVolControl(decay=0.0),
        lambda: EwmaVolControl(window_returns=60),
        lambda: EwmaVolControl(strategy_id=" "),
    ],
)
def test_a_configuration_that_cannot_be_computed_is_refused(build: Callable[[], object]) -> None:
    with pytest.raises(ValueError):
        build()


def test_without_its_estimator_sa11_is_listed_and_refuses_to_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The catalogue shows it, the class builds, and a launch stops with the cause."""
    monkeypatch.setattr(garch.importlib.util, "find_spec", lambda name: None)

    strategy = entry("SA11").load()()

    assert strategy.strategy_id == "SA11_garch_vol_control"
    with pytest.raises(MissingDependency, match="stats extra"):
        strategy.validate()
    EwmaVolControl().validate()  # the control estimates nothing


# --- through the engine, on the offline demo market --------------------------------------

DEMO_PERIOD = ("2025-01-02", "2025-12-31")
"""The second year of the demo market: a year of closes sits before it."""


@pytest.fixture(scope="module")
def demo(tmp_path_factory: pytest.TempPathFactory) -> StrategyRunner:
    """Return a runner over the offline synthetic market."""
    return demo_runner(tmp_path_factory.mktemp("garch_vol_control") / "store", seed=20240101)


@pytest.mark.parametrize(
    "strategy",
    [
        GarchVolControl(
            instrument_id="FUND_A",
            estimation_returns=120,
            ewma_seed_returns=20,
            target_volatility=0.05,
        ),
        EwmaVolControl(
            instrument_id="FUND_A", window_returns=120, seed_returns=20, target_volatility=0.05
        ),
    ],
    ids=lambda strategy: strategy.strategy_id,
)
def test_a_run_trades_after_its_decisions_pays_its_costs_and_never_borrows(
    demo: StrategyRunner, strategy: RuleStrategy
) -> None:
    pytest.importorskip("arch")
    result = demo.run(strategy, ("FUND_A", "FUND_B"), *DEMO_PERIOD)

    targets, held = result.target_weights(), result.weights()
    assert len(result.fills()) >= 2
    assert (targets.to_numpy() >= 0.0).all()
    assert (targets.sum(axis=1) <= 1.0 + 1e-9).all()
    assert (held.sum(axis=1) <= 1.0 + 1e-9).all()
    assert set(result.fills()["instrument_id"]) == {"FUND_A"}
    # An order is filled at the open after the decision that sent it, never before.
    records = result.records()
    assert not records[0].fills
    for record in records:
        if record.fills:
            assert record.executed_decision is not None
            assert record.executed_decision < record.session_date
    # The gross book made the same trades and paid nothing for them.
    assert result.backtest.total_cost > 0.0
    assert result.backtest.net_return < result.backtest.gross_return
    assert math.isfinite(result.backtest.net_return)
    assert (result.frame()["cash"] >= 0.0).all()
