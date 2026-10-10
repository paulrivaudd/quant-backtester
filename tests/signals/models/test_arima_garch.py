"""The joint forecast: its two-step formulas, its units, its failures and what it cannot see.

The pure functions are tested on written numbers and injected estimates; the
real estimators are run on seeded returns with a window of 120 returns, so
that a fit takes a few hundredths of a second.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from datetime import date, datetime

import numpy as np
import pytest

from quant_backtester.data.calendars import TradingCalendar
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.data.schemas import ActionType, BarField
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.models import arima_garch
from quant_backtester.signals.models.arima_garch import (
    ARIMA_INADMISSIBLE,
    ARIMA_NON_FINITE,
    ARIMA_NOT_CONVERGED,
    ARIMA_STAGE,
    FORECAST_COLUMNS,
    INVALID_RETURN_VARIANCE,
    NEAR_CONSTANT_RETURNS,
    VOLATILITY_STAGE,
    ArimaConfig,
    ArimaEstimate,
    ArimaGarchConfig,
    ArimaGarchForecastSignal,
    VolatilityModel,
    arma_two_step_mean,
    estimate_with_statsmodels,
    forecast_arima_garch,
    read_joint_forecast,
    require_statsmodels,
    second_step_innovation_variance,
    two_step_return_variance,
)
from quant_backtester.signals.models.garch import (
    GarchEstimate,
    GarchForecastConfig,
    MissingDependency,
    ewma_variance,
)
from quant_backtester.signals.types import SignalStatus, WindowSpec
from quant_backtester.signals.windows import load_adjusted_open_window, returns_of

pytest.importorskip("statsmodels")
pytest.importorskip("arch")

RETURNS, BURN = 120, 20
"""The test window: 121 opens, 120 returns, 100 innovations for the variance."""

DECISION_INDEX = 150


def arima(**overrides: object) -> ArimaConfig:
    """Return the conventions of SA12's mean on the test window, unless overridden."""
    parameters: dict[str, object] = {
        "estimation_returns": RETURNS,
        "residual_burn": BURN,
        "ar_order": 1,
        "ma_order": 1,
        "max_iterations": 1000,
        "pgtol": 1e-8,
        "factr": 1e7,
        "root_margin": 1e-6,
        "constant_return_tolerance": 1e-12,
    }
    parameters.update(overrides)
    return ArimaConfig(**parameters)  # type: ignore[arg-type]


def garch(returns: int = RETURNS - BURN) -> GarchForecastConfig:
    """Return SA11's conventions for the variance, on the innovations left."""
    return GarchForecastConfig(
        estimation_returns=returns,
        annualization=252,
        initial_omega_share=0.05,
        initial_alpha=0.05,
        initial_beta=0.90,
        initial_nu=8.0,
        max_iterations=1000,
        ftol=1e-8,
        ewma_decay=0.94,
        ewma_seed_returns=20,
        constant_return_tolerance=1e-12,
    )


def config(model: VolatilityModel = VolatilityModel.GARCH, **overrides: object) -> ArimaGarchConfig:
    """Return the joint configuration of the test window."""
    return ArimaGarchConfig(arima(**overrides), garch(), model)


def seeded_returns(count: int = RETURNS, seed: int = 7) -> list[float]:
    """Return fat-tailed returns with a little autocorrelation, from a seed."""
    rng = np.random.default_rng(seed)
    shocks = rng.standard_t(6, count) * 0.008
    returns = [0.0004 + shocks[0]]
    for index in range(1, count):
        returns.append(0.0004 + 0.15 * (returns[-1] - 0.0004) + shocks[index])
    return returns


def mean_estimate(**overrides: object) -> ArimaEstimate:
    """Return an admissible estimate of the mean, in percent units, unless overridden."""
    rng = np.random.default_rng(11)
    fields: dict[str, object] = {
        "converged": True,
        "loglikelihood": -150.0,
        "mean": 0.04,
        "phi": 0.5,
        "theta": 0.2,
        "sigma2": 0.8,
        "forecast_h1": 0.54,
        "forecast_h2": 0.27,
        "innovations": tuple(float(value) for value in rng.normal(0.0, 0.9, RETURNS)),
        "iterations": 9,
    }
    fields.update(overrides)
    return ArimaEstimate(**fields)  # type: ignore[arg-type]


def variance_estimate(**overrides: object) -> GarchEstimate:
    """Return an admissible GARCH estimate, in percent units, unless overridden."""
    fields: dict[str, object] = {
        "converged": True,
        "loglikelihood": -120.0,
        "omega": 0.2,
        "alpha": 0.1,
        "beta": 0.7,
        "nu": 7.0,
        "last_filtered_variance": 0.9,
        "forecast_variance": 1.0,
        "backcast": 0.8,
        "iterations": 10,
    }
    fields.update(overrides)
    return GarchEstimate(**fields)  # type: ignore[arg-type]


def fixed_mean(
    found: ArimaEstimate, seen: list[list[float]] | None = None
) -> Callable[..., ArimaEstimate]:
    """Return an ARIMA estimator answering ``found``, recording what it was given."""

    def estimator(scaled: Sequence[float], settings: ArimaConfig) -> ArimaEstimate:
        if seen is not None:
            seen.append(list(scaled))
        return found

    return estimator


def fixed_variance(
    found: GarchEstimate, seen: list[list[float]] | None = None
) -> Callable[..., GarchEstimate]:
    """Return a GARCH estimator answering ``found``, recording what it was given."""

    def estimator(scaled: Sequence[float], settings: GarchForecastConfig) -> GarchEstimate:
        if seen is not None:
            seen.append(list(scaled))
        return found

    return estimator


def never(*_: object) -> GarchEstimate:
    """Fail the test if the variance model is reached."""
    raise AssertionError("the variance model must not be fitted here")


# --- the formulas --------------------------------------------------------------------------


def test_the_reference_example_of_the_specification() -> None:
    """Check the formulas on m = 0, phi = 0.5, theta = 0.2, r = 1%, e = 0.2%, h1 = 1e-4."""
    first, second = arma_two_step_mean(0.0, 0.5, 0.2, 0.01, 0.002)
    variance = two_step_return_variance(0.0001, 0.00012, 0.5, 0.2)
    volatility = math.sqrt(252.0 * variance)

    assert (first, second) == (pytest.approx(0.0054), pytest.approx(0.0027))
    assert variance == pytest.approx(0.000169)
    assert volatility == pytest.approx(0.206369, abs=1e-6)
    assert min(1.0, 0.12 / max(volatility, 0.05)) == pytest.approx(0.581484, abs=1e-6)


def test_the_second_innovation_variance_is_one_garch_step_from_the_first() -> None:
    assert second_step_innovation_variance(2e-5, 0.1, 0.7, 1e-4) == pytest.approx(2e-5 + 0.8e-4)


def test_the_return_variance_carries_the_shock_travelling_through_the_mean() -> None:
    """h2 alone is the variance of an innovation, not of the return two steps ahead."""
    assert two_step_return_variance(1e-4, 1.2e-4, 0.0, 0.0) == pytest.approx(1.2e-4)
    assert two_step_return_variance(1e-4, 1.2e-4, 0.5, 0.2) > 1.2e-4
    assert two_step_return_variance(1e-4, 1.2e-4, 0.5, -0.5) == pytest.approx(1.2e-4)


# --- units and horizons, on injected estimates ---------------------------------------------


def test_returns_go_in_as_percent_and_everything_comes_back_decimal() -> None:
    given_mean: list[list[float]] = []
    given_variance: list[list[float]] = []
    found = mean_estimate()
    returns = seeded_returns()

    forecast = forecast_arima_garch(
        returns,
        config(),
        arima_estimator=fixed_mean(found, given_mean),
        garch_estimator=fixed_variance(variance_estimate(), given_variance),
    )

    assert given_mean[0] == [100.0 * value for value in returns]
    # The variance model gets the innovations after the burn, converted once
    # to decimal by the forecast and once back to percent by the GARCH adapter.
    assert len(given_variance[0]) == RETURNS - BURN
    assert given_variance[0] == pytest.approx(list(found.innovations[BURN:]))
    assert forecast.usable and forecast.failure_stage is None
    assert (forecast.n_returns, forecast.n_residuals) == (RETURNS, RETURNS - BURN)
    assert forecast.mu_h1 == pytest.approx(0.0054) and forecast.mu_h2 == pytest.approx(0.0027)
    assert forecast.long_run_mean == pytest.approx(0.0004)
    assert forecast.arima_sigma2 == pytest.approx(0.8 / 10_000.0)
    assert (forecast.phi, forecast.theta) == (0.5, 0.2)
    assert forecast.innovation_variance_h1 == pytest.approx(1.0 / 10_000.0)
    assert forecast.omega_decimal == pytest.approx(0.2 / 10_000.0)
    assert forecast.volatility_source == "GARCH"


def test_the_two_step_variance_and_its_annualisation_are_those_of_the_formulas() -> None:
    forecast = forecast_arima_garch(
        seeded_returns(),
        config(),
        arima_estimator=fixed_mean(mean_estimate()),
        garch_estimator=fixed_variance(variance_estimate()),
    )

    first = 1.0 / 10_000.0
    second = 0.2 / 10_000.0 + 0.8 * first
    assert forecast.innovation_variance_h2 == pytest.approx(second)
    assert forecast.return_variance_h2 == pytest.approx(second + 0.7**2 * first)
    # One session's return forecast two steps ahead: the variance is not halved.
    assert forecast.annualized_volatility == pytest.approx(
        math.sqrt(252.0 * (second + 0.49 * first))
    )


def test_a_refused_garch_fit_falls_back_on_the_ewma_of_the_same_innovations() -> None:
    found = mean_estimate()
    residuals = [value / 100.0 for value in found.innovations[BURN:]]

    forecast = forecast_arima_garch(
        seeded_returns(),
        config(),
        arima_estimator=fixed_mean(found),
        garch_estimator=fixed_variance(variance_estimate(converged=False)),
    )

    first = ewma_variance(residuals, decay=0.94, seed_returns=20)
    assert forecast.usable
    assert forecast.volatility_source == "EWMA_FALLBACK"
    assert forecast.fallback_reason == "NOT_CONVERGED"
    assert forecast.innovation_variance_h1 == pytest.approx(first)
    assert forecast.innovation_variance_h2 == forecast.innovation_variance_h1  # h2 = h1
    assert forecast.return_variance_h2 == pytest.approx((1.0 + 0.49) * first)
    assert forecast.mu_h2 == pytest.approx(0.0027)  # the mean is untouched by the fallback


def test_the_ewma_control_fits_no_garch_and_says_which_variance_it_used() -> None:
    found = mean_estimate()
    residuals = [value / 100.0 for value in found.innovations[BURN:]]

    forecast = forecast_arima_garch(
        seeded_returns(),
        config(VolatilityModel.EWMA),
        arima_estimator=fixed_mean(found),
        garch_estimator=never,
    )

    first = ewma_variance(residuals, decay=0.94, seed_returns=20)
    assert forecast.usable and forecast.volatility_source == "EWMA"
    assert forecast.fallback_reason is None and forecast.omega_decimal is None
    assert forecast.return_variance_h2 == pytest.approx(1.49 * first)


def test_a_constant_mean_has_no_shock_to_propagate() -> None:
    """The control ARIMA(0,0,0): phi = theta = 0, so v2 = h2."""
    found = mean_estimate(phi=0.0, theta=0.0, forecast_h1=0.04, forecast_h2=0.04)

    forecast = forecast_arima_garch(
        seeded_returns(),
        config(ar_order=0, ma_order=0),
        arima_estimator=fixed_mean(found),
        garch_estimator=fixed_variance(variance_estimate()),
    )

    assert forecast.return_variance_h2 == forecast.innovation_variance_h2
    assert forecast.mu_h1 == forecast.mu_h2 == pytest.approx(0.0004)


# --- failures ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("found", "code"),
    [
        (mean_estimate(converged=False), ARIMA_NOT_CONVERGED),
        (mean_estimate(forecast_h2=float("nan")), ARIMA_NON_FINITE),
        (mean_estimate(loglikelihood=float("inf")), ARIMA_NON_FINITE),
        (mean_estimate(phi=1.0), ARIMA_INADMISSIBLE),
        (mean_estimate(phi=-(1.0 - 1e-7)), ARIMA_INADMISSIBLE),
        (mean_estimate(theta=0.9999999), ARIMA_INADMISSIBLE),
        (mean_estimate(sigma2=0.0), ARIMA_INADMISSIBLE),
    ],
    ids=[
        "not-converged",
        "mean-not-finite",
        "likelihood-not-finite",
        "unit-root",
        "root-inside-the-margin",
        "not-invertible",
        "no-innovation-variance",
    ],
)
def test_a_refused_mean_is_not_replaced_by_anything(found: ArimaEstimate, code: str) -> None:
    forecast = forecast_arima_garch(
        seeded_returns(), config(), arima_estimator=fixed_mean(found), garch_estimator=never
    )

    assert not forecast.usable
    assert (forecast.failure_stage, forecast.failure_code) == (ARIMA_STAGE, code)
    # Nothing a decision could act on: no optimistic constant, no old coefficient.
    assert forecast.mu_h2 is None and forecast.return_variance_h2 is None
    assert forecast.annualized_volatility is None
    assert forecast.arima_converged is found.converged


def test_constant_returns_are_not_fitted_at_all() -> None:
    def no_mean(*_: object) -> ArimaEstimate:
        raise AssertionError("constant returns must not reach the estimator")

    forecast = forecast_arima_garch(
        [0.001] * RETURNS, config(), arima_estimator=no_mean, garch_estimator=never
    )

    assert not forecast.usable
    assert (forecast.failure_stage, forecast.failure_code) == (ARIMA_STAGE, NEAR_CONSTANT_RETURNS)


def test_a_variance_of_zero_makes_the_joint_forecast_unusable() -> None:
    """GARCH has nothing to fit on innovations that do not vary, and the EWMA gives zero."""
    found = mean_estimate(innovations=tuple([0.0] * RETURNS))

    forecast = forecast_arima_garch(
        seeded_returns(), config(), arima_estimator=fixed_mean(found), garch_estimator=never
    )

    assert not forecast.usable
    assert (forecast.failure_stage, forecast.failure_code) == (
        VOLATILITY_STAGE,
        INVALID_RETURN_VARIANCE,
    )
    assert forecast.mu_h1 == pytest.approx(0.0054)  # kept as a diagnostic
    assert forecast.mu_h2 is None  # and nothing to act on


def test_invalid_returns_and_a_misconfigured_pair_are_errors_not_forecasts() -> None:
    with pytest.raises(ValueError, match="configured for 120 returns"):
        forecast_arima_garch(seeded_returns(RETURNS - 1), config())
    with pytest.raises(ValueError, match="not finite"):
        forecast_arima_garch([*seeded_returns(RETURNS - 1), float("nan")], config())
    with pytest.raises(ValueError, match="innovations and the mean leaves"):
        ArimaGarchConfig(arima(), garch(returns=90), VolatilityModel.GARCH)
    with pytest.raises(ValueError, match="VolatilityModel"):
        ArimaGarchConfig(arima(), garch(), "GARCH")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"estimation_returns": 0}, "estimation_returns"),
        ({"residual_burn": RETURNS}, "residual_burn"),
        ({"ar_order": 2}, "ar_order"),
        ({"ma_order": -1}, "ma_order"),
        ({"root_margin": 1.0}, "root_margin"),
        ({"pgtol": 0.0}, "pgtol"),
        ({"factr": float("nan")}, "factr"),
    ],
)
def test_a_mean_no_fit_can_come_from_is_refused(overrides: dict[str, object], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        arima(**overrides)


def test_a_missing_estimator_stops_the_launch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(arima_garch.importlib.util, "find_spec", lambda name: None)

    with pytest.raises(MissingDependency, match="stats extra"):
        require_statsmodels()
    with pytest.raises(MissingDependency):
        forecast_arima_garch(seeded_returns(), config())


# --- the real estimators -------------------------------------------------------------------


def test_the_adapter_fits_the_declared_order_from_its_single_starting_point() -> None:
    scaled = [100.0 * value for value in seeded_returns()]

    found = estimate_with_statsmodels(scaled, arima())
    again = estimate_with_statsmodels(scaled, arima())
    constant = estimate_with_statsmodels(scaled, arima(ar_order=0, ma_order=0))

    assert found == again  # no warm start, no random state
    assert found.converged and len(found.innovations) == RETURNS
    assert abs(found.phi) < 1.0 and abs(found.theta) < 1.0 and found.sigma2 > 0.0
    # The constant of the library is the long-run mean, not the intercept (1 - phi) m.
    assert found.mean == pytest.approx(float(np.mean(scaled)), abs=0.15)
    assert (constant.phi, constant.theta) == (0.0, 0.0)
    assert constant.forecast_h1 == pytest.approx(constant.mean)
    assert constant.forecast_h2 == pytest.approx(constant.mean)


def test_the_mean_acted_on_is_the_second_forecast_of_the_filtered_state() -> None:
    returns = seeded_returns()
    found = estimate_with_statsmodels([100.0 * value for value in returns], arima())

    forecast = forecast_arima_garch(returns, config())

    assert forecast.usable
    assert forecast.mu_h1 == pytest.approx(found.forecast_h1 / 100.0)
    assert forecast.mu_h2 == pytest.approx(found.forecast_h2 / 100.0)
    # The recursion of the model links the two; the filter's own state decides the first.
    assert forecast.long_run_mean is not None and forecast.phi is not None
    assert forecast.mu_h1 is not None
    assert forecast.mu_h2 == pytest.approx(
        forecast.long_run_mean + forecast.phi * (forecast.mu_h1 - forecast.long_run_mean), abs=1e-9
    )
    by_hand, _ = arma_two_step_mean(
        found.mean, found.phi, found.theta, 100.0 * returns[-1], found.innovations[-1]
    )
    assert found.forecast_h1 == pytest.approx(by_hand, abs=1e-4)


@pytest.mark.parametrize("seed", range(4))
def test_a_real_joint_forecast_is_usable_or_says_where_it_failed(seed: int) -> None:
    first = forecast_arima_garch(seeded_returns(seed=seed), config())
    second = forecast_arima_garch(seeded_returns(seed=seed), config())

    assert first == second
    if first.usable:
        assert first.mu_h2 is not None and math.isfinite(first.mu_h2)
        assert first.return_variance_h2 is not None and first.return_variance_h2 > 0.0
        assert first.volatility_source in ("GARCH", "EWMA_FALLBACK")
        assert first.annualized_volatility == pytest.approx(
            math.sqrt(252.0 * first.return_variance_h2)
        )
    else:
        assert first.failure_stage in (ARIMA_STAGE, VOLATILITY_STAGE)
        assert first.failure_code is not None and first.mu_h2 is None


# --- the signal, through a context ---------------------------------------------------------


@pytest.fixture
def year(xpar: TradingCalendar) -> list[date]:
    """Return every Paris session of 2026 from the fund's first one."""
    return [session.session_date for session in xpar.sessions(date(2026, 1, 5), date(2026, 12, 31))]


def closes_of(days: Sequence[date], seed: int = 5) -> dict[date, float]:
    """Return a close per session, from seeded returns; the bars open at their close."""
    prices = [100.0]
    for value in seeded_returns(len(days) - 1, seed):
        prices.append(prices[-1] * math.exp(value))
    return dict(zip(days, prices, strict=True))


def signal(model: VolatilityModel = VolatilityModel.GARCH) -> ArimaGarchForecastSignal:
    """Return the joint signal of the test window."""
    return ArimaGarchForecastSignal(
        signal_id="arima101_garch_mu2_120r", config=config(model), max_age_sessions=0
    )


Decide = Callable[[dict[date, float], date], SignalContext]


@pytest.fixture
def decide(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., object],
    make_context: Callable[[MarketDataReader, datetime], SignalContext],
    evening: Callable[[date], datetime],
    xpar: TradingCalendar,
) -> Decide:
    """Return the context of a decision after the close of a day, on written closes."""

    def build(closes: dict[date, float], day: date) -> SignalContext:
        market = make_market({"ETF_EU": make_bars("ETF_EU", xpar, closes)})
        return make_context(market, evening(day))

    return build


def test_the_signal_is_the_joint_forecast_of_its_window_computed_once(
    decide: Decide, year, monkeypatch
) -> None:
    calls: list[int] = []
    real = arima_garch.forecast_arima_garch

    def counted(returns: Sequence[float], settings: ArimaGarchConfig) -> object:
        calls.append(len(returns))
        return real(returns, settings)

    monkeypatch.setattr(arima_garch, "forecast_arima_garch", counted)
    day = year[DECISION_INDEX]
    context = decide(closes_of(year), day)
    window = load_adjusted_open_window(
        context, "ETF_EU", spec=WindowSpec(RETURNS + 1), max_age_sessions=0
    )

    result = signal().compute(context, ["ETF_EU"])

    # The forecast of exactly the window the loader serves: an optimiser on a
    # hundred innovations moves in its fifth digit for a last-bit change of input.
    expected = real(returns_of(window, logarithmic=True), config())
    row = result.frame.loc["ETF_EU"]
    assert calls == [RETURNS]  # one joint fit per instrument and call, not one per column
    assert result.status("ETF_EU") is SignalStatus.OK and expected.usable
    assert result.value("ETF_EU") == expected.mu_h2
    assert row["return_variance_h2"] == expected.return_variance_h2
    assert row["annualized_volatility"] == expected.annualized_volatility
    assert row["volatility_source"] == expected.volatility_source
    assert (row["n_returns"], row["n_residuals"]) == (RETURNS, RETURNS - BURN)
    assert row["observations_used"] == RETURNS + 1 and row["input_end_date"] == day
    assert set(FORECAST_COLUMNS) <= set(result.frame.columns)
    reading = read_joint_forecast(result.frame, "ETF_EU")
    assert (reading.mean, reading.volatility) == (
        result.value("ETF_EU"),
        row["annualized_volatility"],
    )


def test_one_open_short_of_the_window_gets_a_status_and_no_fit(decide: Decide, year) -> None:
    closes = closes_of(year)

    short = signal().compute(decide(closes, year[RETURNS - 1]), ["ETF_EU"])
    full = signal().compute(decide(closes, year[RETURNS]), ["ETF_EU"])

    assert short.status("ETF_EU") is SignalStatus.INSUFFICIENT_HISTORY
    assert math.isnan(short.value("ETF_EU"))
    assert short.frame.loc["ETF_EU", "failure_stage"] is None  # a data status, not a failed fit
    assert full.status("ETF_EU") is SignalStatus.OK
    reading = read_joint_forecast(short.frame, "ETF_EU")
    assert (reading.status, reading.mean, reading.volatility) == (
        SignalStatus.INSUFFICIENT_HISTORY,
        None,
        None,
    )


def test_a_hole_in_the_opens_is_not_imputed(
    make_market, make_bars, make_context, evening, xpar, year
) -> None:
    closes = closes_of(year)
    hole = year[DECISION_INDEX - 30]
    bars = make_bars("ETF_EU", xpar, closes, contested={hole: [BarField.OPEN]})
    context = make_context(make_market({"ETF_EU": bars}), evening(year[DECISION_INDEX]))

    result = signal().compute(context, ["ETF_EU"])

    assert result.status("ETF_EU") is SignalStatus.NON_CONSECUTIVE_HISTORY
    assert result.frame.loc["ETF_EU", "volatility_source"] is None


def test_a_mean_that_cannot_be_fitted_is_invalid_input_at_the_arima_stage(
    decide: Decide, year
) -> None:
    """A flat fund has no direction to forecast: not a hole in the data, and no number."""
    result = signal().compute(decide(dict.fromkeys(year, 100.0), year[DECISION_INDEX]), ["ETF_EU"])

    row = result.frame.loc["ETF_EU"]
    assert result.status("ETF_EU") is SignalStatus.INVALID_INPUT
    assert math.isnan(result.value("ETF_EU"))
    assert (row["failure_stage"], row["failure_code"]) == (ARIMA_STAGE, NEAR_CONSTANT_RETURNS)
    assert row["annualized_volatility"] is None


def test_what_becomes_known_after_the_decision_changes_nothing(
    make_market, make_bars, make_actions, make_context, evening, xpar, year
) -> None:
    """Later prices and a split announced later: the fit of the decision is the same."""
    closes = closes_of(year)
    day = year[DECISION_INDEX]
    bars = {"ETF_EU": make_bars("ETF_EU", xpar, closes)}
    before = signal().compute(make_context(make_market(bars), evening(day)), ["ETF_EU"]).frame

    moved = dict(closes)
    for session in year[DECISION_INDEX + 1 :]:
        moved[session] = closes[session] * 0.5
    known_later = make_actions(
        [("ETF_EU", ActionType.SPLIT, year[DECISION_INDEX - 20], 4.0, evening(year[-1]))]
    )
    later = make_market({"ETF_EU": make_bars("ETF_EU", xpar, moved)}, actions=known_later)
    after = signal().compute(make_context(later, evening(day)), ["ETF_EU"]).frame

    assert after.equals(before)


def test_a_decision_gives_the_same_forecast_whatever_was_computed_before(
    make_market, make_bars, make_context, evening, xpar, year
) -> None:
    market = make_market({"ETF_EU": make_bars("ETF_EU", xpar, closes_of(year))})
    first, second = year[DECISION_INDEX], year[DECISION_INDEX + 15]
    one = signal()

    alone = one.compute(make_context(market, evening(first)), ["ETF_EU"]).frame
    one.compute(make_context(market, evening(second)), ["ETF_EU"])
    again = one.compute(make_context(market, evening(first)), ["ETF_EU"]).frame

    assert again.equals(alone)


def test_the_signal_names_its_price_its_target_and_its_unit() -> None:
    definition = signal().definition_json()

    assert definition["price"] == "RAW_OPEN_TIMES_PIT_CLOSE_ADJUSTMENT_V1"
    assert definition["unit"] == "FRACTION" and "log return" in str(definition["value"])
    assert "second step" in str(definition["target"])
    assert signal().window_spec().observations == RETURNS + 1
    assert signal().fingerprint() != signal(VolatilityModel.EWMA).fingerprint()
    inner = definition["config"]
    assert isinstance(inner, dict)
    assert inner["forecast_horizon_sessions"] == 2 and inner["target_return_sessions"] == 1
    assert inner["arima"]["model"] == "ARIMA(1,0,1)"
    assert "not a joint likelihood" in inner["estimation"]


def test_a_frame_without_its_volatility_is_a_breach_of_contract_not_a_day_in_cash(
    decide: Decide, year
) -> None:
    frame = signal().compute(decide(closes_of(year), year[DECISION_INDEX]), ["ETF_EU"]).frame

    with pytest.raises(KeyError, match="annualized_volatility"):
        read_joint_forecast(frame.drop(columns=["annualized_volatility"]), "ETF_EU")
    broken = frame.copy()
    broken.loc["ETF_EU", "annualized_volatility"] = float("nan")
    with pytest.raises(ValueError, match="OK with a volatility"):
        read_joint_forecast(broken, "ETF_EU")
