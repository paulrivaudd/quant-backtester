"""Nasdaq participation, observable defence, fast recovery and optional relative rotation."""

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
from quant_backtester.strategies.SA15_gpt61_nasdaq import NasdaqAdaptivePlan, SA15NasdaqAdaptive

CORE, FIRST, SECOND, MONEY = "ETF_EU", "ETF_OTHER", "NASDAQ_DEFENCE", "NASDAQ_MONEY"
DEFENSIVE = (FIRST, SECOND)
UNIVERSE = (CORE, *DEFENSIVE, MONEY)
Written = dict[tuple[str, str], float | SignalStatus]


@pytest.fixture
def instruments(instruments: InstrumentRegistry) -> InstrumentRegistry:
    """Add a second defensive fund and monetary fund to the shared registry."""
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


def strategy(**changes: object) -> SA15NasdaqAdaptive:
    """Use real test instruments while preserving the policy's declared defaults."""
    fields: dict[str, object] = {
        "core_id": CORE,
        "defensive_ids": DEFENSIVE,
        "monetary_id": MONEY,
    }
    return SA15NasdaqAdaptive(**(fields | changes))  # type: ignore[arg-type]


def written(allocation: SA15NasdaqAdaptive, changes: Mapping) -> Written:
    """Return rising-market inputs, with Nasdaq stronger than both defensive funds."""
    defaults = {CORE: 0.15, FIRST: 0.10, SECOND: 0.05, MONEY: 0.001}
    values: Written = {}
    for item in allocation.required_signals():
        assert isinstance(item, SignalRequest)
        for name in item.names() or ():
            value = defaults[name]
            if "price_over" in item.signal.signal_id:
                value = 0.05
            elif (
                name == CORE
                and item.signal.signal_id
                == allocation.momentum_signal(allocation.fast_lookback).signal_id
            ):
                value = 0.03
            values[item.signal.signal_id, name] = value
    assert not set(changes) - set(values)
    return values | dict(changes)


def set_defence(allocation: SA15NasdaqAdaptive, name: str, value: float | SignalStatus) -> Written:
    """Set all positive-weight scoring windows for one defensive fund."""
    return {
        (allocation.momentum_signal(window).signal_id, name): value
        for window, weight in zip(
            allocation.defensive_lookbacks, allocation.defensive_weights, strict=True
        )
        if weight > 0.0
    }


def bearish(allocation: SA15NasdaqAdaptive, fast: float = -0.08) -> Written:
    """Trigger the configured guard with an actual fast fall and a weak core."""
    values: Written = {(allocation.momentum_signal(allocation.fast_lookback).signal_id, CORE): fast}
    if allocation.guard_mode == "momentum":
        values[allocation.momentum_signal(allocation.slow_lookback).signal_id, CORE] = -0.10
    else:
        values[allocation.trend_signal().signal_id, CORE] = -0.10
    return values


@pytest.fixture
def decision(written_decision: Callable[..., StrategyContext]) -> Callable[..., StrategyContext]:
    """Build one evening snapshot with explicit actual holdings, including cash."""

    def build(
        allocation: SA15NasdaqAdaptive,
        changes: Mapping | None = None,
        held: Mapping[str, float] | None = None,
    ) -> StrategyContext:
        return written_decision(
            allocation,
            written(allocation, changes or {}),
            universe=UNIVERSE,
            held=held,
        )

    return build


def test_defaults_declare_a_separate_no_fit_policy_without_volatility_control() -> None:
    allocation = SA15NasdaqAdaptive()
    assert allocation.strategy_id == "SA15_GPT-6.1_R3"
    assert allocation.core_id == "ETF_NASDAQ"
    assert allocation.defensive_ids == ("ETF_GOLD", "ETF_SP500_PEA")
    assert allocation.guard_mode == "momentum"
    assert allocation.trend_sessions == 0
    assert not allocation.relative_rotation
    requests = allocation.required_signals()
    assert all(isinstance(item, SignalRequest) for item in requests)
    assert not any("volatility" in item.signal.signal_id for item in requests)
    assert not any("price_over" in item.signal.signal_id for item in requests)
    json.dumps(allocation.definition())


def test_normal_market_initial_cash_enters_full_nasdaq_without_strategic_cash_drag(
    decision,
) -> None:
    allocation = strategy()
    context = decision(allocation)
    plan = allocation.plan(context)
    assert plan.regime == "nasdaq"
    assert not plan.was_defensive
    assert dict(plan.weights) == {CORE: 1.0}
    assert dict(allocation.decide(context).weights) == {CORE: 1.0}


def test_weak_slow_momentum_alone_does_not_sell_into_a_rebound(decision) -> None:
    allocation = strategy()
    plan = allocation.plan(decision(allocation, bearish(allocation, fast=0.02)))
    assert plan.regime == "nasdaq"
    assert dict(plan.weights) == {CORE: 1.0}


def test_fast_fall_without_slow_weakness_does_not_trigger_defence(decision) -> None:
    allocation = strategy()
    changes = {(allocation.momentum_signal(21).signal_id, CORE): -0.08}
    assert dict(allocation.plan(decision(allocation, changes)).weights) == {CORE: 1.0}


def test_joint_weakness_allocates_only_the_declared_defensive_fraction(decision) -> None:
    allocation = strategy(core_floor=0.25)
    plan = allocation.plan(decision(allocation, bearish(allocation)))
    assert plan.regime == "defensive"
    assert plan.selected == (FIRST,)
    assert dict(plan.weights) == {CORE: 0.25, FIRST: 0.75}
    assert plan.absolute_scores[FIRST] == pytest.approx(math.log1p(0.10))
    assert math.fsum(plan.weights.values()) == 1.0


def test_actual_defensive_positions_maintain_the_guard_until_fast_recovery(decision) -> None:
    allocation = strategy()
    intermediate = bearish(allocation, fast=-0.02)
    assert allocation.plan(decision(allocation, intermediate)).regime == "nasdaq"
    held = {CORE: 0.5, FIRST: 0.5}
    plan = allocation.plan(decision(allocation, intermediate, held))
    assert plan.was_defensive
    assert plan.regime == "defensive"
    assert dict(plan.weights) == held
    recovered = allocation.plan(decision(allocation, bearish(allocation, fast=0.0), held))
    assert recovered.recovery
    assert recovered.core_slow == -0.10
    assert dict(recovered.weights) == {CORE: 1.0}


def test_fast_recovery_overrides_the_band_even_when_defensive_capital_is_cash(decision) -> None:
    allocation = strategy(core_floor=0.95, rebalance_band=0.08)
    context = decision(allocation, bearish(allocation, fast=0.01), held={CORE: 0.95})
    plan = allocation.plan(context)
    assert plan.was_defensive and plan.recovery
    target = allocation.decide(context)
    assert not target.hold_positions
    assert dict(target.weights) == {CORE: 1.0}


def test_rejected_initial_purchase_and_empty_cash_have_no_hidden_defensive_state(decision) -> None:
    allocation = strategy()
    context = decision(allocation, bearish(allocation, fast=-0.02), held={})
    assert not allocation.plan(context).was_defensive
    assert dict(allocation.decide(context).weights) == {CORE: 1.0}
    fully_defensive = strategy(core_floor=0.0)
    context = decision(fully_defensive, bearish(fully_defensive, fast=-0.02), held={})
    assert not fully_defensive.plan(context).was_defensive
    assert dict(fully_defensive.plan(context).weights) == {CORE: 1.0}


def test_rejected_defensive_purchase_is_inferred_from_reduced_core_and_cash(decision) -> None:
    allocation = strategy()
    plan = allocation.plan(
        decision(allocation, bearish(allocation, fast=-0.02), held={CORE: 0.497})
    )
    assert plan.was_defensive
    assert plan.regime == "defensive"
    assert dict(plan.weights) == {CORE: 0.5, FIRST: 0.5}


def test_normal_whole_share_residual_cash_does_not_create_a_defensive_regime(decision) -> None:
    allocation = strategy()
    context = decision(allocation, bearish(allocation, fast=-0.02), held={CORE: 0.996})
    plan = allocation.plan(context)
    assert not plan.was_defensive
    assert plan.regime == "nasdaq"
    assert allocation.decide(context).hold_positions


def test_defensive_budget_renormalizes_to_available_positive_funds_and_weights(decision) -> None:
    allocation = strategy(top_k=2, defensive_weights=(1, 2))
    plan = allocation.plan(decision(allocation, bearish(allocation)))
    assert dict(plan.weights) == {CORE: 0.5, FIRST: 0.25, SECOND: 0.25}
    changes = bearish(allocation) | set_defence(allocation, SECOND, -0.01)
    plan = allocation.plan(decision(allocation, changes))
    assert dict(plan.weights) == {CORE: 0.5, FIRST: 0.5}
    assert SECOND not in plan.selected


@pytest.mark.parametrize(
    "carry,expected", [(0.001, {CORE: 0.5, MONEY: 0.5}), (0.0, {CORE: 0.5}), (-0.001, {CORE: 0.5})]
)
def test_no_positive_defensive_score_uses_positive_monetary_carry_or_cash(
    decision, carry, expected
) -> None:
    allocation = strategy()
    changes = bearish(allocation)
    changes |= set_defence(allocation, FIRST, -0.05) | set_defence(allocation, SECOND, 0.0)
    changes[allocation.momentum_signal(allocation.monetary_lookback).signal_id, MONEY] = carry
    plan = allocation.plan(decision(allocation, changes))
    assert dict(plan.weights) == expected
    assert plan.selected == ()


def test_missing_defensive_fund_is_excluded_individually_without_losing_core(decision) -> None:
    allocation = strategy()
    changes = bearish(allocation) | set_defence(allocation, FIRST, SignalStatus.STALE_INPUT)
    context = decision(allocation, changes)
    plan = allocation.plan(context)
    assert dict(plan.weights) == {CORE: 0.5, SECOND: 0.5}
    assert plan.skipped == {FIRST: SignalStatus.STALE_INPUT}
    assert plan.readable == 2
    assert dict(allocation.decide(context).skipped) == dict(plan.skipped)


@pytest.mark.parametrize("window", [21, 126])
def test_missing_mandatory_core_input_liquidates_to_cash_with_reason(decision, window) -> None:
    allocation = strategy()
    changes = {(allocation.momentum_signal(window).signal_id, CORE): SignalStatus.MISSING_INPUT}
    context = decision(allocation, changes, held={CORE: 0.5, FIRST: 0.5})
    plan = allocation.plan(context)
    assert plan.regime == "missing_core"
    assert dict(plan.weights) == {}
    target = allocation.decide(context)
    assert not target.hold_positions
    assert dict(target.weights) == {}
    assert target.skipped[CORE] is SignalStatus.MISSING_INPUT


def test_ma_mode_uses_zero_distance_and_fast_recovery_independently_of_slow_threshold(
    decision,
) -> None:
    allocation = strategy(guard_mode="trend", trend_sessions=200, slow_entry_threshold=0.50)
    requests = allocation.required_signals()
    core_inputs = {item.signal.signal_id for item in requests if CORE in (item.names() or ())}
    assert allocation.momentum_signal(126).signal_id not in core_inputs
    assert allocation.trend_signal().signal_id in core_inputs
    context = decision(allocation, bearish(allocation), held={CORE: 0.5, FIRST: 0.5})
    assert allocation.plan(context).regime == "defensive"
    assert allocation.plan(context).core_slow is None
    context = decision(allocation, bearish(allocation, fast=0.01), held={CORE: 0.5, FIRST: 0.5})
    assert allocation.plan(context).recovery
    assert dict(allocation.plan(context).weights) == {CORE: 1.0}
    changes = {(allocation.trend_signal().signal_id, CORE): SignalStatus.NON_CONSECUTIVE_HISTORY}
    assert allocation.plan(decision(allocation, changes)).regime == "missing_core"


def test_optional_relative_rotation_is_explicit_and_compares_log_momentum_to_nasdaq(
    decision,
) -> None:
    allocation = strategy(relative_rotation=True)
    changes = set_defence(allocation, FIRST, 0.30)
    plan = allocation.plan(decision(allocation, changes))
    assert plan.regime == "relative"
    assert plan.core_fast > 0
    assert plan.relative_scores[FIRST] == pytest.approx(math.log1p(0.30) - math.log1p(0.15))
    assert dict(plan.weights) == {CORE: 0.5, FIRST: 0.5}
    disabled = strategy(relative_rotation=False)
    assert dict(disabled.plan(decision(disabled, changes)).weights) == {CORE: 1.0}


def test_relative_incumbent_buffer_and_observable_coupling_with_weak_core(decision) -> None:
    allocation = strategy(relative_rotation=True, relative_threshold=0.05, switch_buffer=0.02)
    # log(1.19/1.15) = 3.42%, below entry 5%, above held-fund exit 3%.
    changes = set_defence(allocation, FIRST, 0.19)
    assert allocation.plan(decision(allocation, changes)).regime == "nasdaq"
    held = {CORE: 0.5, FIRST: 0.5}
    assert allocation.plan(decision(allocation, changes, held)).regime == "relative"
    # The same actual relative position maintains the guard once Nasdaq is weak.
    changes |= bearish(allocation, fast=-0.02)
    plan = allocation.plan(decision(allocation, changes, held))
    assert plan.was_defensive
    assert plan.regime == "defensive"
    assert dict(plan.weights) == held


def test_relative_rotation_can_remain_after_guard_recovery_only_when_explicitly_enabled(
    decision,
) -> None:
    allocation = strategy(relative_rotation=True)
    changes = bearish(allocation, fast=0.01) | set_defence(allocation, FIRST, 0.30)
    plan = allocation.plan(decision(allocation, changes, held={CORE: 0.5, FIRST: 0.5}))
    assert plan.regime == "relative"
    assert not plan.recovery
    assert plan.selected == (FIRST,)


def test_defensive_ranking_buffer_avoids_small_switches_and_ties_are_stable(decision) -> None:
    allocation = strategy()
    changes = bearish(allocation) | set_defence(allocation, SECOND, 0.095)
    plan = allocation.plan(decision(allocation, changes, held={CORE: 0.5, SECOND: 0.5}))
    assert plan.selected == (SECOND,)
    changes |= set_defence(allocation, FIRST, 0.30)
    plan = allocation.plan(decision(allocation, changes, held={CORE: 0.5, SECOND: 0.5}))
    assert plan.selected == (FIRST,)


def test_configuration_and_plan_are_immutable(decision) -> None:
    ids = list(DEFENSIVE)
    allocation = strategy(defensive_ids=ids)
    fingerprint = allocation.fingerprint()
    ids.clear()
    assert allocation.fingerprint() == fingerprint
    with pytest.raises(FrozenInstanceError):
        allocation.core_floor = 0.1  # type: ignore[misc]
    with pytest.raises(TypeError):
        allocation.plan(decision(allocation)).weights[CORE] = 0.5  # type: ignore[index]


@pytest.mark.parametrize(
    "changes",
    [
        {"defensive_ids": (FIRST, FIRST)},
        {"defensive_ids": FIRST},
        {"defensive_ids": (CORE,)},
        {"monetary_id": CORE},
        {"core_id": ""},
        {"guard_mode": "other"},
        {"trend_sessions": True},
        {"trend_sessions": 1},
        {"guard_mode": "trend", "trend_sessions": 0},
        {"fast_lookback": True},
        {"fast_lookback": 126},
        {"slow_lookback": 0},
        {"fast_entry_threshold": 0.01},
        {"fast_entry_threshold": float("nan")},
        {"slow_entry_threshold": -1.0},
        {"recovery_threshold": float("inf")},
        {"core_floor": -0.01},
        {"core_floor": 1.01},
        {"core_floor": True},
        {"defensive_lookbacks": ()},
        {"defensive_lookbacks": (63, 63)},
        {"defensive_lookbacks": (True, 126)},
        {"defensive_weights": (1,)},
        {"defensive_weights": (0, 0)},
        {"defensive_weights": (float("nan"), 1)},
        {"defensive_weights": (True, 1)},
        {"top_k": True},
        {"top_k": 0},
        {"switch_buffer": -0.01},
        {"rebalance_band": float("nan")},
        {"relative_rotation": 1},
        {"relative_threshold": -0.01},
        {"monetary_lookback": 0},
        {"max_age_sessions": True},
    ],
)
def test_invalid_policy_parameters_are_rejected(changes) -> None:
    with pytest.raises(ValueError):
        strategy(**changes)


def test_real_point_in_time_signals_ignore_future_prices_without_a_backtest(
    make_market,
    make_bars,
    make_context,
    make_decision,
    evening,
    xpar,
) -> None:
    allocation = strategy(fast_lookback=2, slow_lookback=5, defensive_lookbacks=(3, 5))
    days = [session.session_date for session in xpar.sessions(date(2026, 9, 1), date(2026, 9, 15))]

    def evaluate(future: bool) -> NasdaqAdaptivePlan:
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
        requests = [item.resolved(days[-2]) for item in allocation.required_signals()]
        snapshot = SignalEngine().compute(context, requests, list(UNIVERSE))
        return allocation.plan(make_decision(context, snapshot, universe=UNIVERSE))

    before, after = evaluate(False), evaluate(True)
    assert before.core_fast == after.core_fast
    assert before.core_slow == after.core_slow
    assert dict(before.absolute_scores) == dict(after.absolute_scores)
    assert dict(before.weights) == dict(after.weights) == {CORE: 1.0}
    assert before.skipped == after.skipped == {}
    assert all(0 <= weight <= 1 for weight in before.weights.values())
    assert math.fsum(before.weights.values()) <= 1.0
