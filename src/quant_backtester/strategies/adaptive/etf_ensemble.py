"""Several rules, fixed capital budgets, one risk control and one rebalancing band."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.numbers import require_finite_positive, require_unit_fraction
from quant_backtester.portfolio.targets import WEIGHT_SUM_TOLERANCE, TargetAllocation
from quant_backtester.signals.base import Signal
from quant_backtester.signals.engine import SignalRequest
from quant_backtester.signals.types import SignalStatus, require_identifier
from quant_backtester.strategies.adaptive.inputs import SignalReader, merged_requests, volatility
from quant_backtester.strategies.adaptive.rebalance import RuleStrategy, settle
from quant_backtester.strategies.adaptive.rules import (
    RuleTarget,
    conservative_volatility,
    risk_scale,
)
from quant_backtester.strategies.base import Strategy
from quant_backtester.strategies.examples.buffered_dual_momentum import BufferedDualMomentum
from quant_backtester.strategies.examples.factor_etf_blend import FactorETFBlend
from quant_backtester.strategies.examples.monetary_carry import MonetaryCarry
from quant_backtester.strategies.examples.relative_residual_tilt import RelativeResidualTilt
from quant_backtester.strategies.examples.smooth_moving_average import SmoothMovingAverage
from quant_backtester.strategies.examples.trend_filtered_pullback import TrendFilteredPullback
from quant_backtester.strategies.examples.vix_relief_entry import VixReliefEntry

RISK_ROUNDING = 1e-9
"""How far above its target a book's estimated risk may sit and still be the
target, to rounding: a book scaled to exactly 12% must not read as 12.0000001%."""


@dataclass(frozen=True, slots=True)
class EnsemblePlan:
    """What the ensemble computed at one decision, step by step.

    Attributes
    ----------
    rules : Mapping[str, RuleTarget]
        The theoretical target of each budgeted rule, by rule name.
    budgeted : Mapping[str, float]
        ``v_i``: the equity weights after the budgets and the per-fund cap,
        funds without a volatility estimate removed.
    volatilities : Mapping[str, float]
        ``s_i``: the volatility estimate of each equity fund that has one.
    monetary_volatility : float
        ``s_m``: the money-market fund's volatility when it is eligible, zero
        otherwise.
    scale : float
        ``lambda``, the factor the equity weights are multiplied by.
    weights : Mapping[str, float]
        The final target, the money-market fund included.
    unusable : Mapping[str, SignalStatus]
        Why each instrument whose signal had no value had none.
    readable : int
        How many instruments the book may hold had every signal usable.
    """

    rules: Mapping[str, RuleTarget]
    budgeted: Mapping[str, float]
    volatilities: Mapping[str, float]
    monetary_volatility: float
    scale: float
    weights: Mapping[str, float]
    unusable: Mapping[str, SignalStatus]
    readable: int = 0


@dataclass(frozen=True, slots=True)
class ETFEnsemble(Strategy):
    """Trend, rebound, relative and style rules under one estimated-risk limit.

    Attributes
    ----------
    enable_factors : bool
        Whether the three style funds are part of the run. When they are not,
        neither their data nor their signals are declared, and their budget
        stays in cash: such a run is not a test of the complete combination.
    enable_monetary : bool
        Whether the capital left over is placed in the money-market fund.
    world_id, sp500_id : str
        The two core funds.
    vix_id : str
        The published volatility index. Read, never held.
    factor_ids : tuple[str, ...]
        The three style funds, read only when ``enable_factors`` is set.
    monetary_id : str | None
        The money-market fund, read only when ``enable_monetary`` is set.
    momentum_budget, trend_budget, pullback_budget, relative_budget : float
        Share of capital given to rules 1 to 4.
    factor_budget, relief_budget : float
        Share of capital given to rules 6 and 8.
    equity_cap : float
        Largest weight of any one equity fund, before and after the control.
    target_volatility : float
        The estimated annualised risk the book may carry.
    volatility_floor : float
        Smallest volatility an equity fund's estimate may take.
    short_returns, long_returns : int
        Daily returns in each of the two volatility estimates.
    rebalance_band : float
        Largest gap between a weight and its target that sends no order,
        applied once, to the final book.
    strategy_id : str
        Name this configuration is recorded under.

    Raises
    ------
    ValueError
        If a name is empty or used twice, an enabled part has no instruments,
        the budgets add up to more than the book, or a number is out of its
        range.

    Notes
    -----
    Each budgeted rule gives its theoretical target, before any band, and
    ``v = sum(budget_k * weights_k)`` adds them fund by fund. These are budgets
    of capital, not equal contributions to risk. Each equity fund is then cut
    to ``equity_cap``; nothing is renormalised, and a rule that is inactive
    leaves its budget in cash rather than strengthening the others.

    Rule 5 is the risk control. With ``s_i = max(vol_short, vol_long, floor)``,
    ``V = sum(v_i)``, ``S = sum(v_i * s_i)`` and ``s_m`` the money-market
    fund's volatility when rule 7 finds it eligible (zero otherwise),
    ``lambda = min(1, max(0, (target - s_m) / (S - V * s_m)))``, the equity
    weights are ``lambda * v_i`` and the money-market fund takes the rest, or
    nothing when it is not eligible. Every correlation is taken as ``+1``: the
    bound is deliberately conservative and needs no covariance matrix. It
    limits an *estimated* risk and predicts neither jumps nor future
    volatility. An equity fund without a volatility estimate has its weight
    set to zero before the control.

    The band is applied once, to the final book. It is set aside when a held
    fund has a target of zero, when a held equity weight is above the cap, or
    when the estimated risk of the book as it stands is above the target.

    The rules' own ``decide`` is never called: that would apply the band once
    per rule and mistake the shared book for each rule's own.
    """

    enable_factors: bool
    enable_monetary: bool
    world_id: str = "ETF_WORLD"
    sp500_id: str = "ETF_SP500_PEA"
    vix_id: str = "VIX"
    factor_ids: tuple[str, ...] = ()
    monetary_id: str | None = None
    momentum_budget: float = 0.20
    trend_budget: float = 0.20
    pullback_budget: float = 0.10
    relative_budget: float = 0.10
    factor_budget: float = 0.30
    relief_budget: float = 0.10
    equity_cap: float = 0.40
    target_volatility: float = 0.12
    volatility_floor: float = 0.05
    short_returns: int = 20
    long_returns: int = 60
    rebalance_band: float = 0.03
    strategy_id: str = "SA10_ensemble"

    def __post_init__(self) -> None:
        """Reject a configuration that cannot be computed or held."""
        object.__setattr__(self, "factor_ids", tuple(self.factor_ids))
        for flag in ("enable_factors", "enable_monetary"):
            if not isinstance(getattr(self, flag), bool):
                raise ValueError(f"{flag} must be True or False, got {getattr(self, flag)!r}")
        for name in ("world_id", "sp500_id", "vix_id", "strategy_id"):
            require_identifier(getattr(self, name), name)
        if self.enable_monetary and self.monetary_id is None:
            raise ValueError("enable_monetary is set and monetary_id names no fund")
        names = [*self.equity_ids(), self.vix_id]
        if self.enable_monetary and self.monetary_id is not None:
            names.append(self.monetary_id)
        repeated = sorted(name for name, seen in Counter(names).items() if seen > 1)
        if repeated:
            raise ValueError(f"{', '.join(repeated)} is given more than one role")
        budgets = [budget for _, budget, _ in self._budgeted()]
        for budget in budgets:
            require_unit_fraction(budget, "a budget")
        if math.fsum(budgets) > 1.0 + WEIGHT_SUM_TOLERANCE:
            raise ValueError(
                f"the budgets add up to {math.fsum(budgets)}: the book does not borrow"
            )
        require_unit_fraction(self.equity_cap, "equity_cap")
        require_unit_fraction(self.rebalance_band, "rebalance_band")
        require_finite_positive(self.target_volatility, "target_volatility")
        require_finite_positive(self.volatility_floor, "volatility_floor")
        if self.short_returns == self.long_returns:
            raise ValueError(f"both volatility windows hold {self.long_returns} returns")
        if self.enable_monetary and self._monetary().maximum_volatility >= min(
            self.volatility_floor, self.target_volatility
        ):
            raise ValueError(
                "the money-market fund may be as volatile as an equity fund's floor or as "
                "the risk target: the risk control would have nothing to scale"
            )
        self.required_signals()

    # -- the parts --------------------------------------------------------

    def equity_ids(self) -> tuple[str, ...]:
        """Return the equity funds of this configuration, core funds first."""
        factors = self.factor_ids if self.enable_factors else ()
        return (self.world_id, self.sp500_id, *factors)

    def _budgeted(self) -> tuple[tuple[str, float, RuleStrategy], ...]:
        """Return each budgeted rule with its name and its share of capital."""
        rules: list[tuple[str, float, RuleStrategy]] = [
            (
                "momentum",
                self.momentum_budget,
                BufferedDualMomentum(first_id=self.world_id, second_id=self.sp500_id),
            ),
            ("trend", self.trend_budget, SmoothMovingAverage(instrument_id=self.world_id)),
            ("pullback", self.pullback_budget, TrendFilteredPullback(instrument_id=self.world_id)),
            (
                "relative",
                self.relative_budget,
                RelativeResidualTilt(first_id=self.world_id, second_id=self.sp500_id),
            ),
        ]
        if self.enable_factors:
            rules.append(
                ("factors", self.factor_budget, FactorETFBlend(instrument_ids=self.factor_ids))
            )
        rules.append(
            (
                "relief",
                self.relief_budget,
                VixReliefEntry(instrument_id=self.sp500_id, vix_id=self.vix_id),
            )
        )
        return tuple(rules)

    def _monetary(self) -> MonetaryCarry:
        """Return rule 7 on the money-market fund."""
        if self.monetary_id is None:
            raise ValueError("monetary_id names no fund")
        return MonetaryCarry(instrument_id=self.monetary_id)

    def short_signal(self) -> Signal:
        """Return the shorter of the two volatilities of the risk control."""
        return volatility(self.short_returns)

    def long_signal(self) -> Signal:
        """Return the longer of the two volatilities of the risk control."""
        return volatility(self.long_returns)

    def required_signals(self) -> Sequence[Signal | SignalRequest]:
        """Return the union of what the rules read, one request per signal.

        Returns
        -------
        Sequence[Signal | SignalRequest]
            Every signal of every enabled rule, each over an explicit list of
            instruments, plus the two volatilities of the risk control over
            every equity fund. A signal two rules share is declared once, over
            the instruments of both.
        """
        requests: list[SignalRequest] = []
        rules: list[Strategy] = [rule for _, _, rule in self._budgeted()]
        if self.enable_monetary:
            rules.append(self._monetary())
        for rule in rules:
            for item in rule.required_signals():
                if not isinstance(item, SignalRequest):
                    raise ValueError(f"{rule.strategy_id} declares a signal without instruments")
                requests.append(item)
        for signal in (self.short_signal(), self.long_signal()):
            requests.append(SignalRequest(signal=signal, instruments=self.equity_ids()))
        return merged_requests(requests)

    def parameters(self) -> Mapping[str, object]:
        """Return the fields of the ensemble and the parameters of every rule in it."""
        rules = {name: dict(rule.parameters()) for name, _, rule in self._budgeted()}
        if self.enable_monetary:
            rules["monetary"] = dict(self._monetary().parameters())
        return {**Strategy.parameters(self), "rules": rules}

    # -- the decision -----------------------------------------------------

    def plan(self, ctx: StrategyContext) -> EnsemblePlan:
        """Return the final target and every step that led to it.

        Parameters
        ----------
        ctx : StrategyContext
            The decision being taken. Only declared signals are read.

        Returns
        -------
        EnsemblePlan
            The rules' targets, the budgeted and capped equity weights, the
            volatility estimates, the scale and the final weights - before the
            rebalancing band.
        """
        reader = SignalReader(ctx)
        unusable: dict[str, SignalStatus] = {}
        rules: dict[str, RuleTarget] = {}
        combined: dict[str, float] = {}
        for name, budget, rule in self._budgeted():
            evaluation = rule.evaluate(ctx)
            rules[name] = evaluation.target
            for instrument_id, status in evaluation.unusable.items():
                unusable.setdefault(instrument_id, status)
            for instrument_id, weight in evaluation.target.weights.items():
                combined[instrument_id] = combined.get(instrument_id, 0.0) + budget * weight

        short, long = self.short_signal(), self.long_signal()
        volatilities: dict[str, float] = {}
        for instrument_id in self.equity_ids():
            estimate = conservative_volatility(
                reader.value(short, instrument_id),
                reader.value(long, instrument_id),
                floor=self.volatility_floor,
            )
            if estimate is not None:
                volatilities[instrument_id] = estimate
        budgeted = {
            instrument_id: min(weight, self.equity_cap)
            for instrument_id, weight in combined.items()
            if instrument_id in volatilities and weight > 0.0
        }

        monetary_volatility = 0.0
        eligible = False
        if self.enable_monetary and self.monetary_id is not None:
            monetary = self._monetary()
            evaluation = monetary.evaluate(ctx)
            rules["monetary"] = evaluation.target
            for instrument_id, status in evaluation.unusable.items():
                unusable.setdefault(instrument_id, status)
            held_volatility = reader.value(monetary.volatility_signal(), self.monetary_id)
            if evaluation.target.weights and held_volatility is not None:
                eligible, monetary_volatility = True, held_volatility

        scale = risk_scale(
            budgeted,
            volatilities,
            target_volatility=self.target_volatility,
            cash_volatility=monetary_volatility,
        )
        weights = {instrument_id: scale * weight for instrument_id, weight in budgeted.items()}
        if eligible and self.monetary_id is not None:
            weights[self.monetary_id] = max(0.0, 1.0 - math.fsum(weights.values()))
        for instrument_id, status in reader.unusable.items():
            unusable.setdefault(instrument_id, status)
        return EnsemblePlan(
            rules=MappingProxyType(rules),
            budgeted=MappingProxyType(budgeted),
            volatilities=MappingProxyType(volatilities),
            monetary_volatility=monetary_volatility,
            scale=scale,
            weights=MappingProxyType({name: w for name, w in weights.items() if w > 0.0}),
            unusable=MappingProxyType(unusable),
            readable=reader.readable,
        )

    def decide(self, ctx: StrategyContext) -> TargetAllocation:
        """Return the target for the next open: one allocation for the whole book.

        Parameters
        ----------
        ctx : StrategyContext
            Everything the decision may see, fixed at the decision instant,
            after the close of the session it is taken on.

        Returns
        -------
        TargetAllocation
            The final weights; the book as it stands, with no order, when
            every weight is inside the band and neither the cap nor the risk
            target is breached by what is held; cash when nothing is targeted.
        """
        plan = self.plan(ctx)
        held = ctx.portfolio.weights
        held_risk = math.fsum(
            weight * plan.volatilities[name]
            for name, weight in held.items()
            if name in plan.volatilities
        )
        if self.monetary_id is not None:
            held_risk += held.get(self.monetary_id, 0.0) * plan.monetary_volatility
        return settle(
            ctx,
            plan.weights,
            band=self.rebalance_band,
            caps=dict.fromkeys(self.equity_ids(), self.equity_cap),
            force=held_risk > self.target_volatility + RISK_ROUNDING,
            unusable=plan.unusable,
            readable=plan.readable,
        )
