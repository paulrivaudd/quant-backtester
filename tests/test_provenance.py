"""Which code produced a result: a commit when there is one, and nothing guessed when there is not.

The git tests run against a repository created in a temporary directory, so
they read nothing of this checkout and touch no network.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from quant_backtester.provenance import (
    SourceState,
    SourceStatus,
    changed_paths,
    git_source_state,
)

COMMIT = "0123456789abcdef0123456789abcdef01234567"


def git(repository: Path, *arguments: str) -> None:
    """Run a git command in ``repository``, with an identity of its own."""
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "init.defaultBranch=main",
            "-C",
            str(repository),
            *arguments,
        ],
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    """Return a repository holding one committed file."""
    git(tmp_path, "init")
    (tmp_path / "strategy.py").write_text("LOOKBACK = 60\n")
    git(tmp_path, "add", "strategy.py")
    git(tmp_path, "commit", "-m", "a strategy")
    return tmp_path


def test_a_clean_checkout_names_its_commit(repository: Path) -> None:
    """The commit, and a tree identical to it: reproducible from the commit alone."""
    state = git_source_state(repository)

    assert state.status is SourceStatus.CLEAN
    assert state.git_commit is not None
    assert len(state.git_commit) == 40
    assert state.dirty is False


def test_an_edited_file_makes_the_tree_dirty(repository: Path) -> None:
    """A result produced on uncommitted edits is not the commit's result."""
    (repository / "strategy.py").write_text("LOOKBACK = 20\n")

    state = git_source_state(repository)

    assert state.status is SourceStatus.DIRTY
    assert state.dirty is True
    assert state.git_commit is not None


def test_an_untracked_module_makes_the_tree_dirty_too(repository: Path) -> None:
    """A strategy written in a new file produced the result as surely as an edited one."""
    (repository / "new_strategy.py").write_text("LOOKBACK = 5\n")

    assert git_source_state(repository).status is SourceStatus.DIRTY


def test_an_ignored_file_does_not(repository: Path) -> None:
    """The market data store is ignored by the repository, and changes no code."""
    (repository / ".gitignore").write_text("market_data/\n")
    git(repository, "add", ".gitignore")
    git(repository, "commit", "-m", "ignore the store")
    (repository / "market_data").mkdir()
    (repository / "market_data" / "bars.parquet").write_text("not code")

    assert git_source_state(repository).status is SourceStatus.CLEAN


def test_a_directory_outside_any_checkout_is_unversioned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No commit to cite, and none is invented.

    Git is stopped from looking above the temporary directory, so the answer
    does not depend on where the test suite happens to run.
    """
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    outside = tmp_path / "notebooks"
    outside.mkdir()

    state = git_source_state(outside)

    assert state.status is SourceStatus.UNVERSIONED
    assert state.git_commit is None
    assert state.dirty is None


def test_a_machine_without_git_is_unversioned(
    repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing executable is an unknown state, not a clean one."""

    def no_git(*arguments: object, **options: object) -> object:
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", no_git)

    assert git_source_state(repository) == SourceState(SourceStatus.UNVERSIONED)


def test_a_state_nobody_recorded_says_so() -> None:
    """``UNRECORDED`` rather than a guess, and it is what a run carries by default."""
    state = SourceState.unrecorded()

    assert state.definition() == {
        "git_commit": None,
        "dirty": None,
        "source_state": "UNRECORDED",
    }


def test_a_recorded_state_describes_itself_for_the_record() -> None:
    """The three fields a result carries: commit, dirty, and what is known."""
    assert SourceState(SourceStatus.DIRTY, COMMIT).definition() == {
        "git_commit": COMMIT,
        "dirty": True,
        "source_state": "DIRTY",
    }


@pytest.mark.parametrize("commit", [None, "9b15c93", "not a commit at all, forty characters!!"])
def test_a_versioned_state_names_a_full_commit(commit: str | None) -> None:
    """An abbreviated commit is ambiguous in a large repository; none at all is no provenance."""
    with pytest.raises(ValueError, match="names its full commit"):
        SourceState(SourceStatus.CLEAN, commit)


def test_an_unversioned_state_names_no_commit() -> None:
    """A commit is known or it is not."""
    with pytest.raises(ValueError, match="has no commit"):
        SourceState(SourceStatus.UNVERSIONED, COMMIT)


def test_a_status_must_be_one_of_the_statuses() -> None:
    """A free-text status cannot be compared across runs."""
    with pytest.raises(ValueError, match="SourceStatus"):
        SourceState("clean")  # type: ignore[arg-type]


def test_the_changed_paths_are_what_differs_from_the_commit_and_nothing_else(
    repository: Path,
) -> None:
    """Edited, deleted, staged, renamed and untracked; not ignored, not unchanged."""
    (repository / ".gitignore").write_text("cache/\n")
    (repository / "kept.py").write_text("x = 1\n")
    (repository / "removed.py").write_text("x = 2\n")
    (repository / "moved.py").write_text("a long enough file to be seen as renamed\n" * 5)
    git(repository, "add", "-A")
    git(repository, "commit", "-m", "more files")
    assert changed_paths(repository) == frozenset()

    (repository / "strategy.py").write_text("LOOKBACK = 20\n")
    (repository / "removed.py").unlink()
    (repository / "staged.py").write_text("y = 1\n")
    git(repository, "add", "staged.py")
    git(repository, "mv", "moved.py", "arrived.py")
    (repository / "deeper").mkdir()
    (repository / "deeper" / "untracked.py").write_text("z = 1\n")
    (repository / "cache").mkdir()
    (repository / "cache" / "ignored.bin").write_text("ignored\n")

    names = ("strategy.py", "removed.py", "staged.py", "moved.py", "arrived.py")
    expected = {repository.resolve() / name for name in names}
    expected.add(repository.resolve() / "deeper" / "untracked.py")
    assert changed_paths(repository) == expected
    # The whole checkout is read, whichever folder of it is given.
    assert changed_paths(repository / "deeper") == expected


def test_a_changed_link_is_named_itself_not_what_it_points_to(repository: Path) -> None:
    (repository / "output").mkdir()
    (repository / "output" / "generated.txt").write_text("generated\n")
    (repository / "helper.py").symlink_to("output/generated.txt")
    changed = changed_paths(repository)
    assert repository.resolve() / "helper.py" in changed
    assert all(path.name != "generated.txt" or path.parent.name == "output" for path in changed)


def test_a_change_staged_then_undone_is_dirty_with_no_changed_path(repository: Path) -> None:
    """Git's status and its diff against the commit disagree: nothing differs, and it is dirty."""
    (repository / "strategy.py").write_text("LOOKBACK = 20\n")
    git(repository, "add", "strategy.py")
    (repository / "strategy.py").write_text("LOOKBACK = 60\n")
    assert git_source_state(repository).status is SourceStatus.DIRTY
    assert changed_paths(repository) == frozenset()


def test_the_changed_paths_of_a_folder_that_is_not_a_checkout_are_refused(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path_factory.mktemp("no-repository")
    # Wherever the temporary folder lives, git does not look above it.
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(folder.parent))
    with pytest.raises(subprocess.CalledProcessError):
        changed_paths(folder)
