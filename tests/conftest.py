"""Shared pytest fixtures: the synthetic market every layer above data runs on.

Keep fixtures deterministic: no network access, no wall-clock dependence, and
no reliance on files outside `tests/`.

The two venue calendars are synthetic and cover 2026 only. That is enough:
every situation that breaks a layer - a venue closed while another trades, a
half day, a DST switch falling between two markets - happens in that year, and
the committed calendars can then grow without moving a test.

The market itself is hand-checkable on purpose. The prices rise by a fixed step
so that a momentum, a moving average and a drawdown all have an answer anyone
can work out on paper, and the awkward cases - a session the venue held and the
series lacks, a value two sources contest, a fund that listed last month, a
market shut while another trades - are introduced one at a time.

It lives here rather than beside the signal tests because the strategy tests
build on the same one, and two copies of a holiday list drift. The data tests
define their own ``instruments``, ``repository`` and ``calendars``, which
override these.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from quant_backtester.analytics.config import AnalyticsConfig
from quant_backtester.backtest.context import StrategyContext
from quant_backtester.backtest.market import StrategyMarketView
from quant_backtester.backtest.runner import StrategyRunner
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
    LEVELS_SCHEMA,
    ActionType,
    BarField,
    CheckStatus,
)
from quant_backtester.demo import checked_bars_frame
from quant_backtester.execution.costs import CostModel
from quant_backtester.execution.model import ExecutionModel, Sizing
from quant_backtester.ml.config import NeuralStrategyConfig
from quant_backtester.ml.signatures.artifacts import (
    ScheduleEntry,
    SignatureArtifact,
    SignatureModelSchedule,
)
from quant_backtester.ml.signatures.config import (
    ModelKind,
    SignatureModelConfig,
    SignatureTrainingConfig,
    SignatureVariant,
)
from quant_backtester.ml.signatures.models import LinearWeights
from quant_backtester.portfolio.holdings import Holding
from quant_backtester.portfolio.state import PortfolioState
from quant_backtester.portfolio.view import PortfolioView
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.signatures.logsignature import FeatureKind, FeatureSpec
from quant_backtester.signals.signatures.path import SignaturePathConfig
from quant_backtester.signals.snapshot import SignalSnapshot


@pytest.fixture(scope="session")
def rng_seed() -> int:
    """Return the single seed used by every test that needs randomness."""
    return 20240101


@pytest.fixture
def xnys() -> TradingCalendar:
    """Return a minimal NYSE calendar covering the tricky dates of 2026.

    Holidays: two Mondays (MLK Day 19 January, Labor Day 7 September),
    Thanksgiving (Thursday 26 November) and Christmas. Half days: 27 November and
    24 December, closing 13:00 ET. The US DST switches of 8 March and 1 November
    fall inside the year, so sessions on either side of each are covered.

    Synthetic on purpose: the committed ``XNYS.toml`` can grow without moving
    these tests.
    """
    return TradingCalendar(
        calendar_id="XNYS",
        timezone="America/New_York",
        regular_open=time(9, 30),
        regular_close=time(16, 0),
        holidays=frozenset(
            {date(2026, 1, 19), date(2026, 9, 7), date(2026, 11, 26), date(2026, 12, 25)}
        ),
        early_closes={date(2026, 11, 27): time(13, 0), date(2026, 12, 24): time(13, 0)},
        covered_from=date(2026, 1, 1),
        covered_until=date(2026, 12, 31),
    )


@pytest.fixture
def xpar() -> TradingCalendar:
    """Return a minimal Euronext Paris calendar for 2026.

    Easter Monday (6 April) closes Paris while New York trades: the day that
    tests the two calendars disagreeing. 1 November, the usual example, is a
    Sunday in 2026 - and not a Euronext holiday anyway. Half days: 24 and 31
    December, closing 14:05 CET.
    """
    return TradingCalendar(
        calendar_id="XPAR",
        timezone="Europe/Paris",
        regular_open=time(9, 0),
        regular_close=time(17, 30),
        holidays=frozenset(
            {date(2026, 4, 3), date(2026, 4, 6), date(2026, 5, 1), date(2026, 12, 25)}
        ),
        early_closes={date(2026, 12, 24): time(14, 5), date(2026, 12, 31): time(14, 5)},
        covered_from=date(2026, 1, 1),
        covered_until=date(2026, 12, 31),
    )


@pytest.fixture
def market_root(tmp_path: Path) -> Path:
    """Return an empty market data root.

    Notes
    -----
    Exercice T.2. Cree ``metadata/``, ``raw/``, ``clean/`` et ``validation/``.
    """
    for subdir in ("metadata", "raw", "clean", "validation"):
        (tmp_path / subdir).mkdir()
    return tmp_path


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
LevelsBuilder = Callable[..., pd.DataFrame]
MarketBuilder = Callable[..., MarketDataReader]
ContextBuilder = Callable[[MarketDataReader, datetime], SignalContext]
DecisionBuilder = Callable[..., StrategyContext]
BookBuilder = Callable[..., PortfolioState]

BOOK_START = datetime(2026, 9, 1, 9, 1, tzinfo=ZoneInfo("Europe/Paris"))
"""When a hand-built book starts to hold: the first open of the synthetic span."""


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
def make_levels(instruments: InstrumentRegistry) -> LevelsBuilder:
    """Return a builder of clean levels from ``observation_date -> value``.

    A published series has no venue sessions, so its rows carry no calendar:
    what makes a value knowable is the instrument's publication rule, and the
    builder asks the registry for it rather than inventing an instant.
    """

    def build(instrument_id: str, values: Mapping[date, float]) -> pd.DataFrame:
        rule = instruments.get(instrument_id).publication_rule
        if rule is None:
            raise ValueError(f"{instrument_id} declares no publication rule")
        frame = pd.DataFrame(
            [
                {
                    "instrument_id": instrument_id,
                    "observation_date": observation_date,
                    "value": value,
                    "available_at_utc": pd.Timestamp(rule.available_at(observation_date)),
                    "source": "FRED",
                    "source_fetch_id": "20260916T000000Z",
                }
                for observation_date, value in values.items()
            ],
            columns=list(LEVELS_SCHEMA.names),
        )
        frame["available_at_utc"] = frame["available_at_utc"].astype("datetime64[us, UTC]")
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
    """Return one instrument per situation a window loader must tell apart.

    ``ETF_US`` is the tradable one whose venue is not the reference calendar:
    it is held, and its close is a session old whenever New York is shut while
    Paris trades. It is also the one that is quoted in another currency and
    the one that deals in whole shares.
    """
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
                id="ETF_US",
                name="A New York ETF, quoted in dollars",
                asset_type=AssetType.ETF,
                data_type=DataType.BAR,
                currency="USD",
                primary_source="YAHOO",
                source_symbol="US.N",
                tradable=True,
                quantity_step=1.0,
                calendar_id="XNYS",
                first_session=date(2026, 1, 2),
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
        bars: Mapping[str, pd.DataFrame],
        actions: pd.DataFrame | None = None,
        levels: Mapping[str, pd.DataFrame] | None = None,
    ) -> MarketDataReader:
        for instrument_id, frame in bars.items():
            repository.save_checked_bars(instrument_id, frame)
        for instrument_id, frame in (levels or {}).items():
            repository.save_levels(instrument_id, frame)
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
    """Return a reader over four instruments, each there for a reason.

    ``ETF_EU`` rises by one a session over the ten sessions of the span, which
    is what makes every formula checkable by hand. ``ETF_OTHER`` rises faster
    on the same venue, which is what makes a rotation between two tradable
    funds testable at all. ``IDX_US`` reaches a month further back so that a
    decision taken early in the span still has history behind it, and lives on
    the calendar that is shut on 7 September. ``ETF_LATE`` has four sessions,
    one short of what any V1 signal needs.
    """
    us_start = date(2026, 8, 17)
    us_days = [session.session_date for session in xnys.sessions(us_start, DECISION)]
    return make_market(
        {
            "ETF_EU": make_bars("ETF_EU", xpar, rising(100.0, 1.0)),
            "ETF_OTHER": make_bars("ETF_OTHER", xpar, rising(200.0, 3.0)),
            "IDX_US": make_bars("IDX_US", xnys, rising(5_000.0, 10.0, us_days)),
            "ETF_LATE": make_bars("ETF_LATE", xpar, rising(50.0, 1.0, SESSIONS[6:])),
        }
    )


@pytest.fixture
def context(market: MarketDataReader, make_context: ContextBuilder) -> SignalContext:
    """Return the context of a decision taken after the close of 14 September."""
    return make_context(market, paris(DECISION, 23, 0))


@pytest.fixture
def make_decision(instruments: InstrumentRegistry) -> DecisionBuilder:
    """Return a builder of the context a strategy is handed at one decision.

    The engine builds one of these per session; a test about a strategy builds
    it directly, so that what is under test is the decision and not the loop
    around it. Everything defaults to the simplest honest thing: a book of cash
    with no positions, and a universe of every tradable instrument the snapshot
    speaks about.
    """

    def build(
        context: SignalContext,
        snapshot: SignalSnapshot,
        universe: Sequence[str] | None = None,
        holdings: PortfolioState | None = None,
        prices: Mapping[str, float] | None = None,
    ) -> StrategyContext:
        if universe is None:
            names: list[str] = []
            for signal_id in snapshot:
                for name in snapshot.result(signal_id).instruments():
                    if name not in names and instruments.get(name).tradable:
                        names.append(name)
            universe = tuple(names)
        book = PortfolioState.opening(10_000.0, BOOK_START) if holdings is None else holdings
        return StrategyContext(
            as_of=snapshot.as_of,
            signals=snapshot,
            market=StrategyMarketView(context),
            portfolio=PortfolioView.of(book, dict(prices or {}), snapshot.as_of),
            universe=tuple(universe),
            instruments=instruments,
        )

    return build


def book_of(
    cash: float,
    quantities: Mapping[str, float] | None = None,
    as_of: datetime = BOOK_START,
    average_costs: Mapping[str, float] | None = None,
) -> PortfolioState:
    """Return a book holding ``cash`` and the given quantities.

    Average costs are unknown unless given: a book written by hand has no
    history, and inventing one would make a stop-loss test pass for the wrong
    reason.
    """
    costs = average_costs or {}
    return PortfolioState(
        as_of=as_of,
        cash=cash,
        holdings={
            name: Holding(name, size, costs.get(name)) for name, size in (quantities or {}).items()
        },
    )


@pytest.fixture
def make_book() -> BookBuilder:
    """Return a builder of a book from its cash and its quantities."""
    return book_of


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


# --- the market a fitted model is calibrated on --------------------------------------
#
# Ten sessions are enough for a moving average and not for a training set, so
# the tests of ``quant_backtester.ml`` run on a longer market: two Paris funds
# with an open apart from their close, drawn from a seed over every session of
# 2026, and a published level for every weekday. The model itself is kept small
# - six observations of history - so that every window can still be checked by
# hand and a calibration takes a second.

NEURAL_FUNDS = ("ETF_EU", "ETF_OTHER")
"""The two funds a test model may buy."""

NEURAL_LEVEL = "RATE_US"
"""The published series a test model reads the level of."""

NEURAL_TEST_PERIOD = (date(2026, 9, 1), date(2026, 10, 30))
"""A period after the calibration of :func:`neural_config`: its final test."""

Bars = dict[str, dict[date, tuple[float, float, float, float]]]
Levels = dict[date, float]
Mutation = Callable[[Bars, Levels], None]
NeuralMarketBuilder = Callable[..., MarketDataReader]
NeuralRunnerBuilder = Callable[..., StrategyRunner]


def neural_prices(calendar: TradingCalendar, seed: int) -> tuple[Bars, Levels]:
    """Return the drawn bars of the two funds and the level of every weekday of 2026.

    A session's open is drawn around the previous close and its close around
    its open, in session order, so a session's prices depend on the sessions
    before it only.
    """
    rng = np.random.default_rng(seed)
    sessions = [day.session_date for day in calendar.sessions(date(2026, 1, 5), date(2026, 12, 31))]
    bars: Bars = {}
    for name, start, drift in zip(NEURAL_FUNDS, (100.0, 40.0), (0.0006, -0.0002), strict=True):
        close = start
        bars[name] = {}
        for session in sessions:
            overnight, intraday = rng.standard_normal(2)
            opening = close * float(np.exp(0.004 * overnight))
            close = opening * float(np.exp(drift + 0.008 * intraday))
            bars[name][session] = (
                round(opening, 4),
                round(max(opening, close), 4),
                round(min(opening, close), 4),
                round(close, 4),
            )
    levels: Levels = {}
    day = date(2026, 1, 2)
    while day <= date(2026, 12, 31):
        if day.weekday() < 5:
            levels[day] = round(18.0 + 6.0 * float(np.sin(len(levels) / 9.0)), 4)
        day = date.fromordinal(day.toordinal() + 1)
    return bars, levels


@pytest.fixture
def neural_config() -> NeuralStrategyConfig:
    """Return a model small enough to check by hand and to calibrate in a second.

    Six observations of history, averages over 2, 3 and 6 of them, volatilities
    over 2 and 4 returns: the layout of the real model, 9 inputs a series
    instead of 106. Trained from January to June 2026, selected on July and
    August, which leaves September onwards for a test.
    """
    return NeuralStrategyConfig(
        calibration_start=date(2026, 1, 12),
        validation_start=date(2026, 7, 1),
        calibration_end=date(2026, 8, 31),
        feature_ids=(*NEURAL_FUNDS, NEURAL_LEVEL),
        tradable_ids=NEURAL_FUNDS,
        history_sessions=6,
        ma_windows=(2, 3, 6),
        vol_windows=(2, 4),
        max_asset_weight=1.0,
        min_asset_weight=0.01,
        rebalance_band=0.03,
        risk_aversion=5.0,
        seed=42,
        level_id=NEURAL_LEVEL,
        encoder_width=3,
        hidden_width=4,
        max_epochs=6,
        validation_every=2,
        minimum_training_decisions=100,
        minimum_validation_sessions=20,
    )


@pytest.fixture
def make_neural_market(
    tmp_path: Path,
    instruments: InstrumentRegistry,
    calendars: CalendarRegistry,
    xpar: TradingCalendar,
    make_levels: LevelsBuilder,
    rng_seed: int,
) -> NeuralMarketBuilder:
    """Return a builder of a store of its own holding the drawn market.

    ``mutate`` receives the drawn bars and levels and may edit them before
    they are written: that is how a test changes what happens after a date,
    removes an observation or introduces a split, on a second store, and
    compares what two calibrations or two decisions made of it.
    """

    def build(
        name: str = "neural",
        *,
        mutate: Mutation | None = None,
        actions: pd.DataFrame | None = None,
    ) -> MarketDataReader:
        root = tmp_path / name
        for subdir in ("metadata", "raw", "clean", "validation"):
            (root / subdir).mkdir(parents=True)
        bars, levels = neural_prices(xpar, rng_seed)
        if mutate is not None:
            mutate(bars, levels)
        repository = MarketDataRepository(root)
        for instrument_id, drawn in bars.items():
            repository.save_checked_bars(
                instrument_id, checked_bars_frame(instrument_id, xpar, drawn)
            )
        repository.save_levels(NEURAL_LEVEL, make_levels(NEURAL_LEVEL, levels))
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
def neural_market(make_neural_market: NeuralMarketBuilder) -> MarketDataReader:
    """Return the drawn market, as written."""
    return make_neural_market()


@pytest.fixture
def make_neural_runner(calendars: CalendarRegistry) -> NeuralRunnerBuilder:
    """Return a builder of the runner a model is validated and tested with."""

    def build(reader: MarketDataReader, *, cost_scale: float = 1.0) -> StrategyRunner:
        return StrategyRunner(
            reader=reader,
            calendars=calendars,
            reference_calendar_id="XPAR",
            base_currency="EUR",
            analytics=AnalyticsConfig(sessions_per_year=252, risk_free_rate=0.0),
            execution=ExecutionModel(
                costs=CostModel(
                    commission_rate=0.0005 * cost_scale,
                    minimum_commission=1.0 * cost_scale,
                    half_spread_rate=0.0003 * cost_scale,
                    slippage_rate=0.0002 * cost_scale,
                ),
                sizing=Sizing.AT_DECISION,
            ),
            initial_cash=100_000.0,
        )

    return build


@pytest.fixture
def neural_artifact(neural_config: NeuralStrategyConfig):
    """Return an untrained model of :func:`neural_config`, with a fitted-looking scaler.

    The parameters are those of a seeded initialisation: enough to test what
    is read, proposed, decided and stored, none of which depends on a model
    being any good. Its information stops at the end of the validation period.
    """
    torch = pytest.importorskip("torch")
    from quant_backtester.ml.artifacts import NeuralArtifact
    from quant_backtester.ml.features import FeatureScaler
    from quant_backtester.ml.network import NeuralAllocator

    torch.manual_seed(7)
    state = {
        name: values.numpy().copy()
        for name, values in NeuralAllocator(neural_config).state_dict().items()
    }
    size = neural_config.input_size
    scaler = FeatureScaler(np.full(size, 0.01), np.full(size, 0.05), neural_config.clip)
    return NeuralArtifact(
        config=neural_config,
        state=state,
        scaler=scaler,
        information_cutoff=paris(neural_config.calibration_end, 23, 0),
        selected_epoch=0,
    )


# --- the market a signature model reads -----------------------------------------------
#
# A log-signature needs a window of closes and of volumes, and a calibration
# needs months of them: the tests of the signature models run on two Paris
# funds drawn from a seed over every session of 2026, with an open apart from
# the close and a volume that changes every session. The path is kept short -
# ten increments after ten sessions of reference - so that a calibration still
# has room for a training and a validation block inside one year.

SIGNATURE_FUNDS = ("ETF_EU", "ETF_OTHER")
"""The fund a test model forecasts, and the one a context variant also reads."""

SIGNATURE_PATH = SignaturePathConfig(
    steps=10,
    volume_reference_sessions=10,
    price_scale=100.0,
    use_volume=True,
    max_age_sessions=0,
)
"""Ten increments described after ten sessions of reference: twenty sessions of history."""

SIGNATURE_CUT = SignatureTrainingConfig(
    training_candidate_origins=80,
    validation_candidate_origins=30,
    minimum_training_examples=60,
    minimum_validation_examples=20,
    minimum_valid_share=0.9,
)
"""Blocks a year of sessions can hold several of."""

SignatureMarketBuilder = Callable[..., MarketDataReader]
SignatureMutation = Callable[[dict[str, pd.DataFrame]], None]


def signature_frames(calendar: TradingCalendar, seed: int) -> dict[str, pd.DataFrame]:
    """Return the drawn bars of the two funds, with a volume of their own each session."""
    rng = np.random.default_rng(seed)
    sessions = [day.session_date for day in calendar.sessions(date(2026, 1, 5), date(2026, 12, 31))]
    frames: dict[str, pd.DataFrame] = {}
    for name, start in zip(SIGNATURE_FUNDS, (100.0, 40.0), strict=True):
        close = start
        drawn = {}
        volumes = []
        for session in sessions:
            overnight, intraday, activity = rng.standard_normal(3)
            opening = close * float(np.exp(0.004 * overnight))
            close = opening * float(np.exp(0.0004 + 0.008 * intraday))
            drawn[session] = (opening, max(opening, close), min(opening, close), close)
            volumes.append(float(round(5_000.0 * float(np.exp(0.5 * activity)))))
        frame = checked_bars_frame(name, calendar, drawn)
        frame["volume"] = volumes
        frames[name] = frame
    return frames


def signature_model(kind: ModelKind = ModelKind.NEURAL_ADDITIVE) -> SignatureModelConfig:
    """Return the model of the specification, with a short fit."""
    return SignatureModelConfig(
        kind=kind,
        hidden_units=4,
        learning_rate=1e-3,
        weight_decay=1e-3,
        max_epochs=40,
        patience=10,
        minimum_improvement=1e-6,
        gradient_clip_norm=1.0,
        seed=20261010,
        input_clip=5.0,
        target_scale=100.0,
        ridge_alpha=10.0,
    )


def signature_variant(
    variant_id: str = "test_logsig3",
    *,
    kind: ModelKind = ModelKind.RIDGE,
    features: FeatureKind = FeatureKind.LOGSIGNATURE,
    depth: int = 3,
    instruments: tuple[str, ...] = ("ETF_EU",),
    path: SignaturePathConfig = SIGNATURE_PATH,
) -> SignatureVariant:
    """Return a small variant forecasting ``ETF_EU``."""
    return SignatureVariant(
        variant_id=variant_id,
        instrument_id="ETF_EU",
        features=FeatureSpec(features, path, depth, instruments),
        model=signature_model(kind),
        training=SIGNATURE_CUT,
    )


@pytest.fixture
def make_signature_market(
    tmp_path: Path,
    instruments: InstrumentRegistry,
    calendars: CalendarRegistry,
    xpar: TradingCalendar,
    rng_seed: int,
) -> SignatureMarketBuilder:
    """Return a builder of a store of its own holding the two drawn funds.

    ``mutate`` receives the frames of bars before they are written: that is
    how a test changes a price or a volume after a date, on a second store,
    and compares what two decisions or two calibrations made of it.
    """

    def build(
        name: str = "signatures", *, mutate: SignatureMutation | None = None
    ) -> MarketDataReader:
        root = tmp_path / name
        for subdir in ("metadata", "raw", "clean", "validation"):
            (root / subdir).mkdir(parents=True)
        frames = signature_frames(xpar, rng_seed)
        if mutate is not None:
            mutate(frames)
        repository = MarketDataRepository(root)
        for instrument_id, frame in frames.items():
            repository.save_checked_bars(instrument_id, frame)
        return MarketDataReader(
            repository=repository,
            instruments=instruments,
            calendars=calendars,
            reference_calendar_id="XPAR",
        )

    return build


def linear_artifact(
    variant: SignatureVariant,
    month: str,
    cutoff: datetime,
    *,
    coefficients: Sequence[float] | None = None,
    bias: float = 0.0,
    available_after: timedelta = timedelta(hours=12),
) -> SignatureArtifact:
    """Return a hand-written linear model of a variant, with an identity scaler.

    Enough to test what is read, forecast, decided and stored: none of that
    depends on a model being any good.
    """
    names = variant.features.names()
    weights = LinearWeights(
        np.asarray(
            [0.0] * len(names) if coefficients is None else list(coefficients), dtype=np.float64
        ),
        bias,
    )
    return SignatureArtifact(
        variant=variant.definition(),
        weights=weights,
        scaler_mean=np.zeros(len(names)),
        scaler_std=np.ones(len(names)),
        feature_names=names,
        month=month,
        information_cutoff=cutoff,
        available_at=cutoff + available_after,
        training_start=date(2026, 1, 5),
        training_end=date(2026, 6, 30),
        validation_start=date(2026, 7, 1),
        validation_end=date(2026, 8, 31),
        training_examples=100,
        validation_examples=30,
        selected_epoch=None,
        training_label_mean=0.0004,
        environment={"backend": "test"},
    )


@pytest.fixture
def signature_path() -> SignaturePathConfig:
    """Return the short path of the signature tests: ten increments after ten of reference."""
    return SIGNATURE_PATH


@pytest.fixture
def signature_variant_of() -> Callable[..., SignatureVariant]:
    """Return the builder of a small variant forecasting ``ETF_EU``."""
    return signature_variant


@pytest.fixture
def signature_model_of() -> Callable[..., SignatureModelConfig]:
    """Return the builder of the model of the specification, with a short fit."""
    return signature_model


@pytest.fixture
def linear_artifact_of() -> Callable[..., SignatureArtifact]:
    """Return the builder of a hand-written linear model of a variant."""
    return linear_artifact


def signature_schedule(
    variant: SignatureVariant, months: Mapping[str, float | Sequence[float] | str]
) -> SignatureModelSchedule:
    """Return a schedule of hand-written linear models over months of 2026.

    Each month is given a number - the bias of a model without coefficients,
    in percentage points, so ``0.5`` forecasts fifty basis points every evening
    - or the coefficients of a model without bias, or the reason it has no
    model. A model's information stops at 23:00 in Paris on the last day
    before its month, and it is ready twelve hours later.
    """
    entries = []
    for month, written in months.items():
        if isinstance(written, str):
            entries.append(ScheduleEntry(month, None, written))
            continue
        first = date(int(month[:4]), int(month[5:]), 1)
        cutoff = paris(first - timedelta(days=1), 23, 0)
        if isinstance(written, float | int):
            artifact = linear_artifact(variant, month, cutoff, bias=float(written))
        else:
            artifact = linear_artifact(variant, month, cutoff, coefficients=written)
        entries.append(ScheduleEntry(month, artifact))
    return SignatureModelSchedule(variant.variant_id, "Europe/Paris", tuple(entries))


@pytest.fixture
def signature_schedule_of() -> Callable[..., SignatureModelSchedule]:
    """Return the builder of a schedule of hand-written models over months of 2026."""
    return signature_schedule
