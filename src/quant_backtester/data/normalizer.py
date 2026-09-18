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
from quant_backtester.data.instruments import DataType, Instrument, PublicationRule
from quant_backtester.data.schemas import (
    BARS_SCHEMA,
    CORPORATE_ACTIONS_SCHEMA,
    LEVELS_SCHEMA,
    ActionType,
)
from quant_backtester.data.sources.base import RawDownload


@dataclass(frozen=True, slots=True)
class NormalizedData:
    """Canonical frames produced from one raw download.

    Attributes
    ----------
    bars : pd.DataFrame | None
        Rows matching :data:`~quant_backtester.data.schemas.BARS_SCHEMA`.
    levels : pd.DataFrame | None
        Rows matching :data:`~quant_backtester.data.schemas.LEVELS_SCHEMA`.
    corporate_actions : pd.DataFrame | None
        Rows matching
        :data:`~quant_backtester.data.schemas.CORPORATE_ACTIONS_SCHEMA`.
    """

    bars: pd.DataFrame | None = None
    levels: pd.DataFrame | None = None
    corporate_actions: pd.DataFrame | None = None


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
) -> pd.DataFrame:
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
    pd.DataFrame
        Bars in ``BARS_SCHEMA`` column order, in the order of ``session_dates``.

    Raises
    ------
    ValueError
        If ``values`` does not supply exactly the bar fields, a session appears
        twice, or a bar falls on a day the venue was closed.
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
    # Raises on a closed day or outside the coverage: never caught here.
    availability = [bar_availability(day, calendar) for day in session_dates]
    row_count = len(session_dates)
    columns: dict[str, object] = {
        "instrument_id": [instrument.id] * row_count,
        "session_date": list(session_dates),
        **values,
        "open_available_at_utc": [open_at for open_at, _ in availability],
        "close_available_at_utc": [close_at for _, close_at in availability],
        "source": [download.source] * row_count,
        "source_fetch_id": [download.fetch_id] * row_count,
    }
    return pd.DataFrame(columns, columns=list(BARS_SCHEMA.names))


def _levels_frame(
    instrument: Instrument,
    download: RawDownload,
    rule: PublicationRule,
    observations: Mapping[date, float],
    calendar: TradingCalendar | None = None,
) -> pd.DataFrame:
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
    pd.DataFrame
        Levels sorted by ``observation_date``, columns in ``LEVELS_SCHEMA`` order.
    """
    if not observations:
        return _empty_frame(LEVELS_SCHEMA)
    dates = sorted(observations)
    columns: dict[str, object] = {
        "instrument_id": [instrument.id] * len(dates),
        "observation_date": dates,
        "value": [observations[day] for day in dates],
        "available_at_utc": [rule.available_at(day, calendar) for day in dates],
        "source": [download.source] * len(dates),
        "source_fetch_id": [download.fetch_id] * len(dates),
    }
    return pd.DataFrame(columns, columns=list(LEVELS_SCHEMA.names))


def _normalize_yahoo_bars(
    instrument: Instrument, download: RawDownload, calendar: TradingCalendar
) -> pd.DataFrame:
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
        return _empty_frame(BARS_SCHEMA)
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
) -> pd.DataFrame:
    """Turn a raw Yahoo ``actions`` frame into rows of ``CORPORATE_ACTIONS_SCHEMA``.

    Yahoo sends the whole history (``period="max"``): only ex-dates inside the
    requested ``[start, end_inclusive]`` are kept, and they are filtered before
    any calendar lookup, since old ex-dates lie outside the calendar coverage.
    One Yahoo row yields zero, one or two canonical rows, ``0.0`` meaning no
    event. Yahoo omits a column that never held an event (SPY has no
    ``Stock Splits`` column, checked on 2026-09-13): an absent column counts as
    zeros. Dividends are multiplied back by the later splits Yahoo divided them
    by (see :func:`_later_split_factor`), and each action becomes available at
    the close of its ex-date.

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
        return _empty_frame(CORPORATE_ACTIONS_SCHEMA)
    if not any(column in raw.columns for column in YAHOO_ACTION_COLUMNS):
        raise ValueError(
            f"Yahoo actions of {instrument.id} have none of the columns "
            f"{', '.join(YAHOO_ACTION_COLUMNS)}: {', '.join(map(str, raw.columns))}"
        )
    start = _requested_date(download, "start")
    end = _requested_date(download, "end_inclusive")
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
        _, close_at = bar_availability(ex_date, calendar)
        for action_type, value in events:
            rows.append(
                {
                    "instrument_id": instrument.id,
                    "action_type": action_type.value,
                    "ex_date": ex_date,
                    "value": value,
                    "available_at_utc": close_at,
                    "source": download.source,
                    "source_fetch_id": download.fetch_id,
                }
            )
    if not rows:
        return _empty_frame(CORPORATE_ACTIONS_SCHEMA)
    return pd.DataFrame(rows, columns=list(CORPORATE_ACTIONS_SCHEMA.names))


def _normalize_euronext_bars(
    instrument: Instrument, download: RawDownload, calendar: TradingCalendar
) -> pd.DataFrame:
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
        return _empty_frame(BARS_SCHEMA)
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
            return NormalizedData(
                corporate_actions=_normalize_yahoo_actions(instrument, download, venue)
            )
        return NormalizedData(bars=_normalize_yahoo_bars(instrument, download, venue))


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
        return NormalizedData(bars=_normalize_euronext_bars(instrument, download, venue))


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
        raw = download.frame
        if raw.empty:
            return NormalizedData(levels=_empty_frame(LEVELS_SCHEMA))
        value_column = instrument.source_symbol
        missing = sorted({FRED_DATE_COLUMN, value_column} - set(raw.columns))
        if missing:
            raise ValueError(
                f"FRED series of {instrument.id} lacks column(s): {', '.join(missing)}"
            )
        seen: set[date] = set()
        observations: dict[date, float] = {}
        for text_date, text_value in zip(
            raw[FRED_DATE_COLUMN].astype(str), raw[value_column].astype(str), strict=True
        ):
            observation = _iso_date(text_date, f"FRED date of {instrument.id}")
            if observation in seen:
                raise ValueError(f"FRED series of {instrument.id} repeats {observation}")
            seen.add(observation)
            text = text_value.strip()
            if text in FRED_MISSING_MARKERS:
                continue
            what = f"FRED {value_column} of {instrument.id} on {observation}"
            observations[observation] = _finite_number(text, what)
        return NormalizedData(
            levels=_levels_frame(instrument, download, rule, observations, calendar)
        )


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
        return NormalizedData(
            levels=_levels_frame(instrument, download, rule, observations, calendar)
        )


NORMALIZERS: Mapping[str, Normalizer] = {
    normalizer.source_id: normalizer
    for normalizer in (YahooNormalizer(), EuronextNormalizer(), FredNormalizer(), EcbNormalizer())
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
