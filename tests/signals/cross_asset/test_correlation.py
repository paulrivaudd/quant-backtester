"""A fund's returns against a published series' changes, on the dates both hold.

The two series do not keep the same days, so the window cannot be sessions in a
row: it is the last dates they share, and every move is taken over the same
span on both sides.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from datetime import date, datetime

import pandas as pd
import pytest

from quant_backtester.data.calendars import TradingCalendar
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.cross_asset.correlation import (
    ReturnLevelCorrelationSignal,
    correlation,
)
from quant_backtester.signals.types import PriceBasis, SignalStatus, SignalUnit, WindowMode

BarsBuilder = Callable[..., pd.DataFrame]
LevelsBuilder = Callable[..., pd.DataFrame]
MarketBuilder = Callable[..., MarketDataReader]
ContextBuilder = Callable[[MarketDataReader, datetime], SignalContext]
CorrelationContext = Callable[..., SignalContext]

D1, D2, D3, D4 = date(2026, 9, 9), date(2026, 9, 10), date(2026, 9, 11), date(2026, 9, 14)
"""Four Paris sessions in a row, a weekend between the last two."""

PRICES = {D1: 100.0, D2: 110.0, D3: 99.0, D4: 108.9}
"""Log returns of ln 1.1, ln 0.9 and ln 1.1."""


def signal(pairs: int = 3, max_age_sessions: int = 1) -> ReturnLevelCorrelationSignal:
    """Return the correlation of a fund with the synthetic US rate."""
    return ReturnLevelCorrelationSignal(
        signal_id="corr",
        level_id="RATE_US",
        window_pairs=pairs,
        price_basis=PriceBasis.ADJUSTED,
        max_age_sessions=max_age_sessions,
    )


@pytest.fixture
def correlation_context(
    make_market: MarketBuilder,
    make_bars: BarsBuilder,
    make_levels: LevelsBuilder,
    make_context: ContextBuilder,
    xpar: TradingCalendar,
    evening: Callable[[date], datetime],
) -> CorrelationContext:
    """Return a builder of a context holding one fund and the rate, decided after ``on``."""

    def build(
        prices: Mapping[date, float], rates: Mapping[date, float], on: date = D4
    ) -> SignalContext:
        market = make_market(
            {"ETF_EU": make_bars("ETF_EU", xpar, prices)},
            None,
            {"RATE_US": make_levels("RATE_US", rates)},
        )
        return make_context(market, evening(on))

    return build


def test_the_correlation_of_two_samples_can_be_checked_by_hand() -> None:
    # Deviations (-1, 0, 1) and (-1, 1, 0): 1 over the root of 2 times 2.
    assert correlation([1.0, 2.0, 3.0], [1.0, 3.0, 2.0]) == pytest.approx(0.5)
    assert correlation([1.0, 2.0, 3.0], [2.0, 4.0, 6.0]) == pytest.approx(1.0)
    assert correlation([1.0, 2.0, 3.0], [6.0, 4.0, 2.0]) == pytest.approx(-1.0)


def test_a_sample_that_does_not_vary_has_no_correlation() -> None:
    assert correlation([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]) is None
    assert correlation([1.0], [2.0]) is None
    assert correlation([], []) is None


def test_samples_of_different_lengths_are_refused() -> None:
    with pytest.raises(ValueError, match="paired samples of 2 and 3"):
        correlation([1.0, 2.0], [1.0, 2.0, 3.0])


def test_a_fund_rising_with_the_rate_is_positively_correlated(
    correlation_context: CorrelationContext,
) -> None:
    rates = {D1: 4.0, D2: 4.2, D3: 3.9, D4: 4.1}
    result = signal().compute(correlation_context(PRICES, rates), ["ETF_EU"])
    returns = [math.log(1.1), math.log(0.9), math.log(1.1)]
    assert result.status("ETF_EU") is SignalStatus.OK
    assert result.value("ETF_EU") == pytest.approx(correlation(returns, [0.2, -0.3, 0.2]))
    assert result.value("ETF_EU") > 0.99


def test_a_fund_falling_as_the_rate_rises_is_negatively_correlated(
    correlation_context: CorrelationContext,
) -> None:
    rates = {D1: 4.0, D2: 3.8, D3: 4.1, D4: 3.9}
    result = signal().compute(correlation_context(PRICES, rates), ["ETF_EU"])
    assert result.value("ETF_EU") < -0.99


def test_a_move_is_taken_over_the_same_span_on_both_series(
    correlation_context: CorrelationContext,
) -> None:
    # The rate is not published on D3: the fund's return from D2 to D4 is set
    # against the rate's change from D2 to D4, never against one day of it.
    day_zero = date(2026, 9, 8)
    prices = {day_zero: 100.0} | PRICES
    rates = {day_zero: 4.0, D1: 4.1, D2: 4.0, D4: 4.3}
    result = signal().compute(correlation_context(prices, rates), ["ETF_EU"])
    returns = [math.log(100.0 / 100.0), math.log(110.0 / 100.0), math.log(108.9 / 110.0)]
    changes = [0.1, -0.1, 0.3]
    frame = result.frame
    assert result.status("ETF_EU") is SignalStatus.OK
    assert result.value("ETF_EU") == pytest.approx(correlation(returns, changes))
    assert frame.loc["ETF_EU", "input_start_date"] == day_zero
    assert frame.loc["ETF_EU", "input_end_date"] == D4
    assert frame.loc["ETF_EU", "observations_used"] == 4


def test_too_few_common_dates_is_a_status_not_a_number(
    correlation_context: CorrelationContext,
) -> None:
    rates = {D2: 4.2, D3: 3.9, D4: 4.1}
    result = signal().compute(correlation_context(PRICES, rates), ["ETF_EU"])
    assert result.status("ETF_EU") is SignalStatus.INSUFFICIENT_HISTORY
    assert math.isnan(result.value("ETF_EU"))


def test_a_rate_that_stopped_being_published_is_stale(
    correlation_context: CorrelationContext,
) -> None:
    day_zero = date(2026, 9, 8)
    rates = {day_zero: 4.0, D1: 4.0, D2: 4.2}
    context = correlation_context({day_zero: 100.0} | PRICES, rates)
    assert signal(pairs=3).compute(context, ["ETF_EU"]).status("ETF_EU") is SignalStatus.STALE_INPUT
    assert (
        signal(pairs=3, max_age_sessions=2).compute(context, ["ETF_EU"]).status("ETF_EU")
        is SignalStatus.INSUFFICIENT_HISTORY
    )


def test_a_rate_that_does_not_move_is_an_invalid_input(
    correlation_context: CorrelationContext,
) -> None:
    result = signal().compute(correlation_context(PRICES, dict.fromkeys(PRICES, 4.0)), ["ETF_EU"])
    assert result.status("ETF_EU") is SignalStatus.INVALID_INPUT


def test_values_after_the_decision_do_not_change_the_result(
    correlation_context: CorrelationContext,
) -> None:
    rates = {D1: 4.0, D2: 4.2, D3: 3.9, D4: 4.1}
    future = date(2026, 9, 15)
    calm = signal().compute(correlation_context(PRICES, rates), ["ETF_EU"])
    crash = signal().compute(
        correlation_context(PRICES | {future: 1.0}, rates | {future: 99.0}), ["ETF_EU"]
    )
    assert crash.value("ETF_EU") == calm.value("ETF_EU")
    assert crash.frame.loc["ETF_EU", "input_end_date"] == D4


def test_the_signal_refuses_a_published_series_as_the_fund_and_a_fund_as_the_series(
    correlation_context: CorrelationContext,
) -> None:
    context = correlation_context(PRICES, {D1: 4.0, D2: 4.2, D3: 3.9, D4: 4.1})
    with pytest.raises(ValueError, match="returns of a bars instrument"):
        signal().compute(context, ["RATE_US"])
    wired_wrong = ReturnLevelCorrelationSignal(
        signal_id="corr", level_id="ETF_EU", window_pairs=3, price_basis=PriceBasis.ADJUSTED
    )
    with pytest.raises(ValueError, match="reads published series"):
        wired_wrong.compute(context, ["ETF_EU"])


def test_two_pairs_are_refused_at_construction() -> None:
    with pytest.raises(ValueError, match="at least 3"):
        signal(pairs=2)


def test_the_definition_says_what_the_window_and_the_number_are() -> None:
    definition = signal().definition()
    assert definition["window_mode"] == WindowMode.AVAILABLE_OBSERVATIONS.value
    assert definition["unit"] == SignalUnit.CORRELATION.value
    assert definition["level_id"] == "RATE_US"
    assert signal(pairs=3).fingerprint() != signal(pairs=4).fingerprint()
