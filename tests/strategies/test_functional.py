"""Writing a strategy as a function, without losing what a run records."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.engine import SignalEngine
from quant_backtester.signals.price.returns import ReturnSignal
from quant_backtester.signals.types import PriceBasis
from quant_backtester.strategies.functional import FunctionalStrategy, strategy

DecisionBuilder = Callable[..., StrategyContext]
"""Builds the context a strategy is handed; the fixture lives in conftest."""


def a_return() -> ReturnSignal:
    """Return one cheap signal, so a test about the form is about the form."""
    return ReturnSignal(signal_id="return_2d", lookback_sessions=2, price_basis=PriceBasis.RAW)


@strategy(strategy_id="world_or_cash", signals=(a_return(),), floor=0.0)
def world_or_cash(ctx: StrategyContext) -> TargetAllocation:
    """Hold the fund while its two-session return is positive."""
    value = ctx.signal_value_or_none("return_2d", "ETF_EU")
    if value is None or value <= 0.0:
        return ctx.cash()
    return ctx.weights({"ETF_EU": 1.0})


def decision_of(context: SignalContext, make_decision: DecisionBuilder) -> StrategyContext:
    """Return a decision over the rising synthetic fund."""
    snapshot = SignalEngine().compute(context, [a_return()], ["ETF_EU"])
    return make_decision(context, snapshot, universe=("ETF_EU",))


def test_a_decorated_function_is_a_strategy() -> None:
    """The same contract, reached with less ceremony."""
    assert isinstance(world_or_cash, FunctionalStrategy)
    assert world_or_cash.strategy_id == "world_or_cash"


def test_it_decides_like_any_other_strategy(
    context: SignalContext, make_decision: DecisionBuilder
) -> None:
    """The prices rise, so the fund is held."""
    allocation = world_or_cash.decide(decision_of(context, make_decision))

    assert dict(allocation.weights) == {"ETF_EU": 1.0}


def test_it_declares_its_signals_like_any_other(
    context: SignalContext, make_decision: DecisionBuilder
) -> None:
    """Nobody can run it while forgetting the signal it reads."""
    assert [item.signal_id for item in world_or_cash.required_signals()] == ["return_2d"]


def test_its_parameters_are_recorded() -> None:
    """A function closing over a threshold has a parameter, and a run says which."""
    assert world_or_cash.parameters() == {"floor": 0.0}
    assert world_or_cash.definition()["parameters"] == {"floor": 0.0}


def test_two_configurations_have_two_fingerprints() -> None:
    """The point of recording them: telling two experiments apart."""
    other = FunctionalStrategy(
        strategy_id="world_or_cash",
        decision=world_or_cash.decision,
        signals=(a_return(),),
        parameter_values={"floor": 0.01},
    )

    assert other.fingerprint() != world_or_cash.fingerprint()


def test_the_same_configuration_fingerprints_the_same() -> None:
    """Two runs of one experiment must be recognisable as one experiment."""
    same = FunctionalStrategy(
        strategy_id="world_or_cash",
        decision=world_or_cash.decision,
        signals=(a_return(),),
        parameter_values={"floor": 0.0},
    )

    assert same.fingerprint() == world_or_cash.fingerprint()


def test_a_strategy_with_no_name_is_refused() -> None:
    """A result nobody can name is a result nobody can compare."""
    with pytest.raises(ValueError, match="strategy_id"):
        FunctionalStrategy(strategy_id="  ", decision=world_or_cash.decision)


def test_two_signals_sharing_an_id_are_refused() -> None:
    """One would hide the other, and the strategy would read whichever came last."""
    with pytest.raises(ValueError, match="twice"):
        FunctionalStrategy(
            strategy_id="twice",
            decision=world_or_cash.decision,
            signals=(a_return(), a_return()),
        )
