"""What a strategy is allowed to know about the book it manages."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from quant_backtester.portfolio.holdings import Holding
from quant_backtester.portfolio.state import PortfolioState
from quant_backtester.portfolio.view import PortfolioView

AS_OF = datetime(2026, 9, 14, 21, 0, tzinfo=UTC)


def book(cash: float = 500.0, quantities: dict[str, float] | None = None) -> PortfolioState:
    """Build a book holding five units of A unless told otherwise."""
    held = quantities if quantities is not None else {"A": 5.0}
    return PortfolioState(
        as_of=AS_OF,
        cash=cash,
        holdings={name: Holding(name, size) for name, size in held.items()},
    )


def view(cash: float = 500.0, quantities: dict[str, float] | None = None) -> PortfolioView:
    """Build the view of a book holding five units of A at 100."""
    return PortfolioView.of(book(cash, quantities), {"A": 100.0}, AS_OF)


def test_a_view_says_what_the_book_is_worth() -> None:
    """Cash plus positions, at the closes the run valued them at."""
    assert view().equity == pytest.approx(1_000.0)


def test_a_weight_is_the_fraction_of_equity_a_position_represents() -> None:
    """The same units a target is expressed in, so the two can be compared."""
    assert view().weight("A") == pytest.approx(0.5)


def test_a_name_that_is_not_held_weighs_nothing() -> None:
    """How much of this do I hold: the question has an answer for every name."""
    assert view().weight("B") == 0.0
    assert view().quantity("B") == 0.0
    assert not view().holds("B")


def test_a_book_of_cash_is_not_invested() -> None:
    """And it has no weights to speak of."""
    empty = view(cash=1_000.0, quantities={})

    assert empty.invested == 0.0
    assert dict(empty.weights) == {}


def test_a_view_cannot_be_edited_after_the_fact() -> None:
    """A decision reads the book; it does not rewrite it."""
    held = view()

    with pytest.raises(TypeError):
        held.quantities["A"] = 1.0  # type: ignore[index]
    with pytest.raises(TypeError):
        held.weights["A"] = 1.0  # type: ignore[index]
    with pytest.raises(TypeError):
        held.average_costs["A"] = 1.0  # type: ignore[index]


def test_a_view_is_stamped_with_a_timezone() -> None:
    """It belongs to one decision, and a naive instant belongs to none."""
    with pytest.raises(ValueError, match="timezone-aware"):
        PortfolioView(as_of=datetime(2026, 9, 14, 21, 0), cash=0.0, equity=0.0)


def test_a_figure_that_is_not_a_number_is_refused() -> None:
    """A strategy comparing a weight against a threshold must not compare a NaN."""
    with pytest.raises(ValueError, match="equity"):
        PortfolioView(as_of=AS_OF, cash=0.0, equity=float("nan"))


def test_valuing_a_position_without_a_price_is_refused() -> None:
    """The view is what the run believes the book is worth, not a guess about it."""
    with pytest.raises(KeyError):
        PortfolioView.of(book(0.0, {"A": 1.0}), {}, AS_OF)


def test_a_view_carries_what_each_position_cost() -> None:
    """A stop or a take-profit is measured against what was actually paid."""
    state = PortfolioState(
        as_of=AS_OF, cash=0.0, holdings={"A": Holding("A", 5.0, average_cost=90.0)}
    )

    seen = PortfolioView.of(state, {"A": 100.0}, AS_OF)

    assert seen.average_cost("A") == 90.0


def test_a_cost_nobody_knows_is_not_a_cost_of_nothing() -> None:
    """A position with no history, or none at all, has no average cost - never zero."""
    assert view().average_cost("A") is None
    assert view().average_cost("B") is None


def test_an_average_cost_that_is_not_a_price_is_refused() -> None:
    """A stop measured against zero or NaN never fires, or always does."""
    with pytest.raises(ValueError, match="average cost of A"):
        PortfolioView(as_of=AS_OF, cash=0.0, equity=0.0, average_costs={"A": 0.0})
