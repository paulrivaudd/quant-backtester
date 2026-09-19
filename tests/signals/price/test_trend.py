"""MovingAverageTrendSignal: the distance from a price to its own average."""

from __future__ import annotations

import pytest

from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.price.trend import MovingAverageTrendSignal
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
