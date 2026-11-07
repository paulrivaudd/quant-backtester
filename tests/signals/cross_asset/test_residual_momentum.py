"""Monthly momentum on month-end closes: market-adjusted residuals, or the total return."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest

from quant_backtester.data.calendars import TradingCalendar
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.data.schemas import BarField
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.cross_asset.residual_momentum import (
    MomentumMeasure,
    MonthlyMomentumSignal,
    residual_fit,
)
from quant_backtester.signals.types import PriceBasis, SignalStatus
from quant_backtester.signals.windows import month_end_anchors

DECIDED = date(2026, 10, 30)
"""The last Paris session of October 2026, a Friday New York also trades."""

MONTH_ENDS = (
    date(2026, 4, 30),
    date(2026, 5, 29),  # 31 May is a Sunday: the month ends on the Friday before
    date(2026, 6, 30),
    date(2026, 7, 31),
    date(2026, 8, 31),
    date(2026, 9, 30),
    DECIDED,
)
"""The seven month ends a six-month window reads on 30 October, on either venue."""

MARKET = {1: 100.0, 2: 100.0, 3: 100.0, 4: 100.0, 5: 102.0, 6: 100.0}
MARKET |= {7: 104.0, 8: 105.0, 9: 103.0, 10: 106.0, 11: 107.0, 12: 108.0}
"""Month-end level of ``IDX_US`` by month of 2026; every close of a month is it."""

FUND = {1: 50.0, 2: 50.0, 3: 50.0, 4: 50.0, 5: 51.5, 6: 50.2}
FUND |= {7: 52.9, 8: 53.8, 9: 52.5, 10: 54.4, 11: 55.0, 12: 56.0}
"""Month-end level of ``ETF_EU``: close to the market, not a multiple of it."""


def shadow(levels: Mapping[int, float], multiple: float, start: float) -> dict[int, float]:
    """Return levels whose monthly returns are exactly ``multiple`` times those given."""
    shadowed, price = {}, start
    for month in sorted(levels):
        if month > 1:
            price *= 1.0 + multiple * (levels[month] / levels[month - 1] - 1.0)
        shadowed[month] = price
    return shadowed


def monthly(
    calendar: TradingCalendar,
    levels: Mapping[int, float],
    first: date,
    last: date = DECIDED,
) -> dict[date, float]:
    """Return a close for every session from ``first`` to ``last``: its month's level."""
    return {
        session.session_date: levels[session.session_date.month]
        for session in calendar.sessions(first, last)
    }


def signal(
    measure: MomentumMeasure = MomentumMeasure.RESIDUAL, **changes: object
) -> MonthlyMomentumSignal:
    """Return a six-month window scored on three months, skipping the latest."""
    parameters: dict[str, object] = {
        "signal_id": "monthly_momentum",
        "measure": measure,
        "market_id": "IDX_US" if measure is MomentumMeasure.RESIDUAL else None,
        "estimation_months": 6,
        "score_months": 3,
        "skip_months": 1,
        "price_basis": PriceBasis.ADJUSTED,
        "max_age_sessions": 1,
    }
    return MonthlyMomentumSignal(**(parameters | changes))  # type: ignore[arg-type]


@pytest.fixture
def build(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    make_context: Callable[[MarketDataReader, datetime], SignalContext],
    xpar: TradingCalendar,
    xnys: TradingCalendar,
    evening: Callable[[date], datetime],
) -> Callable[..., SignalContext]:
    """Return a builder of the context of a decision on a monthly market.

    ``ETF_EU`` follows :data:`FUND`, ``ETF_OTHER`` moves exactly 1.5 times the
    market, ``IDX_US`` follows :data:`MARKET` on New York's sessions, and
    ``ETF_LATE`` lists on 9 September.
    """

    def make(
        *,
        last: date = DECIDED,
        instant: datetime | None = None,
        contested: Mapping[str, Sequence[date]] | None = None,
        future: bool = False,
    ) -> SignalContext:
        holes = contested or {}
        end = date(2026, 12, 31) if future else last
        series = {
            "ETF_EU": (xpar, FUND, date(2026, 1, 5)),
            "ETF_OTHER": (xpar, shadow(MARKET, 1.5, 80.0), date(2026, 1, 5)),
            "IDX_US": (xnys, MARKET, date(2026, 1, 2)),
            "ETF_LATE": (xpar, FUND, date(2026, 9, 9)),
        }
        bars = {}
        for name, (calendar, levels, first) in series.items():
            if first > end:
                continue  # not listed yet: the store holds nothing of it
            closes = monthly(calendar, levels, first, end)
            if future:
                closes = {day: price if day <= last else 1e6 for day, price in closes.items()}
            bars[name] = make_bars(
                name,
                calendar,
                closes,
                contested={day: [BarField.CLOSE] for day in holes.get(name, ())},
            )
        return make_context(make_market(bars), instant or evening(last))

    return make


def returns_at_month_ends(levels: Mapping[int, float]) -> np.ndarray:
    """Return the six monthly returns from April to October, oldest first."""
    points = np.array([levels[month] for month in range(4, 11)])
    return points[1:] / points[:-1] - 1.0


def test_the_month_ends_are_the_last_calendar_days_then_the_decision() -> None:
    assert month_end_anchors(date(2026, 2, 27), 3) == (
        date(2025, 11, 30),
        date(2025, 12, 31),
        date(2026, 1, 31),
        date(2026, 2, 27),
    )
    assert month_end_anchors(date(2024, 3, 15), 1) == (date(2024, 2, 29), date(2024, 3, 15))


def test_total_return_is_the_compounded_return_of_the_scored_months(build) -> None:
    result = signal(MomentumMeasure.TOTAL).compute(build(), ["ETF_EU"])
    # Scored: July, August, September (October is skipped): end of September
    # over end of June.
    assert result.status("ETF_EU") is SignalStatus.OK
    assert result.value("ETF_EU") == pytest.approx(52.5 / 50.2 - 1.0)
    frame = result.frame
    assert frame.loc["ETF_EU", "input_start_date"] == MONTH_ENDS[0]
    assert frame.loc["ETF_EU", "input_end_date"] == DECIDED
    assert frame.loc["ETF_EU", "observations_used"] == 7


def test_residual_score_matches_a_least_squares_fit(build) -> None:
    result = signal().compute(build(), ["ETF_EU"])
    fund, market = returns_at_month_ends(FUND), returns_at_month_ends(MARKET)
    design = np.column_stack([np.ones(6), market])
    (intercept, beta), *_ = np.linalg.lstsq(design, fund, rcond=None)
    residuals = fund - intercept - beta * market
    scored = residuals[2:5]  # July, August, September
    assert result.status("ETF_EU") is SignalStatus.OK
    assert result.value("ETF_EU") == pytest.approx(scored.mean() / scored.std(ddof=1))
    assert result.frame.loc["ETF_EU", "beta"] == pytest.approx(beta)
    total = float(np.sum((fund - fund.mean()) ** 2))
    r_squared = 1.0 - float(np.sum(residuals**2)) / total
    assert result.frame.loc["ETF_EU", "r_squared"] == pytest.approx(r_squared)


def test_residual_fit_written_as_sums_matches_numpy_on_random_samples(rng_seed) -> None:
    rng = np.random.default_rng(rng_seed)
    for _ in range(20):
        market = rng.normal(0.01, 0.04, 36)
        fund = 0.002 + rng.uniform(0.5, 1.5) * market + rng.normal(0.0, 0.02, 36)
        fit = residual_fit(list(fund), list(market), score_months=11, skip_months=1)
        assert fit is not None
        design = np.column_stack([np.ones(36), market])
        (intercept, beta), *_ = np.linalg.lstsq(design, fund, rcond=None)
        scored = (fund - intercept - beta * market)[24:35]
        assert fit.beta == pytest.approx(beta, rel=1e-10)
        assert fit.score == pytest.approx(scored.mean() / scored.std(ddof=1), rel=1e-9)


def test_a_fund_that_is_a_multiple_of_the_market_has_no_residual(build) -> None:
    result = signal().compute(build(), ["ETF_OTHER"])
    assert result.status("ETF_OTHER") is SignalStatus.INVALID_INPUT
    assert np.isnan(result.value("ETF_OTHER"))


def test_a_month_end_the_provider_did_not_serve_is_missing(build) -> None:
    context = build(contested={"ETF_EU": [date(2026, 8, 31)]})
    result = signal().compute(context, ["ETF_EU"])
    assert result.status("ETF_EU") is SignalStatus.MISSING_INPUT
    assert date(2026, 8, 31) not in (
        result.frame.loc["ETF_EU", "input_start_date"],
        result.frame.loc["ETF_EU", "input_end_date"],
    )


def test_a_hole_inside_a_month_changes_nothing(build) -> None:
    whole = signal().compute(build(), ["ETF_EU"])
    holed = signal().compute(build(contested={"ETF_EU": [date(2026, 8, 12)]}), ["ETF_EU"])
    assert holed.status("ETF_EU") is SignalStatus.OK
    assert holed.value("ETF_EU") == whole.value("ETF_EU")


def test_a_market_that_cannot_be_read_refuses_every_fund(build) -> None:
    context = build(contested={"IDX_US": [date(2026, 6, 30)]})
    result = signal().compute(context, ["ETF_EU", "ETF_OTHER"])
    assert result.status("ETF_EU") is SignalStatus.MISSING_INPUT
    assert result.status("ETF_OTHER") is SignalStatus.MISSING_INPUT
    # The total return reads no market, and does not mind...
    total = signal(MomentumMeasure.TOTAL).compute(context, ["ETF_EU"])
    assert total.status("ETF_EU") is SignalStatus.OK
    # ...unless the market gates it, so that both measures share their dates.
    gated = signal(MomentumMeasure.TOTAL, market_id="IDX_US").compute(context, ["ETF_EU"])
    assert gated.status("ETF_EU") is SignalStatus.MISSING_INPUT


def test_a_gated_total_return_is_the_same_number(build) -> None:
    plain = signal(MomentumMeasure.TOTAL).compute(build(), ["ETF_EU"])
    gated = signal(MomentumMeasure.TOTAL, market_id="IDX_US").compute(build(), ["ETF_EU"])
    assert gated.value("ETF_EU") == plain.value("ETF_EU")
    assert gated.definition["market_role"] == "GATE"
    assert signal().definition()["market_role"] == "REGRESSOR"


def test_a_fund_too_young_for_the_window_is_not_yet_eligible(build) -> None:
    result = signal().compute(build(), ["ETF_EU", "ETF_LATE"])
    assert result.status("ETF_EU") is SignalStatus.OK
    assert result.status("ETF_LATE") is SignalStatus.INSUFFICIENT_HISTORY
    # Ten months reach back to December 2025, before any history and before the
    # synthetic calendars begin: the calendar is not consulted there.
    longer = signal(estimation_months=10).compute(build(), ["ETF_EU"])
    assert longer.status("ETF_EU") is SignalStatus.INSUFFICIENT_HISTORY


@pytest.mark.parametrize("measure", list(MomentumMeasure))
def test_a_young_fund_with_a_late_bar_is_still_only_not_yet_eligible(build, measure) -> None:
    # The fund could not be eligible anyway: its missing latest close is not a
    # failure that should cancel a decision about the funds that are.
    context = build(contested={"ETF_LATE": [DECIDED]})
    result = signal(measure).compute(context, ["ETF_EU", "ETF_LATE"])
    assert result.status("ETF_EU") is SignalStatus.OK
    assert result.status("ETF_LATE") is SignalStatus.INSUFFICIENT_HISTORY
    older = build(contested={"ETF_EU": [DECIDED]})
    assert signal(measure).compute(older, ["ETF_EU"]).status("ETF_EU") is (
        SignalStatus.MISSING_INPUT
    )


def test_a_fund_not_listed_yet_is_not_listed(build) -> None:
    result = signal().compute(build(last=date(2026, 8, 31)), ["ETF_LATE"])
    assert result.status("ETF_LATE") is SignalStatus.NOT_LISTED


def test_a_close_older_than_allowed_is_stale(build) -> None:
    # 7 September: New York is shut, and its freshest close is a session old.
    context = build(last=date(2026, 9, 7))
    assert signal(max_age_sessions=1).compute(context, ["ETF_EU"]).status("ETF_EU") is (
        SignalStatus.OK
    )
    assert signal(max_age_sessions=0).compute(context, ["ETF_EU"]).status("ETF_EU") is (
        SignalStatus.STALE_INPUT
    )


def test_a_freshest_close_from_a_month_already_closed_is_stale(build) -> None:
    # At noon on 1 October, the freshest close is 30 September's: fresh enough
    # in sessions, but October would have no return of its own.
    context = build(
        last=date(2026, 10, 1), instant=datetime.fromisoformat("2026-10-01T12:00:00+02:00")
    )
    result = signal(MomentumMeasure.TOTAL).compute(context, ["ETF_EU"])
    assert result.status("ETF_EU") is SignalStatus.STALE_INPUT


def test_month_ends_are_read_on_each_venue(build) -> None:
    context = build()
    for name in ("ETF_EU", "IDX_US"):
        frame = signal(MomentumMeasure.TOTAL).compute(context, [name]).frame
        assert frame.loc[name, "input_start_date"] == MONTH_ENDS[0]
        assert frame.loc[name, "observations_used"] == len(MONTH_ENDS)


@pytest.mark.parametrize("measure", list(MomentumMeasure))
def test_prices_after_the_decision_change_nothing(build, measure) -> None:
    names = ["ETF_EU", "ETF_LATE"]
    before = signal(measure).compute(build(), names)
    after = signal(measure).compute(build(future=True), names)
    assert before.frame.equals(after.frame)


def test_definition_is_complete_and_serialisable() -> None:
    definition = signal().definition()
    json.dumps(dict(definition))
    assert definition["measure"] == "RESIDUAL"
    assert definition["market_id"] == "IDX_US"
    assert definition["window_mode"] == "EXPECTED_MONTH_END_SESSIONS"
    assert definition["latest_month"] == "MONTH_TO_DECISION"
    assert signal().fingerprint() != signal(skip_months=0).fingerprint()
    assert signal(MomentumMeasure.TOTAL).definition()["unit"] == "FRACTION"


def test_a_currency_guard_alone_records_the_grid_it_actually_reads() -> None:
    # The guard does not switch _window to exact observation dates, so the
    # definition must not say it did.
    guarded = signal(required_currency="USD").definition()
    assert guarded["required_currency"] == "USD"
    assert guarded["month_grid"] == "CALENDAR_MONTHS_OF_THE_DECISION_DAY_ON_THE_REFERENCE_CALENDAR"
    assert guarded["bar_field"] == BarField.CLOSE.value
    assert guarded["latest_month"] == "MONTH_TO_DECISION"
    exact = signal(required_currency="USD", observation_calendar_id="XNYS").definition()
    assert exact["month_grid"] == "EXACT_OBSERVATION_CALENDAR_MONTH_ENDS"
    assert exact["bar_field"] == "LEVEL_OR_CLOSE"
    # The exact-date contract does not read the freshest close's age.
    assert exact["max_age_sessions"] is None
    assert guarded["max_age_sessions"] == 1
    assert signal(completed_months_only=True).definition()["month_grid"] == (
        "EXACT_OBSERVATION_CALENDAR_MONTH_ENDS"
    )


def test_the_market_is_declared_as_read_beside_the_funds() -> None:
    assert signal().referenced_instruments() == ("IDX_US",)
    assert signal(MomentumMeasure.TOTAL).referenced_instruments() == ()


def test_a_published_series_or_the_market_itself_is_refused(build) -> None:
    context = build()
    with pytest.raises(ValueError, match="its own market"):
        signal().compute(context, ["ETF_EU", "IDX_US"])
    with pytest.raises(ValueError, match="holds no venue"):
        signal(MomentumMeasure.TOTAL).compute(context, ["RATE_US"])


@pytest.mark.parametrize(
    ("measure", "changes"),
    [
        (MomentumMeasure.RESIDUAL, {"market_id": None}),
        (MomentumMeasure.TOTAL, {"market_id": " "}),
        (MomentumMeasure.RESIDUAL, {"score_months": 1}),
        (MomentumMeasure.RESIDUAL, {"score_months": 6, "skip_months": 1}),
        (MomentumMeasure.RESIDUAL, {"estimation_months": 2, "score_months": 2, "skip_months": 0}),
        (MomentumMeasure.RESIDUAL, {"skip_months": -1}),
        (MomentumMeasure.RESIDUAL, {"max_age_sessions": -1}),
        (MomentumMeasure.RESIDUAL, {"signal_id": " "}),
        (MomentumMeasure.RESIDUAL, {"price_basis": "ADJUSTED"}),
    ],
)
def test_invalid_configurations_are_refused(measure, changes) -> None:
    with pytest.raises(ValueError):
        signal(measure, **changes)
