"""Ingestion: revision policy and the reproducibility property."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import BinaryIO

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from quant_backtester.data.repository import write_parquet_atomic
from quant_backtester.data.schemas import LEVELS_SCHEMA


@pytest.mark.skip(reason="Exercice 9.5 - test 3/3")
def test_rebuild_is_idempotent(market_root):
    """Rebuilding the clean layer twice produces identical files.

    This is the test everyone forgets to write, and the one that proves the
    pipeline has no hidden state: no clock read, no dictionary ordering, no
    absolute path leaking into the output.
    """


@pytest.mark.skip(reason="Exercice 7.5")
def test_unaccepted_revision_leaves_history_unchanged(market_root):
    """A provider changing a stored value is logged and ignored by default.

    The same backtest must not print a different number three weeks later
    because Yahoo adjusted a past close by a cent.
    """


@pytest.mark.skip(reason="Exercice 7.5")
def test_accepted_revision_is_applied(market_root):
    """A revision listed in accepted_revisions.toml does get applied."""


@pytest.mark.skip(reason="Exercice 7.4")
def test_new_observations_are_not_reported_as_revisions(market_root):
    """A date present only in the incoming frame is new data, not a revision."""


@pytest.mark.skip(reason="Exercice 9.3")
def test_constant_factor_shift_triggers_a_full_refetch(market_root):
    """A whole-series rebasing is not a revision and must not be merged partially.

    If the overlap differs from the stored rows by a constant factor, the
    provider changed convention. Merging five days into an old basis would
    fabricate a fake move in the middle of the series - one that passes every
    other check.
    """


def test_interrupted_write_leaves_the_previous_file_intact(market_root, monkeypatch):
    """An exception mid-write must not destroy the existing dataset."""
    path = market_root / "clean" / "levels" / "US10Y.parquet"
    stored = pd.DataFrame(
        {
            "instrument_id": ["US10Y"],
            "observation_date": [date(2026, 1, 2)],
            "value": [4.1],
            "available_at_utc": pd.DatetimeIndex(
                [datetime(2026, 1, 2, 21, 15, tzinfo=UTC)]
            ).as_unit("us"),
            "source": ["FRED"],
            "source_fetch_id": ["20260103T000000Z"],
        }
    )
    write_parquet_atomic(stored, path, LEVELS_SCHEMA)
    before = path.read_bytes()

    def crash_mid_write(table: pa.Table, where: BinaryIO) -> None:
        where.write(b"PAR1 half a file")
        raise RuntimeError("disk full")

    monkeypatch.setattr(pq, "write_table", crash_mid_write)
    with pytest.raises(RuntimeError, match="disk full"):
        write_parquet_atomic(stored.assign(value=[9.9]), path, LEVELS_SCHEMA)

    assert path.read_bytes() == before
    assert [p.name for p in path.parent.iterdir()] == ["US10Y.parquet"]


@pytest.mark.skip(reason="Exercice 9.2")
def test_invalid_frame_is_archived_raw_but_not_promoted(market_root):
    """A failed validation keeps the raw snapshot and leaves clean untouched."""
