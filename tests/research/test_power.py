import math

import pytest

from quant_backtester.research.power import (
    detectable_information_ratio,
    information_ratio_power,
)


def test_null_power_and_two_sided_symmetry():
    assert information_ratio_power(0, 8.25) == pytest.approx(0.05)
    assert information_ratio_power(0.3, 8.25) == pytest.approx(information_ratio_power(-0.3, 8.25))
    assert 0.13 < information_ratio_power(0.3, 8.25) < 0.15
    assert 0.29 < information_ratio_power(0.5, 8.25) < 0.31


def test_significance_is_not_eighty_percent_power():
    assert information_ratio_power(2 / math.sqrt(8.25), 8.25) < 0.52
    threshold = detectable_information_ratio(8.25)
    assert 0.97 < threshold < 0.98
    assert information_ratio_power(threshold, 8.25) == pytest.approx(0.8, abs=0.00001)


@pytest.mark.parametrize("years", [0, -1, float("nan"), float("inf")])
def test_invalid_horizon(years):
    with pytest.raises(ValueError):
        information_ratio_power(0.3, years)
    with pytest.raises(ValueError):
        detectable_information_ratio(years)
