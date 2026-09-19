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

from quant_backtester.signals.types import SignalStatus


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
    """

    as_of: datetime
    weights: Mapping[str, float]
    selected: tuple[str, ...]
    considered: int
    skipped: Mapping[str, SignalStatus]

    def __post_init__(self) -> None:
        """Freeze the two mappings, so an allocation cannot be edited after the fact."""
        object.__setattr__(self, "weights", MappingProxyType(dict(self.weights)))
        object.__setattr__(self, "skipped", MappingProxyType(dict(self.skipped)))

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
        Units held per instrument. Fractional: lot sizes and whether a broker
        allows fractional shares are properties of an instrument that the
        registry does not carry, and inventing a rounding rule would put a
        silent, untested assumption between a signal and a return.

    Notes
    -----
    Holdings are a state, and a state has no opinion. What they are worth
    depends on prices, and prices depend on an instant: :meth:`value_at` asks
    for both rather than remembering either.
    """

    cash: float
    quantities: Mapping[str, float] = MappingProxyType({})

    def __post_init__(self) -> None:
        """Freeze the quantities and drop the positions that were closed."""
        held = {name: size for name, size in self.quantities.items() if size != 0.0}
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
