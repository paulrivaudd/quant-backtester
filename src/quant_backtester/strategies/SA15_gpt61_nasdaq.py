"""Nasdaq core with conditional defence and an explicit fast recovery rule.

The default is fully invested Nasdaq. Weak slow momentum plus a fast fall can
reduce it; positive fast momentum restores it without waiting for the slow
window. All inputs are evening signals and all orders use the engine's next
executable open. Adjusted-price provider restatements remain a data limitation.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.numbers import (
    require_finite,
    require_finite_non_negative,
    require_unit_fraction,
)
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.signals.base import Signal
from quant_backtester.signals.engine import SignalRequest
from quant_backtester.signals.price.endpoint_momentum import EndpointMomentumSignal
from quant_backtester.signals.price.trend import MovingAverageTrendSignal
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
class NasdaqAdaptivePlan:
    """Immutable explanation of one evening allocation.

    Attributes
    ----------
    regime : str
        ``nasdaq``, ``defensive``, ``relative`` or ``missing_core``.
    core_fast, core_slow, core_trend : float | None
        Available fast/slow returns and price-over-average distance.
    absolute_scores, relative_scores : Mapping[str, float]
        Weighted log momentum and, when enabled, its advantage over Nasdaq.
    selected : tuple[str, ...]
        Selected defensive ETFs, after eligibility and incumbent buffering.
    weights : Mapping[str, float]
        Complete target before the execution band.
    skipped : Mapping[str, SignalStatus]
        First missing or invalid input reason per instrument.
    readable : int
        Tradable names whose required inputs were usable.
    was_defensive : bool
        Defensive exposure inferred exclusively from the actual held book.
    recovery : bool
        Fast recovery that restores the complete Nasdaq target.
    """

    regime: str
    core_fast: float | None
    core_slow: float | None
    core_trend: float | None
    absolute_scores: Mapping[str, float]
    relative_scores: Mapping[str, float]
    selected: tuple[str, ...]
    weights: Mapping[str, float]
    skipped: Mapping[str, SignalStatus]
    readable: int
    was_defensive: bool
    recovery: bool


@dataclass(frozen=True, slots=True)
class SA15NasdaqAdaptive(Strategy):
    """Keep Nasdaq invested, with bounded defensive allocations when justified.

    Attributes
    ----------
    core_id, defensive_ids, monetary_id : str, tuple[str, ...], str
        Nasdaq core, ranked defensive ETFs and optional monetary fallback.
    guard_mode, trend_sessions : str, int
        ``momentum`` uses the slow return; ``trend`` uses close/MA minus one
        with ``trend_sessions >= 2``. Zero disables the unused average.
    fast_lookback, slow_lookback : int
        Own-venue endpoint return windows.
    fast_entry_threshold, slow_entry_threshold, recovery_threshold : float
        Initial defence requires fast return at or below its entry threshold
        and a weak core. In momentum mode weak means slow return at or below
        its threshold; trend mode means MA distance at or below zero. Fast
        return at or above recovery always overrides the defensive guard.
    core_floor : float
        Nasdaq target during defence or an enabled relative rotation. Its
        complement is the entire defensive budget, with no leverage.
    defensive_lookbacks, defensive_weights : tuple
        Windows and nonnegative weights of mean log momentum for defence.
    top_k, switch_buffer : int, float
        Maximum defensive names and log-score buffer for held incumbents.
    rebalance_band : float
        Final weight band; complete exits and full fast recovery override it.
    relative_rotation, relative_threshold : bool, float
        Explicit optional rotation outside a triggered guard. A defence's
        weighted log momentum must exceed Nasdaq by the threshold; an
        incumbent may retain a buffer below that entry threshold.
    monetary_lookback : int
        Positive endpoint return required for a monetary fallback.
    max_age_sessions : int
        Accepted freshest-price age on the reference calendar.
    strategy_id : str
        Stable identifier of this separate third research series.

    Notes
    -----
    There is no hidden regime or stop state. Actual defensive positions imply
    an existing defensive allocation. A positive Nasdaq position below the
    midpoint between ``core_floor`` and one also identifies defence left in
    cash after costs, lot rounding or rejected defensive purchases. An empty
    cash book uses initial entry conditions, including after a full cash exit.

    A relative position can therefore maintain defence if the core subsequently
    becomes weak; this coupling is deliberate and observable in the book.
    Recovery overrides the guard but does not disable an explicitly requested
    relative rotation. Defensive capital is split fully across selected positive
    absolute-momentum funds; none eligible means positive-carry monetary or cash.
    Missing mandatory Nasdaq inputs target cash; a missing defensive ETF is
    excluded individually. There is no model fit or volatility targeting.
    """

    core_id: str = "ETF_NASDAQ"
    defensive_ids: tuple[str, ...] = ("ETF_GOLD", "ETF_SP500_PEA")
    monetary_id: str = "ETF_MONETARY_EUR"
    guard_mode: str = "momentum"
    trend_sessions: int = 0
    fast_lookback: int = 21
    slow_lookback: int = 126
    fast_entry_threshold: float = -0.04
    slow_entry_threshold: float = 0.0
    recovery_threshold: float = 0.0
    core_floor: float = 0.5
    defensive_lookbacks: tuple[int, ...] = (63, 126)
    defensive_weights: tuple[float, ...] = (1.0, 1.0)
    top_k: int = 1
    switch_buffer: float = 0.02
    rebalance_band: float = 0.08
    relative_rotation: bool = False
    relative_threshold: float = 0.02
    monetary_lookback: int = 21
    max_age_sessions: int = 1
    strategy_id: str = "SA15_GPT-6.1_R3"

    def __post_init__(self) -> None:
        """Freeze sequences and reject ambiguous or invalid policy parameters."""
        if isinstance(self.defensive_ids, str):
            raise ValueError("defensive_ids must be a sequence of identifiers")
        object.__setattr__(self, "defensive_ids", tuple(self.defensive_ids))
        object.__setattr__(self, "defensive_lookbacks", tuple(self.defensive_lookbacks))
        object.__setattr__(self, "defensive_weights", tuple(self.defensive_weights))
        names = (self.core_id, self.monetary_id, *self.defensive_ids)
        for name in (*names, self.strategy_id):
            require_identifier(name, "an identifier")
        if len(set(names)) != len(names):
            raise ValueError("core, defensive and monetary identifiers must be distinct")
        if self.guard_mode not in {"momentum", "trend"}:
            raise ValueError("guard_mode must be momentum or trend")
        require_non_negative_int(self.trend_sessions, "trend_sessions")
        if self.trend_sessions == 1 or (self.guard_mode == "trend" and self.trend_sessions < 2):
            raise ValueError("trend mode needs trend_sessions >= 2; zero disables the average")
        for name in ("fast_lookback", "slow_lookback", "top_k", "monetary_lookback"):
            require_positive_int(getattr(self, name), name)
        require_non_negative_int(self.max_age_sessions, "max_age_sessions")
        if self.fast_lookback >= self.slow_lookback:
            raise ValueError("fast_lookback must be smaller than slow_lookback")
        if (
            not self.defensive_lookbacks
            or len(self.defensive_lookbacks) != len(self.defensive_weights)
            or len(set(self.defensive_lookbacks)) != len(self.defensive_lookbacks)
        ):
            raise ValueError("distinct defensive windows and weights need the same positive length")
        for window in self.defensive_lookbacks:
            require_positive_int(window, "a defensive lookback")
        for weight in self.defensive_weights:
            require_finite_non_negative(weight, "a defensive weight")
        if max(self.defensive_weights) <= 0.0:
            raise ValueError("at least one defensive weight must be positive")
        for name in ("fast_entry_threshold", "slow_entry_threshold", "recovery_threshold"):
            require_finite(getattr(self, name), name)
            if getattr(self, name) <= -1.0:
                raise ValueError(f"{name} must exceed a return of -100%")
        if self.fast_entry_threshold > self.recovery_threshold:
            raise ValueError("fast_entry_threshold cannot exceed recovery_threshold")
        for name in ("core_floor", "rebalance_band"):
            require_unit_fraction(getattr(self, name), name)
        for name in ("switch_buffer", "relative_threshold"):
            require_finite_non_negative(getattr(self, name), name)
        if not isinstance(self.relative_rotation, bool):
            raise ValueError("relative_rotation must be True or False")
        self.validate()

    def momentum_signal(self, sessions: int) -> Signal:
        """Return adjusted-close momentum between two exact venue-session dates."""
        return EndpointMomentumSignal(
            signal_id=f"sa15r3_endpoint_{sessions}s",
            lookback_sessions=sessions,
            max_age_sessions=self.max_age_sessions,
        )

    def trend_signal(self) -> Signal:
        """Return a standard consecutive-session adjusted-price MA distance."""
        return MovingAverageTrendSignal(
            signal_id=f"sa15r3_price_over_ma{self.trend_sessions}",
            window_sessions=self.trend_sessions,
            price_basis=PriceBasis.ADJUSTED,
            max_age_sessions=self.max_age_sessions,
        )

    def required_signals(self) -> Sequence[Signal | SignalRequest]:
        """Declare only signals needed by the configured guard and rotation."""
        requests = [SignalRequest(self.momentum_signal(self.fast_lookback), (self.core_id,))]
        if self.guard_mode == "momentum":
            requests.append(
                SignalRequest(self.momentum_signal(self.slow_lookback), (self.core_id,))
            )
        else:
            requests.append(SignalRequest(self.trend_signal(), (self.core_id,)))
        score_names = (
            (*self.defensive_ids, self.core_id) if self.relative_rotation else self.defensive_ids
        )
        requests.extend(
            SignalRequest(self.momentum_signal(window), score_names)
            for window, weight in zip(self.defensive_lookbacks, self.defensive_weights, strict=True)
            if weight > 0.0 and score_names
        )
        requests.append(
            SignalRequest(self.momentum_signal(self.monetary_lookback), (self.monetary_id,))
        )
        return merged_requests(requests)

    def _return(
        self, reader: SignalReader, name: str, window: int, skipped: dict[str, SignalStatus]
    ) -> float | None:
        """Read a finite endpoint return that can be transformed to log units."""
        value = reader.value(self.momentum_signal(window), name)
        if value is not None and (value <= -1.0 or not math.isfinite(value)):
            skipped.setdefault(name, SignalStatus.INVALID_INPUT)
            return None
        return value

    def _score(
        self, reader: SignalReader, name: str, skipped: dict[str, SignalStatus]
    ) -> float | None:
        """Average available mandatory log returns with normalized fixed weights."""
        scaled = [weight / max(self.defensive_weights) for weight in self.defensive_weights]
        total = math.fsum(scaled)
        missing = False
        terms = []
        for window, weight in zip(self.defensive_lookbacks, scaled, strict=True):
            if weight <= 0.0:
                continue
            value = self._return(reader, name, window, skipped)
            if value is None:
                missing = True
            else:
                terms.append(math.log1p(value) * weight / total)
        return None if missing else math.fsum(terms)

    def _was_defensive(self, ctx: StrategyContext) -> bool:
        """Infer prior allocation solely from actual defensive or reduced core holdings."""
        if self.core_floor >= 1.0:
            return False
        held = ctx.portfolio.weights
        if any(held.get(name, 0.0) > 0.0 for name in (*self.defensive_ids, self.monetary_id)):
            return True
        core_weight = held.get(self.core_id, 0.0)
        return 0.0 < core_weight < (1.0 + self.core_floor) / 2.0

    def _select(self, scores: Mapping[str, float], held: Mapping[str, float]) -> tuple[str, ...]:
        """Retain eligible held funds near the entry cutoff, with deterministic ties."""
        ranked = sorted(scores, key=lambda name: (-scores[name], name))
        if not ranked:
            return ()
        cutoff = scores[ranked[min(self.top_k, len(ranked)) - 1]] - self.switch_buffer
        incumbents = [
            name for name in ranked if held.get(name, 0.0) > 0.0 and scores[name] >= cutoff
        ]
        selected = incumbents[: self.top_k]
        selected.extend(name for name in ranked if name not in selected)
        return tuple(selected[: self.top_k])

    def plan(self, ctx: StrategyContext) -> NasdaqAdaptivePlan:
        """Explain the conditional guard, optional relative rotation and complete target."""
        reader = SignalReader(ctx)
        skipped: dict[str, SignalStatus] = {}
        fast = self._return(reader, self.core_id, self.fast_lookback, skipped)
        slow = None
        trend = None
        if self.guard_mode == "momentum":
            slow = self._return(reader, self.core_id, self.slow_lookback, skipped)
            primary = slow
            weak = slow is not None and slow <= self.slow_entry_threshold
        else:
            trend = reader.value(self.trend_signal(), self.core_id)
            primary = trend
            weak = trend is not None and trend <= 0.0
        scores: dict[str, float] = {}
        for name in self.defensive_ids:
            score = self._score(reader, name, skipped)
            if score is not None:
                scores[name] = score
        core_score = self._score(reader, self.core_id, skipped) if self.relative_rotation else None
        relative = (
            {name: score - core_score for name, score in scores.items()}
            if core_score is not None
            else {}
        )
        core_usable = (
            fast is not None
            and primary is not None
            and self.core_id in ctx.universe
            and (not self.relative_rotation or core_score is not None)
        )
        was_defensive = self._was_defensive(ctx)
        guard = bool(
            core_usable
            and fast is not None
            and fast < self.recovery_threshold
            and weak
            and (was_defensive or fast <= self.fast_entry_threshold)
        )
        positive = {
            name: score for name, score in scores.items() if score > 0.0 and name in ctx.universe
        }
        relative_eligible = (
            {
                name: score
                for name, score in positive.items()
                if name in relative
                and relative[name]
                > self.relative_threshold
                - (self.switch_buffer if ctx.portfolio.weights.get(name, 0.0) > 0.0 else 0.0)
            }
            if self.relative_rotation
            else {}
        )
        regime = "missing_core"
        selected: tuple[str, ...] = ()
        weights: dict[str, float] = {}
        if core_usable:
            regime = "defensive" if guard else "relative" if relative_eligible else "nasdaq"
            if regime == "nasdaq" or self.core_floor >= 1.0:
                regime = "nasdaq"
                weights[self.core_id] = 1.0
            else:
                weights[self.core_id] = self.core_floor
                selected = self._select(
                    positive if guard else relative_eligible, ctx.portfolio.weights
                )
                pocket = 1.0 - self.core_floor
                if selected:
                    weights.update({name: pocket / len(selected) for name in selected})
                else:
                    carry = self._return(reader, self.monetary_id, self.monetary_lookback, skipped)
                    if carry is not None and carry > 0.0 and self.monetary_id in ctx.universe:
                        weights[self.monetary_id] = pocket
        for name, status in reader.unusable.items():
            skipped.setdefault(name, status)
        recovery = bool(
            core_usable
            and was_defensive
            and fast is not None
            and fast >= self.recovery_threshold
            and regime == "nasdaq"
        )
        return NasdaqAdaptivePlan(
            regime=regime,
            core_fast=fast,
            core_slow=slow,
            core_trend=trend,
            absolute_scores=MappingProxyType(scores),
            relative_scores=MappingProxyType(relative),
            selected=selected,
            weights=MappingProxyType(
                {name: value for name, value in weights.items() if value > 0.0}
            ),
            skipped=MappingProxyType(skipped),
            readable=reader.readable,
            was_defensive=was_defensive,
            recovery=recovery,
        )

    def decide(self, ctx: StrategyContext) -> TargetAllocation:
        """Send a complete next-open target with one band and explicit fast recovery."""
        plan = self.plan(ctx)
        return settle(
            ctx,
            plan.weights,
            band=self.rebalance_band,
            force=plan.recovery,
            unusable=plan.skipped,
            readable=plan.readable,
        )
