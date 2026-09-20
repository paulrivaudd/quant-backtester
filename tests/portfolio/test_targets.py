"""Targets and holdings: an intention, a state, and no conversion between them."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from quant_backtester.portfolio.targets import Holdings, TargetAllocation
from quant_backtester.signals.types import SignalStatus

AS_OF = datetime(2026, 9, 14, 21, 0, tzinfo=UTC)


def allocation(**overrides: object) -> TargetAllocation:
    """Build a target allocation with the usual defaults."""
    parameters: dict[str, object] = {
        "as_of": AS_OF,
        "weights": {"A": 0.5, "B": 0.25},
        "selected": ("A", "B"),
        "considered": 3,
        "skipped": {"C": SignalStatus.MISSING_INPUT},
    }
    parameters.update(overrides)
    return TargetAllocation(**parameters)  # type: ignore[arg-type]


def test_an_allocation_says_how_much_it_puts_to_work() -> None:
    """It may well be less than everything, and that is not an error."""
    assert allocation().invested == pytest.approx(0.75)


def test_an_allocation_cannot_be_edited_afterwards() -> None:
    """A decision is a record of what was decided, not a working buffer."""
    target = allocation()

    with pytest.raises(TypeError):
        target.weights["A"] = 1.0  # type: ignore[index]
    with pytest.raises(TypeError):
        target.skipped["C"] = SignalStatus.OK  # type: ignore[index]


def test_holdings_are_worth_cash_plus_positions() -> None:
    """The only arithmetic in this file, and it needs prices from outside."""
    holdings = Holdings(cash=1_000.0, quantities={"A": 2.0, "B": 5.0})

    assert holdings.value_at({"A": 100.0, "B": 20.0}) == pytest.approx(1_300.0)


def test_a_closed_position_is_not_a_position() -> None:
    """A quantity of zero is dropped, so a book does not grow ghosts."""
    holdings = Holdings(cash=100.0, quantities={"A": 0.0, "B": 3.0})

    assert dict(holdings.quantities) == {"B": 3.0}


def test_valuing_a_position_without_a_price_is_refused() -> None:
    """Pricing it at nothing would show a loss that did not happen."""
    holdings = Holdings(cash=100.0, quantities={"A": 2.0})

    with pytest.raises(KeyError):
        holdings.value_at({"B": 10.0})


def test_weights_are_what_each_position_represents() -> None:
    """What the portfolio holds now, in the same units as what it wants."""
    holdings = Holdings(cash=500.0, quantities={"A": 5.0})

    assert holdings.weights_at({"A": 100.0}) == {"A": pytest.approx(0.5)}


def test_an_empty_book_has_no_weights() -> None:
    """And no division by a zero total."""
    assert Holdings(cash=0.0).weights_at({}) == {}


def test_a_short_is_not_an_allocation_this_project_can_hold() -> None:
    """Nothing here borrows a security, so a negative weight is refused at birth.

    A forecast score is negative for half a universe by construction, and the
    keystroke that turns one into a weight is a short position nobody financed.
    """
    with pytest.raises(ValueError, match="the weight of B"):
        allocation(weights={"A": 1.0, "B": -1.0}, selected=("A", "B"), considered=2)


def test_a_long_does_not_hide_a_short_behind_a_gross_that_nets_to_zero() -> None:
    """The refusal is per weight, so two positions cannot cancel their way past it."""
    with pytest.raises(ValueError):
        allocation(weights={"A": 1.0, "B": -1.0}, selected=("A", "B"), considered=2)


@pytest.mark.parametrize("weight", [float("nan"), float("inf"), 1.5, True])
def test_a_weight_that_is_not_a_fraction_is_refused(weight: object) -> None:
    """NaN compares false against every later check, and would size an order at NaN."""
    with pytest.raises(ValueError, match="the weight of A"):
        allocation(weights={"A": weight}, selected=("A",), considered=1)


def test_the_selection_and_the_weights_must_describe_the_same_book() -> None:
    """A name chosen with no weight, or weighted without being chosen, is a wiring bug."""
    with pytest.raises(ValueError, match="two different books"):
        allocation(weights={"A": 0.5}, selected=("A", "B"), considered=2)


def test_an_instrument_cannot_be_selected_twice() -> None:
    """Holding the same name twice is a weight written down twice."""
    with pytest.raises(ValueError, match="selected twice"):
        allocation(weights={"A": 0.5}, selected=("A", "A"), considered=2)


def test_more_instruments_cannot_be_chosen_than_were_considered() -> None:
    """``considered`` is what tells two of nine from two of two, so it must hold."""
    with pytest.raises(ValueError, match="were selected among"):
        allocation(weights={"A": 0.5, "B": 0.5}, selected=("A", "B"), considered=1)


def test_a_reason_for_skipping_must_be_one_of_the_statuses() -> None:
    """A free-text reason cannot be counted, and a report would print it as a count."""
    with pytest.raises(ValueError, match="not a SignalStatus"):
        allocation(skipped={"C": "no data"})


def test_an_instrument_cannot_be_both_held_and_skipped() -> None:
    """It was either chosen or it was not, and both is a decision nobody can read."""
    with pytest.raises(ValueError, match="both selected and skipped"):
        allocation(skipped={"A": SignalStatus.OK})


def test_a_decision_is_stamped_with_a_timezone() -> None:
    """A naive instant is a decision nobody can place against a market's close."""
    with pytest.raises(ValueError, match="timezone-aware"):
        allocation(as_of=datetime(2026, 9, 14, 21, 0))


def test_holdings_cannot_carry_a_short_position() -> None:
    """A negative quantity is borrowed stock, and no layer here pays a borrow fee."""
    with pytest.raises(ValueError, match="the quantity of A"):
        Holdings(cash=100.0, quantities={"A": -1.0})


@pytest.mark.parametrize("quantity", [float("nan"), float("inf")])
def test_a_quantity_that_is_not_a_number_is_refused(quantity: float) -> None:
    """One NaN quantity turns the whole equity curve into NaN, silently."""
    with pytest.raises(ValueError, match="the quantity of A"):
        Holdings(cash=100.0, quantities={"A": quantity})


def test_a_book_may_end_on_negative_cash_so_that_the_guard_can_see_it() -> None:
    """Execution never produces one; the diagnostic that counts them must still work."""
    assert Holdings(cash=-1.0).cash == -1.0
