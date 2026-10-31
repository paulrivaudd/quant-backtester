"""SA16: an equity sleeve sized by the trend of its market, and a hedge sized by its own.

Every evening at 23:00 Paris the rule reads the endpoint returns of an equity
gauge over several horizons - by default the Nasdaq-100 index at its New York
close, published before the decision and served without the Xetra gaps of the
funds - and holds the equity fund at the fraction of those horizons that are
strictly positive. What the equity sleeve leaves is offered to a hedge fund, by
default the Xetra-Gold ETC, at the fraction of its own horizons that are
positive, measured on the euro series the book actually holds. What is still
left goes to the euro money-market fund when its recent return is positive,
and stays in cash otherwise.

No model is fitted and no state is kept: the weights are a function of the
evening snapshot and of the book. A decision that cannot read every input it
declares keeps the book as it stands and sends no order, with the reason
recorded: a session a provider failed to serve is not a signal to sell.
Adjusted closes are restated provider histories, not point-in-time vintages.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from quant_backtester.backtest.context import Selection, StrategyContext
from quant_backtester.numbers import require_unit_fraction
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.signals.base import Signal
from quant_backtester.signals.engine import SignalRequest
from quant_backtester.signals.price.endpoint_momentum import EndpointMomentumSignal
from quant_backtester.signals.types import (
    SignalStatus,
    require_identifier,
    require_non_negative_int,
    require_positive_int,
)
from quant_backtester.strategies.adaptive.inputs import SignalReader, merged_requests
from quant_backtester.strategies.adaptive.rebalance import settle
from quant_backtester.strategies.base import Strategy


@dataclass(frozen=True, slots=True)
class RegimePlan:
    """What one decision read and the complete target it computed.

    Attributes
    ----------
    equity_score : float | None
        Fraction of the gauge's horizons with a strictly positive return;
        ``None`` when one of them could not be read.
    hedge_score : float | None
        The same fraction for the hedge fund's own euro series; zero when the
        strategy has no hedge.
    carry : float | None
        Return of the money-market fund over its declared horizon.
    weights : Mapping[str, float]
        Complete target, cash being what the weights leave.
    unusable : Mapping[str, SignalStatus]
        Why each input that could not be read could not.
    readable : int
        Tradable instruments of the universe read through usable signals.
    """

    equity_score: float | None
    hedge_score: float | None
    carry: float | None
    weights: Mapping[str, float]
    unusable: Mapping[str, SignalStatus]
    readable: int

    @property
    def complete(self) -> bool:
        """Return whether every declared input was read."""
        return not self.unusable


@dataclass(frozen=True, slots=True)
class SA16RegimeAllocation(Strategy):
    """Hold equity at its gauge's trend breadth; offer the rest to a trending hedge.

    Parameters
    ----------
    equity_id : str
        Tradable equity fund, ``ETF_NASDAQ`` (SXRV.DE) by default.
    gauge_id : str
        Series whose trend sizes the equity sleeve; the fund itself, or an
        index read as information only (``NDX``, New York close).
    trend_lookbacks : tuple[int, ...]
        Horizons, in sessions of the gauge's own venue, of the endpoint
        returns ``P[t] / P[t-L] - 1``; the equity weight is the share of them
        that is strictly positive, so four horizons give steps of 25 points.
    hedge_id : str | None
        Tradable fund offered what the equity sleeve leaves; ``None`` sends it
        straight to the money-market fund (the ablation of the hedge).
    hedge_lookbacks : tuple[int, ...]
        Horizons of the hedge's own trend breadth, on the fund it holds.
    monetary_id : str
        Euro money-market fund holding what the hedge leaves.
    monetary_lookback : int
        Horizon of the money-market return that must be strictly positive for
        the fund to be held; cash otherwise (negative euro rates, 2019-2022).
    rebalance_band : float
        Largest gap between a held weight and its target that sends no order;
        a complete exit and an entry larger than the band are always sent.
    max_age_sessions : int
        Largest age, in Paris sessions, of the freshest close of any input: a
        New York holiday leaves the index one session old.
    strategy_id : str
        Identity of the strategy in its results.

    Notes
    -----
    All inputs are read at the decision instant only; endpoint dates are
    exact sessions of each series' own calendar, so a missing intermediate
    bar changes nothing, and a missing endpoint makes that input unreadable.
    An unreadable input keeps the book unchanged for that decision.
    """

    equity_id: str = "ETF_NASDAQ"
    gauge_id: str = "NDX"
    trend_lookbacks: tuple[int, ...] = (21, 63, 126, 252)
    hedge_id: str | None = "ETF_GOLD"
    hedge_lookbacks: tuple[int, ...] = (21, 63, 126, 252)
    monetary_id: str = "ETF_MONETARY_EUR"
    monetary_lookback: int = 21
    rebalance_band: float = 0.10
    max_age_sessions: int = 1
    strategy_id: str = "SA16"

    def __post_init__(self) -> None:
        """Freeze the horizons and refuse an ambiguous configuration."""
        for name in ("trend_lookbacks", "hedge_lookbacks"):
            value = getattr(self, name)
            if isinstance(value, str):
                raise ValueError(f"{name} must be a sequence of sessions, not a string")
            object.__setattr__(self, name, tuple(value))
            if not getattr(self, name) or len(set(getattr(self, name))) != len(value):
                raise ValueError(f"{name} needs distinct horizons")
            for window in getattr(self, name):
                require_positive_int(window, f"a horizon of {name}")
        for name in ("equity_id", "gauge_id", "monetary_id", "strategy_id"):
            require_identifier(getattr(self, name), name)
        if self.hedge_id is not None:
            require_identifier(self.hedge_id, "hedge_id")
        funds = (self.equity_id, self.hedge_id, self.monetary_id)
        if len(set(funds)) != len(funds):
            raise ValueError("equity, hedge and money-market funds must be distinct")
        require_positive_int(self.monetary_lookback, "monetary_lookback")
        require_non_negative_int(self.max_age_sessions, "max_age_sessions")
        require_unit_fraction(self.rebalance_band, "rebalance_band")
        self.validate()

    def momentum(self, sessions: int) -> Signal:
        """Return the endpoint return over ``sessions`` on adjusted closes."""
        return EndpointMomentumSignal(
            signal_id=f"sa16_endpoint_{sessions}s",
            lookback_sessions=sessions,
            max_age_sessions=self.max_age_sessions,
        )

    def required_signals(self) -> Sequence[Signal | SignalRequest]:
        """Declare the gauge's, the hedge's and the money-market returns."""
        requests = [SignalRequest(self.momentum(L), (self.gauge_id,)) for L in self.trend_lookbacks]
        if self.hedge_id is not None:
            requests += [
                SignalRequest(self.momentum(L), (self.hedge_id,)) for L in self.hedge_lookbacks
            ]
        requests.append(SignalRequest(self.momentum(self.monetary_lookback), (self.monetary_id,)))
        return merged_requests(requests)

    def _breadth(self, reader: SignalReader, name: str, lookbacks: tuple[int, ...]) -> float | None:
        """Return the share of horizons with a strictly positive return, or ``None``."""
        positive = 0
        for window in lookbacks:
            value = reader.value(self.momentum(window), name)
            if value is None or not math.isfinite(value):
                return None
            positive += value > 0.0
        return positive / len(lookbacks)

    def plan(self, ctx: StrategyContext) -> RegimePlan:
        """Compute the complete target of one evening, or why it cannot be had."""
        reader = SignalReader(ctx)
        equity = self._breadth(reader, self.gauge_id, self.trend_lookbacks)
        hedge = (
            0.0
            if self.hedge_id is None
            else self._breadth(reader, self.hedge_id, self.hedge_lookbacks)
        )
        carry = reader.value(self.momentum(self.monetary_lookback), self.monetary_id)
        weights: dict[str, float] = {}
        if equity is not None and hedge is not None and carry is not None:
            if equity > 0.0 and self.equity_id in ctx.universe:
                weights[self.equity_id] = equity
            hedge_weight = (1.0 - equity) * hedge
            if hedge_weight > 0.0 and self.hedge_id is not None and self.hedge_id in ctx.universe:
                weights[self.hedge_id] = hedge_weight
            residual = 1.0 - math.fsum(weights.values())
            if residual > 1e-12 and carry > 0.0 and self.monetary_id in ctx.universe:
                weights[self.monetary_id] = residual
        return RegimePlan(
            equity_score=equity,
            hedge_score=hedge,
            carry=carry,
            weights=MappingProxyType(weights),
            unusable=MappingProxyType(reader.unusable),
            readable=reader.readable,
        )

    def decide(self, ctx: StrategyContext) -> TargetAllocation:
        """Send the target through the band, or keep the book when an input is unreadable."""
        plan = self.plan(ctx)
        if not plan.complete:
            # The lines kept are what the decision stands among, as in ``settle``.
            considered = max(plan.readable, len(ctx.portfolio.weights))
            return ctx.hold_positions(
                among=Selection(names=(), considered=considered, skipped=plan.unusable)
            )
        return settle(
            ctx,
            plan.weights,
            band=self.rebalance_band,
            unusable=plan.unusable,
            readable=plan.readable,
        )
