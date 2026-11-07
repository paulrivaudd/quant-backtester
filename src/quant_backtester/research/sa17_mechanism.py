"""SA17's mechanism study: residual momentum among Ken French industries, month by month.

The study the protocol separates from execution (``research/SA17/protocol.md``,
"Mechanism study: frozen design"). It asks whether ranking US industries by
the residual momentum of SA17 selects better than plain 12-1 momentum and than
holding every industry, over a century of monthly returns. The ranking reuses
:func:`~quant_backtester.signals.cross_asset.residual_momentum.residual_fit`,
the function SA17's signal scores with, so both studies use the same score.

Every input is a monthly return in USD, as a fraction, labelled by the first
day of its month: Ken French research portfolios, ``RESTATED`` and not
point-in-time. A month's label says which month a return describes, not when
it was known; the study only guarantees that a formation at the end of month
*t* reads no return after *t*. The books are not tradable, and their costs are
a declared hypothesis rather than a measurement.

The functions here are pure. :func:`replay_monthly_returns` reads archived
bytes it is handed and performs no network I/O; the script that runs the study
reads the files.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from types import MappingProxyType

import pandas as pd

from quant_backtester.analytics.config import RETURN_STD_TOLERANCE
from quant_backtester.data.sources.ken_french import (
    KenFrenchDataset,
    KenFrenchSource,
    MonthlyReturns,
    normalize_monthly_returns,
)
from quant_backtester.signals.cross_asset.residual_momentum import residual_fit


class BookName(Enum):
    """The books the study forms at every month end."""

    RESIDUAL = "RESIDUAL"
    """The candidate: the industries with the highest residual-momentum score."""

    C1_MOMENTUM_12_1 = "C1_MOMENTUM_12_1"
    """As many industries, ranked by their compounded return over the same months."""

    C2_EQUAL_WEIGHT = "C2_EQUAL_WEIGHT"
    """Every eligible industry in equal weight."""


class Verdict(Enum):
    """What one comparison of the candidate concludes, by the frozen rules."""

    SUPPORTED_RETROSPECTIVE = "SUPPORTED_RETROSPECTIVE"
    UNCERTAIN = "UNCERTAIN"
    NOT_SUPPORTED = "NOT_SUPPORTED"


@dataclass(frozen=True, slots=True)
class ScoreWindow:
    """The months a formation reads.

    Attributes
    ----------
    estimation_months : int
        Returns in the regression, ending at the formation month.
    score_months : int
        Residuals scored, and months compounded by the 12-1 control.
    skip_months : int
        Most recent months left out of both.

    Raises
    ------
    ValueError
        If a count is not a positive whole number (``skip_months`` may be
        zero), fewer than two months are scored, or the scored and skipped
        months do not fit in the regression window.
    """

    estimation_months: int
    score_months: int
    skip_months: int

    def __post_init__(self) -> None:
        """Refuse a window that cannot hold its score."""
        for name in ("estimation_months", "score_months", "skip_months"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative whole number, got {value!r}")
        if self.score_months < 2:
            raise ValueError("a score needs at least two months")
        if self.score_months + self.skip_months > self.estimation_months:
            raise ValueError(
                f"{self.estimation_months} months cannot hold {self.score_months} scored "
                f"and {self.skip_months} skipped"
            )


@dataclass(frozen=True, slots=True)
class IndustryPanel:
    """Monthly returns of industries, of the market and of the risk-free rate.

    Attributes
    ----------
    months : tuple[date, ...]
        Consecutive month labels, first day of each month, oldest first.
    industries : tuple[str, ...]
        Industry names in the order of the file's columns: the order that
        breaks a tie.
    returns : Mapping[str, tuple[float | None, ...]]
        Each industry's monthly returns, as fractions; ``None`` where the
        library publishes a missing value.
    market : tuple[float, ...]
        ``Mkt = Mkt-RF + RF``, the market's monthly return.
    risk_free : tuple[float, ...]
        ``RF``, the risk-free rate over each month.

    Raises
    ------
    ValueError
        If the months are not consecutive first days, a series has another
        length, an industry is missing or repeated, or a market or risk-free
        value is missing or not finite.
    """

    months: tuple[date, ...]
    industries: tuple[str, ...]
    returns: Mapping[str, tuple[float | None, ...]]
    market: tuple[float, ...]
    risk_free: tuple[float, ...]

    def __post_init__(self) -> None:
        """Refuse a panel whose months or series do not line up."""
        if not self.months:
            raise ValueError("a panel holds at least one month")
        for before, after in zip(self.months, self.months[1:], strict=False):
            if (
                after.day != 1
                or after.year * 12 + after.month != before.year * 12 + before.month + 1
            ):
                raise ValueError(f"months must be consecutive first days: {before} then {after}")
        if self.months[0].day != 1:
            raise ValueError(f"months are labelled by their first day, got {self.months[0]}")
        if len(set(self.industries)) != len(self.industries) or set(self.industries) != set(
            self.returns
        ):
            raise ValueError("the industries and their return series must match one to one")
        count = len(self.months)
        for name, series in (("market", self.market), ("risk_free", self.risk_free)):
            if len(series) != count:
                raise ValueError(f"{name} holds {len(series)} months, the panel {count}")
            if any(value is None or not math.isfinite(value) for value in series):
                raise ValueError(f"{name} must be present and finite in every month")
        for name in self.industries:
            if len(self.returns[name]) != count:
                raise ValueError(
                    f"{name} holds {len(self.returns[name])} months, the panel {count}"
                )
        object.__setattr__(self, "returns", MappingProxyType(dict(self.returns)))

    def position(self, month: date) -> int:
        """Return the index of ``month`` in the panel.

        Raises
        ------
        ValueError
            If the panel does not hold that month.
        """
        try:
            return self.months.index(month)
        except ValueError:
            raise ValueError(f"the panel does not hold {month}") from None


@dataclass(frozen=True, slots=True)
class Formation:
    """What the books hold over the month after ``month``.

    Attributes
    ----------
    month : date
        The formation month: the books are formed at its end, from returns up
        to and including it.
    eligible : tuple[str, ...]
        Industries with every month of the window present and a residual fit,
        in file order.
    refused_fits : tuple[str, ...]
        Industries with a full window whose fit ``residual_fit`` refused.
    residual_scores, momentum : Mapping[str, float]
        Each eligible industry's residual-momentum score, and its compounded
        return over the scored months.
    targets : Mapping[BookName, Mapping[str, float]]
        Each book's weights; what they leave is held at the risk-free rate.
        An empty mapping is a book wholly at the risk-free rate.
    """

    month: date
    eligible: tuple[str, ...]
    refused_fits: tuple[str, ...]
    residual_scores: Mapping[str, float]
    momentum: Mapping[str, float]
    targets: Mapping[BookName, Mapping[str, float]]


@dataclass(frozen=True, slots=True)
class BookMonth:
    """One holding month of one book.

    Attributes
    ----------
    month : date
        The holding month.
    gross, net : float
        The book's return over the month before and after the cost of the
        rebalancing that opened it, as fractions.
    turnover : float
        Traded weight at that rebalancing: the sum over industries of the
        distance between target and drifted weights.
    cost : float
        Fraction of the book's value the rebalancing cost.
    weights : Mapping[str, float]
        The weights held over the month.
    missing_held : tuple[str, ...]
        Held industries without a return this month, which earned the
        risk-free rate instead.
    """

    month: date
    gross: float
    net: float
    turnover: float
    cost: float
    weights: Mapping[str, float]
    missing_held: tuple[str, ...]


def replay_monthly_returns(
    payload: bytes,
    dataset: KenFrenchDataset,
    *,
    sha256: str,
    retrieved_at_utc: datetime,
    start: date,
    end: date,
) -> MonthlyReturns:
    """Parse archived Ken French bytes through the adapter, as if just downloaded.

    Parameters
    ----------
    payload : bytes
        The exact ZIP the library served, read from the archive.
    dataset : KenFrenchDataset
        Which table it is.
    sha256 : str
        The digest the archive recorded for it.
    retrieved_at_utc : datetime
        The recorded retrieval instant, aware UTC: provenance, not the
        availability of any return.
    start, end : date
        Inclusive first-of-month bounds of the months kept.

    Returns
    -------
    MonthlyReturns
        Fractions by month, missing sentinels as ``None``.

    Raises
    ------
    ValueError
        If the bytes are not the ones the archive recorded.
    ProviderResponseError
        If the adapter refuses the file or the range.
    """
    digest = hashlib.sha256(payload).hexdigest()
    if digest != sha256:
        raise ValueError(f"{dataset.value}: archived bytes hash to {digest}, recorded {sha256}")
    source = KenFrenchSource(clock=lambda: retrieved_at_utc, fetch_bytes=lambda _url: payload)
    return normalize_monthly_returns(source.download(dataset, start, end))


def build_panel(industries: MonthlyReturns, factors: MonthlyReturns) -> IndustryPanel:
    """Align an industry table with the market and risk-free rate of the factor table.

    Parameters
    ----------
    industries : MonthlyReturns
        A normalised industry table.
    factors : MonthlyReturns
        The normalised factor table, carrying ``RF`` and ``Mkt``.

    Returns
    -------
    IndustryPanel
        The same months, industries in file order.

    Raises
    ------
    ValueError
        If the two tables cover different months, or the factor table lacks
        ``Mkt`` or ``RF`` or misses one of them in a month.
    """
    if industries.months != factors.months:
        raise ValueError("the industry and factor tables must cover the same months")
    if "Mkt" not in factors.columns or "RF" not in factors.columns:
        raise ValueError("the factor table must carry Mkt and RF")
    market_column = factors.columns.index("Mkt")
    rf_column = factors.columns.index("RF")
    market: list[float] = []
    risk_free: list[float] = []
    for month, row in zip(factors.months, factors.values, strict=True):
        if row[market_column] is None or row[rf_column] is None:
            raise ValueError(f"the factor table misses Mkt or RF in {month}")
        market.append(float(row[market_column]))  # type: ignore[arg-type]
        risk_free.append(float(row[rf_column]))  # type: ignore[arg-type]
    returns = {
        name: tuple(row[column] for row in industries.values)  # noqa: PD011 - a tuple, not pandas
        for column, name in enumerate(industries.columns)
    }
    return IndustryPanel(
        months=industries.months,
        industries=industries.columns,
        returns=returns,
        market=tuple(market),
        risk_free=tuple(risk_free),
    )


def form(panel: IndustryPanel, position: int, window: ScoreWindow, held: int) -> Formation:
    """Form every book at the end of the month at ``position``.

    Parameters
    ----------
    panel : IndustryPanel
        The returns. Only months up to and including ``position`` are read.
    position : int
        Index of the formation month in the panel.
    window : ScoreWindow
        The months the regression and the score read.
    held : int
        Number of industries the candidate and C1 hold.

    Returns
    -------
    Formation
        Eligibility, scores and every book's target weights.

    Raises
    ------
    ValueError
        If the window does not fit before ``position`` or ``held`` is not a
        positive whole number.

    Notes
    -----
    An industry is eligible when its ``estimation_months`` returns ending at
    the formation month are all present and ``residual_fit`` accepts them;
    the same set serves every book, so they differ only by their ranking.
    The candidate and C1 hold their top ``held`` names in equal weight, ties
    going to the earlier column, and hold the risk-free rate when fewer than
    ``held`` are eligible. C2 holds every eligible industry.
    """
    if isinstance(held, bool) or not isinstance(held, int) or held < 1:
        raise ValueError(f"held must be a positive whole number, got {held!r}")
    first = position - window.estimation_months + 1
    if first < 0 or position >= len(panel.months):
        raise ValueError(
            f"a window of {window.estimation_months} months does not fit at position {position}"
        )
    market = list(panel.market[first : position + 1])
    stop = window.estimation_months - window.skip_months
    eligible: list[str] = []
    refused: list[str] = []
    scores: dict[str, float] = {}
    momentum: dict[str, float] = {}
    for name in panel.industries:
        observed = panel.returns[name][first : position + 1]
        if any(value is None for value in observed):
            continue
        values = [float(value) for value in observed]  # type: ignore[arg-type]
        fit = residual_fit(
            values, market, score_months=window.score_months, skip_months=window.skip_months
        )
        if fit is None:
            refused.append(name)
            continue
        growth = 1.0
        for value in values[stop - window.score_months : stop]:
            growth *= 1.0 + value
        eligible.append(name)
        scores[name] = fit.score
        momentum[name] = growth - 1.0
    order = {name: index for index, name in enumerate(panel.industries)}

    def top(ranking: Mapping[str, float]) -> dict[str, float]:
        """Return the top ``held`` names in equal weight, or nothing when too few."""
        if len(eligible) < held:
            return {}
        ranked = sorted(eligible, key=lambda name: (-ranking[name], order[name]))
        return dict.fromkeys(ranked[:held], 1.0 / held)

    every = dict.fromkeys(eligible, 1.0 / len(eligible)) if eligible else {}
    return Formation(
        month=panel.months[position],
        eligible=tuple(eligible),
        refused_fits=tuple(refused),
        residual_scores=MappingProxyType(scores),
        momentum=MappingProxyType(momentum),
        targets=MappingProxyType(
            {
                BookName.RESIDUAL: MappingProxyType(top(scores)),
                BookName.C1_MOMENTUM_12_1: MappingProxyType(top(momentum)),
                BookName.C2_EQUAL_WEIGHT: MappingProxyType(every),
            }
        ),
    )


def _month_return(panel: IndustryPanel, name: str, position: int) -> float | None:
    """Return an industry's return in a month, or ``None`` when it is missing."""
    value = panel.returns[name][position]
    return None if value is None else float(value)


def drift(weights: Mapping[str, float], panel: IndustryPanel, position: int) -> dict[str, float]:
    """Return the weights at the end of a month of a book that held ``weights`` over it.

    Parameters
    ----------
    weights : Mapping[str, float]
        Weights at the start of the month; the rest is at the risk-free rate.
    panel : IndustryPanel
        The returns.
    position : int
        Index of the month the weights were held over.

    Returns
    -------
    dict[str, float]
        Each industry's share of the book's value at the month's end. A held
        industry without a return grew at the risk-free rate, as the book
        assumes it did.
    """
    rate = panel.risk_free[position]
    values: dict[str, float] = {}
    for name, weight in weights.items():
        value = _month_return(panel, name, position)
        values[name] = weight * (1.0 + (rate if value is None else value))
    cash = (1.0 - math.fsum(weights.values())) * (1.0 + rate)
    total = math.fsum(values.values()) + cash
    return {name: value / total for name, value in values.items()}


def holding_formations(
    panel: IndustryPanel,
    window: ScoreWindow,
    held: int,
    first_holding: date,
    last_holding: date,
) -> tuple[Formation, ...]:
    """Form the books at the end of every month before a holding month of the window.

    Parameters
    ----------
    panel : IndustryPanel
        The returns.
    window : ScoreWindow
        The months a formation reads.
    held : int
        Number of industries the candidate and C1 hold.
    first_holding, last_holding : date
        Inclusive first-of-month bounds of the holding months.

    Returns
    -------
    tuple[Formation, ...]
        One formation per holding month, at the end of the month before it.

    Raises
    ------
    ValueError
        If the panel lacks a bound, the bounds are reversed, or the first
        formation has fewer than ``estimation_months`` months behind it.
    """
    start, stop = panel.position(first_holding), panel.position(last_holding)
    if stop < start:
        raise ValueError(f"the holding months run backwards: {first_holding} to {last_holding}")
    return tuple(form(panel, position - 1, window, held) for position in range(start, stop + 1))


def run_book(
    panel: IndustryPanel,
    formations: Sequence[Formation],
    book: BookName,
    cost_rate: float,
) -> tuple[BookMonth, ...]:
    """Hold one book through its formations, paying for every rebalancing.

    Parameters
    ----------
    panel : IndustryPanel
        The returns.
    formations : Sequence[Formation]
        Consecutive formations; each one's book is held over the month after
        it.
    book : BookName
        Which book to hold.
    cost_rate : float
        Cost of one unit of traded weight, one way, as a fraction of the
        traded value. Moves to and from the risk-free rate cost nothing.

    Returns
    -------
    tuple[BookMonth, ...]
        One month per formation. The first formation buys from cash.

    Raises
    ------
    ValueError
        If the cost rate is negative or not finite, or the formations are not
        consecutive months.

    Notes
    -----
    The net return of a month is ``(1 - cost_rate * turnover)(1 + gross) - 1``:
    the cost is paid out of the book at the rebalancing and the rest is
    invested at the target weights.
    """
    if not math.isfinite(cost_rate) or cost_rate < 0.0:
        raise ValueError(f"cost_rate must be a non-negative fraction, got {cost_rate}")
    previous: Mapping[str, float] = {}
    months: list[BookMonth] = []
    for index, formation in enumerate(formations):
        position = panel.position(formation.month)
        if index and formations[index - 1].month != panel.months[position - 1]:
            raise ValueError(f"formations are not consecutive at {formation.month}")
        drifted = drift(previous, panel, position) if previous else {}
        target = formation.targets[book]
        turnover = math.fsum(
            abs(target.get(name, 0.0) - drifted.get(name, 0.0))
            for name in sorted(set(target) | set(drifted))
        )
        holding = position + 1
        rate = panel.risk_free[holding]
        missing: list[str] = []
        parts: list[float] = []
        for name, weight in target.items():
            value = _month_return(panel, name, holding)
            if value is None:
                missing.append(name)
                value = rate
            parts.append(weight * value)
        gross = math.fsum(parts) + (1.0 - math.fsum(target.values())) * rate
        cost = cost_rate * turnover
        months.append(
            BookMonth(
                month=panel.months[holding],
                gross=gross,
                net=(1.0 - cost) * (1.0 + gross) - 1.0,
                turnover=turnover,
                cost=cost,
                weights=target,
                missing_held=tuple(missing),
            )
        )
        previous = target
    return tuple(months)


def market_returns(panel: IndustryPanel, first_holding: date, last_holding: date) -> list[float]:
    """Return the market's monthly returns over the holding months, held at no cost."""
    start, stop = panel.position(first_holding), panel.position(last_holding)
    return list(panel.market[start : stop + 1])


def excess_returns(
    returns: Sequence[float], panel: IndustryPanel, first_holding: date
) -> list[float]:
    """Return monthly returns less the risk-free rate of the same months."""
    start = panel.position(first_holding)
    return [value - panel.risk_free[start + index] for index, value in enumerate(returns)]


def sharpe_ratio(excess: Sequence[float], periods_per_year: int) -> float | None:
    """Return the annualised Sharpe ratio of excess returns, or ``None`` if they do not vary.

    Mean over sample standard deviation (``ddof=1``), times the square root of
    the periods in a year: the statistic
    :func:`~quant_backtester.analytics.uncertainty.paired_stationary_bootstrap`
    resamples on an excess-return curve with a zero risk-free rate.
    """
    count = len(excess)
    if count < 2:
        return None
    mean = math.fsum(excess) / count
    deviation = math.sqrt(math.fsum((value - mean) ** 2 for value in excess) / (count - 1))
    if deviation <= RETURN_STD_TOLERANCE:
        return None
    return mean / deviation * math.sqrt(periods_per_year)


def compound_annual_growth(returns: Sequence[float], periods_per_year: int) -> float:
    """Return the annualised compounded growth of monthly returns, as a fraction."""
    growth = 1.0
    for value in returns:
        growth *= 1.0 + value
    return growth ** (periods_per_year / len(returns)) - 1.0


def max_drawdown(returns: Sequence[float]) -> float:
    """Return the deepest fall from a peak of the compounded returns, as a negative fraction."""
    value, peak, deepest = 1.0, 1.0, 0.0
    for change in returns:
        value *= 1.0 + change
        peak = max(peak, value)
        deepest = min(deepest, value / peak - 1.0)
    return deepest


def active_statistics(
    candidate: Sequence[float], control: Sequence[float], periods_per_year: int
) -> dict[str, float | None]:
    """Return the annualised active mean, tracking error and information ratio.

    Parameters
    ----------
    candidate, control : Sequence[float]
        Monthly returns over the same months.
    periods_per_year : int
        Months in a year.

    Returns
    -------
    dict[str, float | None]
        ``active_mean`` (mean difference times the periods), ``tracking_error``
        (sample deviation of the difference times their square root) and
        ``information_ratio`` (their ratio; ``None`` without a spread).
    """
    if len(candidate) != len(control):
        raise ValueError("the candidate and its control must cover the same months")
    differences = [a - b for a, b in zip(candidate, control, strict=True)]
    count = len(differences)
    mean = math.fsum(differences) / count
    deviation = math.sqrt(math.fsum((value - mean) ** 2 for value in differences) / (count - 1))
    tracking = deviation * math.sqrt(periods_per_year)
    return {
        "active_mean": mean * periods_per_year,
        "tracking_error": tracking,
        "information_ratio": None
        if deviation <= RETURN_STD_TOLERANCE
        else mean * periods_per_year / tracking,
    }


def excess_curve(excess: Sequence[float]) -> pd.Series:  # type: ignore[type-arg]
    """Return a curve compounding excess returns from 1, for the paired bootstrap.

    Its per-period returns are ``excess`` exactly (up to rounding), so a
    bootstrap run on it with a zero risk-free rate resamples the Sharpe ratio
    of excess returns that :func:`sharpe_ratio` reports.
    """
    values = [1.0]
    for value in excess:
        values.append(values[-1] * (1.0 + value))
    return pd.Series(values, index=pd.RangeIndex(len(values)))


def verdict(difference: float, holm_p: float, stressed_difference: float, alpha: float) -> Verdict:
    """Apply the frozen verdict rule to one comparison.

    Parameters
    ----------
    difference : float
        The candidate's Sharpe ratio less the control's, at declared costs.
    holm_p : float
        Holm-adjusted p-value of that difference within its family.
    stressed_difference : float
        The same difference with every cost doubled, in a second real run.
    alpha : float
        The family-wise level.

    Returns
    -------
    Verdict
        ``NOT_SUPPORTED`` at or below zero; ``SUPPORTED_RETROSPECTIVE`` when
        positive, significant after Holm and still positive at doubled costs;
        ``UNCERTAIN`` otherwise.
    """
    if difference <= 0.0:
        return Verdict.NOT_SUPPORTED
    if holm_p < alpha and stressed_difference > 0.0:
        return Verdict.SUPPORTED_RETROSPECTIVE
    return Verdict.UNCERTAIN
