"""A fund's recent residual against another fund: the fit, the sign and the refusals.

Two Paris funds over nine closes: six returns to fit ``r_A = a + beta r_B + e``
on, then two recent ones. ``A`` is built from ``B`` with a known beta and a
small noise, so what moves the signal is known: a move of ``A`` alone does, a
move of ``B`` passed on through beta does not.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Callable, Sequence
from datetime import date, datetime

import pandas as pd
import pytest

from quant_backtester.data.calendars import TradingCalendar
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.data.schemas import BarField
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.cross_asset.relative_residual import (
    QUALITY_LOW_R_SQUARED,
    QUALITY_NON_POSITIVE_BETA,
    QUALITY_OK,
    RelativeResidualSignal,
)
from quant_backtester.signals.types import PriceBasis, SignalStatus

BarsBuilder = Callable[..., pd.DataFrame]
MarketBuilder = Callable[..., MarketDataReader]
ContextBuilder = Callable[[MarketDataReader, datetime], SignalContext]

B_FIT = [0.010, -0.020, 0.015, -0.010, 0.020, -0.005]
"""The reference's six log returns of the estimation window."""


def unexplained(raw: Sequence[float]) -> list[float]:
    """Return ``raw`` less its fit on the reference: zero mean, orthogonal to ``B_FIT``."""
    mean_x, mean_raw = statistics.fmean(B_FIT), statistics.fmean(raw)
    centred = [value - mean_x for value in B_FIT]
    slope = sum(c * r for c, r in zip(centred, raw, strict=True)) / sum(c * c for c in centred)
    return [r - mean_raw - slope * c for c, r in zip(centred, raw, strict=True)]


NOISE = unexplained([0.0010, -0.0010, 0.0020, -0.0020, 0.0005, -0.0005])
"""What of ``A`` the reference does not explain over that window: the fit
gives back exactly the relation ``A`` was built with."""

ALPHA, BETA = 0.0002, 0.9
"""The relation ``A`` is built with."""

NEXT_DAY = date(2026, 9, 15)
"""The session after the decision: a close the decision must not see."""


def signal(**changes: object) -> RelativeResidualSignal:
    """Return the residual of a fund against ``ETF_OTHER``: six returns, then two."""
    fields: dict[str, object] = {
        "signal_id": "residual_vs_etf_other_6r_2r",
        "reference_id": "ETF_OTHER",
        "estimation_returns": 6,
        "recent_returns": 2,
        "minimum_r_squared": 0.50,
        "price_basis": PriceBasis.RAW,
        "max_age_sessions": 0,
    }
    return RelativeResidualSignal(**(fields | changes))  # type: ignore[arg-type]


def explained(reference: Sequence[float], own: Sequence[float]) -> list[float]:
    """Return ``A``'s returns: the relation applied to the reference's, plus its own moves."""
    return [ALPHA + BETA * r + e for r, e in zip(reference, own, strict=True)]


def closes_of(returns: Sequence[float], start: float = 100.0) -> list[float]:
    """Return the closes whose successive log returns are ``returns``."""
    closes = [start]
    for value in returns:
        closes.append(closes[-1] * math.exp(value))
    return closes


def naive(fund: Sequence[float], reference: Sequence[float]) -> tuple[float, float, float]:
    """Return ``(z, beta, r_squared)`` by the textbook formulas, with plain loops."""
    y, x = list(fund[:6]), list(reference[:6])
    mean_x, mean_y = statistics.fmean(x), statistics.fmean(y)
    beta = sum((a - mean_x) * (b - mean_y) for a, b in zip(x, y, strict=True)) / sum(
        (a - mean_x) ** 2 for a in x
    )
    intercept = mean_y - beta * mean_x
    residuals = [b - intercept - beta * a for a, b in zip(x, y, strict=True)]
    r_squared = 1.0 - sum(e**2 for e in residuals) / sum((b - mean_y) ** 2 for b in y)
    sums = [residuals[i] + residuals[i + 1] for i in range(5)]
    recent = [fund[i] - intercept - beta * reference[i] for i in (6, 7)]
    return -sum(recent) / statistics.stdev(sums), beta, r_squared


@pytest.fixture
def context_of(
    make_market: MarketBuilder,
    make_bars: BarsBuilder,
    make_context: ContextBuilder,
    xpar: TradingCalendar,
    sessions: tuple[date, ...],
    evening: Callable[[date], datetime],
) -> Callable[..., SignalContext]:
    """Return a builder of the decision of 14 September from the two funds' returns."""

    def build(
        fund: Sequence[float],
        reference: Sequence[float],
        *,
        future: bool = False,
        contested: date | None = None,
    ) -> SignalContext:
        bars = {}
        for name, returns in (("ETF_EU", fund), ("ETF_OTHER", reference)):
            closes = closes_of(returns)
            days = dict(zip(sessions[-len(closes) :], closes, strict=True))
            if future:
                days[NEXT_DAY] = closes[-1] * (0.5 if name == "ETF_EU" else 2.0)
            holes = {contested: [BarField.CLOSE]} if contested and name == "ETF_OTHER" else None
            bars[name] = make_bars(name, xpar, days, contested=holes)
        return make_context(make_market(bars), evening(sessions[-1]))

    return build


def test_the_value_is_the_recent_residual_in_its_own_spreads(context_of) -> None:
    """The vectorised fit against a naive loop, diagnostics included."""
    reference = [*B_FIT, 0.004, -0.006]
    fund = explained(reference, [*NOISE, -0.004, -0.003])
    z, beta, r_squared = naive(fund, reference)

    result = signal().compute(context_of(fund, reference), ["ETF_EU"])

    assert result.status("ETF_EU") is SignalStatus.OK
    assert result.value("ETF_EU") == pytest.approx(z)
    row = result.frame.loc["ETF_EU"]
    assert row["beta"] == pytest.approx(beta)
    assert row["r_squared"] == pytest.approx(r_squared)
    assert row["quality"] == QUALITY_OK
    assert int(row["observations_used"]) == 9


def test_a_fall_of_the_fund_alone_is_a_positive_value(context_of) -> None:
    reference = [*B_FIT, 0.0, 0.0]
    fund = explained(reference, [*NOISE, -0.010, -0.010])

    assert signal().compute(context_of(fund, reference), ["ETF_EU"]).value("ETF_EU") > 2.0


def test_a_rise_of_the_fund_alone_is_a_negative_value(context_of) -> None:
    reference = [*B_FIT, 0.0, 0.0]
    fund = explained(reference, [*NOISE, 0.010, 0.010])

    assert signal().compute(context_of(fund, reference), ["ETF_EU"]).value("ETF_EU") < -2.0


def test_a_fall_shared_through_beta_is_not_a_signal(context_of) -> None:
    """The reference falls 6% in two sessions and the fund follows by its beta."""
    reference = [*B_FIT, -0.03, -0.03]
    shared = signal().compute(
        context_of(explained(reference, [*NOISE, 0.0, 0.0]), reference), ["ETF_EU"]
    )
    alone = signal().compute(
        context_of(explained([*B_FIT, 0.0, 0.0], [*NOISE, -0.027, -0.027]), [*B_FIT, 0.0, 0.0]),
        ["ETF_EU"],
    )

    assert shared.value("ETF_EU") == pytest.approx(0.0, abs=1e-6)
    assert alone.value("ETF_EU") > 2.0


def test_a_close_published_after_the_decision_changes_nothing(context_of) -> None:
    """The look-ahead guard."""
    reference = [*B_FIT, 0.004, -0.006]
    fund = explained(reference, [*NOISE, -0.004, -0.003])
    seen = signal().compute(context_of(fund, reference), ["ETF_EU"]).value("ETF_EU")

    with_future = signal().compute(context_of(fund, reference, future=True), ["ETF_EU"])

    assert with_future.value("ETF_EU") == seen


def test_a_fund_moving_against_its_reference_is_served_zero(context_of) -> None:
    reference = [*B_FIT, 0.004, -0.006]
    fund = [-value for value in explained(reference, [*NOISE, -0.004, -0.003])]

    result = signal().compute(context_of(fund, reference), ["ETF_EU"])

    assert result.status("ETF_EU") is SignalStatus.OK
    assert result.value("ETF_EU") == 0.0
    assert result.frame.loc["ETF_EU", "quality"] == QUALITY_NON_POSITIVE_BETA
    assert result.frame.loc["ETF_EU", "beta"] < 0.0


def test_a_fit_that_explains_too_little_is_served_zero(context_of) -> None:
    reference = [*B_FIT, 0.004, -0.006]
    # A noise orthogonal to the reference's returns: beta stays 0.9, the fit explains little.
    fund = explained(reference, [0.03, 0.03, 0.03, -0.03, -0.03, -0.03, -0.004, -0.003])

    result = signal().compute(context_of(fund, reference), ["ETF_EU"])

    assert result.status("ETF_EU") is SignalStatus.OK
    assert result.value("ETF_EU") == 0.0
    assert result.frame.loc["ETF_EU", "quality"] == QUALITY_LOW_R_SQUARED
    assert 0.0 <= result.frame.loc["ETF_EU", "r_squared"] < 0.50


def test_a_reference_that_did_not_move_has_no_value(context_of) -> None:
    result = signal().compute(context_of([*NOISE, 0.001, 0.002], [0.0] * 8), ["ETF_EU"])

    assert result.status("ETF_EU") is SignalStatus.INVALID_INPUT
    assert math.isnan(result.value("ETF_EU"))
    assert result.frame.loc["ETF_EU", "quality"] is None


def test_a_fund_that_is_exactly_its_reference_has_no_spread_to_divide_by(context_of) -> None:
    reference = [*B_FIT, 0.004, -0.006]

    result = signal().compute(context_of(explained(reference, [0.0] * 8), reference), ["ETF_EU"])

    assert result.status("ETF_EU") is SignalStatus.INVALID_INPUT


def test_a_window_the_reference_cannot_serve_refuses_the_fund(context_of, sessions) -> None:
    reference = [0.003, *B_FIT, 0.004, -0.006]
    fund = explained(reference, [0.0, *NOISE, -0.004, -0.003])

    result = signal().compute(context_of(fund, reference, contested=sessions[4]), ["ETF_EU"])

    assert result.status("ETF_EU") is SignalStatus.NON_CONSECUTIVE_HISTORY


def test_too_short_a_history_has_no_value(context_of) -> None:
    reference = [*B_FIT, 0.004]
    fund = explained(reference, [*NOISE, -0.004])

    result = signal().compute(context_of(fund, reference), ["ETF_EU"])

    assert result.status("ETF_EU") is SignalStatus.INSUFFICIENT_HISTORY


def test_two_venues_that_do_not_hold_the_same_sessions_have_no_value(
    context: SignalContext,
) -> None:
    """New York was shut on 7 September: the two windows are not the same dates."""
    result = signal(reference_id="IDX_US", estimation_returns=4, recent_returns=2).compute(
        context, ["ETF_EU"]
    )

    assert result.status("ETF_EU") is SignalStatus.INVALID_INPUT


def test_the_reference_has_no_residual_on_itself(context: SignalContext) -> None:
    with pytest.raises(ValueError, match="own reference"):
        signal().compute(context, ["ETF_OTHER"])


@pytest.mark.parametrize(
    "changes",
    [
        {"estimation_returns": 3},
        {"recent_returns": 0},
        {"minimum_r_squared": 1.5},
        {"reference_id": " "},
        {"max_age_sessions": -1},
    ],
)
def test_a_configuration_that_cannot_be_computed_is_refused(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        signal(**changes)
