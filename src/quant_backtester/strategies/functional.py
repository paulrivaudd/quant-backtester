"""Writing a strategy as a function, for the length of a notebook session.

A class is the right form for a strategy that is kept: it has a name, its
parameters are fields, and both end up in the record of every run. For trying
an idea out, that ceremony is noise - so the same contract is available as a
decorated function, and the adapter under it is an ordinary strategy.

What the decorator does not do is make the declaration optional. The name and
the signals are still given, because a run whose configuration is not recorded
is a number nobody can reproduce, whether it came from a class or from four
lines in a notebook.

The decision function is part of that identity. Two functions that decide
opposite things, declared under one name with one set of parameters, must not
fingerprint the same - so the module and qualified name of the function go into
the definition. It is not a hash of the code, and it does not pretend to be:
editing a function in place keeps the fingerprint, which is what the recorded
commit is for. What it does is stop two *different* functions from being filed
as one experiment.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.signals.base import Signal, freeze
from quant_backtester.signals.engine import SignalRequest
from quant_backtester.strategies.base import Strategy

Decision = Callable[[StrategyContext], TargetAllocation]
"""What a decorated function is: one decision, taken at one instant."""


@dataclass(frozen=True, slots=True)
class FunctionalStrategy(Strategy):
    """A strategy whose decision is a plain function.

    Attributes
    ----------
    strategy_id : str
        Stable name, recorded like any other strategy's.
    decision : Decision
        The function called at each decision instant.
    signals : tuple[Signal | SignalRequest, ...]
        What it needs computed.
    parameter_values : Mapping[str, object]
        Anything else that identifies this configuration, recorded in the
        definition. A function closing over a threshold has a parameter, and a
        result that does not say which one cannot be reproduced. Frozen all the
        way down at construction: the caller keeps its own dictionary and may
        do as it likes with it, and this strategy no longer changes.

    Notes
    -----
    Frozen, like every strategy: the function is called once per session and
    must not accumulate anything between calls. What is path-dependent comes
    from the context, which is the only thing that knows which day it is.

    ``frozen=True`` on its own only stops the fields being reassigned. A
    mapping passed in stays the caller's object, so mutating it afterwards
    moved this strategy's fingerprint - the configuration a run started with
    and the one it recorded could differ. Freezing a copy is what makes the
    word mean what it says.
    """

    strategy_id: str
    decision: Decision
    signals: tuple[Signal | SignalRequest, ...] = ()
    parameter_values: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Freeze the parameters, then reject a strategy that cannot be run."""
        frozen = freeze(dict(self.parameter_values))
        assert isinstance(frozen, Mapping)
        object.__setattr__(self, "parameter_values", frozen)
        object.__setattr__(self, "signals", tuple(self.signals))
        self.validate()

    def required_signals(self) -> Sequence[Signal | SignalRequest]:
        """Return the signals the decorated function declared."""
        return self.signals

    def parameters(self) -> Mapping[str, object]:
        """Return what identifies this configuration, as declared.

        Returns
        -------
        Mapping[str, object]
            The declared parameters, and the decision function's module and
            qualified name. Without the second, two functions deciding opposite
            things under one name and one threshold would share a fingerprint
            and be filed as the same experiment.
        """
        return {
            **dict(self.parameter_values),
            "decision": f"{self.decision.__module__}.{self.decision.__qualname__}",
        }

    def decide(self, ctx: StrategyContext) -> TargetAllocation:
        """Return what the decorated function decides at this instant."""
        return self.decision(ctx)


def strategy(
    strategy_id: str,
    signals: Sequence[Signal | SignalRequest] = (),
    **parameters: object,
) -> Callable[[Decision], FunctionalStrategy]:
    """Turn a decision function into a strategy.

    Parameters
    ----------
    strategy_id : str
        Stable name of the strategy.
    signals : Sequence[Signal | SignalRequest]
        What it needs computed at every decision.
    **parameters : object
        Anything else worth recording about this configuration - a threshold
        the function closes over, a count it holds.

    Returns
    -------
    Callable[[Decision], FunctionalStrategy]
        The decorator, which returns a strategy rather than a function.

    Examples
    --------
    >>> from quant_backtester.strategies.functional import strategy
    >>> @strategy(strategy_id="world_or_cash", floor=0.0)
    ... def world_or_cash(ctx):
    ...     if ctx.market.value("ETF_WORLD").require() > 0:
    ...         return ctx.weights({"ETF_WORLD": 1.0})
    ...     return ctx.cash()
    >>> world_or_cash.strategy_id
    'world_or_cash'
    """

    def decorate(decision: Decision) -> FunctionalStrategy:
        return FunctionalStrategy(
            strategy_id=strategy_id,
            decision=decision,
            signals=tuple(signals),
            parameter_values=dict(parameters),
        )

    return decorate
