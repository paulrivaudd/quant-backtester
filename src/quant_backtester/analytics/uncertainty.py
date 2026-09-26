"""How sure a comparison is: a paired block bootstrap of a strategy against its control.

A Sharpe ratio of 0.54 against 0.67 over 437 sessions says nothing until one
knows how much either figure moves with the sample. Two intervals computed
apart say little more: the two books hold correlated assets on the same days,
and what matters is the spread of their *difference*. So the difference is
resampled as a pair - the same blocks of sessions drawn for both series, so
that what they share stays shared, and in blocks, so that what one session
owes to the one before is kept (audit of archive 9, C02).

Everything the result depends on is declared and recorded with it: the block
length, the number of draws, the seed, the level. The generator is created
from the seed here; no global random state is read.

What this does not do: correct for how many variants were tried before this
one. The register counts runs, and many of them share periods and rules, so
their number is not a number of independent trials; a deflated Sharpe built on
it would claim a precision nobody has. Nor does it make a revised series
point-in-time, or an idealised execution real.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from itertools import pairwise

import numpy as np
import pandas as pd


class PairedStatistic(Enum):
    """What difference between the two books is resampled."""

    MEAN_RETURN = "MEAN_RETURN"
    """Mean per-session return of the strategy less the control's, annualised
    by multiplying by the sessions in a year."""

    SHARPE = "SHARPE"
    """Annualised Sharpe ratio of the strategy less the control's, on the
    per-session returns, with no risk-free rate: the same rate would be taken
    from both."""


@dataclass(frozen=True, slots=True)
class PairedBootstrap:
    """The difference between two books, and how far it moves with the sample.

    Attributes
    ----------
    statistic : PairedStatistic
        What was measured.
    estimate : float
        The difference on the sessions as they happened.
    low, high : float
        The equal-tailed percentile interval of the resampled differences.
    level : float
        Its coverage, for instance ``0.90``.
    sessions : int
        Per-session returns the two books share.
    block : int
        Length of the blocks of consecutive sessions drawn.
    draws : int
        Number of resamples.
    seed : int
        Seed of the generator the draws came from.
    """

    statistic: PairedStatistic
    estimate: float
    low: float
    high: float
    level: float
    sessions: int
    block: int
    draws: int
    seed: int

    def definition(self) -> dict[str, object]:
        """Return the result and everything it depends on, as it is recorded."""
        return {
            "statistic": self.statistic.value,
            "estimate": self.estimate,
            "low": self.low,
            "high": self.high,
            "level": self.level,
            "sessions": self.sessions,
            "block": self.block,
            "draws": self.draws,
            "seed": self.seed,
        }


def _returns(equity: pd.Series) -> list[float]:  # type: ignore[type-arg]
    """Return the per-session returns of an equity curve."""
    values = [float(value) for value in equity]
    return [after / before - 1.0 for before, after in pairwise(values)]


def _measure(
    statistic: PairedStatistic, first: list[float], second: list[float], sessions_per_year: int
) -> float:
    """Return one book's statistic less the other's."""
    if statistic is PairedStatistic.MEAN_RETURN:
        return (math.fsum(first) - math.fsum(second)) / len(first) * sessions_per_year
    return _sharpe(first, sessions_per_year) - _sharpe(second, sessions_per_year)


def _sharpe(returns: list[float], sessions_per_year: int) -> float:
    """Return an annualised Sharpe ratio with no risk-free rate; zero for a flat book."""
    mean = math.fsum(returns) / len(returns)
    variance = math.fsum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
    if variance == 0.0:
        return 0.0
    return mean / math.sqrt(variance) * math.sqrt(sessions_per_year)


def paired_block_bootstrap(
    strategy: pd.Series,  # type: ignore[type-arg]
    control: pd.Series,  # type: ignore[type-arg]
    *,
    statistic: PairedStatistic,
    block: int,
    draws: int,
    seed: int,
    level: float,
    sessions_per_year: int,
) -> PairedBootstrap:
    """Resample the difference between a strategy and its control, in blocks of shared sessions.

    Parameters
    ----------
    strategy, control : pd.Series
        Equity curves over the same sessions, in the same order.
    statistic : PairedStatistic
        The difference to measure.
    block : int
        Length of the blocks of consecutive sessions. Declared, never
        inferred: it is the assumption about how long the series remember.
    draws : int
        Number of resamples.
    seed : int
        Seed of the generator; the same seed gives the same draws.
    level : float
        Coverage of the interval, in ``(0, 1)``.
    sessions_per_year : int
        Annualisation, the analytics convention's.

    Returns
    -------
    PairedBootstrap
        The difference, its interval, and everything they were computed with.

    Raises
    ------
    ValueError
        If the curves do not cover the same sessions, hold fewer than three
        points, or a parameter is out of range - a block longer than the
        returns, fewer than a hundred draws, a level outside ``(0, 1)``.

    Notes
    -----
    A moving-block bootstrap: each resample strings together blocks starting
    at uniformly drawn sessions until it is as long as the sample, and applies
    the same indices to both books. It is written as plain loops over indices:
    the samples here are a few hundred sessions, and a reader should be able
    to check the resampling line by line.
    """
    if not strategy.index.equals(control.index):
        raise ValueError("the strategy and its control must cover the same sessions")
    first, second = _returns(strategy), _returns(control)
    count = len(first)
    if count < 2:
        raise ValueError("a comparison needs at least three sessions, two returns")
    if not 1 <= block <= count:
        raise ValueError(f"a block of {block} does not fit {count} returns")
    if draws < 100:
        raise ValueError(f"{draws} draws are too few to read a tail from")
    if not 0.0 < level < 1.0:
        raise ValueError(f"level is a coverage in (0, 1), got {level}")
    generator = np.random.default_rng(seed)
    starts_available = count - block + 1
    resampled: list[float] = []
    for _ in range(draws):
        indices: list[int] = []
        while len(indices) < count:
            start = int(generator.integers(0, starts_available))
            indices.extend(range(start, start + block))
        indices = indices[:count]
        resampled.append(
            _measure(
                statistic,
                [first[index] for index in indices],
                [second[index] for index in indices],
                sessions_per_year,
            )
        )
    tail = (1.0 - level) / 2.0
    ordered = sorted(resampled)
    return PairedBootstrap(
        statistic=statistic,
        estimate=_measure(statistic, first, second, sessions_per_year),
        low=float(np.quantile(ordered, tail)),
        high=float(np.quantile(ordered, 1.0 - tail)),
        level=level,
        sessions=count,
        block=block,
        draws=draws,
        seed=seed,
    )
