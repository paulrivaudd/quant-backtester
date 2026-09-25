"""The book as it is: cash never negative, positions never short, estimates named."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from quant_backtester.data.reader import Observation, ObservationStatus
from quant_backtester.portfolio.holdings import Holding
from quant_backtester.portfolio.state import (
    PortfolioState,
    UnvaluablePosition,
    ValuationResult,
    value_state,
)

AS_OF = datetime(2026, 9, 14, 7, 1, tzinfo=UTC)
LATER = AS_OF + timedelta(days=1)


def book(cash: float = 1_000.0, **quantities: float) -> PortfolioState:
    """Build a book holding ``cash`` and the given quantities, with no known costs."""
    return PortfolioState(
        as_of=AS_OF,
        cash=cash,
        holdings={name: Holding(name, size) for name, size in quantities.items()},
    )


def seen(instrument_id: str, value: float | None, status: ObservationStatus) -> Observation:
    """Return an observation as the reader hands one over."""
    return Observation(
        instrument_id=instrument_id,
        value=value,
        status=status,
        observation_date=date(2026, 9, 14) if value is not None else None,
        available_at=AS_OF if value is not None else None,
        age_sessions=0 if status is ObservationStatus.OK else (1 if value is not None else None),
    )


# -- what a state is -----------------------------------------------------------


def test_a_run_starts_with_nothing_but_cash() -> None:
    """No position is held that the run did not buy."""
    state = PortfolioState.opening(10_000.0, AS_OF)

    assert state.cash == 10_000.0
    assert dict(state.holdings) == {}


@pytest.mark.parametrize("cash", [-0.01, float("nan"), float("inf"), True])
def test_cash_below_zero_or_not_a_number_is_refused(cash: object) -> None:
    """Negative cash is a loan nobody granted, and it cannot even be written down."""
    with pytest.raises(ValueError, match="cash"):
        PortfolioState(as_of=AS_OF, cash=cash)  # type: ignore[arg-type]


def test_a_state_is_stamped_with_a_timezone() -> None:
    """It starts to hold at an instant, and a naive one belongs to no market."""
    with pytest.raises(ValueError, match="timezone-aware"):
        PortfolioState(as_of=datetime(2026, 9, 14, 9, 1), cash=0.0)


def test_a_holding_filed_under_another_name_is_refused() -> None:
    """The key and the position must name the same instrument."""
    with pytest.raises(ValueError, match="is filed under"):
        PortfolioState(as_of=AS_OF, cash=0.0, holdings={"A": Holding("B", 1.0)})


def test_a_holding_must_be_a_holding() -> None:
    """A bare quantity carries no cost and no identity, and is refused."""
    with pytest.raises(ValueError, match="not a Holding"):
        PortfolioState(as_of=AS_OF, cash=0.0, holdings={"A": 1.0})  # type: ignore[dict-item]


def test_a_closed_position_is_not_a_position() -> None:
    """A quantity of zero is dropped, so a book does not grow ghosts."""
    assert list(book(A=0.0, B=3.0).holdings) == ["B"]


def test_positions_are_kept_in_instrument_order() -> None:
    """Two books holding the same things are the same book, whatever order they were given in."""
    assert list(book(C=1.0, A=1.0, B=1.0).holdings) == ["A", "B", "C"]


def test_a_state_cannot_be_edited_afterwards() -> None:
    """A book changes by producing a new state, so every record keeps its own."""
    state = book(A=1.0)

    with pytest.raises(TypeError):
        state.holdings["B"] = Holding("B", 1.0)  # type: ignore[index]
    with pytest.raises(TypeError):
        state.quantities["A"] = 2.0  # type: ignore[index]


def test_a_quantity_is_zero_for_what_is_not_held() -> None:
    """How much of this do I hold has an answer for every name."""
    state = book(A=2.0)

    assert state.quantity("A") == 2.0
    assert state.quantity("B") == 0.0
    assert state.holds("A")
    assert not state.holds("B")


# -- what it is worth ------------------------------------------------------------


def test_a_book_is_worth_cash_plus_positions() -> None:
    """Summed exactly, in instrument order."""
    assert book(1_000.0, A=2.0, B=5.0).value_at({"A": 100.0, "B": 20.0}) == pytest.approx(1_300.0)


def test_valuing_a_position_without_a_price_is_refused() -> None:
    """Pricing it at nothing would show a loss that did not happen."""
    with pytest.raises(KeyError):
        book(100.0, A=2.0).value_at({"B": 10.0})


def test_weights_are_what_each_position_represents() -> None:
    """What the portfolio holds, in the same units as what it wants."""
    assert book(500.0, A=5.0).weights_at({"A": 100.0}) == {"A": pytest.approx(0.5)}


def test_an_empty_book_has_no_weights() -> None:
    """And no division by a zero total."""
    assert book(0.0).weights_at({}) == {}


# -- trading -----------------------------------------------------------------------


def test_a_purchase_takes_its_cost_out_of_cash_and_records_it() -> None:
    """The average cost is what the cash went out at, commission included."""
    after = book(1_000.0).bought("A", 4.0, 404.0, LATER)

    assert after.cash == pytest.approx(596.0)
    assert after.quantity("A") == 4.0
    assert after.holdings["A"].average_cost == pytest.approx(101.0)
    assert after.as_of == LATER


def test_a_purchase_the_cash_cannot_pay_for_is_refused() -> None:
    """Cash below zero is a loan nobody granted."""
    with pytest.raises(ValueError, match="nothing here lends"):
        book(100.0).bought("A", 2.0, 100.01, LATER)


def test_a_purchase_paying_exactly_the_cash_there_is_leaves_zero() -> None:
    """Zero is a balance, not a loan."""
    assert book(100.0).bought("A", 1.0, 100.0, LATER).cash == 0.0


def test_a_sale_brings_its_proceeds_into_cash() -> None:
    """And leaves what was not sold at the cost it had."""
    state = PortfolioState(
        as_of=AS_OF, cash=0.0, holdings={"A": Holding("A", 10.0, average_cost=90.0)}
    )

    after = state.sold("A", 4.0, 398.0, LATER)

    assert after.cash == pytest.approx(398.0)
    assert after.quantity("A") == 6.0
    assert after.holdings["A"].average_cost == 90.0


def test_a_position_sold_in_full_disappears() -> None:
    """It does not stay in the book at a quantity of zero."""
    assert not book(0.0, A=3.0).sold("A", 3.0, 300.0, LATER).holds("A")


def test_a_sale_of_what_is_not_held_is_refused() -> None:
    """Selling nothing that exists is a short, and nothing finances one."""
    with pytest.raises(ValueError, match="is not held"):
        book(100.0).sold("A", 1.0, 100.0, LATER)


def test_a_sale_larger_than_the_position_is_refused() -> None:
    """The position cannot go below zero."""
    with pytest.raises(ValueError, match="short position"):
        book(0.0, A=1.0).sold("A", 2.0, 200.0, LATER)


def test_a_commission_larger_than_the_sale_is_paid_from_cash() -> None:
    """A floor above the value sold takes money out of the account."""
    assert book(10.0, A=1.0).sold("A", 1.0, -3.0, LATER).cash == pytest.approx(7.0)


def test_a_commission_the_cash_cannot_cover_is_refused() -> None:
    """The fee would be paid with money the book has not got."""
    with pytest.raises(ValueError, match="has not got"):
        book(1.0, A=1.0).sold("A", 1.0, -3.0, LATER)


def test_a_trade_dated_before_the_state_it_changes_is_refused() -> None:
    """Time runs one way."""
    with pytest.raises(ValueError, match="time runs one way"):
        book(1_000.0).bought("A", 1.0, 100.0, AS_OF - timedelta(seconds=1))


def test_a_trade_needs_an_aware_instant() -> None:
    """A naive instant cannot be placed against the state's."""
    with pytest.raises(ValueError, match="timezone-aware"):
        book(1_000.0).bought("A", 1.0, 100.0, datetime(2026, 9, 15, 9, 1))


# -- valuation ---------------------------------------------------------------------


def test_a_price_of_the_session_is_not_an_estimate() -> None:
    """The close of the session itself values the position as it is."""
    valuation = value_state(
        book(100.0, A=2.0), {"A": seen("A", 50.0, ObservationStatus.OK)}, {}, AS_OF
    )

    assert valuation.equity == pytest.approx(200.0)
    assert dict(valuation.prices) == {"A": 50.0}
    assert valuation.estimated_instruments == ()
    assert not valuation.is_estimate


def test_a_stale_close_values_the_position_and_says_so() -> None:
    """A real number from an earlier session, and still an estimate of today's."""
    valuation = value_state(
        book(0.0, A=2.0), {"A": seen("A", 48.0, ObservationStatus.STALE)}, {"A": 47.0}, AS_OF
    )

    assert dict(valuation.prices) == {"A": 48.0}
    assert valuation.estimated_instruments == ("A",)


def test_a_missing_close_falls_back_on_the_last_price_known_and_says_so() -> None:
    """The venue held the session and the close is not there: the last price the run knew."""
    valuation = value_state(
        book(0.0, A=2.0), {"A": seen("A", None, ObservationStatus.MISSING)}, {"A": 47.0}, AS_OF
    )

    assert dict(valuation.prices) == {"A": 47.0}
    assert valuation.estimated_instruments == ("A",)


def test_a_position_with_no_price_at_all_stops_the_run() -> None:
    """Inventing zero would show a loss that did not happen and give it back the next day."""
    with pytest.raises(UnvaluablePosition, match="never had a knowable price"):
        value_state(book(0.0, A=2.0), {"A": seen("A", None, ObservationStatus.MISSING)}, {}, AS_OF)


def test_a_position_in_an_instrument_that_is_not_listed_stops_the_run() -> None:
    """A delisted position has to be closed, and this model does not know at what price."""
    with pytest.raises(UnvaluablePosition, match="not listed"):
        value_state(
            book(0.0, A=2.0),
            {"A": seen("A", None, ObservationStatus.NOT_LISTED)},
            {"A": 47.0},
            AS_OF,
        )


def test_a_held_position_nobody_read_is_a_wiring_mistake() -> None:
    """The caller reads every position; one missing from the reading is a bug."""
    with pytest.raises(KeyError):
        value_state(book(0.0, A=2.0), {}, {"A": 47.0}, AS_OF)


def test_an_unvaluable_position_is_a_value_error() -> None:
    """So a caller catching configuration mistakes catches this one too."""
    assert issubclass(UnvaluablePosition, ValueError)


def test_a_valuation_names_only_positions_it_priced() -> None:
    """An estimate of something that has no price is not an estimate."""
    with pytest.raises(ValueError, match="has no price"):
        ValuationResult(as_of=AS_OF, equity=0.0, prices={}, estimated_instruments=("A",))


@pytest.mark.parametrize("price", [0.0, float("nan")])
def test_a_valuation_price_that_is_not_one_is_refused(price: float) -> None:
    """A book marked at zero or NaN is a book whose equity means nothing."""
    with pytest.raises(ValueError, match="valuation price of A"):
        ValuationResult(as_of=AS_OF, equity=0.0, prices={"A": price})


def test_a_valuation_is_stamped_with_a_timezone() -> None:
    """It belongs to one instant."""
    with pytest.raises(ValueError, match="timezone-aware"):
        ValuationResult(as_of=datetime(2026, 9, 14, 23, 0), equity=0.0, prices={})
