"""Fitted models used as signals.

A model brings a training window, a refit schedule and possibly an artifact to
version, none of which can be bolted on afterwards without putting look-ahead
back in.

``garch`` holds the first one fitted inside a decision: a GARCH(1,1) forecast
of the next session's variance, estimated again at every decision on a rolling
window of returns known at that instant, with an EWMA of the same returns as
its declared fallback and as its control. It keeps no state and no artifact.
Its estimator is the ``arch`` package, an optional dependency (the ``stats``
extra) imported when a fit is asked for: everything exported here imports
without it.

The neural allocation lives in ``signals.ml`` beside ``quant_backtester.ml``,
which holds its training window, its artifact and its information cutoff.
"""

from __future__ import annotations

from quant_backtester.signals.models.garch import (
    EwmaVolatilitySignal,
    ForecastSource,
    GarchEstimate,
    GarchForecastConfig,
    GarchVolatilitySignal,
    MissingDependency,
    VolatilityForecast,
    ewma_variance,
    forecast_garch,
    garch_one_step,
    require_arch,
)

__all__ = [
    "EwmaVolatilitySignal",
    "ForecastSource",
    "GarchEstimate",
    "GarchForecastConfig",
    "GarchVolatilitySignal",
    "MissingDependency",
    "VolatilityForecast",
    "ewma_variance",
    "forecast_garch",
    "garch_one_step",
    "require_arch",
]
