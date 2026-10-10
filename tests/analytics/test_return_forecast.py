"""Judging a forecast of a return two sessions away: the pairing, the errors, the losses."""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

from quant_backtester.analytics.return_forecast import (
    NO_FORECAST,
    TARGET_MISSING,
    TARGET_PENDING,
    evaluate_joint,
    evaluate_mean,
    joint_losses,
    out_of_sample_r2,
    pair_at_two_sessions,
    squared_errors,
)

SESSIONS = [date(2026, 9, day) for day in (1, 2, 3, 4, 7, 8, 9)]
"""Seven sessions with a weekend inside them."""

FLOOR = 1e-12


def series(values: dict[date, float]) -> pd.Series:
    """Return a series indexed by session."""
    return pd.Series(values, dtype="float64")


def test_a_decision_is_judged_on_the_return_after_its_fill_never_on_the_one_before() -> None:
    """Origin t, filled at the open of t+1, earns open(t+2) / open(t+1): the second step."""
    realised = series({session: 0.01 * rank for rank, session in enumerate(SESSIONS)})

    paired = pair_at_two_sessions(series({SESSIONS[1]: 0.003}), realised, SESSIONS)

    row = paired.pairs.loc[SESSIONS[1]]
    assert (row["entry"], row["exit"]) == (SESSIONS[2], SESSIONS[3])
    assert row["realised"] == pytest.approx(0.03)  # the return ending at t+2
    assert row["realised"] != realised[SESSIONS[2]]  # not the one ending at the fill


def test_a_weekend_is_not_a_step() -> None:
    realised = series({session: 0.01 * rank for rank, session in enumerate(SESSIONS)})

    paired = pair_at_two_sessions(series({SESSIONS[2]: 0.001}), realised, SESSIONS)

    # Decided on Thursday 3, filled on Friday 4, ending at Monday 7's open.
    row = paired.pairs.loc[SESSIONS[2]]
    assert (row["entry"], row["exit"]) == (date(2026, 9, 4), date(2026, 9, 7))


def test_an_origin_is_left_out_with_its_reason_and_only_from_the_metrics() -> None:
    realised = series({SESSIONS[2]: 0.01, SESSIONS[3]: float("nan"), SESSIONS[4]: 0.02})
    forecasts = series(
        {
            SESSIONS[0]: 0.001,  # exit on the 3rd: paired
            SESSIONS[1]: 0.001,  # exit on the 4th: its return is absent
            SESSIONS[2]: float("nan"),  # no usable forecast
            SESSIONS[5]: 0.001,  # exit after the last session: pending
        }
    )

    paired = pair_at_two_sessions(forecasts, realised, SESSIONS)

    assert list(paired.pairs.index) == [SESSIONS[0]]
    assert dict(paired.exclusions) == {NO_FORECAST: 1, TARGET_PENDING: 1, TARGET_MISSING: 1}
    assert paired.origins == 4 and paired.coverage == pytest.approx(0.25)


def test_the_variance_travels_with_the_mean_and_bad_sessions_are_refused() -> None:
    realised = series({SESSIONS[2]: 0.01})
    means, variances = series({SESSIONS[0]: 0.002}), series({SESSIONS[0]: 1e-4})

    paired = pair_at_two_sessions(means, realised, SESSIONS, forecast_variance=variances)

    assert paired.pairs.loc[SESSIONS[0], "forecast_variance"] == 1e-4
    assert math.isnan(
        pair_at_two_sessions(means, realised, SESSIONS).pairs.loc[SESSIONS[0], "forecast_variance"]
    )
    with pytest.raises(ValueError, match="not one of the sessions"):
        pair_at_two_sessions(series({date(2026, 9, 5): 0.0}), realised, SESSIONS)
    with pytest.raises(ValueError, match="strictly increasing"):
        pair_at_two_sessions(means, realised, SESSIONS[::-1])


def test_the_errors_of_a_mean_are_what_their_names_say() -> None:
    realised = [0.01, -0.02, 0.03, 0.0]
    forecast = [0.02, 0.01, 0.01, -0.01]

    measured = evaluate_mean(realised, forecast)

    errors = [f - r for f, r in zip(forecast, realised, strict=True)]
    assert measured.pairs == 4
    assert measured.mse == pytest.approx(sum(e * e for e in errors) / 4)
    assert measured.mae == pytest.approx(sum(abs(e) for e in errors) / 4)
    assert measured.bias == pytest.approx(sum(errors) / 4)
    assert measured.correlation == pytest.approx(float(np.corrcoef(forecast, realised)[0, 1]))


def test_the_sign_is_scored_on_the_returns_that_moved_with_its_denominators() -> None:
    realised = [0.01, -0.02, 0.03, 0.0, -0.01]
    forecast = [0.02, 0.01, 0.01, 0.01, 0.0]  # a forecast of exactly zero says "not up"

    measured = evaluate_mean(realised, forecast)

    assert (measured.realised_up, measured.realised_down, measured.realised_zero) == (2, 2, 1)
    assert measured.share_up == 0.5 and measured.always_up_accuracy == 0.5
    assert measured.sign_accuracy == pytest.approx(3 / 4)  # two rises and the last fall
    assert measured.balanced_accuracy == pytest.approx(0.5 * (2 / 2 + 1 / 2))
    assert measured.forecast_up == 4


def test_a_drifting_fund_makes_always_up_look_right() -> None:
    """A share of right signs above one half proves nothing by itself."""
    realised = [0.01, 0.02, 0.01, -0.01]

    always = evaluate_mean(realised, [0.001] * 4)

    assert always.sign_accuracy == always.always_up_accuracy == 0.75
    assert always.balanced_accuracy == 0.5  # every rise called, no fall called
    assert always.correlation is None  # a constant forecast correlates with nothing


def test_a_figure_the_sample_cannot_support_does_not_exist() -> None:
    empty = evaluate_mean([], [])
    one_class = evaluate_mean([0.01, 0.02], [0.001, -0.001])

    assert empty.pairs == 0 and empty.mse is None and empty.sign_accuracy is None
    assert one_class.balanced_accuracy is None  # no fall to call
    with pytest.raises(ValueError, match="aligned"):
        evaluate_mean([0.01], [0.01, 0.02])
    with pytest.raises(ValueError, match="not finite"):
        evaluate_mean([float("nan")], [0.01])


def test_the_out_of_sample_r2_is_against_a_frozen_reference() -> None:
    realised = [0.01, -0.02, 0.03]

    assert out_of_sample_r2(realised, realised, [0.0, 0.0, 0.0]) == 1.0
    assert out_of_sample_r2(realised, [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]) == 0.0
    worse = out_of_sample_r2(realised, [0.05, 0.05, 0.05], [0.0, 0.0, 0.0])
    assert worse is not None and worse < 0.0
    assert out_of_sample_r2([], [], []) is None
    assert out_of_sample_r2(realised, [0.0] * 3, realised) is None  # a reference with no error


def pairs_of(rows: list[tuple[float, float, float]]) -> pd.DataFrame:
    """Return pairs of ``(mean, variance, realised)`` on the first sessions."""
    means = series({SESSIONS[i]: mean for i, (mean, _, _) in enumerate(rows)})
    variances = series({SESSIONS[i]: variance for i, (_, variance, _) in enumerate(rows)})
    realised = series({SESSIONS[i + 2]: outcome for i, (_, _, outcome) in enumerate(rows)})
    return pair_at_two_sessions(means, realised, SESSIONS, forecast_variance=variances).pairs


def test_the_joint_loss_is_the_log_variance_plus_the_squared_error_over_it() -> None:
    rows = [(0.001, 1e-4, 0.011), (0.0, 4e-4, -0.02), (0.002, 1e-4, 0.002)]

    measured = evaluate_joint(pairs_of(rows), variance_floor=FLOOR)
    losses = joint_losses(pairs_of(rows), variance_floor=FLOOR)

    by_hand = [math.log(v) + (y - m) ** 2 / v for m, v, y in rows]
    assert list(losses) == pytest.approx(by_hand)
    assert measured.loss == pytest.approx(sum(by_hand) / 3)
    assert measured.mean_ratio == pytest.approx((1.0 + 1.0 + 0.0) / 3)
    assert measured.pairs == 3 and measured.floor_applications == 0
    assert measured.definition()["variance_floor"] == FLOOR


def test_the_error_is_taken_around_the_forecast_mean_not_around_zero() -> None:
    centred = evaluate_joint(pairs_of([(0.01, 1e-4, 0.01)]), variance_floor=FLOOR)
    around_zero = evaluate_joint(pairs_of([(0.0, 1e-4, 0.01)]), variance_floor=FLOOR)

    assert centred.mean_ratio == 0.0
    assert around_zero.mean_ratio == pytest.approx(1.0)


def test_the_floor_is_counted_and_a_negative_variance_is_refused() -> None:
    floored = evaluate_joint(pairs_of([(0.0, 0.0, 0.0), (0.0, 1e-4, 0.01)]), variance_floor=FLOOR)
    empty = evaluate_joint(pairs_of([]), variance_floor=FLOOR)

    assert floored.floor_applications == 1
    assert empty.pairs == 0 and empty.loss is None and empty.residual_autocorrelation is None
    broken = pairs_of([(0.0, 1e-4, 0.01)])
    broken["forecast_variance"] = -1e-4
    with pytest.raises(ValueError, match="finite and non-negative"):
        evaluate_joint(broken, variance_floor=FLOOR)


def test_the_squared_errors_can_be_those_of_another_forecast_on_the_same_pairs() -> None:
    frame = pairs_of([(0.001, 1e-4, 0.011), (0.0, 4e-4, -0.02)])
    zero = pd.Series(0.0, index=frame.index)

    assert list(squared_errors(frame)) == pytest.approx([1e-4, 4e-4])
    assert list(squared_errors(frame, zero)) == pytest.approx([0.011**2, 4e-4])
