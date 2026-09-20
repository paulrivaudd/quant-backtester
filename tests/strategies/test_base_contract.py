"""What identifies a strategy, and what a definition refuses to invent."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.data.universes import Membership, StaticUniverse, Universe
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.signals.engine import SignalRequest
from quant_backtester.signals.price.returns import ReturnSignal
from quant_backtester.signals.types import PriceBasis
from quant_backtester.strategies.base import Strategy


def a_return(signal_id: str = "r") -> ReturnSignal:
    """Return one cheap signal, so a test about identity is about identity."""
    return ReturnSignal(signal_id=signal_id, lookback_sessions=2, price_basis=PriceBasis.RAW)


@dataclass(frozen=True, slots=True)
class Gauged(Strategy):
    """A strategy reading one signal over a universe the test chooses."""

    universe: object
    strategy_id: str = "gauged"

    def required_signals(self) -> tuple[SignalRequest, ...]:
        """Return one request over the given universe."""
        return (SignalRequest(a_return(), self.universe),)  # type: ignore[arg-type]

    def parameters(self) -> dict[str, object]:
        """Return nothing: the universe is recorded through the request."""
        return {}

    def decide(self, ctx: StrategyContext) -> TargetAllocation:
        """Hold nothing; this strategy exists to be fingerprinted."""
        return ctx.cash()


def test_two_static_universes_are_two_experiments() -> None:
    """Recording only the class name filed them as one."""
    first = Gauged(universe=StaticUniverse(("ETF_A", "ETF_B")))
    second = Gauged(universe=StaticUniverse(("ETF_X", "ETF_Y")))

    assert first.fingerprint() != second.fingerprint()


def test_a_dated_universe_is_recorded_by_what_identifies_it() -> None:
    """Its id and its memberships - never the names it happens to hold today.

    A dated universe answers a different list on every session, which is the
    whole point of dating it, so the list is not what identifies it.
    """
    universe = Universe(
        universe_id="GAUGES",
        name="Two gauges, one of which left",
        memberships=(Membership("A"), Membership("B", until_date=date(2026, 9, 10))),
    )

    recorded = Gauged(universe=universe).definition()["signals"][0]["instruments"]  # type: ignore[index]

    assert recorded["type"] == "Universe"  # type: ignore[index]
    assert recorded["id"] == "GAUGES"  # type: ignore[index]
    assert recorded["memberships"][1]["until"] == "2026-09-10"  # type: ignore[index]


def test_two_dated_universes_are_two_experiments() -> None:
    """Two baskets of gauges are not one because they share a class."""
    first = Gauged(universe=Universe(universe_id="ONE", name="one", memberships=(Membership("A"),)))
    second = Gauged(
        universe=Universe(universe_id="TWO", name="two", memberships=(Membership("B"),))
    )

    assert first.fingerprint() != second.fingerprint()


def test_a_class_is_recorded_with_its_module() -> None:
    """Two classes of one name in two modules are not one experiment."""
    recorded = Gauged(universe=["A"]).definition()["class"]

    assert recorded == f"{Gauged.__module__}.Gauged"


def test_a_parameter_nobody_could_write_down_is_refused() -> None:
    """It used to become a ``repr``, which is the worst of both.

    An object whose representation carries its address changes the fingerprint
    between two identical runs; two different objects with one representation
    share it. Refusing says which parameter needs a serialisable form.
    """

    @dataclass(frozen=True, slots=True)
    class Opaque(Strategy):
        thing: object
        strategy_id: str = "opaque"

        def decide(self, ctx: StrategyContext) -> TargetAllocation:
            return ctx.cash()

    with pytest.raises(ValueError, match="thing is a object"):
        Opaque(thing=object()).definition()


def test_a_strategy_declaring_one_signal_twice_is_refused() -> None:
    """One would hide the other, and it would read whichever came last."""

    @dataclass(frozen=True, slots=True)
    class Twice(Strategy):
        strategy_id: str = "twice"

        def required_signals(self) -> tuple[ReturnSignal, ReturnSignal]:
            return (a_return(), a_return())

        def decide(self, ctx: StrategyContext) -> TargetAllocation:
            return ctx.cash()

    with pytest.raises(ValueError, match="twice"):
        Twice().validate()
