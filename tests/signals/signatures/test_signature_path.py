"""The path of a window: what its three coordinates are, and what makes it unusable."""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import date, datetime

import numpy as np
import pytest

from quant_backtester.data.calendars import TradingCalendar
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.data.schemas import BarField
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.signatures.path import (
    CLASSICAL_NAMES,
    NO_ACTIVITY,
    ZERO_VOLUME_REFERENCE,
    SignaturePathConfig,
    UnusablePath,
    build_signature_path,
    classical_indicators,
    load_path_inputs,
    raw_trajectory,
)
from quant_backtester.signals.types import SignalStatus

SignatureMarketBuilder = Callable[..., MarketDataReader]


def config(steps: int = 3, reference: int = 2, **overrides: object) -> SignaturePathConfig:
    """Return a path short enough to compute by hand, unless overridden."""
    parameters: dict[str, object] = {
        "steps": steps,
        "volume_reference_sessions": reference,
        "price_scale": 100.0,
        "use_volume": True,
        "max_age_sessions": 0,
    }
    parameters.update(overrides)
    return SignaturePathConfig(**parameters)  # type: ignore[arg-type]


ADJUSTED = [50.0, 100.0, 110.0, 99.0, 121.0]
RAW = [50.0, 100.0, 110.0, 99.0, 121.0]
VOLUMES = [10.0, 15.0, 10.0, 20.0, 10.0]
"""Two reference sessions (activity 500 and 1 500, median 1 000), the second of which is
the path's first point, then three described sessions."""


def test_the_three_coordinates_are_those_of_the_definition() -> None:
    path = build_signature_path(ADJUSTED, RAW, VOLUMES, config())

    described = ADJUSTED[-4:]
    activity = [RAW[i] * VOLUMES[i] / 1_000.0 for i in (2, 3, 4)]  # 1.1, 1.98, 1.21
    assert path.shape == (4, 3) and path.flags["C_CONTIGUOUS"] and path.dtype == np.float64
    assert list(path[0]) == [0.0, 0.0, 0.0]  # the path starts at the origin
    assert list(path[:, 0]) == pytest.approx(
        [100.0 * math.log(price / described[0]) for price in described]
    )
    assert list(path[:, 1]) == pytest.approx(
        [0.0, activity[0] / 3, sum(activity[:2]) / 3, sum(activity) / 3]
    )
    assert list(path[:, 2]) == pytest.approx([0.0, 1 / 3, 2 / 3, 1.0])


def test_the_price_coordinate_is_a_cumulative_log_return_not_a_sum_of_levels() -> None:
    path = build_signature_path(ADJUSTED, RAW, VOLUMES, config())
    scaled = build_signature_path(
        [10.0 * price for price in ADJUSTED], [10.0 * price for price in RAW], VOLUMES, config()
    )

    # A fund quoted ten times higher has the same path: prices and reference scale together.
    assert np.allclose(scaled, path)
    assert path[-1, 0] == pytest.approx(100.0 * math.log(121.0 / 100.0))


def test_the_activity_is_relative_to_the_sessions_before_not_to_its_own_total() -> None:
    """Twice the recent volume is twice the last point: the window total is not divided out."""
    busier = [*VOLUMES[:2], *[2.0 * volume for volume in VOLUMES[2:]]]

    path = build_signature_path(ADJUSTED, RAW, VOLUMES, config())
    doubled = build_signature_path(ADJUSTED, RAW, busier, config())

    assert doubled[-1, 1] == pytest.approx(2.0 * path[-1, 1])
    assert path[-1, 1] != pytest.approx(1.0)
    assert np.allclose(doubled[:, 0], path[:, 0])


def test_a_split_leaves_the_activity_unchanged() -> None:
    """Raw close times raw volume: a price divided by four comes with four times the units."""
    raw = [*RAW[:3], RAW[3] / 4.0, RAW[4] / 4.0]
    volumes = [*VOLUMES[:3], VOLUMES[3] * 4.0, VOLUMES[4] * 4.0]

    assert np.allclose(
        build_signature_path(ADJUSTED, raw, volumes, config()),
        build_signature_path(ADJUSTED, RAW, VOLUMES, config()),
    )


def test_without_the_volume_channel_the_second_coordinate_is_zero() -> None:
    path = build_signature_path(ADJUSTED, RAW, VOLUMES, config())
    without = build_signature_path(ADJUSTED, RAW, VOLUMES, config(use_volume=False))

    assert not without[:, 1].any()
    assert np.array_equal(without[:, [0, 2]], path[:, [0, 2]])


def test_an_observed_zero_stays_a_zero_and_no_activity_at_all_is_unusable() -> None:
    one_idle = [*VOLUMES[:2], 0.0, 20.0, 10.0]

    path = build_signature_path(ADJUSTED, RAW, one_idle, config())

    assert path[1, 1] == 0.0 and path[-1, 1] > 0.0  # nothing replaced by one
    with pytest.raises(UnusablePath) as idle:
        build_signature_path(ADJUSTED, RAW, [*VOLUMES[:2], 0.0, 0.0, 0.0], config())
    assert idle.value.reason == NO_ACTIVITY
    with pytest.raises(UnusablePath) as no_reference:
        build_signature_path(ADJUSTED, RAW, [0.0, 0.0, 10.0, 20.0, 10.0], config())
    assert no_reference.value.reason == ZERO_VOLUME_REFERENCE


@pytest.mark.parametrize(
    ("adjusted", "raw", "volumes", "match"),
    [
        (ADJUSTED[:-1], RAW, VOLUMES, "three series of 5"),
        ([*ADJUSTED[:-1], float("nan")], RAW, VOLUMES, "finite"),
        ([*ADJUSTED[:-1], 0.0], RAW, VOLUMES, "positive prices"),
        (ADJUSTED, RAW, [*VOLUMES[:-1], -1.0], "non-negative volumes"),
    ],
)
def test_inputs_a_path_cannot_be_built_from_are_a_callers_error(
    adjusted: list[float], raw: list[float], volumes: list[float], match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        build_signature_path(adjusted, raw, volumes, config())


def test_the_raw_trajectory_is_the_increments_the_path_cumulates() -> None:
    path = build_signature_path(ADJUSTED, RAW, VOLUMES, config())

    increments = raw_trajectory(ADJUSTED, RAW, VOLUMES, config())

    assert increments.shape == (6,)
    assert np.allclose(np.cumsum(increments[:3]), path[1:, 0])
    assert np.allclose(np.cumsum(increments[3:]) / 3, path[1:, 1])


def test_the_nine_classical_indicators_are_computed_at_the_same_instant() -> None:
    rng = np.random.default_rng(3)
    prices = list(100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.01, 120))))
    volumes = list(rng.uniform(1_000.0, 2_000.0, 120))
    setting = config(steps=60, reference=60)

    values = classical_indicators(prices, prices, volumes, setting)

    activity = np.asarray(prices) * np.asarray(volumes)
    reference = float(np.median(activity[:60]))
    returns = np.diff(np.log(prices))
    assert len(values) == len(CLASSICAL_NAMES) == 9
    assert values[0] == pytest.approx(100.0 * math.log(prices[-1] / prices[-21]))
    assert values[1] == pytest.approx(100.0 * math.log(prices[-1] / prices[-61]))
    assert values[2] == pytest.approx(100.0 * (prices[-1] / float(np.mean(prices[-20:])) - 1.0))
    assert values[4] == pytest.approx(100.0 * float(np.std(returns[-20:], ddof=1)))
    assert values[7] == pytest.approx(float(np.mean(activity[-60:])) / reference)
    assert values[8] == pytest.approx(activity[-1] / reference)
    with pytest.raises(ValueError, match="60 described sessions"):
        classical_indicators(prices[:5], prices[:5], volumes[:5], config())


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"steps": 0}, "steps"),
        ({"volume_reference_sessions": 0}, "volume_reference_sessions"),
        ({"price_scale": 0.0}, "price_scale"),
        ({"use_volume": "yes"}, "use_volume"),
        ({"max_age_sessions": -1}, "max_age_sessions"),
    ],
)
def test_a_path_that_cannot_be_built_is_refused(overrides: dict[str, object], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        config(**overrides)  # type: ignore[arg-type]


def test_the_conventions_of_the_path_are_recorded(signature_path: SignaturePathConfig) -> None:
    definition = signature_path.definition()

    assert signature_path.required_history_sessions == 20
    assert definition["coordinates"] == [
        "cum_log_price_pct",
        "cum_relative_turnover",
        "session_time",
    ]
    assert definition["volume_proxy"] == "RAW_CLOSE_TIMES_RAW_VOLUME"
    assert definition["interpolation"] == "PIECEWISE_LINEAR"
    assert definition != config(use_volume=False).definition()


# --- the inputs, through a reader fixed at a decision --------------------------------------


@pytest.fixture
def year(xpar: TradingCalendar) -> list[date]:
    """Return every Paris session of 2026 from the funds' first one."""
    return [session.session_date for session in xpar.sessions(date(2026, 1, 5), date(2026, 12, 31))]


Contexts = Callable[[MarketDataReader, date], SignalContext]


@pytest.fixture
def at(
    make_context: Callable[[MarketDataReader, datetime], SignalContext],
    evening: Callable[[date], datetime],
) -> Contexts:
    """Return the context of a decision after the close of a day."""
    return lambda market, day: make_context(market, evening(day))


def test_the_three_series_are_read_over_the_window_and_its_reference(
    make_signature_market: SignatureMarketBuilder,
    at: Contexts,
    year: list[date],
    signature_path: SignaturePathConfig,
) -> None:
    inputs = load_path_inputs(at(make_signature_market(), year[100]), "ETF_EU", signature_path)

    assert inputs.status is SignalStatus.OK and inputs.age_sessions == 0
    assert inputs.dates == tuple(year[81:101])
    assert len(inputs.adjusted_closes) == len(inputs.raw_closes) == len(inputs.volumes) == 20
    assert inputs.adjusted_closes == inputs.raw_closes  # no corporate action in this market
    assert len(set(inputs.volumes)) > 1


def test_a_refused_window_says_why_and_a_zero_volume_is_not_one(
    make_signature_market: SignatureMarketBuilder,
    at: Contexts,
    year: list[date],
    signature_path: SignaturePathConfig,
) -> None:
    """Short, absent, invalid and merely idle are four different days."""

    def idle(frames: dict) -> None:
        frames["ETF_EU"].loc[frames["ETF_EU"]["session_date"] == year[95], "volume"] = 0.0

    def absent(frames: dict) -> None:
        frame = frames["ETF_EU"]
        row = frame["session_date"] == year[95]
        frame.loc[row, "check_status"] = "CONFLICT"
        frame.loc[row, "conflicting_fields"] = BarField.VOLUME.value
        frame.loc[row, "unconfirmed_fields"] = ""

    def worthless(frames: dict) -> None:
        frame = frames["ETF_EU"]
        frame.loc[frame["session_date"] == year[95], ["open", "high", "low", "close"]] = 0.0

    short = load_path_inputs(at(make_signature_market("a"), year[18]), "ETF_EU", signature_path)
    zero = load_path_inputs(
        at(make_signature_market("b", mutate=idle), year[100]), "ETF_EU", signature_path
    )
    missing = load_path_inputs(
        at(make_signature_market("c", mutate=absent), year[100]), "ETF_EU", signature_path
    )
    invalid = load_path_inputs(
        at(make_signature_market("d", mutate=worthless), year[100]), "ETF_EU", signature_path
    )

    assert short.status is SignalStatus.INSUFFICIENT_HISTORY and short.volumes == ()
    assert zero.status is SignalStatus.OK and zero.zero_volume_sessions == 1
    assert missing.status is SignalStatus.NON_CONSECUTIVE_HISTORY and missing.volumes == ()
    assert invalid.status is SignalStatus.INVALID_INPUT


def test_what_happens_after_the_decision_does_not_reach_its_inputs(
    make_signature_market: SignatureMarketBuilder,
    at: Contexts,
    year: list[date],
    signature_path: SignaturePathConfig,
) -> None:
    def later(frames: dict) -> None:
        for frame in frames.values():
            after = frame["session_date"] > year[100]
            frame.loc[after, ["open", "high", "low", "close"]] *= 2.0
            frame.loc[after, "volume"] *= 5.0

    before = load_path_inputs(at(make_signature_market("a"), year[100]), "ETF_EU", signature_path)
    after = load_path_inputs(
        at(make_signature_market("b", mutate=later), year[100]), "ETF_EU", signature_path
    )

    assert after == before
