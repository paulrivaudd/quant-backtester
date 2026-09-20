"""Hold the best-ranked funds of the session's universe."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.signals.base import Signal
from quant_backtester.signals.cross_sectional.rank import CrossSectionalRank
from quant_backtester.signals.engine import SignalRequest
from quant_backtester.signals.price.momentum import MomentumSignal
from quant_backtester.signals.types import (
    PriceBasis,
    require_identifier,
    require_positive_int,
)
from quant_backtester.strategies.base import Strategy


@dataclass(frozen=True, slots=True)
class MomentumRotation(Strategy):
    """Rank the universe by momentum and hold the ``top_n`` best, equally.

    Attributes
    ----------
    lookback_sessions : int
        Sessions the momentum is measured over.
    top_n : int
        How many instruments to hold.
    strategy_id : str
        Name this configuration is recorded under.

    Raises
    ------
    ValueError
        If either count is not a positive number.

    Notes
    -----
    The ranking is what the decision reads, not the momentum itself: a rank
    already excludes the instruments whose number is not usable, and already
    says how many it was taken among. Reading the raw momentum instead would
    put a fund with no history at the bottom of the list rather than out of it,
    and a strategy selling the bottom would be selling the names whose data was
    late.

    Each held position gets ``1 / top_n`` of the capital, not
    ``1 / len(held)``: a rotation meant to hold two names that finds one holds
    it at half the capital, rather than doubling a bet because a provider was
    late.
    """

    lookback_sessions: int = 60
    top_n: int = 2
    strategy_id: str = "momentum_rotation"

    def __post_init__(self) -> None:
        """Reject a configuration that cannot be computed."""
        require_identifier(self.strategy_id, "strategy_id")
        require_positive_int(self.lookback_sessions, "lookback_sessions")
        require_positive_int(self.top_n, "top_n")

    @property
    def rank_id(self) -> str:
        """Return the id of the ranking this strategy reads."""
        return f"momentum_{self.lookback_sessions}d_rank"

    def required_signals(self) -> Sequence[Signal | SignalRequest]:
        """Return the momentum and the ranking taken over it."""
        momentum = MomentumSignal(
            signal_id=f"momentum_{self.lookback_sessions}d",
            lookback_sessions=self.lookback_sessions,
            price_basis=PriceBasis.TOTAL_RETURN,
        )
        return (momentum, CrossSectionalRank(signal_id=self.rank_id, source=momentum))

    def decide(self, ctx: StrategyContext) -> TargetAllocation:
        """Hold the best-ranked instruments of this session's universe."""
        return ctx.equal_weight(ctx.top(self.rank_id, self.top_n), count=self.top_n)
