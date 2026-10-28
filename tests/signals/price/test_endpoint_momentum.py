"""Exact endpoint dates, sparse interiors, venue holidays and information cutoffs."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from quant_backtester.data.calendars import TradingCalendar
from quant_backtester.data.schemas import BarField
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.price.endpoint_momentum import EndpointMomentumSignal
from quant_backtester.signals.types import PriceBasis, SignalStatus

DAYS = (
    date(2026, 9, 1),
    date(2026, 9, 2),
    date(2026, 9, 3),
    date(2026, 9, 4),
    date(2026, 9, 7),
    date(2026, 9, 8),
    date(2026, 9, 9),
    date(2026, 9, 10),
    date(2026, 9, 11),
    date(2026, 9, 14),
)


def signal(lookback: int = 5, skip: int = 0, **changes: object) -> EndpointMomentumSignal:
    """Return the exact-endpoint rule with explicit window identity."""
    fields: dict[str, object] = {
        "signal_id": f"endpoint_{lookback}s_skip{skip}",
        "lookback_sessions": lookback,
        "skip_recent_sessions": skip,
    }
    return EndpointMomentumSignal(**(fields | changes))  # type: ignore[arg-type]


def test_hand_computed_ratio_uses_two_endpoints_and_actual_dates(context: SignalContext) -> None:
    result = signal().compute(context, ["ETF_EU"])
    row = result.frame.loc["ETF_EU"]
    assert result.status("ETF_EU") is SignalStatus.OK
    assert result.value("ETF_EU") == pytest.approx(109 / 104 - 1)
    assert row["input_start_date"] == DAYS[4]
    assert row["input_end_date"] == DAYS[-1]
    assert row["observations_used"] == 2
    assert row["max_input_age_sessions"] == 0
    assert result.definition["endpoint_mode"] == "EXACT_VENUE_SESSION_OFFSETS"
    assert result.definition["observations_consumed"] == 2


def test_skip_moves_recent_endpoint_without_changing_the_freshness_anchor(context) -> None:
    result = signal(5, 2).compute(context, ["ETF_EU"])
    row = result.frame.loc["ETF_EU"]
    assert result.value("ETF_EU") == pytest.approx(107 / 104 - 1)
    assert row["input_start_date"] == DAYS[4]
    assert row["input_end_date"] == DAYS[7]
    assert row["observations_used"] == 2
    assert row["max_input_age_sessions"] == 0
    assert signal(5, 2).fingerprint() != signal(5, 0).fingerprint()


@pytest.fixture
def endpoint_context(make_market, make_bars, make_context, evening, xpar):
    """Build the same evening market while adding or removing observations."""

    def build(closes: dict[date, float]) -> SignalContext:
        return make_context(
            make_market({"ETF_EU": make_bars("ETF_EU", xpar, closes)}),
            evening(DAYS[-1]),
        )

    return build


def test_missing_internal_sessions_do_not_change_the_endpoint_return(endpoint_context) -> None:
    prices = {day: 100.0 + index for index, day in enumerate(DAYS)}
    complete = signal().compute(endpoint_context(prices), ["ETF_EU"])
    sparse = {day: value for day, value in prices.items() if day not in {DAYS[5], DAYS[6], DAYS[8]}}
    result = signal().compute(endpoint_context(sparse), ["ETF_EU"])
    assert result.frame.equals(complete.frame)


@pytest.mark.parametrize("missing", [DAYS[4], DAYS[7], DAYS[-1]])
def test_a_required_endpoint_or_latest_anchor_cannot_be_filled(endpoint_context, missing) -> None:
    prices = {day: 100.0 + index for index, day in enumerate(DAYS) if day != missing}
    result = signal(5, 2).compute(endpoint_context(prices), ["ETF_EU"])
    assert result.status("ETF_EU") is SignalStatus.MISSING_INPUT
    assert not result.ok().shape[0]


def test_only_the_two_required_prices_are_needed_when_latest_is_the_recent_endpoint(
    endpoint_context,
) -> None:
    prices = {DAYS[4]: 104.0, DAYS[-1]: 109.0}
    result = signal().compute(endpoint_context(prices), ["ETF_EU"])
    assert result.status("ETF_EU") is SignalStatus.OK
    assert result.value("ETF_EU") == pytest.approx(109 / 104 - 1)


def test_a_single_latest_close_reports_the_absent_old_endpoint(endpoint_context) -> None:
    result = signal().compute(endpoint_context({DAYS[-1]: 109.0}), ["ETF_EU"])
    assert result.status("ETF_EU") is SignalStatus.MISSING_INPUT
    assert result.frame.loc["ETF_EU", "observations_used"] == 1


def test_skipped_latest_anchor_is_still_mandatory(endpoint_context) -> None:
    prices = {DAYS[4]: 104.0, DAYS[7]: 107.0}
    assert (
        signal(5, 2).compute(endpoint_context(prices), ["ETF_EU"]).status("ETF_EU")
        is SignalStatus.MISSING_INPUT
    )


def test_calendar_coverage_and_listing_history_are_not_invented(context) -> None:
    result = signal(300).compute(context, ["ETF_EU"])
    assert result.status("ETF_EU") is SignalStatus.INSUFFICIENT_HISTORY
    result = signal(6).compute(context, ["ETF_LATE"])
    assert result.status("ETF_LATE") is SignalStatus.INSUFFICIENT_HISTORY


def test_future_bars_do_not_change_values_or_diagnostics(endpoint_context) -> None:
    prices = {day: 100.0 + index for index, day in enumerate(DAYS)}
    before = signal(5, 2).compute(endpoint_context(prices), ["ETF_EU"])
    prices[date(2026, 9, 15)] = 1_000_000.0
    after = signal(5, 2).compute(endpoint_context(prices), ["ETF_EU"])
    assert after.frame.equals(before.frame)


def test_latest_anchor_and_offsets_follow_the_instruments_own_venue(
    make_market,
    make_bars,
    make_context,
    evening,
    xnys: TradingCalendar,
) -> None:
    prices = {day: 100.0 + index for index, day in enumerate(DAYS[:4])}
    context = make_context(
        make_market({"ETF_US": make_bars("ETF_US", xnys, prices)}),
        evening(DAYS[4]),
    )
    result = signal(3).compute(context, ["ETF_US"])
    assert result.status("ETF_US") is SignalStatus.OK
    assert result.value("ETF_US") == pytest.approx(103 / 100 - 1)
    assert result.frame.loc["ETF_US", "input_end_date"] == date(2026, 9, 4)
    assert result.frame.loc["ETF_US", "max_input_age_sessions"] == 1
    assert (
        signal(3, max_age_sessions=0).compute(context, ["ETF_US"]).status("ETF_US")
        is SignalStatus.STALE_INPUT
    )


def test_not_yet_available_same_day_us_close_does_not_enter_an_endpoint(
    make_market,
    make_bars,
    make_context,
    xnys: TradingCalendar,
) -> None:
    us_days = [day for day in DAYS if day != date(2026, 9, 7)]
    closes = {day: 100.0 + index for index, day in enumerate(us_days)}
    reader = make_market({"ETF_US": make_bars("ETF_US", xnys, closes)})
    context = make_context(reader, datetime(2026, 9, 14, 17, 0, tzinfo=UTC))
    result = signal(3).compute(context, ["ETF_US"])
    assert result.status("ETF_US") is SignalStatus.OK
    assert result.frame.loc["ETF_US", "input_end_date"] == date(2026, 9, 11)
    assert result.value("ETF_US") == pytest.approx(107 / 104 - 1)


def test_nonpositive_endpoint_prices_are_invalid(endpoint_context) -> None:
    result = signal().compute(endpoint_context({DAYS[4]: 0.0, DAYS[-1]: 109.0}), ["ETF_EU"])
    assert result.status("ETF_EU") is SignalStatus.INVALID_INPUT


def test_empty_universe_and_non_bar_series_have_explicit_contracts(context) -> None:
    assert signal().compute(context, []).frame.empty
    with pytest.raises(ValueError, match="BAR instrument"):
        signal().compute(context, ["RATE_US"])


@pytest.mark.parametrize(
    "changes",
    [
        {"lookback_sessions": 0},
        {"lookback_sessions": True},
        {"lookback_sessions": 1.5},
        {"skip_recent_sessions": -1},
        {"skip_recent_sessions": True},
        {"skip_recent_sessions": 5},
        {"max_age_sessions": True},
        {"max_age_sessions": -1},
        {"signal_id": ""},
        {"price_basis": "ADJUSTED"},
        {"bar_field": BarField.OPEN},
    ],
)
def test_invalid_signal_configuration_is_rejected(changes) -> None:
    with pytest.raises(ValueError):
        signal(**changes)


def test_explicit_raw_prices_change_the_recorded_definition() -> None:
    assert signal().definition() != signal(price_basis=PriceBasis.RAW).definition()


def test_latest_anchor_must_be_the_expected_venue_close_even_when_loader_allows_age_one(
    endpoint_context,
    monkeypatch,
) -> None:
    from quant_backtester.signals.windows import LoadedWindow

    prices = {day: 100.0 + index for index, day in enumerate(DAYS)}
    context = endpoint_context(prices)
    previous = LoadedWindow(
        status=SignalStatus.OK,
        points=(107.0, 108.0),
        dates=(DAYS[7], DAYS[8]),
        age_sessions=1,
    )
    monkeypatch.setattr(
        "quant_backtester.signals.price.endpoint_momentum.load_window",
        lambda *_args, **_kwargs: previous,
    )
    result = signal().compute(context, ["ETF_EU"])
    assert result.status("ETF_EU") is SignalStatus.MISSING_INPUT
    assert result.frame.loc["ETF_EU", "max_input_age_sessions"] == 1
