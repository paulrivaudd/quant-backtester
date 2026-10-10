"""A joint forecast of the return an order can earn: ARIMA for its mean, GARCH for its risk.

At the evening of session ``t`` the last return known is ``r_t = log(O_t /
O_{t-1})`` on adjusted opens. An order decided then is filled at ``O_{t+1}``,
so the first return it can earn is ``r_{t+2} = log(O_{t+2} / O_{t+1})``: the
**second** step ahead. Everything here forecasts that one return.

**Mean.** An ARIMA(1,0,1) with a constant on the returns - an ARMA(1,1), with
no further differencing -

    r_s = m + phi (r_{s-1} - m) + theta e_{s-1} + e_s,

fitted again at every decision on the window, by Gaussian quasi-likelihood in
state-space form with a stationary initialisation. Its two forecasts are

    mu_1 = m + phi (r_t - m) + theta e_t,      mu_2 = m + phi (mu_1 - m),

taken from the filtered state; only ``mu_2`` is acted on.

**Risk.** A zero-mean GARCH(1,1) with Student innovations is fitted on the
one-step innovations of that ARIMA, the first ones dropped. It gives ``h_1``,
the variance of ``e_{t+1}``, and ``h_2 = omega + (alpha + beta) h_1``. The
shock of the first step also travels through the mean, so the variance of the
*return* two steps ahead is

    v_2 = h_2 + (phi + theta)^2 h_1,

and not ``h_2`` alone. A GARCH fit refused on valid innovations is replaced by
an EWMA of the same innovations, for which ``h_2 = h_1``.

This is a **sequential two-stage estimation**, not a joint ARIMA-GARCH
likelihood, and ``v_2`` is a plug-in variance: the parameters and the last
state are taken as known. ``mu_2`` is a forecast *log* return; it is not the
expectation of a simple P&L, and no probability of a rise is derived from it.

**Units.** The estimators work on returns multiplied by 100. Every public
object is in decimal units: a mean of 20 basis points is ``0.002``, a variance
is a squared decimal return, a volatility of 20% a year is ``0.20``.

**Availability.** The window is the one the reader serves at the decision
instant: opens adjusted by the corporate actions known then
(:func:`~quant_backtester.signals.windows.load_adjusted_open_window`).

Nothing here keeps a fitted model between two calls: the same returns and the
same configuration give the same forecast. ``statsmodels`` and ``arch`` are
optional dependencies (the ``stats`` extra), imported when a fit is asked for.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import statistics
import warnings
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import Enum
from typing import Final

import numpy as np
import pandas as pd

from quant_backtester.numbers import require_finite_non_negative, require_finite_positive
from quant_backtester.signals.base import Signal, SignalResult, build_result_frame, result_row
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.models.garch import (
    PERCENT,
    VARIANCE_SCALE,
    Estimator,
    ForecastSource,
    GarchForecastConfig,
    MissingDependency,
    estimate_with_arch,
    ewma_variance,
    forecast_garch,
)
from quant_backtester.signals.types import (
    SignalStatus,
    SignalUnit,
    WindowMode,
    WindowSpec,
    require_non_negative_int,
    require_positive_int,
)
from quant_backtester.signals.windows import (
    ADJUSTED_OPEN_CONSTRUCTION,
    LoadedWindow,
    load_adjusted_open_window,
    returns_of,
)

ARIMA_STAGE: Final[str] = "ARIMA"
"""The mean could not be forecast: no direction, so no position."""

VOLATILITY_STAGE: Final[str] = "VOLATILITY"
"""The mean was forecast and neither GARCH nor the EWMA gave a usable variance."""

NEAR_CONSTANT_RETURNS: Final[str] = "NEAR_CONSTANT_RETURNS"
"""The returns do not vary: no ARIMA is fitted."""

ARIMA_NOT_CONVERGED: Final[str] = "ARIMA_NOT_CONVERGED"
"""The optimiser stopped without reporting a maximum."""

ARIMA_NON_FINITE: Final[str] = "ARIMA_NON_FINITE"
"""A parameter, the likelihood, an innovation or a forecast mean is not finite."""

ARIMA_INADMISSIBLE: Final[str] = "ARIMA_INADMISSIBLE"
"""``|phi|`` or ``|theta|`` is within the margin of one, or the innovation
variance is not strictly positive. The parameters are refused, not moved."""

INVALID_RETURN_VARIANCE: Final[str] = "INVALID_RETURN_VARIANCE"
"""The two-step variance of the return is not a finite, strictly positive number."""

EWMA_SOURCE: Final[str] = "EWMA"
"""The variance of a configuration that asks for the EWMA: a control, not a fallback."""

FORECAST_COLUMNS: Final[tuple[str, ...]] = (
    "return_variance_h2",
    "annualized_volatility",
    "mu_h1",
    "innovation_variance_h1",
    "innovation_variance_h2",
    "volatility_source",
    "fallback_reason",
    "failure_stage",
    "failure_code",
    "long_run_mean",
    "phi",
    "theta",
    "arima_sigma2",
    "arima_converged",
    "arima_covariance_usable",
    "omega_decimal",
    "alpha",
    "beta",
    "nu",
    "persistence",
    "n_returns",
    "n_residuals",
    "warnings",
)
"""The columns a result of the joint signal carries beside the usual ones."""


def require_statsmodels() -> None:
    """Raise unless the ``statsmodels`` package can be imported.

    Raises
    ------
    MissingDependency
        If it is not installed. Asked before a run starts: a missing
        dependency stops the launch, it never becomes a book held in cash.
    """
    if importlib.util.find_spec("statsmodels") is None:
        raise MissingDependency(
            "the ARIMA forecast needs the 'statsmodels' package, an optional dependency: "
            "install the stats extra (uv sync --extra stats)"
        )


class VolatilityModel(Enum):
    """Which variance the innovations are given."""

    GARCH = "GARCH"
    """A GARCH(1,1) with Student innovations, the EWMA as its declared fallback."""

    EWMA = "EWMA"
    """The EWMA alone: the control that says what GARCH adds."""


@dataclass(frozen=True, slots=True)
class ArimaConfig:
    """Everything the mean's fit depends on besides its returns. Nothing is defaulted.

    Attributes
    ----------
    estimation_returns : int
        Returns the model is fitted on; the window holds one more open.
    residual_burn : int
        First innovations left out of the variance model, to limit the effect
        of the filter's initialisation.
    ar_order, ma_order : int
        ``1`` and ``1`` for the ARMA(1,1); ``0`` and ``0`` for the control
        with a constant mean. No other order is part of this version.
    max_iterations : int
        Iterations L-BFGS may take.
    pgtol, factr : float
        Its two tolerances, as ``scipy`` names them.
    root_margin : float
        ``|phi|`` and ``|theta|`` must be below one by more than this.
    constant_return_tolerance : float
        Sample standard deviation of the decimal returns at or below which no
        model is fitted.

    Raises
    ------
    ValueError
        If a count is not a positive integer, the burn leaves no innovation,
        an order is not 0 or 1, or a tolerance is out of its range.
    """

    estimation_returns: int
    residual_burn: int
    ar_order: int
    ma_order: int
    max_iterations: int
    pgtol: float
    factr: float
    root_margin: float
    constant_return_tolerance: float

    def __post_init__(self) -> None:
        """Reject a configuration no fit can be made from."""
        require_positive_int(self.estimation_returns, "estimation_returns")
        require_non_negative_int(self.residual_burn, "residual_burn")
        require_positive_int(self.max_iterations, "max_iterations")
        if self.residual_burn >= self.estimation_returns:
            raise ValueError("residual_burn leaves no innovation to model")
        for name in ("ar_order", "ma_order"):
            if getattr(self, name) not in (0, 1) or isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} is 0 or 1 in this version, got {getattr(self, name)!r}")
        require_finite_positive(self.pgtol, "pgtol")
        require_finite_positive(self.factr, "factr")
        require_finite_non_negative(self.constant_return_tolerance, "constant_return_tolerance")
        if not (math.isfinite(self.root_margin) and 0.0 <= self.root_margin < 1.0):
            raise ValueError(f"root_margin is a margin in [0, 1), got {self.root_margin!r}")

    @property
    def residuals(self) -> int:
        """Return how many innovations are left for the variance model."""
        return self.estimation_returns - self.residual_burn

    def definition(self) -> dict[str, object]:
        """Return the configuration and the fixed conventions of the fit, serialisable."""
        return {
            "model": f"ARIMA({self.ar_order},0,{self.ma_order})",
            "trend": "c",
            "returns": "logarithmic",
            "return_scale": PERCENT,
            "method": "statespace",
            "initialization": "stationary",
            "optimizer": "lbfgs",
            "start": "window mean, 0, 0, window variance (ddof=0)",
            "covariance_type": "robust",
            "enforce_stationarity": True,
            "enforce_invertibility": True,
            "estimation_returns": self.estimation_returns,
            "residual_burn": self.residual_burn,
            "max_iterations": self.max_iterations,
            "pgtol": self.pgtol,
            "factr": self.factr,
            "root_margin": self.root_margin,
            "constant_return_tolerance": self.constant_return_tolerance,
        }


@dataclass(frozen=True, slots=True)
class ArimaEstimate:
    """What an ARIMA estimator found, in the units it worked in: percent returns.

    Attributes
    ----------
    converged : bool
        Whether the optimiser reported a maximum.
    loglikelihood : float
        The Gaussian log-likelihood at the estimate.
    mean, phi, theta : float
        The long-run mean ``m`` (the constant of the library, not the
        intercept ``(1 - phi) m``) and the two coefficients; zero for an
        order that is not fitted.
    sigma2 : float
        The innovation variance, in percent squared.
    forecast_h1, forecast_h2 : float
        The two forecast means from the filtered state, in percent.
    innovations : tuple[float, ...]
        The one-step prediction errors of the filter, oldest first, in
        percent: neither standardised nor smoothed.
    iterations : int
        Iterations the optimiser took.
    covariance_usable : bool
        Whether the robust covariance of the parameters is finite. A
        diagnostic: it never filters a forecast.
    warnings : tuple[str, ...]
        The numerical warnings raised during the fit.
    """

    converged: bool
    loglikelihood: float
    mean: float
    phi: float
    theta: float
    sigma2: float
    forecast_h1: float
    forecast_h2: float
    innovations: tuple[float, ...]
    iterations: int
    covariance_usable: bool = True
    warnings: tuple[str, ...] = ()


ArimaEstimator = Callable[[Sequence[float], ArimaConfig], ArimaEstimate]
"""Fits the mean on percent returns, oldest first. Injected so that a refused
fit can be tested without waiting for an optimiser to fail."""


def estimate_with_statsmodels(
    scaled_returns: Sequence[float], config: ArimaConfig
) -> ArimaEstimate:
    """Fit the ARIMA of a configuration with ``statsmodels``, by state space.

    Parameters
    ----------
    scaled_returns : Sequence[float]
        Returns multiplied by :data:`~quant_backtester.signals.models.garch.PERCENT`,
        oldest first.
    config : ArimaConfig
        The orders and the optimiser's limits.

    Returns
    -------
    ArimaEstimate
        The estimate in percent units, whether or not it is admissible:
        judging it is :func:`forecast_arima_garch`'s job.

    Raises
    ------
    MissingDependency
        If ``statsmodels`` is not installed.
    ValueError
        If the library names a parameter this adapter does not know: the
        starting point is built by name, never by position alone.

    Notes
    -----
    One starting point and no warm start: the window mean, zero for both
    coefficients and the window variance (``ddof=0``). The two forecasts are
    those of the filtered state, ``get_forecast(steps=2).predicted_mean``.
    Warnings are caught here, and only here, and kept on the estimate.
    """
    require_statsmodels()
    # Imported on use: an optional dependency, and the module must import without it.
    from statsmodels.tsa.arima.model import ARIMA

    observed = np.asarray(scaled_returns, dtype="float64")
    start_by_name = {
        "const": float(observed.mean()),
        "ar.L1": 0.0,
        "ma.L1": 0.0,
        "sigma2": float(observed.var(ddof=0)),
    }
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        model = ARIMA(
            observed,
            order=(config.ar_order, 0, config.ma_order),
            trend="c",
            enforce_stationarity=True,
            enforce_invertibility=True,
            missing="raise",
        )
        unknown = [name for name in model.param_names if name not in start_by_name]
        if unknown:
            raise ValueError(f"the ARIMA of this library names unknown parameters: {unknown}")
        start = np.array([start_by_name[name] for name in model.param_names])
        fitted = model.fit(
            start_params=start,
            method="statespace",
            cov_type="robust",
            method_kwargs={
                "method": "lbfgs",
                "maxiter": config.max_iterations,
                "pgtol": config.pgtol,
                "factr": config.factr,
                "disp": 0,
            },
        )
        forecast = np.asarray(fitted.get_forecast(steps=2).predicted_mean, dtype="float64")
        try:
            covariance_usable = bool(np.isfinite(np.asarray(fitted.cov_params())).all())
        except (np.linalg.LinAlgError, ValueError):
            covariance_usable = False
    estimated = dict(zip(model.param_names, (float(value) for value in fitted.params), strict=True))
    outcome = fitted.mle_retvals
    return ArimaEstimate(
        converged=bool(outcome["converged"]),
        loglikelihood=float(fitted.llf),
        mean=estimated["const"],
        phi=estimated.get("ar.L1", 0.0),
        theta=estimated.get("ma.L1", 0.0),
        sigma2=estimated["sigma2"],
        forecast_h1=float(forecast[0]),
        forecast_h2=float(forecast[1]),
        innovations=tuple(float(value) for value in np.asarray(fitted.resid)),
        iterations=int(outcome["iterations"]),
        covariance_usable=covariance_usable,
        warnings=tuple(f"{item.category.__name__}: {item.message}" for item in caught),
    )


@dataclass(frozen=True, slots=True)
class ArimaGarchConfig:
    """The joint forecast: the mean's fit, the variance's, and which variance is asked for.

    Attributes
    ----------
    arima : ArimaConfig
        The fit of the mean.
    garch : GarchForecastConfig
        The conventions of the variance and of its EWMA, on exactly the
        innovations the mean leaves after its burn.
    volatility_model : VolatilityModel
        GARCH with its fallback, or the EWMA alone.

    Raises
    ------
    ValueError
        If the variance model is not configured for the number of innovations
        the mean leaves.
    """

    arima: ArimaConfig
    garch: GarchForecastConfig
    volatility_model: VolatilityModel

    def __post_init__(self) -> None:
        """Refuse two halves that do not agree on the innovations."""
        if not isinstance(self.volatility_model, VolatilityModel):
            raise ValueError(
                f"volatility_model must be a VolatilityModel, got {self.volatility_model!r}"
            )
        if self.garch.estimation_returns != self.arima.residuals:
            raise ValueError(
                f"the variance model is configured for {self.garch.estimation_returns} "
                f"innovations and the mean leaves {self.arima.residuals}"
            )

    @property
    def annualization(self) -> int:
        """Return the sessions per year a daily variance is scaled by."""
        return self.garch.annualization

    def definition(self) -> dict[str, object]:
        """Return everything the forecast depends on, serialisable."""
        return {
            "arima": self.arima.definition(),
            "volatility": self.garch.definition(),
            "volatility_model": self.volatility_model.value,
            "estimation": "sequential two-stage, not a joint likelihood",
            "forecast_horizon_sessions": 2,
            "target_return_sessions": 1,
            "return_variance": "h2 + (phi + theta)^2 * h1, plug-in",
        }

    def fingerprint(self) -> str:
        """Return a stable hash of the definition."""
        canonical = json.dumps(self.definition(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ArimaGarchForecast:
    """One joint forecast of the return two steps ahead, and how it was obtained.

    Attributes
    ----------
    usable : bool
        Whether the mean is finite and the variance finite and strictly
        positive: what a status of ``OK`` requires.
    failure_stage, failure_code : str | None
        Where and why an unusable forecast failed.
    n_returns, n_residuals : int
        Returns the mean was fitted on, innovations given to the variance.
    mu_h1, mu_h2 : float | None
        Forecast mean log return one and two steps ahead, decimal. Only
        ``mu_h2`` is acted on.
    innovation_variance_h1, innovation_variance_h2 : float | None
        ``h_1`` and ``h_2``, squared decimal returns.
    return_variance_h2 : float | None
        ``v_2 = h_2 + (phi + theta)^2 h_1``.
    annualized_volatility : float | None
        ``sqrt(annualization * v_2)``, as a fraction. Not halved: the target
        is one session's return, forecast two steps ahead.
    volatility_source : str | None
        ``GARCH``, ``EWMA_FALLBACK`` or ``EWMA``.
    fallback_reason : str | None
        Why a GARCH fit was replaced by the EWMA.
    long_run_mean, phi, theta, arima_sigma2 : float | None
        The estimate of the mean, decimal units for the two that have one.
    arima_converged, arima_covariance_usable : bool | None
        What the optimiser reported, and whether its covariance is finite.
    omega_decimal, alpha, beta, nu, persistence : float | None
        The estimate of the GARCH fit, accepted or refused.
    warnings : tuple[str, ...]
        Numerical warnings of both fits.
    """

    usable: bool
    n_returns: int
    n_residuals: int
    failure_stage: str | None = None
    failure_code: str | None = None
    mu_h1: float | None = None
    mu_h2: float | None = None
    innovation_variance_h1: float | None = None
    innovation_variance_h2: float | None = None
    return_variance_h2: float | None = None
    annualized_volatility: float | None = None
    volatility_source: str | None = None
    fallback_reason: str | None = None
    long_run_mean: float | None = None
    phi: float | None = None
    theta: float | None = None
    arima_sigma2: float | None = None
    arima_converged: bool | None = None
    arima_covariance_usable: bool | None = None
    omega_decimal: float | None = None
    alpha: float | None = None
    beta: float | None = None
    nu: float | None = None
    persistence: float | None = None
    warnings: tuple[str, ...] = ()

    def diagnostics(self) -> dict[str, object]:
        """Return the columns of :data:`FORECAST_COLUMNS`, as built-ins."""
        return {
            "return_variance_h2": self.return_variance_h2,
            "annualized_volatility": self.annualized_volatility,
            "mu_h1": self.mu_h1,
            "innovation_variance_h1": self.innovation_variance_h1,
            "innovation_variance_h2": self.innovation_variance_h2,
            "volatility_source": self.volatility_source,
            "fallback_reason": self.fallback_reason,
            "failure_stage": self.failure_stage,
            "failure_code": self.failure_code,
            "long_run_mean": self.long_run_mean,
            "phi": self.phi,
            "theta": self.theta,
            "arima_sigma2": self.arima_sigma2,
            "arima_converged": self.arima_converged,
            "arima_covariance_usable": self.arima_covariance_usable,
            "omega_decimal": self.omega_decimal,
            "alpha": self.alpha,
            "beta": self.beta,
            "nu": self.nu,
            "persistence": self.persistence,
            "n_returns": self.n_returns,
            "n_residuals": self.n_residuals,
            "warnings": " | ".join(self.warnings),
        }


def arma_two_step_mean(
    mean: float, phi: float, theta: float, last_return: float, last_innovation: float
) -> tuple[float, float]:
    """Return ``(mu_1, mu_2)`` of an ARMA(1,1) whose last state is known.

    ``mu_1 = m + phi (r_t - m) + theta e_t`` and ``mu_2 = m + phi (mu_1 - m)``,
    in the unit of the return. The reference of the formulas: a fitted filter
    whose initial state is uncertain need not agree with it to the last digit.
    """
    first = mean + phi * (last_return - mean) + theta * last_innovation
    return first, mean + phi * (first - mean)


def second_step_innovation_variance(
    omega: float, alpha: float, beta: float, first_step: float
) -> float:
    """Return ``h_2 = omega + (alpha + beta) h_1`` of a GARCH(1,1)."""
    return omega + (alpha + beta) * first_step


def two_step_return_variance(
    first_step: float, second_step: float, phi: float, theta: float
) -> float:
    """Return ``v_2 = h_2 + (phi + theta)^2 h_1``, the variance of the return two steps ahead.

    The forecast error is ``(phi + theta) e_{t+1} + e_{t+2}``, whose two
    innovations are uncorrelated given what is known at ``t``. ``h_2`` alone
    is the variance of the second innovation, not of the return.
    """
    return second_step + (phi + theta) ** 2 * first_step


def forecast_arima_garch(
    log_returns: Sequence[float],
    config: ArimaGarchConfig,
    *,
    arima_estimator: ArimaEstimator = estimate_with_statsmodels,
    garch_estimator: Estimator = estimate_with_arch,
) -> ArimaGarchForecast:
    """Forecast the mean and the variance of the return two steps ahead of one window.

    Parameters
    ----------
    log_returns : Sequence[float]
        Open-to-open log returns as fractions, oldest first, every one known
        at the decision. Exactly ``config.arima.estimation_returns`` of them.
    config : ArimaGarchConfig
        The conventions of both fits.
    arima_estimator, garch_estimator
        What fits each model; the library adapters unless a test injects one.

    Returns
    -------
    ArimaGarchForecast
        Usable when the mean is finite and the variance finite and strictly
        positive. A mean that cannot be forecast is not replaced by anything:
        the forecast is unusable at stage ``ARIMA``. A variance that neither
        GARCH nor the EWMA can give makes it unusable at stage ``VOLATILITY``.

    Raises
    ------
    ValueError
        If the returns are not exactly the configured number or one is not
        finite: invalid data is the caller's to refuse.
    MissingDependency
        If a fit is needed and its library is not installed.

    Notes
    -----
    The innovations given to the variance model are the filter's one-step
    errors, the first ``residual_burn`` dropped, back in decimal units. They
    are not the returns: GARCH models what the mean leaves.
    """
    returns = [float(value) for value in log_returns]
    arima = config.arima
    if len(returns) != arima.estimation_returns:
        raise ValueError(
            f"the forecast is configured for {arima.estimation_returns} returns, got {len(returns)}"
        )
    if not all(math.isfinite(value) for value in returns):
        raise ValueError("a return is not finite; invalid data is refused before the forecast")
    count, residual_count = len(returns), arima.residuals
    if statistics.stdev(returns) <= arima.constant_return_tolerance:
        return ArimaGarchForecast(
            usable=False,
            n_returns=count,
            n_residuals=residual_count,
            failure_stage=ARIMA_STAGE,
            failure_code=NEAR_CONSTANT_RETURNS,
        )
    estimate = arima_estimator([PERCENT * value for value in returns], arima)
    mean_fields: dict[str, object] = {
        "long_run_mean": estimate.mean / PERCENT,
        "phi": estimate.phi,
        "theta": estimate.theta,
        "arima_sigma2": estimate.sigma2 / VARIANCE_SCALE,
        "arima_converged": estimate.converged,
        "arima_covariance_usable": estimate.covariance_usable,
    }
    refusal = _arima_refusal(estimate, arima)
    if refusal is not None:
        return _forecast(
            count, residual_count, mean_fields, estimate.warnings, failure=(ARIMA_STAGE, refusal)
        )
    mean_fields["mu_h1"] = estimate.forecast_h1 / PERCENT
    mean_fields["mu_h2"] = estimate.forecast_h2 / PERCENT
    residuals = [value / PERCENT for value in estimate.innovations[arima.residual_burn :]]
    if len(residuals) != residual_count:
        raise ValueError(
            f"the estimator returned {len(estimate.innovations)} innovations for {count} returns"
        )
    garch = config.garch
    notes = estimate.warnings
    variance_fields: dict[str, object] = {}
    first: float | None
    second: float | None
    if config.volatility_model is VolatilityModel.EWMA:
        first = ewma_variance(
            residuals, decay=garch.ewma_decay, seed_returns=garch.ewma_seed_returns
        )
        second = first
        variance_fields["volatility_source"] = EWMA_SOURCE
    else:
        volatility = forecast_garch(residuals, garch, estimator=garch_estimator)
        notes = (*notes, *volatility.warnings)
        variance_fields.update(
            {
                "volatility_source": volatility.source.value,
                "fallback_reason": volatility.fallback_reason,
                "omega_decimal": volatility.omega,
                "alpha": volatility.alpha,
                "beta": volatility.beta,
                "nu": volatility.nu,
                "persistence": volatility.persistence,
            }
        )
        first = volatility.variance
        if volatility.source is ForecastSource.GARCH:
            assert first is not None and volatility.omega is not None
            assert volatility.alpha is not None and volatility.beta is not None
            second = second_step_innovation_variance(
                volatility.omega, volatility.alpha, volatility.beta, first
            )
        else:
            # The expectation of an EWMA stays where it is: h_2 = h_1.
            second = first
    fields = {**mean_fields, **variance_fields}
    if first is None or second is None:
        return _forecast(
            count,
            residual_count,
            fields,
            notes,
            failure=(VOLATILITY_STAGE, INVALID_RETURN_VARIANCE),
        )
    variance = two_step_return_variance(first, second, estimate.phi, estimate.theta)
    fields.update(
        {
            "innovation_variance_h1": first,
            "innovation_variance_h2": second,
            "return_variance_h2": variance,
        }
    )
    if not (math.isfinite(variance) and variance > 0.0):
        return _forecast(
            count,
            residual_count,
            fields,
            notes,
            failure=(VOLATILITY_STAGE, INVALID_RETURN_VARIANCE),
        )
    fields["annualized_volatility"] = math.sqrt(config.annualization * variance)
    return _forecast(count, residual_count, fields, notes, failure=None)


def _arima_refusal(estimate: ArimaEstimate, config: ArimaConfig) -> str | None:
    """Return why an estimate of the mean is not used, or ``None`` when it is admissible."""
    if not estimate.converged:
        return ARIMA_NOT_CONVERGED
    numbers = (
        estimate.loglikelihood,
        estimate.mean,
        estimate.phi,
        estimate.theta,
        estimate.sigma2,
        estimate.forecast_h1,
        estimate.forecast_h2,
        *estimate.innovations,
    )
    if not all(math.isfinite(value) for value in numbers):
        return ARIMA_NON_FINITE
    bound = 1.0 - config.root_margin
    if not (estimate.sigma2 > 0.0 and abs(estimate.phi) < bound and abs(estimate.theta) < bound):
        return ARIMA_INADMISSIBLE
    return None


def _forecast(
    n_returns: int,
    n_residuals: int,
    fields: Mapping[str, object],
    notes: Sequence[str],
    *,
    failure: tuple[str, str] | None,
) -> ArimaGarchForecast:
    """Return a forecast carrying the fields found so far, usable unless it failed."""
    kept = dict(fields)
    if failure is not None:
        # An unusable forecast exposes nothing a decision could act on.
        for name in ("mu_h2", "return_variance_h2", "annualized_volatility"):
            kept.pop(name, None)
    base = ArimaGarchForecast(
        usable=failure is None,
        n_returns=n_returns,
        n_residuals=n_residuals,
        failure_stage=None if failure is None else failure[0],
        failure_code=None if failure is None else failure[1],
        warnings=tuple(notes),
    )
    return replace(base, **kept)


@dataclass(frozen=True, slots=True)
class JointReading:
    """What a strategy reads off one row of the joint signal.

    Attributes
    ----------
    status : SignalStatus
        ``OK`` when both numbers can be acted on.
    mean : float | None
        Forecast log return two steps ahead, decimal.
    volatility : float | None
        Annualised volatility of that return, as a fraction.
    """

    status: SignalStatus
    mean: float | None
    volatility: float | None


def read_joint_forecast(frame: pd.DataFrame, instrument_id: str) -> JointReading:
    """Return the mean and the volatility of one instrument's row, checked.

    Parameters
    ----------
    frame : pd.DataFrame
        The frame of an :class:`ArimaGarchForecastSignal` result.
    instrument_id : str
        The row to read.

    Returns
    -------
    JointReading
        Both numbers on an ``OK`` row, neither otherwise.

    Raises
    ------
    KeyError
        If the frame lacks the volatility column or the row: a breach of the
        signal's contract, never a missing forecast to turn into cash.
    ValueError
        If an ``OK`` row carries a volatility that is not finite and positive.
    """
    for column in ("value", "status", "annualized_volatility"):
        if column not in frame.columns:
            raise KeyError(f"the joint forecast carries no column {column!r}")
    status = frame["status"].to_dict()[instrument_id]
    assert isinstance(status, SignalStatus)
    if status is not SignalStatus.OK:
        return JointReading(status, None, None)
    mean = float(frame["value"].to_dict()[instrument_id])
    volatility = frame["annualized_volatility"].to_dict()[instrument_id]
    if volatility is None or not (math.isfinite(float(volatility)) and float(volatility) > 0.0):
        raise ValueError(f"{instrument_id} is OK with a volatility of {volatility!r}")
    return JointReading(status, mean, float(volatility))


@dataclass(frozen=True, slots=True)
class ArimaGarchForecastSignal(Signal):
    """The mean log return forecast two steps ahead, with its variance beside it.

    Attributes
    ----------
    signal_id : str
        Stable name, e.g. ``"arima101_garch_mu2_756r"``.
    config : ArimaGarchConfig
        The conventions of both fits.
    max_age_sessions : int
        Largest accepted age of the freshest bar, on the reference calendar.

    Notes
    -----
    ``value`` is ``mu_2``, a decimal **log return** of unit ``FRACTION``: what
    the return from the open after the decision to the open after that is
    forecast to be. The other columns of :data:`FORECAST_COLUMNS` carry
    ``v_2``, the annualised volatility, the source of the variance and the
    diagnostics of both fits, computed once per instrument and call.

    ``OK`` requires a finite mean *and* a finite, strictly positive variance.
    A window that is short, holed, stale or invalid gives its own status and
    no fit; a mean or a variance that cannot be forecast gives
    ``INVALID_INPUT`` with ``failure_stage`` saying which - a failed fit is not
    a hole in the market data. An unusable row carries no number to act on.
    """

    signal_id: str
    config: ArimaGarchConfig
    max_age_sessions: int

    def __post_init__(self) -> None:
        """Reject an age that is not a count of sessions."""
        require_non_negative_int(self.max_age_sessions, "max_age_sessions")

    def definition(self) -> Mapping[str, object]:
        """Return every parameter that changes the number."""
        return {
            "type": "ArimaGarchForecastSignal",
            "config": self.config.definition(),
            "price": ADJUSTED_OPEN_CONSTRUCTION,
            "target": "log_adjusted_open_to_open, second step ahead",
            "max_age_sessions": self.max_age_sessions,
            "window_mode": WindowMode.CONSECUTIVE_SESSIONS.value,
            "unit": SignalUnit.FRACTION.value,
            "value": "mu_h2, a decimal log return",
        }

    def window_spec(self) -> WindowSpec:
        """Return the window asked for: one open more than the returns fitted."""
        return WindowSpec(self.config.arima.estimation_returns + 1)

    def forecast_of(self, window: LoadedWindow) -> ArimaGarchForecast:
        """Return the joint forecast of an ``OK`` window of adjusted opens."""
        return forecast_arima_garch(returns_of(window, logarithmic=True), self.config)

    def compute(self, context: SignalContext, instrument_ids: Sequence[str]) -> SignalResult:
        """Compute each instrument's joint forecast, once."""
        rows: dict[str, Mapping[str, object]] = {}
        extras: dict[str, dict[str, object]] = {}
        for instrument_id in instrument_ids:
            window = load_adjusted_open_window(
                context,
                instrument_id,
                spec=self.window_spec(),
                max_age_sessions=self.max_age_sessions,
            )
            empty: dict[str, object] = {column: None for column in FORECAST_COLUMNS}
            extras[instrument_id] = empty
            if window.status is not SignalStatus.OK:
                rows[instrument_id] = result_row(None, window)
                continue
            forecast = self.forecast_of(window)
            extras[instrument_id] = forecast.diagnostics()
            if not forecast.usable:
                refused = LoadedWindow(
                    status=SignalStatus.INVALID_INPUT,
                    points=window.points,
                    dates=window.dates,
                    age_sessions=window.age_sessions,
                )
                rows[instrument_id] = result_row(None, refused)
                continue
            rows[instrument_id] = result_row(forecast.mu_h2, window)
        frame = build_result_frame(rows)
        for column in FORECAST_COLUMNS:
            frame[column] = pd.Series(
                [extras[name][column] for name in frame.index], index=frame.index, dtype="object"
            )
        return SignalResult(
            signal_id=self.signal_id,
            as_of=context.as_of,
            _frame=frame,
            definition=self.definition(),
        )
