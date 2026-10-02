"""Buy one fund above a short moving average, sell it below a longer one."""

from __future__ import annotations

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
class MovingAverageEntryExitETF(Strategy):
    """Buy an ETF when its close is above one moving average, sell it below another.

    Attributes
    ----------
    instrument_id : str
        The ETF studied.
    entry_sessions : int
        Length of the average the close has to be above for the fund to be
        bought, in sessions, the latest close included.
    exit_sessions : int
        Length of the average the close has to be below for the fund to be
        sold, in sessions, the latest close included.
    strategy_id : str
        Name this configuration is recorded under.

    Raises
    ------
    ValueError
        If a name is empty, if a length cannot make an average - checked by
        the signal, at construction - or if both lengths are equal: that is
        :class:`MovingAverageBandETF` with its two levels at ``1.0``, and one
        rule has one name.

    Notes
    -----
    The rule of :class:`MovingAverageBandETF` with a slower exit: the fund is
    bought as soon as its close is above its 50-session average, and a close
    that dips under that average no longer sells it - only a close under the
    100-session one does. The dips that chopped the first rule are sat through.

    The sale comes first. A close below the exit average is cash, whatever the
    entry average says: after a fall the close climbs back above its short
    average while still under its long one, and a rule that bought there would
    sell again the next evening, and buy again the evening after. So the fund
    is bought only when its close is above the entry average and not below the
    exit one.

    In every other case - above the exit average and not above the entry one,
    exactly on a line, or already bought - the rule keeps what it has, fund or
    cash, and sends no order. What it has is read from the book of the
    decision, never from an attribute of this object.

    Both distances are taken on adjusted closes, as in :class:`GoldenCrossETF`,
    so a distribution paid inside a window is not read as a fall below it.

    When either signal cannot be computed - too little history, a session
    missing, a price too old - the rule keeps its positions and sends no
    order: a purchase needs both averages, since it is refused below the exit
    one, and selling because a bar is missing would be a rule nobody wrote.

    The target is executed at the next open, by the engine.
    """

    instrument_id: str = "ETF_WORLD"
    entry_sessions: int = 50
    exit_sessions: int = 100
    strategy_id: str = "moving_average_entry_exit_etf"

    def __post_init__(self) -> None:
        """Reject a configuration that cannot be computed or is another rule's."""
        require_identifier(self.instrument_id, "instrument_id")
        require_identifier(self.strategy_id, "strategy_id")
        # Built once here so that a bad length stops the construction, not the
        # first decision of a run.
        self.entry_signal()
        self.exit_signal()
        if self.entry_sessions == self.exit_sessions:
            raise ValueError(
                f"entry_sessions and exit_sessions are both {self.entry_sessions}: one "
                f"average for both sides is MovingAverageBandETF"
            )

    def entry_signal(self) -> MovingAverageTrendSignal:
        """Return ``P_t / MA_entry(t) - 1`` on adjusted closes."""
        return self._distance_to_average(self.entry_sessions)

    def exit_signal(self) -> MovingAverageTrendSignal:
        """Return ``P_t / MA_exit(t) - 1`` on adjusted closes."""
        return self._distance_to_average(self.exit_sessions)

    @staticmethod
    def _distance_to_average(sessions: int) -> MovingAverageTrendSignal:
        """Return the distance from the adjusted close to its ``sessions`` average."""
        return MovingAverageTrendSignal(
            signal_id=f"price_over_ma{sessions}",
            window_sessions=sessions,
            price_basis=PriceBasis.ADJUSTED,
        )

    def required_signals(self) -> Sequence[Signal | SignalRequest]:
        """Return the two signals this strategy needs, on the studied ETF only."""
        names = (self.instrument_id,)
        return (
            SignalRequest(signal=self.entry_signal(), instruments=names),
            SignalRequest(signal=self.exit_signal(), instruments=names),
        )

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
            Cash when the close is below its exit average; 100% of the fund
            when it is above its entry average, not below the exit one, and the
            fund is not held; the book as it stands, with no order, in every
            other case.
        """
        entry_id = self.entry_signal().signal_id
        exit_id = self.exit_signal().signal_id
        for signal_id in (entry_id, exit_id):
            if ctx.signal_status(signal_id, self.instrument_id) is not SignalStatus.OK:
                return ctx.hold_positions()
        if ctx.signal_value(exit_id, self.instrument_id) < 0.0:
            return ctx.cash()
        above_entry = ctx.signal_value(entry_id, self.instrument_id) > 0.0
        if above_entry and not ctx.portfolio.holds(self.instrument_id):
            return ctx.weights({self.instrument_id: 1.0})
        # A target of 100% restated every evening would trade the overnight drift.
        return ctx.hold_positions()
