"""Rebalancing: sizing, rounding, the cash constraint, and every refusal named.

The arithmetic is small enough to check by hand, which is the point: a
purchase sized at the price it will be paid, a lot rounded down, a sale done
before the purchase it pays for - each has an answer on paper, and any other
sequence gives a different number.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from datetime import UTC, date, datetime, timedelta

import pytest

from quant_backtester.data.instruments import (
    AssetType,
    DataType,
    Instrument,
    InstrumentRegistry,
)
from quant_backtester.data.reader import Observation, ObservationStatus
from quant_backtester.execution.costs import CostModel
from quant_backtester.execution.fills import ExecutionReject, ExecutionRejectReason, OrderStatus
from quant_backtester.execution.model import Execution, ExecutionModel, Sizing
from quant_backtester.execution.orders import Side
from quant_backtester.portfolio.holdings import Holding
from quant_backtester.portfolio.state import PortfolioState, UnvaluablePosition

AT = datetime(2026, 9, 15, 7, 1, tzinfo=UTC)
SESSION = date(2026, 9, 15)
BEFORE = AT - timedelta(days=1)
FREE = ExecutionModel(costs=CostModel())


def fund(
    instrument_id: str,
    *,
    step: float | None = None,
    currency: str = "EUR",
    tradable: bool = True,
) -> Instrument:
    """Return a Paris-listed instrument with the given dealing rules."""
    return Instrument(
        id=instrument_id,
        name=instrument_id,
        asset_type=AssetType.ETF if tradable else AssetType.INDEX,
        data_type=DataType.BAR,
        currency=currency,
        primary_source="YAHOO",
        source_symbol=f"{instrument_id}.PA",
        tradable=tradable,
        quantity_step=step,
        calendar_id="XPAR",
        first_session=date(2026, 1, 2),
    )


REGISTRY = InstrumentRegistry(
    [
        fund("A"),
        fund("B"),
        fund("W", step=1.0),
        fund("V", step=1.0),
        fund("IDX", tradable=False),
        fund("DOLLAR", currency="USD"),
    ]
)
EVERYTHING = ("A", "B", "W", "V")


def price(value: float, status: ObservationStatus = ObservationStatus.OK) -> Observation:
    """Return an opening price as the reader hands one over, knowable a minute ago."""
    return Observation(
        instrument_id="?",
        value=value,
        status=status,
        observation_date=SESSION if status is ObservationStatus.OK else SESSION - timedelta(days=1),
        available_at=AT - timedelta(minutes=1),
        age_sessions=0 if status is ObservationStatus.OK else 1,
    )


def missing(status: ObservationStatus = ObservationStatus.MISSING) -> Observation:
    """Return the observation of an opening auction that did not print."""
    return Observation(instrument_id="?", value=None, status=status)


def book(cash: float = 10_000.0, **quantities: float) -> PortfolioState:
    """Return a book holding ``cash`` and the given quantities."""
    return PortfolioState(
        as_of=BEFORE,
        cash=cash,
        holdings={name: Holding(name, size) for name, size in quantities.items()},
    )


def trade(
    model: ExecutionModel,
    state: PortfolioState,
    target: Mapping[str, float],
    prices: Mapping[str, float | Observation],
    *,
    last_known: Mapping[str, float] | None = None,
    universe: Collection[str] = EVERYTHING,
    hold: bool = False,
    keep: Collection[str] = (),
    cash_shares: Mapping[str, float] | None = None,
    decision_closes: Mapping[str, float] | None = None,
) -> Execution:
    """Rebalance at ``AT``; a bare number is an opening price of the session itself."""
    quotes = {
        name: value if isinstance(value, Observation) else price(value)
        for name, value in prices.items()
    }
    return model.rebalance(
        state,
        target,
        at=AT,
        session=SESSION,
        quotes=quotes,
        last_known=last_known or {},
        instruments=REGISTRY,
        base_currency="EUR",
        universe=universe,
        hold=hold,
        keep=keep,
        cash_shares=cash_shares,
        decision_closes=decision_closes,
    )


def reasons(execution: Execution) -> dict[str, ExecutionRejectReason]:
    """Return the reason of each reject, by instrument."""
    return {reject.instrument_id: reject.reason for reject in execution.rejects}


# -- sizing -----------------------------------------------------------------------------


def test_a_first_rebalancing_buys_the_target() -> None:
    """Ten thousand in cash, half into a name at 100: fifty units."""
    execution = trade(FREE, book(), {"A": 0.5}, {"A": 100.0})

    assert dict(execution.state.quantities) == {"A": 50.0}
    assert execution.state.cash == pytest.approx(5_000.0)
    assert execution.fills[0].side is Side.BUY
    assert execution.status("A") is OrderStatus.FILLED


def test_an_instrument_absent_from_the_target_is_closed() -> None:
    """A target of nothing is still a target, and it is not "leave it alone"."""
    execution = trade(FREE, book(0.0, A=50.0), {}, {"A": 100.0})

    assert dict(execution.state.quantities) == {}
    assert execution.state.cash == pytest.approx(5_000.0)


def test_equity_is_measured_before_this_rebalancing_s_costs() -> None:
    """Otherwise every order would depend on the ones computed before it.

    Half the book into a name at 100 is fifty units whatever the fee, because
    the fee is paid out of the other half rather than out of the order.
    """
    model = ExecutionModel(costs=CostModel(commission_rate=0.01))

    execution = trade(model, book(), {"A": 0.5}, {"A": 100.0})

    assert execution.equity == pytest.approx(10_000.0)
    assert execution.fills[0].quantity == pytest.approx(50.0)
    assert execution.state.cash == pytest.approx(5_000.0 - 50.0)


def test_a_purchase_is_sized_at_the_price_it_will_be_paid() -> None:
    """Five thousand at a fill of 100.3 buys 5000/100.3 units: spent is what was targeted."""
    model = ExecutionModel(
        costs=CostModel(commission_rate=0.001, half_spread_rate=0.002, slippage_rate=0.001)
    )

    execution = trade(model, book(), {"A": 0.5}, {"A": 100.0})

    done = execution.fills[0]
    assert done.fill_price == pytest.approx(100.3)
    assert done.quantity == pytest.approx(5_000.0 / 100.3)
    assert done.traded_value == pytest.approx(5_000.0)
    assert execution.spread_cost == pytest.approx(done.quantity * 0.2)
    assert execution.slippage_cost == pytest.approx(done.quantity * 0.1)
    assert execution.commission == pytest.approx(5.0)
    assert execution.total_cost == pytest.approx(
        execution.commission + execution.spread_cost + execution.slippage_cost
    )


def test_selling_receives_less_than_the_screen() -> None:
    """The sign of the spread follows the side, and cash follows the sign."""
    model = ExecutionModel(costs=CostModel(half_spread_rate=0.01))

    execution = trade(model, book(0.0, A=100.0), {}, {"A": 10.0})

    assert execution.fills[0].fill_price == pytest.approx(9.9)
    assert execution.state.cash == pytest.approx(990.0)


def test_nothing_to_do_is_no_order_at_all() -> None:
    """Already at the target: no order, no fill, no cost, no floor paid."""
    model = ExecutionModel(costs=CostModel(minimum_commission=5.0))

    execution = trade(model, book(5_000.0, A=50.0), {"A": 0.5}, {"A": 100.0})

    assert execution.orders == ()
    assert execution.fills == ()
    assert execution.total_cost == 0.0
    assert execution.status("A") is None


def test_the_spec_example_checks_by_hand() -> None:
    """A hundred thousand, fifty-fifty, opens of 101 and 67: 493 and 744 shares.

    Twenty-five basis points of spread and slippage put the fills at 101.2525
    and 67.1675. Fifty thousand buys 493.8 of the first and 744.4 of the
    second, rounded down to whole shares; the commission fits in what the
    rounding left, so nothing is cut.
    """
    model = ExecutionModel(
        costs=CostModel(commission_rate=0.001, half_spread_rate=0.0015, slippage_rate=0.001)
    )

    execution = trade(model, book(100_000.0), {"W": 0.5, "V": 0.5}, {"W": 101.0, "V": 67.0})

    assert dict(execution.state.quantities) == {"V": 744.0, "W": 493.0}
    assert execution.rejects == ()
    paid = 493 * 101.2525 * 1.001 + 744 * 67.1675 * 1.001
    assert execution.state.cash == pytest.approx(100_000.0 - paid)
    assert execution.state.cash > 0.0


# -- lots -------------------------------------------------------------------------------


def test_three_point_seven_shares_are_three() -> None:
    """A purchase is rounded down: 370 at 100 is 3.7 shares, and a broker takes 3."""
    execution = trade(FREE, book(1_000.0), {"W": 0.37}, {"W": 100.0})

    assert dict(execution.state.quantities) == {"W": 3.0}
    assert execution.state.cash == pytest.approx(700.0)


def test_a_sale_never_sells_more_than_the_target_calls_for() -> None:
    """Ten held, a target worth 3.7: the excess is 6.3 shares, and six are sold.

    Rounded down like a purchase: what remains is within a lot of the target,
    and no share is sold that the target did not ask to be sold.
    """
    execution = trade(FREE, book(0.0, W=10.0), {"W": 0.37}, {"W": 100.0})

    assert dict(execution.state.quantities) == {"W": 4.0}
    assert execution.fills[0].side is Side.SELL
    assert execution.fills[0].quantity == 6.0


def test_a_target_within_a_lot_of_the_position_is_no_trade() -> None:
    """The drift of a morning is a fraction of a share, and it never costs a commission.

    Two hundred shares held, a target worth 199.98 of them: rounding the target
    as a position would sell one share, and the next day's 200.02 would buy
    nothing back - a book asked to keep what it holds would sell itself away.
    """
    model = ExecutionModel(costs=CostModel(commission_rate=0.001, minimum_commission=1.0))

    below = trade(model, book(10.0, W=200.0), {"W": 199.98 / 200.1}, {"W": 100.0})
    above = trade(model, book(10.0, W=200.0), {"W": 200.02 / 200.1}, {"W": 100.0})

    assert below.orders == ()
    assert above.orders == ()
    assert below.state.quantity("W") == above.state.quantity("W") == 200.0


def test_a_position_ends_within_a_lot_of_its_target_from_either_side() -> None:
    """From below three are bought, from above four are kept: both within a lot of 3.7."""
    from_below = trade(FREE, book(1_000.0), {"W": 0.37}, {"W": 100.0})
    from_above = trade(FREE, book(0.0, W=10.0), {"W": 0.37}, {"W": 100.0})

    assert from_below.state.quantity("W") == 3.0
    assert from_above.state.quantity("W") == 4.0
    for execution in (from_below, from_above):
        assert abs(execution.state.quantity("W") - 3.7) < 1.0


def test_the_trade_is_truncated_towards_zero_and_never_floored() -> None:
    """An excess of 4.5 lots sells 4: floored as a signed trade it would sell 5."""
    execution = trade(FREE, book(0.0, W=5.0), {"W": 0.05}, {"W": 100.0})

    assert execution.fills[0].side is Side.SELL
    assert execution.fills[0].quantity == 4.0
    assert execution.state.quantity("W") == 1.0


def test_the_rounding_rule_holds_on_any_book_and_any_target(rng_seed: int) -> None:
    """The invariants of the rule, on two thousand books drawn at random.

    Free trading, so the cash never binds and what is checked is the rounding
    alone: whole lots, a purchase never beyond what is wanted, a sale never
    beyond the excess, and a position that ends within one lot of its target.
    """
    import random

    draw = random.Random(rng_seed)
    for _ in range(2_000):
        price = draw.uniform(5.0, 800.0)
        held = float(draw.randint(0, 300))
        cash = draw.uniform(0.0, 50_000.0)
        equity = cash + held * price
        weight = draw.uniform(0.0, 1.0)
        wanted = equity * weight / price

        execution = trade(FREE, book(cash, W=held), {"W": weight}, {"W": price})

        after = execution.state.quantity("W")
        assert after == float(int(after)), "a position is a whole number of lots"
        if after > held:
            assert after <= wanted + 1e-9, "a purchase never buys beyond the target"
        if after < held:
            assert after >= wanted - 1e-9, "a sale never sells beyond the excess"
        assert abs(after - wanted) < 1.0, "the position ends within one lot of its target"


def test_rounding_never_sells_more_than_is_held() -> None:
    """A position closed in full closes to exactly zero, never below."""
    execution = trade(FREE, book(0.0, W=33.0), {}, {"W": 300.0})

    assert dict(execution.state.quantities) == {}
    assert execution.state.cash == pytest.approx(9_900.0)


def test_an_order_smaller_than_one_lot_is_not_sent_and_not_an_error() -> None:
    """Half a share is no order: at this lot size, the target has been reached."""
    execution = trade(FREE, book(100.0, W=33.0), {"W": 1.0}, {"W": 300.0})

    assert execution.orders == ()
    assert execution.rejects == ()
    assert dict(execution.state.quantities) == {"W": 33.0}


def test_rounding_is_always_downwards_so_the_cash_is_never_overdrawn() -> None:
    """Rounding to the nearest lot would buy a share the sizing never paid for."""
    execution = trade(FREE, book(), {"W": 1.0}, {"W": 199.0})

    # 50.25 units wanted, 50 dealt: never 51, which would need 10,149.
    assert dict(execution.state.quantities) == {"W": 50.0}
    assert execution.state.cash >= 0.0


def test_an_instrument_without_a_step_is_dealt_in_fractions() -> None:
    """Lot sizes are declared per instrument, not assumed for all of them."""
    execution = trade(FREE, book(), {"A": 1.0}, {"A": 300.0})

    assert dict(execution.state.quantities) == {"A": pytest.approx(10_000.0 / 300.0)}


def test_a_position_that_is_not_whole_lots_is_left_alone_and_named() -> None:
    """No order on the lot grid reaches a target from off it; the reason is on the record."""
    execution = trade(FREE, book(0.0, W=2.5), {"W": 0.5}, {"W": 100.0})

    assert reasons(execution) == {"W": ExecutionRejectReason.INVALID_QUANTITY}
    assert execution.state.quantity("W") == 2.5


# -- the cash constraint ---------------------------------------------------------------


def test_a_whole_book_is_bought_with_what_the_book_has() -> None:
    """At one percent, 10 000 buys 10 000/1.01 of stock, and the cut is named.

    Ninety-nine units and a hundredth, not a hundred: the missing unit is the
    commission, and it comes out of the position rather than out of an
    overdraft.
    """
    model = ExecutionModel(costs=CostModel(commission_rate=0.01))

    execution = trade(model, book(), {"A": 1.0}, {"A": 100.0})

    assert execution.fills[0].quantity == pytest.approx(10_000.0 / 101.0)
    assert execution.state.cash == pytest.approx(0.0, abs=1e-9)
    assert execution.state.cash >= 0.0
    assert execution.status("A") is OrderStatus.PARTIALLY_FILLED
    (cut,) = execution.rejects
    assert cut.reason is ExecutionRejectReason.INSUFFICIENT_CASH
    assert cut.requested_quantity == pytest.approx(100.0 - 10_000.0 / 101.0)


def test_a_target_that_leaves_room_for_the_costs_is_filled_whole() -> None:
    """Nothing is cut when nothing needs to be: no trim, and nothing named."""
    model = ExecutionModel(costs=CostModel(commission_rate=0.01))

    execution = trade(model, book(), {"A": 0.9}, {"A": 100.0})

    assert execution.fills[0].quantity == pytest.approx(90.0)
    assert execution.rejects == ()
    assert execution.state.cash == pytest.approx(1_000.0 - 90.0)


def test_a_purchase_the_cash_cannot_carry_is_cut_to_whole_shares() -> None:
    """A thousand in cash, twelve hundred wanted: ten shares, not twelve, and no cash below zero.

    The other half of the book is a position whose auction did not print: it
    is worth its last price for the sizing, and it cannot be sold to pay.
    """
    execution = trade(
        FREE,
        book(1_000.0, B=10.0),
        {"W": 0.6},
        {"W": 100.0, "B": missing()},
        last_known={"B": 100.0},
    )

    assert execution.state.quantity("W") == 10.0
    assert execution.state.cash == pytest.approx(0.0)
    assert execution.status("W") is OrderStatus.PARTIALLY_FILLED
    assert {reject.reason for reject in execution.rejects} == {
        ExecutionRejectReason.INSUFFICIENT_CASH,
        ExecutionRejectReason.NO_EXECUTION_PRICE,
    }


def test_what_is_sold_pays_for_what_is_bought() -> None:
    """The sales are done first, or a switch could not be afforded at all.

    All of the book moves from A to B. Done in name order the purchase would
    come first and find no cash; done in the right order it finds the proceeds
    of the sale, less what the sale cost.
    """
    model = ExecutionModel(costs=CostModel(commission_rate=0.01))

    execution = trade(model, book(0.0, A=100.0), {"B": 1.0}, {"A": 100.0, "B": 50.0})

    assert not execution.state.holds("A")
    assert execution.state.quantity("B") > 0.0
    assert execution.state.cash >= 0.0
    assert [fill.side for fill in execution.fills] == [Side.SELL, Side.BUY]
    assert [order.side for order in execution.orders] == [Side.SELL, Side.BUY]


def test_the_purchases_are_cut_by_the_same_fraction() -> None:
    """Cutting one name to the bone to leave another whole would be a decision about the strategy.

    So every purchase is cut by the same fraction.
    """
    model = ExecutionModel(costs=CostModel(commission_rate=0.01))

    execution = trade(model, book(), {"A": 0.5, "B": 0.5}, {"A": 100.0, "B": 100.0})

    first, second = execution.fills
    assert first.quantity == pytest.approx(second.quantity)
    assert execution.state.cash == pytest.approx(0.0, abs=1e-9)
    assert sorted(reject.instrument_id for reject in execution.rejects) == ["A", "B"]


def test_a_purchase_cut_below_the_threshold_is_dropped() -> None:
    """A trimmed order that is no longer worth sending is not sent."""
    model = ExecutionModel(costs=CostModel(commission_rate=0.5), minimum_trade_value=9_000.0)

    execution = trade(model, book(), {"A": 1.0}, {"A": 100.0})

    assert execution.fills == ()
    assert execution.status("A") is OrderStatus.REJECTED
    assert reasons(execution) == {"A": ExecutionRejectReason.INSUFFICIENT_CASH}
    assert execution.state.cash == pytest.approx(10_000.0)


def test_a_cash_that_cannot_even_pay_the_floor_buys_nothing() -> None:
    """Five in cash and a commission floor of ten: no size of purchase fits."""
    model = ExecutionModel(costs=CostModel(minimum_commission=10.0))

    execution = trade(model, book(5.0), {"B": 1.0}, {"B": 50.0})

    assert execution.fills == ()
    (reject,) = execution.rejects
    assert reject.reason is ExecutionRejectReason.INSUFFICIENT_CASH
    assert reject.requested_quantity == pytest.approx(0.1)
    assert execution.state.cash == 5.0


def test_the_commission_floor_is_carried_through_the_trim() -> None:
    """A floor does not shrink with the order it is charged on, so it has to fit too."""
    model = ExecutionModel(costs=CostModel(minimum_commission=10.0))

    execution = trade(model, book(1_000.0), {"A": 1.0}, {"A": 100.0})

    assert execution.fills[0].quantity == pytest.approx(9.9)
    assert execution.state.cash == pytest.approx(0.0, abs=1e-9)
    assert execution.state.cash >= 0.0


def test_a_sale_whose_fee_the_cash_cannot_cover_is_refused() -> None:
    """A floor above what the sale brings in, and nothing in cash to pay the difference."""
    model = ExecutionModel(costs=CostModel(minimum_commission=10.0))

    execution = trade(model, book(0.0, A=1.0), {}, {"A": 5.0})

    assert reasons(execution) == {"A": ExecutionRejectReason.INSUFFICIENT_CASH}
    assert execution.state.quantity("A") == 1.0
    assert execution.state.cash == 0.0


# -- orders that are not sent ------------------------------------------------------------


def test_an_order_below_the_threshold_is_not_sent_and_says_so() -> None:
    """A rebalancing that moves a position by a few units pays a floor to do nothing."""
    model = ExecutionModel(costs=CostModel(), minimum_trade_value=1_000.0)

    execution = trade(model, book(5_000.0, A=50.0), {"A": 0.51}, {"A": 100.0})

    assert execution.fills == ()
    (reject,) = execution.rejects
    assert reject.reason is ExecutionRejectReason.BELOW_MINIMUM_TRADE
    assert reject.side is Side.BUY
    assert reject.requested_quantity == pytest.approx(1.0)
    assert dict(execution.state.quantities) == {"A": 50.0}


def test_a_position_that_cannot_be_dealt_is_still_worth_something() -> None:
    """Its position stays exactly as it was, and the refusal is named.

    B's opening auction did not print, so it cannot be traded - but the book
    still has to be worth something for A's order to be sized against, and
    valuing B at nothing would size that order off a loss that never happened.
    """
    execution = trade(
        FREE,
        book(1_000.0, A=10.0, B=5.0),
        {"A": 0.5, "B": 0.5},
        {"A": 100.0, "B": missing()},
        last_known={"B": 20.0},
    )

    assert reasons(execution) == {"B": ExecutionRejectReason.NO_EXECUTION_PRICE}
    assert execution.rejects[0].side is None
    assert execution.state.quantity("B") == 5.0
    # Equity was 1000 + 1000 + 100 = 2100, so half of it is 1050 in A.
    assert execution.state.quantity("A") == pytest.approx(10.5)


def test_a_purchase_with_no_price_says_which_way_and_not_how_much() -> None:
    """Wanted, never priced: the side is known, the size is not, and neither is guessed."""
    execution = trade(FREE, book(1_000.0), {"A": 0.5, "B": 0.5}, {"A": 100.0, "B": missing()})

    (reject,) = execution.rejects
    assert (reject.instrument_id, reject.side, reject.requested_quantity) == ("B", Side.BUY, None)
    assert dict(execution.state.quantities) == {"A": 5.0}


def test_a_position_to_close_with_no_price_is_a_sale_of_all_of_it() -> None:
    """What a closing order would have been is knowable without a price."""
    execution = trade(FREE, book(0.0, B=5.0), {}, {"B": missing()}, last_known={"B": 20.0})

    (reject,) = execution.rejects
    assert (reject.side, reject.requested_quantity) == (Side.SELL, 5.0)


def test_a_stale_open_is_never_traded_on() -> None:
    """An opening price from an earlier session is a price nobody could have got that morning."""
    execution = trade(FREE, book(), {"A": 1.0}, {"A": price(100.0, ObservationStatus.STALE)})

    assert execution.fills == ()
    assert reasons(execution) == {"A": ExecutionRejectReason.STALE_EXECUTION_PRICE}


def test_an_instrument_that_is_not_listed_has_no_execution_price() -> None:
    """It cannot be bought before it exists."""
    execution = trade(FREE, book(), {"A": 1.0}, {"A": missing(ObservationStatus.NOT_LISTED)})

    assert reasons(execution) == {"A": ExecutionRejectReason.NO_EXECUTION_PRICE}


def test_an_open_the_reader_calls_current_but_from_the_session_before_is_not_traded() -> None:
    """Before this morning's auction, yesterday's open is the latest there is - and still stale.

    The reader counts its age on the latest session that has *opened*, so at
    08:30 it reports yesterday's open as current. Nobody can trade at it this
    morning, so the order is refused rather than filled at yesterday's price.
    """
    yesterday = Observation(
        instrument_id="A",
        value=100.0,
        status=ObservationStatus.OK,
        observation_date=SESSION - timedelta(days=1),
        available_at=AT - timedelta(days=1),
        age_sessions=0,
    )

    execution = trade(FREE, book(), {"A": 1.0}, {"A": yesterday})

    assert execution.fills == ()
    assert reasons(execution) == {"A": ExecutionRejectReason.STALE_EXECUTION_PRICE}


def test_an_open_of_a_later_session_is_look_ahead() -> None:
    """A price describing tomorrow's session cannot fill today's order."""
    tomorrow = Observation(
        instrument_id="A",
        value=100.0,
        status=ObservationStatus.OK,
        observation_date=SESSION + timedelta(days=1),
        available_at=AT - timedelta(minutes=1),
        age_sessions=0,
    )

    with pytest.raises(ValueError, match="look-ahead"):
        trade(FREE, book(), {"A": 1.0}, {"A": tomorrow})


def test_a_price_published_after_the_execution_instant_is_look_ahead() -> None:
    """A bug rather than a market situation, so it raises instead of rejecting."""
    future = Observation(
        instrument_id="A",
        value=100.0,
        status=ObservationStatus.OK,
        available_at=AT + timedelta(minutes=1),
        age_sessions=0,
    )

    with pytest.raises(ValueError, match="look-ahead"):
        trade(FREE, book(), {"A": 1.0}, {"A": future})


def test_a_purchase_outside_the_execution_session_s_universe_is_refused() -> None:
    """A name that left the universe between the decision and the open is not bought."""
    execution = trade(FREE, book(), {"A": 1.0}, {"A": 100.0}, universe=("B",))

    (reject,) = execution.rejects
    assert reject.reason is ExecutionRejectReason.OUTSIDE_TRADING_UNIVERSE
    assert (reject.side, reject.requested_quantity) == (Side.BUY, pytest.approx(100.0))


def test_a_sale_outside_the_universe_is_always_allowed() -> None:
    """Leaving a universe is exactly when a position must be closable."""
    execution = trade(FREE, book(0.0, A=10.0), {}, {"A": 100.0}, universe=())

    assert not execution.state.holds("A")
    assert execution.rejects == ()


def test_an_instrument_nobody_can_buy_is_refused_at_the_last_guard() -> None:
    """The portfolio layer refuses it first; an execution model used alone still does."""
    execution = trade(FREE, book(), {"IDX": 1.0}, {"IDX": 100.0}, universe=("IDX",))

    assert reasons(execution) == {"IDX": ExecutionRejectReason.NON_TRADABLE}
    assert execution.fills == ()


def test_a_fund_in_another_currency_is_refused_at_the_last_guard() -> None:
    """Nothing converts a dollar into a euro here."""
    execution = trade(FREE, book(), {"DOLLAR": 1.0}, {"DOLLAR": 100.0}, universe=("DOLLAR",))

    assert reasons(execution) == {"DOLLAR": ExecutionRejectReason.CURRENCY_MISMATCH}


def test_a_position_held_at_no_price_ever_stops_the_sizing() -> None:
    """Equity cannot be measured, so nothing is traded on a guess about it."""
    with pytest.raises(UnvaluablePosition):
        trade(FREE, book(0.0, B=5.0), {"A": 1.0}, {"A": 100.0, "B": missing()})


def test_a_held_instrument_without_an_observation_is_a_wiring_mistake() -> None:
    """The engine reads every line the target touches; one missing is a bug."""
    with pytest.raises(KeyError):
        trade(FREE, book(0.0, B=5.0), {"A": 1.0}, {"A": 100.0}, last_known={"B": 1.0})


# -- the target itself -------------------------------------------------------------------


def test_a_negative_target_weight_never_becomes_a_short() -> None:
    """The layer that would create the position is the layer that refuses it."""
    with pytest.raises(ValueError, match="the target weight of A"):
        trade(FREE, book(), {"A": -0.5}, {"A": 100.0})


def test_a_target_weight_of_nan_is_refused() -> None:
    """It would size an order of NaN units and value the book at NaN for ever."""
    with pytest.raises(ValueError, match="the target weight of A"):
        trade(FREE, book(), {"A": float("nan")}, {"A": 100.0})


def test_weights_adding_up_to_more_than_the_book_are_refused() -> None:
    """The rest would be borrowed, and nothing here lends it."""
    with pytest.raises(ValueError, match="add up to"):
        trade(FREE, book(), {"A": 0.6, "B": 0.6}, {"A": 100.0, "B": 100.0})


# -- the record of it ----------------------------------------------------------------------


def test_the_result_does_not_depend_on_the_order_of_the_target() -> None:
    """The same weights written two ways trade the same way, bit for bit."""
    model = ExecutionModel(costs=CostModel(commission_rate=0.01))
    prices = {"A": 100.0, "B": 37.0}

    forward = trade(model, book(), {"A": 0.5, "B": 0.5}, prices)
    backward = trade(model, book(), {"B": 0.5, "A": 0.5}, prices)

    assert forward.fills == backward.fills
    assert forward.state == backward.state


def test_the_rejects_come_back_in_instrument_order() -> None:
    """A report reads the same thing twice the same way."""
    execution = trade(
        FREE,
        book(),
        {"B": 0.5, "A": 0.5},
        {"A": missing(), "B": missing()},
    )

    assert [reject.instrument_id for reject in execution.rejects] == ["A", "B"]


def test_an_execution_is_stamped_and_cannot_be_edited() -> None:
    """What was done is what the record says was done."""
    execution = trade(FREE, book(), {"A": 0.5}, {"A": 100.0})

    assert execution.at == AT
    assert execution.state.as_of == AT
    assert execution.orders[0].submitted_at == AT
    with pytest.raises(AttributeError):
        execution.fills = ()  # type: ignore[misc]


def test_a_rebalancing_that_trades_nothing_leaves_the_state_as_it_was() -> None:
    """No trade, no new state: the book still stands from its last change."""
    state = book(5_000.0, A=50.0)

    execution = trade(FREE, state, {"A": 0.5}, {"A": 100.0})

    assert execution.state is state


def test_the_model_describes_itself_for_the_record() -> None:
    """The fill assumption, the costs and the threshold, as a result records them."""
    model = ExecutionModel(costs=CostModel(commission_rate=0.001), minimum_trade_value=500.0)

    definition = model.definition()

    assert definition["minimum_trade_value"] == 500.0
    assert definition["costs"] == CostModel(commission_rate=0.001).definition()
    assert "opening auction" in str(definition["fill"])


@pytest.mark.parametrize("threshold", [float("nan"), float("inf"), -1.0])
def test_a_minimum_trade_value_that_is_not_a_value_is_refused(threshold: float) -> None:
    """A threshold of NaN compares false against every order and sends them all."""
    with pytest.raises(ValueError, match="minimum_trade_value"):
        ExecutionModel(costs=CostModel(), minimum_trade_value=threshold)


def test_a_cost_model_is_required() -> None:
    """A default of zero costs would be a cost model attached without anyone saying so."""
    with pytest.raises(ValueError, match="CostModel"):
        ExecutionModel(costs=None)  # type: ignore[arg-type]


def test_a_reject_is_never_a_fill() -> None:
    """An instrument rejected in full contributes nothing to the costs."""
    execution = trade(FREE, book(), {"A": 1.0}, {"A": missing()})

    assert execution.traded_value == 0.0
    assert execution.total_cost == 0.0
    assert all(isinstance(reject, ExecutionReject) for reject in execution.rejects)


def test_a_book_kept_as_it_is_sends_nothing_however_the_prices_moved() -> None:
    """The weights of last night's close against this morning's open would call for a trade.

    Two hundred of A, dealt in fractions, and a thousand in cash, recorded at
    the close as a weight of about 0.95; the open is ten percent higher, so
    the same weight now means 0.87 unit fewer, and restating it sells them.
    Keeping the book sends no order and refuses nothing.
    """
    state = book(1_000.0, A=200.0)
    last_nights = {"A": 200.0 * 100.0 / (1_000.0 + 200.0 * 100.0)}

    kept = trade(FREE, state, last_nights, {"A": 110.0}, hold=True)
    restated = trade(FREE, state, last_nights, {"A": 110.0})

    assert kept.orders == () and kept.fills == () and kept.rejects == ()
    assert kept.state is state
    assert kept.equity == pytest.approx(1_000.0 + 200.0 * 110.0)
    assert [order.side for order in restated.orders] == [Side.SELL]


def test_keeping_a_book_still_needs_it_valued() -> None:
    """A position with no price ever is no easier to keep than to trade."""
    with pytest.raises(UnvaluablePosition):
        trade(FREE, book(0.0, W=5.0), {"W": 1.0}, {"W": missing()}, hold=True)


def test_a_kept_line_gets_no_order_while_the_rest_is_bought() -> None:
    """A basket being completed: A is kept as it is, B is bought with the cash.

    Restated in weights, A would be bought back up to last night's weight after
    an overnight fall; kept, it is not touched, and its value still counts in
    the equity B is sized on.
    """
    state = book(10_000.0, A=100.0)
    last_nights = {"A": 0.5, "B": 0.5}

    kept = trade(FREE, state, last_nights, {"A": 90.0, "B": 50.0}, keep={"A"})
    restated = trade(FREE, state, last_nights, {"A": 90.0, "B": 50.0})

    assert [order.instrument_id for order in kept.orders] == ["B"]
    assert kept.state.quantity("A") == 100.0
    assert kept.state.quantity("B") == pytest.approx(0.5 * (10_000.0 + 9_000.0) / 50.0)
    assert "A" in [order.instrument_id for order in restated.orders]


def test_a_kept_line_is_never_rejected_either() -> None:
    """No opening price for a line nobody wanted to trade is not a refusal."""
    kept = trade(
        FREE,
        book(5_000.0, A=50.0),
        {"A": 0.5, "B": 0.5},
        {"A": missing(), "B": 100.0},
        last_known={"A": 100.0},
        keep={"A"},
    )

    assert kept.rejects == ()
    assert [order.instrument_id for order in kept.orders] == ["B"]


@pytest.mark.parametrize(
    ("share", "bought", "left"),
    [(0.5, 40.0, 50.0), (1.0, 90.0, 0.0)],
    ids=["half", "all"],
)
def test_a_cash_share_is_a_budget_commission_included(
    share: float, bought: float, left: float
) -> None:
    """Audit N06: a share of 0.5 of 100 spent 55 once a minimum commission of 10 was paid."""
    floor = ExecutionModel(costs=CostModel(minimum_commission=10.0))

    done = trade(floor, book(100.0), {"A": share}, {"A": 1.0}, cash_shares={"A": share})

    assert done.state.quantity("A") == pytest.approx(bought)
    assert done.state.cash == pytest.approx(left)


def test_two_cash_shares_each_pay_their_own_commission() -> None:
    floor = ExecutionModel(costs=CostModel(minimum_commission=10.0))

    done = trade(
        floor,
        book(100.0),
        {"A": 0.5, "B": 0.5},
        {"A": 1.0, "B": 1.0},
        cash_shares={"A": 0.5, "B": 0.5},
    )

    assert done.state.quantity("A") == pytest.approx(40.0)
    assert done.state.quantity("B") == pytest.approx(40.0)
    assert done.state.cash == pytest.approx(0.0)


AT_DECISION = ExecutionModel(costs=CostModel(), sizing=Sizing.AT_DECISION)


def test_quantities_fixed_at_the_decision_are_cut_to_the_cash_after_a_gap_up() -> None:
    """C04: 100 fixed at the close of 100; the open prints 120; 10 000 buys 83.33 of them."""
    done = trade(
        AT_DECISION, book(10_000.0), {"A": 1.0}, {"A": 120.0}, decision_closes={"A": 100.0}
    )

    assert done.orders[0].quantity == pytest.approx(100.0)
    assert done.state.quantity("A") == pytest.approx(10_000.0 / 120.0)
    assert reasons(done) == {"A": ExecutionRejectReason.INSUFFICIENT_CASH}


def test_quantities_fixed_at_the_decision_leave_cash_after_a_gap_down() -> None:
    """The notional model would buy 125 at 80; an order fixed overnight buys its 100."""
    fixed = trade(
        AT_DECISION, book(10_000.0), {"A": 1.0}, {"A": 80.0}, decision_closes={"A": 100.0}
    )
    notional = trade(FREE, book(10_000.0), {"A": 1.0}, {"A": 80.0})

    assert fixed.state.quantity("A") == pytest.approx(100.0)
    assert fixed.state.cash == pytest.approx(2_000.0)
    assert notional.state.quantity("A") == pytest.approx(125.0)


def test_a_line_without_a_decision_close_is_refused_not_sized_on_the_open() -> None:
    done = trade(AT_DECISION, book(10_000.0), {"A": 1.0}, {"A": 100.0}, decision_closes={})

    assert reasons(done) == {"A": ExecutionRejectReason.NO_DECISION_PRICE}
    assert done.fills == ()


def test_the_sizing_is_named_where_the_run_records_it() -> None:
    assert FREE.definition()["fill_model"] == "OPEN_AUCTION_NOTIONAL"
    assert AT_DECISION.definition()["fill_model"] == "DECISION_CLOSE_QUANTITIES"


def test_decision_sizing_without_the_decision_closes_is_a_wiring_mistake() -> None:
    with pytest.raises(ValueError, match="decision's closes"):
        trade(AT_DECISION, book(10_000.0), {"A": 1.0}, {"A": 100.0})
