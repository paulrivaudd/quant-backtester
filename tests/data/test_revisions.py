"""Accepted revisions: the reviewed decisions that let a provider correction through.

Offline: TOML files are written under ``tmp_path``, plus the committed one.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from quant_backtester.data.revisions import AcceptedRevision, AcceptedRevisions

COMMITTED = (
    Path(__file__).resolve().parents[2] / "market_data" / "metadata" / "accepted_revisions.toml"
)

SP500_CLOSE = AcceptedRevision(
    instrument_id="SP500",
    table="bars",
    observation_date=date(2026, 9, 10),
    field="close",
    reason="Yahoo corrected an obviously wrong print; checked against another source.",
)

US10Y_VALUE = AcceptedRevision(
    instrument_id="US10Y",
    table="levels",
    observation_date=date(2026, 9, 9),
    field="value",
    reason="FRED restated the H.15 value.",
)


def write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "accepted_revisions.toml"
    path.write_text(content, encoding="utf-8")
    return path


TWO_REVISIONS = """
[[revision]]
instrument_id = "SP500"
table = "bars"
observation_date = 2026-09-10
field = "close"
reason = "Yahoo corrected an obviously wrong print; checked against another source."

[[revision]]
instrument_id = "US10Y"
table = "levels"
observation_date = 2026-09-09
field = "value"
reason = "FRED restated the H.15 value."
"""


# --- 7.1 AcceptedRevisions ----------------------------------------------------


def test_no_decision_is_valid_and_accepts_nothing() -> None:
    accepted = AcceptedRevisions([])
    assert not accepted.is_accepted("SP500", "bars", date(2026, 9, 10), "close")


def test_decisions_are_accepted_for_bars_and_levels() -> None:
    accepted = AcceptedRevisions([SP500_CLOSE, US10Y_VALUE])
    assert accepted.is_accepted("SP500", "bars", date(2026, 9, 10), "close")
    assert accepted.is_accepted("US10Y", "levels", date(2026, 9, 9), "value")


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
        "table": "bars",
        "observation_date": date(2026, 9, 10),
        "field": "close",
        "reason": "Checked.",
    }
    fields.update(overrides)
    with pytest.raises(ValueError, match=match):
        AcceptedRevisions([AcceptedRevision(**fields)])  # type: ignore[arg-type]


def test_the_same_correction_accepted_twice_is_rejected() -> None:
    again = AcceptedRevision(
        instrument_id="SP500",
        table="bars",
        observation_date=date(2026, 9, 10),
        field="close",
        reason="A second, different review of the same correction.",
    )
    with pytest.raises(ValueError, match="more than once"):
        AcceptedRevisions([SP500_CLOSE, again])


def test_the_same_day_on_two_fields_is_two_distinct_decisions() -> None:
    open_too = AcceptedRevision(
        instrument_id="SP500",
        table="bars",
        observation_date=date(2026, 9, 10),
        field="open",
        reason="The open was corrected as well.",
    )
    accepted = AcceptedRevisions([SP500_CLOSE, open_too])
    assert accepted.is_accepted("SP500", "bars", date(2026, 9, 10), "open")


def test_decisions_do_not_change_when_the_callers_list_does() -> None:
    decisions = [SP500_CLOSE]
    accepted = AcceptedRevisions(decisions)
    decisions.append(US10Y_VALUE)
    assert not accepted.is_accepted("US10Y", "levels", date(2026, 9, 9), "value")


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
    assert not accepted.is_accepted(instrument_id, table, observation_date, field)


def test_a_datetime_never_matches_the_date_of_a_decision() -> None:
    accepted = AcceptedRevisions([SP500_CLOSE])
    at_midnight = datetime(2026, 9, 10)
    assert not accepted.is_accepted("SP500", "bars", at_midnight, "close")


# --- 7.2 from_toml ------------------------------------------------------------


def test_the_committed_file_loads_and_accepts_nothing_yet() -> None:
    accepted = AcceptedRevisions.from_toml(COMMITTED)
    assert not accepted.is_accepted("SP500", "bars", date(2026, 9, 10), "close")


def test_a_missing_file_means_nothing_accepted(tmp_path: Path) -> None:
    accepted = AcceptedRevisions.from_toml(tmp_path / "absent.toml")
    assert not accepted.is_accepted("SP500", "bars", date(2026, 9, 10), "close")


def test_a_file_with_comments_only_accepts_nothing(tmp_path: Path) -> None:
    accepted = AcceptedRevisions.from_toml(write(tmp_path, "# Nothing reviewed yet.\n"))
    assert not accepted.is_accepted("SP500", "bars", date(2026, 9, 10), "close")


def test_from_toml_reads_every_revision_table(tmp_path: Path) -> None:
    accepted = AcceptedRevisions.from_toml(write(tmp_path, TWO_REVISIONS))
    assert accepted.is_accepted("SP500", "bars", date(2026, 9, 10), "close")
    assert accepted.is_accepted("US10Y", "levels", date(2026, 9, 9), "value")
    assert not accepted.is_accepted("SP500", "bars", date(2026, 9, 10), "open")


def test_the_example_documented_in_the_committed_file_is_valid(tmp_path: Path) -> None:
    # Uncommenting the example must give a loadable decision.
    example = "\n".join(
        line[2:]
        for line in COMMITTED.read_text(encoding="utf-8").splitlines()
        if line.startswith("# [[revision]]") or (line.startswith("# ") and " = " in line)
    )
    accepted = AcceptedRevisions.from_toml(write(tmp_path, example))
    assert accepted.is_accepted("SP500", "bars", date(2026, 9, 10), "close")


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
