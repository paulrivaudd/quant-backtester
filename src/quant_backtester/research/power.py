"""Prospective Gaussian power approximations, not evidence from a backtest.

The annual active information ratio is mean active return over tracking error.
These calculations assume independent stationary returns and known long-run
variance. Serial dependence, selection and multiple tests reduce actual power.
"""

from __future__ import annotations

import math
from statistics import NormalDist

from quant_backtester.numbers import require_finite_positive


def information_ratio_power(information_ratio: float, years: float, alpha: float = 0.05) -> float:
    """Return approximate two-sided power for an annual active information ratio."""
    require_finite_positive(years, "years")
    if not math.isfinite(information_ratio) or not 0 < alpha < 1:
        raise ValueError("Expected a finite IR and alpha strictly between zero and one")
    normal = NormalDist()
    critical = normal.inv_cdf(1 - alpha / 2)
    shift = information_ratio * math.sqrt(years)
    return normal.cdf(-critical - shift) + 1 - normal.cdf(critical - shift)


def detectable_information_ratio(years: float, power: float = 0.8, alpha: float = 0.05) -> float:
    """Return the usual normal approximation to the IR needed for target power.

    ``(z[1-alpha/2] + z[power]) / sqrt(years)`` neglects the tiny opposite-tail
    contribution. It is not the critical observed IR for a significance test.
    """
    require_finite_positive(years, "years")
    if not 0.5 < power < 1 or not 0 < alpha < 1:
        raise ValueError("Expected power in (0.5, 1) and alpha in (0, 1)")
    normal = NormalDist()
    return (normal.inv_cdf(1 - alpha / 2) + normal.inv_cdf(power)) / math.sqrt(years)
