"""The night and the day of a session: what each is, and what it never reads."""

from __future__ import annotations

import math
from datetime import date

import pandas as pd
import pytest

from quant_backtester.analytics.segments import (
    BOOK_COLUMNS,
    segment_books,
    segment_returns,
    segment_summary,
)

D1, D2, D3, D4 = date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5)
FOUR_DAYS = [D1, D2, D3, D4]


def prices(values: dict[date, float]) -> pd.Series:  # type: ignore[type-arg]
    """Return a price series indexed by session date."""
    return pd.Series(list(values.values()), index=pd.Index(list(values), dtype="object"))


def hand_checked() -> pd.DataFrame:
    """Return three sessions whose segments can be computed in the head.

    Close 100; then open 110 (night +10%), close 99 (day -10%); then open 99
    (night 0%), close 108.9 (day +10%); then open 98.01 (night -10%), close
    98.01 (day 0%).
    """
    opens = prices({D1: 100.0, D2: 110.0, D3: 99.0, D4: 98.01})
    closes = prices({D1: 100.0, D2: 99.0, D3: 108.9, D4: 98.01})
    return segment_returns(opens, closes, closes, FOUR_DAYS)


def test_a_close_to_close_return_is_split_into_its_night_and_its_day() -> None:
    returns = hand_checked()
    assert list(returns.index) == [D2, D3, D4]
    assert list(returns["night"]) == pytest.approx([0.10, 0.0, -0.10])
    assert list(returns["day"]) == pytest.approx([-0.10, 0.10, 0.0])


def test_the_two_segments_multiply_back_to_the_close_to_close_return() -> None:
    returns = hand_checked()
    whole = (1.0 + returns["night"]) * (1.0 + returns["day"])
    assert list(whole) == pytest.approx([0.99, 1.1, 0.9])


def test_a_split_on_the_ex_date_is_not_read_as_an_overnight_fall() -> None:
    # Two for one before the open of D2: raw prices halve, adjusted ones do not.
    opens = prices({D1: 100.0, D2: 50.0})
    closes = prices({D1: 100.0, D2: 51.0})
    adjusted = prices({D1: 50.0, D2: 51.0})
    returns = segment_returns(opens, closes, adjusted, [D1, D2])
    assert returns.loc[D2, "night"] == pytest.approx(0.0)
    assert returns.loc[D2, "day"] == pytest.approx(0.02)


def test_a_session_after_a_missing_one_is_left_out_rather_than_given_two_nights() -> None:
    opens = prices({D1: 100.0, D3: 99.0, D4: 98.01})
    closes = prices({D1: 100.0, D3: 108.9, D4: 98.01})
    returns = segment_returns(opens, closes, closes, FOUR_DAYS)
    assert list(returns.index) == [D4]


def test_a_single_session_and_no_session_have_no_segment() -> None:
    one = prices({D1: 100.0})
    assert segment_returns(one, one, one, [D1]).empty
    assert segment_returns(one, one, one, []).empty
    assert list(segment_returns(one, one, one, []).columns) == ["night", "day"]


def test_a_price_at_or_below_zero_is_refused() -> None:
    opens = prices({D1: 100.0, D2: 0.0})
    closes = prices({D1: 100.0, D2: 99.0})
    with pytest.raises(ValueError, match="open on 2024-01-03"):
        segment_returns(opens, closes, closes, [D1, D2])


def test_a_later_price_does_not_change_an_earlier_segment() -> None:
    opens = prices({D1: 100.0, D2: 110.0, D3: 99.0, D4: 98.01})
    closes = prices({D1: 100.0, D2: 99.0, D3: 108.9, D4: 98.01})
    crash_opens = prices({D1: 100.0, D2: 110.0, D3: 99.0, D4: 1.0})
    crash_closes = prices({D1: 100.0, D2: 99.0, D3: 108.9, D4: 500.0})
    calm = segment_returns(opens, closes, closes, FOUR_DAYS)
    crash = segment_returns(crash_opens, crash_closes, crash_closes, FOUR_DAYS)
    pd.testing.assert_frame_equal(calm.iloc[:2], crash.iloc[:2])
    assert calm.loc[D4, "night"] != crash.loc[D4, "night"]


def test_the_summary_adds_the_log_returns_and_gives_the_night_its_share() -> None:
    returns = pd.DataFrame({"night": [0.02, 0.02], "day": [0.01, 0.01]}, index=[D2, D3])
    summary = segment_summary(returns)
    assert summary.sessions == 2
    assert summary.night_log_return == pytest.approx(2 * math.log(1.02))
    assert summary.day_log_return == pytest.approx(2 * math.log(1.01))
    assert summary.night_share == pytest.approx(math.log(1.02) / math.log(1.02 * 1.01))
    # The two differences are equal: no spread to measure a t-statistic against.
    assert summary.difference_t is None


def test_the_summary_t_statistic_is_the_mean_difference_over_its_standard_error() -> None:
    returns = pd.DataFrame(
        {"night": [math.expm1(0.03), math.expm1(0.01)], "day": [0.0, 0.0]}, index=[D2, D3]
    )
    # Differences 0.03 and 0.01: mean 0.02, standard deviation 0.01414, n = 2.
    assert segment_summary(returns).difference_t == pytest.approx(2.0)


def test_the_summary_of_nothing_has_no_share() -> None:
    summary = segment_summary(pd.DataFrame({"night": [], "day": []}))
    assert summary.sessions == 0
    assert summary.night_share is None
    assert summary.difference_t is None


def test_free_books_compound_each_segment_on_its_own() -> None:
    books = segment_books(hand_checked(), initial=100.0, cost_rate=0.0)
    assert list(books.columns) == list(BOOK_COLUMNS)
    assert list(books["hold"]) == pytest.approx([99.0, 108.9, 98.01])
    assert list(books["night_gross"]) == pytest.approx([110.0, 110.0, 99.0])
    assert list(books["day_gross"]) == pytest.approx([90.0, 99.0, 99.0])
    assert list(books["night_net"]) == list(books["night_gross"])
    assert list(books["day_net"]) == list(books["day_gross"])


def test_a_net_book_pays_both_legs_of_every_segment_and_hold_pays_one() -> None:
    returns = pd.DataFrame({"night": [0.0, 0.0], "day": [0.0, 0.0]}, index=[D2, D3])
    books = segment_books(returns, initial=100.0, cost_rate=0.01)
    round_trip = 0.99 / 1.01
    assert list(books["night_net"]) == pytest.approx([100.0 * round_trip, 100.0 * round_trip**2])
    assert list(books["day_net"]) == pytest.approx(list(books["night_net"]))
    assert list(books["night_gross"]) == [100.0, 100.0]
    assert list(books["hold"]) == pytest.approx([100.0 / 1.01, 100.0 / 1.01])


def test_books_of_no_session_are_empty() -> None:
    books = segment_books(
        pd.DataFrame({"night": [], "day": []}, dtype="float64"), initial=100.0, cost_rate=0.0
    )
    assert books.empty
    assert list(books.columns) == list(BOOK_COLUMNS)


@pytest.mark.parametrize(("initial", "cost_rate"), [(0.0, 0.0), (100.0, -0.1), (100.0, 1.0)])
def test_a_capital_or_a_cost_that_means_nothing_is_refused(
    initial: float, cost_rate: float
) -> None:
    with pytest.raises(ValueError, match=r"initial|cost_rate"):
        segment_books(hand_checked(), initial=initial, cost_rate=cost_rate)
