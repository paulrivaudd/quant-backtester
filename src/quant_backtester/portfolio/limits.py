"""The limits a decision is held to, whatever the signals said.

A strategy expresses a view. This layer decides how much of the capital that
view is allowed to move, and it is deliberately separate: a rule that says
"hold the two best" and a rule that says "never more than 40% in one name" are
different statements, and merging them makes the second invisible in a backtest
report.

A limit is a known, declared risk rule, so exceeding one is not an error: the
weight is cut down to it and the cut is **named**, instrument by instrument, in
the decision the run records. What is not a limit - an instrument that cannot
be bought, a currency the book is not kept in - is refused elsewhere, loudly.

Nothing here rescales a capped allocation back up to fully invested. Spreading
the excess over the remaining names would quietly replace the strategy's view
with another one; what a limit takes out stays in cash, and the record says so.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from quant_backtester.numbers import require_finite_positive
from quant_backtester.portfolio.targets import WEIGHT_SUM_TOLERANCE


class LimitAdjustment(Enum):
    """Why an accepted weight is smaller than the one the strategy asked for."""

    CAPPED_AT_MAX_WEIGHT = "CAPPED_AT_MAX_WEIGHT"
    """The instrument was asked more than one name may take, and was cut to it."""

    SCALED_TO_MAX_GROSS = "SCALED_TO_MAX_GROSS"
    """The whole allocation put more of the book to work than allowed, and every
    weight was scaled down by the same factor."""


@dataclass(frozen=True, slots=True)
class PortfolioLimits:
    """How concentrated and how invested an allocation may be.

    Attributes
    ----------
    max_weight_per_instrument : float
        Largest fraction of capital one instrument may take. ``1.0`` allows
        everything in a single name.
    max_gross : float
        Largest gross exposure, ``sum |w|``, the whole allocation may reach.
        ``1.0`` is fully invested and no borrowing.
    long_only : bool
        Whether the book may only hold positive quantities. Must be ``True``:
        it is declared rather than assumed so that a result says, in its own
        configuration, which kind of book it was.

    Raises
    ------
    ValueError
        If a limit is not a finite fraction in ``(0, 1]``, or ``long_only`` is
        not ``True``. Leverage and shorts are not refused because they are
        wrong, but because nothing below this layer models a financing cost,
        a borrow fee, a margin call or a forced liquidation - and a backtest
        that borrows or shorts for free reports a return nobody could have had.
    """

    max_weight_per_instrument: float = 1.0
    max_gross: float = 1.0
    long_only: bool = True

    def __post_init__(self) -> None:
        """Reject a limit that does not describe a fraction of capital."""
        for name, value in (
            ("max_weight_per_instrument", self.max_weight_per_instrument),
            ("max_gross", self.max_gross),
        ):
            require_finite_positive(value, name)
            if value > 1.0:
                raise ValueError(
                    f"{name} must be in (0, 1], got {value}: above one is leverage, and "
                    "nothing here finances it"
                )
        if self.long_only is not True:
            raise ValueError(
                f"long_only must be True, got {self.long_only!r}: a short needs a borrow, a "
                "fee, a margin and a liquidation rule, and none of them is modelled"
            )

    def definition(self) -> dict[str, object]:
        """Return the limits as they are recorded with a run."""
        return {
            "max_weight_per_instrument": self.max_weight_per_instrument,
            "max_gross": self.max_gross,
            "long_only": self.long_only,
        }

    def apply(
        self, weights: Mapping[str, float]
    ) -> tuple[dict[str, float], dict[str, tuple[LimitAdjustment, ...]]]:
        """Return the weights a portfolio is allowed to hold, and why each one moved.

        Parameters
        ----------
        weights : Mapping[str, float]
            What the strategy asked for, one fraction of capital per
            instrument.

        Returns
        -------
        tuple[dict[str, float], dict[str, tuple[LimitAdjustment, ...]]]
            The accepted weights, in instrument order, and for every
            instrument whose weight was cut, the limits that cut it - in the
            order they were applied. An instrument absent from the second
            mapping was accepted as asked.

        Notes
        -----
        The per-instrument cap is applied first, then the gross limit scales
        every weight by the same factor. Scaling rather than trimming the
        largest keeps the relative sizes the strategy chose, which is the only
        part of its view this layer has any right to preserve. A gross within
        :data:`~quant_backtester.portfolio.targets.WEIGHT_SUM_TOLERANCE` of the
        limit is floating-point dust and is left alone, so a book asked to be
        fully invested is not "scaled" by one ulp and reported as such.
        """
        accepted: dict[str, float] = {}
        reasons: dict[str, list[LimitAdjustment]] = {}
        for instrument_id in sorted(weights):
            weight = weights[instrument_id]
            if weight > self.max_weight_per_instrument:
                weight = self.max_weight_per_instrument
                reasons.setdefault(instrument_id, []).append(LimitAdjustment.CAPPED_AT_MAX_WEIGHT)
            accepted[instrument_id] = weight
        gross = math.fsum(abs(weight) for weight in accepted.values())
        if gross > self.max_gross + WEIGHT_SUM_TOLERANCE:
            factor = self.max_gross / gross
            for instrument_id, weight in accepted.items():
                if weight == 0.0:
                    continue
                accepted[instrument_id] = weight * factor
                reasons.setdefault(instrument_id, []).append(LimitAdjustment.SCALED_TO_MAX_GROSS)
        return accepted, {name: tuple(found) for name, found in reasons.items()}
