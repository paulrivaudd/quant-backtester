"""Canonical on-disk schemas for the clean layer.

Everything here is a declaration, not behaviour: these are the contracts every
other module writes against. Two points carry the whole design.

**Availability is a property of the field, not of the row.** On session ``t+1``
of a Paris ETF the open is known at 09:00 local and the close at 17:30 local. A
single availability column per row would either hide the execution price from
the engine or leak the closing price to the strategy eight hours early, so
``bars`` carries one timestamp for the open and one for the rest.

**Nothing restated is stored.** ``adj_close`` is absent on purpose: a provider
rewrites it at every corporate action, so its value for a past date depends on
the day it was downloaded. Raw prices plus a corporate action table let the
reader adjust *as of* a decision instant instead.
"""

from __future__ import annotations

from enum import Enum
from typing import Final

import pyarrow as pa

TIMESTAMP_UTC: Final = pa.timestamp("us", tz="UTC")
"""Single timestamp type used everywhere. Microseconds, always UTC."""


class BarField(Enum):
    """A readable field of a BAR observation."""

    OPEN = "open"
    HIGH = "high"
    LOW = "low"
    CLOSE = "close"
    VOLUME = "volume"


AVAILABILITY_COLUMN: Final[dict[BarField, str]] = {
    BarField.OPEN: "open_available_at_utc",
    BarField.HIGH: "close_available_at_utc",
    BarField.LOW: "close_available_at_utc",
    BarField.CLOSE: "close_available_at_utc",
    BarField.VOLUME: "close_available_at_utc",
}
"""Which availability column gates which field.

The opening auction publishes the open alone. High, low, close and volume are
only final at the closing auction, so they are gated by the close timestamp.
"""


class ActionType(Enum):
    """Kind of corporate action."""

    SPLIT = "SPLIT"
    """``value`` is the split ratio: 4.0 for a 4-for-1."""

    DIVIDEND = "DIVIDEND"
    """``value`` is the cash amount per share, in the instrument currency."""


BARS_SCHEMA: Final = pa.schema(
    [
        pa.field("instrument_id", pa.string(), nullable=False),
        pa.field("session_date", pa.date32(), nullable=False),
        pa.field("open", pa.float64()),
        pa.field("high", pa.float64()),
        pa.field("low", pa.float64()),
        pa.field("close", pa.float64()),
        pa.field("volume", pa.float64()),
        pa.field("open_available_at_utc", TIMESTAMP_UTC, nullable=False),
        pa.field("close_available_at_utc", TIMESTAMP_UTC, nullable=False),
        pa.field("source", pa.string(), nullable=False),
        pa.field("source_fetch_id", pa.string(), nullable=False),
    ]
)
"""Clean bars. Prices are raw, unadjusted, in the instrument currency."""

LEVELS_SCHEMA: Final = pa.schema(
    [
        pa.field("instrument_id", pa.string(), nullable=False),
        pa.field("observation_date", pa.date32(), nullable=False),
        pa.field("value", pa.float64(), nullable=False),
        pa.field("available_at_utc", TIMESTAMP_UTC, nullable=False),
        pa.field("source", pa.string(), nullable=False),
        pa.field("source_fetch_id", pa.string(), nullable=False),
    ]
)
"""Clean levels: one published value per observation date."""

CORPORATE_ACTIONS_SCHEMA: Final = pa.schema(
    [
        pa.field("instrument_id", pa.string(), nullable=False),
        pa.field("action_type", pa.string(), nullable=False),
        pa.field("ex_date", pa.date32(), nullable=False),
        pa.field("value", pa.float64(), nullable=False),
        pa.field("available_at_utc", TIMESTAMP_UTC, nullable=False),
        pa.field("source", pa.string(), nullable=False),
        pa.field("source_fetch_id", pa.string(), nullable=False),
    ]
)
"""Corporate actions.

``available_at_utc`` is set to the ex-date close, not the announcement date,
which the provider does not give us. That is deliberately conservative: we learn
of a split later than the market did, so the backtest can never gain from it.
"""


class CheckStatus(Enum):
    """Outcome of cross-checking one session across sources."""

    CONFIRMED = "CONFIRMED"
    """Every source holding the session agrees within the declared tolerances."""

    SINGLE_SOURCE = "SINGLE_SOURCE"
    """Only one source holds the session: there is nothing to compare it with."""

    CONFLICT = "CONFLICT"
    """Two sources disagree beyond a tolerance, or only one of them has a value."""


CHECKED_BARS_SCHEMA: Final = pa.schema(
    [
        *BARS_SCHEMA,
        pa.field("check_status", pa.string(), nullable=False),
        pa.field("checked_sources", pa.string(), nullable=False),
        pa.field("checked_fetch_ids", pa.string(), nullable=False),
        pa.field("max_price_rel_diff", pa.float64()),
        pa.field("max_volume_rel_diff", pa.float64()),
    ]
)
"""Bars after cross-checking every source configured for an instrument.

The bar fields are the reference source's whenever it holds the session, so a
``CONFIRMED`` row is the reference bar with a second opinion attached, and
``source``/``source_fetch_id`` name the provider the values were taken from.
``checked_sources`` lists the sources holding the session, sorted and
comma-separated; ``checked_fetch_ids`` pairs each with its fetch as
``SOURCE:fetch_id``. The relative differences are the largest seen between any
two sources: ``NaN`` with a single source, ``inf`` when a value is missing on one
side only.
"""

REVISIONS_SCHEMA: Final = pa.schema(
    [
        pa.field("instrument_id", pa.string(), nullable=False),
        pa.field("table", pa.string(), nullable=False),
        pa.field("observation_date", pa.date32(), nullable=False),
        pa.field("field", pa.string(), nullable=False),
        pa.field("old_value", pa.float64()),
        pa.field("new_value", pa.float64()),
        pa.field("old_fetch_id", pa.string()),
        pa.field("new_fetch_id", pa.string(), nullable=False),
        pa.field("detected_at_utc", TIMESTAMP_UTC, nullable=False),
    ]
)
"""Detection log: the provider changed a value we had already stored.

This file records *what happened*; it never records what we decided. The
decision lives in ``metadata/accepted_revisions.toml``, in git, because it
changes past results and must be reviewable in a diff.
"""

VALIDATION_LOG_SCHEMA: Final = pa.schema(
    [
        pa.field("instrument_id", pa.string(), nullable=False),
        pa.field("checked_at_utc", TIMESTAMP_UTC, nullable=False),
        pa.field("code", pa.string(), nullable=False),
        pa.field("severity", pa.string(), nullable=False),
        pa.field("observation_date", pa.date32()),
        pa.field("message", pa.string(), nullable=False),
    ]
)
"""Persisted validation issues. A warning printed to stdout is a warning lost."""
