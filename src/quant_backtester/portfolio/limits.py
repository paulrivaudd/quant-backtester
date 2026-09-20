"""The limits a decision is held to, whatever the signals said.

A strategy expresses a view. This layer decides how much of the capital that
view is allowed to move, and it is deliberately separate: a rule that says
"hold the two best" and a rule that says "never more than 40% in one name" are
different statements, and merging them makes the second invisible in a backtest
report.

Nothing here rescales a capped allocation back up to fully invested. Spreading
the excess over the remaining names would quietly replace the strategy's view
with another one; what a limit takes out stays in cash, and the record says so.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from quant_backtester.numbers import require_finite_positive
from quant_backtester.portfolio.targets import TargetAllocation


@dataclass(frozen=True, slots=True)
class PositionLimits:
    """How concentrated and how invested an allocation may be.

    Attributes
    ----------
    max_weight : float
        Largest fraction of capital one instrument may take. ``1.0`` allows
        everything in a single name.
    max_gross : float
        Largest fraction of capital the whole allocation may put to work.
        ``1.0`` is fully invested and no borrowing.

    Raises
    ------
    ValueError
        If a limit is not a finite fraction in ``(0, 1]``. Leverage is not
        refused because it is wrong, but because nothing below this layer
        models a financing cost, and a backtest that borrows for free is a
        backtest that reports a return nobody could have had.
    """

    max_weight: float = 1.0
    max_gross: float = 1.0

    def __post_init__(self) -> None:
        """Reject a limit that does not describe a fraction of capital."""
        for name, value in (("max_weight", self.max_weight), ("max_gross", self.max_gross)):
            require_finite_positive(value, name)
            if value > 1.0:
                raise ValueError(f"{name} must be in (0, 1], got {value}")

    def apply(self, allocation: TargetAllocation) -> TargetAllocation:
        """Return the allocation a portfolio is allowed to hold.

        Parameters
        ----------
        allocation : TargetAllocation
            What the strategy asked for.

        Returns
        -------
        TargetAllocation
            The same decision, with each weight capped and the total scaled
            down if it exceeded ``max_gross``. Everything else - which
            instruments were selected, how many were considered, why the others
            were not - is carried through untouched: a limit changes sizes, not
            the reading of the market.

        Notes
        -----
        The gross constraint scales every weight by the same factor rather than
        trimming the largest. Trimming would change the relative sizes the
        strategy chose, which is a second opinion this layer has no basis for.
        """
        capped = {name: min(weight, self.max_weight) for name, weight in allocation.weights.items()}
        gross = sum(capped.values())
        if gross > self.max_gross:
            factor = self.max_gross / gross
            capped = {name: weight * factor for name, weight in capped.items()}
        return replace(allocation, weights=capped)
