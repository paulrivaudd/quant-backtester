"""Hold one fund while one of its moving averages is above another."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.signals.base import Signal
from quant_backtester.signals.engine import SignalRequest
from quant_backtester.signals.price.trend import MovingAverageCrossSignal
from quant_backtester.signals.types import PriceBasis, SignalStatus, require_identifier
from quant_backtester.strategies.base import Strategy


@dataclass(frozen=True, slots=True)
class MovingAverageCross(Strategy):
    """Hold an instrument while its ``first`` average is above its ``second``.

    Attributes
    ----------
    instrument_id : str
        The fund to hold.
    first_sessions : int
        Length of the average that has to be on top, in sessions.
    second_sessions : int
        Length of the average it is compared with, in sessions.
    strategy_id : str
        Name this configuration is recorded under.

    Raises
    ------
    ValueError
        If a name is empty, or if the two lengths cannot make two different
        averages - checked by the signal, at construction.

    Notes
    -----
    ``first_sessions=50, second_sessions=20`` holds while the 50-session
    average is above the 20-session one: prices have been falling below
    their slower trend. The classic "golden cross" is the other way round,
    ``first_sessions=20, second_sessions=50``. Both are this strategy with
    different parameters, and a register counts them as two variants.

    The averages are taken on adjusted prices, so a dividend paid inside the
    window is not read as a fall.

    What it does when the signal cannot be computed - too little history, a
    session missing, a price too old - is to hold nothing, as
    :class:`MomentumSingleAsset` does. Staying invested on the last decision
    it could take would be a different strategy.
    """

    instrument_id: str
    first_sessions: int = 50
    second_sessions: int = 20
    strategy_id: str = "moving_average_cross"

    def __post_init__(self) -> None:
        """Reject a configuration that cannot be computed."""
        require_identifier(self.instrument_id, "instrument_id")
        require_identifier(self.strategy_id, "strategy_id")
        # Built once here so that a bad pair of lengths stops the construction,
        # not the first decision of a run.
        self.signal()

    @property
    def signal_id(self) -> str:
        """Return the id of the comparison this strategy reads."""
        return f"ma{self.first_sessions}_over_ma{self.second_sessions}"

    def signal(self) -> MovingAverageCrossSignal:
        """Return the signal this strategy reads, configured from its fields."""
        return MovingAverageCrossSignal(
            signal_id=self.signal_id,
            first_sessions=self.first_sessions,
            second_sessions=self.second_sessions,
            price_basis=PriceBasis.ADJUSTED,
        )

    def required_signals(self) -> Sequence[Signal | SignalRequest]:
        """Return the one signal this strategy needs."""
        return (self.signal(),)

    def decide(self, ctx: StrategyContext) -> TargetAllocation:
        """Hold the fund while the first average is above the second, cash otherwise."""
        if ctx.signal_status(self.signal_id, self.instrument_id) is not SignalStatus.OK:
            return ctx.cash()
        if ctx.signal_value(self.signal_id, self.instrument_id) <= 0.0:
            return ctx.cash()
        return ctx.weights({self.instrument_id: 1.0})
