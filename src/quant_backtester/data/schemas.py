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
    """``value`` is the split ratio: 4.0 for a 4-for-1, 0.125 for a 1-for-8 reverse
    split. Every holding is multiplied by it and every earlier price divided."""

    DIVIDEND = "DIVIDEND"
    """``value`` is the gross cash amount per share, in the instrument currency."""

    SPIN_OFF = "SPIN_OFF"
    """``value`` is the price adjustment factor: earlier prices are divided by it
    exactly as for a split, but no share was multiplied - the holder received
    stock in another company. Providers report it as a fractional split (Yahoo
    gives GE 1.281 for the GE HealthCare spin-off of 2023-01-04), so only a
    reviewed correction turns one into a ``SPIN_OFF``."""

    SPECIAL_DIVIDEND = "SPECIAL_DIVIDEND"
    """``value`` is the gross cash amount per share of a one-off distribution,
    adjusted for exactly like an ordinary dividend. Providers mix the two (Yahoo
    gives COST 15.00 on 2023-12-27 as a plain dividend), and a strategy that
    extrapolates a yield from one is extrapolating from an accident - so only a
    reviewed correction turns one into a ``SPECIAL_DIVIDEND``."""


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

VINTAGES_SCHEMA: Final = pa.schema(
    [
        pa.field("instrument_id", pa.string(), nullable=False),
        pa.field("observation_date", pa.date32(), nullable=False),
        pa.field("vintage_date", pa.date32(), nullable=False),
        pa.field("value", pa.float64(), nullable=True),
        pa.field("withdrawn", pa.bool_(), nullable=False),
        pa.field("available_at_utc", TIMESTAMP_UTC, nullable=False),
        pa.field("source", pa.string(), nullable=False),
        pa.field("source_fetch_id", pa.string(), nullable=False),
    ]
)
"""The archive of a restated series: one value per observation *and* vintage.

A level has one value per observation date. A vintage archive has as many as
there were restatements, and the pair ``(observation_date, vintage_date)`` is
what identifies a fact - US GDP for the first quarter of 2019 is 21 098.827 in
the vintage of 31 January 2020 and 21 115.309 in that of 30 June 2021, and both
are true of their day.

It is a table of its own rather than a column on the levels, because the two
obey different rules. A level may be revised by a provider and the revision
policy governs that; a vintage cannot, by construction - the archive of what
was known on a day does not change - so a value that moves under a pair is a
provider rewriting history, and is refused rather than merged.

``available_at_utc`` is the later of the observation's own release instant and
the vintage's: a number restated in June 2021 was not knowable in 2019, whatever
the observation it describes.

A vintage can also *withdraw* an observation an earlier one published - ALFRED
marks it ``.`` in that vintage's column. That is a row too, with
``withdrawn = True`` and no value: without it, the reader, taking the latest
vintage that holds each observation, would serve the older value as if the
withdrawal had never happened (audit A09). Only a cell the download actually
served becomes one - an observation outside the requested range is not
withdrawn, it was not asked about.
"""

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

``available_at_utc`` is the **open** of the ex-date. The raw open of that session
is already post-split and ex-dividend, so the action has to be knowable no later
than the first price it affects: stamped at the close, a 4-for-1 split would
show a strategy trading that open a -75% gap that never happened. The
announcement date, which the provider does not give us, is earlier still, so
this instant never lets a backtest use information the market did not have.

Only the ex-date is known: no declaration, record or payment date. Cash reaches
the holder weeks later, and ``value`` is a **gross** amount for a dividend -
withholding depends on the account and the treaty, so it is applied downstream
and never stored here.
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
        pa.field("conflicting_fields", pa.string(), nullable=False),
        pa.field("unconfirmed_fields", pa.string(), nullable=False),
        pa.field("max_price_rel_diff", pa.float64()),
        pa.field("max_volume_rel_diff", pa.float64()),
    ]
)
"""Bars after cross-checking every source configured for an instrument.

The bar fields come from the reference source whenever it holds the session with
a complete row, so a ``CONFIRMED`` row is normally the reference bar with a
second opinion attached, and ``source``/``source_fetch_id`` name the provider
the values were taken from. ``checked_sources`` lists the sources holding the
session, sorted and comma-separated; ``checked_fetch_ids`` pairs each with its
fetch as ``SOURCE:fetch_id``.

**Agreement is a property of the field, not of the row**, for the same reason
availability is. Two providers routinely agree on the close of a session to the
last cent and differ on its low, and withholding the close because of the low
would hide a good number behind a bad one. ``conflicting_fields`` lists the
fields two sources hold and disagree on beyond the declared tolerance;
``unconfirmed_fields`` lists those fewer than two sources hold a value for, so a
field nobody could corroborate is never mistaken for one that was. Both are
sorted, comma-separated, and empty strings when they hold nothing.
``check_status`` summarises them: ``CONFLICT`` as soon as one field conflicts,
``SINGLE_SOURCE`` when no field could be compared at all, ``CONFIRMED``
otherwise.

The relative differences are the largest seen between any two sources over the
fields that could be compared, and ``NaN`` when none could be.
"""

REVISIONS_SCHEMA: Final = pa.schema(
    [
        pa.field("instrument_id", pa.string(), nullable=False),
        pa.field("source", pa.string(), nullable=False),
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
"""Detection log: a provider changed a value we had already stored.

``source`` names which one. A check source has a canonical series of its own and
the same policy applies to it, so a restatement by Euronext is logged here
exactly like one by Yahoo - and, unaccepted, ignored exactly like one.


This file records *what happened*; it never records what we decided. The
decision lives in ``metadata/accepted_revisions.toml``, in git, because it
changes past results and must be reviewable in a diff.
"""

APPLIED_FETCHES_SCHEMA: Final = pa.schema(
    [
        pa.field("instrument_id", pa.string(), nullable=False),
        pa.field("source", pa.string(), nullable=False),
        pa.field("fetch_id", pa.string(), nullable=False),
        pa.field("applied_at_utc", TIMESTAMP_UTC, nullable=False),
    ]
)
"""Which archived fetches actually shaped the clean layer.

A raw snapshot is written before the pipeline that consumes it runs, so that a
download which then fails validation is kept rather than lost - it is precisely
the one to re-examine. The consequence is that ``raw/`` holds fetches the live
path never applied, and replaying them all would not rebuild what the live path
built: the first value stored wins, so a snapshot that never reached ``clean/``
would win over the one that did.

A fetch is recorded here once its promotion has completed. ``raw/`` keeps
everything, this says what counts.
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
