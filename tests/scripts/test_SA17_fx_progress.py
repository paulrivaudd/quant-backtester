"""Offline watchdog progress and stall tests; never start the acquisition."""

from __future__ import annotations

import subprocess
from pathlib import Path

from scripts import SA17_fx_progress as progress


def test_progress_needs_no_manifest_and_ignores_unexpected_files(tmp_path: Path) -> None:
    assert progress.progress(tmp_path, "hours") == (0, 272)
    paths = progress.expected_files("hours")
    first = tmp_path / paths[0]
    first.parent.mkdir(parents=True)
    first.write_bytes(b"complete")
    first.with_name("2099-01.bi5").write_bytes(b"unexpected")
    first.with_name("2015-08.bi5.part").write_bytes(b"partial")
    assert progress.progress(tmp_path, "hours") == (1, 272)
    assert progress.progress(tmp_path, "minutes") == (0, 48)
    assert not (tmp_path / "manifest.jsonl").exists()


def test_watchdog_progress_prevents_stopping_an_active_pass(tmp_path: Path) -> None:
    watchdog = Path(__file__).resolve().parents[2] / "scripts/SA17_fx_watchdog.sh"
    subprocess.run(["bash", "-n", str(watchdog)], check=True)
    # All time, network commands and process controls are fakes in this shell.
    script = """
source "$1"
LOG="$2/log"
ticks=0
progress() { echo "$ticks 25"; }
sleep() { ticks=$((ticks + 1)); }
uv() { return 0; }
kill() { [[ "$1" == -0 && "$ticks" -lt 25 ]]; }
pkill() { echo "unexpected stop" >&2; return 1; }
note() { [[ "$*" != *"stopping"* && "$*" != *"pause"* ]]; }
step fetch hours
[[ "$ticks" == 25 ]]
"""
    subprocess.run(
        ["bash", "-e", "-c", script, "test", str(watchdog), str(tmp_path)],
        check=True,
        capture_output=True,
        text=True,
    )
