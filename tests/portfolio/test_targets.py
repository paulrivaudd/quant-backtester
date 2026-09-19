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
