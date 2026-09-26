"""Hypotheses, written down before the experiments that test them.

A register counts the variants a hypothesis took; it cannot say whether the
hypothesis was stated before the variants were run, or read off the best of
them afterwards. That is what this file is for (audit of archive 9, C02): each
hypothesis says what it predicts, over which universe, and what result would
refute it, and carries the day it was written. A run registered under a
hypothesis written after it is refused - it would be a pre-registration in
name only.

The runs made before this file existed are not dressed up as tested ideas:
their hypotheses are declared ``EXPLORATORY``, with the day they were
declared, which is after the fact and says so.
"""

from __future__ import annotations

import tomllib
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, fields
from datetime import date, datetime
from enum import Enum
from pathlib import Path


class HypothesisStatus(Enum):
    """Whether a hypothesis was stated before its experiments."""

    PREREGISTERED = "PREREGISTERED"
    """Written before any of its variants was run. Its runs test it."""

    EXPLORATORY = "EXPLORATORY"
    """Named after runs that were already made. Its runs describe; they test nothing."""


@dataclass(frozen=True, slots=True)
class Hypothesis:
    """One hypothesis, as it was written.

    Attributes
    ----------
    hypothesis_id : str
        What the register files its runs under.
    status : HypothesisStatus
        Stated before its runs, or named after them.
    written_on : date
        The day it was written.
    statement : str
        The idea, in a sentence.
    universe : str
        What it is tested on.
    prediction : str
        What it expects to see, in terms a run can show.
    refutation : str
        The result that would refute it. Required: an idea no result could
        refute is not being tested.
    """

    hypothesis_id: str
    status: HypothesisStatus
    written_on: date
    statement: str
    universe: str
    prediction: str
    refutation: str


HYPOTHESIS_KEYS = frozenset(f.name for f in fields(Hypothesis))
"""Keys of a ``[[hypothesis]]`` table, all required."""


class Hypotheses:
    """The written hypotheses, by id.

    Raises
    ------
    ValueError
        If a hypothesis repeats an id, leaves a text blank, or has a date that
        is not a plain date.
    """

    def __init__(self, hypotheses: Sequence[Hypothesis]) -> None:
        by_id: dict[str, Hypothesis] = {}
        for hypothesis in hypotheses:
            label = f"Hypothesis {hypothesis.hypothesis_id!r}"
            written: object = hypothesis.written_on
            if isinstance(written, datetime) or not isinstance(written, date):
                raise ValueError(f"{label}: written_on must be a plain date")
            if not isinstance(hypothesis.status, HypothesisStatus):
                raise ValueError(f"{label}: status must be a HypothesisStatus")
            for name in ("hypothesis_id", "statement", "universe", "prediction", "refutation"):
                if not str(getattr(hypothesis, name)).strip():
                    raise ValueError(f"{label}: {name} cannot be blank")
            if hypothesis.hypothesis_id in by_id:
                raise ValueError(f"{label} is written twice")
            by_id[hypothesis.hypothesis_id] = hypothesis
        self._by_id = by_id

    @classmethod
    def from_toml(cls, path: Path) -> Hypotheses:
        """Load the committed hypotheses."""
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
        hypotheses: list[Hypothesis] = []
        for index, table in enumerate(raw.get("hypothesis", []), start=1):
            context = f"{path} hypothesis #{index}"
            unknown = sorted(set(table) - HYPOTHESIS_KEYS)
            if unknown:
                raise ValueError(f"{context}: unknown key(s) {', '.join(unknown)}")
            missing = sorted(HYPOTHESIS_KEYS - set(table))
            if missing:
                raise ValueError(f"{context}: missing key(s) {', '.join(missing)}")
            hypotheses.append(Hypothesis(**{**table, "status": HypothesisStatus(table["status"])}))
        return cls(hypotheses)

    def get(self, hypothesis_id: str) -> Hypothesis:
        """Return one hypothesis.

        Raises
        ------
        KeyError
            If it was never written: a run cannot be filed under an idea that
            nobody stated.
        """
        if hypothesis_id not in self._by_id:
            raise KeyError(f"no hypothesis {hypothesis_id!r} is written in the hypotheses file")
        return self._by_id[hypothesis_id]

    def __iter__(self) -> Iterator[Hypothesis]:
        """Iterate over the hypotheses, in id order."""
        return iter(sorted(self._by_id.values(), key=lambda hypothesis: hypothesis.hypothesis_id))
