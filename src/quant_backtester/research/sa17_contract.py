"""Load SA17's preregistered, per-fund execution cost assumptions."""

from __future__ import annotations

import tomllib
from collections.abc import Collection
from pathlib import Path

from quant_backtester.execution.costs import CostModel
from quant_backtester.numbers import require_finite_positive


def load_sector_costs(
    path: Path, sector_ids: Collection[str], *, multiplier: float = 1.0
) -> dict[str, CostModel]:
    """Build explicit sector models, scaling every cost term in stress runs.

    Parameters
    ----------
    path : Path
        The committed ``costs.toml``: rates as fractions of traded value, the
        commission floor in EUR, and one ``[costs.<instrument id>]`` table per
        traded sector fund.
    sector_ids : Collection[str]
        The traded sector funds of the book, exactly. An override missing for
        one of them, or declared for a fund the book does not trade, is a
        mistake: the engine charges an instrument without an override the
        default model, without saying so.
    multiplier : float
        ``1.0`` for the declared costs, or the file's preregistered
        ``stress_multiplier`` for the stress run. Any other value is refused:
        the stress was fixed before the runs.

    Returns
    -------
    dict[str, CostModel]
        One model per sector fund, every term (rates and floor) multiplied by
        ``multiplier``.

    Raises
    ------
    ValueError
        If the funds of the file and ``sector_ids`` differ, or ``multiplier``
        is neither ``1.0`` nor the preregistered stress.

    Notes
    -----
    Quotes in the file are provenance only; crossed quotes are never turned
    into negative costs. Each model uses the separately declared assumption.
    External references and the monetary instrument need their own costs.
    """
    require_finite_positive(multiplier, "multiplier")
    with path.open("rb") as stream:
        config = tomllib.load(stream)
    declared = set(config["costs"])
    expected = set(sector_ids)
    if declared != expected:
        raise ValueError(
            f"{path.name} declares costs for {sorted(declared - expected) or 'no extra fund'} "
            f"and none for {sorted(expected - declared) or 'no missing fund'}: the sector "
            "funds and their cost overrides must match exactly"
        )
    stress = float(config["stress_multiplier"])
    if multiplier not in (1.0, stress):
        raise ValueError(
            f"multiplier {multiplier} is neither the declared costs (1.0) nor the "
            f"preregistered stress ({stress})"
        )
    return {
        name: CostModel(
            commission_rate=config["commission_rate"],
            minimum_commission=config["minimum_commission_eur"],
            half_spread_rate=parameters["half_spread_rate"],
            slippage_rate=config["slippage_rate"],
        ).scaled(multiplier)
        for name, parameters in config["costs"].items()
    }
