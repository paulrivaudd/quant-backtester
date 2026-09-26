"""Moving averages: a price against its own average, and two averages against each other."""

from __future__ import annotations

import pytest

from quant_backtester.data.schemas import BarField
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.price.trend import (
    MovingAverageCrossSignal,
    MovingAverageTrendSignal,
)
from quant_backtester.signals.types import PriceBasis, SignalStatus


def signal(window: int = 5, **overrides: object) -> MovingAverageTrendSignal:
    """Build a trend signal with the usual defaults."""
    parameters: dict[str, object] = {
        "signal_id": f"trend_ma{window}",
        "window_sessions": window,
        "price_basis": PriceBasis.RAW,
    }
    parameters.update(overrides)
    return MovingAverageTrendSignal(**parameters)  # type: ignore[arg-type]


def test_the_formula_on_a_hand_checkable_series(context: SignalContext) -> None:
    """The last five prices are 105 to 109, averaging 107: 109/107 - 1."""
    result = signal(5).compute(context, ["ETF_EU"])

    assert result.status("ETF_EU") is SignalStatus.OK
    assert result.value("ETF_EU") == pytest.approx(109.0 / 107.0 - 1.0)


def test_the_average_includes_the_latest_price(context: SignalContext) -> None:
    """N prices, the latest among them - not N before it.

    Averaging the N prices *before* the latest is a different quantity, and the
    window size is what would silently absorb the difference.
    """
    row = signal(5).compute(context, ["ETF_EU"]).frame.loc["ETF_EU"]

    assert row["observations_used"] == 5


def test_a_price_below_its_average_is_negative(
    make_market, make_bars, make_context, evening, sessions, xpar
) -> None:
    """A falling series sits under its own average, and the sign says so."""
    falling = {session: 110.0 - index for index, session in enumerate(sessions)}
    market = make_market({"ETF_EU": make_bars("ETF_EU", xpar, falling)})

    result = signal(5).compute(make_context(market, evening(sessions[-1])), ["ETF_EU"])

    assert result.value("ETF_EU") < 0


@pytest.mark.parametrize("window", [0, 1, -2])
def test_an_average_of_fewer_than_two_prices_is_refused(window: int) -> None:
    """The distance from a price to itself is always zero, and never a trend."""
    with pytest.raises(ValueError, match="window_sessions"):
        signal(window)


def cross(first: int = 2, second: int = 5, **overrides: object) -> MovingAverageCrossSignal:
    """Build a moving-average cross with the usual defaults."""
    parameters: dict[str, object] = {
        "signal_id": f"ma{first}_over_ma{second}",
        "first_sessions": first,
        "second_sessions": second,
        "price_basis": PriceBasis.RAW,
    }
    parameters.update(overrides)
    return MovingAverageCrossSignal(**parameters)  # type: ignore[arg-type]


def test_the_cross_on_a_hand_checkable_series(context: SignalContext) -> None:
    """108 and 109 average 108.5; 105 to 109 average 107: 108.5/107 - 1."""
    result = cross(2, 5).compute(context, ["ETF_EU"])

    assert result.status("ETF_EU") is SignalStatus.OK
    assert result.value("ETF_EU") == pytest.approx(108.5 / 107.0 - 1.0)


def test_the_order_of_the_averages_is_the_sign(context: SignalContext) -> None:
    """On a rising series the short average is on top, so 5-over-2 is negative."""
    result = cross(5, 2).compute(context, ["ETF_EU"])

    assert result.value("ETF_EU") == pytest.approx(107.0 / 108.5 - 1.0)
    assert result.value("ETF_EU") < 0


def test_the_cross_agrees_with_a_naive_loop(context: SignalContext) -> None:
    """Each average written out as a loop over the closes, oldest first."""
    closes = [100.0 + index for index in range(10)]

    def average(count: int) -> float:
        total = 0.0
        for close in closes[len(closes) - count :]:
            total += close
        return total / count

    result = cross(3, 7).compute(context, ["ETF_EU"])

    assert result.value("ETF_EU") == pytest.approx(average(3) / average(7) - 1.0)


def test_the_window_is_the_longer_average(context: SignalContext) -> None:
    """Five prices for a 2-over-5 cross, whichever average is named first."""
    for first, second in ((2, 5), (5, 2)):
        row = cross(first, second).compute(context, ["ETF_EU"]).frame.loc["ETF_EU"]

        assert row["observations_used"] == 5


def test_too_short_a_history_has_no_cross(context: SignalContext) -> None:
    """ETF_LATE has four sessions, and the longer average wants five."""
    result = cross(2, 5).compute(context, ["ETF_LATE"])

    assert result.status("ETF_LATE") is SignalStatus.INSUFFICIENT_HISTORY


def test_a_hole_inside_the_longer_window_refuses_both_averages(
    make_market, make_bars, make_context, evening, sessions, xpar, prices
) -> None:
    """The short average never sees the hole, and is refused all the same.

    It is the tail of the longer window: computing it over a span the long
    one could not vouch for would compare two averages of different periods.
    """
    closes = make_bars(
        "ETF_EU", xpar, prices(100.0, 1.0), contested={sessions[-4]: [BarField.CLOSE]}
    )
    market = make_market({"ETF_EU": closes})

    result = cross(2, 5).compute(make_context(market, evening(sessions[-1])), ["ETF_EU"])

    assert result.status("ETF_EU") is SignalStatus.NON_CONSECUTIVE_HISTORY


def test_a_later_session_does_not_change_an_earlier_cross(
    make_market, make_bars, make_context, evening, sessions, xpar, prices
) -> None:
    """The look-ahead guard: a price after the decision moves nothing."""
    closes = prices(100.0, 1.0)
    before = cross(2, 5).compute(
        make_context(
            make_market({"ETF_EU": make_bars("ETF_EU", xpar, closes)}), evening(sessions[-2])
        ),
        ["ETF_EU"],
    )

    with_future = dict(closes)
    with_future[sessions[-1]] = 1_000.0
    after = cross(2, 5).compute(
        make_context(
            make_market({"ETF_EU": make_bars("ETF_EU", xpar, with_future)}), evening(sessions[-2])
        ),
        ["ETF_EU"],
    )

    assert after.frame.equals(before.frame)


@pytest.mark.parametrize(
    ("first", "second", "match"),
    [(1, 5, "first_sessions"), (5, 1, "second_sessions"), (5, 5, "compared with itself")],
    ids=["one-price-first", "one-price-second", "same-lengths"],
)
def test_two_averages_that_cannot_differ_are_refused(first: int, second: int, match: str) -> None:
    """An average of one price is the price, and an average against itself is zero."""
    with pytest.raises(ValueError, match=match):
        cross(first, second)
