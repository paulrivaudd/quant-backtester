"""The conventions, and why they are asked for rather than assumed."""

from __future__ import annotations

import pytest

from quant_backtester.analytics.config import AnalyticsConfig


def test_a_convention_is_two_numbers_and_a_floor() -> None:
    """Both figures that change a statistic are declared; the floor only hides one."""
    config = AnalyticsConfig(sessions_per_year=252, risk_free_rate=0.02)

    assert config.sessions_per_year == 252
    assert config.risk_free_rate == 0.02
    assert config.minimum_sessions == 60


def test_the_risk_free_rate_comes_down_the_way_a_return_goes_up() -> None:
    """Compounded to a session, not divided by 252.

    Divided, the rate subtracted over a year would not be the rate that was
    declared, and every Sharpe ratio would carry the difference.
    """
    config = AnalyticsConfig(sessions_per_year=252, risk_free_rate=0.05)

    compounded = (1.0 + config.risk_free_per_session) ** 252 - 1.0

    assert compounded == pytest.approx(0.05)


@pytest.mark.parametrize("sessions", [0, 1, -252, True, 252.0, "252"])
def test_a_year_that_is_not_a_count_of_sessions_is_refused(sessions: object) -> None:
    """The figure scales every volatility in the report; it cannot be a guess."""
    with pytest.raises(ValueError, match="sessions_per_year"):
        AnalyticsConfig(sessions_per_year=sessions, risk_free_rate=0.0)  # type: ignore[arg-type]


@pytest.mark.parametrize("rate", [-1.0, -2.0, float("nan"), float("inf")])
def test_a_rate_that_cannot_be_one_is_refused(rate: float) -> None:
    """Losing everything and more is not a risk-free rate."""
    with pytest.raises(ValueError, match="risk_free_rate"):
        AnalyticsConfig(sessions_per_year=252, risk_free_rate=rate)


def test_a_rate_that_is_not_a_number_is_refused() -> None:
    """``"2%"`` is a string, and a percentage besides."""
    with pytest.raises(ValueError, match="risk_free_rate must be a number"):
        AnalyticsConfig(sessions_per_year=252, risk_free_rate="2%")  # type: ignore[arg-type]


def test_the_floor_is_a_count_of_sessions_too() -> None:
    """A floor of one session would let a fortnight be compounded into a year."""
    with pytest.raises(ValueError, match="minimum_sessions"):
        AnalyticsConfig(sessions_per_year=252, risk_free_rate=0.0, minimum_sessions=1)


def test_the_definition_holds_every_field_of_the_convention() -> None:
    config = AnalyticsConfig(sessions_per_year=252, risk_free_rate=0.02, minimum_sessions=20)

    assert config.definition() == {
        "sessions_per_year": 252,
        "risk_free_rate": 0.02,
        "minimum_sessions": 20,
    }


def test_two_conventions_that_report_differently_are_recorded_differently() -> None:
    """Audit A13: a threshold that decides whether a Sharpe exists is part of the run."""
    short = AnalyticsConfig(sessions_per_year=252, risk_free_rate=0.0, minimum_sessions=2)
    long = AnalyticsConfig(sessions_per_year=252, risk_free_rate=0.0, minimum_sessions=60)

    assert short.definition() != long.definition()
