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
    """Otherwise every order would depend on the ones computed before it.

    Half the book into a name at 100 is fifty units whatever the fee, because
    the fee is paid out of the other half rather than out of the order.
    """
    model = ExecutionModel(costs=CostModel(commission_rate=0.01))

    execution = model.rebalance(Holdings(cash=10_000.0), {"A": 0.5}, {"A": 100.0})

    assert execution.fills[0].quantity == pytest.approx(50.0)
    assert execution.holdings.cash == pytest.approx(5_000.0 - 50.0)


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


# --- an order is never paid for with money the book does not have ------------
#
# A target of a whole book is sized on the equity before this rebalancing's
# costs, and the costs still have to come from somewhere. Letting cash go
# negative would be a loan the model never granted and never charges for, and
# in a strategy that rebalances weekly it compounds out of sight.


def test_a_whole_book_is_bought_with_what_the_book_has() -> None:
    """Hand-checkable: at one percent, 10 000 buys 10 000/1.01 of stock.

    Ninety-nine units and a hundredth, not a hundred: the missing unit is the
    commission, and it comes out of the position rather than out of an
    overdraft.
    """
    model = ExecutionModel(costs=CostModel(commission_rate=0.01))

    execution = model.rebalance(Holdings(cash=10_000.0), {"A": 1.0}, {"A": 100.0})

    assert execution.fills[0].quantity == pytest.approx(10_000.0 / 101.0)
    assert execution.holdings.cash == pytest.approx(0.0, abs=1e-9)
    assert execution.unfunded == ("A",)


def test_the_spread_is_paid_out_of_the_order_too() -> None:
    """The order is sized at the reference price and done above it."""
    model = ExecutionModel(costs=CostModel(half_spread=0.002))

    execution = model.rebalance(Holdings(cash=10_000.0), {"A": 1.0}, {"A": 100.0})

    assert execution.fills[0].quantity == pytest.approx(10_000.0 / 100.2)
    assert execution.holdings.cash == pytest.approx(0.0, abs=1e-9)


def test_a_target_that_leaves_room_for_the_costs_is_filled_whole() -> None:
    """Nothing is cut when nothing needs to be: no trim, and nothing named."""
    model = ExecutionModel(costs=CostModel(commission_rate=0.01))

    execution = model.rebalance(Holdings(cash=10_000.0), {"A": 0.9}, {"A": 100.0})

    assert execution.fills[0].quantity == pytest.approx(90.0)
    assert execution.unfunded == ()
    assert execution.holdings.cash == pytest.approx(1_000.0 - 90.0)


def test_what_is_sold_pays_for_what_is_bought() -> None:
    """The sales are done first, or a switch could not be afforded at all.

    All of the book moves from A to B. Done in name order the purchase would
    come first and find no cash; done in the right order it finds the proceeds
    of the sale, less what the sale cost.
    """
    model = ExecutionModel(costs=CostModel(commission_rate=0.01))
    before = Holdings(cash=0.0, quantities={"A": 100.0})

    execution = model.rebalance(before, {"B": 1.0}, {"A": 100.0, "B": 50.0})

    quantities = dict(execution.holdings.quantities)
    assert "A" not in quantities
    assert quantities["B"] > 0.0
    assert execution.holdings.cash >= 0.0


def test_the_purchases_are_cut_by_the_same_fraction() -> None:
    """Every purchase is cut by the same fraction.

    Cutting one name to the bone to leave another whole would be a decision
    about the strategy, and this layer does not take those.
    """
    model = ExecutionModel(costs=CostModel(commission_rate=0.01))

    execution = model.rebalance(
        Holdings(cash=10_000.0), {"A": 0.5, "B": 0.5}, {"A": 100.0, "B": 100.0}
    )

    first, second = execution.fills
    assert first.quantity == pytest.approx(second.quantity)
    assert execution.holdings.cash == pytest.approx(0.0, abs=1e-9)
    assert execution.unfunded == ("A", "B")


def test_a_purchase_cut_below_the_threshold_is_dropped() -> None:
    """A trimmed order that is no longer worth sending is not sent."""
    model = ExecutionModel(costs=CostModel(commission_rate=0.5), minimum_trade_value=9_000.0)

    execution = model.rebalance(Holdings(cash=10_000.0), {"A": 1.0}, {"A": 100.0})

    assert execution.fills == ()
    assert execution.unfunded == ("A",)
    assert execution.holdings.cash == pytest.approx(10_000.0)


def test_a_book_with_no_cash_buys_nothing() -> None:
    """Nothing to sell, nothing to spend: the target is simply not reachable."""
    model = ExecutionModel(costs=CostModel(commission_rate=0.01))
    before = Holdings(cash=0.0, quantities={"A": 100.0})

    execution = model.rebalance(before, {"A": 1.0, "B": 1.0}, {"A": 100.0, "B": 50.0})

    assert [fill.instrument_id for fill in execution.fills] == []
    assert execution.unfunded == ("B",)


def test_the_commission_floor_is_carried_through_the_trim() -> None:
    """A floor does not shrink with the order it is charged on.

    Which is why the affordable size is found by bisection and not by dividing
    through: a fee of a flat ten has to fit inside the cash as well.
    """
    model = ExecutionModel(costs=CostModel(minimum_commission=10.0))

    execution = model.rebalance(Holdings(cash=1_000.0), {"A": 1.0}, {"A": 100.0})

    assert execution.fills[0].quantity == pytest.approx(9.9)
    assert execution.holdings.cash == pytest.approx(0.0, abs=1e-9)
