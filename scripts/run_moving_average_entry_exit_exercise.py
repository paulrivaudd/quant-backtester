"""Exercise 3: run MovingAverageEntryExitETF and read its results.

The answer to exercise 2, which bought and sold ``ETF_WORLD`` on one average
and was chopped every time the price hovered around it: buy when the close is
above its 50-session average, sell only when it is below its 100-session one.
From the repository root, once the store is filled:

    uv run python scripts/run_moving_average_entry_exit_exercise.py \
        --output moving_average_entry_exit_output

The runner, its costs, its capital, its period and its benchmark are those of
``scripts/run_golden_cross_exercise.py``, imported and not copied, and so is
its figure of a price and two averages: the three exercises differ by the rule
and by nothing else.

The rule was written after looking at the 100-session average drawn over the
run of exercise 2. This period has been looked at each time: the run describes
a history and tests nothing.

The tests are in ``tests/strategies/test_moving_average_entry_exit.py``.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from run_golden_cross_exercise import (
    FIGURE_DPI,
    PERIOD,
    STORE,
    UNIVERSE,
    build_runner,
    cross_figure,
    moving_averages,
    print_run,
    session_date,
)

from quant_backtester.backtest.runner import StrategyResult
from quant_backtester.strategies import MovingAverageEntryExitETF

STRATEGY = MovingAverageEntryExitETF(
    instrument_id="ETF_WORLD", entry_sessions=50, exit_sessions=100
)
"""The strategy of the exercise, its three parameters written and not left to a default."""


def save_figures(
    result: StrategyResult, directory: Path, strategy: MovingAverageEntryExitETF
) -> None:
    """Save the equity, drawdown and moving-average figures of the run as PNG files.

    Parameters
    ----------
    result : StrategyResult
        The finished run.
    directory : Path
        Output folder, created if it does not exist.
    strategy : MovingAverageEntryExitETF
        The strategy of the run: the instrument and the two lengths to draw.

    Notes
    -----
    The averages of ``moving_averages.png`` are recomputed here on the adjusted
    closes as they are known after the last close of the run, and not as each
    decision saw them. The two coincide for a fund with no dividend and no
    split; otherwise a distribution paid since moves the level of every
    earlier price, not its position against its own averages when it was read.
    """
    directory.mkdir(parents=True, exist_ok=True)
    result.plot().savefig(directory / "equity.png", dpi=FIGURE_DPI)
    result.plot_drawdown().savefig(directory / "drawdown.png", dpi=FIGURE_DPI)

    reader = result.reader.at(result.records()[-1].valuation_time)
    closes = reader.adjusted_history(strategy.instrument_id, end=result.end)
    calendar = result.reader.calendars.get(result.reader.reference_calendar_id)
    first = session_date(closes.index[0])
    sessions = [session.session_date for session in calendar.sessions(first, result.end)]
    averages = moving_averages(closes, sessions, strategy.entry_sessions, strategy.exit_sessions)
    weights = result.weights()[strategy.instrument_id]
    figure = cross_figure(
        averages.loc[result.start :],
        held={session_date(day) for day, weight in weights.items() if weight > 0},
        fills=result.fills(),
        fast=strategy.entry_sessions,
        slow=strategy.exit_sessions,
        title=f"{strategy.instrument_id}  buy above MA{strategy.entry_sessions}, sell below "
        f"MA{strategy.exit_sessions}  {result.start} to {result.end}",
    )
    figure.savefig(directory / "moving_averages.png", dpi=FIGURE_DPI)


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
    parser = argparse.ArgumentParser(description="Run the moving-average entry/exit exercise.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("moving_average_entry_exit_output"),
        help="where the equity, drawdown and moving-average figures are written",
    )
    arguments = parser.parse_args(argv)

    result = build_runner(STORE).run(STRATEGY, UNIVERSE, *PERIOD)
    print_run(result)
    save_figures(result, arguments.output, STRATEGY)
    print(f"\nFigures written to {arguments.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
