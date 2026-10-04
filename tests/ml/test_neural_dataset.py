"""The training set: the labels, the purge, what is refused and what cannot be read."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from quant_backtester.backtest.timetable import BacktestTimetable
from quant_backtester.data.calendars import CalendarRegistry, TradingCalendar
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.data.schemas import ActionType, BarField
from quant_backtester.ml.config import NeuralStrategyConfig
from quant_backtester.ml.dataset import (
    ForwardOpenReturnBuilder,
    InsufficientCalibrationData,
    MissingForwardOpen,
    build_training_dataset,
    entry_session,
    exit_session,
    purge,
)
from quant_backtester.ml.features import NeuralFeatureBuilder
from quant_backtester.signals.context import SignalContext

TIMETABLE = BacktestTimetable()
FUNDS = ("ETF_EU", "ETF_OTHER")
MONDAY, TUESDAY, WEDNESDAY = date(2026, 3, 9), date(2026, 3, 10), date(2026, 3, 11)
KNOWN_UNTIL = date(2026, 6, 30)

MarketBuilder = Callable[..., MarketDataReader]


def labels(reader: MarketDataReader, calendar: TradingCalendar, *days: date) -> np.ndarray:
    """Return the labels of some decisions, read as the training reads them."""
    builder = ForwardOpenReturnBuilder(reader, calendar, TIMETABLE)
    return builder.build(days, FUNDS, known_until=KNOWN_UNTIL)


def test_a_label_runs_from_the_open_after_the_decision_to_the_open_after_that(
    neural_market: MarketDataReader, xpar: TradingCalendar
) -> None:
    opens = neural_market.at(datetime(2026, 12, 1, tzinfo=ZoneInfo("UTC"))).history(
        "ETF_EU", BarField.OPEN
    )

    earned = labels(neural_market, xpar, MONDAY)

    assert (entry_session(MONDAY, xpar), exit_session(MONDAY, xpar)) == (TUESDAY, WEDNESDAY)
    assert earned.shape == (1, 2)
    assert earned[0, 0] == pytest.approx(opens[WEDNESDAY] / opens[TUESDAY] - 1.0)
    # A Friday's decision is bought on Monday and measured to Tuesday.
    assert exit_session(date(2026, 3, 6), xpar) == TUESDAY


def test_a_move_that_ends_before_the_purchase_earns_the_decision_nothing(
    make_neural_market: MarketBuilder, xpar: TradingCalendar
) -> None:
    """The fund jumps on the decision's own session and overnight, then its opens are flat."""

    def jump_before_the_entry(bars, levels) -> None:
        bars["ETF_EU"][MONDAY] = (100.0, 150.0, 100.0, 150.0)
        bars["ETF_EU"][TUESDAY] = (180.0, 180.0, 170.0, 170.0)
        bars["ETF_EU"][WEDNESDAY] = (180.0, 190.0, 180.0, 190.0)

    earned = labels(make_neural_market(mutate=jump_before_the_entry), xpar, MONDAY)

    assert earned[0, 0] == 0.0


def test_a_split_alone_is_not_a_return(
    make_neural_market: MarketBuilder, make_actions, xpar: TradingCalendar
) -> None:
    def halve_from_wednesday(bars, levels) -> None:
        bars["ETF_EU"][TUESDAY] = (100.0, 100.0, 100.0, 100.0)
        bars["ETF_EU"][WEDNESDAY] = (51.0, 51.0, 51.0, 51.0)

    known = datetime(2026, 3, 10, 8, 0, tzinfo=ZoneInfo("UTC"))
    actions = make_actions([("ETF_EU", ActionType.SPLIT, WEDNESDAY, 2.0, known)])
    reader = make_neural_market(mutate=halve_from_wednesday, actions=actions)

    earned = labels(reader, xpar, MONDAY)

    # Two shares at 51 for one at 100: +2%, not -49%.
    assert earned[0, 0] == pytest.approx(0.02)


def test_a_missing_open_stops_the_calibration_and_names_the_session(
    make_neural_market: MarketBuilder, xpar: TradingCalendar
) -> None:
    def lose_an_open(bars, levels) -> None:
        del bars["ETF_OTHER"][WEDNESDAY]

    reader = make_neural_market(mutate=lose_an_open)

    with pytest.raises(MissingForwardOpen, match="ETF_OTHER 2026-03-11"):
        labels(reader, xpar, MONDAY, TUESDAY)


def test_an_open_after_the_training_period_cannot_be_read(
    neural_market: MarketDataReader, xpar: TradingCalendar
) -> None:
    builder = ForwardOpenReturnBuilder(neural_market, xpar, TIMETABLE)

    with pytest.raises(ValueError, match="purge the decisions first"):
        builder.build([date(2026, 6, 29)], FUNDS, known_until=KNOWN_UNTIL)


def test_a_decision_whose_label_reaches_the_validation_is_purged(xpar: TradingCalendar) -> None:
    sessions = [date(2026, 6, 25), date(2026, 6, 26), date(2026, 6, 29), date(2026, 6, 30)]

    kept, purged = purge(sessions, xpar, date(2026, 7, 1))

    # Friday 26 June is bought on the 29th and measured to the 30th: kept. Monday
    # 29 June would be measured to the open of 1 July, the first validation day.
    assert kept == (date(2026, 6, 25), date(2026, 6, 26))
    assert purged == (date(2026, 6, 29), date(2026, 6, 30))


def test_the_training_set_is_every_purged_decision_in_order_with_its_input(
    neural_config: NeuralStrategyConfig, neural_market: MarketDataReader, calendars
) -> None:
    dataset = build_training_dataset(neural_config, neural_market, calendars, TIMETABLE)

    assert dataset.decisions[0] == date(2026, 1, 12)
    assert dataset.decisions[-1] == date(2026, 6, 26)
    assert list(dataset.decisions) == sorted(dataset.decisions)
    assert dataset.purged == (date(2026, 6, 29), date(2026, 6, 30))
    assert dataset.inputs.shape == (len(dataset.decisions), neural_config.input_size)
    assert dataset.forward_returns.shape == (len(dataset.decisions), 2)
    assert bool(dataset.valid.all())
    assert dataset.valid_share == 1.0
    # The offline input of a decision is the one the builder gives at that instant.
    day = dataset.decisions[40]
    context = SignalContext(
        market=neural_market.at(TIMETABLE.decision_instant(day)),
        instruments=neural_market.instruments,
        calendars=calendars,
    )
    assert tuple(dataset.inputs[40]) == NeuralFeatureBuilder(neural_config).build(context).values


def test_what_follows_the_training_period_is_not_in_the_training_set(
    neural_config: NeuralStrategyConfig,
    neural_market: MarketDataReader,
    make_neural_market: MarketBuilder,
    calendars: CalendarRegistry,
) -> None:
    """The look-ahead guard: rewriting the validation and the test changes no input or label."""

    def rewrite_from_validation(bars, levels) -> None:
        for prices in bars.values():
            for day in [day for day in prices if day >= neural_config.validation_start]:
                prices[day] = tuple(value * 2.0 for value in prices[day])
        for day in [day for day in levels if day >= neural_config.validation_start]:
            levels[day] = 55.0

    other = make_neural_market("other", mutate=rewrite_from_validation)

    original = build_training_dataset(neural_config, neural_market, calendars, TIMETABLE)
    rewritten = build_training_dataset(neural_config, other, calendars, TIMETABLE)

    assert np.array_equal(rewritten.inputs, original.inputs)
    assert np.array_equal(rewritten.forward_returns, original.forward_returns)


def test_an_invalid_day_stays_in_the_sequence_and_is_reported(
    neural_config: NeuralStrategyConfig, make_neural_market: MarketBuilder, calendars
) -> None:
    def stop_publishing_for_a_week(bars, levels) -> None:
        for day in [day for day in levels if date(2026, 3, 9) <= day <= date(2026, 3, 13)]:
            del levels[day]

    reader = make_neural_market(mutate=stop_publishing_for_a_week)
    config = NeuralStrategyConfig.from_definition(
        neural_config.definition() | {"minimum_valid_share": 0.90}
    )

    dataset = build_training_dataset(config, reader, calendars, TIMETABLE)

    invalid = [day for day, ok in zip(dataset.decisions, dataset.valid, strict=True) if not ok]
    # The 9th reads the 6th, one session old: still valid. The 10th to the 13th are not.
    assert invalid == [date(2026, 3, day) for day in (10, 11, 12, 13)]
    assert {(day, name) for day, name, _ in dataset.anomalies} == {
        (day, "RATE_US") for day in invalid
    }
    assert np.isnan(dataset.inputs[dataset.decisions.index(invalid[0])]).all()
    assert np.isfinite(dataset.forward_returns).all()
    with pytest.raises(InsufficientCalibrationData, match="valid inputs"):
        build_training_dataset(
            NeuralStrategyConfig.from_definition(
                neural_config.definition() | {"minimum_valid_share": 0.99}
            ),
            reader,
            calendars,
            TIMETABLE,
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"minimum_training_decisions": 1000}, "1000 are required"),
        ({"minimum_validation_sessions": 252}, "252 are required"),
    ],
)
def test_periods_that_are_too_short_are_refused_and_not_replaced(
    neural_config, neural_market, calendars, changes, message
) -> None:
    config = NeuralStrategyConfig.from_definition(neural_config.definition() | changes)

    with pytest.raises(InsufficientCalibrationData, match=message):
        build_training_dataset(config, neural_market, calendars, TIMETABLE)


def test_a_fund_that_cannot_be_bought_on_the_reference_calendar_is_refused(
    neural_config, neural_market, calendars
) -> None:
    config = NeuralStrategyConfig.from_definition(
        neural_config.definition()
        | {"feature_ids": ["ETF_EU", "IDX_US", "RATE_US"], "tradable_ids": ["ETF_EU", "IDX_US"]}
    )

    with pytest.raises(ValueError, match="IDX_US must be a tradable bar instrument of XPAR"):
        build_training_dataset(config, neural_market, calendars, TIMETABLE)
