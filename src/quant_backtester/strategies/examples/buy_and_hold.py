"""Hold one book and never change it: the strategy every other one is measured against."""

from __future__ import annotations

from dataclasses import dataclass

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.signals.types import require_identifier
from quant_backtester.strategies.base import Strategy


@dataclass(frozen=True, slots=True)
class BuyAndHold(Strategy):
    """Hold the named instruments in equal parts, on every session.

    Attributes
    ----------
    instruments : tuple[str, ...]
        What to hold. Every one of them must be in the session's universe and
        tradable, which the helper checks.
    strategy_id : str
        Name this configuration is recorded under.

    Raises
    ------
    ValueError
        If no instrument is named, or a name is empty.

    Notes
    -----
    It reads no signal, which is what makes it the useful baseline: a strategy
    that does not beat it after costs is an expensive way of holding the same
    thing. The target is restated at every decision rather than held once,
    because the weights drift with the prices and restating them is what a
    rebalancing *is* - the execution layer then decides whether the difference
    is worth trading.
    """

    instruments: tuple[str, ...]
    strategy_id: str = "buy_and_hold"

    def __post_init__(self) -> None:
        """Reject a book with nothing in it."""
        require_identifier(self.strategy_id, "strategy_id")
        if not self.instruments:
            raise ValueError("buy and hold what? name at least one instrument")
        for instrument_id in self.instruments:
            require_identifier(instrument_id, "an instrument")

    def decide(self, ctx: StrategyContext) -> TargetAllocation:
        """Return the same equally weighted book at every decision."""
        return ctx.equal_weight(self.instruments)
