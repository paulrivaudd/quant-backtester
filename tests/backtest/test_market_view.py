"""The market as a strategy may consult it: one instant, and no way off it.

The façade exists so that a simple rule - *if the gauge is above thirty, stand
aside* - does not need a new signal class. What these tests are about is the
price of that shortcut: staleness stays visible, and the window logic is the
one every signal goes through rather than a ``tail(n)`` written again here.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime

import pandas as pd
import pytest

from quant_backtester.backtest.market import (
    MarketObservation,
    StrategyMarketView,
    UnavailableMarketData,
)
from quant_backtester.data.calendars import TradingCalendar
from quant_backtester.data.reader import (
    MarketDataReader,
    ObservationStatus,
    PointInTimeReader,
)
from quant_backtester.data.repository import MarketDataRepository
from quant_backtester.data.schemas import BarField
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.types import PriceBasis, SignalStatus, WindowMode


@pytest.fixture
def view(context: SignalContext) -> StrategyMarketView:
    """Return the market view of the shared decision instant."""
    return StrategyMarketView(context)


def test_a_value_carries_its_provenance(view: StrategyMarketView) -> None:
    """Not a float: the number, the day it describes, and how old it is."""
    observation = view.value("ETF_EU")

    assert observation.value == pytest.approx(109.0)
    assert observation.status is ObservationStatus.OK
    assert observation.observation_date == date(2026, 9, 14)
    assert observation.age_sessions == 0


def test_a_value_from_an_earlier_session_says_so(
    market: MarketDataReader,
    make_context: Callable[[MarketDataReader, datetime], SignalContext],
    evening: Callable[[date], datetime],
) -> None:
    """New York was shut on 7 September while Paris traded, so its close is stale.

    A ``price()`` returning the last known close would let a strategy trade on
    a number two sessions old with nothing in the code saying so.
    """
    labor_day = StrategyMarketView(make_context(market, evening(date(2026, 9, 7))))

    observation = labor_day.value("IDX_US")

    assert observation.status is ObservationStatus.STALE
    assert observation.age_sessions is not None
    assert observation.age_sessions > 0
    assert not observation.usable()
    assert observation.usable(max_age_sessions=observation.age_sessions)


def test_requiring_a_stale_value_refuses_rather_than_returning_it(
    market: MarketDataReader,
    make_context: Callable[[MarketDataReader, datetime], SignalContext],
    evening: Callable[[date], datetime],
) -> None:
    """A strategy that cannot decide without the number stops instead of guessing."""
    labor_day = StrategyMarketView(make_context(market, evening(date(2026, 9, 7))))

    observation = labor_day.value("IDX_US")

    with pytest.raises(UnavailableMarketData, match="session"):
        observation.require()


def test_a_value_nobody_published_is_not_a_nan(view: StrategyMarketView) -> None:
    """``None`` rather than a NaN: every comparison against a NaN is false."""
    observation = view.value("ETF_LATE", BarField.OPEN)
    listed = view.value("ETF_EU")

    assert listed.value is not None
    if observation.value is None:
        assert not observation.usable()
        with pytest.raises(UnavailableMarketData):
            observation.require()


def test_an_instrument_nobody_declared_is_a_wiring_mistake(
    view: StrategyMarketView,
) -> None:
    """Not an empty reading: a name the registry does not know stops the run."""
    with pytest.raises(KeyError):
        view.value("NOT_A_THING")


def test_a_window_is_the_one_every_signal_goes_through(view: StrategyMarketView) -> None:
    """Five sessions in a row, or the reason they are not."""
    window = view.history("ETF_EU", 5)

    assert window.ok
    assert window.observations_used == 5
    assert window.values[-1] == pytest.approx(109.0)  # noqa: PD011 - a tuple, not a frame
    assert window.last == pytest.approx(109.0)
    assert len(window.dates) == 5


def test_a_window_that_is_not_what_was_asked_for_is_refused(
    view: StrategyMarketView,
) -> None:
    """ETF_LATE has four sessions of history, and five were asked for."""
    window = view.history("ETF_LATE", 5)

    assert not window.ok
    assert window.status is SignalStatus.INSUFFICIENT_HISTORY
    with pytest.raises(UnavailableMarketData):
        _ = window.last


def test_a_window_of_a_published_series_is_counted_in_observations(
    view: StrategyMarketView,
) -> None:
    """Nobody holds sessions for a macro release, so the mode has to be said."""
    with pytest.raises(ValueError, match="AVAILABLE_OBSERVATIONS"):
        view.history("RATE_US", 3)


def test_a_window_of_zero_observations_is_a_configuration_mistake(
    view: StrategyMarketView,
) -> None:
    """Not a status: nobody meant to ask for nothing."""
    with pytest.raises(ValueError, match="observations"):
        view.history("ETF_EU", 0)


def test_the_view_is_fixed_at_the_decision_instant(
    view: StrategyMarketView, context: SignalContext
) -> None:
    """There is no method taking an instant, and no attribute holding a reader."""
    assert view.as_of == context.as_of
    assert not hasattr(view, "at")
    assert not hasattr(view, "reader")


def test_tomorrow_is_not_readable_today(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    make_context: Callable[[MarketDataReader, datetime], SignalContext],
    xpar: TradingCalendar,
    prices: Callable[..., dict[date, float]],
    evening: Callable[[date], datetime],
    sessions: tuple[date, ...],
) -> None:
    """The same decision, on a store that knows what happens next, is unchanged.

    The second market carries a fifty percent jump on the session after the
    decision. If any of it reached the reading, this is where it would show.
    """
    quiet = make_market({"ETF_EU": make_bars("ETF_EU", xpar, prices(100.0, 1.0))})
    known = prices(100.0, 1.0)
    known[sessions[-1]] = known[sessions[-2]] * 1.5
    loud = make_market({"ETF_EU": make_bars("ETF_EU", xpar, known)})

    before = StrategyMarketView(make_context(quiet, evening(sessions[-2]))).value("ETF_EU")
    after = StrategyMarketView(make_context(loud, evening(sessions[-2]))).value("ETF_EU")

    assert before == after


def test_several_values_come_back_keyed_by_instrument(view: StrategyMarketView) -> None:
    """A convenience over one call per name, with the same guarantees."""
    observations = view.values(["ETF_EU", "ETF_OTHER"])

    assert set(observations) == {"ETF_EU", "ETF_OTHER"}
    assert all(isinstance(item, MarketObservation) for item in observations.values())


def test_an_age_nobody_could_state_is_refused() -> None:
    """A tolerance of minus one session is a parameter written wrong."""
    observation = MarketObservation(
        instrument_id="ETF_EU", value=1.0, status=ObservationStatus.OK, age_sessions=0
    )

    with pytest.raises(ValueError, match="max_age_sessions"):
        observation.usable(-1)


def test_a_total_return_window_is_available_to_a_strategy(
    view: StrategyMarketView,
) -> None:
    """The adjusted series, for a rule that needs one - on the same loader."""
    window = view.history("ETF_EU", 3, basis=PriceBasis.TOTAL_RETURN)

    assert window.ok
    assert window.observations_used == 3


def test_a_window_mode_is_declared_not_guessed(
    make_market: Callable[..., MarketDataReader],
    make_levels: Callable[..., pd.DataFrame],
    make_context: Callable[[MarketDataReader, datetime], SignalContext],
    evening: Callable[[date], datetime],
    sessions: tuple[date, ...],
) -> None:
    """Twenty observations and twenty sessions are different questions."""
    rates = {day: 4.0 + 0.05 * step for step, day in enumerate(sessions)}
    market = make_market({}, None, {"RATE_US": make_levels("RATE_US", rates)})
    view = StrategyMarketView(make_context(market, evening(sessions[-1])))

    window = view.history("RATE_US", 3, mode=WindowMode.AVAILABLE_OBSERVATIONS)

    assert window.ok
    assert window.observations_used == 3


def test_the_market_view_hands_back_no_signal_context(view: StrategyMarketView) -> None:
    """The way around the window contract, closed.

    While the context was a public field, a strategy could write
    ``ctx.market.context.market.history(...).tail(20)`` and get twenty
    observations spanning twenty-six sessions - the one mistake
    :meth:`history` goes through the window loader to prevent. The reader is
    fixed at the decision instant either way, so this was never a way of
    reading tomorrow; it was a way of reading a window nobody checked.
    """
    public = {name for name in dir(view) if not name.startswith("_")}

    assert "context" not in public
    assert public == {"as_of", "history", "value", "values"}


def test_no_public_attribute_of_the_view_leads_to_the_reader(
    view: StrategyMarketView, context: SignalContext
) -> None:
    """Not just the name: nothing reachable from it is the reader or the store."""
    forbidden = (PointInTimeReader, MarketDataReader, MarketDataRepository)

    reachable = [getattr(view, name) for name in dir(view) if not name.startswith("_")]

    assert not [item for item in reachable if isinstance(item, forbidden)]
    assert not [item for item in reachable if isinstance(item, SignalContext)]


def test_the_view_says_which_instant_it_answers_for(view: StrategyMarketView) -> None:
    """Its representation names the decision and nothing underneath it."""
    printed = repr(view)

    assert view.as_of.isoformat() in printed
    assert "PointInTimeReader" not in printed


@pytest.mark.parametrize("age", [0.5, True, "1"])
def test_an_age_that_is_not_a_whole_number_of_sessions_is_refused(age: object) -> None:
    """Staleness is counted in sessions; half of one is a parameter written wrong."""
    observation = MarketObservation(
        instrument_id="ETF_EU", value=1.0, status=ObservationStatus.OK, age_sessions=0
    )

    with pytest.raises(ValueError, match="max_age_sessions"):
        observation.usable(age)  # type: ignore[arg-type]
