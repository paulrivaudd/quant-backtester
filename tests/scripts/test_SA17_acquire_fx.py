"""The SA17 FX acquisition: resumable writes, the throttle, and a verification that fails."""

from __future__ import annotations

import hashlib
import json
import lzma
import struct
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from quant_backtester.data.sources.base import ProviderRateLimited
from quant_backtester.data.sources.dukascopy import DukascopyDownload, Side
from scripts import SA17_acquire_fx as fx

NOW = datetime(2026, 11, 7, 22, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fx, "PAUSE_SECONDS", 0.0)
    monkeypatch.setattr(fx, "RATE_LIMIT_WAIT_SECONDS", 0)


def download(payload: bytes = b"data") -> DukascopyDownload:
    return DukascopyDownload(
        pair="EURUSD",
        day=date(2024, 3, 1),
        side=Side.BID,
        url="https://example.org/x.bi5",
        payload=payload,
        sha256=hashlib.sha256(payload).hexdigest(),
        retrieved_at_utc=NOW,
    )


def test_a_file_is_recorded_then_moved_into_place_and_never_fetched_again(tmp_path: Path) -> None:
    path = tmp_path / "raw" / "a.bi5"
    calls: list[int] = []

    def fetch() -> DukascopyDownload:
        calls.append(1)
        return download()

    assert fx.store(tmp_path, path, fetch, "hours", fx.Throttle())
    assert path.read_bytes() == b"data"
    (entry,) = [json.loads(line) for line in (tmp_path / "manifest.jsonl").read_text().splitlines()]
    assert entry["file"] == "raw/a.bi5"
    assert entry["sha256"] == hashlib.sha256(b"data").hexdigest()
    assert not fx.store(tmp_path, path, fetch, "hours", fx.Throttle())
    assert calls == [1]


def test_an_interrupted_move_leaves_a_record_and_no_file_which_the_next_run_refetches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "raw" / "a.bi5"

    def interrupted(source: object, target: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(fx.os, "replace", interrupted)
    with pytest.raises(KeyboardInterrupt):
        fx.store(tmp_path, path, lambda: download(b"first"), "hours", fx.Throttle())
    assert not path.exists()
    monkeypatch.undo()
    monkeypatch.setattr(fx, "PAUSE_SECONDS", 0.0)
    assert fx.store(tmp_path, path, lambda: download(b"second"), "hours", fx.Throttle())
    # The latest record of a file is the one kept, and it matches the file.
    assert fx.read_manifest(tmp_path)["raw/a.bi5"] == hashlib.sha256(b"second").hexdigest()
    assert fx.checked(tmp_path, path, fx.read_manifest(tmp_path)) == b"second"


def test_an_unrecorded_file_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "raw" / "stray.bi5"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"x")
    with pytest.raises(ValueError, match="not in its manifest"):
        fx.checked(tmp_path, path, {})


def test_the_second_refusal_of_a_run_stops_it_even_on_another_file(tmp_path: Path) -> None:
    throttle = fx.Throttle()
    answers: list[object] = [ProviderRateLimited("429"), download()]

    def first() -> DukascopyDownload:
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        assert isinstance(answer, DukascopyDownload)
        return answer

    assert fx.store(tmp_path, tmp_path / "raw" / "one.bi5", first, "hours", throttle)
    assert throttle.refused

    def refused() -> DukascopyDownload:
        raise ProviderRateLimited("429")

    with pytest.raises(fx.RunStopped):
        fx.store(tmp_path, tmp_path / "raw" / "two.bi5", refused, "hours", throttle)
    assert not (tmp_path / "raw" / "two.bi5").exists()


# --- build ------------------------------------------------------------------------


def packed(records: list[tuple[int, int, int, int, int, float]]) -> bytes:
    return lzma.compress(b"".join(struct.pack(">IIIIIf", *record) for record in records))


def price(instant: datetime) -> int:
    """Return a distinct price, in points, for the bar ending at an instant."""
    return 108_000 + int(instant.timestamp() // 3600) % 1000


def write_archive(archive: Path, sessions: list, sample: list) -> None:
    """Write March 2024's hourly files and the sample's minute files, recorded."""
    origin = datetime(2024, 3, 1, tzinfo=UTC)
    records = []
    for hour in range(31 * 24):
        end = origin + timedelta(hours=hour + 1)
        close = price(end)
        records.append((hour * 3600, close, close, close, close, 10.0))
    manifest = []
    for side in Side:
        path = fx.hours_path(archive, 2024, 3, side)
        path.parent.mkdir(parents=True, exist_ok=True)
        spread = 0 if side is Side.BID else 2
        payload = packed(
            [
                (t, o + spread, c + spread, lo + spread, h + spread, v)
                for t, o, c, lo, h, v in records
            ]
        )
        path.write_bytes(payload)
        manifest.append(
            {"file": str(path.relative_to(archive)), "sha256": hashlib.sha256(payload).hexdigest()}
        )
    for session in sample:
        midnight = datetime.combine(session.session_date, datetime.min.time(), UTC)
        start = int((session.close_utc - timedelta(minutes=1) - midnight).total_seconds())
        for side in Side:
            spread = 0 if side is Side.BID else 2
            close = price(session.close_utc) + spread
            payload = packed([(start, close, close, close, close, 3.0)])
            path = fx.minutes_path(archive, session.session_date, side)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            manifest.append(
                {
                    "file": str(path.relative_to(archive)),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            )
    (archive / "manifest.jsonl").write_text("".join(json.dumps(entry) + "\n" for entry in manifest))


@pytest.fixture
def march(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(fx, "START", date(2024, 3, 1))
    monkeypatch.setattr(fx, "END", date(2024, 3, 29))
    monkeypatch.setattr(fx, "SAMPLE_SIZE", 3)
    sessions = fx.xnys().sessions(fx.START, fx.END)
    return sessions, fx.sample(sessions)


def test_build_reads_each_sessions_own_close_and_passes_a_true_verification(
    tmp_path: Path, march
) -> None:
    sessions, sample = march
    write_archive(tmp_path, sessions, sample)
    coverage = fx.build(tmp_path)
    assert coverage["rates"] == len(sessions)
    table = pd.read_parquet(tmp_path / "derived" / "eurusd_us_close.parquet")
    first = table.iloc[0]
    # 1 March 2024: 16:00 New York is 21:00 UTC (before the US switch to DST).
    assert first["instant_utc"] == pd.Timestamp("2024-03-01 21:00", tz="UTC")
    assert first["usd_per_eur"] == pytest.approx(
        (2 * price(first["instant_utc"]) + 2) / 2 / 100_000
    )
    assert all(day["agree"] for day in coverage["verification"]["days"])


def test_build_fails_when_the_sample_was_not_verified(tmp_path: Path, march) -> None:
    sessions, _ = march
    write_archive(tmp_path, sessions, [])  # no minute files: nothing compared
    with pytest.raises(ValueError, match="verification failed on 3 of 3"):
        fx.build(tmp_path)


def test_a_half_day_is_read_at_its_early_close(monkeypatch: pytest.MonkeyPatch) -> None:
    # 29 November 2024 closes at 13:00 New York, 18:00 UTC: not 16:00.
    monkeypatch.setattr(fx, "START", date(2024, 11, 29))
    monkeypatch.setattr(fx, "END", date(2024, 11, 29))
    (session,) = fx.xnys().sessions(fx.START, fx.END)
    assert session.close_utc == datetime(2024, 11, 29, 18, 0, tzinfo=UTC)
