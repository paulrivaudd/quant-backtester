"""Limits: how much of the capital a view is allowed to move."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from quant_backtester.portfolio.limits import PositionLimits
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.signals.types import SignalStatus

AS_OF = datetime(2026, 9, 14, 21, 0, tzinfo=UTC)


def allocation(weights: dict[str, float]) -> TargetAllocation:
    """Build an allocation asking for those weights."""
    return TargetAllocation(
        as_of=AS_OF,
        weights=weights,
        selected=tuple(weights),
        considered=len(weights),
        skipped={"D": SignalStatus.NOT_LISTED},
    )


def test_an_allocation_inside_the_limits_is_untouched() -> None:
    """A limit that binds on nothing changes nothing."""
    wanted = {"A": 0.5, "B": 0.5}

    capped = PositionLimits(max_weight=0.6, max_gross=1.0).apply(allocation(wanted))

    assert dict(capped.weights) == wanted


def test_a_position_above_the_cap_is_trimmed_to_it() -> None:
    """The excess stays in cash rather than moving to the other names.

    Spreading it would replace the strategy's view with another one, and the
    report would show a performance nobody chose.
    """
    capped = PositionLimits(max_weight=0.4).apply(allocation({"A": 0.7, "B": 0.3}))

    assert dict(capped.weights) == {"A": 0.4, "B": 0.3}
    assert capped.invested == pytest.approx(0.7)


def test_a_gross_limit_scales_every_weight_by_the_same_factor() -> None:
    """Trimming the largest would change the sizes the strategy chose."""
    capped = PositionLimits(max_gross=0.5).apply(allocation({"A": 0.6, "B": 0.4}))

    assert dict(capped.weights) == {"A": pytest.approx(0.3), "B": pytest.approx(0.2)}
    assert capped.invested == pytest.approx(0.5)


def test_the_two_limits_apply_in_order() -> None:
    """Capped first, then scaled if what is left still exceeds the gross."""
    capped = PositionLimits(max_weight=0.5, max_gross=0.8).apply(allocation({"A": 0.9, "B": 0.5}))

    assert capped.invested == pytest.approx(0.8)
    assert capped.weights["A"] == pytest.approx(capped.weights["B"])


def test_the_reading_of_the_market_is_carried_through() -> None:
    """A limit changes sizes; it does not change what the signals said."""
    wanted = allocation({"A": 0.9})

    capped = PositionLimits(max_weight=0.4).apply(wanted)

    assert capped.selected == wanted.selected
    assert capped.considered == wanted.considered
    assert dict(capped.skipped) == dict(wanted.skipped)
    assert capped.as_of == wanted.as_of


@pytest.mark.parametrize(
    "overrides",
    [{"max_weight": 0.0}, {"max_weight": 1.5}, {"max_gross": -0.1}, {"max_gross": 2.0}],
    ids=["zero-cap", "cap-above-one", "negative-gross", "leverage"],
)
def test_a_limit_that_is_not_a_fraction_is_refused(overrides: dict[str, float]) -> None:
    """Leverage is refused because nothing below models a financing cost."""
    with pytest.raises(ValueError, match="max_"):
        PositionLimits(**overrides)
