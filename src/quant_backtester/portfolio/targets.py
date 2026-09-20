"""What a decision asks for, and what is actually held.

Two small records, and the line between them is the whole point of this layer.
A target is an intention expressed in fractions of capital; holdings are
quantities that exist. Turning one into the other needs a price, and a price
belongs to an instant - which is why nothing here converts them, and why the
conversion happens at the execution instant rather than at the decision one.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

from quant_backtester.numbers import (
    require_finite,
    require_finite_non_negative,
    require_unit_fraction,
)
from quant_backtester.signals.types import (
    SignalStatus,
    require_identifier,
    require_non_negative_int,
)


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
        is not allocated is not invested.
    selected : tuple[str, ...]
        The instruments held, best first.
    considered : int
        How many instruments had a usable signal to be chosen among. A
        selection of two out of nine and a selection of two out of two are not
        the same decision, and only this number tells them apart.
    skipped : Mapping[str, SignalStatus]
        Why each instrument of the universe was not eligible. Not listed yet,
        no history yet, a session missing, a value too old: a strategy that
        holds nothing today should be able to say which of those it was.

    Raises
    ------
    ValueError
        If the decision is not one a portfolio could hold: a weight that is
        not a finite fraction of ``[0, 1]``, a selection that does not match
        the weights, a count of instruments considered below the number
        chosen, a reason that is not a :class:`SignalStatus`, or a naive
        ``as_of``.

    Notes
    -----
    A weight below zero is a short position. Nothing in this project lends a
    security, charges a borrow or models a margin call, so a backtest holding
    one would report a return nobody could have had - and a forecast score is
    negative for half the universe by construction, so the mistake is one
    keystroke away. The refusal is here rather than in the portfolio limits
    because an allocation that cannot be held should not be constructible at
    all.

    How *much* of the book may be put to work is a different question, and it
    belongs to :class:`~quant_backtester.portfolio.limits.PositionLimits`: a
    strategy may express an intention that adds to more than one, and the
    limits scale it down to what is allowed. What this class refuses is a
    weight that is not a fraction at all.
    """

    as_of: datetime
    weights: Mapping[str, float]
    selected: tuple[str, ...]
    considered: int
    skipped: Mapping[str, SignalStatus]

    def __post_init__(self) -> None:
        """Check the decision is one a portfolio could hold, then freeze it."""
        if not isinstance(self.as_of, datetime) or self.as_of.tzinfo is None:
            raise ValueError(f"as_of must be a timezone-aware datetime, got {self.as_of!r}")
        weights = dict(self.weights)
        for name, weight in weights.items():
            require_identifier(name, "an instrument of weights")
            require_unit_fraction(weight, f"the weight of {name}")
        selected = tuple(self.selected)
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
        if self.considered < len(selected):
            raise ValueError(
                f"{len(selected)} instrument(s) were selected among {self.considered} considered"
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
        object.__setattr__(self, "skipped", MappingProxyType(skipped))

    @property
    def invested(self) -> float:
        """Return the fraction of capital this allocation puts to work."""
        return sum(self.weights.values())


@dataclass(frozen=True, slots=True)
class Holdings:
    """Cash and quantities actually held, between two decisions.

    Attributes
    ----------
    cash : float
        Currency units not invested. Negative would be borrowing, which
        nothing here does yet.
    quantities : Mapping[str, float]
        Units held per instrument, never negative. Fractional unless the
        instrument declares a ``quantity_step``, which the execution layer
        rounds to: a retail broker deals whole ETF shares, and a backtest that
        buys 123.472 of them reports an allocation nobody could have placed.

    Raises
    ------
    ValueError
        If the cash is not a finite number, or a quantity is not a finite
        number of zero or more. A negative quantity is a short position, and
        nothing here borrows a security, pays a borrow fee or answers a margin
        call - so it is refused where it would be created rather than
        discovered in a return that was never available.

    Notes
    -----
    Cash may be negative, because the guard that counts a book ending on
    borrowed money has to be able to see one. Nothing in the execution layer
    produces it: the purchases are cut to what the cash can carry.

    Holdings are a state, and a state has no opinion. What they are worth
    depends on prices, and prices depend on an instant: :meth:`value_at` asks
    for both rather than remembering either.
    """

    cash: float
    quantities: Mapping[str, float] = MappingProxyType({})

    def __post_init__(self) -> None:
        """Check the state can be held, freeze it, and drop the closed positions."""
        require_finite(self.cash, "cash")
        held: dict[str, float] = {}
        for name, size in self.quantities.items():
            require_identifier(name, "a held instrument")
            require_finite_non_negative(size, f"the quantity of {name}")
            if size != 0.0:
                held[name] = size
        object.__setattr__(self, "quantities", MappingProxyType(held))

    def value_at(self, prices: Mapping[str, float]) -> float:
        """Return the total worth of these holdings at the given prices.

        Parameters
        ----------
        prices : Mapping[str, float]
            One price per held instrument.

        Returns
        -------
        float
            Cash plus the market value of every position.

        Raises
        ------
        KeyError
            If an instrument is held and no price is given for it. Valuing a
            position at nothing because its price is missing would show a loss
            that did not happen, then show it back the next day.
        """
        return self.cash + sum(size * prices[name] for name, size in self.quantities.items())

    def weights_at(self, prices: Mapping[str, float]) -> dict[str, float]:
        """Return the fraction of total worth each position represents."""
        total = self.value_at(prices)
        if total == 0.0:
            return {}
        return {name: size * prices[name] / total for name, size in self.quantities.items()}
