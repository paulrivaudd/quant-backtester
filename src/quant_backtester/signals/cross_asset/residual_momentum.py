"""How strongly a fund has lately beaten what its usual sensitivity to a market explains.

The quantity is the residual momentum of Blitz, Huij and Martens (2011),
adapted to a fund and a single market factor: regress the fund's monthly
returns on the market's, keep the residuals, and score the recent ones in
units of their own dispersion. A sector that merely rose with a rising market
scores near zero; one that rose more than its beta says scores high.

The same window also gives the plain compounded return over the same months,
the "12-1" momentum that ranks on total return. Both measures read the same
month ends, and the total return may be gated on the same market, so a
ranking on either is made among the same eligible funds on the same dates:
the comparison of the two isolates the market correction.

Monthly sampling is explicit and checked by
:func:`~quant_backtester.signals.windows.load_month_end_window`: the grid is
fixed by the decision instant on the reference calendar, each month ends at
the venue's last session on or before its last calendar day, and that
session's close must be in the history. Nothing is filled or interpolated.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from enum import Enum
from typing import Final

from quant_backtester.data.schemas import BarField
from quant_backtester.signals.base import Signal, SignalResult, build_result_frame, result_row
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.types import (
    PriceBasis,
    SignalStatus,
    SignalUnit,
    require_identifier,
    require_non_negative_int,
    require_positive_int,
)
from quant_backtester.signals.windows import (
    MONTH_END_SAMPLING,
    MONTH_END_WINDOW_MODE,
    LoadedWindow,
    load_month_end_window,
)

VARIANCE_FLOOR: Final[float] = 1e-12
"""Below this, the market's monthly return variance or the variance of the
scored residuals is treated as zero, and the residual measure has no value."""


class MomentumMeasure(Enum):
    """What the monthly window is turned into."""

    RESIDUAL = "RESIDUAL"
    """Mean of the scored residuals of the fit on the market, divided by their
    sample standard deviation. Dimensionless."""

    TOTAL = "TOTAL"
    """Compounded return over the scored months, as a fraction. A market, when
    named, is read only as a gate, never in the number."""


@dataclass(frozen=True, slots=True)
class ResidualFit:
    """One fund's regression on the market, and the score it gives.

    Attributes
    ----------
    score : float
        Mean of the scored residuals over their sample standard deviation.
    beta : float
        Slope of the fund's monthly returns on the market's.
    r_squared : float
        Share of the fund's monthly variance the fit explains.
    """

    score: float
    beta: float
    r_squared: float


def simple_returns(points: Sequence[float]) -> list[float] | None:
    """Return the simple returns between successive prices.

    Parameters
    ----------
    points : Sequence[float]
        Prices, oldest first.

    Returns
    -------
    list[float] | None
        ``P_k / P_{k-1} - 1``, one fewer than the prices; ``None`` when a
        price is not finite and strictly positive, which the caller turns into
        ``INVALID_INPUT`` rather than a ``-inf`` in a variance.
    """
    if any(not math.isfinite(point) or point <= 0.0 for point in points):
        return None
    return [points[index] / points[index - 1] - 1.0 for index in range(1, len(points))]


def residual_fit(
    fund: Sequence[float], market: Sequence[float], *, score_months: int, skip_months: int
) -> ResidualFit | None:
    """Fit a fund's returns on the market's and score its recent residuals.

    Parameters
    ----------
    fund, market : Sequence[float]
        Monthly returns over the same months, oldest first.
    score_months : int
        Number of residuals scored.
    skip_months : int
        Number of most recent residuals left out of the score.

    Returns
    -------
    ResidualFit | None
        The score of ``e[n - skip - score : n - skip]``: their mean divided by
        their sample standard deviation (``ddof=1``), with ``e`` the residuals
        of the ordinary least-squares fit ``fund = a + beta * market + e`` on
        all ``n`` months. ``None`` when the market's returns or the scored
        residuals do not vary (variance below :data:`VARIANCE_FLOOR`); a fund
        whose returns do not vary has no residual either.

    Raises
    ------
    ValueError
        If the two samples differ in length or are too short for the score.

    Notes
    -----
    Written as sums rather than through a linear-algebra routine, so the
    arithmetic can be read; the tests compare it with ``numpy.linalg.lstsq``.
    The residuals are those of the fit on the whole window, the scored months
    included, as in the published method: the estimate is backward-looking,
    and the score uses no month after the decision.
    """
    count = len(fund)
    if count != len(market):
        raise ValueError(f"paired samples of {count} and {len(market)} months")
    if score_months < 2 or score_months + skip_months > count:
        raise ValueError(
            f"{count} months cannot hold {score_months} scored and {skip_months} skipped"
        )
    mean_market = math.fsum(market) / count
    mean_fund = math.fsum(fund) / count
    spread_market = math.fsum((value - mean_market) ** 2 for value in market)
    if spread_market / (count - 1) < VARIANCE_FLOOR:
        return None
    together = math.fsum(
        (x - mean_market) * (y - mean_fund) for x, y in zip(market, fund, strict=True)
    )
    beta = together / spread_market
    intercept = mean_fund - beta * mean_market
    residuals = [y - intercept - beta * x for x, y in zip(market, fund, strict=True)]
    stop = count - skip_months
    scored = residuals[stop - score_months : stop]
    mean_scored = math.fsum(scored) / score_months
    variance = math.fsum((value - mean_scored) ** 2 for value in scored) / (score_months - 1)
    if variance < VARIANCE_FLOOR:
        return None
    # The fund's returns vary here: constant ones leave no residual, refused above.
    spread_fund = math.fsum((value - mean_fund) ** 2 for value in fund)
    unexplained = math.fsum(value**2 for value in residuals)
    r_squared = min(1.0, max(0.0, 1.0 - unexplained / spread_fund))
    return ResidualFit(score=mean_scored / math.sqrt(variance), beta=beta, r_squared=r_squared)


@dataclass(frozen=True, slots=True)
class MonthlyMomentumSignal(Signal):
    """Momentum on month-end closes: market-adjusted residuals, or the total return.

    Attributes
    ----------
    signal_id : str
        Stable name, e.g. ``"sa17_residual_vs_sp500_36m_11m_skip1"``.
    measure : MomentumMeasure
        ``RESIDUAL`` or ``TOTAL``, said explicitly.
    market_id : str | None
        The fund whose monthly returns explain the others. Required for
        ``RESIDUAL``. Optional for ``TOTAL``, where it is only a gate: a fund
        is refused with the market's status when the market's window cannot
        be read, so the two measures are defined on the same dates.
    estimation_months : int
        Number of monthly returns in the window, the latest being the month
        of the decision. The fit uses all of them.
    score_months : int
        Number of months scored. At least two.
    skip_months : int
        Number of most recent months left out of the score.
    price_basis : PriceBasis
        ``ADJUSTED`` or ``RAW``, said explicitly. For an accumulating fund the
        two coincide; for a distributing one, ``ADJUSTED`` is the adjusted
        price of the data contract, not a dividend-reinvested wealth.
    max_age_sessions : int
        Largest accepted age of the freshest close of a fund or of the market,
        in sessions of the reference calendar. A Xetra fund read on the last
        Paris session of December, when Xetra is shut on the 31st, is one
        session old.

    Raises
    ------
    ValueError
        If a name is empty, a count is not valid, the scored and skipped
        months do not fit in the window, a residual measure names no market,
        or the signal is asked about its market.
    KeyError
        If an instrument is not registered.

    Notes
    -----
    Both measures need the full window of ``estimation_months + 1`` month-end
    closes of the fund. A fund whose history has not reached the oldest month
    end is ``INSUFFICIENT_HISTORY``. A market whose window cannot be read
    gives every fund the market's status; a fund already refused keeps its
    own. Only the residual measure can be ``INVALID_INPUT`` on valid prices,
    when the scored residuals do not vary.

    The fund and the market are each read on their own venue: a New York
    market and a Xetra fund end the same month at their own last session.
    Their returns are paired by month, not by day. The month grid is dated on
    the reader's reference calendar, which the run records.

    Positive is stronger: a residual score above zero means the fund beat
    what its beta to the market explains, in the scored months.
    """

    signal_id: str
    measure: MomentumMeasure
    market_id: str | None
    estimation_months: int
    score_months: int
    skip_months: int
    price_basis: PriceBasis
    max_age_sessions: int = 1

    def __post_init__(self) -> None:
        """Reject a configuration that cannot describe the window and its score."""
        require_identifier(self.signal_id, "signal_id")
        if not isinstance(self.measure, MomentumMeasure):
            raise ValueError(f"measure must be a MomentumMeasure, got {self.measure!r}")
        if not isinstance(self.price_basis, PriceBasis):
            raise ValueError(f"price_basis must be a PriceBasis, got {self.price_basis!r}")
        if self.market_id is not None:
            require_identifier(self.market_id, "market_id")
        elif self.measure is MomentumMeasure.RESIDUAL:
            raise ValueError("a residual momentum needs a market to fit on")
        require_positive_int(self.estimation_months, "estimation_months")
        require_positive_int(self.score_months, "score_months")
        require_non_negative_int(self.skip_months, "skip_months")
        require_non_negative_int(self.max_age_sessions, "max_age_sessions")
        if self.score_months < 2:
            raise ValueError("score_months must be at least 2: one month has no dispersion")
        if self.score_months + self.skip_months > self.estimation_months:
            raise ValueError(
                f"{self.score_months} scored and {self.skip_months} skipped months do not fit "
                f"in {self.estimation_months}"
            )
        if self.measure is MomentumMeasure.RESIDUAL and self.estimation_months < 3:
            raise ValueError("a fit with a constant needs at least 3 months")

    def definition(self) -> Mapping[str, object]:
        """Return every parameter that changes the number."""
        residual = self.measure is MomentumMeasure.RESIDUAL
        return {
            "type": "MonthlyMomentumSignal",
            "measure": self.measure.value,
            "market_id": self.market_id,
            "market_role": (
                None if self.market_id is None else "REGRESSOR" if residual else "GATE"
            ),
            "estimation_months": self.estimation_months,
            "score_months": self.score_months,
            "skip_months": self.skip_months,
            "returns": "SIMPLE",
            "fit": "OLS_WITH_INTERCEPT_ON_ALL_MONTHS" if residual else None,
            "score": "MEAN_OVER_SAMPLE_STD_OF_SCORED_RESIDUALS" if residual else "COMPOUNDED",
            "ddof": 1 if residual else None,
            "variance_floor": VARIANCE_FLOOR if residual else None,
            "sampling": MONTH_END_SAMPLING,
            "month_grid": "CALENDAR_MONTHS_OF_THE_DECISION_DAY_ON_THE_REFERENCE_CALENDAR",
            "latest_month": "MONTH_TO_DECISION",
            "bar_field": BarField.CLOSE.value,
            "price_basis": self.price_basis.value,
            "max_age_sessions": self.max_age_sessions,
            "window_mode": MONTH_END_WINDOW_MODE,
            "unit": (SignalUnit.ZSCORE if residual else SignalUnit.FRACTION).value,
        }

    def compute(self, context: SignalContext, instrument_ids: Sequence[str]) -> SignalResult:
        """Compute, for each fund, its momentum over the declared months."""
        if self.market_id is not None and self.market_id in instrument_ids:
            raise ValueError(
                f"{self.signal_id} is asked about {self.market_id}, its own market: a fund "
                "explains itself perfectly and has no residual"
            )
        market = None if self.market_id is None else self._window(context, self.market_id)
        residual = self.measure is MomentumMeasure.RESIDUAL
        rows: dict[str, Mapping[str, object]] = {}
        fits: list[ResidualFit | None] = []
        for instrument_id in instrument_ids:
            window = self._window(context, instrument_id)
            value: float | None = None
            fit: ResidualFit | None = None
            if window.status is SignalStatus.OK:
                if market is not None and market.status is not SignalStatus.OK:
                    window = replace(window, status=market.status)
                elif residual and market is not None:
                    fit = self._fit(window, market)
                    value = None if fit is None else fit.score
                else:
                    value = self._total(window)
                if window.status is SignalStatus.OK and value is None:
                    window = replace(window, status=SignalStatus.INVALID_INPUT)
            rows[instrument_id] = result_row(value, window)
            fits.append(fit)
        frame = build_result_frame(rows)
        frame["beta"] = [float("nan") if fit is None else fit.beta for fit in fits]
        frame["r_squared"] = [float("nan") if fit is None else fit.r_squared for fit in fits]
        return SignalResult(
            signal_id=self.signal_id,
            as_of=context.as_of,
            _frame=frame,
            definition=self.definition(),
        )

    def _window(self, context: SignalContext, instrument_id: str) -> LoadedWindow:
        """Return one fund's month-end closes."""
        return load_month_end_window(
            context,
            instrument_id,
            months=self.estimation_months,
            basis=self.price_basis,
            max_age_sessions=self.max_age_sessions,
        )

    def _fit(self, window: LoadedWindow, market: LoadedWindow) -> ResidualFit | None:
        """Return the residual fit of two ``OK`` windows, or ``None`` when it has no meaning."""
        fund_returns = simple_returns(window.points)
        market_returns = simple_returns(market.points)
        if fund_returns is None or market_returns is None:
            return None
        return residual_fit(
            fund_returns,
            market_returns,
            score_months=self.score_months,
            skip_months=self.skip_months,
        )

    def _total(self, window: LoadedWindow) -> float | None:
        """Return the compounded return over the scored months of an ``OK`` window."""
        if simple_returns(window.points) is None:
            return None
        last = len(window.points) - 1 - self.skip_months
        return window.points[last] / window.points[last - self.score_months] - 1.0
