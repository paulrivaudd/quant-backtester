"""What a strategy is allowed to know about the book it is managing.

A decision often depends on what is already held. "Keep the fund while it stays
in the top five", "do not rebalance for less than five percent", "sell after a
twenty percent fall from the entry": all of those are strategy decisions, and
none of them can be written without seeing the positions.

What this is not is a handle on the portfolio. It carries no method that trades,
sizes or rebalances, and the quantities in it are the ones held **at the
decision instant** - before the open the next order will be filled at. A view
that could see the fill price of tomorrow's open would be the whole look-ahead
problem again, one layer up.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

from quant_backtester.numbers import require_finite, require_finite_positive
from quant_backtester.portfolio.state import PortfolioState


@dataclass(frozen=True, slots=True)
class PortfolioView:
    """The book as it stands at one decision instant, read-only.

    Attributes
    ----------
    as_of : datetime
        The decision this view belongs to. The same instant as the signals and
        the market view beside it, checked when the context is built.
    cash : float
        Currency units not invested.
    equity : float
        Cash plus the market value of every position, at the closes the run
        valued the book at.
    quantities : Mapping[str, float]
        Units held per instrument. Positions closed are absent rather than
        held at zero.
    weights : Mapping[str, float]
        Fraction of equity each position represents, at those same closes.
        Empty for a book worth nothing, which has no fractions to speak of.
    average_costs : Mapping[str, float]
        Mean price paid per unit, costs included, for every position whose
        history the run knows. What a stop, a take-profit or a plain "am I up
        on this" is measured against - and only ever what was actually paid,
        never a price the strategy wished it had got.

    Raises
    ------
    ValueError
        If ``as_of`` is naive, or a number is not finite. A strategy comparing
        a weight against a threshold must not be comparing against ``NaN``,
        which is false whichever way the test is written.
    """

    as_of: datetime
    cash: float
    equity: float
    quantities: Mapping[str, float] = MappingProxyType({})
    weights: Mapping[str, float] = MappingProxyType({})
    average_costs: Mapping[str, float] = MappingProxyType({})

    def __post_init__(self) -> None:
        """Check the view describes a book, and freeze it."""
        if not isinstance(self.as_of, datetime) or self.as_of.tzinfo is None:
            raise ValueError(f"as_of must be a timezone-aware datetime, got {self.as_of!r}")
        require_finite(self.cash, "cash")
        require_finite(self.equity, "equity")
        for name, size in self.quantities.items():
            require_finite(size, f"the quantity of {name}")
        for name, weight in self.weights.items():
            require_finite(weight, f"the weight of {name}")
        for name, cost in self.average_costs.items():
            require_finite_positive(cost, f"the average cost of {name}")
        object.__setattr__(self, "quantities", MappingProxyType(dict(self.quantities)))
        object.__setattr__(self, "weights", MappingProxyType(dict(self.weights)))
        object.__setattr__(self, "average_costs", MappingProxyType(dict(self.average_costs)))

    @classmethod
    def of(
        cls, state: PortfolioState, prices: Mapping[str, float], as_of: datetime
    ) -> PortfolioView:
        """Build the view of a book at the prices it was valued at.

        Parameters
        ----------
        state : PortfolioState
            Cash and positions held at the decision instant.
        prices : Mapping[str, float]
            One price per held instrument - the closes the run marked the book
            at, stale ones included. The view is what the run believes it is
            worth, not a second opinion about it.
        as_of : datetime
            The decision instant.

        Returns
        -------
        PortfolioView
            The same book, in the terms a strategy reasons in.

        Raises
        ------
        KeyError
            If a position is held and no price is given for it.
        """
        return cls(
            as_of=as_of,
            cash=state.cash,
            equity=state.value_at(prices),
            quantities=dict(state.quantities),
            weights=state.weights_at(prices),
            average_costs={
                name: holding.average_cost
                for name, holding in state.holdings.items()
                if holding.average_cost is not None
            },
        )

    def weight(self, instrument_id: str) -> float:
        """Return the fraction of equity held in one instrument.

        Parameters
        ----------
        instrument_id : str
            Instrument to look up.

        Returns
        -------
        float
            Its weight, and ``0.0`` for one that is not held. Zero rather than
            a raise on purpose: "how much of this do I hold" has an answer for
            every name, and it is none.
        """
        return self.weights.get(instrument_id, 0.0)

    def quantity(self, instrument_id: str) -> float:
        """Return the units held of one instrument, ``0.0`` when it is not held."""
        return self.quantities.get(instrument_id, 0.0)

    def holds(self, instrument_id: str) -> bool:
        """Return whether the book has a position in one instrument."""
        return instrument_id in self.quantities

    def average_cost(self, instrument_id: str) -> float | None:
        """Return the mean price paid per unit held, or ``None`` when it is not known.

        Parameters
        ----------
        instrument_id : str
            Instrument to look up.

        Returns
        -------
        float | None
            ``None`` for an instrument not held, and for a position whose
            history the run does not know. Never zero: a cost nobody knows is
            not a cost of nothing, and a stop measured against zero never fires.
        """
        return self.average_costs.get(instrument_id)

    @property
    def invested(self) -> float:
        """Return the fraction of equity that is in positions rather than cash."""
        if self.equity == 0.0:
            return 0.0
        return (self.equity - self.cash) / self.equity
