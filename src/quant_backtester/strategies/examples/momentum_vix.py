"""A rotation that stands aside when a gauge it never trades says so."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.numbers import require_finite
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.signals.base import Signal
from quant_backtester.signals.cross_sectional.rank import CrossSectionalRank
from quant_backtester.signals.engine import SignalRequest
from quant_backtester.signals.level.zscore import LevelZScoreSignal
from quant_backtester.signals.price.momentum import MomentumSignal
from quant_backtester.signals.types import (
    PriceBasis,
    require_identifier,
    require_positive_int,
)
from quant_backtester.strategies.base import Strategy


@dataclass(frozen=True, slots=True)
class MomentumVix(Strategy):
    """Rotate on momentum while a volatility gauge stays below a threshold.

    Attributes
    ----------
    gauge_id : str
        Instrument the gate is read from - a volatility index, a yield. It is
        never held, and it need not be tradable at all.
    lookback_sessions : int
        Sessions the momentum is measured over.
    gauge_observations : int
        Observations the gauge's z-score is standardised over. Counted in
        observations rather than sessions: nobody holds sessions for a
        published series.
    top_n : int
        How many instruments to hold when the gate is open.
    maximum : float
        The rotation runs while the gauge is at or below this, in the gauge's
        own unit - for a z-score, spreads from its own recent mean.
    flat_when_unknown : bool
        What to do when the gauge has no usable value. No default: a risk
        filter that silently becomes no filter the day its input is late is
        the kind of thing that is only noticed afterwards.
    strategy_id : str
        Name this configuration is recorded under.

    Raises
    ------
    ValueError
        If a count is not positive, the threshold is not finite, or a name is
        empty.

    Notes
    -----
    The first strategy in this project that reads two universes at one
    instant: the funds it ranks, and the gauge it reads. That is what a
    per-signal universe is for - a level signal asked about a fund is a wiring
    mistake rather than a number, and the gauge has no business being ranked
    against the funds.

    A gated day is not a day with nothing to choose from, and the record keeps
    them apart: standing aside passes the selection it stood aside from, so
    ``considered`` stays above zero.
    """

    gauge_id: str = "VIX"
    lookback_sessions: int = 60
    gauge_observations: int = 60
    top_n: int = 2
    maximum: float = 1.5
    flat_when_unknown: bool = True
    strategy_id: str = "momentum_vix"

    def __post_init__(self) -> None:
        """Reject a configuration that cannot be computed."""
        require_identifier(self.gauge_id, "gauge_id")
        require_identifier(self.strategy_id, "strategy_id")
        require_positive_int(self.lookback_sessions, "lookback_sessions")
        require_positive_int(self.gauge_observations, "gauge_observations")
        require_positive_int(self.top_n, "top_n")
        require_finite(self.maximum, "maximum")
        if not isinstance(self.flat_when_unknown, bool):
            raise ValueError(
                f"flat_when_unknown must be said explicitly as a boolean, got "
                f"{self.flat_when_unknown!r}"
            )

    @property
    def rank_id(self) -> str:
        """Return the id of the ranking this strategy reads."""
        return f"momentum_{self.lookback_sessions}d_rank"

    @property
    def gate_id(self) -> str:
        """Return the id of the gauge's z-score."""
        return f"{self.gauge_id.lower()}_z_{self.gauge_observations}o"

    def required_signals(self) -> Sequence[Signal | SignalRequest]:
        """Return the momentum, its ranking, and the gauge over its own universe."""
        momentum = MomentumSignal(
            signal_id=f"momentum_{self.lookback_sessions}d",
            lookback_sessions=self.lookback_sessions,
            price_basis=PriceBasis.ADJUSTED,
        )
        return (
            momentum,
            CrossSectionalRank(signal_id=self.rank_id, source=momentum),
            SignalRequest(
                LevelZScoreSignal(
                    signal_id=self.gate_id, window_observations=self.gauge_observations
                ),
                (self.gauge_id,),
            ),
        )

    def decide(self, ctx: StrategyContext) -> TargetAllocation:
        """Hold the best-ranked funds while the gauge allows it."""
        selected = ctx.top(self.rank_id, self.top_n)
        gauge = ctx.signal_value_or_none(self.gate_id, self.gauge_id)
        unreadable = gauge is None and self.flat_when_unknown
        if unreadable or (gauge is not None and gauge > self.maximum):
            return ctx.cash(among=selected)
        return ctx.equal_weight(selected, count=self.top_n)
