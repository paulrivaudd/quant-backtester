"""SpanScaledVolatilitySignal: available closes, each return scaled by the sessions it spans."""

from __future__ import annotations

import math
import statistics

import pytest

from quant_backtester.signals.risk.span_volatility import SpanScaledVolatilitySignal
from quant_backtester.signals.risk.volatility import RealizedVolatilitySignal
from quant_backtester.signals.types import PriceBasis, SignalStatus


def signal(returns: int = 4, max_span: int = 3, **overrides: object) -> SpanScaledVolatilitySignal:
    """Build the estimator annualised over 252 sessions, unless overridden."""
    parameters: dict[str, object] = {
        "signal_id": f"span_volatility_{returns}r",
        "window_returns": returns,
        "annualization": 252,
        "max_span_sessions": max_span,
        "price_basis": PriceBasis.RAW,
    }
    parameters.update(overrides)
    return SpanScaledVolatilitySignal(**parameters)  # type: ignore[arg-type]


def zigzag(sessions, start: float = 100.0) -> dict:
    """Return closes moving +2 %, -1 %, +3 %, -2 % in turn, by session."""
    moves = (0.02, -0.01, 0.03, -0.02)
    closes, price = {}, start
    for index, day in enumerate(sessions):
        if index:
            price *= 1.0 + moves[index % len(moves)]
        closes[day] = price
    return closes


def test_without_a_gap_it_is_the_consecutive_estimator(
    make_market, make_bars, make_context, evening, sessions, xpar
) -> None:
    market = make_market({"ETF_EU": make_bars("ETF_EU", xpar, zigzag(sessions))})
    context = make_context(market, evening(sessions[-1]))
    consecutive = RealizedVolatilitySignal(
        signal_id="volatility_4r", window_returns=4, price_basis=PriceBasis.RAW, annualization=252
    )
    value = signal(4).compute(context, ["ETF_EU"])
    assert value.status("ETF_EU") is SignalStatus.OK
    assert value.value("ETF_EU") == pytest.approx(
        consecutive.compute(context, ["ETF_EU"]).value("ETF_EU")
    )


def test_a_missing_session_is_scaled_by_its_span_by_hand(
    make_market, make_bars, make_context, evening, sessions, xpar
) -> None:
    closes = zigzag(sessions)
    missing = sessions[-3]
    del closes[missing]
    market = make_market({"ETF_EU": make_bars("ETF_EU", xpar, closes)})
    context = make_context(market, evening(sessions[-1]))
    kept = [day for day in sessions if day != missing][-5:]
    prices = [closes[day] for day in kept]
    spans = [2 if kept[i] == sessions[-2] else 1 for i in range(1, 5)]
    scaled = [math.log(prices[i] / prices[i - 1]) / math.sqrt(spans[i - 1]) for i in range(1, 5)]
    expected = statistics.stdev(scaled) * math.sqrt(252)
    result = signal(4).compute(context, ["ETF_EU"])
    assert result.status("ETF_EU") is SignalStatus.OK
    assert result.value("ETF_EU") == pytest.approx(expected)
    # the consecutive estimator refuses the same window
    consecutive = RealizedVolatilitySignal(
        signal_id="volatility_4r", window_returns=4, price_basis=PriceBasis.RAW, annualization=252
    )
    refused = consecutive.compute(context, ["ETF_EU"])
    assert refused.status("ETF_EU") is SignalStatus.NON_CONSECUTIVE_HISTORY


def test_a_hole_longer_than_the_declared_span_is_refused(
    make_market, make_bars, make_context, evening, sessions, xpar
) -> None:
    closes = zigzag(sessions)
    for day in sessions[-4:-1]:
        del closes[day]
    market = make_market({"ETF_EU": make_bars("ETF_EU", xpar, closes)})
    context = make_context(market, evening(sessions[-1]))
    assert signal(3, max_span=3).compute(context, ["ETF_EU"]).status("ETF_EU") is (
        SignalStatus.NON_CONSECUTIVE_HISTORY
    )
    assert signal(3, max_span=4).compute(context, ["ETF_EU"]).status("ETF_EU") is SignalStatus.OK


def test_a_weekend_is_not_a_gap(
    make_market, make_bars, make_context, evening, sessions, xpar
) -> None:
    market = make_market({"ETF_EU": make_bars("ETF_EU", xpar, zigzag(sessions))})
    context = make_context(market, evening(sessions[-1]))
    assert signal(9, max_span=1).compute(context, ["ETF_EU"]).status("ETF_EU") is SignalStatus.OK


def test_too_few_closes_is_insufficient_history(context) -> None:
    assert signal(4).compute(context, ["ETF_LATE"]).status("ETF_LATE") is (
        SignalStatus.INSUFFICIENT_HISTORY
    )


def test_a_future_price_changes_nothing(
    make_market, make_bars, make_context, evening, sessions, xpar
) -> None:
    closes = zigzag(sessions)
    decided = sessions[-2]
    past = {day: price for day, price in closes.items() if day <= decided}
    before = signal(4).compute(
        make_context(make_market({"ETF_EU": make_bars("ETF_EU", xpar, past)}), evening(decided)),
        ["ETF_EU"],
    )
    future = dict(past)
    future[sessions[-1]] = 1_000_000.0
    after = signal(4).compute(
        make_context(make_market({"ETF_EU": make_bars("ETF_EU", xpar, future)}), evening(decided)),
        ["ETF_EU"],
    )
    assert before.frame.equals(after.frame)


@pytest.mark.parametrize(
    "overrides",
    [
        {"window_returns": 1},
        {"window_returns": 0},
        {"annualization": 0},
        {"max_span_sessions": 0},
        {"max_age_sessions": -1},
        {"price_basis": "ADJUSTED"},
    ],
)
def test_an_impossible_configuration_stops_the_run(overrides) -> None:
    with pytest.raises(ValueError):
        signal(**overrides)


def test_the_definition_names_its_contract() -> None:
    definition = signal(4).definition()
    assert definition["window_mode"] == "AVAILABLE_OBSERVATIONS"
    assert definition["max_span_sessions"] == 3
    assert signal(4, max_span=2).fingerprint() != signal(4).fingerprint()
