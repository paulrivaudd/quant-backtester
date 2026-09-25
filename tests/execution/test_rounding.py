"""Whole lots, rounded the one safe way: down, and never by floating-point accident."""

from __future__ import annotations

import pytest

from quant_backtester.execution.rounding import (
    LOT_TOLERANCE,
    is_whole_lots,
    round_down_to_lot,
    target_quantity,
    whole_lots,
)


def test_three_point_seven_shares_are_three() -> None:
    """A purchase is never rounded up: the cash for the extra unit was never set aside."""
    assert round_down_to_lot(3.7, 1.0) == 3.0


def test_a_quantity_on_the_grid_is_left_alone() -> None:
    """A hundred whole shares are a hundred, not 99.999999999999986."""
    assert round_down_to_lot(100.0, 1.0) == 100.0
    assert whole_lots(100.0, 1.0) == 100


def test_floating_point_dust_below_a_lot_does_not_cost_a_share() -> None:
    """``300.09 / 100.03`` is ``2.9999999999999996``, and the arithmetic meant three."""
    assert 300.09 / 100.03 < 3.0
    assert target_quantity(300.09, 100.03, 1.0) == 3.0


def test_a_real_shortfall_below_a_lot_is_not_forgiven() -> None:
    """The tolerance absorbs representation error and nothing else."""
    assert round_down_to_lot(3.0 - 1e-6, 1.0) == 2.0


def test_the_tolerance_is_a_billionth_of_a_lot() -> None:
    """Far above floating-point error, far below anything anyone trades."""
    assert LOT_TOLERANCE == 1e-9


def test_lots_of_a_fraction_are_counted_as_whole_lots() -> None:
    """A step of a quarter deals quarters, and 1.3 of them is five."""
    assert whole_lots(1.3, 0.25) == 5
    assert round_down_to_lot(1.3, 0.25) == pytest.approx(1.25)


def test_without_a_step_nothing_is_rounded() -> None:
    """An instrument dealt in fractions keeps its fractions."""
    assert round_down_to_lot(3.7, None) == 3.7
    assert target_quantity(1_000.0, 300.0, None) == pytest.approx(1_000.0 / 300.0)


def test_a_value_buys_whole_lots_at_a_price() -> None:
    """Ten thousand at 300 is 33.33 shares, and a broker takes 33."""
    assert target_quantity(10_000.0, 300.0, 1.0) == 33.0


@pytest.mark.parametrize(
    ("quantity", "step", "expected"),
    [
        (3.0, 1.0, True),
        (3.5, 1.0, False),
        (3.0 + 1e-12, 1.0, True),
        (0.3, 0.1, True),
        (2.0, None, True),
    ],
)
def test_whether_a_quantity_is_whole_lots(
    quantity: float, step: float | None, expected: bool
) -> None:
    """Checked with the same tolerance the rounding uses, so the two never disagree."""
    assert is_whole_lots(quantity, step) is expected


@pytest.mark.parametrize("quantity", [-1.0, float("nan")])
def test_a_quantity_that_is_not_one_is_refused(quantity: float) -> None:
    """Rounding a negative quantity down would make it more negative."""
    with pytest.raises(ValueError, match="quantity"):
        round_down_to_lot(quantity, 1.0)


@pytest.mark.parametrize("step", [0.0, -1.0, float("nan")])
def test_a_step_that_is_not_a_lot_is_refused(step: float) -> None:
    """A step of zero would divide by nothing, and a negative one has no meaning."""
    with pytest.raises(ValueError, match="step"):
        whole_lots(1.0, step)


def test_a_price_that_is_not_one_is_refused() -> None:
    """A quantity sized at a price of zero is infinite."""
    with pytest.raises(ValueError, match="price"):
        target_quantity(100.0, 0.0, 1.0)


def test_rounding_down_matches_a_naive_loop() -> None:
    """The vectorised-looking floor against the slow obvious count of lots."""
    for quantity in (0.0, 0.9, 1.0, 7.3, 99.999, 100.0, 12345.6):
        lots = 0
        while (lots + 1) * 1.0 <= quantity + 1e-9:
            lots += 1
        assert whole_lots(quantity, 1.0) == lots
