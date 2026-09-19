"""Every signal, in every situation where there is no number to give.

The five signals share one window loader, and the formulas above test each one's
arithmetic. What this file pins is that none of them slips past the contract:
whatever the formula, a fund that did not exist, a history too short, a session
missing, a value too old and a price that breaks the arithmetic all come back
as themselves rather than as a ``NaN`` nobody can interpret.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime

import pytest

from quant_backtester.data.calendars import TradingCalendar
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.data.schemas import BarField
from quant_backtester.signals.base import Signal
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.price.momentum import MomentumSignal
from quant_backtester.signals.price.returns import ReturnSignal
from quant_backtester.signals.price.trend import MovingAverageTrendSignal
from quant_backtester.signals.risk.drawdown import CurrentDrawdownSignal
from quant_backtester.signals.risk.volatility import RealizedVolatilitySignal
from quant_backtester.signals.types import PriceBasis, SignalStatus

RAW = PriceBasis.RAW

SIGNALS: tuple[Signal, ...] = (
    ReturnSignal(signal_id="return_4d", lookback_sessions=4, price_basis=RAW),
    MomentumSignal(
        signal_id="momentum_4d", lookback_sessions=4, skip_recent_sessions=1, price_basis=RAW
    ),
    MovingAverageTrendSignal(signal_id="trend_ma5", window_sessions=5, price_basis=RAW),
    RealizedVolatilitySignal(signal_id="volatility_4d", window_returns=4, price_basis=RAW),
    CurrentDrawdownSignal(signal_id="drawdown_5d", window_sessions=5, price_basis=RAW),
)
"""One instance of each V1 signal, every one of them needing five prices."""

IDS = [signal.signal_id for signal in SIGNALS]


@pytest.fixture(params=SIGNALS, ids=IDS)
def any_signal(request: pytest.FixtureRequest) -> Signal:
    """Return each of the five signals in turn."""
    return request.param


def test_a_number_and_a_reason_for_every_instrument(
    any_signal: Signal, context: SignalContext
) -> None:
    """A row per instrument asked for, in the order asked, whatever happened."""
    result = any_signal.compute(context, ["ETF_EU", "ETF_LATE"])

    assert list(result.frame.index) == ["ETF_EU", "ETF_LATE"]
    assert result.status("ETF_EU") is SignalStatus.OK
    assert result.signal_id == any_signal.signal_id
    assert result.as_of == context.as_of


def test_an_instrument_that_did_not_exist(
    any_signal: Signal,
    market: MarketDataReader,
    make_context: Callable[..., SignalContext],
    evening: Callable[[date], datetime],
    sessions: tuple[date, ...],
) -> None:
    """Normal, and not a hole: the strategy drops it from its universe."""
    early = make_context(market, evening(sessions[1]))

    assert any_signal.compute(early, ["ETF_LATE"]).status("ETF_LATE") is SignalStatus.NOT_LISTED


def test_a_history_too_short(any_signal: Signal, context: SignalContext) -> None:
    """Every one of them needs five prices; a fund with four has none of them."""
    assert (
        any_signal.compute(context, ["ETF_LATE"]).status("ETF_LATE")
        is SignalStatus.INSUFFICIENT_HISTORY
    )


def test_a_session_the_venue_held_and_the_series_lacks(
    any_signal: Signal,
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., object],
    make_context: Callable[..., SignalContext],
    evening: Callable[[date], datetime],
    prices: Callable[..., dict[date, float]],
    sessions: tuple[date, ...],
    xpar: TradingCalendar,
) -> None:
    """Five observations over six sessions is not the window any of them asked for."""
    market = make_market(
        {
            "ETF_EU": make_bars(
                "ETF_EU", xpar, prices(100.0, 1.0), contested={sessions[-3]: [BarField.CLOSE]}
            )
        }
    )
    context = make_context(market, evening(sessions[-1]))

    assert (
        any_signal.compute(context, ["ETF_EU"]).status("ETF_EU")
        is SignalStatus.NON_CONSECUTIVE_HISTORY
    )


def test_the_freshest_value_missing(
    any_signal: Signal,
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., object],
    make_context: Callable[..., SignalContext],
    evening: Callable[[date], datetime],
    prices: Callable[..., dict[date, float]],
    sessions: tuple[date, ...],
    xpar: TradingCalendar,
) -> None:
    """A hole at the front is loud, and is not the same thing as a stale value."""
    market = make_market(
        {
            "ETF_EU": make_bars(
                "ETF_EU", xpar, prices(100.0, 1.0), contested={sessions[-1]: [BarField.CLOSE]}
            )
        }
    )
    context = make_context(market, evening(sessions[-1]))

    assert any_signal.compute(context, ["ETF_EU"]).status("ETF_EU") is SignalStatus.MISSING_INPUT


def test_a_value_older_than_allowed(
    any_signal: Signal,
    market: MarketDataReader,
    make_context: Callable[..., SignalContext],
    evening: Callable[[date], datetime],
) -> None:
    """Labor Day, read from Paris: the US close is one session old.

    Every signal here defaults to accepting one session, so the cross-market
    case works by default and refusing it is a declared choice.
    """
    context = make_context(market, evening(date(2026, 9, 7)))

    assert any_signal.compute(context, ["IDX_US"]).status("IDX_US") is SignalStatus.OK


def test_a_later_session_changes_nothing(
    any_signal: Signal,
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., object],
    make_context: Callable[..., SignalContext],
    evening: Callable[[date], datetime],
    prices: Callable[..., dict[date, float]],
    sessions: tuple[date, ...],
    xpar: TradingCalendar,
) -> None:
    """The look-ahead guard, for all five at once.

    The second archive holds one more session at a price nothing like the
    others - and, for good measure, a split that would move every adjusted
    price before it. A signal taken before both must not move.
    """
    closes = prices(100.0, 1.0)
    before = any_signal.compute(
        make_context(
            make_market({"ETF_EU": make_bars("ETF_EU", xpar, closes)}), evening(sessions[-1])
        ),
        ["ETF_EU"],
    )

    with_future = dict(closes)
    with_future[date(2026, 9, 15)] = 500.0
    after = any_signal.compute(
        make_context(
            make_market({"ETF_EU": make_bars("ETF_EU", xpar, with_future)}),
            evening(sessions[-1]),
        ),
        ["ETF_EU"],
    )

    assert after.frame.equals(before.frame)


def test_the_same_computation_twice(any_signal: Signal, context: SignalContext) -> None:
    """Same data, same instant, same definition: the same frame."""
    once = any_signal.compute(context, ["ETF_EU", "IDX_US"])
    twice = any_signal.compute(context, ["ETF_EU", "IDX_US"])

    assert once.frame.equals(twice.frame)


def test_the_definition_is_serialisable_and_complete(any_signal: Signal) -> None:
    """A fingerprint is only worth something if the definition is."""
    import json

    definition = dict(any_signal.definition())

    assert json.loads(json.dumps(definition)) == definition
    assert definition["window_mode"] == "CONSECUTIVE_SESSIONS"
    assert "price_basis" in definition
    assert "max_age_sessions" in definition
    assert len(any_signal.fingerprint()) == 64


def test_an_unknown_instrument_is_not_a_status(any_signal: Signal, context: SignalContext) -> None:
    """A typo in a universe is a configuration mistake, and stops the run."""
    with pytest.raises(KeyError):
        any_signal.compute(context, ["NOT_REGISTERED"])
