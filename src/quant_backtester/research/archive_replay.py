"""Reading a retrieval archive back: a file is used only if it is the one that was recorded.

A study on archived research series - the Ken French tables, the Pink Sheet,
the Nasdaq Composite - is frozen before it is run, and its inputs with it:
the retrieval writes each file beside a coverage record carrying its SHA-256,
and the run replays the files rather than fetching them again. A file whose
bytes are not the recorded ones is another input, so it is refused here, in
one place, for every study that replays an archive (SA16's long history and
its levered variant, SA18).

Nothing here performs network I/O, and no instant here is an availability
instant: the retrieval time of a record is provenance. The series are
restated research series, not point-in-time vintages.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any

from quant_backtester.data.sources.ken_french import (
    KenFrenchDataset,
    KenFrenchSource,
    MonthlyReturns,
    normalize_monthly_returns,
)


def record_month(value: str) -> date:
    """Return the first day of a month a coverage record writes as ``YYYYMM``.

    Parameters
    ----------
    value : str
        Six digits: the year, then the month.

    Returns
    -------
    date
        The first day of that month.

    Raises
    ------
    ValueError
        If ``value`` is not six digits naming a month.
    """
    if len(value) != 6 or not (value.isascii() and value.isdigit()):
        raise ValueError(f"a record month is written YYYYMM, got {value!r}")
    return date(int(value[:4]), int(value[4:]), 1)


def checked_bytes(archive: Path, recorded: Mapping[str, Mapping[str, Any]], name: str) -> bytes:
    """Return an archived file's bytes, refused unless they hash to its coverage record.

    Parameters
    ----------
    archive : Path
        The folder the retrieval archived its files in.
    recorded : Mapping[str, Mapping[str, Any]]
        The coverage records of the retrieval, by file name; each carries
        the ``sha256`` of its file.
    name : str
        The file to read.

    Returns
    -------
    bytes
        The file, byte for byte as it was retrieved.

    Raises
    ------
    ValueError
        If the coverage records do not name the file, or its bytes do not
        hash to the ``sha256`` recorded for it.
    FileNotFoundError
        If the archive does not hold the file.
    """
    if name not in recorded:
        raise ValueError(f"{name}: the coverage records do not name this file")
    payload = (archive / name).read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if digest != recorded[name]["sha256"]:
        raise ValueError(f"{name}: archived bytes hash to {digest}, not to the record")
    return payload


def replay_french(
    archive: Path, recorded: Mapping[str, Mapping[str, Any]], dataset: KenFrenchDataset
) -> MonthlyReturns:
    """Replay an archived Ken French file over the months its coverage record states.

    Parameters
    ----------
    archive, recorded
        As :func:`checked_bytes`. The record of a Ken French file also
        carries ``first_month`` and ``last_month`` (``YYYYMM``) and
        ``retrieved_at_utc`` (ISO, aware UTC).
    dataset : KenFrenchDataset
        The dataset; its file is ``<dataset value>.zip``.

    Returns
    -------
    MonthlyReturns
        The table from the record's first month to its last, both included,
        stamped with the record's retrieval instant.

    Raises
    ------
    ValueError
        As :func:`checked_bytes`, before anything else of the record is read;
        then if the record's months are not written ``YYYYMM`` or its
        retrieval instant carries no timezone.
    FileNotFoundError
        If the archive does not hold the file.
    ProviderResponseError
        If the adapter refuses the file or the range.

    Notes
    -----
    The bytes are hashed once, by :func:`checked_bytes`, and then parsed by
    the same adapter that downloaded them, as if just served.
    """
    name = f"{dataset.value}.zip"
    payload = checked_bytes(archive, recorded, name)
    entry = recorded[name]
    retrieved_at_utc = datetime.fromisoformat(entry["retrieved_at_utc"])
    if retrieved_at_utc.tzinfo is None:
        raise ValueError(f"{name}: the recorded retrieval instant carries no timezone")
    start, end = record_month(entry["first_month"]), record_month(entry["last_month"])
    source = KenFrenchSource(clock=lambda: retrieved_at_utc, fetch_bytes=lambda _url: payload)
    return normalize_monthly_returns(source.download(dataset, start, end))
