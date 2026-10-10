"""How good a forecast of a return was, when the return is two sessions away.

A decision taken at the evening of session ``t`` is filled at the open of
``t + 1``; the first return it can earn runs from that open to the open of
``t + 2``. A forecast made at ``t`` *for that return* is paired here with it:
the origin ``t``, the entry ``t + 1``, the exit ``t + 2``. Pairing it with the
return that ends at ``t + 1`` - the next one in the series - would judge the
forecast on a return that was over when the order was filled.

Two things are measured, and kept apart:

- the **mean**: squared and absolute error, bias, correlation and the sign,
  the last with its denominators said out loud, since a share of right signs
  above one half can be nothing more than the drift of the fund;
- the **mean and the variance together**: the quasi-Gaussian loss ``log(v) +
  e^2 / v`` of the error ``e`` around the forecast mean. With a common mean it
  compares variances, like QLIKE; with different means it is a joint loss and
  is named so.

Everything here is read after the fact. A forecast is never recomputed with
its target, an origin whose target is not known yet is counted as pending and
left out of the metrics only, and a figure the sample cannot support is
``None``, never a zero.

This module reads no market data: it is handed forecasts and realised returns.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from itertools import pairwise
from types import MappingProxyType

import numpy as np
import pandas as pd
from scipy.stats import kurtosis, skew

from quant_backtester.numbers import require_finite_positive

HORIZON_PAIR_COLUMNS = ("entry", "exit", "forecast_mean", "forecast_variance", "realised")
"""Columns of a frame of pairs, indexed by the origin session."""

NO_FORECAST = "no_forecast"
"""The origin has no usable forecast."""

TARGET_PENDING = "target_pending"
"""The exit session is after the last session: the target is not known yet."""

TARGET_MISSING = "target_missing"
"""The exit session exists and its realised return does not."""


@dataclass(frozen=True, slots=True)
class PairedForecasts:
    """Forecasts paired with the return two sessions after their origin, and what was left out.

    Attributes
    ----------
    pairs : pd.DataFrame
        Indexed by origin, with :data:`HORIZON_PAIR_COLUMNS`.
    exclusions : Mapping[str, int]
        How many origins were left out, by reason: :data:`NO_FORECAST`,
        :data:`TARGET_PENDING`, :data:`TARGET_MISSING`.
    origins : int
        Origins examined.
    """

    pairs: pd.DataFrame
    exclusions: Mapping[str, int]
    origins: int

    def __post_init__(self) -> None:
        """Freeze the count of exclusions."""
        object.__setattr__(self, "exclusions", MappingProxyType(dict(self.exclusions)))

    @property
    def coverage(self) -> float | None:
        """Return the share of the origins that made a pair; ``None`` without an origin."""
        return None if self.origins == 0 else len(self.pairs) / self.origins


def pair_at_two_sessions(
    forecast_mean: pd.Series,  # type: ignore[type-arg]
    realised_by_exit: pd.Series,  # type: ignore[type-arg]
    sessions: Sequence[date],
    *,
    forecast_variance: pd.Series | None = None,  # type: ignore[type-arg]
) -> PairedForecasts:
    """Pair each forecast with the return from the open after its origin to the next one.

    Parameters
    ----------
    forecast_mean : pd.Series
        The forecast return, indexed by the session it was made at the evening
        of. A missing value is an origin without a usable forecast.
    realised_by_exit : pd.Series
        The realised return of each open-to-open interval, indexed by the
        session it **ends** at: the value at ``s`` is the return from the open
        of the session before ``s`` to the open of ``s``.
    sessions : Sequence[date]
        The venue's sessions in order, covering every origin and the two
        sessions after it when they exist. What says which session follows
        which: a weekend or a holiday is not a step.
    forecast_variance : pd.Series | None
        The forecast variance of that return, indexed like the mean.

    Returns
    -------
    PairedForecasts
        One pair per origin that has a forecast and a known target, with the
        entry and exit sessions; the origins left out counted by reason.

    Raises
    ------
    ValueError
        If the sessions are not strictly increasing or an origin is not one of
        them.
    """
    ordered = list(sessions)
    if any(later <= earlier for earlier, later in pairwise(ordered)):
        raise ValueError("sessions must be strictly increasing")
    place = {day: rank for rank, day in enumerate(ordered)}
    realised = realised_by_exit.to_dict()
    variances = {} if forecast_variance is None else forecast_variance.to_dict()
    rows: dict[date, dict[str, object]] = {}
    excluded = {NO_FORECAST: 0, TARGET_PENDING: 0, TARGET_MISSING: 0}
    for origin, mean in forecast_mean.items():
        if origin not in place:
            raise ValueError(f"a forecast is dated {origin}, which is not one of the sessions")
        assert isinstance(origin, date)
        if pd.isna(mean):
            excluded[NO_FORECAST] += 1
            continue
        rank = place[origin]
        if rank + 2 >= len(ordered):
            excluded[TARGET_PENDING] += 1
            continue
        entry, out = ordered[rank + 1], ordered[rank + 2]
        outcome = realised.get(out)
        if outcome is None or not math.isfinite(float(outcome)):
            excluded[TARGET_MISSING] += 1
            continue
        variance = variances.get(origin)
        rows[origin] = {
            "entry": entry,
            "exit": out,
            "forecast_mean": float(mean),
            "forecast_variance": float("nan") if variance is None else float(variance),
            "realised": float(outcome),
        }
    frame = pd.DataFrame.from_dict(rows, orient="index", columns=list(HORIZON_PAIR_COLUMNS))
    return PairedForecasts(frame.rename_axis("origin"), excluded, len(forecast_mean))


@dataclass(frozen=True, slots=True)
class MeanEvaluation:
    """The errors of one series of forecast means over its pairs.

    Attributes
    ----------
    pairs : int
        Pairs measured.
    mse, mae : float | None
        Mean squared and mean absolute error of the forecast.
    bias : float | None
        Mean of forecast less realisation.
    correlation : float | None
        Pearson correlation of forecast and realisation; ``None`` when either
        does not vary.
    realised_up, realised_down, realised_zero : int
        Realisations strictly positive, strictly negative and exactly zero.
    share_up : float | None
        ``realised_up`` over the realisations that are not zero.
    sign_accuracy : float | None
        Share of the non-zero realisations whose sign the forecast had, a
        forecast counting as "up" when strictly positive and as "down"
        otherwise - zero included.
    always_up_accuracy : float | None
        What always saying "up" would have scored: ``share_up``.
    balanced_accuracy : float | None
        Mean of the share of rises called and of the share of falls called;
        ``None`` when one of the two classes is empty.
    forecast_up : int
        Forecasts strictly positive.
    """

    pairs: int
    mse: float | None
    mae: float | None
    bias: float | None
    correlation: float | None
    realised_up: int
    realised_down: int
    realised_zero: int
    share_up: float | None
    sign_accuracy: float | None
    always_up_accuracy: float | None
    balanced_accuracy: float | None
    forecast_up: int

    def definition(self) -> dict[str, object]:
        """Return the evaluation as it is recorded."""
        return {name: getattr(self, name) for name in self.__slots__}


def evaluate_mean(realised: Sequence[float], forecast: Sequence[float]) -> MeanEvaluation:
    """Measure a series of forecast means against the realisations they were about.

    Parameters
    ----------
    realised : Sequence[float]
        The realised returns, pair by pair.
    forecast : Sequence[float]
        The forecasts, aligned with them.

    Returns
    -------
    MeanEvaluation
        Every figure ``None`` on no pair; the sign figures computed on the
        realisations that are not exactly zero, whose number is given.

    Raises
    ------
    ValueError
        If the two do not hold the same number of finite values.
    """
    actual = np.asarray(realised, dtype="float64")
    said = np.asarray(forecast, dtype="float64")
    if actual.shape != said.shape or actual.ndim != 1:
        raise ValueError("realisations and forecasts must be two aligned series")
    if not (np.isfinite(actual).all() and np.isfinite(said).all()):
        raise ValueError("a pair holds a value that is not finite")
    count = len(actual)
    up, down = actual > 0.0, actual < 0.0
    rises, falls = int(up.sum()), int(down.sum())
    called_up = said > 0.0
    if count == 0:
        return MeanEvaluation(0, None, None, None, None, 0, 0, 0, None, None, None, None, 0)
    error = said - actual
    varies = count > 1 and float(np.std(actual)) > 0.0 and float(np.std(said)) > 0.0
    decided = rises + falls
    right = int((called_up & up).sum()) + int((~called_up & down).sum())
    return MeanEvaluation(
        pairs=count,
        mse=float(np.mean(error**2)),
        mae=float(np.mean(np.abs(error))),
        bias=float(np.mean(error)),
        correlation=float(np.corrcoef(said, actual)[0, 1]) if varies else None,
        realised_up=rises,
        realised_down=falls,
        realised_zero=count - decided,
        share_up=rises / decided if decided else None,
        sign_accuracy=right / decided if decided else None,
        always_up_accuracy=rises / decided if decided else None,
        balanced_accuracy=(
            0.5 * (int((called_up & up).sum()) / rises + int((~called_up & down).sum()) / falls)
            if rises and falls
            else None
        ),
        forecast_up=int(called_up.sum()),
    )


def out_of_sample_r2(
    realised: Sequence[float], forecast: Sequence[float], reference: Sequence[float]
) -> float | None:
    """Return ``1 - sum((y - f)^2) / sum((y - ref)^2)``, or ``None`` when it does not exist.

    Parameters
    ----------
    realised, forecast : Sequence[float]
        Realisations and the forecasts judged.
    reference : Sequence[float]
        The naive forecast of each pair, frozen when the forecast was made -
        the mean of a training block, never a mean taken over the test.

    Returns
    -------
    float | None
        Positive when the forecast beats the reference in squared error.
        ``None`` on no pair or a reference that makes no error at all.
    """
    actual = np.asarray(realised, dtype="float64")
    if len(actual) == 0:
        return None
    denominator = float(np.sum((actual - np.asarray(reference, dtype="float64")) ** 2))
    if denominator <= 0.0:
        return None
    return 1.0 - float(np.sum((actual - np.asarray(forecast, dtype="float64")) ** 2)) / denominator


def joint_losses(pairs: pd.DataFrame, *, variance_floor: float) -> pd.Series:  # type: ignore[type-arg]
    """Return ``log(v) + e^2 / v`` of each pair, indexed by origin.

    Parameters
    ----------
    pairs : pd.DataFrame
        Pairs holding a forecast mean, a forecast variance and a realisation.
    variance_floor : float
        Smallest variance the loss is evaluated at: a floor of the metric,
        not of any allocation.

    Raises
    ------
    ValueError
        If a variance is negative or not finite: that is a broken forecast,
        which the floor is not there to repair.
    """
    require_finite_positive(variance_floor, "variance_floor")
    variance = pairs["forecast_variance"].to_numpy(dtype="float64")
    if not np.isfinite(variance).all() or bool((variance < 0.0).any()):
        raise ValueError("a forecast variance must be finite and non-negative")
    error = (pairs["realised"] - pairs["forecast_mean"]).to_numpy(dtype="float64")
    floored = np.maximum(variance, variance_floor)
    return pd.Series(np.log(floored) + error**2 / floored, index=pairs.index, dtype="float64")


def squared_errors(pairs: pd.DataFrame, forecast: pd.Series | None = None) -> pd.Series:  # type: ignore[type-arg]
    """Return the squared error of each pair, of its own mean or of another forecast."""
    said = pairs["forecast_mean"] if forecast is None else forecast.reindex(pairs.index)
    error = (pairs["realised"] - said).to_numpy(dtype="float64")
    return pd.Series(error**2, index=pairs.index, dtype="float64")


@dataclass(frozen=True, slots=True)
class JointEvaluation:
    """The joint loss of a forecast mean and variance, and what its errors look like.

    Attributes
    ----------
    pairs : int
        Pairs measured.
    loss : float | None
        Mean of ``log(v) + e^2 / v``; lower is better.
    mean_ratio : float | None
        Mean of ``e^2 / v``: one for a variance right on average.
    floor_applications : int
        Pairs whose variance was raised to the metric's floor.
    residual_std, residual_skew, residual_kurtosis : float | None
        Of the standardised errors ``e / sqrt(v)``; a kurtosis of 3 is normal.
    residual_autocorrelation : float | None
        Lag-one autocorrelation of the standardised errors.
    squared_autocorrelation : float | None
        Lag-one autocorrelation of their squares: what a variance model
        should have removed.
    variance_floor : float
        The floor the loss was evaluated with.
    """

    pairs: int
    loss: float | None
    mean_ratio: float | None
    floor_applications: int
    residual_std: float | None
    residual_skew: float | None
    residual_kurtosis: float | None
    residual_autocorrelation: float | None
    squared_autocorrelation: float | None
    variance_floor: float

    def definition(self) -> dict[str, object]:
        """Return the evaluation as it is recorded."""
        return {name: getattr(self, name) for name in self.__slots__}


def _lag_one(values: np.ndarray) -> float | None:
    """Return the lag-one autocorrelation of a series, ``None`` when it does not vary."""
    if len(values) < 3 or float(np.std(values)) == 0.0:
        return None
    return float(np.corrcoef(values[:-1], values[1:])[0, 1])


def evaluate_joint(pairs: pd.DataFrame, *, variance_floor: float) -> JointEvaluation:
    """Measure the joint loss of a frame of pairs holding a mean and a variance.

    Parameters
    ----------
    pairs : pd.DataFrame
        What :func:`pair_at_two_sessions` returns, in the order of the origins.
    variance_floor : float
        The floor of the metric, counted when it applies.

    Returns
    -------
    JointEvaluation
        Means over the pairs; every figure ``None`` on an empty frame. The
        square of one daily error is a very noisy measure of a variance: the
        loss is read as a mean over many pairs.
    """
    require_finite_positive(variance_floor, "variance_floor")
    count = len(pairs)
    if count == 0:
        return JointEvaluation(0, None, None, 0, None, None, None, None, None, variance_floor)
    variance = pairs["forecast_variance"].to_numpy(dtype="float64")
    losses = joint_losses(pairs, variance_floor=variance_floor).to_numpy(dtype="float64")
    floored = np.maximum(variance, variance_floor)
    error = (pairs["realised"] - pairs["forecast_mean"]).to_numpy(dtype="float64")
    standardised = error / np.sqrt(floored)
    several = count > 2
    return JointEvaluation(
        pairs=count,
        loss=float(np.mean(losses)),
        mean_ratio=float(np.mean(error**2 / floored)),
        floor_applications=int((variance < variance_floor).sum()),
        residual_std=float(np.std(standardised, ddof=1)) if count > 1 else None,
        residual_skew=float(skew(standardised)) if several else None,
        residual_kurtosis=float(kurtosis(standardised, fisher=False)) if several else None,
        residual_autocorrelation=_lag_one(standardised),
        squared_autocorrelation=_lag_one(standardised**2),
        variance_floor=variance_floor,
    )
