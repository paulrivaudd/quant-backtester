from pathlib import Path

import pytest

from quant_backtester.research.sa17_contract import load_sector_costs

COSTS = Path(__file__).resolve().parents[2] / "research/SA17/costs.toml"
SECTORS = (
    "SA17_ETF_ENERGY",
    "SA17_ETF_MATERIALS",
    "SA17_ETF_INDUSTRIALS",
    "SA17_ETF_CONSUMER_DISCRETIONARY",
    "SA17_ETF_CONSUMER_STAPLES",
    "SA17_ETF_HEALTH_CARE",
    "SA17_ETF_FINANCIALS",
    "SA17_ETF_TECHNOLOGY",
    "SA17_ETF_COMMUNICATION",
    "SA17_ETF_UTILITIES",
)


def test_declared_costs_and_real_stress_all_terms():
    base = load_sector_costs(COSTS, SECTORS)
    stress = load_sector_costs(COSTS, SECTORS, multiplier=2)
    assert len(base) == 10
    assert base["SA17_ETF_TECHNOLOGY"].half_spread_rate == 0.0015
    assert len({cost.half_spread_rate for cost in base.values()}) > 1
    for name, cost in base.items():
        terms = cost.definition()
        assert all(isinstance(value, float) for value in terms.values())
        assert stress[name].definition() == pytest.approx(
            {term: 2 * value for term, value in terms.items() if isinstance(value, float)}
        )


@pytest.mark.parametrize(
    "sectors",
    [
        SECTORS[:-1],  # a traded fund without an override would cost the default
        (*SECTORS, "SA17_ETF_REAL_ESTATE"),  # an override nobody trades
        (*SECTORS[:-1], "SA17_ETF_COMMUNICATION_SERVICES"),  # a renamed key
    ],
)
def test_overrides_must_match_the_traded_sectors_exactly(sectors):
    with pytest.raises(ValueError, match="match exactly"):
        load_sector_costs(COSTS, sectors)


@pytest.mark.parametrize("multiplier", [1.5, 3.0, 0.5])
def test_only_the_preregistered_stress_is_accepted(multiplier):
    with pytest.raises(ValueError, match="preregistered stress"):
        load_sector_costs(COSTS, SECTORS, multiplier=multiplier)
