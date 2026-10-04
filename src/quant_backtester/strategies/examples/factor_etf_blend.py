"""Spread the capital over three style funds, half equally and half by inverse volatility."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.numbers import require_finite_positive, require_unit_fraction
from quant_backtester.signals.base import Signal
from quant_backtester.signals.engine import SignalRequest
from quant_backtester.signals.types import require_identifier
from quant_backtester.strategies.adaptive.inputs import SignalReader, volatility
from quant_backtester.strategies.adaptive.rebalance import Evaluation, RuleStrategy
from quant_backtester.strategies.adaptive.rules import factor_blend_rule

FACTOR_COUNT = 3
"""Value, quality and minimum volatility: the blend is of exactly three funds."""


@dataclass(frozen=True, slots=True)
class FactorETFBlend(RuleStrategy):
    """Three style funds, each capped, the cut left in cash.

    Attributes
    ----------
    instrument_ids : tuple[str, ...]
        Exactly three registered funds: value, quality and minimum volatility.
        There is no default: which funds stand for the styles is a decision
        taken before any test result is seen.
    volatility_returns : int
        Daily returns each fund's volatility is taken over.
    volatility_floor : float
        Smallest volatility a fund is given.
    maximum_weight : float
        Cap on each fund.
    equal_share : float
        Share of the capital split equally; the rest goes by inverse
        volatility.
    rebalance_band : float
        Largest gap between a weight and its target that sends no order.
    strategy_id : str
        Name this configuration is recorded under.

    Raises
    ------
    ValueError
        If there are not exactly three distinct funds, a name is empty, the
        window cannot make a volatility or a number is out of its range.

    Notes
    -----
    ``a_i = 1 / max(vol_i, floor)``, ``q_i = a_i / sum(a)`` and
    ``w_i = min(maximum_weight, equal_share / 3 + (1 - equal_share) * q_i)``.
    A weight cut by the cap is not shared out again: it stays in cash. The
    three funds and their ``volatility_returns + 1`` closes must all be there;
    otherwise the rule holds nothing.

    The funds pick the shares; the backtest only sees their prices. A factor
    premium is not an alpha, and the three stay share funds.
    """

    instrument_ids: tuple[str, ...]
    volatility_returns: int = 60
    volatility_floor: float = 0.10
    maximum_weight: float = 0.40
    equal_share: float = 0.50
    rebalance_band: float = 0.03
    strategy_id: str = "SA7_factor_blend"

    def __post_init__(self) -> None:
        """Reject a configuration that cannot be computed or held."""
        object.__setattr__(self, "instrument_ids", tuple(self.instrument_ids))
        require_identifier(self.strategy_id, "strategy_id")
        for name in self.instrument_ids:
            require_identifier(name, "an instrument of instrument_ids")
        repeated = sorted(name for name, seen in Counter(self.instrument_ids).items() if seen > 1)
        if len(self.instrument_ids) != FACTOR_COUNT or repeated:
            raise ValueError(
                f"instrument_ids must hold exactly {FACTOR_COUNT} distinct funds, got "
                f"{self.instrument_ids!r}"
            )
        require_finite_positive(self.volatility_floor, "volatility_floor")
        for name in ("maximum_weight", "equal_share", "rebalance_band"):
            require_unit_fraction(getattr(self, name), name)
        self.signal()

    def signal(self) -> Signal:
        """Return the realised volatility each fund is weighted by."""
        return volatility(self.volatility_returns)

    def required_signals(self) -> Sequence[Signal | SignalRequest]:
        """Return the volatility, over the three funds."""
        return (SignalRequest(signal=self.signal(), instruments=self.instrument_ids),)

    def caps(self) -> Mapping[str, float]:
        """Return the cap on each fund: the band does not hold a larger position."""
        return dict.fromkeys(self.instrument_ids, self.maximum_weight)

    def evaluate(self, ctx: StrategyContext) -> Evaluation:
        """Return the three capped weights, or nothing when a fund cannot be read."""
        reader = SignalReader(ctx)
        signal = self.signal()
        target = factor_blend_rule(
            {name: reader.value(signal, name) for name in self.instrument_ids},
            floor=self.volatility_floor,
            maximum_weight=self.maximum_weight,
            equal_share=self.equal_share,
        )
        return Evaluation(target, reader.unusable, reader.readable)
