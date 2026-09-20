"""Drawing a run: what ends up on the figure, and what never gets called.

A plot is the fastest way to see a shape a table hides and the slowest way to
lose an argument about what was measured, so the tests here are narrow: the
figure holds the curves it was given, it is labelled, and nothing opens a
window.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, time

import pandas as pd
import pytest
from matplotlib.figure import Figure
from matplotlib.lines import Line2D

from quant_backtester.analytics.config import AnalyticsConfig
from quant_backtester.analytics.plots import drawdown_figure, equity_figure
from quant_backtester.backtest.engine import Timetable
from quant_backtester.backtest.runner import StrategyRunner
from quant_backtester.data.calendars import CalendarRegistry, TradingCalendar
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.strategies.examples import BuyAndHold

PARIS = Timetable(decision_time=time(23, 0), execution_time=time(9, 1), timezone="Europe/Paris")
CONFIG = AnalyticsConfig(sessions_per_year=255, risk_free_rate=0.0)


def _ydata(line: Line2D) -> list[float]:
    """Return the values a line was drawn with."""
    return [float(value) for value in line.get_ydata()]  # type: ignore[union-attr]


def a_curve() -> pd.Series:  # type: ignore[type-arg]
    """Return a three-session equity curve."""
    return pd.Series(
        [100.0, 105.0, 102.0],
        index=[date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3)],
        name="net",
    )


@pytest.fixture
def result(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    calendars: CalendarRegistry,
    xpar: TradingCalendar,
    prices: Callable[..., dict[date, float]],
):
    """Return a finished run over the rising synthetic fund."""
    market = make_market(
        {
            "ETF_EU": make_bars("ETF_EU", xpar, prices(100.0, 1.0)),
            "ETF_OTHER": make_bars("ETF_OTHER", xpar, prices(200.0, 3.0)),
        }
    )
    runner = StrategyRunner(
        reader=market,
        calendars=calendars,
        reference_calendar_id="XPAR",
        base_currency="EUR",
        analytics=CONFIG,
        initial_cash=10_000.0,
        timetable=PARIS,
    )
    return runner.run(BuyAndHold(instruments=("ETF_EU",)), ["ETF_EU"], "2026-09-01", "2026-09-14")


def test_an_equity_figure_holds_the_curve_it_was_given() -> None:
    """One line, three points, and the values are the ones passed in."""
    figure = equity_figure(a_curve(), title="a run")

    axes = figure.axes[0]
    assert len(axes.lines) == 1
    assert _ydata(axes.lines[0]) == [100.0, 105.0, 102.0]


def test_a_figure_is_labelled_with_what_it_shows() -> None:
    """A plot of an unnamed run over an unnamed period is a picture, not a result."""
    figure = equity_figure(a_curve(), title="momentum_rotation  2026-09-01 to 2026-09-03")

    assert "momentum_rotation" in figure.axes[0].get_title()


def test_the_gross_book_is_drawn_behind_the_net_one() -> None:
    """The gap between them is what execution took."""
    figure = equity_figure(a_curve(), title="a run", gross=a_curve() * 1.01)

    labels = [line.get_label() for line in figure.axes[0].lines]
    assert labels == ["gross", "net"]


def test_a_benchmark_is_drawn_beside_the_strategy() -> None:
    """Normalised elsewhere; this only draws it."""
    benchmark = a_curve().rename("ETF_OTHER")

    figure = equity_figure(a_curve(), title="a run", benchmark=benchmark)

    assert "ETF_OTHER" in [line.get_label() for line in figure.axes[0].lines]


def test_a_figure_of_nothing_is_refused() -> None:
    """An empty figure in a report reads as a flat strategy."""
    with pytest.raises(ValueError, match="nothing to draw"):
        equity_figure(pd.Series(dtype="float64"), title="a run")


def test_a_drawdown_figure_is_in_percent() -> None:
    """The axis a reader expects, and the sign it expects."""
    drawdown = pd.Series([0.0, -0.05], index=[date(2026, 9, 1), date(2026, 9, 2)])

    figure = drawdown_figure(drawdown, title="a drawdown")

    assert _ydata(figure.axes[0].lines[0]) == [0.0, -5.0]
    assert "%" in figure.axes[0].get_ylabel()


def test_a_result_draws_itself(result) -> None:
    """What a notebook calls, without reaching into the run."""
    figure = result.plot()

    assert isinstance(figure, Figure)
    assert result.strategy_id in figure.axes[0].get_title()


def test_a_result_draws_itself_against_a_benchmark(result) -> None:
    """The comparison a reader actually wants to see."""
    figure = result.plot(benchmark="ETF_OTHER")

    assert "ETF_OTHER" in [line.get_label() for line in figure.axes[0].lines]


def test_a_result_draws_its_drawdown(result) -> None:
    """And the curve is the one the analytics computed."""
    figure = result.plot_drawdown()

    assert "drawdown" in figure.axes[0].get_title()


def test_drawing_shows_nothing_by_itself(result, monkeypatch: pytest.MonkeyPatch) -> None:
    """A notebook displays it, a script saves it, and neither is forced on the other."""
    import matplotlib.pyplot as plt

    def refuse() -> None:
        raise AssertionError("show must not be called")

    monkeypatch.setattr(plt, "show", refuse)

    assert isinstance(result.plot(), Figure)
    assert isinstance(result.plot_drawdown(), Figure)
