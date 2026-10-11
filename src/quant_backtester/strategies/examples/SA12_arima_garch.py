"""Hold a fund while an ARIMA forecasts a positive return, sized by a GARCH variance."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from quant_backtester.analytics.config import RETURN_STD_TOLERANCE
from quant_backtester.backtest.context import StrategyContext
from quant_backtester.numbers import (
    require_finite,
    require_finite_positive,
    require_unit_fraction,
)
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.signals.base import Signal
from quant_backtester.signals.engine import SignalRequest
from quant_backtester.signals.models.arima_garch import (
    ArimaConfig,
    ArimaGarchConfig,
    ArimaGarchForecastSignal,
    VolatilityModel,
    read_joint_forecast,
    require_statsmodels,
)
from quant_backtester.signals.models.garch import GarchForecastConfig, require_arch
from quant_backtester.signals.types import SignalStatus, require_identifier
from quant_backtester.strategies.adaptive.inputs import ANNUALIZATION, PRICE_MAX_AGE_SESSIONS
from quant_backtester.strategies.adaptive.rebalance import settle
from quant_backtester.strategies.adaptive.rules import RuleTarget, gated_volatility_rule
from quant_backtester.strategies.base import Strategy


@dataclass(frozen=True, slots=True)
class ArimaGarch(Strategy):
    """A fund held while its forecast return is positive, at a weight scaled to its risk.

    Attributes
    ----------
    instrument_id : str
        The fund held; the rest is cash.
    estimation_returns : int
        Open-to-open log returns both models start from: 756 are 757 opens.
    residual_burn : int
        First ARIMA innovations left out of the variance model.
    ar_order, ma_order : int
        ``1, 1`` for the strategy; ``0, 0`` for the control with a constant mean.
    direction_filter : bool
        ``False`` for the control that sizes the same risk and never stands
        aside on the mean.
    volatility_model : str
        ``"GARCH"`` (with its EWMA fallback) or ``"EWMA"`` for the control.
    entry_threshold : float
        Forecast log return a book in cash enters strictly above: 20 basis
        points, a round trip of the reference costs.
    exit_threshold : float
        A held position is kept strictly above it and sold at it.
    target_volatility, volatility_floor, rebalance_band : float
        The sizing and the band of the SA family.
    arima_max_iterations, arima_pgtol, arima_factr, root_margin
        The mean's optimiser and its admissibility margin.
    initial_omega_share, initial_alpha, initial_beta, initial_nu, garch_max_iterations, garch_ftol
        The variance's single starting point and optimiser, as for SA11.
    ewma_decay, ewma_seed_returns
        The EWMA a refused GARCH fit falls back on.
    strategy_id : str
        Name this configuration is recorded under.

    Raises
    ------
    ValueError
        If a name is empty, the thresholds are not ``0 <= exit < entry``, a
        number is out of its range or a model cannot be configured.

    Notes
    -----
    At the evening of ``t`` the forecast is of ``log(O_{t+2} / O_{t+1})``, the
    return of the first session the order - filled at ``O_{t+1}`` - can be
    held over (:mod:`quant_backtester.signals.models.arima_garch`). With ``g``
    the gate of :func:`~quant_backtester.strategies.adaptive.rules.direction_gate`
    read on the position actually held, ``w = g * min(1, target / max(sigma,
    floor))`` and ``sigma = sqrt(252 * v_2)``.

    The band of the family applies, with two priorities: a complete exit is
    always sent, and so is an entry from cash, however small. A forecast that
    is unusable - no window, a mean that could not be fitted, no variance - is
    a target of cash. A rejected purchase leaves the book in cash, so the next
    decision still needs the entry threshold. Cash earns nothing.

    The thresholds act on a forecast log return and are not costs: the engine
    alone charges those. The estimation needs ``statsmodels`` and ``arch``
    (the ``stats`` extra); the class imports without them and
    :meth:`validate` does not pass without them.
    """

    instrument_id: str = "ETF_WORLD"
    estimation_returns: int = 756
    residual_burn: int = 60
    ar_order: int = 1
    ma_order: int = 1
    direction_filter: bool = True
    volatility_model: str = "GARCH"
    entry_threshold: float = 0.002
    exit_threshold: float = 0.0
    target_volatility: float = 0.12
    volatility_floor: float = 0.05
    rebalance_band: float = 0.03
    arima_max_iterations: int = 1000
    arima_pgtol: float = 1e-8
    arima_factr: float = 1e7
    root_margin: float = 1e-6
    initial_omega_share: float = 0.05
    initial_alpha: float = 0.05
    initial_beta: float = 0.90
    initial_nu: float = 8.0
    garch_max_iterations: int = 1000
    garch_ftol: float = 1e-8
    ewma_decay: float = 0.94
    ewma_seed_returns: int = 60
    strategy_id: str = "SA12_arima_garch"

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
        self.forecast_config()

    def forecast_config(self) -> ArimaGarchConfig:
        """Return the conventions of both fits, annualised as every rule of the family."""
        arima = ArimaConfig(
            estimation_returns=self.estimation_returns,
            residual_burn=self.residual_burn,
            ar_order=self.ar_order,
            ma_order=self.ma_order,
            max_iterations=self.arima_max_iterations,
            pgtol=self.arima_pgtol,
            factr=self.arima_factr,
            root_margin=self.root_margin,
            constant_return_tolerance=RETURN_STD_TOLERANCE,
        )
        garch = GarchForecastConfig(
            estimation_returns=arima.residuals,
            annualization=ANNUALIZATION,
            initial_omega_share=self.initial_omega_share,
            initial_alpha=self.initial_alpha,
            initial_beta=self.initial_beta,
            initial_nu=self.initial_nu,
            max_iterations=self.garch_max_iterations,
            ftol=self.garch_ftol,
            ewma_decay=self.ewma_decay,
            ewma_seed_returns=self.ewma_seed_returns,
            constant_return_tolerance=RETURN_STD_TOLERANCE,
        )
        if self.volatility_model not in {model.value for model in VolatilityModel}:
            raise ValueError(f"volatility_model is GARCH or EWMA, got {self.volatility_model!r}")
        return ArimaGarchConfig(arima, garch, VolatilityModel(self.volatility_model))

    def forecast_signal(self) -> ArimaGarchForecastSignal:
        """Return the joint forecast, on adjusted opens of the decided session."""
        name = (
            f"arima{self.ar_order}0{self.ma_order}_{self.volatility_model.lower()}"
            f"_mu2_{self.estimation_returns}r"
        )
        return ArimaGarchForecastSignal(
            signal_id=name, config=self.forecast_config(), max_age_sessions=PRICE_MAX_AGE_SESSIONS
        )

    def required_signals(self) -> Sequence[Signal | SignalRequest]:
        """Return the joint forecast, on the fund only."""
        return (SignalRequest(signal=self.forecast_signal(), instruments=(self.instrument_id,)),)

    def validate(self) -> None:
        """Raise unless this strategy can be run, its estimators included.

        Raises
        ------
        MissingDependency
            If ``statsmodels``, or ``arch`` when GARCH is asked for, is not
            installed: a launch stops here and never becomes a book in cash.
        ValueError
            As for every strategy.
        """
        Strategy.validate(self)
        require_statsmodels()
        if self.volatility_model == VolatilityModel.GARCH.value:
            require_arch()

    def evaluate(self, ctx: StrategyContext) -> tuple[RuleTarget, SignalStatus]:
        """Return the theoretical target, before the band, and the forecast's status."""
        reading = read_joint_forecast(
            ctx.signal(self.forecast_signal().signal_id), self.instrument_id
        )
        target = gated_volatility_rule(
            self.instrument_id,
            reading.mean,
            reading.volatility,
            held=ctx.portfolio.holds(self.instrument_id),
            entry_threshold=self.entry_threshold,
            exit_threshold=self.exit_threshold,
            target_volatility=self.target_volatility,
            floor=self.volatility_floor,
            gated=self.direction_filter,
        )
        return target, reading.status

    def decide(self, ctx: StrategyContext) -> TargetAllocation:
        """Return the target for the next open: the gate, the sizing, then the band."""
        target, status = self.evaluate(ctx)
        usable = status is SignalStatus.OK
        entering = bool(target.weights) and not ctx.portfolio.holds(self.instrument_id)
        return settle(
            ctx,
            target.weights,
            band=self.rebalance_band,
            # An entry from cash is sent even when its target is inside the band.
            force=entering,
            unusable={} if usable else {self.instrument_id: status},
            readable=1 if usable and self.instrument_id in ctx.universe else 0,
        )
