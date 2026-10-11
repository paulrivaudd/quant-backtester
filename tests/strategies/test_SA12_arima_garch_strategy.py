"""SA12 and its controls: the gate with hysteresis, the sizing, the band and the book held.

Decisions are taken on joint forecasts of written value; the fits are tested in
``tests/signals/models/test_arima_garch.py``. The strategy is then run through
the engine on the offline demo market, with a window short enough for it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

import pandas as pd
import pytest

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.backtest.runner import StrategyRunner
from quant_backtester.demo import demo_runner
from quant_backtester.portfolio.state import PortfolioState
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.signals.base import Signal, SignalResult, build_result_frame, result_row
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.engine import SignalEngine, SignalRequest
from quant_backtester.signals.models import arima_garch
from quant_backtester.signals.models.arima_garch import ArimaGarchForecastSignal
from quant_backtester.signals.models.garch import MissingDependency
from quant_backtester.signals.types import SignalStatus
from quant_backtester.signals.windows import LoadedWindow
from quant_backtester.strategies import ArimaGarch
from quant_backtester.strategies.adaptive.rules import (
    MISSING_INPUT,
    direction_gate,
    gated_volatility_rule,
)
from quant_backtester.strategies.catalogue import entry, entry_of

WORLD = "ETF_EU"
UNIVERSE = (WORLD, "ETF_OTHER")
SA12 = ArimaGarch(instrument_id=WORLD)
SIGNAL = "arima101_garch_mu2_756r"
BOOK_EQUITY, BOOK_PRICE = 10_000.0, 100.0


class WrittenJoint(Signal):
    """A joint forecast whose mean and volatility are written by the test."""

    def __init__(
        self, signal_id: str, written: tuple[float, float] | SignalStatus, *, with_volatility: bool
    ) -> None:
        self.signal_id = signal_id
        self._written = written
        self._with_volatility = with_volatility

    def definition(self) -> Mapping[str, object]:
        """Return what identifies this stand-in."""
        return {"type": "WrittenJoint", "signal_id": self.signal_id}

    def compute(self, context: SignalContext, instrument_ids: Sequence[str]) -> SignalResult:
        """Return the written forecast, or the written status, for each instrument."""
        rows: dict[str, Mapping[str, object]] = {}
        volatility: list[object] = []
        for instrument_id in instrument_ids:
            if isinstance(self._written, SignalStatus):
                rows[instrument_id] = result_row(None, LoadedWindow(status=self._written))
                volatility.append(None)
            else:
                window = LoadedWindow(status=SignalStatus.OK, points=(1.0,), age_sessions=0)
                rows[instrument_id] = result_row(self._written[0], window)
                volatility.append(self._written[1])
        frame = build_result_frame(rows)
        if self._with_volatility:
            frame["annualized_volatility"] = pd.Series(
                volatility, index=frame.index, dtype="object"
            )
        return SignalResult(self.signal_id, context.as_of, frame, self.definition())


Decide = Callable[..., TargetAllocation]


@pytest.fixture
def decide(
    context: SignalContext,
    make_decision: Callable[..., StrategyContext],
    make_book: Callable[..., PortfolioState],
) -> Decide:
    """Return what a strategy decides on a written joint forecast, from a given book."""

    def run(
        strategy: ArimaGarch,
        written: tuple[float, float] | SignalStatus,
        held: float = 0.0,
        *,
        with_volatility: bool = True,
    ) -> TargetAllocation:
        signal_id = strategy.forecast_signal().signal_id
        stand_in = WrittenJoint(signal_id, written, with_volatility=with_volatility)
        snapshot = SignalEngine().compute(
            context, [SignalRequest(stand_in, (strategy.instrument_id,))], list(UNIVERSE)
        )
        weights = {WORLD: held} if held > 0.0 else {}
        book = make_book(
            BOOK_EQUITY * (1.0 - held),
            {name: weight * BOOK_EQUITY / BOOK_PRICE for name, weight in weights.items()},
        )
        return strategy.decide(
            make_decision(
                context,
                snapshot,
                universe=UNIVERSE,
                holdings=book,
                prices=dict.fromkeys(weights, BOOK_PRICE),
            )
        )

    return run


def weight_of(allocation: TargetAllocation) -> float:
    """Return the fund's weight in a target that is not a hold; zero for cash."""
    assert not allocation.hold_positions
    return dict(allocation.weights).get(WORLD, 0.0)


# --- what is declared ----------------------------------------------------------------------


def test_the_defaults_are_the_frozen_configuration_of_the_specification() -> None:
    strategy = ArimaGarch()

    assert strategy.strategy_id == "SA12_arima_garch" and strategy.instrument_id == "ETF_WORLD"
    assert (strategy.estimation_returns, strategy.residual_burn) == (756, 60)
    assert (strategy.ar_order, strategy.ma_order) == (1, 1)
    assert (strategy.entry_threshold, strategy.exit_threshold) == (0.002, 0.0)
    assert (strategy.target_volatility, strategy.volatility_floor) == (0.12, 0.05)
    assert strategy.rebalance_band == 0.03
    assert (strategy.arima_max_iterations, strategy.arima_pgtol, strategy.arima_factr) == (
        1000,
        1e-8,
        1e7,
    )
    assert strategy.root_margin == 1e-6
    assert (strategy.ewma_decay, strategy.ewma_seed_returns) == (0.94, 60)
    config = strategy.forecast_config()
    assert config.arima.residuals == 696 == config.garch.estimation_returns
    assert config.annualization == 252


def test_one_joint_signal_is_asked_for_the_fund_on_757_adjusted_opens() -> None:
    (request,) = ArimaGarch().required_signals()

    assert isinstance(request, SignalRequest) and request.names() == ("ETF_WORLD",)
    signal = request.signal
    assert isinstance(signal, ArimaGarchForecastSignal)
    assert signal.signal_id == SIGNAL
    assert signal.window_spec().observations == 757
    assert signal.definition_json()["max_age_sessions"] == 0


def test_sa12_is_catalogued_under_a_label_without_a_hyphen() -> None:
    item = entry("SA12")

    assert item.display_name == "SA12 - ARIMA GARCH"
    assert item.strategy_id == ArimaGarch().strategy_id == "SA12_arima_garch"
    assert item.load() is ArimaGarch and entry_of(SA12) is item


def test_the_controls_are_the_same_rule_with_one_thing_changed() -> None:
    """D0 drops the filter, D1 the GARCH, D2 the ARMA dynamics: three other signals or rules."""
    no_filter = ArimaGarch(direction_filter=False, strategy_id="research_sa12_d0")
    ewma = ArimaGarch(volatility_model="EWMA", strategy_id="research_sa12_d1")
    constant = ArimaGarch(ar_order=0, ma_order=0, strategy_id="research_sa12_d2")

    # D0 reads the very forecast SA12 reads: only the decision differs.
    assert no_filter.forecast_signal() == ArimaGarch().forecast_signal()
    assert no_filter.fingerprint() != ArimaGarch().fingerprint()
    assert ewma.forecast_signal().signal_id == "arima101_ewma_mu2_756r"
    assert constant.forecast_signal().signal_id == "arima000_garch_mu2_756r"
    assert len({book.forecast_signal().fingerprint() for book in (SA12, ewma, constant)}) == 3
    # A control carries a research identifier, never a catalogue code of its own.
    assert all(book.strategy_id.startswith("research_") for book in (no_filter, ewma, constant))


# --- the gate and the sizing ---------------------------------------------------------------


def test_the_gate_enters_above_its_threshold_and_holds_above_zero() -> None:
    thresholds = {"entry_threshold": 0.002, "exit_threshold": 0.0}

    assert direction_gate(0.003, held=False, **thresholds)
    assert not direction_gate(0.0008, held=False, **thresholds)
    assert not direction_gate(0.002, held=False, **thresholds)  # equality does not buy
    assert direction_gate(0.0008, held=True, **thresholds)
    assert not direction_gate(0.0, held=True, **thresholds)  # equality sells
    assert not direction_gate(-0.0002, held=True, **thresholds)


@pytest.mark.parametrize(
    ("held", "mean", "volatility", "weight"),
    [
        (0.0, 0.0030, 0.20, 0.60),
        (0.0, 0.0008, 0.20, 0.00),
        (0.0, 0.0020, 0.20, 0.00),
        (0.6, 0.0008, 0.20, 0.60),
        (0.6, 0.0000, 0.20, 0.00),
        (0.6, -0.0002, 0.20, 0.00),
        (0.0, 0.0030, 0.40, 0.30),
        (0.0, 0.0030, 0.04, 1.00),
    ],
)
def test_the_table_of_the_specification(
    held: float, mean: float, volatility: float, weight: float
) -> None:
    target = gated_volatility_rule(
        WORLD,
        mean,
        volatility,
        held=held > 0.0,
        entry_threshold=0.002,
        exit_threshold=0.0,
        target_volatility=0.12,
        floor=0.05,
        gated=True,
    )

    assert dict(target.weights).get(WORLD, 0.0) == pytest.approx(weight)
    assert sum(target.weights.values()) <= 1.0


def test_the_mean_never_sizes_the_position_and_the_control_ignores_it() -> None:
    settings = {
        "entry_threshold": 0.002,
        "exit_threshold": 0.0,
        "target_volatility": 0.12,
        "floor": 0.05,
    }
    small = gated_volatility_rule(WORLD, 0.0021, 0.20, held=False, gated=True, **settings)
    large = gated_volatility_rule(WORLD, 0.0500, 0.20, held=False, gated=True, **settings)
    ungated = gated_volatility_rule(WORLD, -0.01, 0.20, held=False, gated=False, **settings)
    missing = gated_volatility_rule(WORLD, None, 0.20, held=True, gated=False, **settings)

    assert dict(small.weights) == dict(large.weights) == {WORLD: pytest.approx(0.6)}
    assert dict(ungated.weights) == {WORLD: pytest.approx(0.6)}  # D0: same risk, no filter
    assert ungated.diagnostics["gate"] == 0.0  # and it still records what the gate said
    assert dict(missing.weights) == {} and missing.reason == MISSING_INPUT


# --- decisions, from the book actually held ------------------------------------------------


def test_from_cash_the_book_enters_only_above_twenty_basis_points(decide: Decide) -> None:
    assert weight_of(decide(SA12, (0.0030, 0.20))) == pytest.approx(0.6)
    assert weight_of(decide(SA12, (0.0008, 0.20))) == 0.0
    assert weight_of(decide(SA12, (0.0020, 0.20))) == 0.0


def test_a_position_is_kept_while_the_forecast_is_positive_and_sold_at_zero(
    decide: Decide,
) -> None:
    kept = decide(SA12, (0.0008, 0.20), held=0.6)
    sold = decide(SA12, (0.0, 0.20), held=0.6)

    assert kept.hold_positions  # at its target: nothing to trade
    assert weight_of(sold) == 0.0


def test_a_rejected_purchase_leaves_the_book_in_cash_for_the_next_decision(
    decide: Decide,
) -> None:
    """The gate reads the position held, never the target asked for the day before."""
    after_a_rejected_entry = decide(SA12, (0.0008, 0.20), held=0.0)

    assert weight_of(after_a_rejected_entry) == 0.0


def test_the_band_is_three_points_and_an_entry_from_cash_passes_under_it(decide: Decide) -> None:
    inside = decide(SA12, (0.0030, 0.20), held=0.571)
    at_the_band = decide(SA12, (0.0030, 0.20), held=0.57)
    small_entry = decide(SA12, (0.0030, 6.0))  # a target of 2%, under the band

    assert inside.hold_positions
    assert weight_of(at_the_band) == pytest.approx(0.6)
    assert weight_of(small_entry) == pytest.approx(0.02)


def test_a_small_position_is_still_sold_whole(decide: Decide) -> None:
    assert weight_of(decide(SA12, (-0.0001, 0.20), held=0.01)) == 0.0


@pytest.mark.parametrize(
    "status",
    [
        SignalStatus.INSUFFICIENT_HISTORY,
        SignalStatus.NON_CONSECUTIVE_HISTORY,
        SignalStatus.STALE_INPUT,
        SignalStatus.INVALID_INPUT,
    ],
)
def test_an_unusable_forecast_is_cash_and_is_recorded_as_such(
    decide: Decide, status: SignalStatus
) -> None:
    allocation = decide(SA12, status, held=0.6)

    assert weight_of(allocation) == 0.0
    assert allocation.considered == 0 and dict(allocation.skipped) == {WORLD: status}


def test_a_usable_forecast_that_says_no_is_a_decision_not_a_hole(decide: Decide) -> None:
    allocation = decide(SA12, (0.0008, 0.20))

    assert weight_of(allocation) == 0.0
    assert allocation.considered == 1 and dict(allocation.skipped) == {}


def test_the_control_without_filter_holds_whatever_the_mean_says(decide: Decide) -> None:
    control = ArimaGarch(
        instrument_id=WORLD, direction_filter=False, strategy_id="research_sa12_d0"
    )

    assert weight_of(decide(control, (-0.0050, 0.20))) == pytest.approx(0.6)
    assert weight_of(decide(control, SignalStatus.INVALID_INPUT, held=0.6)) == 0.0


def test_a_forecast_without_its_volatility_stops_the_run(decide: Decide) -> None:
    with pytest.raises(KeyError, match="annualized_volatility"):
        decide(SA12, (0.0030, 0.20), with_volatility=False)


@pytest.mark.parametrize(
    "build",
    [
        lambda: ArimaGarch(instrument_id=""),
        lambda: ArimaGarch(entry_threshold=0.0),
        lambda: ArimaGarch(exit_threshold=-0.001),
        lambda: ArimaGarch(exit_threshold=0.003),
        lambda: ArimaGarch(target_volatility=0.0),
        lambda: ArimaGarch(rebalance_band=1.5),
        lambda: ArimaGarch(residual_burn=756),
        lambda: ArimaGarch(ar_order=2),
        lambda: ArimaGarch(volatility_model="ARCH"),
        lambda: ArimaGarch(direction_filter="yes"),  # type: ignore[arg-type]
        lambda: ArimaGarch(ewma_seed_returns=696),
    ],
)
def test_a_configuration_that_cannot_be_computed_is_refused(build: Callable[[], object]) -> None:
    with pytest.raises(ValueError):
        build()


def test_without_its_estimators_sa12_is_listed_and_refuses_to_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(arima_garch.importlib.util, "find_spec", lambda name: None)

    strategy = entry("SA12").load()()

    assert strategy.strategy_id == "SA12_arima_garch"
    with pytest.raises(MissingDependency, match="stats extra"):
        strategy.validate()


# --- through the engine, on the offline demo market ----------------------------------------


@pytest.fixture(scope="module")
def demo(tmp_path_factory: pytest.TempPathFactory) -> StrategyRunner:
    """Return a runner over the offline synthetic market."""
    return demo_runner(tmp_path_factory.mktemp("arima_garch") / "store", seed=20240101)


def short(**overrides: object) -> ArimaGarch:
    """Return SA12 on a window the demo market can serve, entering on any positive mean."""
    parameters: dict[str, object] = {
        "instrument_id": "FUND_A",
        "estimation_returns": 120,
        "residual_burn": 20,
        "ewma_seed_returns": 20,
        "entry_threshold": 1e-6,
        "target_volatility": 0.05,
    }
    parameters.update(overrides)
    return ArimaGarch(**parameters)  # type: ignore[arg-type]


def test_a_run_trades_after_its_decisions_never_borrows_and_holds_cash_on_a_no(
    demo: StrategyRunner,
) -> None:
    pytest.importorskip("statsmodels")
    pytest.importorskip("arch")
    result = demo.run(short(), ("FUND_A", "FUND_B"), "2025-09-01", "2025-12-31")
    control = demo.run(
        short(direction_filter=False, strategy_id="research_sa12_d0"),
        ("FUND_A", "FUND_B"),
        "2025-09-01",
        "2025-12-31",
    )

    held = result.weights().sum(axis=1)
    assert (held <= 1.0 + 1e-9).all() and (result.frame()["cash"] >= 0.0).all()
    assert not result.records()[0].fills
    for record in result.records():
        if record.fills:
            assert record.executed_decision is not None
            assert record.executed_decision < record.session_date
    # The control is never out on a usable forecast; the strategy stands aside
    # when the mean says no, and those days stay in its performance.
    assert float(control.weights().sum(axis=1).iloc[1:].min()) > 0.0
    assert float(held.mean()) <= float(control.weights().sum(axis=1).mean()) + 1e-9
    assert len(result.equity()) == len(control.equity())
