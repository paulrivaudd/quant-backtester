from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta, timezone

import pandas as pd
import pytest
from tests.data.test_instruments import LEVEL_FIELDS, SAMPLE_TOML, make_instrument, write_toml

from quant_backtester.data.instruments import InstrumentRegistry, PublicationRule

FLOOR = datetime(2026, 11, 7, 15, 59, 1, 951210, tzinfo=UTC)


def test_floor_bounds_schedule_without_replacing_it():
    rule = PublicationRule(time(16), "UTC", not_before_utc=FLOOR)
    assert rule.available_at(date(2020, 1, 1)) == FLOOR
    assert rule.available_at(date(2026, 11, 7)) == datetime(2026, 11, 7, 16, tzinfo=UTC)


def test_floor_preserves_calendar_requirements_and_session_lag(xnys):
    rule = PublicationRule(time(16), "America/New_York", 1, "XNYS", FLOOR)
    with pytest.raises(ValueError, match="calendar"):
        rule.available_at(date(2026, 11, 6))
    scheduled = replace(rule, not_before_utc=None).available_at(date(2026, 11, 6), xnys)
    assert rule.available_at(date(2026, 11, 6), xnys) == max(scheduled, FLOOR)


@pytest.mark.parametrize(
    "floor",
    [
        datetime(2026, 11, 7),
        date(2026, 11, 7),
        "2026-11-07T00:00:00Z",
        datetime(2026, 11, 7, tzinfo=timezone(timedelta(hours=1))),
        float("nan"),
        float("inf"),
        pd.NaT,
    ],
)
def test_floor_rejects_non_utc_or_nonfinite_values(floor):
    with pytest.raises(ValueError, match="not_before_utc"):
        PublicationRule(time(0), "UTC", not_before_utc=floor)


def test_unset_floor_preserves_definition_and_set_floor_serializes():
    instrument = make_instrument(**LEVEL_FIELDS)
    assert instrument.definition()["publication_rule"] == {
        "publication_time": "16:00:00",
        "timezone": "Europe/Paris",
        "lag_sessions": 0,
        "calendar_id": None,
    }
    rule = replace(instrument.publication_rule, not_before_utc=FLOOR)
    definition = replace(instrument, publication_rule=rule).definition()
    assert definition["publication_rule"]["not_before_utc"] == FLOOR.isoformat()


@pytest.mark.parametrize(
    "text",
    [
        "2026-11-07T15:59:01.951210Z",
        '"2026-11-07T15:59:01.951210Z"',
    ],
)
def test_toml_floor_accepts_datetime_or_iso_string(tmp_path, text):
    path = write_toml(tmp_path, SAMPLE_TOML + f"\nnot_before_utc = {text}\n")
    rule = InstrumentRegistry.from_toml(path).get("US10Y").publication_rule
    assert rule.not_before_utc == FLOOR


@pytest.mark.parametrize(
    "text",
    [
        '"bad"',
        "2026-11-07T15:59:01",
        "2026-11-07T15:59:01+01:00",
        "2026-11-07",
        "42",
    ],
)
def test_toml_floor_rejects_invalid_values(tmp_path, text):
    path = write_toml(tmp_path, SAMPLE_TOML + f"\nnot_before_utc = {text}\n")
    with pytest.raises(ValueError, match="not_before_utc"):
        InstrumentRegistry.from_toml(path)
