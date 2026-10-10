"""The GARCH forecast: its recursion, its units, its fallback, and what it cannot see.

The pure functions are tested on written returns; the signal is tested through
a real context, on a seeded market of every Paris session of 2026, with a
window of 120 returns so that a fit takes milliseconds.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import date, datetime
from itertools import pairwise

import numpy as np
import pytest

from quant_backtester.data.calendars import TradingCalendar
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.data.schemas import ActionType, BarField
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.models import garch
from quant_backtester.signals.models.garch import (
    INADMISSIBLE_PARAMETERS,
    INVALID_FORECAST,
    NEAR_CONSTANT_RETURNS,
    NON_FINITE_ESTIMATE,
    NOT_CONVERGED,
    PERCENT,
    EwmaVolatilitySignal,
    ForecastSource,
    GarchEstimate,
    GarchForecastConfig,
    GarchVolatilitySignal,
    MissingDependency,
    estimate_with_arch,
    ewma_variance,
    forecast_garch,
    garch_one_step,
    require_arch,
)
from quant_backtester.signals.types import PriceBasis, SignalStatus

pytest.importorskip("arch")

RETURNS = 120
"""Returns the test model is fitted on: 121 closes."""

DECISION_INDEX = 150
"""The session, among those of 2026, most tests decide after the close of."""


def config(**overrides: object) -> GarchForecastConfig:
    """Return the conventions of SA11 on a window of 120 returns, unless overridden."""
    parameters: dict[str, object] = {
        "estimation_returns": RETURNS,
        "annualization": 252,
        "initial_omega_share": 0.05,
        "initial_alpha": 0.05,
        "initial_beta": 0.90,
        "initial_nu": 8.0,
        "max_iterations": 1000,
        "ftol": 1e-8,
        "ewma_decay": 0.94,
        "ewma_seed_returns": 60,
        "constant_return_tolerance": 1e-12,
    }
    parameters.update(overrides)
    return GarchForecastConfig(**parameters)  # type: ignore[arg-type]


def simulated_returns(count: int, seed: int) -> list[float]:
    """Return ``count`` returns of a GARCH(1,1) with Student innovations, from a seed."""
    rng = np.random.default_rng(seed)
    omega, alpha, beta, nu = 2e-6, 0.08, 0.90, 8.0
    variance = omega / (1.0 - alpha - beta)
    returns: list[float] = []
    for _ in range(count):
        shock = float(rng.standard_t(nu)) / math.sqrt(nu / (nu - 2.0))
        value = math.sqrt(variance) * shock
        returns.append(value)
        variance = omega + alpha * value**2 + beta * variance
    return returns


def estimate(**overrides: object) -> GarchEstimate:
    """Return an admissible estimate in percent units, unless overridden."""
    fields: dict[str, object] = {
        "converged": True,
        "loglikelihood": -150.0,
        "omega": 0.02,
        "alpha": 0.10,
        "beta": 0.85,
        "nu": 7.0,
        "last_filtered_variance": 1.2,
        "forecast_variance": 1.5,
        "backcast": 1.0,
        "iterations": 12,
    }
    fields.update(overrides)
    return GarchEstimate(**fields)  # type: ignore[arg-type]


def returning(
    found: GarchEstimate,
) -> Callable[[Sequence[float], GarchForecastConfig], GarchEstimate]:
    """Return an estimator that answers ``found`` whatever it is asked."""

    def estimator(scaled: Sequence[float], settings: GarchForecastConfig) -> GarchEstimate:
        return found

    return estimator


# --- the recursion and the units ---------------------------------------------------------


def test_the_one_step_forecast_is_omega_plus_alpha_shock_plus_beta_variance() -> None:
    assert garch_one_step(0.02, 0.10, 0.85, 2.0, 1.2) == pytest.approx(0.02 + 0.10 * 4.0 + 1.02)


def test_the_adapter_forecast_is_the_recursion_on_its_own_estimate() -> None:
    """The forecast used holds the last shock: it is not the filtered variance."""
    returns = simulated_returns(RETURNS, seed=3)

    forecast = forecast_garch(returns, config())

    assert forecast.source is ForecastSource.GARCH
    assert forecast.omega is not None and forecast.alpha is not None and forecast.beta is not None
    assert forecast.last_filtered_variance is not None
    by_hand = garch_one_step(
        forecast.omega, forecast.alpha, forecast.beta, returns[-1], forecast.last_filtered_variance
    )
    assert forecast.variance == pytest.approx(by_hand, rel=1e-9)
    assert forecast.variance != pytest.approx(forecast.last_filtered_variance, rel=1e-6)


def test_returns_are_scaled_by_one_hundred_and_variances_by_ten_thousand() -> None:
    seen: list[list[float]] = []

    def estimator(scaled: Sequence[float], settings: GarchForecastConfig) -> GarchEstimate:
        seen.append(list(scaled))
        return estimate()

    returns = simulated_returns(RETURNS, seed=1)

    forecast = forecast_garch(returns, config(), estimator=estimator)

    assert seen[0] == [PERCENT * value for value in returns]
    assert forecast.variance == pytest.approx(1.5 / 10_000.0)
    assert forecast.omega == pytest.approx(0.02 / 10_000.0)
    assert forecast.last_filtered_variance == pytest.approx(1.2 / 10_000.0)
    assert forecast.backcast == pytest.approx(1.0 / 10_000.0)
    # Unit-free parameters are not rescaled.
    assert (forecast.alpha, forecast.beta, forecast.nu) == (0.10, 0.85, 7.0)
    assert forecast.persistence == pytest.approx(0.95)


def test_a_volatility_of_twenty_percent_is_written_zero_point_two() -> None:
    daily = 0.20**2 / 252.0 * 10_000.0
    forecast = forecast_garch(
        simulated_returns(RETURNS, seed=1),
        config(),
        estimator=returning(estimate(forecast_variance=daily)),
    )

    assert forecast.annualized_volatility(252) == pytest.approx(0.20)
    # The annualisation is the caller's: another convention is another number.
    assert forecast.annualized_volatility(255) == pytest.approx(0.20 * math.sqrt(255 / 252))


def test_the_adapter_records_its_backcast_and_its_single_starting_point() -> None:
    scaled = [PERCENT * value for value in simulated_returns(RETURNS, seed=5)]

    first = estimate_with_arch(scaled, config())
    again = estimate_with_arch(scaled, config())

    assert first == again  # no restart, no random state: one fit is every fit
    assert first.backcast > 0.0
    assert first.iterations >= 1


@pytest.mark.parametrize("seed", range(6))
def test_a_seeded_series_gives_an_admissible_fit_or_a_documented_fallback(seed: int) -> None:
    """A finite sample need not give back the parameters that generated it."""
    forecast = forecast_garch(simulated_returns(RETURNS, seed=seed), config())

    assert forecast.variance is not None and math.isfinite(forecast.variance)
    assert forecast.variance > 0.0
    if forecast.source is ForecastSource.GARCH:
        assert forecast.fallback_reason is None
        assert forecast.converged is True
        assert forecast.omega is not None and forecast.omega > 0.0
        assert forecast.persistence is not None and forecast.persistence < 1.0
        assert forecast.nu is not None and forecast.nu > 2.0
    else:
        assert forecast.source is ForecastSource.EWMA_FALLBACK
        assert forecast.fallback_reason in garch.FALLBACK_REASONS


# --- the fallback ------------------------------------------------------------------------


def reference_ewma(returns: Sequence[float], decay: float, seed_returns: int) -> float:
    """Return the EWMA of the specification, written as its loop."""
    variance = sum(value**2 for value in returns[:seed_returns]) / seed_returns
    for index in range(seed_returns, len(returns)):
        variance = decay * variance + (1.0 - decay) * returns[index] ** 2
    return variance


def test_the_ewma_is_the_loop_of_its_definition() -> None:
    returns = simulated_returns(RETURNS, seed=2)

    assert ewma_variance(returns, decay=0.94, seed_returns=60) == pytest.approx(
        reference_ewma(returns, 0.94, 60), rel=1e-12
    )
    # With nothing after the seed but one return, the recursion runs once.
    assert ewma_variance([0.01, 0.01, 0.03], decay=0.5, seed_returns=2) == pytest.approx(
        0.5 * 0.0001 + 0.5 * 0.0009
    )


@pytest.mark.parametrize(
    ("found", "reason"),
    [
        (estimate(converged=False), NOT_CONVERGED),
        (estimate(alpha=0.15, beta=0.85), INADMISSIBLE_PARAMETERS),
        (estimate(alpha=0.20, beta=0.85), INADMISSIBLE_PARAMETERS),
        (estimate(nu=2.0), INADMISSIBLE_PARAMETERS),
        (estimate(omega=0.0), INADMISSIBLE_PARAMETERS),
        (estimate(alpha=-0.01), INADMISSIBLE_PARAMETERS),
        (estimate(loglikelihood=float("nan")), NON_FINITE_ESTIMATE),
        (estimate(beta=float("inf")), NON_FINITE_ESTIMATE),
        (estimate(forecast_variance=float("nan")), INVALID_FORECAST),
        (estimate(forecast_variance=0.0), INVALID_FORECAST),
    ],
    ids=[
        "solver-failed",
        "persistence-of-one",
        "persistence-above-one",
        "student-without-variance",
        "omega-of-zero",
        "negative-alpha",
        "likelihood-not-finite",
        "parameter-not-finite",
        "forecast-not-finite",
        "forecast-of-zero",
    ],
)
def test_a_refused_fit_falls_back_on_the_ewma_and_says_why(
    found: GarchEstimate, reason: str
) -> None:
    returns = simulated_returns(RETURNS, seed=4)

    forecast = forecast_garch(returns, config(), estimator=returning(found))

    assert forecast.source is ForecastSource.EWMA_FALLBACK
    assert forecast.fallback_reason == reason
    assert forecast.variance == pytest.approx(reference_ewma(returns, 0.94, 60), rel=1e-12)
    # What the refused fit found is kept as it was found: nothing is nudged inside.
    assert forecast.converged is found.converged
    assert forecast.alpha == found.alpha or math.isnan(found.alpha)


def test_constant_returns_are_not_fitted_and_an_ewma_of_zero_is_admissible() -> None:
    def never(scaled: Sequence[float], settings: GarchForecastConfig) -> GarchEstimate:
        raise AssertionError("constant returns must not reach the estimator")

    forecast = forecast_garch([0.0] * RETURNS, config(), estimator=never)

    assert forecast.source is ForecastSource.EWMA_FALLBACK
    assert forecast.fallback_reason == NEAR_CONSTANT_RETURNS
    assert forecast.variance == 0.0
    assert forecast.annualized_volatility(252) == 0.0
    assert forecast.converged is None and forecast.omega is None


def test_a_fallback_that_is_not_finite_gives_no_number() -> None:
    huge = [1e160 if index % 2 else -1e160 for index in range(RETURNS)]

    forecast = forecast_garch(huge, config(), estimator=returning(estimate(converged=False)))

    assert forecast.source is ForecastSource.FALLBACK_FAILED
    assert forecast.variance is None
    assert forecast.annualized_volatility(252) is None
    assert forecast.fallback_reason == NOT_CONVERGED


def test_invalid_returns_are_refused_and_never_reach_the_fallback() -> None:
    returns = simulated_returns(RETURNS, seed=1)

    with pytest.raises(ValueError, match="configured for 120 returns"):
        forecast_garch(returns[:-1], config())
    with pytest.raises(ValueError, match="not finite"):
        forecast_garch([*returns[:-1], float("nan")], config())


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"estimation_returns": 0}, "estimation_returns"),
        ({"annualization": 0}, "annualization"),
        ({"initial_alpha": 0.2, "initial_beta": 0.8}, "initial_alpha"),
        ({"initial_nu": 2.0}, "initial_nu"),
        ({"ewma_decay": 1.0}, "ewma_decay"),
        ({"ewma_seed_returns": RETURNS}, "seed"),
        ({"ftol": float("nan")}, "ftol"),
        ({"constant_return_tolerance": -1.0}, "constant_return_tolerance"),
    ],
)
def test_a_configuration_no_forecast_can_come_from_is_refused(
    overrides: dict[str, object], match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        config(**overrides)


def test_the_configuration_is_recorded_whole_and_in_a_stable_form() -> None:
    definition = config().definition()

    assert definition == config().definition()
    assert definition["model"] == "GARCH(1,1)"
    assert definition["mean"] == "Zero"
    assert definition["estimation_returns"] == RETURNS
    assert definition["annualization"] == 252
    assert definition["return_scale"] == 100.0
    assert definition != config(ewma_decay=0.97).definition()


def test_a_missing_estimator_stops_the_launch_and_is_not_a_failed_fit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(garch.importlib.util, "find_spec", lambda name: None)

    with pytest.raises(MissingDependency, match="stats extra"):
        require_arch()
    with pytest.raises(MissingDependency):
        forecast_garch(simulated_returns(RETURNS, seed=1), config())
    # Returns that need no fit need no estimator either.
    assert forecast_garch([0.0] * RETURNS, config()).variance == 0.0


# --- the signal, through a context -------------------------------------------------------


@pytest.fixture
def year(xpar: TradingCalendar) -> list[date]:
    """Return every Paris session of 2026 from the fund's first one."""
    return [session.session_date for session in xpar.sessions(date(2026, 1, 5), date(2026, 12, 31))]


def closes_of(days: Sequence[date], seed: int = 11, start: float = 100.0) -> dict[date, float]:
    """Return a close per session, the first at ``start``, from simulated returns."""
    prices = [start]
    for value in simulated_returns(len(days) - 1, seed):
        prices.append(prices[-1] * math.exp(value))
    return dict(zip(days, prices, strict=True))


def signal(**overrides: object) -> GarchVolatilitySignal:
    """Return the forecast signal on adjusted closes of the decided session."""
    parameters: dict[str, object] = {
        "signal_id": "garch11_t_vol_120r",
        "config": config(),
        "price_basis": PriceBasis.ADJUSTED,
        "max_age_sessions": 0,
    }
    parameters.update(overrides)
    return GarchVolatilitySignal(**parameters)  # type: ignore[arg-type]


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


def log_returns(prices: Sequence[float]) -> list[float]:
    """Return the successive log returns of a list of prices."""
    return [math.log(after / before) for before, after in pairwise(prices)]


def test_the_signal_is_the_annualised_forecast_of_its_window(decide: Decide, year) -> None:
    closes = closes_of(year)
    day = year[DECISION_INDEX]
    window = [closes[session] for session in year[DECISION_INDEX - RETURNS : DECISION_INDEX + 1]]

    result = signal().compute(decide(closes, day), ["ETF_EU"])

    expected = forecast_garch(log_returns(window), config())
    assert expected.variance is not None
    assert result.status("ETF_EU") is SignalStatus.OK
    assert result.value("ETF_EU") == pytest.approx(math.sqrt(252.0 * expected.variance), rel=1e-12)
    row = result.frame.loc["ETF_EU"]
    assert row["observations_used"] == RETURNS + 1
    assert row["input_end_date"] == day
    assert row["max_input_age_sessions"] == 0


def test_the_annualisation_is_carried_by_the_configuration(decide: Decide, year) -> None:
    context = decide(closes_of(year), year[DECISION_INDEX])

    yearly = signal().compute(context, ["ETF_EU"]).value("ETF_EU")
    daily = signal(config=config(annualization=1)).compute(context, ["ETF_EU"]).value("ETF_EU")

    assert yearly == pytest.approx(daily * math.sqrt(252.0), rel=1e-12)
    assert signal().fingerprint() != signal(config=config(annualization=1)).fingerprint()


def test_one_close_short_of_the_window_is_refused_and_the_full_window_accepted(
    decide: Decide, year
) -> None:
    closes = closes_of(year)

    short = signal().compute(decide(closes, year[RETURNS - 1]), ["ETF_EU"])
    full = signal().compute(decide(closes, year[RETURNS]), ["ETF_EU"])

    assert short.status("ETF_EU") is SignalStatus.INSUFFICIENT_HISTORY
    assert math.isnan(short.value("ETF_EU"))
    assert full.status("ETF_EU") is SignalStatus.OK


def counting_fits(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Count the forecasts the signal asks for, and let them through."""
    calls: list[int] = []
    real = garch.forecast_garch

    def counted(returns: Sequence[float], settings: GarchForecastConfig) -> object:
        calls.append(len(returns))
        return real(returns, settings)

    monkeypatch.setattr(garch, "forecast_garch", counted)
    return calls


def test_a_window_with_a_hole_gets_no_fit_and_no_fallback(
    make_market, make_bars, make_context, evening, xpar, year, monkeypatch
) -> None:
    """A session the venue held and the series cannot serve is not a return of zero."""
    calls = counting_fits(monkeypatch)
    closes = closes_of(year)
    hole = year[DECISION_INDEX - 40]
    bars = make_bars("ETF_EU", xpar, closes, contested={hole: [BarField.CLOSE]})
    context = make_context(make_market({"ETF_EU": bars}), evening(year[DECISION_INDEX]))

    result = signal().compute(context, ["ETF_EU"])
    window, forecast = signal().diagnose(context, "ETF_EU")

    assert result.status("ETF_EU") is SignalStatus.NON_CONSECUTIVE_HISTORY
    assert math.isnan(result.value("ETF_EU"))
    assert window.status is SignalStatus.NON_CONSECUTIVE_HISTORY and forecast is None
    assert calls == []


def test_a_close_that_is_not_of_the_decided_session_gets_no_fit(
    decide: Decide, year, monkeypatch
) -> None:
    calls = counting_fits(monkeypatch)
    closes = closes_of(year)
    day = year[DECISION_INDEX]
    without_today = {session: close for session, close in closes.items() if session < day}

    result = signal().compute(decide(without_today, day), ["ETF_EU"])

    assert result.status("ETF_EU") in (SignalStatus.STALE_INPUT, SignalStatus.MISSING_INPUT)
    assert math.isnan(result.value("ETF_EU"))
    assert calls == []


def test_a_price_that_is_not_positive_is_invalid_and_is_not_fitted(
    decide: Decide, year, monkeypatch
) -> None:
    calls = counting_fits(monkeypatch)
    closes = closes_of(year)
    closes[year[DECISION_INDEX - 10]] = 0.0

    result = signal().compute(decide(closes, year[DECISION_INDEX]), ["ETF_EU"])

    assert result.status("ETF_EU") is SignalStatus.INVALID_INPUT
    assert math.isnan(result.value("ETF_EU"))
    assert calls == []


def test_a_flat_fund_is_usable_through_the_fallback(decide: Decide, year) -> None:
    """``OK`` says the number can be used, not that GARCH converged."""
    context = decide(dict.fromkeys(year, 100.0), year[DECISION_INDEX])

    result = signal().compute(context, ["ETF_EU"])
    _, forecast = signal().diagnose(context, "ETF_EU")

    assert result.status("ETF_EU") is SignalStatus.OK
    assert result.value("ETF_EU") == 0.0
    assert forecast is not None
    assert forecast.source is ForecastSource.EWMA_FALLBACK
    assert forecast.fallback_reason == NEAR_CONSTANT_RETURNS


def test_the_diagnosis_is_the_number_the_signal_gave(decide: Decide, year) -> None:
    context = decide(closes_of(year), year[DECISION_INDEX])

    value = signal().compute(context, ["ETF_EU"]).value("ETF_EU")
    window, forecast = signal().diagnose(context, "ETF_EU")

    assert forecast is not None
    assert forecast.annualized_volatility(252) == value
    assert window.dates[-1] == year[DECISION_INDEX]
    assert forecast.diagnostics()["forecast_source"] in ("GARCH", "EWMA_FALLBACK")
    assert forecast.diagnostics()["n_returns"] == RETURNS


def test_prices_after_the_decision_do_not_change_the_fit(decide: Decide, year) -> None:
    """The look-ahead guard, with the real estimation inside it."""
    closes = closes_of(year)
    day = year[DECISION_INDEX]
    before = signal().compute(decide(closes, day), ["ETF_EU"]).frame

    crashed = dict(closes)
    for session in year[DECISION_INDEX + 1 :]:
        crashed[session] = closes[session] * 0.5
    after = signal().compute(decide(crashed, day), ["ETF_EU"]).frame

    assert after.equals(before)


def test_an_action_known_after_the_decision_does_not_change_the_fit(
    make_market, make_bars, make_actions, make_context, evening, xpar, year
) -> None:
    closes = closes_of(year)
    day = year[DECISION_INDEX]
    bars = {"ETF_EU": make_bars("ETF_EU", xpar, closes)}
    before = signal().compute(make_context(make_market(bars), evening(day)), ["ETF_EU"]).frame

    known_later = make_actions(
        [("ETF_EU", ActionType.SPLIT, year[DECISION_INDEX - 30], 4.0, evening(year[-1]))]
    )
    after = (
        signal()
        .compute(make_context(make_market(bars, actions=known_later), evening(day)), ["ETF_EU"])
        .frame
    )

    assert after.equals(before)


def test_a_split_inside_the_window_is_not_a_shock(
    make_market, make_bars, make_actions, make_context, evening, xpar, year
) -> None:
    """Adjusted closes are continuous through a split: the convention of the reader."""
    closes = closes_of(year)
    day, ex_date = year[DECISION_INDEX], year[DECISION_INDEX - 30]
    plain = signal().compute(
        make_context(make_market({"ETF_EU": make_bars("ETF_EU", xpar, closes)}), evening(day)),
        ["ETF_EU"],
    )

    quoted = {
        session: close / 4.0 if session >= ex_date else close for session, close in closes.items()
    }
    split = make_actions(
        [("ETF_EU", ActionType.SPLIT, ex_date, 4.0, evening(year[DECISION_INDEX - 31]))]
    )
    adjusted = signal().compute(
        make_context(
            make_market({"ETF_EU": make_bars("ETF_EU", xpar, quoted)}, actions=split), evening(day)
        ),
        ["ETF_EU"],
    )

    assert adjusted.status("ETF_EU") is SignalStatus.OK
    assert adjusted.value("ETF_EU") == pytest.approx(plain.value("ETF_EU"), rel=1e-6)


def test_a_decision_gives_the_same_signal_whatever_was_computed_before(
    make_market, make_bars, make_context, evening, xpar, year
) -> None:
    """No fitted model, no warm start: the order of the calls leaves no trace."""
    market = make_market({"ETF_EU": make_bars("ETF_EU", xpar, closes_of(year))})
    first, second = year[DECISION_INDEX], year[DECISION_INDEX + 20]
    one = signal()

    alone = one.compute(make_context(market, evening(first)), ["ETF_EU"]).frame
    later = one.compute(make_context(market, evening(second)), ["ETF_EU"]).frame
    again = one.compute(make_context(market, evening(first)), ["ETF_EU"]).frame
    fresh = signal().compute(make_context(market, evening(second)), ["ETF_EU"]).frame

    assert again.equals(alone)
    assert fresh.equals(later)
    assert not later.equals(alone)


def test_the_signal_is_identified_by_everything_that_changes_its_number() -> None:
    definition = signal().definition_json()

    assert definition["type"] == "GarchVolatilitySignal"
    assert definition["unit"] == "ANNUALIZED_VOLATILITY"
    assert definition["window_mode"] == "CONSECUTIVE_SESSIONS"
    assert definition["price_basis"] == "ADJUSTED"
    assert definition["max_age_sessions"] == 0
    assert signal().window_spec().observations == RETURNS + 1
    assert signal().fingerprint() != signal(config=config(ewma_decay=0.97)).fingerprint()
    assert signal().fingerprint() != signal(max_age_sessions=1).fingerprint()
    with pytest.raises(ValueError, match="max_age_sessions"):
        signal(max_age_sessions=-1)


# --- the EWMA control --------------------------------------------------------------------


def ewma_signal(**overrides: object) -> EwmaVolatilitySignal:
    """Return the control signal on the same window as the forecast."""
    parameters: dict[str, object] = {
        "signal_id": "ewma94_vol_120r",
        "window_returns": RETURNS,
        "decay": 0.94,
        "seed_returns": 60,
        "annualization": 252,
        "price_basis": PriceBasis.ADJUSTED,
        "max_age_sessions": 0,
    }
    parameters.update(overrides)
    return EwmaVolatilitySignal(**parameters)  # type: ignore[arg-type]


def test_the_control_is_the_ewma_of_the_same_window(decide: Decide, year) -> None:
    closes = closes_of(year)
    day = year[DECISION_INDEX]
    window = [closes[session] for session in year[DECISION_INDEX - RETURNS : DECISION_INDEX + 1]]

    result = ewma_signal().compute(decide(closes, day), ["ETF_EU"])

    by_hand = math.sqrt(252.0 * reference_ewma(log_returns(window), 0.94, 60))
    assert result.status("ETF_EU") is SignalStatus.OK
    assert result.value("ETF_EU") == pytest.approx(by_hand, rel=1e-12)
    assert result.frame.loc["ETF_EU", "observations_used"] == RETURNS + 1


def test_the_control_does_not_see_the_future_either(decide: Decide, year) -> None:
    closes = closes_of(year)
    day = year[DECISION_INDEX]
    before = ewma_signal().compute(decide(closes, day), ["ETF_EU"]).frame

    moved = dict(closes)
    for session in year[DECISION_INDEX + 1 :]:
        moved[session] = closes[session] * 2.0

    assert ewma_signal().compute(decide(moved, day), ["ETF_EU"]).frame.equals(before)


def test_the_control_and_the_forecast_never_share_a_signal() -> None:
    assert ewma_signal().signal_id != signal().signal_id
    assert ewma_signal().fingerprint() != ewma_signal(decay=0.97).fingerprint()
    assert replace(ewma_signal(), seed_returns=30).definition()["seed_returns"] == 30
    with pytest.raises(ValueError, match="ewma_decay"):
        ewma_signal(decay=0.0)
    with pytest.raises(ValueError, match="seed"):
        ewma_signal(seed_returns=RETURNS)
