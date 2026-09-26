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
  costs, the universe, the fill assumption, the rebalancing calendar and the
  state of the code is not a result, so the result carries all of them.

What it is not is a second engine. It builds one, runs it, and hands back what
it produced beside the report of it.

It is also the one module of this package that reaches upwards: it imports the
analytics that describe a run and the strategy contract that produces one,
because composing those is its whole job. The engine below it must not, and
does not.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from enum import Enum

import pandas as pd
from matplotlib.figure import Figure

from quant_backtester.analytics.comparison import (
    BenchmarkBasis,
    BenchmarkCurrencyMismatch,
    BenchmarkCurve,
    BenchmarkSpec,
    Comparison,
    compare,
)
from quant_backtester.analytics.config import AnalyticsConfig
from quant_backtester.analytics.curves import Book, drawdown_curve, equity_curve
from quant_backtester.analytics.plots import drawdown_figure, equity_figure
from quant_backtester.analytics.report import PerformanceReport
from quant_backtester.backtest.config import BacktestConfig
from quant_backtester.backtest.engine import BacktestEngine, StrategyMutated
from quant_backtester.backtest.records import BacktestRecord
from quant_backtester.backtest.result import BacktestResult
from quant_backtester.backtest.schedule import DecisionSchedule, EverySession
from quant_backtester.backtest.timetable import BacktestTimetable
from quant_backtester.data.calendars import CalendarRegistry
from quant_backtester.data.reader import MarketDataReader, ObservationStatus
from quant_backtester.data.repository import StoreState
from quant_backtester.data.schemas import ActionType, BarField
from quant_backtester.data.universes import StaticUniverse, UniverseRegistry, UniverseSource
from quant_backtester.execution.model import ExecutionModel
from quant_backtester.numbers import require_finite_positive
from quant_backtester.portfolio.allocation import PortfolioModel
from quant_backtester.portfolio.limits import PortfolioLimits
from quant_backtester.provenance import SourceState
from quant_backtester.signals.base import freeze
from quant_backtester.signals.types import require_identifier
from quant_backtester.strategies.base import Strategy

__all__ = ["Period", "StrategyMutated", "StrategyResult", "StrategyRunner", "value_benchmark"]

Period = date | str
"""A bound of a run: a date, or an ISO string for the convenience of a notebook."""


class StoreChanged(RuntimeError):
    """Raised when a finished run is asked for a figure the store can no longer give.

    The run's records are its own and never change. A benchmark it did not
    value while running has to be read from the store afterwards, and that is
    only the same experiment if the store still holds exactly what the run
    read.
    """


def _digest(value: object) -> str:
    """Return the SHA-256 of a value rendered as canonical JSON."""
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _inputs_digest(reader: MarketDataReader, calendars: CalendarRegistry) -> dict[str, str]:
    """Return the digests of the registries a run was handed, whatever made them.

    The store's digest covers ``metadata/`` as files; a registry built in
    memory, or edited after it was loaded, is covered by nothing there. Two
    calendars sharing the id ``XPAR`` and differing by one holiday gave one
    configuration and one ``run_id`` for two different runs (audit R07,
    decision D15). Every calendar and every instrument a run could have read
    is hashed as it was handed over - a superset of what it did read, which
    errs towards telling runs apart.
    """
    return {
        "calendars": _digest(sorted((c.definition() for c in calendars), key=_calendar_key)),
        "reader_calendars": _digest(
            sorted((c.definition() for c in reader.calendars), key=_calendar_key)
        ),
        "instruments": _digest(
            sorted((i.definition() for i in reader.instruments), key=lambda d: str(d["id"]))
        ),
    }


def _calendar_key(definition: Mapping[str, object]) -> str:
    """Return the id a calendar definition is sorted by."""
    return str(definition["calendar_id"])


def plain_configuration(value: object) -> object:
    """Return a frozen configuration as built-ins JSON can render."""
    if isinstance(value, Mapping):
        return {str(key): plain_configuration(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [plain_configuration(item) for item in value]
    if isinstance(value, Enum):
        return plain_configuration(value.value)
    if isinstance(value, date):
        return value.isoformat()
    return value


@dataclass(frozen=True, slots=True)
class StrategyResult:
    """A finished run, everything it was run with, and the report of it.

    Attributes
    ----------
    backtest : BacktestResult
        The run itself, session by session, with the strategy's definition and
        fingerprint and the state of the code that produced it.
    analytics : PerformanceReport
        Gross and net side by side, the costs between them, what each
        instrument contributed, and the caveats.
    configuration : Mapping[str, object]
        Everything the numbers depend on: what the engine recorded - the
        period, the universe, the calendar, the schedule, the starting cash,
        the limits, the execution and cost models, the lot sizes, the
        timetable - plus the bounds the caller asked for, the analytics
        convention, the declared benchmark and the state of the code.
    reader : MarketDataReader
        The store the run read, kept so that another benchmark can be valued
        over the same sessions afterwards - and only while the store still
        holds exactly what the run read (see ``data_state``).
    data_state : StoreState
        The digest of every file of ``clean/`` and ``metadata/`` while the run
        held the store: no writer could change them during it.
    analytics_config : AnalyticsConfig
        The convention every annualised figure was computed under, applied to a
        benchmark as well so that the two sides are comparable.
    benchmark_spec : BenchmarkSpec | None
        What the run is measured against by default, when the runner declared
        it.
    benchmark_curve : BenchmarkCurve | None
        That benchmark, valued inside the run from the same state of the
        store: kept, never recomputed.

    Notes
    -----
    Everything here is frozen all the way down. A record of an experiment that
    can be edited afterwards is a record of nothing; one that recorded only
    its numbers would be a number nobody can reproduce.
    """

    backtest: BacktestResult
    analytics: PerformanceReport
    configuration: Mapping[str, object]
    reader: MarketDataReader
    data_state: StoreState
    analytics_config: AnalyticsConfig
    benchmark_spec: BenchmarkSpec | None = None
    benchmark_curve: BenchmarkCurve | None = None

    def __post_init__(self) -> None:
        """Freeze the configuration, all the way down."""
        frozen = freeze(dict(self.configuration))
        assert isinstance(frozen, Mapping)
        object.__setattr__(self, "configuration", frozen)

    # -- what the run was -----------------------------------------------------

    @property
    def run_id(self) -> str:
        """Return the identity of the whole experiment.

        Returns
        -------
        str
            SHA-256 of the configuration - which records the code's state and
            the store's digest - and of the strategy's fingerprint. The
            fingerprint names the question; this names the run: the same
            question asked of other data, or by other code, is another run.
        """
        canonical = json.dumps(
            {
                "configuration": plain_configuration(self.configuration),
                "fingerprint": self.fingerprint,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @property
    def strategy_id(self) -> str:
        """Return the name of the strategy that produced the run."""
        return str(self.backtest.strategy_definition["strategy_id"])

    @property
    def definition(self) -> Mapping[str, object]:
        """Return what the strategy was: its class, its parameters, its signals."""
        return self.backtest.strategy_definition

    @property
    def fingerprint(self) -> str:
        """Return the hash of the strategy's definition."""
        return self.backtest.strategy_fingerprint

    @property
    def source(self) -> SourceState:
        """Return the state of the code that produced the run."""
        return self.backtest.source

    @property
    def base_currency(self) -> str:
        """Return the currency the book was kept in."""
        return self.backtest.config.base_currency

    @property
    def start(self) -> date:
        """Return the first session of the run."""
        return self.backtest.records[0].session_date

    @property
    def end(self) -> date:
        """Return the last session of the run."""
        return self.backtest.records[-1].session_date

    # -- what it did ------------------------------------------------------------

    def report(self) -> PerformanceReport:
        """Return the performance report of the run."""
        return self.analytics

    def records(self) -> tuple[BacktestRecord, ...]:
        """Return the records of the run: the source of truth every view is built from."""
        return self.backtest.records

    def frame(self) -> pd.DataFrame:
        """Return the run as a frame, one row per session."""
        return self.backtest.frame()

    def fills(self) -> pd.DataFrame:
        """Return every fill of the run, one row each."""
        return self.backtest.fills()

    def orders(self) -> pd.DataFrame:
        """Return every order of the run, with what became of it."""
        return self.backtest.orders()

    def rejects(self) -> pd.DataFrame:
        """Return every order refused or cut, with its reason."""
        return self.backtest.rejects()

    def holdings(self) -> pd.DataFrame:
        """Return the units held of every instrument, and the cash, after each session."""
        return self.backtest.holdings()

    def weights(self) -> pd.DataFrame:
        """Return what fraction of the book each instrument actually was, per session."""
        return self.backtest.weights()

    def target_weights(self) -> pd.DataFrame:
        """Return the target standing after each session, as the portfolio accepted it."""
        return self.backtest.target_weights()

    def costs(self) -> pd.DataFrame:
        """Return what execution took on each session, term by term."""
        return self.backtest.costs()

    def equity(self, book: Book = Book.NET) -> pd.Series:  # type: ignore[type-arg]
        """Return the equity curve, net of costs by default.

        Parameters
        ----------
        book : Book
            ``NET`` for what an investor would have been left with, ``GROSS``
            for what the same trades would have been worth having paid the
            market price and no fee.

        Returns
        -------
        pd.Series
            Indexed by session date.
        """
        return equity_curve(self.backtest, book)

    def drawdown(self, book: Book = Book.NET) -> pd.Series:  # type: ignore[type-arg]
        """Return the drawdown curve, measured against the running peak."""
        return drawdown_curve(equity_curve(self.backtest, book))

    # -- against what -----------------------------------------------------------

    def benchmark(self, benchmark: BenchmarkSpec | str | None = None) -> BenchmarkCurve:
        """Value something else over the same sessions.

        Parameters
        ----------
        benchmark : BenchmarkSpec | str | None
            What could have been held instead - an instrument id, or a
            specification saying which price basis to compare on. The one the
            runner declared when left out.

        Returns
        -------
        BenchmarkCurve
            Its worth, normalised to this run's starting value. The declared
            benchmark is the curve valued during the run.

        Raises
        ------
        ValueError
            If no benchmark is given and none was declared.
        StoreChanged
            If another benchmark is asked for and the store no longer holds
            what the run read. A revised close would otherwise change the
            conclusion of a finished run (audit A05).
        BenchmarkCurrencyMismatch
            If it is quoted in another currency than the book. Without an FX
            conversion, the difference between the two curves is an exchange
            rate with a strategy's name on it.
        """
        wanted = self._benchmark(benchmark)
        if self.benchmark_curve is not None and wanted == self.benchmark_spec:
            return self.benchmark_curve
        with self.reader.pinned() as now:
            if now.digest != self.data_state.digest:
                changed = sorted(
                    path
                    for path in set(now.files) | set(self.data_state.files)
                    if now.files.get(path) != self.data_state.files.get(path)
                )
                raise StoreChanged(
                    f"the store no longer holds what this run read ({len(changed)} file(s) "
                    f"differ, e.g. {changed[0]}); a benchmark valued now would describe "
                    "another experiment. Run it again."
                )
            return value_benchmark(
                self.backtest, self.reader, wanted, base_currency=self.base_currency
            )

    def compare(
        self, benchmark: BenchmarkSpec | str | None = None, book: Book = Book.NET
    ) -> Comparison:
        """Measure this run against something else, over the days they share.

        Parameters
        ----------
        benchmark : BenchmarkSpec | str | None
            What could have been held instead; the declared one when left out.
        book : Book
            Which of the run's curves to compare, net by default.

        Returns
        -------
        Comparison
            The same statistics for both sides, over the same sessions.
        """
        return compare(self.equity(book), self.benchmark(benchmark), self.analytics_config)

    def plot(
        self,
        benchmark: BenchmarkSpec | str | None = None,
        *,
        gross: bool = True,
    ) -> Figure:
        """Draw the run, and what it could have been measured against.

        Parameters
        ----------
        benchmark : BenchmarkSpec | str | None
            Drawn beside the strategy, normalised to the same starting value -
            the declared one when left out, and none when neither exists.
        gross : bool
            Whether to draw the book that paid nothing behind the net one. The
            gap between the two is what execution took, and it is usually the
            most useful thing in the picture.

        Returns
        -------
        Figure
            A matplotlib figure. ``show`` is never called, so a notebook
            displays it, a script saves it and a test inspects it.
        """
        wanted = benchmark if benchmark is not None else self.benchmark_spec
        other = None if wanted is None else self.benchmark(wanted).equity
        return equity_figure(
            self.equity(),
            title=f"{self.strategy_id}  {self.start} to {self.end}",
            gross=self.equity(Book.GROSS) if gross else None,
            benchmark=other,
        )

    def plot_drawdown(self, book: Book = Book.NET) -> Figure:
        """Draw the drawdown curve, measured against the running peak."""
        return drawdown_figure(
            self.drawdown(book), title=f"{self.strategy_id}  drawdown  {self.start} to {self.end}"
        )

    def _benchmark(self, benchmark: BenchmarkSpec | str | None) -> BenchmarkSpec:
        """Return the benchmark asked for, or the declared one."""
        if benchmark is not None:
            return BenchmarkSpec.of(benchmark)
        if self.benchmark_spec is None:
            raise ValueError(
                "no benchmark was given and the runner declared none; name one, or declare it "
                "on the runner so that every run records what it is measured against"
            )
        return self.benchmark_spec


@dataclass(frozen=True, slots=True)
class StrategyRunner:
    """Runs a strategy over a period, on one store and one set of assumptions.

    Attributes
    ----------
    reader : MarketDataReader
        The store, read point in time. Its reference calendar is the one the
        runs advance on.
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
    execution : ExecutionModel
        The fill assumption and the three costs. Required: a runner that
        defaulted to free trading would report returns no account could have
        had, from a line nobody wrote.
    universes : UniverseRegistry | None
        Where a universe named by its id is looked up. ``None`` runs only with
        a universe given as an object or a list of names.
    initial_cash : float
        What a run starts with, unless a call says otherwise.
    limits : PortfolioLimits
        Applied to whatever a strategy asks for.
    timetable : BacktestTimetable
        When, on each session, an order is filled, the book valued and a
        target decided.
    schedule : DecisionSchedule
        Which sessions a strategy is asked on, unless a call says otherwise.
    source : SourceState
        The state of the code that produces the runs - the commit, and whether
        the tree had uncommitted changes - as the caller established it, with
        :func:`~quant_backtester.provenance.git_source_state` normally.
        Recorded as given and never guessed at: a fingerprint hashes a
        strategy's *configuration*, not its source, so editing a ``decide`` in
        place leaves the fingerprint alone and only this field can say the two
        runs were not the same code.
    benchmark : BenchmarkSpec | str | None
        What every run is measured against by default, recorded with it.

    Raises
    ------
    ValueError
        If the starting cash is not a finite positive number, an identifier is
        empty, the reader counts ages on another calendar, or the benchmark is
        not in the registry.
    BenchmarkCurrencyMismatch
        If the declared benchmark is quoted in another currency than the book.
    """

    reader: MarketDataReader
    calendars: CalendarRegistry
    reference_calendar_id: str
    base_currency: str
    analytics: AnalyticsConfig
    execution: ExecutionModel
    universes: UniverseRegistry | None = None
    initial_cash: float = 100_000.0
    limits: PortfolioLimits = field(default_factory=PortfolioLimits)
    timetable: BacktestTimetable = field(default_factory=BacktestTimetable)
    schedule: DecisionSchedule = field(default_factory=EverySession)
    source: SourceState = field(default_factory=SourceState.unrecorded)
    benchmark: BenchmarkSpec | str | None = None

    def __post_init__(self) -> None:
        """Reject a runner that could not describe the runs it produces."""
        require_identifier(self.reference_calendar_id, "reference_calendar_id")
        require_identifier(self.base_currency, "base_currency")
        require_finite_positive(self.initial_cash, "initial_cash")
        if self.reader.reference_calendar_id != self.reference_calendar_id:
            raise ValueError(
                f"the reader counts ages on {self.reader.reference_calendar_id} and the runs "
                f"advance on {self.reference_calendar_id}"
            )
        if not isinstance(self.execution, ExecutionModel):
            raise ValueError(f"execution must be an ExecutionModel, got {self.execution!r}")
        if self.benchmark is not None:
            spec = BenchmarkSpec.of(self.benchmark)
            if spec.instrument_id not in self.reader.instruments:
                raise ValueError(f"the benchmark {spec.instrument_id!r} is not in the registry")
            _require_same_currency(self.reader, spec, self.base_currency)
            object.__setattr__(self, "benchmark", spec)

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
        InvalidTradingUniverse
            If the universe holds an instrument no book could hold, on any
            session of the period.
        StrategyMutated
            If the strategy's definition changed while it was deciding.
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
        cash = self.initial_cash if initial_cash is None else initial_cash
        require_finite_positive(cash, "initial_cash")
        config = BacktestConfig(
            start=sessions[0].session_date,
            end=sessions[-1].session_date,
            initial_cash=cash,
            base_currency=self.base_currency,
            reference_calendar=self.reference_calendar_id,
            schedule=self.schedule if schedule is None else schedule,
            timetable=self.timetable,
        )
        engine = BacktestEngine(
            reader=self.reader,
            calendars=self.calendars,
            strategy=strategy,
            universe=self._universe(universe),
            config=config,
            execution=self.execution,
            portfolio=PortfolioModel(self.limits),
            source=self.source,
        )
        benchmark = self.benchmark if isinstance(self.benchmark, BenchmarkSpec) else None
        # Every read of the run, the benchmark's included, happens while the
        # store is held: no promotion can land between two of them.
        with self.reader.pinned() as state:
            result = engine.run()
            curve = (
                None
                if benchmark is None
                else value_benchmark(
                    result, self.reader, benchmark, base_currency=self.base_currency
                )
            )
        return StrategyResult(
            backtest=result,
            analytics=PerformanceReport.of(result, self.analytics),
            configuration={
                **result.configuration,
                "requested_start": first.isoformat(),
                "requested_end": last.isoformat(),
                "analytics": self.analytics.definition(),
                "benchmark": benchmark.definition() if benchmark is not None else None,
                "source": result.source.definition(),
                "data_state": state.digest,
                "inputs": _inputs_digest(self.reader, self.calendars),
            },
            reader=self.reader,
            data_state=state,
            analytics_config=self.analytics,
            benchmark_spec=benchmark,
            benchmark_curve=curve,
        )

    def _bounds(self, start: Period, end: Period) -> tuple[date, date]:
        """Return the requested bounds as dates, in order."""
        first, last = _as_date(start, "start"), _as_date(end, "end")
        if first > last:
            raise ValueError(f"start {first} is after end {last}")
        return first, last

    def _universe(self, universe: str | UniverseSource | Sequence[str]) -> UniverseSource:
        """Return the universe to run over.

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
            return self.universes.get(universe)
        if isinstance(universe, UniverseSource):
            return universe
        return StaticUniverse(tuple(universe))


def value_benchmark(
    result: BacktestResult,
    reader: MarketDataReader,
    spec: BenchmarkSpec | str,
    *,
    base_currency: str | None = None,
    book: Book = Book.NET,
) -> BenchmarkCurve:
    """Value a benchmark over the sessions of a finished run.

    Parameters
    ----------
    result : BacktestResult
        The run to compare against. Only its sessions and its starting value
        are used.
    reader : MarketDataReader
        The store, read at each session's valuation instant - the same instant
        the strategy's own equity was valued at, so neither curve sees a price
        the other could not.
    spec : BenchmarkSpec | str
        What could have been held instead.
    base_currency : str | None
        The currency the book is kept in. When given, a benchmark quoted in
        another one is refused rather than drawn.
    book : Book
        Which of the run's curves the starting value is taken from.

    Returns
    -------
    BenchmarkCurve
        Its worth over the same sessions, normalised to the run's starting
        value, naming the sessions it had to be marked from an earlier close
        on.

    Raises
    ------
    ValueError
        If the run holds no session, if the benchmark has no usable price at
        the first one - there is nothing to normalise to - if it stops being
        listed during the run, if it is not registered, or on a corporate
        action :func:`session_growth` refuses.
    BenchmarkCurrencyMismatch
        If it is quoted in another currency than the book.

    Notes
    -----
    It lives here rather than in ``analytics`` because it needs a reader, and
    analytics is handed finished runs precisely so that no statistic can be
    computed against prices the run never saw. This one reads at the run's own
    valuation instants, which is what makes the comparison fair: a benchmark
    valued at today's revision of a price would be measuring the strategy
    against a series that did not exist while it was running.

    The wealth is chained over the benchmark's own sessions - every close
    knowable at the valuation instant since the last one counted - and read at
    the run's valuation instants: a run on another calendar reads the same
    wealth on the days both hold (decision D13). A close the store does not
    have is not invented: the dividend of that session is reinvested at the
    next close there is.

    A session the benchmark's own venue did not hold, or whose close is
    missing, is marked at the last close that existed, and named. A benchmark
    that is no longer listed is not: the run stops a book holding a delisted
    line, and its yardstick is held to the same rule (audit A15, decision D7).
    A European strategy measured against a US index has a handful of closed
    days every year, and a curve with a flat day in it should say why rather
    than look like a day the index did not move.
    """
    specification = BenchmarkSpec.of(spec)
    if not result.records:
        raise ValueError("a benchmark has nothing to be measured over: the run holds no session")
    instrument = reader.instruments.get(specification.instrument_id)
    if base_currency is not None:
        _require_same_currency(reader, specification, base_currency)
    timetable = result.config.timetable
    wealth = 1.0
    path: list[float] = []
    stale: list[date] = []
    last: tuple[date, float] | None = None
    first_observed: date | None = None
    counted: set[tuple[date, str]] = set()
    for record in result.records:
        market = reader.at(record.valuation_time)
        row = market.values([instrument.id], BarField.CLOSE).loc[instrument.id]
        status = row["status"]
        if status is ObservationStatus.NOT_LISTED and last is not None:
            raise ValueError(
                f"{instrument.id} stopped trading before {record.session_date}; a benchmark "
                "is not carried at its last price past its delisting, as the book is not"
            )
        close = None if pd.isna(row["value"]) else float(row["value"])
        if last is None:
            if close is None:
                raise ValueError(
                    f"{instrument.id} has no price at {record.valuation_time}, so there is "
                    "nothing to normalise the benchmark to"
                )
            require_finite_positive(close, f"the first price of {instrument.id}")
            last = (row["observation_date"], close)
            first_observed = row["observation_date"]
        elif close is not None and row["observation_date"] > last[0]:
            # Walk the benchmark's own closes since the last one counted, not
            # just the one of this valuation: a dividend whose ex-date is a
            # session the run's calendar does not hold is reinvested at its own
            # close, as the convention says, and not at the next close the run
            # happens to look at (audit R02, decision D13). Only closes
            # knowable now are walked.
            actions = market.corporate_actions(instrument.id)
            keys = list(zip(actions["ex_date"], actions["action_type"], strict=True))
            known_at = [pd.Timestamp(at) for at in actions["available_at_utc"]]
            since: date = last[0]
            until: date = row["observation_date"]
            closes = market.history(instrument.id, BarField.CLOSE, start=since)
            days: list[date] = list(closes.index)
            steps = [
                (day, float(price))
                for day, price in zip(days, closes, strict=True)
                if since < day <= until
            ]
            steps_from = last[1]
            for day, price in steps:
                # The chronology is the benchmark's own (decision D17): a step
                # is one of its closes, dated at the timetable's valuation
                # instant of that session, and an action counts on the first
                # step on or after its ex-date at which it was already known.
                # Judged by what this valuation knows, an action announced on
                # the 7th was reinvested at the close of the 3rd whenever the
                # run's calendar skipped both, and not when it held them all
                # (audit N01): the same history, two answers.
                step_at = pd.Timestamp(timetable.valuation_instant(day))
                due = [
                    key not in counted and first_observed < key[0] <= day and at <= step_at
                    for key, at in zip(keys, known_at, strict=True)
                ]
                wealth *= session_growth(
                    instrument.id,
                    previous_close=steps_from,
                    close=price,
                    events=actions.loc[due],
                    basis=specification.basis,
                )
                counted.update(key for key, take in zip(keys, due, strict=True) if take)
                steps_from = price
            last = (until, steps_from)
        if status is not ObservationStatus.OK:
            stale.append(record.session_date)
        path.append(wealth)
    start = float(equity_curve(result, book).iloc[0])
    values = pd.Series(
        [start * growth for growth in path],
        index=pd.Index(
            [record.session_date for record in result.records],
            dtype="object",
            name="session_date",
        ),
        name=specification.name,
    )
    return BenchmarkCurve(spec=specification, equity=values, marked_from_earlier=tuple(stale))


def session_growth(
    instrument_id: str,
    *,
    previous_close: float,
    close: float,
    events: pd.DataFrame,
    basis: BenchmarkBasis,
) -> float:
    """Return what one share held from one close to the next has become.

    Parameters
    ----------
    instrument_id : str
        Instrument, quoted in errors.
    previous_close, close : float
        Raw closes at the two ends.
    events : pd.DataFrame
        The corporate actions to count between them, with the columns of
        :meth:`PointInTimeReader.corporate_actions`, in ex-date order.
    basis : BenchmarkBasis
        Whether a distribution is counted.

    Returns
    -------
    float
        ``(shares x close + cash received) / previous close``, where a split
        multiplies the shares and, under ``TOTAL_RETURN``, a dividend - ordinary
        or special - pays its amount on every share held on its ex-date.
        Multiplying the wealth by it reinvests that cash at the close.

    Raises
    ------
    ValueError
        On a spin-off, which is not a split whatever ratio names it and has no
        value here to be counted (decision D3), and on a split and a
        distribution sharing an ex-date: nothing says whether the amount is per
        share before or after the split (decision D2), and the two readings
        differ by the ratio.

    Notes
    -----
    The raw closes are what a holder's worth is made of. The adjusted history
    a signal reads is rebased every time an action becomes known, so its last
    point on one day and its last point on the next are not on the same base
    (audit A01): a 2-for-1 split read that way halved the benchmark.
    """
    kinds_by_day: dict[date, set[ActionType]] = {}
    for ex_date, kind in zip(events["ex_date"], events["action_type"], strict=True):
        kinds_by_day.setdefault(ex_date, set()).add(ActionType(kind))
    for ex_date, kinds in kinds_by_day.items():
        if ActionType.SPIN_OFF in kinds:
            raise ValueError(
                f"{instrument_id} has a spin-off on {ex_date}; a benchmark cannot value what "
                "was distributed, and does not treat it as a split"
            )
        if ActionType.SPLIT in kinds and len(kinds) > 1:
            raise ValueError(
                f"{instrument_id} has a split and a distribution on {ex_date}; whether the "
                "amount is per share before or after the split is not declared"
            )
    shares = 1.0
    cash = 0.0
    for kind, value in zip(events["action_type"], events["value"], strict=True):
        if ActionType(kind) is ActionType.SPLIT:
            shares *= float(value)
        elif basis is BenchmarkBasis.TOTAL_RETURN:
            cash += shares * float(value)
    return (shares * close + cash) / previous_close


def _require_same_currency(
    reader: MarketDataReader, spec: BenchmarkSpec, base_currency: str
) -> None:
    """Raise unless a benchmark is quoted in the currency the book is kept in."""
    instrument = reader.instruments.get(spec.instrument_id)
    if instrument.currency != base_currency:
        raise BenchmarkCurrencyMismatch(
            f"{instrument.id} is quoted in {instrument.currency} and the book is kept in "
            f"{base_currency}; without an FX conversion the difference between the two "
            "curves is an exchange rate"
        )


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
