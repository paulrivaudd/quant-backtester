"""Tests of SA18's trend filter: the level, the average, the switch and its cost."""

from __future__ import annotations

from datetime import date

import pytest

from quant_backtester.research.sa18_trend import above_average, levels, run_switch_book


def months(count: int, year: int = 2000) -> list[date]:
    return [date(year + index // 12, index % 12 + 1, 1) for index in range(count)]


def test_levels_compound_from_one() -> None:
    assert levels([0.10, -0.50, 1.0]) == pytest.approx([1.10, 0.55, 1.10])
    assert levels([]) == []


@pytest.mark.parametrize("change", [-1.0, float("nan"), float("inf")])
def test_a_change_that_cannot_compound_is_refused(change: float) -> None:
    with pytest.raises(ValueError, match="finite and above -1"):
        levels([0.01, change])


def test_the_signal_compares_the_level_with_the_average_that_includes_it() -> None:
    # Averages of three: (1+2+3)/3 = 2 < 3; (2+3+1)/3 = 2 > 1; (3+1+2)/3 = 2, not above.
    assert above_average([1.0, 2.0, 3.0, 1.0, 2.0], 3) == [None, None, True, False, False]


def test_no_signal_before_the_window_is_full_and_a_window_of_one_is_refused() -> None:
    assert above_average([1.0], 2) == [None]
    assert above_average([], 2) == []
    with pytest.raises(ValueError, match="at least two"):
        above_average([1.0, 2.0], 1)


def test_the_signal_at_a_month_ignores_later_levels() -> None:
    """The look-ahead guard: changing the future leaves every earlier signal as it was."""
    values = [1.0, 1.2, 1.1, 1.3, 0.9, 1.0]
    altered = [*values[:4], 50.0, 0.01]
    assert above_average(altered, 3)[:4] == above_average(values, 3)[:4]


def test_the_book_holds_what_the_previous_month_end_decided() -> None:
    asset = [0.50, 0.10, -0.20, 0.30, 0.05]
    bills = [0.01] * 5
    signal = [True, True, False, True, False]
    book = run_switch_book(months(5), asset, bills, signal, date(2000, 2, 1), date(2000, 5, 1), 0.0)
    assert [record.invested for record in book] == [True, True, False, True]
    assert [record.gross for record in book] == [0.10, -0.20, 0.01, 0.05]
    # The first position is free; a switch is a change from the month before.
    assert [record.traded for record in book] == [False, False, True, True]
    assert [record.month for record in book] == months(5)[1:]


def test_a_switch_costs_the_rate_once_on_the_whole_book() -> None:
    signal = [True, False, False, True]
    book = run_switch_book(
        months(4),
        [0.0, 0.0, 0.0, 0.10],
        [0.0] * 4,
        signal,
        date(2000, 2, 1),
        date(2000, 4, 1),
        0.01,
    )
    assert [record.net for record in book] == pytest.approx([0.0, -0.01, 0.0])
    assert book[1].gross == 0.0
    # No switch, no cost: the bill month after the exit is untouched.
    assert book[2].net == book[2].gross


def test_a_book_that_starts_in_bills_pays_when_it_first_buys() -> None:
    book = run_switch_book(
        months(3), [0.0, 0.0, 0.20], [0.0] * 3, [False, True, True], date(2000, 2, 1),
        date(2000, 3, 1), 0.01,
    )  # fmt: skip
    assert [record.traded for record in book] == [False, True]
    assert book[1].net == pytest.approx(0.99 * 1.20 - 1.0)


def test_the_held_month_does_not_read_its_own_month_end() -> None:
    """The look-ahead guard: the signal of a month and of later ones cannot change its return."""
    asset, bills = [0.0, 0.10, -0.30, 0.20], [0.0, 0.01, 0.01, 0.01]
    first, last = date(2000, 2, 1), date(2000, 3, 1)
    book = run_switch_book(months(4), asset, bills, [True, False, True, True], first, last, 0.0)
    other = run_switch_book(months(4), asset, bills, [True, False, False, None], first, last, 0.0)
    assert book == other


def test_a_single_held_month() -> None:
    book = run_switch_book(
        months(2), [0.0, 0.07], [0.0, 0.01], [False, None], date(2000, 2, 1), date(2000, 2, 1), 0.01
    )
    assert len(book) == 1
    assert (book[0].invested, book[0].traded, book[0].net) == (False, False, 0.01)


def test_a_month_without_a_signal_before_it_is_refused() -> None:
    with pytest.raises(ValueError, match="no signal"):
        run_switch_book(
            months(3), [0.0] * 3, [0.0] * 3, [None, None, True], date(2000, 2, 1),
            date(2000, 3, 1), 0.0,
        )  # fmt: skip
    with pytest.raises(ValueError, match="no month before it"):
        run_switch_book(
            months(3), [0.0] * 3, [0.0] * 3, [True] * 3, date(2000, 1, 1), date(2000, 3, 1), 0.0
        )


def test_misaligned_series_and_unknown_or_reversed_months_are_refused() -> None:
    with pytest.raises(ValueError, match="same months"):
        run_switch_book(
            months(3), [0.0] * 2, [0.0] * 3, [True] * 3, date(2000, 2, 1), date(2000, 3, 1), 0.0
        )
    with pytest.raises(ValueError, match="not a month of the series"):
        run_switch_book(
            months(3), [0.0] * 3, [0.0] * 3, [True] * 3, date(2000, 2, 1), date(2001, 3, 1), 0.0
        )
    with pytest.raises(ValueError, match="after the last"):
        run_switch_book(
            months(3), [0.0] * 3, [0.0] * 3, [True] * 3, date(2000, 3, 1), date(2000, 2, 1), 0.0
        )
