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


def _field_difference(bars: list[dict[str, Any]], field: str) -> float:
    """Return how far apart the sources holding a value for ``field`` are.

    Parameters
    ----------
    bars : list[dict[str, Any]]
        One canonical bar per source, all for the same session.
    field : str
        Field to compare.

    Returns
    -------
    float
        The largest pairwise relative difference between the values that are
        present; ``NaN`` when fewer than two sources hold one.

    Notes
    -----
    A value absent from one source is dropped rather than compared, so
    :func:`relative_difference` never meets a missing value here. An absence is
    not a disagreement: it says nothing about the value the other source holds,
    and treating it as an infinite difference used to discard a whole session
    because one provider served an incomplete bar. The field is reported as
    unconfirmed instead - see :func:`cross_check_bars`.
    """
    values = [value for value in (float(bar[field]) for bar in bars) if not math.isnan(value)]
    if len(values) < 2:
        return math.nan
    largest = 0.0
    for first in range(len(values)):
        for second in range(first + 1, len(values)):
            largest = max(largest, relative_difference(values[first], values[second]))
    return largest


def _is_complete(bar: Mapping[str, Any]) -> bool:
    """Return whether a bar holds every price field.

    Parameters
    ----------
    bar : Mapping[str, Any]
        One canonical bar.

    Returns
    -------
    bool
        ``True`` when open, high, low and close are all present. Volume is not
        part of it: a provider leaving it empty is ordinary and no price is
        derived from it.
    """
    return all(not math.isnan(float(bar[field])) for field in PRICE_FIELDS)


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


def _preferred_source(
    by_source: Mapping[str, dict[date, dict[str, Any]]],
    holders: list[str],
    reference_source: str,
    session: date,
) -> str:
    """Return the source whose row is stored for one session.

    Parameters
    ----------
    by_source : Mapping[str, dict[date, dict[str, Any]]]
        Every source's bars, indexed by session.
    holders : list[str]
        Sources holding this session, in source order.
    reference_source : str
        Source whose values are kept when it can be.
    session : date
        Session concerned.

    Returns
    -------
    str
        The reference source when it holds the session with a complete row;
        otherwise the first other holder whose row is complete; otherwise the
        reference source, or the first holder when it does not hold the session
        at all. A row that is missing a price everywhere is stored as it is,
        with the gap visible.

    Notes
    -----
    Verified live on 2026-09-18: Yahoo served CW8 on 2026-09-17 without a close
    while Euronext had the full bar. Keeping the reference's row regardless
    stored a ``NaN`` close and left the exchange's own number on disk, unused.
    """
    complete = [source for source in holders if _is_complete(by_source[source][session])]
    if reference_source in complete:
        return reference_source
    if complete:
        return complete[0]
    if reference_source in holders:
        return reference_source
    return holders[0]


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
        columns in ``CHECKED_BARS_SCHEMA`` order. Values come from the reference
        source when it holds the session with a complete row, and otherwise from
        the first other source that does - see :func:`_preferred_source`.

        Every field is compared on its own: a field two sources hold and
        disagree on beyond its tolerance lands in ``conflicting_fields``, a
        field fewer than two sources hold a value for lands in
        ``unconfirmed_fields``, and ``check_status`` summarises the two. An
        absence is never a disagreement, so an incomplete bar from one provider
        no longer condemns the fields the others agree on.

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
        conflicting: list[str] = []
        unconfirmed: list[str] = []
        price_differences: list[float] = []
        volume_differences: list[float] = []
        for field in (*PRICE_FIELDS, *VOLUME_FIELDS):
            is_price = field in PRICE_FIELDS
            difference = _field_difference(bars, field)
            if math.isnan(difference):
                unconfirmed.append(field)
                continue
            (price_differences if is_price else volume_differences).append(difference)
            tolerance = policy.price_rel_tolerance if is_price else policy.volume_rel_tolerance
            if difference > tolerance:
                conflicting.append(field)
        if conflicting:
            status = CheckStatus.CONFLICT
        elif len(unconfirmed) == len(PRICE_FIELDS) + len(VOLUME_FIELDS):
            status = CheckStatus.SINGLE_SOURCE
        else:
            status = CheckStatus.CONFIRMED
        # The values come from one source, so a row stays verifiable against a
        # single raw snapshot; a complete one is preferred to the reference's
        # own when the reference served a bar with a price missing.
        chosen_source = _preferred_source(by_source, holders, reference_source, session)
        row = {field: by_source[chosen_source][session][field] for field in BARS_SCHEMA.names}
        row["check_status"] = status.value
        row["checked_sources"] = ",".join(holders)
        row["checked_fetch_ids"] = ",".join(
            f"{source}:{by_source[source][session]['source_fetch_id']}" for source in holders
        )
        row["conflicting_fields"] = ",".join(sorted(conflicting))
        row["unconfirmed_fields"] = ",".join(sorted(unconfirmed))
        row["max_price_rel_diff"] = max(price_differences) if price_differences else math.nan
        row["max_volume_rel_diff"] = max(volume_differences) if volume_differences else math.nan
        rows.append(row)
    if not rows:
        return CHECKED_BARS_SCHEMA.empty_table().to_pandas()
    return pd.DataFrame(rows, columns=list(CHECKED_BARS_SCHEMA.names))
