"""Buy an unusual fall moderately, while the long trend is still up."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.numbers import require_finite, require_finite_positive, require_unit_fraction
from quant_backtester.signals.base import Signal
from quant_backtester.signals.engine import SignalRequest
from quant_backtester.signals.types import require_identifier
from quant_backtester.strategies.adaptive.inputs import SignalReader, price_over_average, pullback
from quant_backtester.strategies.adaptive.rebalance import Evaluation, RuleStrategy
from quant_backtester.strategies.adaptive.rules import pullback_rule


@dataclass(frozen=True, slots=True)
class TrendFilteredPullback(RuleStrategy):
    """A capped position in a fund that fell unusually, above its long average only.

    Attributes
    ----------
    instrument_id : str
        The fund held.
    reference_returns : int
        Daily returns the standard deviation is taken over, ending before the
        recent move.
    recent_sessions : int
        Length of the fall measured, in sessions.
    trend_sessions : int
        Length of the long average the close must be above.
    maximum_weight : float
        Largest position: a deeper fall does not buy more.
    entry_z : float
        Normalised fall at or below which nothing is held.
    z_range : float
        Width over which the position grows from zero to its maximum.
    rebalance_band : float
        Largest gap between the fund's weight and its target that sends no
        order.
    strategy_id : str
        Name this configuration is recorded under.

    Raises
    ------
    ValueError
        If a name is empty, a window cannot make its signal, or a number is
        not finite or not in its range.

    Notes
    -----
    ``z = -ln(P_t / P_{t-k}) / (s * sqrt(k))`` with ``s`` the sample standard
    deviation of the ``reference_returns`` daily log returns ending at
    ``t - k``, and ``w = maximum_weight * clip((z - entry_z) / z_range, 0, 1)``,
    set to zero when ``P_t <= MA_trend``. The position shrinks as the signal
    fades; no holding period is imposed. Either signal missing is a target of
    cash.

    With the defaults the pullback needs 66 consecutive closes and the trend
    200.
    """

    instrument_id: str = "ETF_WORLD"
    reference_returns: int = 60
    recent_sessions: int = 5
    trend_sessions: int = 200
    maximum_weight: float = 0.50
    entry_z: float = 0.50
    z_range: float = 1.00
    rebalance_band: float = 0.03
    strategy_id: str = "SA4_pullback"

    def __post_init__(self) -> None:
        """Reject a configuration that cannot be computed or held."""
        require_identifier(self.instrument_id, "instrument_id")
        require_identifier(self.strategy_id, "strategy_id")
        require_unit_fraction(self.maximum_weight, "maximum_weight")
        require_unit_fraction(self.rebalance_band, "rebalance_band")
        require_finite(self.entry_z, "entry_z")
        require_finite_positive(self.z_range, "z_range")
        self.pullback_signal()
        self.trend_signal()

    def pullback_signal(self) -> Signal:
        """Return the recent fall in the standard deviations of the returns before it."""
        return pullback(self.reference_returns, self.recent_sessions)

    def trend_signal(self) -> Signal:
        """Return ``P_t / MA_N(t) - 1`` for the long average."""
        return price_over_average(self.trend_sessions)

    def required_signals(self) -> Sequence[Signal | SignalRequest]:
        """Return the pullback and the trend, both on the fund only."""
        fund = (self.instrument_id,)
        return (
            SignalRequest(signal=self.pullback_signal(), instruments=fund),
            SignalRequest(signal=self.trend_signal(), instruments=fund),
        )

    def caps(self) -> Mapping[str, float]:
        """Return the cap on the fund: the band does not hold a larger position."""
        return {self.instrument_id: self.maximum_weight}

    def evaluate(self, ctx: StrategyContext) -> Evaluation:
        """Return the position the fall stands for, zero below the long average."""
        reader = SignalReader(ctx)
        target = pullback_rule(
            self.instrument_id,
            reader.value(self.pullback_signal(), self.instrument_id),
            reader.value(self.trend_signal(), self.instrument_id),
            maximum_weight=self.maximum_weight,
            entry_z=self.entry_z,
            z_range=self.z_range,
        )
        return Evaluation(target, reader.unusable, reader.readable)
