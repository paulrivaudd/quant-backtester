"""Writing a strategy as a function, without losing what a run records."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.signals.base import Signal
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.engine import SignalEngine, SignalRequest
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


def _id_of(item: Signal | SignalRequest) -> str:
    """Return the id of a declared signal, whether or not it carries a universe."""
    return item.signal.signal_id if isinstance(item, SignalRequest) else item.signal_id


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
    declared = world_or_cash.required_signals()

    assert [_id_of(item) for item in declared] == ["return_2d"]


def test_its_parameters_are_recorded() -> None:
    """A function closing over a threshold has a parameter, and a run says which."""
    recorded = world_or_cash.parameters()

    assert recorded["floor"] == 0.0
    assert world_or_cash.definition()["parameters"]["floor"] == 0.0  # type: ignore[index]


def test_the_decision_function_is_part_of_the_identity() -> None:
    """Two functions deciding opposite things must not be filed as one experiment.

    Same name, same parameters, same signals: before the function itself was
    recorded, these two had the same fingerprint and a result could not say
    which of them produced it.
    """

    def hold(ctx: StrategyContext) -> TargetAllocation:
        return ctx.weights({"ETF_EU": 1.0})

    def stand_aside(ctx: StrategyContext) -> TargetAllocation:
        return ctx.cash()

    first = FunctionalStrategy(strategy_id="same", decision=hold)
    second = FunctionalStrategy(strategy_id="same", decision=stand_aside)

    assert first.fingerprint() != second.fingerprint()
    assert "hold" in str(first.parameters()["decision"])


def test_mutating_the_caller_s_parameters_does_not_change_the_strategy() -> None:
    """Frozen has to mean frozen, or a run records a configuration it did not use."""
    given = {"threshold": 1.5}
    strategy = FunctionalStrategy(
        strategy_id="threshold", decision=world_or_cash.decision, parameter_values=given
    )
    before = strategy.fingerprint()

    given["threshold"] = 3.0

    assert strategy.fingerprint() == before
    assert strategy.parameters()["threshold"] == 1.5


def test_the_parameters_of_a_strategy_are_read_only() -> None:
    """Including the nested ones: the definition is what a fingerprint is taken of."""
    strategy = FunctionalStrategy(
        strategy_id="nested",
        decision=world_or_cash.decision,
        parameter_values={"bounds": {"low": 0.0}},
    )

    with pytest.raises(TypeError):
        strategy.parameter_values["bounds"] = {}  # type: ignore[index]
    with pytest.raises(TypeError):
        strategy.parameter_values["bounds"]["low"] = 1.0  # type: ignore[index]


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
