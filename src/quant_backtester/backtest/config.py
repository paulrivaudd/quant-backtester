"""Everything a run is, apart from the strategy and the data it reads.

A backtest result is a function of committed code, the market data store and
this: the period, the starting cash, the currency the book is kept in, the
calendar time advances on, how often the strategy is asked and when in each
session things happen. None of them has a default that matters, because each
of them changes the numbers - and a number whose conditions nobody wrote down
is a number nobody can reproduce.

The object is immutable and validated where it is built. A starting cash of
``NaN``, a period running backwards or a time with an offset baked into it is
refused here, before a single session is walked, rather than discovered in an
equity curve.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

from quant_backtester.backtest.schedule import (
    DecisionSchedule,
    EveryNSessions,
    EverySession,
    Monthly,
    Weekly,
)
from quant_backtester.backtest.timetable import BacktestTimetable
from quant_backtester.numbers import require_finite_positive
from quant_backtester.signals.types import require_identifier

_CURRENCY = re.compile(r"[A-Z]{3}")
"""An ISO 4217 code: three capital letters."""


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    """The conditions of one run.

    Attributes
    ----------
    start, end : date
        Inclusive bounds of the run, as sessions of the reference calendar.
        The performance starts at ``start``; the data does not - a signal may
        read as far back as it needs, which is what a warm-up is.
    initial_cash : float
        What the run starts with, in ``base_currency``, all of it in cash.
    base_currency : str
        The ISO code of the currency the book is kept in. Every instrument the
        book may hold is quoted in it: nothing here converts one currency into
        another.
    reference_calendar : str
        The calendar time advances on. A European strategy decides on Paris
        sessions even when a signal reads a US index.
    schedule : DecisionSchedule
        Which sessions the strategy is asked on.
    timetable : BacktestTimetable
        When, on each session, orders are filled, the book is valued and the
        next target is decided - and at which price an order is filled.

    Raises
    ------
    ValueError
        If a bound is not a plain date or the period runs backwards, the
        starting cash is not a finite positive number, the currency is not an
        ISO code, the calendar is not a name, or the schedule or the timetable
        is not one this version knows.
    """

    start: date
    end: date
    initial_cash: float
    base_currency: str
    reference_calendar: str
    schedule: DecisionSchedule
    timetable: BacktestTimetable

    def __post_init__(self) -> None:
        """Reject a configuration that cannot describe a run."""
        for name, bound in (("start", self.start), ("end", self.end)):
            # A datetime is a date too, and would carry an instant nobody
            # meant into a bound that is a session.
            if not isinstance(bound, date) or isinstance(bound, datetime):
                raise ValueError(f"{name} must be a date, got {bound!r}")
        if self.start > self.end:
            raise ValueError(f"start {self.start} is after end {self.end}")
        require_finite_positive(self.initial_cash, "initial_cash")
        if not isinstance(self.base_currency, str) or not _CURRENCY.fullmatch(self.base_currency):
            raise ValueError(
                f"base_currency must be an ISO 4217 code such as 'EUR', got {self.base_currency!r}"
            )
        require_identifier(self.reference_calendar, "reference_calendar")
        if not isinstance(self.schedule, EverySession | EveryNSessions | Weekly | Monthly):
            raise ValueError(f"schedule must be a DecisionSchedule, got {self.schedule!r}")
        if not isinstance(self.timetable, BacktestTimetable):
            raise ValueError(f"timetable must be a BacktestTimetable, got {self.timetable!r}")

    def definition(self) -> dict[str, object]:
        """Return the configuration as it is recorded with a run.

        Returns
        -------
        dict[str, object]
            Built-ins only. The schedule is recorded with its parameters:
            deciding every five sessions and every twenty are two experiments.
        """
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "initial_cash": self.initial_cash,
            "base_currency": self.base_currency,
            "reference_calendar": self.reference_calendar,
            "schedule": self.schedule.definition(),
            "timetable": self.timetable.definition(),
        }
