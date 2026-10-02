"""Hold one fund while its price is above its moving average, cash while it is below."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.signals.base import Signal
from quant_backtester.signals.engine import SignalRequest
from quant_backtester.signals.price.trend import MovingAverageTrendSignal
from quant_backtester.signals.types import PriceBasis, SignalStatus, require_identifier
from quant_backtester.strategies.base import Strategy


@dataclass(frozen=True, slots=True)
class MovingAverageBandETF(Strategy):
    """Buy an ETF when its close passes above its moving average, sell it when it passes below.

    Attributes
    ----------
    instrument_id : str
        The ETF studied.
    window_sessions : int
        Length of the moving average, in sessions, the latest close included.
    sell_below : float
        The fund is sold when its close is strictly below this multiple of its
        average: ``1.0`` is the average itself, ``0.95`` is 95% of it.
    buy_above : float
        The fund is bought when its close is strictly above this multiple of
        its average: ``1.0`` is the average itself, ``1.05`` is 105% of it.
    strategy_id : str
        Name this configuration is recorded under.

    Raises
    ------
    ValueError
        If a name is empty, if the window cannot make an average - checked by
        the signal, at construction - or unless ``0 < sell_below <= buy_above``,
        both finite: with the two levels the other way round there would be
        closes that say buy and sell at once.

    Notes
    -----
    A trend rule, like a golden cross, but it compares the close of the day
    with one average instead of two averages with each other, so it turns
    sooner. With both levels at ``1.0`` the fund is held while its close is
    above its average and sold while it is below.

    Two different levels leave a band between them, and inside it - as on a
    level exactly - the rule keeps what it has, fund or cash. What it has is
    read from the book of the decision, never from an attribute of this
    object. The band is what keeps a price hovering around its average from
    being bought and sold every other day.

    The close and its average are taken on adjusted prices, as in
    :class:`GoldenCrossETF`, so a distribution paid inside the window is not
    read as a fall below the average.

    When the signal cannot be computed - too little history, a session missing,
    a price too old - the rule keeps its positions and sends no order. It only
    ever acts on a level it has seen crossed; selling because a bar is missing
    would be a third rule that nobody wrote down.

    The target is executed at the next open, by the engine.
    """

    instrument_id: str = "ETF_WORLD"
    window_sessions: int = 50
    sell_below: float = 1.0
    buy_above: float = 1.0
    strategy_id: str = "moving_average_band_etf"

    def __post_init__(self) -> None:
        """Reject a configuration that cannot be computed or contradicts itself."""
        require_identifier(self.instrument_id, "instrument_id")
        require_identifier(self.strategy_id, "strategy_id")
        # Built once here so that a bad window stops the construction, not the
        # first decision of a run.
        self.signal()
        for name in ("sell_below", "buy_above"):
            level = getattr(self, name)
            if isinstance(level, bool) or not isinstance(level, (int, float)):
                raise ValueError(f"{name} must be a number, got {level!r}")
            if not math.isfinite(level) or level <= 0.0:
                raise ValueError(f"{name} must be a finite positive multiple, got {level!r}")
        if self.sell_below > self.buy_above:
            raise ValueError(
                f"sell_below ({self.sell_below}) must not be above buy_above ({self.buy_above})"
            )

    @property
    def signal_id(self) -> str:
        """Return the id of the distance this strategy reads."""
        return f"price_over_ma{self.window_sessions}"

    def signal(self) -> MovingAverageTrendSignal:
        """Return ``P_t / MA_N(t) - 1`` on adjusted closes, configured from the fields."""
        return MovingAverageTrendSignal(
            signal_id=self.signal_id,
            window_sessions=self.window_sessions,
            price_basis=PriceBasis.ADJUSTED,
        )

    def required_signals(self) -> Sequence[Signal | SignalRequest]:
        """Return the one signal this strategy needs, on the studied ETF only."""
        return (SignalRequest(signal=self.signal(), instruments=(self.instrument_id,)),)

    def decide(self, ctx: StrategyContext) -> TargetAllocation:
        """Return the target for the next open.

        Parameters
        ----------
        ctx : StrategyContext
            Everything the decision may see, fixed at the decision instant,
            after the close of the session it is taken on.

        Returns
        -------
        TargetAllocation
            100% of the fund when the close is above ``buy_above`` times its
            average and the fund is not held; cash when it is below
            ``sell_below`` times it; the book as it stands, with no order, in
            every other case.
        """
        if ctx.signal_status(self.signal_id, self.instrument_id) is not SignalStatus.OK:
            return ctx.hold_positions()
        price_over_average = 1.0 + ctx.signal_value(self.signal_id, self.instrument_id)
        if price_over_average < self.sell_below:
            return ctx.cash()
        if price_over_average > self.buy_above and not ctx.portfolio.holds(self.instrument_id):
            return ctx.weights({self.instrument_id: 1.0})
        # On a level, between the two, or above while already bought: a target
        # of 100% restated every evening would trade the overnight drift.
        return ctx.hold_positions()
