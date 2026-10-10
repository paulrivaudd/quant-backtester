"""SA13 and its control: the gate on the forecast, the sizing of SA6, the band, the book kept.

Decisions are taken on forecasts and volatilities of written value; the models
are tested in ``tests/ml/signatures`` and the signal in
``tests/signals/ml/test_signature_return_signal.py``. The strategy is then run
through the engine on a drawn market, with hand-written models, across months.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime

import numpy as np
import pandas as pd
import pytest

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.backtest.runner import StrategyRunner
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.ml.signatures.artifacts import (
    ModelCausalityError,
    ScheduleEntry,
    SignatureModelSchedule,
)
from quant_backtester.ml.signatures.config import SignatureVariant
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.signals.engine import SignalRequest
from quant_backtester.signals.ml.signature_return import SignatureReturnSignal
from quant_backtester.signals.models.garch import MissingDependency
from quant_backtester.signals.signatures import logsignature
from quant_backtester.signals.signatures.logsignature import FeatureKind
from quant_backtester.signals.types import SignalStatus
from quant_backtester.strategies.catalogue import entry, entry_of
from quant_backtester.strategies.examples.signatures_neurons import (
    STRATEGY_ID,
    SignaturesNeurons,
)

FUND, OTHER = "ETF_EU", "ETF_OTHER"
UNIVERSE = (FUND, OTHER)
FORECAST = "signature_return_test_logsig3"
SHORT, LONG = "volatility_20r", "volatility_60r"

Variants = Callable[..., SignatureVariant]
Schedules = Callable[..., SignatureModelSchedule]
Markets = Callable[..., MarketDataReader]
Decide = Callable[..., TargetAllocation]
Books = Callable[..., SignaturesNeurons]


@pytest.fixture
def book_of(signature_variant_of: Variants, signature_schedule_of: Schedules) -> Books:
    """Return SA13, or a variation of it, on a schedule of hand-written models."""

    def build(months: dict[str, float | str] | None = None, **changes: object) -> SignaturesNeurons:
        variant = signature_variant_of()
        schedule = signature_schedule_of(variant, months or {"2026-09": 0.1})
        return replace(SignaturesNeurons.from_schedule(schedule, variant), **changes)  # type: ignore[arg-type]

    return build


@pytest.fixture
def decide(written_decision: Callable[..., StrategyContext]) -> Decide:
    """Return what a book decides on a written forecast and written volatilities."""

    def run(
        strategy: SignaturesNeurons,
        mean: float | SignalStatus,
        short: float | SignalStatus = 0.20,
        long: float | SignalStatus = 0.15,
        held: float = 0.0,
    ) -> TargetAllocation:
        values = {(FORECAST, FUND): mean, (SHORT, FUND): short, (LONG, FUND): long}
        return strategy.decide(
            written_decision(
                strategy, values, universe=UNIVERSE, held={FUND: held} if held > 0.0 else None
            )
        )

    return run


def weight_of(allocation: TargetAllocation) -> float:
    """Return the fund's weight in a target that is not a hold; zero for cash."""
    assert not allocation.hold_positions
    return dict(allocation.weights).get(FUND, 0.0)


# --- what is declared ----------------------------------------------------------------------


def test_the_defaults_are_the_frozen_configuration_of_the_specification(book_of: Books) -> None:
    strategy = book_of()

    assert strategy.strategy_id == STRATEGY_ID == "SA13_signatures_neurons"
    assert strategy.direction_filter is True
    assert (strategy.entry_threshold, strategy.exit_threshold) == (0.002, 0.0)
    assert (strategy.short_returns, strategy.long_returns) == (20, 60)
    assert (strategy.target_volatility, strategy.volatility_floor) == (0.12, 0.05)
    assert strategy.rebalance_band == 0.03
    assert (strategy.instrument_id, strategy.variant_id) == (FUND, "test_logsig3")


def test_the_forecast_and_two_volatilities_are_asked_for_the_fund_only(book_of: Books) -> None:
    strategy = book_of()
    requests = strategy.required_signals()

    assert [
        request.signal.signal_id for request in requests if isinstance(request, SignalRequest)
    ] == [FORECAST, SHORT, LONG]
    assert all(
        isinstance(request, SignalRequest) and request.names() == (FUND,) for request in requests
    )
    forecast = strategy.forecast_signal()
    assert isinstance(forecast, SignatureReturnSignal)
    assert forecast.schedule_id == strategy.schedule_id
    assert forecast.features.kind is FeatureKind.LOGSIGNATURE


def test_sa13_is_catalogued_under_a_label_without_a_hyphen(book_of: Books) -> None:
    item = entry("SA13")

    assert item.display_name == "SA13 - Signatures Neurons"
    assert item.strategy_id == STRATEGY_ID
    assert item.load() is SignaturesNeurons and entry_of(book_of()) is item


def test_a_book_is_recorded_with_the_schedule_of_models_it_read(
    signature_variant_of: Variants, signature_schedule_of: Schedules
) -> None:
    """Two schedules are two runs: the models are part of what a result follows from."""
    variant = signature_variant_of()
    one = SignaturesNeurons.from_schedule(signature_schedule_of(variant, {"2026-09": 0.1}), variant)
    same = SignaturesNeurons.from_schedule(
        signature_schedule_of(variant, {"2026-09": 0.1}), variant
    )
    other = SignaturesNeurons.from_schedule(
        signature_schedule_of(variant, {"2026-09": 0.2}), variant
    )
    control = SignaturesNeurons.from_schedule(
        signature_schedule_of(variant, {"2026-09": 0.1}),
        variant,
        direction_filter=False,
        strategy_id="research_sa13_c0_no_filter",
    )

    assert one.fingerprint() == same.fingerprint() != other.fingerprint()
    assert one.schedule_id != other.schedule_id
    # C0 reads the very forecast SA13 reads, from the same models: only the decision differs.
    assert control.forecast_signal().fingerprint() == one.forecast_signal().fingerprint()
    assert control.fingerprint() != one.fingerprint()
    with pytest.raises(ValueError, match="belongs to"):
        SignaturesNeurons.from_schedule(
            signature_schedule_of(variant, {"2026-09": 0.1}), signature_variant_of("another")
        )


# --- decisions, from the book actually held ------------------------------------------------


def test_from_cash_the_book_enters_only_above_twenty_basis_points(
    decide: Decide, book_of: Books
) -> None:
    strategy = book_of()

    assert weight_of(decide(strategy, 0.0025)) == pytest.approx(0.6)  # 12% over 20%
    assert weight_of(decide(strategy, 0.0020)) == 0.0  # twenty exactly does not buy
    assert weight_of(decide(strategy, 0.0008)) == 0.0


def test_a_position_is_kept_while_the_forecast_is_positive_and_sold_at_zero(
    decide: Decide, book_of: Books
) -> None:
    strategy = book_of()

    assert decide(strategy, 0.0008, held=0.6).hold_positions  # at its target: nothing to trade
    assert weight_of(decide(strategy, 0.0, held=0.6)) == 0.0  # zero sells
    assert weight_of(decide(strategy, -0.0004, held=0.6)) == 0.0


def test_a_rejected_entry_does_not_switch_the_hysteresis_on(decide: Decide, book_of: Books) -> None:
    """The gate reads the position held, never the target asked for the day before."""
    assert weight_of(decide(book_of(), 0.0008, held=0.0)) == 0.0


def test_the_position_is_sized_on_the_larger_of_the_two_volatilities(
    decide: Decide, book_of: Books
) -> None:
    strategy = book_of()

    assert weight_of(decide(strategy, 0.0030, 0.15, 0.30)) == pytest.approx(0.4)
    assert weight_of(decide(strategy, 0.0030, 0.30, 0.15)) == pytest.approx(0.4)
    assert weight_of(decide(strategy, 0.0030, 0.02, 0.03)) == pytest.approx(1.0)  # no leverage
    # The mean opens the gate and never sizes: a forecast twenty times larger, the same weight.
    assert weight_of(decide(strategy, 0.0600, 0.15, 0.30)) == pytest.approx(0.4)


def test_the_band_is_three_points_and_an_entry_from_cash_passes_under_it(
    decide: Decide, book_of: Books
) -> None:
    strategy = book_of()

    assert decide(strategy, 0.0030, held=0.571).hold_positions
    assert weight_of(decide(strategy, 0.0030, held=0.57)) == pytest.approx(0.6)
    assert weight_of(decide(strategy, 0.0030, 6.0, 1.0)) == pytest.approx(0.02)  # under the band
    assert weight_of(decide(strategy, -0.0001, held=0.01)) == 0.0  # a small position sold whole


@pytest.mark.parametrize(
    "status",
    [
        SignalStatus.INSUFFICIENT_HISTORY,
        SignalStatus.NON_CONSECUTIVE_HISTORY,
        SignalStatus.STALE_INPUT,
        SignalStatus.INVALID_INPUT,
    ],
)
def test_an_unusable_forecast_or_volatility_is_cash_and_is_recorded(
    decide: Decide, book_of: Books, status: SignalStatus
) -> None:
    strategy = book_of()

    without_forecast = decide(strategy, status, held=0.6)
    without_volatility = decide(strategy, 0.0030, 0.20, status, held=0.6)

    for allocation in (without_forecast, without_volatility):
        assert weight_of(allocation) == 0.0
        assert allocation.considered == 0 and dict(allocation.skipped) == {FUND: status}


def test_a_usable_forecast_that_says_no_is_a_decision_not_a_hole(
    decide: Decide, book_of: Books
) -> None:
    allocation = decide(book_of(), 0.0008)

    assert weight_of(allocation) == 0.0
    assert allocation.considered == 1 and dict(allocation.skipped) == {}


def test_the_control_holds_whatever_the_mean_says_with_the_same_availability(
    decide: Decide, book_of: Books
) -> None:
    control = book_of(direction_filter=False, strategy_id="research_sa13_c0_no_filter")

    assert weight_of(decide(control, -0.0050)) == pytest.approx(0.6)
    assert decide(control, 0.0, held=0.6).hold_positions
    # Without a forecast - no window, or no model that month - the control is in cash too.
    assert weight_of(decide(control, SignalStatus.INSUFFICIENT_HISTORY, held=0.6)) == 0.0


@pytest.mark.parametrize(
    "changes",
    [
        {"instrument_id": ""},
        {"strategy_id": ""},
        {"entry_threshold": 0.0},
        {"exit_threshold": -0.001},
        {"exit_threshold": 0.003},
        {"target_volatility": 0.0},
        {"volatility_floor": 0.0},
        {"rebalance_band": 1.5},
        {"short_returns": 60},
        {"direction_filter": "yes"},
        {"schedule_id": "another"},
        {"instrument_id": OTHER},
    ],
)
def test_a_configuration_that_cannot_be_computed_is_refused(
    book_of: Books, changes: dict[str, object]
) -> None:
    with pytest.raises(ValueError):
        book_of(**changes)


def test_without_its_backend_sa13_is_listed_and_refuses_to_run(
    monkeypatch: pytest.MonkeyPatch,
    book_of: Books,
    signature_variant_of: Variants,
    signature_schedule_of: Schedules,
) -> None:
    monkeypatch.setattr(logsignature.importlib.util, "find_spec", lambda name: None)

    assert entry("SA13").load() is SignaturesNeurons
    with pytest.raises(MissingDependency, match="signatures extra"):
        book_of().validate()
    # A variant that reads no log-signature needs no log-signature backend.
    classical = signature_variant_of("test_classical", features=FeatureKind.CLASSICAL)
    SignaturesNeurons.from_schedule(
        signature_schedule_of(classical, {"2026-09": 0.1}), classical
    ).validate()


# --- through the engine, across months ------------------------------------------------------


@pytest.fixture
def runner(
    make_signature_market: Markets, make_neural_runner: Callable[..., StrategyRunner]
) -> StrategyRunner:
    """Return a runner over the drawn market of the signature tests."""
    pytest.importorskip("esig")
    pytest.importorskip("roughpy")
    return make_neural_runner(make_signature_market())


def test_the_book_is_continuous_when_the_model_changes(
    runner: StrategyRunner, book_of: Books
) -> None:
    """A new month is a new model, not a new portfolio: nothing is reset, nothing is traded."""
    always = book_of({"2026-08": 0.5, "2026-09": 0.6, "2026-10": 0.7})

    result = runner.run(always, UNIVERSE, "2026-08-03", "2026-10-30")

    frame, holdings, fills = result.frame(), result.holdings(), result.fills()
    assert len(frame) == 65  # every session of the three months is in the run
    assert frame["net_equity"].iloc[0] == 100_000.0
    # Decided on the evening of 3 August, bought at the open of the 4th.
    assert holdings.loc[date(2026, 8, 3), FUND] == 0.0
    assert fills["session_date"].iloc[0] == date(2026, 8, 4) and fills["side"].iloc[0] == "BUY"
    # The first decision of a month is filled at the open of its second session. On this
    # drawn market the band asks for nothing on those evenings, so neither that open nor
    # the one before trades: the units and the cash are those of the last evening of the
    # month before. The model changed; the book did not.
    for last, first, second in (
        (date(2026, 8, 31), date(2026, 9, 1), date(2026, 9, 2)),
        (date(2026, 9, 30), date(2026, 10, 1), date(2026, 10, 2)),
    ):
        assert holdings.loc[last, FUND] > 0.0
        for session in (first, second):
            assert frame.loc[session, "fills"] == 0
            assert holdings.loc[session, FUND] == holdings.loc[last, FUND]
            assert holdings.loc[session, "cash"] == holdings.loc[last, "cash"]
    # The capital is never put back to its start, and every cost paid stays paid.
    net = frame["net_equity"].to_numpy(dtype="float64")
    assert net[-1] != 100_000.0
    assert float(frame["total_cost"].to_numpy(dtype="float64").sum()) == pytest.approx(
        float(fills["total_cost"].to_numpy(dtype="float64").sum())
    )
    paid = pd.Series(frame["gross_equity"] - frame["net_equity"]).astype("float64")
    assert (np.diff(paid.to_numpy()) >= -1e-9).all() and float(paid.to_numpy()[-1]) > 0.0
    assert float(paid.loc[date(2026, 10, 1)]) >= float(paid.loc[date(2026, 8, 31)]) > 0.0


def test_a_month_without_a_model_is_spent_in_cash_and_stays_in_the_results(
    runner: StrategyRunner, book_of: Books
) -> None:
    months: dict[str, float | str] = {
        "2026-08": 0.5,
        "2026-09": "TRAINING_EXAMPLES:10<60",
        "2026-10": 0.5,
    }

    result = runner.run(book_of(months), UNIVERSE, "2026-08-03", "2026-10-30")
    control = runner.run(
        book_of(months, direction_filter=False, strategy_id="research_sa13_c0_no_filter"),
        UNIVERSE,
        "2026-08-03",
        "2026-10-30",
    )

    for run in (result, control):
        held = run.weights()[FUND]
        # No model on the evening of 1 September: sold at the open of the 2nd. A model
        # again on the evening of 1 October: bought at the open of the 2nd.
        out = held[(held.index >= date(2026, 9, 2)) & (held.index <= date(2026, 10, 1))]
        assert len(run.frame()) == 65 and len(out) == 22  # the month stays in the results
        assert (out == 0.0).all()
        before = held[held.index <= date(2026, 9, 1)].to_numpy(dtype="float64")
        after = held[held.index >= date(2026, 10, 2)].to_numpy(dtype="float64")
        assert before[1:].min() > 0.0 and after.min() > 0.0
        assert (run.frame()["cash"].to_numpy(dtype="float64") >= 0.0).all()
        decisions = run.frame()
        september = decisions[
            (decisions.index >= date(2026, 9, 1)) & (decisions.index <= date(2026, 9, 30))
        ]
        # A decision was taken every evening of the month; none had a forecast to consider.
        assert bool(september["decided"].to_numpy().all())
        assert (september["considered"].to_numpy() == 0).all()


def test_a_model_of_the_future_stops_the_run(
    runner: StrategyRunner,
    signature_variant_of: Variants,
    linear_artifact_of: Callable[..., object],
) -> None:
    variant = signature_variant_of()
    future = linear_artifact_of(variant, "2026-09", datetime(2026, 9, 20, 21, 0, tzinfo=UTC))
    schedule = SignatureModelSchedule(
        variant.variant_id,
        "Europe/Paris",
        (ScheduleEntry("2026-09", future),),  # type: ignore[arg-type]
    )

    with pytest.raises(ModelCausalityError, match="cannot be used"):
        runner.run(
            SignaturesNeurons.from_schedule(schedule, variant), UNIVERSE, "2026-09-01", "2026-09-30"
        )
