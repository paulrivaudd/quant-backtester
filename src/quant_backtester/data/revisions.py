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

import tomllib
from collections.abc import Sequence
from dataclasses import dataclass, fields
from datetime import date, datetime
from pathlib import Path

import pandas as pd


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
        Rows matching the revisions schema; empty when nothing changed.

    Notes
    -----
    Exercice 7.4 (moyen). Ne compare **que** l'intersection des dates : une date
    presente d'un seul cote est une nouvelle observation ou une troncature de
    plage, pas une revision. Compare en valeur absolue et non en egalite exacte :
    un aller-retour float64 -> Parquet -> float64 est exact, mais un changement
    d'arrondi chez le fournisseur ne l'est pas.
    """
    raise NotImplementedError("Exercice 7.4")


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
        Merged frame, chronologically sorted.

    Notes
    -----
    Exercice 7.5 (moyen, c'est le coeur de la reproductibilite). Regle :

    - date absente du stock -> la ligne entrante est ajoutee ;
    - date presente, valeurs identiques -> on garde le stock ;
    - date presente, valeurs differentes -> on garde le stock, **sauf** si
      ``accepted.is_accepted(...)`` pour ce champ precis.

    Un ``drop_duplicates`` silencieux ferait exactement le contraire de ce qu'on
    veut : il laisserait l'historique bouger tout seul.
    """
    raise NotImplementedError("Exercice 7.5")
