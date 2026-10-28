"""Hand-checkable allocation, missing inputs and the evening information boundary."""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping
from dataclasses import FrozenInstanceError
from datetime import date, datetime

import pandas as pd
import pytest

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.data.calendars import TradingCalendar
from quant_backtester.data.instruments import AssetType, DataType, Instrument, InstrumentRegistry
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.engine import SignalEngine, SignalRequest
from quant_backtester.signals.types import SignalStatus
from quant_backtester.strategies.SA15_gpt61 import (
    SA15GPT61,
    rotation_weights,
    weighted_momentum,
)

FIRST, SECOND, THIRD, MONEY = "ETF_EU", "ETF_OTHER", "SA15_THIRD", "SA15_MONEY"
FUNDS = (FIRST, SECOND, THIRD)
UNIVERSE = (*FUNDS, MONEY)
Written = dict[tuple[str, str], float | SignalStatus]


@pytest.fixture
def instruments(instruments: InstrumentRegistry) -> InstrumentRegistry:
    """Extend the common registry with a tactical and a money-market ETF."""
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
                for name in (THIRD, MONEY)
            ),
        ]
    )


def strategy(**changes: object) -> SA15GPT61:
    """Return the strategy over the small registered universe."""
    config: dict[str, object] = {
        "risky_ids": FUNDS,
        "core_id": FIRST,
        "monetary_id": MONEY,
    }
    return SA15GPT61(**(config | changes))  # type: ignore[arg-type]


def written(
    strategy: SA15GPT61, changes: Mapping[tuple[str, str], float | SignalStatus]
) -> Written:
    """Return fully usable rising-market signals plus explicit changes."""
    result: Written = {}
    for item in strategy.required_signals():
        assert isinstance(item, SignalRequest)
        for name in item.names() or ():
            value = 0.10
            if "price_over" in item.signal.signal_id:
                value = 0.05
            if "volatility" in item.signal.signal_id:
                value = 0.10 if name != MONEY else 0.01
            if "momentum" in item.signal.signal_id and name == MONEY:
                value = 0.001
            result[item.signal.signal_id, name] = value
    assert not set(changes) - set(result)
    return result | dict(changes)


@pytest.fixture
def decision(written_decision: Callable[..., StrategyContext]) -> Callable[..., StrategyContext]:
    """Return a context builder using real snapshots of written signal values."""

    def build(
        allocation: SA15GPT61,
        changes: Mapping[tuple[str, str], float | SignalStatus] | None = None,
        held: Mapping[str, float] | None = None,
        universe: tuple[str, ...] = UNIVERSE,
    ) -> StrategyContext:
        return written_decision(
            allocation,
            written(allocation, changes or {}),
            universe=universe,
            held=held,
        )

    return build


def weights(target: TargetAllocation) -> dict[str, float]:
    """Extract a concrete order target, refusing an accidental hold."""
    assert not target.hold_positions
    return dict(target.weights)


def test_mean_has_financial_units_and_zero_weight_inputs_are_optional() -> None:
    assert weighted_momentum((0.10, 0.20, 0.30, 0.40), (1, 1, 2, 0)) == pytest.approx(0.225)
    assert weighted_momentum((0.10, None), (1, 0)) == pytest.approx(0.10)
    assert weighted_momentum((0.10, None), (1, 1)) is None
    assert weighted_momentum((0.10, float("nan")), (1, 1)) is None


def test_occupied_slots_get_inverse_volatility_without_consuming_empty_slots() -> None:
    result = rotation_weights(
        {"A": 0.30, "B": 0.20, "C": -0.10},
        {"A": 0.10, "B": 0.20, "C": 0.10},
        top_k=3,
        volatility_power=1.0,
        renormalize_active=False,
    )
    assert result == pytest.approx({"A": 4 / 9, "B": 2 / 9})
    full = rotation_weights(
        {"A": 0.30, "B": 0.20},
        {"A": 0.10, "B": 0.20},
        top_k=3,
        volatility_power=1.0,
        renormalize_active=True,
    )
    assert full == pytest.approx({"A": 2 / 3, "B": 1 / 3})


def test_ties_are_deterministic_and_allocation_ignores_bad_volatility() -> None:
    args = {"top_k": 1, "volatility_power": 0.0, "renormalize_active": False}
    assert rotation_weights({"B": 1.0, "A": 1.0}, {"A": 0.10, "B": 0.10}, **args) == {"A": 1.0}
    assert rotation_weights({"A": 1.0}, {"A": float("nan")}, **args) == {}
    assert rotation_weights({"A": 0.0}, {"A": 0.1}, **args) == {}


def test_extreme_inverse_volatility_power_does_not_overflow() -> None:
    result = rotation_weights(
        {"A": 1.0, "B": 0.5},
        {"A": 0.05, "B": 0.50},
        top_k=2,
        volatility_power=10000.0,
        renormalize_active=False,
    )
    assert result == {"A": 1.0}


def test_default_signals_declare_all_assets_and_allow_one_reference_holiday() -> None:
    allocation = SA15GPT61()
    declared = allocation.required_signals()
    names = set()
    ids = []
    for item in declared:
        assert isinstance(item, SignalRequest)
        names.update(item.names() or ())
        ids.append(item.signal.signal_id)
        assert item.signal.definition()["max_age_sessions"] == 1
    assert names == {*allocation.risky_ids, allocation.monetary_id}
    assert len(ids) == len(set(ids)) == 7
    assert allocation.strategy_id == "SA15_GPT-6.1"
    json.dumps(allocation.definition())
    assert allocation.fingerprint() == SA15GPT61().fingerprint()


def test_configuration_is_immutable_and_records_sequence_copies() -> None:
    names = list(FUNDS)
    allocation = strategy(risky_ids=names)
    fingerprint = allocation.fingerprint()
    names[0] = "CHANGED"
    assert allocation.risky_ids == FUNDS
    assert allocation.fingerprint() == fingerprint
    with pytest.raises(FrozenInstanceError):
        allocation.top_k = 5  # type: ignore[misc]


@pytest.mark.parametrize(
    "changes",
    [
        {"risky_ids": ()},
        {"risky_ids": (FIRST, FIRST)},
        {"risky_ids": FIRST},
        {"risky_ids": ("",)},
        {"monetary_id": FIRST},
        {"monetary_id": ""},
        {"core_id": MONEY},
        {"momentum_lookbacks": ()},
        {"momentum_lookbacks": (21, 21)},
        {"momentum_lookbacks": (True, 63, 126, 252)},
        {"momentum_weights": (1, 2)},
        {"momentum_weights": (0, 0, 0, 0)},
        {"momentum_weights": (-1, 1, 1, 1)},
        {"momentum_weights": (float("nan"), 1, 1, 1)},
        {"momentum_weights": (True, 1, 1, 1)},
        {"top_k": True},
        {"top_k": 0},
        {"top_k": 1.5},
        {"use_trend_filter": 1},
        {"renormalize_active": 1},
        {"volatility_power": float("inf")},
        {"volatility_power": -1},
        {"target_volatility": float("nan")},
        {"target_volatility": True},
        {"target_volatility": 0.01},
        {"volatility_floor": 0.01},
        {"max_asset_weight": 1.01},
        {"max_asset_weight": -0.01},
        {"core_fraction": 1.01},
        {"core_fraction": float("nan")},
        {"rebalance_band": float("nan")},
        {"short_returns": True},
        {"short_returns": 60},
        {"short_returns": 1},
        {"long_returns": True},
        {"trend_sessions": True},
        {"trend_sessions": 1},
        {"monetary_lookback": 0},
        {"max_age_sessions": True},
        {"max_age_sessions": -1},
    ],
)
def test_invalid_configuration_is_rejected(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        strategy(**changes)


def test_three_equal_rising_funds_are_held_equally(decision) -> None:
    allocation = strategy()
    plan = allocation.plan(decision(allocation))
    assert dict(plan.weights) == pytest.approx(dict.fromkeys(FUNDS, 1 / 3))
    assert plan.scale == 1.0
    assert plan.readable == 4
    assert plan.unusable == {}
    assert len(plan.selected) == 3
    assert weights(allocation.decide(decision(allocation))) == pytest.approx(dict(plan.weights))
    with pytest.raises(TypeError):
        plan.weights[FIRST] = 0.9  # type: ignore[index]


def test_one_negative_trend_leaves_its_slot_in_money_market(decision) -> None:
    allocation = strategy()
    changes = {(allocation.trend_signal().signal_id, THIRD): -0.01}
    plan = allocation.plan(decision(allocation, changes))
    assert dict(plan.weights) == pytest.approx({FIRST: 1 / 3, SECOND: 1 / 3, MONEY: 1 / 3})
    assert THIRD not in plan.selected


def test_nonpositive_momentum_is_excluded_even_above_its_average(decision) -> None:
    allocation = strategy()
    changes = {
        (allocation.momentum_signal(window).signal_id, THIRD): -0.1
        for window in allocation.momentum_lookbacks
    }
    assert dict(allocation.plan(decision(allocation, changes)).weights) == pytest.approx(
        {FIRST: 1 / 3, SECOND: 1 / 3, MONEY: 1 / 3}
    )


def test_trend_can_be_disabled_and_zero_weight_windows_are_not_required(decision) -> None:
    allocation = strategy(use_trend_filter=False, momentum_weights=(0, 0, 0, 1))
    requests = {item.signal.signal_id for item in allocation.required_signals()}
    assert allocation.trend_signal().signal_id not in requests
    assert allocation.momentum_signal(63).signal_id not in requests
    assert dict(allocation.plan(decision(allocation)).weights) == pytest.approx(
        dict.fromkeys(FUNDS, 1 / 3)
    )


def test_core_budget_adds_to_same_tactical_name_and_risky_cap_leaves_residual(decision) -> None:
    allocation = strategy(core_fraction=0.5, max_asset_weight=0.60)
    plan = allocation.plan(decision(allocation))
    assert dict(plan.budgeted) == pytest.approx({FIRST: 0.60, SECOND: 1 / 6, THIRD: 1 / 6})
    assert plan.weights[MONEY] == pytest.approx(1 / 15)
    assert all(plan.weights[name] <= 0.60 for name in FUNDS)
    assert math.fsum(plan.weights.values()) == pytest.approx(1.0)


def test_inactive_core_budget_does_not_strengthen_tactical_funds(decision) -> None:
    allocation = strategy(core_fraction=0.5)
    changes = {(allocation.trend_signal().signal_id, FIRST): 0.0}
    plan = allocation.plan(decision(allocation, changes))
    assert dict(plan.weights) == pytest.approx({SECOND: 1 / 6, THIRD: 1 / 6, MONEY: 2 / 3})


def test_risk_control_includes_money_market_in_its_plus_one_correlation_bound(decision) -> None:
    allocation = strategy()
    changes = {(allocation.volatility_signal(20).signal_id, name): 0.30 for name in FUNDS}
    plan = allocation.plan(decision(allocation, changes))
    scale = (0.18 - 0.01) / (0.30 - 0.01)
    assert plan.scale == pytest.approx(scale)
    assert plan.weights[MONEY] == pytest.approx(1 - scale)
    risk = math.fsum(plan.weights[name] * plan.volatilities[name] for name in FUNDS)
    risk += plan.weights[MONEY] * plan.monetary_volatility
    assert risk == pytest.approx(0.18)
    assert all(0 < value <= 1 for value in plan.weights.values())
    assert math.fsum(plan.weights.values()) == pytest.approx(1.0)


def test_volatility_uses_larger_horizon_and_floor(decision) -> None:
    allocation = strategy()
    changes = {
        (allocation.volatility_signal(window).signal_id, name): value
        for name, value in ((FIRST, 0.0), (SECOND, 0.02))
        for window in (20, 60)
    }
    changes[allocation.volatility_signal(60).signal_id, THIRD] = 0.20
    plan = allocation.plan(decision(allocation, changes))
    assert dict(plan.volatilities) == pytest.approx({FIRST: 0.05, SECOND: 0.05, THIRD: 0.20})
    assert plan.budgeted[FIRST] == pytest.approx(4 / 9)
    assert plan.budgeted[THIRD] == pytest.approx(1 / 9)


@pytest.mark.parametrize(
    "signal", ["sa15_momentum_126s", "sa15_price_over_ma200", "sa15_volatility_60r"]
)
def test_missing_required_input_disables_only_its_asset_and_keeps_reason(
    decision, signal: str
) -> None:
    allocation = strategy()
    context = decision(allocation, {(signal, THIRD): SignalStatus.STALE_INPUT})
    plan = allocation.plan(context)
    assert THIRD not in plan.weights
    assert plan.unusable == {THIRD: SignalStatus.STALE_INPUT}
    assert plan.readable == 3
    target = allocation.decide(context)
    assert target.skipped == {THIRD: SignalStatus.STALE_INPUT}
    assert weights(target) == pytest.approx({FIRST: 1 / 3, SECOND: 1 / 3, MONEY: 1 / 3})


@pytest.mark.parametrize(
    "changes",
    [
        {("sa15_momentum_21s", MONEY): 0.0},
        {("sa15_momentum_21s", MONEY): -0.001},
        {("sa15_volatility_60r", MONEY): 0.02},
        {("sa15_volatility_60r", MONEY): SignalStatus.MISSING_INPUT},
    ],
)
def test_money_market_requires_positive_carry_and_strict_low_volatility(decision, changes) -> None:
    allocation = strategy()
    changed = changes | {(allocation.trend_signal().signal_id, THIRD): -0.01}
    plan = allocation.plan(decision(allocation, changed))
    assert MONEY not in plan.weights
    assert dict(plan.weights) == pytest.approx({FIRST: 1 / 3, SECOND: 1 / 3})


def test_all_inputs_missing_exits_to_cash_with_reasons(decision) -> None:
    allocation = strategy()
    changes = {key: SignalStatus.MISSING_INPUT for key in written(allocation, {})}
    target = allocation.decide(decision(allocation, changes, held={FIRST: 0.30}))
    assert weights(target) == {}
    assert dict(target.skipped) == dict.fromkeys(UNIVERSE, SignalStatus.MISSING_INPUT)


def test_target_never_buys_a_name_outside_current_trading_universe(decision) -> None:
    allocation = strategy()
    plan = allocation.plan(decision(allocation, universe=(FIRST, SECOND, MONEY)))
    assert dict(plan.weights) == pytest.approx({FIRST: 1 / 3, SECOND: 1 / 3, MONEY: 1 / 3})


def test_band_keeps_small_drifts_but_never_delays_an_exit(decision) -> None:
    allocation = strategy()
    held = {FIRST: 0.35, SECOND: 0.32, THIRD: 0.33}
    assert allocation.decide(decision(allocation, held=held)).hold_positions
    changes = {(allocation.trend_signal().signal_id, THIRD): -0.01}
    assert THIRD not in weights(allocation.decide(decision(allocation, changes, held=held)))


def test_band_never_keeps_a_cap_or_estimated_risk_breach(decision) -> None:
    capped = strategy(max_asset_weight=0.30)
    cap_target = capped.decide(
        decision(capped, held={FIRST: 0.31, SECOND: 0.30, THIRD: 0.30, MONEY: 0.09})
    )
    assert weights(cap_target)[FIRST] == pytest.approx(0.30)
    allocation = strategy()
    changes = {(allocation.volatility_signal(20).signal_id, name): 0.30 for name in FUNDS}
    context = decision(
        allocation, changes, held={FIRST: 0.20, SECOND: 0.20, THIRD: 0.20, MONEY: 0.40}
    )
    assert not allocation.decide(context).hold_positions


def test_real_signals_ignore_future_close_and_refuse_a_missing_internal_session(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    make_context: Callable[[MarketDataReader, datetime], SignalContext],
    make_decision: Callable[..., StrategyContext],
    xpar: TradingCalendar,
    evening: Callable[[date], datetime],
) -> None:
    allocation = strategy()
    days = [session.session_date for session in xpar.sessions(date(2026, 1, 5), date(2026, 12, 31))]
    paths = {
        name: {
            day: 100
            * math.exp(
                (0.0005 if name != MONEY else 0.0001) * index
                + (0.002 * math.sin(index / 7) if name != MONEY else 0.0)
            )
            for index, day in enumerate(days)
        }
        for name in UNIVERSE
    }
    instant = evening(days[-2])

    def evaluate(
        *, future: bool, hole: bool = False
    ) -> tuple[dict[str, float], dict[str, SignalStatus]]:
        bars = {}
        for name, series in paths.items():
            seen = dict(series)
            if future:
                seen[days[-1]] = 1_000_000.0
            else:
                del seen[days[-1]]
            if hole and name == THIRD:
                del seen[days[-20]]
            bars[name] = make_bars(name, xpar, seen)
        signal_context = make_context(make_market(bars), instant)
        requests = [item.resolved(days[-2]) for item in allocation.required_signals()]
        snapshot = SignalEngine().compute(signal_context, requests, list(UNIVERSE))
        context = make_decision(signal_context, snapshot, universe=UNIVERSE)
        plan = allocation.plan(context)
        return dict(plan.weights), dict(plan.unusable)

    clean_weights, reasons = evaluate(future=False)
    assert reasons == {}
    assert clean_weights == evaluate(future=True)[0]
    assert set(clean_weights) == set(FUNDS)
    damaged_weights, refusals = evaluate(future=True, hole=True)
    assert THIRD not in damaged_weights
    assert refusals == {THIRD: SignalStatus.NON_CONSECUTIVE_HISTORY}
