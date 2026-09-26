"""Which code produced a result, stated by whoever ran it.

A strategy's fingerprint hashes its *configuration*, never the source that
read it, so two runs of an edited ``decide`` share one. What tells them apart
is the state of the code: the commit, and whether the working tree had changes
nobody committed. A result without it cannot be traced back to what produced
it, and one that claims a commit while running on uncommitted edits is worse
than one that says nothing.

The library never finds this out by itself. A backtest that shells out to git
from inside a notebook in another directory reports the wrong repository, and
one run where git is not installed reports nothing at all while looking as if
it had. So the state is **given** to a run, and :func:`git_source_state` is the
helper a script calls, deliberately, from the checkout it runs in.
"""

from __future__ import annotations

import hashlib
import platform
import re
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from importlib import metadata
from pathlib import Path

_COMMIT = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")
"""A full commit id as ``git rev-parse HEAD`` prints it: SHA-1, or SHA-256."""


class SourceStatus(Enum):
    """What is known about the code a run was produced by."""

    CLEAN = "CLEAN"
    """A commit, and a working tree identical to it."""

    DIRTY = "DIRTY"
    """A commit, and changes to it nobody committed - the result is not
    reproducible from the commit alone."""

    UNVERSIONED = "UNVERSIONED"
    """Not a git checkout, or git is not available: there is no commit to cite."""

    UNRECORDED = "UNRECORDED"
    """Nobody said. Recorded as such rather than guessed at."""


@dataclass(frozen=True, slots=True)
class SourceState:
    """The state of the code a run was produced by.

    Attributes
    ----------
    status : SourceStatus
        What is known about it.
    git_commit : str | None
        The commit checked out, for a clean or dirty tree; ``None`` otherwise.

    Raises
    ------
    ValueError
        If a clean or dirty state carries no full commit id, or another state
        carries one. A commit is either known or it is not.
    """

    status: SourceStatus
    git_commit: str | None = None

    def __post_init__(self) -> None:
        """Check the commit is there exactly when the status says it is."""
        if not isinstance(self.status, SourceStatus):
            raise ValueError(f"status must be a SourceStatus, got {self.status!r}")
        versioned = self.status in (SourceStatus.CLEAN, SourceStatus.DIRTY)
        if versioned and (self.git_commit is None or not _COMMIT.fullmatch(self.git_commit)):
            raise ValueError(
                f"a {self.status.value} source names its full commit, got {self.git_commit!r}"
            )
        if not versioned and self.git_commit is not None:
            raise ValueError(f"a {self.status.value} source has no commit to name")

    @classmethod
    def unrecorded(cls) -> SourceState:
        """Return the state of a run nobody described."""
        return cls(SourceStatus.UNRECORDED)

    @property
    def dirty(self) -> bool | None:
        """Return whether the tree had uncommitted changes, ``None`` when unknown."""
        if self.status is SourceStatus.CLEAN:
            return False
        if self.status is SourceStatus.DIRTY:
            return True
        return None

    def definition(self) -> dict[str, object]:
        """Return the state as it is recorded with a run."""
        return {
            "git_commit": self.git_commit,
            "dirty": self.dirty,
            "source_state": self.status.value,
        }


def git_source_state(path: Path) -> SourceState:
    """Return the state of the git checkout ``path`` belongs to.

    Parameters
    ----------
    path : Path
        A directory inside the checkout - the repository root, normally.

    Returns
    -------
    SourceState
        ``CLEAN`` or ``DIRTY`` with the commit checked out, or ``UNVERSIONED``
        when ``path`` is not inside a git checkout or git cannot be run.

    Notes
    -----
    An untracked file counts as a change: a strategy written in a new module
    and never committed produced the result as surely as an edited one. Files
    the repository ignores - the market data store, caches - do not.
    """
    try:
        head = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        if head.returncode != 0:
            return SourceState(SourceStatus.UNVERSIONED)
        changes = subprocess.run(
            ["git", "-C", str(path), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return SourceState(SourceStatus.UNVERSIONED)
    if changes.returncode != 0:
        return SourceState(SourceStatus.UNVERSIONED)
    commit = head.stdout.strip()
    status = SourceStatus.DIRTY if changes.stdout.strip() else SourceStatus.CLEAN
    return SourceState(status, commit)


ENVIRONMENT_PACKAGES: tuple[str, ...] = ("numpy", "pandas", "pyarrow", "scipy")
"""The libraries whose version can change a number a run prints."""


def environment_state(lockfile: Path | None = None) -> dict[str, str]:
    """Return the environment a run is computed in, as it can be stated.

    Parameters
    ----------
    lockfile : Path | None
        The ``uv.lock`` the environment was synced from, when the caller knows
        it - a script, from the checkout it runs in. ``None`` records the
        lockfile as unrecorded rather than guessing where one is.

    Returns
    -------
    dict[str, str]
        The Python version and implementation, the platform, the SHA-256 of
        the lockfile, and the installed version of each library of
        :data:`ENVIRONMENT_PACKAGES`. A commit pins the lockfile a checkout
        holds, not the environment actually installed from it; two machines
        with one commit and two installs are two environments, and a run says
        which one it had (audit of archive 9, point 3.2).
    """
    state = {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": sys.platform,
        "lockfile_sha256": (
            hashlib.sha256(lockfile.read_bytes()).hexdigest()
            if lockfile is not None
            else "UNRECORDED"
        ),
    }
    for name in ENVIRONMENT_PACKAGES:
        try:
            state[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            state[name] = "NOT_INSTALLED"
    return state
