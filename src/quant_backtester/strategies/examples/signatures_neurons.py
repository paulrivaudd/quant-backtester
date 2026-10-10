"""Hold a fund while a model on its log-signature forecasts a positive return, sized as SA6."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.ml.signatures.artifacts import SignatureModelSchedule
from quant_backtester.ml.signatures.config import SignatureVariant
from quant_backtester.numbers import require_finite, require_finite_positive, require_unit_fraction
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.signals.base import Signal
from quant_backtester.signals.engine import SignalRequest
from quant_backtester.signals.ml.signature_return import SignatureReturnSignal
from quant_backtester.signals.signatures.logsignature import FeatureKind, require_esig
from quant_backtester.signals.types import SignalStatus, require_identifier
from quant_backtester.strategies.adaptive.inputs import SignalReader, volatility
from quant_backtester.strategies.adaptive.rebalance import settle
from quant_backtester.strategies.adaptive.rules import (
    RuleTarget,
    conservative_volatility,
    gated_volatility_rule,
)
from quant_backtester.strategies.base import Strategy

STRATEGY_ID = "SA13_signatures_neurons"
"""The identifier of the strategy in the catalogue."""


@dataclass(frozen=True, slots=True)
class SignaturesNeurons(Strategy):
    """A fund held while its forecast return is positive, at the weight SA6 would size.

    Attributes
    ----------
    instrument_id : str
        The fund held; the rest is cash.
    variant_id : str
        The variant of model the forecasts come from.
    schedule_id : str
        The identity of the monthly schedule of frozen models.
    direction_filter : bool
        ``False`` for the control that sizes the same risk, with the same
        availability of models and features, and never stands aside on the mean.
    entry_threshold : float
        Forecast simple return a book in cash enters strictly above: 20 basis
        points.
    exit_threshold : float
        A held position is kept strictly above it and sold at it.
    short_returns, long_returns : int
        Daily returns of the two realised volatilities of the sizing.
    target_volatility, volatility_floor, rebalance_band : float
        The sizing of ``SA6`` and the band of the family.
    _signal : SignatureReturnSignal
        The signal holding the schedule. Recorded through its definition.
    strategy_id : str
        Name this configuration is recorded under.

    Raises
    ------
    ValueError
        If a name is empty, the thresholds are not ``0 <= exit < entry``, a
        number is out of its range, or the signal is not the one identified.

    Notes
    -----
    At the evening of ``t`` the signal forecasts the simple return from the
    open of ``t + 1`` to the open of ``t + 2``. With ``g`` the gate of
    :func:`~quant_backtester.strategies.adaptive.rules.direction_gate` read on
    the position actually held, ``w = g * min(1, target / max(vol_short,
    vol_long, floor))``: the mean decides whether to be in the market, the
    realised volatilities of the closes - a proxy, not a forecast of the
    label's variance - decide how much. A complete exit and an entry from cash
    are always sent; otherwise the band applies.

    A forecast or a volatility that is unusable, or a month without a model,
    is a target of cash, recorded with its status. A model the decision could
    not have had stops the run. The book is continuous across months: a new
    model never resets the capital, the positions or the costs.

    Build one with :meth:`from_schedule`. The class imports without the
    optional dependencies; :meth:`validate` does not pass without the
    log-signature backend when the variant reads log-signatures.
    """

    instrument_id: str
    variant_id: str
    schedule_id: str
    _signal: SignatureReturnSignal = field(repr=False, compare=False)
    direction_filter: bool = True
    entry_threshold: float = 0.002
    exit_threshold: float = 0.0
    short_returns: int = 20
    long_returns: int = 60
    target_volatility: float = 0.12
    volatility_floor: float = 0.05
    rebalance_band: float = 0.03
    strategy_id: str = STRATEGY_ID

    def __post_init__(self) -> None:
        """Reject a configuration that cannot be computed."""
        require_identifier(self.instrument_id, "instrument_id")
        require_identifier(self.strategy_id, "strategy_id")
        if not isinstance(self.direction_filter, bool):
            raise ValueError(
                f"direction_filter must be True or False, got {self.direction_filter!r}"
            )
        require_finite(self.entry_threshold, "entry_threshold")
        require_finite(self.exit_threshold, "exit_threshold")
        if not 0.0 <= self.exit_threshold < self.entry_threshold:
            raise ValueError("the thresholds must satisfy 0 <= exit_threshold < entry_threshold")
        require_finite_positive(self.target_volatility, "target_volatility")
        require_finite_positive(self.volatility_floor, "volatility_floor")
        require_unit_fraction(self.rebalance_band, "rebalance_band")
        if self.short_returns == self.long_returns:
            raise ValueError(f"both volatility windows hold {self.long_returns} returns")
        if (
            self._signal.schedule_id != self.schedule_id
            or self._signal.instrument_id != self.instrument_id
        ):
            raise ValueError("the signal handed to the strategy is not the one of its schedule")
        self.short_signal()
        self.long_signal()

    @classmethod
    def from_schedule(
        cls,
        schedule: SignatureModelSchedule,
        variant: SignatureVariant,
        *,
        direction_filter: bool = True,
        strategy_id: str = STRATEGY_ID,
    ) -> SignaturesNeurons:
        """Return the strategy of a schedule of models already calibrated.

        Parameters
        ----------
        schedule : SignatureModelSchedule
            The monthly models, built before the run.
        variant : SignatureVariant
            The variant they belong to: gives the fund and the features.
        direction_filter : bool
            ``False`` for the control without the filter on the mean.
        strategy_id : str
            Name the run is recorded under.

        Raises
        ------
        ValueError
            If the schedule belongs to another variant.
        """
        if schedule.variant_id != variant.variant_id:
            raise ValueError(
                f"the schedule belongs to {schedule.variant_id}, not to {variant.variant_id}"
            )
        signal = SignatureReturnSignal(
            signal_id=f"signature_return_{variant.variant_id}",
            instrument_id=variant.instrument_id,
            features=variant.features,
            schedule_id=schedule.schedule_id,
            _schedule=schedule,
        )
        return cls(
            instrument_id=variant.instrument_id,
            variant_id=variant.variant_id,
            schedule_id=schedule.schedule_id,
            _signal=signal,
            direction_filter=direction_filter,
            strategy_id=strategy_id,
        )

    def forecast_signal(self) -> SignatureReturnSignal:
        """Return the signal forecasting the next open-to-open return."""
        return self._signal

    def short_signal(self) -> Signal:
        """Return the realised volatility over the shorter window."""
        return volatility(self.short_returns)

    def long_signal(self) -> Signal:
        """Return the realised volatility over the longer window."""
        return volatility(self.long_returns)

    def required_signals(self) -> Sequence[Signal | SignalRequest]:
        """Return the forecast and the two volatilities, all on the fund only."""
        fund = (self.instrument_id,)
        return (
            SignalRequest(signal=self._signal, instruments=fund),
            SignalRequest(signal=self.short_signal(), instruments=fund),
            SignalRequest(signal=self.long_signal(), instruments=fund),
        )

    def validate(self) -> None:
        """Raise unless this strategy can be run.

        Raises
        ------
        MissingDependency
            If the variant reads log-signatures and their backend is not
            installed: a launch stops here and never becomes a book in cash.
        ValueError
            As for every strategy.
        """
        Strategy.validate(self)
        if self._signal.features.kind is FeatureKind.LOGSIGNATURE:
            require_esig()

    def evaluate(self, ctx: StrategyContext) -> tuple[RuleTarget, SignalReader]:
        """Return the theoretical target, before the band, and what could not be read."""
        reader = SignalReader(ctx)
        mean = reader.value(self._signal, self.instrument_id)
        estimate = conservative_volatility(
            reader.value(self.short_signal(), self.instrument_id),
            reader.value(self.long_signal(), self.instrument_id),
            floor=self.volatility_floor,
        )
        target = gated_volatility_rule(
            self.instrument_id,
            mean,
            estimate,
            held=ctx.portfolio.holds(self.instrument_id),
            entry_threshold=self.entry_threshold,
            exit_threshold=self.exit_threshold,
            target_volatility=self.target_volatility,
            floor=self.volatility_floor,
            gated=self.direction_filter,
        )
        return target, reader

    def decide(self, ctx: StrategyContext) -> TargetAllocation:
        """Return the target for the next open: the gate, the sizing, then the band."""
        target, reader = self.evaluate(ctx)
        unusable: dict[str, SignalStatus] = dict(reader.unusable)
        entering = bool(target.weights) and not ctx.portfolio.holds(self.instrument_id)
        return settle(
            ctx,
            target.weights,
            band=self.rebalance_band,
            # An entry from cash is sent even when its target is inside the band.
            force=entering,
            unusable=unusable,
            readable=reader.readable,
        )
