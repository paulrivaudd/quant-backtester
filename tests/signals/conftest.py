"""A small synthetic market, and the context a signal computes against.

Everything is hand-checkable on purpose. The prices rise by a fixed step so that
a momentum, a moving average and a drawdown all have an answer anyone can work
out on paper, and the awkward cases - a session the venue held and the series
lacks, a value two sources contest, a fund that listed last month, a market shut
while another trades - are introduced one at a time.

The builders are fixtures rather than importable helpers so that the tests in
``price/`` and ``risk/`` see them without any import path arrangement.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from quant_backtester.data.calendars import CalendarRegistry, TradingCalendar
from quant_backtester.data.instruments import (
    AssetType,
    DataType,
    Instrument,
    InstrumentRegistry,
    PublicationRule,
)
from quant_backtester.data.normalizer import bar_availability
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.data.repository import MarketDataRepository
from quant_backtester.data.schemas import (
    CHECKED_BARS_SCHEMA,
    CORPORATE_ACTIONS_SCHEMA,
    ActionType,
    BarField,
    CheckStatus,
)
from quant_backtester.signals.context import SignalContext

PARIS = ZoneInfo("Europe/Paris")

SESSIONS: tuple[date, ...] = (
    date(2026, 9, 1),
    date(2026, 9, 2),
    date(2026, 9, 3),
    date(2026, 9, 4),
    date(2026, 9, 7),
    date(2026, 9, 8),
    date(2026, 9, 9),
    date(2026, 9, 10),
    date(2026, 9, 11),
    date(2026, 9, 14),
)
"""Ten Paris sessions of September 2026, with two weekends inside them.

Monday 7 September is one of them, and it is the day New York is shut: the two
calendars disagree inside this span, which is what makes a cross-market
staleness testable without inventing a holiday.
"""

US_SESSIONS: tuple[date, ...] = tuple(day for day in SESSIONS if day != date(2026, 9, 7))
"""The same span as New York holds it: nine sessions, Labor Day missing."""

DECISION = SESSIONS[-1]
"""The session most tests take their decision after the close of."""

ALL_BAR_FIELDS = ",".join(sorted(field.value for field in BarField))
"""Every field of a bar, as the cross-check spells an unconfirmed set."""

BarsBuilder = Callable[..., pd.DataFrame]
MarketBuilder = Callable[..., MarketDataReader]
ContextBuilder = Callable[[MarketDataReader, datetime], SignalContext]


def paris(day: date, hour: int, minute: int = 0) -> datetime:
    """Return a Paris wall-clock instant, timezone-aware."""
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=PARIS)


def rising(start: float, step: float, sessions: Sequence[date] = SESSIONS) -> dict[date, float]:
    """Return a price rising by ``step`` each session, oldest first."""
    return {session: start + step * index for index, session in enumerate(sessions)}


@pytest.fixture
def make_bars() -> BarsBuilder:
    """Return a builder of checked bars from ``session_date -> close``.

    The builder takes the instrument id, its venue calendar, the closes, and
    optionally the fields two sources disagreed on per session. A contested
    field is how a hole is introduced without deleting a row: the reader
    refuses to serve it, exactly as it does on real data.
    """

    def build(
        instrument_id: str,
        calendar: TradingCalendar,
        closes: Mapping[date, float],
        *,
        contested: Mapping[date, Sequence[BarField]] | None = None,
    ) -> pd.DataFrame:
        rows = []
        for session_date, close in closes.items():
            open_at, close_at = bar_availability(session_date, calendar)
            fields = sorted(field.value for field in (contested or {}).get(session_date, ()))
            rows.append(
                {
                    "instrument_id": instrument_id,
                    "session_date": session_date,
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": 1_000.0,
                    "open_available_at_utc": pd.Timestamp(open_at),
                    "close_available_at_utc": pd.Timestamp(close_at),
                    "source": "YAHOO",
                    "source_fetch_id": "20260916T000000Z",
                    "check_status": (
                        CheckStatus.CONFLICT.value if fields else CheckStatus.SINGLE_SOURCE.value
                    ),
                    "checked_sources": "EURONEXT,YAHOO" if fields else "YAHOO",
                    "checked_fetch_ids": "YAHOO:20260916T000000Z",
                    "conflicting_fields": ",".join(fields),
                    "unconfirmed_fields": "" if fields else ALL_BAR_FIELDS,
                    "max_price_rel_diff": 1e-3 if fields else float("nan"),
                    "max_volume_rel_diff": float("nan"),
                }
            )
        frame = pd.DataFrame(rows, columns=list(CHECKED_BARS_SCHEMA.names))
        for column in ("open_available_at_utc", "close_available_at_utc"):
            frame[column] = frame[column].astype("datetime64[us, UTC]")
        return frame

    return build


@pytest.fixture
def make_actions() -> Callable[
    [Sequence[tuple[str, ActionType, date, float, datetime]]], pd.DataFrame
]:
    """Return a builder of corporate actions from tuples."""

    def build(
        rows: Sequence[tuple[str, ActionType, date, float, datetime]],
    ) -> pd.DataFrame:
        frame = pd.DataFrame(
            [
                {
                    "instrument_id": instrument_id,
                    "action_type": action_type.value,
                    "ex_date": ex_date,
                    "value": value,
                    "available_at_utc": pd.Timestamp(available_at),
                    "source": "YAHOO",
                    "source_fetch_id": "20260916T000000Z",
                }
                for instrument_id, action_type, ex_date, value, available_at in rows
            ],
            columns=list(CORPORATE_ACTIONS_SCHEMA.names),
        )
        frame["available_at_utc"] = frame["available_at_utc"].astype("datetime64[us, UTC]")
        return frame

    return build


@pytest.fixture
def calendars(xnys: TradingCalendar, xpar: TradingCalendar) -> CalendarRegistry:
    """Return the two venue calendars."""
    return CalendarRegistry([xnys, xpar])


@pytest.fixture
def instruments() -> InstrumentRegistry:
    """Return one instrument per situation a window loader must tell apart."""
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
                first_session=date(2026, 1, 5),
            ),
            Instrument(
                id="ETF_OTHER",
                name="A second Paris ETF",
                asset_type=AssetType.ETF,
                data_type=DataType.BAR,
                currency="EUR",
                primary_source="YAHOO",
                source_symbol="OTHER.PA",
                tradable=True,
                calendar_id="XPAR",
                first_session=date(2026, 1, 5),
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
                first_session=date(2026, 1, 2),
            ),
            Instrument(
                id="ETF_LATE",
                name="ETF listed this month",
                asset_type=AssetType.ETF,
                data_type=DataType.BAR,
                currency="EUR",
                primary_source="YAHOO",
                source_symbol="LATE.PA",
                tradable=True,
                calendar_id="XPAR",
                first_session=date(2026, 9, 9),
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
                publication_rule=PublicationRule(
                    publication_time=time(16, 15), timezone="America/New_York"
                ),
                first_session=date(2026, 1, 2),
            ),
        ]
    )


@pytest.fixture
def repository(market_root: Path) -> MarketDataRepository:
    """Return an empty repository on a temporary tree."""
    return MarketDataRepository(market_root)


@pytest.fixture
def make_market(
    repository: MarketDataRepository,
    instruments: InstrumentRegistry,
    calendars: CalendarRegistry,
) -> MarketBuilder:
    """Return a builder of a reader over exactly the series a test needs.

    Staleness is counted on XPAR, the calendar a European strategy decides on,
    which is what makes a US close read on Labor Day one session old rather
    than perfectly fresh.
    """

    def build(
        bars: Mapping[str, pd.DataFrame], actions: pd.DataFrame | None = None
    ) -> MarketDataReader:
        for instrument_id, frame in bars.items():
            repository.save_checked_bars(instrument_id, frame)
        if actions is not None:
            repository.save_corporate_actions(actions)
        return MarketDataReader(
            repository=repository,
            instruments=instruments,
            calendars=calendars,
            reference_calendar_id="XPAR",
        )

    return build


@pytest.fixture
def make_context(calendars: CalendarRegistry) -> ContextBuilder:
    """Return a builder of the context of one decision instant."""

    def build(market: MarketDataReader, instant: datetime) -> SignalContext:
        return SignalContext(
            market=market.at(instant),
            instruments=market.instruments,
            calendars=calendars,
        )

    return build


@pytest.fixture
def market(
    make_market: MarketBuilder,
    make_bars: BarsBuilder,
    xpar: TradingCalendar,
    xnys: TradingCalendar,
) -> MarketDataReader:
    """Return a reader over three instruments, each there for a reason.

    ``ETF_EU`` rises by one a session over the ten sessions of the span, which
    is what makes every formula checkable by hand. ``IDX_US`` reaches a month
    further back so that a decision taken early in the span still has history
    behind it, and lives on the calendar that is shut on 7 September.
    ``ETF_LATE`` has four sessions, one short of what any V1 signal needs.
    """
    us_start = date(2026, 8, 17)
    us_days = [session.session_date for session in xnys.sessions(us_start, DECISION)]
    return make_market(
        {
            "ETF_EU": make_bars("ETF_EU", xpar, rising(100.0, 1.0)),
            "IDX_US": make_bars("IDX_US", xnys, rising(5_000.0, 10.0, us_days)),
            "ETF_LATE": make_bars("ETF_LATE", xpar, rising(50.0, 1.0, SESSIONS[6:])),
        }
    )


@pytest.fixture
def context(market: MarketDataReader, make_context: ContextBuilder) -> SignalContext:
    """Return the context of a decision taken after the close of 14 September."""
    return make_context(market, paris(DECISION, 23, 0))


@pytest.fixture
def sessions() -> tuple[date, ...]:
    """Return the ten Paris sessions the synthetic market spans."""
    return SESSIONS


@pytest.fixture
def us_sessions() -> tuple[date, ...]:
    """Return the same span as New York holds it, Labor Day missing."""
    return US_SESSIONS


@pytest.fixture
def evening() -> Callable[[date], datetime]:
    """Return a builder of "after the Paris close of" instants."""

    def build(day: date) -> datetime:
        return paris(day, 23, 0)

    return build


@pytest.fixture
def prices() -> Callable[..., dict[date, float]]:
    """Return a builder of a price rising by a fixed step each session."""
    return rising
