"""Standardising a published level against its own recent history.

The arithmetic is checked on numbers anyone can do on paper. What the rest of
the file is about is the two conventions that make a z-score mean one thing
rather than another: which observations the mean is taken over, and what
happens when there is no spread to divide by.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable
from datetime import date, datetime

import pandas as pd
import pytest

from quant_backtester.data.reader import MarketDataReader
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.engine import SignalEngine
from quant_backtester.signals.level.change import LevelChangeSignal
from quant_backtester.signals.level.zscore import LevelZScoreSignal
from quant_backtester.signals.types import SignalStatus, SignalUnit, WindowMode

BarsBuilder = Callable[..., pd.DataFrame]
LevelsBuilder = Callable[..., pd.DataFrame]
MarketBuilder = Callable[..., MarketDataReader]
ContextBuilder = Callable[[MarketDataReader, datetime], SignalContext]

SPAN: tuple[date, ...] = (
    date(2026, 9, 1),
    date(2026, 9, 2),
    date(2026, 9, 3),
    date(2026, 9, 4),
    date(2026, 9, 7),
    date(2026, 9, 8),
    date(2026, 9, 9),
    date(2026, 9, 10),
    date(2026, 9, 11),
    date(2026, 9, 14),
)


def rate_context(
    make_market: MarketBuilder,
    make_levels: LevelsBuilder,
    make_context: ContextBuilder,
    make_bars: BarsBuilder,
    xpar: object,
    prices: Callable[..., dict[date, float]],
    evening: Callable[[date], datetime],
    values: list[float],
) -> SignalContext:
    """Return a context whose rate holds ``values``, oldest first."""
    levels = dict(zip(SPAN[-len(values) :], values, strict=True))
    market = make_market(
        {"ETF_EU": make_bars("ETF_EU", xpar, prices(100.0, 1.0))},
        None,
        {"RATE_US": make_levels("RATE_US", levels)},
    )
    return make_context(market, evening(date(2026, 9, 14)))


def test_a_level_is_measured_in_the_spreads_of_its_own_window(
    make_market: MarketBuilder,
    make_levels: LevelsBuilder,
    make_context: ContextBuilder,
    make_bars: BarsBuilder,
    xpar,
    prices,
    evening,
) -> None:
    """Hand-checkable: 1, 2, 3, 4, 10 against their own mean and spread."""
    values = [1.0, 2.0, 3.0, 4.0, 10.0]
    context = rate_context(
        make_market, make_levels, make_context, make_bars, xpar, prices, evening, values
    )
    expected = (10.0 - statistics.fmean(values)) / statistics.stdev(values)

    result = LevelZScoreSignal(signal_id="rate_z_5o", window_observations=5).compute(
        context, ["RATE_US"]
    )

    assert result.status("RATE_US") is SignalStatus.OK
    assert result.value("RATE_US") == pytest.approx(expected)


def test_the_freshest_observation_is_part_of_what_it_is_measured_against(
    make_market: MarketBuilder,
    make_levels: LevelsBuilder,
    make_context: ContextBuilder,
    make_bars: BarsBuilder,
    xpar,
    prices,
    evening,
) -> None:
    """The stated convention, pinned so it cannot drift.

    "At the top of its own last quarter" includes today in the quarter.
    Standardising against the observations strictly before it measures the
    surprise of the release instead - a different quantity, and one that would
    give a visibly larger number here.
    """
    values = [1.0, 2.0, 3.0, 4.0, 10.0]
    context = rate_context(
        make_market, make_levels, make_context, make_bars, xpar, prices, evening, values
    )
    including = (10.0 - statistics.fmean(values)) / statistics.stdev(values)
    excluding = (10.0 - statistics.fmean(values[:-1])) / statistics.stdev(values[:-1])

    result = LevelZScoreSignal(signal_id="rate_z_5o", window_observations=5).compute(
        context, ["RATE_US"]
    )

    assert result.value("RATE_US") == pytest.approx(including)
    assert result.value("RATE_US") != pytest.approx(excluding)


def test_a_level_at_its_own_mean_scores_zero(
    make_market: MarketBuilder,
    make_levels: LevelsBuilder,
    make_context: ContextBuilder,
    make_bars: BarsBuilder,
    xpar,
    prices,
    evening,
) -> None:
    """Symmetric values around the last one: nothing unusual is happening."""
    context = rate_context(
        make_market,
        make_levels,
        make_context,
        make_bars,
        xpar,
        prices,
        evening,
        [1.0, 3.0, 1.0, 3.0, 2.0],
    )

    result = LevelZScoreSignal(signal_id="rate_z_5o", window_observations=5).compute(
        context, ["RATE_US"]
    )

    assert result.value("RATE_US") == pytest.approx(0.0)


def test_a_series_that_did_not_move_has_no_spread_to_divide_by(
    make_market: MarketBuilder,
    make_levels: LevelsBuilder,
    make_context: ContextBuilder,
    make_bars: BarsBuilder,
    xpar,
    prices,
    evening,
) -> None:
    """A policy rate held for a quarter is a real case, not a corner one.

    Infinity is not the answer and zero is worse: the first is unusable and the
    second says "perfectly ordinary", which is a claim about a distribution
    that does not exist.
    """
    context = rate_context(
        make_market,
        make_levels,
        make_context,
        make_bars,
        xpar,
        prices,
        evening,
        [2.0, 2.0, 2.0, 2.0, 2.0],
    )

    result = LevelZScoreSignal(signal_id="rate_z_5o", window_observations=5).compute(
        context, ["RATE_US"]
    )

    assert result.status("RATE_US") is SignalStatus.INVALID_INPUT
    assert result.value("RATE_US") != result.value("RATE_US")


def test_the_spread_is_the_one_the_sample_supports(
    make_market: MarketBuilder,
    make_levels: LevelsBuilder,
    make_context: ContextBuilder,
    make_bars: BarsBuilder,
    xpar,
    prices,
    evening,
) -> None:
    """``ddof=1``: dividing by n would report a z-score it has not earned."""
    values = [1.0, 2.0, 3.0, 4.0, 10.0]
    context = rate_context(
        make_market, make_levels, make_context, make_bars, xpar, prices, evening, values
    )
    population = (10.0 - statistics.fmean(values)) / statistics.pstdev(values)

    result = LevelZScoreSignal(signal_id="rate_z_5o", window_observations=5).compute(
        context, ["RATE_US"]
    )

    assert result.value("RATE_US") < population


def test_only_the_window_is_looked_at(
    make_market: MarketBuilder,
    make_levels: LevelsBuilder,
    make_context: ContextBuilder,
    make_bars: BarsBuilder,
    xpar,
    prices,
    evening,
) -> None:
    """Not an expanding mean over whatever the store happens to hold today.

    The older observations here are wild; the last three are calm, and a
    three-observation z-score must not know about the rest.
    """
    context = rate_context(
        make_market,
        make_levels,
        make_context,
        make_bars,
        xpar,
        prices,
        evening,
        [50.0, -30.0, 90.0, 1.0, 2.0, 3.0],
    )
    calm = [1.0, 2.0, 3.0]
    expected = (3.0 - statistics.fmean(calm)) / statistics.stdev(calm)

    result = LevelZScoreSignal(signal_id="rate_z_3o", window_observations=3).compute(
        context, ["RATE_US"]
    )

    assert result.value("RATE_US") == pytest.approx(expected)


def test_a_later_observation_changes_nothing(
    make_market: MarketBuilder,
    make_levels: LevelsBuilder,
    make_context: ContextBuilder,
    make_bars: BarsBuilder,
    xpar,
    prices,
    evening,
) -> None:
    """The look-ahead guard: what is published after the decision is not in it."""
    values = [1.0, 2.0, 3.0, 4.0, 10.0]
    signal = LevelZScoreSignal(signal_id="rate_z_5o", window_observations=5)
    without = rate_context(
        make_market, make_levels, make_context, make_bars, xpar, prices, evening, values
    )
    before = signal.compute(without, ["RATE_US"]).value("RATE_US")

    levels = dict(zip(SPAN[-5:], values, strict=True))
    levels[date(2026, 9, 15)] = 99.0
    market = make_market(
        {"ETF_EU": make_bars("ETF_EU", xpar, prices(100.0, 1.0))},
        None,
        {"RATE_US": make_levels("RATE_US", levels)},
    )
    with_the_future = make_context(market, evening(date(2026, 9, 14)))

    assert signal.compute(with_the_future, ["RATE_US"]).value("RATE_US") == pytest.approx(before)


def test_a_fund_is_not_a_published_series(
    make_market: MarketBuilder,
    make_levels: LevelsBuilder,
    make_context: ContextBuilder,
    make_bars: BarsBuilder,
    xpar,
    prices,
    evening,
) -> None:
    """A window over a fund is counted in sessions, by a signal that says so."""
    context = rate_context(
        make_market, make_levels, make_context, make_bars, xpar, prices, evening, [1.0, 2.0, 3.0]
    )

    with pytest.raises(ValueError, match="must be counted in sessions"):
        LevelZScoreSignal(signal_id="z_3o", window_observations=3).compute(context, ["ETF_EU"])


def test_a_window_of_one_observation_is_refused() -> None:
    """One point has no spread, and a z-score of it is a division by nothing."""
    with pytest.raises(ValueError, match="at least 2"):
        LevelZScoreSignal(signal_id="z_1o", window_observations=1)


def test_the_definition_records_the_convention() -> None:
    """Two z-scores computed on different conventions are different signals."""
    definition = LevelZScoreSignal(signal_id="z_60o", window_observations=60).definition()

    assert definition["window_mode"] == WindowMode.AVAILABLE_OBSERVATIONS.value
    assert definition["unit"] == SignalUnit.ZSCORE.value
    assert definition["includes_latest_observation"] is True


def test_a_published_series_goes_through_the_engine_like_any_other(
    make_market: MarketBuilder,
    make_levels: LevelsBuilder,
    make_context: ContextBuilder,
    make_bars: BarsBuilder,
    xpar,
    prices,
    evening,
) -> None:
    """Two signals over a rate, one snapshot, one instant.

    The engine asks every signal about the same universe, so a level signal
    belongs to a snapshot computed over published series. Mixing a fund into
    that universe is refused by the signal rather than half-answered - and a
    strategy that wants both takes two snapshots until the engine learns to
    give a signal a universe of its own.
    """
    context = rate_context(
        make_market, make_levels, make_context, make_bars, xpar, prices, evening, [1.0, 2.0, 3.0]
    )

    snapshot = SignalEngine().compute(
        context,
        [
            LevelChangeSignal(signal_id="rate_change_2o", lookback_observations=2),
            LevelZScoreSignal(signal_id="rate_z_3o", window_observations=3),
        ],
        ["RATE_US"],
    )

    assert set(snapshot) == {"rate_change_2o", "rate_z_3o"}
    assert snapshot.value("rate_change_2o", "RATE_US") == pytest.approx(2.0)
    assert snapshot.status("rate_z_3o", "RATE_US") is SignalStatus.OK
    assert snapshot.as_of == context.as_of
