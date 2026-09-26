"""A run kept on disk: read back without recomputing, and recomputable from what it kept.

A ``StrategyResult`` lives in memory. Its ``run_id`` names the experiment and
its store digest says which data it read, but neither keeps anything: once the
process ends and the store is revised, the positions and the curves are gone,
and the digest can only say that the store is no longer the one the run read
(audit of archive 9, C01). Three things are distinct - *identifying* a run,
*reading it back* and *recomputing it* - and this module gives the last two.

A kept run is a directory:

- ``manifest.json``: the format, the ``run_id``, the fingerprint, and the
  SHA-256 of every other file - written last, so a directory without it was
  never finished;
- ``configuration.json`` and ``definition.json``: what the run was;
- ``sessions.jsonl``: every session's whole economic state - the decision,
  orders, fills with their prices and costs, rejects, holdings, cash, equity -
  in the form a paper log keeps;
- ``curves.json``: the net and gross equity, and the benchmark valued inside
  the run;
- ``report.txt``: the report as printed;
- ``store/`` (on request): a copy of every file of ``clean/`` and
  ``metadata/`` the run's store digest names, checked against it, so that the
  run can be computed again from exactly what it read.

The directory is written under a temporary name and renamed into place, so it
is either all there or not there. Reading it back checks the format and every
digest, and touches neither the current store nor the network.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from quant_backtester.analytics.curves import Book
from quant_backtester.backtest.runner import StoreChanged, StrategyResult, plain_configuration
from quant_backtester.data.repository import MarketDataRepository
from quant_backtester.research.paper import PaperEntry, entries_of

FORMAT = "quant-backtester-run/1"
"""The format of a kept run. A reader refuses any other."""

MANIFEST = "manifest.json"
"""The file that makes a kept run complete: written last, and naming every other one."""


STORE_LOCK = "store/.lock"
"""The lock file a repository opened on the kept store creates; not part of the run."""


class ArchiveError(ValueError):
    """Raised when a kept run cannot be trusted: another format, or a file that changed."""


@dataclass(frozen=True, slots=True)
class KeptRun:
    """A run read back from disk.

    Attributes
    ----------
    path : Path
        The directory it was read from.
    run_id : str
        Identity of the experiment.
    fingerprint : str
        Identity of the strategy's definition.
    configuration : Mapping[str, object]
        Everything the run recorded it depended on.
    definition : Mapping[str, object]
        The strategy's definition.
    sessions : tuple[PaperEntry, ...]
        Every session's economic state.
    net, gross : pd.Series
        The equity curves, by session date.
    benchmark : pd.Series | None
        The benchmark valued inside the run, when one was declared.
    report : str
        The report as it was printed.
    store : Path | None
        The copy of the store the run read, when it was kept.
    """

    path: Path
    run_id: str
    fingerprint: str
    configuration: Mapping[str, object]
    definition: Mapping[str, object]
    sessions: tuple[PaperEntry, ...]
    net: pd.Series  # type: ignore[type-arg]
    gross: pd.Series  # type: ignore[type-arg]
    benchmark: pd.Series | None  # type: ignore[type-arg]
    report: str
    store: Path | None


def _sha256(path: Path) -> str:
    """Return the hex SHA-256 of a file's bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _curve(series: pd.Series) -> list[list[object]]:  # type: ignore[type-arg]
    """Return a curve as ``[date, value]`` pairs."""
    return [[str(day), float(value)] for day, value in zip(series.index, series, strict=True)]


def _series(pairs: list[list[object]], name: str) -> pd.Series:  # type: ignore[type-arg]
    """Return a curve read back, indexed by session date."""
    return pd.Series(
        [float(str(value)) for _, value in pairs],
        index=pd.Index([date.fromisoformat(str(day)) for day, _ in pairs], dtype="object"),
        name=name,
        dtype="float64",
    )


def keep(
    result: StrategyResult,
    directory: Path,
    *,
    store: MarketDataRepository | None = None,
) -> Path:
    """Write a finished run to ``directory``, whole or not at all.

    Parameters
    ----------
    result : StrategyResult
        The run.
    directory : Path
        Where to keep it. Must not exist: a kept run is never overwritten.
    store : MarketDataRepository | None
        The store the run read, to copy its files beside the run. Only done
        when the store still holds exactly what the run read.

    Returns
    -------
    Path
        ``directory``.

    Raises
    ------
    FileExistsError
        If ``directory`` exists.
    StoreChanged
        If ``store`` is given and no longer holds what the run read: a copy of
        another state would recompute another experiment.
    """
    if directory.exists():
        raise FileExistsError(f"{directory} exists; a kept run is never overwritten")
    directory.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(dir=directory.parent, prefix=f".{directory.name}."))
    try:
        (staging / "configuration.json").write_text(
            json.dumps(plain_configuration(result.configuration), sort_keys=True, indent=1),
            encoding="utf-8",
        )
        (staging / "definition.json").write_text(
            json.dumps(plain_configuration(result.definition), sort_keys=True, indent=1),
            encoding="utf-8",
        )
        (staging / "sessions.jsonl").write_text(
            "".join(entry.as_json() + "\n" for entry in entries_of(result)), encoding="utf-8"
        )
        curve = result.benchmark_curve
        (staging / "curves.json").write_text(
            json.dumps(
                {
                    "net": _curve(result.equity(Book.NET)),
                    "gross": _curve(result.equity(Book.GROSS)),
                    "benchmark": None if curve is None else _curve(curve.equity),
                    "benchmark_spec": None if curve is None else curve.spec.definition(),
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        (staging / "report.txt").write_text(result.report().render() + "\n", encoding="utf-8")
        if store is not None:
            _copy_store(result, store, staging / "store")
        files = {
            path.relative_to(staging).as_posix(): _sha256(path)
            for path in sorted(staging.rglob("*"))
            if path.is_file()
        }
        manifest = {
            "format": FORMAT,
            "run_id": result.run_id,
            "fingerprint": result.fingerprint,
            "files": files,
        }
        (staging / MANIFEST).write_text(
            json.dumps(manifest, sort_keys=True, indent=1), encoding="utf-8"
        )
        os.rename(staging, directory)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return directory


def _copy_store(result: StrategyResult, store: MarketDataRepository, into: Path) -> None:
    """Copy every file the run's store digest names, refusing a store that moved on."""
    with store.reading() as now:
        if now.digest != result.data_state.digest:
            raise StoreChanged(
                "the store no longer holds what this run read; keeping a copy of it would "
                "keep another experiment's inputs"
            )
        for relative, digest in result.data_state.files.items():
            target = into / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(store.root / relative, target)
            if _sha256(target) != digest:
                raise StoreChanged(f"{relative} changed while it was being copied")


def read_back(directory: Path) -> KeptRun:
    """Read a kept run, checking its format and every file against its manifest.

    Raises
    ------
    ArchiveError
        If the manifest is missing or of another format, a file it names is
        missing or has changed, or a file is there that it does not name.
    """
    manifest_path = directory / MANIFEST
    if not manifest_path.is_file():
        raise ArchiveError(f"{directory} has no {MANIFEST}: it was never finished")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format") != FORMAT:
        raise ArchiveError(f"{directory} is in format {manifest.get('format')!r}, not {FORMAT}")
    files: dict[str, str] = manifest["files"]
    present = {
        path.relative_to(directory).as_posix()
        for path in directory.rglob("*")
        if path.is_file() and path.relative_to(directory).as_posix() != MANIFEST
    }
    missing = sorted(set(files) - present)
    # The one file a kept run may gain: the lock a repository opened on the
    # kept store creates to read it. Replaying the run from its own store is
    # what the copy is for, and doing it must not make the run unreadable
    # (audit of archive 10). Only that exact path, and only when the manifest
    # does not name it; every file it names is still checked below.
    unexpected = sorted(present - set(files) - {STORE_LOCK})
    if missing or unexpected:
        raise ArchiveError(
            f"{directory} does not hold what its manifest names: missing {missing}, "
            f"unexpected {unexpected}"
        )
    for relative, digest in files.items():
        if _sha256(directory / relative) != digest:
            raise ArchiveError(f"{directory / relative} is not the file that was kept")
    curves = json.loads((directory / "curves.json").read_text(encoding="utf-8"))
    sessions = tuple(
        PaperEntry(**json.loads(line))
        for line in (directory / "sessions.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    )
    benchmark = curves["benchmark"]
    return KeptRun(
        path=directory,
        run_id=manifest["run_id"],
        fingerprint=manifest["fingerprint"],
        configuration=json.loads((directory / "configuration.json").read_text(encoding="utf-8")),
        definition=json.loads((directory / "definition.json").read_text(encoding="utf-8")),
        sessions=sessions,
        net=_series(curves["net"], "net"),
        gross=_series(curves["gross"], "gross"),
        benchmark=None if benchmark is None else _series(benchmark, "benchmark"),
        report=(directory / "report.txt").read_text(encoding="utf-8").rstrip("\n"),
        store=directory / "store" if (directory / "store").is_dir() else None,
    )


def same_economics(kept: KeptRun, result: StrategyResult) -> bool:
    """Return whether a run did, session by session, exactly what a kept run did."""
    return list(kept.sessions) == entries_of(result)
