"""SA16 risk budget: inverse-volatility weights scaled by a declared budget of risk."""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping
from datetime import date

import pytest

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.signals.engine import SignalEngine
from quant_backtester.signals.types import SignalStatus
from quant_backtester.strategies.SA16_risk_budget import BudgetPlan, SA16RiskBudget

GROWTH, HEDGE = "ETF_EU", "ETF_OTHER"
UNIVERSE = (GROWTH, HEDGE)
Written = dict[tuple[str, str], float | SignalStatus]


def strategy(**changes: object) -> SA16RiskBudget:
    """Return the rule on the test funds, other parameters as declared."""
    return SA16RiskBudget(**({"growth_id": GROWTH, "hedge_id": HEDGE} | changes))  # type: ignore[arg-type]


def vols(
    allocation: SA16RiskBudget, growth: float | SignalStatus, hedge: float | SignalStatus
) -> Written:
    """Write the volatility of each fund."""
    signal_id = allocation.volatility().signal_id
    return {(signal_id, GROWTH): growth, (signal_id, HEDGE): hedge}


@pytest.fixture
def decision(written_decision: Callable[..., StrategyContext]) -> Callable[..., StrategyContext]:
    """Build the decision a strategy sees on written values and a held book."""

    def build(
        allocation: SA16RiskBudget, written: Written, held: Mapping[str, float] | None = None
    ) -> StrategyContext:
        return written_decision(allocation, written, universe=UNIVERSE, held=held)

    return build


def test_budgeted_inverse_volatility_by_hand(decision) -> None:
    allocation = strategy(growth_risk_budget=0.75)
    # 0.75 / 0.20 = 3.75 and 0.25 / 0.10 = 2.5: weights 0.6 and 0.4
    plan = allocation.plan(decision(allocation, vols(allocation, 0.20, 0.10)))
    assert dict(plan.weights) == pytest.approx({GROWTH: 0.6, HEDGE: 0.4})
    assert math.fsum(plan.weights.values()) == pytest.approx(1.0)


def test_risk_contributions_follow_the_budget_when_correlation_is_zero(decision) -> None:
    allocation = strategy(growth_risk_budget=0.8)
    plan = allocation.plan(decision(allocation, vols(allocation, 0.30, 0.12)))
    risk = {name: plan.weights[name] * plan.volatilities[name] for name in UNIVERSE}
    assert risk[GROWTH] / math.fsum(risk.values()) == pytest.approx(0.8)


def test_a_flat_series_is_floored(decision) -> None:
    allocation = strategy(volatility_floor=0.05, growth_risk_budget=0.5)
    plan = allocation.plan(decision(allocation, vols(allocation, 0.0, 0.05)))
    assert dict(plan.weights) == pytest.approx({GROWTH: 0.5, HEDGE: 0.5})


@pytest.mark.parametrize("side", [GROWTH, HEDGE])
def test_an_unreadable_volatility_keeps_the_book(decision, side) -> None:
    allocation = strategy()
    written = vols(allocation, 0.2, 0.1)
    written[allocation.volatility().signal_id, side] = SignalStatus.NON_CONSECUTIVE_HISTORY
    held = {GROWTH: 0.7, HEDGE: 0.3}
    plan = allocation.plan(decision(allocation, written, held))
    assert dict(plan.weights) == {}
    assert plan.unusable[side] is SignalStatus.NON_CONSECUTIVE_HISTORY
    target = allocation.decide(decision(allocation, written, held))
    assert target.hold_positions
    assert dict(target.weights) == pytest.approx(held)


def test_band_holds_small_drift_and_rebalances_a_large_one(decision) -> None:
    allocation = strategy(growth_risk_budget=0.75, rebalance_band=0.05)
    written = vols(allocation, 0.20, 0.10)
    kept = allocation.decide(decision(allocation, written, {GROWTH: 0.63, HEDGE: 0.37}))
    assert kept.hold_positions
    rebalanced = allocation.decide(decision(allocation, written, {GROWTH: 0.68, HEDGE: 0.32}))
    assert not rebalanced.hold_positions
    assert dict(rebalanced.weights) == pytest.approx({GROWTH: 0.6, HEDGE: 0.4})


def test_definition_is_serialisable() -> None:
    allocation = SA16RiskBudget()
    assert allocation.growth_id == "ETF_US_TECH"
    json.dumps(allocation.definition())


@pytest.mark.parametrize(
    "changes",
    [
        {"hedge_id": GROWTH},
        {"growth_risk_budget": 0.0},
        {"growth_risk_budget": 1.0},
        {"growth_risk_budget": 1.2},
        {"volatility_returns": 0},
        {"max_span_sessions": 0},
        {"volatility_floor": 0.0},
        {"rebalance_band": -0.1},
        {"max_age_sessions": -1},
    ],
)
def test_invalid_parameters_are_rejected(changes) -> None:
    with pytest.raises(ValueError):
        strategy(**changes)


def test_real_signals_ignore_future_prices(
    make_market, make_bars, make_context, make_decision, evening, xpar
) -> None:
    allocation = strategy(volatility_returns=5)
    days = [day.session_date for day in xpar.sessions(date(2026, 8, 3), date(2026, 9, 15))]
    decided = days[-2]

    def evaluate(future: bool) -> BudgetPlan:
        bars = {}
        for name, amplitude in ((GROWTH, 0.02), (HEDGE, 0.01)):
            kept = [day for day in days if future or day <= decided]
            closes, price = {}, 100.0
            for index, day in enumerate(kept):
                price *= 1.0 + (amplitude if index % 2 else -amplitude)
                closes[day] = price if day <= decided else 1_000_000.0
            bars[name] = make_bars(name, xpar, closes)
        context = make_context(make_market(bars), evening(decided))
        requests = [request.resolved(decided) for request in allocation.required_signals()]
        snapshot = SignalEngine().compute(context, requests, list(UNIVERSE))
        return allocation.plan(make_decision(context, snapshot, universe=UNIVERSE))

    before, after = evaluate(False), evaluate(True)
    assert before.complete and after.complete
    assert dict(before.volatilities) == dict(after.volatilities)
    assert dict(before.weights) == dict(after.weights)
    # the growth fund moves twice as much: with b = 0.75 it holds 0.75/2 / (0.75/2 + 0.25)
    assert before.weights[GROWTH] == pytest.approx(0.6, rel=0.02)
