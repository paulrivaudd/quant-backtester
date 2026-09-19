"""ReturnSignal: the formula, and the six ways of having no number.

The prices rise by one a session from 100 to 109, so every expected value below
can be worked out on paper. What the tests are really about is the other rows:
a fund that did not exist, one that has not lived long enough, a session the
venue held and the series lacks, a value too old to use, and a parameter that
makes no sense.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime

import pytest

from quant_backtester.data.calendars import TradingCalendar
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.data.schemas import BarField
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.price.returns import ReturnSignal
from quant_backtester.signals.types import PriceBasis, SignalStatus

MarketBuilder = Callable[..., MarketDataReader]
BarsBuilder = Callable[..., object]
ContextBuilder = Callable[[MarketDataReader, datetime], SignalContext]
Evening = Callable[[date], datetime]
Prices = Callable[..., dict[date, float]]


def signal(lookback: int = 4, **overrides: object) -> ReturnSignal:
    """Build a return signal with the usual defaults."""
    parameters: dict[str, object] = {
        "signal_id": f"return_{lookback}d",
        "lookback_sessions": lookback,
        "price_basis": PriceBasis.RAW,
    }
    parameters.update(overrides)
    return ReturnSignal(**parameters)  # type: ignore[arg-type]


def test_the_formula_on_a_hand_checkable_series(context: SignalContext) -> None:
    """Four sessions back from 109 is 105, so the return is 109/105 - 1."""
    result = signal(4).compute(context, ["ETF_EU"])

    assert result.status("ETF_EU") is SignalStatus.OK
    assert result.value("ETF_EU") == pytest.approx(109.0 / 105.0 - 1.0)


def test_the_diagnostics_say_which_window_produced_the_number(
    context: SignalContext, sessions: tuple[date, ...]
) -> None:
    """A number without its window is not reviewable."""
    row = signal(4).compute(context, ["ETF_EU"]).frame.loc["ETF_EU"]

    assert row["observations_used"] == 5
    assert row["input_start_date"] == sessions[-5]
    assert row["input_end_date"] == sessions[-1]
    assert row["max_input_age_sessions"] == 0


def test_a_history_shorter_than_the_lookback(context: SignalContext) -> None:
    """Ten sessions stored, eleven needed: no number, and it says why."""
    result = signal(10).compute(context, ["ETF_EU"])

    assert result.status("ETF_EU") is SignalStatus.INSUFFICIENT_HISTORY
    assert result.value("ETF_EU") != result.value("ETF_EU")  # NaN


def test_an_instrument_not_yet_listed(
    market: MarketDataReader,
    make_context: ContextBuilder,
    evening: Evening,
    sessions: tuple[date, ...],
) -> None:
    """Not a data problem: the strategy drops it from its universe."""
    early = make_context(market, evening(sessions[1]))

    result = signal(2).compute(early, ["ETF_LATE"])

    assert result.status("ETF_LATE") is SignalStatus.NOT_LISTED


def test_a_session_the_venue_held_and_the_series_lacks(
    make_market: MarketBuilder,
    make_bars: BarsBuilder,
    make_context: ContextBuilder,
    evening: Evening,
    prices: Prices,
    sessions: tuple[date, ...],
    xpar: TradingCalendar,
) -> None:
    """Five observations spanning six sessions is not a four-session return."""
    market = make_market(
        {
            "ETF_EU": make_bars(
                "ETF_EU",
                xpar,
                prices(100.0, 1.0),
                contested={date(2026, 9, 10): [BarField.CLOSE]},
            )
        }
    )

    result = signal(4).compute(make_context(market, evening(sessions[-1])), ["ETF_EU"])

    assert result.status("ETF_EU") is SignalStatus.NON_CONSECUTIVE_HISTORY


def test_the_last_value_missing(
    make_market: MarketBuilder,
    make_bars: BarsBuilder,
    make_context: ContextBuilder,
    evening: Evening,
    prices: Prices,
    sessions: tuple[date, ...],
    xpar: TradingCalendar,
) -> None:
    """A hole at the freshest end is loud, and is not the same as being stale."""
    market = make_market(
        {
            "ETF_EU": make_bars(
                "ETF_EU",
                xpar,
                prices(100.0, 1.0),
                contested={sessions[-1]: [BarField.CLOSE]},
            )
        }
    )

    result = signal(4).compute(make_context(market, evening(sessions[-1])), ["ETF_EU"])

    assert result.status("ETF_EU") is SignalStatus.MISSING_INPUT


@pytest.mark.parametrize(
    ("max_age_sessions", "expected"),
    [(0, SignalStatus.STALE_INPUT), (1, SignalStatus.OK)],
    ids=["just-over-the-threshold", "at-the-threshold"],
)
def test_staleness_is_declared_by_the_signal(
    market: MarketDataReader,
    make_context: ContextBuilder,
    evening: Evening,
    max_age_sessions: int,
    expected: SignalStatus,
) -> None:
    """Labor Day: Paris trades, the US close is a session old, and the signal chooses."""
    context = make_context(market, evening(date(2026, 9, 7)))

    result = signal(2, max_age_sessions=max_age_sessions).compute(context, ["IDX_US"])

    assert result.status("IDX_US") is expected


def test_a_later_session_does_not_change_an_earlier_number(
    make_market: MarketBuilder,
    make_bars: BarsBuilder,
    make_context: ContextBuilder,
    evening: Evening,
    prices: Prices,
    sessions: tuple[date, ...],
    xpar: TradingCalendar,
) -> None:
    """The look-ahead guard: the same decision, over an archive that grew.

    The second market holds one more session, at a price nothing like the
    others. A signal taken before it must not move by a hair.
    """
    closes = prices(100.0, 1.0)
    before = signal(4).compute(
        make_context(
            make_market({"ETF_EU": make_bars("ETF_EU", xpar, closes)}), evening(sessions[-1])
        ),
        ["ETF_EU"],
    )

    with_future = dict(closes)
    with_future[date(2026, 9, 15)] = 500.0
    after = signal(4).compute(
        make_context(
            make_market({"ETF_EU": make_bars("ETF_EU", xpar, with_future)}),
            evening(sessions[-1]),
        ),
        ["ETF_EU"],
    )

    assert after.frame.equals(before.frame)


def test_the_same_signal_twice_gives_the_same_frame(context: SignalContext) -> None:
    """Reproducibility, and the context's cache must not change an answer."""
    once = signal(4).compute(context, ["ETF_EU"])
    twice = signal(4).compute(context, ["ETF_EU"])

    assert once.frame.equals(twice.frame)
    assert once.definition == twice.definition


def test_the_definition_holds_every_parameter_that_changes_the_number() -> None:
    """Two signals with the same fingerprint must compute the same thing."""
    assert signal(4).fingerprint() != signal(5).fingerprint()
    assert signal(4).fingerprint() == signal(4).fingerprint()
    assert signal(4, price_basis=PriceBasis.TOTAL_RETURN).fingerprint() != signal(4).fingerprint()
    assert signal(4).definition()["unit"] == "FRACTION"


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"lookback_sessions": 0}, "lookback_sessions"),
        ({"lookback_sessions": -1}, "lookback_sessions"),
        ({"max_age_sessions": -1}, "max_age_sessions"),
    ],
    ids=["zero-lookback", "negative-lookback", "negative-age"],
)
def test_an_impossible_configuration_stops_the_run(
    overrides: dict[str, object], match: str
) -> None:
    """Not a status: no instrument would have been computed correctly either."""
    with pytest.raises(ValueError, match=match):
        signal(4, **overrides)
