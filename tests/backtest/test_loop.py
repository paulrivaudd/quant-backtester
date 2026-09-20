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

import pandas as pd
import pytest

from quant_backtester.backtest.engine import (
    BacktestEngine,
    BacktestResult,
    Strategy,
    Timetable,
)
from quant_backtester.data.calendars import CalendarRegistry, TradingCalendar
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.data.universes import Membership, Universe
from quant_backtester.execution.costs import CostModel
from quant_backtester.execution.fills import ExecutionModel
from quant_backtester.portfolio.limits import PositionLimits
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.signals.base import Signal
from quant_backtester.signals.cross_sectional.rank import CrossSectionalRank
from quant_backtester.signals.engine import SignalRequest
from quant_backtester.signals.level.change import LevelChangeSignal
from quant_backtester.signals.price.returns import ReturnSignal
from quant_backtester.signals.snapshot import SignalSnapshot
from quant_backtester.signals.types import PriceBasis, SignalStatus
from quant_backtester.strategies.risk_gated import RiskGatedRotation
from quant_backtester.strategies.rotation import TopRankRotation

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
    base_currency: str = "EUR",
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
        base_currency=base_currency,
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
    assert result.records[0].target_invested == pytest.approx(0.25)
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
        ({"initial_cash": float("nan")}, "initial_cash"),
        ({"initial_cash": float("inf")}, "initial_cash"),
        ({"initial_cash": True}, "initial_cash"),
        ({"base_currency": ""}, "base_currency"),
        ({"universe": ("ETF_EU", "ETF_EU")}, "more than once"),
    ],
    ids=[
        "no-capital",
        "negative-capital",
        "capital-that-is-not-a-number",
        "infinite-capital",
        "capital-as-a-boolean",
        "no-currency",
        "repeated-instrument",
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


def test_a_run_never_spends_cash_it_does_not_have(
    market: MarketDataReader, calendars: CalendarRegistry, sessions: tuple[date, ...]
) -> None:
    """A fully invested strategy pays its costs out of the position.

    The target is a whole book and the costs have to come from somewhere. A
    book that let its cash go negative would be borrowing at no rate, every
    session, for the length of the run - a loan the model never granted and a
    return nobody could have earned.
    """
    costly = ExecutionModel(
        costs=CostModel(commission_rate=0.001, half_spread=0.002, slippage_rate=0.001)
    )

    result = run_over(market, calendars, sessions, AlwaysHold({"ETF_EU": 1.0}), execution=costly)

    for record in result.records:
        assert record.cash >= -1e-9, f"{record.session_date} ended on borrowed cash"


def test_a_purchase_the_cash_could_not_carry_is_named(
    market: MarketDataReader, calendars: CalendarRegistry, sessions: tuple[date, ...]
) -> None:
    """Trimmed, and said out loud: the record carries what execution cut."""
    costly = ExecutionModel(costs=CostModel(commission_rate=0.001, half_spread=0.002))

    result = run_over(market, calendars, sessions, AlwaysHold({"ETF_EU": 1.0}), execution=costly)

    assert result.records[1].unfunded == ("ETF_EU",)
    assert result.records[0].unfunded == ()


# --- the universe is asked session by session --------------------------------


@dataclass(frozen=True, slots=True)
class HoldWhatIsOffered(Strategy):
    """Equal weights over whatever the snapshot holds.

    It exists so that a test about the universe is about the universe: the
    strategy has no opinion of its own, so what it targets is exactly what it
    was allowed to choose from.
    """

    signal_id: str

    def decide(self, signals: SignalSnapshot) -> TargetAllocation:
        """Spread the book over every instrument in the snapshot."""
        names = tuple(signals.result(self.signal_id).instruments())
        weight = 1.0 / len(names) if names else 0.0
        return TargetAllocation(
            as_of=signals.as_of,
            weights={name: weight for name in names},
            selected=names,
            considered=len(names),
            skipped={},
        )


def test_a_member_that_left_is_not_chosen_after_it_did(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    xpar: TradingCalendar,
    calendars: CalendarRegistry,
    prices: Callable[..., dict[date, float]],
    sessions: tuple[date, ...],
) -> None:
    """The universe is asked on every session, and it answers for that session.

    ETF_OTHER leaves after 10 September. The decision taken at that close still
    holds it; the one taken the next session cannot, and the sale happens at
    the open after that - the same gap every other order goes through.
    """
    market = make_market(
        {
            "ETF_EU": make_bars("ETF_EU", xpar, prices(100.0, 1.0)),
            "ETF_OTHER": make_bars("ETF_OTHER", xpar, prices(200.0, 2.0)),
        }
    )
    universe = Universe(
        universe_id="LEAVER",
        name="One fund leaves",
        memberships=(
            Membership("ETF_EU"),
            Membership("ETF_OTHER", until_date=date(2026, 9, 10)),
        ),
    )
    engine = BacktestEngine(
        reader=market,
        calendars=calendars,
        reference_calendar_id="XPAR",
        signals=a_return(),
        strategy=HoldWhatIsOffered(signal_id="return_2d"),
        universe=universe,
        initial_cash=10_000.0,
        base_currency="EUR",
        limits=PositionLimits(),
        execution=ExecutionModel(),
        timetable=PARIS,
    )

    result = engine.run(sessions[-4], sessions[-1])

    decided_on_the_tenth = result.records[1]
    decided_on_the_eleventh = result.records[2]
    assert set(decided_on_the_tenth.weights) == {"ETF_EU", "ETF_OTHER"}
    assert set(decided_on_the_eleventh.weights) == {"ETF_EU"}
    assert decided_on_the_eleventh.considered == 1
    # The target that drops it is filled at the next open, not at the close it
    # was decided after.
    assert result.records[-1].traded_value > 0.0


def test_a_universe_given_as_a_list_is_still_asked_by_session(
    market: MarketDataReader, calendars: CalendarRegistry, sessions: tuple[date, ...]
) -> None:
    """A plain sequence becomes a static universe, and nothing below notices."""
    engine = engine_over(market, calendars, AlwaysHold({"ETF_EU": 1.0}))

    assert engine.dated_universe.members_at(sessions[0]) == ("ETF_EU",)
    assert engine.dated_universe.members_at(sessions[-1]) == ("ETF_EU",)


def test_a_universe_that_repeats_an_instrument_is_refused(
    market: MarketDataReader, calendars: CalendarRegistry
) -> None:
    """Twice in a universe would weight it twice in a ranking."""
    with pytest.raises(ValueError, match="more than once"):
        engine_over(market, calendars, AlwaysHold({"ETF_EU": 1.0}), universe=("ETF_EU", "ETF_EU"))


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
    engine = BacktestEngine(
        reader=market,
        calendars=calendars,
        reference_calendar_id="XPAR",
        signals=[
            momentum,
            CrossSectionalRank(signal_id="return_rank", source=momentum),
            SignalRequest(
                LevelChangeSignal(signal_id="rate_change_1o", lookback_observations=1),
                ["RATE_US"],
            ),
        ],
        strategy=RiskGatedRotation(
            rotation=TopRankRotation(signal_id="return_rank", top_n=1),
            gate_signal_id="rate_change_1o",
            gate_instrument_id="RATE_US",
            maximum=0.10,
            flat_when_unknown=True,
        ),
        universe=("ETF_EU", "ETF_OTHER"),
        initial_cash=10_000.0,
        base_currency="EUR",
        limits=PositionLimits(),
        execution=ExecutionModel(),
        timetable=PARIS,
    )

    result = engine.run(sessions[-4], sessions[-1])

    invested, gated, sold = result.records[1], result.records[2], result.records[3]
    assert invested.target_invested == pytest.approx(1.0)
    assert gated.target_invested == 0.0
    # Not an empty universe: both funds were rankable, and the gate stood them down.
    assert gated.considered == 2
    assert sold.traded_value > 0.0
    assert sold.cash == pytest.approx(sold.equity)


def test_an_instrument_the_registry_says_is_not_tradable_cannot_be_in_the_universe(
    market: MarketDataReader, calendars: CalendarRegistry, sessions: tuple[date, ...]
) -> None:
    """An index has a price and no way to buy it, and the registry says so.

    The refusal is at the top of the session rather than at the fill: by the
    time execution declines the order, the strategy has already ranked the
    index, chosen it and sized a position in it, and the run would report a
    rotation whose orders are quietly never sent.
    """
    engine = engine_over(market, calendars, AlwaysHold({}), universe=("ETF_EU", "IDX_US"))

    with pytest.raises(ValueError, match="IDX_US is declared tradable = false"):
        engine.run(sessions[-4], sessions[-1])


def test_an_instrument_that_may_not_be_held_is_never_dealt_at_either(
    market: MarketDataReader, calendars: CalendarRegistry, sessions: tuple[date, ...]
) -> None:
    """The last check before a trade exists, and it does not trust the first one.

    The universe here is clean; the strategy asks for the index anyway. The
    index prints an opening auction every morning, so only the registry can
    say that nobody could have bought it.
    """
    result = run_over(market, calendars, sessions, AlwaysHold({"IDX_US": 1.0}))

    filled = result.records[1]
    assert filled.untradable == ("IDX_US",)
    assert filled.fills == ()
    assert filled.equity == pytest.approx(10_000.0)


def test_a_signal_may_read_an_instrument_the_book_may_not_hold(
    market: MarketDataReader, calendars: CalendarRegistry, sessions: tuple[date, ...]
) -> None:
    """Which is the whole point of a universe of its own.

    The index is not tradable and not in the trading universe, and a signal is
    still computed for it - a gauge is read, never bought.
    """
    momentum = ReturnSignal(signal_id="index_2d", lookback_sessions=2, price_basis=PriceBasis.RAW)
    engine = BacktestEngine(
        reader=market,
        calendars=calendars,
        reference_calendar_id="XPAR",
        signals=[*a_return(), SignalRequest(momentum, ["IDX_US"])],
        strategy=AlwaysHold({"ETF_EU": 1.0}),
        universe=("ETF_EU",),
        initial_cash=10_000.0,
        base_currency="EUR",
        limits=PositionLimits(),
        execution=ExecutionModel(),
        timetable=PARIS,
    )

    result = engine.run(sessions[-4], sessions[-1])

    assert result.records[-1].equity > 0.0
    assert all(record.untradable == () for record in result.records[1:])


def test_a_fund_quoted_in_another_currency_cannot_join_the_book(
    market: MarketDataReader, calendars: CalendarRegistry, sessions: tuple[date, ...]
) -> None:
    """Nothing here converts a currency, so adding the two would be adding apples.

    A euro of one fund and a dollar of another are not a euro and a euro, and
    an equity curve that added them would carry the error inside itself rather
    than beside it.
    """
    engine = engine_over(market, calendars, AlwaysHold({}), universe=("ETF_EU", "ETF_US"))

    with pytest.raises(ValueError, match="ETF_US is quoted in USD"):
        engine.run(sessions[-4], sessions[-1])


def test_a_signal_only_instrument_may_be_quoted_in_anything(
    market: MarketDataReader, calendars: CalendarRegistry, sessions: tuple[date, ...]
) -> None:
    """The currency rule is about what is held, not about what is read."""
    dollars = ReturnSignal(signal_id="us_2d", lookback_sessions=2, price_basis=PriceBasis.RAW)
    engine = BacktestEngine(
        reader=market,
        calendars=calendars,
        reference_calendar_id="XPAR",
        signals=[*a_return(), SignalRequest(dollars, ["IDX_US"])],
        strategy=AlwaysHold({"ETF_EU": 1.0}),
        universe=("ETF_EU",),
        initial_cash=10_000.0,
        base_currency="EUR",
        limits=PositionLimits(),
        execution=ExecutionModel(),
        timetable=PARIS,
    )

    assert engine.run(sessions[-4], sessions[-1]).records


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


NEW_YORK_OPEN = Timetable(
    decision_time=time(23, 0), execution_time=time(16, 0), timezone="Europe/Paris"
)
"""Decide after the New York close, fill just after the next New York open.

16:00 in Paris is 10:00 in New York. A European timetable would fill at 09:01
Paris, three hours before the American auction, and every order would be
refused for a reason that has nothing to do with what is being tested.
"""


def dollar_engine(market: MarketDataReader, calendars: CalendarRegistry) -> BacktestEngine:
    """Wire an engine that keeps its book in dollars and trades in New York."""
    return BacktestEngine(
        reader=market,
        calendars=calendars,
        reference_calendar_id="XPAR",
        signals=a_return(),
        strategy=AlwaysHold({"ETF_US": 1.0}),
        universe=("ETF_US",),
        initial_cash=10_000.0,
        base_currency="USD",
        limits=PositionLimits(),
        execution=ExecutionModel(),
        timetable=NEW_YORK_OPEN,
    )


def test_a_close_from_an_earlier_session_values_the_book_and_says_so(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    calendars: CalendarRegistry,
    xnys: TradingCalendar,
    us_sessions: tuple[date, ...],
) -> None:
    """A stale close is a number, and it is still not this session's price.

    The reader hands back the last close it had, which is the right thing to
    mark the book at. A run that only looked at the number would report an
    estimate as a print, and the report would say no session was valued on an
    older close when a position was.
    """
    market = dollar_market(make_market, make_bars, xnys, us_sessions)

    result = dollar_engine(market, calendars).run(date(2026, 9, 2), date(2026, 9, 8))

    labor_day = next(r for r in result.records if r.session_date == date(2026, 9, 7))
    assert labor_day.priced_from_earlier == ("ETF_US",)
    # Friday's close, carried: the position is worth something, just not a
    # price of the day.
    friday = next(r for r in result.records if r.session_date == date(2026, 9, 4))
    assert labor_day.equity == pytest.approx(friday.equity)


def test_a_close_of_the_session_itself_is_not_an_estimate(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    calendars: CalendarRegistry,
    xnys: TradingCalendar,
    us_sessions: tuple[date, ...],
) -> None:
    """The other side of the same rule, so the diagnostic is not simply always on."""
    market = dollar_market(make_market, make_bars, xnys, us_sessions)

    result = dollar_engine(market, calendars).run(date(2026, 9, 2), date(2026, 9, 8))

    traded = [r for r in result.records if r.session_date != date(2026, 9, 7)]
    assert all(record.priced_from_earlier == () for record in traded)


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
    market = dollar_market(make_market, make_bars, xnys, us_sessions)

    result = dollar_engine(market, calendars).run(date(2026, 9, 2), date(2026, 9, 8))

    held = result.records[1].quantities["ETF_US"]
    assert held == float(int(held))
    assert result.records[1].cash > 0.0


def test_the_record_keeps_the_fills_and_the_positions_they_produced(
    market: MarketDataReader, calendars: CalendarRegistry, sessions: tuple[date, ...]
) -> None:
    """Why the P&L moved on a given day is a question about fills and positions.

    Without them, a run can only be read as an equity curve with costs beside
    it, and any attribution per instrument would have to be guessed at.
    """
    result = run_over(market, calendars, sessions, AlwaysHold({"ETF_EU": 1.0}))

    filled = result.records[1]
    assert [fill.instrument_id for fill in filled.fills] == ["ETF_EU"]
    assert filled.fills[0].reference_price > 0.0
    assert filled.quantities["ETF_EU"] == pytest.approx(10_000.0 / filled.fills[0].fill_price)


def test_a_record_cannot_be_edited_into_a_different_run(
    market: MarketDataReader, calendars: CalendarRegistry, sessions: tuple[date, ...]
) -> None:
    """A result is what the run produced, and reproducibility says it stays that."""
    record = run_over(market, calendars, sessions, AlwaysHold({"ETF_EU": 1.0})).records[1]

    with pytest.raises(TypeError):
        record.weights["ETF_EU"] = 0.5  # type: ignore[index]
    with pytest.raises(TypeError):
        record.quantities["ETF_EU"] = 1.0  # type: ignore[index]


def test_what_was_asked_for_and_what_was_reached_are_two_numbers(
    market: MarketDataReader, calendars: CalendarRegistry, sessions: tuple[date, ...]
) -> None:
    """On the first session the target is everything and nothing is held yet.

    Reporting the target as the exposure would say the book was fully invested
    on a session it held nothing at all.
    """
    result = run_over(market, calendars, sessions, AlwaysHold({"ETF_EU": 1.0}))

    first = result.records[0]
    assert first.target_invested == pytest.approx(1.0)
    assert first.actual_invested == 0.0
    assert result.records[1].actual_invested == pytest.approx(1.0)
