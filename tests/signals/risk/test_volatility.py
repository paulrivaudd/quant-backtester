"""RealizedVolatilitySignal: N returns, not N prices, and the scale said out loud."""

from __future__ import annotations

import math
import statistics

import pytest

from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.risk.volatility import RealizedVolatilitySignal
from quant_backtester.signals.types import PriceBasis, SignalStatus


def signal(returns: int = 4, **overrides: object) -> RealizedVolatilitySignal:
    """Build a volatility signal with the usual defaults."""
    parameters: dict[str, object] = {
        "signal_id": f"volatility_{returns}d",
        "window_returns": returns,
        "price_basis": PriceBasis.RAW,
    }
    parameters.update(overrides)
    return RealizedVolatilitySignal(**parameters)  # type: ignore[arg-type]


def expected(prices: list[float], annualization: int = 252, ddof: int = 1) -> float:
    """Return the annualised standard deviation of the log returns, by hand."""
    returns = [math.log(prices[i] / prices[i - 1]) for i in range(1, len(prices))]
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - ddof)
    return math.sqrt(variance) * math.sqrt(annualization)


def test_the_formula_on_a_hand_checkable_series(context: SignalContext) -> None:
    """Four returns out of the prices 105 to 109, annualised by sqrt(252)."""
    result = signal(4).compute(context, ["ETF_EU"])

    assert result.status("ETF_EU") is SignalStatus.OK
    assert result.value("ETF_EU") == pytest.approx(expected([105.0, 106.0, 107.0, 108.0, 109.0]))


def test_n_returns_need_n_plus_one_prices(context: SignalContext) -> None:
    """The off-by-one this signal exists to get right.

    A "twenty-day" volatility computed on twenty prices is nineteen returns,
    and nothing in the output would say so.
    """
    row = signal(4).compute(context, ["ETF_EU"]).frame.loc["ETF_EU"]

    assert row["observations_used"] == 5


def test_the_annualisation_is_a_parameter_and_not_a_law(context: SignalContext) -> None:
    """252 is a convention. Changing it scales the answer, and the id follows."""
    daily = signal(4, annualization=1).compute(context, ["ETF_EU"])
    yearly = signal(4, annualization=252).compute(context, ["ETF_EU"])

    assert yearly.value("ETF_EU") == pytest.approx(daily.value("ETF_EU") * math.sqrt(252))
    assert signal(4, annualization=1).fingerprint() != signal(4).fingerprint()


def test_the_degrees_of_freedom_are_explicit(context: SignalContext) -> None:
    """The population estimate is available, and is a different number."""
    sample = signal(4, ddof=1).compute(context, ["ETF_EU"]).value("ETF_EU")
    population = signal(4, ddof=0).compute(context, ["ETF_EU"]).value("ETF_EU")

    assert population < sample
    assert population == pytest.approx(expected([105.0, 106.0, 107.0, 108.0, 109.0], ddof=0))


def test_simple_returns_are_available_and_differ(context: SignalContext) -> None:
    """Log returns are the default; the other convention is a declared choice."""
    logarithmic = signal(4).compute(context, ["ETF_EU"]).value("ETF_EU")
    simple = signal(4, logarithmic=False).compute(context, ["ETF_EU"]).value("ETF_EU")

    prices = [105.0, 106.0, 107.0, 108.0, 109.0]
    plain = [prices[i] / prices[i - 1] - 1.0 for i in range(1, len(prices))]
    assert simple == pytest.approx(statistics.stdev(plain) * math.sqrt(252))
    assert simple != logarithmic


def test_a_flat_series_has_no_volatility(
    make_market, make_bars, make_context, evening, sessions, xpar
) -> None:
    """Zero, and not a rounding of it: a price that never moved never moved."""
    flat = dict.fromkeys(sessions, 100.0)
    market = make_market({"ETF_EU": make_bars("ETF_EU", xpar, flat)})

    result = signal(4).compute(make_context(market, evening(sessions[-1])), ["ETF_EU"])

    assert result.value("ETF_EU") == 0.0


def test_a_non_positive_price_is_named_rather_than_computed(
    make_market, make_bars, make_context, evening, sessions, xpar
) -> None:
    """A ratio of prices, and its logarithm, mean nothing at zero.

    Returning a ``-inf`` that travels into a standard deviation is exactly how
    an unusable number reaches a portfolio.
    """
    broken = {session: 100.0 for session in sessions}
    broken[sessions[-2]] = 0.0
    market = make_market({"ETF_EU": make_bars("ETF_EU", xpar, broken)})

    result = signal(4).compute(make_context(market, evening(sessions[-1])), ["ETF_EU"])

    assert result.status("ETF_EU") is SignalStatus.INVALID_INPUT
    assert math.isnan(result.value("ETF_EU"))


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"window_returns": 1, "ddof": 1}, "ddof"),
        ({"window_returns": 0}, "window_returns"),
        ({"annualization": 0}, "annualization"),
        ({"ddof": -1}, "ddof"),
    ],
    ids=["no-degrees-of-freedom-left", "zero-window", "zero-annualisation", "negative-ddof"],
)
def test_an_impossible_configuration_stops_the_run(
    overrides: dict[str, object], match: str
) -> None:
    """A variance with no degrees of freedom is a division by zero waiting."""
    parameters: dict[str, object] = {"window_returns": 4}
    parameters.update(overrides)
    with pytest.raises(ValueError, match=match):
        signal(**parameters)  # type: ignore[arg-type]
