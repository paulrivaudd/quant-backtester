"""Exercise 2: run MovingAverageBandETF and read its results.

The answer to the golden cross of exercise 1, which bought and sold long after
the move: compare the close of ``ETF_WORLD`` with its 50-session average
directly. The fund is bought when its close passes above the average and sold
when it passes below. From the repository root, once the store is filled:

    uv run python scripts/run_moving_average_band_exercise.py --output moving_average_band_output

The runner, its costs, its capital, its period and its benchmark are those of
``scripts/run_golden_cross_exercise.py``, imported and not copied, so the two
runs differ by the rule and by nothing else.

The rule and its levels were settled after three runs of a first reading of the
idea, which bought below the average and sold above it, at 90%/110%, 95%/105%
and 100%/100%. This period has been looked at each time: the run describes a
history and tests nothing.

The tests are in ``tests/strategies/test_moving_average_band.py``.
"""

from __future__ import annotations

import argparse
import math
import sys
from collections.abc import Collection, Sequence
from datetime import date
from pathlib import Path

import pandas as pd
from matplotlib.figure import Figure
from run_golden_cross_exercise import (
    FIGURE_DPI,
    HELD_COLOUR,
    PERIOD,
    PRICE_COLOUR,
    SELL_COLOUR,
    SLOW_COLOUR,
    STORE,
    UNIVERSE,
    build_runner,
    print_run,
    session_date,
)

from quant_backtester.backtest.runner import StrategyResult
from quant_backtester.strategies import MovingAverageBandETF

STRATEGY = MovingAverageBandETF(
    instrument_id="ETF_WORLD", window_sessions=50, sell_below=1.0, buy_above=1.0
)
"""The strategy of the exercise, its four parameters written and not left to a default."""

LEVEL_COLOUR = "#c05621"
"""Colour of the two levels around the average."""


def band_levels(
    closes: pd.Series,  # type: ignore[type-arg]
    sessions: Sequence[date],
    window: int,
    sell_below: float,
    buy_above: float,
) -> pd.DataFrame:
    """Return the close, its moving average and the two levels, one row per expected session.

    Parameters
    ----------
    closes : pd.Series
        Adjusted closes indexed by session date, as known after the close of
        the last session of ``sessions``.
    sessions : Sequence[date]
        The expected sessions of the calendar, in order, holes included.
    window : int
        Length of the average, in sessions.
    sell_below, buy_above : float
        The two levels, as multiples of the average.

    Returns
    -------
    pd.DataFrame
        Columns ``close``, ``average``, ``sell_level`` and ``buy_level``,
        indexed by ``sessions``. The average of a session reads the closes of
        that session and of the ones before it only. It is ``NaN``, and both
        levels with it, until its ``window`` consecutive sessions all have a
        close: the signal's contract, which refuses a window with a hole rather
        than filling it with older sessions.
    """
    known = {session_date(day): float(value) for day, value in closes.items()}
    frame = pd.DataFrame(
        {"close": [known.get(day, math.nan) for day in sessions]},
        index=pd.Index(list(sessions), name="session_date"),
    )
    frame["average"] = frame["close"].rolling(window, min_periods=window).mean()
    frame["sell_level"] = frame["average"] * sell_below
    frame["buy_level"] = frame["average"] * buy_above
    return frame


def band_figure(
    levels: pd.DataFrame,
    held: Collection[date],
    fills: pd.DataFrame,
    *,
    strategy: MovingAverageBandETF,
    title: str,
) -> Figure:
    """Draw the price, its average, the two levels and what the run did about them.

    Parameters
    ----------
    levels : pd.DataFrame
        The result of :func:`band_levels`, cut to the period to draw.
    held : Collection[date]
        The sessions at whose close the run held the instrument.
    fills : pd.DataFrame
        The executions of the run: columns ``session_date`` and ``side``.
    strategy : MovingAverageBandETF
        The strategy of the run: the window and the two levels, for the legend.
    title : str
        What the figure shows.

    Returns
    -------
    Figure
        The close, its average, and each level that is not the average itself; a coloured
        background on the sessions invested; a cross on the price, green at
        every buy and red at every sell.

    Raises
    ------
    ValueError
        If ``levels`` holds no session.

    Notes
    -----
    The curves explain, they do not decide: the background and the crosses
    come from the run itself. An order is executed at the open after the close
    that reached a level, so a cross falls one session after it.
    """
    if len(levels) == 0:
        raise ValueError("there is nothing to draw: the levels hold no session")
    days = list(levels.index)
    window = strategy.window_sessions
    figure = Figure(figsize=(11, 5.5), layout="constrained")
    axes = figure.add_subplot()
    axes.fill_between(
        days,
        0.0,
        1.0,
        where=[day in held for day in days],
        transform=axes.get_xaxis_transform(),
        color=HELD_COLOUR,
        alpha=0.10,
        linewidth=0.0,
        label="invested",
    )
    axes.plot(days, list(levels["close"]), color=PRICE_COLOUR, linewidth=0.9, label="close")
    axes.plot(days, list(levels["average"]), color=SLOW_COLOUR, linewidth=1.5, label=f"MA{window}")
    for column, level, style, verb in (
        ("buy_level", strategy.buy_above, "--", "buy above"),
        ("sell_level", strategy.sell_below, ":", "sell below"),
    ):
        if level == 1.0:
            # The level is the average itself, which is drawn already.
            continue
        axes.plot(
            days,
            list(levels[column]),
            color=LEVEL_COLOUR,
            linewidth=1.1,
            linestyle=style,
            label=f"{verb} {level:.0%} of MA{window}",
        )
    for side, colour in (("BUY", HELD_COLOUR), ("SELL", SELL_COLOUR)):
        traded = [day for day in fills.loc[fills["side"] == side, "session_date"] if day in days]
        prices = [float(levels.loc[day, "close"]) for day in traded]
        axes.scatter(
            traded,
            prices,
            marker="x",
            color=colour,
            s=90,
            linewidths=2.2,
            zorder=3,
            label=side.lower(),
        )
    axes.set_title(title)
    axes.set_ylabel("adjusted close")
    axes.grid(visible=True, alpha=0.25)
    axes.legend(loc="upper left", frameon=False)
    return figure


def save_figures(result: StrategyResult, directory: Path, strategy: MovingAverageBandETF) -> None:
    """Save the equity, drawdown and band figures of the run as PNG files.

    Parameters
    ----------
    result : StrategyResult
        The finished run.
    directory : Path
        Output folder, created if it does not exist.
    strategy : MovingAverageBandETF
        The strategy of the run: the instrument, the window and the levels to draw.

    Notes
    -----
    The average of ``moving_average_band.png`` is recomputed here on the
    adjusted closes as they are known after the last close of the run, and not
    as each decision saw them. The two coincide for a fund with no dividend and
    no split; otherwise a distribution paid since moves the level of every
    earlier price, not its position against its own average when it was read.
    """
    directory.mkdir(parents=True, exist_ok=True)
    result.plot().savefig(directory / "equity.png", dpi=FIGURE_DPI)
    result.plot_drawdown().savefig(directory / "drawdown.png", dpi=FIGURE_DPI)

    reader = result.reader.at(result.records()[-1].valuation_time)
    closes = reader.adjusted_history(strategy.instrument_id, end=result.end)
    calendar = result.reader.calendars.get(result.reader.reference_calendar_id)
    first = session_date(closes.index[0])
    sessions = [session.session_date for session in calendar.sessions(first, result.end)]
    levels = band_levels(
        closes, sessions, strategy.window_sessions, strategy.sell_below, strategy.buy_above
    )
    weights = result.weights()[strategy.instrument_id]
    figure = band_figure(
        levels.loc[result.start :],
        held={session_date(day) for day, weight in weights.items() if weight > 0},
        fills=result.fills(),
        strategy=strategy,
        title=f"{strategy.instrument_id}  buy above {strategy.buy_above:.0%}, sell below "
        f"{strategy.sell_below:.0%} of MA{strategy.window_sessions}  "
        f"{result.start} to {result.end}",
    )
    figure.savefig(directory / "moving_average_band.png", dpi=FIGURE_DPI)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the exercise and print its results.

    Parameters
    ----------
    argv : Sequence[str] | None
        Command-line arguments; ``sys.argv[1:]`` if ``None``.

    Returns
    -------
    int
        The exit code, 0 on success.
    """
    parser = argparse.ArgumentParser(description="Run the moving-average band exercise.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("moving_average_band_output"),
        help="where the equity, drawdown and band figures are written",
    )
    arguments = parser.parse_args(argv)

    result = build_runner(STORE).run(STRATEGY, UNIVERSE, *PERIOD)
    print_run(result)
    save_figures(result, arguments.output, STRATEGY)
    print(f"\nFigures written to {arguments.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
