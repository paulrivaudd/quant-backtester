"""Reviewed sessions a series is known not to have, and why.

A hole in a series is either a fact that was looked at or a problem nobody has
seen yet, and a coverage report that cannot tell the two apart hides the
second behind the first. BNP Easy S&P 500 (``ESE.PA``) has four Euronext
sessions Yahoo does not serve - two Christmas Eves, a New Year's Eve and Whit
Monday 2015, each a half day in Paris or a day New York was shut, on a fund
trading a few thousand shares a day - and one bar dropped by review, on
2017-09-07. Those five are known. A sixth appearing tomorrow should stand out.

So each known gap is committed, with its kind, the hypothesis about it, the
evidence the hypothesis rests on and the day it was reviewed:

    [[gap]]
    instrument_id = "ETF_SP500_PEA"
    session_date = 2015-05-25
    kind = "NO_BAR_SERVED"
    hypothesis = "no trade: Memorial Day, the underlying market was shut"
    evidence = "Yahoo serves 2015-05-22 (18 828 shares) and 2015-05-26 ..."
    reviewed_on = 2026-09-26

**A gap is never filled.** No last price carried over, no interpolation, no
bar taken from another venue: a session without a trade and a session whose
data was lost call for different treatments, and nothing here can prove which
one a gap is. The reader goes on serving it as ``MISSING``.

**A gap has to keep being one.** If the provider starts serving a bar for a
session reviewed as ``NO_BAR_SERVED``, the review no longer describes the data
and the ingestion refuses the fetch until someone looks again - the same rule
as a bar correction whose defect has disappeared. A ``BAR_DROPPED`` gap is the
trace of a bar correction and must have one.
"""

from __future__ import annotations

import tomllib
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, fields
from datetime import date, datetime
from enum import Enum
from pathlib import Path

import pandas as pd


class GapKind(Enum):
    """Why a session is missing from a series."""

    NO_BAR_SERVED = "NO_BAR_SERVED"
    """The provider serves no row for a session the venue held."""

    BAR_DROPPED = "BAR_DROPPED"
    """A row was served and dropped by a reviewed bar correction."""


@dataclass(frozen=True, slots=True)
class KnownGap:
    """One session reviewed as missing from one instrument's series.

    Attributes
    ----------
    instrument_id : str
        Instrument concerned.
    session_date : date
        The venue session the series does not have.
    kind : GapKind
        Why it does not.
    hypothesis : str
        What the gap most probably is. A hypothesis, said as one.
    evidence : str
        What the hypothesis rests on: neighbouring volumes, the calendar of
        the underlying market, what a second source says or could not say.
    reviewed_on : date
        When the gap was reviewed.
    """

    instrument_id: str
    session_date: date
    kind: GapKind
    hypothesis: str
    evidence: str
    reviewed_on: date


GAP_KEYS = frozenset(f.name for f in fields(KnownGap))
"""Keys of a ``[[gap]]`` table, all required."""


class KnownGaps:
    """The reviewed gaps, keyed by instrument and session.

    Parameters
    ----------
    gaps : Sequence[KnownGap]
        Reviewed gaps. Empty is valid.

    Raises
    ------
    ValueError
        If a gap has a blank identifier, hypothesis or evidence, a date that is
        not a plain date, or repeats another's key.
    """

    def __init__(self, gaps: Sequence[KnownGap]) -> None:
        keys: set[tuple[str, date]] = set()
        for gap in gaps:
            label = f"Known gap of {gap.instrument_id} on {gap.session_date}"
            for name in ("session_date", "reviewed_on"):
                value: object = getattr(gap, name)
                if isinstance(value, datetime) or not isinstance(value, date):
                    raise ValueError(f"{label}: {name} must be a plain date")
            if not isinstance(gap.kind, GapKind):
                raise ValueError(f"{label}: kind must be a GapKind, got {gap.kind!r}")
            for name in ("instrument_id", "hypothesis", "evidence"):
                if not str(getattr(gap, name)).strip():
                    raise ValueError(f"{label}: {name} cannot be blank")
            key = (gap.instrument_id, gap.session_date)
            if key in keys:
                raise ValueError(f"{label}: reviewed more than once")
            keys.add(key)
        self._gaps = tuple(sorted(gaps, key=lambda gap: (gap.instrument_id, gap.session_date)))

    @classmethod
    def from_toml(cls, path: Path) -> KnownGaps:
        """Load the reviewed gaps from the committed TOML file.

        Parameters
        ----------
        path : Path
            File holding zero or more ``[[gap]]`` tables.

        Returns
        -------
        KnownGaps
            The reviewed gaps. A missing file is an error: it is committed, so
            its absence means the metadata tree is incomplete.

        Raises
        ------
        FileNotFoundError
            If the file does not exist.
        ValueError
            If an entry lacks a key, carries an unknown one, or names an
            unknown kind.
        """
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
        gaps: list[KnownGap] = []
        for index, table in enumerate(raw.get("gap", []), start=1):
            context = f"{path} gap #{index}"
            unknown = sorted(set(table) - GAP_KEYS)
            if unknown:
                raise ValueError(f"{context}: unknown key(s) {', '.join(unknown)}")
            missing = sorted(GAP_KEYS - set(table))
            if missing:
                raise ValueError(f"{context}: missing key(s) {', '.join(missing)}")
            try:
                kind = GapKind(table["kind"])
            except ValueError as error:
                raise ValueError(f"{context}: {error}") from None
            gaps.append(
                KnownGap(
                    instrument_id=str(table["instrument_id"]),
                    session_date=table["session_date"],
                    kind=kind,
                    hypothesis=str(table["hypothesis"]),
                    evidence=str(table["evidence"]),
                    reviewed_on=table["reviewed_on"],
                )
            )
        return cls(gaps)

    def of(self, instrument_id: str) -> tuple[KnownGap, ...]:
        """Return an instrument's reviewed gaps, in session order."""
        return tuple(gap for gap in self._gaps if gap.instrument_id == instrument_id)

    def sessions(self, instrument_id: str) -> frozenset[date]:
        """Return the sessions of an instrument reviewed as missing."""
        return frozenset(gap.session_date for gap in self.of(instrument_id))

    def served_anyway(self, instrument_id: str, frame: pd.DataFrame) -> tuple[KnownGap, ...]:
        """Return the ``NO_BAR_SERVED`` gaps a fetch now carries a bar for.

        Parameters
        ----------
        instrument_id : str
            Instrument the frame belongs to.
        frame : pd.DataFrame
            Canonical bars of the primary source, with ``session_date``.

        Returns
        -------
        tuple[KnownGap, ...]
            Each reviewed gap the provider has started to serve. The review no
            longer describes the data, and has to be looked at again.
        """
        served = set(frame["session_date"]) if not frame.empty else set()
        return tuple(
            gap
            for gap in self.of(instrument_id)
            if gap.kind is GapKind.NO_BAR_SERVED and gap.session_date in served
        )

    def __iter__(self) -> Iterator[KnownGap]:
        """Iterate over the gaps, by instrument then session."""
        return iter(self._gaps)

    def __len__(self) -> int:
        """Return how many gaps were reviewed."""
        return len(self._gaps)
