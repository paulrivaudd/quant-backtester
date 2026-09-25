"""One position: a quantity that cannot go short, and what it cost."""

from __future__ import annotations

import pytest

from quant_backtester.portfolio.holdings import Holding


def test_a_position_is_worth_its_quantity_at_a_price() -> None:
    """The only arithmetic a holding does, and it needs the price from outside."""
    assert Holding("A", 5.0).value_at(20.0) == pytest.approx(100.0)


@pytest.mark.parametrize("price", [0.0, -1.0, float("nan"), float("inf")])
def test_a_position_is_never_valued_at_a_price_that_is_not_one(price: float) -> None:
    """A NaN price values the position at NaN, and the equity curve with it."""
    with pytest.raises(ValueError, match="the price of A"):
        Holding("A", 5.0).value_at(price)


@pytest.mark.parametrize("quantity", [-1.0, float("nan"), float("inf"), True])
def test_a_quantity_that_could_not_be_held_is_refused(quantity: object) -> None:
    """A negative quantity is borrowed stock, and no layer here pays a borrow fee."""
    with pytest.raises(ValueError, match="the quantity of A"):
        Holding("A", quantity)  # type: ignore[arg-type]


@pytest.mark.parametrize("cost", [0.0, -5.0, float("nan")])
def test_an_average_cost_that_is_not_a_price_is_refused(cost: float) -> None:
    """A cost of zero would make every position look like a gain."""
    with pytest.raises(ValueError, match="the average cost of A"):
        Holding("A", 1.0, average_cost=cost)


def test_a_position_needs_a_name() -> None:
    """An empty id makes a record unreadable."""
    with pytest.raises(ValueError, match="instrument_id"):
        Holding(" ", 1.0)


def test_a_first_purchase_sets_the_average_cost() -> None:
    """What the cash went out at, costs included."""
    bought = Holding("A", 0.0).bought(10.0, 101.0)

    assert bought.quantity == 10.0
    assert bought.average_cost == pytest.approx(101.0)


def test_a_second_purchase_averages_by_quantity() -> None:
    """Ten at 100 and thirty at 120 cost 115 each, on average."""
    held = Holding("A", 10.0, average_cost=100.0).bought(30.0, 120.0)

    assert held.quantity == 40.0
    assert held.average_cost == pytest.approx(115.0)


def test_an_unknown_cost_stays_unknown() -> None:
    """Averaging a known price into an unknown one would invent a number."""
    held = Holding("A", 10.0).bought(5.0, 100.0)

    assert held.quantity == 15.0
    assert held.average_cost is None


@pytest.mark.parametrize(("quantity", "price"), [(0.0, 100.0), (1.0, 0.0), (-1.0, 100.0)])
def test_a_purchase_of_nothing_or_for_nothing_is_refused(quantity: float, price: float) -> None:
    """Either is a bug in the layer that sized the order."""
    with pytest.raises(ValueError):
        Holding("A", 1.0).bought(quantity, price)


def test_a_sale_does_not_change_what_the_rest_cost() -> None:
    """Selling half a position does not change what the other half cost."""
    held = Holding("A", 10.0, average_cost=100.0).sold(4.0)

    assert held.quantity == 6.0
    assert held.average_cost == 100.0


def test_selling_everything_leaves_nothing() -> None:
    """A position closed in full closes to exactly zero."""
    assert Holding("A", 3.0).sold(3.0).quantity == 0.0


def test_selling_more_than_is_held_is_refused() -> None:
    """Nothing here goes short, so this is a sizing bug rather than a position."""
    with pytest.raises(ValueError, match="short position"):
        Holding("A", 3.0).sold(4.0)


def test_a_holding_cannot_be_edited_afterwards() -> None:
    """A position changes by producing a new one, so a record keeps the old."""
    held = Holding("A", 3.0)

    with pytest.raises(AttributeError):
        held.quantity = 4.0  # type: ignore[misc]
