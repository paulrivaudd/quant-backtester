"""Rebalancing: the fill assumption, and what happens when it cannot be met."""

from __future__ import annotations

import pytest

from quant_backtester.execution.costs import CostModel, Side
from quant_backtester.execution.fills import ExecutionModel
from quant_backtester.portfolio.targets import Holdings

FREE = ExecutionModel()


def test_a_first_rebalancing_buys_the_target() -> None:
    """Ten thousand in cash, half into a name at 100: fifty units."""
    execution = FREE.rebalance(Holdings(cash=10_000.0), {"A": 0.5}, {"A": 100.0})

    assert dict(execution.holdings.quantities) == {"A": 50.0}
    assert execution.holdings.cash == pytest.approx(5_000.0)
    assert execution.fills[0].side is Side.BUY


def test_an_instrument_absent_from_the_target_is_closed() -> None:
    """A target of nothing is still a target, and it is not "leave it alone"."""
    before = Holdings(cash=0.0, quantities={"A": 50.0})

    execution = FREE.rebalance(before, {}, {"A": 100.0})

    assert dict(execution.holdings.quantities) == {}
    assert execution.holdings.cash == pytest.approx(5_000.0)


def test_equity_is_measured_before_this_rebalancing_s_costs() -> None:
    """Otherwise every order would depend on the ones computed before it."""
    model = ExecutionModel(costs=CostModel(commission_rate=0.01))
    execution = model.rebalance(Holdings(cash=10_000.0), {"A": 1.0}, {"A": 100.0})

    assert execution.fills[0].quantity == pytest.approx(100.0)
    assert execution.holdings.cash == pytest.approx(-100.0)


def test_the_costs_are_taken_out_of_cash_and_named_apart() -> None:
    """A report has to be able to say which of the two ate the return."""
    model = ExecutionModel(
        costs=CostModel(commission_rate=0.001, half_spread=0.002, slippage_rate=0.001)
    )

    execution = model.rebalance(Holdings(cash=10_000.0), {"A": 0.5}, {"A": 100.0})

    fill = execution.fills[0]
    assert fill.fill_price == pytest.approx(100.3)
    assert execution.market_cost == pytest.approx(fill.quantity * 0.3)
    assert execution.commission == pytest.approx(fill.traded_value * 0.001)
    assert execution.cost == pytest.approx(execution.market_cost + execution.commission)


def test_an_order_below_the_threshold_is_not_sent() -> None:
    """A rebalancing that moves a position by a few units pays a floor to do nothing."""
    model = ExecutionModel(minimum_trade_value=1_000.0)
    before = Holdings(cash=5_000.0, quantities={"A": 50.0})

    execution = model.rebalance(before, {"A": 0.51}, {"A": 100.0})

    assert execution.fills == ()
    assert dict(execution.holdings.quantities) == {"A": 50.0}


def test_a_position_that_cannot_be_dealt_is_still_worth_something() -> None:
    """Its position stays exactly as it was, and the refusal is named.

    B's opening auction did not print, so it cannot be traded - but the book
    still has to be worth something for A's order to be sized against, and
    valuing B at nothing would size that order off a loss that never happened.
    """
    before = Holdings(cash=1_000.0, quantities={"A": 10.0, "B": 5.0})

    execution = FREE.rebalance(
        before, {"A": 0.5, "B": 0.5}, {"A": 100.0, "B": 20.0}, tradable={"A"}
    )

    assert execution.untradable == ("B",)
    assert execution.holdings.quantities["B"] == 5.0
    # Equity was 1000 + 1000 + 100 = 2100, so half of it is 1050 in A.
    assert execution.holdings.quantities["A"] == pytest.approx(10.5)


def test_an_instrument_with_no_price_at_all_is_untradable() -> None:
    """Wanted, never priced: no order, and the reason is on the record."""
    execution = FREE.rebalance(Holdings(cash=1_000.0), {"A": 0.5, "B": 0.5}, {"A": 100.0})

    assert execution.untradable == ("B",)
    assert dict(execution.holdings.quantities) == {"A": 5.0}


def test_a_position_held_at_no_price_stops_the_valuation() -> None:
    """Equity cannot be measured, so nothing is traded on a guess about it."""
    before = Holdings(cash=0.0, quantities={"B": 5.0})

    with pytest.raises(KeyError):
        FREE.rebalance(before, {"A": 1.0}, {"A": 100.0})


def test_selling_receives_less_than_the_screen() -> None:
    """The sign of the spread follows the side, and cash follows the sign."""
    model = ExecutionModel(costs=CostModel(half_spread=0.01))
    before = Holdings(cash=0.0, quantities={"A": 100.0})

    execution = model.rebalance(before, {}, {"A": 10.0})

    assert execution.fills[0].fill_price == pytest.approx(9.9)
    assert execution.holdings.cash == pytest.approx(990.0)


def test_nothing_to_do_is_no_order_at_all() -> None:
    """Already at the target: no fill, no cost, no floor paid."""
    model = ExecutionModel(costs=CostModel(minimum_commission=5.0))
    before = Holdings(cash=5_000.0, quantities={"A": 50.0})

    execution = model.rebalance(before, {"A": 0.5}, {"A": 100.0})

    assert execution.fills == ()
    assert execution.cost == 0.0


def test_a_negative_threshold_is_refused() -> None:
    with pytest.raises(ValueError, match="minimum_trade_value"):
        ExecutionModel(minimum_trade_value=-1.0)
