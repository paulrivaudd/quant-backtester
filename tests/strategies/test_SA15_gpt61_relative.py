"""Core fallback, exact log-relative scores and turnover buffering without backtests."""

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
from quant_backtester.strategies.SA15_gpt61_relative import (
    RelativeMomentumPlan,
    SA15RelativeMomentum,
    buffered_selection,
)

CORE, FIRST, SECOND, MONEY = "ETF_EU", "ETF_OTHER", "RELATIVE_SECOND", "RELATIVE_MONEY"
SATELLITES = (FIRST, SECOND)
UNIVERSE = (CORE, *SATELLITES, MONEY)
Written = dict[tuple[str, str], float | SignalStatus]


@pytest.fixture
def instruments(instruments: InstrumentRegistry) -> InstrumentRegistry:
    """Add two registered EUR funds to the shared synthetic market."""
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


def strategy(**changes: object) -> SA15RelativeMomentum:
    """Build a core and two satellites over real registered test instruments."""
    fields: dict[str, object] = {
        "core_id": CORE,
        "satellite_ids": SATELLITES,
        "monetary_id": MONEY,
    }
    return SA15RelativeMomentum(**(fields | changes))  # type: ignore[arg-type]


def written(allocation: SA15RelativeMomentum, changes: Mapping) -> Written:
    """Write stable returns for each declared endpoint signal."""
    returns = {CORE: 0.10, FIRST: 0.20, SECOND: 0.15, MONEY: 0.001}
    values: Written = {}
    for item in allocation.required_signals():
        assert isinstance(item, SignalRequest)
        for name in item.names() or ():
            values[item.signal.signal_id, name] = returns[name]
    assert not set(changes) - set(values)
    return values | dict(changes)


def set_return(allocation: SA15RelativeMomentum, name: str, value: float | SignalStatus) -> Written:
    """Change all directional windows of a fund while preserving other inputs."""
    return {
        (allocation.momentum_signal(window).signal_id, name): value
        for window, weight in zip(
            allocation.momentum_lookbacks, allocation.momentum_weights, strict=True
        )
        if weight > 0.0
    }


@pytest.fixture
def decision(written_decision: Callable[..., StrategyContext]) -> Callable[..., StrategyContext]:
    """Build one evening context from written signals and actual held weights."""

    def build(
        allocation: SA15RelativeMomentum,
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


def test_defaults_identify_the_new_round_and_declare_no_defensive_or_volatility_inputs() -> None:
    allocation = SA15RelativeMomentum()
    assert allocation.strategy_id == "SA15_GPT-6.1_R2"
    assert allocation.core_fraction == 0.5
    assert allocation.top_k == 1
    assert not allocation.crash_guard_enabled()
    requests = allocation.required_signals()
    assert len(requests) == 3
    assert all(allocation.monetary_id not in (item.names() or ()) for item in requests)
    assert not any("volatility" in item.signal.signal_id for item in requests)
    json.dumps(allocation.definition())


def test_relative_score_is_the_weighted_difference_of_log_returns(decision) -> None:
    allocation = strategy(momentum_weights=(1, 2, 0))
    changes = {
        (allocation.momentum_signal(63).signal_id, FIRST): 0.30,
        (allocation.momentum_signal(126).signal_id, FIRST): 0.40,
        (allocation.momentum_signal(126).signal_id, CORE): 0.20,
    }
    plan = allocation.plan(decision(allocation, changes))
    expected = (
        (math.log1p(0.30) - math.log1p(0.10)) + 2 * (math.log1p(0.40) - math.log1p(0.20))
    ) / 3
    assert plan.scores[FIRST] == pytest.approx(expected)
    assert plan.absolute_scores[FIRST] == pytest.approx(
        (math.log1p(0.30) + 2 * math.log1p(0.40)) / 3
    )
    assert dict(plan.weights) == {FIRST: 0.5, CORE: 0.5}
    assert plan.selected == (FIRST,)


def test_equal_momentum_or_no_advantage_leaves_every_slot_in_the_core(decision) -> None:
    allocation = strategy()
    changes = set_return(allocation, FIRST, 0.10) | set_return(allocation, SECOND, 0.05)
    plan = allocation.plan(decision(allocation, changes))
    assert plan.selected == ()
    assert plan.scores[FIRST] == 0.0
    assert dict(plan.weights) == {CORE: 1.0}


def test_absolute_filter_only_gates_satellites_and_never_the_core(decision) -> None:
    allocation = strategy()
    changes = set_return(allocation, CORE, -0.20)
    changes |= set_return(allocation, FIRST, -0.10) | set_return(allocation, SECOND, -0.15)
    assert dict(allocation.plan(decision(allocation, changes)).weights) == {CORE: 1.0}
    ungated = strategy(absolute_filter=False)
    assert dict(ungated.plan(decision(ungated, changes)).weights) == {CORE: 0.5, FIRST: 0.5}


def test_missing_or_capped_satellite_slots_return_their_capital_to_the_core(decision) -> None:
    allocation = strategy(top_k=2)
    changes = set_return(allocation, SECOND, SignalStatus.MISSING_INPUT)
    plan = allocation.plan(decision(allocation, changes))
    assert dict(plan.weights) == {FIRST: 0.25, CORE: 0.75}
    assert plan.skipped == {SECOND: SignalStatus.MISSING_INPUT}
    assert plan.readable == 2
    capped = strategy(top_k=2, satellite_cap=0.10)
    assert dict(capped.plan(decision(capped)).weights) == {FIRST: 0.10, SECOND: 0.10, CORE: 0.80}


def test_missing_core_targets_cash_and_records_the_signal_reason(decision) -> None:
    allocation = strategy()
    changes = {(allocation.momentum_signal(63).signal_id, CORE): SignalStatus.STALE_INPUT}
    context = decision(allocation, changes, held={CORE: 0.5, FIRST: 0.5})
    plan = allocation.plan(context)
    assert dict(plan.weights) == {}
    target = allocation.decide(context)
    assert not target.hold_positions
    assert dict(target.weights) == {}
    assert target.skipped[CORE] is SignalStatus.STALE_INPUT


def test_buffer_keeps_a_qualifying_incumbent_until_the_entrant_advantage_is_large(decision) -> None:
    allocation = strategy()
    held = {CORE: 0.5, SECOND: 0.5}
    close_scores = set_return(allocation, SECOND, 0.19)
    context = decision(allocation, close_scores, held)
    assert allocation.plan(context).selected == (SECOND,)
    assert allocation.decide(context).hold_positions
    large_gap = close_scores | set_return(allocation, FIRST, 0.25)
    context = decision(allocation, large_gap, held)
    assert allocation.plan(context).selected == (FIRST,)
    assert not allocation.decide(context).hold_positions
    assert dict(allocation.decide(context).weights) == {CORE: 0.5, FIRST: 0.5}


def test_buffer_never_keeps_an_ineligible_incumbent(decision) -> None:
    allocation = strategy(switch_buffer=1.0)
    changes = set_return(allocation, SECOND, 0.05)
    plan = allocation.plan(decision(allocation, changes, held={CORE: 0.5, SECOND: 0.5}))
    assert plan.selected == (FIRST,)


def test_multiple_slots_and_ties_are_deterministic() -> None:
    scores = {"C": 0.09, "B": 0.10, "A": 0.10}
    assert buffered_selection(scores, {}, top_k=2, switch_buffer=0.02) == ("A", "B")
    assert buffered_selection(scores, {"C": 0.2}, top_k=2, switch_buffer=0.02) == ("C", "A")
    assert buffered_selection({}, {}, top_k=2, switch_buffer=0.02) == ()


def test_small_weight_drifts_are_kept_but_a_satellite_cap_breach_is_rebalanced(decision) -> None:
    allocation = strategy()
    assert allocation.decide(decision(allocation, held={CORE: 0.53, FIRST: 0.47})).hold_positions
    capped = strategy(satellite_cap=0.45)
    target = capped.decide(decision(capped, held={CORE: 0.54, FIRST: 0.46}))
    assert not target.hold_positions
    assert dict(target.weights) == {CORE: 0.55, FIRST: 0.45}


def test_default_crash_guard_is_disabled_even_after_a_severe_core_fall(decision) -> None:
    allocation = strategy()
    changes = {}
    for name in (CORE, FIRST, SECOND):
        changes |= set_return(allocation, name, -0.90)
    plan = allocation.plan(decision(allocation, changes))
    assert not plan.crash_guard_active
    assert dict(plan.weights) == {CORE: 1.0}


@pytest.mark.parametrize("carry,expected", [(0.001, {CORE: 0.4, MONEY: 0.6}), (0.0, {CORE: 0.4})])
def test_enabled_crash_guard_uses_positive_monetary_carry_or_cash(
    decision, carry, expected
) -> None:
    allocation = strategy(
        core_crash_threshold=-0.20, core_crash_lookback=21, defensive_fraction=0.60
    )
    changes = {
        (allocation.momentum_signal(21, 0).signal_id, CORE): -0.20,
        (allocation.momentum_signal(21, 0).signal_id, MONEY): carry,
    }
    plan = allocation.plan(decision(allocation, changes))
    assert plan.crash_guard_active
    assert plan.selected == ()
    assert dict(plan.weights) == expected


def test_missing_enabled_core_crash_input_fails_closed(decision) -> None:
    allocation = strategy(core_crash_threshold=-0.20, core_crash_lookback=21)
    changes = {(allocation.momentum_signal(21, 0).signal_id, CORE): SignalStatus.MISSING_INPUT}
    plan = allocation.plan(decision(allocation, changes))
    assert dict(plan.weights) == {}
    assert plan.skipped[CORE] is SignalStatus.MISSING_INPUT


def test_empty_satellite_universe_core_only_and_configuration_immutability(decision) -> None:
    names = list(SATELLITES)
    allocation = strategy(satellite_ids=names)
    fingerprint = allocation.fingerprint()
    names.clear()
    assert allocation.fingerprint() == fingerprint
    with pytest.raises(FrozenInstanceError):
        allocation.core_fraction = 0.25  # type: ignore[misc]
    core_only = strategy(satellite_ids=())
    assert dict(core_only.plan(decision(core_only)).weights) == {CORE: 1.0}


@pytest.mark.parametrize(
    "changes",
    [
        {"satellite_ids": (FIRST, FIRST)},
        {"satellite_ids": FIRST},
        {"satellite_ids": (CORE,)},
        {"monetary_id": CORE},
        {"core_id": ""},
        {"top_k": True},
        {"top_k": 0},
        {"momentum_lookbacks": ()},
        {"momentum_lookbacks": (63, 63, 252)},
        {"momentum_lookbacks": (True, 126, 252)},
        {"momentum_weights": (1, 1)},
        {"momentum_weights": (0, 0, 0)},
        {"momentum_weights": (True, 1, 1)},
        {"momentum_weights": (float("nan"), 1, 1)},
        {"skip_recent_sessions": 63},
        {"skip_recent_sessions": True},
        {"core_fraction": -0.01},
        {"core_fraction": 1.01},
        {"switch_buffer": float("nan")},
        {"switch_buffer": -0.01},
        {"absolute_filter": 1},
        {"rebalance_band": True},
        {"satellite_cap": 1.01},
        {"core_crash_lookback": True},
        {"core_crash_threshold": float("nan")},
        {"core_crash_threshold": 0.01},
        {"defensive_fraction": 1.01},
        {"max_age_sessions": True},
    ],
)
def test_invalid_configuration_is_refused(changes) -> None:
    with pytest.raises(ValueError):
        strategy(**changes)


def test_real_endpoint_signals_and_allocation_ignore_every_future_close(
    make_market,
    make_bars,
    make_context,
    make_decision,
    evening,
    xpar,
) -> None:
    days = [session.session_date for session in xpar.sessions(date(2026, 9, 1), date(2026, 9, 15))]
    allocation = strategy(momentum_lookbacks=(3, 5, 7))

    def evaluate(future: bool) -> RelativeMomentumPlan:
        slopes = {CORE: 0.001, FIRST: 0.003, SECOND: -0.001}
        bars = {}
        for name, slope in slopes.items():
            closes = {
                day: 100 * math.exp(index * slope)
                for index, day in enumerate(days if future else days[:-1])
            }
            if future:
                closes[days[-1]] = 0.01 if name == FIRST else 1_000_000.0
            bars[name] = make_bars(name, xpar, closes)
        context = make_context(make_market(bars), evening(days[-2]))
        requests = [item.resolved(days[-2]) for item in allocation.required_signals()]
        snapshot = SignalEngine().compute(context, requests, list(UNIVERSE))
        decision = make_decision(context, snapshot, universe=UNIVERSE)
        return allocation.plan(decision)

    before, after = evaluate(False), evaluate(True)
    assert before.skipped == after.skipped == {}
    assert dict(before.scores) == dict(after.scores)
    assert dict(before.weights) == dict(after.weights) == {CORE: 0.5, FIRST: 0.5}
    assert math.fsum(before.weights.values()) <= 1.0
    assert all(weight >= 0 for weight in before.weights.values())
