"""The strategies a user is meant to copy, and the decisions they encode.

Each of these is a few lines long, which is the point. What is tested is not
arithmetic - the layers underneath have their own tests for that - but the
decisions the examples take: what they hold, what they do when a number cannot
be computed, and what they refuse to touch.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date

import pytest

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.portfolio.state import PortfolioState
from quant_backtester.signals.base import Signal
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.engine import SignalEngine, SignalRequest
from quant_backtester.signals.types import SignalStatus
from quant_backtester.strategies.base import Strategy
from quant_backtester.strategies.examples import (
    BuyAndHold,
    EqualWeightRebalance,
)

DecisionBuilder = Callable[..., StrategyContext]
"""Builds the context a strategy is handed; the fixture lives in conftest."""

UNIVERSE = ("ETF_EU", "ETF_OTHER")
"""Two tradable Paris funds, which is what makes a rotation a rotation."""


def snapshot_of(context: SignalContext, values: dict[str, float]):
    """Return a snapshot holding one score per instrument."""
    from quant_backtester.signals.base import (
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


def test_buy_and_hold_lets_the_weights_drift(
    context: SignalContext,
    make_decision: DecisionBuilder,
    make_book: Callable[..., PortfolioState],
) -> None:
    """The difference with the constant-weight baseline, and it is not cosmetic.

    Two funds bought at half each, one of which has doubled: buy and hold asks
    for the book it has - two thirds and one third - while the rebalanced
    version sells the winner to get back to half.
    """
    held = make_decision(
        context,
        snapshot_of(context, {"ETF_EU": 0.9, "ETF_OTHER": 0.4}),
        universe=UNIVERSE,
        holdings=make_book(0.0, {"ETF_EU": 2.0, "ETF_OTHER": 1.0}),
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


def test_every_strategy_this_package_exports_can_be_run_as_it_stands(
    context: SignalContext, make_decision: DecisionBuilder
) -> None:
    """A strategy that needed its signals wired in from outside looks the same.

    It looks identical in an import list, and fails at the first decision with
    a ``KeyError`` on a signal nobody computed. So every exported strategy
    declares what it reads, and this is what says so.
    """
    import quant_backtester.strategies as package
    from quant_backtester.strategies import (
        ArimaGarch,
        BufferedDualMomentum,
        ETFEnsemble,
        EwmaVolControl,
        FactorETFBlend,
        FixedWeights,
        GarchVolControl,
        MonetaryCarry,
        RealizedVolControl,
        RelativeResidualTilt,
        SmoothMovingAverage,
        TrendFilteredPullback,
        VixReliefEntry,
        WorldMA20Benchmark,
    )
    from quant_backtester.strategies.base import Strategy as Contract

    runnable = {
        BuyAndHold(instruments=UNIVERSE),
        EqualWeightRebalance(instruments=UNIVERSE),
        WorldMA20Benchmark(instrument_id="ETF_EU"),
        BufferedDualMomentum(first_id="ETF_EU", second_id="ETF_OTHER"),
        SmoothMovingAverage(instrument_id="ETF_EU"),
        TrendFilteredPullback(instrument_id="ETF_EU"),
        RelativeResidualTilt(first_id="ETF_EU", second_id="ETF_OTHER"),
        RealizedVolControl(instrument_id="ETF_EU"),
        GarchVolControl(instrument_id="ETF_EU"),
        ArimaGarch(instrument_id="ETF_EU"),
        EwmaVolControl(instrument_id="ETF_EU"),
        FixedWeights(weights=(("ETF_EU", 0.6),)),
        FactorETFBlend(instrument_ids=("ETF_EU", "ETF_OTHER", "ETF_LATE")),
        MonetaryCarry(instrument_id="ETF_LATE"),
        VixReliefEntry(instrument_id="ETF_OTHER", vix_id="RATE_US"),
        ETFEnsemble(
            enable_factors=False,
            enable_monetary=False,
            world_id="ETF_EU",
            sp500_id="ETF_OTHER",
            vix_id="RATE_US",
        ),
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


def test_buy_and_hold_completes_its_basket_and_keeps_what_it_has(
    context: SignalContext,
    make_decision: DecisionBuilder,
    make_book: Callable[..., PortfolioState],
) -> None:
    """Audit A07: holding one name of two used to switch to holding for good.

    Half the book went into ETF_EU; ETF_OTHER had no opening price. The next
    decision keeps ETF_EU as it is and puts the cash left into ETF_OTHER.
    """
    half = make_decision(
        context,
        snapshot_of(context, {"ETF_EU": 0.0, "ETF_OTHER": 0.0}),
        universe=UNIVERSE,
        holdings=make_book(5_000.0, {"ETF_EU": 50.0}),
        prices={"ETF_EU": 100.0},
    )

    allocation = BuyAndHold(instruments=UNIVERSE).decide(half)

    assert allocation.kept == frozenset({"ETF_EU"})
    assert not allocation.hold_positions
    assert dict(allocation.weights) == pytest.approx({"ETF_EU": 0.5, "ETF_OTHER": 0.5})


def test_buy_and_hold_splits_the_cash_among_every_missing_name(
    context: SignalContext,
    make_decision: DecisionBuilder,
    make_book: Callable[..., PortfolioState],
) -> None:
    three = ("ETF_EU", "ETF_OTHER", "ETF_LATE")
    decision = make_decision(
        context,
        snapshot_of(context, dict.fromkeys(three, 0.0)),
        universe=three,
        holdings=make_book(6_000.0, {"ETF_EU": 40.0}),
        prices={"ETF_EU": 100.0},
    )

    allocation = BuyAndHold(instruments=three).decide(decision)

    assert dict(allocation.weights) == pytest.approx(
        {"ETF_EU": 0.4, "ETF_OTHER": 0.3, "ETF_LATE": 0.3}
    )


def test_a_kept_line_is_not_bought_again(
    context: SignalContext,
    make_decision: DecisionBuilder,
    make_book: Callable[..., PortfolioState],
) -> None:
    held = make_decision(
        context,
        snapshot_of(context, {"ETF_EU": 0.0, "ETF_OTHER": 0.0}),
        universe=UNIVERSE,
        holdings=make_book(5_000.0, {"ETF_EU": 50.0}),
        prices={"ETF_EU": 100.0},
    )

    with pytest.raises(ValueError, match="held already"):
        held.keep_and_buy({"ETF_EU": 0.1})
