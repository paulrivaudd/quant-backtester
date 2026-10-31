"""SA16: a growth fund and gold held together, weighted by a declared budget of risk.

Every week, at 23:00 Paris, the rule estimates the volatility of each fund on
the euro closes the book holds and gives each a weight inversely proportional
to it, scaled by the share of the risk it is budgeted: with a budget ``b`` for
the growth fund, ``w_growth ~ b / vol_growth`` and ``w_gold ~ (1 - b) / vol_gold``,
the two adding up to the whole book. Nothing forecasts a direction. When the
prices move the weights apart, the band sends the book back to its target: the
rule sells what rose against the other and buys what fell, and in an equity
crash in which gold holds, it buys equity.

The volatility is the span-scaled estimator: a session the provider failed to
serve does not blind it for half a year. A decision that cannot read an input
keeps the book. Adjusted closes are restated provider histories.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from quant_backtester.backtest.context import Selection, StrategyContext
from quant_backtester.numbers import require_finite_positive, require_unit_fraction
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.signals.base import Signal
from quant_backtester.signals.engine import SignalRequest
from quant_backtester.signals.risk.span_volatility import SpanScaledVolatilitySignal
from quant_backtester.signals.types import (
    PriceBasis,
    SignalStatus,
    require_identifier,
    require_non_negative_int,
    require_positive_int,
)
from quant_backtester.strategies.adaptive.inputs import SignalReader, merged_requests
from quant_backtester.strategies.adaptive.rebalance import settle
from quant_backtester.strategies.base import Strategy


@dataclass(frozen=True, slots=True)
class BudgetPlan:
    """What one decision read and the target it computed.

    Attributes
    ----------
    volatilities : Mapping[str, float]
        Annualised volatility estimate of each fund, floored.
    weights : Mapping[str, float]
        Complete target; empty when an input could not be read.
    unusable : Mapping[str, SignalStatus]
        Why each unreadable input was unreadable.
    readable : int
        Funds read through usable signals.
    """

    volatilities: Mapping[str, float]
    weights: Mapping[str, float]
    unusable: Mapping[str, SignalStatus]
    readable: int

    @property
    def complete(self) -> bool:
        """Return whether every input was read."""
        return not self.unusable


@dataclass(frozen=True, slots=True)
class SA16RiskBudget(Strategy):
    """Hold a growth fund and gold at inverse-volatility weights scaled by a risk budget.

    Parameters
    ----------
    growth_id : str
        Growth fund, ``ETF_US_TECH`` (QDVE.DE, the core of SA15) by default.
    hedge_id : str
        Diversifying fund, ``ETF_GOLD`` (Xetra-Gold ETC).
    growth_risk_budget : float
        Share ``b`` of the risk given to the growth fund, in ``(0, 1)``; with
        correlation ignored, ``b = 0.75`` gives it three quarters of the
        stand-alone risk of the book.
    volatility_returns : int
        Number of span-scaled daily log returns of each volatility estimate.
    max_span_sessions : int
        Largest number of venue sessions one return may span (see
        ``SpanScaledVolatilitySignal``).
    volatility_floor : float
        Lower bound of an annualised volatility, against a division by a
        series that did not move.
    rebalance_band : float
        Largest gap between a held weight and its target that sends no order.
    max_age_sessions : int
        Largest age of a fund's freshest close, in Paris sessions.
    strategy_id : str
        Identity of the strategy in its results.

    Notes
    -----
    Long only, fully invested, no leverage: the two weights add up to one
    before whole units and costs. Correlation is not estimated; the weights
    are the "naive" risk-parity form of a risk budget.
    """

    growth_id: str = "ETF_US_TECH"
    hedge_id: str = "ETF_GOLD"
    growth_risk_budget: float = 0.75
    volatility_returns: int = 126
    max_span_sessions: int = 3
    volatility_floor: float = 0.05
    rebalance_band: float = 0.05
    max_age_sessions: int = 1
    strategy_id: str = "SA16"

    def __post_init__(self) -> None:
        """Refuse a configuration that is not a budget of two distinct funds."""
        for name in ("growth_id", "hedge_id", "strategy_id"):
            require_identifier(getattr(self, name), name)
        if self.growth_id == self.hedge_id:
            raise ValueError("the growth fund and the hedge must be distinct")
        require_unit_fraction(self.growth_risk_budget, "growth_risk_budget")
        if not 0.0 < self.growth_risk_budget < 1.0:
            raise ValueError("the risk budget of the growth fund lies strictly in (0, 1)")
        require_positive_int(self.volatility_returns, "volatility_returns")
        require_positive_int(self.max_span_sessions, "max_span_sessions")
        require_finite_positive(self.volatility_floor, "volatility_floor")
        require_unit_fraction(self.rebalance_band, "rebalance_band")
        require_non_negative_int(self.max_age_sessions, "max_age_sessions")
        self.validate()

    def volatility(self) -> Signal:
        """Return the span-scaled volatility both funds are measured with."""
        return SpanScaledVolatilitySignal(
            signal_id=f"sa16_span_volatility_{self.volatility_returns}r",
            window_returns=self.volatility_returns,
            annualization=252,
            max_span_sessions=self.max_span_sessions,
            price_basis=PriceBasis.ADJUSTED,
            max_age_sessions=self.max_age_sessions,
        )

    def required_signals(self) -> Sequence[Signal | SignalRequest]:
        """Declare one volatility per fund."""
        return merged_requests([SignalRequest(self.volatility(), (self.growth_id, self.hedge_id))])

    def plan(self, ctx: StrategyContext) -> BudgetPlan:
        """Compute the budgeted target of one evening, or why it cannot be had."""
        reader = SignalReader(ctx)
        volatilities: dict[str, float] = {}
        for name in (self.growth_id, self.hedge_id):
            value = reader.value(self.volatility(), name)
            if value is not None and math.isfinite(value):
                volatilities[name] = max(self.volatility_floor, value)
        weights: dict[str, float] = {}
        if len(volatilities) == 2 and not reader.unusable:
            raw = {
                self.growth_id: self.growth_risk_budget / volatilities[self.growth_id],
                self.hedge_id: (1.0 - self.growth_risk_budget) / volatilities[self.hedge_id],
            }
            total = math.fsum(raw.values())
            weights = {name: value / total for name, value in raw.items() if name in ctx.universe}
        return BudgetPlan(
            volatilities=MappingProxyType(volatilities),
            weights=MappingProxyType(weights),
            unusable=MappingProxyType(reader.unusable),
            readable=reader.readable,
        )

    def decide(self, ctx: StrategyContext) -> TargetAllocation:
        """Send the target through the band, or keep the book when an input is unreadable."""
        plan = self.plan(ctx)
        if not plan.complete:
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
