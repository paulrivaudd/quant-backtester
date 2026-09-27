"""A synthetic market to run the real engine on, offline and without a store.

Everything here exists so that a newcomer can run a backtest in ten lines,
before any provider, key or download: the reader, the engine, the execution
model and the report are the project's own, and only the prices are invented.

Nothing in this module is market data, and nothing it produces says anything
about a real instrument:

- the two funds, ``FUND_A`` and ``FUND_B``, are geometric random walks drawn
  from an explicit seed, so the same seed gives the same prices bit for bit;
- the calendar ``DEMO`` copies the Euronext Paris holidays and half days of
  2024 and 2025 for realism, but it is not the committed ``XPAR`` calendar and
  must not stand for it;
- the bars are stored as single-source checked bars, as if one provider had
  served them and no second source had been asked.

The series are invented, so they are never revised: each fund declares
``ASSUMED_UNREVISED``, and the assumption is true by construction.

Availability follows the real convention: a session's open is knowable at the
venue's open and its high, low, close and volume at its close, both in UTC.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, time
from pathlib import Path

import numpy as np
import pandas as pd

from quant_backtester.analytics.config import AnalyticsConfig
from quant_backtester.backtest.runner import StrategyRunner
from quant_backtester.backtest.timetable import BacktestTimetable
from quant_backtester.data.calendars import CalendarRegistry, TradingCalendar
from quant_backtester.data.instruments import (
    AssetType,
    DataType,
    HistoryBasis,
    Instrument,
    InstrumentRegistry,
)
from quant_backtester.data.normalizer import bar_availability
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.data.repository import MarketDataRepository
from quant_backtester.data.schemas import CHECKED_BARS_SCHEMA, BarField, CheckStatus
from quant_backtester.execution.costs import CostModel
from quant_backtester.execution.model import ExecutionModel

DEMO_CALENDAR_ID = "DEMO"
"""The synthetic venue every demo instrument trades on."""

DEMO_START = date(2024, 1, 2)
"""First session of the demo history: a year of warm-up before the demo runs."""

DEMO_END = date(2025, 12, 31)
"""Last session of the demo history."""

DEMO_SESSIONS_PER_YEAR = 255
"""Annualisation of the demo's report: the sessions the ``DEMO`` calendar
holds in 2025, the same convention as the Paris baselines."""

DEMO_RISK_FREE_RATE = 0.02
"""Annual risk-free rate of the demo's Sharpe ratio, as a fraction."""

DEMO_INITIAL_CASH = 10_000.0
"""Cash the demo book starts with, in EUR."""

DEMO_COSTS = CostModel(
    commission_rate=0.0005,
    minimum_commission=1.0,
    half_spread_rate=0.0002,
    slippage_rate=0.0001,
)
"""Five basis points of commission with a one-euro floor, two of half spread
and one of slippage: the assumptions of the baselines, stated again here."""

DEMO_MINIMUM_TRADE = 100.0
"""No demo order below a hundred euros."""

_FETCH_ID = "20260101T000000Z"
"""The download id every demo bar claims: fixed, never the wall clock."""

_ALL_BAR_FIELDS = ",".join(sorted(field.value for field in BarField))
"""Every field of a bar, as the cross-check spells an unconfirmed set."""


@dataclass(frozen=True, slots=True)
class SyntheticFund:
    """How one invented fund's prices are drawn.

    Attributes
    ----------
    instrument_id : str
        Identifier in the demo registry.
    start_price : float
        Open of the first session, in EUR per share.
    annual_drift : float
        Expected log return per year, as a fraction.
    annual_volatility : float
        Standard deviation of the log return over a year, as a fraction. A
        session's is this divided by ``sqrt(DEMO_SESSIONS_PER_YEAR)``.
    """

    instrument_id: str
    start_price: float
    annual_drift: float
    annual_volatility: float

    def __post_init__(self) -> None:
        """Refuse a price that is not positive or a volatility that is negative."""
        if not math.isfinite(self.start_price) or self.start_price <= 0.0:
            raise ValueError(f"{self.instrument_id}: start_price must be positive")
        if not math.isfinite(self.annual_drift):
            raise ValueError(f"{self.instrument_id}: annual_drift must be finite")
        if not math.isfinite(self.annual_volatility) or self.annual_volatility < 0.0:
            raise ValueError(f"{self.instrument_id}: annual_volatility must be non-negative")


DEMO_FUNDS: tuple[SyntheticFund, ...] = (
    SyntheticFund("FUND_A", start_price=100.0, annual_drift=0.06, annual_volatility=0.15),
    SyntheticFund("FUND_B", start_price=50.0, annual_drift=0.02, annual_volatility=0.25),
)
"""A steadier fund and a more volatile one, drawn independently."""


def demo_calendar() -> TradingCalendar:
    """Return the ``DEMO`` venue calendar, 2024-2025.

    Returns
    -------
    TradingCalendar
        Paris hours (09:00-17:30, Europe/Paris) with the Euronext holidays and
        14:05 half days of 2024 and 2025. Any date outside those two years
        raises :class:`~quant_backtester.data.calendars.CalendarCoverageError`.
    """
    holidays = {
        date(2024, 1, 1),
        date(2024, 3, 29),
        date(2024, 4, 1),
        date(2024, 5, 1),
        date(2024, 12, 25),
        date(2024, 12, 26),
        date(2025, 1, 1),
        date(2025, 4, 18),
        date(2025, 4, 21),
        date(2025, 5, 1),
        date(2025, 12, 25),
        date(2025, 12, 26),
    }
    half_days = (date(2024, 12, 24), date(2024, 12, 31), date(2025, 12, 24), date(2025, 12, 31))
    return TradingCalendar(
        calendar_id=DEMO_CALENDAR_ID,
        timezone="Europe/Paris",
        regular_open=time(9, 0),
        regular_close=time(17, 30),
        holidays=frozenset(holidays),
        early_closes={day: time(14, 5) for day in half_days},
        covered_from=date(2024, 1, 1),
        covered_until=DEMO_END,
    )


def demo_instruments(funds: tuple[SyntheticFund, ...] = DEMO_FUNDS) -> InstrumentRegistry:
    """Return the registry of the demo funds.

    Parameters
    ----------
    funds : tuple[SyntheticFund, ...]
        The funds to declare.

    Returns
    -------
    InstrumentRegistry
        One tradable EUR ETF per fund, dealt in whole shares on ``DEMO``,
        listed from :data:`DEMO_START`.
    """
    return InstrumentRegistry(
        [
            Instrument(
                id=fund.instrument_id,
                name=f"Synthetic fund {fund.instrument_id}",
                asset_type=AssetType.ETF,
                data_type=DataType.BAR,
                currency="EUR",
                primary_source="DEMO",
                source_symbol=fund.instrument_id,
                tradable=True,
                quantity_step=1.0,
                calendar_id=DEMO_CALENDAR_ID,
                first_session=DEMO_START,
                history_basis=HistoryBasis.ASSUMED_UNREVISED,
                history_note="Invented by quant_backtester.demo; never revised.",
            )
            for fund in funds
        ]
    )


def draw_bars(
    fund: SyntheticFund, sessions: tuple[date, ...], rng: np.random.Generator
) -> dict[date, tuple[float, float, float, float]]:
    """Draw one fund's open, high, low and close for each session.

    The session's log return is normal with the fund's drift and volatility
    scaled to a session. A third of its variance falls overnight, between the
    previous close and the open, and the rest during the session. The high and
    the low stretch the range between open and close by a half-normal amount.

    Parameters
    ----------
    fund : SyntheticFund
        What to draw.
    sessions : tuple[date, ...]
        The sessions, oldest first.
    rng : numpy.random.Generator
        The only source of randomness; the caller seeds it. Four draws are
        taken per session, in session order, so the bars of a session do not
        depend on how many sessions follow it.

    Returns
    -------
    dict[date, tuple[float, float, float, float]]
        ``(open, high, low, close)`` per session, in EUR, rounded to four
        decimals, with ``low <= min(open, close)`` and ``high >= max(open, close)``.
    """
    per_session = fund.annual_volatility / math.sqrt(DEMO_SESSIONS_PER_YEAR)
    drift = fund.annual_drift / DEMO_SESSIONS_PER_YEAR - per_session**2 / 2.0
    bars: dict[date, tuple[float, float, float, float]] = {}
    previous_close = fund.start_price
    for index, session in enumerate(sessions):
        # Four draws per session, in session order: a session's prices depend
        # on the sessions before it only, so a longer history leaves them be.
        overnight, intraday, up, down = rng.standard_normal(4)
        opening = (
            fund.start_price
            if index == 0
            else previous_close * math.exp(overnight * per_session * math.sqrt(1.0 / 3.0))
        )
        closing = opening * math.exp(drift + intraday * per_session * math.sqrt(2.0 / 3.0))
        high = max(opening, closing) * math.exp(abs(up) * per_session / 2.0)
        low = min(opening, closing) * math.exp(-abs(down) * per_session / 2.0)
        rounded = (round(opening, 4), round(high, 4), round(low, 4), round(closing, 4))
        bars[session] = (rounded[0], max(rounded), min(rounded), rounded[3])
        previous_close = closing
    return bars


def checked_bars_frame(
    instrument_id: str,
    calendar: TradingCalendar,
    bars: dict[date, tuple[float, float, float, float]],
) -> pd.DataFrame:
    """Return drawn bars as the canonical checked-bars table.

    Parameters
    ----------
    instrument_id : str
        The instrument the bars belong to.
    calendar : TradingCalendar
        Its venue calendar, which dates each field's availability.
    bars : dict[date, tuple[float, float, float, float]]
        ``(open, high, low, close)`` per session.

    Returns
    -------
    pandas.DataFrame
        Rows in :data:`~quant_backtester.data.schemas.CHECKED_BARS_SCHEMA`,
        each ``SINGLE_SOURCE`` with every field unconfirmed, as one provider
        with no second source would leave them.
    """
    rows = []
    for session_date, (opening, high, low, closing) in bars.items():
        open_at, close_at = bar_availability(session_date, calendar)
        rows.append(
            {
                "instrument_id": instrument_id,
                "session_date": session_date,
                "open": opening,
                "high": high,
                "low": low,
                "close": closing,
                "volume": 10_000.0,
                "open_available_at_utc": pd.Timestamp(open_at),
                "close_available_at_utc": pd.Timestamp(close_at),
                "source": "DEMO",
                "source_fetch_id": _FETCH_ID,
                "check_status": CheckStatus.SINGLE_SOURCE.value,
                "checked_sources": "DEMO",
                "checked_fetch_ids": f"DEMO:{_FETCH_ID}",
                "conflicting_fields": "",
                "unconfirmed_fields": _ALL_BAR_FIELDS,
                "max_price_rel_diff": float("nan"),
                "max_volume_rel_diff": float("nan"),
            }
        )
    frame = pd.DataFrame(rows, columns=list(CHECKED_BARS_SCHEMA.names))
    for column in ("open_available_at_utc", "close_available_at_utc"):
        frame[column] = frame[column].astype("datetime64[us, UTC]")
    return frame


def build_demo_market(root: Path, *, seed: int) -> MarketDataReader:
    """Write the demo market under ``root`` and return a reader over it.

    Parameters
    ----------
    root : Path
        An empty or missing directory; it becomes the store's root, with
        ``metadata/``, ``raw/``, ``clean/`` and ``validation/`` inside.
    seed : int
        Seed of the demo prices; each fund draws from its own stream spawned
        from it. The same seed writes the same prices bit for bit.

    Returns
    -------
    MarketDataReader
        The project's reader over the demo store, counting staleness on
        ``DEMO``.

    Raises
    ------
    ValueError
        If ``root`` exists and is not empty: the demo never writes over
        something it did not make.
    """
    if root.exists() and any(root.iterdir()):
        raise ValueError(f"{root} is not empty; the demo writes a new store only")
    for subdir in ("metadata", "raw", "clean", "validation"):
        (root / subdir).mkdir(parents=True, exist_ok=True)
    calendar = demo_calendar()
    instruments = demo_instruments()
    sessions = tuple(day.session_date for day in calendar.sessions(DEMO_START, DEMO_END))
    # One stream per fund, spawned from the seed: each fund's prices depend on
    # the seed and its own sessions only.
    streams = np.random.SeedSequence(seed).spawn(len(DEMO_FUNDS))
    repository = MarketDataRepository(root)
    for fund, stream in zip(DEMO_FUNDS, streams, strict=True):
        bars = draw_bars(fund, sessions, np.random.default_rng(stream))
        repository.save_checked_bars(
            fund.instrument_id, checked_bars_frame(fund.instrument_id, calendar, bars)
        )
    return MarketDataReader(
        repository=repository,
        instruments=instruments,
        calendars=CalendarRegistry([calendar]),
        reference_calendar_id=DEMO_CALENDAR_ID,
    )


def demo_runner(root: Path, *, seed: int) -> StrategyRunner:
    """Return a runner over a fresh demo market, with every assumption stated.

    Parameters
    ----------
    root : Path
        Where the demo store is written; see :func:`build_demo_market`.
    seed : int
        Seed of the demo prices.

    Returns
    -------
    StrategyRunner
        Decisions at 23:00 Paris and fills at the next 09:01 open, the costs of
        :data:`DEMO_COSTS`, whole shares, :data:`DEMO_INITIAL_CASH` EUR, and
        ``FUND_A`` held without costs as the benchmark.
    """
    reader = build_demo_market(root, seed=seed)
    return StrategyRunner(
        reader=reader,
        calendars=reader.calendars,
        reference_calendar_id=DEMO_CALENDAR_ID,
        base_currency="EUR",
        analytics=AnalyticsConfig(
            sessions_per_year=DEMO_SESSIONS_PER_YEAR, risk_free_rate=DEMO_RISK_FREE_RATE
        ),
        execution=ExecutionModel(costs=DEMO_COSTS, minimum_trade_value=DEMO_MINIMUM_TRADE),
        initial_cash=DEMO_INITIAL_CASH,
        timetable=BacktestTimetable(
            decision_time=time(23, 0), execution_time=time(9, 1), valuation_time=time(23, 0)
        ),
        benchmark="FUND_A",
    )
