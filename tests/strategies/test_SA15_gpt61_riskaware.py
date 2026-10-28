"""Risk-aware families on explicit evening values and point-in-time prices."""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping
from dataclasses import FrozenInstanceError
from datetime import date

import pytest

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.data.instruments import AssetType, DataType, Instrument, InstrumentRegistry
from quant_backtester.signals.engine import SignalEngine, SignalRequest
from quant_backtester.signals.types import SignalStatus
from quant_backtester.strategies.SA15_gpt61_riskaware import RiskAwarePlan, SA15RiskAwareRotation

CORE, FIRST, SECOND, MONEY = "ETF_EU", "ETF_OTHER", "RISK_THIRD", "RISK_MONEY"
UNIVERSE = (CORE, FIRST, SECOND, MONEY)
Written = dict[tuple[str, str], float | SignalStatus]


@pytest.fixture
def instruments(instruments: InstrumentRegistry) -> InstrumentRegistry:
    """Add two fixed-currency Paris funds to the shared offline registry."""
    return InstrumentRegistry(
        [
            *instruments,
            *(
                Instrument(
                    id=name,
                    name=name,
                    asset_type=AssetType.ETF,
                    data_type=DataType.BAR,
                    currency="EUR",
                    primary_source="YAHOO",
                    source_symbol=f"{name}.PA",
                    tradable=True,
                    calendar_id="XPAR",
                    first_session=date(2026, 1, 5),
                )
                for name in (SECOND, MONEY)
            ),
        ]
    )


def strategy(**changes: object) -> SA15RiskAwareRotation:
    """Use test identifiers and preserve all other explicit prototype defaults."""
    defaults = {
        "core_id": CORE,
        "risky_ids": (CORE, FIRST, SECOND),
        "defensive_ids": (FIRST, SECOND),
        "monetary_id": MONEY,
    }
    return SA15RiskAwareRotation(**(defaults | changes))  # type: ignore[arg-type]


def values(allocation: SA15RiskAwareRotation, changes: Mapping | None = None) -> Written:
    """Write rising prices with a stronger core and unequal standalone risks."""
    returns = {CORE: 0.15, FIRST: 0.10, SECOND: 0.04, MONEY: 0.001}
    volatilities = {CORE: 0.20, FIRST: 0.10, SECOND: 0.30}
    written: Written = {}
    for request in allocation.required_signals():
        assert isinstance(request, SignalRequest)
        for name in request.names() or ():
            value = returns[name]
            if "volatility" in request.signal.signal_id:
                value = volatilities[name]
            elif "price_over" in request.signal.signal_id:
                value = 0.05
            written[request.signal.signal_id, name] = value
    assert not set(changes or {}) - set(written)
    return written | dict(changes or {})


def momentum(allocation: SA15RiskAwareRotation, name: str, value: float | SignalStatus) -> Written:
    """Set every positive-weight scoring endpoint for one name."""
    return {
        (allocation.momentum_signal(window).signal_id, name): value
        for window, weight in zip(
            allocation.momentum_lookbacks, allocation.momentum_weights, strict=True
        )
        if weight > 0
    }


@pytest.fixture
def decision(written_decision: Callable[..., StrategyContext]) -> Callable[..., StrategyContext]:
    """Build actual held positions and real snapshots from written signal values."""

    def build(
        allocation: SA15RiskAwareRotation,
        changes: Mapping | None = None,
        held: Mapping[str, float] | None = None,
    ) -> StrategyContext:
        return written_decision(
            allocation, values(allocation, changes), universe=UNIVERSE, held=held
        )

    return build


def test_definition_records_separate_identity_all_parameters_and_unique_requests() -> None:
    allocation = SA15RiskAwareRotation()
    assert allocation.strategy_id == "SA15_GPT-6.1_R4"
    assert allocation.target_volatility == 0
    assert allocation.fixed_weights == ()
    requests = allocation.required_signals()
    assert len({item.signal.signal_id for item in requests}) == len(requests)
    assert not any("volatility" in item.signal.signal_id for item in requests)
    assert not any("price_over" in item.signal.signal_id for item in requests)
    json.dumps(allocation.definition())


def test_rotation_holds_strong_core_without_permanent_cash_or_defence(decision) -> None:
    allocation = strategy()
    context = decision(allocation)
    plan = allocation.plan(context)
    assert plan.selected == (CORE,)
    assert dict(plan.weights) == {CORE: 1}
    assert plan.scores[CORE] == pytest.approx(math.log1p(0.15))
    assert dict(allocation.decide(context).weights) == {CORE: 1}


def test_core_bonus_and_actual_incumbent_bonus_require_material_advantage(decision) -> None:
    allocation = strategy(core_preference=0.02, switch_buffer=0.03)
    changes = momentum(allocation, FIRST, 0.18)
    assert allocation.plan(decision(allocation, changes)).selected == (FIRST,)
    assert allocation.plan(decision(allocation, changes, {CORE: 0.995})).selected == (CORE,)
    changes = momentum(allocation, FIRST, 0.30)
    assert allocation.plan(decision(allocation, changes, {CORE: 0.995})).selected == (FIRST,)


def test_absolute_eligibility_is_applied_before_ranking_bonus(decision) -> None:
    allocation = strategy(core_preference=10, switch_buffer=10)
    changes = momentum(allocation, CORE, -0.01)
    assert allocation.plan(decision(allocation, changes, {CORE: 0.99})).selected == (FIRST,)
    disabled = strategy(core_preference=10, absolute_filter=False)
    assert disabled.plan(decision(disabled, momentum(disabled, CORE, -0.01))).selected == (CORE,)


def test_missing_risky_input_excludes_individual_name_but_preserves_others(decision) -> None:
    allocation = strategy()
    changes = momentum(allocation, CORE, SignalStatus.MISSING_INPUT)
    plan = allocation.plan(decision(allocation, changes))
    assert plan.selected == (FIRST,)
    assert dict(plan.weights) == {FIRST: 1}
    assert plan.skipped[CORE] is SignalStatus.MISSING_INPUT


def test_core_floor_is_reserved_and_total_offensive_names_do_not_exceed_three(decision) -> None:
    allocation = strategy(core_floor=0.4, top_k=2)
    changes = momentum(allocation, FIRST, 0.30) | momentum(allocation, SECOND, 0.25)
    plan = allocation.plan(decision(allocation, changes))
    assert dict(plan.weights) == pytest.approx({CORE: 0.4, FIRST: 0.3, SECOND: 0.3})
    assert math.fsum(plan.weights.values()) == 1


def test_equal_balanced_ignores_negative_momentum_and_long_scoring_windows(decision) -> None:
    allocation = strategy(mode="balanced", risky_ids=(CORE, FIRST), defensive_ids=())
    names = {item.signal.signal_id for item in allocation.required_signals()}
    assert allocation.momentum_signal(126).signal_id not in names
    changes = {(allocation.momentum_signal(1).signal_id, CORE): -0.20}
    plan = allocation.plan(decision(allocation, changes))
    assert dict(plan.weights) == {CORE: 0.5, FIRST: 0.5}
    assert dict(plan.scores) == {}


def test_balanced_fixed_explicit_weights_and_missing_name_renormalization(decision) -> None:
    allocation = strategy(
        mode="balanced",
        allocation_mode="fixed",
        risky_ids=(CORE, FIRST, SECOND),
        fixed_weights=(0.7, 0.2, 0.1),
        defensive_ids=(),
    )
    assert dict(allocation.plan(decision(allocation)).weights) == {
        CORE: 0.7,
        FIRST: 0.2,
        SECOND: 0.1,
    }
    missing = {(allocation.momentum_signal(1).signal_id, FIRST): SignalStatus.STALE_INPUT}
    plan = allocation.plan(decision(allocation, missing))
    assert dict(plan.weights) == pytest.approx({CORE: 0.875, SECOND: 0.125})
    assert plan.skipped[FIRST] is SignalStatus.STALE_INPUT


def test_balanced_zero_fixed_weights_are_never_selected(decision) -> None:
    allocation = strategy(
        mode="balanced",
        allocation_mode="fixed",
        risky_ids=(CORE, FIRST),
        fixed_weights=(1.0, 0.0),
        defensive_ids=(),
    )
    assert allocation.plan(decision(allocation)).selected == (CORE,)
    missing = {(allocation.momentum_signal(1).signal_id, CORE): SignalStatus.MISSING_INPUT}
    assert dict(allocation.plan(decision(allocation, missing)).weights) == {MONEY: 1}


def test_inverse_volatility_balanced_normalizes_individual_risks_without_leverage(decision) -> None:
    allocation = strategy(
        mode="balanced", allocation_mode="inverse_vol", risky_ids=(CORE, FIRST), defensive_ids=()
    )
    plan = allocation.plan(decision(allocation))
    assert dict(plan.weights) == pytest.approx({CORE: 1 / 3, FIRST: 2 / 3})
    assert plan.offensive_volatility == pytest.approx(0.2 / 3 + 0.1 * 2 / 3)
    assert plan.risk_scale == 1


def test_missing_required_volatility_drops_only_the_affected_offensive_name(decision) -> None:
    allocation = strategy(
        mode="balanced", allocation_mode="inverse_vol", risky_ids=(CORE, FIRST), defensive_ids=()
    )
    changes = {
        (allocation.volatility_signal(20).signal_id, CORE): SignalStatus.NON_CONSECUTIVE_HISTORY
    }
    plan = allocation.plan(decision(allocation, changes))
    assert dict(plan.weights) == {FIRST: 1}
    assert plan.skipped[CORE] is SignalStatus.NON_CONSECUTIVE_HISTORY


def test_bounded_offensive_risk_scales_after_allocating_and_uses_positive_defence(decision) -> None:
    allocation = strategy(
        mode="balanced", risky_ids=(CORE, FIRST), target_volatility=0.075, defensive_ids=(SECOND,)
    )
    plan = allocation.plan(decision(allocation))
    assert plan.offensive_volatility == pytest.approx(0.15)
    assert plan.risk_scale == pytest.approx(0.5)
    assert dict(plan.offensive_weights) == pytest.approx({CORE: 0.25, FIRST: 0.25})
    assert dict(plan.weights) == pytest.approx({CORE: 0.25, FIRST: 0.25, SECOND: 0.5})


def test_vol_control_is_capped_at_one_and_never_increases_exposure_with_low_vol(decision) -> None:
    allocation = strategy(mode="vol_control", target_volatility=0.4, defensive_ids=())
    assert dict(allocation.plan(decision(allocation)).weights) == {CORE: 1}
    smaller = strategy(mode="vol_control", target_volatility=0.1, defensive_ids=())
    assert dict(smaller.plan(decision(smaller)).weights) == {CORE: 0.5, MONEY: 0.5}


def test_zero_volatility_is_floored_instead_of_producing_division_by_zero(decision) -> None:
    allocation = strategy(
        mode="vol_control", target_volatility=0.02, volatility_floor=0.05, defensive_ids=()
    )
    changes = {
        (allocation.volatility_signal(window).signal_id, CORE): 0
        for window in allocation.volatility_windows
    }
    plan = allocation.plan(decision(allocation, changes))
    assert plan.risk_scale == pytest.approx(0.4)
    assert dict(plan.weights) == pytest.approx({CORE: 0.4, MONEY: 0.6})


def test_ensemble_fraction_uses_weighted_positive_votes_strictly_above_zero(decision) -> None:
    allocation = strategy(
        mode="ensemble", momentum_weights=(1.0, 2.0, 1.0), core_floor=0.2, defensive_ids=()
    )
    changes = {
        (allocation.momentum_signal(21).signal_id, CORE): 0.01,
        (allocation.momentum_signal(63).signal_id, CORE): 0,
        (allocation.momentum_signal(126).signal_id, CORE): -0.1,
    }
    plan = allocation.plan(decision(allocation, changes))
    assert plan.trend_fraction == 0.25
    assert dict(plan.weights) == pytest.approx({CORE: 0.4, MONEY: 0.6})


def test_ma_ensemble_uses_exact_ma_distances_without_core_momentum_requests(decision) -> None:
    allocation = strategy(mode="ensemble", trend_kind="moving_average", defensive_ids=())
    names = {item.signal.signal_id for item in allocation.required_signals()}
    assert allocation.momentum_signal(63).signal_id not in names
    changes = {(allocation.trend_signal(63).signal_id, CORE): -0.01}
    plan = allocation.plan(decision(allocation, changes))
    assert plan.trend_fraction == pytest.approx(2 / 3)
    assert dict(plan.weights) == pytest.approx({CORE: 2 / 3, MONEY: 1 / 3})


def test_missing_mandatory_ensemble_vote_does_not_force_floor_or_discard_defence(decision) -> None:
    allocation = strategy(mode="ensemble", core_floor=0.5)
    missing = {(allocation.momentum_signal(63).signal_id, CORE): SignalStatus.STALE_INPUT}
    plan = allocation.plan(decision(allocation, missing))
    assert dict(plan.offensive_weights) == {}
    assert dict(plan.weights) == {FIRST: 1}
    assert plan.skipped[CORE] is SignalStatus.STALE_INPUT


def test_short_recovery_restores_direction_but_cannot_bypass_the_offensive_risk_cap(
    decision,
) -> None:
    allocation = strategy(
        mode="ensemble", recovery_lookback=5, target_volatility=0.1, defensive_ids=()
    )
    changes = momentum(allocation, CORE, -0.1)
    changes[allocation.momentum_signal(5).signal_id, CORE] = 0.01
    plan = allocation.plan(decision(allocation, changes))
    assert plan.recovery and plan.trend_fraction == 1
    assert plan.risk_scale == 0.5
    assert dict(plan.weights) == {CORE: 0.5, MONEY: 0.5}


def test_canary_breadth_counts_missing_as_negative_and_threshold_is_inclusive(decision) -> None:
    allocation = strategy(
        mode="ensemble", canary_ids=(FIRST, SECOND), canary_min_breadth=0.5, defensive_ids=()
    )
    changes = {
        (allocation.momentum_signal(window).signal_id, SECOND): SignalStatus.MISSING_INPUT
        for window in allocation.canary_lookbacks
    }
    plan = allocation.plan(decision(allocation, changes))
    assert plan.canary_breadth == 0.5
    assert dict(plan.weights) == {CORE: 1}
    stricter = strategy(
        mode="ensemble", canary_ids=(FIRST, SECOND), canary_min_breadth=1.0, defensive_ids=()
    )
    plan = stricter.plan(decision(stricter, changes))
    assert dict(plan.weights) == {MONEY: 1}


def test_canary_gate_preserves_configured_floor_and_recovery_cannot_bypass_it(decision) -> None:
    allocation = strategy(
        mode="ensemble", canary_ids=(FIRST,), core_floor=0.25, recovery_lookback=5, defensive_ids=()
    )
    changes = momentum(allocation, FIRST, -0.05)
    changes[allocation.momentum_signal(5).signal_id, CORE] = 0.01
    plan = allocation.plan(decision(allocation, changes))
    assert plan.recovery and plan.canary_breadth == 0
    assert dict(plan.weights) == {CORE: 0.25, MONEY: 0.75}


@pytest.mark.parametrize("carry, expected", [(0.0, {}), (-0.001, {}), (0.001, {MONEY: 1.0})])
def test_no_positive_defence_uses_only_strictly_positive_monetary_carry(
    decision, carry, expected
) -> None:
    allocation = strategy(mode="ensemble", defensive_ids=(FIRST,))
    changes = momentum(allocation, CORE, -0.1) | momentum(allocation, FIRST, -0.1)
    changes[allocation.momentum_signal(allocation.monetary_lookback).signal_id, MONEY] = carry
    assert dict(allocation.plan(decision(allocation, changes)).weights) == expected


def test_small_drift_holds_positions_and_complete_exit_overrides_the_band(decision) -> None:
    allocation = strategy(
        mode="balanced", risky_ids=(CORE, FIRST), defensive_ids=(), rebalance_band=0.1
    )
    context = decision(allocation, held={CORE: 0.55, FIRST: 0.45})
    assert allocation.decide(context).hold_positions
    rotation = strategy(rebalance_band=1.0)
    context = decision(rotation, held={CORE: 0.99, FIRST: 0.01})
    assert not rotation.decide(context).hold_positions
    assert dict(rotation.decide(context).weights) == {CORE: 1}


def test_configuration_input_lists_and_plan_mappings_are_immutable(decision) -> None:
    risky = [CORE, FIRST]
    allocation = strategy(mode="balanced", risky_ids=risky, defensive_ids=())
    fingerprint = allocation.fingerprint()
    risky.clear()
    assert allocation.fingerprint() == fingerprint
    with pytest.raises(FrozenInstanceError):
        allocation.mode = "rotate"  # type: ignore[misc]
    with pytest.raises(TypeError):
        allocation.plan(decision(allocation)).weights[CORE] = 0.1  # type: ignore[index]


@pytest.mark.parametrize(
    "changes",
    [
        {"risky_ids": ()},
        {"risky_ids": (FIRST,)},
        {"risky_ids": (CORE, CORE)},
        {"risky_ids": CORE},
        {"core_id": ""},
        {"monetary_id": CORE},
        {"defensive_ids": (CORE,)},
        {"defensive_ids": (MONEY,)},
        {"canary_ids": (FIRST, FIRST)},
        {"canary_ids": FIRST},
        {"mode": "unknown"},
        {"allocation_mode": "unknown"},
        {"trend_kind": "unknown"},
        {"mode": "balanced", "risky_ids": (CORE, FIRST, SECOND, "FOURTH")},
        {"momentum_lookbacks": ()},
        {"momentum_lookbacks": (21, 21, 126)},
        {"momentum_lookbacks": (True, 63, 126)},
        {"momentum_weights": (1,)},
        {"momentum_weights": (0, 0, 0)},
        {"momentum_weights": (True, 1, 1)},
        {"canary_weights": (0, 0, 0)},
        {"canary_lookbacks": (0, 63, 126)},
        {"trend_kind": "moving_average", "momentum_lookbacks": (1, 63, 126)},
        {"core_floor": -0.01},
        {"core_floor": 1.01},
        {"core_floor": True},
        {"top_k": 0},
        {"top_k": 4},
        {"defensive_top_k": True},
        {"core_preference": -0.01},
        {"switch_buffer": float("nan")},
        {"absolute_filter": 1},
        {"rebalance_band": float("inf")},
        {"canary_min_breadth": 1.01},
        {"volatility_windows": ()},
        {"volatility_windows": (20, 20)},
        {"volatility_windows": (1, 20)},
        {"volatility_floor": 0.0},
        {"target_volatility": -0.01},
        {"mode": "vol_control", "target_volatility": 0.0},
        {"recovery_lookback": True},
        {"recovery_threshold": -0.01},
        {"monetary_lookback": 0},
        {"max_age_sessions": True},
        {"allocation_mode": "fixed", "fixed_weights": (1.0, 0.0, 0.0)},
        {"mode": "balanced", "allocation_mode": "fixed", "fixed_weights": (0.8, 0.2)},
        {"mode": "balanced", "allocation_mode": "fixed", "fixed_weights": (0.8, 0.2, 0.2)},
        {"mode": "balanced", "allocation_mode": "fixed", "fixed_weights": (1.0, -0.1, 0.1)},
        {"fixed_weights": (0.8, 0.1, 0.1)},
    ],
)
def test_invalid_parameters_are_rejected(changes) -> None:
    with pytest.raises(ValueError):
        strategy(**changes)


@pytest.mark.parametrize("mode", ["rotate", "ensemble", "vol_control", "balanced"])
def test_real_signals_ignore_future_prices_without_running_a_candidate_backtest(
    mode, make_market, make_bars, make_context, make_decision, evening, xpar
) -> None:
    allocation = strategy(
        mode=mode,
        momentum_lookbacks=(2, 3, 5),
        momentum_weights=(1, 1, 1),
        canary_lookbacks=(2, 3, 5),
        canary_ids=(FIRST,),
        target_volatility=0.2,
        volatility_windows=(2, 4),
        monetary_lookback=2,
    )
    days = [session.session_date for session in xpar.sessions(date(2026, 9, 1), date(2026, 9, 15))]

    def evaluate(future: bool) -> RiskAwarePlan:
        bars = {}
        for name, slope in ((CORE, 0.002), (FIRST, 0.001), (SECOND, -0.001), (MONEY, 0.0001)):
            closes = {
                day: 100 * math.exp(index * slope)
                for index, day in enumerate(days if future else days[:-1])
            }
            if future:
                closes[days[-1]] = 0.01 if name == CORE else 1_000_000.0
            bars[name] = make_bars(name, xpar, closes)
        context = make_context(make_market(bars), evening(days[-2]))
        requests = [request.resolved(days[-2]) for request in allocation.required_signals()]
        snapshot = SignalEngine().compute(context, requests, list(UNIVERSE))
        return allocation.plan(make_decision(context, snapshot, universe=UNIVERSE))

    before, after = evaluate(False), evaluate(True)
    assert dict(before.weights) == dict(after.weights)
    assert dict(before.scores) == dict(after.scores)
    assert before.canary_breadth == after.canary_breadth
    assert before.offensive_volatility == after.offensive_volatility
    assert before.skipped == after.skipped == {}
    assert all(0 <= weight <= 1 for weight in before.weights.values())
    assert math.fsum(before.weights.values()) <= 1


def test_ma_ensemble_also_requires_latest_own_close_endpoint_guard(decision) -> None:
    allocation = strategy(mode="ensemble", trend_kind="moving_average", defensive_ids=())
    missing = {(allocation.momentum_signal(1).signal_id, CORE): SignalStatus.MISSING_INPUT}
    plan = allocation.plan(decision(allocation, missing))
    assert dict(plan.offensive_weights) == {}
    assert dict(plan.weights) == {MONEY: 1}
    assert plan.skipped[CORE] is SignalStatus.MISSING_INPUT


def test_zero_weight_horizons_are_not_mandatory_inputs(decision) -> None:
    allocation = strategy(momentum_weights=(0.0, 1.0, 0.0), canary_weights=(0.0, 1.0, 0.0))
    requests = {item.signal.signal_id for item in allocation.required_signals()}
    assert allocation.momentum_signal(126).signal_id not in requests
    assert allocation.plan(decision(allocation)).selected == (CORE,)
