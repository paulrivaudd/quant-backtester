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
from typing import Protocol
from zoneinfo import ZoneInfo

import pandas as pd

from quant_backtester.data.calendars import CalendarRegistry, Session
from quant_backtester.data.instruments import InstrumentRegistry
from quant_backtester.data.reader import MarketDataReader, ObservationStatus, PointInTimeReader
from quant_backtester.data.schemas import BarField
from quant_backtester.execution.fills import Execution, ExecutionModel
from quant_backtester.portfolio.limits import PositionLimits
from quant_backtester.portfolio.targets import Holdings, TargetAllocation
from quant_backtester.signals.base import Signal
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.engine import SignalEngine
from quant_backtester.signals.snapshot import SignalSnapshot


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
    invested : float
        Fraction of equity the target put to work.
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
    """

    session_date: date
    decision_at: datetime
    equity: float
    gross_equity: float
    cash: float
    invested: float
    considered: int
    traded_value: float
    commission: float
    market_cost: float
    untradable: tuple[str, ...]
    unfunded: tuple[str, ...]
    priced_from_earlier: tuple[str, ...]
    weights: Mapping[str, float]

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
                "invested": record.invested,
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
    signals : Sequence[Signal]
        Computed at every decision, in order.
    strategy : Strategy
        Given the snapshot, and nothing else.
    universe : Sequence[str]
        Instruments the signals are computed for. Fixed for the whole run: a
        universe that changes with time needs a point-in-time universe, which
        is a layer that does not exist yet, and pretending otherwise would put
        survivorship back into a backtest.
    limits : PositionLimits
        Applied to whatever the strategy asks for.
    execution : ExecutionModel
        The fill price assumption and the three costs.
    timetable : Timetable
        When a decision is taken and when it is filled.
    initial_cash : float
        What the run starts with, in the currency the instruments are quoted
        in. Nothing here converts a currency.

    Raises
    ------
    ValueError
        If ``initial_cash`` is not positive, or the universe repeats an
        instrument.

    Notes
    -----
    Every one of these is a declared parameter with no hidden default that
    matters: a result follows from committed code plus this configuration.
    """

    reader: MarketDataReader
    calendars: CalendarRegistry
    reference_calendar_id: str
    signals: Sequence[Signal]
    strategy: Strategy
    universe: Sequence[str]
    initial_cash: float
    limits: PositionLimits = field(default_factory=PositionLimits)
    execution: ExecutionModel = field(default_factory=ExecutionModel)
    timetable: Timetable = field(default_factory=Timetable)

    def __post_init__(self) -> None:
        """Reject a configuration that cannot describe a run."""
        if self.initial_cash <= 0:
            raise ValueError(f"initial_cash must be positive, got {self.initial_cash}")
        repeated = sorted({name for name in self.universe if list(self.universe).count(name) > 1})
        if repeated:
            raise ValueError(f"Universe holds {', '.join(repeated)} more than once")

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
            pending = self._decide(engine, market)
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
                )
            )
        return BacktestResult(records=tuple(records), initial_cash=self.initial_cash)

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
        execution = self.execution.rebalance(holdings, pending.weights, prices, tradable)
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
        Only a status of ``OK`` may be dealt at. A stale open is an open from
        an earlier session, and filling an order at it would put a trade in the
        record at a price nobody could have got that morning. But a held
        position whose auction did not print is still worth something, and the
        last knowable value is what the book is marked at meanwhile - being
        untradable and being worthless are not the same thing.
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
            if status is ObservationStatus.OK:
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
        """
        held = sorted(holdings.quantities)
        if not held:
            return {}, ()
        frame = market.values(held, BarField.CLOSE)
        prices: dict[str, float] = {}
        estimated: list[str] = []
        for name, published in zip(frame.index, frame["value"], strict=True):
            instrument_id = str(name)
            value = float(published)
            if value == value:  # not NaN
                prices[instrument_id] = value
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

    def _decide(self, engine: SignalEngine, market: PointInTimeReader) -> TargetAllocation:
        """Compute the signals and ask the strategy what to hold next."""
        context = SignalContext(
            market=market, instruments=self.instruments, calendars=self.calendars
        )
        snapshot = engine.compute(context, list(self.signals), list(self.universe))
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
    ) -> BacktestRecord:
        """Assemble one session's record."""
        positions = sum(size * prices[name] for name, size in holdings.quantities.items())
        return BacktestRecord(
            session_date=session.session_date,
            decision_at=decision_at,
            equity=holdings.cash + positions,
            gross_equity=gross_cash + positions,
            cash=holdings.cash,
            invested=allocation.invested,
            considered=allocation.considered,
            traded_value=execution.traded_value if execution else 0.0,
            commission=execution.commission if execution else 0.0,
            market_cost=execution.market_cost if execution else 0.0,
            untradable=execution.untradable if execution else (),
            unfunded=execution.unfunded if execution else (),
            priced_from_earlier=estimated,
            weights=dict(allocation.weights),
        )
