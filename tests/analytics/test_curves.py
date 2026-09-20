"""The three curves, and the one property that makes a drawdown honest."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

import pandas as pd
import pytest

from quant_backtester.analytics.curves import (
    Book,
    drawdown_curve,
    elapsed_years,
    equity_curve,
    session_returns,
)
from quant_backtester.backtest.engine import BacktestResult

RunBuilder = Callable[..., BacktestResult]


def test_a_run_becomes_a_curve_indexed_by_its_sessions(run: RunBuilder) -> None:
    """The order the run walked, kept."""
    result = run([100.0, 101.0, 99.0])

    equity = equity_curve(result, Book.NET)

    assert list(equity) == [100.0, 101.0, 99.0]
    assert list(equity.index) == [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)]
    assert equity.index.name == "session_date"


def test_the_two_books_are_two_curves(run: RunBuilder) -> None:
    """The gross book paid nothing, and it is not the one an investor held."""
    result = run([100.0, 99.0], gross=[100.0, 101.0])

    assert list(equity_curve(result, Book.NET)) == [100.0, 99.0]
    assert list(equity_curve(result, Book.GROSS)) == [100.0, 101.0]


def test_the_book_has_to_be_named_by_the_enum(run: RunBuilder) -> None:
    """``"NET" in Book`` is true since Python 3.12, and ``"NET" is Book.NET`` is not.

    A membership test would wave the string through and then hand back the
    gross curve under a net name - the one mistake that turns a report into a
    lie about what an investor earned.
    """
    with pytest.raises(ValueError, match="book must be a Book"):
        equity_curve(run([100.0]), "NET")  # type: ignore[arg-type]


def test_a_run_of_nothing_is_an_empty_curve(run: RunBuilder) -> None:
    """A range with no session is not an error, and has no statistics either."""
    equity = equity_curve(run([]), Book.NET)

    assert equity.empty
    assert session_returns(equity).empty
    assert drawdown_curve(equity).empty


def test_the_first_session_has_no_return(run: RunBuilder) -> None:
    """There is nothing before it to be compared against.

    Reported as a zero it would be counted as a calm session and drag a
    volatility down, which is why it is left out instead.
    """
    returns = session_returns(equity_curve(run([100.0, 110.0, 99.0]), Book.NET))

    assert list(returns.index) == [date(2026, 1, 6), date(2026, 1, 7)]
    assert list(returns) == pytest.approx([0.1, -0.1])


def test_a_single_session_has_no_returns_at_all(run: RunBuilder) -> None:
    """One point is a position, not a performance."""
    assert session_returns(equity_curve(run([100.0]), Book.NET)).empty


def test_a_book_worth_nothing_is_not_a_percentage(run: RunBuilder) -> None:
    """A run that reached zero is looked at, not summarised."""
    with pytest.raises(ValueError, match="at or below zero"):
        session_returns(equity_curve(run([100.0, 0.0]), Book.NET))


def test_a_drawdown_is_measured_against_the_highest_point_so_far(run: RunBuilder) -> None:
    """Hand-checkable: 100, 120, 90, 120, 150."""
    drawdown = drawdown_curve(equity_curve(run([100.0, 120.0, 90.0, 120.0, 150.0]), Book.NET))

    assert list(drawdown) == pytest.approx([0.0, 0.0, -0.25, 0.0, 0.0])


def test_appending_a_later_session_changes_no_earlier_drawdown(run: RunBuilder) -> None:
    """The look-ahead guard of this layer, and its whole point.

    A drawdown measured against a peak that had not happened yet is not one
    anybody lived through. Here the run ends far above every earlier price, and
    the falls before it read exactly as they did when they happened.
    """
    lived_through = drawdown_curve(equity_curve(run([100.0, 120.0, 90.0]), Book.NET))

    with_the_future = drawdown_curve(
        equity_curve(run([100.0, 120.0, 90.0, 400.0, 1_000.0]), Book.NET)
    )

    assert list(with_the_future.iloc[:3]) == pytest.approx(list(lived_through))


def test_a_curve_that_only_rises_never_falls_below_a_peak(run: RunBuilder) -> None:
    """Zero is a measurement here, not a missing value."""
    assert list(
        drawdown_curve(equity_curve(run([100.0, 101.0, 102.0]), Book.NET))
    ) == pytest.approx([0.0, 0.0, 0.0])


def test_the_years_a_run_covers_are_calendar_years() -> None:
    """A strategy that trades twice a week still waits a whole year."""
    sessions = pd.Index([date(2024, 1, 1), date(2025, 1, 1)], name="session_date")

    assert elapsed_years(sessions) == pytest.approx(366 / 365.25)
    assert elapsed_years(pd.Index([date(2024, 1, 1)])) == 0.0
    assert elapsed_years(pd.Index([])) == 0.0
