"""Fixed-formula Nasdaq mechanisms with independently removable controls.

Every input is available at a timezone-aware evening decision; the engine
executes at a later open. Adjusted provider prices may be restated. There is no
model fit, search for historical weights, or mutable regime state. All numeric
fields are explicit fixed research constants, not an optimisation menu.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, replace
from types import MappingProxyType
from typing import ClassVar

from quant_backtester.backtest.context import Selection, StrategyContext
from quant_backtester.numbers import require_finite, require_finite_positive, require_unit_fraction
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.signals.base import Signal
from quant_backtester.signals.engine import SignalRequest
from quant_backtester.signals.price.endpoint_momentum import EndpointMomentumSignal
from quant_backtester.signals.price.trend import MovingAverageTrendSignal
from quant_backtester.signals.risk.drawdown import CurrentDrawdownSignal
from quant_backtester.signals.risk.volatility import RealizedVolatilitySignal
from quant_backtester.signals.types import (
    PriceBasis,
    SignalStatus,
    require_identifier,
    require_non_negative_int,
    require_positive_int,
)
from quant_backtester.strategies.adaptive.inputs import merged_requests
from quant_backtester.strategies.adaptive.rebalance import settle
from quant_backtester.strategies.base import Strategy

BLOCK_PARAMETERS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        name: (f"{name}_rule",)
        for name in ("trend", "risk", "recovery", "shock", "confirmation", "defensive", "execution")
    }
)
"""Categorical mechanism groups; numerical constants stay identical in the study."""


@dataclass(frozen=True, slots=True)
class MechanismPlan:
    """Immutable allocation stages before the execution band.

    Weights are equity fractions, and risk is annualised Nasdaq risk, not total
    portfolio volatility or a loss bound. Diagnostic-only unavailable inputs
    are present in signal_statuses; only mandatory trading inputs set
    missing_core. The audit is passive and cannot change a trading decision.
    """

    signals: Mapping[str, float | None]
    signal_statuses: Mapping[str, SignalStatus]
    trend_fraction: float
    recovery_fraction: float
    confirmed_fraction: float
    shocked_fraction: float
    recovery_active: bool
    shock_active: bool
    risk_estimate: float | None
    risk_scale: float
    core_weight: float
    weights: Mapping[str, float]
    skipped: Mapping[str, SignalStatus]
    readable: int
    regime: str
    missing_core: bool
    reasons: tuple[str, ...]

    def audit_dict(self) -> dict[str, object]:
        """Return finite JSON-compatible evening values and explicit statuses."""
        return {
            "signals": dict(self.signals),
            "signal_statuses": {k: v.value for k, v in self.signal_statuses.items()},
            "trend_fraction": self.trend_fraction,
            "recovery_fraction": self.recovery_fraction,
            "confirmed_fraction": self.confirmed_fraction,
            "shocked_fraction": self.shocked_fraction,
            "recovery_active": self.recovery_active,
            "shock_active": self.shock_active,
            "risk_estimate": self.risk_estimate,
            "risk_scale": self.risk_scale,
            "core_weight": self.core_weight,
            "weights": dict(self.weights),
            "skipped": {k: v.value for k, v in self.skipped.items()},
            "readable": self.readable,
            "regime": self.regime,
            "missing_core": self.missing_core,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True, slots=True)
class SA15Mechanisms(Strategy):
    """Compose seven ablatable mechanisms over one stable Nasdaq core.

    Direction precedes recovery, confirmation, shock and finally risk sizing.
    Recovery never evades unavailable mandatory inputs, confirmation, a shock
    or a risk cap. Residual capital follows the declared defensive mechanism.
    No leverage, shorts or fitted weights are possible. Missing mandatory core
    inputs target zero core; missing defence is individually excluded.

    Trend off permits one; ma200 requires positive price/MA200 minus one;
    dual_ma requires positive MA50 and MA200 distances; momentum requires
    positive momentum126. Consensus is the fraction of positive MA200,
    momentum63 and momentum126 votes. Partial holds one or the fixed half
    exposure according to MA200. Slow_fast_guard permits MA200 OR momentum21.
    All zero readings are non-bullish.

    Risk is min(1, target/max(estimate, floor)). Cap_max uses max(vol20,vol60);
    cap_fast uses vol20. Negative_only applies cap_max when momentum21<=0,
    and is NOT semivariance. Conditional disables the cap while MA200 and
    momentum21 are positive. Trend_relief keeps at least its fixed risk floor
    while MA50 and momentum21 are positive. Exceptions give up protection.

    Recovery positive21, ma50 or dual_confirm restores direction when positive.
    Breakout requires equality with the rolling high; near_high requires
    DD63>=-2%. Positive_acceleration requires positive momentum21 and its
    average daily log return to exceed momentum63's. Confirmation momentum
    requires momentum63>0; double_trend requires MA50/200>0; canary requires
    every fixed canary's momentum126>0; persistence requires two consecutive,
    non-overlapping positive 21-session returns. Fast_loss shock stops at
    momentum21<=-8%; drawdown shock stops at DD63<=-10%.

    Monetary requires positive 21-session carry. Gold_momentum uses gold if
    momentum63>0, else monetary; dual_defense chooses the strongest positive
    momentum63 among gold/government, ties by identifier, else monetary.
    Defensive risk is not included in the Nasdaq risk estimate.

    Execution off sends every target; band uses one symmetric band.
    Asymmetric tolerates larger entries than reductions with fixed bands.
    Hold_defense preserves an existing defensive allocation while the core
    weight stays within the common band and the core regime is unchanged.
    Full core exits always execute. Calendar cadence is recorded externally.
    """

    core_id: str = "ETF_NASDAQ"
    monetary_id: str = "ETF_MONETARY_EUR"
    gold_id: str = "ETF_GOLD"
    government_id: str = "ETF_EURO_GOV"
    canary_ids: tuple[str, ...] = ("ETF_WORLD", "ETF_EMERGING")
    trend_rule: str = "ma200"
    risk_rule: str = "cap_max"
    recovery_rule: str = "off"
    shock_rule: str = "off"
    confirmation_rule: str = "off"
    defensive_rule: str = "monetary"
    execution_rule: str = "band"
    fast_sessions: int = 21
    medium_sessions: int = 63
    slow_sessions: int = 126
    ma_fast_sessions: int = 50
    ma_slow_sessions: int = 200
    vol_fast_returns: int = 20
    vol_slow_returns: int = 60
    target_volatility: float = 0.20
    volatility_floor: float = 0.05
    partial_exposure: float = 0.5
    risk_relief_floor: float = 0.75
    drawdown_sessions: int = 63
    near_high_threshold: float = -0.02
    shock_loss_threshold: float = -0.08
    shock_drawdown_threshold: float = -0.10
    defensive_sessions: int = 63
    monetary_sessions: int = 21
    rebalance_band: float = 0.10
    entry_band: float = 0.20
    reduction_band: float = 0.05
    max_age_sessions: int = 1
    strategy_id: str = "SA15_GPT-6.1_R5"

    BLOCK_PARAMETERS: ClassVar[Mapping[str, tuple[str, ...]]] = BLOCK_PARAMETERS

    def __post_init__(self) -> None:
        """Reject invalid categories, non-finite constants and ambiguous roles."""
        categories = {
            "trend_rule": {
                "off",
                "ma200",
                "dual_ma",
                "momentum",
                "consensus",
                "partial",
                "slow_fast_guard",
            },
            "risk_rule": {
                "off",
                "cap_max",
                "cap_fast",
                "negative_only",
                "conditional",
                "trend_relief",
            },
            "recovery_rule": {
                "off",
                "positive21",
                "ma50",
                "dual_confirm",
                "breakout",
                "near_high",
                "positive_acceleration",
            },
            "shock_rule": {"off", "fast_loss", "drawdown"},
            "confirmation_rule": {"off", "momentum", "double_trend", "canary", "persistence"},
            "defensive_rule": {"cash", "monetary", "gold_momentum", "dual_defense"},
            "execution_rule": {"off", "band", "hold_defense", "asymmetric"},
        }
        for name, allowed in categories.items():
            if getattr(self, name) not in allowed:
                raise ValueError(f"unknown {name}: {getattr(self, name)!r}")
        if isinstance(self.canary_ids, str):
            raise ValueError("canary_ids must be a sequence")
        object.__setattr__(self, "canary_ids", tuple(self.canary_ids))
        roles = (self.core_id, self.monetary_id, self.gold_id, self.government_id)
        for value in (*roles, *self.canary_ids, self.strategy_id):
            require_identifier(value, "an identifier")
        if len(set(roles)) != len(roles) or len(set(self.canary_ids)) != len(self.canary_ids):
            raise ValueError("asset roles and canary identifiers must be distinct")
        if not self.canary_ids:
            raise ValueError("the fixed canary list cannot be empty")
        for name in (
            "fast_sessions",
            "medium_sessions",
            "slow_sessions",
            "ma_fast_sessions",
            "ma_slow_sessions",
            "vol_fast_returns",
            "vol_slow_returns",
            "drawdown_sessions",
            "defensive_sessions",
            "monetary_sessions",
        ):
            require_positive_int(getattr(self, name), name)
        require_non_negative_int(self.max_age_sessions, "max_age_sessions")
        if not self.fast_sessions < self.medium_sessions < self.slow_sessions:
            raise ValueError("momentum windows must be increasing")
        if not 2 <= self.ma_fast_sessions < self.ma_slow_sessions:
            raise ValueError("moving-average windows must be increasing and at least two")
        if not 2 <= self.vol_fast_returns < self.vol_slow_returns or self.drawdown_sessions < 2:
            raise ValueError("volatility/drawdown windows require at least two")
        for name in ("target_volatility", "volatility_floor"):
            require_finite_positive(getattr(self, name), name)
        for name in (
            "partial_exposure",
            "risk_relief_floor",
            "rebalance_band",
            "entry_band",
            "reduction_band",
        ):
            require_unit_fraction(getattr(self, name), name)
        if self.reduction_band > self.entry_band:
            raise ValueError("reduction_band cannot exceed entry_band")
        for name in ("shock_loss_threshold", "shock_drawdown_threshold", "near_high_threshold"):
            value = getattr(self, name)
            require_finite(value, name)
            if not -1.0 < value < 0.0:
                raise ValueError("thresholds must lie strictly between -1 and zero")

    def active_blocks(self) -> tuple[str, ...]:
        """Return every non-neutral mechanism in deterministic pipeline order."""
        return tuple(
            name
            for name in BLOCK_PARAMETERS
            if getattr(self, f"{name}_rule") != ("cash" if name == "defensive" else "off")
        )

    def without_block(self, block: str) -> SA15Mechanisms:
        """Return the complete policy with only the named block neutralised."""
        if block not in BLOCK_PARAMETERS:
            raise ValueError(f"unknown mechanism block {block!r}")
        return replace(self, **{f"{block}_rule": "cash" if block == "defensive" else "off"})

    def momentum_signal(self, sessions: int, *, skip: int = 0) -> EndpointMomentumSignal:
        """Build an adjusted exact-endpoint return with explicit freshness."""
        return EndpointMomentumSignal(
            signal_id=f"r5_momentum_{sessions}s_skip{skip}",
            lookback_sessions=sessions,
            skip_recent_sessions=skip,
            price_basis=PriceBasis.ADJUSTED,
            max_age_sessions=self.max_age_sessions,
        )

    def trend_signal(self, sessions: int) -> MovingAverageTrendSignal:
        """Build consecutive adjusted close/MA minus one."""
        return MovingAverageTrendSignal(
            signal_id=f"r5_price_over_ma{sessions}",
            window_sessions=sessions,
            price_basis=PriceBasis.ADJUSTED,
            max_age_sessions=self.max_age_sessions,
        )

    def volatility_signal(self, returns: int) -> RealizedVolatilitySignal:
        """Build annual sample log-return volatility on consecutive sessions."""
        return RealizedVolatilitySignal(
            signal_id=f"r5_volatility_{returns}r",
            window_returns=returns,
            price_basis=PriceBasis.ADJUSTED,
            annualization=252,
            logarithmic=True,
            ddof=1,
            max_age_sessions=self.max_age_sessions,
        )

    def drawdown_signal(self) -> CurrentDrawdownSignal:
        """Build current distance to the consecutive rolling adjusted-price high."""
        return CurrentDrawdownSignal(
            signal_id=f"r5_drawdown_{self.drawdown_sessions}s",
            window_sessions=self.drawdown_sessions,
            price_basis=PriceBasis.ADJUSTED,
            max_age_sessions=self.max_age_sessions,
        )

    def _core_required(self) -> set[str]:
        fast, medium, slow = (
            f"mom_{n}" for n in (self.fast_sessions, self.medium_sessions, self.slow_sessions)
        )
        ma_fast, ma_slow = f"ma_{self.ma_fast_sessions}", f"ma_{self.ma_slow_sessions}"
        needed = {"fresh"}
        needed.update(
            {
                "off": set(),
                "ma200": {ma_slow},
                "dual_ma": {ma_fast, ma_slow},
                "momentum": {slow},
                "consensus": {ma_slow, medium, slow},
                "partial": {ma_slow},
                "slow_fast_guard": {ma_slow, fast},
            }[self.trend_rule]
        )
        if self.risk_rule != "off":
            needed.add(f"vol_{self.vol_fast_returns}")
            if self.risk_rule != "cap_fast":
                needed.add(f"vol_{self.vol_slow_returns}")
        if self.risk_rule in {"negative_only", "conditional", "trend_relief"}:
            needed.add(fast)
        if self.risk_rule == "conditional":
            needed.add(ma_slow)
        if self.risk_rule == "trend_relief":
            needed.add(ma_fast)
        needed.update(
            {
                "off": set(),
                "positive21": {fast},
                "ma50": {ma_fast},
                "dual_confirm": {fast, ma_fast},
                "breakout": {"drawdown"},
                "near_high": {"drawdown"},
                "positive_acceleration": {fast, medium},
            }[self.recovery_rule]
        )
        needed.update(
            {"off": set(), "fast_loss": {fast}, "drawdown": {"drawdown"}}[self.shock_rule]
        )
        needed.update(
            {
                "off": set(),
                "momentum": {medium},
                "double_trend": {ma_fast, ma_slow},
                "canary": {f"canary:{name}" for name in self.canary_ids},
                "persistence": {fast, "previous_fast"},
            }[self.confirmation_rule]
        )
        return needed

    def _inputs(self) -> dict[str, tuple[Signal, str]]:
        pairs: dict[str, tuple[Signal, str]] = {
            "fresh": (self.momentum_signal(1), self.core_id),
            f"mom_{self.fast_sessions}": (self.momentum_signal(self.fast_sessions), self.core_id),
            f"mom_{self.slow_sessions}": (self.momentum_signal(self.slow_sessions), self.core_id),
        }
        for label in sorted(self._core_required()):
            if label.startswith("mom_"):
                pairs[label] = (self.momentum_signal(int(label.removeprefix("mom_"))), self.core_id)
            elif label.startswith("ma_"):
                pairs[label] = (self.trend_signal(int(label.removeprefix("ma_"))), self.core_id)
            elif label.startswith("vol_"):
                pairs[label] = (
                    self.volatility_signal(int(label.removeprefix("vol_"))),
                    self.core_id,
                )
            elif label == "drawdown":
                pairs[label] = (self.drawdown_signal(), self.core_id)
            elif label == "previous_fast":
                pairs[label] = (
                    self.momentum_signal(2 * self.fast_sessions, skip=self.fast_sessions),
                    self.core_id,
                )
            elif label.startswith("canary:"):
                pairs[label] = (
                    self.momentum_signal(self.slow_sessions),
                    label.removeprefix("canary:"),
                )
        if self.defensive_rule != "cash":
            pairs[f"{self.monetary_id}:carry"] = (
                self.momentum_signal(self.monetary_sessions),
                self.monetary_id,
            )
        if self.defensive_rule in {"gold_momentum", "dual_defense"}:
            pairs[f"{self.gold_id}:defense"] = (
                self.momentum_signal(self.defensive_sessions),
                self.gold_id,
            )
        if self.defensive_rule == "dual_defense":
            pairs[f"{self.government_id}:defense"] = (
                self.momentum_signal(self.defensive_sessions),
                self.government_id,
            )
        return pairs

    def required_signals(self) -> Sequence[SignalRequest]:
        """Declare fixed instruments and the union of required signal definitions."""
        return merged_requests(
            SignalRequest(signal=signal, instruments=(name,))
            for signal, name in self._inputs().values()
        )

    def plan(self, ctx: StrategyContext) -> MechanismPlan:
        """Compute each allocation stage solely from the immutable evening context."""
        inputs, required = self._inputs(), self._core_required()
        values: dict[str, float | None] = {}
        statuses: dict[str, SignalStatus] = {}
        skipped: dict[str, SignalStatus] = {}
        reasons: list[str] = []
        for label, (signal, name) in inputs.items():
            status = ctx.signal_status(signal.signal_id, name)
            value = (
                ctx.signal_value_or_none(signal.signal_id, name)
                if status is SignalStatus.OK
                else None
            )
            if value is not None and (
                not math.isfinite(value)
                or (label.startswith("vol_") and value < 0)
                or (not label.startswith("vol_") and value <= -1)
            ):
                status, value = SignalStatus.INVALID_INPUT, None
            values[label], statuses[label] = value, status
            if value is None and label in required:
                if name in ctx.universe:
                    skipped.setdefault(name, status)
                reasons.append(f"missing:{label}:{status.value}")
        missing = (
            any(values[label] is None for label in required) or self.core_id not in ctx.universe
        )
        if self.core_id not in ctx.universe:
            reasons.append("core_outside_universe")

        def v(label: str) -> float:
            value = values.get(label)
            return value if value is not None else 0.0

        def positive(label: str) -> bool:
            return v(label) > 0

        fast, medium, slow = (
            f"mom_{n}" for n in (self.fast_sessions, self.medium_sessions, self.slow_sessions)
        )
        ma_fast, ma_slow = f"ma_{self.ma_fast_sessions}", f"ma_{self.ma_slow_sessions}"
        direction = {
            "off": 1.0,
            "ma200": float(positive(ma_slow)),
            "dual_ma": float(positive(ma_fast) and positive(ma_slow)),
            "momentum": float(positive(slow)),
            "consensus": math.fsum(float(positive(label)) for label in (ma_slow, medium, slow)) / 3,
            "partial": 1.0 if positive(ma_slow) else self.partial_exposure,
            "slow_fast_guard": float(positive(ma_slow) or positive(fast)),
        }[self.trend_rule]
        recovered = {
            "off": False,
            "positive21": positive(fast),
            "ma50": positive(ma_fast),
            "dual_confirm": positive(fast) and positive(ma_fast),
            "breakout": values.get("drawdown") is not None and v("drawdown") >= 0,
            "near_high": values.get("drawdown") is not None
            and v("drawdown") >= self.near_high_threshold,
            "positive_acceleration": positive(fast)
            and math.log1p(v(fast)) / self.fast_sessions
            > math.log1p(v(medium)) / self.medium_sessions,
        }[self.recovery_rule]
        recovery_fraction = 1.0 if recovered else direction
        confirmation = {
            "off": True,
            "momentum": positive(medium),
            "double_trend": positive(ma_fast) and positive(ma_slow),
            "canary": all(positive(f"canary:{name}") for name in self.canary_ids),
            "persistence": positive(fast) and positive("previous_fast"),
        }[self.confirmation_rule]
        confirmed = recovery_fraction * float(confirmation)
        shock = {
            "off": False,
            "fast_loss": v(fast) <= self.shock_loss_threshold,
            "drawdown": v("drawdown") <= self.shock_drawdown_threshold,
        }[self.shock_rule]
        shocked = 0.0 if shock else confirmed
        risk_values = [v(f"vol_{self.vol_fast_returns}")]
        if self.risk_rule not in {"off", "cap_fast"}:
            risk_values.append(v(f"vol_{self.vol_slow_returns}"))
        estimate = max(self.volatility_floor, *risk_values) if self.risk_rule != "off" else None
        scale = min(1.0, self.target_volatility / estimate) if estimate is not None else 1.0
        if self.risk_rule == "negative_only" and positive(fast):
            scale = 1.0
        if self.risk_rule == "conditional" and positive(ma_slow) and positive(fast):
            scale = 1.0
        if self.risk_rule == "trend_relief" and positive(ma_fast) and positive(fast):
            scale = max(scale, self.risk_relief_floor)
        core_weight = 0.0 if missing else shocked * scale
        weights = {self.core_id: core_weight} if core_weight > 0 else {}
        residual = max(0.0, 1.0 - core_weight)
        chosen: str | None = None
        if residual > 0 and self.defensive_rule in {"gold_momentum", "dual_defense"}:
            ids = (
                (self.gold_id, self.government_id)
                if self.defensive_rule == "dual_defense"
                else (self.gold_id,)
            )
            eligible: list[str] = []
            for name in ids:
                label = f"{name}:defense"
                if values[label] is None:
                    skipped.setdefault(name, statuses[label])
                elif values[label] > 0 and name in ctx.universe:
                    eligible.append(name)
            if eligible:
                chosen = min(eligible, key=lambda name: (-v(f"{name}:defense"), name))
        if residual > 0 and chosen is None and self.defensive_rule != "cash":
            label = f"{self.monetary_id}:carry"
            if values[label] is None:
                skipped.setdefault(self.monetary_id, statuses[label])
            elif values[label] > 0 and self.monetary_id in ctx.universe:
                chosen = self.monetary_id
        if chosen is not None:
            weights[chosen] = residual
        if recovered and direction < 1:
            reasons.append("recovery_restores_direction")
        if not confirmation:
            reasons.append("confirmation_blocks_direction")
        if shock:
            reasons.append("shock_stops_direction")
        if scale < 1:
            reasons.append("risk_scales_direction")
        readable_ids = {
            name
            for label, (_, name) in inputs.items()
            if values[label] is not None and name in ctx.universe
        } - set(skipped)
        return MechanismPlan(
            MappingProxyType(values),
            MappingProxyType(statuses),
            direction,
            recovery_fraction,
            confirmed,
            shocked,
            bool(recovered and direction < 1 and not missing),
            bool(shock and not missing),
            None if missing else estimate,
            scale,
            core_weight,
            MappingProxyType(weights),
            MappingProxyType(skipped),
            len(readable_ids),
            "missing_core"
            if missing
            else "nasdaq"
            if core_weight == 1
            else "defensive"
            if core_weight == 0
            else "risk_reduced",
            missing,
            tuple(reasons),
        )

    def decide(self, ctx: StrategyContext) -> TargetAllocation:
        """Apply the declared execution mechanism once to the complete target."""
        plan = self.plan(ctx)
        held_core = ctx.portfolio.weights.get(self.core_id, 0.0)
        band = self.rebalance_band
        if self.execution_rule == "off":
            band = 0.0
        elif self.execution_rule == "asymmetric":
            band = self.entry_band if plan.core_weight > held_core else self.reduction_band
        elif self.execution_rule == "hold_defense":
            same_regime = (plan.core_weight > 0) == (held_core > 0)
            if (
                ctx.portfolio.weights
                and same_regime
                and abs(plan.core_weight - held_core) < band
                and not plan.missing_core
                and not set(plan.skipped).intersection(ctx.portfolio.weights)
            ):
                return ctx.hold_positions(
                    among=Selection(
                        names=(),
                        considered=max(plan.readable, len(ctx.portfolio.weights)),
                        skipped=plan.skipped,
                    )
                )
        return settle(ctx, plan.weights, band=band, unusable=plan.skipped, readable=plan.readable)


FROZEN_PARAMETERS: tuple[str, ...] = tuple(
    field.name
    for field in fields(SA15Mechanisms)
    if field.name != "strategy_id"
    and field.name not in {key for keys in BLOCK_PARAMETERS.values() for key in keys}
)
"""Fields that must stay identical throughout a categorical mechanism study."""
