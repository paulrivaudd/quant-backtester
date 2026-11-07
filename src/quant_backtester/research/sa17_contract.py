"""Load SA17's preregistered, per-fund execution cost assumptions."""

from __future__ import annotations

import tomllib
from pathlib import Path

from quant_backtester.execution.costs import CostModel
from quant_backtester.numbers import require_finite_positive


def load_sector_costs(path: Path, *, multiplier: float = 1.0) -> dict[str, CostModel]:
    """Build explicit sector models, scaling every cost term in stress runs.

    Quotes in the file are provenance only; crossed quotes are never turned
    into negative costs. Each model uses the separately declared assumption.
    External references and the monetary instrument need their own costs.
    """
    require_finite_positive(multiplier, "multiplier")
    with path.open("rb") as stream:
        config = tomllib.load(stream)
    return {
        name: CostModel(
            commission_rate=config["commission_rate"] * multiplier,
            minimum_commission=config["minimum_commission_eur"] * multiplier,
            half_spread_rate=parameters["half_spread_rate"] * multiplier,
            slippage_rate=config["slippage_rate"] * multiplier,
        )
        for name, parameters in config["costs"].items()
    }
