"""A gauge that spiked and has come down: the peak, the relief and the window."""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import date, datetime

import pandas as pd
import pytest

from quant_backtester.data.calendars import TradingCalendar
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.level.vix_relief import VixReliefSignal
from quant_backtester.signals.types import SignalStatus

BarsBuilder = Callable[..., pd.DataFrame]
LevelsBuilder = Callable[..., pd.DataFrame]
MarketBuilder = Callable[..., MarketDataReader]
ContextBuilder = Callable[[MarketDataReader, datetime], SignalContext]


def signal(**changes: object) -> VixReliefSignal:
    """Return the relief over five observations: a peak of 30, a fall to 80% of it."""
    fields: dict[str, object] = {
        "signal_id": "relief_5o",
        "window_observations": 5,
        "peak_minimum": 30.0,
        "relief_ratio": 0.80,
        "max_age_sessions": 1,
    }
    return VixReliefSignal(**(fields | changes))  # type: ignore[arg-type]


@pytest.fixture
def context_of(
    make_market: MarketBuilder,
    make_bars: BarsBuilder,
    make_levels: LevelsBuilder,
    make_context: ContextBuilder,
    xpar: TradingCalendar,
    sessions: tuple[date, ...],
    prices: Callable[..., dict[date, float]],
    evening: Callable[[date], datetime],
) -> Callable[..., SignalContext]:
    """Return a builder of the decision of 14 September over gauge values ending on a day."""

    def build(
        values: list[float], *, last: date | None = None, extra: dict[date, float] | None = None
    ) -> SignalContext:
        days = [day for day in sessions if last is None or day <= last]
        levels = dict(zip(days[-len(values) :], values, strict=True)) | (extra or {})
        market = make_market(
            {"ETF_EU": make_bars("ETF_EU", xpar, prices(100.0, 1.0))},
            None,
            {"RATE_US": make_levels("RATE_US", levels)},
        )
        return make_context(market, evening(sessions[-1]))

    return build


def value_of(context: SignalContext, **changes: object) -> float:
    """Return the signal's value for the gauge."""
    result = signal(**changes).compute(context, ["RATE_US"])
    assert result.status("RATE_US") is SignalStatus.OK
    return result.value("RATE_US")


def test_a_panic_peak_left_behind_is_a_relief(context_of) -> None:
    assert value_of(context_of([20.0, 40.0, 36.0, 34.0, 32.0])) == 1.0


def test_exactly_the_two_thresholds_are_a_relief(context_of) -> None:
    """``peak >= 30`` and ``last <= 0.80 * peak``, both inclusive."""
    assert value_of(context_of([20.0, 30.0, 28.0, 26.0, 24.0])) == 1.0


def test_a_level_still_close_to_the_peak_is_not(context_of) -> None:
    assert value_of(context_of([20.0, 40.0, 38.0, 36.0, 33.0])) == 0.0


def test_a_peak_below_the_panic_level_is_not(context_of) -> None:
    assert value_of(context_of([20.0, 29.0, 22.0, 21.0, 20.0])) == 0.0


def test_the_latest_observation_can_be_the_peak(context_of) -> None:
    assert value_of(context_of([20.0, 22.0, 21.0, 25.0, 45.0])) == 0.0


def test_the_peak_leaves_the_window_by_itself(context_of) -> None:
    """Six observations: the 40 is the sixth from the end and no longer counted."""
    assert value_of(context_of([40.0, 25.0, 24.0, 23.0, 22.0, 21.0])) == 0.0


def test_the_thresholds_are_in_the_units_of_the_series(context_of) -> None:
    """A gauge quoted as 0.40 is not above a threshold of 30."""
    assert value_of(context_of([0.20, 0.40, 0.36, 0.34, 0.32])) == 0.0


def test_an_observation_published_after_the_decision_changes_nothing(context_of) -> None:
    """The look-ahead guard: a later spike is not the peak of this window."""
    calm = [20.0, 21.0, 22.0, 21.0, 20.0]

    assert value_of(context_of(calm, extra={date(2026, 9, 15): 80.0})) == 0.0


def test_too_few_observations_have_no_value(context_of) -> None:
    result = signal().compute(context_of([40.0, 36.0, 34.0, 32.0]), ["RATE_US"])

    assert result.status("RATE_US") is SignalStatus.INSUFFICIENT_HISTORY
    assert math.isnan(result.value("RATE_US"))


def test_a_gauge_two_sessions_old_is_stale(context_of) -> None:
    result = signal().compute(
        context_of([20.0, 40.0, 36.0, 34.0, 32.0], last=date(2026, 9, 10)), ["RATE_US"]
    )

    assert result.status("RATE_US") is SignalStatus.STALE_INPUT


def test_a_fund_is_refused(context_of) -> None:
    with pytest.raises(ValueError, match="published series"):
        signal().compute(context_of([20.0, 40.0, 36.0, 34.0, 32.0]), ["ETF_EU"])


@pytest.mark.parametrize(
    "changes",
    [
        {"window_observations": 1},
        {"peak_minimum": 0.0},
        {"relief_ratio": 1.2},
        {"relief_ratio": 0.0},
        {"max_age_sessions": -1},
    ],
)
def test_a_configuration_that_cannot_be_computed_is_refused(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        signal(**changes)


def test_the_definition_names_the_window_and_the_unit() -> None:
    definition = signal().definition()

    assert definition["window_mode"] == "AVAILABLE_OBSERVATIONS"
    assert definition["unit"] == "BINARY"
    assert definition["price_basis"] == "RAW"
