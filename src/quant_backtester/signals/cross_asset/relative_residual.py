"""How far a fund has lately strayed from what another fund's moves explain of it."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Final

import numpy as np

from quant_backtester.data.schemas import BarField
from quant_backtester.numbers import require_unit_fraction
from quant_backtester.signals.base import Signal, SignalResult, build_result_frame, result_row
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.types import (
    PriceBasis,
    SignalStatus,
    SignalUnit,
    WindowMode,
    WindowSpec,
    require_identifier,
    require_non_negative_int,
    require_positive_int,
)
from quant_backtester.signals.windows import LoadedWindow, load_window

VARIANCE_FLOOR: Final[float] = 1e-12
"""Below this, the reference's return variance or the spread of the residual
sums is treated as zero, and the signal has no value."""

QUALITY_OK: Final[str] = "OK"
"""The fit explains enough, in the expected direction, for the residual to be read."""

QUALITY_NON_POSITIVE_BETA: Final[str] = "NON_POSITIVE_BETA"
"""The fund moved against the reference, or not with it: the value is zero."""

QUALITY_LOW_R_SQUARED: Final[str] = "LOW_R_SQUARED"
"""The fit explains too little of the fund's variance: the value is zero."""

EXTRA_COLUMNS: Final[tuple[str, ...]] = ("beta", "r_squared", "quality")
"""Diagnostics of the fit, carried beside the usual columns of a result."""


@dataclass(frozen=True, slots=True)
class _Fit:
    """One instrument's regression: the value served and what produced it."""

    value: float
    beta: float
    r_squared: float
    quality: str


@dataclass(frozen=True, slots=True)
class RelativeResidualSignal(Signal):
    """Minus the recent residual of a fund against a reference, in its own spreads.

    Attributes
    ----------
    signal_id : str
        Stable name, e.g. ``"residual_vs_etf_sp500_pea_126r_5r"``.
    reference_id : str
        ``B``, the fund whose returns explain the others.
    estimation_returns : int
        Number of daily log returns the regression is fitted on. They end
        ``recent_returns`` sessions before the decision.
    recent_returns : int
        ``k``, the number of latest returns whose residuals are summed.
    minimum_r_squared : float
        Share of the fund's variance the fit must explain for the residual to
        be read.
    price_basis : PriceBasis
        ``ADJUSTED`` or ``RAW``, said explicitly.
    max_age_sessions : int
        Largest accepted age of the freshest close of either fund.

    Raises
    ------
    ValueError
        If a name is empty, a count is not positive, the estimation window is
        too short to hold two sums of ``k`` residuals, the threshold is not in
        ``[0, 1]``, or the signal is asked about its own reference.
    KeyError
        If an instrument is not registered.

    Notes
    -----
    For a fund ``A``, over the estimation window, ``r_A = a + beta * r_B + e``
    is fitted by least squares. ``a`` and ``beta`` are then frozen and the
    ``k`` following residuals, up to the decision, are computed with them: the
    move being measured never enters the fit that measures it. ``s_k`` is the
    sample standard deviation (``ddof=1``) of every rolling sum of ``k``
    residuals inside the estimation window, and the value is
    ``z = -sum(recent residuals) / s_k``: positive when ``A`` lagged what ``B``
    explains of it.

    When ``beta <= 0`` or ``R^2 < minimum_r_squared`` the relation is not one
    to lean on: the value is ``0.0``, the status stays ``OK`` and the
    ``quality`` column says why. When the reference's variance or ``s_k`` is
    below :data:`VARIANCE_FLOOR`, a price is not positive, the fund's own
    returns do not vary, or the two windows do not hold the same dates, there
    is no value: ``INVALID_INPUT``.

    Both windows are ``estimation_returns + recent_returns + 1`` consecutive
    closes of each fund's venue. A window the reference cannot serve refuses
    every fund with the reference's status.
    """

    signal_id: str
    reference_id: str
    estimation_returns: int
    recent_returns: int
    minimum_r_squared: float
    price_basis: PriceBasis
    max_age_sessions: int = 1

    def __post_init__(self) -> None:
        """Reject a configuration that cannot describe a fit and its residual."""
        require_identifier(self.signal_id, "signal_id")
        require_identifier(self.reference_id, "reference_id")
        require_positive_int(self.estimation_returns, "estimation_returns")
        require_positive_int(self.recent_returns, "recent_returns")
        require_non_negative_int(self.max_age_sessions, "max_age_sessions")
        require_unit_fraction(self.minimum_r_squared, "minimum_r_squared")
        if self.estimation_returns < self.recent_returns + 2:
            raise ValueError(
                f"estimation_returns ({self.estimation_returns}) must exceed recent_returns "
                f"({self.recent_returns}) by at least 2, or the sums of residuals have no spread"
            )

    def definition(self) -> Mapping[str, object]:
        """Return every parameter that changes the number."""
        return {
            "type": "RelativeResidualSignal",
            "reference_id": self.reference_id,
            "estimation_returns": self.estimation_returns,
            "recent_returns": self.recent_returns,
            "estimation_ends_before_recent": True,
            "minimum_r_squared": self.minimum_r_squared,
            "variance_floor": VARIANCE_FLOOR,
            "ddof": 1,
            "bar_field": BarField.CLOSE.value,
            "price_basis": self.price_basis.value,
            "max_age_sessions": self.max_age_sessions,
            "window_mode": WindowMode.CONSECUTIVE_SESSIONS.value,
            "unit": SignalUnit.ZSCORE.value,
        }

    def compute(self, context: SignalContext, instrument_ids: Sequence[str]) -> SignalResult:
        """Compute, for each fund, its normalised recent residual against the reference."""
        if self.reference_id in instrument_ids:
            raise ValueError(
                f"{self.signal_id} is asked about {self.reference_id}, its own reference: a "
                f"fund explains itself perfectly and has no residual"
            )
        reference = self._window(context, self.reference_id)
        rows: dict[str, Mapping[str, object]] = {}
        fits: list[_Fit | None] = []
        for instrument_id in instrument_ids:
            window = self._window(context, instrument_id)
            fit: _Fit | None = None
            if window.status is SignalStatus.OK and reference.status is not SignalStatus.OK:
                window = replace(window, status=reference.status)
            elif window.status is SignalStatus.OK:
                fit = self._fit(window, reference)
                if fit is None:
                    window = replace(window, status=SignalStatus.INVALID_INPUT)
            rows[instrument_id] = result_row(None if fit is None else fit.value, window)
            fits.append(fit)
        frame = build_result_frame(rows)
        frame["beta"] = [float("nan") if fit is None else fit.beta for fit in fits]
        frame["r_squared"] = [float("nan") if fit is None else fit.r_squared for fit in fits]
        frame["quality"] = [None if fit is None else fit.quality for fit in fits]
        return SignalResult(
            signal_id=self.signal_id,
            as_of=context.as_of,
            _frame=frame,
            definition=self.definition(),
        )

    def _window(self, context: SignalContext, instrument_id: str) -> LoadedWindow:
        """Return the consecutive closes one fund's returns are taken from."""
        return load_window(
            context,
            instrument_id,
            spec=WindowSpec(self.estimation_returns + self.recent_returns + 1),
            bar_field=BarField.CLOSE,
            basis=self.price_basis,
            max_age_sessions=self.max_age_sessions,
        )

    def _fit(self, window: LoadedWindow, reference: LoadedWindow) -> _Fit | None:
        """Return the fit of two ``OK`` windows, or ``None`` when it has no meaning."""
        if window.dates != reference.dates:
            return None
        if any(point <= 0 for point in (*window.points, *reference.points)):
            return None
        fund = np.diff(np.log(np.asarray(window.points, dtype="float64")))
        other = np.diff(np.log(np.asarray(reference.points, dtype="float64")))
        count = self.estimation_returns
        explained, explaining = fund[:count], other[:count]
        if float(np.var(explaining, ddof=1)) < VARIANCE_FLOOR:
            return None
        total = float(np.sum((explained - explained.mean()) ** 2))
        if total <= 0.0:
            return None
        design = np.column_stack([np.ones(count), explaining])
        coefficients = np.linalg.lstsq(design, explained, rcond=None)[0]
        intercept, beta = float(coefficients[0]), float(coefficients[1])
        residuals = explained - intercept - beta * explaining
        r_squared = min(1.0, max(0.0, 1.0 - float(np.sum(residuals**2)) / total))
        sums = np.convolve(residuals, np.ones(self.recent_returns), mode="valid")
        spread = float(np.std(sums, ddof=1))
        if spread < VARIANCE_FLOOR:
            return None
        recent = fund[count:] - intercept - beta * other[count:]
        if beta <= 0.0:
            return _Fit(0.0, beta, r_squared, QUALITY_NON_POSITIVE_BETA)
        if r_squared < self.minimum_r_squared:
            return _Fit(0.0, beta, r_squared, QUALITY_LOW_R_SQUARED)
        return _Fit(-float(np.sum(recent)) / spread, beta, r_squared, QUALITY_OK)
