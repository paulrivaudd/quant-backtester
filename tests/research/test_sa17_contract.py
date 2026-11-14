import tomllib
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from quant_backtester.data.calendars import TradingCalendar
from quant_backtester.data.instruments import PublicationRule
from quant_backtester.research.sa17_contract import (
    ReleaseDecision,
    load_sector_costs,
    month_end_release_decisions,
)

COSTS = Path(__file__).resolve().parents[2] / "research/SA17/costs.toml"
SECTORS = (
    "SA17_ETF_ENERGY",
    "SA17_ETF_MATERIALS",
    "SA17_ETF_INDUSTRIALS",
    "SA17_ETF_CONSUMER_DISCRETIONARY",
    "SA17_ETF_CONSUMER_STAPLES",
    "SA17_ETF_HEALTH_CARE",
    "SA17_ETF_FINANCIALS",
    "SA17_ETF_TECHNOLOGY",
    "SA17_ETF_COMMUNICATION",
    "SA17_ETF_UTILITIES",
)


def test_declared_costs_and_real_stress_all_terms():
    base = load_sector_costs(COSTS, SECTORS)
    stress = load_sector_costs(COSTS, SECTORS, multiplier=2)
    assert len(base) == 10
    assert base["SA17_ETF_TECHNOLOGY"].half_spread_rate == 0.0015
    assert len({cost.half_spread_rate for cost in base.values()}) > 1
    for name, cost in base.items():
        terms = cost.definition()
        assert all(isinstance(value, float) for value in terms.values())
        assert stress[name].definition() == pytest.approx(
            {term: 2 * value for term, value in terms.items() if isinstance(value, float)}
        )


@pytest.mark.parametrize(
    "sectors",
    [
        SECTORS[:-1],  # a traded fund without an override would cost the default
        (*SECTORS, "SA17_ETF_REAL_ESTATE"),  # an override nobody trades
        (*SECTORS[:-1], "SA17_ETF_COMMUNICATION_SERVICES"),  # a renamed key
    ],
)
def test_overrides_must_match_the_traded_sectors_exactly(sectors):
    with pytest.raises(ValueError, match="match exactly"):
        load_sector_costs(COSTS, sectors)


@pytest.mark.parametrize("multiplier", [1.5, 3.0, 0.5])
def test_only_the_preregistered_stress_is_accepted(multiplier):
    with pytest.raises(ValueError, match="preregistered stress"):
        load_sector_costs(COSTS, SECTORS, multiplier=multiplier)


ROOT = Path(__file__).resolve().parents[2]
DECLARED = PublicationRule(
    publication_time=time(23), timezone="Europe/Paris", lag_sessions=1, calendar_id="XLON"
)


def committed_calendar(name: str) -> TradingCalendar:
    """Return a committed calendar: the venues, or SA17's study calendars."""
    venue = ROOT / "market_data" / "metadata" / "calendars" / f"{name}.toml"
    study = ROOT / "research" / "SA17" / "calendars" / f"{name}.toml"
    return TradingCalendar.from_toml(venue if venue.exists() else study)


def decisions(first: date, last: date) -> tuple[ReleaseDecision, ...]:
    return month_end_release_decisions(
        committed_calendar("XNYS_XLON"),
        committed_calendar("XLON"),
        committed_calendar("XPAR"),
        DECLARED,
        time(23),
        first,
        last,
    )


@pytest.mark.parametrize(
    ("month", "last", "decided"),
    [
        # The ordinary case: released and decided on the next day, a Paris session.
        (date(2018, 7, 1), date(2018, 7, 31), date(2018, 8, 1)),
        # Released on 1 May, a London session; Paris is shut, so decided on the 2nd.
        (date(2019, 4, 1), date(2019, 4, 30), date(2019, 5, 2)),
        # Good Friday on the 29th, Easter Monday shuts London: released on 2 April.
        (date(2024, 3, 1), date(2024, 3, 28), date(2024, 4, 2)),
        # The early May bank holiday on Monday 3 May delays the release past Paris's first session.
        (date(2021, 4, 1), date(2021, 4, 30), date(2021, 5, 4)),
        # The UK's substitute New Year holiday on 3 January 2022.
        (date(2021, 12, 1), date(2021, 12, 31), date(2022, 1, 4)),
        # 31 August 2015, a UK bank holiday, is not on the grid: the month ends on the 28th.
        (date(2015, 8, 1), date(2015, 8, 28), date(2015, 9, 1)),
    ],
)
def test_hand_checked_release_decisions(month: date, last: date, decided: date) -> None:
    (only,) = decisions(month, month)
    assert only.last_observation == last
    assert only.decision == decided


def test_a_decision_never_precedes_its_release_nor_falls_in_its_own_month() -> None:
    paris = ZoneInfo("Europe/Paris")
    for item in decisions(date(2015, 8, 1), date(2026, 9, 1)):
        decided_at = datetime.combine(item.decision, time(23), tzinfo=paris)
        assert decided_at >= item.released
        assert f"{item.decision:%Y-%m}" > item.month


def test_a_later_release_never_advances_a_decision() -> None:
    """The look-ahead guard: half an hour later, every same-day decision moves a session on."""
    later = PublicationRule(
        publication_time=time(23, 30), timezone="Europe/Paris", lag_sessions=1, calendar_id="XLON"
    )
    declared = decisions(date(2018, 7, 1), date(2026, 9, 1))
    delayed = month_end_release_decisions(
        committed_calendar("XNYS_XLON"),
        committed_calendar("XLON"),
        committed_calendar("XPAR"),
        later,
        time(23),
        date(2018, 7, 1),
        date(2026, 9, 1),
    )
    paris = ZoneInfo("Europe/Paris")
    for slow, fast in zip(delayed, declared, strict=True):
        released_on = fast.released.astimezone(paris).date()
        if fast.decision == released_on:
            assert slow.decision > fast.decision
        else:
            assert slow.decision == fast.decision


def test_the_frozen_schedule_of_the_executable_run_is_the_calendars_own() -> None:
    """research/SA17/study.toml lists the 99 decisions; the calendars must give exactly them."""
    with (ROOT / "research" / "SA17" / "study.toml").open("rb") as stream:
        frozen = tomllib.load(stream)["schedule"]["decisions"]
    derived = decisions(date(2018, 7, 1), date(2026, 9, 1))
    assert [[item.month, item.last_observation, item.decision] for item in derived] == frozen
    assert len(derived) == 99


def test_a_rule_on_another_calendar_and_an_empty_range_are_refused() -> None:
    with pytest.raises(ValueError, match="counts on"):
        month_end_release_decisions(
            committed_calendar("XNYS_XLON"),
            committed_calendar("XPAR"),
            committed_calendar("XPAR"),
            DECLARED,
            time(23),
            date(2020, 1, 1),
            date(2020, 1, 1),
        )
    with pytest.raises(ValueError, match="after"):
        decisions(date(2020, 2, 1), date(2020, 1, 1))
