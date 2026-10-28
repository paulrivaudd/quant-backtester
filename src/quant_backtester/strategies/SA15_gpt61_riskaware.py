"""Low-turnover ETF rotation, trend ensembles and bounded offensive risk.

The policy sees only evening signal snapshots. Adjusted provider prices may
have been restated; no historical vintage is reconstructed here. The engine
executes the complete target at a following tradable open. All allocations are
long-only, cash-funded, and contain no fitted model or hidden mutable state.
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
from quant_backtester.signals.price.endpoint_momentum import EndpointMomentumSignal
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
from quant_backtester.strategies.base import Strategy


@dataclass(frozen=True, slots=True)
class RiskAwarePlan:
    """Immutable audit of the target before the common execution band.

    Attributes
    ----------
    mode : str
        Explicit configured family, never inferred from past results.
    scores : Mapping[str, float]
        Weighted endpoint log momentum of risky and defensive instruments.
    trend_fraction, canary_breadth : float
        Positive weighted core votes and positive canary-asset share. A
        disabled canary reports breadth one.
    selected : tuple[str, ...]
        Offensive instruments selected before the risk cap.
    offensive_weights : Mapping[str, float]
        Offensive sleeve after canary gating and optional risk scaling.
    offensive_volatility : float | None
        Conservative pre-scaling annual risk estimate, sum(weight * vol).
        Each vol is the largest configured historical estimate. This is not
        the volatility of the complete portfolio and includes no defence.
    risk_scale : float
        Final multiplier on the offensive sleeve, between zero and one.
    recovery : bool
        Whether a configured positive short return restored directional votes.
    weights : Mapping[str, float]
        Complete target, with uninvested capital left as cash.
    skipped : Mapping[str, SignalStatus]
        First unavailable or invalid signal reason per instrument.
    readable : int
        Tradable instruments with readable required signals.
    """

    mode: str
    scores: Mapping[str, float]
    trend_fraction: float
    canary_breadth: float
    selected: tuple[str, ...]
    offensive_weights: Mapping[str, float]
    offensive_volatility: float | None
    risk_scale: float
    recovery: bool
    weights: Mapping[str, float]
    skipped: Mapping[str, SignalStatus]
    readable: int


@dataclass(frozen=True, slots=True)
class SA15RiskAwareRotation(Strategy):
    """Combine a declared allocation family with optional canaries and risk cap.

    Parameters
    ----------
    core_id, risky_ids, defensive_ids, monetary_id : str or tuple[str, ...]
        Benchmark core, offensive universe, ranked fallback funds and monetary
        fallback. Risky and defensive roles may overlap; core and monetary
        cannot be defensive, and monetary cannot be risky. Canaries may be
        tradable funds or external gauges supported by endpoint price signals.
    mode : {"rotate", "ensemble", "vol_control", "balanced"}
        Rotate ranks eligible offensive momentum. Ensemble allocates the core
        according to weighted positive horizon votes. Vol control starts with
        the core then applies the declared risk cap. Balanced holds every
        available offensive fund without any momentum eligibility filter.
    momentum_lookbacks, momentum_weights : tuple
        Own-venue endpoint horizons and weights for ranking and defence. In
        moving-average ensemble mode these horizons are MA lengths for core
        votes; defensive ranking remains endpoint momentum.
    trend_kind : {"momentum", "moving_average"}
        Ensemble vote source. A vote is positive strictly above zero.
    core_floor : float
        Reserved core share in rotate, and minimum directional share in
        ensemble before canary gating and the risk cap. A missing core signal
        cannot force an allocation. The volatility cap may reduce this floor.
    top_k, allocation_mode : int, {"equal", "inverse_vol", "fixed"}
        Offensive selection count (at most three) and allocation among selected
        names. Balanced holds all its at most three configured offensive names.
    fixed_weights : tuple[float, ...]
        Explicit weights aligned with risky_ids, summing to one, for balanced
        fixed mode. Missing funds are excluded and the remaining positive
        weights renormalized. Other modes leave this tuple empty.
    absolute_filter : bool
        Rotate eligibility requires strictly positive raw momentum if true.
    core_preference, switch_buffer : float
        Log-score bonuses for the core and actual held offensive incumbents.
        These affect ranking only, after absolute eligibility. Defensive
        incumbents receive the same switch buffer.
    rebalance_band : float
        Maximum individual weight drift tolerated by the common settlement
        helper; complete exits are never delayed.
    canary_ids, canary_lookbacks, canary_weights : tuple
        Optional cross-asset canaries. Each has positive weighted log momentum
        or a negative vote; missing canaries count as negative, not removed.
    canary_min_breadth : float
        Minimum inclusive share of positive canary assets needed to permit
        tactical risk above the reserved core floor. Zero disables gating even
        if all canaries are negative; an empty canary list also disables it.
    volatility_windows, volatility_floor, target_volatility : tuple, float, float
        Consecutive-session log-return volatility estimates, annualised with
        252 sessions. Target zero disables the cap except vol_control requires
        a positive target. A positive target caps the offensive risk estimate
        sum(weight * max(window vols, floor)). This ignores defensive risk;
        it is not a guarantee or a total portfolio volatility target.
    recovery_lookback, recovery_threshold : int, float
        Zero disables short recovery. In ensemble, a return strictly above the
        threshold restores core votes before canary gating and risk scaling.
        Other families already rank or size current risk without a recovery
        state and do not read this signal.
    defensive_top_k, monetary_lookback, max_age_sessions : int
        Ranked positive-momentum defence slots (at most three), strictly
        positive monetary carry horizon and accepted reference-session age.
    strategy_id : str
        Separate identity for this fourth research series.

    Notes
    -----
    Unavailable offensive inputs exclude only the affected instrument. An
    ensemble with missing mandatory core votes has no offensive allocation.
    Balanced/equal requires a fresh one-session endpoint return to establish
    availability, not its sign. Inverse-volatility or enabled risk caps require
    every volatility window for an individual name. Missing defence excludes
    that name; any residual uses positive monetary carry or unremunerated cash.
    No positions are reconstructed from previous targets: ranking hysteresis
    reads actual weights only. A declared positive core floor plus selection
    still holds at most three offensive names.
    """

    core_id: str = "ETF_NASDAQ"
    risky_ids: tuple[str, ...] = ("ETF_NASDAQ", "ETF_GOLD", "ETF_SP500_PEA")
    defensive_ids: tuple[str, ...] = ("ETF_GOLD", "ETF_EURO_GOV")
    monetary_id: str = "ETF_MONETARY_EUR"
    mode: str = "rotate"
    momentum_lookbacks: tuple[int, ...] = (21, 63, 126)
    momentum_weights: tuple[float, ...] = (1.0, 1.0, 1.0)
    trend_kind: str = "momentum"
    core_floor: float = 0.0
    top_k: int = 1
    allocation_mode: str = "equal"
    fixed_weights: tuple[float, ...] = ()
    absolute_filter: bool = True
    core_preference: float = 0.02
    switch_buffer: float = 0.02
    rebalance_band: float = 0.10
    canary_ids: tuple[str, ...] = ()
    canary_lookbacks: tuple[int, ...] = (21, 63, 126)
    canary_weights: tuple[float, ...] = (1.0, 1.0, 1.0)
    canary_min_breadth: float = 0.5
    volatility_windows: tuple[int, ...] = (20, 60)
    volatility_floor: float = 0.05
    target_volatility: float = 0.0
    recovery_lookback: int = 0
    recovery_threshold: float = 0.0
    defensive_top_k: int = 1
    monetary_lookback: int = 21
    max_age_sessions: int = 1
    strategy_id: str = "SA15_GPT-6.1_R4"

    def __post_init__(self) -> None:
        """Freeze all declared sequences and reject ambiguous configurations."""
        for name in (
            "risky_ids",
            "defensive_ids",
            "momentum_lookbacks",
            "momentum_weights",
            "canary_ids",
            "canary_lookbacks",
            "canary_weights",
            "volatility_windows",
            "fixed_weights",
        ):
            value = getattr(self, name)
            if isinstance(value, str):
                raise ValueError(f"{name} must be a sequence, not a string")
            object.__setattr__(self, name, tuple(value))
        for names in (self.risky_ids, self.defensive_ids, self.canary_ids):
            if len(set(names)) != len(names):
                raise ValueError("each instrument list must have distinct identifiers")
            for name in names:
                require_identifier(name, "an instrument identifier")
        for name in (self.core_id, self.monetary_id, self.strategy_id):
            require_identifier(name, "an identifier")
        if not self.risky_ids or self.core_id not in self.risky_ids:
            raise ValueError("risky_ids must contain the declared core")
        if self.core_id == self.monetary_id or self.monetary_id in self.risky_ids:
            raise ValueError("monetary and offensive roles must be distinct")
        if self.core_id in self.defensive_ids or self.monetary_id in self.defensive_ids:
            raise ValueError("core and monetary cannot be ranked defensive funds")
        if self.mode not in {"rotate", "ensemble", "vol_control", "balanced"}:
            raise ValueError("unknown allocation mode")
        if self.mode == "balanced" and len(self.risky_ids) > 3:
            raise ValueError("balanced holds at most three offensive funds")
        if self.allocation_mode not in {"equal", "inverse_vol", "fixed"}:
            raise ValueError("allocation_mode must be equal, inverse_vol or fixed")
        if self.allocation_mode == "fixed":
            if self.mode != "balanced" or len(self.fixed_weights) != len(self.risky_ids):
                raise ValueError("fixed allocation needs balanced and aligned fixed_weights")
            for weight in self.fixed_weights:
                require_finite_non_negative(weight, "a fixed weight")
            if not math.isclose(math.fsum(self.fixed_weights), 1.0, abs_tol=1e-12, rel_tol=0):
                raise ValueError("fixed weights must sum to one")
        elif self.fixed_weights:
            raise ValueError("fixed_weights are only meaningful with fixed allocation")
        if self.trend_kind not in {"momentum", "moving_average"}:
            raise ValueError("trend_kind must be momentum or moving_average")
        self._validate_horizons(self.momentum_lookbacks, self.momentum_weights, "momentum")
        self._validate_horizons(self.canary_lookbacks, self.canary_weights, "canary")
        if self.trend_kind == "moving_average" and min(self.momentum_lookbacks) < 2:
            raise ValueError("moving-average horizons must be at least two sessions")
        for name in ("top_k", "defensive_top_k", "monetary_lookback"):
            require_positive_int(getattr(self, name), name)
        if max(self.top_k, self.defensive_top_k) > 3:
            raise ValueError("at most three offensive or defensive slots are allowed")
        for name in ("max_age_sessions", "recovery_lookback"):
            require_non_negative_int(getattr(self, name), name)
        for name in ("core_floor", "rebalance_band", "canary_min_breadth"):
            require_unit_fraction(getattr(self, name), name)
        for name in ("core_preference", "switch_buffer", "target_volatility", "recovery_threshold"):
            require_finite_non_negative(getattr(self, name), name)
        require_finite_positive(self.volatility_floor, "volatility_floor")
        if not self.volatility_windows or len(set(self.volatility_windows)) != len(
            self.volatility_windows
        ):
            raise ValueError("volatility_windows need distinct nonempty horizons")
        for window in self.volatility_windows:
            require_positive_int(window, "a volatility window")
            if window < 2:
                raise ValueError("a sample volatility requires at least two returns")
        if self.mode == "vol_control" and self.target_volatility <= 0:
            raise ValueError("vol_control requires a positive target_volatility")
        if not isinstance(self.absolute_filter, bool):
            raise ValueError("absolute_filter must be a bool")
        self.validate()

    @staticmethod
    def _validate_horizons(windows: tuple[int, ...], weights: tuple[float, ...], name: str) -> None:
        if not windows or len(windows) != len(weights) or len(set(windows)) != len(windows):
            raise ValueError(f"{name} needs distinct horizons and equally many weights")
        for window in windows:
            require_positive_int(window, f"a {name} horizon")
        for weight in weights:
            require_finite_non_negative(weight, f"a {name} weight")
        if max(weights) <= 0:
            raise ValueError(f"{name} needs a positive weight")

    def momentum_signal(self, sessions: int) -> Signal:
        """Return exact adjusted-close endpoint momentum with freshness guards."""
        return EndpointMomentumSignal(
            signal_id=f"sa15r4_endpoint_{sessions}s",
            lookback_sessions=sessions,
            max_age_sessions=self.max_age_sessions,
        )

    def trend_signal(self, sessions: int) -> Signal:
        """Return close divided by an exact consecutive-session adjusted MA."""
        return MovingAverageTrendSignal(
            signal_id=f"sa15r4_price_over_ma{sessions}",
            window_sessions=sessions,
            price_basis=PriceBasis.ADJUSTED,
            max_age_sessions=self.max_age_sessions,
        )

    def volatility_signal(self, returns: int) -> Signal:
        """Return annual sample volatility of consecutive adjusted log returns."""
        return RealizedVolatilitySignal(
            signal_id=f"sa15r4_volatility_{returns}r",
            window_returns=returns,
            price_basis=PriceBasis.ADJUSTED,
            annualization=252,
            logarithmic=True,
            ddof=1,
            max_age_sessions=self.max_age_sessions,
        )

    def needs_volatility(self) -> bool:
        """Return whether allocation or risk scaling needs historical volatility."""
        return self.allocation_mode == "inverse_vol" or self.target_volatility > 0

    def required_signals(self) -> Sequence[Signal | SignalRequest]:
        """Declare only family-specific inputs and explicit fallback signals."""
        requests: list[SignalRequest] = []
        if self.mode == "rotate":
            requests.extend(
                SignalRequest(self.momentum_signal(window), self.risky_ids)
                for window, weight in zip(
                    self.momentum_lookbacks, self.momentum_weights, strict=True
                )
                if weight > 0
            )
        elif self.mode == "ensemble":
            if self.trend_kind == "moving_average":
                requests.append(SignalRequest(self.momentum_signal(1), (self.core_id,)))
            requests.extend(
                SignalRequest(
                    self.trend_signal(window)
                    if self.trend_kind == "moving_average"
                    else self.momentum_signal(window),
                    (self.core_id,),
                )
                for window, weight in zip(
                    self.momentum_lookbacks, self.momentum_weights, strict=True
                )
                if weight > 0
            )
            if self.recovery_lookback > 0:
                requests.append(
                    SignalRequest(self.momentum_signal(self.recovery_lookback), (self.core_id,))
                )
        else:
            names = self.risky_ids if self.mode == "balanced" else (self.core_id,)
            requests.append(SignalRequest(self.momentum_signal(1), names))
        requests.extend(
            SignalRequest(self.momentum_signal(window), self.defensive_ids)
            for window, weight in zip(self.momentum_lookbacks, self.momentum_weights, strict=True)
            if weight > 0 and self.defensive_ids
        )
        requests.extend(
            SignalRequest(self.momentum_signal(window), self.canary_ids)
            for window, weight in zip(self.canary_lookbacks, self.canary_weights, strict=True)
            if weight > 0 and self.canary_ids
        )
        if self.needs_volatility():
            names = self.risky_ids if self.mode in {"rotate", "balanced"} else (self.core_id,)
            requests.extend(
                SignalRequest(self.volatility_signal(window), names)
                for window in self.volatility_windows
            )
        requests.append(
            SignalRequest(self.momentum_signal(self.monetary_lookback), (self.monetary_id,))
        )
        return merged_requests(requests)

    @staticmethod
    def _positive_weights(weights: tuple[float, ...]) -> tuple[float, ...]:
        largest = max(weights)
        scaled = tuple(weight / largest for weight in weights)
        total = math.fsum(scaled)
        return tuple(weight / total for weight in scaled)

    def _return(
        self, reader: SignalReader, name: str, window: int, skipped: dict[str, SignalStatus]
    ) -> float | None:
        value = reader.value(self.momentum_signal(window), name)
        if value is not None and (not math.isfinite(value) or value <= -1):
            skipped.setdefault(name, SignalStatus.INVALID_INPUT)
            return None
        return value

    def _score(
        self,
        reader: SignalReader,
        name: str,
        skipped: dict[str, SignalStatus],
        *,
        canary: bool = False,
    ) -> float | None:
        windows = self.canary_lookbacks if canary else self.momentum_lookbacks
        weights = self.canary_weights if canary else self.momentum_weights
        terms = []
        missing = False
        for window, weight in zip(windows, self._positive_weights(weights), strict=True):
            if weight <= 0:
                continue
            value = self._return(reader, name, window, skipped)
            if value is None:
                missing = True
            else:
                terms.append(weight * math.log1p(value))
        return None if missing else math.fsum(terms)

    def _volatility(
        self, reader: SignalReader, name: str, skipped: dict[str, SignalStatus]
    ) -> float | None:
        estimates = []
        for window in self.volatility_windows:
            value = reader.value(self.volatility_signal(window), name)
            if value is None:
                return None
            if not math.isfinite(value) or value < 0:
                skipped.setdefault(name, SignalStatus.INVALID_INPUT)
                return None
            estimates.append(value)
        return max(self.volatility_floor, *estimates)

    def _rank(
        self, scores: Mapping[str, float], held: Mapping[str, float], *, count: int, offensive: bool
    ) -> tuple[str, ...]:
        adjusted = {
            name: score
            + (self.core_preference if offensive and name == self.core_id else 0.0)
            + (self.switch_buffer if held.get(name, 0.0) > 0 else 0.0)
            for name, score in scores.items()
        }
        return tuple(sorted(scores, key=lambda name: (-adjusted[name], name))[:count])

    def plan(self, ctx: StrategyContext) -> RiskAwarePlan:
        """Build a cash-funded complete allocation from one evening snapshot."""
        reader = SignalReader(ctx)
        skipped: dict[str, SignalStatus] = {}
        scores: dict[str, float] = {}
        vols: dict[str, float] = {}
        usable: list[str] = []
        names = self.risky_ids if self.mode in {"rotate", "balanced"} else (self.core_id,)
        votes = 1.0
        recovery = False
        for name in names:
            if name not in ctx.universe:
                continue
            if self.mode == "rotate":
                score = self._score(reader, name, skipped)
                available = score is not None
                if score is not None:
                    scores[name] = score
            elif self.mode == "ensemble":
                terms = []
                available = (
                    self.trend_kind != "moving_average"
                    or self._return(reader, name, 1, skipped) is not None
                )
                for window, weight in zip(
                    self.momentum_lookbacks,
                    self._positive_weights(self.momentum_weights),
                    strict=True,
                ):
                    if weight <= 0:
                        continue
                    signal = (
                        self.trend_signal(window)
                        if self.trend_kind == "moving_average"
                        else self.momentum_signal(window)
                    )
                    value = reader.value(signal, name)
                    if value is None:
                        available = False
                    elif not math.isfinite(value) or value <= -1:
                        skipped.setdefault(name, SignalStatus.INVALID_INPUT)
                        available = False
                    else:
                        terms.append(weight * float(value > 0))
                votes = math.fsum(terms) if available else 0.0
                if self.recovery_lookback > 0:
                    short = self._return(reader, name, self.recovery_lookback, skipped)
                    recovery = bool(
                        available and short is not None and short > self.recovery_threshold
                    )
                    if recovery:
                        votes = 1.0
            else:
                available = self._return(reader, name, 1, skipped) is not None
            if available and self.needs_volatility():
                estimate = self._volatility(reader, name, skipped)
                available = estimate is not None
                if estimate is not None:
                    vols[name] = estimate
            if available:
                usable.append(name)
        positive_canaries = 0
        for name in self.canary_ids:
            score = self._score(reader, name, skipped, canary=True)
            positive_canaries += int(score is not None and score > 0)
        breadth = positive_canaries / len(self.canary_ids) if self.canary_ids else 1.0
        gate = breadth >= self.canary_min_breadth
        floor = (
            self.core_floor
            if self.core_id in usable and self.mode in {"rotate", "ensemble"}
            else 0.0
        )
        offensive: dict[str, float] = {self.core_id: floor} if floor > 0 else {}
        if self.mode == "rotate":
            eligible = {
                name: scores[name]
                for name in usable
                if not self.absolute_filter or scores[name] > 0
            }
            selected = self._rank(eligible, ctx.portfolio.weights, count=self.top_k, offensive=True)
            if floor > 0 and self.core_id not in selected:
                selected = selected[:2]
            budget = (1.0 - floor) * float(gate)
        elif self.mode == "balanced":
            fixed = (
                dict(zip(self.risky_ids, self.fixed_weights, strict=True))
                if self.allocation_mode == "fixed"
                else {}
            )
            selected = tuple(
                name for name in usable if self.allocation_mode != "fixed" or fixed[name] > 0
            )
            budget = float(gate)
        else:
            selected = (self.core_id,) if self.core_id in usable else ()
            budget = (1.0 - floor) * votes * float(gate)
        if selected and budget > 0:
            raw = {
                name: 1.0 / vols[name]
                if self.allocation_mode == "inverse_vol"
                else fixed[name]
                if self.allocation_mode == "fixed"
                else 1.0
                for name in selected
            }
            total = math.fsum(raw.values())
            for name, value in raw.items():
                offensive[name] = offensive.get(name, 0.0) + budget * value / total
        estimate = (
            math.fsum(weight * vols[name] for name, weight in offensive.items())
            if self.needs_volatility()
            else None
        )
        scale = (
            min(1.0, self.target_volatility / estimate)
            if self.target_volatility > 0 and estimate is not None and estimate > 0
            else 1.0
        )
        offensive = {name: value * scale for name, value in offensive.items() if value > 0}
        weights = dict(offensive)
        residual = max(0.0, 1.0 - math.fsum(weights.values()))
        if residual > 1e-12:
            defensive = {}
            for name in self.defensive_ids:
                score = self._score(reader, name, skipped)
                if score is not None:
                    scores.setdefault(name, score)
                    if score > 0 and name in ctx.universe:
                        defensive[name] = score
            chosen = self._rank(
                defensive, ctx.portfolio.weights, count=self.defensive_top_k, offensive=False
            )
            if chosen:
                for name in chosen:
                    weights[name] = weights.get(name, 0.0) + residual / len(chosen)
            else:
                carry = self._return(reader, self.monetary_id, self.monetary_lookback, skipped)
                if carry is not None and carry > 0 and self.monetary_id in ctx.universe:
                    weights[self.monetary_id] = residual
        for name, status in reader.unusable.items():
            skipped.setdefault(name, status)
        return RiskAwarePlan(
            mode=self.mode,
            scores=MappingProxyType(scores),
            trend_fraction=votes,
            canary_breadth=breadth,
            selected=selected,
            offensive_weights=MappingProxyType(offensive),
            offensive_volatility=estimate,
            risk_scale=scale,
            recovery=recovery,
            weights=MappingProxyType(weights),
            skipped=MappingProxyType(skipped),
            readable=reader.readable,
        )

    def decide(self, ctx: StrategyContext) -> TargetAllocation:
        """Apply the common band once to the complete long-only target."""
        plan = self.plan(ctx)
        return settle(
            ctx,
            plan.weights,
            band=self.rebalance_band,
            unusable=plan.skipped,
            readable=plan.readable,
        )
