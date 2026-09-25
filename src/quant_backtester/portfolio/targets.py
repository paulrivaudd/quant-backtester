"""What a decision asks for, stated in fractions of capital.

A target is an intention. What is actually held is a different object - see
:mod:`quant_backtester.portfolio.state` - and the line between them is the
whole point of this layer: turning one into the other needs a price, and a
price belongs to an instant, which is why nothing here converts them and why
the conversion happens at the execution instant rather than at the decision
one.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Final

from quant_backtester.numbers import require_unit_fraction
from quant_backtester.signals.types import (
    SignalStatus,
    require_identifier,
    require_non_negative_int,
)

WEIGHT_SUM_TOLERANCE: Final[float] = 1e-9
"""How far above one a sum of weights may be and still mean "the whole book".

Floating-point dust, not a margin: ``0.7 + 0.2 + 0.1`` is ``0.9999999999999999``
and other sums land an ulp above one. A tolerance of a billionth of the book is
a thousand times larger than that dust and a million times smaller than any
weight a strategy means, so it forgives arithmetic and nothing else.
"""


@dataclass(frozen=True, slots=True)
class TargetAllocation:
    """What a strategy wants to hold at one decision instant.

    Attributes
    ----------
    as_of : datetime
        The decision this allocation answers. The same instant as the snapshot
        it was read from, so an allocation cannot be mistaken for another day's.
    weights : Mapping[str, float]
        Fraction of capital per instrument. It may sum to less than one: what
        is not allocated is cash, and cash needs no line of its own.
    selected : tuple[str, ...]
        The instruments held, best first. Left empty, it is the instruments
        of ``weights`` in id order - a list of weights carries no ranking, and
        inventing one from the order a mapping was written in would make two
        identical decisions record differently.
    considered : int
        How many instruments had a usable signal to be chosen among. A
        selection of two out of nine and a selection of two out of two are not
        the same decision, and only this number tells them apart. Left at
        zero with a non-empty selection - which could not otherwise be true -
        it is the size of the selection.
    skipped : Mapping[str, SignalStatus]
        Why each instrument of the universe was not eligible. Not listed yet,
        no history yet, a session missing, a value too old: a strategy that
        holds nothing today should be able to say which of those it was.
    hold_positions : bool
        Whether the decision is to keep every position exactly as it is and
        send no order. The weights are then the book's own, as it was valued
        at the decision - recorded as the target the decision stands for, and
        checked to be exactly that by the engine. A risk limit still overrules
        it: a held book that breaches a limit is traded down to the limit, like
        any other target.

    Raises
    ------
    ValueError
        If the decision is not one a portfolio could hold: a weight that is
        not a finite fraction of ``[0, 1]``, weights adding up to more than
        the whole book, a selection that does not match the weights, a count
        of instruments considered below the number chosen, a reason that is
        not a :class:`SignalStatus`, or a naive ``as_of``.

    Notes
    -----
    A weight below zero is a short position. Nothing in this project lends a
    security, charges a borrow or models a margin call, so a backtest holding
    one would report a return nobody could have had - and a forecast score is
    negative for half the universe by construction, so the mistake is one
    keystroke away. The refusal is here rather than in the portfolio limits
    because an allocation that cannot be held should not be constructible at
    all. The same goes for a sum above one, which is leverage: nothing here
    finances it either.

    Keeping a book and restating its weights are not the same decision. The
    weights of the close are not the weights of the next open - two funds move
    apart overnight - so a target of "the weights I have" trades the drift
    every morning, and only a minimum trade value would hide it. A target that
    holds its positions sends no order at all.

    How much of the book a *risk limit* lets through is a different question,
    and it belongs to :class:`~quant_backtester.portfolio.limits.PortfolioLimits`:
    what this class refuses is an allocation that is not a fraction of a book
    at all, and what the limits do is cut a legitimate one down to policy.

    Every sum here is ``math.fsum``, which is exact and therefore does not
    depend on the order the weights were written in.
    """

    as_of: datetime
    weights: Mapping[str, float]
    selected: tuple[str, ...] = ()
    considered: int = 0
    skipped: Mapping[str, SignalStatus] = field(default_factory=lambda: MappingProxyType({}))
    hold_positions: bool = False

    def __post_init__(self) -> None:
        """Check the decision is one a portfolio could hold, then freeze it."""
        if not isinstance(self.as_of, datetime) or self.as_of.tzinfo is None:
            raise ValueError(f"as_of must be a timezone-aware datetime, got {self.as_of!r}")
        if not isinstance(self.hold_positions, bool):
            raise ValueError(
                f"hold_positions must be said as a boolean, got {self.hold_positions!r}"
            )
        weights = dict(self.weights)
        for name, weight in weights.items():
            require_identifier(name, "an instrument of weights")
            require_unit_fraction(weight, f"the weight of {name}")
        total = math.fsum(weights.values())
        if total > 1.0 + WEIGHT_SUM_TOLERANCE:
            raise ValueError(
                f"the weights add up to {total}: more than the whole book is leverage, "
                "and nothing here finances it"
            )
        selected = tuple(self.selected) if self.selected else tuple(sorted(weights))
        for name in selected:
            require_identifier(name, "a selected instrument")
        if len(set(selected)) != len(selected):
            raise ValueError(f"an instrument is selected twice: {selected}")
        if set(selected) != set(weights):
            raise ValueError(
                f"selected {sorted(selected)} and weights {sorted(weights)} "
                "describe two different books"
            )
        require_non_negative_int(self.considered, "considered")
        considered = self.considered if self.considered or not selected else len(selected)
        if considered < len(selected):
            raise ValueError(
                f"{len(selected)} instrument(s) were selected among {considered} considered"
            )
        skipped = dict(self.skipped)
        for name, status in skipped.items():
            require_identifier(name, "an instrument of skipped")
            if not isinstance(status, SignalStatus):
                raise ValueError(f"{name} was skipped for {status!r}, which is not a SignalStatus")
        both = sorted(set(skipped) & set(selected))
        if both:
            raise ValueError(f"{', '.join(both)} is both selected and skipped")
        object.__setattr__(self, "weights", MappingProxyType(weights))
        object.__setattr__(self, "selected", selected)
        object.__setattr__(self, "considered", considered)
        object.__setattr__(self, "skipped", MappingProxyType(skipped))

    @property
    def invested(self) -> float:
        """Return the fraction of capital this allocation puts to work."""
        return math.fsum(self.weights.values())

    @property
    def gross(self) -> float:
        """Return the gross exposure, the sum of the absolute weights.

        Returns
        -------
        float
            ``sum |w|``. Equal to :attr:`invested` for as long as the project
            is long-only, and the definition that stays right the day it is not:
            a long and a short of the same size are a gross of two, not zero.
        """
        return math.fsum(abs(weight) for weight in self.weights.values())

    @property
    def cash(self) -> float:
        """Return the fraction of capital this allocation leaves in cash."""
        return max(0.0, 1.0 - self.invested)
