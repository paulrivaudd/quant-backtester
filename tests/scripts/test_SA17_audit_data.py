"""SA17 data audit: date coverage that tells a missing session from a closed day."""

from __future__ import annotations

import importlib.util
import sys
from datetime import date, time
from pathlib import Path
from types import ModuleType

import pytest

from quant_backtester.data.calendars import CalendarCoverageError, TradingCalendar

REPOSITORY = Path(__file__).resolve().parents[2]


def load_script() -> ModuleType:
    """Import ``scripts/SA17_audit_data.py`` by its path, as the other script tests do."""
    path = REPOSITORY / "scripts" / "SA17_audit_data.py"
    spec = importlib.util.spec_from_file_location("SA17_audit_data", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SCRIPT = load_script()
date_coverage = SCRIPT.date_coverage
main = SCRIPT.main


def _calendar() -> TradingCalendar:
    return TradingCalendar(
        calendar_id="TEST",
        timezone="Europe/Paris",
        regular_open=time(9),
        regular_close=time(17, 30),
        covered_from=date(2025, 1, 1),
        covered_until=date(2025, 12, 31),
        holidays=frozenset({date(2025, 1, 1), date(2025, 1, 8)}),
        early_closes={},
    )


def test_missing_session_is_not_confused_with_a_weekend():
    coverage = date_coverage([date(2025, 1, 2), date(2025, 1, 6)], _calendar())
    assert coverage["missing_sessions_within_observed_range"] == ["2025-01-03"]
    assert coverage["non_session_dates"] == []
    assert coverage["rows"] == 2


def test_missing_session_is_not_confused_with_a_holiday():
    coverage = date_coverage([date(2025, 1, 6), date(2025, 1, 9)], _calendar())
    assert coverage["missing_sessions_within_observed_range"] == ["2025-01-07"]


def test_duplicates_and_closed_day_observations_remain_visible():
    coverage = date_coverage([date(2025, 1, 2), date(2025, 1, 2), date(2025, 1, 4)], _calendar())
    assert coverage["rows"] == 3
    assert coverage["unique_dates"] == 2
    assert coverage["non_session_dates"] == ["2025-01-04"]
    assert coverage["missing_sessions_within_observed_range"] == ["2025-01-03"]


def test_empty_data_is_not_reported_as_complete():
    coverage = date_coverage([], _calendar())
    assert coverage["first_observation"] is None
    assert coverage["missing_sessions_within_observed_range"] is None


def test_calendar_is_not_extended_silently():
    with pytest.raises(CalendarCoverageError):
        date_coverage([date(2024, 12, 31), date(2025, 1, 2)], _calendar())


def test_level_observations_do_not_get_an_invented_exchange_schedule():
    coverage = date_coverage([date(2025, 1, 2), date(2025, 2, 3)], None)
    assert coverage["rows"] == 2
    assert coverage["missing_sessions_within_observed_range"] is None


def test_existing_evidence_is_not_overwritten(tmp_path, monkeypatch):
    output = tmp_path / "evidence.json"
    output.write_text("original evidence\n", encoding="utf-8")
    monkeypatch.setattr(
        sys, "argv", ["audit", "--store", str(tmp_path / "absent-store"), "--output", str(output)]
    )
    with pytest.raises(SystemExit, match="2"):
        main()
    assert output.read_text(encoding="utf-8") == "original evidence\n"
