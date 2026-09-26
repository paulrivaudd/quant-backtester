"""Normalisation: provider frames -> canonical schemas.

This is the only layer that knows a provider's column names, its date handling
and its sign conventions. It is also where availability is stamped: a BAR gets
its two timestamps from the venue calendar, a LEVEL gets its single timestamp
from the instrument's publication rule.

Normalisation is a pure function of (raw frame, instrument, calendar). It must
never look at the clock, the filesystem or the network - that is what makes
``clean/`` rebuildable from ``raw/`` and the test of exercise 9.4 possible.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

import pandas as pd
import pyarrow as pa

from quant_backtester.data.calendars import TradingCalendar
from quant_backtester.data.instruments import (
    DataType,
    Instrument,
    PublicationRule,
    VintagePolicy,
)
from quant_backtester.data.schemas import (
    BARS_SCHEMA,
    CORPORATE_ACTIONS_SCHEMA,
    LEVELS_SCHEMA,
    VINTAGES_SCHEMA,
    ActionType,
)
from quant_backtester.data.sources.alfred import vintage_column
from quant_backtester.data.sources.base import RawDownload


@dataclass(frozen=True, slots=True)
class RejectedRows:
    """Rows a normalizer refused to store, kept apart so none disappears in silence.

    Attributes
    ----------
    non_session : tuple[date, ...]
        Dates the provider sent a row for although the venue held no session
        then. They carry no availability instant, so they cannot be stored.
    unlisted : tuple[date, ...]
        Dates outside the instrument's listing window. Before a fund lists, a
        provider still serves a value - a net asset value repeated with no
        volume - and stored as a bar it becomes a price nobody could trade.
    unpublished : tuple[date, ...]
        Dates whose value was not yet public when the fetch happened. A daily
        bar downloaded mid-session is a snapshot of a price still moving;
        stamped with the official closing instant, it would freeze an intraday
        value as the session's canonical close.
    """

    non_session: tuple[date, ...] = ()
    unlisted: tuple[date, ...] = ()
    unpublished: tuple[date, ...] = ()

    def __bool__(self) -> bool:
        """Return whether anything was rejected at all."""
        return bool(self.non_session or self.unlisted or self.unpublished)


@dataclass(frozen=True, slots=True)
class NormalizedData:
    """Canonical frames produced from one raw download.

    Attributes
    ----------
    bars : pd.DataFrame | None
        Rows matching :data:`~quant_backtester.data.schemas.BARS_SCHEMA`.
    levels : pd.DataFrame | None
        Rows matching :data:`~quant_backtester.data.schemas.LEVELS_SCHEMA`.
    vintages : pd.DataFrame | None
        Rows matching :data:`~quant_backtester.data.schemas.VINTAGES_SCHEMA`,
        for a published series read as of each decision rather than pinned to
        one vintage.
    corporate_actions : pd.DataFrame | None
        Rows matching
        :data:`~quant_backtester.data.schemas.CORPORATE_ACTIONS_SCHEMA`.
    rejected : RejectedRows
        Rows the normalizer could not store, by reason. The updater reports
        them rather than letting them disappear.
    """

    bars: pd.DataFrame | None = None
    levels: pd.DataFrame | None = None
    vintages: pd.DataFrame | None = None
    corporate_actions: pd.DataFrame | None = None
    rejected: RejectedRows = RejectedRows()


def bar_availability(session_date: date, calendar: TradingCalendar) -> tuple[datetime, datetime]:
    """Return the availability instants of a bar's open and close fields.

    Parameters
    ----------
    session_date : date
        Session the bar describes.
    calendar : TradingCalendar
        Venue calendar.

    Returns
    -------
    tuple[datetime, datetime]
        ``(open_available_at_utc, close_available_at_utc)``, both UTC-aware.

    Raises
    ------
    ValueError
        If the venue was closed on ``session_date`` - a bar on a non-session is
        a data error, not something to silently accept.

    Notes
    -----
    Exercice 5.1 (facile, mais c'est la fonction centrale du module). Elle est
    l'endroit unique ou la disponibilite par champ prend corps ; tout le reste du
    systeme en depend.
    """
    # 1. Demander la séance au calendrier (il gère fuseau, heure d'été, demi-séance,
    #    couverture et TypeError : ne rien recalculer ici)
    session = calendar.session(session_date)
    # 2. Pas de séance -> ValueError avec calendar.calendar_id et la date dans le message
    if session is None:
        raise ValueError(f"Venue {calendar.calendar_id} was closed on {session_date}")
    # 3. Renvoyer les deux instants UTC de la séance
    return session.open_utc, session.close_utc


BAR_VALUE_FIELDS: tuple[str, ...] = ("open", "high", "low", "close", "volume")
"""Canonical bar fields a provider supplies; the other columns are stamped here."""

YAHOO_BAR_COLUMNS: dict[str, str] = {
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Volume": "volume",
}
"""Yahoo bar column -> canonical field. ``Adj Close`` is absent on purpose: it is dropped."""

YAHOO_ACTION_COLUMNS: dict[str, ActionType] = {
    "Dividends": ActionType.DIVIDEND,
    "Stock Splits": ActionType.SPLIT,
}
"""Yahoo corporate action column -> action type. ``0.0`` means no event that day."""

EURONEXT_DATE_COLUMN = "Date"
"""Session column of a Euronext export."""

EURONEXT_DATE_FORMAT = "%d/%m/%Y"
"""Date format of a Euronext export."""

EURONEXT_BAR_COLUMNS: dict[str, str] = {
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Number of Shares": "volume",
}
"""Euronext column -> canonical field. ``Last``, trades, turnover and VWAP are dropped."""

FRED_DATE_COLUMN = "observation_date"
"""Date column of a ``fredgraph.csv`` export."""

FRED_MISSING_MARKERS = frozenset({"", "."})
"""FRED cells meaning "no observation": empty today, ``"."`` in older exports."""

ECB_KEY_COLUMN = "KEY"
"""Series key column of an ECB ``csvdata`` answer."""

ECB_DATE_COLUMN = "TIME_PERIOD"
"""Observation date column of an ECB ``csvdata`` answer."""

ECB_VALUE_COLUMN = "OBS_VALUE"
"""Value column of an ECB ``csvdata`` answer."""

ECB_MISSING_MARKERS = frozenset({"", "NaN"})
"""ECB cells meaning "no observation"."""


def _empty_frame(schema: pa.Schema) -> pd.DataFrame:
    """Return a zero-row frame carrying the columns and dtypes of ``schema``."""
    return schema.empty_table().to_pandas()


def _finite_number(text: str, what: str) -> float:
    """Return a published cell as a finite float.

    Parameters
    ----------
    text : str
        Cell as the provider sent it.
    what : str
        Description of the cell, quoted in the error message.

    Returns
    -------
    float
        The value.

    Raises
    ------
    ValueError
        If ``text`` is not a number, or is ``nan`` or infinite.
    """
    try:
        value = float(text)
    except ValueError:
        raise ValueError(f"{what} is {text!r}, not a number") from None
    if not math.isfinite(value):
        raise ValueError(f"{what} is {text!r}, not a finite number")
    return value


def _iso_date(text: str, what: str) -> date:
    """Return a published ``YYYY-MM-DD`` cell as a date.

    Parameters
    ----------
    text : str
        Cell as the provider sent it.
    what : str
        Description of the cell, quoted in the error message.

    Returns
    -------
    date
        The date.

    Raises
    ------
    ValueError
        If ``text`` is not an ISO date.
    """
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise ValueError(f"{what} is {text!r}, not an ISO date") from None


def _require_same_download(
    normalizer: str, source_id: str, instrument: Instrument, download: RawDownload
) -> None:
    """Reject a download from another source or for another instrument.

    Parameters
    ----------
    normalizer : str
        Normalizer name, quoted in the error message.
    source_id : str
        Source the normalizer handles.
    instrument : Instrument
        Instrument the caller asked for.
    download : RawDownload
        Download to normalise.

    Raises
    ------
    ValueError
        If ``download`` comes from another source or belongs to another
        instrument.
    """
    if download.source != source_id:
        raise ValueError(f"{normalizer} got a download from {download.source}")
    if download.instrument_id != instrument.id:
        raise ValueError(
            f"{normalizer} got a download for {download.instrument_id}, "
            f"but was asked to normalize {instrument.id}"
        )


def _require_bar_call(
    normalizer: str,
    source_id: str,
    instrument: Instrument,
    download: RawDownload,
    calendar: TradingCalendar | None,
) -> TradingCalendar:
    """Reject a bar normalisation called with inconsistent arguments.

    Parameters
    ----------
    normalizer : str
        Normalizer name, quoted in the error message.
    source_id : str
        Source the normalizer handles.
    instrument : Instrument
        Instrument the caller asked for.
    download : RawDownload
        Download to normalise.
    calendar : TradingCalendar | None
        Venue calendar passed by the caller.

    Returns
    -------
    TradingCalendar
        ``calendar``, now known not to be ``None``.

    Raises
    ------
    ValueError
        If ``calendar`` is missing, the download comes from another source or
        belongs to another instrument, or the instrument is not a ``BAR``.
    """
    if calendar is None:
        raise ValueError(f"{normalizer} needs a calendar")
    _require_same_download(normalizer, source_id, instrument, download)
    if instrument.data_type != DataType.BAR:
        raise ValueError(
            f"{normalizer} only handles BAR instruments, "
            f"{instrument.id} is {instrument.data_type.value}"
        )
    return calendar


def _require_level_call(
    normalizer: str, source_id: str, instrument: Instrument, download: RawDownload
) -> PublicationRule:
    """Reject a level normalisation called with inconsistent arguments.

    Parameters
    ----------
    normalizer : str
        Normalizer name, quoted in the error message.
    source_id : str
        Source the normalizer handles.
    instrument : Instrument
        Instrument the caller asked for.
    download : RawDownload
        Download to normalise.

    Returns
    -------
    PublicationRule
        The instrument's publication rule.

    Raises
    ------
    ValueError
        If the download comes from another source or belongs to another
        instrument, or the instrument is not a ``LEVEL``.
    """
    _require_same_download(normalizer, source_id, instrument, download)
    if instrument.data_type != DataType.LEVEL or instrument.publication_rule is None:
        raise ValueError(
            f"{normalizer} only handles LEVEL instruments, "
            f"{instrument.id} is {instrument.data_type.value}"
        )
    return instrument.publication_rule


def _session_dates(index: pd.Index, calendar: TradingCalendar) -> list[date]:
    """Return the exchange-local session date of each entry of a Yahoo index.

    A tz-aware index is converted to the venue's zone before ``.date()`` is
    taken: a Paris midnight read in UTC is 22:00 on the day before. A naive index
    already holds local dates.

    Parameters
    ----------
    index : pd.Index
        Index of a raw Yahoo frame.
    calendar : TradingCalendar
        Venue calendar, for its timezone.

    Returns
    -------
    list[date]
        One exchange-local date per index entry, in index order.

    Raises
    ------
    ValueError
        If ``index`` is not a ``DatetimeIndex`` or holds a missing timestamp.
    """
    if not isinstance(index, pd.DatetimeIndex):
        raise ValueError(f"Yahoo index must be a DatetimeIndex, got {type(index).__name__}")
    if index.hasnans:
        raise ValueError("Yahoo index holds a missing timestamp")
    local = index.tz_convert(calendar.timezone) if index.tz is not None else index
    return [timestamp.date() for timestamp in local]


def _requested_date(download: RawDownload, key: str) -> date:
    """Return a date the adapter recorded in ``download.request``.

    Parameters
    ----------
    download : RawDownload
        Provider response.
    key : str
        Request key holding an ISO date, e.g. ``"start"``.

    Returns
    -------
    date
        The recorded date.

    Raises
    ------
    ValueError
        If the key is absent or not an ISO date string.
    """
    value = download.request.get(key)
    if not isinstance(value, str):
        raise ValueError(f"Request of fetch {download.fetch_id} has no {key!r} date")
    return _iso_date(value, f"Request {key!r} of fetch {download.fetch_id}")


def _bars_frame(
    instrument: Instrument,
    download: RawDownload,
    calendar: TradingCalendar,
    session_dates: Sequence[date],
    values: Mapping[str, list[float]],
) -> tuple[pd.DataFrame, RejectedRows]:
    """Assemble canonical bars once a provider's columns are mapped to fields.

    Parameters
    ----------
    instrument : Instrument
        Instrument the bars belong to.
    download : RawDownload
        Download they come from, for the lineage columns.
    calendar : TradingCalendar
        Venue calendar: availability instants.
    session_dates : Sequence[date]
        One session per bar.
    values : Mapping[str, list[float]]
        Every field of :data:`BAR_VALUE_FIELDS` -> values aligned with
        ``session_dates``.

    Returns
    -------
    tuple[pd.DataFrame, RejectedRows]
        The canonical bars, in ``BARS_SCHEMA`` column order and in the order of
        ``session_dates``, and the dates dropped with the reason for each.

    Raises
    ------
    ValueError
        If ``values`` does not supply exactly the bar fields or a session
        appears twice.
    CalendarCoverageError
        If a bar falls outside the period the calendar covers.
    """
    if sorted(values) != sorted(BAR_VALUE_FIELDS):
        raise ValueError(f"Bar values must be exactly {BAR_VALUE_FIELDS}, got {sorted(values)}")
    repeated = sorted(day for day, count in Counter(session_dates).items() if count > 1)
    if repeated:
        raise ValueError(
            f"{download.source} bars of {instrument.id} repeat session(s): "
            f"{', '.join(map(str, repeated))}"
        )
    # A bar is stored only once every one of its fields is knowable. Three
    # reasons to refuse one, each named rather than guessed at:
    #
    #   - outside the listing window, where a provider still serves a value the
    #     market never made: Yahoo gives CW8 74 flat net asset values before it
    #     traded, from 2018-01-02 to 2018-04-17;
    #   - the venue held no session, so there is no instant at which the bar
    #     became knowable (Yahoo serves one for CW8 on 2019-12-25, a Christmas
    #     Euronext was shut);
    #   - the session had not closed when the fetch happened. Such a row is an
    #     intraday snapshot; stamped with the official closing instant it would
    #     become the session's canonical close and, stored first, win over the
    #     real one for good.
    #
    # Outside the calendar's coverage the calendar still raises - there we do
    # not know whether the venue traded, which is a different problem.
    kept: list[int] = []
    non_session: list[date] = []
    unlisted: list[date] = []
    unpublished: list[date] = []
    for index, day in enumerate(session_dates):
        if not instrument.is_listed(day):
            unlisted.append(day)
        elif not calendar.is_open(day):
            non_session.append(day)
        elif bar_availability(day, calendar)[1] > download.retrieved_at_utc:
            unpublished.append(day)
        else:
            kept.append(index)
    rejected = RejectedRows(
        non_session=tuple(non_session),
        unlisted=tuple(unlisted),
        unpublished=tuple(unpublished),
    )
    days = [session_dates[index] for index in kept]
    availability = [bar_availability(day, calendar) for day in days]
    row_count = len(days)
    columns: dict[str, object] = {
        "instrument_id": [instrument.id] * row_count,
        "session_date": days,
        **{field: [column[index] for index in kept] for field, column in values.items()},
        "open_available_at_utc": [open_at for open_at, _ in availability],
        "close_available_at_utc": [close_at for _, close_at in availability],
        "source": [download.source] * row_count,
        "source_fetch_id": [download.fetch_id] * row_count,
    }
    return pd.DataFrame(columns, columns=list(BARS_SCHEMA.names)), rejected


def _levels_frame(
    instrument: Instrument,
    download: RawDownload,
    rule: PublicationRule,
    observations: Mapping[date, float],
    calendar: TradingCalendar | None = None,
) -> tuple[pd.DataFrame, RejectedRows]:
    """Assemble canonical levels, each stamped by the publication rule.

    Parameters
    ----------
    instrument : Instrument
        Instrument the levels belong to.
    download : RawDownload
        Download they come from, for the lineage columns.
    rule : PublicationRule
        When each observation became public.
    observations : Mapping[date, float]
        Published value per observation date.
    calendar : TradingCalendar | None
        Calendar the rule counts its lag on; required as soon as the rule has
        one, ignored for a same-day release.

    Returns
    -------
    tuple[pd.DataFrame, RejectedRows]
        Levels sorted by ``observation_date``, columns in ``LEVELS_SCHEMA``
        order, and the observations dropped with the reason for each.

    Notes
    -----
    A published series has no session, so only two of the three reasons apply:
    an observation outside the listing window, and one whose release time had
    not come when the fetch happened. FRED serves the latter - a rate for today
    appears in the file before the lag its rule declares has elapsed.
    """
    if not observations:
        return _empty_frame(LEVELS_SCHEMA), RejectedRows()
    kept: dict[date, float] = {}
    unlisted: list[date] = []
    unpublished: list[date] = []
    for day in sorted(observations):
        if not instrument.is_listed(day):
            unlisted.append(day)
        elif rule.available_at(day, calendar) > download.retrieved_at_utc:
            unpublished.append(day)
        else:
            kept[day] = observations[day]
    rejected = RejectedRows(unlisted=tuple(unlisted), unpublished=tuple(unpublished))
    observations = kept
    if not observations:
        return _empty_frame(LEVELS_SCHEMA), rejected
    dates = sorted(observations)
    columns: dict[str, object] = {
        "instrument_id": [instrument.id] * len(dates),
        "observation_date": dates,
        "value": [observations[day] for day in dates],
        "available_at_utc": [rule.available_at(day, calendar) for day in dates],
        "source": [download.source] * len(dates),
        "source_fetch_id": [download.fetch_id] * len(dates),
    }
    return pd.DataFrame(columns, columns=list(LEVELS_SCHEMA.names)), rejected


def _vintages_frame(
    instrument: Instrument,
    download: RawDownload,
    rule: PublicationRule,
    by_vintage: Mapping[date, Mapping[date, float | None]],
    calendar: TradingCalendar | None = None,
) -> tuple[pd.DataFrame, RejectedRows]:
    """Assemble a vintage archive: one row per observation and per vintage.

    Parameters
    ----------
    instrument : Instrument
        Instrument the rows belong to.
    download : RawDownload
        Download they come from, for the lineage columns.
    rule : PublicationRule
        When an observation, and a vintage, became public.
    by_vintage : Mapping[date, Mapping[date, float | None]]
        Published value per observation date, per vintage date; ``None`` for a
        cell the vintage served as missing. Such a cell, for an observation no
        later than the vintage, is a withdrawal and becomes a row with
        ``withdrawn = True``.
    calendar : TradingCalendar | None
        Calendar the rule counts its lag on.

    Returns
    -------
    tuple[pd.DataFrame, RejectedRows]
        Rows of :data:`~quant_backtester.data.schemas.VINTAGES_SCHEMA`, sorted
        by observation date then vintage date, and what was dropped.

    Notes
    -----
    Availability is the later of two instants: the observation's own release,
    and the vintage's. The second is what makes this a point-in-time series -
    a number restated in June 2021 was not knowable in 2019, whatever quarter
    it describes - and taking the later of the two rather than the vintage
    alone keeps the first release honest as well: the vintage of a day carries
    observations published that morning, and they were not knowable the evening
    before.

    A vintage that did not exist when the fetch ran is refused by the adapter,
    so nothing here has to guess at one.
    """
    rows: list[tuple[date, date, float | None, datetime]] = []
    unlisted: set[date] = set()
    unpublished: set[date] = set()
    for vintage in sorted(by_vintage):
        vintage_at = rule.available_at(vintage, calendar)
        for day in sorted(by_vintage[vintage]):
            value = by_vintage[vintage][day]
            if value is None and day > vintage:
                # Not withdrawn: a vintage cannot hold what happened after it.
                continue
            if not instrument.is_listed(day):
                if value is not None:
                    unlisted.add(day)
                continue
            available_at = max(rule.available_at(day, calendar), vintage_at)
            if available_at > download.retrieved_at_utc:
                if value is not None:
                    unpublished.add(day)
                continue
            rows.append((day, vintage, value, available_at))
    rejected = RejectedRows(
        unlisted=tuple(sorted(unlisted)), unpublished=tuple(sorted(unpublished))
    )
    if not rows:
        return _empty_frame(VINTAGES_SCHEMA), rejected
    rows.sort(key=lambda row: (row[0], row[1]))
    columns: dict[str, object] = {
        "instrument_id": [instrument.id] * len(rows),
        "observation_date": [row[0] for row in rows],
        "vintage_date": [row[1] for row in rows],
        "value": [float("nan") if row[2] is None else row[2] for row in rows],
        "withdrawn": [row[2] is None for row in rows],
        "available_at_utc": [row[3] for row in rows],
        "source": [download.source] * len(rows),
        "source_fetch_id": [download.fetch_id] * len(rows),
    }
    return pd.DataFrame(columns, columns=list(VINTAGES_SCHEMA.names)), rejected


def _normalize_yahoo_bars(
    instrument: Instrument, download: RawDownload, calendar: TradingCalendar
) -> tuple[pd.DataFrame, RejectedRows]:
    """Turn a raw Yahoo ``history`` frame into rows of ``BARS_SCHEMA``.

    Parameters
    ----------
    instrument : Instrument
        Instrument the download belongs to.
    download : RawDownload
        Raw Yahoo bars.
    calendar : TradingCalendar
        Venue calendar: session dates and availability instants.

    Returns
    -------
    pd.DataFrame
        One row per session, columns in ``BARS_SCHEMA`` order. Empty, with the
        columns, when Yahoo returned no bar.

    Raises
    ------
    ValueError
        If a bar column is missing, the index is unusable, a session appears
        twice, or a row falls on a day the venue was closed.
    CalendarCoverageError
        If a row falls outside the period the calendar covers.
    """
    raw = download.frame
    if raw.empty:
        return _empty_frame(BARS_SCHEMA), RejectedRows()
    missing = sorted(set(YAHOO_BAR_COLUMNS) - set(raw.columns))
    if missing:
        raise ValueError(f"Yahoo bars of {instrument.id} lack column(s): {', '.join(missing)}")
    session_dates = _session_dates(raw.index, calendar)
    # to_numpy leaves Yahoo's index behind; float64 matches the schema, volume included.
    values = {
        field: raw[column].to_numpy(dtype="float64").tolist()
        for column, field in YAHOO_BAR_COLUMNS.items()
    }
    return _bars_frame(instrument, download, calendar, session_dates, values)


def _later_split_factor(position: int, ex_dates: Sequence[date], splits: Sequence[float]) -> float:
    """Return the product of the split ratios dated strictly after one row.

    Yahoo divides a past dividend by every later split ratio: AAPL's 0.77 of
    February 2020 is served as 0.1925 since the 4-for-1 split of August 2020.
    Multiplying by this product gives back the cash amount actually paid, the
    same whichever side of the split the data was fetched on.

    Parameters
    ----------
    position : int
        Row of the dividend.
    ex_dates : Sequence[date]
        Ex-date of every row.
    splits : Sequence[float]
        Split ratio of every row, ``0.0`` for none.

    Returns
    -------
    float
        ``1.0`` when no split follows the row.
    """
    factor = 1.0
    for other, ratio in enumerate(splits):
        if ratio > 0 and ex_dates[other] > ex_dates[position]:
            factor *= ratio
    return factor


def _normalize_yahoo_actions(
    instrument: Instrument, download: RawDownload, calendar: TradingCalendar
) -> tuple[pd.DataFrame, RejectedRows]:
    """Turn a raw Yahoo ``actions`` frame into rows of ``CORPORATE_ACTIONS_SCHEMA``.

    Yahoo sends the whole history (``period="max"``): only ex-dates inside the
    requested ``[start, end_inclusive]`` are kept, and they are filtered before
    any calendar lookup, since old ex-dates lie outside the calendar coverage.
    One Yahoo row yields zero, one or two canonical rows, ``0.0`` meaning no
    event. Yahoo omits a column that never held an event (SPY has no
    ``Stock Splits`` column, checked on 2026-09-13): an absent column counts as
    zeros. Dividends are multiplied back by the later splits Yahoo divided them
    by (see :func:`_later_split_factor`), and each action becomes available at
    the open of its ex-date, together with the first price it affects.

    Parameters
    ----------
    instrument : Instrument
        Instrument the download belongs to.
    download : RawDownload
        Raw Yahoo corporate actions.
    calendar : TradingCalendar
        Venue calendar: ex-dates and availability instants.

    Returns
    -------
    pd.DataFrame
        One row per event, columns in ``CORPORATE_ACTIONS_SCHEMA`` order. Empty,
        with the columns, when no event falls inside the requested range.

    Raises
    ------
    ValueError
        If the frame has no action column at all, a request date is missing,
        the index is unusable, any value is negative or missing (a later split
        scales the dividends before it, so every row counts), or an event falls
        on a day the venue was closed.
    CalendarCoverageError
        If an event inside the requested range falls outside the calendar
        coverage.
    """
    raw = download.frame
    if raw.empty:
        return _empty_frame(CORPORATE_ACTIONS_SCHEMA), RejectedRows()
    if not any(column in raw.columns for column in YAHOO_ACTION_COLUMNS):
        raise ValueError(
            f"Yahoo actions of {instrument.id} have none of the columns "
            f"{', '.join(YAHOO_ACTION_COLUMNS)}: {', '.join(map(str, raw.columns))}"
        )
    start = _requested_date(download, "start")
    end = _requested_date(download, "end_inclusive")
    non_session: list[date] = []
    unlisted: list[date] = []
    unpublished: list[date] = []
    ex_dates = _session_dates(raw.index, calendar)
    # Yahoo drops a column that never held an event: absent means zeros, not an error.
    values: dict[str, list[float]] = {
        column: (
            raw[column].to_numpy(dtype="float64").tolist()
            if column in raw.columns
            else [0.0] * len(ex_dates)
        )
        for column in YAHOO_ACTION_COLUMNS
    }
    for column, column_values in values.items():
        for position, value in enumerate(column_values):
            if math.isnan(value) or value < 0:
                raise ValueError(
                    f"Yahoo {column} of {instrument.id} on {ex_dates[position]} is {value}"
                )
    rows: list[dict[str, object]] = []
    for position, ex_date in enumerate(ex_dates):
        if not start <= ex_date <= end:
            continue
        events: list[tuple[ActionType, float]] = []
        for column, action_type in YAHOO_ACTION_COLUMNS.items():
            value = values[column][position]
            if value == 0:
                continue
            if action_type is ActionType.DIVIDEND:
                value *= _later_split_factor(position, ex_dates, values["Stock Splits"])
            events.append((action_type, value))
        if not events:
            continue
        if not instrument.is_listed(ex_date):
            # The instrument did not exist then: the event belongs to another
            # history, or the provider dated it wrong.
            unlisted.append(ex_date)
            continue
        if not calendar.is_open(ex_date):
            # No session, no open to be adjusted at: the event cannot be dated.
            non_session.append(ex_date)
            continue
        # The ex-date open is already adjusted, so the action must be known by
        # then: stamped at the close, a 4-for-1 split would show a strategy
        # trading that open a -75% gap that never happened.
        open_at, _ = bar_availability(ex_date, calendar)
        if open_at > download.retrieved_at_utc:
            # An announced but not yet effective event. Storing it would let a
            # decision taken before the ex-date adjust prices for it.
            unpublished.append(ex_date)
            continue
        for action_type, value in events:
            rows.append(
                {
                    "instrument_id": instrument.id,
                    "action_type": action_type.value,
                    "ex_date": ex_date,
                    "value": value,
                    "available_at_utc": open_at,
                    "source": download.source,
                    "source_fetch_id": download.fetch_id,
                }
            )
    rejected = RejectedRows(
        non_session=tuple(non_session),
        unlisted=tuple(unlisted),
        unpublished=tuple(unpublished),
    )
    if not rows:
        return _empty_frame(CORPORATE_ACTIONS_SCHEMA), rejected
    return pd.DataFrame(rows, columns=list(CORPORATE_ACTIONS_SCHEMA.names)), rejected


def _normalize_euronext_bars(
    instrument: Instrument, download: RawDownload, calendar: TradingCalendar
) -> tuple[pd.DataFrame, RejectedRows]:
    """Turn a raw Euronext export into rows of ``BARS_SCHEMA``.

    Parameters
    ----------
    instrument : Instrument
        Instrument the download belongs to.
    download : RawDownload
        Raw Euronext rows, every cell a string, newest first.
    calendar : TradingCalendar
        Venue calendar: availability instants.

    Returns
    -------
    pd.DataFrame
        One row per session, oldest first, columns in ``BARS_SCHEMA`` order.
        An empty price cell becomes ``NaN``; judging the gap is the validator's
        job.

    Raises
    ------
    ValueError
        If a column is missing, a date is not ``dd/mm/yyyy``, a cell is neither
        empty nor a finite number, a session appears twice, or a row falls on a
        day the venue was closed.
    CalendarCoverageError
        If a row falls outside the period the calendar covers.
    """
    raw = download.frame
    if raw.empty:
        return _empty_frame(BARS_SCHEMA), RejectedRows()
    missing = sorted({EURONEXT_DATE_COLUMN, *EURONEXT_BAR_COLUMNS} - set(raw.columns))
    if missing:
        raise ValueError(f"Euronext bars of {instrument.id} lack column(s): {', '.join(missing)}")
    parsed: list[tuple[date, dict[str, float]]] = []
    for record in raw.to_dict("records"):
        cells = {str(column): str(value) for column, value in record.items()}
        text_date = cells[EURONEXT_DATE_COLUMN]
        try:
            session = datetime.strptime(text_date, EURONEXT_DATE_FORMAT).date()
        except ValueError:
            raise ValueError(
                f"Euronext date of {instrument.id} is {text_date!r}, not dd/mm/yyyy"
            ) from None
        fields: dict[str, float] = {}
        for column, field in EURONEXT_BAR_COLUMNS.items():
            text = cells[column].strip()
            what = f"Euronext {column} of {instrument.id} on {session}"
            fields[field] = math.nan if text == "" else _finite_number(text, what)
        parsed.append((session, fields))
    # Euronext serves the newest session first.
    parsed.sort(key=lambda row: row[0])
    session_dates = [session for session, _ in parsed]
    values = {field: [fields[field] for _, fields in parsed] for field in BAR_VALUE_FIELDS}
    return _bars_frame(instrument, download, calendar, session_dates, values)


class Normalizer(Protocol):
    """Turn one provider's frames into canonical ones."""

    source_id: str

    def normalize(
        self,
        instrument: Instrument,
        download: RawDownload,
        calendar: TradingCalendar | None = None,
    ) -> NormalizedData:
        """Convert a raw download to canonical frames.

        Parameters
        ----------
        instrument : Instrument
            Instrument the download belongs to.
        download : RawDownload
            Provider response.
        calendar : TradingCalendar | None
            Required for ``BAR`` instruments, unused for ``LEVEL`` ones.

        Returns
        -------
        NormalizedData
            Canonical frames, columns and dtypes matching the schemas.
        """
        ...


class YahooNormalizer:
    """Normalise Yahoo Finance frames."""

    source_id = "YAHOO"

    def normalize(
        self,
        instrument: Instrument,
        download: RawDownload,
        calendar: TradingCalendar | None = None,
    ) -> NormalizedData:
        """Convert Yahoo bars and actions to canonical frames.

        Parameters
        ----------
        instrument : Instrument
            Instrument the download belongs to.
        download : RawDownload
            Provider response.
        calendar : TradingCalendar | None
            Venue calendar; required here.

        Returns
        -------
        NormalizedData
            Canonical ``bars`` for a ``history`` download, canonical
            ``corporate_actions`` for an ``actions`` download; the other fields
            are ``None``.

        Raises
        ------
        ValueError
            If ``calendar`` is missing, the download belongs to another source
            or instrument, the instrument is not a ``BAR``, or the raw frame is
            malformed or dated on a day the venue was closed.
        CalendarCoverageError
            If a row falls outside the period the calendar covers.

        Notes
        -----
        Exercice 5.2 (moyen). Points de vigilance :

        - ``Open/High/Low/Close/Volume`` -> minuscules ; ``Adj Close`` est
          **jete** : c'est une serie reecrite retroactivement, elle n'a aucune
          place dans le clean.
        - L'index Yahoo devient ``session_date`` ; s'il est tz-aware, convertis
          d'abord vers le fuseau de la place avant de prendre ``.date()``, sinon
          tu decales les seances d'un jour selon l'heure.
        - Une ligne dont la seance n'existe pas au calendrier doit lever, pas
          etre silencieusement gardee.
        - Recopie ``source`` et ``source_fetch_id`` sur chaque ligne : c'est la
          tracabilite d'une valeur vers le fichier brut exact qui l'a produite.
        """
        venue = _require_bar_call("YahooNormalizer", self.source_id, instrument, download, calendar)
        # Bars and corporate actions share the YAHOO source id: the request tells them apart.
        if download.request.get("endpoint") == "actions":
            actions, rejected = _normalize_yahoo_actions(instrument, download, venue)
            return NormalizedData(corporate_actions=actions, rejected=rejected)
        bars, rejected = _normalize_yahoo_bars(instrument, download, venue)
        return NormalizedData(bars=bars, rejected=rejected)


class EuronextNormalizer:
    """Normalise Euronext historical price exports into bars."""

    source_id = "EURONEXT"

    def normalize(
        self,
        instrument: Instrument,
        download: RawDownload,
        calendar: TradingCalendar | None = None,
    ) -> NormalizedData:
        """Convert a Euronext export to canonical bars.

        Parameters
        ----------
        instrument : Instrument
            Instrument the download belongs to.
        download : RawDownload
            Provider response.
        calendar : TradingCalendar | None
            Venue calendar; required here.

        Returns
        -------
        NormalizedData
            Canonical ``bars``; the other fields are ``None``.

        Raises
        ------
        ValueError
            If ``calendar`` is missing, the download belongs to another source
            or instrument, the instrument is not a ``BAR``, or the export is
            malformed or dated on a day the venue was closed.
        CalendarCoverageError
            If a row falls outside the period the calendar covers.

        Notes
        -----
        ``Close`` is the official closing price and ``Number of Shares`` the
        volume. Euronext's dates are already exchange-local days: no timezone
        conversion is involved.
        """
        venue = _require_bar_call(
            "EuronextNormalizer", self.source_id, instrument, download, calendar
        )
        bars, rejected = _normalize_euronext_bars(instrument, download, venue)
        return NormalizedData(bars=bars, rejected=rejected)


def _fred_style_cells(
    raw: pd.DataFrame, instrument: Instrument, value_column: str, what: str
) -> dict[date, float | None]:
    """Return every cell of a St. Louis Fed graph CSV, missing ones included.

    Parameters
    ----------
    raw : pd.DataFrame
        The provider frame, every cell a string.
    instrument : Instrument
        Instrument the frame belongs to, quoted in the messages.
    value_column : str
        Column holding the values: the series id on FRED, the series id and the
        vintage on ALFRED.
    what : str
        How to name the source in an error message.

    Returns
    -------
    dict[date, float | None]
        One entry per row of the frame: the number, or ``None`` for an empty
        field or the ``"."`` of older exports. What a missing cell means is the
        caller's to say - on FRED no observation, in an ALFRED vintage a
        withdrawal.

    Raises
    ------
    ValueError
        If a column is missing, a date is not ISO or appears twice, or a value
        is neither a missing marker nor a finite number.
    """
    if raw.empty:
        return {}
    missing = sorted({FRED_DATE_COLUMN, value_column} - set(raw.columns))
    if missing:
        raise ValueError(f"{what} series of {instrument.id} lacks column(s): {', '.join(missing)}")
    seen: set[date] = set()
    observations: dict[date, float | None] = {}
    for text_date, text_value in zip(
        raw[FRED_DATE_COLUMN].astype(str), raw[value_column].astype(str), strict=True
    ):
        observation = _iso_date(text_date, f"{what} date of {instrument.id}")
        if observation in seen:
            raise ValueError(f"{what} series of {instrument.id} repeats {observation}")
        seen.add(observation)
        text = text_value.strip()
        if text in FRED_MISSING_MARKERS:
            observations[observation] = None
            continue
        observations[observation] = _finite_number(
            text, f"{what} {value_column} of {instrument.id} on {observation}"
        )
    return observations


def _fred_style_observations(
    raw: pd.DataFrame, instrument: Instrument, value_column: str, what: str
) -> dict[date, float]:
    """Return the observations of a St. Louis Fed graph CSV.

    Parameters
    ----------
    raw : pd.DataFrame
        The provider frame, every cell a string.
    instrument : Instrument
        Instrument the frame belongs to, quoted in the messages.
    value_column : str
        Column holding the values.
    what : str
        How to name the source in an error message.

    Returns
    -------
    dict[date, float]
        One entry per published observation. A missing cell becomes an absent
        row rather than a ``NaN``: a missing observation does not exist, it
        does not equal "unknown".

    Raises
    ------
    ValueError
        As :func:`_fred_style_cells`.
    """
    cells = _fred_style_cells(raw, instrument, value_column, what)
    return {day: value for day, value in cells.items() if value is not None}


class FredNormalizer:
    """Normalise FRED frames into levels."""

    source_id = "FRED"

    def normalize(
        self,
        instrument: Instrument,
        download: RawDownload,
        calendar: TradingCalendar | None = None,
    ) -> NormalizedData:
        """Convert a FRED series to canonical levels.

        Parameters
        ----------
        instrument : Instrument
            Instrument the download belongs to.
        download : RawDownload
            Provider response.
        calendar : TradingCalendar | None
            Unused.

        Returns
        -------
        NormalizedData
            Canonical ``levels``, sorted by observation date; the other fields
            are ``None``.

        Raises
        ------
        ValueError
            If the download belongs to another source or instrument, the
            instrument is not a ``LEVEL``, a column is missing, a date is not ISO
            or appears twice, or a value is neither a missing marker nor a finite
            number.

        Notes
        -----
        Exercice 5.3 (facile). Le raw vient de ``fredgraph.csv`` : colonnes
        ``observation_date`` et ``<series id>``, tout en chaines. Les champs
        vides (et les ``"."`` des anciens exports) deviennent des lignes
        absentes, pas des ``NaN`` : une observation manquante n'existe pas, elle ne vaut pas
        "inconnu". ``available_at_utc`` vient de
        ``instrument.publication_rule.available_at``, jamais d'un calendrier de
        bourse.
        """
        rule = _require_level_call("FredNormalizer", self.source_id, instrument, download)
        observations = _fred_style_observations(
            download.frame, instrument, instrument.source_symbol, "FRED"
        )
        levels, rejected = _levels_frame(instrument, download, rule, observations, calendar)
        return NormalizedData(levels=levels, rejected=rejected)


class AlfredNormalizer:
    """Normalise ALFRED vintages, into levels or into a vintage archive.

    The same file as FRED's with one difference that matters: each value column
    carries its vintage, ``GDP_20200131`` rather than ``GDP``, because one
    export holds several of them. The columns are required to be exactly the
    ones the instrument declares - a raw archive that does not say what it
    holds would give the numbers below somebody else's.

    What comes out depends on how the instrument says the series is read. A
    ``PINNED`` series becomes ordinary levels, one value per observation, as of
    the one day it is pinned to. An ``AS_OF_DECISION`` series becomes vintage
    rows, one per observation *and* vintage, and the reader picks the latest
    vintage each decision could have seen.

    A vintage row is available at the later of two instants: when the
    observation itself was released, and when that vintage existed. A number
    restated in June 2021 was not knowable in 2019, whatever quarter it
    describes, and that is the whole reason this path exists.
    """

    source_id = "ALFRED"

    def normalize(
        self,
        instrument: Instrument,
        download: RawDownload,
        calendar: TradingCalendar | None = None,
    ) -> NormalizedData:
        """Convert one vintage of a published series to canonical levels.

        Parameters
        ----------
        instrument : Instrument
            Instrument the download belongs to; its ``vintage_date`` names the
            column that is read.
        download : RawDownload
            Provider response.
        calendar : TradingCalendar | None
            Unused for the values, and passed on for the publication rule.

        Returns
        -------
        NormalizedData
            Canonical ``levels`` for a pinned series, canonical ``vintages``
            for one read as of each decision.

        Raises
        ------
        ValueError
            If the download belongs to another source or instrument, the
            instrument is not a ``LEVEL`` or declares no vintage, a declared
            vintage column is missing, a date is not ISO or appears twice, or a
            value is neither a missing marker nor a finite number.
        """
        rule = _require_level_call("AlfredNormalizer", self.source_id, instrument, download)
        vintages = tuple(sorted(instrument.vintage_dates))
        if not vintages:
            raise ValueError(f"ALFRED series of {instrument.id} declares no vintage_dates")
        if instrument.vintage_policy is VintagePolicy.PINNED:
            column = vintage_column(instrument.source_symbol, vintages[0])
            observations = _fred_style_observations(download.frame, instrument, column, "ALFRED")
            levels, rejected = _levels_frame(instrument, download, rule, observations, calendar)
            return NormalizedData(levels=levels, rejected=rejected)
        by_vintage = {
            vintage: _fred_style_cells(
                download.frame,
                instrument,
                vintage_column(instrument.source_symbol, vintage),
                "ALFRED",
            )
            for vintage in vintages
        }
        frame, rejected = _vintages_frame(instrument, download, rule, by_vintage, calendar)
        return NormalizedData(vintages=frame, rejected=rejected)


class EcbNormalizer:
    """Normalise ECB reference rates into levels."""

    source_id = "ECB"

    def normalize(
        self,
        instrument: Instrument,
        download: RawDownload,
        calendar: TradingCalendar | None = None,
    ) -> NormalizedData:
        """Convert an ECB series to canonical levels.

        Parameters
        ----------
        instrument : Instrument
            Instrument the download belongs to.
        download : RawDownload
            Provider response.
        calendar : TradingCalendar | None
            Unused.

        Returns
        -------
        NormalizedData
            Canonical ``levels``, sorted by observation date; the other fields
            are ``None``.

        Raises
        ------
        ValueError
            If the download belongs to another source or instrument, the
            instrument is not a ``LEVEL``, a column is missing, a row belongs to
            another series, a date is not ISO or appears twice, or a value is
            neither a missing marker nor a finite number.

        Notes
        -----
        Exercice 5.4 (facile). Attention au sens de la cotation : l'ECB publie
        EUR/USD (dollars par euro). Si une strategie attend l'inverse, c'est ici
        qu'on le fixe une fois, pas dans chaque signal.

        The value is kept as published, in units of ``instrument.currency`` per
        euro (1.0393 USD per EUR on 2024-12-23). No instrument declares the
        inverse quote, so nothing is inverted; one that does would get its own
        instrument and the inversion here.
        """
        rule = _require_level_call("EcbNormalizer", self.source_id, instrument, download)
        raw = download.frame
        if raw.empty:
            return NormalizedData(levels=_empty_frame(LEVELS_SCHEMA))
        missing = sorted({ECB_KEY_COLUMN, ECB_DATE_COLUMN, ECB_VALUE_COLUMN} - set(raw.columns))
        if missing:
            raise ValueError(f"ECB series of {instrument.id} lacks column(s): {', '.join(missing)}")
        seen: set[date] = set()
        observations: dict[date, float] = {}
        for key, text_date, text_value in zip(
            raw[ECB_KEY_COLUMN].astype(str),
            raw[ECB_DATE_COLUMN].astype(str),
            raw[ECB_VALUE_COLUMN].astype(str),
            strict=True,
        ):
            if key != instrument.source_symbol:
                raise ValueError(
                    f"ECB answer for {instrument.id} holds series {key!r}, "
                    f"expected {instrument.source_symbol!r}"
                )
            observation = _iso_date(text_date, f"ECB date of {instrument.id}")
            if observation in seen:
                raise ValueError(f"ECB series of {instrument.id} repeats {observation}")
            seen.add(observation)
            text = text_value.strip()
            if text in ECB_MISSING_MARKERS:
                continue
            what = f"ECB {ECB_VALUE_COLUMN} of {instrument.id} on {observation}"
            observations[observation] = _finite_number(text, what)
        levels, rejected = _levels_frame(instrument, download, rule, observations, calendar)
        return NormalizedData(levels=levels, rejected=rejected)


NORMALIZERS: Mapping[str, Normalizer] = {
    normalizer.source_id: normalizer
    for normalizer in (
        YahooNormalizer(),
        EuronextNormalizer(),
        FredNormalizer(),
        AlfredNormalizer(),
        EcbNormalizer(),
    )
}
"""Registered normalizers, keyed by source identifier. They hold no state."""


def get_normalizer(source_id: str) -> Normalizer:
    """Return the normalizer registered for a source.

    Parameters
    ----------
    source_id : str
        Source identifier, e.g. ``"YAHOO"``.

    Returns
    -------
    Normalizer
        Matching normalizer.

    Raises
    ------
    KeyError
        If no normalizer is registered for that source.

    Notes
    -----
    Exercice 5.5 (facile).
    """
    try:
        return NORMALIZERS[source_id]
    except KeyError:
        raise KeyError(
            f"No normalizer registered for source {source_id!r}; "
            f"known: {', '.join(sorted(NORMALIZERS))}"
        ) from None
