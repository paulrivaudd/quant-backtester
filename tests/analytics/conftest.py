"""A finished run, written by hand.

Analytics is a function of a curve, so its tests are about curves and not about
the engine: every number below is small enough to check on paper, and no test
here has to run a backtest to find out what a drawdown is. The one test that
does run the engine lives in ``test_report.py``, and its job is to check that
the two layers meet, not to check arithmetic.

A hand-written run is still a run the engine could have produced: its records
are the same objects, validated the same way. So the costs of a session are
carried by a fill that cost exactly that, a caveat by a reject or an estimate
on a position that exists, and the equity by cash and positions that add up to
it - a record cannot say it is worth one hundred while holding ninety.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta

import pytest

from quant_backtester.backtest.config import BacktestConfig
from quant_backtester.backtest.records import BacktestRecord
from quant_backtester.backtest.result import BacktestResult
from quant_backtester.backtest.schedule import EverySession
from quant_backtester.backtest.timetable import BacktestTimetable
from quant_backtester.execution.fills import ExecutionReject, ExecutionRejectReason, Fill
from quant_backtester.execution.orders import Order, Side
from quant_backtester.portfolio.allocation import ConstrainedTarget, PortfolioDecision
from quant_backtester.portfolio.holdings import Holding
from quant_backtester.portfolio.targets import TargetAllocation

START = date(2026, 1, 5)
"""First session of a hand-written run."""

HELD = "HELD"
"""The position a hand-written session holds when its cash is below its equity."""

RunBuilder = Callable[..., BacktestResult]
ResultBuilder = Callable[..., BacktestResult]


def sessions_from(start: date, count: int, step_days: int) -> list[date]:
    """Return ``count`` session dates, ``step_days`` apart."""
    return [start + timedelta(days=step_days * position) for position in range(count)]


def instant(session: date, hour: int = 0) -> datetime:
    """Return an aware instant on a session date."""
    return datetime.combine(session, datetime.min.time(), tzinfo=UTC) + timedelta(hours=hour)


def result_of(
    records: Sequence[BacktestRecord], initial_cash: float, start: date = START
) -> BacktestResult:
    """Wrap hand-written records in a result, with a configuration that covers them."""
    first = records[0].session_date if records else start
    last = records[-1].session_date if records else start
    return BacktestResult(
        records=tuple(records),
        config=BacktestConfig(
            start=first,
            end=last,
            initial_cash=initial_cash,
            base_currency="EUR",
            reference_calendar="XPAR",
            schedule=EverySession(),
            timetable=BacktestTimetable(),
        ),
        configuration={"note": "written by hand"},
        strategy_definition={"strategy_id": "hand_written"},
        strategy_fingerprint="hand_written",
    )


def decision_on(session: date, considered: int) -> PortfolioDecision:
    """Return a decision holding nothing, taken among ``considered`` instruments."""
    at = instant(session, 23)
    return PortfolioDecision(
        requested=TargetAllocation(as_of=at, weights={}, considered=considered),
        constrained=ConstrainedTarget(as_of=at, requested_weights={}, accepted_weights={}),
    )


def costing_fill(at: datetime, traded_value: float, commission: float, market_cost: float) -> Fill:
    """Return one purchase that exchanged and cost exactly what it is told to.

    One unit at a fill price equal to the traded value; the market price below
    it by the market cost, which is booked as spread. Unrealistic as a trade,
    exact as a record of what a session paid.
    """
    value = traded_value if traded_value > 0.0 else commission + market_cost + 1.0
    return Fill(
        instrument_id="TRADED",
        side=Side.BUY,
        quantity=1.0,
        market_price=value - market_cost,
        fill_price=value,
        commission=commission,
        spread_cost=market_cost,
        slippage_cost=0.0,
        executed_at=at,
    )


def make_run(
    equity: Sequence[float],
    *,
    gross: Sequence[float] | None = None,
    start: date = START,
    step_days: int = 1,
    initial_cash: float | None = None,
    commission: Sequence[float] | None = None,
    market_cost: Sequence[float] | None = None,
    traded_value: Sequence[float] | None = None,
    considered: int = 2,
    cash: Sequence[float] | None = None,
    untradable: Sequence[tuple[str, ...]] | None = None,
    unfunded: Sequence[tuple[str, ...]] | None = None,
    priced_from_earlier: Sequence[tuple[str, ...]] | None = None,
) -> BacktestResult:
    """Return a run whose records say exactly what the test needs them to say.

    Parameters
    ----------
    equity : Sequence[float]
        The net book, session by session.
    gross : Sequence[float] | None
        The book that paid nothing; the net one again when left out.
    start : date
        First session.
    step_days : int
        Calendar days between two sessions. One by default, so that a run of
        366 of them covers a year.
    initial_cash : float | None
        What the run started with; the first equity when left out.
    commission, market_cost, traded_value : Sequence[float] | None
        Per session, zero everywhere when left out. A session with any of them
        carries one fill that exchanged and cost exactly that.
    considered : int
        Instruments the strategy had to choose among, the same on every
        session.
    cash : Sequence[float] | None
        The uninvested part per session: all of the equity when left out,
        unless a position is valued on an older price, in which case none of it.
        What is not cash is held, in ``HELD`` or in the estimated instruments.
    untradable, unfunded : Sequence[tuple[str, ...]] | None
        Instruments refused for want of a price, or of cash, per session.
    priced_from_earlier : Sequence[tuple[str, ...]] | None
        Held instruments valued on an older price, per session.

    Returns
    -------
    BacktestResult
        A run holding one record per equity given.
    """
    dates = sessions_from(start, len(equity), step_days)
    nothing: list[tuple[str, ...]] = [() for _ in equity]
    zeros = [0.0] * len(equity)
    estimated = list(priced_from_earlier or nothing)
    records = []
    for position, (session, net) in enumerate(zip(dates, equity, strict=True)):
        names = estimated[position]
        free = (cash or [])[position] if cash is not None else (0.0 if names else net)
        held_value = net - free
        holdings: dict[str, Holding] = {}
        prices: dict[str, float] = {}
        if held_value > 0.0:
            carriers = names or (HELD,)
            for name in carriers:
                holdings[name] = Holding(name, 1.0)
                prices[name] = held_value / len(carriers)
        gross_net = (gross or equity)[position]
        fees = (commission or zeros)[position]
        market = (market_cost or zeros)[position]
        value = (traded_value or zeros)[position]
        rejects = tuple(
            ExecutionReject(name, reason)
            for reason, lists in (
                (ExecutionRejectReason.NO_EXECUTION_PRICE, untradable),
                (ExecutionRejectReason.INSUFFICIENT_CASH, unfunded),
            )
            for name in (lists or nothing)[position]
        )
        at = instant(session, 9)
        fills = (costing_fill(at, value, fees, market),) if (value or fees or market) else ()
        executed = fills or rejects
        records.append(
            BacktestRecord(
                session_date=session,
                valuation_time=instant(session, 23),
                cash=free,
                gross_cash=gross_net - held_value,
                holdings=holdings,
                valuation_prices=prices,
                target_invested=1.0,
                estimated_valuation_instruments=names,
                execution_time=at if executed else None,
                executed_decision=session - timedelta(days=1) if executed else None,
                orders=tuple(
                    Order(fill.instrument_id, fill.side, fill.quantity, at) for fill in fills
                ),
                fills=fills,
                rejects=rejects,
                decision_time=instant(session, 23),
                decision=decision_on(session, considered),
            )
        )
    first_cash = equity[0] if equity else 1.0
    return result_of(records, initial_cash if initial_cash is not None else first_cash, start)


@pytest.fixture
def run() -> RunBuilder:
    """Return the builder of a hand-written run."""
    return make_run


@pytest.fixture
def make_result() -> ResultBuilder:
    """Return the builder of a result around hand-written records."""
    return result_of
