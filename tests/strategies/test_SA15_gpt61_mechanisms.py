"""Hand-checkable mechanism boundaries, ablations and availability guards."""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping
from dataclasses import FrozenInstanceError, replace
from datetime import date

import pytest

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.data.instruments import AssetType, DataType, Instrument, InstrumentRegistry
from quant_backtester.signals.engine import SignalEngine
from quant_backtester.signals.types import SignalStatus
from quant_backtester.strategies.SA15_gpt61_mechanisms import (
    BLOCK_PARAMETERS,
    FROZEN_PARAMETERS,
    SA15Mechanisms,
)
from quant_backtester.strategies.SA15_gpt61_riskaware import SA15RiskAwareRotation

CORE, GOLD, MONEY, GOV, CANARY1, CANARY2 = (
    "ETF_EU",
    "ETF_OTHER",
    "MECH_MONEY",
    "MECH_GOV",
    "MECH_CANARY1",
    "MECH_CANARY2",
)
UNIVERSE = (CORE, MONEY, GOLD, GOV)
Written = dict[tuple[str, str], float | SignalStatus]


@pytest.fixture
def instruments(instruments: InstrumentRegistry) -> InstrumentRegistry:
    """Add fixed-currency funds, including canaries outside the trading universe."""
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
                for name in (MONEY, GOV, CANARY1, CANARY2)
            ),
        ]
    )


def strategy(**changes: object) -> SA15Mechanisms:
    """Keep numerical research constants unchanged unless a small window is tested."""
    defaults = {
        "core_id": CORE,
        "monetary_id": MONEY,
        "gold_id": GOLD,
        "government_id": GOV,
        "canary_ids": (CANARY1, CANARY2),
    }
    return SA15Mechanisms(**(defaults | changes))  # type: ignore[arg-type]


def values(policy: SA15Mechanisms, changes: Mapping[str, object] | None = None) -> Written:
    """Write prices above average, positive returns and twenty percent risk."""
    written: Written = {}
    for request in policy.required_signals():
        for name in request.names() or ():
            value = 0.001 if name == MONEY else 0.05
            if "volatility" in request.signal.signal_id:
                value = 0.20
            elif "drawdown" in request.signal.signal_id:
                value = -0.01
            elif "price_over_ma" in request.signal.signal_id:
                value = 0.02
            written[request.signal.signal_id, name] = value
    for label, value in (changes or {}).items():
        signal, name = policy._inputs()[label]
        written[signal.signal_id, name] = value  # type: ignore[assignment]
    return written


@pytest.fixture
def decision(written_decision: Callable[..., StrategyContext]) -> Callable[..., StrategyContext]:
    """Build genuine evening contexts from explicit values and held positions."""

    def build(
        policy: SA15Mechanisms, changes=None, held=None, universe=UNIVERSE
    ) -> StrategyContext:
        return written_decision(policy, values(policy, changes), held=held, universe=universe)

    return build


def test_defaults_reproduce_pilot_contract_and_all_constants_are_serialised() -> None:
    policy = SA15Mechanisms()
    assert policy.active_blocks() == ("trend", "risk", "defensive", "execution")
    assert (policy.trend_rule, policy.risk_rule, policy.target_volatility) == (
        "ma200",
        "cap_max",
        0.20,
    )
    assert policy.rebalance_band == 0.10 and policy.max_age_sessions == 1
    assert set(policy.parameters()) == {
        "strategy_id",
        *FROZEN_PARAMETERS,
        *(f"{name}_rule" for name in BLOCK_PARAMETERS),
    }
    json.dumps(policy.definition(), allow_nan=False)
    policy.validate()
    assert policy.fingerprint() == SA15Mechanisms().fingerprint()


@pytest.mark.parametrize("block", tuple(BLOCK_PARAMETERS))
def test_ablation_changes_only_the_named_categorical_field(block) -> None:
    policy = strategy(
        recovery_rule="positive21", shock_rule="fast_loss", confirmation_rule="momentum"
    )
    ablated = policy.without_block(block)
    assert {
        key for key in policy.parameters() if policy.parameters()[key] != ablated.parameters()[key]
    } == {f"{block}_rule"}
    assert block not in ablated.active_blocks()
    assert all(policy.parameters()[key] == ablated.parameters()[key] for key in FROZEN_PARAMETERS)


def test_unknown_ablation_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown"):
        strategy().without_block("oracle")


@pytest.mark.parametrize(
    "rule, changes, expected",
    [
        ("off", {}, 1.0),
        ("ma200", {"ma_200": 0.0}, 0.0),
        ("dual_ma", {"ma_50": 0.0}, 0.0),
        ("momentum", {"mom_126": 0.0}, 0.0),
        ("consensus", {"ma_200": 0.0, "mom_63": -0.10}, 1 / 3),
        ("partial", {"ma_200": -0.10}, 0.5),
        ("slow_fast_guard", {"ma_200": -0.10, "mom_21": 0.01}, 1.0),
    ],
)
def test_direction_rules_have_hand_checkable_positive_and_zero_boundaries(
    decision, rule, changes, expected
) -> None:
    policy = strategy(trend_rule=rule, risk_rule="off")
    plan = policy.plan(decision(policy, changes))
    assert plan.trend_fraction == pytest.approx(expected)
    assert plan.core_weight == pytest.approx(expected)


@pytest.mark.parametrize(
    "rule, changes, expected",
    [
        ("off", {}, 1.0),
        ("cap_max", {"vol_20": 0.40, "vol_60": 0.10}, 0.5),
        ("cap_max", {"vol_20": 0.10, "vol_60": 0.40}, 0.5),
        ("cap_fast", {"vol_20": 0.10}, 1.0),
        ("negative_only", {"vol_20": 0.40, "vol_60": 0.40, "mom_21": 0.01}, 1.0),
        ("negative_only", {"vol_20": 0.40, "vol_60": 0.40, "mom_21": 0.0}, 0.5),
        ("conditional", {"vol_20": 0.40, "vol_60": 0.40, "ma_200": 0.01}, 1.0),
        ("conditional", {"vol_20": 0.40, "vol_60": 0.40, "ma_200": 0.0}, 0.5),
        ("trend_relief", {"vol_20": 0.40, "vol_60": 0.40, "ma_50": 0.01}, 0.75),
        ("trend_relief", {"vol_20": 0.40, "vol_60": 0.40, "ma_50": 0.0}, 0.5),
    ],
)
def test_risk_rules_scale_and_exceptions_deliberately_relax_protection(
    decision, rule, changes, expected
) -> None:
    policy = strategy(trend_rule="off", risk_rule=rule)
    plan = policy.plan(decision(policy, changes))
    assert plan.risk_scale == pytest.approx(expected)
    assert plan.core_weight == pytest.approx(expected)
    assert sum(plan.weights.values()) <= 1.0


def test_zero_volatility_uses_explicit_floor_without_leverage(decision) -> None:
    policy = strategy()
    plan = policy.plan(decision(policy, {"vol_20": 0.0, "vol_60": 0.0}))
    assert plan.risk_estimate == 0.05
    assert plan.core_weight == 1


@pytest.mark.parametrize(
    "rule, changes, restored",
    [
        ("off", {}, False),
        ("positive21", {"mom_21": 0.001}, True),
        ("positive21", {"mom_21": 0.0}, False),
        ("ma50", {"ma_50": 0.01}, True),
        ("dual_confirm", {"ma_50": 0.0}, False),
        ("breakout", {"drawdown": 0.0}, True),
        ("breakout", {"drawdown": -0.001}, False),
        ("near_high", {"drawdown": -0.02}, True),
        ("near_high", {"drawdown": -0.02001}, False),
        ("positive_acceleration", {"mom_21": 0.05, "mom_63": 0.01}, True),
        ("positive_acceleration", {"mom_21": 0.01, "mom_63": 0.20}, False),
    ],
)
def test_recovery_changes_direction_but_still_respects_risk_cap(
    decision, rule, changes, restored
) -> None:
    policy = strategy(recovery_rule=rule)
    plan = policy.plan(
        decision(policy, {"ma_200": -0.05, "vol_20": 0.40, "vol_60": 0.40} | changes)
    )
    assert plan.recovery_active is restored
    assert plan.core_weight == pytest.approx(0.5 if restored else 0)


@pytest.mark.parametrize(
    "shock,changes",
    [
        ("fast_loss", {"mom_21": -0.08}),
        ("drawdown", {"drawdown": -0.10}),
    ],
)
def test_shock_boundary_stops_even_recovered_direction(decision, shock, changes) -> None:
    policy = strategy(recovery_rule="ma50", shock_rule=shock)
    plan = policy.plan(decision(policy, {"ma_200": -0.10} | changes))
    assert plan.recovery_active and plan.shock_active
    assert plan.recovery_fraction == 1 and plan.core_weight == 0


@pytest.mark.parametrize(
    "rule,changes",
    [
        ("momentum", {"mom_63": 0.0}),
        ("double_trend", {"ma_50": 0.0}),
        ("canary", {f"canary:{CANARY2}": 0.0}),
        ("persistence", {"previous_fast": 0.0}),
    ],
)
def test_confirmation_can_refuse_fast_recovery(decision, rule, changes) -> None:
    policy = strategy(recovery_rule="positive21", confirmation_rule=rule)
    plan = policy.plan(decision(policy, {"ma_200": -0.10} | changes))
    assert plan.recovery_active and plan.confirmed_fraction == 0 and plan.core_weight == 0


def test_missing_external_canary_is_logged_without_invalid_trading_skipped_name(decision) -> None:
    policy = strategy(confirmation_rule="canary")
    plan = policy.plan(decision(policy, {f"canary:{CANARY2}": SignalStatus.MISSING_INPUT}))
    assert plan.missing_core and plan.core_weight == 0
    assert CANARY2 not in plan.skipped
    assert plan.signal_statuses[f"canary:{CANARY2}"] is SignalStatus.MISSING_INPUT
    assert dict(
        policy.decide(decision(policy, {f"canary:{CANARY2}": SignalStatus.MISSING_INPUT})).weights
    ) == {MONEY: 1.0}


@pytest.mark.parametrize("label", ["fresh", "ma_200", "vol_20", "vol_60"])
def test_missing_required_core_input_prevents_recovery_and_targets_declared_defence(
    decision, label
) -> None:
    policy = strategy(recovery_rule="positive21")
    plan = policy.plan(decision(policy, {label: SignalStatus.NON_CONSECUTIVE_HISTORY}))
    assert plan.missing_core and plan.core_weight == 0 and not plan.recovery_active
    assert plan.skipped[CORE] is SignalStatus.NON_CONSECUTIVE_HISTORY
    assert dict(plan.weights) == {MONEY: 1.0}


def test_diagnostic_only_missing_momentum_never_creates_an_order_or_exit(decision) -> None:
    policy = strategy(trend_rule="off", risk_rule="off", defensive_rule="cash")
    plan = policy.plan(
        decision(
            policy, {"mom_126": SignalStatus.MISSING_INPUT, "mom_21": SignalStatus.MISSING_INPUT}
        )
    )
    assert not plan.missing_core and plan.core_weight == 1
    assert not plan.skipped


@pytest.mark.parametrize(
    "rule,changes,expected",
    [
        ("cash", {}, {}),
        ("monetary", {}, {MONEY: 1.0}),
        ("monetary", {f"{MONEY}:carry": 0.0}, {}),
        ("gold_momentum", {}, {GOLD: 1.0}),
        ("gold_momentum", {f"{GOLD}:defense": 0.0}, {MONEY: 1.0}),
        ("dual_defense", {f"{GOV}:defense": 0.10}, {GOV: 1.0}),
        ("dual_defense", {f"{GOV}:defense": 0.05}, {GOLD: 1.0}),
        ("dual_defense", {f"{GOV}:defense": -0.01, f"{GOLD}:defense": -0.01}, {MONEY: 1.0}),
        ("gold_momentum", {f"{GOLD}:defense": SignalStatus.MISSING_INPUT}, {MONEY: 1.0}),
    ],
)
def test_residual_defence_is_indicator_selected_without_optimised_mix(
    decision, rule, changes, expected
) -> None:
    policy = strategy(defensive_rule=rule)
    plan = policy.plan(decision(policy, {"ma_200": -0.01} | changes))
    assert dict(plan.weights) == expected


def test_band_avoids_small_risk_changes_and_complete_exit_is_forced(decision) -> None:
    policy = strategy()
    assert policy.decide(decision(policy, held={CORE: 0.95})).hold_positions
    assert not policy.decide(
        decision(policy, {"ma_200": 0.0}, held={CORE: 0.01, MONEY: 0.99})
    ).hold_positions
    unbanded = replace(policy, execution_rule="off")
    assert not unbanded.decide(decision(unbanded, held={CORE: 0.95})).hold_positions


def test_asymmetric_band_delays_small_entry_but_executes_same_sized_risk_reduction(
    decision,
) -> None:
    policy = strategy(execution_rule="asymmetric", defensive_rule="cash")
    assert policy.decide(decision(policy, held={CORE: 0.90})).hold_positions
    assert not policy.decide(
        decision(policy, {"vol_20": 0.25, "vol_60": 0.25}, held={CORE: 0.90})
    ).hold_positions


def test_hold_defence_preserves_incumbent_only_when_core_regime_and_band_allow(decision) -> None:
    policy = strategy(defensive_rule="dual_defense", execution_rule="hold_defense")
    changes = {"ma_200": -0.01, f"{GOV}:defense": 0.10}
    assert policy.decide(decision(policy, changes, held={GOLD: 0.99})).hold_positions
    regular = replace(policy, execution_rule="band")
    assert not regular.decide(decision(regular, changes, held={GOLD: 0.99})).hold_positions
    assert not policy.decide(
        decision(policy, changes, held={CORE: 0.05, GOLD: 0.95})
    ).hold_positions


def test_plan_and_configuration_are_immutable_and_audit_is_passive(decision) -> None:
    canaries = [CANARY1, CANARY2]
    policy = strategy(canary_ids=canaries)
    fingerprint = policy.fingerprint()
    canaries.clear()
    assert policy.fingerprint() == fingerprint
    plan = policy.plan(decision(policy))
    with pytest.raises(FrozenInstanceError):
        policy.trend_rule = "off"  # type: ignore[misc]
    with pytest.raises(TypeError):
        plan.weights[CORE] = 0.0  # type: ignore[index]
    audit = plan.audit_dict()
    json.dumps(audit, allow_nan=False)
    audit["core_weight"] = 0.0
    assert policy.plan(decision(policy)).core_weight == 1 and plan.core_weight == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"trend_rule": "oracle"},
        {"risk_rule": "garch"},
        {"recovery_rule": "oracle"},
        {"shock_rule": "oracle"},
        {"confirmation_rule": "oracle"},
        {"defensive_rule": "oracle"},
        {"execution_rule": "oracle"},
        {"core_id": ""},
        {"monetary_id": CORE},
        {"canary_ids": []},
        {"canary_ids": [CANARY1, CANARY1]},
        {"canary_ids": CANARY1},
        {"fast_sessions": True},
        {"medium_sessions": 21},
        {"ma_fast_sessions": 1},
        {"vol_fast_returns": 1},
        {"drawdown_sessions": 1},
        {"max_age_sessions": True},
        {"target_volatility": 0.0},
        {"volatility_floor": float("nan")},
        {"partial_exposure": 1.1},
        {"risk_relief_floor": True},
        {"rebalance_band": -0.1},
        {"entry_band": 0.01},
        {"shock_loss_threshold": -1.0},
        {"shock_drawdown_threshold": 0.0},
        {"near_high_threshold": float("inf")},
    ],
)
def test_invalid_configurations_are_rejected(changes) -> None:
    with pytest.raises(ValueError):
        strategy(**changes)


@pytest.mark.parametrize("trend", [-0.05, 0.0, 0.05])
@pytest.mark.parametrize("risks", [(0.0, 0.0), (0.10, 0.30), (0.40, 0.20)])
@pytest.mark.parametrize("carry", [0.0, 0.001])
def test_default_policy_matches_old_pilot_targets_on_identical_inputs(
    written_decision, decision, trend, risks, carry
) -> None:
    policy = strategy()
    actual = policy.plan(
        decision(
            policy,
            {
                "ma_200": trend,
                "vol_20": risks[0],
                "vol_60": risks[1],
                f"{MONEY}:carry": carry,
            },
        )
    )
    pilot = SA15RiskAwareRotation(
        core_id=CORE,
        risky_ids=(CORE,),
        defensive_ids=(),
        monetary_id=MONEY,
        mode="ensemble",
        momentum_lookbacks=(200,),
        momentum_weights=(1.0,),
        trend_kind="moving_average",
        core_floor=0.0,
        top_k=1,
        allocation_mode="equal",
        absolute_filter=True,
        core_preference=0.0,
        switch_buffer=0.0,
        rebalance_band=0.10,
        volatility_windows=(20, 60),
        volatility_floor=0.05,
        target_volatility=0.20,
        recovery_lookback=0,
        monetary_lookback=21,
        max_age_sessions=1,
    )
    written = {}
    for request in pilot.required_signals():
        for name in request.names() or ():
            value = carry if name == MONEY else 0.01
            if "volatility" in request.signal.signal_id:
                value = risks[0] if "20" in request.signal.signal_id else risks[1]
            elif "price_over" in request.signal.signal_id:
                value = trend
            written[request.signal.signal_id, name] = value
    expected = pilot.plan(written_decision(pilot, written, universe=UNIVERSE))
    assert dict(actual.weights) == pytest.approx(dict(expected.weights))


@pytest.mark.parametrize(
    "changes",
    [
        {
            "recovery_rule": "positive21",
            "shock_rule": "drawdown",
            "confirmation_rule": "momentum",
            "defensive_rule": "gold_momentum",
        },
        {
            "trend_rule": "consensus",
            "risk_rule": "conditional",
            "recovery_rule": "near_high",
            "shock_rule": "fast_loss",
            "confirmation_rule": "double_trend",
            "defensive_rule": "dual_defense",
        },
        {
            "trend_rule": "momentum",
            "risk_rule": "negative_only",
            "recovery_rule": "positive_acceleration",
            "confirmation_rule": "canary",
        },
        {
            "trend_rule": "partial",
            "risk_rule": "trend_relief",
            "recovery_rule": "dual_confirm",
            "confirmation_rule": "persistence",
            "defensive_rule": "cash",
        },
        {"trend_rule": "dual_ma", "risk_rule": "cap_fast", "recovery_rule": "breakout"},
    ],
)
def test_real_signals_and_policy_ignore_future_values(
    changes, make_market, make_bars, make_context, make_decision, evening, xpar
) -> None:
    policy = strategy(
        fast_sessions=2,
        medium_sessions=4,
        slow_sessions=8,
        ma_fast_sessions=3,
        ma_slow_sessions=5,
        vol_fast_returns=2,
        vol_slow_returns=4,
        drawdown_sessions=5,
        defensive_sessions=4,
        monetary_sessions=2,
        **changes,
    )
    days = [session.session_date for session in xpar.sessions(date(2026, 9, 1), date(2026, 9, 23))]

    def evaluate(with_future: bool) -> dict[str, object]:
        bars = {}
        for name, slope in (
            (CORE, 0.002),
            (GOLD, 0.001),
            (GOV, -0.001),
            (MONEY, 0.0001),
            (CANARY1, 0.001),
            (CANARY2, 0.002),
        ):
            closes = {
                day: 100 * math.exp(index * slope)
                for index, day in enumerate(days if with_future else days[:-1])
            }
            if with_future:
                closes[days[-1]] = 0.001 if name == CORE else 1_000_000
            bars[name] = make_bars(name, xpar, closes)
        context = make_context(make_market(bars), evening(days[-2]))
        snapshot = SignalEngine().compute(
            context, [request.resolved(days[-2]) for request in policy.required_signals()], UNIVERSE
        )
        return policy.plan(make_decision(context, snapshot, universe=UNIVERSE)).audit_dict()

    assert evaluate(False) == evaluate(True)


def test_missing_internal_bar_invalidates_strict_ma_and_risk_without_repair(
    make_market, make_bars, make_context, make_decision, evening, xpar
) -> None:
    policy = strategy(
        fast_sessions=2,
        medium_sessions=4,
        slow_sessions=8,
        ma_fast_sessions=3,
        ma_slow_sessions=5,
        vol_fast_returns=2,
        vol_slow_returns=4,
        drawdown_sessions=5,
        defensive_sessions=4,
        monetary_sessions=2,
    )
    days = [session.session_date for session in xpar.sessions(date(2026, 9, 1), date(2026, 9, 23))]
    bars = {
        name: make_bars(
            name,
            xpar,
            {
                day: 100 + index
                for index, day in enumerate(days)
                if not (name == CORE and day == days[-3])
            },
        )
        for name in (CORE, MONEY)
    }
    context = make_context(make_market(bars), evening(days[-1]))
    snapshot = SignalEngine().compute(
        context, [request.resolved(days[-1]) for request in policy.required_signals()], UNIVERSE
    )
    plan = policy.plan(make_decision(context, snapshot, universe=UNIVERSE))
    assert plan.missing_core and plan.core_weight == 0
    assert plan.signal_statuses["ma_5"] is SignalStatus.NON_CONSECUTIVE_HISTORY
    assert plan.signal_statuses["mom_8"] is SignalStatus.OK
    assert dict(plan.weights) == {MONEY: 1.0}


def test_core_outside_trading_universe_uses_defence_even_with_positive_inputs(decision) -> None:
    policy = strategy()
    plan = policy.plan(decision(policy, universe=(MONEY, GOLD, GOV)))
    assert plan.missing_core and plan.core_weight == 0
    assert "core_outside_universe" in plan.reasons
    assert dict(plan.weights) == {MONEY: 1.0}


def test_missing_defence_does_not_reduce_full_core_exposure(decision) -> None:
    policy = strategy(defensive_rule="dual_defense")
    plan = policy.plan(
        decision(
            policy,
            {
                f"{GOLD}:defense": SignalStatus.MISSING_INPUT,
                f"{GOV}:defense": SignalStatus.MISSING_INPUT,
                f"{MONEY}:carry": SignalStatus.MISSING_INPUT,
            },
        )
    )
    assert not plan.missing_core and not plan.skipped
    assert dict(plan.weights) == {CORE: 1.0}


def test_hold_defence_never_preserves_held_fund_with_unavailable_required_input(decision) -> None:
    policy = strategy(defensive_rule="dual_defense", execution_rule="hold_defense")
    changes = {"ma_200": -0.01, f"{GOLD}:defense": SignalStatus.MISSING_INPUT}
    target = policy.decide(decision(policy, changes, held={GOLD: 0.99}))
    assert not target.hold_positions
    assert dict(target.weights) == {GOV: 1.0}
