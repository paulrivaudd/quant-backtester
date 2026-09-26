"""Repository: atomic Parquet writes and the immutable raw archive.

Everything runs against the ``market_root`` temporary tree: no network, no
wall clock, no shared state between tests.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq
import pytest

from quant_backtester.data.repository import MarketDataRepository, write_parquet_atomic
from quant_backtester.data.schemas import (
    BARS_SCHEMA,
    CHECKED_BARS_SCHEMA,
    CORPORATE_ACTIONS_SCHEMA,
    LEVELS_SCHEMA,
    REVISIONS_SCHEMA,
    VALIDATION_LOG_SCHEMA,
)
from quant_backtester.data.sources.base import RawDownload
from quant_backtester.data.validator import Severity, ValidationIssue, ValidationReport

RETRIEVED_AT = datetime(2026, 9, 12, 21, 3, 11, tzinfo=UTC)
"""Instant of the synthetic fetch; ``FETCH_ID`` is its compact form."""

FETCH_ID = "20260912T210311Z"


def make_levels(**overrides: object) -> pd.DataFrame:
    """Build a valid two-row levels frame, with the columns under test overridden."""
    columns: dict[str, Any] = {
        "instrument_id": ["US10Y", "US10Y"],
        "observation_date": [date(2026, 1, 2), date(2026, 1, 5)],
        "value": [4.1, 4.2],
        "available_at_utc": pd.DatetimeIndex(
            [datetime(2026, 1, 2, 21, 15, tzinfo=UTC), datetime(2026, 1, 5, 21, 15, tzinfo=UTC)]
        ).as_unit("us"),
        "source": ["FRED", "FRED"],
        "source_fetch_id": [FETCH_ID, FETCH_ID],
    }
    columns.update(overrides)
    return pd.DataFrame(columns)


def make_download(**overrides: object) -> RawDownload:
    """Build a Yahoo-like raw download, with the fields under test overridden.

    The frame keeps the provider's own shape: capitalised columns and a
    New York ``Date`` index. Nothing about it is canonical, on purpose.
    """
    frame = pd.DataFrame(
        {"Open": [100.0, 101.0], "Close": [100.5, 101.5], "Volume": [1_000, 2_000]},
        index=pd.DatetimeIndex(["2026-09-10", "2026-09-11"], name="Date").tz_localize(
            "America/New_York"
        ),
    )
    fields: dict[str, Any] = {
        "instrument_id": "SPY",
        "source": "YAHOO",
        "fetch_id": FETCH_ID,
        "retrieved_at_utc": RETRIEVED_AT,
        "frame": frame,
        "request": {"symbol": "SPY", "start": date(2026, 9, 10), "yfinance": "1.7.0"},
    }
    fields.update(overrides)
    return RawDownload(**fields)


# --- 3.1 write_parquet_atomic -------------------------------------------------


def test_valid_frame_round_trips(market_root):
    """A frame matching the schema reads back unchanged, parents created."""
    path = market_root / "clean" / "levels" / "US10Y.parquet"
    frame = make_levels()

    write_parquet_atomic(frame, path, LEVELS_SCHEMA)

    pd.testing.assert_frame_equal(pq.read_table(path).to_pandas(), frame)


def test_file_carries_the_declared_schema(market_root):
    """Column order and types on disk follow the schema, not the frame.

    The frame is given with its columns reversed and an integer ``value``: both
    are lossless to fix, and the file must not depend on how the caller built it.
    """
    path = market_root / "levels.parquet"
    frame = make_levels(value=[4, 5])
    reversed_frame = frame.reindex(columns=list(reversed(frame.columns)))

    write_parquet_atomic(reversed_frame, path, LEVELS_SCHEMA)

    stored = pq.read_schema(path)
    assert stored.names == LEVELS_SCHEMA.names
    assert stored.types == LEVELS_SCHEMA.types


def test_empty_frame_with_the_right_columns_is_written(market_root):
    """Zero rows is a valid dataset, not an error."""
    path = market_root / "empty.parquet"

    write_parquet_atomic(make_levels().iloc[0:0], path, LEVELS_SCHEMA)

    assert pq.read_table(path).num_rows == 0


def test_existing_file_is_replaced(market_root):
    """A second write replaces the first and leaves no temporary file behind."""
    path = market_root / "clean" / "levels" / "US10Y.parquet"
    write_parquet_atomic(make_levels(), path, LEVELS_SCHEMA)

    write_parquet_atomic(make_levels(value=[5.0, 6.0]), path, LEVELS_SCHEMA)

    assert pq.read_table(path).column("value").to_pylist() == [5.0, 6.0]
    assert [p.name for p in path.parent.iterdir()] == ["US10Y.parquet"]


def test_temporary_file_is_renamed_from_the_target_directory(market_root, monkeypatch):
    """The temporary lives next to the target, never in ``/tmp``.

    ``os.replace`` is only atomic within one filesystem: a temporary created
    elsewhere would turn the rename into a copy that a crash can interrupt.
    """
    path = market_root / "clean" / "levels" / "US10Y.parquet"
    renames: list[tuple[Path, Path]] = []
    real_replace = os.replace

    def spy_replace(src: Path, dst: Path) -> None:
        renames.append((Path(src), Path(dst)))
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy_replace)
    write_parquet_atomic(make_levels(), path, LEVELS_SCHEMA)

    assert len(renames) == 1
    source, target = renames[0]
    assert source.parent == path.parent
    assert target == path


@pytest.mark.parametrize(
    "frame",
    [
        make_levels().drop(columns="source"),
        make_levels(extra=[1, 2]),
        make_levels(
            available_at_utc=pd.DatetimeIndex(
                [datetime(2026, 1, 2, 21, 15), datetime(2026, 1, 5, 21, 15)]
            ).as_unit("us")
        ),
        make_levels(
            available_at_utc=pd.DatetimeIndex(
                [datetime(2026, 1, 2, 21, 15, tzinfo=UTC), datetime(2026, 1, 5, 21, 15, tzinfo=UTC)]
            )
            .tz_convert("Europe/Paris")
            .as_unit("us")
        ),
        make_levels(value=[4.1, None]),
        make_levels(value=["4.1", "high"]),
        make_levels().iloc[0:0].drop(columns="value"),
    ],
    ids=[
        "missing-column",
        "extra-column",
        "naive-timestamp",
        "non-utc-timestamp",
        "null-in-non-nullable",
        "text-in-float",
        "empty-with-missing-column",
    ],
)
def test_frame_not_matching_the_schema_is_rejected(market_root, frame):
    """A mismatch raises ``ValueError`` and writes nothing.

    The naive case is the one that matters: Arrow would otherwise store it as
    UTC without a word, shifting every availability instant of a Paris series.
    """
    path = market_root / "levels.parquet"

    with pytest.raises(ValueError):
        write_parquet_atomic(frame, path, LEVELS_SCHEMA)

    assert not path.exists()


def test_rejected_frame_leaves_the_previous_file_intact(market_root):
    """Validation happens before the temporary is even created."""
    path = market_root / "levels.parquet"
    write_parquet_atomic(make_levels(), path, LEVELS_SCHEMA)
    before = path.read_bytes()

    with pytest.raises(ValueError):
        write_parquet_atomic(make_levels().drop(columns="value"), path, LEVELS_SCHEMA)

    assert path.read_bytes() == before
    assert [p.name for p in path.parent.iterdir() if p.suffix == ".tmp"] == []


# --- 3.2 MarketDataRepository.__init__ ----------------------------------------


def test_repository_exposes_its_root(market_root):
    """The root given is the root used."""
    assert MarketDataRepository(market_root).root == market_root


def test_missing_root_is_rejected(market_root):
    """A typo in the path fails at construction instead of reading as "no data"."""
    with pytest.raises(FileNotFoundError):
        MarketDataRepository(market_root / "does-not-exist")


def test_file_as_root_is_rejected(market_root):
    """The root must be a directory."""
    not_a_directory = market_root / "instruments.toml"
    not_a_directory.write_text("")

    with pytest.raises(FileNotFoundError):
        MarketDataRepository(not_a_directory)


# --- 3.3 MarketDataRepository.save_raw ----------------------------------------


def test_save_raw_follows_the_layout(market_root):
    """Data and manifest land under ``raw/<source>/<instrument_id>/``."""
    path = MarketDataRepository(market_root).save_raw(make_download())

    assert path == market_root / "raw" / "YAHOO" / "SPY" / f"{FETCH_ID}.parquet"
    assert sorted(p.name for p in path.parent.iterdir()) == [
        f"{FETCH_ID}.json",
        f"{FETCH_ID}.parquet",
    ]


def test_save_raw_keeps_the_provider_frame_exactly(market_root):
    """Original column names, dtypes and index survive the archive."""
    download = make_download()

    path = MarketDataRepository(market_root).save_raw(download)

    pd.testing.assert_frame_equal(pq.read_table(path).to_pandas(), download.frame)


def test_save_raw_writes_a_readable_manifest(market_root):
    """The manifest explains the snapshot without opening the Parquet file."""
    path = MarketDataRepository(market_root).save_raw(make_download())

    manifest = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))

    assert manifest == {
        "instrument_id": "SPY",
        "source": "YAHOO",
        "fetch_id": FETCH_ID,
        "retrieved_at_utc": "2026-09-12T21:03:11+00:00",
        "row_count": 2,
        "columns": ["Open", "Close", "Volume"],
        "request": {"symbol": "SPY", "start": "2026-09-10", "yfinance": "1.7.0"},
    }


def test_save_raw_refuses_to_overwrite_a_fetch(market_root):
    """Raw is append-only: the same fetch id twice raises and changes nothing."""
    repository = MarketDataRepository(market_root)
    path = repository.save_raw(make_download())
    before = (path.read_bytes(), path.with_suffix(".json").read_bytes())
    altered = make_download(frame=make_download().frame.assign(Close=[0.0, 0.0]))

    with pytest.raises(FileExistsError):
        repository.save_raw(altered)

    assert (path.read_bytes(), path.with_suffix(".json").read_bytes()) == before


def test_save_raw_refuses_a_fetch_whose_manifest_exists(market_root):
    """A manifest alone is enough to claim the fetch id."""
    manifest = market_root / "raw" / "YAHOO" / "SPY" / f"{FETCH_ID}.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("{}")

    with pytest.raises(FileExistsError):
        MarketDataRepository(market_root).save_raw(make_download())


def test_save_raw_keeps_successive_fetches_side_by_side(market_root):
    """A later fetch of the same instrument is a new file, not a replacement."""
    repository = MarketDataRepository(market_root)
    first = repository.save_raw(make_download())
    later = RETRIEVED_AT + timedelta(days=1)

    second = repository.save_raw(make_download(fetch_id="20260913T210311Z", retrieved_at_utc=later))

    assert first.exists()
    assert second.exists()
    assert first != second


@pytest.mark.parametrize(
    "retrieved_at_utc",
    [
        datetime(2026, 9, 12, 21, 3, 11),
        datetime(2026, 9, 12, 23, 3, 11, tzinfo=timezone(timedelta(hours=2))),
    ],
    ids=["naive", "non-utc-offset"],
)
def test_save_raw_rejects_a_non_utc_retrieval_instant(market_root, retrieved_at_utc):
    """The retrieval instant must be UTC; nothing is archived otherwise."""
    with pytest.raises(ValueError, match="retrieved_at_utc"):
        MarketDataRepository(market_root).save_raw(make_download(retrieved_at_utc=retrieved_at_utc))

    assert list((market_root / "raw").iterdir()) == []


# --- 3.4 MarketDataRepository.load_raw ----------------------------------------


def test_load_raw_returns_what_was_saved(market_root):
    """Every field of the archived download comes back."""
    repository = MarketDataRepository(market_root)
    download = make_download()
    repository.save_raw(download)

    loaded = repository.load_raw("SPY", "YAHOO", FETCH_ID)

    assert (loaded.instrument_id, loaded.source, loaded.fetch_id) == ("SPY", "YAHOO", FETCH_ID)
    assert loaded.retrieved_at_utc == RETRIEVED_AT
    assert loaded.retrieved_at_utc.utcoffset() == timedelta(0)
    pd.testing.assert_frame_equal(loaded.frame, download.frame)


def test_load_raw_returns_request_dates_as_iso_strings(market_root):
    """JSON has no date type: a date sent to the provider comes back as text."""
    repository = MarketDataRepository(market_root)
    repository.save_raw(make_download())

    loaded = repository.load_raw("SPY", "YAHOO", FETCH_ID)

    assert dict(loaded.request) == {"symbol": "SPY", "start": "2026-09-10", "yfinance": "1.7.0"}


def test_load_raw_of_an_unknown_fetch_fails(market_root):
    """Asking for a fetch that was never archived raises."""
    with pytest.raises(FileNotFoundError):
        MarketDataRepository(market_root).load_raw("SPY", "YAHOO", FETCH_ID)


def test_load_raw_of_an_interrupted_archive_fails(market_root):
    """Data without its manifest is an archive that did not complete."""
    repository = MarketDataRepository(market_root)
    path = repository.save_raw(make_download())
    path.with_suffix(".json").unlink()

    with pytest.raises(FileNotFoundError):
        repository.load_raw("SPY", "YAHOO", FETCH_ID)


# --- 3.5 MarketDataRepository.list_raw_fetches --------------------------------


def test_list_raw_fetches_of_an_unknown_instrument_is_empty(market_root):
    """No archive yet is an empty list, not an error."""
    assert MarketDataRepository(market_root).list_raw_fetches("SPY", "YAHOO") == []


def test_list_raw_fetches_is_chronological_whatever_the_write_order(market_root):
    """A rebuild replays fetches oldest first, even if they were archived out of order."""
    repository = MarketDataRepository(market_root)
    for fetch_id, day in [
        ("20260914T210000Z", 14),
        ("20260912T210000Z", 12),
        ("20260913T210000Z", 13),
    ]:
        retrieved = datetime(2026, 9, day, 21, 0, tzinfo=UTC)
        repository.save_raw(make_download(fetch_id=fetch_id, retrieved_at_utc=retrieved))

    assert repository.list_raw_fetches("SPY", "YAHOO") == [
        "20260912T210000Z",
        "20260913T210000Z",
        "20260914T210000Z",
    ]


def test_list_raw_fetches_skips_an_interrupted_archive(market_root):
    """A data file whose manifest was never written is not replayed."""
    repository = MarketDataRepository(market_root)
    repository.save_raw(make_download())
    later = repository.save_raw(
        make_download(
            fetch_id="20260913T210311Z", retrieved_at_utc=RETRIEVED_AT + timedelta(days=1)
        )
    )
    later.with_suffix(".json").unlink()

    assert repository.list_raw_fetches("SPY", "YAHOO") == [FETCH_ID]


def test_list_raw_fetches_is_scoped_to_one_instrument_and_source(market_root):
    """Fetches of another instrument or source are not mixed in."""
    repository = MarketDataRepository(market_root)
    repository.save_raw(make_download(instrument_id="QQQ", fetch_id="20260901T000000Z"))
    repository.save_raw(make_download(source="STOOQ", fetch_id="20260902T000000Z"))
    repository.save_raw(make_download())

    assert repository.list_raw_fetches("SPY", "YAHOO") == [FETCH_ID]


# --- 3.6 / 3.7 MarketDataRepository.save_bars and load_bars -------------------

SESSIONS = [date(2026, 9, 8), date(2026, 9, 9), date(2026, 9, 10), date(2026, 9, 11)]
"""Four consecutive NYSE sessions, Tuesday to Friday."""


def make_bars(sessions: list[date] = SESSIONS, instrument_id: str = "SPY") -> pd.DataFrame:
    """Build canonical bars for ``sessions``, open at 13:30 UTC and close at 20:00 UTC."""
    count = len(sessions)
    return pd.DataFrame(
        {
            "instrument_id": [instrument_id] * count,
            "session_date": sessions,
            "open": [100.0 + i for i in range(count)],
            "high": [102.0 + i for i in range(count)],
            "low": [99.0 + i for i in range(count)],
            "close": [101.0 + i for i in range(count)],
            "volume": [1_000.0] * count,
            "open_available_at_utc": pd.DatetimeIndex(
                [datetime.combine(day, time(13, 30), tzinfo=UTC) for day in sessions]
            ).as_unit("us"),
            "close_available_at_utc": pd.DatetimeIndex(
                [datetime.combine(day, time(20, 0), tzinfo=UTC) for day in sessions]
            ).as_unit("us"),
            "source": ["YAHOO"] * count,
            "source_fetch_id": [FETCH_ID] * count,
        }
    )


def test_bars_round_trip(market_root):
    """Saved bars load back unchanged, availability columns included."""
    repository = MarketDataRepository(market_root)
    bars = make_bars()

    repository.save_bars("SPY", bars)

    assert (market_root / "clean" / "bars" / "SPY.parquet").exists()
    pd.testing.assert_frame_equal(repository.load_bars("SPY"), bars)


def test_save_bars_replaces_the_previous_series(market_root):
    """One file per instrument, replaced whole."""
    repository = MarketDataRepository(market_root)
    repository.save_bars("SPY", make_bars())

    repository.save_bars("SPY", make_bars(SESSIONS[:2]))

    assert repository.load_bars("SPY")["session_date"].tolist() == SESSIONS[:2]


@pytest.mark.parametrize(
    "bars",
    [
        make_bars(instrument_id="QQQ"),
        make_bars(list(reversed(SESSIONS))),
        make_bars([SESSIONS[0], SESSIONS[0]]),
        make_bars().drop(columns="close_available_at_utc"),
        make_bars().drop(columns="session_date"),
    ],
    ids=[
        "other-instrument",
        "unsorted",
        "duplicate-session",
        "missing-availability",
        "missing-session-date",
    ],
)
def test_save_bars_rejects_an_invalid_frame(market_root, bars):
    """An invalid frame raises and nothing is written.

    The missing availability column is the dangerous one: without it the reader
    cannot tell when a price became known, which is the whole point of the layer.
    """
    repository = MarketDataRepository(market_root)

    with pytest.raises(ValueError):
        repository.save_bars("SPY", bars)

    assert not (market_root / "clean" / "bars" / "SPY.parquet").exists()


def test_load_bars_of_an_unknown_instrument_has_the_canonical_columns(market_root):
    """No file is zero rows with the same columns and dtypes as a real file."""
    repository = MarketDataRepository(market_root)
    repository.save_bars("SPY", make_bars())

    empty = repository.load_bars("QQQ")

    assert empty.empty
    assert list(empty.columns) == BARS_SCHEMA.names
    pd.testing.assert_series_equal(empty.dtypes, repository.load_bars("SPY").dtypes)


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (SESSIONS[1], SESSIONS[2], SESSIONS[1:3]),
        (SESSIONS[2], None, SESSIONS[2:]),
        (None, SESSIONS[1], SESSIONS[:2]),
        (None, None, SESSIONS),
        (date(2026, 9, 12), date(2026, 9, 13), []),
    ],
    ids=["both-bounds", "start-only", "end-only", "unbounded", "weekend-no-session"],
)
def test_load_bars_bounds_are_inclusive(market_root, start, end, expected):
    """``start`` and ``end`` are both included, and the index restarts at zero."""
    repository = MarketDataRepository(market_root)
    repository.save_bars("SPY", make_bars())

    loaded = repository.load_bars("SPY", start, end)

    assert loaded["session_date"].tolist() == expected
    assert loaded.index.tolist() == list(range(len(expected)))


# --- save_checked_bars and load_checked_bars ----------------------------------


def make_checked_bars(
    sessions: list[date] = SESSIONS, instrument_id: str = "SPY", status: str = "CONFIRMED"
) -> pd.DataFrame:
    """Build cross-checked bars: ``make_bars`` plus the verdict columns."""
    count = len(sessions)
    return make_bars(sessions, instrument_id).assign(
        check_status=[status] * count,
        checked_sources=["EURONEXT,YAHOO"] * count,
        checked_fetch_ids=[f"EURONEXT:{FETCH_ID},YAHOO:{FETCH_ID}"] * count,
        conflicting_fields=[""] * count,
        unconfirmed_fields=[""] * count,
        max_price_rel_diff=[0.0] * count,
        max_volume_rel_diff=[0.0] * count,
    )


def test_checked_bars_round_trip(market_root: Path) -> None:
    """Checked bars load back unchanged, under their own directory."""
    repository = MarketDataRepository(market_root)
    checked = make_checked_bars()

    repository.save_checked_bars("SPY", checked)

    assert (market_root / "clean" / "checked_bars" / "SPY.parquet").exists()
    assert not (market_root / "clean" / "bars" / "SPY.parquet").exists()
    pd.testing.assert_frame_equal(repository.load_checked_bars("SPY"), checked)


def test_checked_bars_keep_every_status_and_missing_differences(market_root: Path) -> None:
    """A single-source row has no difference to report: NaN survives the round trip."""
    repository = MarketDataRepository(market_root)
    checked = make_checked_bars(status="SINGLE_SOURCE").assign(
        checked_sources=["YAHOO"] * len(SESSIONS),
        unconfirmed_fields=["close,high,low,open,volume"] * len(SESSIONS),
        max_price_rel_diff=[float("nan")] * len(SESSIONS),
        max_volume_rel_diff=[float("nan")] * len(SESSIONS),
    )

    repository.save_checked_bars("SPY", checked)

    pd.testing.assert_frame_equal(repository.load_checked_bars("SPY"), checked)


@pytest.mark.parametrize(
    "checked",
    [
        make_checked_bars(instrument_id="QQQ"),
        make_checked_bars(list(reversed(SESSIONS))),
        make_checked_bars([SESSIONS[0], SESSIONS[0]]),
        make_checked_bars(status="PROBABLY_FINE"),
        make_checked_bars().drop(columns="check_status"),
        make_checked_bars().drop(columns="checked_sources"),
        make_bars(),
    ],
    ids=[
        "other-instrument",
        "unsorted",
        "duplicate-session",
        "unknown-status",
        "missing-status",
        "missing-checked-sources",
        "plain-bars",
    ],
)
def test_save_checked_bars_rejects_an_invalid_frame(
    market_root: Path, checked: pd.DataFrame
) -> None:
    """An invalid frame raises and nothing is written."""
    repository = MarketDataRepository(market_root)

    with pytest.raises(ValueError):
        repository.save_checked_bars("SPY", checked)

    assert not (market_root / "clean" / "checked_bars" / "SPY.parquet").exists()


def test_load_checked_bars_of_an_unknown_instrument_has_the_canonical_columns(
    market_root: Path,
) -> None:
    """No file is zero rows with the checked bars columns."""
    empty = MarketDataRepository(market_root).load_checked_bars("QQQ")

    assert empty.empty
    assert list(empty.columns) == CHECKED_BARS_SCHEMA.names


def test_load_checked_bars_bounds_are_inclusive(market_root: Path) -> None:
    """``start`` and ``end`` are both included, and the index restarts at zero."""
    repository = MarketDataRepository(market_root)
    repository.save_checked_bars("SPY", make_checked_bars())

    loaded = repository.load_checked_bars("SPY", SESSIONS[1], SESSIONS[2])

    assert loaded["session_date"].tolist() == SESSIONS[1:3]
    assert loaded.index.tolist() == [0, 1]


# --- 3.8 / 3.9 MarketDataRepository.save_levels and load_levels ---------------

LEVEL_DATES = [date(2026, 1, 2), date(2026, 1, 5)]
"""Observation dates of ``make_levels``: a Friday and the following Monday."""


def test_levels_round_trip(market_root):
    """Saved levels load back unchanged from ``clean/levels/<id>.parquet``."""
    repository = MarketDataRepository(market_root)
    levels = make_levels()

    repository.save_levels("US10Y", levels)

    assert (market_root / "clean" / "levels" / "US10Y.parquet").exists()
    pd.testing.assert_frame_equal(repository.load_levels("US10Y"), levels)


def test_negative_levels_are_stored(market_root):
    """A rate can be negative: the Bund was, from 2019 to 2022."""
    repository = MarketDataRepository(market_root)

    repository.save_levels("US10Y", make_levels(value=[-0.25, -0.5]))

    assert repository.load_levels("US10Y")["value"].tolist() == [-0.25, -0.5]


def test_save_levels_replaces_the_previous_series(market_root):
    """One file per instrument, replaced whole."""
    repository = MarketDataRepository(market_root)
    repository.save_levels("US10Y", make_levels())

    repository.save_levels("US10Y", make_levels(value=[5.0, 6.0]))

    assert repository.load_levels("US10Y")["value"].tolist() == [5.0, 6.0]


@pytest.mark.parametrize(
    "levels",
    [
        make_levels(instrument_id=["US10Y", "DE10Y"]),
        make_levels(observation_date=list(reversed(LEVEL_DATES))),
        make_levels(observation_date=[LEVEL_DATES[0], LEVEL_DATES[0]]),
        make_levels().drop(columns="available_at_utc"),
        make_levels().drop(columns="observation_date"),
    ],
    ids=[
        "other-instrument",
        "unsorted",
        "duplicate-date",
        "missing-availability",
        "missing-observation-date",
    ],
)
def test_save_levels_rejects_an_invalid_frame(market_root, levels):
    """An invalid frame raises and nothing is written."""
    repository = MarketDataRepository(market_root)

    with pytest.raises(ValueError):
        repository.save_levels("US10Y", levels)

    assert not (market_root / "clean" / "levels" / "US10Y.parquet").exists()


def test_load_levels_of_an_unknown_instrument_has_the_canonical_columns(market_root):
    """No file is zero rows with the same columns and dtypes as a real file."""
    repository = MarketDataRepository(market_root)
    repository.save_levels("US10Y", make_levels())

    empty = repository.load_levels("DE10Y")

    assert empty.empty
    assert list(empty.columns) == LEVELS_SCHEMA.names
    pd.testing.assert_series_equal(empty.dtypes, repository.load_levels("US10Y").dtypes)


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (LEVEL_DATES[0], LEVEL_DATES[1], LEVEL_DATES),
        (LEVEL_DATES[1], None, LEVEL_DATES[1:]),
        (None, LEVEL_DATES[0], LEVEL_DATES[:1]),
        (date(2026, 1, 3), date(2026, 1, 4), []),
    ],
    ids=["both-bounds", "start-only", "end-only", "weekend-no-observation"],
)
def test_load_levels_bounds_are_inclusive(market_root, start, end, expected):
    """``start`` and ``end`` are both included, and the index restarts at zero."""
    repository = MarketDataRepository(market_root)
    repository.save_levels("US10Y", make_levels())

    loaded = repository.load_levels("US10Y", start, end)

    assert loaded["observation_date"].tolist() == expected
    assert loaded.index.tolist() == list(range(len(expected)))


# --- 3.10 / 3.11 corporate actions --------------------------------------------


def make_actions() -> pd.DataFrame:
    """Build a 4:1 split on SPY and a dividend on QQQ, available at the ex-date close."""
    return pd.DataFrame(
        {
            "instrument_id": ["SPY", "QQQ"],
            "action_type": ["SPLIT", "DIVIDEND"],
            "ex_date": [date(2026, 9, 10), date(2026, 9, 11)],
            "value": [4.0, 0.55],
            "available_at_utc": pd.DatetimeIndex(
                [datetime(2026, 9, 10, 20, 0, tzinfo=UTC), datetime(2026, 9, 11, 20, 0, tzinfo=UTC)]
            ).as_unit("us"),
            "source": ["YAHOO", "YAHOO"],
            "source_fetch_id": [FETCH_ID, FETCH_ID],
        }
    )


def test_corporate_actions_round_trip(market_root):
    """The single table, all instruments, loads back unchanged."""
    repository = MarketDataRepository(market_root)

    repository.save_corporate_actions(make_actions())

    assert (market_root / "clean" / "corporate_actions.parquet").exists()
    pd.testing.assert_frame_equal(repository.load_corporate_actions(), make_actions())


def test_load_corporate_actions_of_one_instrument(market_root):
    """Filtering keeps that instrument's rows only, index restarting at zero."""
    repository = MarketDataRepository(market_root)
    repository.save_corporate_actions(make_actions())

    qqq = repository.load_corporate_actions("QQQ")

    assert qqq["action_type"].tolist() == ["DIVIDEND"]
    assert qqq.index.tolist() == [0]


def test_save_corporate_actions_replaces_the_table(market_root):
    """The table is rewritten whole, not appended to."""
    repository = MarketDataRepository(market_root)
    repository.save_corporate_actions(make_actions())

    repository.save_corporate_actions(make_actions().iloc[:1])

    assert repository.load_corporate_actions()["instrument_id"].tolist() == ["SPY"]


def test_save_corporate_actions_rejects_an_invalid_frame(market_root):
    """A frame without its availability instant is refused.

    Without it the reader could apply a split before the market knew of it.
    """
    with pytest.raises(ValueError):
        MarketDataRepository(market_root).save_corporate_actions(
            make_actions().drop(columns="available_at_utc")
        )

    assert not (market_root / "clean" / "corporate_actions.parquet").exists()


def test_load_corporate_actions_without_a_file_has_the_canonical_columns(market_root):
    """No table yet is zero rows with the canonical columns, filtered or not."""
    repository = MarketDataRepository(market_root)

    for loaded in (repository.load_corporate_actions(), repository.load_corporate_actions("SPY")):
        assert loaded.empty
        assert list(loaded.columns) == CORPORATE_ACTIONS_SCHEMA.names


# --- 3.12 / 3.13 revisions log ------------------------------------------------


def make_revision(
    instrument_id: str = "SPY",
    observation_date: date = SESSIONS[0],
    old_value: float | None = 100.0,
    source: str = "YAHOO",
) -> pd.DataFrame:
    """Build one detected revision: a stored close changed by a later fetch."""
    return pd.DataFrame(
        {
            "instrument_id": [instrument_id],
            "source": [source],
            "table": ["bars"],
            "observation_date": [observation_date],
            "field": ["close"],
            "old_value": pd.Series([old_value], dtype="float64"),
            "new_value": [100.01],
            "old_fetch_id": [FETCH_ID],
            "new_fetch_id": ["20260913T210311Z"],
            "detected_at_utc": pd.DatetimeIndex([RETRIEVED_AT + timedelta(days=1)]).as_unit("us"),
        }
    )


def test_append_revisions_keeps_every_earlier_row(market_root):
    """It is a journal: a second append adds rows after the first, never replaces them."""
    repository = MarketDataRepository(market_root)

    repository.append_revisions(make_revision(observation_date=SESSIONS[0]))
    repository.append_revisions(make_revision(observation_date=SESSIONS[1]))

    log = repository.load_revisions()
    assert log["observation_date"].tolist() == SESSIONS[:2]
    assert log.index.tolist() == [0, 1]


def test_append_revisions_round_trips_a_missing_old_value(market_root):
    """``old_value`` is nullable, and a null survives a later append."""
    repository = MarketDataRepository(market_root)

    repository.append_revisions(make_revision(old_value=None))
    repository.append_revisions(make_revision(observation_date=SESSIONS[1]))

    assert repository.load_revisions()["old_value"].isna().tolist() == [True, False]


def test_append_revisions_with_no_rows_writes_nothing(market_root):
    """An empty detection is not a reason to create the log."""
    MarketDataRepository(market_root).append_revisions(make_revision().iloc[0:0])

    assert not (market_root / "clean" / "revisions.parquet").exists()


def test_append_revisions_rejects_an_invalid_frame_even_when_empty(market_root):
    """A wrong frame is a caller bug, whether or not it happens to hold rows."""
    repository = MarketDataRepository(market_root)
    repository.append_revisions(make_revision())
    before = (market_root / "clean" / "revisions.parquet").read_bytes()

    for invalid in (
        make_revision().drop(columns="field"),
        make_revision().iloc[0:0].drop(columns="field"),
    ):
        with pytest.raises(ValueError):
            repository.append_revisions(invalid)

    assert (market_root / "clean" / "revisions.parquet").read_bytes() == before


def test_load_revisions_of_one_instrument(market_root):
    """Filtering keeps that instrument's rows only, index restarting at zero."""
    repository = MarketDataRepository(market_root)
    repository.append_revisions(make_revision(instrument_id="SPY"))
    repository.append_revisions(make_revision(instrument_id="QQQ"))

    qqq = repository.load_revisions("QQQ")

    assert qqq["instrument_id"].tolist() == ["QQQ"]
    assert qqq.index.tolist() == [0]


def test_load_revisions_without_a_log_has_the_canonical_columns(market_root):
    """No log yet is zero rows with the canonical columns."""
    loaded = MarketDataRepository(market_root).load_revisions()

    assert loaded.empty
    assert list(loaded.columns) == REVISIONS_SCHEMA.names


# --- 3.14 MarketDataRepository.append_validation_log --------------------------

CHECKED_AT = datetime(2026, 9, 12, 21, 3, 11, tzinfo=UTC)
"""Instant the synthetic validation ran."""


def make_issue(code: str, severity: Severity, observation_date: date | None) -> ValidationIssue:
    """Build one validation issue on SPY."""
    return ValidationIssue(
        code=code,
        severity=severity,
        instrument_id="SPY",
        observation_date=observation_date,
        message=f"{code} on SPY",
        context={"close": 100.0},
    )


def read_validation_log(market_root: Path) -> pd.DataFrame:
    """Read the persisted log straight from disk."""
    return pq.read_table(market_root / "validation" / "validation_log.parquet").to_pandas()


def test_validation_log_keeps_warnings_and_errors(market_root):
    """One row per issue, across reports; a warning is logged like an error."""
    reports = [
        ValidationReport(
            "SPY",
            [
                make_issue("SESSION_GAP", Severity.WARNING, SESSIONS[1]),
                make_issue("OHLC_ORDER", Severity.ERROR, SESSIONS[2]),
            ],
        ),
        ValidationReport("QQQ", []),
        ValidationReport("SPY", [make_issue("STALE_OPEN", Severity.WARNING, None)]),
    ]

    MarketDataRepository(market_root).append_validation_log(reports, CHECKED_AT)

    log = read_validation_log(market_root)
    assert list(log.columns) == VALIDATION_LOG_SCHEMA.names
    assert log["code"].tolist() == ["SESSION_GAP", "OHLC_ORDER", "STALE_OPEN"]
    assert log["severity"].tolist() == ["WARNING", "ERROR", "WARNING"]
    assert log["observation_date"].tolist()[:2] == [SESSIONS[1], SESSIONS[2]]
    assert log["observation_date"].isna().tolist() == [False, False, True]
    assert (log["checked_at_utc"] == pd.Timestamp(CHECKED_AT)).all()


def test_validation_log_is_appended_to(market_root):
    """A second validation run adds to the log instead of replacing it."""
    repository = MarketDataRepository(market_root)
    first = ValidationReport("SPY", [make_issue("SESSION_GAP", Severity.WARNING, SESSIONS[1])])
    second = ValidationReport("SPY", [make_issue("OHLC_ORDER", Severity.ERROR, SESSIONS[2])])

    repository.append_validation_log([first], CHECKED_AT)
    repository.append_validation_log([second], CHECKED_AT + timedelta(days=1))

    log = read_validation_log(market_root)
    assert log["code"].tolist() == ["SESSION_GAP", "OHLC_ORDER"]
    assert log["checked_at_utc"].tolist() == [
        pd.Timestamp(CHECKED_AT),
        pd.Timestamp(CHECKED_AT + timedelta(days=1)),
    ]


def test_validation_log_with_no_issue_writes_nothing(market_root):
    """Clean reports leave no trace: the log records problems, not runs."""
    MarketDataRepository(market_root).append_validation_log(
        [ValidationReport("SPY", [])], CHECKED_AT
    )

    assert not (market_root / "validation" / "validation_log.parquet").exists()


@pytest.mark.parametrize(
    "checked_at_utc",
    [
        datetime(2026, 9, 12, 21, 3, 11),
        datetime(2026, 9, 12, 23, 3, 11, tzinfo=timezone(timedelta(hours=2))),
    ],
    ids=["naive", "non-utc-offset"],
)
def test_validation_log_rejects_a_non_utc_instant(market_root, checked_at_utc):
    """The instant is passed in, never read from the clock, and must be UTC."""
    report = ValidationReport("SPY", [make_issue("SESSION_GAP", Severity.WARNING, SESSIONS[1])])

    with pytest.raises(ValueError, match="checked_at_utc"):
        MarketDataRepository(market_root).append_validation_log([report], checked_at_utc)

    assert not (market_root / "validation" / "validation_log.parquet").exists()


# --- 3.15 / 3.16 / 3.17 exists, first_date, last_date -------------------------


def test_instrument_without_clean_data(market_root):
    """No bars and no levels: it does not exist and has no dates."""
    repository = MarketDataRepository(market_root)
    repository.save_corporate_actions(make_actions())

    assert not repository.exists("SPY")
    assert repository.first_date("SPY") is None
    assert repository.last_date("SPY") is None


def test_bars_instrument_dates(market_root):
    """A BAR instrument exists and spans its first to last session."""
    repository = MarketDataRepository(market_root)
    repository.save_bars("SPY", make_bars())

    assert repository.exists("SPY")
    assert repository.first_date("SPY") == SESSIONS[0]
    assert repository.last_date("SPY") == SESSIONS[-1]
    assert not repository.exists("QQQ")


def test_levels_instrument_dates(market_root):
    """A LEVEL instrument exists and spans its first to last observation."""
    repository = MarketDataRepository(market_root)
    repository.save_levels("US10Y", make_levels())

    assert repository.exists("US10Y")
    assert repository.first_date("US10Y") == LEVEL_DATES[0]
    assert repository.last_date("US10Y") == LEVEL_DATES[-1]


def test_empty_series_exists_but_has_no_dates(market_root):
    """A file with zero rows exists, yet there is no date to resume from."""
    repository = MarketDataRepository(market_root)
    repository.save_bars("SPY", make_bars().iloc[0:0])

    assert repository.exists("SPY")
    assert repository.first_date("SPY") is None
    assert repository.last_date("SPY") is None


# ---------------------------------------------------------------------------
# One change to the clean layer, or none
# ---------------------------------------------------------------------------


def test_a_transaction_publishes_every_file_at_once(market_root):
    """Nothing is visible while the block runs, and everything is after it."""
    repository = MarketDataRepository(market_root)
    target = market_root / "clean" / "bars" / "SPY.parquet"

    with repository.transaction():
        repository.save_bars("SPY", make_bars())
        # The writer sees its own work; nothing outside the block does.
        assert len(repository.load_bars("SPY")) == len(SESSIONS)
        assert not target.exists()

    assert target.exists()
    assert len(repository.load_bars("SPY")) == len(SESSIONS)


def test_a_transaction_that_raises_leaves_the_store_untouched(market_root):
    """A half-written promotion is the failure the transaction exists for.

    A series and the verdicts computed from it are one statement. Writing the
    first and dying before the second leaves a store that looks complete and
    describes values that are not there.
    """
    repository = MarketDataRepository(market_root)

    with pytest.raises(RuntimeError, match="the provider went away"), repository.transaction():
        repository.save_bars("SPY", make_bars())
        raise RuntimeError("the provider went away")

    assert repository.load_bars("SPY").empty
    assert list((market_root / ".pending").iterdir()) == []


def test_writes_go_back_to_being_immediate_after_a_transaction(market_root):
    """The block is the exception, not a mode the repository stays in."""
    repository = MarketDataRepository(market_root)
    with repository.transaction():
        repository.save_bars("SPY", make_bars())

    repository.save_bars("OTHER", make_bars(instrument_id="OTHER"))

    assert (market_root / "clean" / "bars" / "OTHER.parquet").exists()


def test_an_interrupted_transaction_is_discarded_when_the_store_is_opened(market_root):
    """Staged files with no manifest had decided nothing, so they are dropped."""
    staged = market_root / ".pending" / "interrupted" / "clean" / "bars"
    staged.mkdir(parents=True)
    (staged / "SPY.parquet").write_bytes(b"not even parquet")

    reopened = MarketDataRepository(market_root)

    assert not (market_root / ".pending" / "interrupted").exists()
    assert reopened.load_bars("SPY").empty


def test_a_commit_interrupted_while_moving_files_is_finished_on_the_next_open(market_root):
    """The manifest is what says the decision was taken; the moves carry it out.

    Writing it is one filesystem operation, so a crash is either before it -
    nothing happened - or after it, and then the work is finished rather than
    thrown away.
    """
    repository = MarketDataRepository(market_root)
    repository.save_bars("SPY", make_bars())
    target = market_root / "clean" / "bars" / "SPY.parquet"
    staging = market_root / ".pending" / "halfway"
    staged = staging / "clean" / "bars" / "SPY.parquet"
    staged.parent.mkdir(parents=True)
    os.replace(target, staged)
    (staging / "COMMIT.json").write_text(
        json.dumps({"clean/bars/SPY.parquet": str(staged)}), encoding="utf-8"
    )

    reopened = MarketDataRepository(market_root)

    assert len(reopened.load_bars("SPY")) == len(SESSIONS)
    assert not staging.exists()


def test_a_transaction_cannot_be_opened_inside_another(market_root):
    """The inner commit would publish the outer one's work halfway through."""
    repository = MarketDataRepository(market_root)

    def open_another() -> None:
        with repository.transaction():
            pass

    with repository.transaction(), pytest.raises(RuntimeError, match="already open"):
        open_another()


def test_two_appends_to_one_log_in_a_transaction_do_not_undo_each_other(market_root):
    """A read-modify-write has to see what the same transaction just wrote."""
    repository = MarketDataRepository(market_root)

    with repository.transaction():
        repository.append_revisions(make_revision(observation_date=SESSIONS[0]))
        repository.append_revisions(make_revision(observation_date=SESSIONS[1]))

    assert len(repository.load_revisions()) == 2


def test_a_transaction_that_wrote_nothing_leaves_nothing_behind(market_root):
    """A fetch with nothing to promote is not a reason to keep a directory."""
    repository = MarketDataRepository(market_root)

    with repository.transaction():
        pass

    assert list((market_root / ".pending").iterdir()) == []


# --- a file decoded once per version -----------------------------------------------


def count_decodes(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Count every file actually decoded from disk, by patching the one reader of them."""
    import quant_backtester.data.repository as repository_module

    decoded: list[Path] = []
    original = repository_module._load_or_empty

    def counting(path: Path, schema: object) -> pd.DataFrame:
        decoded.append(path)
        return original(path, schema)  # type: ignore[arg-type]

    monkeypatch.setattr(repository_module, "_load_or_empty", counting)
    return decoded


def test_an_unchanged_file_is_decoded_once(
    market_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A backtest reads the same few files thousands of times; decoding them once is enough."""
    repository = MarketDataRepository(market_root)
    repository.save_checked_bars("SPY", make_checked_bars())
    decoded = count_decodes(monkeypatch)

    first = repository.load_checked_bars("SPY")
    second = repository.load_checked_bars("SPY")

    assert len(decoded) == 1
    pd.testing.assert_frame_equal(first, second)


def test_a_replaced_file_is_read_again(market_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every write is a new file renamed into place, so a new version is never served stale."""
    repository = MarketDataRepository(market_root)
    repository.save_checked_bars("SPY", make_checked_bars())
    decoded = count_decodes(monkeypatch)
    repository.load_checked_bars("SPY")

    repository.save_checked_bars("SPY", make_checked_bars(status="SINGLE_SOURCE"))
    reloaded = repository.load_checked_bars("SPY")

    assert len(decoded) == 2
    assert set(reloaded["check_status"]) == {"SINGLE_SOURCE"}


def test_a_file_written_by_another_repository_is_read_again(market_root: Path) -> None:
    """Two handles on one store: the version is the file's, not the handle's."""
    reading = MarketDataRepository(market_root)
    writing = MarketDataRepository(market_root)
    writing.save_checked_bars("SPY", make_checked_bars())
    assert set(reading.load_checked_bars("SPY")["check_status"]) == {"CONFIRMED"}

    writing.save_checked_bars("SPY", make_checked_bars(status="SINGLE_SOURCE"))

    assert set(reading.load_checked_bars("SPY")["check_status"]) == {"SINGLE_SOURCE"}


def test_editing_a_loaded_frame_does_not_edit_the_next_one(market_root: Path) -> None:
    """What a caller gets is its own copy: the kept frame is out of its reach."""
    repository = MarketDataRepository(market_root)
    repository.save_checked_bars("SPY", make_checked_bars())

    edited = repository.load_checked_bars("SPY")
    edited["close"] = -1.0
    edited.loc[0, "check_status"] = "CONFLICT"

    fresh = repository.load_checked_bars("SPY")
    pd.testing.assert_frame_equal(fresh, make_checked_bars())


def test_an_absent_file_is_still_an_empty_frame_with_its_columns(market_root: Path) -> None:
    """Nothing to decode, nothing kept, and the same answer as before the cache."""
    repository = MarketDataRepository(market_root)

    assert repository.load_checked_bars("NOPE").empty
    repository.save_checked_bars("NOPE", make_checked_bars(instrument_id="NOPE"))
    assert len(repository.load_checked_bars("NOPE")) == len(SESSIONS)


def test_a_transaction_reads_what_it_staged_and_then_what_it_committed(market_root: Path) -> None:
    """The staged copy is another file, and the committed one is a new version."""
    repository = MarketDataRepository(market_root)
    repository.save_checked_bars("SPY", make_checked_bars())
    repository.load_checked_bars("SPY")

    with repository.transaction():
        repository.save_checked_bars("SPY", make_checked_bars(status="SINGLE_SOURCE"))
        assert set(repository.load_checked_bars("SPY")["check_status"]) == {"SINGLE_SOURCE"}

    assert set(repository.load_checked_bars("SPY")["check_status"]) == {"SINGLE_SOURCE"}


def test_a_transaction_leaves_no_decoded_copy_of_its_staged_files(market_root: Path) -> None:
    """Staged files are gone once the transaction ends; their decoded copies go with them."""
    repository = MarketDataRepository(market_root)

    with repository.transaction():
        repository.save_checked_bars("SPY", make_checked_bars())
        repository.load_checked_bars("SPY")
        assert any(".pending" in str(path) for path in repository._decoded)

    assert not any(".pending" in str(path) for path in repository._decoded)
