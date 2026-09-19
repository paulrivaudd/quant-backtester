"""The loop: the order of a session, the gap it models, and what it records.

The arithmetic below is small enough to check by hand, which is the point. What
the engine has to get right is not a formula but a sequence - value, decide,
fill at the *next* open - and the cheapest way to see that it does is to make
the prices so simple that any other sequence gives a different number.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, time

import pytest

from quant_backtester.backtest.engine import (
    BacktestEngine,
    BacktestResult,
    Strategy,
    Timetable,
)
from quant_backtester.data.calendars import CalendarRegistry, TradingCalendar
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.execution.costs import CostModel
from quant_backtester.execution.fills import ExecutionModel
from quant_backtester.portfolio.limits import PositionLimits
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.signals.base import Signal
from quant_backtester.signals.price.returns import ReturnSignal
from quant_backtester.signals.snapshot import SignalSnapshot
from quant_backtester.signals.types import PriceBasis, SignalStatus

PARIS = Timetable(decision_time=time(23, 0), execution_time=time(9, 1), timezone="Europe/Paris")


@dataclass(frozen=True, slots=True)
class AlwaysHold(Strategy):
    """A strategy that always wants the same book, whatever the signals say.

    It exists so that a test about the loop is about the loop: with the target
    fixed, every number in the record comes from the prices and the sequence.
    """

    weights: Mapping[str, float]

    def decide(self, signals: SignalSnapshot) -> TargetAllocation:
        """Return the fixed target, stamped at the snapshot's instant."""
        return TargetAllocation(
            as_of=signals.as_of,
            weights=dict(self.weights),
            selected=tuple(self.weights),
            considered=len(self.weights),
            skipped={},
        )


def a_return() -> Sequence[Signal]:
    """Return one cheap signal, so the engine has something to compute."""
    return [ReturnSignal(signal_id="return_2d", lookback_sessions=2, price_basis=PriceBasis.RAW)]


def engine_over(
    market: MarketDataReader,
    calendars: CalendarRegistry,
    strategy: Strategy,
    *,
    universe: Sequence[str] = ("ETF_EU",),
    execution: ExecutionModel | None = None,
    limits: PositionLimits | None = None,
    initial_cash: float = 10_000.0,
) -> BacktestEngine:
    """Wire an engine onto the synthetic market."""
    return BacktestEngine(
        reader=market,
        calendars=calendars,
        reference_calendar_id="XPAR",
        signals=a_return(),
        strategy=strategy,
        universe=universe,
        initial_cash=initial_cash,
        limits=limits or PositionLimits(),
        execution=execution or ExecutionModel(),
        timetable=PARIS,
    )


def run_over(
    market: MarketDataReader,
    calendars: CalendarRegistry,
    sessions: tuple[date, ...],
    strategy: Strategy,
    **overrides: object,
) -> BacktestResult:
    """Run over the last four sessions of the synthetic market."""
    engine = engine_over(market, calendars, strategy, **overrides)  # type: ignore[arg-type]
    return engine.run(sessions[-4], sessions[-1])


def test_a_run_records_one_session_at_a_time(
    market: MarketDataReader, calendars: CalendarRegistry, sessions: tuple[date, ...]
) -> None:
    """One record per session of the reference calendar, in order."""
    result = run_over(market, calendars, sessions, AlwaysHold({"ETF_EU": 1.0}))

    assert [record.session_date for record in result.records] == list(sessions[-4:])


def test_the_first_session_holds_nothing_yet(
    market: MarketDataReader, calendars: CalendarRegistry, sessions: tuple[date, ...]
) -> None:
    """Nothing was decided before it, so there is nothing to fill at its open.

    A run that started invested would be a run that traded on a decision it
    never took.
    """
    result = run_over(market, calendars, sessions, AlwaysHold({"ETF_EU": 1.0}))
    first = result.records[0]

    assert first.equity == pytest.approx(10_000.0)
    assert first.cash == pytest.approx(10_000.0)
    assert first.traded_value == 0.0


def test_a_decision_is_filled_at_the_next_open_and_not_before(
    market: MarketDataReader, calendars: CalendarRegistry, sessions: tuple[date, ...]
) -> None:
    """The gap the whole project is built around, in one assertion.

    The prices rise by one a session and the open equals the close, so the
    target decided after the close of the first session buys at 107, not at
    106. Filling at the price that produced the decision would show 10000/106
    units instead.
    """
    result = run_over(market, calendars, sessions, AlwaysHold({"ETF_EU": 1.0}))
    second = result.records[1]

    assert second.traded_value == pytest.approx(10_000.0)
    assert second.cash == pytest.approx(0.0)
    # 10 000 at 107, then marked at that session's close of 107.
    assert second.equity == pytest.approx(10_000.0)


def test_the_book_follows_the_market_after_it_is_invested(
    market: MarketDataReader, calendars: CalendarRegistry, sessions: tuple[date, ...]
) -> None:
    """Bought at 107, marked at 109 two sessions later."""
    result = run_over(market, calendars, sessions, AlwaysHold({"ETF_EU": 1.0}))

    assert result.records[-1].equity == pytest.approx(10_000.0 * 109.0 / 107.0)
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
    market: MarketDataReader, calendars: CalendarRegistry, sessions: tuple[date, ...]
) -> None:
    """What is not allocated is not invested, and does not move."""
    result = run_over(market, calendars, sessions, AlwaysHold({"ETF_EU": 0.5}))
    final = result.records[-1]

    assert final.equity == pytest.approx(walked_by_hand([107.0, 108.0, 109.0], 0.5, 10_000.0))
    assert final.cash == pytest.approx(final.equity * 0.5)
    # Half the exposure, so less than the move a fully invested book made.
    assert 0 < result.net_return < 109.0 / 107.0 - 1.0


def test_gross_and_net_are_reported_side_by_side(
    market: MarketDataReader, calendars: CalendarRegistry, sessions: tuple[date, ...]
) -> None:
    """The same trades, one book paying the costs and one not.

    Re-running the strategy without costs would let the two books hold
    different things and stop them being comparable at all.
    """
    costly = ExecutionModel(
        costs=CostModel(commission_rate=0.001, half_spread=0.002, slippage_rate=0.001)
    )
    result = run_over(market, calendars, sessions, AlwaysHold({"ETF_EU": 1.0}), execution=costly)

    assert result.gross_return > result.net_return
    assert result.total_cost > 0.0
    final = result.records[-1]
    assert final.gross_equity > final.equity


def test_a_run_with_no_costs_has_gross_equal_to_net(
    market: MarketDataReader, calendars: CalendarRegistry, sessions: tuple[date, ...]
) -> None:
    """Which is what makes the difference above attributable to the cost model."""
    result = run_over(market, calendars, sessions, AlwaysHold({"ETF_EU": 1.0}))

    for record in result.records:
        assert record.gross_equity == pytest.approx(record.equity)
    assert result.total_cost == 0.0


def test_the_three_costs_are_recorded_apart(
    market: MarketDataReader, calendars: CalendarRegistry, sessions: tuple[date, ...]
) -> None:
    """A report has to be able to say which of them ate the return."""
    costly = ExecutionModel(costs=CostModel(commission_rate=0.001, half_spread=0.002))
    result = run_over(market, calendars, sessions, AlwaysHold({"ETF_EU": 1.0}), execution=costly)
    traded = result.records[1]

    assert traded.commission > 0.0
    assert traded.market_cost > 0.0
    assert traded.cost == pytest.approx(traded.commission + traded.market_cost)


def test_the_limits_are_applied_to_whatever_the_strategy_asks(
    market: MarketDataReader, calendars: CalendarRegistry, sessions: tuple[date, ...]
) -> None:
    """A strategy asking for everything is held to what the portfolio allows."""
    result = run_over(
        market,
        calendars,
        sessions,
        AlwaysHold({"ETF_EU": 1.0}),
        limits=PositionLimits(max_weight=0.25),
    )

    final = result.records[-1]
    assert result.records[0].invested == pytest.approx(0.25)
    assert final.equity == pytest.approx(walked_by_hand([107.0, 108.0, 109.0], 0.25, 10_000.0))
    assert final.cash == pytest.approx(final.equity * 0.75)


def test_the_last_decision_is_recorded_but_never_filled(
    market: MarketDataReader, calendars: CalendarRegistry, sessions: tuple[date, ...]
) -> None:
    """No session follows it inside the range, so nothing trades on it.

    It is still on the record: what a strategy wanted on its last day is part
    of what the run says, and dropping it would hide the state the book was
    about to move to.
    """
    result = run_over(market, calendars, sessions, AlwaysHold({"ETF_EU": 1.0}))

    assert result.records[-1].weights == {"ETF_EU": 1.0}


def test_an_instrument_that_cannot_be_dealt_is_named_and_left_alone(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., object],
    calendars: CalendarRegistry,
    prices: Callable[..., dict[date, float]],
    sessions: tuple[date, ...],
    xpar: TradingCalendar,
) -> None:
    """A morning with no opening auction is a morning with no trade.

    The position stays where it was, the record names the instrument, and the
    book is still valued - being untradable and being worthless are not the
    same thing.
    """
    from quant_backtester.data.schemas import BarField

    market = make_market(
        {
            "ETF_EU": make_bars(
                "ETF_EU",
                xpar,
                prices(100.0, 1.0),
                contested={sessions[-2]: [BarField.OPEN]},
            )
        }
    )
    result = run_over(market, calendars, sessions, AlwaysHold({"ETF_EU": 1.0}))

    blocked = next(record for record in result.records if record.session_date == sessions[-2])
    assert blocked.untradable == ("ETF_EU",)
    assert blocked.traded_value == 0.0
    # The position bought at 107 the morning before is untouched, and still
    # worth what the market says it is worth at this session's close.
    assert blocked.equity == pytest.approx(10_000.0 * 108.0 / 107.0)


def test_the_run_is_a_frame_anyone_can_read(
    market: MarketDataReader, calendars: CalendarRegistry, sessions: tuple[date, ...]
) -> None:
    """Gross and net beside each other, with the costs that separate them."""
    frame = run_over(market, calendars, sessions, AlwaysHold({"ETF_EU": 1.0})).frame()

    assert list(frame.index) == list(sessions[-4:])
    for column in ("equity", "gross_equity", "cash", "commission", "market_cost", "cost"):
        assert column in frame.columns


def test_the_strategy_only_ever_sees_a_snapshot(
    market: MarketDataReader, calendars: CalendarRegistry, sessions: tuple[date, ...]
) -> None:
    """The boundary, checked from the inside of a real run."""
    seen: list[object] = []

    @dataclass(frozen=True, slots=True)
    class Watching(Strategy):
        def decide(self, signals: SignalSnapshot) -> TargetAllocation:
            seen.append(signals)
            return TargetAllocation(
                as_of=signals.as_of,
                weights={},
                selected=(),
                considered=0,
                skipped={"ETF_EU": SignalStatus.OK},
            )

    run_over(market, calendars, sessions, Watching())

    assert seen
    assert all(isinstance(given, SignalSnapshot) for given in seen)


def test_the_signals_are_computed_at_the_decision_instant(
    market: MarketDataReader, calendars: CalendarRegistry, sessions: tuple[date, ...]
) -> None:
    """Every snapshot answers the close of the session it belongs to."""
    stamps: list[object] = []

    @dataclass(frozen=True, slots=True)
    class Watching(Strategy):
        def decide(self, signals: SignalSnapshot) -> TargetAllocation:
            stamps.append(signals.as_of)
            return TargetAllocation(
                as_of=signals.as_of, weights={}, selected=(), considered=0, skipped={}
            )

    result = run_over(market, calendars, sessions, Watching())

    assert stamps == [record.decision_at for record in result.records]


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"initial_cash": 0.0}, "initial_cash"),
        ({"initial_cash": -1.0}, "initial_cash"),
        ({"universe": ("ETF_EU", "ETF_EU")}, "more than once"),
    ],
    ids=["no-capital", "negative-capital", "repeated-instrument"],
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


def test_a_range_running_backwards_is_refused(
    market: MarketDataReader, calendars: CalendarRegistry, sessions: tuple[date, ...]
) -> None:
    with pytest.raises(ValueError, match="after end"):
        engine_over(market, calendars, AlwaysHold({})).run(sessions[-1], sessions[0])


def test_a_time_carrying_its_own_offset_is_refused() -> None:
    """A wall-clock time plus a zone survives a DST switch; an offset does not."""
    from datetime import UTC

    with pytest.raises(ValueError, match="naive local time"):
        Timetable(decision_time=time(23, 0, tzinfo=UTC))
