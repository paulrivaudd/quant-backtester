"""A fill keeps both prices and three costs; a reject keeps its reason."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from quant_backtester.execution.costs import CostModel
from quant_backtester.execution.fills import (
    ExecutionReject,
    ExecutionRejectReason,
    Fill,
)
from quant_backtester.execution.orders import Order, Side

AT = datetime(2026, 9, 15, 7, 1, tzinfo=UTC)
COSTS = CostModel(commission_rate=0.001, half_spread_rate=0.002, slippage_rate=0.001)


def fill(side: Side = Side.BUY, quantity: float = 10.0, market: float = 100.0) -> Fill:
    """Fill an order in full at a market price, under the usual costs."""
    return Fill.of(Order("A", side, quantity, AT), market, COSTS)


def test_a_buy_is_filled_above_the_market_and_a_sale_below_it() -> None:
    """The spread and the slippage always point against the trader."""
    assert fill(Side.BUY).fill_price > fill(Side.BUY).market_price
    assert fill(Side.SELL).fill_price < fill(Side.SELL).market_price


def test_a_fill_keeps_every_cost_apart_and_they_check_by_hand() -> None:
    """Ten at 100: fill 100.3, commission 1.003, spread 2, slippage 1, total 4.003."""
    done = fill()

    assert done.fill_price == pytest.approx(100.3)
    assert done.commission == pytest.approx(1.003)
    assert done.spread_cost == pytest.approx(2.0)
    assert done.slippage_cost == pytest.approx(1.0)
    assert done.market_cost == pytest.approx(3.0)
    assert done.total_cost == pytest.approx(4.003)
    assert done.costs.total == pytest.approx(done.total_cost)


def test_the_market_cost_is_what_the_fill_price_moved_by() -> None:
    """Spread and slippage add up to the gap between the two prices, to the rounding."""
    done = fill()

    assert done.market_cost == pytest.approx(done.traded_value - done.market_value)


def test_a_purchase_takes_its_value_and_its_fee_out_of_cash() -> None:
    """At the fill price, commission on top."""
    done = fill()

    assert done.cash_flow == pytest.approx(-(1_003.0 + 1.003))
    assert done.gross_cash_flow == pytest.approx(-1_000.0)


def test_a_sale_brings_its_value_in_less_its_fee() -> None:
    """And the book that pays nothing receives the screen price."""
    done = fill(Side.SELL)

    assert done.cash_flow == pytest.approx(997.0 - 0.997)
    assert done.gross_cash_flow == pytest.approx(1_000.0)


def test_a_fill_is_done_when_its_order_was_sent() -> None:
    """A market order at the auction it was sent into."""
    assert fill().executed_at == AT


def test_a_fill_on_the_wrong_side_of_the_market_is_refused() -> None:
    """A buy below the market price would be paid to trade."""
    with pytest.raises(ValueError, match="would be paid to trade"):
        Fill(
            instrument_id="A",
            side=Side.BUY,
            quantity=1.0,
            market_price=100.0,
            fill_price=99.0,
            commission=0.0,
            spread_cost=0.0,
            slippage_cost=0.0,
            executed_at=AT,
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"quantity": 0.0},
        {"market_price": float("nan")},
        {"fill_price": -1.0},
        {"commission": -0.1},
        {"spread_cost": float("inf")},
        {"executed_at": datetime(2026, 9, 15, 9, 1)},
    ],
    ids=["no-units", "nan-price", "negative-fill", "negative-fee", "infinite-cost", "naive"],
)
def test_a_fill_that_could_not_have_happened_is_refused(overrides: dict[str, object]) -> None:
    """Every field of a trade is checked where the trade is written down."""
    fields: dict[str, object] = {
        "instrument_id": "A",
        "side": Side.BUY,
        "quantity": 1.0,
        "market_price": 100.0,
        "fill_price": 100.0,
        "commission": 0.0,
        "spread_cost": 0.0,
        "slippage_cost": 0.0,
        "executed_at": AT,
    }
    fields.update(overrides)

    with pytest.raises(ValueError):
        Fill(**fields)  # type: ignore[arg-type]


def test_a_reject_says_what_why_which_way_and_how_much() -> None:
    """The line a report counts when a book did not match its target."""
    reject = ExecutionReject("A", ExecutionRejectReason.INSUFFICIENT_CASH, Side.BUY, 3.0)

    assert reject.reason is ExecutionRejectReason.INSUFFICIENT_CASH
    assert reject.side is Side.BUY
    assert reject.requested_quantity == 3.0


def test_a_quantity_nobody_could_size_is_recorded_as_missing() -> None:
    """Without a price a purchase has no size, and that is recorded as none - never zero."""
    reject = ExecutionReject("A", ExecutionRejectReason.NO_EXECUTION_PRICE, Side.BUY)

    assert reject.requested_quantity is None


def test_a_reject_reason_must_be_one_of_the_reasons() -> None:
    """A free-text reason cannot be counted."""
    with pytest.raises(ValueError, match="ExecutionRejectReason"):
        ExecutionReject("A", "no price")  # type: ignore[arg-type]


@pytest.mark.parametrize("quantity", [0.0, -1.0, float("nan")])
def test_a_rejected_quantity_is_a_positive_number(quantity: float) -> None:
    """Zero units refused is no refusal, and a negative one is a sign gone wrong."""
    with pytest.raises(ValueError, match="the quantity rejected in A"):
        ExecutionReject("A", ExecutionRejectReason.BELOW_MINIMUM_TRADE, Side.BUY, quantity)


def test_the_reasons_are_the_ones_the_specification_lists() -> None:
    """Every refusal the execution layer can make, and no other."""
    assert {reason.value for reason in ExecutionRejectReason} == {
        "NON_TRADABLE",
        "NO_EXECUTION_PRICE",
        "STALE_EXECUTION_PRICE",
        "BELOW_MINIMUM_TRADE",
        "INSUFFICIENT_CASH",
        "INVALID_QUANTITY",
        "OUTSIDE_TRADING_UNIVERSE",
        "CURRENCY_MISMATCH",
    }
