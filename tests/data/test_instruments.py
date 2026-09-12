"""Instrument registry: availability arithmetic and registry invariants.

Everything here is offline and independent of the wall clock. The dates are not
decorative: each one sits on a boundary that a naive implementation gets wrong -
a DST transition, a fixed UTC offset, a month or year rollover.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from quant_backtester.data.instruments import PublicationRule

FRED_US10Y = PublicationRule(publication_time=time(16, 15), timezone="America/New_York")
"""FRED publishes DGS10 at 16:15 New York wall clock, for the same day."""

ECB_FX = PublicationRule(publication_time=time(16, 0), timezone="Europe/Paris")
"""ECB reference rates, 16:00 Paris wall clock, same day."""

NEXT_DAY = PublicationRule(publication_time=time(16, 15), timezone="America/New_York", lag_days=1)
"""Same release time, published the following calendar day."""


def test_availability_is_utc_aware():
    """The returned instant is timezone-aware and expressed in UTC.

    A naive datetime here would silently be read as local time by every consumer
    downstream, and the reader filters on this exact value.
    """
    available_at = ECB_FX.available_at(date(2024, 1, 8))

    assert available_at.tzinfo is not None
    assert available_at.utcoffset() == timedelta(0)


def test_same_day_publication_is_the_local_release_time():
    """16:00 Paris on 8 January 2024 is 15:00 UTC: hand-checkable, CET is UTC+1."""
    assert ECB_FX.available_at(date(2024, 1, 8)) == datetime(2024, 1, 8, 15, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("rule", "observation_date", "expected"),
    [
        # Same wall clock, two different UTC instants: the offset is not a constant.
        (FRED_US10Y, date(2024, 1, 10), datetime(2024, 1, 10, 21, 15, tzinfo=UTC)),  # EST
        (FRED_US10Y, date(2024, 3, 14), datetime(2024, 3, 14, 20, 15, tzinfo=UTC)),  # EDT
        (ECB_FX, date(2024, 1, 8), datetime(2024, 1, 8, 15, 0, tzinfo=UTC)),  # CET
        (ECB_FX, date(2024, 7, 1), datetime(2024, 7, 1, 14, 0, tzinfo=UTC)),  # CEST
    ],
)
def test_release_time_is_a_wall_clock_that_moves_with_dst(rule, observation_date, expected):
    """The release time is local, so its UTC instant shifts by an hour across DST.

    This is the test a fixed UTC offset fails, and it fails it silently: it would
    be right in winter and an hour early from March to November.
    """
    assert rule.available_at(observation_date) == expected


def test_lag_applies_to_the_date_not_to_the_instant():
    """A lag crossing a DST switch adds a calendar day, not 24 hours.

    9 March 2024 + one day is the 10th, the day the US moves to EDT. Publication
    is still at 16:15 local, so the UTC instant is 20:15 - not the 21:15 that
    adding 24 hours to the previous day's instant would give.
    """
    assert NEXT_DAY.available_at(date(2024, 3, 9)) == datetime(2024, 3, 10, 20, 15, tzinfo=UTC)


@pytest.mark.parametrize(
    ("observation_date", "expected"),
    [
        (date(2024, 2, 29), datetime(2024, 3, 1, 21, 15, tzinfo=UTC)),  # leap day to March
        (date(2024, 12, 31), datetime(2025, 1, 1, 21, 15, tzinfo=UTC)),  # year rollover
    ],
)
def test_lag_crosses_month_and_year_boundaries(observation_date, expected):
    """Date arithmetic, not string manipulation: the rollovers are handled."""
    assert NEXT_DAY.available_at(observation_date) == expected


def test_lag_days_counts_calendar_days_not_business_days():
    """A Friday observation with a one-day lag lands on the Saturday.

    Documented limitation rather than a bug: ``lag_days`` is calendar days by
    definition. A publisher releasing "the next business day" cannot be modelled
    by this field, and must not be approximated with it.
    """
    friday = date(2024, 3, 8)

    available_at = NEXT_DAY.available_at(friday)

    assert available_at.astimezone(ZoneInfo("America/New_York")).date() == date(2024, 3, 9)
    assert available_at == datetime(2024, 3, 9, 21, 15, tzinfo=UTC)


@pytest.mark.parametrize("rule", [FRED_US10Y, ECB_FX, NEXT_DAY])
@pytest.mark.parametrize(
    "observation_date", [date(2024, 1, 10), date(2024, 3, 9), date(2024, 7, 1)]
)
def test_availability_never_precedes_the_observed_day(rule, observation_date):
    """The look-ahead guard: a value describing day *d* is never public before *d* begins.

    Availability moving earlier than the day it describes is the shape of the bug
    that lets a strategy read a value it could not have had.
    """
    day_starts = datetime.combine(observation_date, time(0, 0), tzinfo=ZoneInfo(rule.timezone))

    assert rule.available_at(observation_date) >= day_starts


def test_rule_is_immutable():
    """The rule is configuration: it must not be mutated at runtime."""
    with pytest.raises(FrozenInstanceError):
        ECB_FX.publication_time = time(9, 0)  # type: ignore[misc]


@pytest.mark.skip(reason="Exercice 1.2")
def test_bar_without_calendar_is_rejected():
    """A BAR instrument with no ``calendar_id`` cannot produce an availability."""


@pytest.mark.skip(reason="Exercice 1.2")
def test_level_without_publication_rule_is_rejected():
    """A LEVEL instrument with no ``publication_rule`` cannot produce one either."""


@pytest.mark.skip(reason="Exercice 1.2")
def test_instrument_carrying_the_other_kind_field_is_rejected():
    """A BAR with a ``publication_rule``, or a LEVEL with a ``calendar_id``, is a config error."""


@pytest.mark.skip(reason="Exercice 1.3")
def test_is_listed_bounds_are_inclusive_and_open_when_none():
    """``first_session`` and ``last_session`` are inclusive; ``None`` means unbounded."""


@pytest.mark.skip(reason="Exercice 1.4")
def test_duplicate_ids_are_a_configuration_error():
    """Two instruments sharing an id must fail loudly at registry construction."""


@pytest.mark.skip(reason="Exercice 1.5")
def test_from_toml_reads_dates_enums_and_publication_rules():
    """The committed TOML round-trips into instruments, enums and rules included."""


@pytest.mark.skip(reason="Exercice 1.5")
def test_from_toml_rejects_an_unknown_key():
    """A typo in the config fails loudly rather than being silently ignored."""


@pytest.mark.skip(reason="Exercice 1.6")
def test_get_raises_keyerror_on_unknown_id():
    """An unknown id is a ``KeyError``, never a ``None`` travelling downstream."""


@pytest.mark.skip(reason="Exercice 1.7")
def test_list_all_is_ordered_by_id():
    """A stable order keeps file writes, and therefore diffs, reproducible."""


@pytest.mark.skip(reason="Exercice 1.8")
def test_list_tradable_excludes_signal_only_instruments():
    """VIX and US10Y are readable but never tradable."""


@pytest.mark.skip(reason="Exercice 1.9")
def test_list_by_source_groups_downloads():
    """Instruments are grouped by source so downloads can be batched per provider."""


@pytest.mark.skip(reason="Exercice 1.10")
def test_registry_supports_len_iteration_and_contains():
    """Iteration follows id order, like :meth:`list_all`."""
