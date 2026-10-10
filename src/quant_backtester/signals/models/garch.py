"""A GARCH(1,1) forecast of the next session's variance, and the EWMA it falls back on.

The model is fitted again at every decision, on the daily log returns of one
fund's adjusted closes over a rolling window of consecutive sessions, all of
them known at the decision instant:

    r_t = sqrt(h_t) z_t,        h_t = omega + alpha r_{t-1}^2 + beta h_{t-1},

with a mean fixed at zero and ``z`` a standardised Student of ``nu > 2``
degrees of freedom. What is used is the one-step forecast

    h_{t+1|t} = omega + alpha r_t^2 + beta h_t,

which contains the last observed shock, and not the filtered ``h_t``. It
covers the return from the close of ``t`` to the close of ``t + 1``; an order
decided on it is filled at the open in between, so it is a proxy of the risk
of the position and not a forecast of its open-to-open return.

**Units.** Returns are multiplied by 100 for the optimiser and nowhere else.
Everything returned by :func:`forecast_garch` is in decimal units: a variance
of the daily return as a fraction squared, ``omega`` divided by 10 000, and an
annualised volatility of 20% written ``0.20``. ``alpha``, ``beta`` and ``nu``
carry no unit.

**Availability.** Adjusted closes are restated when a corporate action becomes
known: the window is the one the reader serves at the decision instant, with
the actions known then, and never a window rebuilt afterwards.

**Fallback.** A fit that does not converge, lands on inadmissible parameters
or gives an unusable forecast is replaced by an exponentially weighted
variance of the same returns, and the result says so. Missing or invalid data
is not a numerical failure: it never reaches the estimator, and it never
triggers the fallback.

Nothing here keeps a fitted model between two calls, writes a file or reads
anything but its arguments: the same returns and the same configuration give
the same forecast, whatever was computed before.

The estimation is done by the ``arch`` package, an optional dependency (the
``stats`` extra). It is imported when a fit is asked for, so that this module,
and the catalogue that names its strategy, import without it.
"""

from __future__ import annotations

import importlib.util
import math
import statistics
import warnings
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Final

import numpy as np

from quant_backtester.data.schemas import BarField
from quant_backtester.numbers import require_finite_non_negative, require_finite_positive
from quant_backtester.signals.base import Signal, SignalResult
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.types import (
    PriceBasis,
    SignalStatus,
    SignalUnit,
    WindowMode,
    WindowSpec,
    require_non_negative_int,
    require_positive_int,
)
from quant_backtester.signals.windows import LoadedWindow, load_window, returns_of

PERCENT: Final[float] = 100.0
"""What the returns are multiplied by before the optimiser sees them."""

VARIANCE_SCALE: Final[float] = PERCENT * PERCENT
"""What a variance of percent returns is divided by to be one of decimal returns."""

NEAR_CONSTANT_RETURNS: Final[str] = "NEAR_CONSTANT_RETURNS"
"""The returns do not vary: there is no likelihood to maximise."""

NOT_CONVERGED: Final[str] = "NOT_CONVERGED"
"""The optimiser stopped without reporting a maximum."""

NON_FINITE_ESTIMATE: Final[str] = "NON_FINITE_ESTIMATE"
"""The likelihood, a parameter or the filtered variance is not a finite number."""

INADMISSIBLE_PARAMETERS: Final[str] = "INADMISSIBLE_PARAMETERS"
"""A constraint is not met: ``omega > 0``, ``alpha >= 0``, ``beta >= 0``,
``alpha + beta < 1`` and ``nu > 2``. A fit on the boundary ``alpha + beta = 1``
is refused, and its parameters are not moved to make it pass."""

INVALID_FORECAST: Final[str] = "INVALID_FORECAST"
"""The forecast variance is not a finite, strictly positive number."""

FALLBACK_REASONS: Final[tuple[str, ...]] = (
    NEAR_CONSTANT_RETURNS,
    NOT_CONVERGED,
    NON_FINITE_ESTIMATE,
    INADMISSIBLE_PARAMETERS,
    INVALID_FORECAST,
)
"""Every reason a fit is replaced by the fallback, as stable codes."""


class MissingDependency(ImportError):
    """Raised when a fit is asked for and the ``arch`` package is not installed."""


class ForecastSource(Enum):
    """Where a forecast variance came from."""

    GARCH = "GARCH"
    """The fit was accepted."""

    EWMA_FALLBACK = "EWMA_FALLBACK"
    """The data were valid and the fit was refused: the exponentially weighted variance."""

    FALLBACK_FAILED = "FALLBACK_FAILED"
    """The fit was refused and the fallback is not a usable number either."""


def require_arch() -> None:
    """Raise unless the ``arch`` package can be imported.

    Raises
    ------
    MissingDependency
        If it is not installed. Asked before a run starts, so that a missing
        dependency stops the launch instead of looking like a failed fit.
    """
    if importlib.util.find_spec("arch") is None:
        raise MissingDependency(
            "the GARCH forecast needs the 'arch' package, an optional dependency: "
            "install the stats extra (uv sync --extra stats)"
        )


@dataclass(frozen=True, slots=True)
class GarchForecastConfig:
    """Everything a forecast depends on besides its returns. Nothing is defaulted.

    Attributes
    ----------
    estimation_returns : int
        Daily returns the model is fitted on; the window holds one more close.
    annualization : int
        Sessions per year a daily variance is scaled by.
    initial_omega_share, initial_alpha, initial_beta, initial_nu : float
        The single starting point of the optimiser: ``omega`` starts at
        ``initial_omega_share`` times the mean square of the percent returns.
    max_iterations : int
        Iterations the optimiser may take.
    ftol : float
        Its tolerance on the objective.
    ewma_decay : float
        Weight the fallback keeps of its previous variance, in ``(0, 1)``.
    ewma_seed_returns : int
        Returns whose mean square starts the fallback's recursion.
    constant_return_tolerance : float
        Sample standard deviation of the decimal returns at or below which
        they are treated as constant and no fit is attempted. Passed in by the
        caller: the project's convention lives in a layer above this one.

    Raises
    ------
    ValueError
        If a count is not a positive integer, the fallback's seed does not fit
        the window, a number is not finite, the starting point is outside the
        model's constraints or the decay is outside ``(0, 1)``.
    """

    estimation_returns: int
    annualization: int
    initial_omega_share: float
    initial_alpha: float
    initial_beta: float
    initial_nu: float
    max_iterations: int
    ftol: float
    ewma_decay: float
    ewma_seed_returns: int
    constant_return_tolerance: float

    def __post_init__(self) -> None:
        """Reject a configuration no forecast can be computed from."""
        require_positive_int(self.estimation_returns, "estimation_returns")
        require_positive_int(self.annualization, "annualization")
        require_positive_int(self.max_iterations, "max_iterations")
        require_finite_positive(self.initial_omega_share, "initial_omega_share")
        require_finite_non_negative(self.initial_alpha, "initial_alpha")
        require_finite_non_negative(self.initial_beta, "initial_beta")
        require_finite_positive(self.initial_nu, "initial_nu")
        require_finite_positive(self.ftol, "ftol")
        require_finite_non_negative(self.constant_return_tolerance, "constant_return_tolerance")
        if self.initial_alpha + self.initial_beta >= 1.0:
            raise ValueError("the starting point must satisfy initial_alpha + initial_beta < 1")
        if self.initial_nu <= 2.0:
            raise ValueError(f"initial_nu must exceed 2, got {self.initial_nu}")
        _require_ewma(self.estimation_returns, self.ewma_decay, self.ewma_seed_returns)

    def definition(self) -> dict[str, object]:
        """Return the configuration and the fixed conventions of the model, serialisable."""
        return {
            "model": "GARCH(1,1)",
            "mean": "Zero",
            "distribution": "standardized Student t",
            "returns": "logarithmic",
            "return_scale": PERCENT,
            "backcast": "arch default, computed on the window",
            "forecast_horizon_sessions": 1,
            "estimation_returns": self.estimation_returns,
            "annualization": self.annualization,
            "initial_omega_share": self.initial_omega_share,
            "initial_alpha": self.initial_alpha,
            "initial_beta": self.initial_beta,
            "initial_nu": self.initial_nu,
            "max_iterations": self.max_iterations,
            "ftol": self.ftol,
            "ewma_decay": self.ewma_decay,
            "ewma_seed_returns": self.ewma_seed_returns,
            "constant_return_tolerance": self.constant_return_tolerance,
        }


@dataclass(frozen=True, slots=True)
class GarchEstimate:
    """What an estimator found, in the units it worked in: percent returns.

    Attributes
    ----------
    converged : bool
        Whether the optimiser reported a maximum.
    loglikelihood : float
        The log-likelihood at the estimate.
    omega, alpha, beta, nu : float
        The estimated parameters; ``omega`` is a variance of percent returns.
    last_filtered_variance : float
        ``h_t`` of the last return of the window, in percent squared.
    forecast_variance : float
        ``h_{t+1|t}``, in percent squared.
    backcast : float
        The variance the filter was started from, in percent squared.
    iterations : int
        Iterations the optimiser took.
    warnings : tuple[str, ...]
        The numerical warnings raised during the fit, kept rather than shown.
    """

    converged: bool
    loglikelihood: float
    omega: float
    alpha: float
    beta: float
    nu: float
    last_filtered_variance: float
    forecast_variance: float
    backcast: float
    iterations: int
    warnings: tuple[str, ...] = ()


Estimator = Callable[[Sequence[float], GarchForecastConfig], GarchEstimate]
"""Fits the model on percent returns, oldest first. Injected so that a refused
fit can be tested without waiting for an optimiser to fail."""


@dataclass(frozen=True, slots=True)
class VolatilityForecast:
    """One forecast of the next session's variance, and how it was obtained.

    Attributes
    ----------
    source : ForecastSource
        The accepted fit, the fallback, or neither.
    variance : float | None
        Forecast variance of the next daily log return, in decimal units.
        ``None`` when even the fallback gave no usable number.
    n_returns : int
        Returns the forecast was computed on.
    fallback_reason : str | None
        One of :data:`FALLBACK_REASONS` when the fit was not used.
    converged : bool | None
        What the optimiser reported; ``None`` when no fit was attempted.
    omega, alpha, beta, nu, persistence : float | None
        The estimate of the fit, accepted or refused, ``omega`` in decimal
        units and ``persistence = alpha + beta``. ``None`` without a fit.
    last_filtered_variance, backcast : float | None
        ``h_t`` of the last return and the filter's starting variance, in
        decimal units.
    loglikelihood : float | None
        Log-likelihood of the fit, on percent returns.
    iterations : int | None
        Iterations the optimiser took.
    warnings : tuple[str, ...]
        Numerical warnings raised during the fit.
    """

    source: ForecastSource
    variance: float | None
    n_returns: int
    fallback_reason: str | None = None
    converged: bool | None = None
    omega: float | None = None
    alpha: float | None = None
    beta: float | None = None
    nu: float | None = None
    persistence: float | None = None
    last_filtered_variance: float | None = None
    backcast: float | None = None
    loglikelihood: float | None = None
    iterations: int | None = None
    warnings: tuple[str, ...] = ()

    def annualized_volatility(self, annualization: int) -> float | None:
        """Return ``sqrt(annualization * variance)``, as a fraction, or ``None`` without one."""
        if self.variance is None:
            return None
        return math.sqrt(annualization * self.variance)

    def diagnostics(self) -> dict[str, object]:
        """Return every field as built-ins, the source by its value."""
        return {
            "forecast_source": self.source.value,
            "forecast_variance": self.variance,
            "n_returns": self.n_returns,
            "fallback_reason": self.fallback_reason,
            "converged": self.converged,
            "omega_decimal": self.omega,
            "alpha": self.alpha,
            "beta": self.beta,
            "nu": self.nu,
            "persistence": self.persistence,
            "last_filtered_variance": self.last_filtered_variance,
            "backcast": self.backcast,
            "loglikelihood": self.loglikelihood,
            "iterations": self.iterations,
            "warnings": " | ".join(self.warnings),
        }


def garch_one_step(
    omega: float, alpha: float, beta: float, last_return: float, last_variance: float
) -> float:
    """Return ``omega + alpha * last_return**2 + beta * last_variance``.

    Parameters
    ----------
    omega, alpha, beta : float
        Parameters of the recursion.
    last_return : float
        The last observed return ``r_t``.
    last_variance : float
        Its filtered variance ``h_t``, in the square of the return's unit.

    Returns
    -------
    float
        The variance forecast for the next return, ``h_{t+1|t}``, in the same
        unit as ``omega`` and ``last_variance``.
    """
    return omega + alpha * last_return**2 + beta * last_variance


def ewma_variance(log_returns: Sequence[float], *, decay: float, seed_returns: int) -> float:
    """Return the exponentially weighted variance of returns around a mean of zero.

    Parameters
    ----------
    log_returns : Sequence[float]
        Daily returns as fractions, oldest first.
    decay : float
        Weight kept of the previous variance, in ``(0, 1)``: ``0.94``.
    seed_returns : int
        Returns whose mean square starts the recursion.

    Returns
    -------
    float
        ``v_n`` of ``v_seed = mean(r_1^2 .. r_seed^2)`` and ``v_i = decay *
        v_{i-1} + (1 - decay) * r_i^2`` for the returns after the seed: the
        variance forecast for the next return, in decimal units. Exactly zero
        on returns that are all zero.

    Raises
    ------
    ValueError
        If the decay is outside ``(0, 1)`` or the seed does not leave at least
        one return after it.
    """
    _require_ewma(len(log_returns), decay, seed_returns)
    variance = math.fsum(value * value for value in log_returns[:seed_returns]) / seed_returns
    for value in log_returns[seed_returns:]:
        variance = decay * variance + (1.0 - decay) * value * value
    return variance


def estimate_with_arch(
    scaled_returns: Sequence[float], config: GarchForecastConfig
) -> GarchEstimate:
    """Fit a zero-mean GARCH(1,1) with Student innovations with the ``arch`` package.

    Parameters
    ----------
    scaled_returns : Sequence[float]
        Daily log returns multiplied by :data:`PERCENT`, oldest first.
    config : GarchForecastConfig
        Gives the starting point and the optimiser's limits.

    Returns
    -------
    GarchEstimate
        The estimate in percent units, whether or not it is admissible:
        judging it is :func:`forecast_garch`'s job.

    Raises
    ------
    MissingDependency
        If ``arch`` is not installed.

    Notes
    -----
    One starting point, no restart: ``(omega, alpha, beta, nu)`` starts at
    ``(initial_omega_share * mean(y^2), initial_alpha, initial_beta,
    initial_nu)``. The filter starts from the library's deterministic
    backcast of the window, computed here and passed explicitly so that it is
    recorded. The forecast is the analytic one at horizon one, aligned on its
    origin. Warnings raised by the optimiser are caught here, and only here,
    and kept on the estimate.
    """
    require_arch()
    # Imported on use: an optional dependency, and the module must import without it.
    from arch import arch_model

    observed = np.asarray(scaled_returns, dtype="float64")
    model = arch_model(
        observed, mean="Zero", vol="GARCH", p=1, o=0, q=1, dist="studentst", rescale=False
    )
    second_moment = float(np.mean(observed**2))
    start = np.array(
        [
            config.initial_omega_share * second_moment,
            config.initial_alpha,
            config.initial_beta,
            config.initial_nu,
        ]
    )
    backcast = float(model.volatility.backcast(observed))
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        fitted = model.fit(
            starting_values=start,
            backcast=backcast,
            disp="off",
            update_freq=0,
            show_warning=True,
            options={"maxiter": config.max_iterations, "ftol": config.ftol},
        )
        forecast = fitted.forecast(horizon=1, align="origin", reindex=False)
    omega, alpha, beta, nu = (float(value) for value in np.asarray(fitted.params))
    return GarchEstimate(
        converged=int(fitted.convergence_flag) == 0,
        loglikelihood=float(fitted.loglikelihood),
        omega=omega,
        alpha=alpha,
        beta=beta,
        nu=nu,
        last_filtered_variance=float(np.asarray(fitted.conditional_volatility)[-1]) ** 2,
        forecast_variance=float(np.asarray(forecast.variance)[-1, 0]),
        backcast=backcast,
        iterations=int(fitted.optimization_result.nit),
        warnings=tuple(f"{item.category.__name__}: {item.message}" for item in caught),
    )


def forecast_garch(
    log_returns: Sequence[float],
    config: GarchForecastConfig,
    *,
    estimator: Estimator = estimate_with_arch,
) -> VolatilityForecast:
    """Forecast the variance of the next daily return from the returns of one window.

    Parameters
    ----------
    log_returns : Sequence[float]
        Daily log returns as fractions, oldest first, every one of them known
        at the decision instant. Exactly ``config.estimation_returns`` of them.
    config : GarchForecastConfig
        The conventions of the fit and of the fallback.
    estimator : Estimator
        What fits the model; the ``arch`` adapter unless a test injects one.

    Returns
    -------
    VolatilityForecast
        The accepted fit's forecast, or the fallback's with the reason the
        fit was refused, in decimal units.

    Raises
    ------
    ValueError
        If the returns are not exactly the configured number or one is not
        finite. Invalid data is the caller's to refuse: it is not a numerical
        failure and it does not reach the fallback.
    MissingDependency
        If a fit is needed and ``arch`` is not installed.

    Notes
    -----
    A fit is accepted when the optimiser converged, the likelihood, the
    parameters, the filtered variance and the forecast are finite, ``omega >
    0``, ``alpha >= 0``, ``beta >= 0``, ``alpha + beta < 1``, ``nu > 2`` and
    the forecast is strictly positive. Returns whose sample standard deviation
    is at or below ``config.constant_return_tolerance`` are not fitted at all.
    """
    returns = [float(value) for value in log_returns]
    if len(returns) != config.estimation_returns:
        raise ValueError(
            f"the forecast is configured for {config.estimation_returns} returns, "
            f"got {len(returns)}"
        )
    if not all(math.isfinite(value) for value in returns):
        raise ValueError("a return is not finite; invalid data is refused before the forecast")
    if statistics.stdev(returns) <= config.constant_return_tolerance:
        return _fallback(returns, config, NEAR_CONSTANT_RETURNS, None)
    estimate = estimator([PERCENT * value for value in returns], config)
    reason = _refusal(estimate)
    if reason is not None:
        return _fallback(returns, config, reason, estimate)
    return _forecast(
        ForecastSource.GARCH,
        estimate.forecast_variance / VARIANCE_SCALE,
        len(returns),
        None,
        estimate,
    )


def _refusal(estimate: GarchEstimate) -> str | None:
    """Return why an estimate is not used, or ``None`` when it is admissible."""
    if not estimate.converged:
        return NOT_CONVERGED
    numbers = (
        estimate.loglikelihood,
        estimate.omega,
        estimate.alpha,
        estimate.beta,
        estimate.nu,
        estimate.last_filtered_variance,
    )
    if not all(math.isfinite(value) for value in numbers):
        return NON_FINITE_ESTIMATE
    admissible = (
        estimate.omega > 0.0
        and estimate.alpha >= 0.0
        and estimate.beta >= 0.0
        and estimate.alpha + estimate.beta < 1.0
        and estimate.nu > 2.0
    )
    if not admissible:
        return INADMISSIBLE_PARAMETERS
    if not math.isfinite(estimate.forecast_variance) or estimate.forecast_variance <= 0.0:
        return INVALID_FORECAST
    return None


def _forecast(
    source: ForecastSource,
    variance: float | None,
    n_returns: int,
    reason: str | None,
    estimate: GarchEstimate | None,
) -> VolatilityForecast:
    """Return a forecast carrying an estimate's numbers in decimal units, if there is one."""
    if estimate is None:
        return VolatilityForecast(
            source=source, variance=variance, n_returns=n_returns, fallback_reason=reason
        )
    return VolatilityForecast(
        source=source,
        variance=variance,
        n_returns=n_returns,
        fallback_reason=reason,
        converged=estimate.converged,
        omega=estimate.omega / VARIANCE_SCALE,
        alpha=estimate.alpha,
        beta=estimate.beta,
        nu=estimate.nu,
        persistence=estimate.alpha + estimate.beta,
        last_filtered_variance=estimate.last_filtered_variance / VARIANCE_SCALE,
        backcast=estimate.backcast / VARIANCE_SCALE,
        loglikelihood=estimate.loglikelihood,
        iterations=estimate.iterations,
        warnings=estimate.warnings,
    )


def _fallback(
    returns: Sequence[float],
    config: GarchForecastConfig,
    reason: str,
    estimate: GarchEstimate | None,
) -> VolatilityForecast:
    """Return the EWMA forecast of valid returns, keeping what the refused fit found."""
    variance = ewma_variance(
        returns, decay=config.ewma_decay, seed_returns=config.ewma_seed_returns
    )
    if math.isfinite(variance) and variance >= 0.0:
        return _forecast(ForecastSource.EWMA_FALLBACK, variance, len(returns), reason, estimate)
    return _forecast(ForecastSource.FALLBACK_FAILED, None, len(returns), reason, estimate)


def _require_ewma(returns: int, decay: float, seed_returns: int) -> None:
    """Raise unless an EWMA of ``returns`` values can be seeded and updated."""
    require_positive_int(seed_returns, "ewma_seed_returns")
    if not (math.isfinite(decay) and 0.0 < decay < 1.0):
        raise ValueError(f"ewma_decay is a weight in (0, 1), got {decay!r}")
    if seed_returns >= returns:
        raise ValueError(
            f"a seed of {seed_returns} returns leaves nothing to update on out of {returns}"
        )


def _valid_returns(window: LoadedWindow) -> list[float] | None:
    """Return the log returns of an ``OK`` window, or ``None`` when a price forbids them."""
    if any(not math.isfinite(point) or point <= 0.0 for point in window.points):
        # A logarithm of a ratio of prices means nothing here: INVALID_INPUT.
        return None
    return returns_of(window, logarithmic=True)


@dataclass(frozen=True, slots=True)
class GarchVolatilitySignal(Signal):
    """The annualised volatility a GARCH(1,1) forecasts for the next session.

    Attributes
    ----------
    signal_id : str
        Stable name, e.g. ``"garch11_t_vol_756r"``.
    config : GarchForecastConfig
        The conventions of the fit and of its fallback.
    price_basis : PriceBasis
        ``ADJUSTED`` for a fund: a dividend is not a shock.
    max_age_sessions : int
        Largest accepted age of the freshest close, on the reference calendar.
    bar_field : BarField
        Field to read.

    Notes
    -----
    The window is ``config.estimation_returns + 1`` closes over consecutive
    sessions. A window that is short, holed, stale or holds a price that is
    not finite and positive gives a status and no number: no fit and no
    fallback is run on it. On a valid window the value is ``sqrt(annualization
    * h_{t+1|t})`` from the accepted fit, or from the EWMA when the fit is
    refused - the status is ``OK`` either way, meaning the number is usable,
    not that GARCH converged; :meth:`diagnose` says which it was. A fallback
    that is itself unusable is ``INVALID_INPUT``.
    """

    signal_id: str
    config: GarchForecastConfig
    price_basis: PriceBasis
    max_age_sessions: int
    bar_field: BarField = BarField.CLOSE

    def __post_init__(self) -> None:
        """Reject an age that is not a count of sessions."""
        require_non_negative_int(self.max_age_sessions, "max_age_sessions")

    def definition(self) -> Mapping[str, object]:
        """Return every parameter that changes the number."""
        return {
            "type": "GarchVolatilitySignal",
            "config": self.config.definition(),
            "bar_field": self.bar_field.value,
            "price_basis": self.price_basis.value,
            "max_age_sessions": self.max_age_sessions,
            "window_mode": WindowMode.CONSECUTIVE_SESSIONS.value,
            "unit": SignalUnit.ANNUALIZED_VOLATILITY.value,
        }

    def window_spec(self) -> WindowSpec:
        """Return the window asked for: one close more than the returns fitted."""
        return WindowSpec(self.config.estimation_returns + 1)

    def compute(self, context: SignalContext, instrument_ids: Sequence[str]) -> SignalResult:
        """Compute each instrument's forecast annualised volatility."""
        return self.compute_window(
            context,
            instrument_ids,
            spec=self.window_spec(),
            bar_field=self.bar_field,
            basis=self.price_basis,
            max_age_sessions=self.max_age_sessions,
            formula=self._volatility,
        )

    def forecast_of(self, window: LoadedWindow) -> VolatilityForecast | None:
        """Return the forecast of an ``OK`` window, ``None`` when its prices forbid returns."""
        returns = _valid_returns(window)
        return None if returns is None else forecast_garch(returns, self.config)

    def diagnose(
        self, context: SignalContext, instrument_id: str
    ) -> tuple[LoadedWindow, VolatilityForecast | None]:
        """Return the window one instrument is read on and the forecast made of it.

        Parameters
        ----------
        context : SignalContext
            Environment of the decision.
        instrument_id : str
            Instrument to read.

        Returns
        -------
        tuple[LoadedWindow, VolatilityForecast | None]
            The window exactly as :meth:`compute` loads it, and the forecast
            with its source, parameters and warnings - ``None`` when the
            window is refused or holds a price no return can be taken of.
            The same pure computation as :meth:`compute`: an export made
            after a run finds the numbers the run decided on.
        """
        window = load_window(
            context,
            instrument_id,
            spec=self.window_spec(),
            bar_field=self.bar_field,
            basis=self.price_basis,
            max_age_sessions=self.max_age_sessions,
        )
        if window.status is not SignalStatus.OK:
            return window, None
        return window, self.forecast_of(window)

    def _volatility(self, window: LoadedWindow) -> float | None:
        """Return the annualised forecast volatility, ``None`` when there is none."""
        forecast = self.forecast_of(window)
        if forecast is None:
            return None
        return forecast.annualized_volatility(self.config.annualization)


@dataclass(frozen=True, slots=True)
class EwmaVolatilitySignal(Signal):
    """The annualised volatility an EWMA of squared returns forecasts for the next session.

    Attributes
    ----------
    signal_id : str
        Stable name, e.g. ``"ewma94_vol_756r"``.
    window_returns : int
        Daily log returns read; the window holds one more close.
    decay : float
        Weight kept of the previous variance, in ``(0, 1)``.
    seed_returns : int
        Returns whose mean square starts the recursion.
    annualization : int
        Sessions per year the daily variance is scaled by.
    price_basis : PriceBasis
        ``ADJUSTED`` or ``RAW``, said explicitly.
    max_age_sessions : int
        Largest accepted age of the freshest close.
    bar_field : BarField
        Field to read.

    Raises
    ------
    ValueError
        If a count is not a positive integer, the decay is outside ``(0, 1)``
        or the seed does not fit the window.

    Notes
    -----
    The control of the GARCH forecast: the same window, the same returns and
    the recursion of :func:`ewma_variance`, with nothing estimated.
    """

    signal_id: str
    window_returns: int
    decay: float
    seed_returns: int
    annualization: int
    price_basis: PriceBasis
    max_age_sessions: int
    bar_field: BarField = BarField.CLOSE

    def __post_init__(self) -> None:
        """Reject a configuration that cannot describe the recursion."""
        require_positive_int(self.window_returns, "window_returns")
        require_positive_int(self.annualization, "annualization")
        require_non_negative_int(self.max_age_sessions, "max_age_sessions")
        _require_ewma(self.window_returns, self.decay, self.seed_returns)

    def definition(self) -> Mapping[str, object]:
        """Return every parameter that changes the number."""
        return {
            "type": "EwmaVolatilitySignal",
            "window_returns": self.window_returns,
            "decay": self.decay,
            "seed_returns": self.seed_returns,
            "annualization": self.annualization,
            "returns": "logarithmic",
            "mean": "Zero",
            "bar_field": self.bar_field.value,
            "price_basis": self.price_basis.value,
            "max_age_sessions": self.max_age_sessions,
            "window_mode": WindowMode.CONSECUTIVE_SESSIONS.value,
            "unit": SignalUnit.ANNUALIZED_VOLATILITY.value,
        }

    def compute(self, context: SignalContext, instrument_ids: Sequence[str]) -> SignalResult:
        """Compute each instrument's EWMA annualised volatility."""
        return self.compute_window(
            context,
            instrument_ids,
            spec=WindowSpec(self.window_returns + 1),
            bar_field=self.bar_field,
            basis=self.price_basis,
            max_age_sessions=self.max_age_sessions,
            formula=self._volatility,
        )

    def _volatility(self, window: LoadedWindow) -> float | None:
        """Return ``sqrt(annualization * v_n)``, ``None`` when a price forbids returns."""
        returns = _valid_returns(window)
        if returns is None:
            return None
        variance = ewma_variance(returns, decay=self.decay, seed_returns=self.seed_returns)
        if not math.isfinite(variance):
            return None
        return math.sqrt(self.annualization * variance)
