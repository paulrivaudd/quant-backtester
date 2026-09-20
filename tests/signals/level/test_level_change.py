"""A published series moves in its own units, and over the observations it has.

Two things separate this from a price signal, and both are the reason the
module exists. The window is counted in observations available, because nobody
holds sessions for a macro release; and the move is a difference, because a
yield of 4.20 becoming 4.45 has moved twenty-five basis points and not six
percent.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime

import pandas as pd
import pytest

from quant_backtester.data.reader import MarketDataReader
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.level.change import LevelChangeSignal
from quant_backtester.signals.types import SignalStatus, SignalUnit, WindowMode

BarsBuilder = Callable[..., pd.DataFrame]
LevelsBuilder = Callable[..., pd.DataFrame]
MarketBuilder = Callable[..., MarketDataReader]
ContextBuilder = Callable[[MarketDataReader, datetime], SignalContext]

RATES: dict[date, float] = {
    date(2026, 9, 1): 4.00,
    date(2026, 9, 2): 4.05,
    date(2026, 9, 3): 4.10,
    date(2026, 9, 4): 4.15,
    date(2026, 9, 7): 4.20,
    date(2026, 9, 8): 4.25,
    date(2026, 9, 9): 4.30,
    date(2026, 9, 10): 4.35,
    date(2026, 9, 11): 4.40,
    date(2026, 9, 14): 4.45,
}
"""A ten-year yield rising by five basis points an observation."""


@pytest.fixture
def rate_context(
    make_market: MarketBuilder,
    make_levels: LevelsBuilder,
    make_context: ContextBuilder,
    make_bars: BarsBuilder,
    xpar,
    prices,
    evening,
) -> SignalContext:
    """Return a context holding the rate and one fund, decided after 14 September."""
    market = make_market(
        {"ETF_EU": make_bars("ETF_EU", xpar, prices(100.0, 1.0))},
        None,
        {"RATE_US": make_levels("RATE_US", RATES)},
    )
    return make_context(market, evening(date(2026, 9, 14)))


def test_a_change_is_a_difference_in_the_series_own_units(
    rate_context: SignalContext,
) -> None:
    """Four observations at five basis points each: twenty, not 0.45 percent."""
    signal = LevelChangeSignal(signal_id="us10y_change_4o", lookback_observations=4)

    result = signal.compute(rate_context, ["RATE_US"])

    assert result.status("RATE_US") is SignalStatus.OK
    assert result.value("RATE_US") == pytest.approx(0.20)


def test_a_falling_series_changes_by_a_negative_number(
    make_market: MarketBuilder,
    make_levels: LevelsBuilder,
    make_context: ContextBuilder,
    make_bars: BarsBuilder,
    xpar,
    prices,
    evening,
) -> None:
    """The sign is the direction of the move, and nothing else."""
    falling = {day: 4.45 - (value - 4.00) for day, value in RATES.items()}
    market = make_market(
        {"ETF_EU": make_bars("ETF_EU", xpar, prices(100.0, 1.0))},
        None,
        {"RATE_US": make_levels("RATE_US", falling)},
    )
    context = make_context(market, evening(date(2026, 9, 14)))

    result = LevelChangeSignal(signal_id="change_4o", lookback_observations=4).compute(
        context, ["RATE_US"]
    )

    assert result.value("RATE_US") == pytest.approx(-0.20)


def test_a_series_that_crossed_zero_still_has_a_change(
    make_market: MarketBuilder,
    make_levels: LevelsBuilder,
    make_context: ContextBuilder,
    make_bars: BarsBuilder,
    xpar,
    prices,
    evening,
) -> None:
    """The reason this is not a return.

    A yield going from -0.10 to 0.15 has risen twenty-five basis points. As a
    ratio it would be -250%, a number whose sign says the opposite of what
    happened, and at exactly zero it would not exist at all.
    """
    crossing = dict(RATES)
    days = list(crossing)
    for offset, value in enumerate((-0.10, -0.05, 0.0, 0.10, 0.15)):
        crossing[days[5 + offset]] = value
    market = make_market(
        {"ETF_EU": make_bars("ETF_EU", xpar, prices(100.0, 1.0))},
        None,
        {"RATE_US": make_levels("RATE_US", crossing)},
    )
    context = make_context(market, evening(date(2026, 9, 14)))

    result = LevelChangeSignal(signal_id="change_4o", lookback_observations=4).compute(
        context, ["RATE_US"]
    )

    assert result.value("RATE_US") == pytest.approx(0.25)


def test_the_window_is_counted_in_observations_not_in_sessions(
    make_market: MarketBuilder,
    make_levels: LevelsBuilder,
    make_context: ContextBuilder,
    make_bars: BarsBuilder,
    xpar,
    prices,
    evening,
) -> None:
    """A published series has no venue sessions to be consecutive over.

    Three observations are missing from the middle of the span here, and the
    window is still the four observations that were asked for - but the
    diagnostics say what those four covered, so nobody can read a "four
    observation" change as a four day one.
    """
    with_holes = {
        day: value
        for day, value in RATES.items()
        if day not in {date(2026, 9, 8), date(2026, 9, 9), date(2026, 9, 10)}
    }
    market = make_market(
        {"ETF_EU": make_bars("ETF_EU", xpar, prices(100.0, 1.0))},
        None,
        {"RATE_US": make_levels("RATE_US", with_holes)},
    )
    context = make_context(market, evening(date(2026, 9, 14)))

    result = LevelChangeSignal(signal_id="change_3o", lookback_observations=3).compute(
        context, ["RATE_US"]
    )

    frame = result.frame
    assert result.status("RATE_US") is SignalStatus.OK
    assert result.value("RATE_US") == pytest.approx(4.45 - 4.15)
    assert frame.loc["RATE_US", "input_start_date"] == date(2026, 9, 4)
    assert frame.loc["RATE_US", "input_end_date"] == date(2026, 9, 14)
    assert frame.loc["RATE_US", "observations_used"] == 4


def test_a_history_shorter_than_the_window_is_named(
    rate_context: SignalContext,
) -> None:
    """Ten observations cannot answer a question about twenty."""
    signal = LevelChangeSignal(signal_id="change_20o", lookback_observations=20)

    result = signal.compute(rate_context, ["RATE_US"])

    assert result.status("RATE_US") is SignalStatus.INSUFFICIENT_HISTORY
    assert result.value("RATE_US") != result.value("RATE_US")


def test_a_fund_is_not_a_published_series(rate_context: SignalContext) -> None:
    """Counted in observations, a window on a fund would accept a hole.

    Twenty closes of an ETF spanning twenty-six sessions is the one mistake the
    window contract exists to prevent, so asking this signal about one is a
    wiring mistake and stops the run.
    """
    signal = LevelChangeSignal(signal_id="change_4o", lookback_observations=4)

    with pytest.raises(ValueError, match="must be counted in sessions"):
        signal.compute(rate_context, ["ETF_EU"])


def test_an_unknown_instrument_is_a_configuration_mistake(
    rate_context: SignalContext,
) -> None:
    """A typo in a universe is not a data problem."""
    signal = LevelChangeSignal(signal_id="change_4o", lookback_observations=4)

    with pytest.raises(KeyError):
        signal.compute(rate_context, ["NOT_REGISTERED"])


def test_a_later_observation_changes_nothing(
    make_market: MarketBuilder,
    make_levels: LevelsBuilder,
    make_context: ContextBuilder,
    make_bars: BarsBuilder,
    xpar,
    prices,
    evening,
) -> None:
    """The look-ahead guard: a value published after the decision is not in it."""
    signal = LevelChangeSignal(signal_id="change_4o", lookback_observations=4)
    with_the_future = dict(RATES)
    with_the_future[date(2026, 9, 15)] = 9.99
    market = make_market(
        {"ETF_EU": make_bars("ETF_EU", xpar, prices(100.0, 1.0))},
        None,
        {"RATE_US": make_levels("RATE_US", with_the_future)},
    )
    context = make_context(market, evening(date(2026, 9, 14)))

    result = signal.compute(context, ["RATE_US"])

    assert result.value("RATE_US") == pytest.approx(0.20)


def test_the_definition_says_how_the_window_is_counted() -> None:
    """A reader of the record has to know it was not sessions in a row."""
    definition = LevelChangeSignal(signal_id="change_4o", lookback_observations=4).definition()

    assert definition["window_mode"] == WindowMode.AVAILABLE_OBSERVATIONS.value
    assert definition["unit"] == SignalUnit.SERIES_UNITS.value
    assert definition["lookback_observations"] == 4


@pytest.mark.parametrize("lookback", [0, -1, True, 2.5])
def test_a_lookback_that_is_not_a_count_is_refused(lookback: object) -> None:
    """A configuration mistake, and it stops the run rather than a name."""
    with pytest.raises(ValueError, match="lookback_observations"):
        LevelChangeSignal(signal_id="change", lookback_observations=lookback)  # type: ignore[arg-type]
