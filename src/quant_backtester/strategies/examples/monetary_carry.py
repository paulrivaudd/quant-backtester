"""Place the cash in a money-market fund when its carry pays for the round trip."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.numbers import (
    require_finite_non_negative,
    require_finite_positive,
    require_unit_fraction,
)
from quant_backtester.signals.base import Signal
from quant_backtester.signals.engine import SignalRequest
from quant_backtester.signals.types import require_identifier
from quant_backtester.strategies.adaptive.inputs import (
    ANNUALIZATION,
    SignalReader,
    momentum,
    volatility,
)
from quant_backtester.strategies.adaptive.rebalance import Evaluation, RuleStrategy
from quant_backtester.strategies.adaptive.rules import monetary_carry_rule


@dataclass(frozen=True, slots=True)
class MonetaryCarry(RuleStrategy):
    """All of a money-market fund while it is eligible, cash otherwise.

    Attributes
    ----------
    instrument_id : str
        The accumulating EUR money-market fund. There is no default: it has to
        be a registered fund with a real quoted history, never a yield series
        standing in for one.
    carry_sessions : int
        Sessions the past return is measured over.
    volatility_returns : int
        Daily returns the fund's volatility is taken over.
    horizon_years : float
        How long the carry is given to cover the round-trip cost, in years.
    round_trip_cost : float
        Estimated cost of buying then selling, as a fraction: ``0.002`` is
        0.20%. To be set to the account's fees and the size of its orders.
    maximum_volatility : float
        Largest annualised volatility accepted of a money-market fund.
    rebalance_band : float
        Largest gap between the fund's weight and its target that sends no
        order.
    strategy_id : str
        Name this configuration is recorded under.

    Raises
    ------
    ValueError
        If a name is empty, a window cannot make its signal, or a number is
        not finite or not in its range.

    Notes
    -----
    ``c = (252 / L) * ln(P_t / P_{t-L})`` is a backward-looking annual return,
    not a known future rate; it lags a cut in rates. The fund is eligible when
    ``exp(c * horizon_years) - 1 > round_trip_cost`` and its volatility is at
    most ``maximum_volatility``. Management fees are inside the fund's price
    already and are not taken off again.

    The point is to pay the idle capital, not to promise an alpha: the fund is
    no guaranteed deposit, and this is neither an FX carry nor a roll-down.
    Either signal missing is a target of cash.
    """

    instrument_id: str
    carry_sessions: int = 63
    volatility_returns: int = 60
    horizon_years: float = 0.25
    round_trip_cost: float = 0.002
    maximum_volatility: float = 0.02
    rebalance_band: float = 0.03
    strategy_id: str = "SA8_monetary_carry"

    def __post_init__(self) -> None:
        """Reject a configuration that cannot be computed."""
        require_identifier(self.instrument_id, "instrument_id")
        require_identifier(self.strategy_id, "strategy_id")
        require_finite_positive(self.horizon_years, "horizon_years")
        require_finite_non_negative(self.round_trip_cost, "round_trip_cost")
        require_finite_positive(self.maximum_volatility, "maximum_volatility")
        require_unit_fraction(self.rebalance_band, "rebalance_band")
        self.carry_signal()
        self.volatility_signal()

    def carry_signal(self) -> Signal:
        """Return the fund's return over ``carry_sessions``, nothing skipped."""
        return momentum(self.carry_sessions, 0)

    def volatility_signal(self) -> Signal:
        """Return the fund's realised volatility."""
        return volatility(self.volatility_returns)

    def required_signals(self) -> Sequence[Signal | SignalRequest]:
        """Return the past return and the volatility, both on the fund only."""
        fund = (self.instrument_id,)
        return (
            SignalRequest(signal=self.carry_signal(), instruments=fund),
            SignalRequest(signal=self.volatility_signal(), instruments=fund),
        )

    def evaluate(self, ctx: StrategyContext) -> Evaluation:
        """Return 100% of the fund when it is eligible, cash otherwise."""
        reader = SignalReader(ctx)
        target = monetary_carry_rule(
            self.instrument_id,
            reader.value(self.carry_signal(), self.instrument_id),
            reader.value(self.volatility_signal(), self.instrument_id),
            lookback_sessions=self.carry_sessions,
            annualization=ANNUALIZATION,
            horizon_years=self.horizon_years,
            round_trip_cost=self.round_trip_cost,
            maximum_volatility=self.maximum_volatility,
        )
        return Evaluation(target, reader.unusable)
