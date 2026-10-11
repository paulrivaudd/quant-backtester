"""Hold less of a fund when the volatility a GARCH(1,1) forecasts for it rises."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from quant_backtester.analytics.config import RETURN_STD_TOLERANCE
from quant_backtester.backtest.context import StrategyContext
from quant_backtester.numbers import require_finite_positive, require_unit_fraction
from quant_backtester.signals.base import Signal
from quant_backtester.signals.engine import SignalRequest
from quant_backtester.signals.models.garch import (
    EwmaVolatilitySignal,
    GarchForecastConfig,
    GarchVolatilitySignal,
    require_arch,
)
from quant_backtester.signals.types import PriceBasis, require_identifier
from quant_backtester.strategies.adaptive.inputs import (
    ANNUALIZATION,
    PRICE_MAX_AGE_SESSIONS,
    SignalReader,
)
from quant_backtester.strategies.adaptive.rebalance import Evaluation, RuleStrategy
from quant_backtester.strategies.adaptive.rules import forecast_volatility_rule


@dataclass(frozen=True, slots=True)
class GarchVolControl(RuleStrategy):
    """An exposure scaled to a GARCH(1,1) forecast of the fund's risk, never above 100%.

    Attributes
    ----------
    instrument_id : str
        The fund held; the rest is cash.
    estimation_returns : int
        Daily log returns the model is fitted on at every decision, over
        consecutive sessions: 756 returns are 757 adjusted closes.
    target_volatility : float
        The estimated annualised risk aimed at, as a fraction.
    volatility_floor : float
        Smallest volatility the forecast may take in the allocation.
    rebalance_band : float
        Largest gap between the fund's held weight and its target that sends
        no order. It makes the risk target approximate.
    initial_omega_share, initial_alpha, initial_beta, initial_nu : float
        The single starting point of the optimiser.
    max_iterations : int
        Iterations the optimiser may take.
    ftol : float
        Its tolerance on the objective.
    ewma_decay : float
        Decay of the EWMA a refused fit falls back on.
    ewma_seed_returns : int
        Returns whose mean square starts that EWMA.
    strategy_id : str
        Name this configuration is recorded under.

    Raises
    ------
    ValueError
        If a name is empty, a number is not finite and positive, or the
        forecast cannot be configured.

    Notes
    -----
    ``w = min(1, target / max(sigma, floor))`` with ``sigma = sqrt(252 *
    h_{t+1|t})``, the one-step forecast of a zero-mean GARCH(1,1) with Student
    innovations, estimated again at each decision on the returns known then
    (:mod:`quant_backtester.signals.models.garch`). The forecast covers close
    to close and the order is filled at the next open: it is a proxy of the
    position's risk. The rule forecasts no direction; cash earns nothing.

    A fit that is refused on valid data is replaced by an EWMA of the same
    returns, and the rule is applied to it: what is run is GARCH with a
    declared fallback. A window that is short, holed, stale or invalid is a
    target of cash, whatever the band says.

    The estimation needs the ``arch`` package (the ``stats`` extra). The class
    imports without it; :meth:`validate`, which every run calls first, does not
    pass without it.
    """

    instrument_id: str = "ETF_WORLD"
    estimation_returns: int = 756
    target_volatility: float = 0.12
    volatility_floor: float = 0.05
    rebalance_band: float = 0.03
    initial_omega_share: float = 0.05
    initial_alpha: float = 0.05
    initial_beta: float = 0.90
    initial_nu: float = 8.0
    max_iterations: int = 1000
    ftol: float = 1e-8
    ewma_decay: float = 0.94
    ewma_seed_returns: int = 60
    strategy_id: str = "SA11_garch_vol_control"

    def __post_init__(self) -> None:
        """Reject a configuration that cannot be computed."""
        require_identifier(self.instrument_id, "instrument_id")
        require_identifier(self.strategy_id, "strategy_id")
        require_finite_positive(self.target_volatility, "target_volatility")
        require_finite_positive(self.volatility_floor, "volatility_floor")
        require_unit_fraction(self.rebalance_band, "rebalance_band")
        self.forecast_config()

    def forecast_config(self) -> GarchForecastConfig:
        """Return the conventions of the fit, annualised as every rule of the family."""
        return GarchForecastConfig(
            estimation_returns=self.estimation_returns,
            annualization=ANNUALIZATION,
            initial_omega_share=self.initial_omega_share,
            initial_alpha=self.initial_alpha,
            initial_beta=self.initial_beta,
            initial_nu=self.initial_nu,
            max_iterations=self.max_iterations,
            ftol=self.ftol,
            ewma_decay=self.ewma_decay,
            ewma_seed_returns=self.ewma_seed_returns,
            constant_return_tolerance=RETURN_STD_TOLERANCE,
        )

    def forecast_signal(self) -> GarchVolatilitySignal:
        """Return the forecast volatility, on adjusted closes of the decided session."""
        return GarchVolatilitySignal(
            signal_id=f"garch11_t_vol_{self.estimation_returns}r",
            config=self.forecast_config(),
            price_basis=PriceBasis.ADJUSTED,
            max_age_sessions=PRICE_MAX_AGE_SESSIONS,
        )

    def required_signals(self) -> Sequence[Signal | SignalRequest]:
        """Return the forecast, on the fund only."""
        return (SignalRequest(signal=self.forecast_signal(), instruments=(self.instrument_id,)),)

    def validate(self) -> None:
        """Raise unless this strategy can be run, its estimator included.

        Raises
        ------
        MissingDependency
            If the ``arch`` package is not installed: a launch stops here
            rather than at the first decision with a full window.
        ValueError
            As for every strategy.
        """
        RuleStrategy.validate(self)
        require_arch()

    def evaluate(self, ctx: StrategyContext) -> Evaluation:
        """Return the exposure the forecast stands for."""
        reader = SignalReader(ctx)
        target = forecast_volatility_rule(
            self.instrument_id,
            reader.value(self.forecast_signal(), self.instrument_id),
            target_volatility=self.target_volatility,
            floor=self.volatility_floor,
        )
        return Evaluation(target, reader.unusable, reader.readable)


@dataclass(frozen=True, slots=True)
class EwmaVolControl(RuleStrategy):
    """The control of :class:`GarchVolControl`: the same rule on an EWMA forecast.

    Attributes
    ----------
    instrument_id : str
        The fund held.
    window_returns : int
        Daily log returns read, over consecutive sessions.
    decay : float
        Weight the EWMA keeps of its previous variance.
    seed_returns : int
        Returns whose mean square starts the recursion.
    target_volatility, volatility_floor, rebalance_band : float
        As for :class:`GarchVolControl`.
    strategy_id : str
        A research identifier: this control has no catalogue code.

    Raises
    ------
    ValueError
        If a name is empty, a number is not finite and positive, or the EWMA
        cannot be configured.

    Notes
    -----
    Same window, same returns, same allocation rule and same band as SA11;
    only the forecast differs, and nothing in it is estimated. Its signal
    carries its own id, so the two never share one.
    """

    instrument_id: str = "ETF_WORLD"
    window_returns: int = 756
    decay: float = 0.94
    seed_returns: int = 60
    target_volatility: float = 0.12
    volatility_floor: float = 0.05
    rebalance_band: float = 0.03
    strategy_id: str = "research_ewma94_vol_control"

    def __post_init__(self) -> None:
        """Reject a configuration that cannot be computed."""
        require_identifier(self.instrument_id, "instrument_id")
        require_identifier(self.strategy_id, "strategy_id")
        require_finite_positive(self.target_volatility, "target_volatility")
        require_finite_positive(self.volatility_floor, "volatility_floor")
        require_unit_fraction(self.rebalance_band, "rebalance_band")
        self.forecast_signal()

    def forecast_signal(self) -> EwmaVolatilitySignal:
        """Return the EWMA volatility, on adjusted closes of the decided session."""
        return EwmaVolatilitySignal(
            signal_id=f"ewma{round(self.decay * 100)}_vol_{self.window_returns}r",
            window_returns=self.window_returns,
            decay=self.decay,
            seed_returns=self.seed_returns,
            annualization=ANNUALIZATION,
            price_basis=PriceBasis.ADJUSTED,
            max_age_sessions=PRICE_MAX_AGE_SESSIONS,
        )

    def required_signals(self) -> Sequence[Signal | SignalRequest]:
        """Return the EWMA volatility, on the fund only."""
        return (SignalRequest(signal=self.forecast_signal(), instruments=(self.instrument_id,)),)

    def evaluate(self, ctx: StrategyContext) -> Evaluation:
        """Return the exposure the EWMA volatility stands for."""
        reader = SignalReader(ctx)
        target = forecast_volatility_rule(
            self.instrument_id,
            reader.value(self.forecast_signal(), self.instrument_id),
            target_volatility=self.target_volatility,
            floor=self.volatility_floor,
        )
        return Evaluation(target, reader.unusable, reader.readable)
