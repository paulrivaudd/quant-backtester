"""Reviewed decisions about a session two sources disagree on.

The cross-check marks a session ``CONFLICT`` when two sources disagree beyond
a tolerance, and the reader serves it as a hole. That is the right reflex for a
disagreement nobody has looked at, and an expensive one for a disagreement
somebody has: one flat bar Yahoo served for 24 October 2025 kept a 60-session
momentum from being computed for 61 sessions.

A review settles one session, and only the values it was written for:

    [[review]]
    instrument_id = "ETF_WORLD"
    session_date = 2025-10-24
    use_source = "EURONEXT"
    reason = "Yahoo serves a flat bar with no volume; Euronext is the venue ..."
    reviewed_on = 2026-09-26

      [review.values.YAHOO]
      open = 602.339...
      ...
      [review.values.EURONEXT]
      open = 603.312...
      ...

It records every source's bar exactly as it was reviewed. The session is
served from ``use_source`` and marked ``REVIEWED`` - never ``CONFIRMED``: the
sources did disagree - for as long as each source still serves those very
values. If one changes, the review describes data that is no longer there,
and the session goes back to ``CONFLICT`` until someone looks again.

**What a review may choose.** A source's bar, whole: never a field from one
and a field from another, which could assemble a bar nobody served. The
chosen bar must be valid on its own. And the choice has to be one the time
could have made: the venue's official prices are published the evening of the
session, so choosing them serves a value that was knowable when a decision was
taken. A review written in 2026 does not make any value known in 2025; it
decides which of two values that were both published is the one to believe.
"""

from __future__ import annotations

import math
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

REVIEWED_FIELDS: tuple[str, ...] = ("open", "high", "low", "close", "volume")
"""The values of a bar a review records, for every source it compares."""


@dataclass(frozen=True, slots=True)
class ConflictReview:
    """One reviewed decision about one contested session.

    Attributes
    ----------
    instrument_id : str
        Instrument concerned.
    session_date : date
        The contested session.
    use_source : str
        The source whose bar is served.
    values : Mapping[str, Mapping[str, float]]
        Every compared source's bar as it was reviewed, by source and field.
    reason : str
        Why that source. Required.
    reviewed_on : date
        When the review was made.
    """

    instrument_id: str
    session_date: date
    use_source: str
    values: Mapping[str, Mapping[str, float]]
    reason: str
    reviewed_on: date

    def matches(self, bars: Mapping[str, Mapping[str, Any]]) -> bool:
        """Return whether the sources still serve exactly the values reviewed.

        Parameters
        ----------
        bars : Mapping[str, Mapping[str, Any]]
            The session's bar per source, as the cross-check reads them.
        """
        if set(bars) != set(self.values):
            return False
        for source, reviewed in self.values.items():
            for field, expected in reviewed.items():
                served = bars[source].get(field)
                if served is None or served != served:
                    return False
                if not math.isclose(float(served), expected, rel_tol=1e-12, abs_tol=0.0):
                    return False
        return True


class ConflictReviews:
    """The reviewed conflicts, by instrument and session.

    Raises
    ------
    ValueError
        If a review repeats another's session, leaves its reason blank, does
        not record the source it chooses, or records a field outside
        :data:`REVIEWED_FIELDS`.
    """

    def __init__(self, reviews: Sequence[ConflictReview]) -> None:
        by_key: dict[tuple[str, date], ConflictReview] = {}
        for review in reviews:
            label = f"Review of {review.instrument_id} on {review.session_date}"
            for name in ("session_date", "reviewed_on"):
                value: object = getattr(review, name)
                if isinstance(value, datetime) or not isinstance(value, date):
                    raise ValueError(f"{label}: {name} must be a plain date")
            if not review.reason.strip():
                raise ValueError(f"{label}: reason cannot be blank")
            if review.use_source not in review.values:
                raise ValueError(f"{label}: chooses {review.use_source} and does not record it")
            for source, fields in review.values.items():
                unknown = sorted(set(fields) - set(REVIEWED_FIELDS))
                if unknown:
                    raise ValueError(f"{label}: {source} records unknown field(s) {unknown}")
            key = (review.instrument_id, review.session_date)
            if key in by_key:
                raise ValueError(f"{label}: reviewed more than once")
            by_key[key] = review
        self._by_key = MappingProxyType(by_key)

    @classmethod
    def from_toml(cls, path: Path) -> ConflictReviews:
        """Load the committed reviews. A missing file is an error, not an empty set."""
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
        reviews: list[ConflictReview] = []
        expected = {
            "instrument_id",
            "session_date",
            "use_source",
            "values",
            "reason",
            "reviewed_on",
        }
        for index, table in enumerate(raw.get("review", []), start=1):
            if set(table) != expected:
                raise ValueError(
                    f"{path} review #{index}: a review has exactly the keys {sorted(expected)}"
                )
            reviews.append(
                ConflictReview(
                    instrument_id=str(table["instrument_id"]),
                    session_date=table["session_date"],
                    use_source=str(table["use_source"]),
                    values={
                        str(source): {str(k): float(v) for k, v in fields.items()}
                        for source, fields in table["values"].items()
                    },
                    reason=str(table["reason"]),
                    reviewed_on=table["reviewed_on"],
                )
            )
        return cls(reviews)

    def get(self, instrument_id: str, session_date: date) -> ConflictReview | None:
        """Return the review of one session, or ``None``."""
        return self._by_key.get((instrument_id, session_date))

    def __len__(self) -> int:
        """Return how many sessions were reviewed."""
        return len(self._by_key)
