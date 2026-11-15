"""Tests of the paper store's metadata: kept as seeded, adopted on purpose, never edited."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from scripts.SA16_download_data import combined_registry, metadata_manifest

from scripts import paper_update_store

NOW = datetime(2026, 11, 16, 7, 30, tzinfo=UTC)
COMMIT = "0" * 40


@pytest.fixture(scope="module")
def reviewed() -> dict[str, bytes]:
    """Return the repository's committed metadata, as the script reads it."""
    return paper_update_store.reviewed_metadata(paper_update_store.REVIEWED, combined_registry())


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


def test_the_reviewed_metadata_is_the_committed_folder_with_the_stores_registry(
    reviewed: dict[str, bytes],
) -> None:
    assert reviewed["instruments.toml"].decode() == combined_registry()
    assert {"known_gaps.toml", "calendars/XPAR.toml", "crosscheck.toml"} <= set(reviewed)
    folder = paper_update_store.REVIEWED / "known_gaps.toml"
    assert reviewed["known_gaps.toml"] == folder.read_bytes()


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
