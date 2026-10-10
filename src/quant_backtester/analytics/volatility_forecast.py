"""How good a variance forecast was, measured after the fact.

A forecast made at the close of session ``t`` is about the return of session
``t + 1``. This module pairs the two - the *origin* a forecast was made at and
the *target* it was about - and measures the losses on the pairs. It is an
ex-post reading: nothing here is ever fed back into a decision, and no
forecast is recomputed with the information of its target.

The main loss is QLIKE, ``log(q) + r^2 / q`` with ``q`` the forecast variance
and ``r`` the realised return of the target session: lower is better, and it
punishes a forecast that is too low more than one that is too high. The square
of one daily return is a very noisy proxy of a variance, so a loss is read as
a mean over many pairs, never on a day.

Two things this does not say. QLIKE does not measure the profit of an
allocation built on the forecast: orders are filled at the open, not at the
close the forecast starts from. And the floor applied to a forecast here is a
floor of the *metric* - a variance of zero has no logarithm - counted and
reported; it is not the volatility floor of an allocation, which would flatter
the forecast being judged.

The signal layer does not depend on this module, and this module reads no
market data: it is handed forecasts and realised returns.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from itertools import pairwise

import numpy as np
import pandas as pd
from scipy.stats import kurtosis, skew

from quant_backtester.numbers import require_finite_positive

PAIR_COLUMNS = ("target", "forecast_variance", "realised_return")
"""Columns of a frame of pairs, indexed by the origin session."""


def pair_forecasts(
    forecast_variance: pd.Series,  # type: ignore[type-arg]
    session_returns: pd.Series,  # type: ignore[type-arg]
    sessions: Sequence[date],
) -> pd.DataFrame:
    """Pair each forecast with the realised return of the session that follows its origin.

    Parameters
    ----------
    forecast_variance : pd.Series
        Forecast variance of the next daily return, in decimal units, indexed
        by the session it was made at the close of. A missing value is a
        session without a forecast and makes no pair.
    session_returns : pd.Series
        Realised daily log return of each session - close of the session
        before to its own close - indexed by the session it ends on. A session
        whose return could not be computed over exactly one session is absent.
    sessions : Sequence[date]
        The venue's sessions in order, covering every origin: what says which
        session follows which.

    Returns
    -------
    pd.DataFrame
        Indexed by origin, with :data:`PAIR_COLUMNS`. An origin whose target
        is past the last session, or has no realised return, is left out: a
        return over two sessions is not what the forecast was about.

    Raises
    ------
    ValueError
        If the sessions are not strictly increasing, or an origin is not one
        of them.
    """
    ordered = list(sessions)
    if any(later <= earlier for earlier, later in pairwise(ordered)):
        raise ValueError("sessions must be strictly increasing")
    following = dict(pairwise(ordered))
    known = set(ordered)
    realised = session_returns.to_dict()
    rows: dict[date, dict[str, object]] = {}
    for origin, variance in forecast_variance.items():
        if origin not in known:
            raise ValueError(f"a forecast is dated {origin}, which is not one of the sessions")
        assert isinstance(origin, date)
        target = following.get(origin)
        if target is None or pd.isna(variance) or target not in realised:
            continue
        outcome = float(realised[target])
        if not math.isfinite(outcome):
            continue
        rows[origin] = {
            "target": target,
            "forecast_variance": float(variance),
            "realised_return": outcome,
        }
    frame = pd.DataFrame.from_dict(rows, orient="index", columns=list(PAIR_COLUMNS))
    return frame.rename_axis("origin")


def qlike_loss(forecast_variance: float, realised_return: float, *, variance_floor: float) -> float:
    """Return ``log(q) + r^2 / q`` with ``q = max(forecast_variance, variance_floor)``.

    Parameters
    ----------
    forecast_variance : float
        The forecast, in decimal units.
    realised_return : float
        The daily return it was about, as a fraction.
    variance_floor : float
        Smallest variance the metric is evaluated at, strictly positive.
    """
    require_finite_positive(variance_floor, "variance_floor")
    floored = max(forecast_variance, variance_floor)
    return math.log(floored) + realised_return**2 / floored


@dataclass(frozen=True, slots=True)
class ForecastEvaluation:
    """The losses of one series of forecasts over its pairs.

    Attributes
    ----------
    pairs : int
        Forecast-realisation pairs measured.
    first_origin, last_origin : date | None
        The span of the origins; ``None`` without a pair.
    qlike : float | None
        Mean of ``log(q) + r^2 / q``; lower is better.
    variance_mse : float | None
        Mean of ``(r^2 - q)^2``, the squared error of the variance.
    mean_ratio : float | None
        Mean of ``r^2 / q``: one for a forecast right on average, above one
        for a forecast too low.
    floor_applications : int
        Pairs whose forecast was below the metric's floor and was raised to it.
    residual_std, residual_skew, residual_kurtosis : float | None
        Sample standard deviation, skewness and kurtosis (3 for a normal) of
        the standardised residuals ``r / sqrt(q)``.
    residual_beyond_two : float | None
        Share of the residuals larger than two in absolute value.
    variance_floor : float
        The floor the metric was evaluated with.

    Notes
    -----
    Every figure is ``None`` when there is no pair; nothing is replaced by a
    zero.
    """

    pairs: int
    first_origin: date | None
    last_origin: date | None
    qlike: float | None
    variance_mse: float | None
    mean_ratio: float | None
    floor_applications: int
    residual_std: float | None
    residual_skew: float | None
    residual_kurtosis: float | None
    residual_beyond_two: float | None
    variance_floor: float

    def definition(self) -> dict[str, object]:
        """Return the evaluation as it is recorded, dates as text."""
        return {
            "pairs": self.pairs,
            "first_origin": None if self.first_origin is None else self.first_origin.isoformat(),
            "last_origin": None if self.last_origin is None else self.last_origin.isoformat(),
            "qlike": self.qlike,
            "variance_mse": self.variance_mse,
            "mean_ratio": self.mean_ratio,
            "floor_applications": self.floor_applications,
            "residual_std": self.residual_std,
            "residual_skew": self.residual_skew,
            "residual_kurtosis": self.residual_kurtosis,
            "residual_beyond_two": self.residual_beyond_two,
            "variance_floor": self.variance_floor,
        }


def evaluate_forecasts(pairs: pd.DataFrame, *, variance_floor: float) -> ForecastEvaluation:
    """Measure the losses of a frame of pairs.

    Parameters
    ----------
    pairs : pd.DataFrame
        What :func:`pair_forecasts` returns.
    variance_floor : float
        Smallest variance the metric is evaluated at, strictly positive:
        ``1e-12``. Declared by the caller, and counted when it applies.

    Returns
    -------
    ForecastEvaluation
        Means over the pairs; every figure ``None`` on an empty frame.

    Raises
    ------
    ValueError
        If a forecast is negative or not finite: a variance cannot be, and a
        pair holding one was not a usable forecast to begin with.
    """
    require_finite_positive(variance_floor, "variance_floor")
    count = len(pairs)
    if count == 0:
        return ForecastEvaluation(
            0, None, None, None, None, None, 0, None, None, None, None, variance_floor
        )
    raw = pairs["forecast_variance"].to_numpy(dtype="float64")
    realised = pairs["realised_return"].to_numpy(dtype="float64")
    if not np.all(np.isfinite(raw)) or bool((raw < 0.0).any()):
        raise ValueError("a forecast variance must be finite and non-negative")
    floored = np.maximum(raw, variance_floor)
    squares = realised**2
    residuals = realised / np.sqrt(floored)
    several = count > 2
    first, last = pairs.index[0], pairs.index[-1]
    assert isinstance(first, date) and isinstance(last, date)
    return ForecastEvaluation(
        pairs=count,
        first_origin=first,
        last_origin=last,
        qlike=float(np.mean(np.log(floored) + squares / floored)),
        variance_mse=float(np.mean((squares - floored) ** 2)),
        mean_ratio=float(np.mean(squares / floored)),
        floor_applications=int((raw < variance_floor).sum()),
        residual_std=float(np.std(residuals, ddof=1)) if count > 1 else None,
        residual_skew=float(skew(residuals)) if several else None,
        residual_kurtosis=float(kurtosis(residuals, fisher=False)) if several else None,
        residual_beyond_two=float(np.mean(np.abs(residuals) > 2.0)),
        variance_floor=variance_floor,
    )


def compare_forecasts(
    pairs: Mapping[str, pd.DataFrame],
    *,
    variance_floor: float,
    origins: Sequence[date] | None = None,
) -> dict[str, ForecastEvaluation]:
    """Evaluate several series of forecasts, each on its own pairs or on shared origins.

    Parameters
    ----------
    pairs : Mapping[str, pd.DataFrame]
        Frames of pairs by forecast name.
    variance_floor : float
        The floor of the metric, the same for every forecast.
    origins : Sequence[date] | None
        When given, every forecast is measured on the origins of this list it
        has a pair for, and a forecast that lacks one of them is refused: a
        comparison "on the same dates" must be on the same dates.

    Returns
    -------
    dict[str, ForecastEvaluation]
        One evaluation per forecast, in the order given.

    Raises
    ------
    ValueError
        If ``origins`` is given and a forecast has no pair for one of them.
    """
    evaluations: dict[str, ForecastEvaluation] = {}
    for name, frame in pairs.items():
        kept = frame
        if origins is not None:
            missing = [origin for origin in origins if origin not in frame.index]
            if missing:
                raise ValueError(
                    f"{name} has no pair for {len(missing)} of the shared origins, "
                    f"e.g. {missing[0]}"
                )
            kept = frame.loc[list(origins)]
        evaluations[name] = evaluate_forecasts(kept, variance_floor=variance_floor)
    return evaluations
