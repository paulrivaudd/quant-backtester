"""The quality score: its scales, its blocks, and what it refuses to reward."""

from __future__ import annotations

import dataclasses
import math
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest
from scipy.stats import norm

from quant_backtester.analytics.config import AnalyticsConfig
from quant_backtester.analytics.quality import (
    BLOCKS,
    QUALITY_V1,
    Scale,
    deflated_sharpe_probability,
    expected_maximum_sharpe,
    quality_score,
    session_sharpe,
)

CONFIG = AnalyticsConfig(sessions_per_year=252, risk_free_rate=0.0)
SESSIONS = 505  # 504 returns: six sub-periods of 84


def curve(returns: np.ndarray, start: float = 100_000.0) -> pd.Series:
    """Return the equity curve of a sequence of session returns."""
    days = [date(2024, 1, 1) + timedelta(days=index) for index in range(len(returns) + 1)]
    values = start * np.concatenate([[1.0], np.cumprod(1.0 + returns)])
    return pd.Series(values, index=pd.Index(days, dtype="object"), dtype="float64")


def known(value: float | None) -> float:
    """Return a figure the test expects to exist."""
    assert value is not None
    return value


def market_returns(seed: int = 1) -> np.ndarray:
    """Return a market drawn once: about 8% a year for 16% of volatility."""
    rng = np.random.default_rng(seed)
    return rng.normal(0.08 / 252, 0.16 / math.sqrt(252), SESSIONS - 1)


def score(net: pd.Series, market: pd.Series, gross: pd.Series | None = None, trials: int = 1):
    """Return the version 1 score of a book against a market."""
    return quality_score(
        net,
        net if gross is None else gross,
        market,
        CONFIG,
        trials=trials,
        trial_sharpe_std=0.02 if trials > 1 else 0.0,
        rules=QUALITY_V1,
    )


def test_a_scale_is_linear_between_its_bounds_and_flat_outside() -> None:
    rising, falling = Scale(worst=-0.5, best=0.5), Scale(worst=0.30, best=0.0)

    assert [rising.score(value) for value in (-2.0, -0.5, 0.0, 0.25, 0.5, 9.0)] == [
        0.0,
        0.0,
        0.5,
        0.75,
        1.0,
        1.0,
    ]
    assert falling.score(0.0) == 1.0
    assert falling.score(0.15) == pytest.approx(0.5)
    assert falling.score(math.inf) == 0.0
    # A measure the sample cannot support scores nothing.
    assert rising.score(None) == rising.score(math.nan) == 0.0
    with pytest.raises(ValueError, match="two different bounds"):
        Scale(worst=1.0, best=1.0)


def test_version_one_weighs_five_blocks_to_one() -> None:
    assert tuple(QUALITY_V1.weights) == BLOCKS
    assert math.fsum(QUALITY_V1.weights.values()) == pytest.approx(1.0)
    assert QUALITY_V1.version == "v1"
    assert QUALITY_V1.definition()["weights"] == dict(QUALITY_V1.weights)
    with pytest.raises(ValueError, match="sum to one"):
        dataclasses.replace(QUALITY_V1, weights=dict.fromkeys(BLOCKS, 0.3))
    with pytest.raises(ValueError, match="exactly"):
        dataclasses.replace(QUALITY_V1, weights={"market": 1.0})


def test_a_book_that_adds_a_steady_gain_to_the_market_scores_high() -> None:
    returns = market_returns()
    wobble = np.random.default_rng(5).normal(0.0, 0.001, len(returns))
    market, book = curve(returns), curve(returns + 0.0004 + wobble)

    result = score(book, market)

    assert known(result.score) > 0.85
    assert result.percent == pytest.approx(100.0 * known(result.score))
    assert result.blocks["market"] == 1.0  # ten points of alpha, a large information ratio
    assert result.blocks["implementation"] == 1.0  # no cost between gross and net
    assert result.measures["subperiod_share"] == 1.0
    assert result.diagnostics == ()
    assert result.version == "v1"


def test_a_book_that_loses_steadily_to_the_market_scores_zero_whatever_else_it_does() -> None:
    returns = market_returns()
    wobble = np.random.default_rng(5).normal(0.0, 0.001, len(returns))
    market, book = curve(returns), curve(returns - 0.0004 + wobble)

    result = score(book, market)

    # Cheap to trade, and still a zero: a geometric mean does not compensate.
    assert result.blocks["implementation"] == 1.0
    assert result.blocks["market"] == 0.0
    assert result.score == 0.0


def test_the_score_is_the_weighted_geometric_mean_of_its_blocks() -> None:
    returns = market_returns()
    other = np.random.default_rng(9).normal(0.10 / 252, 0.10 / math.sqrt(252), len(returns))
    result = score(curve(0.5 * returns + 0.5 * other), curve(returns))

    expected = math.prod(result.blocks[name] ** QUALITY_V1.weights[name] for name in BLOCKS)

    assert all(0.0 <= value <= 1.0 for value in result.blocks.values())
    assert result.score == pytest.approx(expected)


def test_a_sample_under_a_year_is_not_scored() -> None:
    returns = market_returns()[:200]

    result = score(curve(returns + 0.001), curve(returns))

    assert result.score is None and result.percent is None
    assert result.diagnostics == ("sample_too_short",)


def test_costs_lower_the_implementation_and_the_stress_measures() -> None:
    returns = market_returns()
    gross_returns = returns + 0.0004 + np.random.default_rng(5).normal(0.0, 0.001, len(returns))
    gross = curve(gross_returns)
    # The same trades, having paid one basis point of equity every session.
    net = curve(gross_returns - 0.0001)

    free, charged = score(gross, curve(returns)), score(net, curve(returns), gross=gross)

    gross_gain = gross.iloc[-1] / gross.iloc[0] - 1.0
    net_gain = net.iloc[-1] / net.iloc[0] - 1.0
    assert charged.measures["cost_drag"] == pytest.approx((gross_gain - net_gain) / gross_gain)
    assert charged.blocks["implementation"] < free.blocks["implementation"] == 1.0
    assert free.measures["stress_retention"] == 1.0
    assert known(charged.measures["stress_retention"]) < 1.0
    assert known(charged.score) < known(free.score)


def test_a_drawdown_is_judged_against_the_markets_own() -> None:
    returns = market_returns()
    market = curve(returns)

    half, double = score(curve(0.5 * returns), market), score(curve(2.0 * returns), market)

    assert known(half.measures["drawdown_ratio"]) < 0.6
    assert half.blocks["risk"] > 0.9
    assert known(double.measures["drawdown_ratio"]) > 1.5
    assert double.blocks["risk"] == 0.0


def test_more_trials_ask_more_of_the_same_sharpe_ratio() -> None:
    book = curve(market_returns(3) + 0.0003)

    alone = deflated_sharpe_probability(book, CONFIG, trials=1, trial_sharpe_std=0.0)
    among = deflated_sharpe_probability(book, CONFIG, trials=200, trial_sharpe_std=0.02)

    assert known(among) < known(alone)
    assert expected_maximum_sharpe(1, 0.02) == 0.0
    assert expected_maximum_sharpe(200, 0.02) > expected_maximum_sharpe(10, 0.02) > 0.0
    assert expected_maximum_sharpe(200, 0.0) == 0.0


def test_the_deflated_sharpe_of_normal_returns_is_the_textbook_formula() -> None:
    returns = np.random.default_rng(2).normal(0.0005, 0.01, 400)
    book = curve(returns)
    observed = session_sharpe(book, CONFIG)
    assert observed is not None
    centred = returns - returns.mean()
    skewness = float((centred**3).mean() / (centred**2).mean() ** 1.5)
    tails = float((centred**4).mean() / (centred**2).mean() ** 2)

    probability = deflated_sharpe_probability(book, CONFIG, trials=1, trial_sharpe_std=0.0)

    variance = 1.0 - skewness * observed + (tails - 1.0) / 4.0 * observed**2
    expected = norm.cdf(observed * math.sqrt(399) / math.sqrt(variance))
    assert observed == pytest.approx(returns.mean() / returns.std(ddof=1))
    assert probability == pytest.approx(float(expected))


def test_a_flat_book_has_no_sharpe_and_says_so() -> None:
    market = curve(market_returns())
    flat = curve(np.zeros(SESSIONS - 1))

    result = score(flat, market)

    assert session_sharpe(flat, CONFIG) is None
    assert result.measures["deflated_sharpe_probability"] is None
    assert "sharpe_undefined" in result.diagnostics
    assert result.blocks["significance"] == 0.0
    assert result.score == 0.0


def test_what_comes_after_a_session_does_not_change_the_score_up_to_it() -> None:
    """The look-ahead guard: the score of a sample ignores what follows it."""
    returns = market_returns()
    book_returns = returns * 0.7 + 0.0002
    longer = np.concatenate([returns, np.full(50, -0.02)])
    longer_book = np.concatenate([book_returns, np.full(50, 0.03)])

    first = score(curve(book_returns), curve(returns))
    again = score(curve(longer_book).iloc[:SESSIONS], curve(longer).iloc[:SESSIONS])

    assert again == first


def test_curves_over_different_sessions_are_refused() -> None:
    returns = market_returns()
    book, market = curve(returns + 0.0001), curve(returns)

    with pytest.raises(ValueError, match="same sessions"):
        quality_score(
            book,
            book.iloc[:-1],
            market,
            CONFIG,
            trials=1,
            trial_sharpe_std=0.0,
            rules=QUALITY_V1,
        )
