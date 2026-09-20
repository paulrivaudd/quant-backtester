"""Hold one fund while its momentum is positive, and stand aside otherwise."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.numbers import require_finite
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.signals.base import Signal
from quant_backtester.signals.engine import SignalRequest
from quant_backtester.signals.price.momentum import MomentumSignal
from quant_backtester.signals.types import (
    PriceBasis,
    SignalStatus,
    require_identifier,
    require_positive_int,
)
from quant_backtester.strategies.base import Strategy


@dataclass(frozen=True, slots=True)
class MomentumSingleAsset(Strategy):
    """Hold one instrument while its trailing return is above a threshold.

    Attributes
    ----------
    instrument_id : str
        The fund to hold.
    lookback_sessions : int
        Sessions the momentum is measured over.
    minimum : float
        The momentum must be above this to hold. ``0.0`` is the usual
        time-series momentum rule: hold what has gone up.
    strategy_id : str
        Name this configuration is recorded under.

    Raises
    ------
    ValueError
        If the lookback is not a positive number of sessions, if the threshold
        is not a finite number, or if a name is empty.

    Notes
    -----
    The momentum is computed on total-return prices, so a dividend paid during
    the window is a return the holder got rather than a fall in the series.

    What it does when the momentum cannot be computed - too little history, a
    session missing, a value too old - is to hold nothing. That is a decision,
    written down here: the alternative, staying invested on the last decision
    it could take, is just as defensible and is a different strategy.
    """

    instrument_id: str
    lookback_sessions: int = 60
    minimum: float = 0.0
    strategy_id: str = "momentum_single_asset"

    def __post_init__(self) -> None:
        """Reject a configuration that cannot be computed."""
        require_identifier(self.instrument_id, "instrument_id")
        require_identifier(self.strategy_id, "strategy_id")
        require_positive_int(self.lookback_sessions, "lookback_sessions")
        # A threshold of NaN compares false against every momentum, so the
        # strategy would be invested whenever a number exists; an infinite one
        # is always cash. Both are a parameter written wrong.
        require_finite(self.minimum, "minimum")

    @property
    def signal_id(self) -> str:
        """Return the id of the momentum this strategy reads."""
        return f"momentum_{self.lookback_sessions}d"

    def required_signals(self) -> Sequence[Signal | SignalRequest]:
        """Return the one signal this strategy needs."""
        return (
            MomentumSignal(
                signal_id=self.signal_id,
                lookback_sessions=self.lookback_sessions,
                price_basis=PriceBasis.TOTAL_RETURN,
            ),
        )

    def decide(self, ctx: StrategyContext) -> TargetAllocation:
        """Hold the fund while its momentum is above the threshold."""
        if ctx.signal_status(self.signal_id, self.instrument_id) is not SignalStatus.OK:
            return ctx.cash()
        if ctx.signal_value(self.signal_id, self.instrument_id) <= self.minimum:
            return ctx.cash()
        return ctx.weights({self.instrument_id: 1.0})
