"""The loop: the order of a session, the gap it models, and what it records.

The arithmetic below is small enough to check by hand, which is the point. What
the engine has to get right is not a formula but a sequence - fill at the open,
value at the close, decide after it - and the cheapest way to see that it does
is to make the prices so simple that any other sequence gives a different
number.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from quant_backtester.backtest.config import BacktestConfig
from quant_backtester.backtest.context import StrategyContext
from quant_backtester.backtest.engine import (
    BacktestEngine,
    StrategyMutated,
    UnsupportedCorporateAction,
)
from quant_backtester.backtest.result import BacktestResult
from quant_backtester.backtest.schedule import DecisionSchedule, EverySession
from quant_backtester.backtest.timetable import BacktestTimetable
from quant_backtester.data.calendars import CalendarRegistry, TradingCalendar
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.data.schemas import ActionType, BarField
from quant_backtester.data.universes import Membership, Universe, UniverseSource
from quant_backtester.execution.costs import CostModel
from quant_backtester.execution.fills import ExecutionRejectReason
from quant_backtester.execution.model import ExecutionModel
from quant_backtester.portfolio.allocation import PortfolioModel
from quant_backtester.portfolio.constraints import (
    CurrencyMismatchInTradingUniverse,
    NonTradableInstrument,
    NonTradableInstrumentInTradingUniverse,
    OutsideTradingUniverse,
)
from quant_backtester.portfolio.limits import PortfolioLimits
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.provenance import SourceState, SourceStatus
from quant_backtester.signals.base import Signal
from quant_backtester.signals.cross_sectional.rank import CrossSectionalRank
from quant_backtester.signals.engine import SignalRequest
from quant_backtester.signals.level.change import LevelChangeSignal
from quant_backtester.signals.price.returns import ReturnSignal
from quant_backtester.signals.snapshot import SignalSnapshot
from quant_backtester.signals.types import PriceBasis
from quant_backtester.strategies.base import Strategy
from quant_backtester.strategies.examples import BuyAndHold

PARIS = BacktestTimetable(
    decision_time=time(23, 0),
    execution_time=time(9, 1),
    valuation_time=time(23, 0),
    timezone="Europe/Paris",
)
FREE = ExecutionModel(costs=CostModel())
PARIS_ZONE = ZoneInfo("Europe/Paris")


@dataclass(frozen=True, slots=True)
class AlwaysHold(Strategy):
    """A strategy that always wants the same book, whatever the signals say.

    It exists so that a test about the loop is about the loop: with the target
    fixed, every number in the record comes from the prices and the sequence.
    """

    weights: Mapping[str, float]
    strategy_id: str = "always_hold"

    def decide(self, ctx: StrategyContext) -> TargetAllocation:
        """Return the fixed target, stamped at the decision instant."""
        return TargetAllocation(as_of=ctx.as_of, weights=dict(self.weights))


@dataclass(frozen=True, slots=True)
class Gated(Strategy):
    """Hold the best-ranked fund while a gauge stays below a threshold.

    Written here rather than taken from ``strategies`` because this test is
    about the engine wiring two universes into one decision, not about a
    particular strategy: the signals are given to the engine directly, which
    is the low-level API this file exercises.
    """

    rank_id: str
    gate_id: str
    maximum: float
    strategy_id: str = "gated"

    def decide(self, ctx: StrategyContext) -> TargetAllocation:
        """Stand aside above the threshold, or when the gauge cannot be read."""
        selected = ctx.top(self.rank_id, 1)
        gauge = ctx.signal_value_or_none(self.gate_id, "RATE_US")
        if gauge is None or gauge > self.maximum:
            return ctx.cash(among=selected)
        return ctx.equal_weight(selected, count=1)


@dataclass(frozen=True, slots=True)
class Watching(Strategy):
    """Hold nothing, and write down every context it was handed."""

    seen: list[StrategyContext] = field(default_factory=list, repr=False, compare=False)
    strategy_id: str = "watching"

    def decide(self, ctx: StrategyContext) -> TargetAllocation:
        """Record the context, and stand aside."""
        self.seen.append(ctx)
        return ctx.cash()


def a_return() -> Sequence[Signal]:
    """Return one cheap signal, so the engine has something to compute."""
    return [ReturnSignal(signal_id="return_2d", lookback_sessions=2, price_basis=PriceBasis.RAW)]


def engine_over(
    market: MarketDataReader,
    calendars: CalendarRegistry,
    strategy: Strategy,
    *,
    start: date = date(2026, 9, 9),
    end: date = date(2026, 9, 14),
    universe: UniverseSource | Sequence[str] = ("ETF_EU",),
    execution: ExecutionModel = FREE,
    limits: PortfolioLimits | None = None,
    initial_cash: float = 10_000.0,
    base_currency: str = "EUR",
    schedule: DecisionSchedule | None = None,
    timetable: BacktestTimetable = PARIS,
    signals: Sequence[Signal | SignalRequest] | None = None,
) -> BacktestEngine:
    """Wire an engine onto the synthetic market, over its last four sessions by default."""
    return BacktestEngine(
        reader=market,
        calendars=calendars,
        strategy=strategy,
        universe=universe,
        config=BacktestConfig(
            start=start,
            end=end,
            initial_cash=initial_cash,
            base_currency=base_currency,
            reference_calendar="XPAR",
            schedule=schedule or EverySession(),
            timetable=timetable,
        ),
        execution=execution,
        portfolio=PortfolioModel(limits or PortfolioLimits()),
        signals=a_return() if signals is None else signals,
    )


def run_over(
    market: MarketDataReader,
    calendars: CalendarRegistry,
    strategy: Strategy,
    **overrides: object,
) -> BacktestResult:
    """Run over the last four sessions of the synthetic market."""
    return engine_over(market, calendars, strategy, **overrides).run()  # type: ignore[arg-type]


def test_a_run_records_one_session_at_a_time(
    market: MarketDataReader, calendars: CalendarRegistry, sessions: tuple[date, ...]
) -> None:
    """One record per session of the reference calendar, in order."""
    result = run_over(market, calendars, AlwaysHold({"ETF_EU": 1.0}))

    assert [record.session_date for record in result.records] == list(sessions[-4:])


def test_the_first_session_holds_nothing_yet(
    market: MarketDataReader, calendars: CalendarRegistry
) -> None:
    """Nothing was decided before it, so there is nothing to fill at its open.

    A run that started invested would be a run that traded on a decision it
    never took.
    """
    result = run_over(market, calendars, AlwaysHold({"ETF_EU": 1.0}))
    first = result.records[0]

    assert first.net_equity == pytest.approx(10_000.0)
    assert first.cash == pytest.approx(10_000.0)
    assert first.execution_time is None
    assert first.orders == ()
    assert first.traded_value == 0.0


def test_a_decision_is_filled_at_the_next_open_and_not_before(
    market: MarketDataReader, calendars: CalendarRegistry
) -> None:
    """The gap the whole project is built around, in one assertion.

    The prices rise by one a session and the open equals the close, so the
    target decided after the close of the first session buys at 107, not at
    106. Filling at the price that produced the decision would show 10000/106
    units instead.
    """
    result = run_over(market, calendars, AlwaysHold({"ETF_EU": 1.0}))
    second = result.records[1]

    assert second.traded_value == pytest.approx(10_000.0)
    assert second.fills[0].market_price == 107.0
    assert second.cash == pytest.approx(0.0)
    # 10 000 at 107, then marked at that session's close of 107.
    assert second.net_equity == pytest.approx(10_000.0)


def test_the_book_follows_the_market_after_it_is_invested(
    market: MarketDataReader, calendars: CalendarRegistry
) -> None:
    """Bought at 107, marked at 109 two sessions later."""
    result = run_over(market, calendars, AlwaysHold({"ETF_EU": 1.0}))

    assert result.records[-1].net_equity == pytest.approx(10_000.0 * 109.0 / 107.0)
    assert result.net_return == pytest.approx(109.0 / 107.0 - 1.0)


def walked_by_hand(prices: Sequence[float], weight: float, cash: float) -> float:
    """Return the equity the same path gives, computed the slow obvious way.

    A book rebalanced to a fixed weight at every open is not a book bought once
    and held: it sells into strength and buys into weakness, and the two give
    different numbers. This loop is the naive form of what the engine does, and
    comparing them is what says the engine walks the path it claims to.
    """
    units = 0.0
    for price in prices:
        equity = cash + units * price
        target = equity * weight / price
        cash = equity - target * price
        units = target
    return cash + units * prices[-1]


def test_half_a_book_moves_half_as_much(
    market: MarketDataReader, calendars: CalendarRegistry
) -> None:
    """What is not allocated is not invested, and does not move."""
    result = run_over(market, calendars, AlwaysHold({"ETF_EU": 0.5}))
    final = result.records[-1]

    assert final.net_equity == pytest.approx(walked_by_hand([107.0, 108.0, 109.0], 0.5, 10_000.0))
    assert final.cash == pytest.approx(final.net_equity * 0.5)
    assert 0 < result.net_return < 109.0 / 107.0 - 1.0


def test_gross_and_net_are_reported_side_by_side(
    market: MarketDataReader, calendars: CalendarRegistry
) -> None:
    """The same trades, one book paying the costs and one not.

    Re-running the strategy without costs would let the two books hold
    different things and stop them being comparable at all.
    """
    costly = ExecutionModel(
        costs=CostModel(commission_rate=0.001, half_spread_rate=0.002, slippage_rate=0.001)
    )
    result = run_over(market, calendars, AlwaysHold({"ETF_EU": 1.0}), execution=costly)

    assert result.gross_return > result.net_return
    assert result.total_cost > 0.0
    final = result.records[-1]
    assert final.gross_equity > final.net_equity
    # The same positions in both books: only the cash differs.
    assert final.gross_cash > final.cash


def test_a_run_with_no_costs_has_gross_equal_to_net(
    market: MarketDataReader, calendars: CalendarRegistry
) -> None:
    """Which is what makes the difference above attributable to the cost model."""
    result = run_over(market, calendars, AlwaysHold({"ETF_EU": 1.0}))

    for record in result.records:
        assert record.gross_equity == pytest.approx(record.net_equity)
    assert result.total_cost == 0.0


def test_the_three_costs_are_recorded_apart(
    market: MarketDataReader, calendars: CalendarRegistry
) -> None:
    """A report has to be able to say which of them ate the return."""
    costly = ExecutionModel(
        costs=CostModel(commission_rate=0.001, half_spread_rate=0.002, slippage_rate=0.001)
    )
    result = run_over(market, calendars, AlwaysHold({"ETF_EU": 1.0}), execution=costly)
    traded = result.records[1]

    assert traded.commission_cost > 0.0
    assert traded.spread_cost == pytest.approx(2.0 * traded.slippage_cost)
    assert traded.total_cost == pytest.approx(
        traded.commission_cost + traded.spread_cost + traded.slippage_cost
    )


def test_the_limits_are_applied_to_whatever_the_strategy_asks(
    market: MarketDataReader, calendars: CalendarRegistry
) -> None:
    """A strategy asking for everything is held to what the portfolio allows."""
    result = run_over(
        market,
        calendars,
        AlwaysHold({"ETF_EU": 1.0}),
        limits=PortfolioLimits(max_weight_per_instrument=0.25),
    )

    first, final = result.records[0], result.records[-1]
    assert first.target_invested == pytest.approx(0.25)
    decision = first.decision
    assert decision is not None
    assert dict(decision.constrained.requested_weights) == {"ETF_EU": 1.0}
    assert dict(decision.accepted_weights) == {"ETF_EU": 0.25}
    assert final.net_equity == pytest.approx(walked_by_hand([107.0, 108.0, 109.0], 0.25, 10_000.0))
    assert final.cash == pytest.approx(final.net_equity * 0.75)


def test_the_last_decision_is_recorded_but_never_filled(
    market: MarketDataReader, calendars: CalendarRegistry
) -> None:
    """No session follows it inside the range, so nothing trades on it.

    It is still on the record: what a strategy wanted on its last day is part
    of what the run says, and dropping it would hide the state the book was
    about to move to.
    """
    result = run_over(market, calendars, AlwaysHold({"ETF_EU": 1.0}))

    last = result.records[-1].decision
    assert last is not None
    assert dict(last.accepted_weights) == {"ETF_EU": 1.0}


def test_an_instrument_that_cannot_be_dealt_is_named_and_left_alone(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., object],
    calendars: CalendarRegistry,
    prices: Callable[..., dict[date, float]],
    sessions: tuple[date, ...],
    xpar: TradingCalendar,
) -> None:
    """A morning with no opening auction is a morning with no trade.

    The position stays where it was, the record names the instrument and the
    reason, and the book is still valued - being untradable and being
    worthless are not the same thing.
    """
    market = make_market(
        {
            "ETF_EU": make_bars(
                "ETF_EU", xpar, prices(100.0, 1.0), contested={sessions[-2]: [BarField.OPEN]}
            )
        }
    )
    result = run_over(market, calendars, AlwaysHold({"ETF_EU": 1.0}))

    blocked = next(record for record in result.records if record.session_date == sessions[-2])
    (reject,) = blocked.rejects
    assert reject.reason is ExecutionRejectReason.NO_EXECUTION_PRICE
    assert blocked.traded_value == 0.0
    # The position bought at 107 the morning before is untouched, and still
    # worth what the market says it is worth at this session's close.
    assert blocked.net_equity == pytest.approx(10_000.0 * 108.0 / 107.0)


def test_one_missing_open_does_not_stop_the_others(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., object],
    calendars: CalendarRegistry,
    prices: Callable[..., dict[date, float]],
    sessions: tuple[date, ...],
    xpar: TradingCalendar,
) -> None:
    """Half into each of two funds, one of which has no opening print on the day.

    The one that printed is bought, the other is refused with its reason, and
    the record shows a target of the whole book against half of it reached -
    rather than pretending the target was met.
    """
    market = make_market(
        {
            "ETF_EU": make_bars("ETF_EU", xpar, prices(100.0, 1.0)),
            "ETF_OTHER": make_bars(
                "ETF_OTHER",
                xpar,
                prices(200.0, 2.0),
                contested={sessions[-3]: [BarField.OPEN]},
            ),
        }
    )
    result = run_over(
        market,
        calendars,
        AlwaysHold({"ETF_EU": 0.5, "ETF_OTHER": 0.5}),
        universe=("ETF_EU", "ETF_OTHER"),
    )

    day = result.records[1]
    assert [reject.instrument_id for reject in day.rejects] == ["ETF_OTHER"]
    assert day.rejects[0].reason is ExecutionRejectReason.NO_EXECUTION_PRICE
    assert [fill.instrument_id for fill in day.fills] == ["ETF_EU"]
    assert day.target_invested == pytest.approx(1.0)
    assert day.actual_invested == pytest.approx(0.5, abs=0.01)


def test_the_run_is_a_frame_anyone_can_read(
    market: MarketDataReader, calendars: CalendarRegistry, sessions: tuple[date, ...]
) -> None:
    """Gross and net beside each other, with the costs that separate them."""
    frame = run_over(market, calendars, AlwaysHold({"ETF_EU": 1.0})).frame()

    assert list(frame.index) == list(sessions[-4:])
    for column in ("net_equity", "gross_equity", "cash", "commission_cost", "total_cost"):
        assert column in frame.columns


def test_the_strategy_only_ever_sees_a_context(
    market: MarketDataReader, calendars: CalendarRegistry
) -> None:
    """The boundary, checked from the inside of a real run."""
    watching = Watching()

    run_over(market, calendars, watching)

    assert watching.seen
    assert all(isinstance(given, StrategyContext) for given in watching.seen)
    # The snapshot inside it, and nothing under it: no reader, no repository.
    assert all(isinstance(given.signals, SignalSnapshot) for given in watching.seen)
    assert not hasattr(watching.seen[0], "reader")


def test_the_signals_are_computed_at_the_decision_instant(
    market: MarketDataReader, calendars: CalendarRegistry
) -> None:
    """Every context answers for the evening of the session it belongs to."""
    watching = Watching()

    result = run_over(market, calendars, watching)

    assert [given.as_of for given in watching.seen] == [
        record.decision_time for record in result.records
    ]


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"initial_cash": 0.0}, "initial_cash"),
        ({"initial_cash": -1.0}, "initial_cash"),
        ({"initial_cash": float("nan")}, "initial_cash"),
        ({"initial_cash": float("inf")}, "initial_cash"),
        ({"initial_cash": True}, "initial_cash"),
        ({"base_currency": ""}, "base_currency"),
        ({"universe": ("ETF_EU", "ETF_EU")}, "more than once"),
        ({"start": date(2026, 9, 14), "end": date(2026, 9, 9)}, "after end"),
    ],
    ids=[
        "no-capital",
        "negative-capital",
        "capital-that-is-not-a-number",
        "infinite-capital",
        "capital-as-a-boolean",
        "no-currency",
        "repeated-instrument",
        "backwards",
    ],
)
def test_an_impossible_configuration_stops_the_run(
    market: MarketDataReader,
    calendars: CalendarRegistry,
    overrides: dict[str, object],
    match: str,
) -> None:
    """A result follows from committed code plus this configuration."""
    with pytest.raises(ValueError, match=match):
        engine_over(market, calendars, AlwaysHold({}), **overrides)  # type: ignore[arg-type]


def test_a_universe_named_by_id_is_the_runner_s_job(
    market: MarketDataReader, calendars: CalendarRegistry
) -> None:
    """Split into letters, an id would be a universe of one-letter instruments."""
    with pytest.raises(ValueError, match="is an id"):
        engine_over(market, calendars, AlwaysHold({}), universe="ROTATION_2")


def test_the_reader_must_count_ages_on_the_calendar_the_run_advances_on(
    market: MarketDataReader, calendars: CalendarRegistry
) -> None:
    """A close one session old on one calendar is fresh on the other."""
    with pytest.raises(ValueError, match="counts ages on XPAR"):
        BacktestEngine(
            reader=market,
            calendars=calendars,
            strategy=AlwaysHold({}),
            universe=("ETF_EU",),
            config=BacktestConfig(
                start=date(2026, 9, 9),
                end=date(2026, 9, 14),
                initial_cash=10_000.0,
                base_currency="EUR",
                reference_calendar="XNYS",
                schedule=EverySession(),
                timetable=PARIS,
            ),
            execution=FREE,
        )


def test_a_period_with_no_session_is_refused(
    market: MarketDataReader, calendars: CalendarRegistry
) -> None:
    """A Saturday to a Sunday has nothing to measure a performance over."""
    engine = engine_over(
        market, calendars, AlwaysHold({}), start=date(2026, 9, 12), end=date(2026, 9, 13)
    )

    with pytest.raises(ValueError, match="holds no session"):
        engine.run()


def test_a_run_never_spends_cash_it_does_not_have(
    market: MarketDataReader, calendars: CalendarRegistry
) -> None:
    """A fully invested strategy pays its costs out of the position.

    The target is a whole book and the costs have to come from somewhere. A
    book that let its cash go negative would be borrowing at no rate, every
    session, for the length of the run - a loan the model never granted and a
    return nobody could have earned.
    """
    costly = ExecutionModel(
        costs=CostModel(commission_rate=0.001, half_spread_rate=0.002, slippage_rate=0.001)
    )

    result = run_over(market, calendars, AlwaysHold({"ETF_EU": 1.0}), execution=costly)

    for record in result.records:
        assert record.cash >= 0.0, f"{record.session_date} ended on borrowed cash"


def test_a_purchase_the_cash_could_not_carry_is_named(
    market: MarketDataReader, calendars: CalendarRegistry
) -> None:
    """Trimmed, and said out loud: the record carries what execution cut."""
    costly = ExecutionModel(costs=CostModel(commission_rate=0.001, half_spread_rate=0.002))

    result = run_over(market, calendars, AlwaysHold({"ETF_EU": 1.0}), execution=costly)

    assert [reject.reason for reject in result.records[1].rejects] == [
        ExecutionRejectReason.INSUFFICIENT_CASH
    ]
    assert result.records[0].rejects == ()


def test_a_strategy_that_fails_stops_the_run(
    market: MarketDataReader, calendars: CalendarRegistry
) -> None:
    """Never converted into a flat day: a bug in a decision is not a decision to hold cash."""

    @dataclass(frozen=True, slots=True)
    class Broken(Strategy):
        strategy_id: str = "broken"

        def decide(self, ctx: StrategyContext) -> TargetAllocation:
            raise ZeroDivisionError("the strategy divided by nothing")

    with pytest.raises(ZeroDivisionError, match="divided by nothing"):
        run_over(market, calendars, Broken())


def test_a_strategy_that_does_not_answer_with_an_allocation_is_refused(
    market: MarketDataReader, calendars: CalendarRegistry
) -> None:
    """A bare mapping carries no instant and no diagnostics."""

    @dataclass(frozen=True, slots=True)
    class Sloppy(Strategy):
        strategy_id: str = "sloppy"

        def decide(self, ctx: StrategyContext) -> TargetAllocation:
            return {"ETF_EU": 1.0}  # type: ignore[return-value]

    with pytest.raises(TypeError, match="a decision is a TargetAllocation"):
        run_over(market, calendars, Sloppy())


def test_an_allocation_for_another_instant_is_refused(
    market: MarketDataReader, calendars: CalendarRegistry
) -> None:
    """A decision stamped yesterday is not today's decision."""

    @dataclass(frozen=True, slots=True)
    class Late(Strategy):
        strategy_id: str = "late"

        def decide(self, ctx: StrategyContext) -> TargetAllocation:
            yesterday = datetime(2026, 9, 1, 21, 0, tzinfo=ctx.as_of.tzinfo)
            return TargetAllocation(as_of=yesterday, weights={})

    with pytest.raises(ValueError, match="answered for"):
        run_over(market, calendars, Late())


def test_a_strategy_that_changes_while_deciding_is_refused(
    market: MarketDataReader, calendars: CalendarRegistry
) -> None:
    """A definition that describes its last decision rather than all of them records nothing."""

    @dataclass(slots=True)
    class Counting(Strategy):
        decisions: int = 0
        strategy_id: str = "counting"

        def decide(self, ctx: StrategyContext) -> TargetAllocation:
            self.decisions += 1
            return ctx.cash()

    with pytest.raises(StrategyMutated, match="not the one it was"):
        run_over(market, calendars, Counting())


def test_the_run_records_what_it_was_run_with(
    market: MarketDataReader, calendars: CalendarRegistry
) -> None:
    """The strategy, its fingerprint, the configuration and the state of the code."""
    strategy = AlwaysHold({"ETF_EU": 1.0})
    engine = engine_over(market, calendars, strategy)
    commit = "0123456789abcdef0123456789abcdef01234567"
    engine = BacktestEngine(
        reader=engine.reader,
        calendars=engine.calendars,
        strategy=strategy,
        universe=engine.universe,
        config=engine.config,
        execution=engine.execution,
        portfolio=engine.portfolio,
        signals=engine.signals,
        source=SourceState(SourceStatus.CLEAN, commit),
    )

    result = engine.run()

    assert result.strategy_fingerprint == strategy.fingerprint()
    assert result.strategy_definition["strategy_id"] == "always_hold"
    assert result.code_version == commit
    configuration = result.configuration
    assert configuration["start"] == "2026-09-09"
    assert configuration["base_currency"] == "EUR"
    # Frozen all the way down: the recorded list is a tuple, and cannot be edited.
    assert configuration["universe"] == {"type": "StaticUniverse", "members": ("ETF_EU",)}
    assert configuration["quantity_steps"] == {"ETF_EU": None}
    assert configuration["portfolio"] == PortfolioModel().definition()
    assert configuration["execution"] == FREE.definition()
    assert configuration["timetable"] == PARIS.definition()


# --- the universe is asked session by session --------------------------------


@dataclass(frozen=True, slots=True)
class HoldWhatIsOffered(Strategy):
    """Equal weights over whatever the snapshot holds.

    It exists so that a test about the universe is about the universe: the
    strategy has no opinion of its own, so what it targets is exactly what it
    was allowed to choose from.
    """

    signal_id: str
    strategy_id: str = "hold_what_is_offered"

    def decide(self, ctx: StrategyContext) -> TargetAllocation:
        """Spread the book over every instrument in the snapshot."""
        names = tuple(ctx.signals.result(self.signal_id).instruments())
        weight = 1.0 / len(names) if names else 0.0
        return TargetAllocation(
            as_of=ctx.as_of,
            weights={name: weight for name in names},
            selected=names,
            considered=len(names),
        )


def leaver_market(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    xpar: TradingCalendar,
    prices: Callable[..., dict[date, float]],
) -> MarketDataReader:
    """Return two Paris funds, both rising, both priced every session."""
    return make_market(
        {
            "ETF_EU": make_bars("ETF_EU", xpar, prices(100.0, 1.0)),
            "ETF_OTHER": make_bars("ETF_OTHER", xpar, prices(200.0, 2.0)),
        }
    )


def test_a_member_that_left_is_not_chosen_after_it_did(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    xpar: TradingCalendar,
    calendars: CalendarRegistry,
    prices: Callable[..., dict[date, float]],
) -> None:
    """The universe is asked on every session, and it answers for that session.

    ETF_OTHER leaves after 10 September. The decision taken at that close still
    holds it; the one taken the next session cannot, and the sale happens at
    the open after that - the same gap every other order goes through.
    """
    universe = Universe(
        universe_id="LEAVER",
        name="One fund leaves",
        memberships=(
            Membership("ETF_EU"),
            Membership("ETF_OTHER", until_date=date(2026, 9, 10)),
        ),
    )
    market = leaver_market(make_market, make_bars, xpar, prices)

    result = run_over(market, calendars, HoldWhatIsOffered("return_2d"), universe=universe)

    tenth, eleventh = result.records[1], result.records[2]
    assert tenth.decision is not None
    assert eleventh.decision is not None
    assert set(tenth.decision.accepted_weights) == {"ETF_EU", "ETF_OTHER"}
    assert set(eleventh.decision.accepted_weights) == {"ETF_EU"}
    assert eleventh.considered == 1
    sold = result.records[-1]
    first = sold.fills[0]
    assert (first.instrument_id, first.side.value) == ("ETF_OTHER", "SELL")
    assert "ETF_OTHER" not in sold.holdings


@dataclass(frozen=True, slots=True)
class BuyOn(Strategy):
    """Hold cash, then all of one fund from one decision session on - while it is offered."""

    day: date
    instrument_id: str
    strategy_id: str = "buy_on"

    def decide(self, ctx: StrategyContext) -> TargetAllocation:
        """Ask for the fund on or after the day, and only while the universe holds it."""
        if ctx.as_of.date() < self.day or self.instrument_id not in ctx.universe:
            return ctx.cash()
        return ctx.weights({self.instrument_id: 1.0})


def test_a_purchase_of_a_fund_that_left_before_the_open_is_refused(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    xpar: TradingCalendar,
    calendars: CalendarRegistry,
    prices: Callable[..., dict[date, float]],
) -> None:
    """Decided on its last day in the universe, due at the open after: not bought.

    An index rebalancing effective on the eleventh removes the fund before
    that morning's auction, and no mandate buys what it has just been told to
    leave. The purchase is refused with its reason, and the book stays in cash.
    """
    universe = Universe(
        universe_id="LEAVER",
        name="One fund leaves",
        memberships=(
            Membership("ETF_EU"),
            Membership("ETF_OTHER", until_date=date(2026, 9, 10)),
        ),
    )
    market = leaver_market(make_market, make_bars, xpar, prices)

    result = run_over(market, calendars, BuyOn(date(2026, 9, 10), "ETF_OTHER"), universe=universe)

    eleventh = result.records[2]
    assert eleventh.executed_decision == date(2026, 9, 10)
    assert [(reject.instrument_id, reject.reason) for reject in eleventh.rejects] == [
        ("ETF_OTHER", ExecutionRejectReason.OUTSIDE_TRADING_UNIVERSE)
    ]
    assert eleventh.fills == ()
    assert eleventh.cash == pytest.approx(10_000.0)


def test_a_fund_that_has_not_joined_yet_cannot_be_held(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    xpar: TradingCalendar,
    calendars: CalendarRegistry,
    prices: Callable[..., dict[date, float]],
) -> None:
    """Joining on the eleventh means not held on the tenth, whatever the strategy asks."""
    universe = Universe(
        universe_id="JOINER",
        name="One fund joins",
        memberships=(
            Membership("ETF_EU"),
            Membership("ETF_OTHER", from_date=date(2026, 9, 11)),
        ),
    )
    market = leaver_market(make_market, make_bars, xpar, prices)

    with pytest.raises(OutsideTradingUniverse, match="ETF_OTHER"):
        run_over(market, calendars, AlwaysHold({"ETF_OTHER": 1.0}), universe=universe)

    offered = run_over(market, calendars, HoldWhatIsOffered("return_2d"), universe=universe)
    held_before = [
        record.session_date for record in offered.records if "ETF_OTHER" in record.holdings
    ]
    assert all(day > date(2026, 9, 11) for day in held_before)


def test_a_universe_given_as_a_list_is_still_asked_by_session(
    market: MarketDataReader, calendars: CalendarRegistry, sessions: tuple[date, ...]
) -> None:
    """A plain sequence becomes a static universe, and nothing below notices."""
    engine = engine_over(market, calendars, AlwaysHold({"ETF_EU": 1.0}))

    assert engine.dated_universe.members_at(sessions[0]) == ("ETF_EU",)
    assert engine.dated_universe.members_at(sessions[-1]) == ("ETF_EU",)


def test_a_gauge_that_is_never_traded_stands_the_book_down(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    make_levels: Callable[..., pd.DataFrame],
    xpar: TradingCalendar,
    calendars: CalendarRegistry,
    prices: Callable[..., dict[date, float]],
    sessions: tuple[date, ...],
) -> None:
    """The first cross-asset run: two funds rotated, a rate deciding whether to.

    The rate creeps up by five basis points a session until 11 September, when
    it jumps by fifty. The decision taken after that close shuts the gate, and
    the book is sold at the next open - the same gap every other order goes
    through, and the reason the sale lands on the fourteenth rather than on the
    evening the gauge moved.
    """
    rates = {day: 4.0 + 0.05 * index for index, day in enumerate(sessions)}
    rates[date(2026, 9, 11)] = rates[date(2026, 9, 10)] + 0.50
    rates[date(2026, 9, 14)] = rates[date(2026, 9, 11)] + 0.05
    market = make_market(
        {
            "ETF_EU": make_bars("ETF_EU", xpar, prices(100.0, 1.0)),
            "ETF_OTHER": make_bars("ETF_OTHER", xpar, prices(200.0, 2.0)),
        },
        None,
        {"RATE_US": make_levels("RATE_US", rates)},
    )
    momentum = ReturnSignal(signal_id="return_2d", lookback_sessions=2, price_basis=PriceBasis.RAW)

    result = run_over(
        market,
        calendars,
        Gated(rank_id="return_rank", gate_id="rate_change_1o", maximum=0.10),
        universe=("ETF_EU", "ETF_OTHER"),
        signals=[
            momentum,
            CrossSectionalRank(signal_id="return_rank", source=momentum),
            SignalRequest(
                LevelChangeSignal(signal_id="rate_change_1o", lookback_observations=1),
                ["RATE_US"],
            ),
        ],
    )

    invested, gated, sold = result.records[1], result.records[2], result.records[3]
    assert invested.target_invested == pytest.approx(1.0)
    assert gated.target_invested == 0.0
    # Not an empty universe: both funds were rankable, and the gate stood them down.
    assert gated.considered == 2
    assert sold.traded_value > 0.0
    assert sold.cash == pytest.approx(sold.net_equity)


def test_an_index_in_the_trading_universe_fails_before_the_first_session(
    market: MarketDataReader, calendars: CalendarRegistry
) -> None:
    """An index has a price and no way to buy it, and the registry says so.

    The refusal comes before a single session is walked: by the time execution
    declined the order, the strategy would already have ranked the index,
    chosen it and sized a position in it.
    """
    watching = Watching()
    engine = engine_over(market, calendars, watching, universe=("ETF_EU", "IDX_US"))

    with pytest.raises(
        NonTradableInstrumentInTradingUniverse, match="IDX_US is declared tradable = false"
    ):
        engine.run()
    assert watching.seen == []


def test_a_bad_member_late_in_the_run_is_still_caught_before_it_starts(
    market: MarketDataReader, calendars: CalendarRegistry
) -> None:
    """Every session's universe is checked first, so a wrong last year fails in the first second."""
    universe = Universe(
        universe_id="LATE_MISTAKE",
        name="An index slips in on the last session",
        memberships=(
            Membership("ETF_EU"),
            Membership("IDX_US", from_date=date(2026, 9, 14)),
        ),
    )
    watching = Watching()

    with pytest.raises(NonTradableInstrumentInTradingUniverse, match="2026-09-14"):
        run_over(market, calendars, watching, universe=universe)
    assert watching.seen == []


def test_a_target_naming_an_instrument_nobody_can_buy_stops_the_run(
    market: MarketDataReader, calendars: CalendarRegistry
) -> None:
    """The universe is clean; the strategy asks for the index anyway.

    Refused where the target is admitted, not clipped to nothing: a rotation
    whose orders are quietly never sent is not a strategy anyone ran.
    """
    with pytest.raises(NonTradableInstrument, match="IDX_US"):
        run_over(market, calendars, AlwaysHold({"IDX_US": 1.0}))


def test_a_signal_may_read_an_instrument_the_book_may_not_hold(
    market: MarketDataReader, calendars: CalendarRegistry
) -> None:
    """Which is the whole point of a universe of its own.

    The index is not tradable, is quoted in dollars and is not in the trading
    universe, and a signal is still computed for it - a gauge is read, never
    bought.
    """
    momentum = ReturnSignal(signal_id="index_2d", lookback_sessions=2, price_basis=PriceBasis.RAW)

    result = run_over(
        market,
        calendars,
        AlwaysHold({"ETF_EU": 1.0}),
        signals=[*a_return(), SignalRequest(momentum, ["IDX_US"])],
    )

    assert result.records[-1].net_equity > 0.0
    assert all(record.rejects == () for record in result.records)


def test_a_fund_quoted_in_another_currency_cannot_join_the_book(
    market: MarketDataReader, calendars: CalendarRegistry
) -> None:
    """Nothing here converts a currency, so adding the two would be adding apples."""
    engine = engine_over(market, calendars, AlwaysHold({}), universe=("ETF_EU", "ETF_US"))

    with pytest.raises(CurrencyMismatchInTradingUniverse, match="ETF_US is quoted in USD"):
        engine.run()


# --- a book kept in dollars, traded in New York ----------------------------------


def dollar_market(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    xnys: TradingCalendar,
    us_sessions: tuple[date, ...],
) -> MarketDataReader:
    """Return a reader over the one fund that trades in New York.

    Its venue is shut on 7 September while Paris - the calendar the run walks -
    is open, which is the only way a held position has a close that is real,
    usable and a session old.
    """
    closes = {session: 100.0 + index for index, session in enumerate(us_sessions)}
    return make_market({"ETF_US": make_bars("ETF_US", xnys, closes)})


NEW_YORK_OPEN = BacktestTimetable(
    decision_time=time(23, 0),
    execution_time=time(16, 0),
    valuation_time=time(23, 0),
    timezone="Europe/Paris",
)
"""Decide after the New York close, fill just after the next New York open.

16:00 in Paris is 10:00 in New York. A European timetable would fill at 09:01
Paris, three hours before the American auction, and every order would be
refused for a reason that has nothing to do with what is being tested.
"""


def dollar_run(
    market: MarketDataReader, calendars: CalendarRegistry, weight: float = 1.0
) -> BacktestResult:
    """Run a book kept in dollars and traded in New York, 2 to 8 September."""
    return run_over(
        market,
        calendars,
        AlwaysHold({"ETF_US": weight}),
        start=date(2026, 9, 2),
        end=date(2026, 9, 8),
        universe=("ETF_US",),
        base_currency="USD",
        timetable=NEW_YORK_OPEN,
    )


def test_a_close_from_an_earlier_session_values_the_book_and_says_so(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    calendars: CalendarRegistry,
    xnys: TradingCalendar,
    us_sessions: tuple[date, ...],
) -> None:
    """A stale close is a number, and it is still not this session's price."""
    result = dollar_run(dollar_market(make_market, make_bars, xnys, us_sessions), calendars)

    labor_day = next(r for r in result.records if r.session_date == date(2026, 9, 7))
    assert labor_day.estimated_valuation_instruments == ("ETF_US",)
    # Friday's close, carried: the position is worth something, just not a
    # price of the day - and nothing was traded on a morning New York was shut.
    friday = next(r for r in result.records if r.session_date == date(2026, 9, 4))
    assert labor_day.net_equity == pytest.approx(friday.net_equity)
    assert [reject.reason for reject in labor_day.rejects] == [
        ExecutionRejectReason.STALE_EXECUTION_PRICE
    ]


def test_a_close_of_the_session_itself_is_not_an_estimate(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    calendars: CalendarRegistry,
    xnys: TradingCalendar,
    us_sessions: tuple[date, ...],
) -> None:
    """The other side of the same rule, so the diagnostic is not simply always on."""
    result = dollar_run(dollar_market(make_market, make_bars, xnys, us_sessions), calendars)

    traded = [r for r in result.records if r.session_date != date(2026, 9, 7)]
    assert all(record.estimated_valuation_instruments == () for record in traded)


def test_whole_shares_are_dealt_where_the_instrument_says_so(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    calendars: CalendarRegistry,
    xnys: TradingCalendar,
    us_sessions: tuple[date, ...],
) -> None:
    """The fund declares a step of one, so the book holds a whole number of them.

    What the rounding leaves stays in cash. A backtest that bought 98.0392 of
    them would have allocated its capital more perfectly than any account
    could, on every rebalancing.
    """
    result = dollar_run(dollar_market(make_market, make_bars, xnys, us_sessions), calendars)

    held = result.records[1].quantities["ETF_US"]
    assert held == float(int(held))
    assert result.records[1].cash > 0.0


def test_a_book_asked_to_keep_what_it_holds_does_not_trade_again(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    calendars: CalendarRegistry,
    xnys: TradingCalendar,
    us_sessions: tuple[date, ...],
) -> None:
    """Bought once in whole shares, then held: one purchase, and nothing else, ever.

    The weight asked for every evening is the one the book has at that close;
    at the next open the prices have moved and the same weight is a fraction
    of a share away from the position. Rounding that target as a position
    would sell a share most mornings and buy none back.
    """
    market = dollar_market(make_market, make_bars, xnys, us_sessions)

    result = run_over(
        market,
        calendars,
        BuyAndHold(instruments=("ETF_US",)),
        start=date(2026, 9, 2),
        end=date(2026, 9, 14),
        universe=("ETF_US",),
        base_currency="USD",
        timetable=NEW_YORK_OPEN,
    )

    fills = [fill for record in result.records for fill in record.fills]
    assert len(fills) == 1
    assert fills[0].side.value == "BUY"
    labor_day = date(2026, 9, 7)
    assert all(r.rejects == () or r.session_date == labor_day for r in result.records)
    held = {record.quantities.get("ETF_US") for record in result.records[1:]}
    assert held == {fills[0].quantity}


def test_whole_shares_keep_the_book_off_its_target(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    calendars: CalendarRegistry,
    xnys: TradingCalendar,
    us_sessions: tuple[date, ...],
) -> None:
    """Half the book asked, a little under half held: target and actual are two numbers."""
    result = dollar_run(
        dollar_market(make_market, make_bars, xnys, us_sessions), calendars, weight=0.5
    )

    filled = result.records[1]
    assert filled.target_invested == 0.5
    assert filled.actual_weights["ETF_US"] != 0.5
    assert filled.actual_weights["ETF_US"] < 0.5


# --- what a record keeps ------------------------------------------------------------


def test_the_record_keeps_the_fills_and_the_positions_they_produced(
    market: MarketDataReader, calendars: CalendarRegistry
) -> None:
    """Why the P&L moved on a given day is a question about fills and positions."""
    result = run_over(market, calendars, AlwaysHold({"ETF_EU": 1.0}))

    filled = result.records[1]
    assert [fill.instrument_id for fill in filled.fills] == ["ETF_EU"]
    assert filled.fills[0].market_price > 0.0
    assert filled.quantities["ETF_EU"] == pytest.approx(10_000.0 / filled.fills[0].fill_price)
    assert filled.holdings["ETF_EU"].average_cost == pytest.approx(107.0)


def test_a_record_cannot_be_edited_into_a_different_run(
    market: MarketDataReader, calendars: CalendarRegistry
) -> None:
    """A result is what the run produced, and reproducibility says it stays that."""
    record = run_over(market, calendars, AlwaysHold({"ETF_EU": 1.0})).records[1]

    with pytest.raises(TypeError):
        record.holdings["ETF_EU"] = record.holdings["ETF_EU"]  # type: ignore[index]
    with pytest.raises(TypeError):
        record.valuation_prices["ETF_EU"] = 1.0  # type: ignore[index]
    assert record.decision is not None
    with pytest.raises(TypeError):
        record.decision.accepted_weights["ETF_EU"] = 0.5  # type: ignore[index]


def test_what_was_asked_for_and_what_was_reached_are_two_numbers(
    market: MarketDataReader, calendars: CalendarRegistry
) -> None:
    """On the first session the target is everything and nothing is held yet.

    Reporting the target as the exposure would say the book was fully invested
    on a session it held nothing at all.
    """
    result = run_over(market, calendars, AlwaysHold({"ETF_EU": 1.0}))

    first = result.records[0]
    assert first.target_invested == pytest.approx(1.0)
    assert first.actual_invested == 0.0
    assert result.records[1].actual_invested == pytest.approx(1.0)


def test_a_gauge_universe_is_asked_about_the_session_being_decided(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    xpar: TradingCalendar,
    calendars: CalendarRegistry,
    prices: Callable[..., dict[date, float]],
) -> None:
    """A signal's own universe may be dated too, and the engine resolves it."""
    gauges = Universe(
        universe_id="GAUGES",
        name="One gauge stops being followed",
        memberships=(
            Membership("ETF_EU"),
            Membership("ETF_OTHER", until_date=date(2026, 9, 10)),
        ),
    )
    watching = Watching()

    run_over(
        leaver_market(make_market, make_bars, xpar, prices),
        calendars,
        watching,
        signals=[
            *a_return(),
            SignalRequest(
                ReturnSignal(signal_id="gauge_2d", lookback_sessions=2, price_basis=PriceBasis.RAW),
                gauges,
            ),
        ],
    )

    watched = [given.signals.result("gauge_2d").instruments() for given in watching.seen]
    # 9 September and 10 September hold both; 11 and 14 hold one.
    assert watched[0] == ("ETF_EU", "ETF_OTHER")
    assert watched[-1] == ("ETF_EU",)


# --- corporate actions -----------------------------------------------------------------


def test_a_split_on_a_held_position_stops_the_run(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    make_actions: Callable[..., pd.DataFrame],
    xpar: TradingCalendar,
    calendars: CalendarRegistry,
    prices: Callable[..., dict[date, float]],
) -> None:
    """Holding the quantity through a split would show a collapse that never happened."""
    open_of_the_eleventh = datetime(2026, 9, 11, 9, 0, tzinfo=PARIS_ZONE)
    market = make_market(
        {"ETF_EU": make_bars("ETF_EU", xpar, prices(100.0, 1.0))},
        make_actions([("ETF_EU", ActionType.SPLIT, date(2026, 9, 11), 2.0, open_of_the_eleventh)]),
    )

    with pytest.raises(UnsupportedCorporateAction, match="ETF_EU is held and goes ex on a SPLIT"):
        run_over(market, calendars, AlwaysHold({"ETF_EU": 1.0}))


def test_a_dividend_on_a_held_position_stops_the_run(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    make_actions: Callable[..., pd.DataFrame],
    xpar: TradingCalendar,
    calendars: CalendarRegistry,
    prices: Callable[..., dict[date, float]],
) -> None:
    """A dividend that never reached the cash would read as a loss."""
    open_of_the_eleventh = datetime(2026, 9, 11, 9, 0, tzinfo=PARIS_ZONE)
    market = make_market(
        {"ETF_EU": make_bars("ETF_EU", xpar, prices(100.0, 1.0))},
        make_actions(
            [("ETF_EU", ActionType.DIVIDEND, date(2026, 9, 11), 1.5, open_of_the_eleventh)]
        ),
    )

    with pytest.raises(UnsupportedCorporateAction, match="DIVIDEND"):
        run_over(market, calendars, AlwaysHold({"ETF_EU": 1.0}))


def test_a_corporate_action_on_something_not_held_changes_nothing(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    make_actions: Callable[..., pd.DataFrame],
    xpar: TradingCalendar,
    calendars: CalendarRegistry,
    prices: Callable[..., dict[date, float]],
) -> None:
    """A split of a fund the book never held does not concern the book."""
    open_of_the_eleventh = datetime(2026, 9, 11, 9, 0, tzinfo=PARIS_ZONE)
    market = make_market(
        {
            "ETF_EU": make_bars("ETF_EU", xpar, prices(100.0, 1.0)),
            "ETF_OTHER": make_bars("ETF_OTHER", xpar, prices(200.0, 2.0)),
        },
        make_actions(
            [("ETF_OTHER", ActionType.SPLIT, date(2026, 9, 11), 2.0, open_of_the_eleventh)]
        ),
    )

    result = run_over(market, calendars, AlwaysHold({"ETF_EU": 1.0}))

    assert result.records[-1].net_equity > 0.0


def test_an_action_before_the_position_was_bought_is_not_its_business(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    make_actions: Callable[..., pd.DataFrame],
    xpar: TradingCalendar,
    calendars: CalendarRegistry,
    prices: Callable[..., dict[date, float]],
) -> None:
    """A split that went ex before the first purchase is already in the price paid."""
    open_of_the_first = datetime(2026, 9, 1, 9, 0, tzinfo=PARIS_ZONE)
    market = make_market(
        {"ETF_EU": make_bars("ETF_EU", xpar, prices(100.0, 1.0))},
        make_actions([("ETF_EU", ActionType.SPLIT, date(2026, 9, 1), 2.0, open_of_the_first)]),
    )

    result = run_over(market, calendars, AlwaysHold({"ETF_EU": 1.0}))

    assert result.records[-1].net_equity == pytest.approx(10_000.0 * 109.0 / 107.0)
