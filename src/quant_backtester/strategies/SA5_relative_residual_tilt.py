"""Overweight the fund that lately lagged what the other one explains of it."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.numbers import require_finite_positive, require_unit_fraction
from quant_backtester.signals.base import Signal
from quant_backtester.signals.engine import SignalRequest
from quant_backtester.signals.types import require_identifier
from quant_backtester.strategies.adaptive.inputs import SignalReader, relative_residual
from quant_backtester.strategies.adaptive.rebalance import Evaluation, RuleStrategy
from quant_backtester.strategies.adaptive.rules import relative_tilt_rule


@dataclass(frozen=True, slots=True)
class RelativeResidualTilt(RuleStrategy):
    """Two funds around an even split, tilted towards the one that lagged the other.

    Attributes
    ----------
    first_id : str
        ``A``, the fund whose residual is measured.
    second_id : str
        ``B``, the fund whose returns explain it.
    estimation_returns : int
        Daily returns the regression is fitted on, ending before the recent ones.
    recent_returns : int
        Latest returns whose residuals are summed.
    minimum_r_squared : float
        Below it the fit is not leaned on, and the split stays neutral.
    full_tilt_z : float
        Normalised residual at which the tilt is complete.
    neutral_weight : float
        Weight of ``A`` without a residual to act on.
    tilt : float
        Largest move away from the neutral weight.
    rebalance_band : float
        Largest gap between a weight and its target that sends no order.
    strategy_id : str
        Name this configuration is recorded under.

    Raises
    ------
    ValueError
        If a name is empty, both funds are the same, a window cannot make the
        signal, or a weight is not a fraction the book could hold.

    Notes
    -----
    ``w_A = neutral + tilt * clip(z / full_tilt_z, -1, 1)`` and ``w_B`` the
    rest, with ``z`` the value of
    :class:`~quant_backtester.signals.cross_asset.relative_residual.RelativeResidualSignal`:
    positive when ``A`` lagged. A non-positive beta or a weak fit gives the
    neutral split; a residual with no value at all - a window missing, a
    variance of zero - gives cash.

    This stays a long book of two share funds: nothing hedges the market, and
    nothing here shows the two are cointegrated. Only what the tilt adds to
    the even split is being tested.
    """

    first_id: str = "ETF_WORLD"
    second_id: str = "ETF_SP500_PEA"
    estimation_returns: int = 126
    recent_returns: int = 5
    minimum_r_squared: float = 0.50
    full_tilt_z: float = 2.0
    neutral_weight: float = 0.50
    tilt: float = 0.25
    rebalance_band: float = 0.03
    strategy_id: str = "SA5_relative_tilt"

    def __post_init__(self) -> None:
        """Reject a configuration that cannot be computed or held."""
        for name in ("first_id", "second_id", "strategy_id"):
            require_identifier(getattr(self, name), name)
        if self.first_id == self.second_id:
            raise ValueError(f"both funds are {self.first_id}: a fund has no residual on itself")
        require_finite_positive(self.full_tilt_z, "full_tilt_z")
        for name in ("neutral_weight", "tilt", "rebalance_band"):
            require_unit_fraction(getattr(self, name), name)
        if not self.tilt <= min(self.neutral_weight, 1.0 - self.neutral_weight):
            raise ValueError(
                f"a tilt of {self.tilt} around {self.neutral_weight} leaves the range [0, 1]"
            )
        self.signal()

    def signal(self) -> Signal:
        """Return the normalised recent residual of a fund against the second one."""
        return relative_residual(
            self.second_id, self.estimation_returns, self.recent_returns, self.minimum_r_squared
        )

    def required_signals(self) -> Sequence[Signal | SignalRequest]:
        """Return the residual, asked about the first fund."""
        return (SignalRequest(signal=self.signal(), instruments=(self.first_id,)),)

    def evaluate(self, ctx: StrategyContext) -> Evaluation:
        """Return the two weights the residual stands for."""
        reader = SignalReader(ctx)
        target = relative_tilt_rule(
            self.first_id,
            self.second_id,
            reader.value(self.signal(), self.first_id),
            full_tilt_z=self.full_tilt_z,
            neutral_weight=self.neutral_weight,
            tilt=self.tilt,
        )
        return Evaluation(target, reader.unusable, reader.readable)
