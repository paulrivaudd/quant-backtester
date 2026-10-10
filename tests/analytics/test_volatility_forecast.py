"""Judging a variance forecast after the fact: the pairing, QLIKE and its floor."""

from __future__ import annotations

import math
from datetime import date

import pandas as pd
import pytest

from quant_backtester.analytics.volatility_forecast import (
    compare_forecasts,
    evaluate_forecasts,
    pair_forecasts,
    qlike_loss,
)

SESSIONS = [date(2026, 9, day) for day in (1, 2, 3, 4, 7, 8)]
"""Six sessions with a weekend inside: the target of Friday is Monday."""

FLOOR = 1e-12


def series(values: dict[date, float]) -> pd.Series:
    """Return a series indexed by session."""
    return pd.Series(values, dtype="float64")


def test_a_forecast_is_paired_with_the_return_of_the_next_session() -> None:
    forecasts = series({SESSIONS[0]: 1e-4, SESSIONS[3]: 4e-4})
    returns = series({SESSIONS[1]: 0.01, SESSIONS[4]: -0.02})

    pairs = pair_forecasts(forecasts, returns, SESSIONS)

    assert list(pairs.index) == [SESSIONS[0], SESSIONS[3]]
    assert list(pairs["target"]) == [SESSIONS[1], SESSIONS[4]]  # Friday's target is Monday
    assert list(pairs["realised_return"]) == [0.01, -0.02]
    assert list(pairs["forecast_variance"]) == [1e-4, 4e-4]


def test_a_forecast_is_never_paired_with_its_own_session_or_a_later_return() -> None:
    """The return of the origin's own session was already known: it is not a target."""
    forecasts = series({SESSIONS[1]: 1e-4})
    returns = series({SESSIONS[1]: 0.05, SESSIONS[3]: 0.07})

    assert pair_forecasts(forecasts, returns, SESSIONS).empty


def test_a_pair_needs_a_forecast_a_target_and_a_return() -> None:
    forecasts = series({SESSIONS[0]: float("nan"), SESSIONS[1]: 1e-4, SESSIONS[5]: 1e-4})
    returns = series({SESSIONS[1]: 0.01, SESSIONS[2]: float("nan")})

    # No forecast on the 1st, no usable return after the 2nd, no session after the 8th.
    assert pair_forecasts(forecasts, returns, SESSIONS).empty


def test_an_origin_outside_the_sessions_and_unordered_sessions_are_refused() -> None:
    returns = series({SESSIONS[1]: 0.01})

    with pytest.raises(ValueError, match="not one of the sessions"):
        pair_forecasts(series({date(2026, 9, 5): 1e-4}), returns, SESSIONS)
    with pytest.raises(ValueError, match="strictly increasing"):
        pair_forecasts(series({SESSIONS[0]: 1e-4}), returns, SESSIONS[::-1])


def test_qlike_is_the_log_of_the_forecast_plus_the_ratio() -> None:
    assert qlike_loss(4e-4, 0.02, variance_floor=FLOOR) == pytest.approx(math.log(4e-4) + 1.0)
    # A forecast that is too low costs more than one too high by the same factor.
    low = qlike_loss(1e-4, 0.02, variance_floor=FLOOR)
    high = qlike_loss(16e-4, 0.02, variance_floor=FLOOR)
    assert low > high > qlike_loss(4e-4, 0.02, variance_floor=FLOOR)
    with pytest.raises(ValueError, match="variance_floor"):
        qlike_loss(1e-4, 0.02, variance_floor=0.0)


def pairs_of(rows: list[tuple[float, float]]) -> pd.DataFrame:
    """Return pairs of ``(forecast_variance, realised_return)`` on the first sessions."""
    forecasts = series({SESSIONS[i]: variance for i, (variance, _) in enumerate(rows)})
    returns = series({SESSIONS[i + 1]: outcome for i, (_, outcome) in enumerate(rows)})
    return pair_forecasts(forecasts, returns, SESSIONS)


def test_the_losses_are_means_over_the_pairs() -> None:
    rows = [(1e-4, 0.01), (4e-4, 0.01), (1e-4, -0.03)]

    measured = evaluate_forecasts(pairs_of(rows), variance_floor=FLOOR)

    ratios = [outcome**2 / variance for variance, outcome in rows]
    assert measured.pairs == 3
    assert (measured.first_origin, measured.last_origin) == (SESSIONS[0], SESSIONS[2])
    assert measured.mean_ratio == pytest.approx(sum(ratios) / 3)
    assert measured.qlike == pytest.approx(
        sum(math.log(variance) + ratio for (variance, _), ratio in zip(rows, ratios, strict=True))
        / 3
    )
    assert measured.variance_mse == pytest.approx(
        sum((outcome**2 - variance) ** 2 for variance, outcome in rows) / 3
    )
    assert measured.residual_beyond_two == pytest.approx(1 / 3)  # 0.03 / 0.01 = 3
    assert measured.floor_applications == 0
    assert measured.definition()["first_origin"] == "2026-09-01"


def test_the_floor_is_the_metrics_own_and_is_counted() -> None:
    """A forecast of zero has no logarithm; flooring it is said, not hidden."""
    measured = evaluate_forecasts(pairs_of([(0.0, 0.0), (1e-4, 0.01)]), variance_floor=FLOOR)

    assert measured.floor_applications == 1
    assert measured.qlike == pytest.approx((math.log(FLOOR) + math.log(1e-4) + 1.0) / 2)
    assert measured.variance_floor == FLOOR


def test_no_pair_gives_no_figure_rather_than_a_zero() -> None:
    measured = evaluate_forecasts(pairs_of([]), variance_floor=FLOOR)

    assert measured.pairs == 0
    assert measured.qlike is None and measured.mean_ratio is None
    assert measured.first_origin is None
    assert measured.residual_std is None


def test_a_negative_or_non_finite_forecast_is_refused() -> None:
    for bad in (-1e-4, float("inf")):
        frame = pairs_of([(1e-4, 0.01)])
        frame["forecast_variance"] = bad
        with pytest.raises(ValueError, match="finite and non-negative"):
            evaluate_forecasts(frame, variance_floor=FLOOR)


def test_a_comparison_on_shared_origins_is_on_exactly_those_origins() -> None:
    wide = pairs_of([(1e-4, 0.01), (1e-4, 0.02), (1e-4, 0.03)])
    narrow = wide.iloc[:2]
    shared = list(narrow.index)

    own = compare_forecasts({"wide": wide, "narrow": narrow}, variance_floor=FLOOR)
    same = compare_forecasts({"wide": wide, "narrow": narrow}, variance_floor=FLOOR, origins=shared)

    assert (own["wide"].pairs, own["narrow"].pairs) == (3, 2)
    assert (same["wide"].pairs, same["narrow"].pairs) == (2, 2)
    assert same["wide"].qlike == same["narrow"].qlike
    with pytest.raises(ValueError, match="no pair for 1 of the shared origins"):
        compare_forecasts({"narrow": narrow}, variance_floor=FLOOR, origins=list(wide.index))
