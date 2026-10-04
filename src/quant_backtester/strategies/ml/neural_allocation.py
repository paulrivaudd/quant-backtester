"""ML1: hold what a frozen network proposes, between the tradable funds and cash."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from quant_backtester.backtest.context import Selection, StrategyContext
from quant_backtester.ml.artifacts import NeuralArtifact
from quant_backtester.ml.config import NeuralStrategyConfig
from quant_backtester.portfolio.targets import WEIGHT_SUM_TOLERANCE, TargetAllocation
from quant_backtester.signals.base import Signal
from quant_backtester.signals.engine import SignalRequest
from quant_backtester.signals.ml.neural_allocation import NeuralAllocationSignal
from quant_backtester.signals.types import SignalStatus, require_identifier
from quant_backtester.strategies.base import Strategy

STRATEGY_ID = "ML1_neural_allocation"
"""The catalogue code of the strategy and its label, as one identifier."""

SIGNAL_ID = "neural_allocation_weights"


class InformationCutoffError(ValueError):
    """Raised when a model is asked to decide at an instant it was calibrated on."""


class Action(Enum):
    """The three answers a decision can give."""

    WEIGHTS = "WEIGHTS"
    """Rebalance to the target weights; the rest stays in cash."""

    CASH = "CASH"
    """Ask for every position to be sold."""

    HOLD = "HOLD"
    """Keep the quantities held; no rebalancing order."""


@dataclass(frozen=True, slots=True)
class NeuralDecision:
    """What the rule made of one proposal, and why.

    Attributes
    ----------
    action : Action
        The answer.
    target : Mapping[str, float]
        The weights after the cap and the minimum, by fund. Empty for cash.
    reason : str
        ``MISSING_DATA``, ``NO_FUND_ABOVE_MINIMUM``, ``INSIDE_BAND``,
        ``OUTSIDE_BAND``, ``FULL_EXIT`` or ``CAP_BREACHED``: a day in cash
        for want of data is not a day in cash by choice.
    gap : float | None
        Largest distance between a held weight and its target, cash included.
    """

    action: Action
    target: Mapping[str, float]
    reason: str
    gap: float | None = None


def capped_targets(
    proposed: Mapping[str, float], *, max_asset_weight: float, min_asset_weight: float
) -> dict[str, float]:
    """Return proposed weights after the cap and the minimum; the rest is cash.

    Parameters
    ----------
    proposed : Mapping[str, float]
        The network's weight per fund, each in ``[0, 1]``, of sum at most one.
    max_asset_weight : float
        Largest weight of one fund.
    min_asset_weight : float
        A weight strictly below this is removed.

    Returns
    -------
    dict[str, float]
        The funds kept. Whatever the cap or the minimum removes goes to cash
        and is not given to the other funds.

    Raises
    ------
    ValueError
        If a weight is not a finite fraction of ``[0, 1]`` or the weights add
        up to more than one, beyond the project's tolerance. Nothing is
        renormalised: a proposal that is not an allocation is a broken model.
    """
    for name, weight in proposed.items():
        if not math.isfinite(weight) or not 0.0 <= weight <= 1.0:
            raise ValueError(f"the proposed weight of {name} is {weight}, outside [0, 1]")
    total = math.fsum(proposed.values())
    if total > 1.0 + WEIGHT_SUM_TOLERANCE:
        raise ValueError(f"the proposed weights add up to {total}, more than the book")
    capped = {name: min(weight, max_asset_weight) for name, weight in proposed.items()}
    return {name: weight for name, weight in capped.items() if weight >= min_asset_weight}


def neural_decision(
    proposed: Mapping[str, float] | None,
    held: Mapping[str, float],
    *,
    max_asset_weight: float,
    min_asset_weight: float,
    rebalance_band: float,
) -> NeuralDecision:
    """Return the decision a proposal stands for, given the book actually held.

    Parameters
    ----------
    proposed : Mapping[str, float] | None
        The network's weight per tradable fund, or ``None`` when a required
        input was unusable.
    held : Mapping[str, float]
        Weight of each position held, as valued at the decision. Cash is the
        complement.
    max_asset_weight, min_asset_weight : float
        The cap and the minimum of :func:`capped_targets`.
    rebalance_band : float
        The book is kept when no weight, cash included, is this far from its
        target.

    Returns
    -------
    NeuralDecision
        Cash when the data is missing or no fund is left after the minimum;
        the book kept when every weight is inside the band; the targets
        otherwise. The band never holds back the complete sale of a held fund
        or a position above its cap.

    Notes
    -----
    The band compares the target with the book as it is, never with the
    proposal of the day before: the network may propose the same weights every
    evening while the weights held drift.
    """
    if proposed is None:
        return NeuralDecision(Action.CASH, {}, "MISSING_DATA")
    target = capped_targets(
        proposed, max_asset_weight=max_asset_weight, min_asset_weight=min_asset_weight
    )
    if not target:
        return NeuralDecision(Action.CASH, {}, "NO_FUND_ABOVE_MINIMUM")
    gaps = [abs(target.get(name, 0.0) - held.get(name, 0.0)) for name in {*target, *held}]
    cash_gap = abs(math.fsum(held.values()) - math.fsum(target.values()))
    gap = max([*gaps, cash_gap])
    if any(name not in target for name in held):
        return NeuralDecision(Action.WEIGHTS, target, "FULL_EXIT", gap)
    if any(weight > max_asset_weight + WEIGHT_SUM_TOLERANCE for weight in held.values()):
        return NeuralDecision(Action.WEIGHTS, target, "CAP_BREACHED", gap)
    if gap < rebalance_band:
        return NeuralDecision(Action.HOLD, target, "INSIDE_BAND", gap)
    return NeuralDecision(Action.WEIGHTS, target, "OUTSIDE_BAND", gap)


@dataclass(frozen=True, slots=True)
class NeuralAllocationStrategy(Strategy):
    """Each session, hold the weights a frozen network proposes, inside a band.

    Attributes
    ----------
    config : NeuralStrategyConfig
        The periods the model was calibrated on, the series it reads, the
        funds it buys and the thresholds of the decision.
    model_id : str
        The content identity of the model.
    information_cutoff : datetime
        The last instant whose information reached the model. A decision at
        or before it is refused.
    _signal : NeuralAllocationSignal
        The signal holding the loaded network. Recorded through its
        definition, which carries ``model_id``.
    strategy_id : str
        Name this configuration is recorded under.

    Notes
    -----
    Long only, no borrowing, cash unpaid. The network is trained before the
    run and never during it. A required input that is missing, stale or not
    positive gives a target of cash with the status recorded; an incompatible
    or broken model stops the run instead.

    Build one with :meth:`from_artifact`.
    """

    config: NeuralStrategyConfig
    model_id: str
    information_cutoff: datetime
    _signal: NeuralAllocationSignal = field(repr=False, compare=False)
    strategy_id: str = STRATEGY_ID

    def __post_init__(self) -> None:
        """Refuse a name that is empty or a signal that is another model's."""
        require_identifier(self.strategy_id, "strategy_id")
        if self._signal.model_id != self.model_id or self._signal.config != self.config:
            raise ValueError("the signal handed to the strategy is not the one of its model")

    @classmethod
    def from_artifact(
        cls, artifact: NeuralArtifact, *, strategy_id: str = STRATEGY_ID
    ) -> NeuralAllocationStrategy:
        """Return the strategy of a calibrated model, its network loaded once.

        Parameters
        ----------
        artifact : NeuralArtifact
            The model, as calibrated or as loaded from its folder.
        strategy_id : str
            Name the run is recorded under.

        Returns
        -------
        NeuralAllocationStrategy
            Ready to run on any period after the artifact's information cutoff.
        """
        signal = NeuralAllocationSignal(
            signal_id=SIGNAL_ID,
            config=artifact.config,
            model_id=artifact.model_id,
            information_cutoff=artifact.information_cutoff,
            _runtime=artifact.runtime(),
        )
        return cls(
            config=artifact.config,
            model_id=artifact.model_id,
            information_cutoff=artifact.information_cutoff,
            _signal=signal,
            strategy_id=strategy_id,
        )

    def signal(self) -> Signal:
        """Return the signal proposing one weight per tradable fund."""
        return self._signal

    def required_signals(self) -> Sequence[Signal | SignalRequest]:
        """Return the network's proposal, asked for the tradable funds only."""
        return (SignalRequest(signal=self._signal, instruments=self.config.tradable_ids),)

    def parameters(self) -> Mapping[str, object]:
        """Return the configuration, the model's identity and its cutoff, as built-ins."""
        return {
            "config": self.config.definition(),
            "model_id": self.model_id,
            "information_cutoff": self.information_cutoff.isoformat(),
        }

    def proposal(self, ctx: StrategyContext) -> dict[str, float] | None:
        """Return the network's weight per fund, or ``None`` when an input was unusable."""
        frame = ctx.signal(self._signal.signal_id)
        if any(status is not SignalStatus.OK for status in frame["status"]):
            return None
        return {name: float(frame.loc[name, "value"]) for name in self.config.tradable_ids}

    def decide(self, ctx: StrategyContext) -> TargetAllocation:
        """Return the target for the next open: the proposal, the thresholds, then the band.

        Raises
        ------
        InformationCutoffError
            If the decision is not after the model's information cutoff.
        ValueError
            If the proposal is not an allocation.
        """
        if ctx.as_of <= self.information_cutoff:
            raise InformationCutoffError(
                f"{self.strategy_id} was calibrated on information up to "
                f"{self.information_cutoff.isoformat()} and is asked to decide at "
                f"{ctx.as_of.isoformat()}; a run starts after the cutoff"
            )
        proposed = self.proposal(ctx)
        decision = neural_decision(
            proposed,
            dict(ctx.portfolio.weights),
            max_asset_weight=self.config.max_asset_weight,
            min_asset_weight=self.config.min_asset_weight,
            rebalance_band=self.config.rebalance_band,
        )
        among = self._among(ctx)
        if decision.action is Action.CASH:
            return ctx.cash(among=among)
        if decision.action is Action.HOLD:
            return ctx.hold_positions(among=among)
        return ctx.weights(dict(decision.target), among=among)

    def _among(self, ctx: StrategyContext) -> Selection:
        """Return what the decision was taken among: the funds that had a proposal.

        Every fund when the input was usable, none - with the status that
        explains it - when it was not: cash chosen on a proposal and cash for
        want of one are recorded as two different days.
        """
        frame = ctx.signal(self._signal.signal_id)
        return ctx.considering(
            {str(name): status for name, status in zip(frame.index, frame["status"], strict=True)}
        )


def require_after_cutoff(strategy: NeuralAllocationStrategy, first_decision: datetime) -> None:
    """Raise unless a run's first decision is after the model's information cutoff.

    Parameters
    ----------
    strategy : NeuralAllocationStrategy
        The strategy about to be run.
    first_decision : datetime
        The decision instant of the first session of the run, timezone-aware.

    Raises
    ------
    InformationCutoffError
        If it is not. Checked before the run, so that a test period that
        overlaps the calibration is refused before any number is produced.
    """
    if first_decision <= strategy.information_cutoff:
        raise InformationCutoffError(
            f"the run's first decision, {first_decision.isoformat()}, is not after the "
            f"model's information cutoff, {strategy.information_cutoff.isoformat()}"
        )
