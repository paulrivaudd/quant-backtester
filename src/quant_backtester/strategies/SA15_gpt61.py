"""Diversified dual momentum with empty selection slots and a conservative risk limit.

Signals consume adjusted closes available at the evening decision timestamp.
Orders execute through the engine at the following executable open. Adjusted
prices may contain provider restatements, not historical provider vintages.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.numbers import (
    require_finite_non_negative,
    require_finite_positive,
    require_unit_fraction,
)
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.signals.base import Signal
from quant_backtester.signals.engine import SignalRequest
from quant_backtester.signals.price.momentum import MomentumSignal
from quant_backtester.signals.price.trend import MovingAverageTrendSignal
from quant_backtester.signals.risk.volatility import RealizedVolatilitySignal
from quant_backtester.signals.types import (
    PriceBasis,
    SignalStatus,
    require_identifier,
    require_non_negative_int,
    require_positive_int,
)
from quant_backtester.strategies.adaptive.inputs import SignalReader, merged_requests
from quant_backtester.strategies.adaptive.rebalance import settle
from quant_backtester.strategies.adaptive.rules import conservative_volatility, risk_scale
from quant_backtester.strategies.base import Strategy


def weighted_momentum(momenta: Sequence[float | None], weights: Sequence[float]) -> float | None:
    """Return a weighted mean, or no score when a mandatory return is missing.

    Parameters
    ----------
    momenta : Sequence[float | None]
        Backward-looking returns as fractions, available at the decision.
    weights : Sequence[float]
        Nonnegative weights with a positive sum; zero weights ignore inputs.

    Returns
    -------
    float | None
        Mean in return units, or ``None`` for a missing mandatory return.

    Raises
    ------
    ValueError
        If vector lengths differ or the importance weights are invalid.
    """
    if not weights or len(momenta) != len(weights):
        raise ValueError("momenta and weights must have the same positive length")
    for weight in weights:
        require_finite_non_negative(weight, "a momentum weight")
    largest = max(weights)
    if largest <= 0.0:
        raise ValueError("at least one momentum weight must be positive")
    normalized = [weight / largest for weight in weights]
    denominator = math.fsum(normalized)
    terms: list[float] = []
    for value, weight in zip(momenta, normalized, strict=True):
        if weight == 0.0:
            continue
        if value is None or not math.isfinite(value):
            return None
        terms.append(value * (weight / denominator))
    return math.fsum(terms)


def rotation_weights(
    scores: Mapping[str, float],
    volatilities: Mapping[str, float],
    *,
    top_k: int,
    volatility_power: float,
    renormalize_active: bool,
    budget: float = 1.0,
) -> dict[str, float]:
    """Allocate occupied momentum slots by inverse volatility.

    Parameters
    ----------
    scores : Mapping[str, float]
        Scores after direction filters; ties use identifier order.
    volatilities : Mapping[str, float]
        Positive annualized estimates known at the same decision instant.
    top_k : int
        Number of slots; missing slots leave their capital defensive.
    volatility_power : float
        Exponent of inverse volatility; zero gives equal occupied weights.
    renormalize_active : bool
        Allow occupied slots to consume the entire tactical budget.
    budget : float
        Tactical capital, as a fraction of portfolio equity.

    Returns
    -------
    dict[str, float]
        Positive weights totalling ``budget * min(eligible, top_k) / top_k``
        unless occupied slots are explicitly renormalized.
    """
    require_positive_int(top_k, "top_k")
    require_finite_non_negative(volatility_power, "volatility_power")
    require_unit_fraction(budget, "budget")
    if not isinstance(renormalize_active, bool):
        raise ValueError("renormalize_active must be True or False")
    selected = sorted(
        (
            name
            for name, score in scores.items()
            if math.isfinite(score)
            and score > 0.0
            and name in volatilities
            and math.isfinite(volatilities[name])
            and volatilities[name] > 0.0
        ),
        key=lambda name: (-scores[name], name),
    )[:top_k]
    if not selected or budget == 0.0:
        return {}
    occupied_budget = budget * (1.0 if renormalize_active else len(selected) / top_k)
    # Relative log volatility keeps exponentiation bounded for large powers.
    smallest_log = min(math.log(volatilities[name]) for name in selected)
    inverse = {
        name: math.exp(-volatility_power * (math.log(volatilities[name]) - smallest_log))
        for name in selected
    }
    total = math.fsum(inverse.values())
    return {name: occupied_budget * value / total for name, value in inverse.items() if value > 0.0}


@dataclass(frozen=True, slots=True)
class SA15Plan:
    """Immutable audit of one evening allocation.

    Attributes
    ----------
    scores, trends : Mapping[str, float]
        Known momentum scores and distances above moving averages.
    selected : tuple[str, ...]
        Tactical holdings surviving direction filters and ranking.
    budgeted : Mapping[str, float]
        Risky weights after the core addition and per-fund cap.
    volatilities : Mapping[str, float]
        Conservative annualized estimates for risky funds.
    monetary_volatility : float
        Eligible defensive ETF estimate; zero for a cash residual.
    scale : float
        Risk reduction factor applied to risky weights.
    weights : Mapping[str, float]
        Final target before the rebalancing band.
    unusable : Mapping[str, SignalStatus]
        First input refusal per instrument.
    readable : int
        Tradable names with all required inputs usable.
    """

    scores: Mapping[str, float]
    trends: Mapping[str, float]
    selected: tuple[str, ...]
    budgeted: Mapping[str, float]
    volatilities: Mapping[str, float]
    monetary_volatility: float
    scale: float
    weights: Mapping[str, float]
    unusable: Mapping[str, SignalStatus]
    readable: int


@dataclass(frozen=True, slots=True)
class SA15GPT61(Strategy):
    """Long-only multi-asset momentum with trend and volatility controls.

    Attributes
    ----------
    risky_ids, monetary_id : tuple[str, ...], str
        Tactical ETFs from several asset classes, and the residual ETF.
    momentum_lookbacks, momentum_weights : tuple
        Session lookbacks and their nonnegative mean-score weights.
    top_k : int
        Maximum tactical holdings; empty slots stay defensive by default.
    use_trend_filter, trend_sessions : bool, int
        Require the close strictly above its average of consecutive prices.
    short_returns, long_returns : int
        Return counts in the two realized volatility windows.
    target_volatility, volatility_floor : float
        Annualized estimated risk limit and minimum risky volatility.
    volatility_power : float
        Inverse-volatility exponent within occupied tactical slots.
    renormalize_active : bool
        Permit occupied tactical slots to absorb empty slots' capital.
    max_asset_weight : float
        Cap per risky ETF; amounts cut from targets stay defensive.
    core_fraction, core_id : float, str
        Optional direction-gated core budget and ETF.
    monetary_lookback, monetary_maximum_volatility : int, float
        Positive carry window and strict annualized defensive risk ceiling.
    max_age_sessions : int
        Accepted age on the reference calendar. One allows a venue holiday;
        missing internal sessions still fail closed.
    rebalance_band : float
        Minimum gap except exits, cap breaches and estimated risk breaches.
    strategy_id : str
        Stable name recorded with the complete parameter fingerprint.

    Notes
    -----
    Estimated risk assumes every correlation is +1 and includes the residual
    ETF. It limits an estimate, not future losses. There is no model fit,
    leverage, short exposure, network access or strategy-held mutable state.
    """

    risky_ids: tuple[str, ...] = (
        "ETF_SP500_PEA",
        "ETF_NASDAQ",
        "ETF_EMERGING",
        "ETF_GOLD",
        "ETF_EURO_GOV",
        "ETF_COMMODITY",
    )
    monetary_id: str = "ETF_MONETARY_EUR"
    momentum_lookbacks: tuple[int, ...] = (21, 63, 126, 252)
    momentum_weights: tuple[float, ...] = (1.0, 1.0, 1.0, 1.0)
    top_k: int = 3
    use_trend_filter: bool = True
    trend_sessions: int = 200
    short_returns: int = 20
    long_returns: int = 60
    target_volatility: float = 0.18
    volatility_floor: float = 0.05
    volatility_power: float = 1.0
    renormalize_active: bool = False
    max_asset_weight: float = 1.0
    core_fraction: float = 0.0
    core_id: str = "ETF_SP500_PEA"
    monetary_lookback: int = 21
    monetary_maximum_volatility: float = 0.02
    max_age_sessions: int = 1
    rebalance_band: float = 0.05
    strategy_id: str = "SA15_GPT-6.1"

    def __post_init__(self) -> None:
        """Freeze sequence parameters and reject invalid configurations."""
        if isinstance(self.risky_ids, str):
            raise ValueError("risky_ids must be a sequence of ETF identifiers")
        object.__setattr__(self, "risky_ids", tuple(self.risky_ids))
        object.__setattr__(self, "momentum_lookbacks", tuple(self.momentum_lookbacks))
        object.__setattr__(self, "momentum_weights", tuple(self.momentum_weights))
        if not self.risky_ids or len(set(self.risky_ids)) != len(self.risky_ids):
            raise ValueError("risky_ids must contain distinct ETFs")
        for name in (*self.risky_ids, self.monetary_id, self.core_id, self.strategy_id):
            require_identifier(name, "an identifier")
        if self.monetary_id in self.risky_ids or self.monetary_id == self.core_id:
            raise ValueError("the monetary ETF cannot also have a risky role")
        for name in ("use_trend_filter", "renormalize_active"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be True or False")
        require_positive_int(self.top_k, "top_k")
        require_non_negative_int(self.max_age_sessions, "max_age_sessions")
        for lookback in self.momentum_lookbacks:
            require_positive_int(lookback, "a momentum lookback")
        if len(set(self.momentum_lookbacks)) != len(self.momentum_lookbacks):
            raise ValueError("momentum lookbacks must be distinct")
        weighted_momentum([0.0] * len(self.momentum_lookbacks), self.momentum_weights)
        for name in ("rebalance_band", "max_asset_weight", "core_fraction"):
            require_unit_fraction(getattr(self, name), name)
        for name in ("target_volatility", "volatility_floor", "monetary_maximum_volatility"):
            require_finite_positive(getattr(self, name), name)
        require_finite_non_negative(self.volatility_power, "volatility_power")
        if self.monetary_maximum_volatility >= min(self.target_volatility, self.volatility_floor):
            raise ValueError("monetary risk ceiling must be below target and risky floor")
        require_positive_int(self.short_returns, "short_returns")
        require_positive_int(self.long_returns, "long_returns")
        if self.short_returns >= self.long_returns:
            raise ValueError("short_returns must be smaller than long_returns")
        self.trend_signal()
        self.required_signals()
        self.validate()

    def investment_ids(self) -> tuple[str, ...]:
        """Return risky funds requiring signals, adding the core when used."""
        if self.core_fraction > 0.0 and self.core_id not in self.risky_ids:
            return (*self.risky_ids, self.core_id)
        return self.risky_ids

    def momentum_signal(self, sessions: int) -> Signal:
        """Return a no-skip adjusted-price return over consecutive sessions."""
        return MomentumSignal(
            signal_id=f"sa15_momentum_{sessions}s",
            lookback_sessions=sessions,
            price_basis=PriceBasis.ADJUSTED,
            max_age_sessions=self.max_age_sessions,
        )

    def trend_signal(self) -> Signal:
        """Return the adjusted close's distance above its moving average."""
        return MovingAverageTrendSignal(
            signal_id=f"sa15_price_over_ma{self.trend_sessions}",
            window_sessions=self.trend_sessions,
            price_basis=PriceBasis.ADJUSTED,
            max_age_sessions=self.max_age_sessions,
        )

    def volatility_signal(self, returns: int) -> Signal:
        """Return annualized sample volatility of consecutive daily log returns."""
        return RealizedVolatilitySignal(
            signal_id=f"sa15_volatility_{returns}r",
            window_returns=returns,
            price_basis=PriceBasis.ADJUSTED,
            annualization=252,
            logarithmic=True,
            ddof=1,
            max_age_sessions=self.max_age_sessions,
        )

    def required_signals(self) -> Sequence[Signal | SignalRequest]:
        """Declare exactly the point-in-time signals read by the allocation."""
        names = self.investment_ids()
        requests = [
            SignalRequest(self.momentum_signal(window), names)
            for window, weight in zip(self.momentum_lookbacks, self.momentum_weights, strict=True)
            if weight > 0.0
        ]
        if self.use_trend_filter:
            requests.append(SignalRequest(self.trend_signal(), names))
        requests.extend(
            SignalRequest(self.volatility_signal(window), names)
            for window in (self.short_returns, self.long_returns)
        )
        requests.extend(
            (
                SignalRequest(self.momentum_signal(self.monetary_lookback), (self.monetary_id,)),
                SignalRequest(self.volatility_signal(self.long_returns), (self.monetary_id,)),
            )
        )
        return merged_requests(requests)

    def plan(self, ctx: StrategyContext) -> SA15Plan:
        """Return the ranking, conservative risk estimates and complete target."""
        reader = SignalReader(ctx)
        scores: dict[str, float] = {}
        trends: dict[str, float] = {}
        volatilities: dict[str, float] = {}
        eligible: dict[str, float] = {}
        for name in self.investment_ids():
            momenta = [
                reader.value(self.momentum_signal(window), name) if weight > 0.0 else None
                for window, weight in zip(
                    self.momentum_lookbacks, self.momentum_weights, strict=True
                )
            ]
            score = weighted_momentum(momenta, self.momentum_weights)
            trend = reader.value(self.trend_signal(), name) if self.use_trend_filter else 1.0
            estimate = conservative_volatility(
                reader.value(self.volatility_signal(self.short_returns), name),
                reader.value(self.volatility_signal(self.long_returns), name),
                floor=self.volatility_floor,
            )
            if score is not None:
                scores[name] = score
            if trend is not None:
                trends[name] = trend
            if estimate is not None:
                volatilities[name] = estimate
            if (
                score is not None
                and score > 0.0
                and trend is not None
                and trend > 0.0
                and estimate is not None
                and name in ctx.universe
            ):
                eligible[name] = score
        tactical = rotation_weights(
            {name: eligible[name] for name in self.risky_ids if name in eligible},
            volatilities,
            top_k=self.top_k,
            volatility_power=self.volatility_power,
            renormalize_active=self.renormalize_active,
            budget=1.0 - self.core_fraction,
        )
        combined = dict(tactical)
        if self.core_fraction > 0.0 and self.core_id in eligible:
            combined[self.core_id] = combined.get(self.core_id, 0.0) + self.core_fraction
        budgeted = {
            name: min(weight, self.max_asset_weight)
            for name, weight in combined.items()
            if weight > 0.0 and self.max_asset_weight > 0.0
        }
        carry = reader.value(self.momentum_signal(self.monetary_lookback), self.monetary_id)
        money_vol = reader.value(self.volatility_signal(self.long_returns), self.monetary_id)
        money_eligible = (
            carry is not None
            and carry > 0.0
            and money_vol is not None
            and 0.0 <= money_vol < self.monetary_maximum_volatility
            and self.monetary_id in ctx.universe
        )
        monetary_volatility = money_vol if money_eligible and money_vol is not None else 0.0
        scale = risk_scale(
            budgeted,
            volatilities,
            target_volatility=self.target_volatility,
            cash_volatility=monetary_volatility,
        )
        weights = {
            name: scale * weight for name, weight in budgeted.items() if scale * weight > 0.0
        }
        if money_eligible:
            residual = max(0.0, 1.0 - math.fsum(weights.values()))
            if residual > 0.0:
                weights[self.monetary_id] = residual
        return SA15Plan(
            scores=MappingProxyType(scores),
            trends=MappingProxyType(trends),
            selected=tuple(tactical),
            budgeted=MappingProxyType(budgeted),
            volatilities=MappingProxyType(volatilities),
            monetary_volatility=monetary_volatility,
            scale=scale,
            weights=MappingProxyType(weights),
            unusable=MappingProxyType(dict(reader.unusable)),
            readable=reader.readable,
        )

    def decide(self, ctx: StrategyContext) -> TargetAllocation:
        """Return one complete target for the next executable open."""
        plan = self.plan(ctx)
        held_risk = math.fsum(
            weight * plan.volatilities[name]
            for name, weight in ctx.portfolio.weights.items()
            if name in plan.volatilities
        )
        held_risk += ctx.portfolio.weights.get(self.monetary_id, 0.0) * plan.monetary_volatility
        return settle(
            ctx,
            plan.weights,
            band=self.rebalance_band,
            caps=dict.fromkeys(self.investment_ids(), self.max_asset_weight),
            force=held_risk > self.target_volatility + 1e-9,
            unusable=plan.unusable,
            readable=plan.readable,
        )
