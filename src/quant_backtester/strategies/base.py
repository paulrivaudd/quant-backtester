"""The contract a strategy answers, and what identifies one.

A strategy is three things and no more: a name it keeps, the signals it needs,
and a decision taken at an instant it did not choose. Everything else - reading
the store, dating a session, adjusting for a corporate action, sizing an order,
charging the spread - belongs to the layers below and is deliberately invisible
here.

The name is not decoration. A result carries it, a comparison prints it and a
fingerprint pins the configuration that produced it, so that "Sharpe 1.4" can
be traced back to the exact parameters it came from. A strategy whose
parameters live in module constants cannot be recorded that way, which is why
the recommended form is a frozen dataclass whose fields *are* the parameters.

A strategy holds no mutable state between decisions. Anything path-dependent -
what is held, what it is worth, how the market has moved - comes from the
context, which is the only thing that knows which day it is. The engine checks
that the declared definition did not change during a run; it cannot check that
nothing else did - a closure, a global, a file - so that part of the contract
rests on the author (audit A14).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from datetime import date
from enum import Enum

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.signals.base import Signal
from quant_backtester.signals.engine import SignalRequest
from quant_backtester.signals.types import require_identifier


class Strategy(ABC):
    """What a strategy is, from the engine's point of view.

    Attributes
    ----------
    strategy_id : str
        Stable name of this strategy, e.g. ``"momentum_rotation_60d"``. It
        goes into results, reports and comparisons, so it is a name rather
        than a description, and it does not change when a parameter does -
        that is what the fingerprint is for.

    Notes
    -----
    Declared as an annotation rather than an abstract property: a strategy is
    usually a frozen dataclass, and a property here would become a field's
    default value.
    """

    strategy_id: str

    def required_signals(self) -> Sequence[Signal | SignalRequest]:
        """Return the signals this strategy needs computed for every decision.

        Returns
        -------
        Sequence[Signal | SignalRequest]
            In the order they are to be computed. A bare signal is computed
            over the session's trading universe; a
            :class:`~quant_backtester.signals.engine.SignalRequest` carries a
            universe of its own, which is how a gauge that is never traded
            reaches the same snapshot as the funds it gates.

        Notes
        -----
        Declared by the strategy rather than passed beside it, so that nobody
        can run a strategy while forgetting a signal it reads - which produces
        a ``KeyError`` deep in a decision at best, and a different backtest at
        worst.
        """
        return ()

    @abstractmethod
    def decide(self, ctx: StrategyContext) -> TargetAllocation:
        """Return what to hold, given one decision instant.

        Parameters
        ----------
        ctx : StrategyContext
            The signals, the market, the book and this session's universe, all
            fixed at the same instant.

        Returns
        -------
        TargetAllocation
            Built through the context's helpers - ``ctx.weights``,
            ``ctx.equal_weight``, ``ctx.cash``, ``ctx.hold_positions`` - which
            check that the decision is one this book could actually hold.
        """

    def parameters(self) -> Mapping[str, object]:
        """Return the parameters that make this instance what it is.

        Returns
        -------
        Mapping[str, object]
            The dataclass fields of the strategy, JSON-serialisable, for a
            strategy written as one; empty otherwise. Override it for a
            strategy that carries its configuration some other way - what is
            not returned here is not recorded, and a result nobody can
            reproduce the configuration of is not a result.

        Raises
        ------
        ValueError
            If a field cannot be written down as built-ins.
        """
        if not dataclasses.is_dataclass(self):
            return {}
        return {
            field.name: _plain(getattr(self, field.name), field.name)
            for field in dataclasses.fields(self)
            if field.repr
        }

    def definition(self) -> Mapping[str, object]:
        """Return everything that identifies this strategy, serialisable.

        Returns
        -------
        Mapping[str, object]
            The name, the class it is written as - module included - its
            parameters and the definition of every signal it declares. Two
            strategies with equal definitions decide the same way on the same
            data.
        """
        return {
            "strategy_id": self.strategy_id,
            # Fully qualified: two classes of one name, in two modules, with
            # the same parameters would otherwise be one experiment.
            "class": f"{type(self).__module__}.{type(self).__qualname__}",
            "parameters": dict(self.parameters()),
            "signals": [_signal_definition(item) for item in self.required_signals()],
        }

    def fingerprint(self) -> str:
        """Return a stable hash of this strategy's definition.

        Returns
        -------
        str
            SHA-256 of the definition rendered as canonical JSON. Two runs
            whose strategies share a fingerprint were asked the same question;
            the project's commit is what identifies the code that answered it.
        """
        canonical = json.dumps(self.definition(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def validate(self) -> None:
        """Raise unless this strategy can be run.

        Raises
        ------
        ValueError
            If the name is empty, or two declared signals share an id - one
            would hide the other, and the strategy would read whichever the
            engine computed last.
        """
        require_identifier(self.strategy_id, "strategy_id")
        seen: set[str] = set()
        for item in self.required_signals():
            signal = item.signal if isinstance(item, SignalRequest) else item
            if signal.signal_id in seen:
                raise ValueError(
                    f"{self.strategy_id} declares the signal {signal.signal_id!r} twice; "
                    "one would hide the other"
                )
            seen.add(signal.signal_id)


def _signal_definition(item: Signal | SignalRequest) -> Mapping[str, object]:
    """Return one declared signal's definition, its own universe included.

    Parameters
    ----------
    item : Signal | SignalRequest
        A declared signal, with or without a universe of its own.

    Returns
    -------
    Mapping[str, object]
        The signal's definition and what it is computed for. A request
        describes itself - including a universe that answers by session - so
        that nothing here has to reach into the data layer to find out what a
        strategy was run over.
    """
    if isinstance(item, SignalRequest):
        return item.definition()
    return {"signal": item.definition_json(), "instruments": None}


def _plain(value: object, name: str = "a parameter") -> object:
    """Return a value JSON can render, for the parameters of a strategy.

    Parameters
    ----------
    value : object
        A parameter, or one of its parts.
    name : str
        What it is called, quoted in the message.

    Returns
    -------
    object
        Built-ins all the way down: scalars unchanged, mappings and sequences
        rebuilt, an enum spelled by its value like everywhere else here.

    Raises
    ------
    ValueError
        If the value is of a kind this cannot render. It used to fall back to
        ``repr``, which is the worst of both: an object whose representation
        carries its address changes the fingerprint between two identical runs,
        and two different objects with one representation share it. Refusing
        says which parameter needs a serialisable form.
    """
    if isinstance(value, str | int | float | bool | type(None)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _plain(item, f"{name}[{key!r}]") for key, item in value.items()}
    if isinstance(value, Enum):  # spelled by its value, like everywhere else here
        return _plain(value.value, name)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Sequence):
        return [_plain(item, name) for item in value]
    raise ValueError(
        f"{name} is a {type(value).__name__}, which cannot be written down: a "
        "definition nobody can serialise is a run nobody can reproduce. Give the "
        "strategy a parameter made of numbers, strings, enums or collections of "
        "those, or override parameters() to say how this one is recorded."
    )
