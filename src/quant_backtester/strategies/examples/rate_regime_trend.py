"""A trend rule that buys a panic only while bonds still hedge shares."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.numbers import require_finite
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.signals.base import Signal
from quant_backtester.signals.cross_asset.correlation import ReturnLevelCorrelationSignal
from quant_backtester.signals.engine import SignalRequest
from quant_backtester.signals.level.zscore import LevelZScoreSignal
from quant_backtester.signals.price.trend import MovingAverageTrendSignal
from quant_backtester.signals.types import (
    PriceBasis,
    SignalStatus,
    require_identifier,
    require_non_negative_int,
)
from quant_backtester.strategies.base import Strategy


@dataclass(frozen=True, slots=True)
class RateRegimeTrend(Strategy):
    """Hold a fund above its long average, and below it only on a hedged panic.

    Attributes
    ----------
    instrument_id : str
        The fund held, and the one whose trend is read.
    equity_id : str
        The share index whose returns are set against the yield: the market
        the regime is a regime of. It is read, never held.
    rate_id : str
        The published yield.
    stress_id : str
        The published volatility index.
    trend_sessions : int
        Length of the average the fund's close is compared with, in sessions.
    correlation_pairs : int
        Paired moves the share-yield correlation is taken over.
    stress_observations : int
        Observations the volatility index is standardised over.
    stress_minimum : float
        A panic is a volatility index more than this many standard deviations
        above its own recent mean.
    regime_max_age_sessions : int
        Largest accepted age of the freshest index close or yield, in sessions
        of the reference calendar.
    stress_max_age_sessions : int
        Largest accepted age of the freshest volatility observation.
    strategy_id : str
        Name this configuration is recorded under.

    Raises
    ------
    ValueError
        If a name is empty, a length cannot make its signal - checked by the
        signals, at construction - an age is not a non-negative integer or the
        threshold is not finite.

    Notes
    -----
    Three questions, asked after the close, in this order.

    Is the fund above its average? Then it is held: a rising market needs no
    other reason.

    Otherwise, do shares and yields move together - a positive correlation,
    the regime in which a fall in shares sends money into bonds - **and** is
    the volatility index in a panic? Then the fund is held all the same: that
    kind of fall has tended to be bought back, and a trend rule sells it at the
    bottom.

    Otherwise the book is cash. Shares falling while yields rise is a fall
    nobody is hedged against, and a fall without a panic is a slow one; the
    trend rule is right about both.

    Below the average, a regime or a panic that cannot be read is not a panic
    in a hedged regime: the book is cash. When the trend itself cannot be read
    the rule keeps what it has and sends no order, as the other trend rules of
    this package do.

    The fund is bought only when it is not held: a target of 100% restated
    every evening would trade the overnight drift. What is held is read from
    the book of the decision, never from an attribute of this object.

    The target is executed at the next open, by the engine.
    """

    instrument_id: str
    equity_id: str
    rate_id: str
    stress_id: str
    trend_sessions: int
    correlation_pairs: int
    stress_observations: int
    stress_minimum: float
    regime_max_age_sessions: int
    stress_max_age_sessions: int
    strategy_id: str = "rate_regime_trend"

    def __post_init__(self) -> None:
        """Reject a configuration that cannot be computed."""
        for name in ("instrument_id", "equity_id", "rate_id", "stress_id", "strategy_id"):
            require_identifier(getattr(self, name), name)
        require_finite(self.stress_minimum, "stress_minimum")
        require_non_negative_int(self.regime_max_age_sessions, "regime_max_age_sessions")
        require_non_negative_int(self.stress_max_age_sessions, "stress_max_age_sessions")
        # Built once here so that a bad length stops the construction, not the
        # first decision of a run.
        self.trend_signal()
        self.regime_signal()
        self.stress_signal()

    def trend_signal(self) -> MovingAverageTrendSignal:
        """Return ``P_t / MA_N(t) - 1`` on the adjusted closes of the fund."""
        return MovingAverageTrendSignal(
            signal_id=f"price_over_ma{self.trend_sessions}",
            window_sessions=self.trend_sessions,
            price_basis=PriceBasis.ADJUSTED,
        )

    def regime_signal(self) -> ReturnLevelCorrelationSignal:
        """Return the correlation of the index's returns with the yield's changes."""
        return ReturnLevelCorrelationSignal(
            signal_id=f"{self.equity_id.lower()}_{self.rate_id.lower()}_corr_{self.correlation_pairs}p",
            level_id=self.rate_id,
            window_pairs=self.correlation_pairs,
            price_basis=PriceBasis.ADJUSTED,
            max_age_sessions=self.regime_max_age_sessions,
        )

    def stress_signal(self) -> LevelZScoreSignal:
        """Return the volatility index against its own recent mean, in standard deviations."""
        return LevelZScoreSignal(
            signal_id=f"{self.stress_id.lower()}_z_{self.stress_observations}o",
            window_observations=self.stress_observations,
            max_age_sessions=self.stress_max_age_sessions,
        )

    def required_signals(self) -> Sequence[Signal | SignalRequest]:
        """Return the three signals, each over the one instrument it is read on."""
        return (
            SignalRequest(signal=self.trend_signal(), instruments=(self.instrument_id,)),
            SignalRequest(signal=self.regime_signal(), instruments=(self.equity_id,)),
            SignalRequest(signal=self.stress_signal(), instruments=(self.stress_id,)),
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
            100% of the fund when it is not held and either its close is above
            its average or a panic falls in a hedged regime; cash below the
            average otherwise; the book as it stands, with no order, when the
            fund is already held and stays so, or when the trend cannot be read.
        """
        trend_id = self.trend_signal().signal_id
        status = ctx.signal_status(trend_id, self.instrument_id)
        among = ctx.considering({self.instrument_id: status})
        if status is not SignalStatus.OK:
            return ctx.hold_positions(among=among)
        rising = ctx.signal_value(trend_id, self.instrument_id) > 0.0
        if not rising and not self._hedged_panic(ctx):
            return ctx.cash(among=among)
        if ctx.portfolio.holds(self.instrument_id):
            return ctx.hold_positions(among=among)
        return ctx.weights({self.instrument_id: 1.0}, among=among)

    def _hedged_panic(self, ctx: StrategyContext) -> bool:
        """Return whether shares move with yields and the volatility index is in a panic."""
        regime = ctx.signal_value_or_none(self.regime_signal().signal_id, self.equity_id)
        stress = ctx.signal_value_or_none(self.stress_signal().signal_id, self.stress_id)
        if regime is None or stress is None:
            return False
        return regime > 0.0 and stress > self.stress_minimum
