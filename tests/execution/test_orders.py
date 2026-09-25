"""An order: an instrument, a direction, a quantity, an instant, and nothing more."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from quant_backtester.execution.orders import Order, Side

AT = datetime(2026, 9, 15, 7, 1, tzinfo=UTC)


def test_an_order_carries_its_direction_in_its_side() -> None:
    """The quantity is always positive; the side says which way."""
    assert Order("A", Side.BUY, 3.0, AT).signed_quantity == 3.0
    assert Order("A", Side.SELL, 3.0, AT).signed_quantity == -3.0


@pytest.mark.parametrize("quantity", [0.0, -1.0, float("nan"), float("inf"), True])
def test_an_order_of_no_units_is_not_an_order(quantity: object) -> None:
    """A zero, a negative or a NaN quantity is a bug in whoever built it."""
    with pytest.raises(ValueError, match="the quantity of the order in A"):
        Order("A", Side.BUY, quantity, AT)  # type: ignore[arg-type]


def test_an_order_is_sent_at_an_instant_with_a_timezone() -> None:
    """A naive instant cannot be placed against the auction it is sized on."""
    with pytest.raises(ValueError, match="submitted_at"):
        Order("A", Side.BUY, 1.0, datetime(2026, 9, 15, 9, 1))


def test_an_order_names_what_it_trades() -> None:
    """An empty id would be a line nobody could audit."""
    with pytest.raises(ValueError, match="instrument_id"):
        Order("", Side.BUY, 1.0, AT)


def test_an_order_has_a_side_and_not_a_sign() -> None:
    """A string is not a side, and a typo in it would be a direction nobody meant."""
    with pytest.raises(ValueError, match="side"):
        Order("A", "BUY", 1.0, AT)  # type: ignore[arg-type]


def test_there_is_no_short_side() -> None:
    """Selling is only ever selling what is held."""
    assert {side.value for side in Side} == {"BUY", "SELL"}


@pytest.mark.parametrize(
    ("quantity", "step", "whole"),
    [(3.0, 1.0, True), (3.5, 1.0, False), (0.25, 0.25, True), (3.7, None, True)],
)
def test_an_order_knows_whether_it_is_whole_lots(
    quantity: float, step: float | None, whole: bool
) -> None:
    """Where a venue deals in lots, an order is a whole number of them."""
    assert Order("A", Side.BUY, quantity, AT).is_whole_lots(step) is whole


def test_an_order_cannot_be_edited_afterwards() -> None:
    """What was sent is what the record says was sent."""
    order = Order("A", Side.BUY, 1.0, AT)

    with pytest.raises(AttributeError):
        order.quantity = 2.0  # type: ignore[misc]
