"""Calendar behaviour on the dates that break naive implementations."""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="Exercice 2.4")
def test_regular_session_close_is_utc_aware(xnys):
    """A regular NYSE session closes at 16:00 ET, expressed in UTC."""


@pytest.mark.skip(reason="Exercice 2.4")
def test_half_day_closes_early(xnys):
    """27 November 2026 closes at 13:00 ET, not 16:00."""


@pytest.mark.skip(reason="Exercice 2.4")
def test_us_and_eu_dst_transitions_are_misaligned(xnys, xpar):
    """Between the US and EU DST switches, the close gap is not the June one.

    The US moves on the second Sunday of March, Europe on the last. For those
    two weeks the NYSE close lands an hour earlier in Paris wall-clock terms
    than it does in June. A calendar that stores a fixed UTC offset gets this
    wrong, and it is silent when it does.
    """


@pytest.mark.skip(reason="Exercice 2.3")
def test_holiday_is_not_a_session(xpar):
    """A venue holiday yields no session, even on a weekday."""


@pytest.mark.skip(reason="Exercice 2.6")
def test_next_session_skips_weekend_and_holiday(xnys):
    """The session after a Friday before a Monday holiday is the Tuesday."""


@pytest.mark.skip(reason="Exercice 2.8")
def test_staleness_is_counted_in_sessions_not_days(xnys):
    """Monday's value is one session old on Tuesday, not three days old."""
