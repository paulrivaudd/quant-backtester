"""The benchmark: hold the world fund while its close is above its 20-session average."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.numbers import require_unit_fraction
from quant_backtester.signals.base import Signal
from quant_backtester.signals.engine import SignalRequest
from quant_backtester.signals.types import require_identifier
from quant_backtester.strategies.adaptive.inputs import SignalReader, price_over_average
from quant_backtester.strategies.adaptive.rebalance import Evaluation, RuleStrategy
from quant_backtester.strategies.adaptive.rules import above_average_rule


@dataclass(frozen=True, slots=True)
class WorldMA20Benchmark(RuleStrategy):
    """All of one fund above its moving average, all cash on it or below.

    Attributes
    ----------
    instrument_id : str
        The fund held.
    window_sessions : int
        Length of the average, in sessions, the close of the decision included.
    rebalance_band : float
        Largest gap between the fund's weight and its target that sends no
        order. It only keeps a position already open from being topped up for
        a cash residue: an entry from cash and a complete exit are never inside
        it.
    strategy_id : str
        Name this configuration is recorded under.

    Raises
    ------
    ValueError
        If a name is empty, the window cannot make an average or the band is
        not a fraction of ``[0, 1]``.

    Notes
    -----
    ``w = 1 if P_t > MA_N(t) else 0`` on adjusted closes. Equality sells. A
    fund already above its average at the first valid decision is bought then:
    no fresh crossing is waited for. A window that is incomplete, or a close
    that is missing, is a target of cash.

    This is the yardstick the other rules are measured against, run on the
    same dates with the same costs. It is decided after the close and executed
    at the next open, by the engine.
    """

    instrument_id: str = "ETF_WORLD"
    window_sessions: int = 20
    rebalance_band: float = 0.03
    strategy_id: str = "SA1_std_ma20"

    def __post_init__(self) -> None:
        """Reject a configuration that cannot be computed."""
        require_identifier(self.instrument_id, "instrument_id")
        require_identifier(self.strategy_id, "strategy_id")
        require_unit_fraction(self.rebalance_band, "rebalance_band")
        self.signal()

    def signal(self) -> Signal:
        """Return ``P_t / MA_N(t) - 1`` on the adjusted closes of the fund."""
        return price_over_average(self.window_sessions, f"world_above_ma{self.window_sessions}")

    def required_signals(self) -> Sequence[Signal | SignalRequest]:
        """Return the one signal this strategy needs, on the fund only."""
        return (SignalRequest(signal=self.signal(), instruments=(self.instrument_id,)),)

    def evaluate(self, ctx: StrategyContext) -> Evaluation:
        """Return 100% of the fund above its average, cash otherwise."""
        reader = SignalReader(ctx)
        distance = reader.value(self.signal(), self.instrument_id)
        return Evaluation(above_average_rule(self.instrument_id, distance), reader.unusable)
