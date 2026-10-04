"""One number between 0 and 100% for a run: did it beat the market, and can that be trusted.

A table of twelve indicators does not rank two hundred strategies, and a
single Sharpe ratio ranks them wrongly: the best of two hundred looks good by
chance. The score answers one question - *would holding the market fund have
been the better decision* - through five blocks, each a number in ``[0, 1]``
read off a fixed scale:

- **market**: the information ratio and the regression alpha of the net book
  against the market fund bought and held with the same costs;
- **significance**: the deflated Sharpe ratio, the probability that the net
  Sharpe ratio is above the best one expected by chance among the trials that
  were run, given the sample's length, skewness and tails;
- **risk**: the maximum drawdown, as a ratio to the market's own;
- **robustness**: the share of consecutive sub-periods in which the book ended
  ahead of the market, and how much of the Sharpe ratio is left when every
  cost is paid twice;
- **implementation**: the share of the gross gain that execution took.

The blocks are combined by a weighted geometric mean, so that a block at zero
is not paid for by another: a book that lost to the market in every way but
was cheap to trade does not get a pass mark for being cheap.

Three rules keep the number honest. The scales and the weights are a named,
versioned constant (:data:`QUALITY_V1`): they are not tuned after a result is
seen, and a change is a new version. A sample shorter than a year of sessions
is not scored at all. And a measure the sample cannot support scores zero and
is named in the diagnostics, never skipped.

The score describes the curves it is handed. Handing it an out-of-sample
curve is the caller's job: for a fitted model that is its test period, and
never the period it was calibrated on.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

import numpy as np
import pandas as pd
from scipy.stats import kurtosis, norm, skew

from quant_backtester.analytics.config import RETURN_STD_TOLERANCE, AnalyticsConfig
from quant_backtester.analytics.curves import aligned_equity_curves
from quant_backtester.analytics.performance import max_drawdown
from quant_backtester.analytics.relative import RelativePerformanceStats
from quant_backtester.numbers import require_finite, require_finite_non_negative
from quant_backtester.signals.types import require_positive_int

EULER_MASCHERONI = 0.5772156649015329
"""The constant of the expected maximum of ``N`` standard normal draws."""

BLOCKS = ("market", "significance", "risk", "robustness", "implementation")
"""The five blocks of the score, in the order they are reported."""


@dataclass(frozen=True, slots=True)
class Scale:
    """A linear scale from a measure to ``[0, 1]``.

    Attributes
    ----------
    worst : float
        The measure at or beyond which the score is 0.
    best : float
        The measure at or beyond which the score is 1. Below ``worst`` when a
        smaller measure is the better one, as for a cost.

    Raises
    ------
    ValueError
        If the two bounds are equal or not finite.
    """

    worst: float
    best: float

    def __post_init__(self) -> None:
        """Refuse a scale with no slope."""
        require_finite(self.worst, "worst")
        require_finite(self.best, "best")
        if self.worst == self.best:
            raise ValueError("a scale needs two different bounds")

    def score(self, value: float | None) -> float:
        """Return the score of a measure; 0 for one that is missing or not finite."""
        if value is None or math.isnan(value):
            return 0.0
        position = (value - self.worst) / (self.best - self.worst)
        return min(1.0, max(0.0, position))

    def definition(self) -> dict[str, float]:
        """Return the scale as it is recorded."""
        return {"worst": self.worst, "best": self.best}


@dataclass(frozen=True, slots=True)
class QualityRules:
    """The scales and the weights of one version of the score.

    Attributes
    ----------
    version : str
        Name of this set of rules, recorded with every score.
    minimum_sessions : int
        Fewest sessions a sample is scored on.
    subperiods : int
        Consecutive sub-periods the sample is cut into for the stability
        measure.
    weights : Mapping[str, float]
        Weight of each block of :data:`BLOCKS`, summing to one.
    information_ratio, alpha, drawdown_ratio, subperiod_share, stress_retention, cost_drag : Scale
        The scale of each measure.

    Raises
    ------
    ValueError
        If a block has no weight, a weight is negative or the weights do not
        sum to one.
    """

    version: str
    minimum_sessions: int
    subperiods: int
    weights: Mapping[str, float]
    information_ratio: Scale
    alpha: Scale
    drawdown_ratio: Scale
    subperiod_share: Scale
    stress_retention: Scale
    cost_drag: Scale

    def __post_init__(self) -> None:
        """Refuse weights that do not describe a mean over the five blocks."""
        require_positive_int(self.minimum_sessions, "minimum_sessions")
        require_positive_int(self.subperiods, "subperiods")
        if set(self.weights) != set(BLOCKS):
            raise ValueError(f"the weights must be given for exactly {', '.join(BLOCKS)}")
        for name, weight in self.weights.items():
            require_finite_non_negative(weight, f"the weight of {name}")
        if not math.isclose(math.fsum(self.weights.values()), 1.0, abs_tol=1e-12):
            raise ValueError("the weights of the blocks must sum to one")
        object.__setattr__(self, "weights", MappingProxyType(dict(self.weights)))

    def definition(self) -> dict[str, object]:
        """Return the rules as they are recorded beside a score."""
        return {
            "version": self.version,
            "minimum_sessions": self.minimum_sessions,
            "subperiods": self.subperiods,
            "weights": dict(self.weights),
            "information_ratio": self.information_ratio.definition(),
            "alpha": self.alpha.definition(),
            "drawdown_ratio": self.drawdown_ratio.definition(),
            "subperiod_share": self.subperiod_share.definition(),
            "stress_retention": self.stress_retention.definition(),
            "cost_drag": self.cost_drag.definition(),
        }


QUALITY_V1 = QualityRules(
    version="v1",
    minimum_sessions=252,
    subperiods=6,
    weights={
        "market": 0.30,
        "significance": 0.25,
        "risk": 0.15,
        "robustness": 0.20,
        "implementation": 0.10,
    },
    # Half a point of information ratio behind the market is a zero, half a
    # point ahead a full mark; the market itself sits in the middle.
    information_ratio=Scale(worst=-0.5, best=0.5),
    # Five points of annual alpha either side of the market.
    alpha=Scale(worst=-0.05, best=0.05),
    # A drawdown half as deep as the market's is a full mark, one and a half
    # times as deep a zero.
    drawdown_ratio=Scale(worst=1.5, best=0.5),
    # Ahead of the market in three sub-periods out of four, or in one.
    subperiod_share=Scale(worst=0.25, best=0.75),
    # Costs paid twice leave all of the Sharpe ratio, or half of it.
    stress_retention=Scale(worst=0.5, best=1.0),
    # Execution took nothing of the gross gain, or thirty percent of it.
    cost_drag=Scale(worst=0.30, best=0.0),
)
"""Version 1 of the score, fixed on 2026-10-04 before any strategy was scored."""


@dataclass(frozen=True, slots=True)
class QualityScore:
    """The score of one run, its blocks and the measures they were read from.

    Attributes
    ----------
    score : float | None
        The weighted geometric mean of the blocks, in ``[0, 1]``. ``None``
        when the sample is too short to be scored.
    blocks : Mapping[str, float]
        The score of each block of :data:`BLOCKS`, in ``[0, 1]``.
    measures : Mapping[str, float | None]
        The measures behind the blocks, in their own units; ``None`` where
        the sample does not support one.
    diagnostics : tuple[str, ...]
        Why a measure is missing or the run was not scored, as stable codes.
    version : str
        The rules the score was computed under.
    """

    score: float | None
    blocks: Mapping[str, float]
    measures: Mapping[str, float | None]
    diagnostics: tuple[str, ...]
    version: str

    def __post_init__(self) -> None:
        """Freeze the two mappings."""
        object.__setattr__(self, "blocks", MappingProxyType(dict(self.blocks)))
        object.__setattr__(self, "measures", MappingProxyType(dict(self.measures)))

    @property
    def percent(self) -> float | None:
        """Return the score between 0 and 100, or ``None`` when there is none."""
        return None if self.score is None else 100.0 * self.score


def session_sharpe(equity: pd.Series, config: AnalyticsConfig) -> float | None:  # type: ignore[type-arg]
    """Return the Sharpe ratio of a curve per session, not annualised.

    Parameters
    ----------
    equity : pd.Series
        A book's worth, session by session.
    config : AnalyticsConfig
        Gives the risk-free rate of one session.

    Returns
    -------
    float | None
        ``mean(excess) / std(excess, ddof=1)`` of the simple session returns,
        or ``None`` when they do not vary. The unit the deflated Sharpe ratio
        works in, and the one the dispersion of a set of trials is stated in.
    """
    excess = _returns(equity) - config.risk_free_per_session
    if len(excess) < 2:
        return None
    deviation = float(np.std(excess, ddof=1))
    if deviation <= RETURN_STD_TOLERANCE:
        return None
    return float(np.mean(excess)) / deviation


def expected_maximum_sharpe(trials: int, trial_sharpe_std: float) -> float:
    """Return the best per-session Sharpe ratio expected by chance among several trials.

    Parameters
    ----------
    trials : int
        How many strategies were tried before this one was looked at.
    trial_sharpe_std : float
        Standard deviation of their per-session Sharpe ratios.

    Returns
    -------
    float
        ``std * ((1 - g) * Z(1 - 1/N) + g * Z(1 - 1/(N e)))`` with ``g`` the
        Euler-Mascheroni constant and ``Z`` the normal quantile: what the
        maximum of ``N`` skill-less trials is expected to show. Zero for a
        single trial.
    """
    require_positive_int(trials, "trials")
    require_finite_non_negative(trial_sharpe_std, "trial_sharpe_std")
    if trials == 1:
        return 0.0
    first = float(norm.ppf(1.0 - 1.0 / trials))
    second = float(norm.ppf(1.0 - 1.0 / (trials * math.e)))
    return trial_sharpe_std * ((1.0 - EULER_MASCHERONI) * first + EULER_MASCHERONI * second)


def deflated_sharpe_probability(
    equity: pd.Series,  # type: ignore[type-arg]
    config: AnalyticsConfig,
    *,
    trials: int,
    trial_sharpe_std: float,
) -> float | None:
    """Return the probability that a curve's Sharpe ratio beats the best expected by chance.

    Parameters
    ----------
    equity : pd.Series
        The net curve of the run.
    config : AnalyticsConfig
        Gives the risk-free rate of one session.
    trials : int
        How many strategies were tried.
    trial_sharpe_std : float
        Standard deviation of the trials' per-session Sharpe ratios.

    Returns
    -------
    float | None
        The deflated Sharpe ratio of Bailey and Lopez de Prado (2014), in
        ``[0, 1]``: ``Phi((SR - SR0) * sqrt(n - 1) / sqrt(1 - skew*SR +
        (kurtosis - 1)/4 * SR^2))``, where ``SR0`` is
        :func:`expected_maximum_sharpe`. ``None`` when the returns do not
        vary.

    Notes
    -----
    A short sample, a negative skew and fat tails all lower it: each makes a
    given Sharpe ratio easier to obtain without skill.
    """
    observed = session_sharpe(equity, config)
    if observed is None:
        return None
    excess = _returns(equity) - config.risk_free_per_session
    skewness = float(skew(excess))
    tails = float(kurtosis(excess, fisher=False))
    variance = 1.0 - skewness * observed + (tails - 1.0) / 4.0 * observed**2
    if variance <= 0.0:
        return None
    threshold = expected_maximum_sharpe(trials, trial_sharpe_std)
    statistic = (observed - threshold) * math.sqrt(len(excess) - 1) / math.sqrt(variance)
    return float(norm.cdf(statistic))


def quality_score(
    net: pd.Series,  # type: ignore[type-arg]
    gross: pd.Series,  # type: ignore[type-arg]
    market: pd.Series,  # type: ignore[type-arg]
    config: AnalyticsConfig,
    *,
    trials: int,
    trial_sharpe_std: float,
    rules: QualityRules,
) -> QualityScore:
    """Score one run against the market fund held over the same sessions.

    Parameters
    ----------
    net : pd.Series
        The run's equity net of costs, indexed by session.
    gross : pd.Series
        The same trades having paid nothing, over the same sessions.
    market : pd.Series
        Net equity of the market fund bought and held by the same engine with
        the same costs, over the same sessions.
    config : AnalyticsConfig
        Sessions per year and the risk-free rate, as for every other figure.
    trials : int
        How many strategies were tried in the search this run belongs to, this
        one included. The honest count, rejected ones included.
    trial_sharpe_std : float
        Standard deviation of those trials' per-session Sharpe ratios; zero
        for a single trial.
    rules : QualityRules
        The scales and the weights. Named by the caller, never defaulted.

    Returns
    -------
    QualityScore
        The score, each block and each measure. Not scored - ``score`` is
        ``None`` - under ``rules.minimum_sessions`` sessions.

    Raises
    ------
    ValueError
        If a curve is invalid, or the three do not hold the same sessions.

    Notes
    -----
    The stress measure pays every cost twice on the same trades:
    ``stressed = net - (gross - net)``, session by session. It ignores that a
    poorer book would have traded slightly smaller amounts, and needs no
    second run.
    """
    book, reference = aligned_equity_curves(net, market)
    if list(gross.index) != list(book.index):
        raise ValueError("the gross and the net curves must hold the same sessions")
    diagnostics: list[str] = []
    if len(book) < rules.minimum_sessions:
        return QualityScore(
            score=None,
            blocks=dict.fromkeys(BLOCKS, 0.0),
            measures={},
            diagnostics=("sample_too_short",),
            version=rules.version,
        )
    relative = RelativePerformanceStats.from_equity(book, reference, config)
    diagnostics.extend(relative.diagnostics)
    deflated = deflated_sharpe_probability(
        book, config, trials=trials, trial_sharpe_std=trial_sharpe_std
    )
    if deflated is None:
        diagnostics.append("sharpe_undefined")
    drawdown_ratio = _drawdown_ratio(book, reference)
    share = _subperiod_share(book, reference, rules.subperiods)
    retention = _stress_retention(book, gross, config)
    if retention is None:
        diagnostics.append("stress_undefined")
    drag = _cost_drag(book, gross)
    measures: dict[str, float | None] = {
        "information_ratio": relative.information_ratio,
        "alpha_annualised": relative.alpha_annualised,
        "deflated_sharpe_probability": deflated,
        "drawdown_ratio": drawdown_ratio,
        "subperiod_share": share,
        "stress_retention": retention,
        "cost_drag": drag,
    }
    blocks = {
        "market": 0.5
        * (
            rules.information_ratio.score(relative.information_ratio)
            + rules.alpha.score(relative.alpha_annualised)
        ),
        "significance": 0.0 if deflated is None else deflated,
        "risk": rules.drawdown_ratio.score(drawdown_ratio),
        "robustness": 0.5
        * (rules.subperiod_share.score(share) + rules.stress_retention.score(retention)),
        "implementation": rules.cost_drag.score(drag),
    }
    return QualityScore(
        score=_geometric_mean(blocks, rules.weights),
        blocks=blocks,
        measures=measures,
        diagnostics=tuple(dict.fromkeys(diagnostics)),
        version=rules.version,
    )


def _returns(equity: pd.Series) -> np.ndarray:  # type: ignore[type-arg]
    """Return the simple session returns of a curve."""
    values = equity.to_numpy(dtype="float64")
    return values[1:] / values[:-1] - 1.0


def _geometric_mean(blocks: Mapping[str, float], weights: Mapping[str, float]) -> float:
    """Return ``prod(block ** weight)``: zero as soon as a weighted block is zero."""
    if any(blocks[name] <= 0.0 and weights[name] > 0.0 for name in BLOCKS):
        return 0.0
    return math.exp(math.fsum(weights[name] * math.log(blocks[name]) for name in BLOCKS))


def _drawdown_ratio(book: pd.Series, market: pd.Series) -> float:  # type: ignore[type-arg]
    """Return the book's maximum drawdown over the market's, both as depths."""
    own, other = abs(max_drawdown(book).depth), abs(max_drawdown(market).depth)
    if other == 0.0:
        return 0.0 if own == 0.0 else math.inf
    return own / other


def _subperiod_share(book: pd.Series, market: pd.Series, subperiods: int) -> float:  # type: ignore[type-arg]
    """Return the share of consecutive sub-periods the book ended ahead of the market in."""
    pairs = zip(
        np.array_split(_returns(book), subperiods),
        np.array_split(_returns(market), subperiods),
        strict=True,
    )
    ahead = [float(np.prod(1.0 + own)) > float(np.prod(1.0 + other)) for own, other in pairs]
    return sum(ahead) / len(ahead)


def _stress_retention(
    net: pd.Series,  # type: ignore[type-arg]
    gross: pd.Series,  # type: ignore[type-arg]
    config: AnalyticsConfig,
) -> float | None:
    """Return the Sharpe ratio with costs paid twice over the net Sharpe ratio."""
    stressed = net - (gross - net)
    observed = session_sharpe(net, config)
    if observed is None or bool((stressed <= 0.0).any()):
        return None
    if observed <= 0.0:
        return 0.0
    doubled = session_sharpe(stressed, config)
    return None if doubled is None else doubled / observed


def _cost_drag(net: pd.Series, gross: pd.Series) -> float:  # type: ignore[type-arg]
    """Return the share of the gross gain that the costs took."""
    gross_gain = float(gross.iloc[-1] / gross.iloc[0]) - 1.0
    taken = gross_gain - (float(net.iloc[-1] / net.iloc[0]) - 1.0)
    if taken <= 0.0:
        return 0.0
    return taken / gross_gain if gross_gain > 0.0 else math.inf
