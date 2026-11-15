"""Extend the paper store: the SA16 study's store, followed forward day by day.

Run under WSL/POSIX from the repository root, before ``scripts/paper_trade.py``::

    uv run python scripts/paper_update_store.py

The first invocation copies the study's store (``runs/sa16_store``, built by
``scripts/SA16_download_data.py`` and frozen at 2026-10-30) to
``runs/paper_sa16_store``, so the paper books start on the very bars the
study was read on. Every invocation then extends each series to the last
observation entirely published at the wall clock: a session still trading is
never fetched. The study's store is never written.

The rules are the data pipeline's and are not relaxed here: stored values
win, a refetch that disagrees with history is logged and dropped, and nothing
is promoted while a validation error stands. An instrument refused today is
reported, the script exits non-zero, and the paper run waits: it logs no
session the store is incomplete for.

The store keeps the metadata it was seeded with (registry, calendars,
reviewed decisions), whatever the repository's becomes: an instrument added
for another study does not stop the paper run, and does not reach it. The
study's store is frozen and refuses any difference; this one runs for a year
and will need a reviewed decision recorded, or a calendar extended. That is
done in the repository, committed, and then adopted on purpose::

    uv run python scripts/paper_update_store.py --adopt-metadata "why"

which replaces the store's metadata by the committed one and appends what
changed, the reason and the commit to the store's ``metadata_changes.jsonl``.
Metadata edited in place in the store is refused, by this script and by
``scripts/paper_trade.py``. An adoption that changes
what a plan decided on a logged session is caught by the log, as any other
change of the past is.

This is the only script of the paper run that touches the network.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from SA16_download_data import (  # noqa: E402
    INSTRUMENT_IDS,
    STUDY_END,
    build_updater,
    combined_registry,
    metadata_manifest,
)
from SA16_download_data import STORE as STUDY_STORE  # noqa: E402

from quant_backtester.data.calendars import CalendarRegistry  # noqa: E402
from quant_backtester.data.instruments import InstrumentRegistry  # noqa: E402
from quant_backtester.data.updater import MarketDataUpdater  # noqa: E402
from quant_backtester.provenance import SourceStatus, git_source_state  # noqa: E402

STORE = ROOT / "runs" / "paper_sa16_store"
SEEDED = ("metadata", "metadata_sha256.json", "raw", "clean", "validation")
"""What a store is made of. Its reports and its lock are its own."""

REVIEWED = ROOT / "market_data" / "metadata"
"""The repository's committed metadata, the registry apart: see :func:`reviewed_metadata`."""

MANIFEST = "metadata_sha256.json"
CHANGES = "metadata_changes.jsonl"
"""In the store: the hashes of its metadata, and the record of every adoption."""


def seed_store(store: Path, seed: Path) -> bool:
    """Copy the study's store once; return whether it was copied now.

    Raises
    ------
    FileNotFoundError
        If neither store exists: the study's has to be built first.
    """
    if store.exists():
        return False
    if not (seed / "metadata_sha256.json").exists():
        raise FileNotFoundError(
            f"{seed} is not a built store; run scripts/SA16_download_data.py first"
        )
    partial = store.with_name(store.name + ".partial")
    if partial.exists():
        shutil.rmtree(partial)
    partial.mkdir(parents=True)
    for name in SEEDED:
        source = seed / name
        if source.is_dir():
            shutil.copytree(source, partial / name)
        elif source.exists():
            shutil.copy2(source, partial / name)
    partial.rename(store)
    return True


def update_store(updater: MarketDataUpdater, instruments: Sequence[str]) -> list[dict[str, Any]]:
    """Extend every series, one at a time, and return what happened to each.

    An instrument that raises or is refused does not stop the others: each
    outcome is recorded, never swallowed.
    """
    outcomes: list[dict[str, Any]] = []
    for instrument_id in instruments:
        try:
            report = updater.update(instrument_id)
        except Exception as exc:  # recorded and reported, never swallowed
            outcomes.append({"instrument_id": instrument_id, "exception": repr(exc)})
            print(f"{instrument_id:<20} RAISED {type(exc).__name__}: {exc}", flush=True)
            continue
        outcomes.append(
            {
                "instrument_id": instrument_id,
                "valid": report.valid,
                "errors": len(report.errors),
                "warnings": len(report.warnings),
                "issues": [
                    {**asdict(issue), "severity": issue.severity.value} for issue in report.issues
                ],
            }
        )
        print(
            f"{instrument_id:<20} {'EXTENDED' if report.valid else 'REFUSED':<8} "
            f"{len(report.errors)} error(s), {len(report.warnings)} warning(s)",
            flush=True,
        )
        for issue in report.errors:
            print(f"  ERROR {issue.code} {issue.observation_date}: {issue.message}", flush=True)
    return outcomes


def failed(outcomes: Sequence[dict[str, Any]]) -> bool:
    """Return whether an instrument raised or was refused."""
    return any("exception" in outcome or not outcome["valid"] for outcome in outcomes)


def reviewed_metadata(source: Path, registry: str) -> dict[str, bytes]:
    """Return the metadata a store is made from, by relative path.

    Parameters
    ----------
    source : Path
        The repository's metadata folder, inside a git checkout.
    registry : str
        The store's registry, which replaces the folder's ``instruments.toml``:
        the project's followed by the studies' additions.

    Returns
    -------
    dict[str, bytes]
        The content of every file of ``source`` that git tracks. A file the
        repository ignores - an editor's backup, a lock - is not metadata, and
        a clean checkout says nothing about it.

    Raises
    ------
    subprocess.CalledProcessError
        If ``source`` is not inside a git checkout.
    """
    listed = subprocess.run(
        ["git", "-C", str(source), "ls-files", "-z"], check=True, capture_output=True
    ).stdout
    files = {
        name.decode(): (source / name.decode()).read_bytes()
        for name in sorted(listed.split(b"\0"))
        if name and (source / name.decode()).is_file()
    }
    files["instruments.toml"] = registry.encode("utf-8")
    return files


def _text_hash(content: bytes) -> str:
    """Hash a metadata file as text: a CRLF line ending is not a difference."""
    return hashlib.sha256(content.replace(b"\r\n", b"\n")).hexdigest()


def _differences(metadata: Path, reviewed: Mapping[str, bytes]) -> dict[str, dict[str, Any]]:
    """Return, for each file whose text differs, its hash in the store and as reviewed.

    The study's store was built from a Windows checkout and its metadata
    carries CRLF line endings; the same text in the repository does not.
    """
    held = {
        path.relative_to(metadata).as_posix(): _text_hash(path.read_bytes())
        for path in sorted(metadata.rglob("*"))
        if path.is_file()
    }
    wanted = {name: _text_hash(content) for name, content in reviewed.items()}
    return {
        name: {"from": held.get(name), "to": wanted.get(name)}
        for name in sorted(held.keys() | wanted.keys())
        if held.get(name) != wanted.get(name)
    }


def require_recorded_metadata(store: Path) -> None:
    """Refuse a store whose metadata is not the one its manifest records.

    Raises
    ------
    ValueError
        If the metadata was edited in place, or an adoption was interrupted.
        Both scripts of the paper run call this before reading the store.
    """
    manifest = store / MANIFEST
    held = metadata_manifest(store / "metadata")
    if not manifest.exists() or json.loads(manifest.read_text(encoding="utf-8")) != held:
        raise ValueError(
            f"the metadata of {store} is not the one it recorded: it is never edited in "
            "place. Commit the change to the repository's metadata, then run "
            "scripts/paper_update_store.py --adopt-metadata REASON, which also repairs an "
            "interrupted adoption"
        )


def metadata_differences(store: Path, reviewed: Mapping[str, bytes]) -> dict[str, dict[str, Any]]:
    """Return what adopting ``reviewed`` would change in a store's metadata.

    Returns
    -------
    dict[str, dict[str, Any]]
        For each file whose text differs, its sha256 in the store (``from``)
        and in ``reviewed`` (``to``), line endings apart; ``None`` where the
        file does not exist.

    Raises
    ------
    ValueError
        As :func:`require_recorded_metadata`.
    """
    require_recorded_metadata(store)
    return _differences(store / "metadata", reviewed)


def adopt_metadata(
    store: Path, reviewed: Mapping[str, bytes], reason: str, git_commit: str, now: datetime
) -> dict[str, dict[str, Any]]:
    """Replace a store's metadata by the committed one, and record the change.

    Parameters
    ----------
    store : Path
        The paper store.
    reviewed : Mapping[str, bytes]
        The committed metadata, from :func:`reviewed_metadata`.
    reason : str
        Why, in a sentence; recorded.
    git_commit : str
        The commit ``reviewed`` was read at; recorded.
    now : datetime
        Timezone-aware wall-clock instant; recorded.

    Returns
    -------
    dict[str, dict[str, Any]]
        What changed, as :func:`metadata_differences`; empty if the store
        already held ``reviewed``, in which case nothing is written but a
        missing or stale manifest.

    Raises
    ------
    ValueError
        If ``reason`` is blank, ``now`` is naive, or ``reviewed`` does not
        load as a registry and its calendars. The store is then untouched.

    Notes
    -----
    The new folder is built beside the old one; the old one is set aside, the
    new one takes its place, the record is appended, the manifest is written,
    and only then is the old one deleted. An interruption leaves the old
    folder set aside, and a manifest that does not match: every run of the
    paper scripts refuses the store until the adoption is run again, which
    first puts the old folder back. The record of an adoption interrupted
    after it was appended is then appended a second time, with the same
    content; no record ever describes a change that was not made.
    """
    if not reason.strip():
        raise ValueError("an adoption needs a reason")
    if now.tzinfo is None:
        raise ValueError(f"now must be timezone-aware, got {now!r}")
    metadata, previous = store / "metadata", store / "metadata.previous"
    partial, manifest = store / "metadata.partial", store / MANIFEST
    if previous.exists():
        # An adoption was interrupted: start again from what the store held.
        if metadata.exists():
            shutil.rmtree(metadata)
        previous.rename(metadata)
    changed = _differences(metadata, reviewed)
    if not changed:
        held = metadata_manifest(metadata)
        if not manifest.exists() or json.loads(manifest.read_text(encoding="utf-8")) != held:
            manifest.write_text(json.dumps(held, indent=2) + "\n", encoding="utf-8")
        return {}
    if partial.exists():
        shutil.rmtree(partial)
    for name, content in reviewed.items():
        path = partial / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    try:
        InstrumentRegistry.from_toml(partial / "instruments.toml")
        CalendarRegistry.from_directory(partial / "calendars")
    except Exception as exc:
        shutil.rmtree(partial)
        raise ValueError(f"the committed metadata does not load: {exc}") from exc
    record = {
        "adopted_at": now.isoformat(),
        "reason": reason.strip(),
        "git_commit": git_commit,
        "files": changed,
    }
    metadata.rename(previous)
    partial.rename(metadata)
    with (store / CHANGES).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    manifest.write_text(json.dumps(metadata_manifest(metadata), indent=2) + "\n", encoding="utf-8")
    shutil.rmtree(previous)
    return changed


def main(arguments: Sequence[str] | None = None) -> int:
    """Seed the paper store if needed, extend it, and write what was done."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--store", type=Path, default=STORE)
    parser.add_argument("--seed", type=Path, default=STUDY_STORE)
    parser.add_argument("--only", nargs="+", choices=INSTRUMENT_IDS)
    parser.add_argument(
        "--adopt-metadata",
        metavar="REASON",
        help="replace the store's metadata by the repository's committed one, and record why",
    )
    parsed = parser.parse_args(arguments)
    store = parsed.store.resolve()
    if seed_store(store, parsed.seed.resolve()):
        print(f"seeded {store} from {parsed.seed}", flush=True)
    now = datetime.now(UTC)
    reviewed = reviewed_metadata(REVIEWED, combined_registry())
    if parsed.adopt_metadata is not None:
        source = git_source_state(ROOT)
        if source.status is not SourceStatus.CLEAN or source.git_commit is None:
            raise SystemExit(
                f"metadata is adopted from a commit; this tree is {source.status.value}"
            )
        changed = adopt_metadata(store, reviewed, parsed.adopt_metadata, source.git_commit, now)
        print(f"adopted: {', '.join(changed) or 'nothing to adopt'}", flush=True)
    else:
        differing = metadata_differences(store, reviewed)
        if differing:
            print(
                f"note: the repository's metadata differs from the store's "
                f"({', '.join(differing)}); the store keeps its own until "
                "--adopt-metadata REASON",
                flush=True,
            )
    updater = build_updater(store, STUDY_END, clock=lambda: now)
    outcomes = update_store(updater, tuple(parsed.only or INSTRUMENT_IDS))
    folder = store / "reports"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"paper_update_{now.strftime('%Y%m%dT%H%M%S%fZ')}.json"
    evidence = {"updated_at": now.isoformat(), "outcomes": outcomes}
    path.write_text(json.dumps(evidence, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"evidence: {path}", flush=True)
    return int(failed(outcomes))


if __name__ == "__main__":
    raise SystemExit(main())
