"""Tests of SA16's long-history study: the monthly series, the rule and the reading."""

from __future__ import annotations

import math
from datetime import date

import pytest

from quant_backtester.research.sa16_long_history import (
    GOLD,
    GROWTH,
    MonthlyPanel,
    Reading,
    annualised_volatility,
    average_changes,
    beats,
    budget_target,
    budget_weights,
    fixed_target,
    month_end_changes,
    reading,
    run_book,
)


def months(count: int, year: int = 2000) -> tuple[date, ...]:
    return tuple(date(year + index // 12, index % 12 + 1, 1) for index in range(count))


def panel(growth: list[float], gold: list[float]) -> MonthlyPanel:
    count = len(growth)
    return MonthlyPanel(months(count), tuple(growth), tuple(gold), (0.0,) * count, (0.0,) * count)


FRED = (
    "observation_date,NASDAQCOM\n"
    "2000-01-28,100.0\n"
    "2000-01-31,110.0\n"
    "2000-02-01,.\n"
    "2000-02-28,121.0\n"
    "2000-02-29,\n"
    "2000-03-31,108.9\n"
)


def test_a_month_end_change_runs_between_the_last_values_of_two_months() -> None:
    changes = month_end_changes(FRED, "NASDAQCOM")
    # January has no month before it; a missing last day falls back on the day before.
    assert set(changes) == {date(2000, 2, 1), date(2000, 3, 1)}
    assert changes[date(2000, 2, 1)] == pytest.approx(0.10)
    assert changes[date(2000, 3, 1)] == pytest.approx(-0.10)


def test_a_month_without_a_value_breaks_the_chain_instead_of_spanning_it() -> None:
    text = "observation_date,X\n2000-01-31,100\n2000-03-31,120\n2000-04-28,132\n"
    assert set(month_end_changes(text, "X")) == {date(2000, 4, 1)}


def test_days_added_later_do_not_change_the_months_before_them() -> None:
    """The look-ahead guard for the month-end series."""
    longer = FRED + "2000-04-28,500.0\n"
    earlier = month_end_changes(FRED, "NASDAQCOM")
    assert {k: v for k, v in month_end_changes(longer, "NASDAQCOM").items() if k in earlier} == (
        earlier
    )


@pytest.mark.parametrize(
    "text",
    [
        "",
        "date,NASDAQCOM\n2000-01-31,1\n",
        "observation_date,OTHER\n2000-01-31,1\n",
        "observation_date,NASDAQCOM\n2000-01-31,1\n2000-01-31,2\n",
        "observation_date,NASDAQCOM\n2000-02-01,1\n2000-01-31,2\n",
        "observation_date,NASDAQCOM\n2000-01-31,0\n",
        "observation_date,NASDAQCOM\n2000-01-31,nan\n",
        "observation_date,NASDAQCOM\n2000-01-31,1,2\n",
    ],
)
def test_a_csv_that_is_not_the_series_is_refused(text: str) -> None:
    with pytest.raises(ValueError):
        month_end_changes(text, "NASDAQCOM")


def test_the_change_of_an_average_is_from_the_month_before() -> None:
    changes = average_changes(months(3), [100.0, 110.0, 99.0])
    assert list(changes) == list(months(3)[1:])
    assert changes[date(2000, 2, 1)] == pytest.approx(0.10)
    assert changes[date(2000, 3, 1)] == pytest.approx(-0.10)
    assert average_changes(months(1), [100.0]) == {}
    with pytest.raises(ValueError):
        average_changes(months(2), [100.0])


def test_the_volatility_is_the_annualised_deviation_of_log_changes() -> None:
    up, down = math.exp(0.02) - 1.0, math.exp(-0.02) - 1.0
    # Logs +0.02, -0.02: mean 0, sample variance 0.0008.
    assert annualised_volatility([up, down], 12) == pytest.approx(math.sqrt(0.0008 * 12))
    assert annualised_volatility([up, down], 12, 1.5) == pytest.approx(math.sqrt(0.0008 * 18))
    with pytest.raises(ValueError):
        annualised_volatility([up], 12)


def test_the_weights_are_the_budget_over_the_volatility() -> None:
    # 0.75 / 0.20 = 3.75 and 0.25 / 0.10 = 2.5: 60% and 40%.
    weights = budget_weights(0.20, 0.10, 0.75, 0.05)
    assert weights[GROWTH] == pytest.approx(0.6)
    assert weights[GOLD] == pytest.approx(0.4)
    # A series that did not move is floored, not divided by.
    floored = budget_weights(0.20, 0.0, 0.75, 0.05)
    assert floored[GOLD] == pytest.approx(5.0 / 8.75)
    for budget in (0.0, 1.0):
        with pytest.raises(ValueError):
            budget_weights(0.2, 0.1, budget, 0.05)


def test_a_book_drifts_inside_its_band_and_pays_to_come_back() -> None:
    held = panel([0.0, 0.50, 0.0, 0.0], [0.0, 0.0, 0.0, 0.0])
    first, last = held.months[0], held.months[-1]
    half = fixed_target({GROWTH: 0.5, GOLD: 0.5})

    book = run_book(held, first, last, half, band=0.05, cost_rate=0.01)

    # Month 1: the first purchase is free. Month 2: +50% on half the book.
    assert book[0].turnover == 0.0 and not book[0].traded
    assert book[1].gross == pytest.approx(0.25)
    assert book[1].net == pytest.approx(0.25)
    # Before month 3 the growth weight is 0.75/1.25 = 0.6: 10 points off, so it trades.
    assert book[2].traded
    assert book[2].turnover == pytest.approx(0.2)
    assert book[2].weights == {GROWTH: 0.5, GOLD: 0.5}
    assert book[2].net == pytest.approx(-0.01 * 0.2)
    assert not book[3].traded

    wide = run_book(held, first, last, half, band=0.15, cost_rate=0.01)
    assert not any(month.traded for month in wide)
    assert wide[2].weights[GROWTH] == pytest.approx(0.6)


def test_a_single_month_is_held_at_its_target_for_free() -> None:
    held = panel([0.02], [-0.04])
    book = run_book(
        held, held.months[0], held.months[0], fixed_target({GROWTH: 0.5, GOLD: 0.5}), 0.05, 0.01
    )
    assert len(book) == 1
    assert book[0].net == book[0].gross == pytest.approx(-0.01)
    with pytest.raises(ValueError):
        run_book(held, date(1999, 1, 1), held.months[0], fixed_target({GROWTH: 1, GOLD: 0}), 0, 0)


def swings(count: int) -> tuple[list[float], list[float]]:
    growth = [0.06 if index % 2 else -0.04 for index in range(count)]
    gold = [0.01 if index % 3 else -0.02 for index in range(count)]
    return growth, gold


def test_the_target_reads_only_the_months_before_the_one_it_is_held_over() -> None:
    growth, gold = swings(12)
    rule = budget_target(panel(growth, gold), 6, 0.75, 0.05, 1.5, 12)
    expected = budget_weights(
        annualised_volatility(growth[2:8], 12),
        annualised_volatility(gold[2:8], 12, 1.5),
        0.75,
        0.05,
    )
    assert rule(8) == pytest.approx(expected)
    with pytest.raises(ValueError, match="fewer than 6"):
        rule(5)


def test_a_future_month_changes_nothing_before_it() -> None:
    """The look-ahead guard: a crash planted in month 10 leaves months 6 to 9 as they were."""
    growth, gold = swings(12)
    planted_growth, planted_gold = list(growth), list(gold)
    planted_growth[10], planted_gold[10] = -0.60, 0.80

    def book(g: list[float], h: list[float]) -> list:
        held = panel(g, h)
        rule = budget_target(held, 6, 0.75, 0.05, 1.5, 12)
        return run_book(held, held.months[6], held.months[11], rule, 0.05, 0.001)

    clean, planted = book(growth, gold), book(planted_growth, planted_gold)
    assert planted[:4] == clean[:4]
    # The weights held over month 10 itself were set before it.
    assert planted[4].weights == clean[4].weights
    assert planted[4].net != clean[4].net


def measures(cagr: float, sharpe: float, drawdown: float) -> dict[str, float | None]:
    return {"cagr": cagr, "sharpe": sharpe, "max_drawdown": drawdown}


@pytest.mark.parametrize(
    ("candidate", "expected"),
    [
        (measures(0.12, 1.0, -0.30), True),
        (measures(0.12, 1.0, -0.32), True),  # 2 points deeper is allowed
        (measures(0.12, 1.0, -0.321), False),
        (measures(0.10, 1.0, -0.30), False),  # an equal CAGR is not higher
        (measures(0.12, 0.8, -0.30), False),
    ],
)
def test_beating_a_reference_is_sa16s_criterion(candidate, expected) -> None:
    assert beats(candidate, measures(0.10, 0.8, -0.30), 0.02) is expected


def test_a_criterion_without_its_measures_is_refused() -> None:
    with pytest.raises(ValueError, match="sharpe"):
        beats(measures(0.1, 1.0, -0.3) | {"sharpe": None}, measures(0.1, 0.8, -0.3), 0.02)


@pytest.mark.parametrize(
    ("declared", "stressed", "holm_p", "expected"),
    [
        (True, True, 0.01, Reading.SUPPORTED_RETROSPECTIVE),
        (True, True, 0.05, Reading.UNCERTAIN),
        (True, False, 0.01, Reading.UNCERTAIN),
        (False, True, 0.01, Reading.NOT_SUPPORTED),
    ],
)
def test_the_reading_follows_the_frozen_rule(declared, stressed, holm_p, expected) -> None:
    assert reading(declared, stressed, holm_p, 0.05) is expected


def test_a_panel_refuses_gaps_unequal_series_and_values_that_are_not_numbers() -> None:
    with pytest.raises(ValueError, match="consecutive"):
        MonthlyPanel(
            (date(2000, 1, 1), date(2000, 3, 1)), (0.0,) * 2, (0.0,) * 2, (0.0,) * 2, (0.0,) * 2
        )
    with pytest.raises(ValueError, match="gold"):
        MonthlyPanel(months(2), (0.0,) * 2, (0.0,), (0.0,) * 2, (0.0,) * 2)
    with pytest.raises(ValueError, match="finite"):
        MonthlyPanel(months(1), (math.nan,), (0.0,), (0.0,), (0.0,))
    with pytest.raises(ValueError, match="no month"):
        MonthlyPanel((), (), (), (), ())
    with pytest.raises(ValueError, match="not a month"):
        panel([0.0], [0.0]).position(date(1999, 1, 1))


def test_constant_weights_name_both_assets_and_add_up_to_one() -> None:
    with pytest.raises(ValueError):
        fixed_target({GROWTH: 0.5, GOLD: 0.4})
    with pytest.raises(ValueError):
        fixed_target({GROWTH: 1.0})
