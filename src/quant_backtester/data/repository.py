"""Persistence: the only module that knows Parquet exists.

Layout under the market data root::

    metadata/
        instruments.toml            committed
        accepted_revisions.toml     committed - it changes past results
        calendars/*.toml            committed
    raw/<source>/<instrument_id>/<fetch_id>.parquet   immutable, append-only
    raw/<source>/<instrument_id>/<fetch_id>.json      request manifest
    clean/bars/<instrument_id>.parquet
    clean/checked_bars/<instrument_id>.parquet        bars cross-checked across sources
    clean/levels/<instrument_id>.parquet
    clean/corporate_actions.parquet
    clean/revisions.parquet
    validation/validation_log.parquet

``raw/`` is written once and never touched again: one file per fetch, named by
the fetch instant. That is what answers "what did Yahoo actually give us on
10 September?" and what lets vintages be reconstructed later.

``clean/`` is entirely derived and disposable: it is a pure function of the raw
snapshots, the accepted revisions, the calendars and the normalizer version.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import BinaryIO

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from quant_backtester.data.schemas import (
    BARS_SCHEMA,
    CHECKED_BARS_SCHEMA,
    CORPORATE_ACTIONS_SCHEMA,
    LEVELS_SCHEMA,
    REVISIONS_SCHEMA,
    VALIDATION_LOG_SCHEMA,
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


class MarketDataRepository:
    """Read and write the market data tree.

    Parameters
    ----------
    root : Path
        Market data root, i.e. the directory holding ``metadata/``, ``raw/``,
        ``clean/`` and ``validation/``. Passed in rather than read from a global
        so tests can point at a temporary directory.
    """

    def __init__(self, root: Path) -> None:
        if not root.is_dir():
            raise FileNotFoundError(f"Market data root {root} does not exist")
        self.root = root

    def _raw_path(self, instrument_id: str, source: str, fetch_id: str) -> Path:
        """Return ``raw/<source>/<instrument_id>/<fetch_id>.parquet``."""
        return self.root / "raw" / source / instrument_id / f"{fetch_id}.parquet"

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
        write_parquet_atomic(frame, path, BARS_SCHEMA)

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
        path = self.root / "clean" / "bars" / f"{instrument_id}.parquet"
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
        write_parquet_atomic(frame, path, CHECKED_BARS_SCHEMA)

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
        path = self.root / "clean" / "checked_bars" / f"{instrument_id}.parquet"
        frame = _load_or_empty(path, CHECKED_BARS_SCHEMA)
        # session_date holds datetime.date objects: compare with dates, not Timestamps.
        if start is not None:
            frame = frame.loc[frame["session_date"] >= start]
        if end is not None:
            frame = frame.loc[frame["session_date"] <= end]
        return frame.reset_index(drop=True)

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
        write_parquet_atomic(frame, replace_path, LEVELS_SCHEMA)

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
        path = self.root / "clean" / "levels" / f"{instrument_id}.parquet"
        frame = _load_or_empty(path, LEVELS_SCHEMA)
        # observation_date holds datetime.date objects: compare with dates, not Timestamps.
        if start is not None:
            frame = frame.loc[frame["observation_date"] >= start]
        if end is not None:
            frame = frame.loc[frame["observation_date"] <= end]
        return frame.reset_index(drop=True)

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
        write_parquet_atomic(frame, path, CORPORATE_ACTIONS_SCHEMA)

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
        path = self.root / "clean" / "corporate_actions.parquet"
        return _only_instrument(_load_or_empty(path, CORPORATE_ACTIONS_SCHEMA), instrument_id)

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
        _append_rows(frame, self.root / "clean" / "revisions.parquet", REVISIONS_SCHEMA)

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
        path = self.root / "clean" / "revisions.parquet"
        return _only_instrument(_load_or_empty(path, REVISIONS_SCHEMA), instrument_id)

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
        _append_rows(
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
            ``True`` if a clean bars or levels file exists.

        Notes
        -----
        Exercice 3.15 (facile).
        """
        clean = self.root / "clean"
        bars = clean / "bars" / f"{instrument_id}.parquet"
        levels = clean / "levels" / f"{instrument_id}.parquet"
        return bars.exists() or levels.exists()

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
        """Return the dates stored for an instrument, bars first, then levels.

        Parameters
        ----------
        instrument_id : str
            Instrument concerned.

        Returns
        -------
        list[date]
            ``session_date`` of its bars or ``observation_date`` of its levels;
            empty if it has neither.
        """
        clean = self.root / "clean"
        for path, column in (
            (clean / "bars" / f"{instrument_id}.parquet", "session_date"),
            (clean / "levels" / f"{instrument_id}.parquet", "observation_date"),
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


def _append_rows(frame: pd.DataFrame, path: Path, schema: pa.Schema) -> None:
    """Append rows to a Parquet log without ever losing the existing ones.

    The file is read, extended and rewritten atomically: a crash leaves either
    the old log or the new one, never a truncated file.

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
    if path.exists():
        frame = pd.concat([pq.read_table(path).to_pandas(), frame], ignore_index=True)
    write_parquet_atomic(frame, path, schema)
