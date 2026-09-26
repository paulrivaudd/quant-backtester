"""Ingestion: the pipeline, the revision policy and the reproducibility property.

The sources and normalizers here are fakes: the updater's contract is with the
two protocols, not with Yahoo. What is real is everything it decides - what gets
archived, what gets promoted, what is refused, and what a replay of the archive
rebuilds.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import BinaryIO

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from quant_backtester.data.bar_corrections import BarCorrection, BarCorrections, BarDefect
from quant_backtester.data.calendars import CalendarRegistry, TradingCalendar
from quant_backtester.data.corporate_actions import ActionCorrection, ActionCorrections
from quant_backtester.data.crosscheck import CrossCheckPolicy
from quant_backtester.data.instruments import (
    AssetType,
    CheckSource,
    DataType,
    Instrument,
    InstrumentRegistry,
    PublicationRule,
)
from quant_backtester.data.normalizer import (
    NormalizedData,
    Normalizer,
    YahooNormalizer,
    bar_availability,
)
from quant_backtester.data.reader import MarketDataReader, ObservationStatus
from quant_backtester.data.repository import MarketDataRepository, write_parquet_atomic
from quant_backtester.data.revisions import AcceptedRevision, AcceptedRevisions
from quant_backtester.data.schemas import (
    BARS_SCHEMA,
    CORPORATE_ACTIONS_SCHEMA,
    LEVELS_SCHEMA,
    ActionType,
    CheckStatus,
)
from quant_backtester.data.sources.base import (
    ProviderRangeUnavailable,
    ProviderResponseError,
    ProviderUnavailable,
    RawDownload,
    make_fetch_id,
)
from quant_backtester.data.updater import MarketDataUpdater, safe_end_date

FIRST_TICK = datetime(2026, 3, 13, 21, 0, tzinfo=UTC)
"""Instant of the first fetch of a test. Every later one is a second apart."""

RATE_RULE = PublicationRule(publication_time=time(16, 15), timezone="UTC")
"""Trivial release rule: 16:15 UTC on the observation date."""

MONDAY = date(2026, 3, 9)
TUESDAY = date(2026, 3, 10)
WEDNESDAY = date(2026, 3, 11)
THURSDAY = date(2026, 3, 12)
FRIDAY = date(2026, 3, 13)
SESSIONS = (MONDAY, TUESDAY, WEDNESDAY, THURSDAY, FRIDAY)
"""One ordinary week, open in Paris and in New York alike."""

POLICY = CrossCheckPolicy(price_rel_tolerance=1e-6, volume_rel_tolerance=0.0)
"""The committed tolerances, restated here so a change to the file is visible."""


class Clock:
    """A clock that advances one second per read, so fetch ids never collide."""

    def __init__(self, start: datetime = FIRST_TICK) -> None:
        self.now = start

    def __call__(self) -> datetime:
        """Return the current instant and move on by one second."""
        instant = self.now
        self.now = instant + timedelta(seconds=1)
        return instant


def raw_bars(rows: Sequence[tuple[date, float]], *, volume: float = 1_000.0) -> pd.DataFrame:
    """Build a provider-shaped bars frame from ``(date, close)`` pairs.

    The high and low sit one unit either side of the close, so a test that moves
    one field by a cent produces a revision rather than an OHLC_ORDER error.
    """
    return pd.DataFrame(
        [
            {
                "date": session_date,
                "open": close,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": volume,
            }
            for session_date, close in rows
        ]
    )


def raw_levels(rows: Sequence[tuple[date, float]]) -> pd.DataFrame:
    """Build a provider-shaped levels frame from ``(date, value)`` pairs."""
    return pd.DataFrame([{"date": day, "value": value} for day, value in rows])


def raw_actions(rows: Sequence[tuple[date, ActionType, float]]) -> pd.DataFrame:
    """Build a provider-shaped actions frame from ``(ex_date, type, value)`` triples."""
    return pd.DataFrame(
        [
            {"ex_date": ex_date, "action_type": action_type.value, "value": value}
            for ex_date, action_type, value in rows
        ],
        columns=["ex_date", "action_type", "value"],
    )


class FakeSource:
    """A provider serving the rows it was handed, restricted to the asked range.

    Attributes
    ----------
    rows : dict[str, pd.DataFrame]
        Bars or levels per instrument id; rewrite one to simulate a provider
        changing its mind.
    actions : dict[str, pd.DataFrame]
        Corporate actions per instrument id. An instrument absent from it has no
        action feed, like an index.
    calls : list[tuple[str, date, date]]
        Every range asked of it, in order.
    window_start : date | None
        Earliest date it declares it can serve; ``None`` for a full history.
    """

    def __init__(
        self,
        source_id: str,
        clock: Callable[[], datetime],
        rows: Mapping[str, pd.DataFrame] | None = None,
        actions: Mapping[str, pd.DataFrame] | None = None,
        window_start: date | None = None,
    ) -> None:
        self.source_id = source_id
        self._clock = clock
        self.rows: dict[str, pd.DataFrame] = dict(rows or {})
        self.actions: dict[str, pd.DataFrame] = dict(actions or {})
        self.calls: list[tuple[str, date, date]] = []
        self.window_start = window_start

    def available_from(self, instrument: Instrument) -> date | None:
        """Return the earliest date this provider declares it holds."""
        return self.window_start

    def download(self, instrument: Instrument, start: date, end: date) -> RawDownload:
        """Return the rows of ``instrument`` inside ``[start, end]``."""
        self.calls.append((instrument.id, start, end))
        frame = self.rows.get(instrument.id, pd.DataFrame(columns=["date"]))
        served = frame.loc[(frame["date"] >= start) & (frame["date"] <= end)]
        retrieved = self._clock()
        return RawDownload(
            instrument_id=instrument.id,
            source=self.source_id,
            fetch_id=make_fetch_id(retrieved),
            retrieved_at_utc=retrieved,
            frame=served.reset_index(drop=True),
            request={
                "symbol": instrument.source_symbol,
                "endpoint": "history",
                "start": start.isoformat(),
                "end_inclusive": end.isoformat(),
            },
        )

    def download_corporate_actions(
        self, instrument: Instrument, start: date, end: date
    ) -> RawDownload | None:
        """Return the actions of ``instrument`` inside ``[start, end]``, if it has a feed."""
        if instrument.id not in self.actions:
            return None
        frame = self.actions[instrument.id]
        served = frame.loc[(frame["ex_date"] >= start) & (frame["ex_date"] <= end)]
        retrieved = self._clock()
        return RawDownload(
            instrument_id=instrument.id,
            source=self.source_id,
            fetch_id=f"{make_fetch_id(retrieved)}-actions",
            retrieved_at_utc=retrieved,
            frame=served.reset_index(drop=True),
            request={
                "symbol": instrument.source_symbol,
                "endpoint": "actions",
                "start": start.isoformat(),
                "end_inclusive": end.isoformat(),
            },
        )


class YahooShapedSource(FakeSource):
    """A provider whose frames carry Yahoo's own columns and index.

    The fakes above speak the canonical shape, which is enough to exercise what
    the updater decides. A test about what the *normalizer* refuses needs the
    real one, and the real one only reads Yahoo's shape.
    """

    def download(self, instrument: Instrument, start: date, end: date) -> RawDownload:
        """Return the asked range as a raw Yahoo ``history`` frame."""
        download = super().download(instrument, start, end)
        frame = download.frame
        shaped = pd.DataFrame(
            {
                "Open": frame["open"].to_numpy(dtype="float64"),
                "High": frame["high"].to_numpy(dtype="float64"),
                "Low": frame["low"].to_numpy(dtype="float64"),
                "Close": frame["close"].to_numpy(dtype="float64"),
                "Volume": frame["volume"].to_numpy(dtype="float64"),
            },
            index=pd.DatetimeIndex([pd.Timestamp(day) for day in frame["date"]], name="Date"),
        )
        return replace(download, frame=shaped)


class FakeNormalizer:
    """Turn the fake provider's frames into canonical ones.

    It does what a real normalizer does and nothing more: rename the date
    column, stamp availability from the calendar, and copy the lineage of the
    fetch onto every row.
    """

    def __init__(self, source_id: str) -> None:
        self.source_id = source_id

    def normalize(
        self,
        instrument: Instrument,
        download: RawDownload,
        calendar: TradingCalendar | None = None,
    ) -> NormalizedData:
        """Convert one response to canonical frames."""
        if download.request.get("endpoint") == "actions":
            return NormalizedData(corporate_actions=self._actions(instrument, download, calendar))
        if instrument.data_type is DataType.BAR:
            return NormalizedData(bars=self._bars(instrument, download, calendar))
        return NormalizedData(levels=self._levels(instrument, download))

    def _bars(
        self, instrument: Instrument, download: RawDownload, calendar: TradingCalendar | None
    ) -> pd.DataFrame:
        if calendar is None:
            raise ValueError(f"{instrument.id} is a BAR instrument and needs a calendar")
        rows = []
        for record in download.frame.to_dict("records"):
            session_date = record["date"]
            open_available, close_available = bar_availability(session_date, calendar)
            rows.append(
                {
                    "instrument_id": instrument.id,
                    "session_date": session_date,
                    "open": float(record["open"]),
                    "high": float(record["high"]),
                    "low": float(record["low"]),
                    "close": float(record["close"]),
                    "volume": float(record["volume"]),
                    "open_available_at_utc": pd.Timestamp(open_available),
                    "close_available_at_utc": pd.Timestamp(close_available),
                    "source": download.source,
                    "source_fetch_id": download.fetch_id,
                }
            )
        return _typed(rows, BARS_SCHEMA, ("open_available_at_utc", "close_available_at_utc"))

    def _levels(self, instrument: Instrument, download: RawDownload) -> pd.DataFrame:
        rule = instrument.publication_rule
        if rule is None:
            raise ValueError(f"{instrument.id} is a LEVEL instrument and needs a publication rule")
        rows = [
            {
                "instrument_id": instrument.id,
                "observation_date": record["date"],
                "value": float(record["value"]),
                "available_at_utc": pd.Timestamp(rule.available_at(record["date"])),
                "source": download.source,
                "source_fetch_id": download.fetch_id,
            }
            for record in download.frame.to_dict("records")
        ]
        return _typed(rows, LEVELS_SCHEMA, ("available_at_utc",))

    def _actions(
        self, instrument: Instrument, download: RawDownload, calendar: TradingCalendar | None
    ) -> pd.DataFrame:
        if calendar is None:
            raise ValueError(f"{instrument.id} needs a calendar to date its actions")
        rows = []
        for record in download.frame.to_dict("records"):
            ex_date = record["ex_date"]
            _, close_available = bar_availability(ex_date, calendar)
            rows.append(
                {
                    "instrument_id": instrument.id,
                    "action_type": record["action_type"],
                    "ex_date": ex_date,
                    "value": float(record["value"]),
                    "available_at_utc": pd.Timestamp(close_available),
                    "source": download.source,
                    "source_fetch_id": download.fetch_id,
                }
            )
        return _typed(rows, CORPORATE_ACTIONS_SCHEMA, ("available_at_utc",))


def _typed(
    rows: list[dict[str, object]], schema: pa.Schema, instants: Sequence[str]
) -> pd.DataFrame:
    """Return the rows as a frame with the schema's columns and UTC instants."""
    if not rows:
        return schema.empty_table().to_pandas()
    frame = pd.DataFrame(rows, columns=list(schema.names))
    for column in instants:
        frame[column] = frame[column].astype("datetime64[us, UTC]")
    return frame


@pytest.fixture
def clock() -> Clock:
    """Return the advancing clock shared by the sources and the updater."""
    return Clock()


@pytest.fixture
def calendars(xnys: TradingCalendar, xpar: TradingCalendar) -> CalendarRegistry:
    """Return the two venue calendars."""
    return CalendarRegistry([xnys, xpar])


@pytest.fixture
def instruments() -> InstrumentRegistry:
    """Return a single-source ETF, a two-source ETF, an index and a rate."""
    return InstrumentRegistry(
        [
            Instrument(
                id="ETF_EU",
                name="Paris ETF",
                asset_type=AssetType.ETF,
                data_type=DataType.BAR,
                currency="EUR",
                primary_source="YAHOO",
                source_symbol="CW8.PA",
                tradable=True,
                calendar_id="XPAR",
                first_session=MONDAY,
            ),
            Instrument(
                id="IDX_US",
                name="US index",
                asset_type=AssetType.INDEX,
                data_type=DataType.BAR,
                currency="USD",
                primary_source="YAHOO",
                source_symbol="^GSPC",
                tradable=False,
                calendar_id="XNYS",
                first_session=MONDAY,
            ),
            Instrument(
                id="RATE_US",
                name="US rate",
                asset_type=AssetType.RATE,
                data_type=DataType.LEVEL,
                currency="NA",
                primary_source="FRED",
                source_symbol="DGS10",
                tradable=False,
                publication_rule=RATE_RULE,
                first_session=MONDAY,
            ),
        ]
    )


@pytest.fixture
def repository(market_root: Path) -> MarketDataRepository:
    """Return an empty repository on a temporary tree."""
    return MarketDataRepository(market_root)


@pytest.fixture
def yahoo(clock: Clock) -> FakeSource:
    """Return the primary source, serving one flat week for every instrument."""
    return FakeSource(
        "YAHOO",
        clock,
        rows={
            "ETF_EU": raw_bars([(day, 100.0 + index) for index, day in enumerate(SESSIONS)]),
            "IDX_US": raw_bars([(day, 5_000.0 + index) for index, day in enumerate(SESSIONS)]),
        },
        actions={"ETF_EU": raw_actions([(WEDNESDAY, ActionType.DIVIDEND, 0.5)])},
    )


@pytest.fixture
def fred(clock: Clock) -> FakeSource:
    """Return the level source."""
    return FakeSource(
        "FRED",
        clock,
        rows={
            "RATE_US": raw_levels([(day, 4.0 + index / 10) for index, day in enumerate(SESSIONS)])
        },
    )


def build_updater(
    repository: MarketDataRepository,
    instruments: InstrumentRegistry,
    calendars: CalendarRegistry,
    sources: Mapping[str, FakeSource],
    clock: Clock,
    accepted: AcceptedRevisions | None = None,
    corrections: ActionCorrections | None = None,
    bar_corrections: BarCorrections | None = None,
    overlap_sessions: int = 5,
    normalizers: Mapping[str, Normalizer] | None = None,
) -> MarketDataUpdater:
    """Wire an updater onto the fakes.

    ``normalizers`` defaults to the fakes; a test that needs the real refusal
    rules passes the production normalizer instead.
    """
    return MarketDataUpdater(
        repository=repository,
        instruments=instruments,
        calendars=calendars,
        sources=dict(sources),
        normalizers=dict(normalizers)
        if normalizers is not None
        else {source_id: FakeNormalizer(source_id) for source_id in sources},
        accepted_revisions=accepted or AcceptedRevisions([]),
        action_corrections=corrections or ActionCorrections([]),
        bar_corrections=bar_corrections or BarCorrections([]),
        cross_check_policy=POLICY,
        overlap_sessions=overlap_sessions,
        clock=clock,
    )


@pytest.fixture
def updater(
    repository: MarketDataRepository,
    instruments: InstrumentRegistry,
    calendars: CalendarRegistry,
    yahoo: FakeSource,
    fred: FakeSource,
    clock: Clock,
) -> MarketDataUpdater:
    """Return an updater over the two fake sources."""
    return build_updater(repository, instruments, calendars, {"YAHOO": yahoo, "FRED": fred}, clock)


def codes(report) -> list[str]:
    """Return the codes of a report's issues, in order."""
    return [issue.code for issue in report.issues]


# ---------------------------------------------------------------------------
# Exercice 9.1 - construction
# ---------------------------------------------------------------------------


def test_a_negative_overlap_is_rejected(
    repository: MarketDataRepository,
    instruments: InstrumentRegistry,
    calendars: CalendarRegistry,
    clock: Clock,
) -> None:
    """Re-fetching a negative number of sessions is a caller bug."""
    with pytest.raises(ValueError, match="overlap_sessions"):
        build_updater(repository, instruments, calendars, {}, clock, overlap_sessions=-1)


# ---------------------------------------------------------------------------
# Exercice 9.2 - download
# ---------------------------------------------------------------------------


def test_download_archives_raw_then_promotes(
    updater: MarketDataUpdater, repository: MarketDataRepository, yahoo: FakeSource
) -> None:
    """The happy path: raw archived, clean written, checked series written."""
    report = updater.download("ETF_EU", MONDAY, FRIDAY)
    assert report.valid

    fetches = repository.list_raw_fetches("ETF_EU", "YAHOO")
    assert len(fetches) == 2  # the bars fetch and the actions fetch

    bars = repository.load_bars("ETF_EU")
    assert list(bars["session_date"]) == list(SESSIONS)
    assert list(bars["close"]) == [100.0, 101.0, 102.0, 103.0, 104.0]

    checked = repository.load_checked_bars("ETF_EU")
    assert list(checked["session_date"]) == list(SESSIONS)
    assert set(checked["check_status"]) == {CheckStatus.SINGLE_SOURCE.value}

    actions = repository.load_corporate_actions("ETF_EU")
    assert list(actions["ex_date"]) == [WEDNESDAY]


def test_download_of_a_level_writes_the_levels_table(
    updater: MarketDataUpdater, repository: MarketDataRepository
) -> None:
    """A published series takes the same path, without a calendar."""
    report = updater.download("RATE_US", MONDAY, FRIDAY)
    assert report.valid
    levels = repository.load_levels("RATE_US")
    assert list(levels["observation_date"]) == list(SESSIONS)
    assert repository.load_bars("RATE_US").empty


def test_invalid_frame_is_archived_raw_but_not_promoted(
    updater: MarketDataUpdater, repository: MarketDataRepository, yahoo: FakeSource
) -> None:
    """A failed validation keeps the raw snapshot and leaves clean untouched."""
    broken = raw_bars([(day, 100.0) for day in SESSIONS])
    broken.loc[2, "low"] = 500.0  # low above high: OHLC_ORDER
    yahoo.rows["ETF_EU"] = broken

    report = updater.download("ETF_EU", MONDAY, FRIDAY)

    assert not report.valid
    assert "OHLC_ORDER" in codes(report)
    assert repository.list_raw_fetches("ETF_EU", "YAHOO")
    assert repository.load_bars("ETF_EU").empty
    assert repository.load_checked_bars("ETF_EU").empty
    log = pq.read_table(repository.root / "validation" / "validation_log.parquet").to_pandas()
    assert "OHLC_ORDER" in set(log["code"])


def test_download_refuses_an_inverted_range(updater: MarketDataUpdater) -> None:
    """An inverted range is a caller bug, not an empty fetch."""
    with pytest.raises(ValueError, match="is after end"):
        updater.download("ETF_EU", FRIDAY, MONDAY)


def test_two_sources_that_agree_are_confirmed(
    repository: MarketDataRepository,
    instruments: InstrumentRegistry,
    calendars: CalendarRegistry,
    clock: Clock,
) -> None:
    """A check source that matches turns SINGLE_SOURCE into CONFIRMED."""
    checked_instrument = Instrument(
        id="ETF_EU",
        name="Paris ETF",
        asset_type=AssetType.ETF,
        data_type=DataType.BAR,
        currency="EUR",
        primary_source="YAHOO",
        source_symbol="CW8.PA",
        tradable=True,
        calendar_id="XPAR",
        first_session=MONDAY,
        check_sources=(
            __import__("quant_backtester.data.instruments", fromlist=["CheckSource"]).CheckSource(
                source="EURONEXT", source_symbol="LU-XPAR"
            ),
        ),
    )
    registry = InstrumentRegistry([checked_instrument])
    week = raw_bars([(day, 100.0 + index) for index, day in enumerate(SESSIONS)])
    sources = {
        "YAHOO": FakeSource("YAHOO", clock, rows={"ETF_EU": week}),
        "EURONEXT": FakeSource("EURONEXT", clock, rows={"ETF_EU": week.copy()}),
    }
    updater = build_updater(repository, registry, calendars, sources, clock)

    report = updater.download("ETF_EU", MONDAY, FRIDAY)

    assert report.valid
    checked = repository.load_checked_bars("ETF_EU")
    assert set(checked["check_status"]) == {CheckStatus.CONFIRMED.value}
    assert set(checked["checked_sources"]) == {"EURONEXT,YAHOO"}
    # The stored bars stay the reference source's.
    assert set(repository.load_bars("ETF_EU")["source"]) == {"YAHOO"}


def test_two_sources_that_disagree_are_a_conflict(
    repository: MarketDataRepository,
    calendars: CalendarRegistry,
    clock: Clock,
) -> None:
    """One session out of tolerance is marked, and the others are not."""
    registry = InstrumentRegistry(
        [
            Instrument(
                id="ETF_EU",
                name="Paris ETF",
                asset_type=AssetType.ETF,
                data_type=DataType.BAR,
                currency="EUR",
                primary_source="YAHOO",
                source_symbol="CW8.PA",
                tradable=True,
                calendar_id="XPAR",
                first_session=MONDAY,
                check_sources=(CheckSource(source="EURONEXT", source_symbol="LU-XPAR"),),
            )
        ]
    )
    week = raw_bars([(day, 100.0 + index) for index, day in enumerate(SESSIONS)])
    other = week.copy()
    other.loc[2, ["open", "high", "low", "close"]] = 90.0
    sources = {
        "YAHOO": FakeSource("YAHOO", clock, rows={"ETF_EU": week}),
        "EURONEXT": FakeSource("EURONEXT", clock, rows={"ETF_EU": other}),
    }
    updater = build_updater(repository, registry, calendars, sources, clock)

    updater.download("ETF_EU", MONDAY, FRIDAY)

    checked = repository.load_checked_bars("ETF_EU")
    verdicts = dict(zip(checked["session_date"], checked["check_status"], strict=True))
    assert verdicts[WEDNESDAY] == CheckStatus.CONFLICT.value
    assert verdicts[TUESDAY] == CheckStatus.CONFIRMED.value


# ---------------------------------------------------------------------------
# Exercice 9.3 - update and the revision policy
# ---------------------------------------------------------------------------


def test_update_refetches_the_overlap_only(updater: MarketDataUpdater, yahoo: FakeSource) -> None:
    """The second call starts `overlap_sessions` stored dates back, not at the beginning."""
    updater.download("ETF_EU", MONDAY, WEDNESDAY)
    yahoo.calls.clear()

    updater.update("ETF_EU")

    instrument_id, start, _ = yahoo.calls[0]
    assert instrument_id == "ETF_EU"
    # Three sessions stored, an overlap of five: back to the first of them.
    assert start == MONDAY


def test_update_of_an_empty_store_starts_at_the_first_session(
    updater: MarketDataUpdater, yahoo: FakeSource, repository: MarketDataRepository
) -> None:
    """With nothing stored, the instrument's declared first session is the start."""
    updater.update("ETF_EU")
    assert yahoo.calls[0][1] == MONDAY
    assert list(repository.load_bars("ETF_EU")["session_date"]) == list(SESSIONS)


def test_new_observations_are_not_reported_as_revisions(
    updater: MarketDataUpdater, repository: MarketDataRepository, yahoo: FakeSource
) -> None:
    """A date present only in the incoming frame is new data, not a revision."""
    updater.download("ETF_EU", MONDAY, WEDNESDAY)
    report = updater.update("ETF_EU")

    assert list(repository.load_bars("ETF_EU")["session_date"]) == list(SESSIONS)
    assert repository.load_revisions("ETF_EU").empty
    assert "VALUE_REVISED" not in codes(report)


def test_unaccepted_revision_leaves_history_unchanged(
    updater: MarketDataUpdater, repository: MarketDataRepository, yahoo: FakeSource
) -> None:
    """A provider changing a stored value is logged and ignored by default.

    The same backtest must not print a different number three weeks later
    because Yahoo adjusted a past close by a cent.
    """
    updater.download("ETF_EU", MONDAY, FRIDAY)
    moved = yahoo.rows["ETF_EU"].copy()
    moved.loc[1, "close"] = 101.01
    yahoo.rows["ETF_EU"] = moved

    report = updater.update("ETF_EU")

    stored = repository.load_bars("ETF_EU")
    assert dict(zip(stored["session_date"], stored["close"], strict=True))[TUESDAY] == 101.0
    revisions = repository.load_revisions("ETF_EU")
    assert list(revisions["field"]) == ["close"]
    assert list(revisions["old_value"]) == [101.0]
    assert list(revisions["new_value"]) == [101.01]
    assert "VALUE_REVISED" in codes(report)
    assert "kept as stored" in report.issues[codes(report).index("VALUE_REVISED")].message


def test_accepted_revision_is_applied(
    repository: MarketDataRepository,
    instruments: InstrumentRegistry,
    calendars: CalendarRegistry,
    yahoo: FakeSource,
    fred: FakeSource,
    clock: Clock,
) -> None:
    """A revision listed in accepted_revisions.toml does get applied."""
    accepted = AcceptedRevisions(
        [
            AcceptedRevision(
                instrument_id="ETF_EU",
                source="YAHOO",
                table="bars",
                observation_date=TUESDAY,
                field="close",
                old_value=101.0,
                new_value=101.01,
                reason="Provider confirmed the Tuesday close was mispriced",
            )
        ]
    )
    updater = build_updater(
        repository, instruments, calendars, {"YAHOO": yahoo, "FRED": fred}, clock, accepted
    )
    updater.download("ETF_EU", MONDAY, FRIDAY)
    first_fetch = repository.load_bars("ETF_EU")["source_fetch_id"].iloc[1]
    moved = yahoo.rows["ETF_EU"].copy()
    moved.loc[1, "close"] = 101.01
    yahoo.rows["ETF_EU"] = moved

    updater.update("ETF_EU")

    stored = repository.load_bars("ETF_EU")
    row = stored.loc[stored["session_date"] == TUESDAY].iloc[0]
    assert row["close"] == 101.01
    # The row now answers to the fetch that moved it.
    assert row["source_fetch_id"] != first_fetch
    # And the unreviewed open of the same day did not travel with it.
    assert row["open"] == 101.0


def test_an_accepted_field_that_breaks_the_merged_bar_refuses_the_whole_promotion(
    repository: MarketDataRepository,
    instruments: InstrumentRegistry,
    calendars: CalendarRegistry,
    yahoo: FakeSource,
    fred: FakeSource,
    clock: Clock,
) -> None:
    """Two valid bars, merged field by field, are not necessarily a valid bar.

    Tuesday is stored at 101 / 102 / 100 / 101 and refetched at 110 / 111 /
    109 / 110, both valid. Only the open was reviewed into the policy, so the
    merge would store an open of 110 above a high of 102 - a bar no source
    ever served. The promotion is refused and nothing it wrote survives.
    """
    accepted = AcceptedRevisions(
        [
            AcceptedRevision(
                instrument_id="ETF_EU",
                source="YAHOO",
                table="bars",
                observation_date=TUESDAY,
                field="open",
                old_value=101.0,
                new_value=110.0,
                reason="synthetic: only the open was reviewed",
            )
        ]
    )
    updater = build_updater(
        repository, instruments, calendars, {"YAHOO": yahoo, "FRED": fred}, clock, accepted
    )
    updater.download("ETF_EU", MONDAY, FRIDAY)
    bars_before = repository.load_bars("ETF_EU")
    checked_before = repository.load_checked_bars("ETF_EU")
    applied_before = repository.load_applied_fetches("ETF_EU")
    moved = yahoo.rows["ETF_EU"].copy()
    moved.loc[1, ["open", "high", "low", "close"]] = [110.0, 111.0, 109.0, 110.0]
    yahoo.rows["ETF_EU"] = moved

    report = updater.update("ETF_EU")

    assert not report.valid
    refused = [issue for issue in report.errors if issue.code == "MERGED_BAR_INVALID"]
    assert [issue.observation_date for issue in refused] == [TUESDAY]
    assert refused[0].context["rules"] == ["OHLC_ORDER"]
    assert "VALUE_REVISED" in codes(report)
    pd.testing.assert_frame_equal(repository.load_bars("ETF_EU"), bars_before)
    pd.testing.assert_frame_equal(repository.load_checked_bars("ETF_EU"), checked_before)
    assert repository.load_applied_fetches("ETF_EU") == applied_before
    logged = pd.read_parquet(repository.root / "validation" / "validation_log.parquet")
    assert "MERGED_BAR_INVALID" in set(logged["code"])


def test_constant_factor_shift_triggers_a_full_refetch(
    updater: MarketDataUpdater, repository: MarketDataRepository, yahoo: FakeSource
) -> None:
    """A whole-series rebasing is not a revision and must not be merged partially.

    If the overlap differs from the stored rows by a constant factor, the
    provider changed convention. Merging five days into an old basis would
    fabricate a fake move in the middle of the series - one that passes every
    other check.
    """
    updater.download("ETF_EU", MONDAY, FRIDAY)
    before = repository.load_bars("ETF_EU").copy()
    rebased = yahoo.rows["ETF_EU"].copy()
    for column in ("open", "high", "low", "close"):
        rebased[column] = rebased[column] / 4.0
    yahoo.rows["ETF_EU"] = rebased
    yahoo.calls.clear()

    report = updater.update("ETF_EU")

    assert not report.valid
    assert "SERIES_REBASED" in codes(report)
    # Not one value moved, and the checked series did not move either.
    pd.testing.assert_frame_equal(repository.load_bars("ETF_EU"), before)
    # The new basis is on disk as evidence: the overlap fetch, then the full one.
    assert yahoo.calls[-1] == ("ETF_EU", MONDAY, FRIDAY)
    assert len(repository.list_raw_fetches("ETF_EU", "YAHOO")) == 6


def test_a_single_changed_value_is_not_read_as_a_rebasing(
    updater: MarketDataUpdater, repository: MarketDataRepository, yahoo: FakeSource
) -> None:
    """One field moving is the ordinary revision path, guard or no guard."""
    updater.download("ETF_EU", MONDAY, FRIDAY)
    moved = yahoo.rows["ETF_EU"].copy()
    moved.loc[1, "close"] = 101.01
    yahoo.rows["ETF_EU"] = moved

    report = updater.update("ETF_EU")

    assert report.valid
    assert "SERIES_REBASED" not in codes(report)


def test_a_rebased_level_series_is_caught_too(
    updater: MarketDataUpdater, repository: MarketDataRepository, fred: FakeSource
) -> None:
    """A rate switching from percent to fraction is the same failure, unpriced."""
    updater.download("RATE_US", MONDAY, FRIDAY)
    before = repository.load_levels("RATE_US").copy()
    rebased = fred.rows["RATE_US"].copy()
    rebased["value"] = rebased["value"] / 100.0
    fred.rows["RATE_US"] = rebased

    report = updater.update("RATE_US")

    assert "SERIES_REBASED" in codes(report)
    pd.testing.assert_frame_equal(repository.load_levels("RATE_US"), before)


def test_an_acceptance_covers_one_correction_and_not_the_next(
    repository: MarketDataRepository,
    instruments: InstrumentRegistry,
    calendars: CalendarRegistry,
    yahoo: FakeSource,
    clock: Clock,
) -> None:
    """A decision is about one transition, never a standing permission.

    Keyed on the field and the date alone, one review let every later change of
    that close through, unreviewed and for ever: accepting 101.0 -> 101.01 also
    accepted 101.01 -> 101.9, and whatever the provider served after that.
    """
    accepted = AcceptedRevisions(
        [
            AcceptedRevision(
                instrument_id="ETF_EU",
                source="YAHOO",
                table="bars",
                observation_date=TUESDAY,
                field="close",
                old_value=101.0,
                new_value=101.01,
                reason="Provider confirmed the Tuesday close was mispriced",
            )
        ]
    )
    updater = build_updater(repository, instruments, calendars, {"YAHOO": yahoo}, clock, accepted)
    updater.download("ETF_EU", MONDAY, FRIDAY)
    reviewed = yahoo.rows["ETF_EU"].copy()
    reviewed.loc[1, "close"] = 101.01
    yahoo.rows["ETF_EU"] = reviewed
    updater.update("ETF_EU")
    assert repository.load_bars("ETF_EU")["close"].iloc[1] == 101.01

    # A second move of the same field, which nobody reviewed.
    again = yahoo.rows["ETF_EU"].copy()
    again.loc[1, "close"] = 101.9
    yahoo.rows["ETF_EU"] = again

    report = updater.update("ETF_EU")

    assert repository.load_bars("ETF_EU")["close"].iloc[1] == 101.01
    assert "VALUE_REVISED" in codes(report)


def test_a_check_source_restating_the_past_is_logged_and_ignored(
    repository: MarketDataRepository,
    calendars: CalendarRegistry,
    clock: Clock,
) -> None:
    """A second opinion follows the same policy as the series it checks.

    Euronext arriving late with a different value for an old session used to
    flip that session from CONFIRMED to CONFLICT on the spot, while a replay of
    the same archive kept the first value and rebuilt CONFIRMED: the live clean
    layer and the rebuilt one disagreed, which is the one property the module
    exists to guarantee. A check source now has a canonical series of its own,
    and a restatement of it is logged and ignored like any other.
    """
    week = raw_bars([(day, 100.0 + index) for index, day in enumerate(SESSIONS)])
    disagreeing = week.copy()
    disagreeing.loc[2, ["open", "high", "low", "close"]] = 90.0
    euronext = FakeSource("EURONEXT", clock, rows={"ETF_EU": week.copy()})
    updater = build_updater(
        repository,
        InstrumentRegistry([two_source_etf()]),
        calendars,
        {"YAHOO": FakeSource("YAHOO", clock, rows={"ETF_EU": week}), "EURONEXT": euronext},
        clock,
    )
    updater.download("ETF_EU", MONDAY, FRIDAY)
    assert verdicts_of(repository, "ETF_EU")[WEDNESDAY] == CheckStatus.CONFIRMED.value
    euronext.rows["ETF_EU"] = disagreeing

    report = updater.update("ETF_EU")

    assert "VALUE_REVISED" in codes(report)
    assert "CHECK_STATUS_CHANGED" not in codes(report)
    assert verdicts_of(repository, "ETF_EU")[WEDNESDAY] == CheckStatus.CONFIRMED.value
    # And the log says which provider changed its mind, not just that one did.
    revisions = repository.load_revisions()
    assert set(revisions["source"]) == {"EURONEXT"}


def test_an_accepted_restatement_of_a_check_source_does_move_the_verdict(
    repository: MarketDataRepository,
    calendars: CalendarRegistry,
    clock: Clock,
) -> None:
    """Ignored by default is not ignored for ever: the decision is reviewable."""
    week = raw_bars([(day, 100.0 + index) for index, day in enumerate(SESSIONS)])
    disagreeing = week.copy()
    disagreeing.loc[2, ["open", "high", "low", "close"]] = 90.0
    euronext = FakeSource("EURONEXT", clock, rows={"ETF_EU": week.copy()})
    accepted = AcceptedRevisions(
        [
            AcceptedRevision(
                instrument_id="ETF_EU",
                source="EURONEXT",
                table="bars",
                observation_date=WEDNESDAY,
                field=field,
                old_value=old,
                new_value=90.0,
                reason="Euronext confirmed its first print was wrong.",
            )
            for field, old in (
                ("open", 102.0),
                ("high", 103.0),
                ("low", 101.0),
                ("close", 102.0),
            )
        ]
    )
    updater = build_updater(
        repository,
        InstrumentRegistry([two_source_etf()]),
        calendars,
        {"YAHOO": FakeSource("YAHOO", clock, rows={"ETF_EU": week}), "EURONEXT": euronext},
        clock,
        accepted,
    )
    updater.download("ETF_EU", MONDAY, FRIDAY)
    euronext.rows["ETF_EU"] = disagreeing

    report = updater.update("ETF_EU")

    assert "CHECK_STATUS_CHANGED" in codes(report)
    assert verdicts_of(repository, "ETF_EU")[WEDNESDAY] == CheckStatus.CONFLICT.value


def test_live_and_rebuild_agree_after_a_check_source_restatement(
    repository: MarketDataRepository,
    calendars: CalendarRegistry,
    clock: Clock,
) -> None:
    """The property the whole module is for, on the path that used to break it."""
    week = raw_bars([(day, 100.0 + index) for index, day in enumerate(SESSIONS)])
    disagreeing = week.copy()
    disagreeing.loc[2, ["open", "high", "low", "close"]] = 90.0
    euronext = FakeSource("EURONEXT", clock, rows={"ETF_EU": week.copy()})
    updater = build_updater(
        repository,
        InstrumentRegistry([two_source_etf()]),
        calendars,
        {"YAHOO": FakeSource("YAHOO", clock, rows={"ETF_EU": week}), "EURONEXT": euronext},
        clock,
    )
    updater.download("ETF_EU", MONDAY, FRIDAY)
    euronext.rows["ETF_EU"] = disagreeing
    updater.update("ETF_EU")
    live = _clean_bytes(repository, "ETF_EU")

    updater.rebuild_clean("ETF_EU")

    assert _clean_bytes(repository, "ETF_EU") == live


def test_a_stored_corporate_action_is_never_rewritten(
    updater: MarketDataUpdater, repository: MarketDataRepository, yahoo: FakeSource
) -> None:
    """A restated dividend is reported and the stored one is kept.

    Applying it would move every adjusted price before that ex-date, silently.
    """
    updater.download("ETF_EU", MONDAY, FRIDAY)
    yahoo.actions["ETF_EU"] = raw_actions([(WEDNESDAY, ActionType.DIVIDEND, 0.75)])

    report = updater.update("ETF_EU")

    actions = repository.load_corporate_actions("ETF_EU")
    assert list(actions["value"]) == [0.5]
    assert "ACTION_REVISED" in codes(report)


def test_a_reviewed_correction_is_applied_when_the_action_is_stored(
    repository: MarketDataRepository,
    instruments: InstrumentRegistry,
    calendars: CalendarRegistry,
    yahoo: FakeSource,
    fred: FakeSource,
    clock: Clock,
) -> None:
    """A spin-off Yahoo reports as a fractional split is stored as a spin-off.

    The price adjustment is identical either way, so nothing in the series
    moves; what changes is that no layer above can read a share multiplication
    into an event where no share was multiplied.
    """
    yahoo.actions["ETF_EU"] = raw_actions([(WEDNESDAY, ActionType.SPLIT, 1.281)])
    corrections = ActionCorrections(
        [
            ActionCorrection(
                instrument_id="ETF_EU",
                ex_date=WEDNESDAY,
                from_type=ActionType.SPLIT,
                to_type=ActionType.SPIN_OFF,
                reason="Spin-off reported as a fractional split",
            )
        ]
    )
    updater = build_updater(
        repository,
        instruments,
        calendars,
        {"YAHOO": yahoo, "FRED": fred},
        clock,
        corrections=corrections,
    )

    updater.download("ETF_EU", MONDAY, FRIDAY)

    stored = repository.load_corporate_actions("ETF_EU")
    assert stored["action_type"].tolist() == ["SPIN_OFF"]
    assert stored["value"].tolist() == [1.281]

    # Refetching does not add the provider's version next to the corrected one.
    updater.update("ETF_EU")
    assert repository.load_corporate_actions("ETF_EU")["action_type"].tolist() == ["SPIN_OFF"]


def test_a_new_corporate_action_is_added(
    updater: MarketDataUpdater, repository: MarketDataRepository, yahoo: FakeSource
) -> None:
    """An event we did not have is stored, next to the one we did."""
    updater.download("ETF_EU", MONDAY, FRIDAY)
    yahoo.actions["ETF_EU"] = raw_actions(
        [(WEDNESDAY, ActionType.DIVIDEND, 0.5), (THURSDAY, ActionType.SPLIT, 4.0)]
    )

    updater.update("ETF_EU")

    actions = repository.load_corporate_actions("ETF_EU")
    assert list(zip(actions["ex_date"], actions["action_type"], strict=True)) == [
        (WEDNESDAY, "DIVIDEND"),
        (THURSDAY, "SPLIT"),
    ]


def test_an_action_withdrawn_by_the_provider_is_reported_and_kept(
    updater: MarketDataUpdater, repository: MarketDataRepository, yahoo: FakeSource
) -> None:
    """A dividend that disappears from a fetch covering its ex-date is loud."""
    updater.download("ETF_EU", MONDAY, FRIDAY)
    yahoo.actions["ETF_EU"] = raw_actions([])

    report = updater.update("ETF_EU")

    assert "ACTION_ABSENT" in codes(report)
    assert list(repository.load_corporate_actions("ETF_EU")["value"]) == [0.5]


def test_corporate_actions_of_other_instruments_survive(
    updater: MarketDataUpdater, repository: MarketDataRepository, yahoo: FakeSource
) -> None:
    """The actions table is global: writing one instrument must not empty it."""
    yahoo.actions["IDX_US"] = raw_actions([(TUESDAY, ActionType.DIVIDEND, 0.1)])
    updater.download("IDX_US", MONDAY, FRIDAY)
    updater.download("ETF_EU", MONDAY, FRIDAY)

    assert list(repository.load_corporate_actions("IDX_US")["value"]) == [0.1]
    assert list(repository.load_corporate_actions("ETF_EU")["value"]) == [0.5]


# ---------------------------------------------------------------------------
# Exercice 9.4 - update_all
# ---------------------------------------------------------------------------


def test_update_all_reports_every_instrument(
    updater: MarketDataUpdater, repository: MarketDataRepository
) -> None:
    """Every registered instrument comes back with a report."""
    reports = updater.update_all()
    assert sorted(reports) == ["ETF_EU", "IDX_US", "RATE_US"]
    assert all(report.valid for report in reports.values())
    assert not repository.load_bars("IDX_US").empty


def test_one_failing_instrument_does_not_stop_the_others(
    repository: MarketDataRepository,
    instruments: InstrumentRegistry,
    calendars: CalendarRegistry,
    yahoo: FakeSource,
    clock: Clock,
) -> None:
    """A source missing for one instrument is an error on that one alone."""
    # No FRED adapter: RATE_US cannot be fetched.
    updater = build_updater(repository, instruments, calendars, {"YAHOO": yahoo}, clock)

    reports = updater.update_all()

    assert codes(reports["RATE_US"]) == ["UPDATE_FAILED"]
    assert not reports["RATE_US"].valid
    assert reports["ETF_EU"].valid
    assert not repository.load_bars("ETF_EU").empty
    log = pq.read_table(repository.root / "validation" / "validation_log.parquet").to_pandas()
    assert "UPDATE_FAILED" in set(log["code"])


# ---------------------------------------------------------------------------
# Exercice 9.5 - rebuild
# ---------------------------------------------------------------------------


def test_rebuild_is_idempotent(
    updater: MarketDataUpdater, repository: MarketDataRepository, yahoo: FakeSource
) -> None:
    """Rebuilding the clean layer twice produces identical files.

    This is the test everyone forgets to write, and the one that proves the
    pipeline has no hidden state: no clock read, no dictionary ordering, no
    absolute path leaking into the output.
    """
    updater.download("ETF_EU", MONDAY, WEDNESDAY)
    updater.update("ETF_EU")
    live = _clean_bytes(repository, "ETF_EU")

    updater.rebuild_clean("ETF_EU")
    first = _clean_bytes(repository, "ETF_EU")
    updater.rebuild_clean("ETF_EU")
    second = _clean_bytes(repository, "ETF_EU")

    assert first == second
    # And a rebuild reproduces what the live pipeline had written.
    assert first == live


def test_a_rebuild_that_cannot_read_an_archive_leaves_the_clean_layer_as_it_was(
    updater: MarketDataUpdater, repository: MarketDataRepository
) -> None:
    """Audit A16: the clean layer used to be emptied before the first archive was read.

    Fault injection only: one applied archive is overwritten with bytes that
    are not Parquet. The rebuild fails, and the series it could not rebuild
    is still there, byte for byte.
    """
    updater.download("ETF_EU", MONDAY, FRIDAY)
    before = _clean_bytes(repository, "ETF_EU")
    fetch_id = repository.list_raw_fetches("ETF_EU", "YAHOO")[0]
    (repository.root / "raw" / "YAHOO" / "ETF_EU" / f"{fetch_id}.parquet").write_bytes(
        b"not parquet"
    )

    with pytest.raises(pa.ArrowInvalid):
        updater.rebuild_clean("ETF_EU")

    assert _clean_bytes(repository, "ETF_EU") == before
    assert list((repository.root / ".pending").iterdir()) == []


def test_a_rebuild_missing_an_applied_archive_refuses_before_writing(
    updater: MarketDataUpdater, repository: MarketDataRepository
) -> None:
    updater.download("ETF_EU", MONDAY, FRIDAY)
    before = _clean_bytes(repository, "ETF_EU")
    fetch_id = repository.list_raw_fetches("ETF_EU", "YAHOO")[0]
    folder = repository.root / "raw" / "YAHOO" / "ETF_EU"
    (folder / f"{fetch_id}.parquet").unlink()
    (folder / f"{fetch_id}.json").unlink()

    with pytest.raises(FileNotFoundError, match="no longer in raw"):
        updater.rebuild_clean("ETF_EU")

    assert _clean_bytes(repository, "ETF_EU") == before


def test_a_rebuild_whose_replay_is_refused_is_abandoned_whole(
    repository: MarketDataRepository,
    instruments: InstrumentRegistry,
    calendars: CalendarRegistry,
    yahoo: FakeSource,
    fred: FakeSource,
    clock: Clock,
) -> None:
    """A replay the live path accepted and the rebuild now refuses publishes nothing.

    Live, the refetched Tuesday was kept as stored. A policy since extended to
    accept only its open would merge an open above the stored high on replay:
    that fetch is refused, so the rebuild is not what the live path built,
    and none of it is published.
    """
    sources = {"YAHOO": yahoo, "FRED": fred}
    live = build_updater(repository, instruments, calendars, sources, clock)
    live.download("ETF_EU", MONDAY, FRIDAY)
    moved = yahoo.rows["ETF_EU"].copy()
    moved.loc[1, ["open", "high", "low", "close"]] = [110.0, 111.0, 109.0, 110.0]
    yahoo.rows["ETF_EU"] = moved
    assert live.update("ETF_EU").valid
    before = _clean_bytes(repository, "ETF_EU")
    accepted = AcceptedRevisions(
        [
            AcceptedRevision(
                instrument_id="ETF_EU",
                source="YAHOO",
                table="bars",
                observation_date=TUESDAY,
                field="open",
                old_value=101.0,
                new_value=110.0,
                reason="synthetic: only the open was reviewed",
            )
        ]
    )
    later = build_updater(repository, instruments, calendars, sources, clock, accepted)

    report = later.rebuild_clean("ETF_EU")

    assert not report.valid
    assert codes(report)[-1] == "REBUILD_ABANDONED"
    assert "MERGED_BAR_INVALID" in codes(report)
    assert _clean_bytes(repository, "ETF_EU") == before


def test_a_rebuild_replays_a_promotion_that_landed_just_before_it_took_the_lock(
    repository: MarketDataRepository,
    instruments: InstrumentRegistry,
    calendars: CalendarRegistry,
    yahoo: FakeSource,
    fred: FakeSource,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Audit R04: the rebuild read the journal, then took the lock.

    Another process promoted Thursday and Friday in between. The rebuild
    replayed the journal it had read before, published Monday to Wednesday
    only, and called the result valid while the journal named both fetches.
    """
    sources = {"YAHOO": yahoo, "FRED": fred}
    rebuilding = build_updater(repository, instruments, calendars, sources, clock)
    rebuilding.download("ETF_EU", MONDAY, WEDNESDAY)
    other = build_updater(
        MarketDataRepository(repository.root), instruments, calendars, sources, clock
    )
    real_transaction = repository.transaction
    raced: list[bool] = []

    def another_process_goes_first():  # noqa: ANN202 - a context manager, as the original
        if not raced:
            raced.append(True)
            assert other.update("ETF_EU").valid
        return real_transaction()

    monkeypatch.setattr(repository, "transaction", another_process_goes_first)

    report = rebuilding.rebuild_clean("ETF_EU")

    assert raced
    assert report.valid
    assert list(repository.load_bars("ETF_EU")["session_date"]) == list(SESSIONS)


def test_rebuild_replays_the_policy_not_the_last_fetch(
    updater: MarketDataUpdater, repository: MarketDataRepository, yahoo: FakeSource
) -> None:
    """The first value stored wins on replay, exactly as it did live."""
    updater.download("ETF_EU", MONDAY, FRIDAY)
    moved = yahoo.rows["ETF_EU"].copy()
    moved.loc[1, "close"] = 101.01
    yahoo.rows["ETF_EU"] = moved
    updater.update("ETF_EU")

    updater.rebuild_clean("ETF_EU")

    stored = repository.load_bars("ETF_EU")
    assert dict(zip(stored["session_date"], stored["close"], strict=True))[TUESDAY] == 101.0


def test_rebuild_does_not_append_to_the_logs(
    updater: MarketDataUpdater, repository: MarketDataRepository, yahoo: FakeSource
) -> None:
    """Replaying the archive is not a second arrival of the data."""
    updater.download("ETF_EU", MONDAY, FRIDAY)
    moved = yahoo.rows["ETF_EU"].copy()
    moved.loc[1, "close"] = 101.01
    yahoo.rows["ETF_EU"] = moved
    updater.update("ETF_EU")
    revisions_before = len(repository.load_revisions("ETF_EU"))
    log_before = len(
        pq.read_table(repository.root / "validation" / "validation_log.parquet").to_pandas()
    )

    report = updater.rebuild_clean("ETF_EU")

    assert len(repository.load_revisions("ETF_EU")) == revisions_before
    assert (
        len(pq.read_table(repository.root / "validation" / "validation_log.parquet").to_pandas())
        == log_before
    )
    # The issues are still reported to the caller.
    assert report.instrument_id == "ETF_EU"


def test_an_incomplete_primary_bar_is_replaced_by_the_complete_one(
    repository: MarketDataRepository,
    instruments: InstrumentRegistry,
    calendars: CalendarRegistry,
    clock: Clock,
) -> None:
    """The CW8 case of 2026-09-17, end to end.

    Yahoo served the session without a close while Euronext had the full bar.
    The checked row must carry the exchange's close, the session must not be
    condemned over a value only one source held, and the reader must serve it.
    """
    instrument = Instrument(
        id="ETF_EU",
        name="Paris ETF",
        asset_type=AssetType.ETF,
        data_type=DataType.BAR,
        currency="EUR",
        primary_source="YAHOO",
        source_symbol="CW8.PA",
        tradable=True,
        calendar_id="XPAR",
        first_session=MONDAY,
        check_sources=(CheckSource(source="EURONEXT", source_symbol="LU-XPAR"),),
    )
    week = raw_bars([(day, 100.0 + index) for index, day in enumerate(SESSIONS)])
    incomplete = week.copy()
    incomplete.loc[4, "close"] = float("nan")
    registry = InstrumentRegistry([instrument])
    updater = build_updater(
        repository,
        registry,
        calendars,
        {
            "YAHOO": FakeSource("YAHOO", clock, rows={"ETF_EU": incomplete}),
            "EURONEXT": FakeSource("EURONEXT", clock, rows={"ETF_EU": week}),
        },
        clock,
    )

    report = updater.download("ETF_EU", MONDAY, FRIDAY)

    assert report.valid
    assert "MISSING_PRICE" in codes(report)  # the hole is still said out loud
    checked = repository.load_checked_bars("ETF_EU")
    friday_row = checked.loc[checked["session_date"] == FRIDAY].iloc[0]
    assert friday_row["close"] == 104.0
    assert friday_row["source"] == "EURONEXT"
    assert friday_row["check_status"] == CheckStatus.CONFIRMED.value
    assert friday_row["conflicting_fields"] == ""

    reader = MarketDataReader(repository, registry, calendars, reference_calendar_id="XPAR")
    values = reader.at(datetime(2026, 3, 13, 21, 0, tzinfo=UTC)).values(["ETF_EU"])
    assert values.loc["ETF_EU", "value"] == 104.0
    assert values.loc["ETF_EU", "status"] is ObservationStatus.OK


def test_a_session_only_the_check_source_holds_keeps_the_store_consistent(
    repository: MarketDataRepository,
    calendars: CalendarRegistry,
    clock: Clock,
) -> None:
    """Ingestion, the consistency guard, an update and a rebuild agree (audit A06).

    Yahoo skips Tuesday, Euronext serves it. The checked series used to take
    Tuesday from Euronext while the primary series had no Tuesday, a store the
    guard in front of the next update then refused - a state the pipeline had
    written itself, and a rebuild would write again.
    """
    instrument = Instrument(
        id="ETF_EU",
        name="Paris ETF",
        asset_type=AssetType.ETF,
        data_type=DataType.BAR,
        currency="EUR",
        primary_source="YAHOO",
        source_symbol="CW8.PA",
        tradable=True,
        calendar_id="XPAR",
        first_session=MONDAY,
        check_sources=(CheckSource(source="EURONEXT", source_symbol="LU-XPAR"),),
    )
    week = raw_bars([(day, 100.0 + index) for index, day in enumerate(SESSIONS)])
    holed = week.loc[week["date"] != TUESDAY].reset_index(drop=True)
    registry = InstrumentRegistry([instrument])
    updater = build_updater(
        repository,
        registry,
        calendars,
        {
            "YAHOO": FakeSource("YAHOO", clock, rows={"ETF_EU": holed}),
            "EURONEXT": FakeSource("EURONEXT", clock, rows={"ETF_EU": week}),
        },
        clock,
    )

    report = updater.download("ETF_EU", MONDAY, FRIDAY)

    assert report.valid
    only = [issue for issue in report.issues if issue.code == "SECONDARY_ONLY_SESSION"]
    assert [issue.observation_date for issue in only] == [TUESDAY]
    served = [day for day in SESSIONS if day != TUESDAY]
    assert repository.load_bars("ETF_EU")["session_date"].tolist() == served
    checked = repository.load_checked_bars("ETF_EU")
    assert checked["session_date"].tolist() == served
    assert TUESDAY in set(repository.load_check_bars("ETF_EU", "EURONEXT")["session_date"])

    assert updater.update("ETF_EU").valid  # the guard in front of it passes
    after_update = repository.load_checked_bars("ETF_EU")
    assert after_update["session_date"].tolist() == served

    rebuilt = updater.rebuild_clean("ETF_EU")
    assert rebuilt.valid
    pd.testing.assert_frame_equal(repository.load_checked_bars("ETF_EU"), after_update)


def test_an_unavailable_check_source_does_not_lose_the_instrument(
    repository: MarketDataRepository,
    calendars: CalendarRegistry,
    clock: Clock,
) -> None:
    """Euronext refuses anything older than its rolling two-year window.

    Asked for a history that starts in 2018, it raises - and used to take the
    whole instrument down with it, primary data included. A second opinion that
    cannot be obtained leaves the sessions single-sourced; it does not delete
    them.
    """

    class RefusingSource(FakeSource):
        def download(self, instrument: Instrument, start: date, end: date) -> RawDownload:
            raise ProviderUnavailable(f"{instrument.source_symbol} is down")

    instrument = Instrument(
        id="ETF_EU",
        name="Paris ETF",
        asset_type=AssetType.ETF,
        data_type=DataType.BAR,
        currency="EUR",
        primary_source="YAHOO",
        source_symbol="CW8.PA",
        tradable=True,
        calendar_id="XPAR",
        first_session=MONDAY,
        check_sources=(CheckSource(source="EURONEXT", source_symbol="LU-XPAR"),),
    )
    week = raw_bars([(day, 100.0 + index) for index, day in enumerate(SESSIONS)])
    updater = build_updater(
        repository,
        InstrumentRegistry([instrument]),
        calendars,
        {
            "YAHOO": FakeSource("YAHOO", clock, rows={"ETF_EU": week}),
            "EURONEXT": RefusingSource("EURONEXT", clock),
        },
        clock,
    )

    report = updater.download("ETF_EU", MONDAY, FRIDAY)

    assert report.valid
    assert "CHECK_SOURCE_UNAVAILABLE" in codes(report)
    assert list(repository.load_bars("ETF_EU")["session_date"]) == list(SESSIONS)
    checked = repository.load_checked_bars("ETF_EU")
    assert set(checked["check_status"]) == {CheckStatus.SINGLE_SOURCE.value}


def test_a_failing_primary_source_still_stops_the_instrument(
    repository: MarketDataRepository,
    instruments: InstrumentRegistry,
    calendars: CalendarRegistry,
    fred: FakeSource,
    clock: Clock,
) -> None:
    """There is nothing to fall back on, so the failure must surface."""

    class BrokenSource(FakeSource):
        def download(self, instrument: Instrument, start: date, end: date) -> RawDownload:
            raise ProviderUnavailable("provider down")

    updater = build_updater(
        repository,
        instruments,
        calendars,
        {"YAHOO": BrokenSource("YAHOO", clock), "FRED": fred},
        clock,
    )

    with pytest.raises(ProviderUnavailable, match="provider down"):
        updater.download("ETF_EU", MONDAY, FRIDAY)


def two_source_etf() -> Instrument:
    """Return the Paris ETF with one check source."""
    return Instrument(
        id="ETF_EU",
        name="Paris ETF",
        asset_type=AssetType.ETF,
        data_type=DataType.BAR,
        currency="EUR",
        primary_source="YAHOO",
        source_symbol="CW8.PA",
        tradable=True,
        calendar_id="XPAR",
        first_session=MONDAY,
        check_sources=(CheckSource(source="EURONEXT", source_symbol="LU-XPAR"),),
    )


def verdicts_of(repository: MarketDataRepository, instrument_id: str) -> dict[date, str]:
    """Return the cross-check status of every stored session."""
    checked = repository.load_checked_bars(instrument_id)
    return dict(zip(checked["session_date"], checked["check_status"], strict=True))


def test_a_check_source_is_asked_only_for_the_window_it_holds(
    repository: MarketDataRepository,
    calendars: CalendarRegistry,
    clock: Clock,
) -> None:
    """A rolling window costs the sessions before it, and nothing else.

    Euronext serves about two years. Asked for a history starting in 2018 it
    refused the whole request, and every one of the 2230 sessions of ETF_WORLD
    stayed SINGLE_SOURCE - the cross-check existed and confirmed nothing.
    """
    week = raw_bars([(day, 100.0 + index) for index, day in enumerate(SESSIONS)])
    euronext = FakeSource("EURONEXT", clock, rows={"ETF_EU": week.copy()}, window_start=WEDNESDAY)
    updater = build_updater(
        repository,
        InstrumentRegistry([two_source_etf()]),
        calendars,
        {"YAHOO": FakeSource("YAHOO", clock, rows={"ETF_EU": week}), "EURONEXT": euronext},
        clock,
    )

    updater.download("ETF_EU", MONDAY, FRIDAY)

    assert euronext.calls == [("ETF_EU", WEDNESDAY, FRIDAY)]
    verdicts = verdicts_of(repository, "ETF_EU")
    assert verdicts[MONDAY] == CheckStatus.SINGLE_SOURCE.value
    assert verdicts[TUESDAY] == CheckStatus.SINGLE_SOURCE.value
    assert verdicts[WEDNESDAY] == CheckStatus.CONFIRMED.value
    assert verdicts[FRIDAY] == CheckStatus.CONFIRMED.value


def test_a_window_that_moved_is_asked_again_from_the_date_it_names(
    repository: MarketDataRepository,
    calendars: CalendarRegistry,
    clock: Clock,
) -> None:
    """The declared window is a shortcut, not the truth; the provider's answer is."""
    week = raw_bars([(day, 100.0 + index) for index, day in enumerate(SESSIONS)])

    class MovedWindow(FakeSource):
        def download(self, instrument: Instrument, start: date, end: date) -> RawDownload:
            if start < THURSDAY:
                self.calls.append((instrument.id, start, end))
                raise ProviderRangeUnavailable(
                    f"served only from {THURSDAY}", available_from=THURSDAY
                )
            return super().download(instrument, start, end)

    euronext = MovedWindow("EURONEXT", clock, rows={"ETF_EU": week.copy()})
    updater = build_updater(
        repository,
        InstrumentRegistry([two_source_etf()]),
        calendars,
        {"YAHOO": FakeSource("YAHOO", clock, rows={"ETF_EU": week}), "EURONEXT": euronext},
        clock,
    )

    updater.download("ETF_EU", MONDAY, FRIDAY)

    assert euronext.calls == [("ETF_EU", MONDAY, FRIDAY), ("ETF_EU", THURSDAY, FRIDAY)]
    verdicts = verdicts_of(repository, "ETF_EU")
    assert verdicts[WEDNESDAY] == CheckStatus.SINGLE_SOURCE.value
    assert verdicts[THURSDAY] == CheckStatus.CONFIRMED.value


@pytest.mark.parametrize(
    "error",
    [TypeError("NoneType is not subscriptable"), ProviderResponseError("header moved")],
    ids=["a-bug-in-the-adapter", "an-answer-we-cannot-read"],
)
def test_a_check_source_that_is_not_merely_down_is_not_degraded(
    repository: MarketDataRepository,
    calendars: CalendarRegistry,
    clock: Clock,
    error: Exception,
) -> None:
    """Neither a bug of ours nor a format that moved may hide behind a warning.

    Both used to become CHECK_SOURCE_UNAVAILABLE, which reads like a provider
    having a bad day and gets ignored for months. Only an outage means that.
    """
    week = raw_bars([(day, 100.0 + index) for index, day in enumerate(SESSIONS)])

    class BadSource(FakeSource):
        def download(self, instrument: Instrument, start: date, end: date) -> RawDownload:
            raise error

    updater = build_updater(
        repository,
        InstrumentRegistry([two_source_etf()]),
        calendars,
        {
            "YAHOO": FakeSource("YAHOO", clock, rows={"ETF_EU": week}),
            "EURONEXT": BadSource("EURONEXT", clock),
        },
        clock,
    )

    with pytest.raises(type(error)):
        updater.download("ETF_EU", MONDAY, FRIDAY)


def test_a_fetch_that_never_completed_is_not_replayed(
    updater: MarketDataUpdater,
    repository: MarketDataRepository,
    yahoo: FakeSource,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """raw/ holds downloads the clean layer never took, and a replay must not take them.

    The snapshot is archived before the pipeline that consumes it runs, so a
    download the validator refuses is kept rather than lost. The cost is that
    raw/ also holds fetches the live path never applied - and since the first
    value stored wins, replaying one would let a value the live path refused
    beat the value it kept, rebuilding a history that never existed.
    """
    updater.download("ETF_EU", MONDAY, FRIDAY)
    before = repository.load_bars("ETF_EU").copy()

    # A run that dies after archiving raw and before the clean layer is whole.
    crashed = yahoo.rows["ETF_EU"].copy()
    crashed.loc[1, "close"] = 101.5
    yahoo.rows["ETF_EU"] = crashed
    monkeypatch.setattr(
        repository,
        "save_checked_bars",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )
    with pytest.raises(OSError, match="disk full"):
        updater.download("ETF_EU", MONDAY, FRIDAY)
    monkeypatch.undo()

    # The archive kept it, and the replay leaves it there.
    assert len(repository.list_raw_fetches("ETF_EU", "YAHOO")) == 4
    report = updater.rebuild_clean("ETF_EU")

    assert "UNAPPLIED_FETCH_SKIPPED" in codes(report)
    pd.testing.assert_frame_equal(repository.load_bars("ETF_EU"), before)


def test_a_download_the_validator_refused_is_not_replayed_either(
    updater: MarketDataUpdater, repository: MarketDataRepository, yahoo: FakeSource
) -> None:
    """Same rule, the ordinary case: refused once is refused on the replay."""
    updater.download("ETF_EU", MONDAY, FRIDAY)
    before = repository.load_bars("ETF_EU").copy()
    broken = yahoo.rows["ETF_EU"].copy()
    broken.loc[1, "high"] = 1.0  # high below low: OHLC_ORDER, an error
    yahoo.rows["ETF_EU"] = broken

    assert not updater.download("ETF_EU", MONDAY, FRIDAY).valid

    updater.rebuild_clean("ETF_EU")

    pd.testing.assert_frame_equal(repository.load_bars("ETF_EU"), before)


@pytest.mark.parametrize("euronext_first", [False, True])
def test_rebuild_reproduces_a_two_source_checked_series(
    repository: MarketDataRepository,
    calendars: CalendarRegistry,
    clock: Clock,
    euronext_first: bool,
) -> None:
    """Replaying one archived fetch at a time must reach the verdicts of the live run.

    The live path downloads every source in one go and cross-checks them
    together; a replay meets them one fetch at a time. Judging each fetch on its
    own would quietly turn every CONFIRMED and CONFLICT back into
    SINGLE_SOURCE - the rebuilt series would look clean and mean less.

    The two orders matter: sources fetched within the same second share a fetch
    id, and the replay then starts with the check source.
    """
    instrument = Instrument(
        id="ETF_EU",
        name="Paris ETF",
        asset_type=AssetType.ETF,
        data_type=DataType.BAR,
        currency="EUR",
        primary_source="YAHOO",
        source_symbol="CW8.PA",
        tradable=True,
        calendar_id="XPAR",
        first_session=MONDAY,
        check_sources=(CheckSource(source="EURONEXT", source_symbol="LU-XPAR"),),
    )
    week = raw_bars([(day, 100.0 + index) for index, day in enumerate(SESSIONS)])
    disagreeing = week.copy()
    disagreeing.loc[2, ["open", "high", "low", "close"]] = 90.0
    # A frozen clock for the check source puts both fetches in the same second,
    # so the replay starts with EURONEXT rather than with the primary source.
    euronext_clock = Clock() if not euronext_first else (lambda: FIRST_TICK)
    sources = {
        "YAHOO": FakeSource("YAHOO", clock, rows={"ETF_EU": week}),
        "EURONEXT": FakeSource("EURONEXT", euronext_clock, rows={"ETF_EU": disagreeing}),
    }
    updater = build_updater(repository, InstrumentRegistry([instrument]), calendars, sources, clock)
    updater.download("ETF_EU", MONDAY, FRIDAY)
    live = _clean_bytes(repository, "ETF_EU")
    live_verdicts = dict(
        zip(
            repository.load_checked_bars("ETF_EU")["session_date"],
            repository.load_checked_bars("ETF_EU")["check_status"],
            strict=True,
        )
    )
    assert live_verdicts[WEDNESDAY] == CheckStatus.CONFLICT.value
    assert live_verdicts[TUESDAY] == CheckStatus.CONFIRMED.value

    updater.rebuild_clean("ETF_EU")

    assert _clean_bytes(repository, "ETF_EU") == live


def test_rebuild_leaves_other_instruments_alone(
    updater: MarketDataUpdater, repository: MarketDataRepository
) -> None:
    """Rebuilding one instrument must not touch another's rows or actions."""
    updater.download("IDX_US", MONDAY, FRIDAY)
    updater.download("ETF_EU", MONDAY, FRIDAY)
    before = repository.load_bars("IDX_US")

    updater.rebuild_clean("ETF_EU")

    pd.testing.assert_frame_equal(repository.load_bars("IDX_US"), before)
    assert list(repository.load_corporate_actions("ETF_EU")["value"]) == [0.5]


def test_rebuild_needs_no_network(
    updater: MarketDataUpdater, repository: MarketDataRepository, yahoo: FakeSource
) -> None:
    """The archive is enough: a rebuild asks the provider nothing."""
    updater.download("ETF_EU", MONDAY, FRIDAY)
    yahoo.calls.clear()

    updater.rebuild_clean("ETF_EU")

    assert yahoo.calls == []
    assert list(repository.load_bars("ETF_EU")["session_date"]) == list(SESSIONS)


def _clean_bytes(repository: MarketDataRepository, instrument_id: str) -> dict[str, bytes]:
    """Return the raw bytes of an instrument's clean files, keyed by table."""
    clean = repository.root / "clean"
    files = {
        "bars": clean / "bars" / f"{instrument_id}.parquet",
        "checked_bars": clean / "checked_bars" / f"{instrument_id}.parquet",
        "corporate_actions": clean / "corporate_actions.parquet",
    }
    # Each check source's own canonical series counts: it is what the verdicts
    # are computed from, so a rebuild that reached them differently would show.
    for path in sorted((clean / "check_bars").glob(f"*/{instrument_id}.parquet")):
        files[f"check_bars/{path.parent.name}"] = path
    return {name: path.read_bytes() for name, path in files.items() if path.exists()}


# ---------------------------------------------------------------------------
# 9.3 Nothing unfinished becomes canonical
# ---------------------------------------------------------------------------


def utc(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    """Return a UTC-aware instant."""
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def bar_on(calendar_id: str) -> Instrument:
    """Return a BAR instrument quoted on one venue."""
    return Instrument(
        id="IDX",
        name="Index",
        asset_type=AssetType.INDEX,
        data_type=DataType.BAR,
        currency="USD",
        primary_source="YAHOO",
        source_symbol="^GSPC",
        tradable=False,
        calendar_id=calendar_id,
    )


def level_with(rule: PublicationRule) -> Instrument:
    """Return a LEVEL instrument published under ``rule``."""
    return Instrument(
        id="RATE",
        name="Rate",
        asset_type=AssetType.RATE,
        data_type=DataType.LEVEL,
        currency="NA",
        primary_source="FRED",
        source_symbol="DGS10",
        tradable=False,
        publication_rule=rule,
    )


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        # New York closes at 20:00 UTC in March: at 17:00 the session is running.
        (utc(2026, 3, 13, 17, 0), THURSDAY),
        # At the closing auction itself the bar is whole, like every other field.
        (utc(2026, 3, 13, 20, 0), FRIDAY),
        (utc(2026, 3, 13, 23, 59), FRIDAY),
        # Saturday: the last closed session is still Friday's.
        (utc(2026, 3, 14, 12, 0), FRIDAY),
        # Half day, 27 November: New York closes at 18:00 UTC, and the session
        # before it is 25 November - Thanksgiving falls in between.
        (utc(2026, 11, 27, 17, 0), date(2026, 11, 25)),
        (utc(2026, 11, 27, 18, 0), date(2026, 11, 27)),
    ],
    ids=["mid-session", "at-the-close", "after-the-close", "weekend", "half-day", "half-day-close"],
)
def test_safe_end_date_stops_at_the_last_closed_session(
    xnys: TradingCalendar, now: datetime, expected: date
) -> None:
    """A bar is fetchable once its session has closed, never before."""
    assert safe_end_date(bar_on("XNYS"), xnys, now) == expected


def test_safe_end_date_follows_the_venue_and_not_the_utc_day(xpar: TradingCalendar) -> None:
    """On 12 March Paris closes at 16:30 UTC and New York four hours later.

    The two venues are on different sides of the US DST switch that week, which
    is exactly when a fixed offset would put the cut in the wrong place.
    """
    assert safe_end_date(bar_on("XPAR"), xpar, utc(2026, 3, 12, 16, 0)) == WEDNESDAY
    assert safe_end_date(bar_on("XPAR"), xpar, utc(2026, 3, 12, 16, 30)) == THURSDAY


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (utc(2026, 3, 13, 16, 14), THURSDAY),
        (utc(2026, 3, 13, 16, 15), FRIDAY),
    ],
    ids=["before-the-release", "at-the-release"],
)
def test_safe_end_date_of_a_level_follows_its_publication_rule(
    now: datetime, expected: date
) -> None:
    """A published value is fetchable at its release time, not at midnight."""
    assert safe_end_date(level_with(RATE_RULE), None, now) == expected


def test_safe_end_date_of_a_lagged_level_counts_sessions(xnys: TradingCalendar) -> None:
    """A D+1 rule makes Thursday's value public on Friday, not on Thursday evening."""
    rule = PublicationRule(
        publication_time=time(20, 15),
        timezone="UTC",
        lag_sessions=1,
        calendar_id="XNYS",
    )
    instrument = level_with(rule)
    assert safe_end_date(instrument, xnys, utc(2026, 3, 13, 20, 14)) == WEDNESDAY
    assert safe_end_date(instrument, xnys, utc(2026, 3, 13, 20, 15)) == THURSDAY


def test_safe_end_date_refuses_a_naive_instant(xnys: TradingCalendar) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        safe_end_date(bar_on("XNYS"), xnys, datetime(2026, 3, 13, 21, 0))


def test_safe_end_date_refuses_a_bar_without_a_calendar() -> None:
    with pytest.raises(ValueError, match="no calendar"):
        safe_end_date(bar_on("XNYS"), None, utc(2026, 3, 13, 21, 0))


def test_update_does_not_reach_into_a_running_session(
    repository: MarketDataRepository,
    instruments: InstrumentRegistry,
    calendars: CalendarRegistry,
    yahoo: FakeSource,
) -> None:
    """The range asked of the provider stops at the last closed session."""
    clock = Clock(utc(2026, 3, 13, 17, 0))
    updater = build_updater(repository, instruments, calendars, {"YAHOO": yahoo}, clock)

    updater.update("IDX_US")

    assert yahoo.calls[-1] == ("IDX_US", MONDAY, THURSDAY)
    assert list(repository.load_bars("IDX_US")["session_date"]) == list(SESSIONS[:4])


def test_a_running_session_is_refused_even_when_asked_for(
    repository: MarketDataRepository,
    instruments: InstrumentRegistry,
    calendars: CalendarRegistry,
) -> None:
    """The bug of 18 September 2026, reproduced on the fixture week.

    An update run while New York was open stored a bar whose open equalled its
    high and whose volume was a quarter of a session's. Because a stored value
    wins, every later refetch of the real close was logged as a revision and
    refused, and replaying the archive kept the same partial bar. The refusal
    therefore sits in the normalizer, where the availability instant is known,
    so that it holds on the replay too - which is what repairs a series already
    polluted, without anyone deciding on a value by hand.
    """
    clock = Clock(utc(2026, 3, 13, 17, 0))
    source = YahooShapedSource(
        "YAHOO",
        clock,
        rows={"IDX_US": raw_bars([(day, 5_000.0 + index) for index, day in enumerate(SESSIONS)])},
    )
    updater = build_updater(
        repository,
        instruments,
        calendars,
        {"YAHOO": source},
        clock,
        normalizers={"YAHOO": YahooNormalizer()},
    )

    report = updater.download("IDX_US", MONDAY, FRIDAY)

    assert "NOT_YET_AVAILABLE" in codes(report)
    assert list(repository.load_bars("IDX_US")["session_date"]) == list(SESSIONS[:4])

    updater.rebuild_clean("IDX_US")

    assert list(repository.load_bars("IDX_US")["session_date"]) == list(SESSIONS[:4])

    # The evening brings the real bar, and nothing had to be revised.
    clock.now = utc(2026, 3, 13, 21, 0)
    report = updater.update("IDX_US")

    assert list(repository.load_bars("IDX_US")["session_date"]) == list(SESSIONS)
    assert "VALUE_REVISED" not in codes(report)


def test_a_clean_layer_missing_a_verdict_is_refused(
    updater: MarketDataUpdater, repository: MarketDataRepository
) -> None:
    """One writer at a time, and a crash between two writes has to be visible.

    An update rewrites several files and each write is atomic on its own; the
    set of them is not. A run that died after the bars and before the verdicts
    left a clean layer whose two halves describe different sessions, and the
    next update merged into it without a word.
    """
    updater.download("ETF_EU", MONDAY, FRIDAY)
    checked = repository.load_checked_bars("ETF_EU")
    repository.save_checked_bars("ETF_EU", checked.iloc[:-1].reset_index(drop=True))

    with pytest.raises(ValueError, match="inconsistent"):
        updater.update("ETF_EU")

    # And the repair is the one the message names.
    updater.rebuild_clean("ETF_EU")
    updater.update("ETF_EU")


def test_a_verdict_that_does_not_match_its_bars_is_refused(
    updater: MarketDataUpdater, repository: MarketDataRepository
) -> None:
    """Same dates on both sides is not the same thing as the same data.

    A crash can leave the bars of one fetch beside the verdicts of the one
    before, describing the same sessions with different values. Comparing the
    two lists of dates sees nothing; the verdicts are a function of the stored
    series, so the check is to compute them again.
    """
    updater.download("ETF_EU", MONDAY, FRIDAY)
    checked = repository.load_checked_bars("ETF_EU")
    tampered = checked.copy()
    tampered.loc[1, "close"] = tampered.loc[1, "close"] + 1.0
    repository.save_checked_bars("ETF_EU", tampered)

    with pytest.raises(ValueError, match="not what the stored series produce"):
        updater.update("ETF_EU")


def test_a_cross_check_policy_that_moved_is_named_as_such(
    repository: MarketDataRepository,
    calendars: CalendarRegistry,
    clock: Clock,
) -> None:
    """Tolerances decide which bars are confirmed, so changing them changes history.

    Legitimate, reviewed, and it still leaves the stored verdicts describing a
    policy that is no longer the committed one. The update says so instead of
    merging into them.
    """
    week = raw_bars([(day, 100.0 + index) for index, day in enumerate(SESSIONS)])
    close_enough = week.copy()
    # A hair above the committed 1e-6 tolerance, well below the 1e-3 tried next.
    close_enough.loc[2, "close"] = 102.001
    sources = {
        "YAHOO": FakeSource("YAHOO", clock, rows={"ETF_EU": week}),
        "EURONEXT": FakeSource("EURONEXT", clock, rows={"ETF_EU": close_enough}),
    }
    instruments = InstrumentRegistry([two_source_etf()])
    strict = build_updater(repository, instruments, calendars, sources, clock)
    strict.download("ETF_EU", MONDAY, FRIDAY)
    assert verdicts_of(repository, "ETF_EU")[WEDNESDAY] == CheckStatus.CONFLICT.value

    lenient = MarketDataUpdater(
        repository=repository,
        instruments=instruments,
        calendars=calendars,
        sources=dict(sources),
        normalizers={source_id: FakeNormalizer(source_id) for source_id in sources},
        accepted_revisions=AcceptedRevisions([]),
        action_corrections=ActionCorrections([]),
        bar_corrections=BarCorrections([]),
        cross_check_policy=CrossCheckPolicy(price_rel_tolerance=1e-3, volume_rel_tolerance=0.0),
        clock=clock,
    )

    with pytest.raises(ValueError, match=r"crosscheck\.toml changed"):
        lenient.update("ETF_EU")


# ---------------------------------------------------------------------------
# Storage safety, independent of any exercise
# ---------------------------------------------------------------------------


def test_interrupted_write_leaves_the_previous_file_intact(market_root, monkeypatch):
    """An exception mid-write must not destroy the existing dataset."""
    path = market_root / "clean" / "levels" / "US10Y.parquet"
    stored = pd.DataFrame(
        {
            "instrument_id": ["US10Y"],
            "observation_date": [date(2026, 1, 2)],
            "value": [4.1],
            "available_at_utc": pd.DatetimeIndex(
                [datetime(2026, 1, 2, 21, 15, tzinfo=UTC)]
            ).as_unit("us"),
            "source": ["FRED"],
            "source_fetch_id": ["20260103T000000Z"],
        }
    )
    write_parquet_atomic(stored, path, LEVELS_SCHEMA)
    before = path.read_bytes()

    def crash_mid_write(table: pa.Table, where: BinaryIO) -> None:
        where.write(b"PAR1 half a file")
        raise RuntimeError("disk full")

    monkeypatch.setattr(pq, "write_table", crash_mid_write)
    with pytest.raises(RuntimeError, match="disk full"):
        write_parquet_atomic(stored.assign(value=[9.9]), path, LEVELS_SCHEMA)

    assert path.read_bytes() == before
    assert [p.name for p in path.parent.iterdir()] == ["US10Y.parquet"]


# ---------------------------------------------------------------------------
# Reviewed bar corrections
# ---------------------------------------------------------------------------


def broken_bar(yahoo: FakeSource) -> None:
    """Make the provider serve an impossible bar on the Wednesday."""
    rows = yahoo.rows["ETF_EU"].copy()
    wednesday = rows["date"] == WEDNESDAY
    # Open above high: arithmetically impossible, and the validator says so.
    rows.loc[wednesday, "open"] = rows.loc[wednesday, "high"] + 1.0
    yahoo.rows["ETF_EU"] = rows


def dropping_wednesday() -> BarCorrections:
    """Return the reviewed decision to drop that bar."""
    return BarCorrections(
        [
            BarCorrection(
                instrument_id="ETF_EU",
                source="YAHOO",
                session_date=WEDNESDAY,
                defect=BarDefect.OHLC_ORDER,
                reason="Yahoo serves an open above the high; no second source for that year",
            )
        ]
    )


def test_a_broken_bar_refuses_the_whole_series_without_a_correction(
    updater: MarketDataUpdater, yahoo: FakeSource, repository: MarketDataRepository
) -> None:
    """The state before the mechanism existed, and it is the right default.

    One impossible row keeps four good ones out of the store, because a bar
    whose open is outside its own range is not something to guess at.
    """
    broken_bar(yahoo)

    report = updater.download("ETF_EU", MONDAY, FRIDAY)

    assert not report.valid
    assert "OHLC_ORDER" in codes(report)
    assert repository.load_bars("ETF_EU").empty


def test_a_reviewed_correction_drops_the_bar_and_stores_the_rest(
    repository: MarketDataRepository,
    instruments: InstrumentRegistry,
    calendars: CalendarRegistry,
    yahoo: FakeSource,
    fred: FakeSource,
    clock: Clock,
) -> None:
    """The session becomes a hole and the four good sessions are ingested."""
    broken_bar(yahoo)
    updater = build_updater(
        repository,
        instruments,
        calendars,
        {"YAHOO": yahoo, "FRED": fred},
        clock,
        bar_corrections=dropping_wednesday(),
    )

    report = updater.download("ETF_EU", MONDAY, FRIDAY)

    assert report.valid
    assert "REVIEWED_BAR_DROPPED" in codes(report)
    assert list(repository.load_bars("ETF_EU")["session_date"]) == [
        MONDAY,
        TUESDAY,
        THURSDAY,
        FRIDAY,
    ]


def test_a_dropped_bar_is_a_hole_the_reader_reports_as_one(
    repository: MarketDataRepository,
    instruments: InstrumentRegistry,
    calendars: CalendarRegistry,
    yahoo: FakeSource,
    fred: FakeSource,
    clock: Clock,
) -> None:
    """Not a price carried over from Tuesday: the session has no price at all."""
    broken_bar(yahoo)
    updater = build_updater(
        repository,
        instruments,
        calendars,
        {"YAHOO": yahoo, "FRED": fred},
        clock,
        bar_corrections=dropping_wednesday(),
    )
    updater.download("ETF_EU", MONDAY, FRIDAY)

    reader = MarketDataReader(
        repository=repository,
        instruments=instruments,
        calendars=calendars,
        reference_calendar_id="XPAR",
    )
    at_close = reader.at(datetime(2026, 3, 11, 20, 0, tzinfo=UTC))
    row = at_close.values(["ETF_EU"]).iloc[0]

    assert row["status"] is ObservationStatus.MISSING


def test_a_rebuild_applies_the_same_corrections_as_the_live_path(
    repository: MarketDataRepository,
    instruments: InstrumentRegistry,
    calendars: CalendarRegistry,
    yahoo: FakeSource,
    fred: FakeSource,
    clock: Clock,
) -> None:
    """Otherwise clean would stop being a function of raw plus the committed config."""
    broken_bar(yahoo)
    updater = build_updater(
        repository,
        instruments,
        calendars,
        {"YAHOO": yahoo, "FRED": fred},
        clock,
        bar_corrections=dropping_wednesday(),
    )
    updater.download("ETF_EU", MONDAY, FRIDAY)
    live = repository.load_bars("ETF_EU")

    report = updater.rebuild_clean("ETF_EU")

    assert "REVIEWED_BAR_DROPPED" in codes(report)
    pd.testing.assert_frame_equal(repository.load_bars("ETF_EU"), live)


def test_a_correction_the_provider_made_obsolete_stops_the_ingestion(
    repository: MarketDataRepository,
    instruments: InstrumentRegistry,
    calendars: CalendarRegistry,
    yahoo: FakeSource,
    fred: FakeSource,
    clock: Clock,
) -> None:
    """The bar is fine now, and a note from last year must not go on dropping it."""
    updater = build_updater(
        repository,
        instruments,
        calendars,
        {"YAHOO": yahoo, "FRED": fred},
        clock,
        bar_corrections=dropping_wednesday(),
    )

    with pytest.raises(ValueError, match="no longer has"):
        updater.download("ETF_EU", MONDAY, FRIDAY)


# ---------------------------------------------------------------------------
# Archiving a history before it disappears
# ---------------------------------------------------------------------------


def test_archiving_asks_for_the_whole_declared_history(
    updater: MarketDataUpdater, yahoo: FakeSource
) -> None:
    """A delisted name cannot be fetched afterwards, so it is fetched in full now."""
    updater.archive_history("ETF_EU")

    asked = [call for call in yahoo.calls if call[0] == "ETF_EU"]
    assert asked[0][1] == MONDAY
    assert asked[0][2] == FRIDAY


def test_a_history_with_no_beginning_cannot_be_asked_for_in_full(
    repository: MarketDataRepository,
    calendars: CalendarRegistry,
    yahoo: FakeSource,
    clock: Clock,
) -> None:
    """Without a first session there is no window to archive."""
    registry = InstrumentRegistry(
        [
            Instrument(
                id="ETF_EU",
                name="Paris ETF",
                asset_type=AssetType.ETF,
                data_type=DataType.BAR,
                currency="EUR",
                primary_source="YAHOO",
                source_symbol="CW8.PA",
                tradable=True,
                calendar_id="XPAR",
            )
        ]
    )
    updater = build_updater(repository, registry, calendars, {"YAHOO": yahoo}, clock)

    with pytest.raises(ValueError, match="no first_session"):
        updater.archive_history("ETF_EU")


def test_coverage_says_a_full_history_is_covered(updater: MarketDataUpdater) -> None:
    """The question the report exists to answer, in its happy case."""
    updater.archive_history("ETF_EU")

    coverage = updater.history_coverage("ETF_EU")

    assert coverage.complete
    assert coverage.stored_from == MONDAY
    assert coverage.missing_head is None


def test_coverage_names_the_history_nobody_fetched(updater: MarketDataUpdater) -> None:
    """A name that was never downloaded is the one that will be lost first."""
    coverage = updater.history_coverage("ETF_EU")

    assert not coverage.complete
    assert coverage.stored_from is None
    assert coverage.raw_fetches == 0
    assert coverage.missing_head == (MONDAY, coverage.declared_until)


def test_coverage_names_the_head_a_partial_store_is_missing(
    updater: MarketDataUpdater,
) -> None:
    """The half that matters: what was never fetched and may never be again."""
    updater.download("ETF_EU", WEDNESDAY, FRIDAY)

    coverage = updater.history_coverage("ETF_EU")

    assert not coverage.complete
    assert coverage.missing_head == (MONDAY, WEDNESDAY)
    assert coverage.raw_fetches > 0


def test_coverage_sees_a_hole_between_two_stored_ends(
    updater: MarketDataUpdater, yahoo: FakeSource
) -> None:
    """Audit A12: Monday and Friday stored, nothing between, used to read ``complete``."""
    week = yahoo.rows["ETF_EU"]
    yahoo.rows["ETF_EU"] = week.loc[week["date"].isin([MONDAY, FRIDAY])].reset_index(drop=True)
    updater.archive_history("ETF_EU")

    coverage = updater.history_coverage("ETF_EU")

    assert coverage.spans_declared_window
    assert not coverage.complete
    assert coverage.missing_sessions == (TUESDAY, WEDNESDAY, THURSDAY)


def test_coverage_names_the_contested_sessions_apart(
    updater: MarketDataUpdater, repository: MarketDataRepository
) -> None:
    """Stored, and served as a hole: not missing, and not to be forgotten either."""
    updater.archive_history("ETF_EU")
    checked = repository.load_checked_bars("ETF_EU")
    checked.loc[checked["session_date"] == WEDNESDAY, "check_status"] = "CONFLICT"
    repository.save_checked_bars("ETF_EU", checked)

    coverage = updater.history_coverage("ETF_EU")

    assert coverage.complete
    assert coverage.contested_sessions == (WEDNESDAY,)


def test_coverage_of_a_published_series_checks_its_ends_only_and_says_so(
    updater: MarketDataUpdater,
) -> None:
    """No venue calendar to count a release series against, so none is invented."""
    updater.archive_history("RATE_US")

    coverage = updater.history_coverage("RATE_US")

    assert coverage.missing_sessions is None
    assert coverage.contested_sessions is None
    assert coverage.complete == coverage.spans_declared_window


def delisted(instruments: InstrumentRegistry, last: date) -> InstrumentRegistry:
    """Return the registry with the Paris ETF delisted on ``last``."""
    return InstrumentRegistry(
        [
            replace(instrument, last_session=last) if instrument.id == "ETF_EU" else instrument
            for instrument in instruments.list_all()
        ]
    )


def test_a_delisted_name_is_never_fetched_past_its_last_session(
    repository: MarketDataRepository,
    instruments: InstrumentRegistry,
    calendars: CalendarRegistry,
    yahoo: FakeSource,
    clock: Clock,
) -> None:
    """Asking for what came after is asking for a ticker somebody else now uses."""
    updater = build_updater(
        repository, delisted(instruments, WEDNESDAY), calendars, {"YAHOO": yahoo}, clock
    )

    updater.archive_history("ETF_EU")

    assert [call[2] for call in yahoo.calls if call[0] == "ETF_EU"] == [WEDNESDAY]


def test_a_delisted_name_already_stored_in_full_is_not_updated_again(
    repository: MarketDataRepository,
    instruments: InstrumentRegistry,
    calendars: CalendarRegistry,
    yahoo: FakeSource,
    clock: Clock,
) -> None:
    """There is nothing to extend, and the archive is the only source left."""
    registry = delisted(instruments, WEDNESDAY)
    updater = build_updater(repository, registry, calendars, {"YAHOO": yahoo}, clock)
    updater.archive_history("ETF_EU")

    with pytest.raises(ValueError, match="delisted"):
        updater.update("ETF_EU")


def test_a_promotion_interrupted_half_way_leaves_the_store_as_it_was(
    updater: MarketDataUpdater,
    repository: MarketDataRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The series and the verdicts computed from it are one change, or none.

    Before the promotion became a transaction, a run that died here left bars
    on disk with no verdicts beside them - a clean layer the next update
    refuses to build on, repaired by hand.
    """

    def die(*_: object, **__: object) -> None:
        raise OSError("the disk went away")

    monkeypatch.setattr(repository, "save_checked_bars", die)

    with pytest.raises(OSError, match="the disk went away"):
        updater.download("ETF_EU", MONDAY, FRIDAY)

    assert repository.load_bars("ETF_EU").empty
    assert repository.load_checked_bars("ETF_EU").empty
    # The raw response is still archived: it is evidence, not part of the change.
    assert repository.list_raw_fetches("ETF_EU", "YAHOO")


@pytest.mark.parametrize("together", [True, False], ids=["one_fetch", "two_fetches"])
def test_a_split_and_a_dividend_on_one_ex_date_are_refused_however_they_arrive(
    updater: MarketDataUpdater,
    repository: MarketDataRepository,
    yahoo: FakeSource,
    together: bool,
) -> None:
    """Audit R08: sent in two fetches, the pair was stored although the validator refuses it.

    The fixture's first fetch carries a dividend on Wednesday. A split on the
    same ex-date is refused whether it comes with it or after it, and a
    refused fetch leaves the actions and the journal as they were.
    """
    if together:
        yahoo.actions["ETF_EU"] = raw_actions(
            [(WEDNESDAY, ActionType.DIVIDEND, 0.5), (WEDNESDAY, ActionType.SPLIT, 2.0)]
        )
        report = updater.download("ETF_EU", MONDAY, FRIDAY)
        assert repository.load_corporate_actions("ETF_EU").empty
    else:
        assert updater.download("ETF_EU", MONDAY, FRIDAY).valid
        before = repository.load_corporate_actions("ETF_EU")
        applied = repository.load_applied_fetches("ETF_EU")
        yahoo.actions["ETF_EU"] = raw_actions([(WEDNESDAY, ActionType.SPLIT, 2.0)])
        report = updater.update("ETF_EU")
        pd.testing.assert_frame_equal(repository.load_corporate_actions("ETF_EU"), before)
        assert repository.load_applied_fetches("ETF_EU") == applied

    assert not report.valid
    assert "SPLIT_WITH_DISTRIBUTION" in [issue.code for issue in report.errors]
