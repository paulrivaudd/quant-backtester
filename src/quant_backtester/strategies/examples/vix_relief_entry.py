"""Take a small position once a volatility panic eases and the fund starts to rise."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.numbers import require_unit_fraction
from quant_backtester.signals.base import Signal
from quant_backtester.signals.engine import SignalRequest
from quant_backtester.signals.types import require_identifier
from quant_backtester.strategies.adaptive.inputs import SignalReader, gauge_relief, momentum
from quant_backtester.strategies.adaptive.rebalance import Evaluation, RuleStrategy
from quant_backtester.strategies.adaptive.rules import relief_entry_rule


@dataclass(frozen=True, slots=True)
class VixReliefEntry(RuleStrategy):
    """Half of the book in a fund while the gauge is in a relief and the fund recovers.

    Attributes
    ----------
    instrument_id : str
        The fund bought.
    vix_id : str
        The published volatility index. Read, never held.
    vix_observations : int
        Published observations the peak is taken over, the latest included.
    peak_minimum : float
        The peak counts as a panic at or above this level, in the index's own
        units: 30, not 0.30.
    relief_ratio : float
        The latest level is a relief at or below this fraction of the peak.
    recovery_sessions : int
        Sessions the fund's own recovery is measured over.
    weight : float
        The position taken.
    vix_max_age_sessions : int
        Largest accepted age of the freshest index observation, in sessions of
        the reference calendar.
    rebalance_band : float
        Largest gap between the fund's weight and its target that sends no
        order.
    strategy_id : str
        Name this configuration is recorded under.

    Raises
    ------
    ValueError
        If a name is empty, a window cannot make its signal, or a number is
        not in its range.

    Notes
    -----
    ``relief = (peak >= peak_minimum) and (VIX_t <= relief_ratio * peak)`` and
    ``recovery = P_t / P_{t-k} - 1 > 0``; the fund is held at ``weight`` while
    both are true and sold as soon as one is not. The peak leaves the window
    by itself. An index too old or missing, or a recovery that cannot be
    computed, is a target of cash.

    Implied volatility is information here: no option and no variance is
    traded, and no ratio is built between an index in dollars and a fund in
    euros. A relief can come before a second fall, and there are few crises to
    learn from.
    """

    instrument_id: str = "ETF_SP500_PEA"
    vix_id: str = "VIX"
    vix_observations: int = 20
    peak_minimum: float = 30.0
    relief_ratio: float = 0.80
    recovery_sessions: int = 5
    weight: float = 0.50
    vix_max_age_sessions: int = 1
    rebalance_band: float = 0.03
    strategy_id: str = "SA9_vix_relief"

    def __post_init__(self) -> None:
        """Reject a configuration that cannot be computed or held."""
        for name in ("instrument_id", "vix_id", "strategy_id"):
            require_identifier(getattr(self, name), name)
        require_unit_fraction(self.weight, "weight")
        require_unit_fraction(self.rebalance_band, "rebalance_band")
        self.relief_signal()
        self.recovery_signal()

    def relief_signal(self) -> Signal:
        """Return whether the index has left a panic peak behind."""
        return gauge_relief(
            self.vix_observations, self.peak_minimum, self.relief_ratio, self.vix_max_age_sessions
        )

    def recovery_signal(self) -> Signal:
        """Return the fund's return over ``recovery_sessions``, nothing skipped."""
        return momentum(self.recovery_sessions, 0)

    def required_signals(self) -> Sequence[Signal | SignalRequest]:
        """Return the relief on the index and the recovery on the fund."""
        return (
            SignalRequest(signal=self.relief_signal(), instruments=(self.vix_id,)),
            SignalRequest(signal=self.recovery_signal(), instruments=(self.instrument_id,)),
        )

    def evaluate(self, ctx: StrategyContext) -> Evaluation:
        """Return the position while the relief and the recovery both hold."""
        reader = SignalReader(ctx)
        target = relief_entry_rule(
            self.instrument_id,
            reader.value(self.relief_signal(), self.vix_id),
            reader.value(self.recovery_signal(), self.instrument_id),
            weight=self.weight,
        )
        return Evaluation(target, reader.unusable)
