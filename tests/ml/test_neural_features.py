"""The input of the network: the formulas, the layout, the refusals and the look-ahead."""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import date, datetime
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from quant_backtester.data.reader import MarketDataReader
from quant_backtester.ml.config import NeuralStrategyConfig
from quant_backtester.ml.features import (
    FeatureScaler,
    FeatureVector,
    NeuralFeatureBuilder,
    series_block,
)
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.types import SignalStatus

DECISION = date(2026, 9, 14)
"""A Monday after the calibration of the small model, with every series fresh."""

Build = Callable[..., FeatureVector]


def evening(day: date) -> datetime:
    """Return the decision instant of a session: 23:00 in Paris."""
    return datetime(day.year, day.month, day.day, 23, 0, tzinfo=ZoneInfo("Europe/Paris"))


@pytest.fixture
def build(neural_config: NeuralStrategyConfig, calendars) -> Build:
    """Return the input of one decision on a given store."""

    def at(reader: MarketDataReader, day: date = DECISION) -> FeatureVector:
        context = SignalContext(
            market=reader.at(evening(day)), instruments=reader.instruments, calendars=calendars
        )
        return NeuralFeatureBuilder(neural_config).build(context)

    return at


def test_a_block_is_the_path_the_trends_and_the_volatilities_worked_by_hand() -> None:
    points = [100.0, 110.0, 121.0, 121.0]

    block = series_block(points, ma_windows=(2, 4), vol_windows=(2, 3), annualization=252)

    assert block is not None
    log = math.log(1.1)
    # Exactly four observations give four path values and three returns.
    assert block[:4] == pytest.approx([0.0, log, 2 * log, 2 * log])
    assert block[4] == pytest.approx(121.0 / 121.0 - 1.0)
    assert block[5] == pytest.approx(121.0 / 113.0 - 1.0)
    # Returns: log, log, 0. The last two have a sample deviation of log/sqrt(2).
    assert block[6] == pytest.approx(math.sqrt(252) * log / math.sqrt(2))
    assert block[7] == pytest.approx(math.sqrt(252) * float(np.std([log, log, 0.0], ddof=1)))
    assert len(block) == 4 + 2 + 2


@pytest.mark.parametrize("bad", [0.0, -3.0, math.nan, math.inf])
def test_a_price_that_is_not_positive_and_finite_gives_no_block(bad: float) -> None:
    block = series_block([100.0, bad, 101.0], ma_windows=(2,), vol_windows=(2,), annualization=252)

    assert block is None


def test_the_vector_is_each_series_block_then_the_level(
    build: Build, neural_market: MarketDataReader, neural_config: NeuralStrategyConfig
) -> None:
    vector = build(neural_market)
    market = neural_market.at(evening(DECISION))
    closes = [float(value) for value in market.adjusted_history("ETF_EU").iloc[-6:]]
    levels = [float(value) for value in market.history("RATE_US").iloc[-6:]]

    assert vector.status is SignalStatus.OK
    assert vector.values is not None
    assert len(vector.values) == neural_config.input_size
    first = series_block(closes, ma_windows=(2, 3, 6), vol_windows=(2, 4), annualization=252)
    assert first is not None
    assert list(vector.values[:11]) == pytest.approx(first)
    assert vector.values[11] == 0.0  # the age of a fund's own session
    # The level block is taken on the published values, and its absolute
    # level is the index over one hundred.
    last = series_block(levels, ma_windows=(2, 3, 6), vol_windows=(2, 4), annualization=252)
    assert last is not None
    assert list(vector.values[24:35]) == pytest.approx(last)
    assert vector.values[-1] == pytest.approx(levels[-1] / 100.0)
    assert [item.observations for item in vector.series] == [6, 6, 6]
    assert vector.series[0].last_date == DECISION


def test_a_level_too_old_invalidates_the_whole_input(
    build: Build, make_neural_market: Callable[..., MarketDataReader]
) -> None:
    def stop_publishing(bars, levels) -> None:
        for day in [day for day in levels if day > date(2026, 9, 9)]:
            del levels[day]

    vector = build(make_neural_market(mutate=stop_publishing))

    # Published on the 9th, read on the 14th: three Paris sessions old, one allowed.
    assert vector.values is None
    assert vector.status is SignalStatus.STALE_INPUT
    assert [item.instrument_id for item in vector.faulty] == ["RATE_US"]
    assert vector.series[2].age_sessions == 3


def test_a_missing_session_inside_a_fund_window_invalidates_the_input(
    build: Build, make_neural_market: Callable[..., MarketDataReader]
) -> None:
    def lose_a_session(bars, levels) -> None:
        del bars["ETF_OTHER"][date(2026, 9, 10)]

    vector = build(make_neural_market(mutate=lose_a_session))

    # Nothing is carried over the hole: six observations spanning seven sessions.
    assert vector.values is None
    assert vector.status is SignalStatus.NON_CONSECUTIVE_HISTORY
    assert [item.instrument_id for item in vector.faulty] == ["ETF_OTHER"]


def test_too_short_a_history_and_a_missing_close_are_told_apart(
    build: Build, make_neural_market: Callable[..., MarketDataReader]
) -> None:
    def lose_the_decision(bars, levels) -> None:
        del bars["ETF_EU"][DECISION]

    assert build(make_neural_market("a"), date(2026, 1, 8)).status is (
        SignalStatus.INSUFFICIENT_HISTORY
    )
    assert build(make_neural_market("b", mutate=lose_the_decision)).status in (
        SignalStatus.MISSING_INPUT,
        SignalStatus.STALE_INPUT,
    )


def test_what_happens_after_the_decision_does_not_change_its_input(
    build: Build,
    neural_market: MarketDataReader,
    make_neural_market: Callable[..., MarketDataReader],
) -> None:
    """The look-ahead guard: a future the reader cannot see changes nothing."""

    def rewrite_the_future(bars, levels) -> None:
        for prices in bars.values():
            for day in [day for day in prices if day > DECISION]:
                prices[day] = tuple(value * 3.0 for value in prices[day])
        for day in [day for day in levels if day > DECISION]:
            levels[day] = 99.0

    assert build(make_neural_market("future", mutate=rewrite_the_future)) == build(neural_market)


def test_the_level_series_must_be_a_published_series(
    neural_config: NeuralStrategyConfig, neural_market: MarketDataReader, calendars
) -> None:
    config = NeuralStrategyConfig.from_definition(
        neural_config.definition()
        | {"feature_ids": ["ETF_EU", "ETF_OTHER", "ETF_LATE"], "level_id": "ETF_LATE"}
    )
    context = SignalContext(
        market=neural_market.at(evening(DECISION)),
        instruments=neural_market.instruments,
        calendars=calendars,
    )

    with pytest.raises(ValueError, match="not a published"):
        NeuralFeatureBuilder(config).build(context)


def test_a_scaler_is_the_training_mean_and_population_deviation() -> None:
    inputs = np.array([[1.0, 5.0, 2.0], [3.0, 5.0, 2.0 + 1e-10]])

    scaler = FeatureScaler.fit(inputs, clip=5.0)
    scaled, clipped = scaler.transform(np.array([[2.0, 7.0, 2.0], [30.0, 5.0, 2.0]]))

    assert list(scaler.mean) == pytest.approx([2.0, 5.0, 2.0])
    assert list(scaler.std) == pytest.approx([1.0, 0.0, 0.5e-10])
    # A deviation under 1e-8 divides by one; 28 deviations are clipped to 5.
    assert scaled.ravel().tolist() == pytest.approx([0.0, 2.0, 0.0, 5.0, 0.0, 0.0], abs=1e-9)
    assert clipped == 1


def test_a_scaler_refuses_what_it_was_not_fitted_for() -> None:
    scaler = FeatureScaler.fit(np.ones((3, 2)), clip=5.0)

    with pytest.raises(ValueError, match="fitted on 2"):
        scaler.transform(np.ones(3))
    with pytest.raises(ValueError, match="at least one input"):
        FeatureScaler.fit(np.ones((0, 2)), clip=5.0)
    with pytest.raises(ValueError, match="valid inputs only"):
        FeatureScaler.fit(np.array([[1.0, math.nan]]), clip=5.0)
    with pytest.raises(ValueError, match="one length"):
        FeatureScaler(np.ones(2), np.ones(3), clip=5.0)
