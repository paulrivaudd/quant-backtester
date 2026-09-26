"""Persistence: the only module that knows Parquet exists.

Layout under the market data root::

    metadata/
        instruments.toml            committed
        accepted_revisions.toml     committed - it changes past results
        calendars/*.toml            committed
    raw/<source>/<instrument_id>/<fetch_id>.parquet   immutable, append-only
    raw/<source>/<instrument_id>/<fetch_id>.json      request manifest
    clean/bars/<instrument_id>.parquet
    clean/check_bars/<source>/<instrument_id>.parquet  a check source's own canonical bars
    clean/checked_bars/<instrument_id>.parquet        bars cross-checked across sources
    clean/levels/<instrument_id>.parquet
    clean/vintages/<instrument_id>.parquet            a restated series, vintage by vintage
    clean/corporate_actions.parquet
    clean/applied_fetches.parquet                     which fetches shaped the clean layer
    clean/revisions.parquet
    validation/validation_log.parquet
    .pending/<id>/...                                 a transaction mid-flight
    .lock                                             who may write, and when

One promotion writes several of those files, and a series whose verdicts no
longer describe its values is worse than one that is a day out of date. So a
set of writes is made through :meth:`MarketDataRepository.transaction`: staged
under ``.pending/``, published together, and finished or discarded by the next
writer - never by someone who merely opened the store.

Every write holds ``.lock`` exclusively, through a transaction: a write made
outside one is a transaction of its own. A second writer - another process, or
another repository object on the same root - is refused with
:class:`StoreBusy` rather than made to wait or allowed to interleave. The lock
is an advisory ``flock``: it binds every process that goes through this
module, on a local filesystem, and nothing else.

``raw/`` is written once and never touched again: one file per fetch, named by
the fetch instant. That is what answers "what did Yahoo actually give us on
10 September?" and what lets vintages be reconstructed later.

``clean/`` is entirely derived and disposable: it is a pure function of the raw
snapshots, the accepted revisions, the calendars and the normalizer version.
"""

from __future__ import annotations

import fcntl
import functools
import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import BinaryIO, Concatenate

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from quant_backtester.data.schemas import (
    APPLIED_FETCHES_SCHEMA,
    BARS_SCHEMA,
    CHECKED_BARS_SCHEMA,
    CORPORATE_ACTIONS_SCHEMA,
    LEVELS_SCHEMA,
    REVISIONS_SCHEMA,
    VALIDATION_LOG_SCHEMA,
    VINTAGES_SCHEMA,
    CheckStatus,
)
from quant_backtester.data.sources.base import RawDownload
from quant_backtester.data.validator import ValidationReport


def _atomic_write(path: Path, write: Callable[[BinaryIO], object]) -> None:
    """Write a file through a temporary sibling, then rename it over ``path``.

    Parameters
    ----------
    path : Path
        Destination file; parent directories are created.
    write : Callable[[BinaryIO], object]
        Writes the content into the open temporary file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # Same directory as the target: os.replace is only atomic within one filesystem.
    descriptor, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            write(handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def write_parquet_atomic(frame: pd.DataFrame, path: Path, schema: pa.Schema) -> None:
    """Write a frame to Parquet so a crash cannot corrupt the dataset.

    Parameters
    ----------
    frame : pd.DataFrame
        Rows to write.
    path : Path
        Destination file; parent directories are created.
    schema : pa.Schema
        Expected schema; a mismatch is an error, not something to coerce.

    Raises
    ------
    ValueError
        If ``frame`` does not match ``schema``.

    Notes
    -----
    Exercice 3.1 (facile, non negociable). Ecris dans un temporaire **dans le
    meme repertoire** que la cible, puis ``os.replace``. Le rename est atomique
    sur le meme systeme de fichiers ; passer par ``/tmp`` casse cette garantie.
    Sans ca, une interruption en cours d'ecriture detruit l'historique complet
    d'un instrument.
    """
    missing = set(schema.names) - set(frame.columns)
    extra = set(frame.columns) - set(schema.names)
    if missing or extra:
        raise ValueError(f"Column mismatch: missing={sorted(missing)}, extra={sorted(extra)}")
    for field in schema:
        if pa.types.is_timestamp(field.type):
            dtype = frame[field.name].dtype
            if not (isinstance(dtype, pd.DatetimeTZDtype) and str(dtype.tz) == "UTC"):
                raise ValueError(f"Column {field.name!r} must be a UTC timestamp, got {dtype}")
    try:
        table = pa.Table.from_pandas(frame, schema=schema, preserve_index=False)
    except (pa.ArrowException, TypeError, ValueError) as exc:
        raise ValueError(f"Schema mismatch: {exc}") from exc

    _atomic_write(path, lambda handle: pq.write_table(table, handle))


LOCK_FILE = ".lock"
"""File, under the root, whose ``flock`` says who may write the store."""


class StoreBusy(RuntimeError):
    """Raised when the store is locked by someone else.

    A writer is refused while another writer holds the store - or, once runs
    hold it for reading, while one does. Failing is the point: an ingestion
    that waited behind a five-minute backtest, or a backtest that read half of
    an ingestion, are both worse than an error that says who holds the store.
    """


class TransactionDoomed(RuntimeError):
    """Raised when a transaction ends after a block joined to it failed.

    A caller may catch what a joined block raised and carry on, but the
    transaction it joined had staged part of that block's work, which nothing
    can now separate from the rest. So the whole transaction is discarded.
    """


class _StoreLock:
    """The ``flock`` a repository holds on ``.lock``, reentrant within it.

    Parameters
    ----------
    path : Path
        The lock file; created on first use.

    Notes
    -----
    A lock belongs to an open file description, so two repository objects in
    one process exclude each other exactly as two processes do: that is what
    makes the second object of a test the same hazard as a second process.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._descriptor: int | None = None
        self._mode: int | None = None

    @contextmanager
    def hold(self, mode: int, what: str) -> Iterator[None]:
        """Hold the lock in ``mode`` for the block, or raise :class:`StoreBusy`.

        Parameters
        ----------
        mode : int
            ``fcntl.LOCK_EX`` to write, ``fcntl.LOCK_SH`` to read.
        what : str
            What is being attempted, for the error.

        Raises
        ------
        StoreBusy
            If another holder excludes ``mode``, or if this object holds the
            lock for reading and asks to write inside that.
        """
        if self._descriptor is not None:
            if mode == fcntl.LOCK_EX and self._mode != fcntl.LOCK_EX:
                raise StoreBusy(f"cannot {what} while this repository holds the store for reading")
            yield
            return
        descriptor = os.open(self._path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(descriptor, mode | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(descriptor)
            holder = "reading or writing it" if mode == fcntl.LOCK_EX else "writing it"
            raise StoreBusy(
                f"cannot {what}: {self._path.parent} is held by another process or "
                f"repository {holder}"
            ) from None
        self._descriptor = descriptor
        self._mode = mode
        try:
            yield
        finally:
            self._descriptor = None
            self._mode = None
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)


def _sha256(path: Path) -> str:
    """Return the hex SHA-256 of a file's bytes."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _writes[**P, R](
    method: Callable[Concatenate[MarketDataRepository, P], R],
) -> Callable[Concatenate[MarketDataRepository, P], R]:
    """Make a write method a transaction of its own unless it is inside one."""

    @functools.wraps(method)
    def write(self: MarketDataRepository, *args: P.args, **kwargs: P.kwargs) -> R:
        with self.transaction():
            return method(self, *args, **kwargs)

    return write


PINNED_TREES: tuple[str, ...] = ("clean", "metadata")
"""The parts of the store a run's result depends on, and so pins.

``clean/`` is what the reader serves; ``metadata/`` is the configuration it
was derived under. ``raw/`` is left out on purpose: a new fetch archived
there changes no result until it is promoted, and promoting it changes
``clean/``.
"""


@dataclass(frozen=True, slots=True)
class StoreState:
    """What the store held when a run read it: one digest per file.

    Attributes
    ----------
    files : Mapping[str, str]
        SHA-256 of every file under :data:`PINNED_TREES`, by path relative to
        the market data root, sorted.

    Notes
    -----
    Two states are equal when every byte a run could have read is equal. That
    is the test a result applies before valuing anything after the run: the
    same state, the same answer; another state, another experiment.
    """

    files: Mapping[str, str]

    def __post_init__(self) -> None:
        """Keep the files sorted and read-only."""
        object.__setattr__(self, "files", MappingProxyType(dict(sorted(self.files.items()))))

    @property
    def digest(self) -> str:
        """Return one SHA-256 over every path and its digest."""
        canonical = json.dumps(dict(self.files), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


PENDING = ".pending"
"""Directory, under the root, where a transaction stages its files.

Under the root on purpose: ``os.replace`` is only atomic within one
filesystem, and a staging area anywhere else would turn every commit into a
copy that can fail half way.
"""

COMMIT_MANIFEST = "COMMIT.json"
"""Written last, and the only thing that makes a staged set of files real.

Its presence is the difference between a transaction that was interrupted
before it decided anything - discarded - and one that had already decided and
was interrupted while moving files - finished.
"""


class MarketDataRepository:
    """Read and write the market data tree.

    Parameters
    ----------
    root : Path
        Market data root, i.e. the directory holding ``metadata/``, ``raw/``,
        ``clean/`` and ``validation/``. Passed in rather than read from a global
        so tests can point at a temporary directory.

    Notes
    -----
    Opening a repository finishes or discards whatever a previous run left
    behind - see :meth:`transaction` - but only when no one else holds the
    store: a staging directory without a manifest is exactly what a writer
    still at work looks like, and opening the store to read it used to delete
    that writer's work under it (audit A02). It is the one side effect a
    constructor here has, and it is the price of a store that can be
    interrupted.

    A file of the clean layer is decoded once per *version* of it and kept:
    a backtest reads the same few files thousands of times, and decoding them
    each time was a quarter of every run. A version is the file's device,
    inode, size and modification time to the nanosecond, so a file replaced -
    every write here is a new file renamed into place - is read again, and one
    that has not changed is never read twice. What a caller gets is its own
    copy: under pandas' copy-on-write, nothing it does to the frame reaches
    the one kept here.
    """

    def __init__(self, root: Path) -> None:
        if not root.is_dir():
            raise FileNotFoundError(f"Market data root {root} does not exist")
        self.root = root
        self._staged: dict[Path, Path] | None = None
        self._staging: Path | None = None
        self._decoded: dict[Path, tuple[tuple[int, int, int, int], pd.DataFrame]] = {}
        self._doomed = False
        self._lock = _StoreLock(root / LOCK_FILE)
        try:
            with self._lock.hold(fcntl.LOCK_EX, "recover interrupted transactions"):
                self._recover()
        except StoreBusy:
            # Someone is writing: what is pending is theirs, or will be
            # recovered by the next writer, which always recovers first.
            pass

    def _forget(self, staging: Path) -> None:
        """Drop the decoded copies of a transaction's staged files.

        They are read while the transaction writes and are gone once it ends -
        moved into place, or discarded - so keeping them would only grow the
        cache by one frame per staged file for as long as a rebuild runs.
        """
        self._decoded = {
            path: kept for path, kept in self._decoded.items() if not path.is_relative_to(staging)
        }

    def _load(self, path: Path, schema: pa.Schema) -> pd.DataFrame:
        """Return a file of the clean layer, decoded once per version of it.

        Parameters
        ----------
        path : Path
            File to read.
        schema : pa.Schema
            Its schema, for the empty frame an absent file gives.

        Returns
        -------
        pd.DataFrame
            The stored rows, as :func:`_load_or_empty` reads them, in a frame
            of the caller's own.

        Notes
        -----
        The version is taken before the file is read. Should the file be
        replaced in between, the frame kept is newer than its version says,
        and the next call - seeing a version that does not match - reads it
        again: the cache can only ever err towards reading once too often.
        """
        try:
            status = path.stat()
        except FileNotFoundError:
            return _load_or_empty(path, schema)
        version = (status.st_dev, status.st_ino, status.st_size, status.st_mtime_ns)
        kept = self._decoded.get(path)
        if kept is None or kept[0] != version:
            kept = (version, _load_or_empty(path, schema))
            self._decoded[path] = kept
        return kept[1].copy(deep=False)

    # -- transactions ------------------------------------------------------

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Write several files as one change, or write none of them.

        Yields
        ------
        None
            Inside the block, every clean-layer write is staged rather than
            applied, and every read sees what this transaction has written so
            far.

        Raises
        ------
        StoreBusy
            If another process or repository holds the store.
        TransactionDoomed
            If a block joined to this transaction raised, whether or not the
            exception was caught on its way out.

        Notes
        -----
        One promotion writes the bars, each check source's bars, the verdicts,
        the revision log and the journal of applied fetches. Each of those
        writes is atomic on its own, and that is not the same thing: a run that
        died between two of them left a clean layer whose verdicts described
        values that were no longer there. It was *detected* - the next update
        refuses to build on it - and detection means someone rebuilds a series
        by hand because a laptop slept at the wrong moment.

        So the set is committed together. Files are written into
        ``.pending/<id>/``, mirroring their place in the tree; the manifest
        naming them is written last; and only then is each file moved onto its
        target. Recovery reads the manifest: present, the moves are finished
        (each one is atomic, and a move already done is simply skipped);
        absent, the whole staging directory is discarded. There is no state in
        between, because the manifest appears in one filesystem operation.

        The store is held exclusively from the first staged write to the last
        move, and a transaction starts by recovering what a crashed writer left:
        holding the lock is what makes a manifest-less staging directory
        abandoned rather than in progress.

        A transaction opened inside another **joins** it: its writes are staged
        with the outer ones and published with them, and it commits nothing of
        its own. If a joined block raises, the outer transaction is doomed and
        publishes nothing - a rebuild is one change, not one per fetch.

        What this does not claim is a database. A reader that opens two files
        while the commit is moving them can still see one old and one new - the
        window is microseconds rather than the seconds an ingestion takes, and
        closing it entirely needs a snapshot the filesystem does not offer.
        """
        if self._staged is not None:
            try:
                yield
            except BaseException:
                self._doomed = True
                raise
            return
        with self._lock.hold(fcntl.LOCK_EX, "write the store"):
            self._recover()
            staging = Path(tempfile.mkdtemp(dir=self._pending_root()))
            self._staged = {}
            self._staging = staging
            self._doomed = False
            try:
                yield
            except BaseException:
                self._staged = None
                self._staging = None
                self._forget(staging)
                shutil.rmtree(staging, ignore_errors=True)
                raise
            staged = self._staged
            doomed = self._doomed
            self._staged = None
            self._staging = None
            self._doomed = False
            self._forget(staging)
            if doomed:
                shutil.rmtree(staging, ignore_errors=True)
                raise TransactionDoomed(
                    "a block joined to this transaction failed; nothing it staged is published"
                )
            self._commit(staging, staged)

    @contextmanager
    def reading(self) -> Iterator[StoreState]:
        """Hold the store for reading, and say what it holds.

        Yields
        ------
        StoreState
            The digests of every pinned file, taken once the lock is held: no
            writer can change them until the block ends.

        Raises
        ------
        StoreBusy
            If a writer holds the store. Readers do not exclude each other;
            they exclude writers, which fail at once rather than wait.
        """
        with self._lock.hold(fcntl.LOCK_SH, "read the store for a run"):
            yield self.state()

    def state(self) -> StoreState:
        """Return the digest of every file under :data:`PINNED_TREES`.

        Returns
        -------
        StoreState
            One entry per file; a temporary file of a write in progress is not
            one, and there is none while :meth:`reading` holds the store.
        """
        files: dict[str, str] = {}
        for tree in PINNED_TREES:
            base = self.root / tree
            if not base.is_dir():
                continue
            for path in sorted(base.rglob("*")):
                if path.is_file() and path.suffix != ".tmp":
                    files[path.relative_to(self.root).as_posix()] = _sha256(path)
        return StoreState(files)

    def recover(self) -> list[Path]:
        """Finish or discard the transactions a previous run left behind.

        Returns
        -------
        list[Path]
            The staging directories that were dealt with, in name order.

        Raises
        ------
        StoreBusy
            If someone else holds the store: its pending work may be alive.
        RuntimeError
            If a committed transaction's staged file is gone and its target
            does not hold what was staged - a publication that cannot be proved.

        Notes
        -----
        Done when a repository is opened and before every transaction, always
        under the exclusive lock. A staging directory holding a manifest had
        decided to commit, so its moves are replayed; one without had not, so
        it is removed. Replaying is safe to repeat: a file already moved is no
        longer in the staging directory, and its target carries the digest the
        manifest recorded for it.
        """
        with self._lock.hold(fcntl.LOCK_EX, "recover interrupted transactions"):
            return self._recover()

    def _recover(self) -> list[Path]:
        """Recover pending transactions; the caller holds the exclusive lock."""
        pending = self.root / PENDING
        if not pending.is_dir():
            return []
        handled: list[Path] = []
        for staging in sorted(pending.iterdir()):
            if not staging.is_dir():
                continue
            handled.append(staging)
            manifest = staging / COMMIT_MANIFEST
            if not manifest.exists():
                shutil.rmtree(staging, ignore_errors=True)
                continue
            moves = json.loads(manifest.read_text(encoding="utf-8"))
            self._apply(
                staging,
                {
                    self.root / target: (Path(move["source"]), str(move["sha256"]))
                    for target, move in moves.items()
                },
            )
        return handled

    def _pending_root(self) -> Path:
        """Return the staging root, created if it is not there yet."""
        pending = self.root / PENDING
        pending.mkdir(parents=True, exist_ok=True)
        return pending

    def _commit(self, staging: Path, staged: Mapping[Path, Path]) -> None:
        """Publish a transaction's files, manifest first, then the moves."""
        if not staged:
            shutil.rmtree(staging, ignore_errors=True)
            return
        moves = {target: (source, _sha256(source)) for target, source in staged.items()}
        manifest = {
            str(target.relative_to(self.root)): {"source": str(source), "sha256": digest}
            for target, (source, digest) in moves.items()
        }
        _atomic_write(
            staging / COMMIT_MANIFEST,
            lambda handle: handle.write(json.dumps(manifest, indent=2).encode("utf-8")),
        )
        self._apply(staging, moves)

    def _apply(self, staging: Path, moves: Mapping[Path, tuple[Path, str]]) -> None:
        """Move every staged file onto its target, then drop the staging directory.

        Raises
        ------
        RuntimeError
            If a staged file is gone and its target does not carry its digest.
            An absent source used to be taken as "already moved" on trust, and
            a staging directory deleted under a live transaction then committed
            nothing without a word.
        """
        for target, (source, digest) in sorted(moves.items()):
            if not source.exists():
                if target.exists() and _sha256(target) == digest:
                    continue  # moved by an earlier pass of the same commit
                raise RuntimeError(
                    f"{target.relative_to(self.root)} was staged and is neither in "
                    f"{staging.name} nor published; this commit cannot be completed"
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, target)
        shutil.rmtree(staging, ignore_errors=True)

    def _append_rows(self, frame: pd.DataFrame, path: Path, schema: pa.Schema) -> None:
        """Append rows to a Parquet log without ever losing the existing ones.

        The file is read, extended and rewritten atomically: a crash leaves
        either the old log or the new one, never a truncated file. Inside a
        transaction it reads what that transaction has already staged, so two
        appends to one log do not undo each other.

        Parameters
        ----------
        frame : pd.DataFrame
            Rows to append.
        path : Path
            Log file; created by the first non-empty append.
        schema : pa.Schema
            Schema of the log.

        Raises
        ------
        ValueError
            If ``frame`` does not match ``schema``, even when it is empty.
        """
        missing = set(schema.names) - set(frame.columns)
        extra = set(frame.columns) - set(schema.names)
        if missing or extra:
            raise ValueError(f"Column mismatch: missing={sorted(missing)}, extra={sorted(extra)}")
        if frame.empty:
            return
        current = self._current(path)
        if current.exists():
            frame = pd.concat([pq.read_table(current).to_pandas(), frame], ignore_index=True)
        write_parquet_atomic(frame, self._target(path), schema)

    def _target(self, path: Path) -> Path:
        """Return where a write should actually land.

        Inside a transaction that is the staging copy of ``path``, recorded so
        the commit knows where to move it; outside one it is ``path`` itself.
        """
        if self._staged is None or self._staging is None:
            return path
        staged = self._staging / path.relative_to(self.root)
        self._staged[path] = staged
        return staged

    def _current(self, path: Path) -> Path:
        """Return the newest version of a file, this transaction's included.

        A read-modify-write - appending to a log, merging a series - has to see
        what the same transaction wrote a moment ago, or the second write would
        silently undo the first.
        """
        if self._staged is None:
            return path
        return self._staged.get(path, path)

    def _raw_path(self, instrument_id: str, source: str, fetch_id: str) -> Path:
        """Return ``raw/<source>/<instrument_id>/<fetch_id>.parquet``."""
        return self.root / "raw" / source / instrument_id / f"{fetch_id}.parquet"

    @_writes
    def save_raw(self, download: RawDownload) -> Path:
        """Persist one provider response, immutably.

        Parameters
        ----------
        download : RawDownload
            Response to archive.

        Returns
        -------
        Path
            File written.

        Raises
        ------
        FileExistsError
            If that ``fetch_id`` already exists. Raw is append-only: overwriting
            would destroy the evidence the layer exists to keep.

        Notes
        -----
        Exercice 3.3 (facile). Ecris aussi le manifeste JSON a cote : symbole
        demande, plage, version de la librairie, nombre de lignes. C'est ce qui
        rend un snapshot lisible trois ans plus tard.
        """
        retrieved = download.retrieved_at_utc
        if retrieved.tzinfo is None or retrieved.utcoffset() != timedelta(0):
            raise ValueError(f"retrieved_at_utc must be a UTC instant, got {retrieved!r}")
        data_path = self._raw_path(download.instrument_id, download.source, download.fetch_id)
        manifest_path = data_path.with_suffix(".json")
        if data_path.exists() or manifest_path.exists():
            raise FileExistsError(
                f"Raw fetch {download.fetch_id} already archived for "
                f"{download.instrument_id} from {download.source}"
            )
        manifest = {
            "instrument_id": download.instrument_id,
            "source": download.source,
            "fetch_id": download.fetch_id,
            "retrieved_at_utc": retrieved.astimezone(UTC).isoformat(),
            "row_count": len(download.frame),
            "columns": [str(column) for column in download.frame.columns],
            "request": dict(download.request),
        }
        # default=str: request values such as dates are archived as ISO strings.
        payload = json.dumps(manifest, indent=2, sort_keys=True, default=str) + "\n"
        # The index is kept: it is part of what the provider returned (Yahoo's ``Date``).
        table = pa.Table.from_pandas(download.frame)
        _atomic_write(data_path, lambda handle: pq.write_table(table, handle))
        # Manifest last: a fetch counts as archived only once its manifest exists.
        _atomic_write(manifest_path, lambda handle: handle.write(payload.encode("utf-8")))
        return data_path

    def load_raw(self, instrument_id: str, source: str, fetch_id: str) -> RawDownload:
        """Load one archived provider response.

        Parameters
        ----------
        instrument_id : str
            Instrument concerned.
        source : str
            Source identifier.
        fetch_id : str
            Fetch identifier.

        Returns
        -------
        RawDownload
            The archived response.

        Notes
        -----
        Exercice 3.4 (facile).
        """
        data_path = self._raw_path(instrument_id, source, fetch_id)
        manifest_path = data_path.with_suffix(".json")
        if not data_path.exists() or not manifest_path.exists():
            raise FileNotFoundError(
                f"Raw fetch {fetch_id} not archived for {instrument_id} from {source}"
            )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        frame = pq.read_table(data_path).to_pandas()
        # A plain datetime, like the one that was saved - not a pandas Timestamp.
        retrieved_at_utc = datetime.fromisoformat(manifest["retrieved_at_utc"]).astimezone(UTC)
        return RawDownload(
            instrument_id=manifest["instrument_id"],
            source=manifest["source"],
            fetch_id=manifest["fetch_id"],
            retrieved_at_utc=retrieved_at_utc,
            request=manifest["request"],
            frame=frame,
        )

    def list_raw_fetches(self, instrument_id: str, source: str) -> list[str]:
        """List the archived fetch identifiers, oldest first.

        Parameters
        ----------
        instrument_id : str
            Instrument concerned.
        source : str
            Source identifier.

        Returns
        -------
        list[str]
            Fetch identifiers in chronological order.

        Notes
        -----
        Exercice 3.5 (facile). L'ordre chronologique est ce qui rend la regle
        "premier arrive gagne" reproductible lors d'un rebuild.
        """
        list_path = self.root / "raw" / source / instrument_id
        if not list_path.is_dir():
            return []
        fetches: list[str] = []
        for entry in list_path.iterdir():
            # The manifest is written last: a .parquet without its .json is an
            # archive that was interrupted, and must not be replayed.
            if entry.is_file() and entry.suffix == ".json":
                fetches.append(entry.stem)
        return sorted(fetches)

    @_writes
    def save_bars(self, instrument_id: str, frame: pd.DataFrame) -> None:
        """Replace an instrument's clean bars.

        Parameters
        ----------
        instrument_id : str
            Instrument concerned.
        frame : pd.DataFrame
            Full canonical frame, chronologically sorted.

        Raises
        ------
        ValueError
            If ``frame`` does not match the bars schema, holds rows of another
            instrument, or is not sorted by ``session_date`` without duplicates.

        Notes
        -----
        Exercice 3.6 (facile). Un fichier par instrument : la mise a jour reste
        bon marche et le remplacement atomique trivial.
        """
        for field in ("instrument_id", "session_date"):
            if field not in frame.columns:
                raise ValueError(f"Missing column {field!r} in bars frame")
        if not (frame["instrument_id"] == instrument_id).all():
            raise ValueError(f"Bars frame for {instrument_id} holds rows of another instrument")
        if not (frame["session_date"].is_monotonic_increasing and frame["session_date"].is_unique):
            raise ValueError("Bars frame must be sorted by session_date, without duplicates")
        path = self.root / "clean" / "bars" / f"{instrument_id}.parquet"
        write_parquet_atomic(frame, self._target(path), BARS_SCHEMA)

    def load_bars(
        self, instrument_id: str, start: date | None = None, end: date | None = None
    ) -> pd.DataFrame:
        """Load an instrument's clean bars.

        Parameters
        ----------
        instrument_id : str
            Instrument concerned.
        start, end : date | None
            Inclusive bounds on ``session_date``; ``None`` means unbounded.

        Returns
        -------
        pd.DataFrame
            Canonical bars; empty frame with the right columns if none.

        Notes
        -----
        Exercice 3.7 (facile). Une frame vide **avec les bonnes colonnes** evite
        un ``KeyError`` a chaque cas limite en aval.

        Cette methode ne filtre **pas** sur la disponibilite : c'est le role du
        reader. Le repository ne connait que des fichiers.
        """
        path = self._current(self.root / "clean" / "bars" / f"{instrument_id}.parquet")
        if not path.exists():
            # Same columns and dtypes as a loaded file, just zero rows.
            return BARS_SCHEMA.empty_table().to_pandas()
        frame = pq.read_table(path).to_pandas()
        # session_date holds datetime.date objects: compare with dates, not Timestamps.
        if start is not None:
            frame = frame.loc[frame["session_date"] >= start]
        if end is not None:
            frame = frame.loc[frame["session_date"] <= end]
        return frame.reset_index(drop=True)

    @_writes
    def save_checked_bars(self, instrument_id: str, frame: pd.DataFrame) -> None:
        """Replace an instrument's cross-checked bars.

        Parameters
        ----------
        instrument_id : str
            Instrument concerned.
        frame : pd.DataFrame
            Full output of
            :func:`~quant_backtester.data.crosscheck.cross_check_bars`,
            chronologically sorted.

        Raises
        ------
        ValueError
            If ``frame`` does not match the checked bars schema, holds rows of
            another instrument, is not sorted by ``session_date`` without
            duplicates, or carries an unknown ``check_status``.
        """
        for field in ("instrument_id", "session_date", "check_status"):
            if field not in frame.columns:
                raise ValueError(f"Missing column {field!r} in checked bars frame")
        if not (frame["instrument_id"] == instrument_id).all():
            raise ValueError(
                f"Checked bars frame for {instrument_id} holds rows of another instrument"
            )
        if not (frame["session_date"].is_monotonic_increasing and frame["session_date"].is_unique):
            raise ValueError(
                "Checked bars frame must be sorted by session_date, without duplicates"
            )
        unknown = sorted(set(frame["check_status"]) - {status.value for status in CheckStatus})
        if unknown:
            raise ValueError(f"Unknown check_status value(s): {', '.join(map(str, unknown))}")
        path = self.root / "clean" / "checked_bars" / f"{instrument_id}.parquet"
        write_parquet_atomic(frame, self._target(path), CHECKED_BARS_SCHEMA)

    @_writes
    def save_check_bars(self, instrument_id: str, source_id: str, frame: pd.DataFrame) -> None:
        """Replace one check source's canonical bars for an instrument.

        Parameters
        ----------
        instrument_id : str
            Instrument concerned.
        source_id : str
            Check source the rows come from.
        frame : pd.DataFrame
            Full canonical frame, chronologically sorted.

        Raises
        ------
        ValueError
            If ``frame`` does not match the bars schema, holds rows of another
            instrument or another source, or is not sorted by ``session_date``
            without duplicates.

        Notes
        -----
        A second opinion is a series, not a passing remark. Kept only inside the
        fetch that downloaded it, it escaped the revision policy that governs
        every other stored value: a provider restating an old session changed a
        verdict on the spot, while a replay of the same archive kept the first
        value and rebuilt a different one. Stored, it obeys the same rule as the
        primary series and the two paths agree by construction.
        """
        for field in ("instrument_id", "session_date", "source"):
            if field not in frame.columns:
                raise ValueError(f"Missing column {field!r} in check bars frame")
        if not (frame["instrument_id"] == instrument_id).all():
            raise ValueError(
                f"Check bars frame for {instrument_id} holds rows of another instrument"
            )
        if not (frame["source"] == source_id).all():
            raise ValueError(f"Check bars frame for {source_id} holds rows of another source")
        if not (frame["session_date"].is_monotonic_increasing and frame["session_date"].is_unique):
            raise ValueError("Check bars frame must be sorted by session_date, without duplicates")
        write_parquet_atomic(
            frame, self._target(self._check_bars_path(instrument_id, source_id)), BARS_SCHEMA
        )

    def load_check_bars(self, instrument_id: str, source_id: str) -> pd.DataFrame:
        """Load one check source's canonical bars for an instrument.

        Parameters
        ----------
        instrument_id : str
            Instrument concerned.
        source_id : str
            Check source concerned.

        Returns
        -------
        pd.DataFrame
            Its canonical bars; an empty frame with the right columns if it has
            never served any.
        """
        return self._load(
            self._current(self._check_bars_path(instrument_id, source_id)), BARS_SCHEMA
        )

    def _check_bars_path(self, instrument_id: str, source_id: str) -> Path:
        """Return where one check source's bars for one instrument live."""
        return self.root / "clean" / "check_bars" / source_id / f"{instrument_id}.parquet"

    def load_checked_bars(
        self, instrument_id: str, start: date | None = None, end: date | None = None
    ) -> pd.DataFrame:
        """Load an instrument's cross-checked bars.

        Parameters
        ----------
        instrument_id : str
            Instrument concerned.
        start, end : date | None
            Inclusive bounds on ``session_date``; ``None`` means unbounded.

        Returns
        -------
        pd.DataFrame
            Checked bars, every status included; empty frame with the right
            columns if none. Choosing which statuses to trust is the caller's
            decision, not the repository's.
        """
        path = self._current(self.root / "clean" / "checked_bars" / f"{instrument_id}.parquet")
        frame = self._load(path, CHECKED_BARS_SCHEMA)
        # session_date holds datetime.date objects: compare with dates, not Timestamps.
        if start is not None:
            frame = frame.loc[frame["session_date"] >= start]
        if end is not None:
            frame = frame.loc[frame["session_date"] <= end]
        return frame.reset_index(drop=True)

    @_writes
    def save_levels(self, instrument_id: str, frame: pd.DataFrame) -> None:
        """Replace an instrument's clean levels.

        Parameters
        ----------
        instrument_id : str
            Instrument concerned.
        frame : pd.DataFrame
            Full canonical frame.

        Raises
        ------
        ValueError
            If ``frame`` does not match the levels schema, holds rows of another
            instrument, or is not sorted by ``observation_date`` without
            duplicates.

        Notes
        -----
        Exercice 3.8 (facile).
        """
        for field in ("instrument_id", "observation_date"):
            if field not in frame.columns:
                raise ValueError(f"Missing column {field!r} in levels frame")
        if not (frame["instrument_id"] == instrument_id).all():
            raise ValueError(f"Levels frame for {instrument_id} holds rows of another instrument")
        dates = frame["observation_date"]
        if not (dates.is_monotonic_increasing and dates.is_unique):
            raise ValueError("Levels frame must be sorted by observation_date, without duplicates")
        replace_path = self.root / "clean" / "levels" / f"{instrument_id}.parquet"
        write_parquet_atomic(frame, self._target(replace_path), LEVELS_SCHEMA)

    @_writes
    def save_vintages(self, instrument_id: str, frame: pd.DataFrame) -> None:
        """Replace an instrument's vintage archive.

        Parameters
        ----------
        instrument_id : str
            Instrument concerned.
        frame : pd.DataFrame
            Full canonical frame, sorted by ``observation_date`` then
            ``vintage_date``, with no pair repeated.

        Raises
        ------
        ValueError
            If a row belongs to another instrument, if the frame is not sorted,
            or if one pair appears twice - two values for one observation as of
            one day is a file that cannot say what was known.
        """
        for field in ("instrument_id", "observation_date", "vintage_date"):
            if field not in frame.columns:
                raise ValueError(f"Missing column {field!r} in vintages frame")
        if not (frame["instrument_id"] == instrument_id).all():
            raise ValueError(f"Vintages frame for {instrument_id} holds rows of another instrument")
        keys = list(zip(frame["observation_date"], frame["vintage_date"], strict=True))
        if keys != sorted(keys):
            raise ValueError("Vintages frame must be sorted by observation_date, then vintage_date")
        if len(set(keys)) != len(keys):
            raise ValueError("Vintages frame holds one observation twice in the same vintage")
        path = self.root / "clean" / "vintages" / f"{instrument_id}.parquet"
        write_parquet_atomic(frame, self._target(path), VINTAGES_SCHEMA)

    def load_vintages(self, instrument_id: str) -> pd.DataFrame:
        """Load an instrument's vintage archive.

        Parameters
        ----------
        instrument_id : str
            Instrument concerned.

        Returns
        -------
        pd.DataFrame
            Every value of every stored vintage, sorted; an empty frame with
            the right columns when the instrument has none.
        """
        path = self._current(self.root / "clean" / "vintages" / f"{instrument_id}.parquet")
        return self._load(path, VINTAGES_SCHEMA)

    def load_levels(
        self, instrument_id: str, start: date | None = None, end: date | None = None
    ) -> pd.DataFrame:
        """Load an instrument's clean levels.

        Parameters
        ----------
        instrument_id : str
            Instrument concerned.
        start, end : date | None
            Inclusive bounds on ``observation_date``.

        Returns
        -------
        pd.DataFrame
            Canonical levels; empty frame with the right columns if none.

        Notes
        -----
        Exercice 3.9 (facile).
        """
        path = self._current(self.root / "clean" / "levels" / f"{instrument_id}.parquet")
        frame = self._load(path, LEVELS_SCHEMA)
        # observation_date holds datetime.date objects: compare with dates, not Timestamps.
        if start is not None:
            frame = frame.loc[frame["observation_date"] >= start]
        if end is not None:
            frame = frame.loc[frame["observation_date"] <= end]
        return frame.reset_index(drop=True)

    @_writes
    def save_corporate_actions(self, frame: pd.DataFrame) -> None:
        """Replace the corporate actions table.

        Parameters
        ----------
        frame : pd.DataFrame
            Full canonical frame, all instruments.

        Raises
        ------
        ValueError
            If ``frame`` does not match the corporate actions schema.

        Notes
        -----
        Exercice 3.10 (facile). Table unique : elle est minuscule et toujours lue
        en entier.
        """
        path = self.root / "clean" / "corporate_actions.parquet"
        write_parquet_atomic(frame, self._target(path), CORPORATE_ACTIONS_SCHEMA)

    def load_corporate_actions(self, instrument_id: str | None = None) -> pd.DataFrame:
        """Load corporate actions.

        Parameters
        ----------
        instrument_id : str | None
            Restrict to one instrument; ``None`` returns all.

        Returns
        -------
        pd.DataFrame
            Canonical corporate actions; empty frame with the right columns if
            none.

        Notes
        -----
        Exercice 3.11 (facile).
        """
        path = self._current(self.root / "clean" / "corporate_actions.parquet")
        return _only_instrument(self._load(path, CORPORATE_ACTIONS_SCHEMA), instrument_id)

    @_writes
    def append_revisions(self, frame: pd.DataFrame) -> None:
        """Append detected revisions to the detection log.

        Parameters
        ----------
        frame : pd.DataFrame
            Rows matching the revisions schema.

        Raises
        ------
        ValueError
            If ``frame`` does not match the revisions schema.

        Notes
        -----
        Exercice 3.12 (facile). Append, jamais remplacement : c'est un journal.

        An empty frame leaves the log untouched.
        """
        self._append_rows(frame, self.root / "clean" / "revisions.parquet", REVISIONS_SCHEMA)

    @_writes
    def mark_fetches_applied(
        self, instrument_id: str, fetches: Sequence[tuple[str, str]], applied_at_utc: datetime
    ) -> None:
        """Record that these fetches completed their promotion.

        Parameters
        ----------
        instrument_id : str
            Instrument concerned.
        fetches : Sequence[tuple[str, str]]
            ``(source, fetch_id)`` pairs the promotion consumed.
        applied_at_utc : datetime
            Timezone-aware UTC instant, the fetch's own ``retrieved_at_utc``.

        Raises
        ------
        ValueError
            If ``applied_at_utc`` is not a UTC instant.
        """
        if applied_at_utc.tzinfo is None or applied_at_utc.utcoffset() != timedelta(0):
            raise ValueError(f"applied_at_utc must be a UTC instant, got {applied_at_utc!r}")
        if not fetches:
            return
        frame = pd.DataFrame(
            {
                "instrument_id": [instrument_id] * len(fetches),
                "source": [source for source, _ in fetches],
                "fetch_id": [fetch_id for _, fetch_id in fetches],
                "applied_at_utc": pd.Series(
                    [applied_at_utc] * len(fetches), dtype="datetime64[us, UTC]"
                ),
            }
        )
        self._append_rows(frame, self._applied_fetches_path, APPLIED_FETCHES_SCHEMA)

    def load_applied_fetches(self, instrument_id: str) -> set[tuple[str, str]]:
        """Return the ``(source, fetch_id)`` pairs whose promotion completed.

        Parameters
        ----------
        instrument_id : str
            Instrument concerned.

        Returns
        -------
        set[tuple[str, str]]
            Empty when nothing was ever recorded for it.
        """
        frame = self._load(self._current(self._applied_fetches_path), APPLIED_FETCHES_SCHEMA)
        mine = frame.loc[frame["instrument_id"] == instrument_id]
        return {
            (str(source), str(fetch))
            for source, fetch in zip(mine["source"], mine["fetch_id"], strict=True)
        }

    @property
    def _applied_fetches_path(self) -> Path:
        """Return where the journal of applied fetches lives."""
        return self.root / "clean" / "applied_fetches.parquet"

    def load_revisions(self, instrument_id: str | None = None) -> pd.DataFrame:
        """Load the detection log.

        Parameters
        ----------
        instrument_id : str | None
            Restrict to one instrument; ``None`` returns all.

        Returns
        -------
        pd.DataFrame
            Detected revisions, in the order they were appended; empty frame
            with the right columns if none.

        Notes
        -----
        Exercice 3.13 (facile).
        """
        path = self._current(self.root / "clean" / "revisions.parquet")
        return _only_instrument(self._load(path, REVISIONS_SCHEMA), instrument_id)

    @_writes
    def append_validation_log(
        self, reports: Sequence[ValidationReport], checked_at_utc: datetime
    ) -> None:
        """Persist validation issues.

        Parameters
        ----------
        reports : Sequence[ValidationReport]
            Reports to flatten into the log.
        checked_at_utc : datetime
            Timezone-aware UTC instant the validation ran, typically the
            ``retrieved_at_utc`` of the download checked. Passed in so the
            repository never reads the clock.

        Raises
        ------
        ValueError
            If ``checked_at_utc`` is naive or not UTC.

        Notes
        -----
        Exercice 3.14 (facile). Les warnings comptent autant que les erreurs :
        un warning affiche sur stdout est un warning perdu.

        One row per issue, warnings and errors alike. ``ValidationIssue.context``
        has no column in the log schema and is not persisted.
        """
        if checked_at_utc.tzinfo is None or checked_at_utc.utcoffset() != timedelta(0):
            raise ValueError(f"checked_at_utc must be a UTC instant, got {checked_at_utc!r}")
        rows = [
            {
                "instrument_id": issue.instrument_id,
                "checked_at_utc": checked_at_utc,
                "code": issue.code,
                "severity": issue.severity.value,
                "observation_date": issue.observation_date,
                "message": issue.message,
            }
            for report in reports
            for issue in report.issues
        ]
        frame = pd.DataFrame(rows, columns=VALIDATION_LOG_SCHEMA.names)
        frame["checked_at_utc"] = pd.Series(
            [checked_at_utc] * len(rows), index=frame.index, dtype="datetime64[us, UTC]"
        )
        self._append_rows(
            frame, self.root / "validation" / "validation_log.parquet", VALIDATION_LOG_SCHEMA
        )

    def exists(self, instrument_id: str) -> bool:
        """Return whether an instrument has any clean data.

        Parameters
        ----------
        instrument_id : str
            Instrument concerned.

        Returns
        -------
        bool
            ``True`` if a clean bars, levels or vintages file exists.

        Notes
        -----
        Exercice 3.15 (facile).
        """
        clean = self.root / "clean"
        return any(
            self._current(clean / table / f"{instrument_id}.parquet").exists()
            for table in ("bars", "levels", "vintages")
        )

    def first_date(self, instrument_id: str) -> date | None:
        """Return the earliest stored observation date.

        Parameters
        ----------
        instrument_id : str
            Instrument concerned.

        Returns
        -------
        date | None
            ``None`` if the instrument has no clean data.

        Notes
        -----
        Exercice 3.16 (facile).
        """
        dates = self._stored_dates(instrument_id)
        return min(dates) if dates else None

    def last_date(self, instrument_id: str) -> date | None:
        """Return the latest stored observation date.

        Parameters
        ----------
        instrument_id : str
            Instrument concerned.

        Returns
        -------
        date | None
            ``None`` if the instrument has no clean data.

        Notes
        -----
        Exercice 3.17 (facile). C'est le point de depart de ``update()``.
        """
        dates = self._stored_dates(instrument_id)
        return max(dates) if dates else None

    def _stored_dates(self, instrument_id: str) -> list[date]:
        """Return the dates stored for an instrument, from bars, levels or vintages.

        Parameters
        ----------
        instrument_id : str
            Instrument concerned.

        Returns
        -------
        list[date]
            ``session_date`` of its bars, or ``observation_date`` of its levels
            or of its vintage archive - one per row, so an observation restated
            in several vintages appears once per vintage; empty if it has none.
            Leaving the vintages out made an archived series look empty (audit
            A10).
        """
        clean = self.root / "clean"
        for path, column in (
            (self._current(clean / "bars" / f"{instrument_id}.parquet"), "session_date"),
            (self._current(clean / "levels" / f"{instrument_id}.parquet"), "observation_date"),
            (self._current(clean / "vintages" / f"{instrument_id}.parquet"), "observation_date"),
        ):
            if path.exists():
                return pq.read_table(path, columns=[column]).column(column).to_pylist()
        return []


def _load_or_empty(path: Path, schema: pa.Schema) -> pd.DataFrame:
    """Read a Parquet file, or return zero rows with the schema's columns.

    Parameters
    ----------
    path : Path
        File to read.
    schema : pa.Schema
        Schema of the file, used for the empty frame.

    Returns
    -------
    pd.DataFrame
        Stored rows; an absent file gives the same columns and dtypes, no rows.
    """
    if not path.exists():
        return schema.empty_table().to_pandas()
    return pq.read_table(path).to_pandas()


def _only_instrument(frame: pd.DataFrame, instrument_id: str | None) -> pd.DataFrame:
    """Keep the rows of one instrument, or every row for ``None``.

    Parameters
    ----------
    frame : pd.DataFrame
        Rows with an ``instrument_id`` column.
    instrument_id : str | None
        Instrument to keep.

    Returns
    -------
    pd.DataFrame
        Matching rows, index restarting at zero.
    """
    if instrument_id is not None:
        frame = frame.loc[frame["instrument_id"] == instrument_id]
    return frame.reset_index(drop=True)
