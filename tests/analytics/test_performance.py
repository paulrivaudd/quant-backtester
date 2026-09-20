"""The statistics, on curves small enough to check by hand.

Two things are being pinned here. The arithmetic - a compounded return, a
spread scaled to a year, a fall measured from a past high - and the refusals: a
run that cannot support a figure gets ``None``, never a zero that would be read
as a measurement.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Callable
from datetime import date

import pytest

from quant_backtester.analytics.config import AnalyticsConfig
from quant_backtester.analytics.curves import Book, equity_curve
from quant_backtester.analytics.performance import PerformanceStats, max_drawdown
from quant_backtester.backtest.engine import BacktestResult

RunBuilder = Callable[..., BacktestResult]

CONFIG = AnalyticsConfig(sessions_per_year=252, risk_free_rate=0.0, minimum_sessions=3)
"""A convention that lets a three-session run be annualised, so the tests stay short."""


def stats(run: RunBuilder, equity: list[float], **overrides: object) -> PerformanceStats:
    """Return the statistics of a hand-written net curve."""
    config = overrides.pop("config", CONFIG)
    assert isinstance(config, AnalyticsConfig)
    return PerformanceStats.from_equity(
        equity_curve(run(equity, **overrides), Book.NET),  # type: ignore[arg-type]
        config,
    )


def test_the_total_return_is_the_first_session_against_the_last(run: RunBuilder) -> None:
    """What happened in between is a different question."""
    assert stats(run, [100.0, 50.0, 125.0]).total_return == pytest.approx(0.25)


def test_a_year_of_gains_annualises_to_itself(run: RunBuilder) -> None:
    """A run covering one year compounds to what it made, and no more."""
    # 366 sessions a day apart: a leap year of calendar time, to the day.
    curve = [100.0 * (1.0 + 0.10) ** (position / 365) for position in range(366)]

    annualised = stats(run, curve).annualised_return

    assert annualised == pytest.approx(0.10, rel=1e-3)


def test_two_years_of_gains_are_not_counted_twice(run: RunBuilder) -> None:
    """21 percent over two years is ten a year, not twenty-one."""
    curve = [100.0, 110.0, 121.0]

    annualised = stats(run, curve, step_days=366).annualised_return

    assert annualised == pytest.approx(0.10, rel=1e-2)


def test_a_run_too_short_is_not_annualised_at_all(run: RunBuilder) -> None:
    """Compounding a fortnight into a year is how a report prints a lie.

    The figures that do not depend on the length of the run - the total return,
    the drawdown - are still there, because they are still true.
    """
    config = AnalyticsConfig(sessions_per_year=252, risk_free_rate=0.0, minimum_sessions=60)

    short = stats(run, [100.0, 101.0, 102.0], config=config)

    assert short.annualised_return is None
    assert short.sharpe_ratio is None
    assert short.total_return == pytest.approx(0.02)


def test_a_volatility_needs_two_returns(run: RunBuilder) -> None:
    """One return has no spread; zero of them have nothing at all."""
    assert stats(run, [100.0, 110.0]).annualised_volatility is None
    assert stats(run, [100.0]).annualised_volatility is None
    assert stats(run, [100.0]).best_session is None


def test_the_volatility_is_the_spread_of_the_sessions_scaled_to_a_year(
    run: RunBuilder,
) -> None:
    """Hand-checkable: returns of +10%, -10%, +10% against a 252-session year."""
    curve = [100.0, 110.0, 99.0, 108.9]
    expected = statistics.stdev([0.1, -0.1, 0.1]) * math.sqrt(252)

    assert stats(run, curve).annualised_volatility == pytest.approx(expected)


def test_a_book_that_never_moves_has_no_ratio(run: RunBuilder) -> None:
    """A Sharpe ratio over a spread of zero is an infinity, not a result."""
    flat = stats(run, [100.0, 100.0, 100.0, 100.0])

    assert flat.annualised_volatility == pytest.approx(0.0)
    assert flat.sharpe_ratio is None


def test_the_risk_free_rate_is_subtracted_before_the_ratio_is_taken(
    run: RunBuilder,
) -> None:
    """A strategy that earns the cash rate has earned nothing to speak of."""
    curve = [100.0, 110.0, 99.0, 108.9]
    against_nothing = stats(run, curve).sharpe_ratio
    against_a_rate = stats(
        run,
        curve,
        config=AnalyticsConfig(sessions_per_year=252, risk_free_rate=0.05, minimum_sessions=3),
    ).sharpe_ratio

    assert against_nothing is not None
    assert against_a_rate is not None
    assert against_a_rate < against_nothing


def test_the_worst_fall_is_named_with_its_dates(run: RunBuilder) -> None:
    """100, 120, 90, 130: a fall of a quarter, from the second to the third."""
    drawdown = stats(run, [100.0, 120.0, 90.0, 130.0]).drawdown

    assert drawdown.depth == pytest.approx(-0.25)
    assert drawdown.peak_date == date(2026, 1, 6)
    assert drawdown.trough_date == date(2026, 1, 7)
    assert drawdown.recovery_date == date(2026, 1, 8)
    assert drawdown.recovered


def test_a_fall_the_run_ended_in_has_no_recovery(run: RunBuilder) -> None:
    """The depth alone would read the same as one that came back in a week."""
    drawdown = stats(run, [100.0, 120.0, 90.0, 100.0]).drawdown

    assert drawdown.depth == pytest.approx(-0.25)
    assert drawdown.recovery_date is None
    assert not drawdown.recovered


def test_a_curve_that_only_rose_has_no_drawdown(run: RunBuilder) -> None:
    """Zero, and no dates: there was no fall to date."""
    drawdown = stats(run, [100.0, 110.0, 120.0]).drawdown

    assert drawdown.depth == 0.0
    assert drawdown.peak_date is None
    assert drawdown.trough_date is None


def test_a_run_of_nothing_has_no_drawdown_either(run: RunBuilder) -> None:
    """An empty range is not an error, and not a fall of zero percent either."""
    empty = equity_curve(run([]), Book.NET)

    assert max_drawdown(empty).depth == 0.0
    assert max_drawdown(empty).trough_date is None


def test_a_later_recovery_does_not_soften_an_earlier_fall(run: RunBuilder) -> None:
    """The look-ahead guard, on the statistic it matters most for.

    The first three sessions are the same run in both cases. Measured against
    a peak that came later, the fall of a quarter would read as a fall against
    1 000 and the strategy would look ruined - or, the other way round, a run
    ending high would have its falls measured against highs that had not
    happened, which is the version that flatters.
    """
    lived_through = stats(run, [100.0, 120.0, 90.0]).drawdown

    with_the_future = stats(run, [100.0, 120.0, 90.0, 1_000.0]).drawdown

    assert with_the_future.depth == pytest.approx(lived_through.depth)
    assert with_the_future.trough_date == lived_through.trough_date
    assert with_the_future.peak_date == lived_through.peak_date


def test_the_best_and_the_worst_session_are_reported(run: RunBuilder) -> None:
    """One session doing all the work is a data problem until proven otherwise."""
    record = stats(run, [100.0, 110.0, 99.0])

    assert record.best_session == pytest.approx(0.1)
    assert record.worst_session == pytest.approx(-0.1)


def test_a_run_of_nothing_still_answers(run: RunBuilder) -> None:
    """An empty range is a run that did nothing, not a crash.

    It happens whenever a backtest is asked for a window the calendar holds no
    session in, and the answer is a record of zeros and absences rather than an
    exception nobody expected.
    """
    empty = stats(run, [])

    assert empty.sessions == 0
    assert empty.total_return == 0.0
    assert empty.annualised_return is None
    assert empty.annualised_volatility is None
    assert empty.drawdown.depth == 0.0
