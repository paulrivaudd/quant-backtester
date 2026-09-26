"""The lock an append-only journal is read, checked and appended under.

A register that refuses a duplicate reads itself before it appends, and two
writers who both read before either writes each find no duplicate and both
append: the same run counted twice, the same session logged twice (audit N07,
decision D22). Opening a file in append mode does not make the check that
came before it atomic. So the whole sequence holds an exclusive ``flock`` on a
lock file beside the journal, and the second writer reads what the first
wrote before it decides anything.
"""

from __future__ import annotations

import fcntl
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def exclusive(journal: Path) -> Iterator[None]:
    """Hold an exclusive lock on ``journal`` for the block, waiting for another holder.

    Parameters
    ----------
    journal : Path
        The journal file. The lock is taken on ``<journal>.lock`` beside it,
        created if needed, so that the journal itself is only ever appended to.

    Notes
    -----
    Waiting rather than failing: a journal is appended to in milliseconds, and
    a second writer arriving meanwhile has nothing better to do than to read
    the result and decide after it.
    """
    journal.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(journal.with_name(journal.name + ".lock"), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
