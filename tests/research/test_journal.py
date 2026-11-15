"""Tests of the lock a journal is read, checked and appended under."""

from __future__ import annotations

import fcntl
import os
import threading
from pathlib import Path

import pytest

from quant_backtester.research.journal import exclusive


def held_by_another(journal: Path) -> bool:
    """Return whether the journal's lock is held, by trying it from another descriptor."""
    descriptor = os.open(journal.with_name(journal.name + ".lock"), os.O_RDWR)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    else:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        return False
    finally:
        os.close(descriptor)


def test_the_lock_is_a_file_beside_the_journal_which_is_not_created(tmp_path: Path) -> None:
    journal = tmp_path / "deeper" / "runs.jsonl"
    with exclusive(journal):
        assert (journal.parent / "runs.jsonl.lock").exists()
        assert not journal.exists()
    assert not journal.exists()


def test_the_lock_is_held_for_the_block_and_released_after_it(tmp_path: Path) -> None:
    journal = tmp_path / "runs.jsonl"
    with exclusive(journal):
        assert held_by_another(journal)
    assert not held_by_another(journal)
    # Taken again, by the same process, once released.
    with exclusive(journal):
        assert held_by_another(journal)


def test_the_lock_is_released_when_the_block_raises(tmp_path: Path) -> None:
    journal = tmp_path / "runs.jsonl"
    with pytest.raises(RuntimeError, match="inside"), exclusive(journal):
        raise RuntimeError("inside")
    assert not held_by_another(journal)


def test_a_second_writer_waits_and_reads_what_the_first_wrote(tmp_path: Path) -> None:
    """Read, check, append: without the lock both writers find no line and both append."""
    journal = tmp_path / "runs.jsonl"
    inside, release = threading.Event(), threading.Event()

    def append_once(first: bool) -> None:
        with exclusive(journal):
            seen = journal.read_text() if journal.exists() else ""
            if first:
                inside.set()
                assert release.wait(timeout=10)
            if "run-1" not in seen:
                with journal.open("a") as stream:
                    stream.write("run-1\n")

    one = threading.Thread(target=append_once, args=(True,))
    two = threading.Thread(target=append_once, args=(False,))
    one.start()
    assert inside.wait(timeout=10)
    two.start()
    two.join(timeout=0.2)
    # The second writer is waiting for the lock, not reading an empty journal.
    assert two.is_alive()
    release.set()
    one.join(timeout=10)
    two.join(timeout=10)
    assert not one.is_alive() and not two.is_alive()
    assert journal.read_text() == "run-1\n"
