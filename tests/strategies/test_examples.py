"""The strategies a user is meant to copy, and the decisions they encode.

Each of these is a few lines long, which is the point. What is tested is not
arithmetic - the layers underneath have their own tests for that - but the
decisions the examples take: what they hold, what they do when a number cannot
be computed, and what they refuse to touch.
"""

from __future__ import annotations

from collections.abc import Callable
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
from quant_backtester.strategies.examples import (
    BuyAndHold,
    MomentumRotation,
    MomentumSingleAsset,
    MomentumVix,
)

DecisionBuilder = Callable[..., StrategyContext]
"""Builds the context a strategy is handed; the fixture lives in conftest."""

UNIVERSE = ("ETF_EU", "ETF_OTHER")
"""Two tradable Paris funds, which is what makes a rotation a rotation."""


def decide_with(
    strategy: BuyAndHold | MomentumRotation | MomentumSingleAsset | MomentumVix,
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
