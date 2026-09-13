"""Yahoo adapter: what is sent to yfinance and what is kept from its answer.

``yfinance.Ticker`` is replaced by a spy, so the routine tests are offline and
never read the wall clock. The ``network`` tests check the live contract of
each endpoint once.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime

import pandas as pd
import pytest
import yfinance

from quant_backtester.data.instruments import AssetType, DataType, Instrument
from quant_backtester.data.sources import yahoo
from quant_backtester.data.sources.yahoo import YahooSource

RETRIEVED_AT = datetime(2026, 9, 12, 21, 3, 11, tzinfo=UTC)


@dataclass
class TickerSpy:
    """Stand-in for ``yfinance.Ticker``: records every call, returns fixed frames."""

    frame: pd.DataFrame
    actions_frame: pd.DataFrame = field(default_factory=pd.DataFrame)
    metadata: dict[str, object] = field(
        default_factory=lambda: {"exchangeTimezoneName": "America/New_York"}
    )
    calls: list[tuple[str, dict[str, object]]] = field(default_factory=list)
    actions_reads: list[str] = field(default_factory=list)
    metadata_reads: list[str] = field(default_factory=list)

    def ticker(self, symbol: str) -> FakeTicker:
        """Return a fake ticker that reports its calls to this spy."""
        return FakeTicker(self, symbol)


class FakeTicker:
    """What ``TickerSpy.ticker`` hands out in place of a real ticker."""

    def __init__(self, spy: TickerSpy, symbol: str) -> None:
        self._spy = spy
        self._symbol = symbol

    def history(self, **kwargs: object) -> pd.DataFrame:
        """Record the keyword arguments and return the spy's frame."""
        self._spy.calls.append((self._symbol, kwargs))
        return self._spy.frame

    @property
    def actions(self) -> pd.DataFrame:
        """Record the read and return the spy's corporate actions frame."""
        self._spy.actions_reads.append(self._symbol)
        return self._spy.actions_frame

    @property
    def history_metadata(self) -> dict[str, object]:
        """Record the read and return the spy's history metadata."""
        self._spy.metadata_reads.append(self._symbol)
        return self._spy.metadata


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> TickerSpy:
    """Replace ``yfinance.Ticker`` with a spy returning two raw daily bars."""
    index = pd.DatetimeIndex(
        [
            pd.Timestamp("2026-09-10", tz="America/New_York"),
            pd.Timestamp("2026-09-11", tz="America/New_York"),
        ],
        name="Date",
    )
    frame = pd.DataFrame(
        {
            "Open": [650.0, 652.5],
            "High": [655.0, 656.0],
            "Low": [648.0, 651.0],
            "Close": [652.0, 655.5],
            "Adj Close": [650.1, 653.6],
            "Volume": [70_000_000, 65_000_000],
        },
        index=index,
    )
    # A dividend before the requested range, a 4:1 split and a dividend inside
    # it. Yahoo ignores the range, so the adapter must keep all three rows.
    actions_index = pd.DatetimeIndex(
        [
            pd.Timestamp("2025-12-19", tz="America/New_York"),
            pd.Timestamp("2026-06-10", tz="America/New_York"),
            pd.Timestamp("2026-09-11", tz="America/New_York"),
        ],
        name="Date",
    )
    actions_frame = pd.DataFrame(
        {"Dividends": [1.74, 0.0, 1.76], "Stock Splits": [0.0, 4.0, 0.0]},
        index=actions_index,
    )
    recorder = TickerSpy(frame=frame, actions_frame=actions_frame)
    monkeypatch.setattr(yahoo.yfinance, "Ticker", recorder.ticker)
    return recorder


@pytest.fixture
def spy_etf() -> Instrument:
    """Return a tradable US ETF whose Yahoo symbol differs from its internal id."""
    return Instrument(
        id="US_SPY",
        name="SPDR S&P 500 ETF",
        asset_type=AssetType.ETF,
        data_type=DataType.BAR,
        currency="USD",
        primary_source="YAHOO",
        source_symbol="SPY",
        tradable=True,
        calendar_id="XNYS",
    )


@pytest.fixture
def source() -> YahooSource:
    """Return an adapter whose clock always reads ``RETRIEVED_AT``."""
    return YahooSource(clock=lambda: RETRIEVED_AT)


def only_call(spy: TickerSpy) -> tuple[str, dict[str, object]]:
    assert len(spy.calls) == 1
    return spy.calls[0]


def test_download_asks_for_the_source_symbol(
    spy: TickerSpy, spy_etf: Instrument, source: YahooSource
) -> None:
    source.download(spy_etf, date(2026, 9, 10), date(2026, 9, 11))
    symbol, _ = only_call(spy)
    assert symbol == "SPY"


def test_download_sends_an_exclusive_end_one_day_later(
    spy: TickerSpy, spy_etf: Instrument, source: YahooSource
) -> None:
    source.download(spy_etf, date(2026, 9, 10), date(2026, 9, 11))
    _, kwargs = only_call(spy)
    assert str(kwargs["start"]) == "2026-09-10"
    assert str(kwargs["end"]) == "2026-09-12"


def test_download_sends_an_exclusive_end_across_a_month_boundary(
    spy: TickerSpy, spy_etf: Instrument, source: YahooSource
) -> None:
    source.download(spy_etf, date(2026, 9, 1), date(2026, 9, 30))
    _, kwargs = only_call(spy)
    assert str(kwargs["end"]) == "2026-10-01"


def test_download_single_day_range_sends_the_next_day_as_end(
    spy: TickerSpy, spy_etf: Instrument, source: YahooSource
) -> None:
    source.download(spy_etf, date(2026, 9, 11), date(2026, 9, 11))
    _, kwargs = only_call(spy)
    assert str(kwargs["start"]) == "2026-09-11"
    assert str(kwargs["end"]) == "2026-09-12"


def test_download_requests_raw_daily_bars_without_actions(
    spy: TickerSpy, spy_etf: Instrument, source: YahooSource
) -> None:
    source.download(spy_etf, date(2026, 9, 10), date(2026, 9, 11))
    _, kwargs = only_call(spy)
    assert kwargs["auto_adjust"] is False
    assert kwargs["actions"] is False
    assert kwargs["interval"] == "1d"


def test_download_returns_the_frame_untouched(
    spy: TickerSpy, spy_etf: Instrument, source: YahooSource
) -> None:
    expected = spy.frame.copy()
    result = source.download(spy_etf, date(2026, 9, 10), date(2026, 9, 11))
    assert result.frame is spy.frame
    pd.testing.assert_frame_equal(result.frame, expected)


def test_download_labels_the_result_with_internal_id_and_source(
    spy: TickerSpy, spy_etf: Instrument, source: YahooSource
) -> None:
    result = source.download(spy_etf, date(2026, 9, 10), date(2026, 9, 11))
    assert result.instrument_id == "US_SPY"
    assert result.source == "YAHOO"


def test_download_takes_timestamps_from_the_injected_clock(
    spy: TickerSpy, spy_etf: Instrument, source: YahooSource
) -> None:
    result = source.download(spy_etf, date(2026, 9, 10), date(2026, 9, 11))
    assert result.retrieved_at_utc == RETRIEVED_AT
    assert result.fetch_id == "20260912T210311Z"


def test_download_reads_the_clock_once(spy: TickerSpy, spy_etf: Instrument) -> None:
    ticks = iter(
        [RETRIEVED_AT, datetime(2026, 9, 12, 21, 3, 12, tzinfo=UTC)],
    )
    result = YahooSource(clock=lambda: next(ticks)).download(
        spy_etf, date(2026, 9, 10), date(2026, 9, 11)
    )
    assert result.retrieved_at_utc == RETRIEVED_AT
    assert result.fetch_id == "20260912T210311Z"


def test_download_records_the_request_and_library_version(
    spy: TickerSpy, spy_etf: Instrument, source: YahooSource
) -> None:
    result = source.download(spy_etf, date(2026, 9, 10), date(2026, 9, 11))
    assert result.request == {
        "symbol": "SPY",
        "start": "2026-09-10",
        "end_inclusive": "2026-09-11",
        "end_sent": "2026-09-12",
        "interval": "1d",
        "auto_adjust": False,
        "actions": False,
        "yfinance_version": yfinance.__version__,
    }


def test_download_rejects_start_after_end_without_calling_yahoo(
    spy: TickerSpy, spy_etf: Instrument, source: YahooSource
) -> None:
    with pytest.raises(ValueError):
        source.download(spy_etf, date(2026, 9, 11), date(2026, 9, 10))
    assert spy.calls == []


def test_download_rejects_a_clock_that_is_not_utc(spy: TickerSpy, spy_etf: Instrument) -> None:
    naive = YahooSource(clock=lambda: datetime(2026, 9, 12, 21, 3, 11))
    with pytest.raises(ValueError):
        naive.download(spy_etf, date(2026, 9, 10), date(2026, 9, 11))


@pytest.mark.network
def test_download_live_spy_returns_raw_unadjusted_bars(spy_etf: Instrument) -> None:
    result = YahooSource().download(spy_etf, date(2024, 1, 2), date(2024, 1, 5))
    assert {"Open", "High", "Low", "Close", "Adj Close", "Volume"} <= set(result.frame.columns)
    # 2 to 5 January 2024: four NYSE sessions, the end date included.
    assert len(result.frame) == 4
    assert result.retrieved_at_utc.tzinfo is UTC


def bar_instrument(asset_type: AssetType, source_symbol: str) -> Instrument:
    """Return a valid NYSE-listed BAR instrument of the given asset type."""
    return Instrument(
        id=f"US_{source_symbol.lstrip('^')}",
        name=source_symbol,
        asset_type=asset_type,
        data_type=DataType.BAR,
        currency="USD",
        primary_source="YAHOO",
        source_symbol=source_symbol,
        tradable=False,
        calendar_id="XNYS",
    )


@pytest.mark.parametrize(
    "asset_type",
    [AssetType.INDEX, AssetType.RATE, AssetType.FX, AssetType.VOLATILITY],
    ids=lambda asset_type: asset_type.value,
)
def test_corporate_actions_is_none_without_calling_yahoo(
    spy: TickerSpy, source: YahooSource, asset_type: AssetType
) -> None:
    instrument = bar_instrument(asset_type, "^GSPC")
    assert (
        source.download_corporate_actions(instrument, date(2026, 1, 1), date(2026, 9, 11)) is None
    )
    assert spy.actions_reads == []
    assert spy.calls == []


@pytest.mark.parametrize(
    "asset_type", [AssetType.ETF, AssetType.EQUITY], ids=lambda asset_type: asset_type.value
)
def test_corporate_actions_downloads_for_assets_that_can_have_them(
    spy: TickerSpy, source: YahooSource, asset_type: AssetType
) -> None:
    instrument = bar_instrument(asset_type, "SPY")
    result = source.download_corporate_actions(instrument, date(2026, 1, 1), date(2026, 9, 11))
    assert result is not None
    assert spy.actions_reads == ["SPY"]


def test_corporate_actions_reads_the_source_symbol_once(
    spy: TickerSpy, spy_etf: Instrument, source: YahooSource
) -> None:
    source.download_corporate_actions(spy_etf, date(2026, 1, 1), date(2026, 9, 11))
    assert spy.actions_reads == ["SPY"]
    assert spy.calls == []


def test_corporate_actions_returns_the_full_frame_untouched(
    spy: TickerSpy, spy_etf: Instrument, source: YahooSource
) -> None:
    expected = spy.actions_frame.copy()
    result = source.download_corporate_actions(spy_etf, date(2026, 1, 1), date(2026, 9, 11))
    assert result is not None
    assert result.frame is spy.actions_frame
    # The 2025 dividend lies before ``start`` and is still there: filtering is
    # the normalizer's job, the raw archive keeps what Yahoo sent.
    pd.testing.assert_frame_equal(result.frame, expected)


def test_corporate_actions_keeps_an_empty_answer(
    spy: TickerSpy, spy_etf: Instrument, source: YahooSource
) -> None:
    spy.actions_frame = pd.DataFrame()
    result = source.download_corporate_actions(spy_etf, date(2026, 1, 1), date(2026, 9, 11))
    assert result is not None
    assert result.frame.empty


def test_corporate_actions_labels_and_timestamps_from_the_clock(
    spy: TickerSpy, spy_etf: Instrument, source: YahooSource
) -> None:
    result = source.download_corporate_actions(spy_etf, date(2026, 1, 1), date(2026, 9, 11))
    assert result is not None
    assert result.instrument_id == "US_SPY"
    assert result.source == "YAHOO"
    assert result.retrieved_at_utc == RETRIEVED_AT
    assert result.fetch_id == "20260912T210311Z"


def test_corporate_actions_records_that_the_range_is_not_applied(
    spy: TickerSpy, spy_etf: Instrument, source: YahooSource
) -> None:
    result = source.download_corporate_actions(spy_etf, date(2026, 1, 1), date(2026, 9, 11))
    assert result is not None
    assert result.request == {
        "symbol": "SPY",
        "endpoint": "actions",
        "period": "max",
        "start": "2026-01-01",
        "end_inclusive": "2026-09-11",
        "yfinance_version": yfinance.__version__,
    }


def test_corporate_actions_rejects_start_after_end_without_calling_yahoo(
    spy: TickerSpy, spy_etf: Instrument, source: YahooSource
) -> None:
    with pytest.raises(ValueError):
        source.download_corporate_actions(spy_etf, date(2026, 9, 11), date(2026, 1, 1))
    assert spy.actions_reads == []


def test_corporate_actions_rejects_a_clock_that_is_not_utc(
    spy: TickerSpy, spy_etf: Instrument
) -> None:
    naive = YahooSource(clock=lambda: datetime(2026, 9, 12, 21, 3, 11))
    with pytest.raises(ValueError):
        naive.download_corporate_actions(spy_etf, date(2026, 1, 1), date(2026, 9, 11))
    assert spy.actions_reads == []


@pytest.mark.network
def test_corporate_actions_live_aapl_has_the_2020_split() -> None:
    aapl = bar_instrument(AssetType.EQUITY, "AAPL")
    result = YahooSource().download_corporate_actions(aapl, date(2020, 1, 1), date(2020, 12, 31))
    assert result is not None
    assert {"Dividends", "Stock Splits"} <= set(result.frame.columns)
    splits = result.frame["Stock Splits"]
    split_dates = [
        pd.Timestamp(str(ex_date)).date() for ex_date, ratio in splits.items() if ratio == 4.0
    ]
    # 4-for-1 split, ex-date 31 August 2020.
    assert date(2020, 8, 31) in split_dates


UNKNOWN_SYMBOL = "NOT_A_TICKER_XYZ123"


def test_download_with_bars_never_reads_the_metadata(
    spy: TickerSpy, spy_etf: Instrument, source: YahooSource
) -> None:
    source.download(spy_etf, date(2026, 9, 10), date(2026, 9, 11))
    assert spy.metadata_reads == []


def test_download_empty_range_of_a_known_symbol_is_kept(
    spy: TickerSpy, spy_etf: Instrument, source: YahooSource
) -> None:
    # A holiday: no bar, but Yahoo knows the symbol and its exchange timezone.
    spy.frame = spy.frame.iloc[0:0]
    result = source.download(spy_etf, date(2026, 9, 7), date(2026, 9, 7))
    assert result.frame.empty
    assert spy.metadata_reads == ["SPY"]


def test_download_unknown_symbol_raises_instead_of_archiving_nothing(
    spy: TickerSpy, spy_etf: Instrument, source: YahooSource
) -> None:
    spy.frame = spy.frame.iloc[0:0]
    spy.metadata = {}
    with pytest.raises(ValueError, match="'SPY'"):
        source.download(spy_etf, date(2026, 9, 10), date(2026, 9, 11))


def test_download_unknown_symbol_with_a_blank_timezone_raises(
    spy: TickerSpy, spy_etf: Instrument, source: YahooSource
) -> None:
    spy.frame = spy.frame.iloc[0:0]
    spy.metadata = {"exchangeTimezoneName": ""}
    with pytest.raises(ValueError, match="'SPY'"):
        source.download(spy_etf, date(2026, 9, 10), date(2026, 9, 11))


def test_corporate_actions_unknown_symbol_raises(
    spy: TickerSpy, spy_etf: Instrument, source: YahooSource
) -> None:
    spy.actions_frame = pd.DataFrame()
    spy.metadata = {}
    with pytest.raises(ValueError, match="'SPY'"):
        source.download_corporate_actions(spy_etf, date(2026, 1, 1), date(2026, 9, 11))


def test_corporate_actions_with_events_never_reads_the_metadata(
    spy: TickerSpy, spy_etf: Instrument, source: YahooSource
) -> None:
    source.download_corporate_actions(spy_etf, date(2026, 1, 1), date(2026, 9, 11))
    assert spy.metadata_reads == []


@pytest.mark.network
def test_download_live_christmas_returns_an_empty_frame(spy_etf: Instrument) -> None:
    result = YahooSource().download(spy_etf, date(2024, 12, 25), date(2024, 12, 25))
    assert result.frame.empty


@pytest.mark.network
def test_download_live_unknown_symbol_raises() -> None:
    unknown = bar_instrument(AssetType.EQUITY, UNKNOWN_SYMBOL)
    with pytest.raises(ValueError, match=UNKNOWN_SYMBOL):
        YahooSource().download(unknown, date(2024, 1, 2), date(2024, 1, 5))
