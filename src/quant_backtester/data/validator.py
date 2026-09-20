"""Validation of canonical frames before they reach the clean layer.

Rules are typed by instrument. Two rules that look universal are not:

- ``close > 0`` is false for a rate. The German 10-year yield was negative from
  2019 to 2022.
- a 50% daily move is not an anomaly on the VIX, which gained 115% on
  5 February 2018.

A rule that cries wolf is a rule that gets switched off, so each one is scoped to
the asset types where it means something.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any

import pandas as pd

from quant_backtester.data.calendars import CalendarCoverageError, TradingCalendar
from quant_backtester.data.instruments import (
    AssetType,
    DataType,
    DistributionPolicy,
    Instrument,
)
from quant_backtester.data.schemas import ActionType


class Severity(Enum):
    """How a validation issue is treated by the updater."""

    WARNING = "WARNING"
    """Logged; the write proceeds."""

    ERROR = "ERROR"
    """Logged; the write is aborted and the clean layer left untouched."""


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """One problem found in a candidate frame.

    Attributes
    ----------
    code : str
        Stable machine-readable code, e.g. ``"OHLC_ORDER"``. Stable so the log
        stays queryable as messages are reworded.
    severity : Severity
        Whether the issue blocks the write.
    instrument_id : str
        Instrument concerned.
    observation_date : date | None
        Row concerned; ``None`` for a whole-frame issue.
    message : str
        Human-readable explanation.
    context : Mapping[str, object]
        Values that led to the issue, for the log.
    """

    code: str
    severity: Severity
    instrument_id: str
    observation_date: date | None
    message: str
    context: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Outcome of validating one instrument's frame.

    Attributes
    ----------
    instrument_id : str
        Instrument concerned.
    issues : Sequence[ValidationIssue]
        Everything found, in row order.
    """

    instrument_id: str
    issues: Sequence[ValidationIssue]

    @property
    def valid(self) -> bool:
        """Return whether the frame may be written.

        Returns
        -------
        bool
            ``True`` when no issue has ``Severity.ERROR``.

        Notes
        -----
        Exercice 6.1 (trivial).
        """
        return not any(issue.severity == Severity.ERROR for issue in self.issues)

    @property
    def errors(self) -> list[ValidationIssue]:
        """Return the blocking issues.

        Returns
        -------
        list[ValidationIssue]
            Issues with ``Severity.ERROR``.

        Notes
        -----
        Exercice 6.1 (trivial).
        """
        return [issue for issue in self.issues if issue.severity == Severity.ERROR]

    @property
    def warnings(self) -> list[ValidationIssue]:
        """Return the non-blocking issues.

        Returns
        -------
        list[ValidationIssue]
            Issues with ``Severity.WARNING``.

        Notes
        -----
        Exercice 6.1 (trivial).
        """
        return [issue for issue in self.issues if issue.severity == Severity.WARNING]


REQUIRED_BAR_COLUMNS: tuple[str, ...] = (
    "session_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "open_available_at_utc",
    "close_available_at_utc",
)
"""Columns ``validate_bars`` reads. Lineage columns are the repository's concern."""

BAR_PRICE_FIELDS: tuple[str, ...] = ("open", "high", "low", "close")
"""Price fields of a bar."""

POSITIVE_PRICE_ASSET_TYPES = frozenset({AssetType.ETF, AssetType.EQUITY, AssetType.INDEX})
"""Asset types whose prices must be strictly positive. Never a rate."""

EXTREME_MOVE_THRESHOLDS: dict[AssetType, float | None] = {
    # Given by the exercise statement.
    AssetType.ETF: 0.25,
    # The S&P 500's worst day (-20.5%, 1987-10-19) stays below; beyond 25% an index bar is suspect.
    AssetType.INDEX: 0.25,
    # A liquid stock can move 20-30% on earnings; beyond 40% the bar deserves a look.
    AssetType.EQUITY: 0.40,
    # No useful threshold: the VIX gained 115% on 2018-02-05.
    AssetType.VOLATILITY: None,
}
"""Absolute close-to-close move above which a bar is reported. Absent or ``None``: never.

A move is not rejected, only reported: it catches the data errors that look like
real moves - a price from another instrument, a shifted decimal, an undeclared
split - without blocking the genuine crashes a backtest must keep.
"""


def _issue(
    code: str,
    severity: Severity,
    instrument: Instrument,
    on: date | None,
    message: str,
    context: Mapping[str, object],
) -> ValidationIssue:
    """Build one issue for ``instrument``.

    Parameters
    ----------
    code : str
        Stable issue code.
    severity : Severity
        Whether it blocks the write.
    instrument : Instrument
        Instrument concerned.
    on : date | None
        Row concerned, ``None`` for a whole-frame issue.
    message : str
        Human-readable explanation.
    context : Mapping[str, object]
        Values that led to the issue.

    Returns
    -------
    ValidationIssue
        The issue.
    """
    return ValidationIssue(
        code=code,
        severity=severity,
        instrument_id=instrument.id,
        observation_date=on,
        message=message,
        context=context,
    )


def _number(value: object) -> float | None:
    """Return a cell as a float, or ``None`` when it holds no number.

    Parameters
    ----------
    value : object
        Cell read from a canonical frame.

    Returns
    -------
    float | None
        ``None`` for ``None``, ``NaN`` or ``pd.NA``. Prices are nullable, and a
        comparison with ``NaN`` is silently ``False``, so one must never reach it.
    """
    if value is None or value is pd.NA:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return None if math.isnan(number) else number


def _check_order(instrument: Instrument, dates: list[date]) -> list[ValidationIssue]:
    """Report duplicated sessions and rows out of chronological order.

    Parameters
    ----------
    instrument : Instrument
        Instrument concerned.
    dates : list[date]
        ``session_date`` of every row, in frame order.

    Returns
    -------
    list[ValidationIssue]
        ``DATE_DUPLICATE`` once per repeated session and ``DATES_UNSORTED`` for
        each row dated before the row above it, both ``ERROR``.
    """
    issues: list[ValidationIssue] = []
    for day, count in sorted(Counter(dates).items()):
        if count > 1:
            issues.append(
                _issue(
                    "DATE_DUPLICATE",
                    Severity.ERROR,
                    instrument,
                    day,
                    f"Session {day} appears {count} times",
                    {"count": count},
                )
            )
    for position in range(1, len(dates)):
        if dates[position] < dates[position - 1]:
            issues.append(
                _issue(
                    "DATES_UNSORTED",
                    Severity.ERROR,
                    instrument,
                    dates[position],
                    f"Session {dates[position]} comes after {dates[position - 1]}",
                    {"previous_date": dates[position - 1]},
                )
            )
    return issues


def _check_sessions(
    instrument: Instrument, dates: list[date], calendar: TradingCalendar
) -> list[ValidationIssue]:
    """Report rows dated on a day the venue was closed or the calendar does not cover.

    Parameters
    ----------
    instrument : Instrument
        Instrument concerned.
    dates : list[date]
        ``session_date`` of every row.
    calendar : TradingCalendar
        Venue calendar.

    Returns
    -------
    list[ValidationIssue]
        ``NON_SESSION`` for a closed day and ``OUTSIDE_CALENDAR_COVERAGE`` for a
        day the calendar cannot judge, both ``ERROR``, once per date. A validator
        reports: it does not stop at the first date it cannot place.
    """
    issues: list[ValidationIssue] = []
    for day in sorted(set(dates)):
        try:
            is_open = calendar.is_open(day)
        except CalendarCoverageError:
            issues.append(
                _issue(
                    "OUTSIDE_CALENDAR_COVERAGE",
                    Severity.ERROR,
                    instrument,
                    day,
                    f"{calendar.calendar_id} does not cover {day} "
                    f"({calendar.covered_from} to {calendar.covered_until})",
                    {"calendar_id": calendar.calendar_id},
                )
            )
            continue
        if not is_open:
            issues.append(
                _issue(
                    "NON_SESSION",
                    Severity.ERROR,
                    instrument,
                    day,
                    f"{calendar.calendar_id} was closed on {day}",
                    {"calendar_id": calendar.calendar_id},
                )
            )
    return issues


def bar_row_issues(instrument: Instrument, row: Mapping[str, Any]) -> list[ValidationIssue]:
    """Report what is wrong within one bar.

    Parameters
    ----------
    instrument : Instrument
        Instrument concerned.
    row : Mapping[str, Any]
        One canonical bar.

    Returns
    -------
    list[ValidationIssue]
        At most one of each. ``ERROR``: ``OHLC_ORDER`` (``low <= open <= high``,
        ``low <= close <= high``, compared only between prices present),
        ``NON_POSITIVE_PRICE`` (only for :data:`POSITIVE_PRICE_ASSET_TYPES`),
        ``NEGATIVE_VOLUME`` and ``AVAILABILITY_ORDER`` (the open must become
        available strictly before the close). ``WARNING``: ``MISSING_PRICE``.

    Notes
    -----
    ``MISSING_PRICE`` exists because every other rule here skips a price that is
    absent, so a bar with no close used to pass in silence - Yahoo served
    exactly that for CW8 on 2026-09-17, open, high and low present and no close.
    It is a warning rather than an error: one incomplete recent bar must not
    block a whole series from being updated, and nothing downstream will use the
    value anyway. The cross-check marks the session against a second source and
    the reader drops a missing value from the series it serves.

    Volume is deliberately out of it: a provider leaving it empty on an index is
    ordinary, and no price is derived from it.

    Public because a reviewed bar correction has to be able to ask whether the
    defect it was written for is still in the data. Two copies of the OHLC rule
    would drift, and the day they did, a correction would go on dropping a bar
    the provider had already fixed.
    """
    day: date = row["session_date"]
    prices = {field: _number(row[field]) for field in BAR_PRICE_FIELDS}
    issues: list[ValidationIssue] = []

    absent = [field for field, value in prices.items() if value is None]
    if absent:
        issues.append(
            _issue(
                "MISSING_PRICE",
                Severity.WARNING,
                instrument,
                day,
                f"Bar of {day} has no {', '.join(absent)}",
                {"missing": absent},
            )
        )

    low, high = prices["low"], prices["high"]
    broken: list[str] = []
    if low is not None and high is not None and low > high:
        broken.append(f"low {low} > high {high}")
    for field in ("open", "close"):
        value = prices[field]
        if value is None:
            continue
        if low is not None and value < low:
            broken.append(f"{field} {value} < low {low}")
        if high is not None and value > high:
            broken.append(f"{field} {value} > high {high}")
    if broken:
        issues.append(
            _issue(
                "OHLC_ORDER",
                Severity.ERROR,
                instrument,
                day,
                f"Bar of {day} breaks the OHLC order: {'; '.join(broken)}",
                dict(prices),
            )
        )

    if instrument.asset_type in POSITIVE_PRICE_ASSET_TYPES:
        non_positive: dict[str, object] = {
            field: value for field, value in prices.items() if value is not None and value <= 0
        }
        if non_positive:
            issues.append(
                _issue(
                    "NON_POSITIVE_PRICE",
                    Severity.ERROR,
                    instrument,
                    day,
                    f"Bar of {day} has non-positive price(s) for a "
                    f"{instrument.asset_type.value}: {non_positive}",
                    non_positive,
                )
            )

    volume = _number(row["volume"])
    present = [value for value in prices.values() if value is not None]
    # A warning, deliberately, and not a quarantine - and the message says
    # "possibly" because the two causes are indistinguishable from the row. Of
    # the 76 such bars the first real ingestion found on CW8, 74 were the block
    # before it listed, which is the listing window's business and not this
    # rule's; the two left are a session a second source contradicts - the
    # cross-check settles that one - and 24 December 2018, a half day on a fund
    # then trading a few hundred shares, where no trade at all is perfectly
    # ordinary. A rule that withheld prices on this pattern would be wrong about
    # the case it is left with.
    if len(present) == len(BAR_PRICE_FIELDS) and len(set(present)) == 1 and volume == 0:
        issues.append(
            _issue(
                "FLAT_ZERO_VOLUME",
                Severity.WARNING,
                instrument,
                day,
                f"Bar of {day} is flat at {present[0]} with no volume: possibly a "
                "provider placeholder, possibly a session where nothing traded",
                {"price": present[0]},
            )
        )
    if volume is not None and volume < 0:
        issues.append(
            _issue(
                "NEGATIVE_VOLUME",
                Severity.ERROR,
                instrument,
                day,
                f"Bar of {day} has a negative volume {volume}",
                {"volume": volume},
            )
        )

    open_at: object = row["open_available_at_utc"]
    close_at: object = row["close_available_at_utc"]
    ordered = (
        isinstance(open_at, pd.Timestamp)
        and isinstance(close_at, pd.Timestamp)
        and open_at < close_at
    )
    if not ordered:
        issues.append(
            _issue(
                "AVAILABILITY_ORDER",
                Severity.ERROR,
                instrument,
                day,
                f"Bar of {day}: open available at {open_at}, close at {close_at}; "
                "the open must come strictly first",
                {"open_available_at_utc": open_at, "close_available_at_utc": close_at},
            )
        )
    return issues


def _check_gaps(
    instrument: Instrument, dates: list[date], calendar: TradingCalendar
) -> list[ValidationIssue]:
    """Report sessions of the calendar that have no row.

    Parameters
    ----------
    instrument : Instrument
        Instrument concerned, for its listing bounds.
    dates : list[date]
        ``session_date`` of every row.
    calendar : TradingCalendar
        Venue calendar: a holiday is not a hole.

    Returns
    -------
    list[ValidationIssue]
        ``SESSION_GAP`` (``WARNING``) for each session between the first and the
        last row, within the calendar coverage, while the instrument was listed.
    """
    if not dates:
        return []
    start = max(min(dates), calendar.covered_from)
    end = min(max(dates), calendar.covered_until)
    if start > end:
        return []
    present = set(dates)
    issues: list[ValidationIssue] = []
    for session in calendar.sessions(start, end):
        day = session.session_date
        if day in present or not instrument.is_listed(day):
            continue
        issues.append(
            _issue(
                "SESSION_GAP",
                Severity.WARNING,
                instrument,
                day,
                f"{calendar.calendar_id} held a session on {day}, but no bar is stored",
                {"calendar_id": calendar.calendar_id},
            )
        )
    return issues


def _check_moves(instrument: Instrument, rows: list[dict[str, Any]]) -> list[ValidationIssue]:
    """Report close-to-close moves beyond the threshold of the asset type.

    Parameters
    ----------
    instrument : Instrument
        Instrument concerned, for its asset type.
    rows : list[dict[str, Any]]
        Canonical bars, in any order: they are compared chronologically.

    Returns
    -------
    list[ValidationIssue]
        ``EXTREME_MOVE`` (``WARNING``) on the later bar of each offending pair.
        A missing or non-positive close is skipped; the next close is compared
        with the last valid one.
    """
    threshold = EXTREME_MOVE_THRESHOLDS.get(instrument.asset_type)
    if threshold is None:
        return []
    closes: list[tuple[date, float | None]] = sorted(
        ((row["session_date"], _number(row["close"])) for row in rows), key=lambda item: item[0]
    )
    issues: list[ValidationIssue] = []
    previous: tuple[date, float] | None = None
    for day, close in closes:
        if close is None or close <= 0:
            continue
        if previous is not None:
            move = close / previous[1] - 1
            if abs(move) > threshold:
                issues.append(
                    _issue(
                        "EXTREME_MOVE",
                        Severity.WARNING,
                        instrument,
                        day,
                        f"Close moved {move:+.1%} from {previous[0]} to {day}, beyond "
                        f"{threshold:.0%} for a {instrument.asset_type.value}",
                        {
                            "previous_date": previous[0],
                            "previous_close": previous[1],
                            "close": close,
                            "move": move,
                            "threshold": threshold,
                        },
                    )
                )
        previous = (day, close)
    return issues


def validate_bars(
    instrument: Instrument, frame: pd.DataFrame, calendar: TradingCalendar
) -> ValidationReport:
    """Check a canonical bars frame.

    Parameters
    ----------
    instrument : Instrument
        Instrument the frame belongs to.
    frame : pd.DataFrame
        Candidate rows, already normalised.
    calendar : TradingCalendar
        Venue calendar, needed to tell a holiday from a hole.

    Returns
    -------
    ValidationReport
        Issues found.

    Notes
    -----
    Exercice 6.2 (le plus long du module, moyen). Regles a implementer, chacune
    avec son propre ``code`` :

    ERROR
        ``DATES_UNSORTED`` / ``DATE_DUPLICATE`` ; ``NON_SESSION`` (une seance qui
        n'existe pas au calendrier) ; ``OHLC_ORDER`` (``low <= open <= high`` et
        ``low <= close <= high``) ; ``NON_POSITIVE_PRICE``, mais uniquement pour
        ``AssetType`` ``ETF``, ``EQUITY``, ``INDEX`` - jamais pour un taux ;
        ``NEGATIVE_VOLUME`` ; ``AVAILABILITY_ORDER`` (``open_available_at_utc <
        close_available_at_utc``).

    WARNING
        ``SESSION_GAP`` (seances du calendrier sans ligne) ; ``EXTREME_MOVE``,
        avec un seuil dependant de l'``AssetType`` : 25% sur un ETF, mais aucun
        seuil utile sur la volatilite ; ``STALE_OPEN`` (voir exercice 6.3).

    Ne modifie jamais la frame ici. Un validateur qui corrige est un validateur
    qu'on ne peut plus auditer.

    Three codes beyond the statement. Two ``ERROR``: ``MISSING_COLUMN`` (nothing
    else can be checked) and ``OUTSIDE_CALENDAR_COVERAGE`` (the calendar cannot
    say whether the day was a session, so the row cannot be trusted either). One
    ``WARNING``: ``MISSING_PRICE``, a bar whose open, high, low or close is
    absent - see :func:`bar_row_issues`.
    Issues are sorted by date, whole-frame issues first.
    """
    missing = [column for column in REQUIRED_BAR_COLUMNS if column not in frame.columns]
    if missing:
        issue = _issue(
            "MISSING_COLUMN",
            Severity.ERROR,
            instrument,
            None,
            f"Bars of {instrument.id} lack column(s): {', '.join(missing)}",
            {"missing": missing},
        )
        return ValidationReport(instrument_id=instrument.id, issues=[issue])
    rows = [
        {str(column): value for column, value in record.items()}
        for record in frame.to_dict("records")
    ]
    dates: list[date] = [row["session_date"] for row in rows]
    issues = _check_order(instrument, dates)
    issues += _check_sessions(instrument, dates, calendar)
    for row in rows:
        issues += bar_row_issues(instrument, row)
    issues += _check_gaps(instrument, dates, calendar)
    issues += _check_moves(instrument, rows)
    issues += check_stale_open(instrument, frame)
    # Stable sort: within one date, issues keep the order of the rules above.
    issues.sort(
        key=lambda issue: (issue.observation_date is not None, issue.observation_date or date.min)
    )
    return ValidationReport(instrument_id=instrument.id, issues=issues)


STALE_OPEN_REL_TOLERANCE = 1e-6
"""Relative gap under which an open counts as equal to the previous close.

Yahoo stores prices as float32, a relative noise below 6e-8: exact equality would
miss the very repeats this rule exists to catch.
"""

STALE_OPEN_ASSET_TYPES = frozenset({AssetType.ETF, AssetType.EQUITY})
"""Asset types whose open is an execution price.

An index open is computed, and old index data often repeats the previous close:
checked there, the rule would cry wolf.
"""


def _stale_open_flags(rows: list[dict[str, Any]]) -> list[tuple[date, bool]]:
    """Return, session by session, whether the open repeats the previous close.

    Parameters
    ----------
    rows : list[dict[str, Any]]
        Canonical bars, in any order.

    Returns
    -------
    list[tuple[date, bool]]
        ``(session_date, stale)`` in chronological order. The first session has
        no previous close and is never stale; a missing open or previous close is
        neither evidence nor counter-evidence, so it counts as not stale.
    """
    flags: list[tuple[date, bool]] = []
    previous_close: float | None = None
    for row in sorted(rows, key=lambda row: row["session_date"]):
        open_ = _number(row["open"])
        stale = (
            previous_close is not None
            and open_ is not None
            and math.isclose(open_, previous_close, rel_tol=STALE_OPEN_REL_TOLERANCE)
        )
        flags.append((row["session_date"], stale))
        previous_close = _number(row["close"])
    return flags


def check_stale_open(
    instrument: Instrument, frame: pd.DataFrame, window: int = 20, threshold: float = 0.3
) -> list[ValidationIssue]:
    """Flag opening prints that merely repeat the previous close.

    Parameters
    ----------
    instrument : Instrument
        Instrument the frame belongs to.
    frame : pd.DataFrame
        Canonical bars, chronologically sorted.
    window : int
        Rolling window, in sessions.
    threshold : float
        Fraction of the window above which the pattern is reported.

    Returns
    -------
    list[ValidationIssue]
        One ``STALE_OPEN`` (``WARNING``) each time a rolling window becomes
        offending, dated on its last session: an episode spanning many windows
        is reported once, and later sessions never change an issue already
        emitted. Empty for asset types outside :data:`STALE_OPEN_ASSET_TYPES`
        and for fewer sessions than ``window``.

    Raises
    ------
    ValueError
        If ``window`` is below 2 or ``threshold`` lies outside ``]0, 1[``.

    Notes
    -----
    Exercice 6.3 (moyen, et le plus rentable du module). Sur un ETF europeen peu
    liquide, Yahoo sert parfois un open egal au close de la veille : il n'y a pas
    eu de fixing exploitable. Comme l'open **est** notre prix d'execution, une
    strategie qui achete a ce prix realise un gain qui n'existe pas. C'est le
    type exact de mauvaise donnee qui fabrique un faux alpha : elle passe tous
    les autres controles.

    Un ``open == close`` isole est normal et ne doit rien declencher ; c'est la
    repetition qui est le signal.
    """
    if window < 2:
        raise ValueError(f"window {window} must be at least 2")
    if not 0 < threshold < 1:
        raise ValueError(f"threshold {threshold} must lie in ]0, 1[")
    if instrument.asset_type not in STALE_OPEN_ASSET_TYPES or len(frame) < window:
        return []
    records = [
        {str(column): value for column, value in record.items()}
        for record in frame.to_dict("records")
    ]
    flags = _stale_open_flags(records)
    issues: list[ValidationIssue] = []
    previous_offending = False
    # Rolling window of `window` sessions, counted in rows, not calendar days.
    for last in range(window - 1, len(flags)):
        first = last - window + 1
        count = sum(stale for _, stale in flags[first : last + 1])
        offending = count / window > threshold
        # One issue when a window becomes offending, not one per offending window.
        if offending and not previous_offending:
            issues.append(
                _issue(
                    "STALE_OPEN",
                    Severity.WARNING,
                    instrument,
                    flags[last][0],
                    f"Open repeated the previous close {count} times in the {window} sessions "
                    f"to {flags[last][0]}, above the {threshold:.0%} threshold",
                    {
                        "window_start": flags[first][0],
                        "window_end": flags[last][0],
                        "stale_count": count,
                        "window": window,
                        "threshold": threshold,
                    },
                )
            )
        previous_offending = offending
    return issues


REQUIRED_LEVEL_COLUMNS: tuple[str, ...] = ("observation_date", "value", "available_at_utc")
"""Columns ``validate_levels`` reads."""

REQUIRED_ACTION_COLUMNS: tuple[str, ...] = ("action_type", "ex_date", "value", "available_at_utc")
"""Columns ``validate_corporate_actions`` reads."""


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Return the rows of ``frame`` as dicts keyed by column name, leaving ``frame`` untouched."""
    return [
        {str(column): value for column, value in record.items()}
        for record in frame.to_dict("records")
    ]


def _missing_columns(
    instrument: Instrument, frame: pd.DataFrame, required: Sequence[str], table: str
) -> ValidationReport | None:
    """Return a ``MISSING_COLUMN`` report when ``frame`` lacks a required column.

    Parameters
    ----------
    instrument : Instrument
        Instrument concerned.
    frame : pd.DataFrame
        Candidate rows.
    required : Sequence[str]
        Columns the validation reads.
    table : str
        Table name for the message, e.g. ``"Levels"``.

    Returns
    -------
    ValidationReport | None
        A report holding the single whole-frame ``ERROR``, or ``None`` when every
        column is present: nothing else can be checked without them.
    """
    missing = [column for column in required if column not in frame.columns]
    if not missing:
        return None
    issue = _issue(
        "MISSING_COLUMN",
        Severity.ERROR,
        instrument,
        None,
        f"{table} of {instrument.id} lack column(s): {', '.join(missing)}",
        {"missing": missing},
    )
    return ValidationReport(instrument_id=instrument.id, issues=[issue])


def _timestamp(value: object) -> pd.Timestamp | None:
    """Return a cell as a ``pd.Timestamp``, or ``None`` when it holds no instant.

    Parameters
    ----------
    value : object
        Cell read from a canonical frame.

    Returns
    -------
    pd.Timestamp | None
        ``None`` for ``None``, ``NaT`` or ``pd.NA``. ``NaT`` is checked first: it
        passes an ``isinstance(value, datetime)`` test.
    """
    if value is None or value is pd.NaT or value is pd.NA:
        return None
    if isinstance(value, pd.Timestamp):
        return value
    if isinstance(value, datetime):
        timestamp = pd.Timestamp(value)
        # pandas types the conversion as Timestamp | NaTType.
        return timestamp if isinstance(timestamp, pd.Timestamp) else None
    return None


def _by_date(issues: list[ValidationIssue]) -> list[ValidationIssue]:
    """Return ``issues`` sorted by date, whole-frame issues first, stable within a date."""
    return sorted(
        issues,
        key=lambda issue: (issue.observation_date is not None, issue.observation_date or date.min),
    )


def validate_levels(
    instrument: Instrument,
    frame: pd.DataFrame,
    calendar: TradingCalendar | None = None,
    available_at: Callable[[date], datetime] | None = None,
) -> ValidationReport:
    """Check a canonical levels frame.

    Parameters
    ----------
    instrument : Instrument
        Instrument the frame belongs to.
    frame : pd.DataFrame
        Candidate rows, already normalised.
    calendar : TradingCalendar | None
        Calendar the instrument's publication rule counts its lag on, needed to
        recompute the expected availability. Only a same-day release can do
        without one.
    available_at : Callable[[date], datetime] | None
        What the availability of an observation is expected to be. The
        publication rule applied to the observation date, by default; a row of
        a vintage archive passes the later of that and the vintage's own
        release, because a number restated in June 2021 was not knowable in
        2019. It is a parameter rather than a second copy of these rules: the
        only thing that differs between the two is this instant.

    Returns
    -------
    ValidationReport
        Issues found, sorted by date, all ``ERROR``: ``MISSING_COLUMN`` (alone:
        nothing else can be checked), ``DATES_UNSORTED`` / ``DATE_DUPLICATE``,
        ``MISSING_VALUE``, ``MISSING_AVAILABILITY``, ``AVAILABILITY_NOT_UTC``,
        ``AVAILABILITY_BEFORE_OBSERVATION`` (published, in the publication
        timezone, before the day it describes) and ``AVAILABILITY_MISMATCH``
        (not the instant the instrument's publication rule gives). ``frame`` is
        never modified.

    Raises
    ------
    ValueError
        If ``instrument`` is not a ``LEVEL`` with a publication rule: that is a
        wrong call, not a data problem.

    Notes
    -----
    Exercice 6.4 (facile). Dates triees, sans doublon, ``available_at_utc`` non
    nul et posterieur a ``observation_date``. Pas de controle de signe : un taux
    peut etre negatif, et c'est precisement le genre de regle "evidente" qui
    rendrait le Bund 2019-2022 inchargeable.

    ``AVAILABILITY_MISMATCH`` goes beyond the statement on purpose: the instant
    must be the one the committed rule gives today. Correct a rule - a
    publication lag, a release time - and every level stamped under the old one
    fails here until ``clean/`` is rebuilt, instead of silently keeping an
    availability the configuration no longer says.
    """
    rule = instrument.publication_rule
    if instrument.data_type != DataType.LEVEL or rule is None:
        raise ValueError(
            f"validate_levels only handles LEVEL instruments, "
            f"{instrument.id} is {instrument.data_type.value}"
        )
    missing = _missing_columns(instrument, frame, REQUIRED_LEVEL_COLUMNS, "Levels")
    if missing is not None:
        return missing
    rows = _records(frame)
    issues = _check_order(instrument, [row["observation_date"] for row in rows])
    for row in rows:
        day: date = row["observation_date"]
        if _number(row["value"]) is None:
            issues.append(
                _issue(
                    "MISSING_VALUE",
                    Severity.ERROR,
                    instrument,
                    day,
                    f"Level of {day} has no value: a missing observation is no row, not a NaN",
                    {"value": row["value"]},
                )
            )
        available = _timestamp(row["available_at_utc"])
        if available is None:
            issues.append(
                _issue(
                    "MISSING_AVAILABILITY",
                    Severity.ERROR,
                    instrument,
                    day,
                    f"Level of {day} has no availability instant",
                    {},
                )
            )
            continue
        if available.tzinfo is None:
            issues.append(
                _issue(
                    "AVAILABILITY_NOT_UTC",
                    Severity.ERROR,
                    instrument,
                    day,
                    f"Level of {day} is available at the naive instant {available}",
                    {"available_at_utc": available},
                )
            )
            continue
        published_on = available.tz_convert(rule.timezone).date()
        expected = pd.Timestamp(
            rule.available_at(day, calendar) if available_at is None else available_at(day)
        )
        if published_on < day:
            issues.append(
                _issue(
                    "AVAILABILITY_BEFORE_OBSERVATION",
                    Severity.ERROR,
                    instrument,
                    day,
                    f"Level of {day} is available on {published_on} ({rule.timezone}), "
                    "before the day it describes",
                    {"available_at_utc": available, "published_on": published_on},
                )
            )
        elif available != expected:
            issues.append(
                _issue(
                    "AVAILABILITY_MISMATCH",
                    Severity.ERROR,
                    instrument,
                    day,
                    f"Level of {day} is available at {available}, but its publication rule "
                    f"gives {expected}",
                    {"available_at_utc": available, "expected": expected},
                )
            )
    return ValidationReport(instrument_id=instrument.id, issues=_by_date(issues))


def validate_corporate_actions(instrument: Instrument, frame: pd.DataFrame) -> ValidationReport:
    """Check a canonical corporate actions frame.

    Parameters
    ----------
    instrument : Instrument
        Instrument the frame belongs to.
    frame : pd.DataFrame
        Candidate rows.

    Returns
    -------
    ValidationReport
        Issues found, sorted by ex-date, all ``ERROR``: ``MISSING_COLUMN`` (alone),
        ``DUPLICATE_ACTION`` (same type twice on one ex-date),
        ``UNKNOWN_ACTION_TYPE``, ``INVALID_SPLIT_RATIO`` (a split ratio must be
        positive and not 1; below 1 is a reverse split, and valid),
        ``NON_POSITIVE_DIVIDEND`` (ordinary or special),
        ``INVALID_SPIN_OFF_FACTOR``, ``MISSING_AVAILABILITY`` and
        ``UNEXPECTED_DISTRIBUTION`` (a distribution on an accumulating share
        class). ``frame`` is never modified.

    Raises
    ------
    ValueError
        If ``instrument`` is not a ``BAR``: only traded instruments have
        corporate actions.

    Notes
    -----
    Exercice 6.5 (facile). Un ``SPLIT`` a un ratio strictement positif et
    different de 1 ; un ``DIVIDEND`` a un montant strictement positif. Deux
    actions du meme type a la meme ex-date sont une erreur.

    Only the shape is checked. Whether a ratio is plausible - a split the prices
    do not show - needs the bars, and belongs to a review this layer does not
    run. What an event *was*, when the provider mislabelled it, is a reviewed
    decision in ``metadata/corporate_actions.toml``; see
    :mod:`quant_backtester.data.corporate_actions`.
    """
    if instrument.data_type != DataType.BAR:
        raise ValueError(
            f"validate_corporate_actions only handles BAR instruments, "
            f"{instrument.id} is {instrument.data_type.value}"
        )
    missing = _missing_columns(instrument, frame, REQUIRED_ACTION_COLUMNS, "Corporate actions")
    if missing is not None:
        return missing
    rows = _records(frame)
    issues: list[ValidationIssue] = []
    occurrences = Counter((row["ex_date"], str(row["action_type"])) for row in rows)
    for (ex_date, action_type), count in sorted(occurrences.items()):
        if count > 1:
            issues.append(
                _issue(
                    "DUPLICATE_ACTION",
                    Severity.ERROR,
                    instrument,
                    ex_date,
                    f"{action_type} appears {count} times on {ex_date}",
                    {"action_type": action_type, "count": count},
                )
            )
    known_types = {action_type.value for action_type in ActionType}
    for row in rows:
        ex_date: date = row["ex_date"]
        action_type = str(row["action_type"])
        value = _number(row["value"])
        context: dict[str, object] = {"action_type": action_type, "value": row["value"]}
        if action_type not in known_types:
            issues.append(
                _issue(
                    "UNKNOWN_ACTION_TYPE",
                    Severity.ERROR,
                    instrument,
                    ex_date,
                    f"Unknown action type {action_type!r} on {ex_date}; known: "
                    f"{', '.join(sorted(known_types))}",
                    context,
                )
            )
        elif action_type == ActionType.SPLIT.value and (value is None or value <= 0 or value == 1):
            issues.append(
                _issue(
                    "INVALID_SPLIT_RATIO",
                    Severity.ERROR,
                    instrument,
                    ex_date,
                    f"Split ratio {row['value']} on {ex_date} must be positive and not 1",
                    context,
                )
            )
        elif action_type == ActionType.SPIN_OFF.value and (value is None or value <= 0):
            issues.append(
                _issue(
                    "INVALID_SPIN_OFF_FACTOR",
                    Severity.ERROR,
                    instrument,
                    ex_date,
                    f"Spin-off factor {row['value']} on {ex_date} must be positive",
                    context,
                )
            )
        elif action_type in (
            ActionType.DIVIDEND.value,
            ActionType.SPECIAL_DIVIDEND.value,
        ) and (value is None or value <= 0):
            issues.append(
                _issue(
                    "NON_POSITIVE_DIVIDEND",
                    Severity.ERROR,
                    instrument,
                    ex_date,
                    f"Dividend {row['value']} on {ex_date} must be a positive amount",
                    context,
                )
            )
        if (
            action_type in (ActionType.DIVIDEND.value, ActionType.SPECIAL_DIVIDEND.value)
            and instrument.distribution_policy is DistributionPolicy.ACCUMULATING
        ):
            issues.append(
                _issue(
                    "UNEXPECTED_DISTRIBUTION",
                    Severity.ERROR,
                    instrument,
                    ex_date,
                    f"{instrument.id} is an accumulating share class and cannot pay the "
                    f"dividend of {row['value']} reported on {ex_date}",
                    context,
                )
            )
        if _timestamp(row["available_at_utc"]) is None:
            issues.append(
                _issue(
                    "MISSING_AVAILABILITY",
                    Severity.ERROR,
                    instrument,
                    ex_date,
                    f"{action_type} on {ex_date} has no availability instant",
                    context,
                )
            )
    return ValidationReport(instrument_id=instrument.id, issues=_by_date(issues))
