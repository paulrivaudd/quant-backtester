"""The event loop: the only place in the project that advances time.

One session at a time, and the order inside a session is the whole point::

    open of session s      the allocation decided on s-1 is filled here
    close of session s     the portfolio is valued
    after that close       the signals are computed and s+1's target is decided

A decision is therefore never filled at a price that produced it. That gap -
decide after the close, trade at the next open - is modelled rather than
assumed away, which is what stops a backtest from buying at the very close it
just read.

Nothing above this module sees the reader. The engine builds two of them per
session, one for the decision and one for the fill, and hands the strategy only
what the signals made of the first. It builds them from the same
:class:`~quant_backtester.data.reader.MarketDataReader`, so a run reads exactly
what was knowable at each instant and nothing else.

Gross and net are reported side by side, as the project requires. They are the
same trades: the gross book pays the reference price and no commission, the net
book pays the spread, the slippage and the fee. Re-running the strategy without
costs would let the two books hold different things and stop them being
comparable at all.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time
from types import MappingProxyType
from typing import Protocol
from zoneinfo import ZoneInfo

import pandas as pd

from quant_backtester.data.calendars import CalendarRegistry, Session
from quant_backtester.data.instruments import InstrumentRegistry
from quant_backtester.data.reader import MarketDataReader, ObservationStatus, PointInTimeReader
from quant_backtester.data.schemas import BarField
from quant_backtester.data.universes import StaticUniverse, UniverseSource
from quant_backtester.execution.fills import Execution, ExecutionModel, Fill
from quant_backtester.numbers import require_finite_positive
from quant_backtester.portfolio.limits import PositionLimits
from quant_backtester.portfolio.targets import Holdings, TargetAllocation
from quant_backtester.signals.base import Signal
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.engine import SignalEngine, SignalRequest
from quant_backtester.signals.snapshot import SignalSnapshot
from quant_backtester.signals.types import require_identifier


class Strategy(Protocol):
    """What the engine needs a strategy to be, and nothing more.

    Declared here rather than imported from ``strategies`` because that package
    sits above this one: a layer that needs something from above takes it as an
    argument instead of reaching for it.
    """

    def decide(self, signals: SignalSnapshot) -> TargetAllocation:
        """Return what to hold, given the signals of one decision instant."""
        ...


@dataclass(frozen=True, slots=True)
class Timetable:
    """When a decision is taken, and when it is filled.

    Attributes
    ----------
    decision_time : time
        Local time, on the decision session, at which the signals are computed.
        Late enough that the closes the strategy reads are published: 23:00 in
        Paris is after New York's, which is the case the project is built for.
    execution_time : time
        Local time, on the next session, at which the order is filled. Just
        after the opening auction, since that is the price it is filled at.
    timezone : str
        IANA zone both times are expressed in. The reference calendar's own
        zone, normally, so that a run is stated in the hours its decisions are
        actually taken in.

    Raises
    ------
    ValueError
        If either time carries a fixed offset. A wall-clock time plus a zone
        survives a DST switch; a time with an offset baked in does not, and the
        decision would move by an hour twice a year.
    """

    decision_time: time = time(23, 0)
    execution_time: time = time(9, 1)
    timezone: str = "Europe/Paris"

    def __post_init__(self) -> None:
        """Reject a time that carries its own offset."""
        for name, value in (
            ("decision_time", self.decision_time),
            ("execution_time", self.execution_time),
        ):
            if value.tzinfo is not None:
                raise ValueError(f"{name} must be a naive local time, got {value!r}")
        ZoneInfo(self.timezone)

    def decision_instant(self, session_date: date) -> datetime:
        """Return the UTC-aware instant a decision is taken on that session."""
        return datetime.combine(session_date, self.decision_time, tzinfo=ZoneInfo(self.timezone))

    def execution_instant(self, session_date: date) -> datetime:
        """Return the UTC-aware instant an order is filled on that session."""
        return datetime.combine(session_date, self.execution_time, tzinfo=ZoneInfo(self.timezone))


@dataclass(frozen=True, slots=True)
class BacktestRecord:
    """What happened on one session.

    Attributes
    ----------
    session_date : date
        The session of the reference calendar this record is about.
    decision_at : datetime
        When the portfolio was valued and the next target decided.
    equity : float
        Total worth after costs, at this session's close.
    gross_equity : float
        What the same trades would have been worth having paid the reference
        price and no fee. The difference is everything execution took.
    cash : float
        The part not invested.
    target_invested : float
        Fraction of equity the target decided at this close asks to put to
        work. What was *reached* is ``actual_invested``: an order that could
        not be sent, a purchase cut down for want of cash and a lot rounded
        down all sit between the two, and a record that carried one number
        would be read as the other.
    actual_invested : float
        Fraction of equity actually held in positions at this close, after
        whatever execution managed to do at this session's open.
    considered : int
        Instruments that had a usable signal to choose among.
    traded_value : float
        Value exchanged at this session's open, both directions counted.
    commission : float
        Paid to the broker at this session's open.
    market_cost : float
        Paid to the market at this session's open: spread and slippage.
    untradable : tuple[str, ...]
        Instruments whose opening price was not knowable, so the order was not
        sent and the position stayed as it was.
    unfunded : tuple[str, ...]
        Instruments whose purchase was cut down, or dropped, for want of the
        cash to pay for it. A target of a whole book costs a little more than
        the book is worth, and what execution charges comes out of the
        position rather than out of a loan the model never granted.
    priced_from_earlier : tuple[str, ...]
        Held instruments valued at an older close, because none was published
        for this session. The equity is an estimate for those, and says so.
    weights : Mapping[str, float]
        Target decided at this session's close, for the next open.
    quantities : Mapping[str, float]
        Units actually held after this session's open, per instrument. With
        the fills and the closing prices, this is what lets a run answer why
        the equity moved on a given day rather than only by how much.
    fills : tuple[Fill, ...]
        The orders done at this session's open, with their reference price,
        their fill price and their commission.
    closes : Mapping[str, float]
        The price each held instrument was valued at, at this session's close.
        The one named in ``priced_from_earlier`` is an older close carried
        forward, and the record says which. With the quantities and the fills,
        this is what lets a run be taken apart per instrument afterwards -
        without it, an attribution would have to re-read the market data, and
        analytics that re-reads the market data is analytics that can quietly
        use a price the run never saw.

    Notes
    -----
    Both mappings are frozen at construction, so a record cannot be edited
    into a different run after the fact.
    """

    session_date: date
    decision_at: datetime
    equity: float
    gross_equity: float
    cash: float
    target_invested: float
    actual_invested: float
    considered: int
    traded_value: float
    commission: float
    market_cost: float
    untradable: tuple[str, ...]
    unfunded: tuple[str, ...]
    priced_from_earlier: tuple[str, ...]
    weights: Mapping[str, float]
    quantities: Mapping[str, float] = MappingProxyType({})
    fills: tuple[Fill, ...] = ()
    closes: Mapping[str, float] = MappingProxyType({})

    def __post_init__(self) -> None:
        """Freeze what was recorded, so a result stays what the run produced."""
        object.__setattr__(self, "weights", MappingProxyType(dict(self.weights)))
        object.__setattr__(self, "quantities", MappingProxyType(dict(self.quantities)))
        object.__setattr__(self, "closes", MappingProxyType(dict(self.closes)))
        object.__setattr__(self, "untradable", tuple(self.untradable))
        object.__setattr__(self, "unfunded", tuple(self.unfunded))
        object.__setattr__(self, "priced_from_earlier", tuple(self.priced_from_earlier))
        object.__setattr__(self, "fills", tuple(self.fills))

    @property
    def cost(self) -> float:
        """Return everything this session's rebalancing cost."""
        return self.commission + self.market_cost


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """Every session of a run, and what it cost to get there.

    Attributes
    ----------
    records : tuple[BacktestRecord, ...]
        One per session of the reference calendar inside the range.
    initial_cash : float
        What the run started with.
    """

    records: tuple[BacktestRecord, ...]
    initial_cash: float

    def frame(self) -> pd.DataFrame:
        """Return the run as a frame, indexed by session date.

        Returns
        -------
        pd.DataFrame
            One row per session, gross and net side by side, with the costs and
            the diagnostics that explain them.
        """
        rows = [
            {
                "decision_at": record.decision_at,
                "equity": record.equity,
                "gross_equity": record.gross_equity,
                "cash": record.cash,
                "target_invested": record.target_invested,
                "actual_invested": record.actual_invested,
                "considered": record.considered,
                "traded_value": record.traded_value,
                "commission": record.commission,
                "market_cost": record.market_cost,
                "cost": record.cost,
                "untradable": ",".join(record.untradable),
                "unfunded": ",".join(record.unfunded),
                "priced_from_earlier": ",".join(record.priced_from_earlier),
            }
            for record in self.records
        ]
        index = pd.Index(
            [record.session_date for record in self.records],
            dtype="object",
            name="session_date",
        )
        return pd.DataFrame(rows, index=index)

    @property
    def total_cost(self) -> float:
        """Return everything execution took over the whole run."""
        return sum(record.cost for record in self.records)

    @property
    def net_return(self) -> float:
        """Return the run's return after costs, as a fraction."""
        return self._return(self.records[-1].equity) if self.records else 0.0

    @property
    def gross_return(self) -> float:
        """Return what the same trades would have returned having paid nothing."""
        return self._return(self.records[-1].gross_equity) if self.records else 0.0

    def _return(self, final: float) -> float:
        """Return the growth from the starting cash to ``final``."""
        return final / self.initial_cash - 1.0


@dataclass(frozen=True, slots=True)
class BacktestEngine:
    """Walks the reference calendar, deciding at each close and filling at each open.

    Attributes
    ----------
    reader : MarketDataReader
        The store, read point in time. The engine is the only holder of it.
    calendars : CalendarRegistry
        Venue calendars, for the signals and for the reference timeline.
    reference_calendar_id : str
        The calendar time is advanced on. A European strategy decides on Paris
        sessions even when it holds a US index, and the staleness of that
        index's close is counted on the same calendar.
    signals : Sequence[Signal | SignalRequest]
        Computed at every decision, in order. A bare signal is computed over
        that session's universe; a
        :class:`~quant_backtester.signals.engine.SignalRequest` may carry a
        universe of its own, which is how a gauge that is never traded - a
        volatility index, a yield - reaches the same snapshot as the funds it
        gates. That universe may itself be dated: the engine resolves it for
        the session being decided, like the trading one, so a basket of gauges
        that changed over the years is not read as the list of those that
        survived.
    strategy : Strategy
        Given the snapshot, and nothing else.
    universe : Universe | StaticUniverse | Sequence[str]
        What the signals are computed for, asked session by session. A
        :class:`~quant_backtester.data.universes.Universe` carries dated
        memberships, so a run over a changing index chooses among the names
        that were in it on the day - which is the only way a backtest avoids
        being a study of the survivors. A plain sequence is accepted and
        wrapped in a
        :class:`~quant_backtester.data.universes.StaticUniverse`: honest for
        two funds that both existed throughout, and a lie for anything with
        entries and exits.
        The trading universe holds what the book may actually hold, and
        nothing else. An index, a yield or a volatility gauge reaches the same
        decision through a
        :class:`~quant_backtester.signals.engine.SignalRequest` of its own,
        which is what keeps "a thing to read" and "a thing to buy" from being
        the same list.
    limits : PositionLimits
        Applied to whatever the strategy asks for.
    execution : ExecutionModel
        The fill price assumption and the three costs.
    timetable : Timetable
        When a decision is taken and when it is filled.
    initial_cash : float
        What the run starts with, in ``base_currency``.
    base_currency : str
        The currency the book is kept in. Every tradable member of the
        universe must be quoted in it, because nothing here converts one
        currency into another: adding a fund quoted in euros to one quoted in
        dollars would value the book as though the two were worth the same,
        and the error would sit inside the equity curve rather than beside it.
        An instrument a signal only reads - an index, a yield, an FX
        fixing - may be quoted in anything, since it is never held.

    Raises
    ------
    ValueError
        If ``initial_cash`` is not a finite positive number, if
        ``base_currency`` is not a name, or if the universe holds an
        instrument the book may not actually hold: one the registry does not
        know, one declared ``tradable = false``, or one quoted in another
        currency. Checked session by session, since a dated universe answers a
        different list on each of them.

    Notes
    -----
    Every one of these is a declared parameter with no hidden default that
    matters: a result follows from committed code plus this configuration.
    """

    reader: MarketDataReader
    calendars: CalendarRegistry
    reference_calendar_id: str
    signals: Sequence[Signal | SignalRequest]
    strategy: Strategy
    universe: UniverseSource | Sequence[str]
    initial_cash: float
    base_currency: str
    limits: PositionLimits = field(default_factory=PositionLimits)
    execution: ExecutionModel = field(default_factory=ExecutionModel)
    timetable: Timetable = field(default_factory=Timetable)

    def __post_init__(self) -> None:
        """Reject a configuration that cannot describe a run, and date the universe.

        A plain sequence of names becomes a
        :class:`~quant_backtester.data.universes.StaticUniverse` here, so that
        everything below asks one question - what was in the universe on this
        session - and never has to know which kind it was handed.
        """
        require_finite_positive(self.initial_cash, "initial_cash")
        require_identifier(self.base_currency, "base_currency")
        if not isinstance(self.universe, UniverseSource):
            object.__setattr__(self, "universe", StaticUniverse(tuple(self.universe)))
        object.__setattr__(self, "signals", tuple(self.signals))

    @property
    def dated_universe(self) -> UniverseSource:
        """Return the universe in the form the engine asks it: by session.

        Returns
        -------
        UniverseSource
            What ``__post_init__`` normalised, whether a plain sequence of
            names or a universe of dated memberships was given.
        """
        universe = self.universe
        if not isinstance(universe, UniverseSource):
            raise TypeError(f"the universe was not dated: {universe!r}")
        return universe

    @property
    def instruments(self) -> InstrumentRegistry:
        """Return the registry the reader resolves against."""
        return self.reader.instruments

    def run(self, start: date, end: date) -> BacktestResult:
        """Walk the sessions in ``[start, end]`` and return what happened.

        Parameters
        ----------
        start, end : date
            Inclusive bounds on the reference calendar's sessions.

        Returns
        -------
        BacktestResult
            One record per session, gross and net side by side.

        Raises
        ------
        ValueError
            If ``start`` is after ``end``.
        CalendarCoverageError
            If the range reaches outside the reference calendar's coverage.
            Loud on purpose: inventing sessions past the end of a holiday list
            is how a backtest ends up trading on Christmas.

        Notes
        -----
        The target decided on the last session is never filled, since no
        session follows it inside the range. It is still recorded, because what
        a strategy wanted on its last day is part of what the run says.
        """
        if start > end:
            raise ValueError(f"start {start} is after end {end}")
        calendar = self.calendars.get(self.reference_calendar_id)
        sessions = calendar.sessions(start, end)
        engine = SignalEngine()
        holdings = Holdings(cash=self.initial_cash)
        gross_cash = self.initial_cash
        pending: TargetAllocation | None = None
        last_price: dict[str, float] = {}
        records: list[BacktestRecord] = []

        for session in sessions:
            execution, gross_cash = self._fill(session, pending, holdings, gross_cash, last_price)
            holdings = execution.holdings if execution is not None else holdings
            decision_at = self.timetable.decision_instant(session.session_date)
            market = self.reader.at(decision_at)
            prices, estimated = self._valuation(market, holdings, last_price)
            last_price.update(prices)
            members = self._trading_universe(session.session_date)
            pending = self._decide(engine, market, members, session.session_date)
            records.append(
                self._record(
                    session=session,
                    decision_at=decision_at,
                    holdings=holdings,
                    prices=prices,
                    gross_cash=gross_cash,
                    execution=execution,
                    estimated=estimated,
                    allocation=pending,
                    fills=execution.fills if execution is not None else (),
                )
            )
        return BacktestResult(records=tuple(records), initial_cash=self.initial_cash)

    def _trading_universe(self, session_date: date) -> Sequence[str]:
        """Return the instruments the book may hold on that session.

        Parameters
        ----------
        session_date : date
            The session being decided on.

        Returns
        -------
        Sequence[str]
            What the universe held that day, once every member has been
            checked against the registry.

        Raises
        ------
        ValueError
            If a member is unknown to the registry, is not tradable, or is
            quoted in another currency than the book.

        Notes
        -----
        Loud, and at the top of the session rather than at the fill. A
        non-tradable instrument reaching the execution layer is caught there
        too, but by then the strategy has already ranked it, chosen it and
        sized a position in it, and the run would report a rotation whose
        orders are quietly never sent. The configuration is wrong, and the
        place to say so is where it is read.
        """
        members = self.dated_universe.members_at(session_date)
        for instrument_id in members:
            instrument = self.instruments.get(instrument_id)
            if not instrument.tradable:
                raise ValueError(
                    f"{instrument_id} is declared tradable = false and cannot be in the "
                    f"trading universe on {session_date}; a signal reads it through a "
                    "SignalRequest of its own"
                )
            if instrument.currency != self.base_currency:
                raise ValueError(
                    f"{instrument_id} is quoted in {instrument.currency} and the book is "
                    f"kept in {self.base_currency}; nothing here converts a currency"
                )
        return members

    def _quantity_steps(self, instrument_ids: Sequence[str]) -> dict[str, float]:
        """Return the smallest dealable quantity of each instrument that declares one."""
        steps: dict[str, float] = {}
        for instrument_id in instrument_ids:
            instrument = self.instruments.get(instrument_id)
            if instrument.quantity_step is not None:
                steps[instrument_id] = instrument.quantity_step
        return steps

    def _fill(
        self,
        session: Session,
        pending: TargetAllocation | None,
        holdings: Holdings,
        gross_cash: float,
        last_price: Mapping[str, float],
    ) -> tuple[Execution | None, float]:
        """Fill the previous session's target at this session's opening auction.

        Parameters
        ----------
        session : Session
            The session whose open the order is filled at.
        pending : TargetAllocation | None
            What was decided at the previous close; ``None`` on the first
            session of a run, which has no decision behind it.
        holdings : Holdings
            What is held before the fill.
        gross_cash : float
            The cash of the book that pays no costs.
        last_price : Mapping[str, float]
            The last price each instrument was valued at, used when an opening
            auction did not print.

        Returns
        -------
        tuple[Execution | None, float]
            What was traded, and the gross book's cash after the same trades.
        """
        if pending is None:
            return None, gross_cash
        market = self.reader.at(self.timetable.execution_instant(session.session_date))
        wanted = sorted(set(pending.weights) | set(holdings.quantities))
        prices, tradable = self._opens(market, wanted, holdings, last_price)
        execution = self.execution.rebalance(
            holdings,
            pending.weights,
            prices,
            tradable,
            quantity_steps=self._quantity_steps(wanted),
        )
        for fill in execution.fills:
            # The same quantity, at the price on the screen and with no fee.
            signed = -1.0 if fill.side.value == "BUY" else 1.0
            gross_cash += signed * fill.quantity * fill.reference_price
        return execution, gross_cash

    def _opens(
        self,
        market: PointInTimeReader,
        instrument_ids: Sequence[str],
        holdings: Holdings,
        last_price: Mapping[str, float],
    ) -> tuple[dict[str, float], set[str]]:
        """Return a price for everything, and the subset that may be dealt at.

        Parameters
        ----------
        market : PointInTimeReader
            The reader of the execution instant.
        instrument_ids : Sequence[str]
            Everything held or wanted.
        holdings : Holdings
            What is held, so that every position can be valued.
        last_price : Mapping[str, float]
            The last price each instrument was valued at, used when an opening
            auction did not print.

        Returns
        -------
        tuple[dict[str, float], set[str]]
            Prices for valuing, and the instruments actually tradable.

        Notes
        -----
        Only a status of ``OK`` on an instrument declared ``tradable`` may be
        dealt at. A stale open is an open from an earlier session, and filling
        an order at it would put a trade in the record at a price nobody could
        have got that morning. An index has an opening print and no way to buy
        it, which is a different refusal and the one the registry declares.
        Both are checked here even though the universe is checked first: this
        is the last point before a trade exists, and a guard that only holds
        when the configuration is right is not a guard.

        A held position whose auction did not print is still worth something,
        and the last knowable value is what the book is marked at meanwhile -
        being untradable and being worthless are not the same thing.
        """
        if not instrument_ids:
            return {}, set()
        frame = market.values(list(instrument_ids), BarField.OPEN)
        prices: dict[str, float] = {}
        tradable: set[str] = set()
        for name, value, status in zip(frame.index, frame["value"], frame["status"], strict=True):
            instrument_id = str(name)
            price = float(value)
            if price == price:  # not NaN
                prices[instrument_id] = price
            if status is ObservationStatus.OK and self.instruments.get(instrument_id).tradable:
                tradable.add(instrument_id)
        for instrument_id in sorted(set(holdings.quantities) - set(prices)):
            carried = last_price.get(instrument_id)
            if carried is None:
                raise ValueError(
                    f"{instrument_id} is held and has never had a knowable price; "
                    f"the book cannot be valued at {market.as_of}"
                )
            prices[instrument_id] = carried
        return prices, tradable

    def _valuation(
        self,
        market: PointInTimeReader,
        holdings: Holdings,
        last_price: Mapping[str, float],
    ) -> tuple[dict[str, float], tuple[str, ...]]:
        """Return a price for every held instrument, and which ones are estimates.

        Notes
        -----
        A held position whose close was not published for this session is
        valued at the last one that was, and named. Marking it at nothing would
        show a loss that did not happen and give it back the next day; refusing
        to value the book at all would stop a run because one vendor missed a
        print. Saying which positions are estimated is what keeps the equity
        curve honest.

        A ``STALE`` close is one of those, and the status is what says so: the
        reader hands back a real number - the last close it had - and a run
        that only looked at the number would report an estimate as a print.
        The equity is the same either way; what changes is whether the report
        admits how it was reached.
        """
        held = sorted(holdings.quantities)
        if not held:
            return {}, ()
        frame = market.values(held, BarField.CLOSE)
        prices: dict[str, float] = {}
        estimated: list[str] = []
        for name, published, status in zip(
            frame.index, frame["value"], frame["status"], strict=True
        ):
            instrument_id = str(name)
            if status is ObservationStatus.NOT_LISTED:
                raise ValueError(
                    f"{instrument_id} is held and the registry says it was not listed at "
                    f"{market.as_of}; a position in a delisted instrument has to be closed, "
                    "and this model does not know at what price"
                )
            value = float(published)
            if status is ObservationStatus.OK:
                prices[instrument_id] = value
                continue
            # STALE is a close from an earlier session: a real number, and
            # still an estimate of what this session's close would have been.
            if value == value:  # not NaN
                prices[instrument_id] = value
                estimated.append(instrument_id)
                continue
            carried = last_price.get(instrument_id)
            if carried is None:
                raise ValueError(
                    f"{instrument_id} is held and has never had a knowable price; "
                    f"the run cannot value the book at {market.as_of}"
                )
            prices[instrument_id] = carried
            estimated.append(instrument_id)
        return prices, tuple(estimated)

    def _decide(
        self,
        engine: SignalEngine,
        market: PointInTimeReader,
        members: Sequence[str],
        session_date: date,
    ) -> TargetAllocation:
        """Compute the signals over that session's universes and decide what to hold.

        Notes
        -----
        Every universe is asked about this session, the trading one and each
        signal's own. A request carrying a dated universe is resolved here
        because here is the only place that knows which session is being
        decided: a signal that chose its own date could choose one the decision
        cannot see.
        """
        context = SignalContext(
            market=market, instruments=self.instruments, calendars=self.calendars
        )
        requests = [
            item.resolved(session_date) if isinstance(item, SignalRequest) else item
            for item in self.signals
        ]
        snapshot = engine.compute(context, requests, list(members))
        return self.limits.apply(self.strategy.decide(snapshot))

    def _record(
        self,
        *,
        session: Session,
        decision_at: datetime,
        holdings: Holdings,
        prices: Mapping[str, float],
        gross_cash: float,
        execution: Execution | None,
        estimated: tuple[str, ...],
        allocation: TargetAllocation,
        fills: tuple[Fill, ...],
    ) -> BacktestRecord:
        """Assemble one session's record."""
        positions = sum(size * prices[name] for name, size in holdings.quantities.items())
        equity = holdings.cash + positions
        return BacktestRecord(
            session_date=session.session_date,
            decision_at=decision_at,
            equity=equity,
            gross_equity=gross_cash + positions,
            cash=holdings.cash,
            target_invested=allocation.invested,
            # A book worth nothing is a book with nothing in it, and no
            # fraction of it is invested.
            actual_invested=positions / equity if equity != 0.0 else 0.0,
            considered=allocation.considered,
            traded_value=execution.traded_value if execution else 0.0,
            commission=execution.commission if execution else 0.0,
            market_cost=execution.market_cost if execution else 0.0,
            untradable=execution.untradable if execution else (),
            unfunded=execution.unfunded if execution else (),
            priced_from_earlier=estimated,
            weights=dict(allocation.weights),
            quantities=dict(holdings.quantities),
            fills=fills,
            closes=dict(prices),
        )
