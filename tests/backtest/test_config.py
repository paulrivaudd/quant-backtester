"""The conditions of a run, refused where they are written down rather than in an equity curve."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from quant_backtester.backtest.config import BacktestConfig
from quant_backtester.backtest.schedule import EveryNSessions, EverySession
from quant_backtester.backtest.timetable import BacktestTimetable


def config(**overrides: object) -> BacktestConfig:
    """Build a configuration with the usual values, some of them overridden."""
    parameters: dict[str, object] = {
        "start": date(2026, 9, 1),
        "end": date(2026, 9, 14),
        "initial_cash": 100_000.0,
        "base_currency": "EUR",
        "reference_calendar": "XPAR",
        "schedule": EverySession(),
        "timetable": BacktestTimetable(),
    }
    parameters.update(overrides)
    return BacktestConfig(**parameters)  # type: ignore[arg-type]


def test_a_configuration_describes_itself_for_the_record() -> None:
    """Built-ins only, the schedule with its parameters and the timetable in full."""
    described = config(schedule=EveryNSessions(5)).definition()

    assert described == {
        "start": "2026-09-01",
        "end": "2026-09-14",
        "initial_cash": 100_000.0,
        "base_currency": "EUR",
        "reference_calendar": "XPAR",
        "schedule": {"type": "EveryNSessions", "parameters": {"n": 5}},
        "timetable": BacktestTimetable().definition(),
    }


def test_a_configuration_cannot_be_edited_afterwards() -> None:
    """What a run was made with is what its result says it was made with."""
    made = config()

    with pytest.raises(AttributeError):
        made.initial_cash = 1.0  # type: ignore[misc]


@pytest.mark.parametrize("cash", [0.0, -1.0, float("nan"), float("inf"), True, "100000"], ids=str)
def test_a_starting_cash_that_is_not_a_positive_number_is_refused(cash: object) -> None:
    """A number, not a boolean, finite, and above zero."""
    with pytest.raises(ValueError, match="initial_cash"):
        config(initial_cash=cash)


def test_a_period_running_backwards_is_refused() -> None:
    """A caller bug, not an empty range."""
    with pytest.raises(ValueError, match="after end"):
        config(start=date(2026, 9, 14), end=date(2026, 9, 1))


def test_a_period_of_one_session_is_a_period() -> None:
    """The bounds are inclusive."""
    assert config(start=date(2026, 9, 1), end=date(2026, 9, 1)).start == date(2026, 9, 1)


@pytest.mark.parametrize("bound", ["start", "end"])
def test_a_bound_carrying_an_instant_is_refused(bound: str) -> None:
    """A datetime is a date to Python, and would smuggle an instant nobody meant into a session."""
    with pytest.raises(ValueError, match=f"{bound} must be a date"):
        config(**{bound: datetime(2026, 9, 1, 12, 0)})


@pytest.mark.parametrize("currency", ["", "eur", "EURO", "€", 978])
def test_a_currency_that_is_not_an_iso_code_is_refused(currency: object) -> None:
    """Three capital letters: what every instrument of the registry is quoted in."""
    with pytest.raises(ValueError, match="ISO 4217"):
        config(base_currency=currency)


def test_a_calendar_needs_a_name() -> None:
    """Time advances on a calendar, and an unnamed one is no calendar."""
    with pytest.raises(ValueError, match="reference_calendar"):
        config(reference_calendar=" ")


def test_a_schedule_must_be_one_of_the_schedules() -> None:
    """A free-form "monthly" string is a schedule nobody can record the parameters of."""
    with pytest.raises(ValueError, match="DecisionSchedule"):
        config(schedule="monthly")


def test_a_timetable_must_be_a_timetable() -> None:
    """The three instants are declared together, not as loose times."""
    with pytest.raises(ValueError, match="BacktestTimetable"):
        config(timetable=None)
