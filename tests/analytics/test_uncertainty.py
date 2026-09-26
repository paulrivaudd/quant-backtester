"""The paired block bootstrap: shared blocks, a declared seed, a difference and its spread."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_backtester.analytics.uncertainty import (
    PairedStatistic,
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


SETTINGS = {"block": 5, "draws": 400, "seed": 7, "level": 0.9, "sessions_per_year": 255}


@pytest.mark.parametrize("statistic", list(PairedStatistic))
def test_two_identical_books_differ_by_nothing_in_every_draw(statistic: PairedStatistic) -> None:
    """C02 acceptance: the same curve twice gives a zero difference, estimate and interval."""
    book = curve(noise(250, 1))

    result = paired_block_bootstrap(book, book.copy(), statistic=statistic, **SETTINGS)

    assert (result.estimate, result.low, result.high) == (0.0, 0.0, 0.0)


def test_the_same_seed_gives_the_same_interval_and_another_seed_another() -> None:
    strategy, control = curve(noise(250, 1)), curve(noise(250, 2))

    first = paired_block_bootstrap(strategy, control, statistic=PairedStatistic.SHARPE, **SETTINGS)
    again = paired_block_bootstrap(strategy, control, statistic=PairedStatistic.SHARPE, **SETTINGS)
    other = paired_block_bootstrap(
        strategy, control, statistic=PairedStatistic.SHARPE, **(SETTINGS | {"seed": 8})
    )

    assert first == again
    assert (first.low, first.high) != (other.low, other.high)


def test_a_constant_edge_is_measured_exactly_and_with_no_spread() -> None:
    """Every session 0.1% better: resampled in pairs, the edge never moves."""
    base = noise(250, 3)
    strategy = curve([value + 0.001 for value in base])
    control = curve(base)

    result = paired_block_bootstrap(
        strategy, control, statistic=PairedStatistic.MEAN_RETURN, **SETTINGS
    )

    assert result.estimate == pytest.approx(0.001 * 255)
    assert result.low == pytest.approx(0.001 * 255)
    assert result.high == pytest.approx(0.001 * 255)


def test_pairing_keeps_what_the_books_share() -> None:
    """Correlated books: the paired interval of the difference is much narrower than apart."""
    common = noise(250, 4, scale=0.02)
    own = noise(250, 5, scale=0.001)
    strategy = curve([c + o for c, o in zip(common, own, strict=True)])
    control = curve(common)

    paired = paired_block_bootstrap(
        strategy, control, statistic=PairedStatistic.MEAN_RETURN, **SETTINGS
    )

    assert paired.high - paired.low < 0.1


def test_everything_the_result_depends_on_is_recorded() -> None:
    result = paired_block_bootstrap(
        curve(noise(50, 1)), curve(noise(50, 2)), statistic=PairedStatistic.SHARPE, **SETTINGS
    )

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
        paired_block_bootstrap(
            book,
            book,
            statistic=PairedStatistic.SHARPE,
            **(SETTINGS | change),  # type: ignore[arg-type]
        )


def test_books_over_different_sessions_are_not_compared() -> None:
    book = curve(noise(50, 1))

    with pytest.raises(ValueError, match="same sessions"):
        paired_block_bootstrap(
            book,
            book.iloc[1:],
            statistic=PairedStatistic.SHARPE,
            **SETTINGS,  # type: ignore[arg-type]
        )
