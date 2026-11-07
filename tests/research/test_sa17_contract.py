from pathlib import Path

import pytest

from quant_backtester.research.sa17_contract import load_sector_costs


def test_declared_costs_and_real_stress_all_terms():
    path = Path(__file__).resolve().parents[2] / "research/SA17/costs.toml"
    base = load_sector_costs(path)
    stress = load_sector_costs(path, multiplier=2)
    assert len(base) == 10
    assert base["SA17_ETF_TECHNOLOGY"].half_spread_rate == 0.0015
    assert len({cost.half_spread_rate for cost in base.values()}) > 1
    for name, cost in base.items():
        terms = cost.definition()
        assert all(isinstance(value, float) for value in terms.values())
        assert stress[name].definition() == pytest.approx(
            {term: 2 * value for term, value in terms.items() if isinstance(value, float)}
        )
