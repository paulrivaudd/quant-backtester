"""Cross-checking: several sources' canonical bars -> one checked series.

No free source can be trusted on its own. On 2025-10-24 Yahoo served CW8 a flat
placeholder bar with zero volume, and it rounds some highs and lows; Euronext has
the exchange's own prices but only about two years of them. Comparing the same
session across independent sources is what turns "a number we downloaded" into
"a number two providers agree on", and marks the sessions where they do not.

Everything here is a pure function of canonical frames and a declared policy: no
clock, no filesystem, no network, no calendar. Each session is judged on its own
rows only, so data about a later session can never change an earlier verdict.
"""

from __future__ import annotations

import math
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from quant_backtester.data.schemas import BARS_SCHEMA, CHECKED_BARS_SCHEMA, CheckStatus

PRICE_FIELDS: tuple[str, ...] = ("open", "high", "low", "close")
"""Bar fields compared with ``price_rel_tolerance``."""

VOLUME_FIELDS: tuple[str, ...] = ("volume",)
"""Bar fields compared with ``volume_rel_tolerance``."""

AVAILABILITY_FIELDS: tuple[str, ...] = ("open_available_at_utc", "close_available_at_utc")
"""Fields every source must agree on exactly: they come from the one venue calendar."""

POLICY_KEYS = frozenset({"price_rel_tolerance", "volume_rel_tolerance"})
"""Keys of the ``[bars]`` table of ``crosscheck.toml``, all required."""


@dataclass(frozen=True, slots=True)
class CrossCheckPolicy:
    """Tolerances deciding when two sources agree on a bar.

    Attributes
    ----------
    price_rel_tolerance : float
        Largest accepted relative difference on open, high, low and close.
    volume_rel_tolerance : float
        Largest accepted relative difference on volume.

    Notes
    -----
    The relative difference of ``a`` and ``b`` is ``|a - b| / max(|a|, |b|)``,
    zero when both are zero. There are no defaults: tolerances decide which bars
    are trusted, so they are declared in ``metadata/crosscheck.toml``.
    """

    price_rel_tolerance: float
    volume_rel_tolerance: float

    def __post_init__(self) -> None:
        """Reject a tolerance that is not a finite number in ``[0, 1)``.

        Raises
        ------
        ValueError
            If a tolerance is a bool, not a number, negative, not finite, or
            ``1`` or more (which would accept any pair of positive values).
        """
        for name in ("price_rel_tolerance", "volume_rel_tolerance"):
            value: object = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise ValueError(f"{name} must be a number, got {value!r}")
            if not (math.isfinite(value) and 0 <= value < 1):
                raise ValueError(f"{name} must lie in [0, 1), got {value!r}")

    @classmethod
    def from_toml(cls, path: Path) -> CrossCheckPolicy:
        """Load the policy from a committed TOML file.

        Parameters
        ----------
        path : Path
            File holding a ``[bars]`` table with every key of :data:`POLICY_KEYS`.

        Returns
        -------
        CrossCheckPolicy
            The declared tolerances.

        Raises
        ------
        ValueError
            If the table is absent, lacks a key or carries an unknown one, or if
            a tolerance is invalid.
        """
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
        bars = raw.get("bars")
        if not isinstance(bars, dict):
            raise ValueError(f"{path} declares no [bars] table")
        unknown = sorted(set(bars) - POLICY_KEYS)
        if unknown:
            raise ValueError(f"{path} [bars] has unknown key(s): {', '.join(unknown)}")
        missing = sorted(POLICY_KEYS - set(bars))
        if missing:
            raise ValueError(f"{path} [bars] is missing key(s): {', '.join(missing)}")
        return cls(
            price_rel_tolerance=bars["price_rel_tolerance"],
            volume_rel_tolerance=bars["volume_rel_tolerance"],
        )


def relative_difference(a: float, b: float) -> float:
    """Return how far apart two values are, relative to the larger one.

    Parameters
    ----------
    a, b : float
        Values of one field from two sources; ``NaN`` means missing.

    Returns
    -------
    float
        ``|a - b| / max(|a|, |b|)``; ``0.0`` when both are zero or both missing;
        ``inf`` when only one is missing, which no tolerance accepts.
    """
    a_missing, b_missing = math.isnan(a), math.isnan(b)
    if a_missing and b_missing:
        return 0.0
    if a_missing or b_missing:
        return math.inf
    scale = max(abs(a), abs(b))
    return 0.0 if scale == 0 else abs(a - b) / scale


def _largest_difference(bars: list[dict[str, Any]], fields: tuple[str, ...]) -> float:
    """Return the largest relative difference between any two bars on ``fields``.

    Parameters
    ----------
    bars : list[dict[str, Any]]
        One canonical bar per source, all for the same session.
    fields : tuple[str, ...]
        Fields to compare.

    Returns
    -------
    float
        The largest pairwise difference; ``NaN`` for fewer than two bars.
    """
    if len(bars) < 2:
        return math.nan
    largest = 0.0
    for first in range(len(bars)):
        for second in range(first + 1, len(bars)):
            for field in fields:
                difference = relative_difference(
                    float(bars[first][field]), float(bars[second][field])
                )
                largest = max(largest, difference)
    return largest


def _bars_by_session(
    instrument_id: str, source: str, frame: pd.DataFrame
) -> dict[date, dict[str, Any]]:
    """Index one source's canonical bars by session date.

    Parameters
    ----------
    instrument_id : str
        Instrument every row must belong to.
    source : str
        Source the frame was given under; every row's ``source`` must match it.
    frame : pd.DataFrame
        Canonical bars of that source.

    Returns
    -------
    dict[date, dict[str, Any]]
        One row per session.

    Raises
    ------
    ValueError
        If a bars column is missing, a row belongs to another instrument or
        source, or a session appears twice.
    """
    missing = sorted(set(BARS_SCHEMA.names) - set(frame.columns))
    if missing:
        raise ValueError(f"{source} bars of {instrument_id} lack column(s): {', '.join(missing)}")
    by_session: dict[date, dict[str, Any]] = {}
    for record in frame.to_dict("records"):
        row = {str(column): value for column, value in record.items()}
        if row["instrument_id"] != instrument_id:
            raise ValueError(f"{source} bars given for {instrument_id} hold {row['instrument_id']}")
        if row["source"] != source:
            raise ValueError(
                f"Bars given as {source} for {instrument_id} come from {row['source']}"
            )
        session: date = row["session_date"]
        if session in by_session:
            raise ValueError(f"{source} bars of {instrument_id} repeat session {session}")
        by_session[session] = row
    return by_session


def cross_check_bars(
    instrument_id: str,
    frames: Mapping[str, pd.DataFrame],
    reference_source: str,
    policy: CrossCheckPolicy,
) -> pd.DataFrame:
    """Merge several sources' canonical bars into one checked series.

    Parameters
    ----------
    instrument_id : str
        Instrument the bars describe.
    frames : Mapping[str, pd.DataFrame]
        Canonical bars (``BARS_SCHEMA``) keyed by source identifier.
    reference_source : str
        Source whose values are kept whenever it holds a session, normally the
        instrument's ``primary_source``.
    policy : CrossCheckPolicy
        Declared tolerances.

    Returns
    -------
    pd.DataFrame
        One row per session held by any source, sorted by ``session_date``,
        columns in ``CHECKED_BARS_SCHEMA`` order. A session missing from the
        reference source takes the values of the first other source holding it,
        in source order, and is ``SINGLE_SOURCE`` or checked like any other.

    Raises
    ------
    ValueError
        If no frame is given, ``reference_source`` is not among them, a frame is
        malformed (see :func:`_bars_by_session`), or two sources disagree on a
        session's availability instants - they come from one venue calendar, so
        that is a bug upstream, not a data conflict.
    """
    if not frames:
        raise ValueError(f"Cross-checking {instrument_id} needs at least one source")
    if reference_source not in frames:
        raise ValueError(
            f"Reference source {reference_source} of {instrument_id} is not among "
            f"{', '.join(sorted(frames))}"
        )
    by_source = {
        source: _bars_by_session(instrument_id, source, frames[source]) for source in sorted(frames)
    }
    sessions = sorted({session for bars in by_source.values() for session in bars})
    rows: list[dict[str, Any]] = []
    for session in sessions:
        holders = [source for source in by_source if session in by_source[source]]
        bars = [by_source[source][session] for source in holders]
        for field in AVAILABILITY_FIELDS:
            if len({pd.Timestamp(bar[field]) for bar in bars}) > 1:
                raise ValueError(
                    f"Sources {', '.join(holders)} disagree on {field} of {instrument_id} "
                    f"on {session}: they must share one calendar"
                )
        chosen = by_source[reference_source if reference_source in holders else holders[0]]
        price_difference = _largest_difference(bars, PRICE_FIELDS)
        volume_difference = _largest_difference(bars, VOLUME_FIELDS)
        if len(holders) == 1:
            status = CheckStatus.SINGLE_SOURCE
        elif (
            price_difference <= policy.price_rel_tolerance
            and volume_difference <= policy.volume_rel_tolerance
        ):
            status = CheckStatus.CONFIRMED
        else:
            status = CheckStatus.CONFLICT
        row = {field: chosen[session][field] for field in BARS_SCHEMA.names}
        row["check_status"] = status.value
        row["checked_sources"] = ",".join(holders)
        row["checked_fetch_ids"] = ",".join(
            f"{source}:{by_source[source][session]['source_fetch_id']}" for source in holders
        )
        row["max_price_rel_diff"] = price_difference
        row["max_volume_rel_diff"] = volume_difference
        rows.append(row)
    if not rows:
        return CHECKED_BARS_SCHEMA.empty_table().to_pandas()
    return pd.DataFrame(rows, columns=list(CHECKED_BARS_SCHEMA.names))
