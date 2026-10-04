"""Hold less of a fund when its realised volatility rises."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.numbers import require_finite_positive, require_unit_fraction
from quant_backtester.signals.base import Signal
from quant_backtester.signals.engine import SignalRequest
from quant_backtester.signals.types import require_identifier
from quant_backtester.strategies.adaptive.inputs import SignalReader, volatility
from quant_backtester.strategies.adaptive.rebalance import Evaluation, RuleStrategy
from quant_backtester.strategies.adaptive.rules import volatility_control_rule


@dataclass(frozen=True, slots=True)
class RealizedVolControl(RuleStrategy):
    """An exposure scaled to an estimated risk, never above 100%.

    Attributes
    ----------
    instrument_id : str
        The fund held.
    short_returns, long_returns : int
        Daily returns in each of the two volatility estimates.
    target_volatility : float
        The estimated annualised risk aimed at, as a fraction.
    volatility_floor : float
        Smallest volatility the estimate may take.
    rebalance_band : float
        Largest gap between the fund's weight and its target that sends no
        order. It makes the risk target approximate.
    strategy_id : str
        Name this configuration is recorded under.

    Raises
    ------
    ValueError
        If a name is empty, a window cannot make a volatility, both windows
        are the same, or a number is not finite and positive.

    Notes
    -----
    ``w = min(1, target / max(vol_short, vol_long, floor))``, each volatility
    the sample standard deviation of daily log returns on adjusted closes,
    scaled by ``sqrt(252)``. Taking the larger of two estimates keeps the
    exposure from being rebuilt straight after a shock. The rule forecasts no
    direction and promises no future volatility; cash earns nothing here.
    Either volatility missing is a target of cash.
    """

    instrument_id: str = "ETF_WORLD"
    short_returns: int = 20
    long_returns: int = 60
    target_volatility: float = 0.12
    volatility_floor: float = 0.05
    rebalance_band: float = 0.03
    strategy_id: str = "SA6_vol_control"

    def __post_init__(self) -> None:
        """Reject a configuration that cannot be computed."""
        require_identifier(self.instrument_id, "instrument_id")
        require_identifier(self.strategy_id, "strategy_id")
        require_finite_positive(self.target_volatility, "target_volatility")
        require_finite_positive(self.volatility_floor, "volatility_floor")
        require_unit_fraction(self.rebalance_band, "rebalance_band")
        if self.short_returns == self.long_returns:
            raise ValueError(f"both volatility windows hold {self.long_returns} returns")
        self.short_signal()
        self.long_signal()

    def short_signal(self) -> Signal:
        """Return the volatility over the shorter window."""
        return volatility(self.short_returns)

    def long_signal(self) -> Signal:
        """Return the volatility over the longer window."""
        return volatility(self.long_returns)

    def required_signals(self) -> Sequence[Signal | SignalRequest]:
        """Return the two volatilities, both on the fund only."""
        fund = (self.instrument_id,)
        return (
            SignalRequest(signal=self.short_signal(), instruments=fund),
            SignalRequest(signal=self.long_signal(), instruments=fund),
        )

    def evaluate(self, ctx: StrategyContext) -> Evaluation:
        """Return the exposure the larger of the two volatilities stands for."""
        reader = SignalReader(ctx)
        target = volatility_control_rule(
            self.instrument_id,
            reader.value(self.short_signal(), self.instrument_id),
            reader.value(self.long_signal(), self.instrument_id),
            target_volatility=self.target_volatility,
            floor=self.volatility_floor,
        )
        return Evaluation(target, reader.unusable)
