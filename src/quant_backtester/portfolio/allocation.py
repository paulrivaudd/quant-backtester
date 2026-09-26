"""From what a strategy asked for to what the book is allowed to hold.

The strategy decides what it would like to hold; this module decides what it
may. The answer is a separate object rather than an edited copy of the
request, because a result has to be able to show both - "asked for 70% of one
name, allowed 50%" is a fact about the run, and a record that kept only the
second number would describe a strategy that never asked for the first.

The model applies two kinds of rule, in this order:

1. **admissibility** (:mod:`quant_backtester.portfolio.constraints`): every
   instrument named exists, can be bought, is quoted in the book's currency and
   is in the day's trading universe - or the run stops, because a target that
   breaks one of these was written against the wrong list;
2. **limits** (:mod:`quant_backtester.portfolio.limits`): the weights are cut
   to the declared risk policy, and every cut is named.

Nothing here knows what a signal is, what the VIX did or why the strategy
wanted what it wanted.
"""

from __future__ import annotations

import math
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType

from quant_backtester.data.instruments import InstrumentRegistry
from quant_backtester.numbers import require_unit_fraction
from quant_backtester.portfolio.constraints import check_admissible
from quant_backtester.portfolio.limits import LimitAdjustment, PortfolioLimits
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.signals.types import SignalStatus, require_identifier


@dataclass(frozen=True, slots=True)
class ConstrainedTarget:
    """What the portfolio allowed, beside what it was asked for.

    Attributes
    ----------
    as_of : datetime
        The decision instant both answer for.
    requested_weights : Mapping[str, float]
        The strategy's weights, as it returned them.
    accepted_weights : Mapping[str, float]
        The weights the book will be traded towards, one per requested
        instrument and never above it.
    adjustments : Mapping[str, tuple[LimitAdjustment, ...]]
        For every instrument whose accepted weight is below its requested one,
        the limits that cut it, in the order they were applied.
    hold_positions : bool
        Whether the book is to be kept exactly as it is, with no order sent.
        True only when the strategy asked to hold and no limit cut anything: a
        limit that binds on a held book is a trade the policy requires.
    kept : frozenset[str]
        Instruments whose positions get no order while the rest is traded:
        those the strategy kept that no limit cut.
    cash_shares : Mapping[str, float]
        Lines sized on the cash at the execution instant: those the strategy
        asked for that no limit cut. A cut line is sized on its accepted
        weight, like any other.

    Raises
    ------
    ValueError
        If the two sides describe different instruments, an accepted weight
        is above its request or is not a fraction, or a weight moved without a
        reason - or a reason is given for one that did not move. A difference
        nobody can explain is the one thing an audit trail must not contain.

    Notes
    -----
    Nothing is ever dropped quietly between the two sides. An instrument the
    book may not hold at all is refused before this object exists, and an
    instrument a limit reduced keeps its line with the reason beside it.
    """

    as_of: datetime
    requested_weights: Mapping[str, float]
    accepted_weights: Mapping[str, float]
    adjustments: Mapping[str, tuple[LimitAdjustment, ...]] = field(
        default_factory=lambda: MappingProxyType({})
    )
    hold_positions: bool = False
    kept: frozenset[str] = frozenset()
    cash_shares: Mapping[str, float] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        """Check the two sides tell one consistent story, and freeze them."""
        if not isinstance(self.as_of, datetime) or self.as_of.tzinfo is None:
            raise ValueError(f"as_of must be a timezone-aware datetime, got {self.as_of!r}")
        if not isinstance(self.hold_positions, bool):
            raise ValueError(
                f"hold_positions must be said as a boolean, got {self.hold_positions!r}"
            )
        if self.hold_positions and self.adjustments:
            raise ValueError(
                "a book a limit had to cut cannot be kept as it is: the cut is a trade"
            )
        requested = {name: self.requested_weights[name] for name in sorted(self.requested_weights)}
        accepted = {name: self.accepted_weights[name] for name in sorted(self.accepted_weights)}
        if set(requested) != set(accepted):
            raise ValueError(
                f"requested {sorted(requested)} and accepted {sorted(accepted)} are not "
                "the same instruments"
            )
        adjustments: dict[str, tuple[LimitAdjustment, ...]] = {}
        for name in sorted(self.adjustments):
            reasons = tuple(self.adjustments[name])
            if name not in requested:
                raise ValueError(f"{name} was adjusted and never requested")
            if not reasons or not all(isinstance(reason, LimitAdjustment) for reason in reasons):
                raise ValueError(f"{name} is adjusted for {reasons!r}, which is not a limit")
            adjustments[name] = reasons
        for name, wanted in requested.items():
            require_identifier(name, "an instrument of the target")
            require_unit_fraction(wanted, f"the requested weight of {name}")
            allowed = accepted[name]
            require_unit_fraction(allowed, f"the accepted weight of {name}")
            if allowed > wanted:
                raise ValueError(
                    f"{name} was accepted at {allowed}, above the {wanted} requested: a limit "
                    "only ever takes out"
                )
            if (allowed != wanted) != (name in adjustments):
                raise ValueError(
                    f"{name}: requested {wanted}, accepted {allowed}, and the adjustments "
                    "do not say why - a weight moves with a reason or not at all"
                )
        kept = frozenset(self.kept)
        if not kept <= set(accepted):
            raise ValueError(f"{sorted(kept - set(accepted))} is kept and was never requested")
        if kept & set(adjustments):
            raise ValueError(
                f"{sorted(kept & set(adjustments))} is kept and a limit cut it: the cut is a trade"
            )
        object.__setattr__(self, "kept", kept)
        cash_shares = dict(self.cash_shares)
        if not set(cash_shares) <= set(accepted) or set(cash_shares) & set(adjustments):
            raise ValueError(
                f"{sorted(cash_shares)} are sized on cash, and must be accepted lines no limit cut"
            )
        object.__setattr__(self, "cash_shares", MappingProxyType(cash_shares))
        object.__setattr__(self, "requested_weights", MappingProxyType(requested))
        object.__setattr__(self, "accepted_weights", MappingProxyType(accepted))
        object.__setattr__(self, "adjustments", MappingProxyType(adjustments))

    @property
    def requested_invested(self) -> float:
        """Return the fraction of capital the strategy asked to put to work."""
        return math.fsum(self.requested_weights.values())

    @property
    def invested(self) -> float:
        """Return the fraction of capital the book is allowed to put to work."""
        return math.fsum(self.accepted_weights.values())

    @property
    def gross(self) -> float:
        """Return the accepted gross exposure, ``sum |w|``."""
        return math.fsum(abs(weight) for weight in self.accepted_weights.values())

    @property
    def was_adjusted(self) -> bool:
        """Return whether any limit changed anything."""
        return bool(self.adjustments)


@dataclass(frozen=True, slots=True)
class PortfolioDecision:
    """One decision, as the strategy took it and as the portfolio allowed it.

    Attributes
    ----------
    requested : TargetAllocation
        What the strategy returned, with its own diagnostics: what it selected,
        among how many, and why the others were not eligible.
    constrained : ConstrainedTarget
        What the portfolio allowed of it.

    Raises
    ------
    ValueError
        If the two do not answer for the same instant, or the constrained side
        does not start from exactly the weights the strategy returned.
    """

    requested: TargetAllocation
    constrained: ConstrainedTarget

    def __post_init__(self) -> None:
        """Check both halves describe the same decision."""
        if self.requested.as_of != self.constrained.as_of:
            raise ValueError(
                f"the strategy answered for {self.requested.as_of} and the portfolio for "
                f"{self.constrained.as_of}"
            )
        if dict(self.requested.weights) != dict(self.constrained.requested_weights):
            raise ValueError("the constrained target does not start from what was requested")

    @property
    def as_of(self) -> datetime:
        """Return the decision instant."""
        return self.requested.as_of

    @property
    def accepted_weights(self) -> Mapping[str, float]:
        """Return the weights the book will be traded towards."""
        return self.constrained.accepted_weights

    @property
    def holds_positions(self) -> bool:
        """Return whether the book is to be kept exactly as it is, with no order."""
        return self.constrained.hold_positions

    @property
    def kept(self) -> frozenset[str]:
        """Return the lines that get no order while the rest of the book is traded."""
        return self.constrained.kept

    @property
    def cash_shares(self) -> Mapping[str, float]:
        """Return the lines sized on the cash at the execution instant."""
        return self.constrained.cash_shares

    @property
    def considered(self) -> int:
        """Return how many instruments the strategy had a usable signal for."""
        return self.requested.considered

    @property
    def selected(self) -> tuple[str, ...]:
        """Return what the strategy chose, best first."""
        return self.requested.selected

    @property
    def skipped(self) -> Mapping[str, SignalStatus]:
        """Return why each instrument that was not eligible was not."""
        return self.requested.skipped


@dataclass(frozen=True, slots=True)
class PortfolioModel:
    """Turns a strategy's request into the target the book is traded towards.

    Attributes
    ----------
    limits : PortfolioLimits
        The declared risk policy. The default is none beyond the project's
        invariants: long-only, and never more than the whole book.
    """

    limits: PortfolioLimits = field(default_factory=PortfolioLimits)

    def definition(self) -> dict[str, object]:
        """Return the model as it is recorded with a run."""
        return {"limits": self.limits.definition()}

    def decide(
        self,
        requested: TargetAllocation,
        *,
        instruments: InstrumentRegistry,
        universe: Collection[str],
        base_currency: str,
    ) -> PortfolioDecision:
        """Return what the book may hold of what the strategy asked for.

        Parameters
        ----------
        requested : TargetAllocation
            The strategy's decision.
        instruments : InstrumentRegistry
            What each instrument is.
        universe : Collection[str]
            The trading universe on the session being decided.
        base_currency : str
            The currency the book is kept in.

        Returns
        -------
        PortfolioDecision
            The request and what was allowed of it, with every cut named.

        Raises
        ------
        InadmissibleTarget
            If the request names an instrument the book may not hold - unknown,
            not tradable, in another currency, or outside the day's universe.
            Never clipped silently: a limit is policy, and this is a mistake.
        """
        check_admissible(
            requested.weights,
            instruments=instruments,
            universe=universe,
            base_currency=base_currency,
        )
        accepted, adjustments = self.limits.apply(requested.weights)
        return PortfolioDecision(
            requested=requested,
            constrained=ConstrainedTarget(
                as_of=requested.as_of,
                requested_weights=requested.weights,
                accepted_weights=accepted,
                adjustments=adjustments,
                # A limit that binds overrules a hold: the book is traded down
                # to the policy, like any other target that breached it.
                hold_positions=requested.hold_positions and not adjustments,
                # Likewise for a single kept line: one a limit cut is traded.
                kept=requested.kept - set(adjustments),
                cash_shares={
                    name: share
                    for name, share in requested.cash_shares.items()
                    if name not in adjustments
                },
            ),
        )
