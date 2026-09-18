"""Revision handling: detection is not decision.

When a provider returns a different value for a date we already stored, two
things must happen, and they must not be confused:

**Detection** is mechanical and goes to ``clean/revisions.parquet``. It says the
provider changed its mind.

**Decision** is ours and lives in ``metadata/accepted_revisions.toml``, in git.
Accepting a revision changes results that were already produced, so it belongs in
a diff someone reviews - not in a data file nobody reads.

Default policy: the canonical history is stable. An unaccepted revision is
logged and ignored. This is what stops the same backtest from quietly printing a
different number three weeks later.
"""

from __future__ import annotations

import math
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass, fields
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from quant_backtester.data.schemas import REVISIONS_SCHEMA


@dataclass(frozen=True, slots=True)
class AcceptedRevision:
    """One reviewed decision to let a provider correction through.

    Attributes
    ----------
    instrument_id : str
        Instrument concerned.
    table : str
        ``"bars"`` or ``"levels"``.
    observation_date : date
        Row concerned.
    field : str
        Column concerned, e.g. ``"close"``.
    reason : str
        Why it was accepted. Required: a decision without a reason cannot be
        re-examined later.
    """

    instrument_id: str
    table: str
    observation_date: date
    field: str
    reason: str


REVISION_TABLES = frozenset({"bars", "levels"})
"""Tables a revision can be accepted for."""

REVISION_KEYS = frozenset(field.name for field in fields(AcceptedRevision))
"""Keys of a ``[[revision]]`` table, all required.

Derived from the dataclass, like the instrument loader's keys: a field added to
:class:`AcceptedRevision` is accepted by the loader the same day.
"""


class AcceptedRevisions:
    """The set of revisions we have explicitly agreed to apply.

    Parameters
    ----------
    revisions : Sequence[AcceptedRevision]
        Reviewed decisions. Empty is valid and the normal state: nothing has
        been accepted yet, so the history stays exactly as first stored.

    Raises
    ------
    ValueError
        If a decision names a table other than ``bars`` or ``levels``, has an
        observation date that is not a plain date, has a blank reason, or
        repeats the key of another decision: two reviews of the same correction
        cannot both be the one that was made.
    """

    def __init__(self, revisions: Sequence[AcceptedRevision]) -> None:
        keys: set[tuple[str, str, date, str]] = set()
        for revision in revisions:
            label = (
                f"Accepted revision of {revision.instrument_id} {revision.table}."
                f"{revision.field} on {revision.observation_date}"
            )
            if revision.table not in REVISION_TABLES:
                raise ValueError(f"{label}: table must be one of {sorted(REVISION_TABLES)}")
            observation_date: object = revision.observation_date
            if isinstance(observation_date, datetime) or not isinstance(observation_date, date):
                raise ValueError(f"{label}: observation_date must be a plain date")
            if not revision.reason.strip():
                raise ValueError(f"{label}: a reason is required")
            key = (
                revision.instrument_id,
                revision.table,
                revision.observation_date,
                revision.field,
            )
            if key in keys:
                raise ValueError(f"{label}: accepted more than once")
            keys.add(key)
        # A tuple and a frozenset: the caller's list can change, the decisions cannot.
        self._revisions = tuple(revisions)
        self._keys = frozenset(keys)

    @classmethod
    def from_toml(cls, path: Path) -> AcceptedRevisions:
        """Load decisions from the committed TOML file.

        Parameters
        ----------
        path : Path
            File to read; a missing file means "nothing accepted yet".

        Returns
        -------
        AcceptedRevisions
            Loaded decisions.

        Raises
        ------
        ValueError
            If ``path`` exists but is not a file, the file holds a table other
            than ``[[revision]]``, an entry has an unknown or missing key or an
            observation date that is not a bare TOML date, or a decision is
            invalid (see the class).

        Notes
        -----
        Exercice 7.2 (facile).

        Entries are ``[[revision]]`` tables, the shape the committed file
        documents. The date is a bare TOML date (``observation_date =
        2026-09-10``), which ``tomllib`` already returns as a ``date``; a quoted
        string or a datetime is refused rather than guessed at.
        """
        if not path.exists():
            return cls([])
        if not path.is_file():
            raise ValueError(f"Accepted revisions path is not a file: {path}")
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
        unknown_tables = sorted(set(raw) - {"revision"})
        if unknown_tables:
            raise ValueError(f"{path} has unknown table(s): {', '.join(unknown_tables)}")
        entries = raw.get("revision", [])
        if not isinstance(entries, list):
            raise ValueError(f"{path}: revision must be an array of [[revision]] tables")
        revisions: list[AcceptedRevision] = []
        for position, entry in enumerate(entries):
            context = f"{path} revision[{position}]"
            if not isinstance(entry, dict):
                raise ValueError(f"{context} must be a table")
            unknown = sorted(set(entry) - REVISION_KEYS)
            missing = sorted(REVISION_KEYS - set(entry))
            if unknown or missing:
                raise ValueError(f"{context}: unknown key(s) {unknown}, missing key(s) {missing}")
            observation_date = entry["observation_date"]
            if isinstance(observation_date, datetime) or not isinstance(observation_date, date):
                raise ValueError(
                    f"{context}: observation_date = {observation_date!r}; "
                    "expected a bare date such as 2026-09-10"
                )
            revisions.append(
                AcceptedRevision(
                    instrument_id=entry["instrument_id"],
                    table=entry["table"],
                    observation_date=observation_date,
                    field=entry["field"],
                    reason=entry["reason"],
                )
            )
        try:
            return cls(revisions)
        except ValueError as exc:
            raise ValueError(f"{path}: {exc}") from None

    def is_accepted(
        self, instrument_id: str, table: str, observation_date: date, field: str
    ) -> bool:
        """Return whether one specific correction was approved.

        Parameters
        ----------
        instrument_id : str
            Instrument concerned.
        table : str
            ``"bars"`` or ``"levels"``.
        observation_date : date
            Row concerned.
        field : str
            Column concerned.

        Returns
        -------
        bool
            ``True`` when the correction may be applied.

        Notes
        -----
        Exercice 7.3 (facile).

        All four parts must match exactly. Accepting the close of a session does
        not accept its open, and a ``datetime`` never equals the ``date`` of a
        decision.
        """
        return (instrument_id, table, observation_date, field) in self._keys


def _rows_by_date(frame: pd.DataFrame, key_column: str, side: str) -> dict[date, dict[str, Any]]:
    """Index one side's rows by date, refusing anything that makes a row ambiguous.

    Parameters
    ----------
    frame : pd.DataFrame
        Canonical rows of one instrument, as stored or as refetched.
    key_column : str
        Date column identifying a row: ``"session_date"`` or
        ``"observation_date"``.
    side : str
        ``"stored"`` or ``"incoming"``, named in the error messages.

    Returns
    -------
    dict[date, dict[str, Any]]
        One row per date, in the order the frame holds them.

    Raises
    ------
    ValueError
        If ``key_column`` is absent, a date appears twice - which of the two
        rows holds the value we compare against has no answer - or the rows do
        not all belong to one instrument, which would compare two unrelated
        series and report every difference between them as a revision.
    """
    if key_column not in frame.columns:
        raise ValueError(f"The {side} rows have no {key_column} column")
    by_date: dict[date, dict[str, Any]] = {}
    instrument_id: str | None = None
    for record in frame.to_dict("records"):
        row = {str(column): value for column, value in record.items()}
        if instrument_id is None:
            instrument_id = str(row["instrument_id"])
        elif str(row["instrument_id"]) != instrument_id:
            raise ValueError(
                f"The {side} rows mix instruments {instrument_id} and {row['instrument_id']}"
            )
        observation_date: date = row[key_column]
        if observation_date in by_date:
            raise ValueError(f"The {side} rows repeat {observation_date}")
        by_date[observation_date] = row
    return by_date


def _instrument_of(rows: dict[date, dict[str, Any]]) -> str | None:
    """Return the instrument indexed rows describe, or ``None`` when there are none.

    Parameters
    ----------
    rows : dict[date, dict[str, Any]]
        Rows of one side, already checked to hold a single instrument.

    Returns
    -------
    str | None
        The instrument identifier; ``None`` for an empty side, which contradicts
        nothing.
    """
    for row in rows.values():
        return str(row["instrument_id"])
    return None


def _shared_instrument(
    stored_rows: dict[date, dict[str, Any]], incoming_rows: dict[date, dict[str, Any]]
) -> str | None:
    """Return the instrument both sides describe, refusing a pair that disagrees.

    Parameters
    ----------
    stored_rows, incoming_rows : dict[date, dict[str, Any]]
        Indexed rows of each side.

    Returns
    -------
    str | None
        The instrument identifier; ``None`` only when both sides are empty.

    Raises
    ------
    ValueError
        If the two sides name different instruments: comparing one series
        against another reports every difference between them as a revision.
    """
    stored = _instrument_of(stored_rows)
    incoming = _instrument_of(incoming_rows)
    if stored is not None and incoming is not None and stored != incoming:
        raise ValueError(
            f"Stored rows of {stored} cannot be compared with incoming rows of {incoming}"
        )
    return stored if stored is not None else incoming


def _has_changed(old: float, new: float, tolerance: float) -> bool:
    """Return whether a stored value and an incoming one differ materially.

    Parameters
    ----------
    old, new : float
        One field of one date, as stored and as refetched. ``NaN`` means the
        provider published nothing for it.
    tolerance : float
        Largest absolute difference that still counts as unchanged.

    Returns
    -------
    bool
        ``True`` when the values differ by strictly more than ``tolerance``, and
        whenever exactly one of them is missing: a value appearing or vanishing
        changes a past result exactly as a value moving does. Missing on both
        sides is not a change.

    Notes
    -----
    Same convention as :func:`quant_backtester.data.crosscheck.relative_difference`:
    both missing agree, one missing never does.
    """
    old_missing, new_missing = math.isnan(old), math.isnan(new)
    if old_missing and new_missing:
        return False
    if old_missing or new_missing:
        return True
    return abs(old - new) > tolerance


def detect_revisions(
    existing: pd.DataFrame,
    incoming: pd.DataFrame,
    *,
    table: str,
    key_column: str,
    value_columns: Sequence[str],
    new_fetch_id: str,
    detected_at_utc: datetime,
    tolerance: float = 0.0,
) -> pd.DataFrame:
    """Compare overlapping rows and report every changed value.

    Parameters
    ----------
    existing : pd.DataFrame
        Rows already stored in the clean layer.
    incoming : pd.DataFrame
        Newly normalised rows.
    table : str
        ``"bars"`` or ``"levels"``, recorded in the log.
    key_column : str
        ``"session_date"`` or ``"observation_date"``.
    value_columns : Sequence[str]
        Columns to compare.
    new_fetch_id : str
        Fetch that produced ``incoming``.
    detected_at_utc : datetime
        UTC instant of the comparison.
    tolerance : float
        Absolute difference below which values count as unchanged.

    Returns
    -------
    pd.DataFrame
        Rows matching the revisions schema; empty when nothing changed. One row
        per changed field, not per changed date: acceptance is decided field by
        field, so detection reports that way too. Sorted by date, then by the
        order of ``value_columns``, so the same inputs always give the same log.

    Raises
    ------
    ValueError
        If ``detected_at_utc`` is not a UTC instant, a frame lacks
        ``key_column`` or one of ``value_columns``, a frame repeats a date or
        mixes instruments (see :func:`_rows_by_date`), or the two frames
        describe different instruments.

    Notes
    -----
    Exercice 7.4 (moyen). Ne compare **que** l'intersection des dates : une date
    presente d'un seul cote est une nouvelle observation ou une troncature de
    plage, pas une revision. Compare en valeur absolue et non en egalite exacte :
    un aller-retour float64 -> Parquet -> float64 est exact, mais un changement
    d'arrondi chez le fournisseur ne l'est pas.

    A missing value is a value: see :func:`_has_changed`. Nothing here reads a
    clock or a file, so replaying the same two frames replays the same log.
    """
    if detected_at_utc.tzinfo is None or detected_at_utc.utcoffset() != timedelta(0):
        raise ValueError(f"detected_at_utc must be a UTC instant, got {detected_at_utc!r}")
    for side, frame in (("stored", existing), ("incoming", incoming)):
        absent = [column for column in value_columns if column not in frame.columns]
        if absent:
            raise ValueError(f"The {side} rows lack column(s): {', '.join(absent)}")
    stored_rows = _rows_by_date(existing, key_column, "stored")
    incoming_rows = _rows_by_date(incoming, key_column, "incoming")
    _shared_instrument(stored_rows, incoming_rows)
    rows: list[dict[str, Any]] = []
    # Only the overlap: a date on one side alone is a new observation or a
    # window that does not reach that far back, never a change of mind.
    for observation_date in sorted(set(stored_rows) & set(incoming_rows)):
        stored_row = stored_rows[observation_date]
        incoming_row = incoming_rows[observation_date]
        for field in value_columns:
            old_value = float(stored_row[field])
            new_value = float(incoming_row[field])
            if not _has_changed(old_value, new_value, tolerance):
                continue
            rows.append(
                {
                    "instrument_id": stored_row["instrument_id"],
                    "table": table,
                    "observation_date": observation_date,
                    "field": field,
                    "old_value": old_value,
                    "new_value": new_value,
                    "old_fetch_id": stored_row["source_fetch_id"],
                    "new_fetch_id": new_fetch_id,
                    "detected_at_utc": detected_at_utc,
                }
            )
    if not rows:
        return REVISIONS_SCHEMA.empty_table().to_pandas()
    frame = pd.DataFrame(rows, columns=list(REVISIONS_SCHEMA.names))
    # Pin the instant's dtype rather than leave it to inference, like the
    # validation log does: the schema says microseconds, UTC.
    frame["detected_at_utc"] = pd.Series(
        [detected_at_utc] * len(rows), index=frame.index, dtype="datetime64[us, UTC]"
    )
    return frame


def merge_with_policy(
    existing: pd.DataFrame,
    incoming: pd.DataFrame,
    accepted: AcceptedRevisions,
    *,
    table: str,
    key_column: str,
    value_columns: Sequence[str],
) -> pd.DataFrame:
    """Merge new rows into stored ones under the stability policy.

    Parameters
    ----------
    existing : pd.DataFrame
        Rows already stored.
    incoming : pd.DataFrame
        Newly normalised rows.
    accepted : AcceptedRevisions
        Reviewed decisions.
    table : str
        ``"bars"`` or ``"levels"``.
    key_column : str
        Date column to join on.
    value_columns : Sequence[str]
        Columns subject to the policy.

    Returns
    -------
    pd.DataFrame
        Merged frame, chronologically sorted, carrying the stored frame's
        columns and dtypes. A row whose value an accepted correction actually
        moved takes the incoming ``source_fetch_id``: that is the fetch to
        reopen when re-examining the value, and the detection log records field
        by field what moved. Every other row keeps the provenance it had.

    Raises
    ------
    ValueError
        If the two frames do not carry the same columns, a frame lacks
        ``key_column`` or one of ``value_columns``, a frame repeats a date or
        mixes instruments (see :func:`_rows_by_date`), or the two frames
        describe different instruments.

    Notes
    -----
    Exercice 7.5 (moyen, c'est le coeur de la reproductibilite). Regle :

    - date absente du stock -> la ligne entrante est ajoutee ;
    - date presente, valeurs identiques -> on garde le stock ;
    - date presente, valeurs differentes -> on garde le stock, **sauf** si
      ``accepted.is_accepted(...)`` pour ce champ precis.

    Un ``drop_duplicates`` silencieux ferait exactement le contraire de ce qu'on
    veut : il laisserait l'historique bouger tout seul.

    The first two rules are one rule: an unaccepted difference is kept as
    stored, so identical and different values take the same path. Acceptance is
    per field, so a reviewed close does not drag the day's unreviewed open along
    with it. A value that vanished from the refetch is a difference like any
    other: the stored value survives unless its disappearance was reviewed.

    A date the refetch does not reach is left alone: a shorter window is not the
    provider withdrawing history.
    """
    if set(existing.columns) != set(incoming.columns):
        raise ValueError(
            "Stored and incoming rows carry different columns: "
            f"only stored={sorted(set(existing.columns) - set(incoming.columns))}, "
            f"only incoming={sorted(set(incoming.columns) - set(existing.columns))}"
        )
    for side, frame in (("stored", existing), ("incoming", incoming)):
        absent = [column for column in value_columns if column not in frame.columns]
        if absent:
            raise ValueError(f"The {side} rows lack column(s): {', '.join(absent)}")
    stored_rows = _rows_by_date(existing, key_column, "stored")
    incoming_rows = _rows_by_date(incoming, key_column, "incoming")
    instrument_id = _shared_instrument(stored_rows, incoming_rows)
    merged: list[dict[str, Any]] = []
    for observation_date in sorted(set(stored_rows) | set(incoming_rows)):
        stored_row = stored_rows.get(observation_date)
        incoming_row = incoming_rows.get(observation_date)
        if stored_row is None:
            # A date we had never stored: new data, nothing to decide.
            merged.append(dict(incoming_row or {}))
            continue
        if incoming_row is None:
            merged.append(dict(stored_row))
            continue
        row = dict(stored_row)
        moved = False
        for field in value_columns:
            if not _has_changed(float(stored_row[field]), float(incoming_row[field]), 0.0):
                continue
            if not accepted.is_accepted(str(instrument_id), table, observation_date, field):
                continue
            row[field] = incoming_row[field]
            moved = True
        if moved:
            row["source_fetch_id"] = incoming_row["source_fetch_id"]
        merged.append(row)
    if not merged:
        return existing.iloc[0:0].reset_index(drop=True)
    # Rebuilt from plain Python values, so the canonical dtypes are restored
    # rather than left to inference.
    return pd.DataFrame(merged, columns=list(existing.columns)).astype(existing.dtypes.to_dict())
