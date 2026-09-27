"""A first backtest, offline: the real engine on an invented market.

Run from the repository root, with nothing downloaded::

    uv run python scripts/demo.py
    uv run python scripts/demo.py --figures demo_output

Two synthetic funds are drawn from a fixed seed (see ``quant_backtester.demo``),
written to a temporary store and read back through the project's own reader.
A monthly momentum rotation and a buy-and-hold of the steadier fund are run
over 2025, under the same costs, and both reports are printed. The numbers
describe invented prices: they show how the engine works, not whether a rule
does.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from quant_backtester.backtest.schedule import Monthly
from quant_backtester.demo import demo_runner
from quant_backtester.strategies.examples import BuyAndHold, MomentumRotation

SEED = 20240101
"""The seed of the demo prices, printed with the run."""

PERIOD = ("2025-01-02", "2025-12-31")
"""The measured period; 2024 is the warm-up the signals read."""

UNIVERSE = ("FUND_A", "FUND_B")
"""The two demo funds."""


def main(argv: Sequence[str] | None = None) -> int:
    """Run the demo and print its reports.

    Parameters
    ----------
    argv : Sequence[str] | None
        Command-line arguments; ``sys.argv[1:]`` when ``None``.

    Returns
    -------
    int
        The exit status, 0 on success.
    """
    parser = argparse.ArgumentParser(
        description="A first backtest, offline: the real engine on an invented market."
    )
    parser.add_argument(
        "--figures",
        type=Path,
        help="write the equity and drawdown figures of the rotation there",
    )
    arguments = parser.parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="quant_backtester_demo_") as scratch:
        runner = demo_runner(Path(scratch) / "store", seed=SEED)
        rotation = runner.run(
            MomentumRotation(lookback_sessions=60, top_n=1),
            UNIVERSE,
            *PERIOD,
            schedule=Monthly(),
        )
        control = runner.run(BuyAndHold(instruments=("FUND_A",)), UNIVERSE, *PERIOD)

        print(f"Synthetic market, seed {SEED}: invented prices, not market data.\n")
        print("== Momentum rotation, 60 sessions, top 1, monthly ==")
        print(rotation.report().render())
        print()
        print(rotation.compare().render())
        print("\n== Control: buy and hold FUND_A ==")
        print(control.report().render())

        if arguments.figures is not None:
            arguments.figures.mkdir(parents=True, exist_ok=True)
            rotation.plot().savefig(arguments.figures / "equity.png", dpi=160)
            rotation.plot_drawdown().savefig(arguments.figures / "drawdown.png", dpi=160)
            print(f"\nFigures written to {arguments.figures}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
