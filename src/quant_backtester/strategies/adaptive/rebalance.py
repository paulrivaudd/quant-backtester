"""From a theoretical target to a decision: the rebalancing band, applied once."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from quant_backtester.backtest.context import Selection, StrategyContext
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.signals.types import SignalStatus
from quant_backtester.strategies.adaptive.rules import RuleTarget
from quant_backtester.strategies.base import Strategy


@dataclass(frozen=True, slots=True)
class Evaluation:
    """A rule's theoretical target at one decision, and what it could not read.

    Attributes
    ----------
    target : RuleTarget
        The complete target, before the rebalancing band.
    unusable : Mapping[str, SignalStatus]
        Why each instrument whose signal had no value had none.
    """

    target: RuleTarget
    unusable: Mapping[str, SignalStatus] = field(default_factory=lambda: MappingProxyType({}))


def settle(
    ctx: StrategyContext,
    target: Mapping[str, float],
    *,
    band: float,
    caps: Mapping[str, float] | None = None,
    force: bool = False,
    unusable: Mapping[str, SignalStatus] | None = None,
) -> TargetAllocation:
    """Return the decision a complete target stands for, given the book.

    Parameters
    ----------
    ctx : StrategyContext
        The decision being taken; its portfolio is the book the target is
        compared with, valued at the closes of the decision.
    target : Mapping[str, float]
        Complete target weights. An instrument left out has a target of zero.
    band : float
        The book is kept when no weight is further than this from its target,
        as a fraction of equity: ``0.03`` is three percentage points.
    caps : Mapping[str, float] | None
        Largest weight allowed per instrument. A held weight above its cap is
        traded back whatever the band says.
    force : bool
        Send the target whatever the band says.
    unusable : Mapping[str, SignalStatus] | None
        Why inputs were missing, recorded on the decision.

    Returns
    -------
    TargetAllocation
        Cash for an empty target; the book as it stands, with no order, when
        every weight is inside the band; the complete target otherwise.

    Notes
    -----
    The band never holds back a complete exit: a held instrument whose target
    is zero is sold, however small the line. It never delays an entry from
    cash larger than the band either, since that gap is the target itself.
    """
    wanted = {name: weight for name, weight in target.items() if weight > 0.0}
    held = dict(ctx.portfolio.weights)
    if not wanted:
        return ctx.cash(among=_among((), unusable))
    exits = any(name not in wanted for name in held)
    breached = any(held.get(name, 0.0) > cap for name, cap in (caps or {}).items())
    gap = max(abs(wanted.get(name, 0.0) - held.get(name, 0.0)) for name in {*wanted, *held})
    if force or exits or breached or gap >= band:
        return ctx.weights(wanted, among=_among(tuple(wanted), unusable))
    return ctx.hold_positions(among=_among(tuple(held), unusable))


def _among(names: tuple[str, ...], unusable: Mapping[str, SignalStatus] | None) -> Selection | None:
    """Return the record of what could not be read, or ``None`` when all could."""
    if not unusable:
        return None
    return Selection(names=(), considered=len(names), skipped=dict(unusable))


class RuleStrategy(Strategy):
    """A strategy that is one rule and the common rebalancing band.

    Attributes
    ----------
    rebalance_band : float
        Largest gap between a weight and its target that sends no order.
    """

    rebalance_band: float

    @abstractmethod
    def evaluate(self, ctx: StrategyContext) -> Evaluation:
        """Return the rule's theoretical target, before the band.

        Parameters
        ----------
        ctx : StrategyContext
            The decision being taken. Only declared signals are read.
        """

    def caps(self) -> Mapping[str, float]:
        """Return the weight caps the band must not hold a breach of."""
        return {}

    def decide(self, ctx: StrategyContext) -> TargetAllocation:
        """Return the target for the next open: the rule, then the band."""
        evaluation = self.evaluate(ctx)
        return settle(
            ctx,
            evaluation.target.weights,
            band=self.rebalance_band,
            caps=self.caps(),
            unusable=evaluation.unusable,
        )
