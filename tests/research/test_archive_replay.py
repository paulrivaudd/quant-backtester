"""Tests of the replay of a retrieval archive: a file is the recorded one, or it is refused."""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from tests.research.test_sa17_mechanism import RETRIEVED, factor_zip

from quant_backtester.data.sources.ken_french import KenFrenchDataset
from quant_backtester.research.archive_replay import checked_bytes, record_month, replay_french

FACTORS = f"{KenFrenchDataset.FACTORS.value}.zip"


def archived(folder: Path, rows: list[str], **record: str) -> dict[str, dict[str, Any]]:
    """Write a factor table in ``folder`` and return its coverage record."""
    payload = factor_zip(rows)
    (folder / FACTORS).write_bytes(payload)
    entry = {
        "sha256": hashlib.sha256(payload).hexdigest(),
        "retrieved_at_utc": RETRIEVED.isoformat(),
        "first_month": "192607",
        "last_month": "192609",
    }
    return {FACTORS: {**entry, **record}}


ROWS = ["192607,2.96,0,0,0.22\n", "192608,2.64,0,0,0.25\n", "192609,0.36,0,0,0.23\n"]


def test_a_record_month_is_the_first_day_of_the_month_written() -> None:
    assert record_month("192607") == date(1926, 7, 1)
    assert record_month("201812") == date(2018, 12, 1)


@pytest.mark.parametrize(
    "value",
    ["201813", "201800", "2018-1", "20181", "1926071", "", "\uff11\uff19\uff12\uff16\uff10\uff17"],
)
def test_a_record_month_that_names_no_month_is_refused(value: str) -> None:
    with pytest.raises(ValueError):
        record_month(value)


def test_archived_bytes_are_returned_only_if_they_hash_to_their_record(tmp_path: Path) -> None:
    (tmp_path / "file.csv").write_bytes(b"as archived")
    recorded = {"file.csv": {"sha256": hashlib.sha256(b"as archived").hexdigest()}}
    assert checked_bytes(tmp_path, recorded, "file.csv") == b"as archived"
    (tmp_path / "file.csv").write_bytes(b"as altered")
    with pytest.raises(ValueError, match="not to the record"):
        checked_bytes(tmp_path, recorded, "file.csv")


def test_a_file_the_records_do_not_name_or_the_archive_does_not_hold_is_refused(
    tmp_path: Path,
) -> None:
    (tmp_path / "unrecorded.csv").write_bytes(b"present, and nobody recorded it")
    with pytest.raises(ValueError, match="do not name this file"):
        checked_bytes(tmp_path, {}, "unrecorded.csv")
    with pytest.raises(FileNotFoundError):
        checked_bytes(tmp_path, {"missing.csv": {"sha256": "0" * 64}}, "missing.csv")
    with pytest.raises(ValueError, match="do not name this file"):
        replay_french(tmp_path, {}, KenFrenchDataset.FACTORS)
    (tmp_path / FACTORS).unlink(missing_ok=True)
    with pytest.raises(FileNotFoundError):
        replay_french(tmp_path, {FACTORS: {"sha256": "0" * 64}}, KenFrenchDataset.FACTORS)


def test_a_french_table_is_replayed_over_the_months_its_record_states(tmp_path: Path) -> None:
    recorded = archived(tmp_path, ROWS)
    table = replay_french(tmp_path, recorded, KenFrenchDataset.FACTORS)
    assert table.months == (date(1926, 7, 1), date(1926, 8, 1), date(1926, 9, 1))
    # The record bounds the months kept: a narrower record, a narrower table.
    narrower = archived(tmp_path, ROWS, last_month="192608")
    table = replay_french(tmp_path, narrower, KenFrenchDataset.FACTORS)
    assert table.months == (date(1926, 7, 1), date(1926, 8, 1))


def test_a_french_file_altered_since_its_retrieval_is_refused(tmp_path: Path) -> None:
    recorded = archived(tmp_path, ROWS)
    (tmp_path / FACTORS).write_bytes(factor_zip(ROWS[:2]))
    with pytest.raises(ValueError, match="not to the record"):
        replay_french(tmp_path, recorded, KenFrenchDataset.FACTORS)
    # The bytes are refused before anything else of the record is read.
    with pytest.raises(ValueError, match="not to the record"):
        replay_french(tmp_path, {FACTORS: {"sha256": "0" * 64}}, KenFrenchDataset.FACTORS)


def test_a_record_without_a_timezone_or_with_a_month_not_written_as_one_is_refused(
    tmp_path: Path,
) -> None:
    naive = archived(tmp_path, ROWS, retrieved_at_utc="2026-11-07T16:01:00")
    with pytest.raises(ValueError, match="no timezone"):
        replay_french(tmp_path, naive, KenFrenchDataset.FACTORS)
    with pytest.raises(ValueError, match="YYYYMM"):
        replay_french(
            tmp_path, archived(tmp_path, ROWS, first_month="19267"), KenFrenchDataset.FACTORS
        )
