"""The event loop: the only place in the project that advances time.

One session at a time, and three instants inside each, in this order::

    execution   the decision of the previous session is filled at this open
    valuation   the book is marked at this session's closes
    decision    the signals run, and the next target is decided on that book

A decision is therefore never filled at a price that produced it. That gap -
decide after the close, trade at the next open - is modelled rather than
assumed away, which is what stops a backtest from buying at the very close it
just read. The instants are declared in the run's
:class:`~quant_backtester.backtest.timetable.BacktestTimetable`, and each
reading of the market is taken at its own: the reader built for the execution
cannot see the close the decision will read, and the one built for the decision
cannot see tomorrow's open.

A decision goes through every layer on its way to the book, and each step is
kept in the record of the session::

    Strategy.decide()         what the strategy wants          TargetAllocation
    PortfolioModel.decide()   what the book may hold of it     ConstrainedTarget
    ExecutionModel            what could be done at the open   orders, fills, rejects
    PortfolioState            what is held afterwards          holdings, cash
    value_state()             what that is worth               valuation, estimates

Nothing above this module sees the reader. The strategy is handed a context
built from the decision instant's reader, and the execution layer is handed the
opening prices of its own instant, each with its status.

Gross and net are reported side by side, as the project requires. They are the
same trades: the gross book pays the market price and no fee, the net book pays
the spread, the slippage and the commission. Re-running the strategy without
costs would let the two books hold different things and stop them being
comparable at all.

What this version does not model is stated rather than approximated: a corporate
action on a position the book holds - a split, a dividend - stops the run. The
funds it trades today are accumulating and have not split, and a position that
silently halved overnight, or a dividend that never reached the cash, would be
worse than a run that refuses to continue.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import Protocol

from quant_backtester.backtest.config import BacktestConfig
from quant_backtester.backtest.context import StrategyContext
from quant_backtester.backtest.market import StrategyMarketView
from quant_backtester.backtest.records import BacktestRecord
from quant_backtester.backtest.result import BacktestResult
from quant_backtester.data.calendars import CalendarRegistry
from quant_backtester.data.instruments import InstrumentRegistry
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.data.schemas import BarField
from quant_backtester.data.universes import StaticUniverse, UniverseSource, universe_definition
from quant_backtester.execution.model import Execution, ExecutionModel
from quant_backtester.portfolio.allocation import PortfolioDecision, PortfolioModel
from quant_backtester.portfolio.constraints import check_trading_universe
from quant_backtester.portfolio.state import PortfolioState, ValuationResult, value_state
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.portfolio.view import PortfolioView
from quant_backtester.provenance import SourceState
from quant_backtester.signals.base import Signal, freeze
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.engine import SignalEngine, SignalRequest


class Strategy(Protocol):
    """What the engine needs a strategy to be, and nothing more.

    Declared here rather than imported from ``strategies`` because that package
    sits above this one: a layer that needs something from above takes it as an
    argument instead of reaching for it.
    """

    def decide(self, ctx: StrategyContext) -> TargetAllocation:
        """Return what to hold, given one decision instant."""
        ...

    def required_signals(self) -> Sequence[Signal | SignalRequest]:
        """Return the signals this strategy needs computed for each decision."""
        ...

    def definition(self) -> Mapping[str, object]:
        """Return everything that identifies this strategy, serialisable."""
        ...

    def fingerprint(self) -> str:
        """Return a stable hash of the definition."""
        ...


class StrategyMutated(RuntimeError):
    """Raised when a strategy's declared definition changed during its run.

    A strategy is meant to hold no state between decisions: everything
    path-dependent - what is held, what it is worth, how the market moved -
    comes from the context. A strategy that rebuilt its parameters as it went
    would be recorded under a definition that describes its last decision
    rather than all of them, and the experiment could not be reproduced from
    its own result.

    What this guards is the *declared* definition, compared before and after
    the run - and nothing more. A counter in a closure, a module global, a
    file read inside ``decide`` leave the definition as it was and are not
    seen: no fingerprint of Python code proves a function pure (audit A14).
    The contract is the author's to keep, and the way to check it is to run
    the same strategy twice, on a fresh object each time, and compare.
    """


class UnsupportedCorporateAction(RuntimeError):
    """Raised when a held position goes through a corporate action this version does not book.

    A split multiplies the shares and divides the price overnight; a dividend
    moves value from the price into the cash. Holding the quantity still would
    show the first as a collapse and the second as a loss, and neither ever
    happened - so the run stops, and says which action on which day, rather
    than report either.
    """


@dataclass(frozen=True, slots=True)
class BacktestEngine:
    """Walks the reference calendar: filling at each open, valuing and deciding at each close.

    Attributes
    ----------
    reader : MarketDataReader
        The store, read point in time. The engine is the only holder of it.
        Its reference calendar must be the run's: ages are counted on the
        calendar time advances on.
    calendars : CalendarRegistry
        Venue calendars, for the signals and for the reference timeline.
    strategy : Strategy
        Given a decision context, and nothing else.
    universe : UniverseSource | Sequence[str]
        What the book may hold, asked session by session. A
        :class:`~quant_backtester.data.universes.Universe` carries dated
        memberships, so a run over a changing index chooses among the names
        that were in it on the day - the only way a backtest avoids being a
        study of the survivors. A plain sequence is accepted and wrapped in a
        :class:`~quant_backtester.data.universes.StaticUniverse`: honest for
        two funds that both existed throughout, and a lie for anything with
        entries and exits. An index, a yield or a volatility gauge reaches a
        decision through a
        :class:`~quant_backtester.signals.engine.SignalRequest` of its own,
        which keeps "a thing to read" and "a thing to buy" from being the same
        list.
    config : BacktestConfig
        The period, the cash, the currency, the calendar, the schedule and the
        timetable.
    execution : ExecutionModel
        The fill assumption and the three costs. Required, like the costs
        inside it: no return is reported without a cost model attached.
    portfolio : PortfolioModel
        The limits a decision is held to. None beyond the project's
        invariants by default.
    signals : Sequence[Signal | SignalRequest]
        Signals computed at every decision besides the strategy's own - for a
        run that wants a number recorded that no strategy reads.
    source : SourceState
        The state of the code, as the caller knows it. Recorded as given.

    Raises
    ------
    ValueError
        If the reader counts ages on another calendar than the run advances
        on, the universe is given as a bare id - resolving one is the runner's
        job - or a component is not of the kind expected.
    """

    reader: MarketDataReader
    calendars: CalendarRegistry
    strategy: Strategy
    universe: UniverseSource | Sequence[str]
    config: BacktestConfig
    execution: ExecutionModel
    portfolio: PortfolioModel = field(default_factory=PortfolioModel)
    signals: Sequence[Signal | SignalRequest] = ()
    source: SourceState = field(default_factory=SourceState.unrecorded)

    def __post_init__(self) -> None:
        """Reject a configuration that cannot describe a run, and date the universe."""
        if self.reader.reference_calendar_id != self.config.reference_calendar:
            raise ValueError(
                f"the reader counts ages on {self.reader.reference_calendar_id} and the run "
                f"advances on {self.config.reference_calendar}; a value one session old on "
                "one calendar is fresh on the other"
            )
        if not isinstance(self.execution, ExecutionModel):
            raise ValueError(f"execution must be an ExecutionModel, got {self.execution!r}")
        if not isinstance(self.portfolio, PortfolioModel):
            raise ValueError(f"portfolio must be a PortfolioModel, got {self.portfolio!r}")
        if not isinstance(self.source, SourceState):
            raise ValueError(f"source must be a SourceState, got {self.source!r}")
        if isinstance(self.universe, str):
            raise ValueError(
                f"the universe {self.universe!r} is an id; the engine takes the universe "
                "itself, and the runner is what looks an id up"
            )
        if not isinstance(self.universe, UniverseSource):
            object.__setattr__(self, "universe", StaticUniverse(tuple(self.universe)))
        object.__setattr__(self, "signals", tuple(self.signals))

    @property
    def dated_universe(self) -> UniverseSource:
        """Return the universe in the form the engine asks it: by session."""
        universe = self.universe
        if not isinstance(universe, UniverseSource):
            raise TypeError(f"the universe was not dated: {universe!r}")
        return universe

    @property
    def instruments(self) -> InstrumentRegistry:
        """Return the registry the reader resolves against."""
        return self.reader.instruments

    def run(self) -> BacktestResult:
        """Walk the sessions of the configured period and return what happened.

        Returns
        -------
        BacktestResult
            One record per session, and everything the run was made with.

        Raises
        ------
        ValueError
            If the period holds no session of the reference calendar.
        InvalidTradingUniverse
            If the trading universe holds, on any session of the period, an
            instrument no book could hold - checked before the first session
            is walked, not on the day that instrument first comes up.
        CalendarCoverageError
            If the period reaches outside the reference calendar's coverage.
            Loud on purpose: inventing sessions past the end of a holiday list
            is how a backtest ends up trading on Christmas.
        StrategyMutated
            If the strategy's definition changed while it was deciding.
        UnsupportedCorporateAction
            If a held position goes through a split or a dividend.

        Notes
        -----
        The target decided on the last session is never filled, since no
        session follows it inside the period. It is still recorded, because
        what a strategy wanted on its last day is part of what the run says.
        """
        config = self.config
        timetable = config.timetable
        calendar = self.calendars.get(config.reference_calendar)
        sessions = [session.session_date for session in calendar.sessions(config.start, config.end)]
        if not sessions:
            raise ValueError(
                f"{config.start} to {config.end} holds no session of {config.reference_calendar}"
            )
        self._check_universe(sessions)
        # Asked once, and used for every decision of this run. A strategy that
        # answered differently on the second session would be computing signals
        # nobody recorded - the declaration and what ran must be one thing.
        declared = self._declared_signals()
        # Taken before the run, not after: a strategy that changed itself while
        # deciding would otherwise be recorded in its final state.
        definition = self._strategy_definition()
        fingerprint = self.strategy.fingerprint()
        configuration = self._configuration(sessions)
        deciding = config.schedule.decision_sessions(
            sessions, following=calendar.next_session(sessions[-1]).session_date
        )
        signal_engine = SignalEngine()

        state = PortfolioState.opening(
            config.initial_cash, timetable.execution_instant(sessions[0])
        )
        gross_cash = config.initial_cash
        last_known: dict[str, float] = {}
        pending: PortfolioDecision | None = None
        pending_from: date | None = None
        standing = 0.0
        previous: date | None = None
        records: list[BacktestRecord] = []

        for session_date in sessions:
            execution_at = timetable.execution_instant(session_date)
            self._require_no_corporate_action(state, previous, session_date, execution_at)
            execution: Execution | None = None
            if pending is not None:
                execution = self._execute(state, pending, session_date, execution_at, last_known)
                state = execution.state
                for fill in execution.fills:
                    # The same trade, at the price on the screen and with no fee,
                    # booked in the same order as the net book books it.
                    gross_cash = gross_cash + fill.gross_cash_flow
                    last_known[fill.instrument_id] = fill.market_price
            valuation_at = timetable.valuation_instant(session_date)
            valuation = self._value(state, valuation_at, last_known)
            last_known.update(valuation.prices)
            decision: PortfolioDecision | None = None
            decision_at: datetime | None = None
            if session_date in deciding:
                decision_at = timetable.decision_instant(session_date)
                decision = self._decide(
                    signal_engine, session_date, decision_at, state, valuation, declared
                )
                standing = decision.constrained.invested
            records.append(
                BacktestRecord(
                    session_date=session_date,
                    valuation_time=valuation_at,
                    cash=state.cash,
                    gross_cash=gross_cash,
                    holdings=state.holdings,
                    valuation_prices=valuation.prices,
                    target_invested=standing,
                    estimated_valuation_instruments=valuation.estimated_instruments,
                    execution_time=execution.at if execution is not None else None,
                    executed_decision=pending_from if execution is not None else None,
                    orders=execution.orders if execution is not None else (),
                    fills=execution.fills if execution is not None else (),
                    rejects=execution.rejects if execution is not None else (),
                    decision_time=decision_at,
                    decision=decision,
                )
            )
            # Not a decision session: nothing is asked, so nothing is sent at the
            # next open. What stands is the last decision, which the book holds.
            pending = decision
            pending_from = session_date if decision is not None else None
            previous = session_date

        if self.strategy.fingerprint() != fingerprint:
            raise StrategyMutated(
                "the strategy is not the one it was at the start of the run: its definition "
                "changed while it was deciding. A strategy holds no state between decisions - "
                "what is path-dependent comes from the context."
            )
        return BacktestResult(
            records=tuple(records),
            config=config,
            configuration=configuration,
            strategy_definition=definition,
            strategy_fingerprint=fingerprint,
            source=self.source,
        )

    def _members(self, session_date: date) -> tuple[str, ...]:
        """Return the trading universe on one session, in instrument order.

        Sorted whatever the universe was declared in: two runs over the same
        names written in two orders are the same experiment, and a ranking
        that breaks ties in the order it is asked must not be able to tell
        them apart.
        """
        return tuple(sorted(self.dated_universe.members_at(session_date)))

    def _check_universe(self, sessions: Sequence[date]) -> None:
        """Raise unless every member the universe will ever have in the run could be held.

        Notes
        -----
        Every session is asked, before the first one is walked, and each
        member is checked on the first session it appears on - so the error
        names the day, and a run whose configuration is wrong in its last year
        fails in its first second rather than after seven years of sessions.
        """
        seen: set[str] = set()
        for session_date in sessions:
            new = set(self.dated_universe.members_at(session_date)) - seen
            if new:
                check_trading_universe(
                    new,
                    instruments=self.instruments,
                    base_currency=self.config.base_currency,
                    on=session_date,
                )
                seen |= new

    def _require_no_corporate_action(
        self, state: PortfolioState, previous: date | None, session_date: date, at: datetime
    ) -> None:
        """Raise if a held position goes ex on a corporate action since the last session.

        Parameters
        ----------
        state : PortfolioState
            The book before this session's fills.
        previous : date | None
            The previous session of the run; ``None`` on the first, when
            nothing is held yet.
        session_date : date
            The session about to be walked.
        at : datetime
            Its execution instant: an action is knowable at the open of its
            ex-date, which is the first price it affects.
        """
        if previous is None or not state.holdings:
            return
        market = self.reader.at(at)
        for instrument_id in state.holdings:
            actions = market.corporate_actions(instrument_id)
            for action_type, ex_date, value in zip(
                actions["action_type"], actions["ex_date"], actions["value"], strict=True
            ):
                if previous < ex_date <= session_date:
                    raise UnsupportedCorporateAction(
                        f"{instrument_id} is held and goes ex on a {action_type} of {value} on "
                        f"{ex_date}. This version does not book a corporate action on a "
                        "position - a split would read as a collapse of the price and a "
                        "dividend would never reach the cash - so the run stops rather than "
                        "report either."
                    )

    def _execute(
        self,
        state: PortfolioState,
        decision: PortfolioDecision,
        session_date: date,
        at: datetime,
        last_known: Mapping[str, float],
    ) -> Execution:
        """Fill the previous decision at this session's opening auction.

        Notes
        -----
        The prices are read at the execution instant and nowhere else, with
        their status: only an opening price of this session is ever traded
        on. The universe passed on is this session's, so a name that left it
        between the decision and the open is not bought - and may always be
        sold. A decision to keep the positions is carried out too, as an
        execution with nothing to do: the record says the decision was acted
        on, and that acting on it sent no order.
        """
        market = self.reader.at(at)
        wanted = sorted(set(decision.accepted_weights) | set(state.holdings))
        quotes = market.observations(wanted, self.config.timetable.execution.field)
        return self.execution.rebalance(
            state,
            decision.accepted_weights,
            at=at,
            session=session_date,
            quotes=quotes,
            last_known=last_known,
            instruments=self.instruments,
            base_currency=self.config.base_currency,
            universe=self._members(session_date),
            hold=decision.holds_positions,
            keep=decision.kept,
        )

    def _value(
        self, state: PortfolioState, at: datetime, last_known: Mapping[str, float]
    ) -> ValuationResult:
        """Mark the book at the closing prices knowable at the valuation instant."""
        held = sorted(state.holdings)
        observations = self.reader.at(at).observations(held, BarField.CLOSE) if held else {}
        return value_state(state, observations, last_known, at)

    def _decide(
        self,
        engine: SignalEngine,
        session_date: date,
        at: datetime,
        state: PortfolioState,
        valuation: ValuationResult,
        declared: Sequence[Signal | SignalRequest],
    ) -> PortfolioDecision:
        """Compute the signals, ask the strategy, and hold its answer to the portfolio's rules.

        Parameters
        ----------
        engine : SignalEngine
            Computes the declared signals for this decision.
        session_date : date
            The session being decided on.
        at : datetime
            The decision instant.
        state : PortfolioState
            The book, before the order this decision will produce.
        valuation : ValuationResult
            What it was just valued at.
        declared : Sequence[Signal | SignalRequest]
            The signals of the run, resolved once at its start.

        Returns
        -------
        PortfolioDecision
            What the strategy asked for and what the book may hold of it.

        Raises
        ------
        TypeError
            If the strategy answers with something other than an allocation.
        ValueError
            If the allocation answers for another instant than the decision.
        InadmissibleTarget
            If it names an instrument the book may not hold.

        Notes
        -----
        Every universe is asked about this session, the trading one and each
        signal's own, and every list of names is put in instrument order
        before anything is computed on it. A request carrying a dated universe
        is resolved here because here is the only place that knows which
        session is being decided.
        """
        members = self._members(session_date)
        context = SignalContext(
            market=self.reader.at(at), instruments=self.instruments, calendars=self.calendars
        )
        requests = [_canonical(item, session_date) for item in declared]
        snapshot = engine.compute(context, requests, list(members))
        ctx = StrategyContext(
            as_of=context.as_of,
            signals=snapshot,
            market=StrategyMarketView(context),
            portfolio=PortfolioView.of(state, valuation.prices, context.as_of),
            universe=members,
            instruments=self.instruments,
        )
        requested = self.strategy.decide(ctx)
        if not isinstance(requested, TargetAllocation):
            raise TypeError(
                f"the strategy returned {requested!r}; a decision is a TargetAllocation"
            )
        if requested.as_of != context.as_of:
            raise ValueError(
                f"the strategy answered for {requested.as_of} and was asked at {context.as_of}"
            )
        if requested.hold_positions and dict(requested.weights) != dict(ctx.portfolio.weights):
            raise ValueError(
                "a decision to keep the positions must record the book as it is: it asked "
                f"for {dict(requested.weights)} and the book was {dict(ctx.portfolio.weights)}"
            )
        book = dict(ctx.portfolio.weights)
        misrecorded = sorted(
            name for name in requested.kept if requested.weights[name] != book.get(name)
        )
        if misrecorded:
            raise ValueError(
                f"{', '.join(misrecorded)} is kept at a weight that is not the book's: a kept "
                "line is recorded as it is"
            )
        return self.portfolio.decide(
            requested,
            instruments=self.instruments,
            universe=members,
            base_currency=self.config.base_currency,
        )

    def _declared_signals(self) -> tuple[Signal | SignalRequest, ...]:
        """Return the signals to compute: the engine's, plus the strategy's own.

        Notes
        -----
        A strategy declares what it reads, so that nobody can run one while
        forgetting a signal it needs - a mistake that produces a ``KeyError``
        deep inside a decision at best, and a different backtest at worst.
        """
        return (*self.signals, *self.strategy.required_signals())

    def _strategy_definition(self) -> Mapping[str, object]:
        """Return the strategy's definition, frozen, or refuse a strategy that has none."""
        definition = self.strategy.definition()
        if not isinstance(definition, Mapping):
            raise TypeError(
                f"the strategy's definition is {definition!r}; a run records what it ran, and "
                "a strategy that cannot say what it is cannot be recorded"
            )
        frozen = freeze(dict(definition))
        assert isinstance(frozen, Mapping)
        return frozen

    def _configuration(self, sessions: Sequence[date]) -> dict[str, object]:
        """Return everything the numbers of a run depend on, apart from the strategy.

        Notes
        -----
        The lot size of every instrument the book could hold during the run is
        recorded beside the rest: it is read from the registry, and a registry
        edited afterwards would otherwise change what a result says it was run
        with.
        """
        members = sorted(
            {name for session in sessions for name in self.dated_universe.members_at(session)}
        )
        return {
            **self.config.definition(),
            "universe": universe_definition(self.dated_universe),
            "signals": [_signal_definition(item) for item in self.signals],
            "portfolio": self.portfolio.definition(),
            "execution": self.execution.definition(),
            "quantity_steps": {name: self.instruments.get(name).quantity_step for name in members},
            # Decision D9: a decision is sent to the next open and to that one
            # only. An order refused there is not carried: the next decision
            # replaces it, and on a monthly schedule that is a month away.
            "decision_lifetime": "one execution",
        }


def _canonical(item: Signal | SignalRequest, session_date: date) -> Signal | SignalRequest:
    """Return a declared signal resolved for one session, its names in instrument order."""
    if not isinstance(item, SignalRequest):
        return item
    resolved = item.resolved(session_date)
    names = resolved.names()
    if names is None:
        return resolved
    return replace(resolved, instruments=tuple(sorted(names)))


def _signal_definition(item: Signal | SignalRequest) -> Mapping[str, object]:
    """Return one engine-level signal's definition, its own universe included."""
    if isinstance(item, SignalRequest):
        return item.definition()
    return {"signal": item.definition_json(), "instruments": None}
