"""The paired block bootstrap: shared blocks, a declared seed, a difference and its spread."""

from __future__ import annotations

from datetime import date, timedelta
from itertools import pairwise

import numpy as np
import pandas as pd
import pytest

from quant_backtester.analytics.config import AnalyticsConfig
from quant_backtester.analytics.performance import PerformanceStats
from quant_backtester.analytics.uncertainty import (
    PairedStatistic,
    UndefinedStatistic,
    holm_adjusted,
    paired_block_bootstrap,
    paired_stationary_bootstrap,
    stationary_indices,
)


def curve(returns: list[float]) -> pd.Series:
    """Return an equity curve from 100 compounding the given returns."""
    values = [100.0]
    for value in returns:
        values.append(values[-1] * (1.0 + value))
    return pd.Series(values, index=pd.RangeIndex(len(values)))


def noise(count: int, seed: int, scale: float = 0.01) -> list[float]:
    return list(np.random.default_rng(seed).normal(0.0, scale, count))


CONFIG = AnalyticsConfig(sessions_per_year=255, risk_free_rate=0.0)


def boot(
    strategy: pd.Series,
    control: pd.Series,
    statistic: PairedStatistic,
    *,
    block: int = 5,
    draws: int = 400,
    seed: int = 7,
    level: float = 0.9,
    config: AnalyticsConfig = CONFIG,
):
    """Run the bootstrap with the test settings, some of them replaced."""
    return paired_block_bootstrap(
        strategy,
        control,
        statistic=statistic,
        block=block,
        draws=draws,
        seed=seed,
        level=level,
        config=config,
    )


@pytest.mark.parametrize("statistic", list(PairedStatistic))
def test_two_identical_books_differ_by_nothing_in_every_draw(statistic: PairedStatistic) -> None:
    """C02 acceptance: the same curve twice gives a zero difference, estimate and interval."""
    book = curve(noise(250, 1))

    result = boot(book, book.copy(), statistic)

    assert (result.estimate, result.low, result.high) == (0.0, 0.0, 0.0)


def test_the_same_seed_gives_the_same_interval_and_another_seed_another() -> None:
    strategy, control = curve(noise(250, 1)), curve(noise(250, 2))

    first = boot(strategy, control, PairedStatistic.SHARPE)
    again = boot(strategy, control, PairedStatistic.SHARPE)
    other = boot(strategy, control, PairedStatistic.SHARPE, seed=8)

    assert first == again
    assert (first.low, first.high) != (other.low, other.high)


def test_a_constant_edge_is_measured_exactly_and_with_no_spread() -> None:
    """Every session 0.1% better: resampled in pairs, the edge never moves."""
    base = noise(250, 3)
    strategy = curve([value + 0.001 for value in base])
    control = curve(base)

    result = boot(strategy, control, PairedStatistic.MEAN_RETURN)

    assert result.estimate == pytest.approx(0.001 * 255)
    assert result.low == pytest.approx(0.001 * 255)
    assert result.high == pytest.approx(0.001 * 255)


def test_pairing_keeps_what_the_books_share() -> None:
    """Correlated books: the paired interval of the difference is much narrower than apart."""
    common = noise(250, 4, scale=0.02)
    own = noise(250, 5, scale=0.001)
    strategy = curve([c + o for c, o in zip(common, own, strict=True)])
    control = curve(common)

    paired = boot(strategy, control, PairedStatistic.MEAN_RETURN)

    assert paired.high - paired.low < 0.1


def test_everything_the_result_depends_on_is_recorded() -> None:
    result = boot(curve(noise(50, 1)), curve(noise(50, 2)), PairedStatistic.SHARPE)

    assert result.definition() | {"estimate": 0, "low": 0, "high": 0} == {
        "statistic": "SHARPE",
        "estimate": 0,
        "low": 0,
        "high": 0,
        "level": 0.9,
        "sessions": 50,
        "block": 5,
        "draws": 400,
        "seed": 7,
        "analytics": {"sessions_per_year": 255, "risk_free_rate": 0.0, "minimum_sessions": 60},
    }


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"block": 0}, "does not fit"),
        ({"block": 300}, "does not fit"),
        ({"draws": 10}, "too few"),
        ({"level": 1.0}, "coverage"),
    ],
)
def test_parameters_out_of_range_are_refused(change: dict[str, object], message: str) -> None:
    book = curve(noise(250, 1))

    with pytest.raises(ValueError, match=message):
        boot(book, book, PairedStatistic.SHARPE, **change)  # type: ignore[arg-type]


def test_books_over_different_sessions_are_not_compared() -> None:
    book = curve(noise(50, 1))

    with pytest.raises(ValueError, match="same sessions"):
        boot(book, book.iloc[1:], PairedStatistic.SHARPE)


def test_the_sharpe_difference_is_the_one_the_report_prints() -> None:
    """Audit of archive 10: with no risk-free rate the difference was -0.079, of the wrong sign.

    The rate does not cancel in a difference of Sharpe ratios - each is divided
    by its own spread - so the bootstrap measures under the report's convention.
    """
    first = curve([0.0008 - 0.008, 0.0008 + 0.008] * 50)
    second = curve([0.00021 - 0.002, 0.00021 + 0.002] * 50)
    config = AnalyticsConfig(sessions_per_year=252, risk_free_rate=0.02, minimum_sessions=2)
    index = pd.Index([date(2026, 1, 1) + timedelta(days=n) for n in range(101)])

    result = paired_block_bootstrap(
        first,
        second,
        statistic=PairedStatistic.SHARPE,
        block=10,
        draws=100,
        seed=1,
        level=0.9,
        config=config,
    )
    reported = [
        PerformanceStats.from_equity(book.set_axis(index), config).sharpe_ratio
        for book in (first, second)
    ]

    assert result.estimate == pytest.approx(0.3864918659)
    assert reported[0] is not None and reported[1] is not None
    assert result.estimate == pytest.approx(reported[0] - reported[1])


def test_a_mean_return_difference_does_not_depend_on_the_rate() -> None:
    strategy, control = curve(noise(250, 1)), curve(noise(250, 2))
    rated = AnalyticsConfig(sessions_per_year=255, risk_free_rate=0.05)

    free = boot(strategy, control, PairedStatistic.MEAN_RETURN)
    with_rate = boot(strategy, control, PairedStatistic.MEAN_RETURN, config=rated)

    assert (with_rate.estimate, with_rate.low, with_rate.high) == pytest.approx(
        (free.estimate, free.low, free.high)
    )


def test_a_book_that_does_not_vary_has_no_sharpe_and_is_not_compared() -> None:
    """The report prints no Sharpe for it; the bootstrap refuses rather than reads zero."""
    flat = curve([0.0] * 100)

    with pytest.raises(UndefinedStatistic, match="control's returns do not vary"):
        boot(curve(noise(100, 1)), flat, PairedStatistic.SHARPE)


@pytest.mark.parametrize("rate", [0.001, 0.0, -0.001])
def test_returns_constant_in_theory_are_refused_like_the_report_refuses_them(rate: float) -> None:
    """Audit 13, C01: the bootstrap and the report draw the line at the same place.

    Compounding a constant return leaves rounding noise between sessions. The
    report prints no Sharpe ratio for it; a Sharpe difference of 1e14 is not
    resampled either.
    """
    steady = curve([rate] * 100)

    with pytest.raises(UndefinedStatistic, match="strategy's returns do not vary"):
        boot(steady, curve(noise(100, 1)), PairedStatistic.SHARPE)


# --- The stationary bootstrap (SA17) -------------------------------------------


def stationary(
    strategy: pd.Series,
    control: pd.Series,
    statistic: PairedStatistic,
    *,
    mean_block: int = 5,
    draws: int = 400,
    seed: int = 7,
    level: float = 0.9,
):
    """Run the stationary bootstrap with the test settings, some of them replaced."""
    return paired_stationary_bootstrap(
        strategy,
        control,
        statistic=statistic,
        mean_block=mean_block,
        draws=draws,
        seed=seed,
        level=level,
        config=CONFIG,
    )


def test_stationary_indices_are_reproducible_and_in_range() -> None:
    first = stationary_indices(50, 4, np.random.default_rng(3))
    again = stationary_indices(50, 4, np.random.default_rng(3))
    other = stationary_indices(50, 4, np.random.default_rng(4))
    assert first == again
    assert first != other
    assert len(first) == 50
    assert all(0 <= index < 50 for index in first)


def test_stationary_blocks_have_the_declared_mean_length_and_wrap() -> None:
    # Over many sessions the share of restarts is 1 / mean_block, so the mean
    # length of a block is mean_block.
    count, mean_block = 20_000, 10
    indices = stationary_indices(count, mean_block, np.random.default_rng(11))
    breaks = sum(1 for before, after in pairwise(indices) if after != (before + 1) % count)
    assert count / (breaks + 1) == pytest.approx(mean_block, rel=0.05)
    # A block reaching the last session continues at the first.
    small = stationary_indices(5, 1_000, np.random.default_rng(0))
    assert any(before == 4 and after == 0 for before, after in pairwise(small))


def test_a_mean_block_of_one_restarts_at_every_session() -> None:
    # Every session is a new uniform draw: the ordinary bootstrap.
    indices = stationary_indices(2_000, 1, np.random.default_rng(5))
    continued = sum(1 for before, after in pairwise(indices) if after == before + 1)
    assert continued < 10


@pytest.mark.parametrize("statistic", list(PairedStatistic))
def test_stationary_identical_books_differ_by_nothing(statistic: PairedStatistic) -> None:
    book = curve(noise(120, 1))
    result = stationary(book, book, statistic)
    assert result.estimate == 0.0
    assert result.low == result.high == 0.0
    assert result.p_value == 1.0


def test_stationary_constant_edge_is_exact_and_significant() -> None:
    # Every return of the strategy is the control's plus 1 bp: each resample
    # gives the same mean difference, and none is as far from it as zero is.
    base = noise(200, 2)
    result = stationary(
        curve([value + 0.0001 for value in base]),
        curve(base),
        PairedStatistic.MEAN_RETURN,
        draws=200,
    )
    assert result.estimate == pytest.approx(0.0001 * 255, rel=1e-6)
    assert result.low == pytest.approx(result.estimate, rel=1e-6)
    assert result.high == pytest.approx(result.estimate, rel=1e-6)
    assert result.p_value == pytest.approx(1 / 201)


def test_stationary_p_value_is_large_for_noise_and_seeded() -> None:
    strategy, control = curve(noise(300, 21)), curve(noise(300, 22))
    first = stationary(strategy, control, PairedStatistic.SHARPE, seed=9)
    again = stationary(strategy, control, PairedStatistic.SHARPE, seed=9)
    assert first == again
    assert first.low < first.estimate < first.high
    assert 0.0 < first.p_value <= 1.0
    # A difference inside its own interval around zero is not significant.
    if first.low < 0.0 < first.high:
        assert first.p_value > 0.05


def test_stationary_records_everything_it_rests_on() -> None:
    book = curve(noise(80, 3))
    recorded = stationary(book, curve(noise(80, 4)), PairedStatistic.SHARPE).definition()
    assert recorded["method"] == "STATIONARY_CIRCULAR"
    assert recorded["mean_block"] == 5
    assert recorded["draws"] == 400
    assert recorded["seed"] == 7
    assert recorded["analytics"] == CONFIG.definition()
    assert set(recorded) >= {"estimate", "low", "high", "p_value", "level", "sessions"}


@pytest.mark.parametrize(
    "change, message",
    [
        ({"mean_block": 0}, "does not fit"),
        ({"mean_block": 500}, "does not fit"),
        ({"mean_block": 2.5}, "whole number"),
        ({"draws": 99}, "too few"),
        ({"level": 1.0}, "coverage"),
    ],
)
def test_stationary_parameters_out_of_range_are_refused(
    change: dict[str, object], message: str
) -> None:
    book = curve(noise(60, 5))
    with pytest.raises(ValueError, match=message):
        stationary(book, book, PairedStatistic.SHARPE, **change)  # type: ignore[arg-type]


def test_stationary_books_over_different_sessions_are_not_compared() -> None:
    book = curve(noise(30, 6))
    shifted = book.copy()
    shifted.index = shifted.index + 1
    with pytest.raises(ValueError, match="same sessions"):
        stationary(book, shifted, PairedStatistic.SHARPE)


def test_holm_adjusts_by_rank_and_keeps_the_order() -> None:
    # Sorted: a 0.01 x3 = 0.03; c 0.03 x2 = 0.06; b 0.04 x1 = 0.04, raised to 0.06.
    adjusted = holm_adjusted({"a": 0.01, "b": 0.04, "c": 0.03})
    assert adjusted == pytest.approx({"a": 0.03, "b": 0.06, "c": 0.06})
    assert list(adjusted) == ["a", "b", "c"]
    assert holm_adjusted({"x": 0.6, "y": 0.7}) == {"x": 1.0, "y": 1.0}
    assert holm_adjusted({"only": 0.02}) == {"only": 0.02}


@pytest.mark.parametrize("values", [{}, {"a": -0.1}, {"a": 1.5}, {"a": float("nan")}])
def test_holm_refuses_an_empty_family_or_a_value_that_is_not_a_probability(
    values: dict[str, float],
) -> None:
    with pytest.raises(ValueError):
        holm_adjusted(values)
