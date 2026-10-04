"""Enter a trend progressively, as the fast average pulls away from the slow one."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.numbers import require_finite_positive, require_unit_fraction
from quant_backtester.signals.base import Signal
from quant_backtester.signals.engine import SignalRequest
from quant_backtester.signals.types import require_identifier
from quant_backtester.strategies.adaptive.inputs import SignalReader, average_cross
from quant_backtester.strategies.adaptive.rebalance import Evaluation, RuleStrategy
from quant_backtester.strategies.adaptive.rules import smooth_trend_rule


@dataclass(frozen=True, slots=True)
class SmoothMovingAverage(RuleStrategy):
    """An exposure that grows with the gap between two moving averages.

    Attributes
    ----------
    instrument_id : str
        The fund held.
    fast, slow : int
        Lengths of the two averages, in sessions.
    full_exposure_gap : float
        ``MA_fast / MA_slow - 1`` at which the fund is held at 100%.
    rebalance_band : float
        Largest gap between the fund's weight and its target that sends no
        order.
    strategy_id : str
        Name this configuration is recorded under.

    Raises
    ------
    ValueError
        If a name is empty, the fast average is not shorter than the slow one,
        the gap is not a finite positive number or the band is not a fraction.

    Notes
    -----
    ``w = clip((MA_fast / MA_slow - 1) / full_exposure_gap, 0, 1)`` on adjusted
    closes: cash while the fast average is below the slow one, half invested
    at half the gap, fully invested at the gap and beyond. The same formula
    drives entries and exits; there is no hidden hysteresis, only the common
    band. A cross that cannot be computed is a target of cash.
    """

    instrument_id: str = "ETF_WORLD"
    fast: int = 50
    slow: int = 200
    full_exposure_gap: float = 0.02
    rebalance_band: float = 0.03
    strategy_id: str = "SA3_smooth_ma"

    def __post_init__(self) -> None:
        """Reject a configuration that cannot be computed."""
        require_identifier(self.instrument_id, "instrument_id")
        require_identifier(self.strategy_id, "strategy_id")
        require_finite_positive(self.full_exposure_gap, "full_exposure_gap")
        require_unit_fraction(self.rebalance_band, "rebalance_band")
        self.signal()
        if self.fast >= self.slow:
            raise ValueError(f"fast ({self.fast}) must be shorter than slow ({self.slow})")

    def signal(self) -> Signal:
        """Return ``MA_fast / MA_slow - 1`` on the adjusted closes of the fund."""
        return average_cross(self.fast, self.slow)

    def required_signals(self) -> Sequence[Signal | SignalRequest]:
        """Return the one signal this strategy needs, on the fund only."""
        return (SignalRequest(signal=self.signal(), instruments=(self.instrument_id,)),)

    def evaluate(self, ctx: StrategyContext) -> Evaluation:
        """Return the exposure the gap between the averages stands for."""
        reader = SignalReader(ctx)
        cross = reader.value(self.signal(), self.instrument_id)
        target = smooth_trend_rule(
            self.instrument_id, cross, full_exposure_gap=self.full_exposure_gap
        )
        return Evaluation(target, reader.unusable, reader.readable)
