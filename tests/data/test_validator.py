"""Validation rules are typed by instrument, not universal.

Synthetic canonical bars on the 2026 NYSE fixture calendar: offline, no clock.
"""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import UTC, date, datetime, time

import pandas as pd
import pytest

from quant_backtester.data.calendars import TradingCalendar
from quant_backtester.data.instruments import (
    AssetType,
    DataType,
    DistributionPolicy,
    Instrument,
    PublicationRule,
)
from quant_backtester.data.validator import (
    Severity,
    ValidationIssue,
    ValidationReport,
    check_stale_open,
    validate_bars,
    validate_corporate_actions,
    validate_levels,
)


def make_instrument(asset_type: AssetType = AssetType.ETF, **overrides: object) -> Instrument:
    """Return a NYSE-listed BAR instrument of ``asset_type``."""
    instrument = Instrument(
        id="US_SPY",
        name="Test instrument",
        asset_type=asset_type,
        data_type=DataType.BAR,
        currency="USD",
        primary_source="YAHOO",
        source_symbol="SPY",
        tradable=True,
        calendar_id="XNYS",
    )
    return replace(instrument, **overrides)


def bar(
    day: date,
    open_: float = 100.0,
    high: float = 102.0,
    low: float = 99.0,
    close: float = 101.0,
    volume: float = 1000.0,
) -> dict[str, object]:
    """Return one canonical bar, available 09:30-16:00 New York in September (EDT)."""
    return {
        "instrument_id": "US_SPY",
        "session_date": day,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "open_available_at_utc": pd.Timestamp(datetime.combine(day, time(13, 30), tzinfo=UTC)),
        "close_available_at_utc": pd.Timestamp(datetime.combine(day, time(20, 0), tzinfo=UTC)),
        "source": "YAHOO",
        "source_fetch_id": "20260912T210311Z",
    }


def frame(*bars: dict[str, object]) -> pd.DataFrame:
    """Return a canonical bars frame holding ``bars`` in the given order."""
    return pd.DataFrame(list(bars))


def codes(report: ValidationReport) -> list[str]:
    return [issue.code for issue in report.issues]


def issues_of(report: ValidationReport, code: str) -> list[ValidationIssue]:
    return [issue for issue in report.issues if issue.code == code]


TUE, WED, THU, FRI = date(2026, 9, 8), date(2026, 9, 9), date(2026, 9, 10), date(2026, 9, 11)
"""A clean NYSE week, the day after Labor Day (Monday 7 September 2026)."""


# --- 6.1 ValidationReport -------------------------------------------------------


def issue(severity: Severity) -> ValidationIssue:
    return ValidationIssue("CODE", severity, "US_SPY", None, "message", {})


def test_report_without_issue_is_valid() -> None:
    report = ValidationReport("US_SPY", [])
    assert report.valid
    assert report.errors == []
    assert report.warnings == []


def test_report_with_warnings_only_is_valid() -> None:
    report = ValidationReport("US_SPY", [issue(Severity.WARNING)])
    assert report.valid
    assert len(report.warnings) == 1


def test_report_with_one_error_is_invalid_and_splits_its_issues() -> None:
    warning, error = issue(Severity.WARNING), issue(Severity.ERROR)
    report = ValidationReport("US_SPY", [warning, error, warning])
    assert not report.valid
    assert report.errors == [error]
    assert report.warnings == [warning, warning]


# --- 6.2 behaviour ------------------------------------------------------------


def test_clean_bars_have_no_issue(xnys: TradingCalendar) -> None:
    report = validate_bars(make_instrument(), frame(bar(TUE), bar(WED), bar(THU)), xnys)
    assert report.issues == []
    assert report.valid
    assert report.instrument_id == "US_SPY"


@pytest.mark.parametrize(
    "broken",
    [
        {"close": 103.0},
        {"open_": 98.0},
        {"low": 103.0, "open_": 103.0, "close": 103.0},
    ],
    ids=["close-above-high", "open-below-low", "low-above-high"],
)
def test_ohlc_ordering_is_enforced(xnys: TradingCalendar, broken: dict[str, float]) -> None:
    report = validate_bars(make_instrument(), frame(bar(TUE), bar(WED, **broken)), xnys)
    assert codes(report) == ["OHLC_ORDER"]
    assert report.issues[0].severity is Severity.ERROR
    assert report.issues[0].observation_date == WED
    assert not report.valid


def test_negative_price_is_rejected_for_an_etf(xnys: TradingCalendar) -> None:
    report = validate_bars(
        make_instrument(),
        frame(bar(TUE, open_=-1.0, high=-0.5, low=-2.0, close=-1.0)),
        xnys,
    )
    assert codes(report) == ["NON_POSITIVE_PRICE"]
    assert report.issues[0].context == {"open": -1.0, "high": -0.5, "low": -2.0, "close": -1.0}


@pytest.mark.parametrize("asset_type", [AssetType.ETF, AssetType.EQUITY, AssetType.INDEX])
def test_zero_price_is_rejected_where_prices_are_positive(
    xnys: TradingCalendar, asset_type: AssetType
) -> None:
    report = validate_bars(make_instrument(asset_type), frame(bar(TUE, low=0.0)), xnys)
    assert codes(report) == ["NON_POSITIVE_PRICE"]


@pytest.mark.parametrize("asset_type", [AssetType.RATE, AssetType.FX, AssetType.VOLATILITY])
def test_non_positive_price_rule_does_not_apply_to_other_asset_types(
    xnys: TradingCalendar, asset_type: AssetType
) -> None:
    negative = bar(TUE, open_=-0.3, high=-0.1, low=-0.4, close=-0.2)
    report = validate_bars(make_instrument(asset_type), frame(negative), xnys)
    assert "NON_POSITIVE_PRICE" not in codes(report)


def test_negative_volume_is_an_error(xnys: TradingCalendar) -> None:
    report = validate_bars(make_instrument(), frame(bar(TUE, volume=-5.0)), xnys)
    assert codes(report) == ["NEGATIVE_VOLUME"]


@pytest.mark.parametrize("infinity", [math.inf, -math.inf], ids=["plus", "minus"])
def test_an_infinite_bar_is_refused_and_not_ordered(xnys: TradingCalendar, infinity: float) -> None:
    """``inf >= inf`` passes every order rule, so an infinite bar used to be valid."""
    report = validate_bars(
        make_instrument(),
        frame(bar(TUE, open_=infinity, high=infinity, low=infinity, close=infinity)),
        xnys,
    )
    assert codes(report) == ["NON_FINITE_VALUE"]
    assert report.issues[0].context == {
        field: infinity for field in ("close", "high", "low", "open")
    }
    assert not report.valid


@pytest.mark.parametrize("field", ["open", "high", "low", "close", "volume"])
def test_one_infinite_field_is_named_and_is_not_also_reported_missing(
    xnys: TradingCalendar, field: str
) -> None:
    row = bar(TUE)
    row[field] = math.inf
    report = validate_bars(make_instrument(), frame(row), xnys)
    assert codes(report) == ["NON_FINITE_VALUE"]
    assert report.issues[0].context == {field: math.inf}


def test_finite_nan_and_missing_prices_are_not_non_finite_errors(xnys: TradingCalendar) -> None:
    missing = bar(TUE, close=math.nan)
    missing["open"] = pd.NA
    report = validate_bars(make_instrument(), frame(missing, bar(WED)), xnys)
    assert codes(report) == ["MISSING_PRICE"]


def test_open_available_after_the_close_is_an_error(xnys: TradingCalendar) -> None:
    swapped = bar(TUE)
    swapped["open_available_at_utc"], swapped["close_available_at_utc"] = (
        swapped["close_available_at_utc"],
        swapped["open_available_at_utc"],
    )
    report = validate_bars(make_instrument(), frame(swapped), xnys)
    assert codes(report) == ["AVAILABILITY_ORDER"]


def test_open_available_at_the_same_instant_as_the_close_is_an_error(
    xnys: TradingCalendar,
) -> None:
    same = bar(TUE)
    same["open_available_at_utc"] = same["close_available_at_utc"]
    report = validate_bars(make_instrument(), frame(same), xnys)
    assert codes(report) == ["AVAILABILITY_ORDER"]


def test_non_session_is_an_error(xnys: TradingCalendar) -> None:
    labor_day = date(2026, 9, 7)
    report = validate_bars(make_instrument(), frame(bar(labor_day), bar(TUE)), xnys)
    assert codes(report) == ["NON_SESSION"]
    assert report.issues[0].observation_date == labor_day


def test_unsorted_and_duplicate_dates_are_errors(xnys: TradingCalendar) -> None:
    report = validate_bars(make_instrument(), frame(bar(WED), bar(TUE), bar(THU), bar(THU)), xnys)
    assert sorted(codes(report)) == ["DATES_UNSORTED", "DATE_DUPLICATE"]
    assert issues_of(report, "DATES_UNSORTED")[0].observation_date == TUE
    assert issues_of(report, "DATE_DUPLICATE")[0].context == {"count": 2}


def test_gap_against_the_calendar_is_a_warning(xnys: TradingCalendar) -> None:
    report = validate_bars(make_instrument(), frame(bar(WED), bar(FRI)), xnys)
    assert codes(report) == ["SESSION_GAP"]
    assert report.issues[0].observation_date == THU
    assert report.issues[0].severity is Severity.WARNING
    assert report.valid


def test_holiday_is_not_a_gap(xnys: TradingCalendar) -> None:
    friday_before_labor_day = date(2026, 9, 4)
    report = validate_bars(make_instrument(), frame(bar(friday_before_labor_day), bar(TUE)), xnys)
    assert report.issues == []


def test_etf_move_above_its_threshold_is_a_warning(xnys: TradingCalendar) -> None:
    crash = bar(WED, open_=74.0, high=76.0, low=73.0, close=75.0)  # 101 -> 75: -25.7%
    report = validate_bars(make_instrument(), frame(bar(TUE), crash), xnys)
    assert codes(report) == ["EXTREME_MOVE"]
    moved = report.issues[0]
    assert moved.observation_date == WED
    assert moved.context["previous_date"] == TUE
    assert moved.context["threshold"] == 0.25
    assert report.valid


def test_etf_move_just_below_its_threshold_is_not_flagged(xnys: TradingCalendar) -> None:
    drop = bar(WED, open_=76.0, high=77.0, low=75.0, close=76.0)  # 101 -> 76: -24.8%
    report = validate_bars(make_instrument(), frame(bar(TUE), drop), xnys)
    assert report.issues == []


def test_large_volatility_move_is_not_flagged(xnys: TradingCalendar) -> None:
    # The VIX closed at 17.31 on 2 February 2018 and 37.32 on 5 February.
    before = bar(TUE, open_=17.0, high=18.0, low=16.0, close=17.31)
    spike = bar(WED, open_=18.0, high=38.0, low=17.0, close=37.32)
    report = validate_bars(make_instrument(AssetType.VOLATILITY), frame(before, spike), xnys)
    assert report.issues == []


@pytest.mark.parametrize(
    ("asset_type", "close", "flagged"),
    [
        (AssetType.INDEX, 74.0, True),
        (AssetType.INDEX, 77.0, False),
        (AssetType.EQUITY, 150.0, True),
        (AssetType.EQUITY, 140.0, False),
    ],
    ids=["index-minus-27", "index-minus-24", "equity-plus-49", "equity-plus-39"],
)
def test_move_threshold_depends_on_the_asset_type(
    xnys: TradingCalendar, asset_type: AssetType, close: float, flagged: bool
) -> None:
    moved = bar(WED, open_=close, high=close + 1, low=close - 1, close=close)
    report = validate_bars(make_instrument(asset_type), frame(bar(TUE), moved), xnys)
    assert ("EXTREME_MOVE" in codes(report)) is flagged


# --- 6.2 boundaries -----------------------------------------------------------


def test_empty_frame_is_valid(xnys: TradingCalendar) -> None:
    empty = frame(bar(TUE)).iloc[0:0]
    assert validate_bars(make_instrument(), empty, xnys).issues == []


def test_single_bar_has_no_move_and_no_gap(xnys: TradingCalendar) -> None:
    assert validate_bars(make_instrument(), frame(bar(TUE)), xnys).issues == []


def test_missing_prices_are_not_ohlc_errors(xnys: TradingCalendar) -> None:
    holey = bar(TUE, open_=math.nan, high=math.nan, close=math.nan)
    report = validate_bars(make_instrument(), frame(holey), xnys)
    assert codes(report) == ["MISSING_PRICE"]
    assert report.valid


def test_a_missing_price_is_reported_once_and_names_the_fields(xnys: TradingCalendar) -> None:
    """A bar with no close passed in silence before this rule existed.

    Yahoo served exactly that for CW8 on 2026-09-17: open, high and low present,
    no close. Every other rule skips a price that is absent, so nothing said a
    word about it.
    """
    report = validate_bars(make_instrument(), frame(bar(TUE, close=math.nan)), xnys)
    missing = issues_of(report, "MISSING_PRICE")
    assert len(missing) == 1
    assert missing[0].severity is Severity.WARNING
    assert missing[0].observation_date == TUE
    assert missing[0].context["missing"] == ["close"]


def test_a_missing_volume_is_not_reported(xnys: TradingCalendar) -> None:
    """A provider leaving the volume empty on an index is ordinary."""
    report = validate_bars(make_instrument(), frame(bar(TUE, volume=math.nan)), xnys)
    assert "MISSING_PRICE" not in codes(report)


def test_a_missing_close_is_skipped_by_the_move_check(xnys: TradingCalendar) -> None:
    # 101 -> (missing) -> 102: compared with the last valid close, no move reported.
    missing = bar(WED, close=math.nan)
    report = validate_bars(make_instrument(), frame(bar(TUE), missing, bar(THU, close=102.0)), xnys)
    assert codes(report) == ["MISSING_PRICE"]
    assert "EXTREME_MOVE" not in codes(report)


def test_gap_while_not_listed_is_not_reported(xnys: TradingCalendar) -> None:
    # Delisted after Wednesday: Thursday is not a hole, and Friday's row is the only anomaly.
    delisted = make_instrument(last_session=WED)
    report = validate_bars(delisted, frame(bar(WED), bar(FRI)), xnys)
    assert "SESSION_GAP" not in codes(report)


def test_date_outside_calendar_coverage_is_reported_not_raised(xnys: TradingCalendar) -> None:
    new_year_eve = date(2025, 12, 31)
    report = validate_bars(make_instrument(), frame(bar(new_year_eve), bar(date(2026, 1, 2))), xnys)
    outside = issues_of(report, "OUTSIDE_CALENDAR_COVERAGE")
    assert [issue.observation_date for issue in outside] == [new_year_eve]
    assert outside[0].severity is Severity.ERROR
    assert "NON_SESSION" not in codes(report)
    assert not report.valid


def test_missing_column_is_a_whole_frame_error(xnys: TradingCalendar) -> None:
    report = validate_bars(make_instrument(), frame(bar(TUE)).drop(columns="volume"), xnys)
    assert codes(report) == ["MISSING_COLUMN"]
    assert report.issues[0].observation_date is None
    assert report.issues[0].context == {"missing": ["volume"]}


# --- 6.2 properties -----------------------------------------------------------


def test_validator_does_not_modify_the_frame(xnys: TradingCalendar) -> None:
    candidate = frame(bar(WED), bar(TUE, close=500.0), bar(TUE))
    before = candidate.copy()
    validate_bars(make_instrument(), candidate, xnys)
    pd.testing.assert_frame_equal(candidate, before)


def test_issues_come_in_date_order(xnys: TradingCalendar) -> None:
    report = validate_bars(
        make_instrument(),
        frame(bar(FRI, volume=-1.0), bar(TUE, close=500.0), bar(date(2026, 9, 7))),
        xnys,
    )
    dates = [issue.observation_date for issue in report.issues]
    assert dates == sorted(day for day in dates if day is not None)


def test_a_later_bar_does_not_change_issues_on_earlier_rows(xnys: TradingCalendar) -> None:
    earlier = [bar(TUE), bar(WED, close=103.0)]
    baseline = validate_bars(make_instrument(), frame(*earlier), xnys)
    extended = validate_bars(make_instrument(), frame(*earlier, bar(THU, close=10.0)), xnys)
    before_thursday = [issue for issue in extended.issues if issue.observation_date != THU]
    assert before_thursday == baseline.issues


# --- 6.4 validate_levels ------------------------------------------------------

SAME_DAY_PARIS = PublicationRule(publication_time=time(16, 0), timezone="Europe/Paris")
"""Released at 16:00 Paris on the observation day, like an ECB reference rate."""

MON, TUE_L, WED_L = date(2019, 8, 12), date(2019, 8, 13), date(2019, 8, 14)
"""Three days of August 2019, when the German 10-year yield was around -0.6%."""


def level_instrument(rule: PublicationRule = SAME_DAY_PARIS) -> Instrument:
    """Return a LEVEL rate released under ``rule``."""
    return Instrument(
        id="DE10Y",
        name="German 10-year yield",
        asset_type=AssetType.RATE,
        data_type=DataType.LEVEL,
        currency="NA",
        primary_source="ECB",
        source_symbol="DE10Y",
        tradable=False,
        publication_rule=rule,
    )


AUGUST_2019 = TradingCalendar(
    calendar_id="XNYS",
    timezone="America/New_York",
    regular_open=time(9, 30),
    regular_close=time(16, 0),
    holidays=frozenset(),
    early_closes={},
    covered_from=date(2019, 8, 1),
    covered_until=date(2019, 8, 31),
)
"""August 2019 held no NYSE holiday, so only the weekends interrupt it."""

NEXT_SESSION_NY = PublicationRule(
    time(16, 15), "America/New_York", lag_sessions=1, calendar_id="XNYS"
)
"""Released one session after the day it describes, the corrected DGS10 rule."""


def levels(
    rows: list[tuple[date, float]],
    rule: PublicationRule = SAME_DAY_PARIS,
    calendar: TradingCalendar | None = None,
) -> pd.DataFrame:
    """Return canonical levels stamped exactly as ``rule`` makes them available."""
    return pd.DataFrame(
        {
            "instrument_id": ["DE10Y"] * len(rows),
            "observation_date": [day for day, _ in rows],
            "value": [value for _, value in rows],
            "available_at_utc": [pd.Timestamp(rule.available_at(day, calendar)) for day, _ in rows],
            "source": ["ECB"] * len(rows),
            "source_fetch_id": ["20260912T210311Z"] * len(rows),
        }
    )


def test_clean_levels_have_no_issue() -> None:
    report = validate_levels(level_instrument(), levels([(MON, 0.5), (TUE_L, 0.6)]))
    assert report.issues == []
    assert report.valid


def test_negative_rate_is_accepted() -> None:
    """A negative level is valid for a RATE.

    The German 10-year yield was negative from 2019 to 2022. A blanket
    ``value > 0`` rule would make that period unloadable.
    """
    report = validate_levels(level_instrument(), levels([(MON, -0.58), (TUE_L, -0.61)]))
    assert report.issues == []


def test_unsorted_and_duplicate_levels_are_errors() -> None:
    report = validate_levels(
        level_instrument(), levels([(TUE_L, 0.6), (MON, 0.5), (WED_L, 0.7), (WED_L, 0.7)])
    )
    assert sorted(codes(report)) == ["DATES_UNSORTED", "DATE_DUPLICATE"]
    assert not report.valid


def test_a_level_without_value_is_an_error() -> None:
    report = validate_levels(level_instrument(), levels([(MON, 0.5), (TUE_L, math.nan)]))
    assert codes(report) == ["MISSING_VALUE"]
    assert report.issues[0].observation_date == TUE_L


@pytest.mark.parametrize("infinity", [math.inf, -math.inf], ids=["plus", "minus"])
def test_an_infinite_level_is_refused(infinity: float) -> None:
    report = validate_levels(level_instrument(), levels([(MON, 0.5), (TUE_L, infinity)]))
    assert codes(report) == ["NON_FINITE_VALUE"]
    assert report.issues[0].observation_date == TUE_L
    assert not report.valid


def test_a_level_without_availability_is_an_error() -> None:
    candidate = levels([(MON, 0.5), (TUE_L, 0.6)])
    candidate["available_at_utc"] = [pd.NaT, candidate["available_at_utc"].iloc[1]]
    report = validate_levels(level_instrument(), candidate)
    assert codes(report) == ["MISSING_AVAILABILITY"]
    assert report.issues[0].observation_date == MON


def test_a_naive_availability_is_an_error() -> None:
    candidate = levels([(MON, 0.5)])
    candidate["available_at_utc"] = [pd.Timestamp("2019-08-12 14:00")]
    report = validate_levels(level_instrument(), candidate)
    assert codes(report) == ["AVAILABILITY_NOT_UTC"]


def test_a_level_published_before_the_day_it_describes_is_an_error() -> None:
    candidate = levels([(TUE_L, 0.6)])
    # Stamped with Monday's release: readable a day before Tuesday's value exists.
    candidate["available_at_utc"] = [pd.Timestamp(SAME_DAY_PARIS.available_at(MON))]
    report = validate_levels(level_instrument(), candidate)
    assert codes(report) == ["AVAILABILITY_BEFORE_OBSERVATION"]
    assert report.issues[0].context["published_on"] == MON


def test_an_availability_the_rule_does_not_give_is_an_error() -> None:
    candidate = levels([(MON, 0.5)])
    candidate["available_at_utc"] = [candidate["available_at_utc"].iloc[0] - pd.Timedelta(hours=1)]
    report = validate_levels(level_instrument(), candidate)
    assert codes(report) == ["AVAILABILITY_MISMATCH"]
    assert report.issues[0].context["expected"] == pd.Timestamp("2019-08-12 14:00", tz="UTC")


def test_levels_stamped_under_an_old_rule_fail_after_the_rule_is_corrected() -> None:
    # Stamped same day, while the corrected rule publishes the next session:
    # exactly what US10Y looked like before its lag was fixed, and the reason
    # the fix has to be followed by a rebuild.
    same_day = PublicationRule(time(16, 15), "America/New_York")
    stale = levels([(MON, 1.7)], rule=same_day)
    report = validate_levels(level_instrument(NEXT_SESSION_NY), stale, AUGUST_2019)
    assert codes(report) == ["AVAILABILITY_MISMATCH"]


def test_a_publication_lag_is_accepted_when_consistent_with_the_rule() -> None:
    report = validate_levels(
        level_instrument(NEXT_SESSION_NY),
        levels([(MON, 1.7)], rule=NEXT_SESSION_NY, calendar=AUGUST_2019),
        AUGUST_2019,
    )
    assert report.issues == []


def test_a_lagged_friday_is_published_after_the_weekend() -> None:
    """Friday 16 August 2019 plus one session is Monday the 19th.

    A lag counted in calendar days would have made it readable on the Saturday,
    a decision taken on a number nobody had yet.
    """
    friday = date(2019, 8, 16)
    stamped = levels([(friday, 1.7)], rule=NEXT_SESSION_NY, calendar=AUGUST_2019)

    assert stamped["available_at_utc"].iloc[0] == pd.Timestamp("2019-08-19 20:15", tz="UTC")
    assert validate_levels(level_instrument(NEXT_SESSION_NY), stamped, AUGUST_2019).issues == []


def test_the_publication_day_is_judged_in_the_publication_timezone() -> None:
    # 08:50 in Tokyo on 12 August is still 11 August in UTC: not published early.
    tokyo = PublicationRule(time(8, 50), "Asia/Tokyo")
    candidate = levels([(MON, -0.2)], rule=tokyo)
    assert candidate["available_at_utc"].iloc[0].date() == date(2019, 8, 11)
    assert validate_levels(level_instrument(tokyo), candidate).issues == []


def test_levels_missing_a_column_is_a_whole_frame_error() -> None:
    report = validate_levels(
        level_instrument(), levels([(MON, 0.5)]).drop(columns="available_at_utc")
    )
    assert codes(report) == ["MISSING_COLUMN"]
    assert report.issues[0].observation_date is None
    assert report.issues[0].context == {"missing": ["available_at_utc"]}


def test_empty_levels_are_valid() -> None:
    assert validate_levels(level_instrument(), levels([])).issues == []


def test_validate_levels_refuses_a_bar_instrument() -> None:
    with pytest.raises(ValueError, match="LEVEL"):
        validate_levels(make_instrument(), levels([(MON, 0.5)]))


def test_validate_levels_does_not_modify_the_frame_and_sorts_its_issues() -> None:
    candidate = levels([(WED_L, math.nan), (MON, 0.5), (TUE_L, math.nan)])
    before = candidate.copy()
    report = validate_levels(level_instrument(), candidate)
    pd.testing.assert_frame_equal(candidate, before)
    dates = [issue.observation_date for issue in report.issues]
    assert dates == sorted(day for day in dates if day is not None)


def test_a_later_level_does_not_change_issues_on_earlier_rows() -> None:
    baseline = validate_levels(level_instrument(), levels([(MON, math.nan), (TUE_L, 0.6)]))
    extended = validate_levels(
        level_instrument(), levels([(MON, math.nan), (TUE_L, 0.6), (WED_L, math.nan)])
    )

    # Compared without the context: it holds NaN, and NaN != NaN.
    def summary(issues: list[ValidationIssue]) -> list[tuple[str, date | None, str]]:
        return [(issue.code, issue.observation_date, issue.message) for issue in issues]

    earlier = [issue for issue in extended.issues if issue.observation_date != WED_L]
    assert summary(earlier) == summary(list(baseline.issues))


# --- 6.5 validate_corporate_actions -------------------------------------------


def actions(rows: list[tuple[str, date, float]]) -> pd.DataFrame:
    """Return canonical corporate actions from ``(type, ex_date, value)``."""
    return pd.DataFrame(
        {
            "instrument_id": ["US_SPY"] * len(rows),
            "action_type": [action_type for action_type, _, _ in rows],
            "ex_date": [ex_date for _, ex_date, _ in rows],
            "value": [value for _, _, value in rows],
            "available_at_utc": [
                pd.Timestamp(datetime.combine(ex_date, time(20, 0), tzinfo=UTC))
                for _, ex_date, _ in rows
            ],
            "source": ["YAHOO"] * len(rows),
            "source_fetch_id": ["20260912T210311Z"] * len(rows),
        }
    )


def test_clean_actions_have_no_issue() -> None:
    report = validate_corporate_actions(
        make_instrument(),
        actions([("DIVIDEND", date(2020, 8, 7), 0.82), ("SPLIT", date(2020, 8, 31), 4.0)]),
    )
    assert report.issues == []
    assert report.valid


@pytest.mark.parametrize("distribution", ["DIVIDEND", "SPECIAL_DIVIDEND"])
def test_a_split_and_a_distribution_on_the_same_ex_date_are_refused(distribution: str) -> None:
    """Per share before the split or after it? Unsaid, and the answers differ by the ratio."""
    same_day = actions([("SPLIT", date(2020, 8, 31), 4.0), (distribution, date(2020, 8, 31), 0.2)])

    report = validate_corporate_actions(make_instrument(), same_day)

    assert codes(report) == ["SPLIT_WITH_DISTRIBUTION"]
    assert report.issues[0].observation_date == date(2020, 8, 31)


def test_a_split_and_a_dividend_on_different_days_are_valid() -> None:
    apart = actions([("SPLIT", date(2020, 8, 31), 4.0), ("DIVIDEND", date(2020, 9, 1), 0.2)])
    assert validate_corporate_actions(make_instrument(), apart).issues == []


@pytest.mark.parametrize("action_type", ["SPLIT", "DIVIDEND", "SPIN_OFF"])
def test_an_infinite_action_value_is_refused(action_type: str) -> None:
    report = validate_corporate_actions(
        make_instrument(), actions([(action_type, date(2020, 8, 31), math.inf)])
    )
    assert codes(report) == ["NON_FINITE_VALUE"]
    assert not report.valid


def test_a_reverse_split_is_valid() -> None:
    # GE's 1-for-8 reverse split of 2 August 2021.
    reverse = actions([("SPLIT", date(2021, 8, 2), 0.125)])
    assert validate_corporate_actions(make_instrument(AssetType.EQUITY), reverse).issues == []


@pytest.mark.parametrize(
    "ratio", [1.0, 0.0, -2.0, math.nan], ids=["one", "zero", "negative", "nan"]
)
def test_an_invalid_split_ratio_is_an_error(ratio: float) -> None:
    report = validate_corporate_actions(
        make_instrument(), actions([("SPLIT", date(2020, 8, 31), ratio)])
    )
    assert codes(report) == ["INVALID_SPLIT_RATIO"]
    assert report.issues[0].observation_date == date(2020, 8, 31)


@pytest.mark.parametrize("amount", [0.0, -0.5, math.nan], ids=["zero", "negative", "nan"])
def test_a_non_positive_dividend_is_an_error(amount: float) -> None:
    report = validate_corporate_actions(
        make_instrument(), actions([("DIVIDEND", date(2020, 8, 7), amount)])
    )
    assert codes(report) == ["NON_POSITIVE_DIVIDEND"]


def test_the_same_type_twice_on_one_ex_date_is_an_error() -> None:
    twice = actions([("DIVIDEND", date(2020, 8, 7), 0.82), ("DIVIDEND", date(2020, 8, 7), 0.82)])
    report = validate_corporate_actions(make_instrument(), twice)
    assert codes(report) == ["DUPLICATE_ACTION"]
    assert report.issues[0].context == {"action_type": "DIVIDEND", "count": 2}


def test_an_unknown_action_type_is_an_error() -> None:
    report = validate_corporate_actions(
        make_instrument(), actions([("RIGHTS_ISSUE", date(2023, 1, 4), 1.281)])
    )
    assert codes(report) == ["UNKNOWN_ACTION_TYPE"]


def test_a_spin_off_and_a_special_dividend_are_valid_shapes() -> None:
    """Both exist because a provider mislabels them, not because they are odd."""
    report = validate_corporate_actions(
        make_instrument(),
        actions(
            [
                ("SPIN_OFF", date(2023, 1, 4), 1.281),
                ("SPECIAL_DIVIDEND", date(2023, 12, 27), 15.0),
            ]
        ),
    )
    assert report.issues == []


def test_a_non_positive_spin_off_factor_is_an_error() -> None:
    """Dividing earlier prices by zero or less is not an adjustment."""
    report = validate_corporate_actions(
        make_instrument(), actions([("SPIN_OFF", date(2023, 1, 4), 0.0)])
    )
    assert codes(report) == ["INVALID_SPIN_OFF_FACTOR"]


def test_a_special_dividend_must_be_positive() -> None:
    """A one-off payment is still a payment."""
    report = validate_corporate_actions(
        make_instrument(), actions([("SPECIAL_DIVIDEND", date(2023, 12, 27), 0.0)])
    )
    assert codes(report) == ["NON_POSITIVE_DIVIDEND"]


def test_an_action_without_availability_is_an_error() -> None:
    candidate = actions([("SPLIT", date(2020, 8, 31), 4.0)])
    candidate["available_at_utc"] = [pd.NaT]
    report = validate_corporate_actions(make_instrument(), candidate)
    assert codes(report) == ["MISSING_AVAILABILITY"]


def test_actions_missing_columns_is_a_whole_frame_error() -> None:
    candidate = actions([("SPLIT", date(2020, 8, 31), 4.0)]).drop(columns=["ex_date", "value"])
    report = validate_corporate_actions(make_instrument(), candidate)
    assert codes(report) == ["MISSING_COLUMN"]
    assert report.issues[0].context == {"missing": ["ex_date", "value"]}


def test_empty_actions_are_valid() -> None:
    assert validate_corporate_actions(make_instrument(), actions([])).issues == []


def test_validate_corporate_actions_refuses_a_level_instrument() -> None:
    with pytest.raises(ValueError, match="BAR"):
        validate_corporate_actions(level_instrument(), actions([]))


def test_validate_corporate_actions_does_not_modify_the_frame_and_sorts_its_issues() -> None:
    candidate = actions([("DIVIDEND", date(2020, 11, 6), -1.0), ("SPLIT", date(2020, 8, 31), 1.0)])
    before = candidate.copy()
    report = validate_corporate_actions(make_instrument(), candidate)
    pd.testing.assert_frame_equal(candidate, before)
    assert [issue.observation_date for issue in report.issues] == [
        date(2020, 8, 31),
        date(2020, 11, 6),
    ]


# --- 6.3 check_stale_open -----------------------------------------------------


@pytest.fixture
def spring(xnys: TradingCalendar) -> list[date]:
    """Return the fixture NYSE sessions from March to May 2026, about sixty."""
    return [session.session_date for session in xnys.sessions(date(2026, 3, 2), date(2026, 5, 29))]


def stale_run(sessions: list[date], stale: set[int], relative_gap: float = 0.0) -> pd.DataFrame:
    """Return bars whose open repeats the previous close at the positions in ``stale``.

    Closes rise by 1 per session. A stale open sits ``relative_gap`` above the
    previous close; every other open sits 0.5 above it, a real opening auction.
    """
    rows = []
    for position, day in enumerate(sessions):
        close = 100.0 + position
        previous_close = close - 1.0
        # A stale open repeats the previous close; a real auction lands 0.5 above it.
        open_ = previous_close * (1 + relative_gap) if position in stale else previous_close + 0.5
        rows.append(
            bar(
                day, open_=open_, high=max(open_, close) + 1, low=min(open_, close) - 1, close=close
            )
        )
    return frame(*rows)


EVERY_OTHER_OF_THE_FIRST_16 = {1, 3, 5, 7, 9, 11, 13, 15}
"""Eight stale opens within the first twenty sessions: 40%, above 30%."""


def test_repeated_stale_open_is_flagged(spring: list[date]) -> None:
    """An open repeatedly equal to the previous close is reported.

    One occurrence is normal. A run of them on an illiquid ETF means there was
    no usable auction - and since the open is our execution price, a strategy
    trading it would book a gain that never existed.
    """
    issues = check_stale_open(make_instrument(), stale_run(spring, EVERY_OTHER_OF_THE_FIRST_16))
    assert [issue.code for issue in issues] == ["STALE_OPEN"]
    assert issues[0].severity is Severity.WARNING
    # The first full window, sessions 0 to 19, already holds the eight.
    assert issues[0].observation_date == spring[19]
    assert issues[0].context == {
        "window_start": spring[0],
        "window_end": spring[19],
        "stale_count": 8,
        "window": 20,
        "threshold": 0.3,
    }


def test_isolated_stale_open_is_not_flagged(spring: list[date]) -> None:
    assert check_stale_open(make_instrument(), stale_run(spring, {5})) == []


def test_exactly_the_threshold_is_not_flagged(spring: list[date]) -> None:
    six_of_twenty = {1, 3, 5, 7, 9, 11}
    assert check_stale_open(make_instrument(), stale_run(spring, six_of_twenty)) == []


def test_a_long_episode_gives_one_issue_not_one_per_window(spring: list[date]) -> None:
    ten_in_a_row = set(range(20, 30))
    issues = check_stale_open(make_instrument(), stale_run(spring, ten_in_a_row))
    assert len(issues) == 1
    # The window becomes offending with its seventh stale open, at position 26.
    assert issues[0].observation_date == spring[26]
    assert issues[0].context["stale_count"] == 7


def test_two_separate_episodes_give_two_issues(spring: list[date]) -> None:
    episodes = set(range(5, 15)) | set(range(45, 55))
    issues = check_stale_open(make_instrument(), stale_run(spring, episodes))
    assert [issue.observation_date for issue in issues] == [spring[19], spring[51]]


def test_float32_noise_still_counts_as_stale(spring: list[date]) -> None:
    # Yahoo stores 567.8383 as 567.838318: a relative gap of about 3e-8.
    noisy = stale_run(spring, EVERY_OTHER_OF_THE_FIRST_16, relative_gap=3e-8)
    assert len(check_stale_open(make_instrument(), noisy)) == 1


def test_a_small_real_gap_is_not_stale(spring: list[date]) -> None:
    every_session = set(range(len(spring)))
    real_auctions = stale_run(spring, every_session, relative_gap=0.001)
    assert check_stale_open(make_instrument(), real_auctions) == []


@pytest.mark.parametrize("asset_type", [AssetType.INDEX, AssetType.VOLATILITY, AssetType.RATE])
def test_an_open_that_is_not_an_execution_price_is_not_checked(
    spring: list[date], asset_type: AssetType
) -> None:
    run = stale_run(spring, EVERY_OTHER_OF_THE_FIRST_16)
    assert check_stale_open(make_instrument(asset_type), run) == []


def test_an_equity_is_checked_like_an_etf(spring: list[date]) -> None:
    run = stale_run(spring, EVERY_OTHER_OF_THE_FIRST_16)
    assert len(check_stale_open(make_instrument(AssetType.EQUITY), run)) == 1


def test_fewer_sessions_than_the_window_are_not_judged(spring: list[date]) -> None:
    all_stale = stale_run(spring[:10], set(range(10)))
    assert check_stale_open(make_instrument(), all_stale) == []


def test_empty_frame_has_no_stale_open(spring: list[date]) -> None:
    empty = stale_run(spring, set()).iloc[0:0]
    assert check_stale_open(make_instrument(), empty) == []


def test_missing_open_or_close_does_not_count(spring: list[date]) -> None:
    run = stale_run(spring, EVERY_OTHER_OF_THE_FIRST_16)
    run["open"] = [
        math.nan if position in EVERY_OTHER_OF_THE_FIRST_16 else value
        for position, value in enumerate(run["open"])
    ]
    assert check_stale_open(make_instrument(), run) == []


def test_an_unsorted_frame_is_judged_chronologically(spring: list[date]) -> None:
    run = stale_run(spring, EVERY_OTHER_OF_THE_FIRST_16)
    shuffled = run.iloc[::-1].reset_index(drop=True)
    assert check_stale_open(make_instrument(), shuffled) == check_stale_open(make_instrument(), run)


@pytest.mark.parametrize(
    ("window", "threshold", "match"),
    [(1, 0.3, "window"), (20, 0.0, "threshold"), (20, 1.0, "threshold")],
    ids=["window-of-one", "zero-threshold", "threshold-of-one"],
)
def test_invalid_parameters_raise(
    spring: list[date], window: int, threshold: float, match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        check_stale_open(make_instrument(), stale_run(spring, set()), window, threshold)


def test_a_shorter_window_and_lower_threshold_are_honoured(spring: list[date]) -> None:
    # Two stale opens in five sessions: 40% > 30% with window=5.
    issues = check_stale_open(make_instrument(), stale_run(spring, {1, 3}), window=5, threshold=0.3)
    assert [issue.observation_date for issue in issues] == [spring[4]]


def test_validate_bars_reports_stale_opens_as_warnings(
    spring: list[date], xnys: TradingCalendar
) -> None:
    report = validate_bars(make_instrument(), stale_run(spring, EVERY_OTHER_OF_THE_FIRST_16), xnys)
    assert codes(report) == ["STALE_OPEN"]
    assert report.valid


def test_check_stale_open_does_not_modify_the_frame(spring: list[date]) -> None:
    run = stale_run(spring, EVERY_OTHER_OF_THE_FIRST_16).iloc[::-1]
    before = run.copy()
    check_stale_open(make_instrument(), run)
    pd.testing.assert_frame_equal(run, before)


def test_later_sessions_do_not_change_an_earlier_stale_open_issue(spring: list[date]) -> None:
    episodes = set(range(5, 15)) | set(range(45, 55))
    baseline = check_stale_open(make_instrument(), stale_run(spring[:40], episodes))
    extended = check_stale_open(make_instrument(), stale_run(spring, episodes))
    earlier = [
        issue
        for issue in extended
        if issue.observation_date is not None and issue.observation_date <= spring[39]
    ]
    assert earlier == baseline


# --- provider placeholders and share class policy -----------------------------


def test_a_flat_bar_with_no_volume_is_a_placeholder(xnys: TradingCalendar) -> None:
    """Yahoo served exactly this for CW8 on 2025-10-24.

    Four identical prices and no volume is not a session, it is a provider
    filling a hole. Every other rule passes it: the OHLC order holds, the prices
    are positive, the volume is not negative.
    """
    placeholder = bar(TUE, open_=500.0, high=500.0, low=500.0, close=500.0, volume=0.0)
    report = validate_bars(make_instrument(), frame(placeholder), xnys)

    flat = issues_of(report, "FLAT_ZERO_VOLUME")
    assert [issue.observation_date for issue in flat] == [TUE]
    assert flat[0].severity is Severity.WARNING
    # A warning: the cross-check and the reader deal with it, the series still updates.
    assert report.valid


def test_a_flat_bar_that_traded_is_not_a_placeholder(xnys: TradingCalendar) -> None:
    """An illiquid session can print one price all day, and it is a real one."""
    traded = bar(TUE, open_=500.0, high=500.0, low=500.0, close=500.0, volume=120.0)
    assert "FLAT_ZERO_VOLUME" not in codes(validate_bars(make_instrument(), frame(traded), xnys))


def test_a_zero_volume_bar_that_moved_is_not_a_placeholder(xnys: TradingCalendar) -> None:
    """An index reports no volume at all; only a flat one is suspicious."""
    index = make_instrument(AssetType.INDEX)
    moved = bar(TUE, volume=0.0)
    assert "FLAT_ZERO_VOLUME" not in codes(validate_bars(index, frame(moved), xnys))


def test_an_accumulating_share_class_cannot_pay_a_dividend() -> None:
    """CW8 reinvests its income, so a dividend on it is bad data, not an event.

    Without the declared policy, an empty action feed and a provider that lost
    the dividends look identical - and so do a real distribution and a stray row.
    """
    accumulating = make_instrument(distribution_policy=DistributionPolicy.ACCUMULATING)
    report = validate_corporate_actions(accumulating, actions([("DIVIDEND", TUE, 0.5)]))

    unexpected = issues_of(report, "UNEXPECTED_DISTRIBUTION")
    assert [issue.observation_date for issue in unexpected] == [TUE]
    assert unexpected[0].severity is Severity.ERROR
    assert not report.valid


def test_an_accumulating_share_class_may_still_split() -> None:
    """The policy is about income, not about share counts."""
    accumulating = make_instrument(distribution_policy=DistributionPolicy.ACCUMULATING)
    report = validate_corporate_actions(accumulating, actions([("SPLIT", TUE, 4.0)]))
    assert report.issues == []


def test_a_distributing_fund_pays_dividends_without_complaint() -> None:
    """The rule fires on the declared policy, not on every fund."""
    distributing = make_instrument(distribution_policy=DistributionPolicy.DISTRIBUTING)
    report = validate_corporate_actions(distributing, actions([("DIVIDEND", TUE, 0.5)]))
    assert report.issues == []
