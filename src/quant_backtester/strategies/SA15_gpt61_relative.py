"""S&P 500 core with buffered relative-momentum satellites.

The core stays invested when its endpoint signals are available, irrespective
of its trend. Satellites must beat the core's weighted log momentum; unfilled
slots return to the core. All decisions use the evening signal snapshot and
execute through the engine at a following open.
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
class RelativeMomentumPlan:
    """Immutable audit of a core and satellite allocation.

    Attributes
    ----------
    scores : Mapping[str, float]
        Satellite weighted log momentum minus the core's weighted log momentum.
    absolute_scores : Mapping[str, float]
        Weighted log momentum of every fund with all required endpoints.
    selected : tuple[str, ...]
        Satellites retained after eligibility, ranking and incumbent buffering.
    weights : Mapping[str, float]
        Complete target before the rebalancing band.
    skipped : Mapping[str, SignalStatus]
        First reason an instrument lacked a mandatory input.
    readable : int
        Tradable instruments whose required inputs were all usable.
    crash_guard_active : bool
        Whether an explicitly enabled crash threshold triggered defence.
    """

    scores: Mapping[str, float]
    absolute_scores: Mapping[str, float]
    selected: tuple[str, ...]
    weights: Mapping[str, float]
    skipped: Mapping[str, SignalStatus]
    readable: int
    crash_guard_active: bool = False


def buffered_selection(
    scores: Mapping[str, float], held: Mapping[str, float], *, top_k: int, switch_buffer: float
) -> tuple[str, ...]:
    """Rank eligible satellites while retaining incumbents near the entry cutoff.

    Parameters
    ----------
    scores : Mapping[str, float]
        Only eligible, finite relative log-momentum scores at the decision.
    held : Mapping[str, float]
        Actual portfolio weights, rather than previous target weights.
    top_k : int
        Maximum selected satellite names.
    switch_buffer : float
        Retain eligible incumbents at or above the unbuffered cutoff minus
        this gap in log-return units. Ties use identifier order.

    Returns
    -------
    tuple[str, ...]
        Incumbents first by score, then the highest-ranked remaining entrants.
    """
    require_positive_int(top_k, "top_k")
    require_finite_non_negative(switch_buffer, "switch_buffer")
    ranked = sorted(scores, key=lambda name: (-scores[name], name))
    if not ranked:
        return ()
    cutoff = scores[ranked[min(top_k, len(ranked)) - 1]]
    selected = [
        name
        for name in ranked
        if held.get(name, 0.0) > 0.0 and scores[name] >= cutoff - switch_buffer
    ][:top_k]
    selected.extend(name for name in ranked if name not in selected)
    return tuple(selected[:top_k])


@dataclass(frozen=True, slots=True)
class SA15RelativeMomentum(Strategy):
    """Keep an equity core and allocate a few slots to stronger ETF momentum.

    Attributes
    ----------
    core_id, satellite_ids, monetary_id : str, tuple[str, ...], str
        Invested benchmark core, ranked tactical ETFs, and optional defence.
    core_fraction : float
        Minimum core share outside a triggered crash guard.
    top_k : int
        Tactical slots, each of size ``(1-core_fraction)/top_k``. Unfilled or
        capped slot capital returns to the core, without leverage.
    momentum_lookbacks, momentum_weights : tuple
        Own-venue session offsets and nonnegative importance weights.
    skip_recent_sessions : int
        Recent endpoint offset; smaller than every declared lookback.
    minimum_relative_momentum : float
        Minimum mean log-return advantage over the core, strictly exceeded.
    switch_buffer : float
        Advantage required to replace an otherwise eligible incumbent.
    rebalance_band : float
        Small drifts inside this band produce no orders; exits are immediate.
    absolute_filter : bool
        Require strictly positive satellite weighted log momentum.
    satellite_cap : float
        Per-satellite capital cap; any excess goes to the core.
    core_crash_lookback, core_crash_threshold : int, float
        Optional unskipped core return and inclusive crash threshold. The
        default threshold ``-1`` disables the guard completely.
    defensive_fraction : float
        Capital moved out of the core after a crash trigger; placed in the
        monetary ETF only if its 21-session endpoint return is positive.
    max_age_sessions : int
        Accepted latest-price age on the reference calendar.
    strategy_id : str
        Identifier distinct from the frozen first SA15 study.

    Notes
    -----
    A missing mandatory core input targets cash. A missing satellite input
    excludes only that satellite and returns its slot to the core. The default
    policy does not control volatility or time the core's absolute trend.
    Signals use adjusted closes as available at the decision; provider price
    restatements remain a data limitation rather than a reconstructed vintage.
    """

    core_id: str = "ETF_SP500_PEA"
    satellite_ids: tuple[str, ...] = (
        "ETF_NASDAQ",
        "ETF_GOLD",
        "ETF_EMERGING",
        "ETF_COMMODITY",
    )
    monetary_id: str = "ETF_MONETARY_EUR"
    core_fraction: float = 0.5
    top_k: int = 1
    momentum_lookbacks: tuple[int, ...] = (63, 126, 252)
    momentum_weights: tuple[float, ...] = (1.0, 1.0, 1.0)
    skip_recent_sessions: int = 0
    minimum_relative_momentum: float = 0.0
    switch_buffer: float = 0.02
    rebalance_band: float = 0.08
    absolute_filter: bool = True
    satellite_cap: float = 1.0
    core_crash_lookback: int = 63
    core_crash_threshold: float = -1.0
    defensive_fraction: float = 1.0
    max_age_sessions: int = 1
    strategy_id: str = "SA15_GPT-6.1_R2"

    def __post_init__(self) -> None:
        """Freeze configuration sequences and reject invalid research parameters."""
        if isinstance(self.satellite_ids, str):
            raise ValueError("satellite_ids must be a sequence of identifiers")
        object.__setattr__(self, "satellite_ids", tuple(self.satellite_ids))
        object.__setattr__(self, "momentum_lookbacks", tuple(self.momentum_lookbacks))
        object.__setattr__(self, "momentum_weights", tuple(self.momentum_weights))
        for name in (self.core_id, self.monetary_id, self.strategy_id, *self.satellite_ids):
            require_identifier(name, "an identifier")
        roles = (self.core_id, self.monetary_id, *self.satellite_ids)
        if len(set(roles)) != len(roles):
            raise ValueError("core, satellite and monetary identifiers must be distinct")
        require_positive_int(self.top_k, "top_k")
        require_non_negative_int(self.skip_recent_sessions, "skip_recent_sessions")
        require_non_negative_int(self.max_age_sessions, "max_age_sessions")
        require_positive_int(self.core_crash_lookback, "core_crash_lookback")
        if (
            not self.momentum_lookbacks
            or len(self.momentum_lookbacks) != len(self.momentum_weights)
            or len(set(self.momentum_lookbacks)) != len(self.momentum_lookbacks)
        ):
            raise ValueError(
                "distinct momentum lookbacks and weights need the same positive length"
            )
        for lookback in self.momentum_lookbacks:
            require_positive_int(lookback, "a momentum lookback")
            if self.skip_recent_sessions >= lookback:
                raise ValueError("skip_recent_sessions must be below every momentum lookback")
        for weight in self.momentum_weights:
            require_finite_non_negative(weight, "a momentum weight")
        if max(self.momentum_weights) <= 0.0:
            raise ValueError("at least one momentum weight must be positive")
        if not isinstance(self.absolute_filter, bool):
            raise ValueError("absolute_filter must be True or False")
        for name in ("core_fraction", "rebalance_band", "satellite_cap", "defensive_fraction"):
            require_unit_fraction(getattr(self, name), name)
        require_finite(self.minimum_relative_momentum, "minimum_relative_momentum")
        require_finite_non_negative(self.switch_buffer, "switch_buffer")
        require_finite(self.core_crash_threshold, "core_crash_threshold")
        if not -1.0 <= self.core_crash_threshold <= 0.0:
            raise ValueError("core_crash_threshold must lie in [-1, 0]")
        self.validate()

    def crash_guard_enabled(self) -> bool:
        """Return whether the explicitly configured crash guard can change holdings."""
        return self.core_crash_threshold > -1.0 and self.defensive_fraction > 0.0

    def momentum_signal(self, sessions: int, skip: int | None = None) -> Signal:
        """Return exact endpoint momentum with the declared or overridden skip."""
        skip = self.skip_recent_sessions if skip is None else skip
        return EndpointMomentumSignal(
            signal_id=f"sa15r2_endpoint_{sessions}s_skip{skip}",
            lookback_sessions=sessions,
            skip_recent_sessions=skip,
            max_age_sessions=self.max_age_sessions,
        )

    def required_signals(self) -> Sequence[Signal | SignalRequest]:
        """Declare endpoint momentum and only explicitly enabled defence inputs."""
        names = (self.core_id, *self.satellite_ids)
        requests = [
            SignalRequest(self.momentum_signal(window), names)
            for window, weight in zip(self.momentum_lookbacks, self.momentum_weights, strict=True)
            if weight > 0.0
        ]
        if self.crash_guard_enabled():
            requests.extend(
                (
                    SignalRequest(
                        self.momentum_signal(self.core_crash_lookback, 0), (self.core_id,)
                    ),
                    SignalRequest(self.momentum_signal(21, 0), (self.monetary_id,)),
                )
            )
        return merged_requests(requests)

    def _absolute_score(
        self, reader: SignalReader, name: str, skipped: dict[str, SignalStatus]
    ) -> float | None:
        """Read every mandatory endpoint and average log returns with fixed weights."""
        terms: list[float] = []
        missing = False
        largest = max(self.momentum_weights)
        scaled = [weight / largest for weight in self.momentum_weights]
        denominator = math.fsum(scaled)
        for window, weight in zip(self.momentum_lookbacks, scaled, strict=True):
            if weight == 0.0:
                continue
            value = reader.value(self.momentum_signal(window), name)
            if value is None:
                missing = True
            elif value <= -1.0 or not math.isfinite(value):
                skipped.setdefault(name, SignalStatus.INVALID_INPUT)
                missing = True
            else:
                terms.append(math.log1p(value) * weight / denominator)
        return None if missing else math.fsum(terms)

    def plan(self, ctx: StrategyContext) -> RelativeMomentumPlan:
        """Return relative scores, buffered satellites and the complete core target."""
        reader = SignalReader(ctx)
        skipped: dict[str, SignalStatus] = {}
        absolute: dict[str, float] = {}
        scores: dict[str, float] = {}
        selected: tuple[str, ...] = ()
        weights: dict[str, float] = {}
        core_score = self._absolute_score(reader, self.core_id, skipped)
        if core_score is not None:
            absolute[self.core_id] = core_score
        guard = None
        if self.crash_guard_enabled():
            guard = reader.value(self.momentum_signal(self.core_crash_lookback, 0), self.core_id)
        core_usable = (
            core_score is not None
            and self.core_id in ctx.universe
            and (not self.crash_guard_enabled() or guard is not None)
        )
        triggered = bool(core_usable and guard is not None and guard <= self.core_crash_threshold)
        for name in self.satellite_ids:
            value = self._absolute_score(reader, name, skipped)
            if value is not None:
                absolute[name] = value
                if core_score is not None:
                    scores[name] = value - core_score
        if core_usable:
            if triggered:
                weights[self.core_id] = 1.0 - self.defensive_fraction
                carry = reader.value(self.momentum_signal(21, 0), self.monetary_id)
                if carry is not None and carry > 0.0 and self.monetary_id in ctx.universe:
                    weights[self.monetary_id] = self.defensive_fraction
            else:
                eligible = {
                    name: score
                    for name, score in scores.items()
                    if score > self.minimum_relative_momentum
                    and (not self.absolute_filter or absolute[name] > 0.0)
                    and name in ctx.universe
                }
                selected = buffered_selection(
                    eligible,
                    ctx.portfolio.weights,
                    top_k=self.top_k,
                    switch_buffer=self.switch_buffer,
                )
                slot = min((1.0 - self.core_fraction) / self.top_k, self.satellite_cap)
                weights = {name: slot for name in selected if slot > 0.0}
                weights[self.core_id] = max(0.0, 1.0 - math.fsum(weights.values()))
        for name, status in reader.unusable.items():
            skipped.setdefault(name, status)
        return RelativeMomentumPlan(
            scores=MappingProxyType(scores),
            absolute_scores=MappingProxyType(absolute),
            selected=selected,
            weights=MappingProxyType(
                {name: value for name, value in weights.items() if value > 0.0}
            ),
            skipped=MappingProxyType(skipped),
            readable=reader.readable,
            crash_guard_active=triggered,
        )

    def decide(self, ctx: StrategyContext) -> TargetAllocation:
        """Apply one band to the complete target while never postponing exits."""
        plan = self.plan(ctx)
        return settle(
            ctx,
            plan.weights,
            band=self.rebalance_band,
            caps=dict.fromkeys(self.satellite_ids, self.satellite_cap),
            unusable=plan.skipped,
            readable=plan.readable,
        )
