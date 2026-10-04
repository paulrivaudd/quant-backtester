"""A recent fall measured in the standard deviations of the returns before it."""

from __future__ import annotations

import math
import statistics
from collections.abc import Callable
from datetime import date, datetime

import pandas as pd
import pytest

from quant_backtester.data.calendars import TradingCalendar
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.data.schemas import BarField
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.price.normalized_pullback import NormalizedPullbackSignal
from quant_backtester.signals.types import PriceBasis, SignalStatus

BarsBuilder = Callable[..., pd.DataFrame]
MarketBuilder = Callable[..., MarketDataReader]
ContextBuilder = Callable[[MarketDataReader, datetime], SignalContext]

CLOSES = [100.0, 101.0, 100.0, 102.0, 101.0, 99.0, 96.0]
"""Seven closes: four reference returns, then a two-session fall from 101 to 96."""

NEXT_DAY = date(2026, 9, 15)
"""The session after the decision: a close the decision must not see."""


def signal(**changes: object) -> NormalizedPullbackSignal:
    """Return the signal on four reference returns and a two-session move."""
    fields: dict[str, object] = {
        "signal_id": "pullback_2s_over_4r",
        "reference_returns": 4,
        "recent_sessions": 2,
        "price_basis": PriceBasis.RAW,
        "max_age_sessions": 0,
    }
    return NormalizedPullbackSignal(**(fields | changes))  # type: ignore[arg-type]


@pytest.fixture
def context_of(
    make_market: MarketBuilder,
    make_bars: BarsBuilder,
    make_context: ContextBuilder,
    xpar: TradingCalendar,
    sessions: tuple[date, ...],
    evening: Callable[[date], datetime],
) -> Callable[..., SignalContext]:
    """Return a builder of the decision of 14 September over closes ending that day."""

    def build(closes: list[float], *, future: float | None = None, **bars: object) -> SignalContext:
        days = dict(zip(sessions[-len(closes) :], closes, strict=True))
        if future is not None:
            days[NEXT_DAY] = future
        market = make_market({"ETF_EU": make_bars("ETF_EU", xpar, days, **bars)})
        return make_context(market, evening(sessions[-1]))

    return build


def expected(closes: list[float]) -> float:
    """Return the value by the definition, with a naive loop."""
    returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    spread = statistics.stdev(returns[:4])
    return -math.log(closes[-1] / closes[-3]) / (spread * math.sqrt(2))


def test_a_fall_is_positive_and_counted_in_the_earlier_spread(context_of) -> None:
    result = signal().compute(context_of(CLOSES), ["ETF_EU"])

    assert result.status("ETF_EU") is SignalStatus.OK
    assert result.value("ETF_EU") == pytest.approx(expected(CLOSES))
    assert result.value("ETF_EU") > 0.0
    assert int(result.frame.loc["ETF_EU", "observations_used"]) == 7


def test_a_rise_is_negative(context_of) -> None:
    closes = [*CLOSES[:5], 103.0, 106.0]

    assert signal().compute(context_of(closes), ["ETF_EU"]).value("ETF_EU") < 0.0


def test_the_fall_does_not_enter_its_own_yardstick(context_of) -> None:
    """A deeper fall changes the numerator only: the spread ends before it."""
    shallow = signal().compute(context_of(CLOSES), ["ETF_EU"]).value("ETF_EU")
    deeper = [*CLOSES[:5], 95.0, 90.0]
    deep = signal().compute(context_of(deeper), ["ETF_EU"]).value("ETF_EU")

    ratio = math.log(deeper[-1] / deeper[-3]) / math.log(CLOSES[-1] / CLOSES[-3])
    assert deep == pytest.approx(shallow * ratio)


def test_a_close_published_after_the_decision_changes_nothing(context_of) -> None:
    """The look-ahead guard."""
    seen = signal().compute(context_of(CLOSES), ["ETF_EU"]).value("ETF_EU")
    with_future = signal().compute(context_of(CLOSES, future=50.0), ["ETF_EU"]).value("ETF_EU")

    assert with_future == seen


def test_a_window_one_close_short_has_no_value(context_of) -> None:
    result = signal().compute(context_of(CLOSES[1:]), ["ETF_EU"])

    assert result.status("ETF_EU") is SignalStatus.INSUFFICIENT_HISTORY
    assert math.isnan(result.value("ETF_EU"))


def test_a_missing_session_inside_the_window_refuses_it(context_of, sessions) -> None:
    closes = [100.0, *CLOSES]
    result = signal().compute(
        context_of(closes, contested={sessions[-4]: [BarField.CLOSE]}), ["ETF_EU"]
    )

    assert result.status("ETF_EU") is SignalStatus.NON_CONSECUTIVE_HISTORY


def test_a_reference_window_that_did_not_move_has_no_spread(context_of) -> None:
    result = signal().compute(context_of([100.0] * 5 + [99.0, 96.0]), ["ETF_EU"])

    assert result.status("ETF_EU") is SignalStatus.INVALID_INPUT


@pytest.mark.parametrize(
    "changes", [{"reference_returns": 1}, {"recent_sessions": 0}, {"max_age_sessions": -1}]
)
def test_a_configuration_that_cannot_be_computed_is_refused(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        signal(**changes)


def test_the_definition_says_the_reference_ends_before_the_move() -> None:
    definition = signal().definition()

    assert definition["reference_ends_before_recent"] is True
    assert definition["ddof"] == 1
    assert definition["window_mode"] == "CONSECUTIVE_SESSIONS"
