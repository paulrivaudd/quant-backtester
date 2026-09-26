"""Targets: an intention, stated in fractions of a book that could exist."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from quant_backtester.portfolio.targets import WEIGHT_SUM_TOLERANCE, TargetAllocation
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


def test_weights_adding_up_to_more_than_the_book_are_refused() -> None:
    """A sum above one is leverage, and nothing here finances it."""
    with pytest.raises(ValueError, match="add up to"):
        allocation(weights={"A": 0.6, "B": 0.5}, selected=("A", "B"), considered=2)


def test_a_sum_above_one_by_floating_point_dust_is_still_the_whole_book() -> None:
    """Arithmetic lands an ulp above one; the tolerance forgives that and nothing else."""
    target = allocation(
        weights={"A": 0.5, "B": 0.5 + WEIGHT_SUM_TOLERANCE / 2}, selected=("A", "B"), considered=2
    )

    assert target.invested == pytest.approx(1.0)


def test_what_is_not_allocated_is_cash() -> None:
    """Cash needs no line of its own."""
    target = allocation(weights={"A": 0.75}, selected=("A",), considered=1, skipped={})

    assert target.cash == pytest.approx(0.25)


def test_the_gross_is_the_sum_of_the_absolute_weights() -> None:
    """Equal to what is invested for as long as the project is long-only."""
    target = allocation()

    assert target.gross == pytest.approx(0.75)
    assert target.gross == target.invested


def test_the_simple_contract_needs_only_an_instant_and_weights() -> None:
    """A list of weights carries no ranking, so the selection is the weights in id order."""
    target = TargetAllocation(as_of=AS_OF, weights={"B": 0.4, "A": 0.6})

    assert target.selected == ("A", "B")
    assert target.considered == 2
    assert dict(target.skipped) == {}


def test_a_book_of_cash_needs_no_weight_at_all() -> None:
    """Holding nothing is a decision, and it is written as an empty target."""
    target = TargetAllocation(as_of=AS_OF, weights={})

    assert target.invested == 0.0
    assert target.cash == 1.0
    assert target.selected == ()
    assert target.considered == 0


def test_what_is_invested_does_not_depend_on_the_order_the_weights_were_written_in() -> None:
    """An exact sum, so two identical decisions written two ways record the same number."""
    weights = {"A": 0.1, "B": 0.2, "C": 0.3, "D": 0.4}
    reversed_weights = dict(reversed(list(weights.items())))

    forward = TargetAllocation(as_of=AS_OF, weights=weights)
    backward = TargetAllocation(as_of=AS_OF, weights=reversed_weights)

    assert forward.invested == backward.invested


def test_the_caller_cannot_edit_an_allocation_through_the_mapping_it_passed() -> None:
    """The weights are copied at construction; the strategy's dict stays the strategy's."""
    weights = {"A": 0.5}
    target = TargetAllocation(as_of=AS_OF, weights=weights)

    weights["A"] = 1.0

    assert target.weights["A"] == 0.5


def test_an_allocation_does_not_hold_its_positions_unless_it_says_so() -> None:
    """Weights are a target to trade towards; keeping the book is a separate statement."""
    assert TargetAllocation(as_of=AS_OF, weights={"A": 0.5}).hold_positions is False
    assert TargetAllocation(as_of=AS_OF, weights={"A": 0.5}, hold_positions=True).hold_positions


@pytest.mark.parametrize("flag", [1, "yes", None])
def test_holding_is_said_as_a_boolean(flag: object) -> None:
    """A truthy value is not a decision to hold."""
    with pytest.raises(ValueError, match="hold_positions"):
        TargetAllocation(as_of=AS_OF, weights={}, hold_positions=flag)  # type: ignore[arg-type]


def test_a_kept_line_needs_a_weight() -> None:
    with pytest.raises(ValueError, match="kept and has no weight"):
        TargetAllocation(as_of=AS_OF, weights={"A": 0.5}, kept=frozenset({"B"}))


def test_a_whole_hold_has_no_lines_to_keep_apart() -> None:
    with pytest.raises(ValueError, match="no lines to keep apart"):
        TargetAllocation(
            as_of=AS_OF, weights={"A": 0.5}, hold_positions=True, kept=frozenset({"A"})
        )


def test_cash_shares_add_up_to_at_most_the_cash() -> None:
    with pytest.raises(ValueError, match="more than the cash"):
        TargetAllocation(
            as_of=AS_OF, weights={"A": 0.3, "B": 0.3}, cash_shares={"A": 0.6, "B": 0.6}
        )


def test_a_cash_share_is_a_line_of_the_target_and_not_a_kept_one() -> None:
    with pytest.raises(ValueError, match="not kept ones"):
        TargetAllocation(
            as_of=AS_OF,
            weights={"A": 0.5, "B": 0.5},
            kept=frozenset({"A"}),
            cash_shares={"A": 1.0},
        )
    with pytest.raises(ValueError, match="lines of the target"):
        TargetAllocation(as_of=AS_OF, weights={"A": 0.5}, cash_shares={"B": 1.0})
