"""CurrentDrawdownSignal: how far below its recent high a price sits."""

from __future__ import annotations

import pytest

from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.risk.drawdown import CurrentDrawdownSignal
from quant_backtester.signals.types import PriceBasis, SignalStatus


def signal(window: int = 5, **overrides: object) -> CurrentDrawdownSignal:
    """Build a drawdown signal with the usual defaults."""
    parameters: dict[str, object] = {
        "signal_id": f"drawdown_{window}d",
        "window_sessions": window,
        "price_basis": PriceBasis.RAW,
    }
    parameters.update(overrides)
    return CurrentDrawdownSignal(**parameters)  # type: ignore[arg-type]


def test_a_rising_series_is_at_its_high(context: SignalContext) -> None:
    """The latest price is the highest of the window, so the drawdown is zero."""
    result = signal(5).compute(context, ["ETF_EU"])

    assert result.status("ETF_EU") is SignalStatus.OK
    assert result.value("ETF_EU") == 0.0


def test_the_formula_after_a_fall(
    make_market, make_bars, make_context, evening, sessions, xpar
) -> None:
    """A series peaking at 120 and ending at 90 is 25% below its high."""
    closes = dict.fromkeys(sessions, 100.0)
    closes[sessions[-3]] = 120.0
    closes[sessions[-1]] = 90.0
    market = make_market({"ETF_EU": make_bars("ETF_EU", xpar, closes)})

    result = signal(5).compute(make_context(market, evening(sessions[-1])), ["ETF_EU"])

    assert result.value("ETF_EU") == pytest.approx(90.0 / 120.0 - 1.0)


def test_the_window_decides_which_high_is_meant(
    make_market, make_bars, make_context, evening, sessions, xpar
) -> None:
    """A peak older than the window is not the high this signal measures against.

    It is not an all-time drawdown, and it is not the maximum drawdown of a
    strategy either. The window says what it is.
    """
    closes = dict.fromkeys(sessions, 100.0)
    closes[sessions[0]] = 200.0
    closes[sessions[-1]] = 90.0
    market = make_market({"ETF_EU": make_bars("ETF_EU", xpar, closes)})
    context = make_context(market, evening(sessions[-1]))

    near = signal(5).compute(context, ["ETF_EU"])
    far = signal(10).compute(context, ["ETF_EU"])

    assert near.value("ETF_EU") == pytest.approx(90.0 / 100.0 - 1.0)
    assert far.value("ETF_EU") == pytest.approx(90.0 / 200.0 - 1.0)


def test_the_value_is_never_positive(context: SignalContext) -> None:
    """A price cannot be above a maximum it belongs to."""
    assert signal(5).compute(context, ["ETF_EU"]).value("ETF_EU") <= 0.0


@pytest.mark.parametrize("window", [0, 1, -2])
def test_a_window_of_fewer_than_two_prices_is_refused(window: int) -> None:
    """A price is never below itself."""
    with pytest.raises(ValueError, match="window_sessions"):
        signal(window)
