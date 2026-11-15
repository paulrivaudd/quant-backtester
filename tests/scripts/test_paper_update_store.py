"""Tests of the paper store: seeded once, extended, its metadata adopted on purpose."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts.SA16_download_data import combined_registry, metadata_manifest

from quant_backtester.provenance import SourceState, SourceStatus
from scripts import paper_update_store

NOW = datetime(2026, 11, 16, 7, 30, tzinfo=UTC)
COMMIT = "0" * 40


@pytest.fixture(scope="module")
def reviewed() -> dict[str, bytes]:
    """Return the committed metadata folder with the store's registry, read from disk.

    Read file by file, not through git: these tests ask nothing of this
    checkout's state. What git tracks is tested on a repository of its own.
    """
    source = paper_update_store.REVIEWED
    files = {
        path.relative_to(source).as_posix(): path.read_bytes()
        for path in sorted(source.rglob("*"))
        if path.is_file()
    }
    files["instruments.toml"] = combined_registry().encode("utf-8")
    return files


def store_holding(root: Path, files: dict[str, bytes]) -> Path:
    """Return a store whose metadata is ``files``, with its manifest."""
    for name, content in files.items():
        path = root / "metadata" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    manifest = metadata_manifest(root / "metadata")
    (root / paper_update_store.MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n")
    return root


def records(store: Path) -> list[dict[str, object]]:
    path = store / paper_update_store.CHANGES
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_a_store_holding_the_committed_metadata_differs_in_nothing(
    reviewed: dict[str, bytes], tmp_path: Path
) -> None:
    store = store_holding(tmp_path / "store", reviewed)
    assert paper_update_store.metadata_differences(store, reviewed) == {}
    # The study's store was built from a Windows checkout: same text, CRLF endings.
    windows = {name: content.replace(b"\n", b"\r\n") for name, content in reviewed.items()}
    store = store_holding(tmp_path / "windows", windows)
    assert paper_update_store.metadata_differences(store, reviewed) == {}


def test_a_change_in_the_repository_is_reported_and_does_not_reach_the_store(
    reviewed: dict[str, bytes], tmp_path: Path
) -> None:
    """An instrument added for another study, a decision recorded, a file added or removed."""
    store = store_holding(tmp_path / "store", reviewed)
    before = metadata_manifest(store / "metadata")
    later = dict(reviewed)
    later["instruments.toml"] += b"\n# an instrument of another study\n"
    later["known_gaps.toml"] += b"\n# a gap reviewed since\n"
    later["new.toml"] = b"x = 1\n"
    del later["universes.toml"]

    differing = paper_update_store.metadata_differences(store, later)

    assert list(differing) == ["instruments.toml", "known_gaps.toml", "new.toml", "universes.toml"]
    assert differing["new.toml"]["from"] is None and differing["universes.toml"]["to"] is None
    assert metadata_manifest(store / "metadata") == before
    assert records(store) == []


def test_metadata_edited_in_place_is_refused(reviewed: dict[str, bytes], tmp_path: Path) -> None:
    store = store_holding(tmp_path / "store", reviewed)
    with (store / "metadata" / "known_gaps.toml").open("ab") as stream:
        stream.write(b"\n# written straight into the store\n")
    with pytest.raises(ValueError, match="never edited in place"):
        paper_update_store.metadata_differences(store, reviewed)
    (store / paper_update_store.MANIFEST).unlink()
    with pytest.raises(ValueError, match="not the one it recorded"):
        paper_update_store.metadata_differences(store, reviewed)


def test_an_adoption_replaces_the_metadata_and_records_what_why_and_from_which_commit(
    reviewed: dict[str, bytes], tmp_path: Path
) -> None:
    store = store_holding(tmp_path / "store", reviewed)
    later = dict(reviewed)
    later["known_gaps.toml"] += b"\n# a gap reviewed since\n"
    del later["universes.toml"]

    changed = paper_update_store.adopt_metadata(store, later, " a reviewed gap ", COMMIT, NOW)

    assert list(changed) == ["known_gaps.toml", "universes.toml"]
    assert (store / "metadata" / "known_gaps.toml").read_bytes() == later["known_gaps.toml"]
    assert not (store / "metadata" / "universes.toml").exists()
    assert not (store / "metadata.partial").exists()
    assert paper_update_store.metadata_differences(store, later) == {}
    assert records(store) == [
        {
            "adopted_at": NOW.isoformat(),
            "reason": "a reviewed gap",
            "git_commit": COMMIT,
            "files": changed,
        }
    ]
    # Adopting what is already held writes nothing.
    assert paper_update_store.adopt_metadata(store, later, "again", COMMIT, NOW) == {}
    assert len(records(store)) == 1


def test_an_adoption_without_a_reason_or_of_metadata_that_does_not_load_leaves_the_store(
    reviewed: dict[str, bytes], tmp_path: Path
) -> None:
    store = store_holding(tmp_path / "store", reviewed)
    before = metadata_manifest(store / "metadata")
    later = dict(reviewed)
    later["known_gaps.toml"] += b"\n# a gap reviewed since\n"
    with pytest.raises(ValueError, match="needs a reason"):
        paper_update_store.adopt_metadata(store, later, "  ", COMMIT, NOW)
    with pytest.raises(ValueError, match="timezone-aware"):
        paper_update_store.adopt_metadata(store, later, "why", COMMIT, datetime(2026, 11, 16))
    broken = dict(reviewed)
    broken["instruments.toml"] = b"this is not a registry ["
    with pytest.raises(ValueError, match="does not load"):
        paper_update_store.adopt_metadata(store, broken, "why", COMMIT, NOW)
    assert metadata_manifest(store / "metadata") == before
    assert records(store) == [] and not (store / "metadata.partial").exists()
    assert paper_update_store.metadata_differences(store, reviewed) == {}


def test_an_interrupted_adoption_is_refused_until_it_is_run_again(
    reviewed: dict[str, bytes], tmp_path: Path
) -> None:
    """The folder was swapped and the manifest was not written."""
    store = store_holding(tmp_path / "store", reviewed)
    later = dict(reviewed)
    later["known_gaps.toml"] += b"\n# a gap reviewed since\n"
    (store / "metadata" / "known_gaps.toml").write_bytes(later["known_gaps.toml"])
    with pytest.raises(ValueError, match="interrupted adoption"):
        paper_update_store.metadata_differences(store, later)
    assert paper_update_store.adopt_metadata(store, later, "again", COMMIT, NOW) == {}
    assert paper_update_store.metadata_differences(store, later) == {}


def test_an_adoption_interrupted_between_the_two_folders_starts_again_from_the_old_one(
    reviewed: dict[str, bytes], tmp_path: Path
) -> None:
    """The old folder was set aside and the new one never took its place."""
    store = store_holding(tmp_path / "store", reviewed)
    later = dict(reviewed)
    later["known_gaps.toml"] += b"\n# a gap reviewed since\n"
    (store / "metadata").rename(store / "metadata.previous")
    with pytest.raises(ValueError, match="not the one it recorded"):
        paper_update_store.require_recorded_metadata(store)

    changed = paper_update_store.adopt_metadata(store, later, "again", COMMIT, NOW)

    # The record says what changed from what the store held, not that every file is new.
    assert list(changed) == ["known_gaps.toml"] and changed["known_gaps.toml"]["from"] is not None
    assert [record["files"] for record in records(store)] == [changed]
    assert not (store / "metadata.previous").exists()
    paper_update_store.require_recorded_metadata(store)


def test_the_reviewed_metadata_is_what_git_tracks_with_the_stores_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On a repository of its own: a file git ignores or does not track is not metadata."""
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    source = tmp_path / "repository" / "metadata"
    (source / "calendars").mkdir(parents=True)
    (source / "known_gaps.toml").write_text("x = 1\n")
    (source / "instruments.toml").write_text("the project's registry alone\n")
    (source / "calendars" / "XPAR.toml").write_text("y = 2\n")
    (source.parent / ".gitignore").write_text("*.bak\n")
    for arguments in (["init", "-q"], ["add", "-A"]):
        subprocess.run(["git", "-C", str(source.parent), *arguments], check=True)
    (source / "known_gaps.toml.bak").write_text("an editor's backup\n")
    (source / "untracked.toml").write_text("not committed\n")

    files = paper_update_store.reviewed_metadata(source, "registry")

    assert files == {
        "calendars/XPAR.toml": b"y = 2\n",
        "known_gaps.toml": b"x = 1\n",
        "instruments.toml": b"registry",
    }
    # Git does not look above the ceiling from a folder below it.
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(subprocess.CalledProcessError):
        paper_update_store.reviewed_metadata(outside, "registry")


def store_like(root: Path) -> Path:
    for name in ("metadata", "raw", "clean", "validation", "reports"):
        (root / name).mkdir(parents=True)
        (root / name / "file.txt").write_text(name)
    (root / "metadata_sha256.json").write_text("{}\n")
    (root / ".lock").write_text("")
    return root


def test_the_paper_store_is_seeded_once_from_the_studys(tmp_path: Path) -> None:
    seed, store = store_like(tmp_path / "seed"), tmp_path / "paper"
    assert paper_update_store.seed_store(store, seed) is True
    assert sorted(path.name for path in store.iterdir()) == sorted(paper_update_store.SEEDED)
    assert (store / "clean" / "file.txt").read_text() == "clean"
    # The seed is read, never written, and a store that exists is left alone.
    (store / "clean" / "file.txt").write_text("extended")
    assert paper_update_store.seed_store(store, seed) is False
    assert (store / "clean" / "file.txt").read_text() == "extended"
    assert (seed / "clean" / "file.txt").read_text() == "clean"


def test_a_seed_that_is_not_a_built_store_is_refused(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="SA16_download_data"):
        paper_update_store.seed_store(tmp_path / "paper", tmp_path / "missing")
    assert not (tmp_path / "paper").exists()


def test_every_instrument_is_extended_and_a_failure_is_recorded_not_swallowed() -> None:
    class Updater:
        def update(self, instrument_id: str) -> SimpleNamespace:
            if instrument_id == "DOWN":
                raise RuntimeError("provider is down")
            return SimpleNamespace(
                valid=instrument_id != "REFUSED", errors=[], warnings=[], issues=[]
            )

    outcomes = paper_update_store.update_store(Updater(), ("FINE", "DOWN", "REFUSED"))  # type: ignore[arg-type]

    assert [outcome["instrument_id"] for outcome in outcomes] == ["FINE", "DOWN", "REFUSED"]
    assert outcomes[0]["valid"] is True and "provider is down" in outcomes[1]["exception"]
    assert paper_update_store.failed(outcomes) is True
    assert paper_update_store.failed(outcomes[:1]) is False
    assert paper_update_store.failed(outcomes[2:]) is True


def test_a_copy_left_by_an_interrupted_seed_is_replaced(tmp_path: Path) -> None:
    seed, store = store_like(tmp_path / "seed"), tmp_path / "paper"
    partial = tmp_path / "paper.partial"
    (partial / "clean").mkdir(parents=True)
    (partial / "clean" / "stale.txt").write_text("from a copy that never finished")
    assert paper_update_store.seed_store(store, seed) is True
    assert not partial.exists()
    assert not (store / "clean" / "stale.txt").exists()
    # The store's reports and its lock are its own: the seed's are not copied.
    assert not (store / "reports").exists() and not (store / ".lock").exists()


class RecordingUpdater:
    """An updater that fetches nothing and refuses the instruments it is told to."""

    def __init__(self, refused: tuple[str, ...] = ()) -> None:
        self.refused = refused
        self.asked: list[str] = []

    def update(self, instrument_id: str) -> SimpleNamespace:
        """Record the instrument asked for, and return a report of its extension."""
        self.asked.append(instrument_id)
        return SimpleNamespace(
            valid=instrument_id not in self.refused, errors=[], warnings=[], issues=[]
        )


@pytest.fixture
def paper_run(
    reviewed: dict[str, bytes], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, RecordingUpdater]:
    """Return a store holding the committed metadata, and the updater the script is handed."""
    store = store_holding(tmp_path / "store", reviewed)
    updater = RecordingUpdater()
    monkeypatch.setattr(paper_update_store, "build_updater", lambda *_args, **_kwargs: updater)
    # The script compares the store with what the fixture read, not with a second reading.
    monkeypatch.setattr(paper_update_store, "reviewed_metadata", lambda *_args: reviewed)
    return store, updater


def test_the_script_extends_every_series_and_writes_what_it_did(
    paper_run: tuple[Path, RecordingUpdater], capsys: pytest.CaptureFixture[str]
) -> None:
    store, updater = paper_run
    assert paper_update_store.main(["--store", str(store)]) == 0
    assert tuple(updater.asked) == paper_update_store.INSTRUMENT_IDS
    (evidence,) = (store / "reports").glob("paper_update_*.json")
    outcomes = json.loads(evidence.read_text())["outcomes"]
    assert [outcome["instrument_id"] for outcome in outcomes] == updater.asked
    assert "note:" not in capsys.readouterr().out


def test_the_script_exits_non_zero_when_a_series_is_refused(
    paper_run: tuple[Path, RecordingUpdater],
) -> None:
    store, updater = paper_run
    updater.refused = ("VIX",)
    assert paper_update_store.main(["--store", str(store), "--only", "VIX", "US10Y"]) == 1
    assert updater.asked == ["VIX", "US10Y"]


def test_the_script_reports_a_repository_that_moved_on_and_updates_all_the_same(
    paper_run: tuple[Path, RecordingUpdater],
    reviewed: dict[str, bytes],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store, updater = paper_run
    later = {**reviewed, "known_gaps.toml": reviewed["known_gaps.toml"] + b"\n# since\n"}
    monkeypatch.setattr(paper_update_store, "reviewed_metadata", lambda *_args: later)
    before = metadata_manifest(store / "metadata")

    assert paper_update_store.main(["--store", str(store), "--only", "VIX"]) == 0

    assert "note: the repository's metadata differs from the store's (known_gaps.toml)" in (
        capsys.readouterr().out
    )
    assert metadata_manifest(store / "metadata") == before and updater.asked == ["VIX"]


def test_the_script_adopts_from_a_clean_checkout_only(
    paper_run: tuple[Path, RecordingUpdater],
    reviewed: dict[str, bytes],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, updater = paper_run
    later = {**reviewed, "known_gaps.toml": reviewed["known_gaps.toml"] + b"\n# since\n"}
    monkeypatch.setattr(paper_update_store, "reviewed_metadata", lambda *_args: later)
    arguments = ["--store", str(store), "--only", "VIX", "--adopt-metadata", "a reviewed gap"]

    dirty = SourceState(SourceStatus.DIRTY, COMMIT)
    monkeypatch.setattr(paper_update_store, "git_source_state", lambda _root: dirty)
    with pytest.raises(SystemExit, match="adopted from a commit; this tree is DIRTY"):
        paper_update_store.main(arguments)
    assert records(store) == [] and updater.asked == []

    clean = SourceState(SourceStatus.CLEAN, COMMIT)
    monkeypatch.setattr(paper_update_store, "git_source_state", lambda _root: clean)
    assert paper_update_store.main(arguments) == 0
    (record,) = records(store)
    assert record["reason"] == "a reviewed gap" and record["git_commit"] == COMMIT
    assert (store / "metadata" / "known_gaps.toml").read_bytes() == later["known_gaps.toml"]
    assert updater.asked == ["VIX"]


def test_the_script_refuses_metadata_edited_in_place_before_fetching_anything(
    paper_run: tuple[Path, RecordingUpdater],
) -> None:
    store, updater = paper_run
    (store / "metadata" / "known_gaps.toml").write_text("x = 1\n")
    with pytest.raises(ValueError, match="never edited in place"):
        paper_update_store.main(["--store", str(store)])
    assert updater.asked == [] and not (store / "reports").exists()
