"""Where the gap between the two books went, and what a run had to make do on."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

import pytest

from quant_backtester.analytics.attribution import CostAttribution, RunQuality
from quant_backtester.backtest.records import BacktestRecord
from quant_backtester.backtest.result import BacktestResult
from quant_backtester.execution.fills import ExecutionReject, ExecutionRejectReason
from quant_backtester.portfolio.allocation import ConstrainedTarget, PortfolioDecision
from quant_backtester.portfolio.holdings import Holding
from quant_backtester.portfolio.targets import TargetAllocation

RunBuilder = Callable[..., BacktestResult]
ResultBuilder = Callable[..., BacktestResult]


def test_the_three_terms_are_added_up_and_kept_apart(run: RunBuilder) -> None:
    """A commission and a spread are not the same problem, so they are not one number.

    Sixty-five cheap rebalancings and one expensive trade cost the same and
    call for opposite fixes; only the split says which happened.
    """
    result = run(
        [100.0, 99.0, 98.0],
        commission=[0.0, 1.0, 2.0],
        market_cost=[0.0, 0.5, 0.25],
    )

    costs = CostAttribution.of(result)

    assert costs.commission == pytest.approx(3.0)
    assert costs.market_cost == pytest.approx(0.75)
    assert costs.spread_cost + costs.slippage_cost == pytest.approx(costs.market_cost)
    assert costs.total == pytest.approx(3.75)


def test_the_drag_is_the_distance_between_the_two_books(run: RunBuilder) -> None:
    """The costs, in the unit a return is read in."""
    result = run([100.0, 112.0], gross=[100.0, 117.0])

    assert CostAttribution.of(result).drag == pytest.approx(0.05)


def test_the_share_of_the_gross_return_the_costs_took(run: RunBuilder) -> None:
    """Seventeen gross, twelve net: costs took five of the seventeen."""
    result = run([100.0, 112.0], gross=[100.0, 117.0])

    assert CostAttribution.of(result).cost_share_of_gross == pytest.approx(5.0 / 17.0)


def test_a_losing_gross_book_has_no_such_share(run: RunBuilder) -> None:
    """A percentage of a loss reads like a good number and means nothing."""
    result = run([100.0, 88.0], gross=[100.0, 90.0])

    assert CostAttribution.of(result).cost_share_of_gross is None


def test_only_the_sessions_that_traded_are_rebalancings(run: RunBuilder) -> None:
    """A strategy that keeps its book pays nothing on the sessions it does nothing."""
    result = run(
        [100.0, 100.0, 100.0, 100.0],
        traded_value=[0.0, 50.0, 0.0, 30.0],
        commission=[0.0, 1.0, 0.0, 1.0],
    )

    costs = CostAttribution.of(result)

    assert costs.rebalancings == 2
    assert costs.average_cost_per_rebalancing == pytest.approx(1.0)


def test_a_run_that_never_traded_has_no_average(run: RunBuilder) -> None:
    """Dividing by no rebalancing would be a number about nothing."""
    costs = CostAttribution.of(run([100.0, 101.0]))

    assert costs.rebalancings == 0
    assert costs.average_cost_per_rebalancing is None
    assert costs.turnover == 0.0


def test_turnover_is_what_changed_hands_against_what_was_held(run: RunBuilder) -> None:
    """A book of 100 that exchanged 200 turned over twice."""
    result = run([100.0, 100.0, 100.0], traded_value=[0.0, 100.0, 100.0])

    costs = CostAttribution.of(result)

    assert costs.turnover == pytest.approx(2.0)
    assert costs.annual_turnover == pytest.approx(2.0 * 365.25 / 2)


def test_turnover_a_year_needs_a_run_that_covers_time(run: RunBuilder) -> None:
    """One session is not a rate."""
    assert CostAttribution.of(run([100.0], traded_value=[10.0])).annual_turnover is None


def test_a_run_says_where_it_was_stretched(run: RunBuilder) -> None:
    """The caveats belong beside the figures, not in a log nobody opens."""
    result = run(
        [100.0, 100.0, 100.0],
        priced_from_earlier=[(), ("ETF_EU",), ()],
        untradable=[(), (), ("IDX_US",)],
    )

    quality = RunQuality.of(result)

    assert quality.sessions == 3
    assert quality.decisions == 3
    assert quality.estimated_valuations == 1
    assert quality.sessions_without_execution_price == 1
    assert quality.rejects == 1
    assert dict(quality.rejects_by_reason) == {"NO_EXECUTION_PRICE": 1}
    assert quality.sessions_with_nothing_to_choose == 0


def test_a_run_with_nothing_to_choose_from_is_not_a_flat_strategy(run: RunBuilder) -> None:
    """A universe that went empty is a data hole, and reads as one."""
    quality = RunQuality.of(run([100.0, 100.0], considered=0))

    assert quality.sessions_with_nothing_to_choose == 2


def test_a_purchase_the_cash_could_not_carry_is_a_caveat(run: RunBuilder) -> None:
    """Expected on the session a strategy goes fully invested, and telling in bulk.

    One session is the entry paying for itself. A run where most sessions are
    here is a strategy asking, day after day, for more than it holds.
    """
    result = run([100.0, 100.0, 100.0], unfunded=[(), ("ETF_EU",), ()])

    quality = RunQuality.of(result)

    assert quality.insufficient_cash_adjustments == 1
    assert dict(quality.rejects_by_reason) == {"INSUFFICIENT_CASH": 1}


def test_orders_fills_and_rejects_are_counted(run: RunBuilder) -> None:
    """What was sent, what was done, what was refused - three numbers, not one."""
    result = run(
        [100.0, 100.0, 100.0],
        traded_value=[0.0, 50.0, 30.0],
        unfunded=[(), (), ("ETF_EU",)],
    )

    quality = RunQuality.of(result)

    assert (quality.orders, quality.fills, quality.rejects) == (2, 2, 1)


def test_the_average_cash_share_is_the_mean_of_each_session_s(run: RunBuilder) -> None:
    """All cash, then a quarter: three eighths on average."""
    result = run([100.0, 100.0], cash=[100.0, 25.0])

    assert RunQuality.of(result).average_cash_share == pytest.approx(0.625)


def test_a_run_with_no_session_has_no_cash_share(run: RunBuilder) -> None:
    """A mean of nothing is not zero."""
    assert RunQuality.of(run([])).average_cash_share is None


def target_of(session: date, weights: dict[str, float]) -> PortfolioDecision:
    """Return a decision taken after a session's close, accepted as asked."""
    at = datetime.combine(session, datetime.min.time(), tzinfo=UTC) + timedelta(hours=23)
    return PortfolioDecision(
        requested=TargetAllocation(as_of=at, weights=weights),
        constrained=ConstrainedTarget(
            as_of=at, requested_weights=weights, accepted_weights=weights
        ),
    )


def session(
    day: date,
    *,
    held: dict[str, float],
    decision: PortfolioDecision | None = None,
    executed: bool = False,
) -> BacktestRecord:
    """Return a session holding one unit at 50 of each named instrument."""
    at = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
    return BacktestRecord(
        session_date=day,
        valuation_time=at + timedelta(hours=23),
        cash=100.0 - 50.0 * len(held),
        gross_cash=100.0 - 50.0 * len(held),
        holdings={name: Holding(name, size) for name, size in held.items()},
        valuation_prices=dict.fromkeys(held, 50.0),
        target_invested=1.0,
        execution_time=at + timedelta(hours=9) if executed else None,
        executed_decision=day - timedelta(days=1) if executed else None,
        rejects=(
            (ExecutionReject("B", ExecutionRejectReason.NO_EXECUTION_PRICE),) if executed else ()
        ),
        decision_time=decision.as_of if decision is not None else None,
        decision=decision,
    )


def test_a_line_of_the_target_that_is_not_held_is_a_partial_investment(
    make_result: ResultBuilder,
) -> None:
    """Half in A and half in B was traded towards; B never printed, so only A is held.

    Counted against the target the book was traded towards, not the one just
    decided at the same close: a book does not hold tomorrow's purchase tonight.
    """
    first, second, third = date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)
    both = {"A": 0.5, "B": 0.5}
    records = [
        session(first, held={}, decision=target_of(first, both)),
        session(second, held={"A": 1.0}, executed=True),
        session(third, held={"A": 1.0}),
    ]

    quality = RunQuality.of(make_result(records, 100.0))

    # The first session decided the target and could not hold it yet; the
    # next two were traded towards it and hold only half of it.
    assert quality.sessions_partially_invested == 2
