"""Reviewed decisions about a bar a provider sent broken.

A provider occasionally serves a bar that is not a bar. Yahoo's only
inconsistent row for the BNP Easy S&P 500 in thirteen years is 2017-09-07, an
open of 9.22583 above a high of 9.20667: two tenths of a percent apart, and
arithmetically impossible. The validator refuses the whole series for it, which
is the right reflex - a bar whose open is outside its own range is a number
nobody can price anything from.

Refusing for ever is not an answer either: one broken row in 2017 keeps four
years of good history out of the store. So the decision is committed, exactly
like an accepted revision or a mislabelled corporate action: one entry per bar,
with the reason it was made.

**A correction drops the row; it never repairs it.** Repairing would mean
inventing the high the market really made, and nothing here knows it - the
second source does not reach back that far, and a value invented in a config
file is worse than a hole, because a hole is visible. What the correction
changes is only this: the row stops poisoning the rest of the series, and the
session becomes what it honestly is, a session with no price we can stand
behind. The reader already reports that as ``MISSING``.

A correction also has to keep matching. It names the defect it was written
for, and applying it to a row that no longer shows that defect is an error: the
provider fixed its own data, and a correction nobody re-examined would go on
dropping a good bar for ever.

The file lives at ``metadata/bar_corrections.toml`` and looks like::

    [[correction]]
    instrument_id = "ETF_SP500_PEA"
    source = "YAHOO"
    session_date = 2017-09-07
    defect = "OHLC_ORDER"
    reason = "Yahoo serves open 9.22583 above high 9.20667; no second source reaches 2017"

Corrections apply where the raw becomes canonical, so a correction added today
takes effect on the next fetch and, for the history already stored, on the next
``--rebuild``. Like every other committed decision, it is part of what a result
is reproduced from.
"""

from __future__ import annotations

import tomllib
from collections.abc import Sequence
from dataclasses import dataclass, fields
from datetime import date, datetime
from enum import Enum
from pathlib import Path

import pandas as pd

from quant_backtester.data.instruments import Instrument
from quant_backtester.data.validator import Severity, bar_row_issues


class BarDefect(Enum):
    """What a reviewed correction may be written for.

    Only defects that make a bar arithmetically impossible. A price that looks
    surprising is not one of these: dropping a bar because it moved a lot is
    how a backtest quietly loses its worst days.
    """

    OHLC_ORDER = "OHLC_ORDER"
    """An open or a close outside the bar's own high-low range."""

    NON_POSITIVE_PRICE = "NON_POSITIVE_PRICE"
    """A price of zero or less on an instrument that cannot have one."""


@dataclass(frozen=True, slots=True)
class BarCorrection:
    """One reviewed decision to drop one provider's bar.

    Attributes
    ----------
    instrument_id : str
        Instrument concerned.
    source : str
        The provider that sent the broken row. A defect belongs to one feed:
        another source's bar for the same session is untouched, and is exactly
        what the cross-check should be free to use.
    session_date : date
        Session of the row.
    defect : BarDefect
        What is wrong with it. Checked against the row before the row is
        dropped, so the correction stops applying if the provider repairs it.
    reason : str
        Why. Required: a decision without a reason cannot be re-examined.
    """

    instrument_id: str
    source: str
    session_date: date
    defect: BarDefect
    reason: str


CORRECTION_KEYS = frozenset(f.name for f in fields(BarCorrection))
"""Keys of a ``[[correction]]`` table, all required."""


class BarCorrections:
    """The set of reviewed bar corrections, keyed by instrument, source and session.

    Parameters
    ----------
    corrections : Sequence[BarCorrection]
        Reviewed decisions. Empty is valid and is the normal state.

    Raises
    ------
    ValueError
        If a correction has a blank reason or identifier, a ``session_date``
        that is not a plain date, or repeats another's key: two reviews of one
        bar cannot both be the one that was made.
    """

    def __init__(self, corrections: Sequence[BarCorrection]) -> None:
        keys: set[tuple[str, str, date]] = set()
        for correction in corrections:
            label = (
                f"Correction of {correction.instrument_id} from {correction.source} "
                f"on {correction.session_date}"
            )
            session_date: object = correction.session_date
            if isinstance(session_date, datetime) or not isinstance(session_date, date):
                raise ValueError(f"{label}: session_date must be a plain date")
            for name, value in (
                ("instrument_id", correction.instrument_id),
                ("source", correction.source),
                ("reason", correction.reason),
            ):
                if not value.strip():
                    raise ValueError(f"{label}: {name} cannot be blank")
            key = (correction.instrument_id, correction.source, correction.session_date)
            if key in keys:
                raise ValueError(f"{label}: corrected more than once")
            keys.add(key)
        self._corrections = tuple(corrections)
        self._by_key = {(c.instrument_id, c.source, c.session_date): c for c in corrections}

    @classmethod
    def from_toml(cls, path: Path) -> BarCorrections:
        """Load decisions from the committed TOML file.

        Parameters
        ----------
        path : Path
            File holding zero or more ``[[correction]]`` tables.

        Returns
        -------
        BarCorrections
            The reviewed decisions. A missing file is an error: the empty file
            is committed on purpose, so its absence means the metadata tree is
            incomplete rather than that nothing was decided.

        Raises
        ------
        FileNotFoundError
            If the file does not exist.
        ValueError
            If an entry lacks a key, carries an unknown one, or names a defect
            no correction may be written for.
        """
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
        corrections: list[BarCorrection] = []
        for index, table in enumerate(raw.get("correction", []), start=1):
            context = f"{path} correction #{index}"
            unknown = sorted(set(table) - CORRECTION_KEYS)
            if unknown:
                raise ValueError(f"{context}: unknown key(s) {', '.join(unknown)}")
            missing = sorted(CORRECTION_KEYS - set(table))
            if missing:
                raise ValueError(f"{context}: missing key(s) {', '.join(missing)}")
            try:
                defect = BarDefect(table["defect"])
            except ValueError as error:
                raise ValueError(f"{context}: {error}") from None
            corrections.append(
                BarCorrection(
                    instrument_id=str(table["instrument_id"]),
                    source=str(table["source"]),
                    session_date=table["session_date"],
                    defect=defect,
                    reason=str(table["reason"]),
                )
            )
        return cls(corrections)

    def apply(
        self, instrument: Instrument, source: str, frame: pd.DataFrame
    ) -> tuple[pd.DataFrame, tuple[BarCorrection, ...]]:
        """Return the bars without the rows a review decided to drop.

        Parameters
        ----------
        instrument : Instrument
            Instrument the frame belongs to.
        source : str
            Provider that sent it.
        frame : pd.DataFrame
            Canonical bars of one fetch.

        Returns
        -------
        tuple[pd.DataFrame, tuple[BarCorrection, ...]]
            The frame with the corrected rows removed, and the corrections that
            matched a row of this fetch. A correction naming a session the
            fetch does not cover matches nothing, which is the ordinary case:
            most fetches are a window of recent sessions.

        Raises
        ------
        ValueError
            If a row named by a correction no longer shows the defect the
            correction was written for. The provider has repaired its data, the
            decision no longer describes anything, and dropping a good bar
            because of a note written in 2026 is exactly what this class exists
            to prevent.
        """
        if frame.empty or not self._corrections:
            return frame, ()
        applied: list[BarCorrection] = []
        drop: list[int] = []
        for position, record in enumerate(frame.to_dict("records")):
            row = {str(column): value for column, value in record.items()}
            correction = self._by_key.get((instrument.id, source, row["session_date"]))
            if correction is None:
                continue
            codes = {
                issue.code
                for issue in bar_row_issues(instrument, row)
                if issue.severity is Severity.ERROR
            }
            if correction.defect.value not in codes:
                raise ValueError(
                    f"{instrument.id}: the reviewed correction for {source} on "
                    f"{correction.session_date} was written for a "
                    f"{correction.defect.value} that the row no longer has. The provider "
                    f"has changed its data; the decision has to be re-examined rather "
                    f"than go on dropping a bar. Reason on file: {correction.reason}"
                )
            drop.append(position)
            applied.append(correction)
        if not drop:
            return frame, ()
        kept = frame.drop(frame.index[drop]).reset_index(drop=True)
        return kept, tuple(applied)

    def __len__(self) -> int:
        """Return how many decisions were reviewed."""
        return len(self._corrections)
