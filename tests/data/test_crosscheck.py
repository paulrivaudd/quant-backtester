"""Cross-checking: sessions confirmed, conflicting or single-sourced, and the policy.

Pure functions on synthetic canonical bars: no calendar, no clock, no network.
The disagreements mirror the real ones found between Yahoo and Euronext on CW8.
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, time
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pytest

from quant_backtester.data.crosscheck import (
    CrossCheckPolicy,
    cross_check_bars,
    relative_difference,
)
from quant_backtester.data.repository import write_parquet_atomic
from quant_backtester.data.schemas import BARS_SCHEMA, CHECKED_BARS_SCHEMA, CheckStatus

POLICY = CrossCheckPolicy(price_rel_tolerance=1e-6, volume_rel_tolerance=0.0)
"""The committed tolerances."""

FETCH_IDS = {
    "YAHOO": "20260912T210311Z",
    "EURONEXT": "20260912T210312Z",
    "STOOQ": "20260912T210313Z",
}

SESSIONS = [date(2026, 9, 9), date(2026, 9, 10), date(2026, 9, 11)]

COMMITTED_POLICY = (
    Path(__file__).resolve().parents[2] / "market_data" / "metadata" / "crosscheck.toml"
)


def bars(
    source: str,
    sessions: list[date] = SESSIONS,
    closes: list[float] | None = None,
    volumes: list[float] | None = None,
    instrument_id: str = "ETF_WORLD",
) -> pd.DataFrame:
    """Build canonical bars for one source; prices rise by 1 per day after ``SESSIONS[0]``.

    Prices follow the date, not the row position, so two sources covering
    different spans still agree on every session they share.
    """
    count = len(sessions)
    offsets = [float(day.toordinal() - SESSIONS[0].toordinal()) for day in sessions]
    return pd.DataFrame(
        {
            "instrument_id": [instrument_id] * count,
            "session_date": sessions,
            "open": [99.0 + offset for offset in offsets],
            "high": [101.0 + offset for offset in offsets],
            "low": [98.0 + offset for offset in offsets],
            "close": closes if closes is not None else [100.0 + offset for offset in offsets],
            "volume": volumes if volumes is not None else [1000.0] * count,
            "open_available_at_utc": [
                datetime.combine(day, time(7, 0), tzinfo=UTC) for day in sessions
            ],
            "close_available_at_utc": [
                datetime.combine(day, time(15, 30), tzinfo=UTC) for day in sessions
            ],
            "source": [source] * count,
            "source_fetch_id": [FETCH_IDS[source]] * count,
        },
        columns=list(BARS_SCHEMA.names),
    )


def check(frames: dict[str, pd.DataFrame], reference: str = "YAHOO") -> pd.DataFrame:
    """Cross-check with the committed policy."""
    return cross_check_bars("ETF_WORLD", frames, reference, POLICY)


# --- relative_difference ------------------------------------------------------


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        (100.0, 100.0, 0.0),
        (100.0, 99.0, 0.01),
        (99.0, 100.0, 0.01),
        (0.0, 0.0, 0.0),
        (5663.0, 0.0, 1.0),
        (-2.0, 2.0, 2.0),
        (math.nan, math.nan, 0.0),
        (math.nan, 1.0, math.inf),
        (1.0, math.nan, math.inf),
    ],
    ids=[
        "equal",
        "one-percent",
        "symmetric",
        "both-zero",
        "zero-volume-placeholder",
        "opposite-signs",
        "both-missing",
        "left-missing",
        "right-missing",
    ],
)
def test_relative_difference_by_hand(a: float, b: float, expected: float) -> None:
    assert relative_difference(a, b) == pytest.approx(expected)


# --- verdicts -----------------------------------------------------------------


def test_identical_sources_are_confirmed() -> None:
    checked = check({"YAHOO": bars("YAHOO"), "EURONEXT": bars("EURONEXT")})
    assert checked["check_status"].tolist() == ["CONFIRMED"] * 3
    assert checked["max_price_rel_diff"].tolist() == [0.0] * 3
    assert checked["max_volume_rel_diff"].tolist() == [0.0] * 3


def test_float32_storage_noise_is_confirmed() -> None:
    # Yahoo stores prices as float32: Euronext's 567.8383 comes back as 567.838318.
    yahoo = bars("YAHOO", closes=[567.838318, 101.0, 102.0])
    euronext = bars("EURONEXT", closes=[567.8383, 101.0, 102.0])
    checked = check({"YAHOO": yahoo, "EURONEXT": euronext})
    assert checked["check_status"].tolist()[0] == "CONFIRMED"
    assert 0 < checked["max_price_rel_diff"].tolist()[0] < 1e-7


def test_a_price_beyond_tolerance_is_a_conflict() -> None:
    # 24 October 2025: Yahoo's flat placeholder close against Euronext's real one.
    yahoo = bars("YAHOO", closes=[602.3394, 101.0, 102.0])
    euronext = bars("EURONEXT", closes=[603.3125, 101.0, 102.0])
    checked = check({"YAHOO": yahoo, "EURONEXT": euronext})
    assert checked["check_status"].tolist() == ["CONFLICT", "CONFIRMED", "CONFIRMED"]
    assert checked["max_price_rel_diff"].tolist()[0] == pytest.approx(0.0016129, rel=1e-3)


def test_a_volume_mismatch_is_a_conflict_even_with_equal_prices() -> None:
    yahoo = bars("YAHOO", volumes=[0.0, 1000.0, 1000.0])
    euronext = bars("EURONEXT", volumes=[5663.0, 1000.0, 1000.0])
    checked = check({"YAHOO": yahoo, "EURONEXT": euronext})
    assert checked["check_status"].tolist()[0] == "CONFLICT"
    assert checked["max_price_rel_diff"].tolist()[0] == 0.0
    assert checked["max_volume_rel_diff"].tolist()[0] == 1.0


def test_a_value_missing_on_one_side_only_is_a_conflict() -> None:
    yahoo = bars("YAHOO", closes=[math.nan, 101.0, 102.0])
    checked = check({"YAHOO": yahoo, "EURONEXT": bars("EURONEXT")})
    assert checked["check_status"].tolist()[0] == "CONFLICT"
    assert checked["max_price_rel_diff"].tolist()[0] == math.inf


def test_a_value_missing_on_both_sides_does_not_conflict() -> None:
    yahoo = bars("YAHOO", closes=[math.nan, 101.0, 102.0])
    euronext = bars("EURONEXT", closes=[math.nan, 101.0, 102.0])
    checked = check({"YAHOO": yahoo, "EURONEXT": euronext})
    assert checked["check_status"].tolist()[0] == "CONFIRMED"


def test_a_conflict_keeps_the_reference_values_and_lineage() -> None:
    yahoo = bars("YAHOO", closes=[602.3394, 101.0, 102.0])
    euronext = bars("EURONEXT", closes=[603.3125, 101.0, 102.0])
    checked = check({"YAHOO": yahoo, "EURONEXT": euronext}, reference="EURONEXT")
    assert checked["close"].tolist()[0] == 603.3125
    assert set(checked["source"]) == {"EURONEXT"}
    assert set(checked["source_fetch_id"]) == {FETCH_IDS["EURONEXT"]}


def test_sources_and_fetches_are_listed_sorted_on_every_row() -> None:
    checked = check({"YAHOO": bars("YAHOO"), "EURONEXT": bars("EURONEXT")})
    assert set(checked["checked_sources"]) == {"EURONEXT,YAHOO"}
    assert set(checked["checked_fetch_ids"]) == {
        f"EURONEXT:{FETCH_IDS['EURONEXT']},YAHOO:{FETCH_IDS['YAHOO']}"
    }


def test_three_sources_report_the_largest_pairwise_difference() -> None:
    yahoo = bars("YAHOO", closes=[100.0, 101.0, 102.0])
    euronext = bars("EURONEXT", closes=[100.0, 101.0, 102.0])
    stooq = bars("STOOQ", closes=[99.0, 101.0, 102.0])
    checked = check({"YAHOO": yahoo, "EURONEXT": euronext, "STOOQ": stooq})
    assert checked["check_status"].tolist() == ["CONFLICT", "CONFIRMED", "CONFIRMED"]
    assert checked["max_price_rel_diff"].tolist()[0] == pytest.approx(0.01)
    assert set(checked["checked_sources"]) == {"EURONEXT,STOOQ,YAHOO"}


# --- coverage differences -----------------------------------------------------


def test_sessions_held_by_one_source_only_are_single_source() -> None:
    # Euronext's two-year window: the older sessions exist on Yahoo alone.
    yahoo = bars("YAHOO", sessions=SESSIONS)
    euronext = bars("EURONEXT", sessions=SESSIONS[1:])
    checked = check({"YAHOO": yahoo, "EURONEXT": euronext})
    assert checked["check_status"].tolist() == ["SINGLE_SOURCE", "CONFIRMED", "CONFIRMED"]
    assert checked["checked_sources"].tolist()[0] == "YAHOO"
    assert checked["checked_fetch_ids"].tolist()[0] == f"YAHOO:{FETCH_IDS['YAHOO']}"
    assert math.isnan(checked["max_price_rel_diff"].tolist()[0])
    assert math.isnan(checked["max_volume_rel_diff"].tolist()[0])


def test_a_session_missing_from_the_reference_takes_the_other_source() -> None:
    yahoo = bars("YAHOO", sessions=SESSIONS[:2])
    euronext = bars("EURONEXT", sessions=SESSIONS, closes=[100.0, 101.0, 555.0])
    checked = check({"YAHOO": yahoo, "EURONEXT": euronext})
    last = checked.iloc[-1]
    assert (last["check_status"], last["source"], last["close"]) == (
        "SINGLE_SOURCE",
        "EURONEXT",
        555.0,
    )


def test_rows_are_sorted_by_session_across_interleaved_sources() -> None:
    yahoo = bars("YAHOO", sessions=[SESSIONS[0], SESSIONS[2]])
    euronext = bars("EURONEXT", sessions=[SESSIONS[1]])
    checked = check({"YAHOO": yahoo, "EURONEXT": euronext})
    assert checked["session_date"].tolist() == SESSIONS
    assert checked["source"].tolist() == ["YAHOO", "EURONEXT", "YAHOO"]


def test_a_single_source_marks_every_session_single_source() -> None:
    checked = check({"YAHOO": bars("YAHOO")})
    assert checked["check_status"].tolist() == ["SINGLE_SOURCE"] * 3


def test_empty_sources_give_an_empty_frame_with_the_checked_columns() -> None:
    checked = check(
        {"YAHOO": bars("YAHOO", sessions=[]), "EURONEXT": bars("EURONEXT", sessions=[])}
    )
    assert checked.empty
    assert list(checked.columns) == CHECKED_BARS_SCHEMA.names


def test_every_status_is_a_declared_check_status() -> None:
    yahoo = bars("YAHOO", closes=[1.0, 101.0, 102.0])
    euronext = bars("EURONEXT", sessions=SESSIONS[:2])
    checked = check({"YAHOO": yahoo, "EURONEXT": euronext})
    assert set(checked["check_status"]) <= {status.value for status in CheckStatus}


# --- storage ------------------------------------------------------------------


def test_checked_frame_converts_to_the_arrow_schema() -> None:
    euronext = bars("EURONEXT", sessions=SESSIONS[1:])
    checked = check({"YAHOO": bars("YAHOO"), "EURONEXT": euronext})
    table = pa.Table.from_pandas(checked, schema=CHECKED_BARS_SCHEMA, preserve_index=False)
    assert table.num_rows == 3


def test_checked_frame_passes_the_repository_write_checks(tmp_path: Path) -> None:
    # write_parquet_atomic insists on UTC timestamp dtypes, not just convertible values.
    checked = check({"YAHOO": bars("YAHOO"), "EURONEXT": bars("EURONEXT")})
    write_parquet_atomic(checked, tmp_path / "ETF_WORLD.parquet", CHECKED_BARS_SCHEMA)
    assert (tmp_path / "ETF_WORLD.parquet").exists()


def test_inputs_are_left_untouched() -> None:
    yahoo, euronext = bars("YAHOO"), bars("EURONEXT", closes=[1.0, 2.0, 3.0])
    before = (yahoo.copy(), euronext.copy())
    check({"YAHOO": yahoo, "EURONEXT": euronext})
    pd.testing.assert_frame_equal(yahoo, before[0])
    pd.testing.assert_frame_equal(euronext, before[1])


# --- refusals -----------------------------------------------------------------


def test_no_source_raises() -> None:
    with pytest.raises(ValueError, match="at least one source"):
        check({})


def test_a_reference_absent_from_the_sources_raises() -> None:
    with pytest.raises(ValueError, match="YAHOO"):
        check({"EURONEXT": bars("EURONEXT")})


@pytest.mark.parametrize(
    ("frame", "match"),
    [
        (bars("EURONEXT").drop(columns="close_available_at_utc"), "close_available_at_utc"),
        (bars("EURONEXT", instrument_id="US_SPY"), "US_SPY"),
        (bars("STOOQ"), "STOOQ"),
        (bars("EURONEXT", sessions=[SESSIONS[0], SESSIONS[0]]), "repeat"),
    ],
    ids=["missing-column", "other-instrument", "mislabelled-source", "repeated-session"],
)
def test_a_malformed_frame_raises(frame: pd.DataFrame, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        check({"YAHOO": bars("YAHOO"), "EURONEXT": frame})


def test_sources_disagreeing_on_availability_raise() -> None:
    euronext = bars("EURONEXT")
    euronext["close_available_at_utc"] = [
        datetime.combine(day, time(16, 30), tzinfo=UTC) for day in SESSIONS
    ]
    with pytest.raises(ValueError, match="one calendar"):
        check({"YAHOO": bars("YAHOO"), "EURONEXT": euronext})


# --- look-ahead guard ---------------------------------------------------------


def test_a_later_session_does_not_change_earlier_verdicts() -> None:
    baseline = check({"YAHOO": bars("YAHOO"), "EURONEXT": bars("EURONEXT")})
    later = [*SESSIONS, date(2026, 9, 14)]
    extended = check(
        {
            "YAHOO": bars("YAHOO", sessions=later, closes=[100.0, 101.0, 102.0, 1.0]),
            "EURONEXT": bars("EURONEXT", sessions=later, closes=[100.0, 101.0, 102.0, 9.0]),
        }
    )
    assert extended["check_status"].tolist()[-1] == "CONFLICT"
    pd.testing.assert_frame_equal(extended.head(3), baseline)


# --- policy -------------------------------------------------------------------


@pytest.mark.parametrize(
    "tolerance",
    [-1e-6, 1.0, math.nan, math.inf, True, "1e-6"],
    ids=["negative", "one", "nan", "infinite", "bool", "string"],
)
def test_policy_rejects_an_invalid_tolerance(tolerance: object) -> None:
    with pytest.raises(ValueError, match="price_rel_tolerance"):
        CrossCheckPolicy(price_rel_tolerance=tolerance, volume_rel_tolerance=0.0)  # type: ignore[arg-type]


def test_policy_accepts_zero_and_an_integer() -> None:
    assert (
        CrossCheckPolicy(price_rel_tolerance=0, volume_rel_tolerance=0.0).price_rel_tolerance == 0
    )


def test_the_committed_policy_loads() -> None:
    assert CrossCheckPolicy.from_toml(COMMITTED_POLICY) == POLICY


@pytest.mark.parametrize(
    ("content", "match"),
    [
        ("[prices]\nprice_rel_tolerance = 1e-6\n", r"\[bars\]"),
        ("[bars]\nprice_rel_tolerance = 1e-6\n", "volume_rel_tolerance"),
        (
            "[bars]\nprice_rel_tolerance = 1e-6\nvolume_rel_tolerance = 0.0\nprice_tol = 1\n",
            "price_tol",
        ),
        ("[bars]\nprice_rel_tolerance = -1.0\nvolume_rel_tolerance = 0.0\n", r"\[0, 1\)"),
    ],
    ids=["no-bars-table", "missing-key", "unknown-key", "invalid-value"],
)
def test_policy_from_toml_rejects_a_bad_file(tmp_path: Path, content: str, match: str) -> None:
    path = tmp_path / "crosscheck.toml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match=match):
        CrossCheckPolicy.from_toml(path)
