"""Limits: how much of the capital a view is allowed to move, and why a weight moved."""

from __future__ import annotations

import pytest

from quant_backtester.portfolio.limits import LimitAdjustment, PortfolioLimits


def test_an_allocation_inside_the_limits_is_untouched() -> None:
    """A limit that binds on nothing changes nothing, and says nothing."""
    wanted = {"A": 0.5, "B": 0.5}

    accepted, adjustments = PortfolioLimits(max_weight_per_instrument=0.6).apply(wanted)

    assert accepted == wanted
    assert adjustments == {}


def test_a_position_above_the_cap_is_trimmed_to_it_and_named() -> None:
    """The excess stays in cash rather than moving to the other names.

    Spreading it would replace the strategy's view with another one, and the
    report would show a performance nobody chose.
    """
    accepted, adjustments = PortfolioLimits(max_weight_per_instrument=0.4).apply(
        {"A": 0.7, "B": 0.3}
    )

    assert accepted == {"A": 0.4, "B": 0.3}
    assert adjustments == {"A": (LimitAdjustment.CAPPED_AT_MAX_WEIGHT,)}


def test_a_gross_limit_scales_every_weight_by_the_same_factor() -> None:
    """Trimming the largest would change the sizes the strategy chose."""
    accepted, adjustments = PortfolioLimits(max_gross=0.5).apply({"A": 0.6, "B": 0.4})

    assert accepted == {"A": pytest.approx(0.3), "B": pytest.approx(0.2)}
    assert adjustments == {
        "A": (LimitAdjustment.SCALED_TO_MAX_GROSS,),
        "B": (LimitAdjustment.SCALED_TO_MAX_GROSS,),
    }


def test_the_two_limits_apply_in_order_and_both_are_named() -> None:
    """Capped first, then scaled if what is left still exceeds the gross."""
    accepted, adjustments = PortfolioLimits(max_weight_per_instrument=0.5, max_gross=0.8).apply(
        {"A": 0.9, "B": 0.1}
    )

    assert sum(accepted.values()) == pytest.approx(0.6)
    accepted, adjustments = PortfolioLimits(max_weight_per_instrument=0.5, max_gross=0.5).apply(
        {"A": 0.9, "B": 0.1}
    )
    assert sum(accepted.values()) == pytest.approx(0.5)
    assert adjustments["A"] == (
        LimitAdjustment.CAPPED_AT_MAX_WEIGHT,
        LimitAdjustment.SCALED_TO_MAX_GROSS,
    )
    assert adjustments["B"] == (LimitAdjustment.SCALED_TO_MAX_GROSS,)


def test_a_zero_weight_is_never_scaled() -> None:
    """Scaling nothing is not an adjustment, and must not be reported as one."""
    accepted, adjustments = PortfolioLimits(max_gross=0.5).apply({"A": 1.0, "B": 0.0})

    assert accepted["B"] == 0.0
    assert "B" not in adjustments


def test_a_gross_within_the_tolerance_is_floating_point_dust() -> None:
    """A book asked to be fully invested is not "scaled" by one ulp and reported as such."""
    accepted, adjustments = PortfolioLimits().apply({"A": 0.7, "B": 0.2, "C": 0.1 + 1e-12})

    assert adjustments == {}
    assert accepted["C"] == 0.1 + 1e-12


def test_the_gross_is_the_sum_of_the_absolute_weights() -> None:
    """The definition that stays right the day a short is allowed: long and short add up.

    A target refuses a negative weight long before it reaches a limit; the
    arithmetic is checked on one anyway, because a gross measured as the plain
    sum would see a long and a short of the same size as no exposure at all.
    """
    accepted, _ = PortfolioLimits(max_gross=0.5).apply({"A": 0.4, "B": -0.4})

    assert accepted == {"A": pytest.approx(0.25), "B": pytest.approx(-0.25)}


def test_the_accepted_weights_come_back_in_instrument_order() -> None:
    """Two strategies returning the same weights in two orders record the same decision."""
    accepted, _ = PortfolioLimits().apply({"B": 0.5, "A": 0.5})

    assert list(accepted) == ["A", "B"]


def test_the_limits_describe_themselves_for_the_record() -> None:
    """A result says which limits it ran under, long-only included."""
    assert PortfolioLimits(max_weight_per_instrument=0.4).definition() == {
        "max_weight_per_instrument": 0.4,
        "max_gross": 1.0,
        "long_only": True,
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {"max_weight_per_instrument": 0.0},
        {"max_weight_per_instrument": 1.5},
        {"max_gross": -0.1},
        {"max_gross": 2.0},
        {"max_gross": float("nan")},
        {"max_weight_per_instrument": True},
    ],
    ids=["zero-cap", "cap-above-one", "negative-gross", "leverage", "nan", "bool"],
)
def test_a_limit_that_is_not_a_fraction_is_refused(overrides: dict[str, object]) -> None:
    """Leverage is refused because nothing below models a financing cost."""
    with pytest.raises(ValueError, match="max_"):
        PortfolioLimits(**overrides)  # type: ignore[arg-type]


@pytest.mark.parametrize("long_only", [False, 1, None])
def test_a_book_that_may_go_short_is_refused(long_only: object) -> None:
    """A short needs a borrow, a fee, a margin and a liquidation rule, and none exists."""
    with pytest.raises(ValueError, match="long_only"):
        PortfolioLimits(long_only=long_only)  # type: ignore[arg-type]
