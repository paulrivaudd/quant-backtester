"""Reviewed corrections to what a provider called a corporate action.

A provider gives one label for events that are not the same thing. Yahoo encodes
a spin-off as a fractional ``Stock Splits`` row - GE 1.281 on 2023-01-04 for GE
HealthCare - and a special dividend as an ordinary one, COST 15.00 on
2023-12-27. Stored as they arrive, a spin-off multiplies a share count that
never moved and a one-off payment feeds a dividend yield as if it recurred.

The provider cannot be fixed and the label cannot be guessed, so the decision is
committed, exactly like an accepted revision: one entry per event, with the
reason it was made. Nothing here inspects prices or dates to decide on its own -
a correction that reclassified an event by itself would change past results
whenever the provider changed a number.

The file lives at ``metadata/corporate_actions.toml`` and looks like::

    [[correction]]
    instrument_id = "GE"
    ex_date = 2023-01-04
    from_type = "SPLIT"
    to_type = "SPIN_OFF"
    reason = "GE HealthCare spin-off; Yahoo reports it as a 1.281 split"
"""

from __future__ import annotations

import tomllib
from collections.abc import Sequence
from dataclasses import dataclass, fields
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from quant_backtester.data.schemas import ActionType

CORRECTIBLE: dict[ActionType, frozenset[ActionType]] = {
    ActionType.SPLIT: frozenset({ActionType.SPIN_OFF}),
    ActionType.DIVIDEND: frozenset({ActionType.SPECIAL_DIVIDEND}),
}
"""What a reviewed correction may turn an action into.

A correction renames an event the provider mislabelled; it never turns a
dividend into a split. The price adjustment is unchanged on both sides of every
allowed pair, so a correction can never move a stored series - it only stops the
layers above from reading the event as something it is not.
"""


@dataclass(frozen=True, slots=True)
class ActionCorrection:
    """One reviewed decision about what an event really was.

    Attributes
    ----------
    instrument_id : str
        Instrument concerned.
    ex_date : date
        Ex-date of the event.
    from_type : ActionType
        What the provider called it. Recorded so a correction stops applying if
        the provider ever fixes its own label.
    to_type : ActionType
        What it is.
    reason : str
        Why. Required: a decision without a reason cannot be re-examined.
    """

    instrument_id: str
    ex_date: date
    from_type: ActionType
    to_type: ActionType
    reason: str


CORRECTION_KEYS = frozenset(f.name for f in fields(ActionCorrection))
"""Keys of a ``[[correction]]`` table, all required."""


class ActionCorrections:
    """The set of reviewed corrections, keyed by instrument and ex-date.

    Parameters
    ----------
    corrections : Sequence[ActionCorrection]
        Reviewed decisions. Empty is valid and is the normal state.

    Raises
    ------
    ValueError
        If a correction has a blank reason, an ``ex_date`` that is not a plain
        date, a pair outside :data:`CORRECTIBLE`, or repeats the key of another:
        two reviews of one event cannot both be the one that was made.
    """

    def __init__(self, corrections: Sequence[ActionCorrection]) -> None:
        keys: set[tuple[str, date, ActionType]] = set()
        for correction in corrections:
            label = (
                f"Correction of {correction.instrument_id} on {correction.ex_date} "
                f"({correction.from_type.value} -> {correction.to_type.value})"
            )
            ex_date: object = correction.ex_date
            if isinstance(ex_date, datetime) or not isinstance(ex_date, date):
                raise ValueError(f"{label}: ex_date must be a plain date")
            if not correction.reason.strip():
                raise ValueError(f"{label}: a reason is required")
            allowed = CORRECTIBLE.get(correction.from_type, frozenset())
            if correction.to_type not in allowed:
                permitted = ", ".join(sorted(action.value for action in allowed)) or "nothing"
                raise ValueError(
                    f"{label}: a {correction.from_type.value} may only be corrected "
                    f"into {permitted}"
                )
            key = (correction.instrument_id, correction.ex_date, correction.from_type)
            if key in keys:
                raise ValueError(f"{label}: corrected more than once")
            keys.add(key)
        self._corrections = tuple(corrections)
        self._by_key = {(c.instrument_id, c.ex_date, c.from_type): c.to_type for c in corrections}

    @classmethod
    def from_toml(cls, path: Path) -> ActionCorrections:
        """Load decisions from the committed TOML file.

        Parameters
        ----------
        path : Path
            File holding zero or more ``[[correction]]`` tables.

        Returns
        -------
        ActionCorrections
            The reviewed decisions. A missing file is an error: the empty file
            is committed on purpose, so its absence means the metadata tree is
            incomplete rather than that nothing was decided.

        Raises
        ------
        FileNotFoundError
            If the file does not exist.
        ValueError
            If an entry lacks a key, carries an unknown one, or names an action
            type that does not exist.
        """
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
        corrections: list[ActionCorrection] = []
        for index, table in enumerate(raw.get("correction", []), start=1):
            context = f"{path} correction #{index}"
            unknown = sorted(set(table) - CORRECTION_KEYS)
            if unknown:
                raise ValueError(f"{context}: unknown key(s) {', '.join(unknown)}")
            missing = sorted(CORRECTION_KEYS - set(table))
            if missing:
                raise ValueError(f"{context}: missing key(s) {', '.join(missing)}")
            try:
                from_type = ActionType(table["from_type"])
                to_type = ActionType(table["to_type"])
            except ValueError as error:
                raise ValueError(f"{context}: {error}") from None
            corrections.append(
                ActionCorrection(
                    instrument_id=str(table["instrument_id"]),
                    ex_date=table["ex_date"],
                    from_type=from_type,
                    to_type=to_type,
                    reason=str(table["reason"]),
                )
            )
        return cls(corrections)

    def corrected_type(self, instrument_id: str, ex_date: date, action_type: str) -> str:
        """Return what an event really was, or the label it arrived with.

        Parameters
        ----------
        instrument_id : str
            Instrument concerned.
        ex_date : date
            Ex-date of the event.
        action_type : str
            The provider's label.

        Returns
        -------
        str
            The reviewed type when one was decided for exactly this event and
            this label, the unchanged label otherwise.
        """
        try:
            reported = ActionType(action_type)
        except ValueError:
            return action_type
        corrected = self._by_key.get((instrument_id, ex_date, reported))
        return action_type if corrected is None else corrected.value

    def apply(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Return the actions with every reviewed label applied.

        Parameters
        ----------
        frame : pd.DataFrame
            Canonical corporate actions.

        Returns
        -------
        pd.DataFrame
            A copy with ``action_type`` corrected where a decision exists.
            Values, dates and lineage are untouched: a correction says what an
            event was, never what it was worth.
        """
        if frame.empty:
            return frame
        corrected = frame.copy()
        rows: list[dict[str, Any]] = [
            {str(column): value for column, value in record.items()}
            for record in frame.to_dict("records")
        ]
        corrected["action_type"] = [
            self.corrected_type(str(row["instrument_id"]), row["ex_date"], str(row["action_type"]))
            for row in rows
        ]
        return corrected

    def __len__(self) -> int:
        """Return how many decisions were reviewed."""
        return len(self._corrections)
