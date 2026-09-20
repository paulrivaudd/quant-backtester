"""Running a strategy over a period, and recording what it was run with.

The engine is the primitive: it takes a reader, a calendar, a universe, a
strategy, a cost model and a timetable, and it walks sessions. Everything in
that list has to be right, and a user comparing two lookbacks should not have
to restate all of it twice.

So this is the façade. It is wired once with the store and the configuration
that do not change between experiments, and then::

    result = runner.run(MomentumRotation(top_n=2), "ROTATION_2", "2018-01-01", "2026-09-18")

Three things it is careful about, because each of them is a way to get a wrong
number quietly:

- **the bounds are read as sessions.** A Saturday is not a session, so a run
  from the first of January starts at the first session on or after it, and
  ends at the last session on or before ``end``;
- **there is no warm-up.** ``start`` is where the *performance* starts, not
  where the data does. A sixty-session momentum run from January reads the
  previous October, because the reader is point-in-time and has always been
  allowed to look back - what it may never do is look forward;
- **the configuration is recorded.** A Sharpe ratio without the period, the
  costs, the universe, the fill assumption and the rebalancing calendar is not
  a result, so the result carries all of them.

What it is not is a second engine. It builds one, runs it, and hands back what
it produced beside the report of it.

It is also the one module of this package that reaches upwards: it imports the
analytics that describe a run and the strategy contract that produces one,
because composing those is its whole job. The engine below it must not, and
does not.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from quant_backtester.analytics.config import AnalyticsConfig
from quant_backtester.analytics.curves import Book, drawdown_curve, equity_curve
from quant_backtester.analytics.report import PerformanceReport
from quant_backtester.backtest.engine import BacktestEngine, BacktestResult, Timetable
from quant_backtester.backtest.schedule import DecisionSchedule, EverySession
from quant_backtester.data.calendars import CalendarRegistry
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.data.universes import StaticUniverse, UniverseRegistry, UniverseSource
from quant_backtester.execution.fills import ExecutionModel
from quant_backtester.numbers import require_finite_positive
from quant_backtester.portfolio.limits import PositionLimits
from quant_backtester.signals.types import require_identifier
from quant_backtester.strategies.base import Strategy

Period = date | str
"""A bound of a run: a date, or an ISO string for the convenience of a notebook."""


@dataclass(frozen=True, slots=True)
class StrategyResult:
    """A finished run, everything it was run with, and the report of it.

    Attributes
    ----------
    strategy_id : str
        Name of the strategy that produced it.
    definition : Mapping[str, object]
        What the strategy was: its class, its parameters, its signals.
    fingerprint : str
        Hash of that definition, for telling two experiments apart.
    configuration : Mapping[str, object]
        Everything else the numbers depend on: the period, the universe, the
        reference calendar, the rebalancing schedule, the starting cash, the
        limits, the cost model and the fill timetable.
    backtest : BacktestResult
        The run itself, session by session.
    analytics : PerformanceReport
        Gross and net side by side, the costs between them, what each
        instrument contributed, and the caveats.

    Notes
    -----
    A result that recorded only its numbers would be a number nobody can
    reproduce. Everything here is what "Sharpe 1.4" has to be read with, and
    it is carried in the object rather than remembered by whoever ran it.
    """

    strategy_id: str
    definition: Mapping[str, object]
    fingerprint: str
    configuration: Mapping[str, object]
    backtest: BacktestResult
    analytics: PerformanceReport

    @property
    def start(self) -> date:
        """Return the first session of the run."""
        return self.backtest.records[0].session_date

    @property
    def end(self) -> date:
        """Return the last session of the run."""
        return self.backtest.records[-1].session_date

    def report(self) -> PerformanceReport:
        """Return the performance report of the run."""
        return self.analytics

    def equity(self, book: Book = Book.NET) -> pd.Series:  # type: ignore[type-arg]
        """Return the equity curve, net of costs by default.

        Parameters
        ----------
        book : Book
            ``NET`` for what an investor would have been left with, ``GROSS``
            for what the same trades would have been worth having paid the
            reference price and no fee.

        Returns
        -------
        pd.Series
            Indexed by session date.
        """
        return equity_curve(self.backtest, book)

    def drawdown(self, book: Book = Book.NET) -> pd.Series:  # type: ignore[type-arg]
        """Return the drawdown curve, measured against the running peak."""
        return drawdown_curve(equity_curve(self.backtest, book))

    def frame(self) -> pd.DataFrame:
        """Return the run as a frame, one row per session."""
        return self.backtest.frame()


@dataclass(frozen=True, slots=True)
class StrategyRunner:
    """Runs a strategy over a period, on one store and one set of assumptions.

    Attributes
    ----------
    reader : MarketDataReader
        The store, read point in time.
    calendars : CalendarRegistry
        Venue calendars, and the reference one among them.
    reference_calendar_id : str
        The calendar time is advanced on.
    base_currency : str
        The currency the book is kept in.
    analytics : AnalyticsConfig
        The annualisation convention and the rate the Sharpe ratio is taken
        against. Required, like everywhere else in this project: a ratio whose
        convention nobody stated is not comparable with anything.
    universes : UniverseRegistry | None
        Where a universe named by its id is looked up. ``None`` runs only with
        a universe given as an object or a list of names.
    initial_cash : float
        What a run starts with, unless a call says otherwise.
    limits : PositionLimits
        Applied to whatever a strategy asks for.
    execution : ExecutionModel
        The fill assumption and the three costs.
    timetable : Timetable
        When a decision is taken, and when it is filled.
    schedule : DecisionSchedule
        Which sessions a strategy is asked on, unless a call says otherwise.

    Raises
    ------
    ValueError
        If the starting cash is not a finite positive number, or an identifier
        is empty.
    """

    reader: MarketDataReader
    calendars: CalendarRegistry
    reference_calendar_id: str
    base_currency: str
    analytics: AnalyticsConfig
    universes: UniverseRegistry | None = None
    initial_cash: float = 100_000.0
    limits: PositionLimits = field(default_factory=PositionLimits)
    execution: ExecutionModel = field(default_factory=ExecutionModel)
    timetable: Timetable = field(default_factory=Timetable)
    schedule: DecisionSchedule = field(default_factory=EverySession)

    def __post_init__(self) -> None:
        """Reject a runner that could not describe the runs it produces."""
        require_identifier(self.reference_calendar_id, "reference_calendar_id")
        require_identifier(self.base_currency, "base_currency")
        require_finite_positive(self.initial_cash, "initial_cash")

    def run(
        self,
        strategy: Strategy,
        universe: str | UniverseSource | Sequence[str],
        start: Period,
        end: Period,
        *,
        initial_cash: float | None = None,
        schedule: DecisionSchedule | None = None,
    ) -> StrategyResult:
        """Run a strategy over a period and return the result with its configuration.

        Parameters
        ----------
        strategy : Strategy
            What to run. Its declared signals are computed at every decision.
        universe : str | UniverseSource | Sequence[str]
            What it may hold: the id of a committed universe, a universe
            object, or a plain list of names - which is honest only for
            instruments that existed throughout the period.
        start, end : date | str
            Inclusive bounds of the *measured performance*. A bound that is not
            a session moves inwards to one that is. Data before ``start`` stays
            available to the signals: that is what a warm-up is, and forbidding
            it would give every strategy two months of artificial cash.
        initial_cash : float | None
            What the run starts with; the runner's own by default.
        schedule : DecisionSchedule | None
            Which sessions to decide on; the runner's own by default.

        Returns
        -------
        StrategyResult
            The run, the report, and everything both were produced with.

        Raises
        ------
        ValueError
            If the strategy cannot be run, if the period holds no session of
            the reference calendar, or if a universe id is not declared.
        CalendarCoverageError
            If the period reaches outside the reference calendar's coverage.
        """
        strategy.validate()
        calendar = self.calendars.get(self.reference_calendar_id)
        first, last = self._bounds(start, end)
        sessions = calendar.sessions(first, last)
        if not sessions:
            raise ValueError(
                f"{first} to {last} holds no session of {self.reference_calendar_id}; "
                "there is nothing to measure a performance over"
            )
        resolved, universe_id = self._universe(universe)
        cash = self.initial_cash if initial_cash is None else initial_cash
        require_finite_positive(cash, "initial_cash")
        decisions = self.schedule if schedule is None else schedule
        engine = BacktestEngine(
            reader=self.reader,
            calendars=self.calendars,
            reference_calendar_id=self.reference_calendar_id,
            signals=(),
            strategy=strategy,
            universe=resolved,
            initial_cash=cash,
            base_currency=self.base_currency,
            schedule=decisions,
            limits=self.limits,
            execution=self.execution,
            timetable=self.timetable,
        )
        result = engine.run(sessions[0].session_date, sessions[-1].session_date)
        return StrategyResult(
            strategy_id=strategy.strategy_id,
            definition=strategy.definition(),
            fingerprint=strategy.fingerprint(),
            configuration=self._configuration(
                start=sessions[0].session_date,
                end=sessions[-1].session_date,
                asked=(first, last),
                universe_id=universe_id,
                cash=cash,
                schedule=decisions,
            ),
            backtest=result,
            analytics=PerformanceReport.of(result, self.analytics),
        )

    def _bounds(self, start: Period, end: Period) -> tuple[date, date]:
        """Return the requested bounds as dates, in order."""
        first, last = _as_date(start, "start"), _as_date(end, "end")
        if first > last:
            raise ValueError(f"start {first} is after end {last}")
        return first, last

    def _universe(
        self, universe: str | UniverseSource | Sequence[str]
    ) -> tuple[UniverseSource, str | None]:
        """Return the universe to run over, and the id it was named by.

        Raises
        ------
        ValueError
            If a universe is named by id and no registry was given, or the
            registry does not declare it.
        """
        if isinstance(universe, str):
            if self.universes is None:
                raise ValueError(
                    f"the universe {universe!r} was named by id and this runner was "
                    "given no universe registry to look it up in"
                )
            return self.universes.get(universe), universe
        if isinstance(universe, UniverseSource):
            return universe, getattr(universe, "universe_id", None)
        return StaticUniverse(tuple(universe)), None

    def _configuration(
        self,
        *,
        start: date,
        end: date,
        asked: tuple[date, date],
        universe_id: str | None,
        cash: float,
        schedule: DecisionSchedule,
    ) -> dict[str, object]:
        """Return everything the numbers of a run depend on."""
        return {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "requested_start": asked[0].isoformat(),
            "requested_end": asked[1].isoformat(),
            "reference_calendar": self.reference_calendar_id,
            "base_currency": self.base_currency,
            "universe": universe_id,
            "initial_cash": cash,
            "schedule": type(schedule).__name__,
            "limits": {
                "max_weight": self.limits.max_weight,
                "max_gross": self.limits.max_gross,
            },
            "costs": {
                "commission_rate": self.execution.costs.commission_rate,
                "minimum_commission": self.execution.costs.minimum_commission,
                "half_spread": self.execution.costs.half_spread,
                "slippage_rate": self.execution.costs.slippage_rate,
                "minimum_trade_value": self.execution.minimum_trade_value,
            },
            "timetable": {
                "decision_time": self.timetable.decision_time.isoformat(),
                "execution_time": self.timetable.execution_time.isoformat(),
                "timezone": self.timetable.timezone,
            },
            "analytics": {
                "sessions_per_year": self.analytics.sessions_per_year,
                "risk_free_rate": self.analytics.risk_free_rate,
            },
        }


def _as_date(value: Period, name: str) -> date:
    """Return a bound as a plain date.

    Parameters
    ----------
    value : date | str
        The bound, as a date or an ISO string.
    name : str
        Its name, quoted in the message.

    Returns
    -------
    date
        The bound.

    Raises
    ------
    ValueError
        If a string is not an ISO date, or the value is neither.
    """
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            raise ValueError(
                f"{name} must be an ISO date such as 2018-01-01, got {value!r}"
            ) from None
    if isinstance(value, date):
        return value
    raise ValueError(f"{name} must be a date or an ISO date string, got {value!r}")
