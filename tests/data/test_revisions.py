"""Revisions: detecting that a provider changed its mind, and the decisions that let it through.

Offline: TOML files are written under ``tmp_path``, plus the committed one. The
detection tests are pure functions over synthetic frames - no clock, no
filesystem, no network: ``detected_at_utc`` is passed in like every other input.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, time
from pathlib import Path

import pandas as pd
import pytest

from quant_backtester.data.repository import MarketDataRepository
from quant_backtester.data.revisions import (
    AcceptedRevision,
    AcceptedRevisions,
    detect_revisions,
    merge_with_policy,
)
from quant_backtester.data.schemas import BARS_SCHEMA, LEVELS_SCHEMA, REVISIONS_SCHEMA

COMMITTED = (
    Path(__file__).resolve().parents[2] / "market_data" / "metadata" / "accepted_revisions.toml"
)

SP500_MOVE = (6590.25, 6591.1)
"""The one transition reviewed on the SP500 close of 10 September."""

US10Y_MOVE = (4.1, 4.12)
"""The one transition reviewed on the US10Y value of 9 September."""

SP500_CLOSE = AcceptedRevision(
    instrument_id="SP500",
    source="YAHOO",
    table="bars",
    observation_date=date(2026, 9, 10),
    field="close",
    old_value=SP500_MOVE[0],
    new_value=SP500_MOVE[1],
    reason="Yahoo corrected an obviously wrong print; checked against another source.",
)

US10Y_VALUE = AcceptedRevision(
    instrument_id="US10Y",
    source="FRED",
    table="levels",
    observation_date=date(2026, 9, 9),
    field="value",
    old_value=US10Y_MOVE[0],
    new_value=US10Y_MOVE[1],
    reason="FRED restated the H.15 value.",
)


def write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "accepted_revisions.toml"
    path.write_text(content, encoding="utf-8")
    return path


TWO_REVISIONS = """
[[revision]]
instrument_id = "SP500"
source = "YAHOO"
table = "bars"
observation_date = 2026-09-10
field = "close"
old_value = 6590.25
new_value = 6591.1
reason = "Yahoo corrected an obviously wrong print; checked against another source."

[[revision]]
instrument_id = "US10Y"
source = "FRED"
table = "levels"
observation_date = 2026-09-09
field = "value"
old_value = 4.1
new_value = 4.12
reason = "FRED restated the H.15 value."
"""


# --- 7.1 AcceptedRevisions ----------------------------------------------------


def test_no_decision_is_valid_and_accepts_nothing() -> None:
    accepted = AcceptedRevisions([])
    assert not accepted.is_accepted(
        "SP500", "YAHOO", "bars", date(2026, 9, 10), "close", *SP500_MOVE
    )


def test_decisions_are_accepted_for_bars_and_levels() -> None:
    accepted = AcceptedRevisions([SP500_CLOSE, US10Y_VALUE])
    assert accepted.is_accepted("SP500", "YAHOO", "bars", date(2026, 9, 10), "close", *SP500_MOVE)
    assert accepted.is_accepted("US10Y", "FRED", "levels", date(2026, 9, 9), "value", *US10Y_MOVE)


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"table": "prices"}, "table"),
        ({"reason": "   "}, "reason"),
        ({"reason": ""}, "reason"),
        ({"observation_date": datetime(2026, 9, 10, 20, 0)}, "plain date"),
    ],
    ids=["unknown-table", "blank-reason", "empty-reason", "datetime"],
)
def test_an_invalid_decision_is_rejected(overrides: dict[str, object], match: str) -> None:
    fields: dict[str, object] = {
        "instrument_id": "SP500",
        "source": "YAHOO",
        "table": "bars",
        "observation_date": date(2026, 9, 10),
        "field": "close",
        "old_value": SP500_MOVE[0],
        "new_value": SP500_MOVE[1],
        "reason": "Checked.",
    }
    fields.update(overrides)
    with pytest.raises(ValueError, match=match):
        AcceptedRevisions([AcceptedRevision(**fields)])  # type: ignore[arg-type]


def test_the_same_correction_accepted_twice_is_rejected() -> None:
    again = AcceptedRevision(
        instrument_id="SP500",
        source="YAHOO",
        table="bars",
        observation_date=date(2026, 9, 10),
        field="close",
        old_value=SP500_MOVE[0],
        new_value=SP500_MOVE[1],
        reason="A second, different review of the same correction.",
    )
    with pytest.raises(ValueError, match="more than once"):
        AcceptedRevisions([SP500_CLOSE, again])


def test_the_same_day_on_two_fields_is_two_distinct_decisions() -> None:
    open_too = AcceptedRevision(
        instrument_id="SP500",
        source="YAHOO",
        table="bars",
        observation_date=date(2026, 9, 10),
        field="open",
        old_value=SP500_MOVE[0],
        new_value=SP500_MOVE[1],
        reason="The open was corrected as well.",
    )
    accepted = AcceptedRevisions([SP500_CLOSE, open_too])
    assert accepted.is_accepted("SP500", "YAHOO", "bars", date(2026, 9, 10), "open", *SP500_MOVE)


def test_decisions_do_not_change_when_the_callers_list_does() -> None:
    decisions = [SP500_CLOSE]
    accepted = AcceptedRevisions(decisions)
    decisions.append(US10Y_VALUE)
    assert not accepted.is_accepted(
        "US10Y", "FRED", "levels", date(2026, 9, 9), "value", *US10Y_MOVE
    )


# --- 7.3 is_accepted ----------------------------------------------------------


@pytest.mark.parametrize(
    ("instrument_id", "table", "observation_date", "field"),
    [
        ("VIX", "bars", date(2026, 9, 10), "close"),
        ("SP500", "levels", date(2026, 9, 10), "close"),
        ("SP500", "bars", date(2026, 9, 11), "close"),
        ("SP500", "bars", date(2026, 9, 10), "open"),
    ],
    ids=["other-instrument", "other-table", "other-date", "other-field"],
)
def test_a_correction_differing_in_any_part_is_not_accepted(
    instrument_id: str, table: str, observation_date: date, field: str
) -> None:
    accepted = AcceptedRevisions([SP500_CLOSE])
    assert not accepted.is_accepted(
        instrument_id, "YAHOO", table, observation_date, field, *SP500_MOVE
    )


def test_a_datetime_never_matches_the_date_of_a_decision() -> None:
    accepted = AcceptedRevisions([SP500_CLOSE])
    at_midnight = datetime(2026, 9, 10)
    assert not accepted.is_accepted("SP500", "YAHOO", "bars", at_midnight, "close", *SP500_MOVE)


# --- 7.2 from_toml ------------------------------------------------------------


def test_the_committed_file_loads_and_accepts_nothing_yet() -> None:
    accepted = AcceptedRevisions.from_toml(COMMITTED)
    assert not accepted.is_accepted(
        "SP500", "YAHOO", "bars", date(2026, 9, 10), "close", *SP500_MOVE
    )


def test_a_missing_file_means_nothing_accepted(tmp_path: Path) -> None:
    accepted = AcceptedRevisions.from_toml(tmp_path / "absent.toml")
    assert not accepted.is_accepted(
        "SP500", "YAHOO", "bars", date(2026, 9, 10), "close", *SP500_MOVE
    )


def test_a_file_with_comments_only_accepts_nothing(tmp_path: Path) -> None:
    accepted = AcceptedRevisions.from_toml(write(tmp_path, "# Nothing reviewed yet.\n"))
    assert not accepted.is_accepted(
        "SP500", "YAHOO", "bars", date(2026, 9, 10), "close", *SP500_MOVE
    )


def test_from_toml_reads_every_revision_table(tmp_path: Path) -> None:
    accepted = AcceptedRevisions.from_toml(write(tmp_path, TWO_REVISIONS))
    assert accepted.is_accepted("SP500", "YAHOO", "bars", date(2026, 9, 10), "close", *SP500_MOVE)
    assert accepted.is_accepted("US10Y", "FRED", "levels", date(2026, 9, 9), "value", *US10Y_MOVE)
    assert not accepted.is_accepted(
        "SP500", "YAHOO", "bars", date(2026, 9, 10), "open", *SP500_MOVE
    )


def test_the_example_documented_in_the_committed_file_is_valid(tmp_path: Path) -> None:
    # Uncommenting the example must give a loadable decision.
    example = "\n".join(
        line[2:]
        for line in COMMITTED.read_text(encoding="utf-8").splitlines()
        if line.startswith("# [[revision]]") or (line.startswith("# ") and " = " in line)
    )
    accepted = AcceptedRevisions.from_toml(write(tmp_path, example))
    assert accepted.is_accepted("SP500", "YAHOO", "bars", date(2026, 9, 10), "close", *SP500_MOVE)


@pytest.mark.parametrize(
    ("content", "match"),
    [
        (
            TWO_REVISIONS.replace(
                "observation_date = 2026-09-10", 'observation_date = "2026-09-10"'
            ),
            "bare date",
        ),
        (
            TWO_REVISIONS.replace(
                "observation_date = 2026-09-10", "observation_date = 2026-09-10T20:00:00"
            ),
            "bare date",
        ),
        (TWO_REVISIONS.replace('field = "close"', 'column = "close"'), "column"),
        (TWO_REVISIONS.replace('reason = "FRED restated the H.15 value."\n', ""), "reason"),
        (
            TWO_REVISIONS.replace('reason = "FRED restated the H.15 value."', 'reason = ""'),
            "reason is required",
        ),
        (TWO_REVISIONS.replace('table = "levels"', 'table = "prices"'), "table"),
        (TWO_REVISIONS.replace("[[revision]]", "[[accepted_revisions]]", 1), "accepted_revisions"),
        (TWO_REVISIONS + TWO_REVISIONS.split("\n\n")[1], "more than once"),
        ('revision = "SP500 close"\n', "array"),
    ],
    ids=[
        "quoted-date",
        "datetime",
        "unknown-key",
        "missing-reason",
        "blank-reason",
        "unknown-table",
        "misnamed-array",
        "duplicate",
        "not-an-array",
    ],
)
def test_from_toml_rejects_a_bad_file(tmp_path: Path, content: str, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        AcceptedRevisions.from_toml(write(tmp_path, content))


def test_from_toml_names_the_file_and_the_entry(tmp_path: Path) -> None:
    broken = TWO_REVISIONS.replace('field = "value"', 'colum = "value"')
    path = write(tmp_path, broken)
    with pytest.raises(ValueError, match=r"revision\[1\]") as raised:
        AcceptedRevisions.from_toml(path)
    assert str(path) in str(raised.value)


def test_from_toml_rejects_a_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not a file"):
        AcceptedRevisions.from_toml(tmp_path)


# --- 7.4 detect_revisions -----------------------------------------------------

SESSIONS = [date(2026, 9, 9), date(2026, 9, 10), date(2026, 9, 11)]
"""Three consecutive sessions: no holiday, no half day, nothing to model."""

OLD_FETCH = "20260912T210311Z"
"""Fetch that produced the stored rows."""

NEW_FETCH = "20260913T210311Z"
"""Fetch that produced the incoming rows."""

DETECTED_AT = datetime(2026, 9, 13, 21, 3, 11, tzinfo=UTC)
"""Instant the comparison ran."""

BAR_FIELDS = ("open", "high", "low", "close", "volume")
"""Bar columns compared, in the order the log is expected to report them."""


def bars(
    sessions: Sequence[date] = SESSIONS,
    *,
    opens: Sequence[float] | None = None,
    closes: Sequence[float] | None = None,
    volumes: Sequence[float] | None = None,
    fetch_id: str = OLD_FETCH,
    instrument_id: str = "SPY",
) -> pd.DataFrame:
    """Build canonical bars whose values follow the date, not the row position.

    Keying the prices on the date means a frame covering more sessions still
    holds the same values on the sessions it shares with a shorter one, so a
    difference of span can never show up as a difference of value.
    """
    count = len(sessions)
    offsets = [float(day.toordinal() - SESSIONS[0].toordinal()) for day in sessions]
    return pd.DataFrame(
        {
            "instrument_id": [instrument_id] * count,
            "session_date": list(sessions),
            "open": list(opens) if opens is not None else [99.0 + offset for offset in offsets],
            "high": [101.0 + offset for offset in offsets],
            "low": [98.0 + offset for offset in offsets],
            "close": list(closes) if closes is not None else [100.0 + offset for offset in offsets],
            "volume": list(volumes) if volumes is not None else [1000.0] * count,
            "open_available_at_utc": [
                datetime.combine(day, time(13, 30), tzinfo=UTC) for day in sessions
            ],
            "close_available_at_utc": [
                datetime.combine(day, time(20, 0), tzinfo=UTC) for day in sessions
            ],
            "source": ["YAHOO"] * count,
            "source_fetch_id": [fetch_id] * count,
        },
        columns=list(BARS_SCHEMA.names),
    )


def levels(
    observation_dates: Sequence[date] = SESSIONS,
    *,
    values: Sequence[float] | None = None,
    fetch_id: str = OLD_FETCH,
    instrument_id: str = "US10Y",
) -> pd.DataFrame:
    """Build canonical levels: one published value per observation date."""
    count = len(observation_dates)
    return pd.DataFrame(
        {
            "instrument_id": [instrument_id] * count,
            "observation_date": list(observation_dates),
            "value": list(values) if values is not None else [4.10, 4.11, 4.12][:count],
            "available_at_utc": [
                datetime.combine(day, time(20, 15), tzinfo=UTC) for day in observation_dates
            ],
            "source": ["FRED"] * count,
            "source_fetch_id": [fetch_id] * count,
        },
        columns=list(LEVELS_SCHEMA.names),
    )


def detect(existing: pd.DataFrame, incoming: pd.DataFrame, tolerance: float = 0.0) -> pd.DataFrame:
    """Compare two bar frames on every bar field."""
    return detect_revisions(
        existing,
        incoming,
        table="bars",
        key_column="session_date",
        value_columns=BAR_FIELDS,
        new_fetch_id=NEW_FETCH,
        detected_at_utc=DETECTED_AT,
        tolerance=tolerance,
    )


def detect_levels(existing: pd.DataFrame, incoming: pd.DataFrame) -> pd.DataFrame:
    """Compare two level frames on their single value column."""
    return detect_revisions(
        existing,
        incoming,
        table="levels",
        key_column="observation_date",
        value_columns=("value",),
        new_fetch_id=NEW_FETCH,
        detected_at_utc=DETECTED_AT,
    )


def test_a_refetch_that_changed_nothing_detects_nothing() -> None:
    """The normal case, and the one that must stay quiet: same values, later fetch."""
    log = detect(bars(), bars(fetch_id=NEW_FETCH))

    assert log.empty
    assert list(log.columns) == REVISIONS_SCHEMA.names


def test_a_changed_close_is_logged_with_both_values() -> None:
    """One row naming what was stored, what arrived, and which fetch said each."""
    stored = bars()
    refetched = bars(fetch_id=NEW_FETCH, closes=[100.0, 101.5, 102.0])

    log = detect(stored, refetched)

    assert list(log.columns) == REVISIONS_SCHEMA.names
    assert log.to_dict("records") == [
        {
            "instrument_id": "SPY",
            "source": "YAHOO",
            "table": "bars",
            "observation_date": SESSIONS[1],
            "field": "close",
            "old_value": 101.0,
            "new_value": 101.5,
            "old_fetch_id": OLD_FETCH,
            "new_fetch_id": NEW_FETCH,
            "detected_at_utc": DETECTED_AT,
        }
    ]


def test_each_changed_field_of_one_day_is_its_own_row() -> None:
    """Acceptance is per field, so detection is too: the open and the close are two decisions."""
    stored = bars()
    refetched = bars(
        fetch_id=NEW_FETCH,
        opens=[99.0, 100.5, 101.0],
        closes=[100.0, 101.5, 102.0],
    )

    log = detect(stored, refetched)

    assert log["field"].tolist() == ["open", "close"]
    assert log["observation_date"].tolist() == [SESSIONS[1], SESSIONS[1]]
    assert log["old_value"].tolist() == [100.0, 101.0]
    assert log["new_value"].tolist() == [100.5, 101.5]


def test_a_restated_volume_is_a_revision_like_any_other() -> None:
    """The commonest revision there is: a late print lands and the tape is restated.

    Every declared field is compared, not a hardcoded list of prices - the
    fields are the caller's to declare, and volume is where a provider actually
    changes its mind most often.
    """
    stored = bars()
    refetched = bars(fetch_id=NEW_FETCH, volumes=[1000.0, 1250.0, 1000.0])

    log = detect(stored, refetched)

    assert log["field"].tolist() == ["volume"]
    assert log["old_value"].tolist() == [1000.0]
    assert log["new_value"].tolist() == [1250.0]


def test_a_date_only_in_the_refetch_is_a_new_observation() -> None:
    """A session we had never stored is data arriving, not a value changing."""
    log = detect(bars(SESSIONS[:2]), bars(fetch_id=NEW_FETCH))

    assert log.empty


def test_a_date_only_in_the_stored_series_is_a_shorter_window() -> None:
    """The overlap window not reaching back that far is not the provider deleting a session."""
    log = detect(bars(), bars(SESSIONS[1:], fetch_id=NEW_FETCH))

    assert log.empty


def test_only_the_overlap_is_compared() -> None:
    """Both edges at once: one shared session changed, and nothing else reported."""
    stored = bars(SESSIONS[:2])
    refetched = bars(SESSIONS[1:], fetch_id=NEW_FETCH, closes=[101.5, 102.0])

    log = detect(stored, refetched)

    assert log["observation_date"].tolist() == [SESSIONS[1]]
    assert log["field"].tolist() == ["close"]


def test_the_default_tolerance_reports_the_smallest_change() -> None:
    """``tolerance=0.0`` means anything that moved: a float64 round trip is exact."""
    stored = bars()
    refetched = bars(fetch_id=NEW_FETCH, closes=[100.0, 101.000000001, 102.0])

    log = detect(stored, refetched)

    assert log["field"].tolist() == ["close"]


def test_a_rounding_change_under_the_tolerance_is_not_a_revision() -> None:
    """The provider printing one more decimal is not it changing its mind."""
    stored = bars()
    refetched = bars(fetch_id=NEW_FETCH, closes=[100.0, 101.000000001, 102.0])

    log = detect(stored, refetched, tolerance=1e-6)

    assert log.empty


@pytest.mark.parametrize(
    ("close", "expected_rows"),
    [(101.25, 0), (101.5, 0), (101.75, 1)],
    ids=["under", "exactly-at-the-tolerance", "over"],
)
def test_the_tolerance_is_the_largest_difference_still_counting_as_unchanged(
    close: float, expected_rows: int
) -> None:
    """Halves keep the arithmetic exact, so the boundary case really sits on the boundary."""
    stored = bars()
    refetched = bars(fetch_id=NEW_FETCH, closes=[100.0, close, 102.0])

    log = detect(stored, refetched, tolerance=0.5)

    assert len(log) == expected_rows


def test_a_value_that_appears_is_a_revision() -> None:
    """A hole being filled changes a result, so it belongs in the log like any other change."""
    stored = bars(closes=[100.0, math.nan, 102.0])
    refetched = bars(fetch_id=NEW_FETCH)

    log = detect(stored, refetched)

    assert log["field"].tolist() == ["close"]
    assert math.isnan(log["old_value"].iloc[0])
    assert log["new_value"].tolist() == [101.0]


def test_a_value_that_disappears_is_a_revision() -> None:
    """Silently keeping a value the provider withdrew is the same bug the other way round."""
    stored = bars()
    refetched = bars(fetch_id=NEW_FETCH, closes=[100.0, math.nan, 102.0])

    log = detect(stored, refetched)

    assert log["field"].tolist() == ["close"]
    assert log["old_value"].tolist() == [101.0]
    assert math.isnan(log["new_value"].iloc[0])


def test_a_value_missing_on_both_sides_is_not_a_revision() -> None:
    """Still missing is still the same answer."""
    log = detect(
        bars(closes=[100.0, math.nan, 102.0]),
        bars(fetch_id=NEW_FETCH, closes=[100.0, math.nan, 102.0]),
    )

    assert log.empty


def test_levels_are_compared_on_their_own_key_column() -> None:
    """``session_date`` or ``observation_date`` in, one log shape out."""
    stored = levels(values=[4.10, 4.11, 4.12])
    refetched = levels(values=[4.10, 4.15, 4.12], fetch_id=NEW_FETCH)

    log = detect_levels(stored, refetched)

    assert list(log.columns) == REVISIONS_SCHEMA.names
    assert log.to_dict("records") == [
        {
            "instrument_id": "US10Y",
            "source": "FRED",
            "table": "levels",
            "observation_date": SESSIONS[1],
            "field": "value",
            "old_value": 4.11,
            "new_value": 4.15,
            "old_fetch_id": OLD_FETCH,
            "new_fetch_id": NEW_FETCH,
            "detected_at_utc": DETECTED_AT,
        }
    ]


def test_the_instrument_is_read_from_the_rows() -> None:
    """Nothing here knows which instrument it is looking at until it reads one."""
    stored = bars(instrument_id="QQQ")
    refetched = bars(instrument_id="QQQ", fetch_id=NEW_FETCH, closes=[100.0, 101.5, 102.0])

    log = detect(stored, refetched)

    assert log["instrument_id"].tolist() == ["QQQ"]


def test_two_empty_frames_detect_nothing() -> None:
    """The boundary: nothing stored, nothing fetched, and still the canonical columns."""
    empty = BARS_SCHEMA.empty_table().to_pandas()

    log = detect(empty, empty)

    assert log.empty
    assert list(log.columns) == REVISIONS_SCHEMA.names


def test_the_log_is_ordered_by_date_then_by_declared_field() -> None:
    """Input row order must not leak into the output: reproducibility is bit for bit."""
    scrambled = [SESSIONS[2], SESSIONS[0], SESSIONS[1]]
    stored = bars(scrambled)
    refetched = bars(
        scrambled,
        fetch_id=NEW_FETCH,
        opens=[101.0, 99.5, 100.0],
        closes=[112.0, 100.5, 101.0],
    )

    log = detect(stored, refetched)

    assert list(zip(log["observation_date"], log["field"], strict=True)) == [
        (SESSIONS[0], "open"),
        (SESSIONS[0], "close"),
        (SESSIONS[2], "close"),
    ]


def test_a_later_session_does_not_change_what_is_reported_for_earlier_ones() -> None:
    """The look-ahead guard: each date is judged on its own two rows and nothing else."""
    stored = bars(SESSIONS[:2])
    refetched = bars(SESSIONS[:2], fetch_id=NEW_FETCH, closes=[100.0, 101.5])

    before = detect(stored, refetched)

    with_a_future_session = detect(
        bars(SESSIONS),
        bars(SESSIONS, fetch_id=NEW_FETCH, closes=[100.0, 101.5, 999.0]),
    )

    assert with_a_future_session.iloc[:1].to_dict("records") == before.to_dict("records")


@pytest.mark.parametrize("side", ["existing", "incoming"])
def test_a_repeated_date_is_rejected(side: str) -> None:
    """Which of the two rows is the stored value? Unanswerable, so it is a caller bug."""
    doubled = bars([SESSIONS[0], SESSIONS[0], SESSIONS[1]])
    single = bars(SESSIONS[:2], fetch_id=NEW_FETCH)
    existing, incoming = (doubled, single) if side == "existing" else (single, doubled)

    with pytest.raises(ValueError, match="repeat"):
        detect(existing, incoming)


@pytest.mark.parametrize("side", ["existing", "incoming"])
def test_rows_mixing_two_instruments_are_rejected(side: str) -> None:
    """One call compares one instrument; a frame holding two is a caller bug."""
    mixed = pd.concat(
        [bars(SESSIONS[:2]), bars(SESSIONS[2:], instrument_id="QQQ")], ignore_index=True
    )
    single = bars(fetch_id=NEW_FETCH)
    existing, incoming = (mixed, single) if side == "existing" else (single, mixed)

    with pytest.raises(ValueError, match="mix"):
        detect(existing, incoming)


def test_two_different_instruments_are_never_compared() -> None:
    """SPY's stored bars against QQQ's refetch would report the whole series as revised."""
    with pytest.raises(ValueError, match="cannot be compared"):
        detect(bars(), bars(instrument_id="QQQ", fetch_id=NEW_FETCH))


@pytest.mark.parametrize("column", ["session_date", "close"])
def test_a_frame_without_a_compared_column_is_rejected(column: str) -> None:
    """A column that is not there is a malformed caller, not an absence of revisions."""
    with pytest.raises(ValueError, match=column):
        detect(bars().drop(columns=column), bars(fetch_id=NEW_FETCH))


def test_a_naive_detection_instant_is_rejected() -> None:
    """A timestamp with no zone is one nobody can place later; the log keeps UTC only."""
    with pytest.raises(ValueError, match="UTC"):
        detect_revisions(
            bars(),
            bars(fetch_id=NEW_FETCH),
            table="bars",
            key_column="session_date",
            value_columns=BAR_FIELDS,
            new_fetch_id=NEW_FETCH,
            detected_at_utc=datetime(2026, 9, 13, 21, 3, 11),
        )


def test_a_detected_revision_can_be_appended_to_the_log_7_4(market_root: Path) -> None:
    """The frame is the repository's contract, dtypes included, not merely the right columns."""
    stored = bars()
    log = detect(stored, bars(fetch_id=NEW_FETCH, closes=[100.0, 101.5, 102.0]))
    repository = MarketDataRepository(market_root)

    repository.append_revisions(log)

    assert repository.load_revisions()["new_value"].tolist() == [101.5]


# --- 7.5 merge_with_policy ----------------------------------------------------

NOTHING_ACCEPTED = AcceptedRevisions([])
"""The normal state: nothing reviewed, so nothing may move."""


def accepting(
    *fields: str,
    observation_date: date = SESSIONS[1],
    instrument_id: str = "SPY",
    source: str = "YAHOO",
    table: str = "bars",
    old_value: float = 101.0,
    new_value: float = 101.5,
) -> AcceptedRevisions:
    """Build the reviewed decision letting one transition of one date through.

    The defaults are the move the frames below make: the middle session's close
    from 101.0 to 101.5. A decision names the values, so a test that moves a
    field somewhere else has to say so.
    """
    return AcceptedRevisions(
        [
            AcceptedRevision(
                instrument_id=instrument_id,
                source=source,
                table=table,
                observation_date=observation_date,
                field=field,
                old_value=old_value,
                new_value=new_value,
                reason="Checked against a second source.",
            )
            for field in fields
        ]
    )


def merge(
    existing: pd.DataFrame,
    incoming: pd.DataFrame,
    accepted: AcceptedRevisions = NOTHING_ACCEPTED,
) -> pd.DataFrame:
    """Merge two bar frames under the stability policy."""
    return merge_with_policy(
        existing,
        incoming,
        accepted,
        table="bars",
        key_column="session_date",
        value_columns=BAR_FIELDS,
    )


def test_an_unaccepted_revision_leaves_the_stored_value_in_place() -> None:
    """The reason the module exists: the same backtest prints the same number in a month."""
    stored = bars()
    refetched = bars(fetch_id=NEW_FETCH, closes=[100.0, 101.5, 102.0])

    merged = merge(stored, refetched)

    assert merged["close"].tolist() == [100.0, 101.0, 102.0]
    assert merged["source_fetch_id"].tolist() == [OLD_FETCH] * 3


def test_an_accepted_revision_is_applied() -> None:
    """A line in the committed decisions file is the only thing that moves history."""
    stored = bars()
    refetched = bars(fetch_id=NEW_FETCH, closes=[100.0, 101.5, 102.0])

    merged = merge(stored, refetched, accepting("close"))

    assert merged["close"].tolist() == [100.0, 101.5, 102.0]


def test_acceptance_moves_the_named_field_and_no_other() -> None:
    """A reviewed close does not drag the same day's unreviewed open along with it."""
    stored = bars()
    refetched = bars(
        fetch_id=NEW_FETCH,
        opens=[99.0, 100.5, 101.0],
        closes=[100.0, 101.5, 102.0],
    )

    merged = merge(stored, refetched, accepting("close"))

    assert merged["close"].tolist() == [100.0, 101.5, 102.0]
    assert merged["open"].tolist() == [99.0, 100.0, 101.0]


def test_an_applied_correction_takes_the_incoming_fetch_id() -> None:
    """Provenance follows the value: that fetch is the one to reopen when re-examining it."""
    stored = bars()
    refetched = bars(fetch_id=NEW_FETCH, closes=[100.0, 101.5, 102.0])

    merged = merge(stored, refetched, accepting("close"))

    assert merged["source_fetch_id"].tolist() == [OLD_FETCH, NEW_FETCH, OLD_FETCH]


def test_an_accepted_field_that_did_not_move_leaves_provenance_alone() -> None:
    """Acceptance is permission, not an instruction: nothing moved, nothing is rewritten."""
    merged = merge(bars(), bars(fetch_id=NEW_FETCH), accepting("close"))  # nothing moved

    assert merged["source_fetch_id"].tolist() == [OLD_FETCH] * 3


def test_a_date_absent_from_the_stored_series_is_appended() -> None:
    """A session we never held is new data, not a decision."""
    merged = merge(bars(SESSIONS[:2]), bars(fetch_id=NEW_FETCH))

    assert merged["session_date"].tolist() == SESSIONS
    assert merged["source_fetch_id"].tolist() == [OLD_FETCH, OLD_FETCH, NEW_FETCH]


def test_a_date_the_refetch_does_not_reach_survives() -> None:
    """A shorter window is not the provider withdrawing history."""
    merged = merge(bars(), bars(SESSIONS[1:], fetch_id=NEW_FETCH))

    assert merged["session_date"].tolist() == SESSIONS


def test_the_merge_is_chronological_whatever_the_input_order() -> None:
    """Neither side's row order reaches the clean layer."""
    merged = merge(bars([SESSIONS[2], SESSIONS[0]]), bars([SESSIONS[1]], fetch_id=NEW_FETCH))

    assert merged["session_date"].tolist() == SESSIONS


def test_a_value_that_vanished_is_not_dropped_without_review() -> None:
    """A hole appearing in the refetch would silently delete a number we traded on."""
    stored = bars()
    refetched = bars(fetch_id=NEW_FETCH, closes=[100.0, math.nan, 102.0])

    merged = merge(stored, refetched)

    assert merged["close"].tolist() == [100.0, 101.0, 102.0]


def test_a_reviewed_disappearance_is_applied() -> None:
    """Reviewed is reviewed: if the value really was wrong, the hole is the correction."""
    stored = bars()
    refetched = bars(fetch_id=NEW_FETCH, closes=[100.0, math.nan, 102.0])

    merged = merge(stored, refetched, accepting("close", new_value=math.nan))

    assert math.isnan(merged["close"].iloc[1])


@pytest.mark.parametrize(
    "accepted",
    [
        accepting("close", instrument_id="QQQ"),
        accepting("close", table="levels"),
        accepting("close", observation_date=SESSIONS[0]),
        accepting("open"),
        accepting("close", new_value=101.9),
    ],
    ids=["other-instrument", "other-table", "other-date", "other-field", "other-value"],
)
def test_a_decision_differing_in_any_part_does_not_apply(accepted: AcceptedRevisions) -> None:
    """The six parts of a decision are one key; a near miss is a miss.

    ``other-value`` is the one that was missing. Keyed on the field and the date
    alone, a decision reviewed once stood for ever: accepting 101.0 -> 101.5 also
    accepted every later move of that close, unreviewed.
    """
    stored = bars()
    refetched = bars(fetch_id=NEW_FETCH, closes=[100.0, 101.5, 102.0])

    merged = merge(stored, refetched, accepted)

    assert merged["close"].tolist() == [100.0, 101.0, 102.0]


def test_an_empty_stored_series_takes_the_refetch() -> None:
    """First download: everything is new, nothing is a revision."""
    merged = merge(BARS_SCHEMA.empty_table().to_pandas(), bars(fetch_id=NEW_FETCH))

    assert merged["session_date"].tolist() == SESSIONS
    assert merged["source_fetch_id"].tolist() == [NEW_FETCH] * 3


def test_two_empty_sides_stay_empty_with_the_canonical_columns() -> None:
    """The boundary: nothing stored, nothing fetched, still a canonical frame."""
    empty = BARS_SCHEMA.empty_table().to_pandas()

    merged = merge(empty, empty)

    assert merged.empty
    assert list(merged.columns) == BARS_SCHEMA.names


def test_the_merge_keeps_the_canonical_dtypes() -> None:
    """Rebuilt rows must not quietly become objects: the clean layer is schema-checked."""
    stored = bars()
    refetched = bars(fetch_id=NEW_FETCH, closes=[100.0, 101.5, 102.0])

    merged = merge(stored, refetched, accepting("close"))

    assert merged.dtypes.to_dict() == stored.dtypes.to_dict()


def test_a_merged_series_can_be_saved_and_read_back(market_root: Path) -> None:
    """The merge feeds the clean layer, so it must satisfy the bars schema."""
    repository = MarketDataRepository(market_root)
    stored = bars()
    refetched = bars(fetch_id=NEW_FETCH, closes=[100.0, 101.5, 102.0])

    repository.save_bars("SPY", merge(stored, refetched, accepting("close")))

    assert repository.load_bars("SPY")["close"].tolist() == [100.0, 101.5, 102.0]


def test_a_later_session_does_not_change_earlier_merged_rows() -> None:
    """The look-ahead guard: a date is decided on its own rows and the decisions file."""
    before = merge(
        bars(SESSIONS[:2]),
        bars(SESSIONS[:2], fetch_id=NEW_FETCH, closes=[100.0, 101.5]),
        accepting("close"),
    )

    with_a_future_session = merge(
        bars(SESSIONS),
        bars(SESSIONS, fetch_id=NEW_FETCH, closes=[100.0, 101.5, 999.0]),
        accepting("close"),
    )

    assert with_a_future_session.iloc[:2].to_dict("records") == before.to_dict("records")


def test_levels_merge_on_their_own_key_column() -> None:
    """One policy, either table."""
    stored = levels(values=[4.10, 4.11, 4.12])
    refetched = levels(values=[4.10, 4.15, 4.12], fetch_id=NEW_FETCH)

    merged = merge_with_policy(
        stored,
        refetched,
        accepting(
            "value",
            instrument_id="US10Y",
            source="FRED",
            table="levels",
            old_value=4.11,
            new_value=4.15,
        ),
        table="levels",
        key_column="observation_date",
        value_columns=("value",),
    )

    assert merged["value"].tolist() == [4.10, 4.15, 4.12]


def test_what_the_log_records_is_exactly_what_the_merge_refused() -> None:
    """Detection and decision are two halves of one story: written down, and not applied."""
    stored = bars()
    refetched = bars(fetch_id=NEW_FETCH, closes=[100.0, 101.5, 102.0])

    log = detect(stored, refetched)
    merged = merge(stored, refetched)

    assert log["field"].tolist() == ["close"]
    assert merged["close"].tolist() == stored["close"].tolist()


@pytest.mark.parametrize("side", ["existing", "incoming"])
def test_the_merge_rejects_a_repeated_date(side: str) -> None:
    """Same refusal as detection: an ambiguous row is a caller bug."""
    doubled = bars([SESSIONS[0], SESSIONS[0], SESSIONS[1]])
    single = bars(SESSIONS[:2], fetch_id=NEW_FETCH)
    existing, incoming = (doubled, single) if side == "existing" else (single, doubled)

    with pytest.raises(ValueError, match="repeat"):
        merge(existing, incoming)


def test_the_merge_rejects_two_different_instruments() -> None:
    """Merging QQQ's refetch into SPY's history would rewrite the series wholesale."""
    with pytest.raises(ValueError, match="cannot be compared"):
        merge(bars(), bars(instrument_id="QQQ", fetch_id=NEW_FETCH))


def test_the_merge_rejects_frames_with_different_columns() -> None:
    """Two shapes cannot be merged into one canonical frame."""
    with pytest.raises(ValueError, match="different columns"):
        merge(bars(), bars(fetch_id=NEW_FETCH).drop(columns="volume"))


def test_the_merge_rejects_frames_without_a_compared_column() -> None:
    """A column the policy governs but the frames lack is a malformed caller."""
    stored = bars().drop(columns="close")
    refetched = bars(fetch_id=NEW_FETCH).drop(columns="close")

    with pytest.raises(ValueError, match="close"):
        merge(stored, refetched)


def test_a_value_that_is_not_a_number_is_rejected(tmp_path: Path) -> None:
    """The transition is the key: a string or a boolean cannot stand for a value."""
    content = TWO_REVISIONS.replace("old_value = 6590.25", 'old_value = "6590.25"')
    with pytest.raises(ValueError, match="old_value"):
        AcceptedRevisions.from_toml(write(tmp_path, content))


def test_a_withdrawal_is_written_nan(tmp_path: Path) -> None:
    """A value vanishing is a correction like any other, and reviewable like one."""
    content = TWO_REVISIONS.replace("new_value = 6591.1", "new_value = nan")
    accepted = AcceptedRevisions.from_toml(write(tmp_path, content))
    assert accepted.is_accepted(
        "SP500", "YAHOO", "bars", date(2026, 9, 10), "close", SP500_MOVE[0], math.nan
    )
    assert not accepted.is_accepted(
        "SP500", "YAHOO", "bars", date(2026, 9, 10), "close", *SP500_MOVE
    )


def test_a_decision_that_moves_nothing_is_rejected() -> None:
    """Accepting a value onto itself is not a decision, it is a typo."""
    with pytest.raises(ValueError, match="the same"):
        AcceptedRevisions([replace(SP500_CLOSE, new_value=SP500_CLOSE.old_value)])


# --- the whole decision workflow, end to end --------------------------------


def test_a_detected_revision_becomes_an_entry_that_applies_it(tmp_path: Path) -> None:
    """revisions.parquet -> TOML entry -> from_toml -> the exact correction applies.

    Every link matters and each one has broken at some point: the entry has to
    name the source and both values, the floats have to round-trip to the bit,
    and what comes back has to match the correction that was detected rather
    than merely the field it touched.
    """
    stored = bars()
    refetched = bars(fetch_id=NEW_FETCH, closes=[100.0, 101.5, 102.0])
    log = detect(stored, refetched)
    assert len(log) == 1

    entry = AcceptedRevision.from_detected(log.to_dict("records")[0], "Checked against Stooq.")
    accepted = AcceptedRevisions.from_toml(write(tmp_path, entry.to_toml()))

    merged = merge(stored, refetched, accepted)

    assert merged["close"].tolist() == [100.0, 101.5, 102.0]


def test_the_generated_entry_is_about_that_correction_and_no_other(tmp_path: Path) -> None:
    """The round trip must not quietly widen into a permission over the field."""
    stored = bars()
    log = detect(stored, bars(fetch_id=NEW_FETCH, closes=[100.0, 101.5, 102.0]))
    entry = AcceptedRevision.from_detected(log.to_dict("records")[0], "Checked.")
    accepted = AcceptedRevisions.from_toml(write(tmp_path, entry.to_toml()))

    # The same field and date, moving somewhere else.
    merged = merge(stored, bars(fetch_id=NEW_FETCH, closes=[100.0, 101.9, 102.0]), accepted)

    assert merged["close"].tolist() == [100.0, 101.0, 102.0]


def test_a_withdrawn_value_round_trips_through_the_entry(tmp_path: Path) -> None:
    """``nan`` is a value like any other, and has to survive being written down."""
    stored = bars()
    refetched = bars(fetch_id=NEW_FETCH, closes=[100.0, math.nan, 102.0])
    log = detect(stored, refetched)

    entry = AcceptedRevision.from_detected(log.to_dict("records")[0], "The print was wrong.")
    assert "nan" in entry.to_toml()
    accepted = AcceptedRevisions.from_toml(write(tmp_path, entry.to_toml()))

    merged = merge(stored, refetched, accepted)

    assert math.isnan(merged["close"].iloc[1])


def test_a_reason_holding_a_quote_survives_the_entry(tmp_path: Path) -> None:
    """A reason is free text: it must not be able to break the file it goes into."""
    stored = bars()
    log = detect(stored, bars(fetch_id=NEW_FETCH, closes=[100.0, 101.5, 102.0]))
    reason = 'Checked against "Stooq", and against the exchange\'s own export.'

    entry = AcceptedRevision.from_detected(log.to_dict("records")[0], reason)
    accepted = AcceptedRevisions.from_toml(write(tmp_path, entry.to_toml()))

    assert accepted.is_accepted("SPY", "YAHOO", "bars", SESSIONS[1], "close", 101.0, 101.5)
