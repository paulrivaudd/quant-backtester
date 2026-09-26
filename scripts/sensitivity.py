"""How much the README's reference run depends on how it is executed (C04).

Run from the repository root, once the store is filled::

    uv run python scripts/sensitivity.py

The reference rotation and its executable control are run over the README's
period under four simulations of the same orders - the opening auction's
notional or quantities fixed at the decision's close, at the declared costs or
at twice them - and each is printed next to the others. The figures are what
the simulation gives under each hypothesis; which one an account would get
depends on how it places its orders, which is the point of showing all four.
"""

from __future__ import annotations

from dataclasses import replace

from run_baselines import (
    CONTROL,
    EXECUTION,
    README_PERIOD,
    REFERENCE,
    UNIVERSE,
    number,
    percent,
    runner,
)

from quant_backtester.execution.costs import CostModel
from quant_backtester.execution.model import ExecutionModel, Sizing


def doubled(costs: CostModel) -> CostModel:
    """Return the same cost model with every rate and floor doubled."""
    return CostModel(
        commission_rate=2 * costs.commission_rate,
        minimum_commission=2 * costs.minimum_commission,
        half_spread_rate=2 * costs.half_spread_rate,
        slippage_rate=2 * costs.slippage_rate,
    )


SCENARIOS: tuple[tuple[str, ExecutionModel], ...] = (
    ("notional, costs x1", EXECUTION),
    ("notional, costs x2", replace(EXECUTION, costs=doubled(EXECUTION.costs))),
    ("overnight, costs x1", replace(EXECUTION, sizing=Sizing.AT_DECISION)),
    (
        "overnight, costs x2",
        replace(EXECUTION, costs=doubled(EXECUTION.costs), sizing=Sizing.AT_DECISION),
    ),
)
"""The four simulations: sizing at the auction or at the decision, costs once or twice."""


def main() -> None:
    """Run both books under every scenario and print one line each."""
    start, end = README_PERIOD
    base = runner()
    print(f"{'scenario':<22}{'book':<20}{'net':>9}{'sharpe':>8}{'costs':>10}{'rejects':>9}")
    for label, execution in SCENARIOS:
        runs = replace(base, execution=execution)
        for baseline in (REFERENCE, CONTROL):
            result = runs.run(baseline.strategy, UNIVERSE, start, end, schedule=baseline.schedule)
            report = result.report()
            print(
                f"{label:<22}{baseline.label:<20}{percent(report.net.total_return):>9}"
                f"{number(report.net.sharpe_ratio):>8}{report.costs.total:>10,.0f}"
                f"{report.quality.rejects:>9}",
                flush=True,
            )


if __name__ == "__main__":
    main()
