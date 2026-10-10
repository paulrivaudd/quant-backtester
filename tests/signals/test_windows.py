"""Windows: what a window of N sessions is, and when it is not one.

This is where the layer earns its place. The reader drops a session it cannot
serve rather than returning a ``NaN``, so the last twenty observations of a
series are not necessarily the last twenty sessions of its venue - and every
signal computed on the difference would be measuring something other than what
its name says.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from itertools import pairwise

import pytest

from quant_backtester.data.calendars import TradingCalendar
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.data.schemas import ActionType, BarField
from quant_backtester.demo import checked_bars_frame
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.types import PriceBasis, SignalStatus, WindowMode, WindowSpec
from quant_backtester.signals.windows import (
    LoadedWindow,
    load_adjusted_open_window,
    load_window,
    returns_of,
)


def load(
    context: SignalContext,
    instrument_id: str = "ETF_EU",
    *,
    observations: int = 5,
    mode: WindowMode = WindowMode.CONSECUTIVE_SESSIONS,
    max_age_sessions: int = 1,
) -> LoadedWindow:
    """Load one window with the usual defaults."""
    return load_window(
        context,
        instrument_id,
        spec=WindowSpec(observations, mode),
        bar_field=BarField.CLOSE,
        basis=PriceBasis.RAW,
        max_age_sessions=max_age_sessions,
    )


def test_a_window_holds_exactly_what_was_asked_for(
    context: SignalContext, sessions: tuple[date, ...]
) -> None:
    """Five observations, the five most recent, oldest first."""
    window = load(context, observations=5)

    assert window.status is SignalStatus.OK
    assert window.points == (105.0, 106.0, 107.0, 108.0, 109.0)
    assert window.dates == sessions[-5:]
    assert window.first == 105.0
    assert window.last == 109.0


def test_a_window_stops_at_the_decision_instant(
    market: MarketDataReader,
    make_context: Callable[[MarketDataReader, datetime], SignalContext],
    evening: Callable[[date], datetime],
    sessions: tuple[date, ...],
) -> None:
    """The look-ahead guard: a later session is not in a window taken before it."""
    earlier = make_context(market, evening(sessions[-3]))

    window = load(earlier, observations=3)

    assert window.dates == sessions[-5:-2]
    assert window.last == 107.0


def test_the_same_window_twice_is_the_same_window(context: SignalContext) -> None:
    """Reproducibility, and the cache must not change an answer."""
    assert load(context, observations=4) == load(context, observations=4)


def test_a_history_shorter_than_the_window_is_named(context: SignalContext) -> None:
    """Ten sessions stored, eleven asked for: the fund has not lived long enough.

    The ten it does have come back with the refusal. "Not enough history" is a
    verdict nobody can act on; "ten of the eleven sessions asked for" tells a
    reader whether to wait a day or to drop the instrument.
    """
    window = load(context, observations=11)

    assert window.status is SignalStatus.INSUFFICIENT_HISTORY
    assert len(window.points) == 10
    assert window.dates[-1] == date(2026, 9, 14)


def test_an_instrument_that_did_not_exist_is_not_a_data_problem(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., object],
    make_context: Callable[[MarketDataReader, datetime], SignalContext],
    evening: Callable[[date], datetime],
    prices: Callable[..., dict[date, float]],
    sessions: tuple[date, ...],
    xpar: TradingCalendar,
) -> None:
    """A fund listed on 9 September has no window on the 14th, and no hole either."""
    market = make_market({"ETF_LATE": make_bars("ETF_LATE", xpar, prices(50.0, 1.0, sessions[6:]))})

    late = make_context(market, evening(sessions[-1]))
    assert load(late, "ETF_LATE", observations=10).status is SignalStatus.INSUFFICIENT_HISTORY

    early = make_context(market, evening(sessions[2]))
    assert load(early, "ETF_LATE", observations=3).status is SignalStatus.NOT_LISTED


def test_a_session_the_venue_held_and_the_series_lacks_invalidates_the_window(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., object],
    make_context: Callable[[MarketDataReader, datetime], SignalContext],
    evening: Callable[[date], datetime],
    prices: Callable[..., dict[date, float]],
    sessions: tuple[date, ...],
    xpar: TradingCalendar,
) -> None:
    """The case the whole module exists for.

    Two sources contest the close of 10 September, so the reader refuses to
    serve it. Five observations are still available - they simply span six
    sessions, and a five-session momentum computed on them would be a
    six-session one wearing the wrong name.
    """
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
    context = make_context(market, evening(sessions[-1]))

    assert load(context, observations=5).status is SignalStatus.NON_CONSECUTIVE_HISTORY

    # A window that begins after the hole is untouched by it.
    assert load(context, observations=2).status is SignalStatus.OK


def test_a_weekend_is_not_a_hole(context: SignalContext) -> None:
    """The window spans two weekends and stays consecutive.

    Ten sessions from 1 to 14 September: thirteen calendar days apart, and not
    one of the four weekend days between them is a gap.
    """
    window = load(context, observations=10)

    assert window.status is SignalStatus.OK
    assert (window.dates[-1] - window.dates[0]).days == 13


def test_available_observations_does_not_look_at_the_calendar(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., object],
    make_context: Callable[[MarketDataReader, datetime], SignalContext],
    evening: Callable[[date], datetime],
    prices: Callable[..., dict[date, float]],
    sessions: tuple[date, ...],
    xpar: TradingCalendar,
) -> None:
    """The other semantics, asked for explicitly: N points, wherever they fall."""
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
    context = make_context(market, evening(sessions[-1]))

    window = load(context, observations=5, mode=WindowMode.AVAILABLE_OBSERVATIONS)

    assert window.status is SignalStatus.OK
    assert len(window.points) == 5


@pytest.mark.parametrize(
    ("max_age_sessions", "expected"),
    [(0, SignalStatus.STALE_INPUT), (1, SignalStatus.OK), (2, SignalStatus.OK)],
    ids=["refused-at-zero", "accepted-at-the-threshold", "accepted-below-it"],
)
def test_staleness_is_the_signal_s_choice(
    market: MarketDataReader,
    make_context: Callable[[MarketDataReader, datetime], SignalContext],
    evening: Callable[[date], datetime],
    max_age_sessions: int,
    expected: SignalStatus,
) -> None:
    """One session old is fresh for some signals and stale for others.

    Monday 7 September: Paris trades, New York is shut for Labor Day. A
    decision taken that evening finds the US index's freshest close dated the
    4th - one session old on the calendar the decision is taken on, and
    perfectly fresh on the index's own. Whether that is acceptable is the
    signal's to declare.
    """
    context = make_context(market, evening(date(2026, 9, 7)))

    window = load(context, "IDX_US", observations=3, max_age_sessions=max_age_sessions)

    assert window.status is expected
    assert window.age_sessions == 1


def test_an_unknown_instrument_is_a_configuration_mistake(context: SignalContext) -> None:
    """Not a status: no instrument would have been computed correctly either."""
    with pytest.raises(KeyError):
        load(context, "NOT_REGISTERED")


def test_consecutive_sessions_on_a_published_series_is_refused(
    context: SignalContext,
) -> None:
    """A published series has no venue calendar, so there are no sessions to count.

    A configuration mistake rather than a status: asking a rate for twenty
    consecutive market sessions is a question with no meaning, and an empty
    answer would let it pass.
    """
    with pytest.raises(ValueError, match="AVAILABLE_OBSERVATIONS"):
        load(context, "RATE_US", observations=3)


@pytest.mark.parametrize("observations", [0, 1, -3])
def test_a_window_of_fewer_than_two_points_is_refused(observations: int) -> None:
    """One point is not a window, and every formula here needs at least two."""
    with pytest.raises(ValueError, match="at least 2"):
        WindowSpec(observations)


def test_a_negative_age_threshold_is_refused(context: SignalContext) -> None:
    with pytest.raises(ValueError, match="max_age_sessions"):
        load(context, max_age_sessions=-1)


def test_returns_of_a_window_are_one_shorter_than_it(context: SignalContext) -> None:
    """Twenty returns need twenty-one prices, and the off-by-one is worth pinning."""
    window = load(context, observations=5)

    simple = returns_of(window, logarithmic=False)

    assert len(simple) == 4
    assert simple[0] == pytest.approx(106.0 / 105.0 - 1.0)


# --- a refused window still says what it found -------------------------------


def test_insufficient_history_reports_what_was_available(
    context: SignalContext, sessions: tuple[date, ...]
) -> None:
    """Ten of the eleven asked for, and the dates they cover.

    "Not enough history" alone cannot be acted on. Ten out of eleven means
    waiting a day; two out of eleven means dropping the instrument for months.
    """
    window = load(context, observations=11)

    assert window.status is SignalStatus.INSUFFICIENT_HISTORY
    assert len(window.points) == 10
    assert window.dates == sessions


def test_non_consecutive_history_reports_the_window_it_tried(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., object],
    make_context: Callable[[MarketDataReader, datetime], SignalContext],
    evening: Callable[[date], datetime],
    prices: Callable[..., dict[date, float]],
    sessions: tuple[date, ...],
    xpar: TradingCalendar,
) -> None:
    """The five observations it found, and the six sessions they turned out to span."""
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
    context = make_context(market, evening(sessions[-1]))

    window = load(context, observations=5)

    assert window.status is SignalStatus.NON_CONSECUTIVE_HISTORY
    assert len(window.points) == 5
    assert window.dates[0] == date(2026, 9, 7)
    assert window.dates[-1] == sessions[-1]
    assert date(2026, 9, 10) not in window.dates


def test_the_diagnostics_reach_the_result(context: SignalContext) -> None:
    """A signal's row carries them, which is where a reader actually looks."""
    from quant_backtester.signals.price.returns import ReturnSignal

    result = ReturnSignal(
        signal_id="return_10d", lookback_sessions=10, price_basis=PriceBasis.RAW
    ).compute(context, ["ETF_EU"])
    row = result.frame.loc["ETF_EU"]

    assert row["status"] is SignalStatus.INSUFFICIENT_HISTORY
    assert row["observations_used"] == 10
    assert row["input_end_date"] == date(2026, 9, 14)


# --- adjusted opens ------------------------------------------------------------------------


def bars_with_opens(
    calendar: TradingCalendar,
    sessions: tuple[date, ...],
    *,
    scale_from: int | None = None,
    scale: float = 1.0,
) -> object:
    """Return bars opening half a point under their close, optionally rescaled from a session.

    Closes rise from 100 by one a session; from ``scale_from`` on, every quoted
    price is multiplied by ``scale``, as a split would do to them.
    """
    drawn = {}
    for index, session in enumerate(sessions):
        factor = scale if scale_from is not None and index >= scale_from else 1.0
        close = (100.0 + index) * factor
        opening = close - 0.5 * factor
        drawn[session] = (opening, close, opening, close)
    return checked_bars_frame("ETF_EU", calendar, drawn)


def adjusted_opens(context: SignalContext, observations: int = 5) -> LoadedWindow:
    """Load a window of adjusted opens of the decided session."""
    return load_adjusted_open_window(
        context, "ETF_EU", spec=WindowSpec(observations), max_age_sessions=0
    )


def test_without_a_corporate_action_an_adjusted_open_is_the_open(
    make_market, make_context, evening, sessions, xpar
) -> None:
    market = make_market({"ETF_EU": bars_with_opens(xpar, sessions)})

    window = adjusted_opens(make_context(market, evening(sessions[-1])))

    assert window.status is SignalStatus.OK
    assert window.points == (104.5, 105.5, 106.5, 107.5, 108.5)
    assert window.dates == sessions[-5:]
    assert window.age_sessions == 0


def test_a_known_split_leaves_the_adjusted_opens_continuous(
    make_market, make_actions, make_context, evening, sessions, xpar
) -> None:
    """The factor is the reader's own: adjusted close over raw close, session by session."""
    split = make_actions([("ETF_EU", ActionType.SPLIT, sessions[7], 4.0, evening(sessions[6]))])
    market = make_market(
        {"ETF_EU": bars_with_opens(xpar, sessions, scale_from=7, scale=0.25)}, actions=split
    )

    window = adjusted_opens(make_context(market, evening(sessions[-1])))

    assert window.status is SignalStatus.OK
    # Quoted after the split; the sessions before it are divided by four.
    assert window.points == pytest.approx((104.5 / 4, 105.5 / 4, 106.5 / 4, 107.5 / 4, 108.5 / 4))
    ratios = [later / earlier for earlier, later in pairwise(window.points)]
    assert max(ratios) < 1.02  # no jump of a factor four anywhere in the window


def test_a_split_not_known_at_the_decision_is_not_in_the_window(
    make_market, make_actions, make_context, evening, sessions, xpar
) -> None:
    bars = {"ETF_EU": bars_with_opens(xpar, sessions)}
    before = adjusted_opens(make_context(make_market(bars), evening(sessions[5])))

    known_later = make_actions(
        [("ETF_EU", ActionType.SPLIT, sessions[3], 4.0, evening(sessions[-1]))]
    )
    after = adjusted_opens(
        make_context(make_market(bars, actions=known_later), evening(sessions[5]))
    )

    assert after == before
    assert before.points == (100.5, 101.5, 102.5, 103.5, 104.5)


def test_prices_after_the_decision_do_not_reach_an_adjusted_open(
    make_market, make_context, evening, sessions, xpar
) -> None:
    early = adjusted_opens(
        make_context(make_market({"ETF_EU": bars_with_opens(xpar, sessions)}), evening(sessions[5]))
    )
    moved = bars_with_opens(xpar, sessions, scale_from=6, scale=3.0)

    late = adjusted_opens(make_context(make_market({"ETF_EU": moved}), evening(sessions[5])))

    assert late == early


def test_a_refused_window_of_adjusted_opens_says_why_and_holds_no_price(
    make_market, make_bars, make_context, evening, sessions, xpar
) -> None:
    """A hole, a stale bar, a short history and a zero are four statuses, and none is filled."""
    whole = make_market({"ETF_EU": bars_with_opens(xpar, sessions)})
    short = adjusted_opens(make_context(whole, evening(sessions[2])))
    assert short.status is SignalStatus.INSUFFICIENT_HISTORY and short.points == ()

    closes = {session: 100.0 + index for index, session in enumerate(sessions)}
    holed = make_bars("ETF_EU", xpar, closes, contested={sessions[-3]: [BarField.OPEN]})
    hole = adjusted_opens(make_context(make_market({"ETF_EU": holed}), evening(sessions[-1])))
    assert hole.status is SignalStatus.NON_CONSECUTIVE_HISTORY and hole.points == ()

    stale = bars_with_opens(xpar, sessions[:-1])
    old = adjusted_opens(make_context(make_market({"ETF_EU": stale}), evening(sessions[-1])))
    assert old.status in (SignalStatus.STALE_INPUT, SignalStatus.MISSING_INPUT)
    assert old.points == ()

    closes[sessions[-2]] = 0.0
    zero = adjusted_opens(
        make_context(
            make_market({"ETF_EU": make_bars("ETF_EU", xpar, closes)}), evening(sessions[-1])
        )
    )
    assert zero.status is SignalStatus.INVALID_INPUT and zero.points == ()
