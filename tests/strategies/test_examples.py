"""The strategies a user is meant to copy, and the decisions they encode.

Each of these is a few lines long, which is the point. What is tested is not
arithmetic - the layers underneath have their own tests for that - but the
decisions the examples take: what they hold, what they do when a number cannot
be computed, and what they refuse to touch.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date, datetime

import pandas as pd
import pytest

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.data.calendars import TradingCalendar
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.signals.base import Signal
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.engine import SignalEngine, SignalRequest
from quant_backtester.signals.types import SignalStatus
from quant_backtester.strategies.base import Strategy
from quant_backtester.strategies.examples import (
    BuyAndHold,
    EqualWeightRebalance,
    MomentumRotation,
    MomentumSingleAsset,
    MomentumVix,
)

DecisionBuilder = Callable[..., StrategyContext]
"""Builds the context a strategy is handed; the fixture lives in conftest."""

UNIVERSE = ("ETF_EU", "ETF_OTHER")
"""Two tradable Paris funds, which is what makes a rotation a rotation."""


def snapshot_of(context: SignalContext, values: dict[str, float]):
    """Return a snapshot holding one score per instrument."""
    from quant_backtester.signals.base import (
        Signal,
        SignalResult,
        build_result_frame,
        result_row,
    )
    from quant_backtester.signals.windows import LoadedWindow

    class Fixed(Signal):
        signal_id = "score"

        def definition(self) -> dict[str, object]:
            return {"type": "Fixed"}

        def compute(self, context: SignalContext, instrument_ids: Sequence[str]) -> SignalResult:
            rows = {
                name: result_row(
                    values[name],
                    LoadedWindow(status=SignalStatus.OK, points=(1.0,), age_sessions=0),
                )
                for name in instrument_ids
            }
            return SignalResult(
                signal_id="score",
                as_of=context.as_of,
                _frame=build_result_frame(rows),
                definition=self.definition(),
            )

    return SignalEngine().compute(context, [Fixed()], list(values))


def decide_with(
    strategy: Strategy,
    context: SignalContext,
    make_decision: DecisionBuilder,
    universe: tuple[str, ...] = UNIVERSE,
):
    """Compute the strategy's own signals, then let it decide."""
    requests = [
        item.resolved(date(2026, 9, 14)) if isinstance(item, SignalRequest) else item
        for item in strategy.required_signals()
    ]
    snapshot = SignalEngine().compute(context, requests, list(universe))
    return strategy.decide(make_decision(context, snapshot, universe=universe))


def _id_of(item: Signal | SignalRequest) -> str:
    """Return the id of a declared signal, whether or not it carries a universe."""
    return item.signal.signal_id if isinstance(item, SignalRequest) else item.signal_id


def test_buy_and_hold_holds_the_same_book_every_session(
    context: SignalContext, make_decision: DecisionBuilder
) -> None:
    """No signal, no condition: the baseline every other strategy is judged against."""
    allocation = decide_with(BuyAndHold(instruments=UNIVERSE), context, make_decision)

    assert dict(allocation.weights) == {"ETF_EU": 0.5, "ETF_OTHER": 0.5}


def test_buy_and_hold_cannot_hold_what_the_universe_does_not(
    context: SignalContext, make_decision: DecisionBuilder
) -> None:
    """A name outside the session's universe is a configuration mistake."""
    strategy = BuyAndHold(instruments=("ETF_US",))

    with pytest.raises(ValueError, match="not in this session's universe"):
        decide_with(strategy, context, make_decision)


def test_buy_and_hold_of_nothing_is_refused() -> None:
    """A book with nothing in it is not a book to hold."""
    with pytest.raises(ValueError, match="at least one instrument"):
        BuyAndHold(instruments=())


def test_momentum_holds_the_fund_while_it_is_rising(
    context: SignalContext, make_decision: DecisionBuilder
) -> None:
    """The synthetic market rises by one a session, so the momentum is positive."""
    strategy = MomentumSingleAsset(instrument_id="ETF_EU", lookback_sessions=5)

    allocation = decide_with(strategy, context, make_decision)

    assert dict(allocation.weights) == {"ETF_EU": 1.0}


def test_momentum_stands_aside_when_the_fund_is_falling(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    make_context: Callable[[MarketDataReader, datetime], SignalContext],
    make_decision: DecisionBuilder,
    xpar: TradingCalendar,
    prices: Callable[..., dict[date, float]],
    evening: Callable[[date], datetime],
    sessions: tuple[date, ...],
) -> None:
    """A falling series is a flat day, and the rule is written in the strategy."""
    falling = make_market({"ETF_EU": make_bars("ETF_EU", xpar, prices(200.0, -1.0))})
    context = make_context(falling, evening(sessions[-1]))
    strategy = MomentumSingleAsset(instrument_id="ETF_EU", lookback_sessions=5)

    allocation = decide_with(strategy, context, make_decision, universe=("ETF_EU",))

    assert dict(allocation.weights) == {}
    assert allocation.invested == 0.0


def test_momentum_stands_aside_when_it_cannot_be_computed(
    context: SignalContext, make_decision: DecisionBuilder
) -> None:
    """ETF_LATE has four sessions of history, and sixty were asked for."""
    strategy = MomentumSingleAsset(instrument_id="ETF_LATE", lookback_sessions=60)

    allocation = decide_with(strategy, context, make_decision, universe=("ETF_LATE",))

    assert allocation.invested == 0.0


def test_a_rotation_holds_the_best_ranked_fund(
    context: SignalContext, make_decision: DecisionBuilder
) -> None:
    """ETF_OTHER rises by three a session against ETF_EU's one."""
    strategy = MomentumRotation(lookback_sessions=5, top_n=1)

    allocation = decide_with(strategy, context, make_decision)

    assert allocation.selected == ("ETF_OTHER",)
    assert allocation.invested == pytest.approx(1.0)


def test_a_rotation_that_finds_one_name_holds_it_at_its_share(
    context: SignalContext, make_decision: DecisionBuilder
) -> None:
    """Not everything: a provider being late must not double a bet."""
    strategy = MomentumRotation(lookback_sessions=5, top_n=2)

    allocation = decide_with(
        strategy, context, make_decision, universe=("ETF_EU", "ETF_OTHER", "ETF_LATE")
    )

    assert "ETF_LATE" not in allocation.weights
    assert allocation.skipped["ETF_LATE"] is SignalStatus.INSUFFICIENT_HISTORY
    assert allocation.invested == pytest.approx(1.0)


def test_a_rotation_declares_the_ranking_it_reads() -> None:
    """Nobody can run it while forgetting a signal it needs."""
    declared = MomentumRotation(lookback_sessions=60, top_n=2).required_signals()

    assert [_id_of(item) for item in declared] == ["momentum_60d", "momentum_60d_rank"]


def gated_market(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    make_levels: Callable[..., pd.DataFrame],
    xpar: TradingCalendar,
    prices: Callable[..., dict[date, float]],
    sessions: tuple[date, ...],
    gauge: list[float],
) -> MarketDataReader:
    """Return two rising funds and a gauge whose last value the test decides."""
    return make_market(
        {
            "ETF_EU": make_bars("ETF_EU", xpar, prices(100.0, 1.0)),
            "ETF_OTHER": make_bars("ETF_OTHER", xpar, prices(200.0, 3.0)),
        },
        None,
        {"RATE_US": make_levels("RATE_US", dict(zip(sessions, gauge, strict=True)))},
    )


def test_a_quiet_gauge_lets_the_rotation_run(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    make_levels: Callable[..., pd.DataFrame],
    make_context: Callable[[MarketDataReader, datetime], SignalContext],
    make_decision: DecisionBuilder,
    xpar: TradingCalendar,
    prices: Callable[..., dict[date, float]],
    evening: Callable[[date], datetime],
    sessions: tuple[date, ...],
) -> None:
    """A gauge sitting on its own mean is a z-score of zero, and the gate is open."""
    market = gated_market(
        make_market, make_bars, make_levels, xpar, prices, sessions, [4.0] * 9 + [4.1]
    )
    context = make_context(market, evening(sessions[-1]))
    strategy = MomentumVix(
        gauge_id="RATE_US", lookback_sessions=5, gauge_observations=5, top_n=1, maximum=5.0
    )

    allocation = decide_with(strategy, context, make_decision)

    assert allocation.selected == ("ETF_OTHER",)


def test_a_loud_gauge_stands_the_book_down(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    make_levels: Callable[..., pd.DataFrame],
    make_context: Callable[[MarketDataReader, datetime], SignalContext],
    make_decision: DecisionBuilder,
    xpar: TradingCalendar,
    prices: Callable[..., dict[date, float]],
    evening: Callable[[date], datetime],
    sessions: tuple[date, ...],
) -> None:
    """The funds were rankable, and the strategy chose not to hold them.

    ``considered`` stays above zero, which is what tells a gated day from a day
    with nothing to choose from.
    """
    market = gated_market(
        make_market, make_bars, make_levels, xpar, prices, sessions, [4.0] * 9 + [9.0]
    )
    context = make_context(market, evening(sessions[-1]))
    strategy = MomentumVix(
        gauge_id="RATE_US", lookback_sessions=5, gauge_observations=5, top_n=1, maximum=1.0
    )

    allocation = decide_with(strategy, context, make_decision)

    assert allocation.selected == ()
    assert allocation.considered == 2


def test_the_gauge_is_never_held(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    make_levels: Callable[..., pd.DataFrame],
    make_context: Callable[[MarketDataReader, datetime], SignalContext],
    make_decision: DecisionBuilder,
    xpar: TradingCalendar,
    prices: Callable[..., dict[date, float]],
    evening: Callable[[date], datetime],
    sessions: tuple[date, ...],
) -> None:
    """It is read through a universe of its own and never reaches the book."""
    market = gated_market(
        make_market, make_bars, make_levels, xpar, prices, sessions, [4.0] * 9 + [4.1]
    )
    context = make_context(market, evening(sessions[-1]))
    strategy = MomentumVix(
        gauge_id="RATE_US", lookback_sessions=5, gauge_observations=5, top_n=2, maximum=5.0
    )

    allocation = decide_with(strategy, context, make_decision)

    assert "RATE_US" not in allocation.weights
    assert set(allocation.weights) <= set(UNIVERSE)


def test_what_a_strategy_does_with_an_unreadable_gauge_is_declared() -> None:
    """A risk filter that silently becomes no filter is only noticed afterwards."""
    with pytest.raises(ValueError, match="flat_when_unknown"):
        MomentumVix(flat_when_unknown="yes")  # type: ignore[arg-type]


def test_an_unreadable_gauge_can_be_declared_harmless(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    make_levels: Callable[..., pd.DataFrame],
    make_context: Callable[[MarketDataReader, datetime], SignalContext],
    make_decision: DecisionBuilder,
    xpar: TradingCalendar,
    prices: Callable[..., dict[date, float]],
    evening: Callable[[date], datetime],
    sessions: tuple[date, ...],
) -> None:
    """The other policy, taken deliberately rather than by omission.

    A risk filter that silently becomes no filter the day its input is late is
    only ever noticed afterwards, so both answers are written in the config.
    """
    market = gated_market(make_market, make_bars, make_levels, xpar, prices, sessions, [4.0] * 10)
    context = make_context(market, evening(sessions[-1]))
    # Sixty observations asked of a ten-session series: the gauge has no value.
    strategy = MomentumVix(
        gauge_id="RATE_US",
        lookback_sessions=5,
        gauge_observations=60,
        top_n=1,
        maximum=1.0,
        flat_when_unknown=False,
    )

    allocation = decide_with(strategy, context, make_decision)

    assert allocation.selected == ("ETF_OTHER",)


def test_an_unreadable_gauge_stands_the_book_down_by_default(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    make_levels: Callable[..., pd.DataFrame],
    make_context: Callable[[MarketDataReader, datetime], SignalContext],
    make_decision: DecisionBuilder,
    xpar: TradingCalendar,
    prices: Callable[..., dict[date, float]],
    evening: Callable[[date], datetime],
    sessions: tuple[date, ...],
) -> None:
    """And the names it stood aside from are still counted."""
    market = gated_market(make_market, make_bars, make_levels, xpar, prices, sessions, [4.0] * 10)
    context = make_context(market, evening(sessions[-1]))
    strategy = MomentumVix(
        gauge_id="RATE_US",
        lookback_sessions=5,
        gauge_observations=60,
        top_n=1,
        maximum=1.0,
        flat_when_unknown=True,
    )

    allocation = decide_with(strategy, context, make_decision)

    assert allocation.selected == ()
    assert allocation.considered == 2


def test_buy_and_hold_lets_the_weights_drift(
    context: SignalContext, make_decision: DecisionBuilder
) -> None:
    """The difference with the constant-weight baseline, and it is not cosmetic.

    Two funds bought at half each, one of which has doubled: buy and hold asks
    for the book it has - two thirds and one third - while the rebalanced
    version sells the winner to get back to half.
    """
    from quant_backtester.portfolio.targets import Holdings

    held = make_decision(
        context,
        snapshot_of(context, {"ETF_EU": 0.9, "ETF_OTHER": 0.4}),
        universe=UNIVERSE,
        holdings=Holdings(cash=0.0, quantities={"ETF_EU": 2.0, "ETF_OTHER": 1.0}),
        prices={"ETF_EU": 100.0, "ETF_OTHER": 100.0},
    )

    holding = BuyAndHold(instruments=UNIVERSE).decide(held)
    rebalanced = EqualWeightRebalance(instruments=UNIVERSE).decide(held)

    assert holding.weights["ETF_EU"] == pytest.approx(2 / 3)
    assert rebalanced.weights["ETF_EU"] == pytest.approx(0.5)


def test_buy_and_hold_buys_once_when_the_book_is_empty(
    context: SignalContext, make_decision: DecisionBuilder
) -> None:
    """Nothing is held on the first session of a run, so that is the purchase."""
    allocation = decide_with(BuyAndHold(instruments=UNIVERSE), context, make_decision)

    assert dict(allocation.weights) == {"ETF_EU": 0.5, "ETF_OTHER": 0.5}


def test_a_book_cannot_name_the_same_instrument_twice() -> None:
    """It would be given two shares of the capital under one position."""
    for strategy in (BuyAndHold, EqualWeightRebalance):
        with pytest.raises(ValueError, match="more than once"):
            strategy(instruments=("ETF_EU", "ETF_EU"))


@pytest.mark.parametrize("minimum", [float("nan"), float("inf"), True])
def test_a_momentum_threshold_that_is_not_a_number_is_refused(minimum: object) -> None:
    """NaN is invested whenever a number exists; an infinity is always cash."""
    with pytest.raises(ValueError, match="minimum"):
        MomentumSingleAsset(instrument_id="ETF_EU", minimum=minimum)  # type: ignore[arg-type]


def test_every_strategy_this_package_exports_can_be_run_as_it_stands(
    context: SignalContext, make_decision: DecisionBuilder
) -> None:
    """A strategy that needed its signals wired in from outside looks the same.

    It looks identical in an import list, and fails at the first decision with
    a ``KeyError`` on a signal nobody computed. So every exported strategy
    declares what it reads, and this is what says so.
    """
    import quant_backtester.strategies as package
    from quant_backtester.strategies.base import Strategy as Contract

    runnable = {
        BuyAndHold(instruments=UNIVERSE),
        EqualWeightRebalance(instruments=UNIVERSE),
        MomentumSingleAsset(instrument_id="ETF_EU", lookback_sessions=5),
        MomentumRotation(lookback_sessions=5, top_n=1),
        MomentumVix(gauge_id="RATE_US", lookback_sessions=5, gauge_observations=5),
    }
    exported = {
        name
        for name in package.__all__
        if isinstance(getattr(package, name), type)
        and issubclass(getattr(package, name), Contract)
        and getattr(package, name) is not Contract
        and name != "FunctionalStrategy"  # a form, not a strategy of its own
    }

    assert exported == {type(strategy).__name__ for strategy in runnable}
    for strategy in runnable:
        # Declared, not wired: every signal a decision reads comes from here.
        assert isinstance(strategy.required_signals(), tuple)
