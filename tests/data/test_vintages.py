"""A restated series, read as it stood on the day of each decision.

US GDP for the first quarter of 2019 is 21 098.827 to a reader in January 2020
and 21 115.309 to one in June 2021. Both are true of their day, and a backtest
deciding in 2020 on the second number is deciding on information that did not
exist. These tests are about that one sentence: which of the two a decision
gets, and why.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from pathlib import Path

import pandas as pd
import pytest

from quant_backtester.data.bar_corrections import BarCorrections
from quant_backtester.data.calendars import CalendarRegistry, TradingCalendar
from quant_backtester.data.corporate_actions import ActionCorrections
from quant_backtester.data.crosscheck import CrossCheckPolicy
from quant_backtester.data.instruments import (
    AssetType,
    DataType,
    Instrument,
    InstrumentRegistry,
    PublicationRule,
    VintagePolicy,
)
from quant_backtester.data.normalizer import AlfredNormalizer
from quant_backtester.data.reader import MarketDataReader, ObservationStatus
from quant_backtester.data.repository import MarketDataRepository
from quant_backtester.data.revisions import AcceptedRevisions
from quant_backtester.data.schemas import VINTAGES_SCHEMA
from quant_backtester.data.sources.base import RawDownload, make_fetch_id
from quant_backtester.data.updater import MarketDataUpdater

FIRST_QUARTER = date(2019, 1, 1)
"""The observation everything here is about."""

JANUARY_2020 = date(2020, 1, 31)
JUNE_2021 = date(2021, 6, 30)
"""The two vintages: the first release, and the restatement."""


def gdp(policy: VintagePolicy = VintagePolicy.AS_OF_DECISION) -> Instrument:
    """Return a published series read under the given vintage policy."""
    dates = (JANUARY_2020, JUNE_2021) if policy is VintagePolicy.AS_OF_DECISION else (JANUARY_2020,)
    return Instrument(
        id="US_GDP",
        name="US gross domestic product",
        asset_type=AssetType.RATE,
        data_type=DataType.LEVEL,
        currency="NA",
        primary_source="ALFRED",
        source_symbol="GDP",
        tradable=False,
        publication_rule=PublicationRule(publication_time=time(8, 30), timezone="America/New_York"),
        first_session=date(1947, 1, 1),
        vintage_dates=dates,
        vintage_policy=policy,
    )


def available_at(day: date) -> datetime:
    """Return 8:30 New York on ``day``, as the publication rule stamps it."""
    return PublicationRule(publication_time=time(8, 30), timezone="America/New_York").available_at(
        day
    )


def archive() -> pd.DataFrame:
    """Return the two vintages of the first quarter of 2019."""
    rows = [
        (FIRST_QUARTER, JANUARY_2020, 21_098.827),
        (FIRST_QUARTER, JUNE_2021, 21_115.309),
    ]
    frame = pd.DataFrame(
        {
            "instrument_id": ["US_GDP"] * len(rows),
            "observation_date": [row[0] for row in rows],
            "vintage_date": [row[1] for row in rows],
            "value": [row[2] for row in rows],
            "available_at_utc": [available_at(row[1]) for row in rows],
            "source": ["ALFRED"] * len(rows),
            "source_fetch_id": ["20260920T210311Z"] * len(rows),
        },
        columns=list(VINTAGES_SCHEMA.names),
    )
    frame["available_at_utc"] = frame["available_at_utc"].astype("datetime64[us, UTC]")
    return frame


@pytest.fixture
def decision_calendar() -> CalendarRegistry:
    """Return a Paris calendar covering the years these vintages span.

    The shared fixture covers 2026 only, and a decision taken in 2020 has to be
    dateable on the calendar it is taken on - the reader refuses to invent a
    session outside the coverage, which is the behaviour being relied on
    everywhere else.
    """
    return CalendarRegistry(
        [
            TradingCalendar(
                calendar_id="XPAR",
                timezone="Europe/Paris",
                regular_open=time(9, 0),
                regular_close=time(17, 30),
                holidays=frozenset(),
                early_closes={},
                covered_from=date(2019, 1, 1),
                covered_until=date(2022, 12, 31),
            )
        ]
    )


@pytest.fixture
def reader(market_root: Path, decision_calendar: CalendarRegistry) -> MarketDataReader:
    """Return a reader over a store holding the two vintages."""
    repository = MarketDataRepository(market_root)
    repository.save_vintages("US_GDP", archive())
    return MarketDataReader(
        repository=repository,
        instruments=InstrumentRegistry([gdp()]),
        calendars=decision_calendar,
        reference_calendar_id="XPAR",
    )


def test_a_decision_reads_the_series_as_it_stood_that_day(reader: MarketDataReader) -> None:
    """The first release, because the restatement had not happened yet."""
    at_the_time = reader.at(datetime(2020, 6, 1, 12, 0, tzinfo=UTC))

    assert at_the_time.values(["US_GDP"]).iloc[0]["value"] == pytest.approx(21_098.827)


def test_a_later_decision_reads_the_restatement(reader: MarketDataReader) -> None:
    """And the same code, run next year, still gives the 2020 decision its number."""
    later = reader.at(datetime(2021, 9, 1, 12, 0, tzinfo=UTC))

    assert later.values(["US_GDP"]).iloc[0]["value"] == pytest.approx(21_115.309)


def test_a_revision_published_this_morning_is_invisible_to_last_night(
    reader: MarketDataReader,
) -> None:
    """The availability rule applies to the vintage as much as to the observation."""
    the_evening_before = reader.at(datetime(2021, 6, 30, 11, 0, tzinfo=UTC))

    assert the_evening_before.values(["US_GDP"]).iloc[0]["value"] == pytest.approx(21_098.827)


def test_a_decision_before_the_first_vintage_has_nothing_to_read(
    reader: MarketDataReader,
) -> None:
    """Not the earliest value it will ever have: nothing had been published.

    Serving the first vintage to a decision taken before it existed would be
    the look-ahead this whole table exists to prevent, one level deeper.
    """
    too_early = reader.at(datetime(2019, 5, 1, 12, 0, tzinfo=UTC))

    assert too_early.values(["US_GDP"]).iloc[0]["status"] is ObservationStatus.MISSING


def test_the_history_a_signal_sees_is_the_series_of_that_day(
    reader: MarketDataReader,
) -> None:
    """A window is built on the numbers the decision had, not on today's."""
    at_the_time = reader.at(datetime(2020, 6, 1, 12, 0, tzinfo=UTC))

    history = at_the_time.history("US_GDP")

    assert list(history) == [pytest.approx(21_098.827)]
    assert list(history.index) == [FIRST_QUARTER]


def test_a_pinned_series_is_not_a_point_in_time_series() -> None:
    """Two policies, two meanings, and the registry makes the difference explicit."""
    assert gdp(VintagePolicy.PINNED).vintage_date == JANUARY_2020
    assert gdp(VintagePolicy.AS_OF_DECISION).vintage_date is None


def test_a_pin_is_one_day() -> None:
    """Three vintages and a pin is an unanswered question about which."""
    with pytest.raises(ValueError, match="a pin is one day"):
        Instrument(
            id="US_GDP",
            name="US gross domestic product",
            asset_type=AssetType.RATE,
            data_type=DataType.LEVEL,
            currency="NA",
            primary_source="ALFRED",
            source_symbol="GDP",
            tradable=False,
            publication_rule=PublicationRule(
                publication_time=time(8, 30), timezone="America/New_York"
            ),
            vintage_dates=(JANUARY_2020, JUNE_2021),
            vintage_policy=VintagePolicy.PINNED,
        )


def test_a_vintage_with_no_policy_is_refused() -> None:
    """A vintage nobody says how to read is a number whose date of knowledge is unstated."""
    with pytest.raises(ValueError, match="declared together or not at all"):
        Instrument(
            id="US_GDP",
            name="US gross domestic product",
            asset_type=AssetType.RATE,
            data_type=DataType.LEVEL,
            currency="NA",
            primary_source="ALFRED",
            source_symbol="GDP",
            tradable=False,
            publication_rule=PublicationRule(
                publication_time=time(8, 30), timezone="America/New_York"
            ),
            vintage_dates=(JANUARY_2020,),
        )


def test_the_same_observation_cannot_be_stored_twice_in_one_vintage(
    market_root: Path,
) -> None:
    """Two values for one observation as of one day is a file that cannot say what was known."""
    repository = MarketDataRepository(market_root)
    doubled = pd.concat([archive().iloc[:1], archive().iloc[:1]], ignore_index=True)

    with pytest.raises(ValueError, match="one observation twice"):
        repository.save_vintages("US_GDP", doubled)


class OneExport:
    """A fake ALFRED serving one recorded export, whatever the range."""

    source_id = "ALFRED"

    def __init__(self, body: pd.DataFrame, retrieved_at: datetime) -> None:
        self.body = body
        self.retrieved_at = retrieved_at

    def available_from(self, instrument: Instrument) -> None:
        """Return ``None``: the archive serves its whole history."""
        return None

    def download(self, instrument: Instrument, start: date, end: date) -> RawDownload:
        """Return the recorded export, unfiltered."""
        return RawDownload(
            instrument_id=instrument.id,
            source=self.source_id,
            fetch_id=make_fetch_id(self.retrieved_at),
            retrieved_at_utc=self.retrieved_at,
            frame=self.body,
            request={"endpoint": "alfredgraph.csv"},
        )

    def download_corporate_actions(self, instrument: Instrument, start: date, end: date) -> None:
        """Return ``None``: a published series has no corporate actions."""
        return None


def export(**columns: list[str]) -> pd.DataFrame:
    """Build an ALFRED-shaped export, every cell a string."""
    return pd.DataFrame({"observation_date": ["2019-01-01"], **columns}, dtype=str)


def updater_over(
    market_root: Path, decision_calendar: CalendarRegistry, source: OneExport
) -> MarketDataUpdater:
    """Wire an updater onto that one export."""
    return MarketDataUpdater(
        repository=MarketDataRepository(market_root),
        instruments=InstrumentRegistry([gdp()]),
        calendars=decision_calendar,
        sources={"ALFRED": source},
        normalizers={"ALFRED": AlfredNormalizer()},
        accepted_revisions=AcceptedRevisions([]),
        action_corrections=ActionCorrections([]),
        bar_corrections=BarCorrections([]),
        cross_check_policy=CrossCheckPolicy(price_rel_tolerance=1e-6, volume_rel_tolerance=0.0),
        clock=lambda: datetime(2022, 1, 3, 12, 0, tzinfo=UTC),
    )


def test_an_ingestion_stores_one_row_per_observation_and_vintage(
    market_root: Path, decision_calendar: CalendarRegistry
) -> None:
    """The archive is a fact per day of knowledge, not a series."""
    source = OneExport(
        export(GDP_20200131=["21098.827"], GDP_20210630=["21115.309"]),
        datetime(2022, 1, 3, 12, 0, tzinfo=UTC),
    )
    updater = updater_over(market_root, decision_calendar, source)

    report = updater.download("US_GDP", FIRST_QUARTER, date(2019, 3, 31))

    assert report.valid
    stored = MarketDataRepository(market_root).load_vintages("US_GDP")
    assert list(stored["vintage_date"]) == [JANUARY_2020, JUNE_2021]
    assert list(stored["value"]) == [pytest.approx(21_098.827), pytest.approx(21_115.309)]


def test_a_vintage_a_provider_rewrote_stops_the_ingestion(
    market_root: Path, decision_calendar: CalendarRegistry
) -> None:
    """An archive of what was known on a day is a fact about the past.

    The revision policy governs a series that may legitimately be restated.
    A vintage cannot be: a pair whose value moves is a provider rewriting
    history, and merging it under a rule meant for something else would hide
    exactly the thing the archive exists to pin down.
    """
    first = OneExport(
        export(GDP_20200131=["21098.827"], GDP_20210630=["21115.309"]),
        datetime(2022, 1, 3, 12, 0, tzinfo=UTC),
    )
    updater = updater_over(market_root, decision_calendar, first)
    updater.download("US_GDP", FIRST_QUARTER, date(2019, 3, 31))

    rewritten = OneExport(
        export(GDP_20200131=["21100.000"], GDP_20210630=["21115.309"]),
        datetime(2022, 1, 4, 12, 0, tzinfo=UTC),
    )
    report = updater_over(market_root, decision_calendar, rewritten).download(
        "US_GDP", FIRST_QUARTER, date(2019, 3, 31)
    )

    assert not report.valid
    assert [issue.code for issue in report.errors] == ["VINTAGE_REWRITTEN"]
    # And the archive still says what it said.
    stored = MarketDataRepository(market_root).load_vintages("US_GDP")
    assert stored.loc[stored["vintage_date"] == JANUARY_2020, "value"].iloc[0] == pytest.approx(
        21_098.827
    )


def test_a_later_fetch_adds_a_vintage_without_touching_the_others(
    market_root: Path, decision_calendar: CalendarRegistry
) -> None:
    """The archive grows forwards: an ingestion is not a rewrite."""
    first = OneExport(
        export(GDP_20200131=["21098.827"], GDP_20210630=["21115.309"]),
        datetime(2022, 1, 3, 12, 0, tzinfo=UTC),
    )
    updater_over(market_root, decision_calendar, first).download(
        "US_GDP", FIRST_QUARTER, date(2019, 3, 31)
    )
    again = OneExport(
        export(GDP_20200131=["21098.827"], GDP_20210630=["21115.309"]),
        datetime(2022, 1, 5, 12, 0, tzinfo=UTC),
    )

    report = updater_over(market_root, decision_calendar, again).download(
        "US_GDP", FIRST_QUARTER, date(2019, 3, 31)
    )

    assert report.valid
    assert len(MarketDataRepository(market_root).load_vintages("US_GDP")) == 2


def test_a_rebuild_reproduces_the_archive_from_the_raw_alone(
    market_root: Path, decision_calendar: CalendarRegistry
) -> None:
    """The reproducibility property, applied to the vintage table too."""
    source = OneExport(
        export(GDP_20200131=["21098.827"], GDP_20210630=["21115.309"]),
        datetime(2022, 1, 3, 12, 0, tzinfo=UTC),
    )
    updater = updater_over(market_root, decision_calendar, source)
    updater.download("US_GDP", FIRST_QUARTER, date(2019, 3, 31))
    live = MarketDataRepository(market_root).load_vintages("US_GDP")

    updater.rebuild_clean("US_GDP")

    pd.testing.assert_frame_equal(MarketDataRepository(market_root).load_vintages("US_GDP"), live)
