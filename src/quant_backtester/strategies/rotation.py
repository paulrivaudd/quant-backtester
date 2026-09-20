"""Hold the best-ranked instruments of a universe, and nothing else.

The simplest strategy that is still a strategy, and it is here to prove one
thing: that a decision needs the signals and nothing underneath them. This
module imports no reader, no repository, no calendar and no provider. It cannot
open a file, it cannot know what a corporate action is, and it cannot ask what
happened the day after the decision - the only thing it is given is a
:class:`~quant_backtester.backtest.context.StrategyContext`, whose every part is
fixed at one instant.

What it does is deliberately thin. Read a ranking, keep the top few, weight them
equally. A cap per position, a gross limit, a turnover budget: those are the
portfolio layer's, and they are applied to what comes out of here rather than
folded into it, so that a report can say what each of them cost.
"""

from __future__ import annotations

from dataclasses import dataclass

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.signals.types import require_identifier, require_positive_int
from quant_backtester.strategies.base import Strategy


@dataclass(frozen=True, slots=True)
class TopRankRotation(Strategy):
    """Hold the ``top_n`` best-ranked instruments, equally weighted.

    Attributes
    ----------
    signal_id : str
        The ranking to read from the snapshot. A ranking rather than a raw
        signal on purpose: a rank already excludes the instruments whose data
        is not usable, and already says how many it was taken among.
    top_n : int
        How many instruments to hold.
    strategy_id : str
        Name this configuration is recorded under.

    Raises
    ------
    ValueError
        If ``top_n`` is not a positive integer, or an identifier is empty.

    Notes
    -----
    Each held position gets ``1 / top_n`` of the capital, not ``1 / len(held)``.
    A rotation meant to hold two names that can only find one holds that one at
    half the capital and leaves the rest in cash, rather than doubling a bet
    because a provider was late. Concentrating on the survivors is a decision,
    and it is not one a data problem should take.

    The signals are not declared here: a ranking is built on a source signal
    whose parameters this strategy has no opinion about, so both are passed to
    the engine, or declared by a strategy that composes this one.
    """

    signal_id: str
    top_n: int
    strategy_id: str = "top_rank_rotation"

    def __post_init__(self) -> None:
        """Reject a rotation that cannot hold anything."""
        require_identifier(self.signal_id, "signal_id")
        require_identifier(self.strategy_id, "strategy_id")
        require_positive_int(self.top_n, "top_n")

    def decide(self, ctx: StrategyContext) -> TargetAllocation:
        """Return what to hold, given one decision instant.

        Parameters
        ----------
        ctx : StrategyContext
            The signals, the market and the book of this decision.

        Returns
        -------
        TargetAllocation
            The instruments to hold and their weights, with the reason every
            other one was left out.

        Raises
        ------
        KeyError
            If the snapshot holds no such signal. A strategy naming a signal
            the engine was not given is a wiring mistake, not an empty day.
        """
        selected = ctx.top(self.signal_id, self.top_n)
        return ctx.equal_weight(selected, count=self.top_n)
