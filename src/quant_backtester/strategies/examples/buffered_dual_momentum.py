"""Lean progressively towards the fund with the stronger momentum."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.numbers import require_finite_positive, require_unit_fraction
from quant_backtester.signals.base import Signal
from quant_backtester.signals.engine import SignalRequest
from quant_backtester.signals.types import require_identifier
from quant_backtester.strategies.adaptive.inputs import SignalReader, momentum
from quant_backtester.strategies.adaptive.rebalance import Evaluation, RuleStrategy
from quant_backtester.strategies.adaptive.rules import dual_momentum_rule


@dataclass(frozen=True, slots=True)
class BufferedDualMomentum(RuleStrategy):
    """Two funds, weighted by the difference of their momentum scores.

    Attributes
    ----------
    first_id, second_id : str
        The two funds.
    medium_lookback, long_lookback : int
        Lookbacks of the two momenta, in sessions, the skipped ones included.
    skip_recent_sessions : int
        Most recent sessions left out of both.
    full_tilt_gap : float
        Difference of scores at which the stronger fund is at its maximum.
    neutral_weight : float
        Weight of the first fund when the scores are equal.
    tilt : float
        Largest move away from the neutral weight.
    single_weight : float
        Weight of a fund that is the only eligible one; the rest is cash.
    rebalance_band : float
        Largest gap between a weight and its target that sends no order.
    strategy_id : str
        Name this configuration is recorded under.

    Raises
    ------
    ValueError
        If a name is empty, both funds are the same, a lookback cannot make a
        momentum, or a weight is not a fraction the book could hold.

    Notes
    -----
    For each fund, ``m = P_{t-S} / P_{t-L} - 1`` on adjusted closes for the two
    lookbacks, ``score = (m_medium + m_long) / 2``, and the fund is eligible
    when its long momentum is strictly positive. With both eligible the first
    holds ``neutral + tilt * clip((score_first - score_second) / gap, -1, 1)``
    and the second the rest; with one, ``single_weight`` of it; with none,
    cash. A momentum that cannot be computed, on either fund, leaves the whole
    rule in cash.

    The long momentum needs ``long_lookback + 1`` consecutive closes: 253 with
    the default.
    """

    first_id: str = "ETF_WORLD"
    second_id: str = "ETF_SP500_PEA"
    medium_lookback: int = 126
    long_lookback: int = 252
    skip_recent_sessions: int = 21
    full_tilt_gap: float = 0.05
    neutral_weight: float = 0.50
    tilt: float = 0.25
    single_weight: float = 0.75
    rebalance_band: float = 0.03
    strategy_id: str = "SA2_dual_momentum"

    def __post_init__(self) -> None:
        """Reject a configuration that cannot be computed or held."""
        for name in ("first_id", "second_id", "strategy_id"):
            require_identifier(getattr(self, name), name)
        if self.first_id == self.second_id:
            raise ValueError(f"both funds are {self.first_id}: there is nothing to lean between")
        require_finite_positive(self.full_tilt_gap, "full_tilt_gap")
        for name in ("neutral_weight", "tilt", "single_weight", "rebalance_band"):
            require_unit_fraction(getattr(self, name), name)
        if not self.tilt <= min(self.neutral_weight, 1.0 - self.neutral_weight):
            raise ValueError(
                f"a tilt of {self.tilt} around {self.neutral_weight} leaves the range [0, 1]"
            )
        if self.medium_lookback == self.long_lookback:
            raise ValueError(f"both lookbacks are {self.long_lookback} sessions")
        self.medium_signal()
        self.long_signal()

    def medium_signal(self) -> Signal:
        """Return the medium momentum, the skipped sessions inside its lookback."""
        return momentum(self.medium_lookback, self.skip_recent_sessions)

    def long_signal(self) -> Signal:
        """Return the long momentum, the skipped sessions inside its lookback."""
        return momentum(self.long_lookback, self.skip_recent_sessions)

    def required_signals(self) -> Sequence[Signal | SignalRequest]:
        """Return the two momenta, each over both funds."""
        funds = (self.first_id, self.second_id)
        return (
            SignalRequest(signal=self.medium_signal(), instruments=funds),
            SignalRequest(signal=self.long_signal(), instruments=funds),
        )

    def evaluate(self, ctx: StrategyContext) -> Evaluation:
        """Return the two weights the momentum scores stand for."""
        reader = SignalReader(ctx)
        medium, long = self.medium_signal(), self.long_signal()
        target = dual_momentum_rule(
            self.first_id,
            self.second_id,
            first_medium=reader.value(medium, self.first_id),
            first_long=reader.value(long, self.first_id),
            second_medium=reader.value(medium, self.second_id),
            second_long=reader.value(long, self.second_id),
            full_tilt_gap=self.full_tilt_gap,
            neutral_weight=self.neutral_weight,
            tilt=self.tilt,
            single_weight=self.single_weight,
        )
        return Evaluation(target, reader.unusable)
