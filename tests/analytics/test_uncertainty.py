"""The paired block bootstrap: shared blocks, a declared seed, a difference and its spread."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from quant_backtester.analytics.config import AnalyticsConfig
from quant_backtester.analytics.performance import PerformanceStats
from quant_backtester.analytics.uncertainty import (
    PairedStatistic,
    UndefinedStatistic,
    paired_block_bootstrap,
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
