"""SA16: trend-breadth equity, trend-breadth hedge, money market, and the book kept on a gap."""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping
from datetime import date

import pytest

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.data.instruments import AssetType, DataType, Instrument, InstrumentRegistry
from quant_backtester.signals.engine import SignalEngine, SignalRequest
from quant_backtester.signals.types import SignalStatus
from quant_backtester.strategies.SA16_regime_allocation import RegimePlan, SA16RegimeAllocation

EQUITY, HEDGE, GAUGE, MONEY = "ETF_EU", "ETF_OTHER", "IDX_US", "SA16_MONEY"
UNIVERSE = (EQUITY, HEDGE, MONEY)
Written = dict[tuple[str, str], float | SignalStatus]


@pytest.fixture
def instruments(instruments: InstrumentRegistry) -> InstrumentRegistry:
    """Add a Paris money-market fund to the shared offline registry."""
    return InstrumentRegistry(
        [
            *instruments,
            Instrument(
                id=MONEY,
                name=MONEY,
                asset_type=AssetType.ETF,
                data_type=DataType.BAR,
                currency="EUR",
                primary_source="YAHOO",
                source_symbol=f"{MONEY}.PA",
                tradable=True,
                calendar_id="XPAR",
                first_session=date(2026, 1, 5),
            ),
        ]
    )


def strategy(**changes: object) -> SA16RegimeAllocation:
    """Return the rule on the test funds, other parameters as declared."""
    defaults = {"equity_id": EQUITY, "gauge_id": GAUGE, "hedge_id": HEDGE, "monetary_id": MONEY}
    return SA16RegimeAllocation(**(defaults | changes))  # type: ignore[arg-type]


def returns(
    allocation: SA16RegimeAllocation,
    gauge: tuple[float, ...],
    hedge: tuple[float, ...] = (0.01, 0.01, 0.01, 0.01),
    carry: float | SignalStatus = 0.001,
) -> Written:
    """Write one endpoint return per declared horizon, in declared order."""
    written: Written = {}
    for window, value in zip(allocation.trend_lookbacks, gauge, strict=True):
        written[allocation.momentum(window).signal_id, GAUGE] = value
    if allocation.hedge_id is not None:
        for window, value in zip(allocation.hedge_lookbacks, hedge, strict=True):
            written[allocation.momentum(window).signal_id, HEDGE] = value
    written[allocation.momentum(allocation.monetary_lookback).signal_id, MONEY] = carry
    return written


@pytest.fixture
def decision(written_decision: Callable[..., StrategyContext]) -> Callable[..., StrategyContext]:
    """Build the decision a strategy sees on written values and a held book."""

    def build(
        allocation: SA16RegimeAllocation,
        written: Written,
        held: Mapping[str, float] | None = None,
    ) -> StrategyContext:
        return written_decision(allocation, written, universe=UNIVERSE, held=held)

    return build


def test_breadth_sizes_equity_then_hedge_then_money_by_hand(decision) -> None:
    allocation = strategy()
    # three of four gauge horizons up: equity 0.75; half the hedge horizons up:
    # (1 - 0.75) * 0.5 = 0.125 of gold; the remaining 0.125 to the money market.
    written = returns(allocation, (0.02, -0.01, 0.03, 0.10), hedge=(0.01, -0.02, 0.0, 0.05))
    plan = allocation.plan(decision(allocation, written))
    assert plan.equity_score == 0.75
    assert plan.hedge_score == 0.5
    assert dict(plan.weights) == pytest.approx({EQUITY: 0.75, HEDGE: 0.125, MONEY: 0.125})


def test_a_zero_return_is_not_positive(decision) -> None:
    allocation = strategy()
    plan = allocation.plan(decision(allocation, returns(allocation, (0.0, 0.0, 0.0, 0.01))))
    assert plan.equity_score == 0.25


def test_full_trend_holds_only_equity_and_a_bear_hands_everything_to_a_trending_hedge(
    decision,
) -> None:
    allocation = strategy()
    bull = allocation.plan(decision(allocation, returns(allocation, (0.01,) * 4)))
    assert dict(bull.weights) == {EQUITY: 1.0}
    bear = allocation.plan(decision(allocation, returns(allocation, (-0.01,) * 4)))
    assert dict(bear.weights) == {HEDGE: 1.0}


@pytest.mark.parametrize("carry", [0.0, -0.001])
def test_residual_stays_in_cash_unless_the_money_market_return_is_strictly_positive(
    decision, carry
) -> None:
    allocation = strategy()
    written = returns(allocation, (-0.01,) * 4, hedge=(-0.01,) * 4, carry=carry)
    plan = allocation.plan(decision(allocation, written))
    assert dict(plan.weights) == {}
    assert allocation.decide(decision(allocation, written)).weights == {}


def test_without_hedge_the_residual_goes_to_the_money_market(decision) -> None:
    allocation = strategy(hedge_id=None)
    assert all(HEDGE not in (item.names() or ()) for item in allocation.required_signals())
    plan = allocation.plan(decision(allocation, returns(allocation, (0.01, 0.01, -0.01, -0.01))))
    assert plan.hedge_score == 0.0
    assert dict(plan.weights) == pytest.approx({EQUITY: 0.5, MONEY: 0.5})


@pytest.mark.parametrize(
    ("name", "status"),
    [
        (GAUGE, SignalStatus.STALE_INPUT),
        (HEDGE, SignalStatus.MISSING_INPUT),
        (MONEY, SignalStatus.INSUFFICIENT_HISTORY),
    ],
)
def test_an_unreadable_input_keeps_the_book_and_records_why(decision, name, status) -> None:
    allocation = strategy()
    written = returns(allocation, (-0.01,) * 4, hedge=(-0.01,) * 4)
    key = next(key for key in written if key[1] == name)
    written[key] = status
    held = {EQUITY: 0.9}
    plan = allocation.plan(decision(allocation, written, held))
    assert not plan.complete
    assert plan.unusable[name] is status
    target = allocation.decide(decision(allocation, written, held))
    assert target.hold_positions
    assert target.skipped[name] is status


def test_a_book_of_several_lines_is_kept_when_the_hedge_is_unreadable(decision) -> None:
    allocation = strategy()
    written = returns(allocation, (0.01, 0.01, -0.01, -0.01))
    written[allocation.momentum(21).signal_id, HEDGE] = SignalStatus.MISSING_INPUT
    held = {EQUITY: 0.5, HEDGE: 0.4}
    plan = allocation.plan(decision(allocation, written, held))
    assert plan.unusable == {HEDGE: SignalStatus.MISSING_INPUT}
    target = allocation.decide(decision(allocation, written, held))
    assert target.hold_positions
    assert dict(target.weights) == pytest.approx(held)
    # A line kept is not a line skipped: the record holds it, the plan says why.
    assert HEDGE not in target.skipped


def test_small_drift_is_held_and_a_complete_exit_is_always_sent(decision) -> None:
    allocation = strategy(rebalance_band=0.10)
    written = returns(allocation, (0.01,) * 4)
    kept = allocation.decide(decision(allocation, written, {EQUITY: 0.93}))
    assert kept.hold_positions
    exit_hedge = allocation.decide(decision(allocation, written, {EQUITY: 0.97, HEDGE: 0.02}))
    assert not exit_hedge.hold_positions
    assert dict(exit_hedge.weights) == {EQUITY: 1.0}


def test_definition_is_serialisable_and_requests_are_unique() -> None:
    allocation = SA16RegimeAllocation()
    requests = allocation.required_signals()
    assert len({request.signal.signal_id for request in requests}) == len(requests)
    assert allocation.trend_lookbacks == (21, 63, 126, 252)
    json.dumps(allocation.definition())


@pytest.mark.parametrize(
    "changes",
    [
        {"trend_lookbacks": ()},
        {"trend_lookbacks": (21, 21)},
        {"trend_lookbacks": (0, 21)},
        {"trend_lookbacks": "21"},
        {"hedge_lookbacks": (True, 63)},
        {"hedge_id": EQUITY},
        {"monetary_id": EQUITY},
        {"monetary_lookback": 0},
        {"rebalance_band": 1.5},
        {"max_age_sessions": -1},
    ],
)
def test_invalid_parameters_are_rejected(changes) -> None:
    with pytest.raises(ValueError):
        strategy(**changes)


def test_real_signals_ignore_future_prices(
    make_market, make_bars, make_context, make_decision, evening, xpar, xnys
) -> None:
    allocation = strategy(trend_lookbacks=(2, 3, 5), hedge_lookbacks=(2, 4), monetary_lookback=2)
    paris_days = [day.session_date for day in xpar.sessions(date(2026, 8, 3), date(2026, 9, 15))]
    us_days = [day.session_date for day in xnys.sessions(date(2026, 8, 3), date(2026, 9, 15))]
    decided = paris_days[-2]

    def evaluate(future: bool) -> RegimePlan:
        bars = {}
        for name, slope, calendar, days in (
            (EQUITY, 0.002, xpar, paris_days),
            (HEDGE, -0.001, xpar, paris_days),
            (MONEY, 0.0001, xpar, paris_days),
            (GAUGE, 0.003, xnys, us_days),
        ):
            kept = [day for day in days if future or day <= decided]
            closes = {day: 100 * math.exp(index * slope) for index, day in enumerate(kept)}
            if future:
                for day in kept:
                    if day > decided:
                        closes[day] = 0.01 if name == GAUGE else 1_000_000.0
            bars[name] = make_bars(name, calendar, closes)
        context = make_context(make_market(bars), evening(decided))
        requests = [request.resolved(decided) for request in allocation.required_signals()]
        snapshot = SignalEngine().compute(context, requests, list(UNIVERSE))
        return allocation.plan(make_decision(context, snapshot, universe=UNIVERSE))

    before, after = evaluate(False), evaluate(True)
    assert before.complete and after.complete
    assert (before.equity_score, before.hedge_score) == (after.equity_score, after.hedge_score)
    assert before.carry == after.carry
    assert dict(before.weights) == dict(after.weights)
    assert before.equity_score == 1.0
    assert before.hedge_score == 0.0
    assert dict(before.weights) == {EQUITY: 1.0}


def test_requests_name_the_gauge_not_the_traded_fund() -> None:
    allocation = strategy()
    gauges = {
        request.signal.signal_id: request.names()
        for request in allocation.required_signals()
        if isinstance(request, SignalRequest)
    }
    assert all(EQUITY not in (names or ()) for names in gauges.values())
    assert any(GAUGE in (names or ()) for names in gauges.values())
