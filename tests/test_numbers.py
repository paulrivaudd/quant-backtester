"""The guards every declared number goes through.

Each case here is a value Python compares without complaining: ``NaN`` is
false against everything, ``True`` is an integer, an infinity is a perfectly
good float. A configuration that accepts one of them produces a run whose
numbers cannot be explained afterwards.
"""

from __future__ import annotations

import pytest

from quant_backtester.numbers import (
    require_finite,
    require_finite_non_negative,
    require_finite_positive,
    require_unit_fraction,
)

NOT_NUMBERS = [True, False, "0.5", None, (), [0.5]]
"""Values that are not numbers, ``True`` included: it is an ``int`` to Python."""


@pytest.mark.parametrize("value", NOT_NUMBERS)
def test_a_parameter_that_is_not_a_number_is_refused(value: object) -> None:
    """A boolean and a string both pass a type hint and neither is a quantity."""
    with pytest.raises(ValueError, match="must be a number"):
        require_finite(value, "rate")  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_a_parameter_that_is_not_finite_is_refused(value: float) -> None:
    """NaN compares false against every bound, so no later check would catch it."""
    with pytest.raises(ValueError, match="must be a finite number"):
        require_finite(value, "rate")


def test_a_finite_number_of_any_sign_is_accepted() -> None:
    """The plain guard is about being a number, not about being positive."""
    require_finite(-2.5, "threshold")
    require_finite(0, "threshold")


def test_a_negative_number_is_refused_where_zero_is_the_floor() -> None:
    """A cost of less than nothing is a rebate nobody was paid."""
    with pytest.raises(ValueError, match="must not be negative"):
        require_finite_non_negative(-0.01, "commission_rate")


def test_zero_is_a_value_but_not_a_positive_one() -> None:
    """The two guards differ on exactly one number, and it is the interesting one."""
    require_finite_non_negative(0.0, "commission_rate")

    with pytest.raises(ValueError, match="must be positive"):
        require_finite_positive(0.0, "initial_cash")


@pytest.mark.parametrize("value", [-0.001, 1.001, float("nan")])
def test_a_weight_outside_zero_and_one_is_refused(value: float) -> None:
    """Below zero is a short, above one is bought with money that is not there."""
    with pytest.raises(ValueError):
        require_unit_fraction(value, "the weight of ETF_EU")


@pytest.mark.parametrize("value", [0.0, 0.5, 1.0])
def test_both_ends_of_a_fraction_are_allowed(value: float) -> None:
    """Nothing and everything are both things a book can hold."""
    require_unit_fraction(value, "the weight of ETF_EU")
