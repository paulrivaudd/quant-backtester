"""SA16_it2 on a long history: a growth fund and gold at a risk budget, month by month.

The study ``research/SA16/long_history.md`` freezes. SA16_it2 was designed and
read on 2018-08 to 2026-10; this replays its rule on months it never saw,
from 1975, in US dollars, on research series rather than funds:

- growth: the value-weighted "BusEq" portfolio of Ken French's 12 industries
  (computers, software, electronic equipment), a total return of the month;
- gold: the World Bank's monthly **average** price. A change between two
  averages runs from mid-month to mid-month and varies less than a month-end
  change; :func:`budget_weights` is given the declared variance scale that
  undoes it in the volatility estimate, and nothing undoes it in the returns;
- the Nasdaq Composite at each month's last close, **without dividends**;
- the one-month Treasury bill of the French factor file as the risk-free rate.

Every input is ``RESTATED``, labelled by the month it describes. A decision
at the end of month *t* reads the changes of months up to *t* and sets the
weights held over month *t+1*; nothing here reads a later month. The books
are not tradable and their costs are a declared hypothesis.

The functions are pure and perform no I/O; the script hands them parsed data.
"""

from __future__ import annotations

import csv
import io
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum
from itertools import pairwise

from quant_backtester.data.sources.ken_french import MonthlyReturns

GROWTH = "GROWTH"
GOLD = "GOLD"


class Reading(Enum):
    """What the comparison with one reference concludes, by the frozen rule."""

    SUPPORTED_RETROSPECTIVE = "SUPPORTED_RETROSPECTIVE"
    UNCERTAIN = "UNCERTAIN"
    NOT_SUPPORTED = "NOT_SUPPORTED"


@dataclass(frozen=True, slots=True)
class MonthlyPanel:
    """The four monthly series on the months they all cover, in order.

    Attributes
    ----------
    months : tuple[date, ...]
        First day of each month, consecutive.
    growth : tuple[float, ...]
        Total return of the growth portfolio over the month, as a fraction.
    gold : tuple[float, ...]
        Change of gold's monthly average price from the month before.
    nasdaq : tuple[float, ...]
        Change of the Nasdaq Composite between the last closes of the month
        before and of the month; dividends excluded.
    risk_free : tuple[float, ...]
        One-month Treasury bill return of the month.
    """

    months: tuple[date, ...]
    growth: tuple[float, ...]
    gold: tuple[float, ...]
    nasdaq: tuple[float, ...]
    risk_free: tuple[float, ...]

    def __post_init__(self) -> None:
        """Refuse series of unequal length or months that are not consecutive."""
        count = len(self.months)
        if count == 0:
            raise ValueError("the panel has no month")
        for name in ("growth", "gold", "nasdaq", "risk_free"):
            values = getattr(self, name)
            if len(values) != count:
                raise ValueError(f"{name} does not cover the panel's months")
            if any(not math.isfinite(value) for value in values):
                raise ValueError(f"{name} holds a value that is not finite")
        ordinals = [month.year * 12 + month.month for month in self.months]
        if any(month.day != 1 for month in self.months) or any(
            later != earlier + 1 for earlier, later in pairwise(ordinals)
        ):
            raise ValueError("the panel's months must be consecutive first days")

    def position(self, month: date) -> int:
        """Return the index of a month, refusing one the panel does not hold."""
        try:
            return self.months.index(month)
        except ValueError as error:
            raise ValueError(f"{month:%Y-%m} is not a month of the panel") from error

    def returns(self, asset: str) -> tuple[float, ...]:
        """Return the monthly changes of ``GROWTH`` or ``GOLD``."""
        if asset == GROWTH:
            return self.growth
        if asset == GOLD:
            return self.gold
        raise ValueError(f"unknown asset {asset!r}")


@dataclass(frozen=True, slots=True)
class BookMonth:
    """One held month of a book.

    Attributes
    ----------
    month : date
        The month held.
    weights : Mapping[str, float]
        Weights at the start of the month, after any trade.
    traded : bool
        Whether the book was brought back to its target before the month.
    turnover : float
        Sum of the absolute weight changes of that trade (both legs).
    gross : float
        The month's return before costs.
    net : float
        The month's return after the trade's cost.
    """

    month: date
    weights: Mapping[str, float]
    traded: bool
    turnover: float
    gross: float
    net: float


def month_end_changes(text: str, series_id: str) -> dict[date, float]:
    """Return the change between the last values of consecutive months of a FRED series.

    Parameters
    ----------
    text : str
        A FRED ``fredgraph.csv`` body: ``observation_date,<series_id>`` then
        one row per day, a missing value printed as ``.`` or left empty.
    series_id : str
        The series the header must name.

    Returns
    -------
    dict[date, float]
        By month (its first day), the fractional change from the last value
        of the month before to the last value of the month. A month is absent
        when it or the month before has no value.

    Raises
    ------
    ValueError
        If the header is not the series', a date repeats or goes back, or a
        value is not a finite positive number.
    """
    rows = list(csv.reader(io.StringIO(text), strict=True))
    if not rows or rows[0] != ["observation_date", series_id]:
        raise ValueError(f"not a FRED series CSV of {series_id}")
    last: dict[date, float] = {}
    previous: date | None = None
    for row in rows[1:]:
        if not row:
            continue
        if len(row) != 2:
            raise ValueError(f"unexpected row {row!r}")
        day = date.fromisoformat(row[0])
        if previous is not None and day <= previous:
            raise ValueError(f"dates repeat or go back at {day}")
        previous = day
        if row[1] in ("", "."):
            continue
        value = float(row[1])
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError(f"invalid value on {day}")
        last[day.replace(day=1)] = value
    changes: dict[date, float] = {}
    for month, value in last.items():
        before = (month - timedelta(days=1)).replace(day=1)
        if before in last:
            changes[month] = value / last[before] - 1.0
    return changes


def average_changes(months: Sequence[date], values: Sequence[float]) -> dict[date, float]:
    """Return the change of a monthly average from the month before.

    Parameters
    ----------
    months : Sequence[date]
        Consecutive first days of months.
    values : Sequence[float]
        The average of each month, positive.

    Returns
    -------
    dict[date, float]
        By month, ``value / previous value - 1``; the first month has none.
    """
    if len(months) != len(values):
        raise ValueError("as many values as months are needed")
    return {
        month: value / before - 1.0
        for month, value, before in zip(months[1:], values[1:], values, strict=False)
    }


def _column(table: MonthlyReturns, name: str) -> dict[date, float | None]:
    if name not in table.columns:
        raise ValueError(f"the table has no column {name!r}")
    index = table.columns.index(name)
    return {month: row[index] for month, row in zip(table.months, table.values, strict=True)}


def build_panel(
    industries: MonthlyReturns,
    growth_column: str,
    factors: MonthlyReturns,
    gold: Mapping[date, float],
    nasdaq: Mapping[date, float],
    first: date,
    last: date,
) -> MonthlyPanel:
    """Align the four series on every month from ``first`` to ``last``.

    Parameters
    ----------
    industries : MonthlyReturns
        The French industry table holding the growth portfolio.
    growth_column : str
        Its column, ``"BusEq"`` in the 12-industry table.
    factors : MonthlyReturns
        The French factor table; its ``RF`` column is the risk-free rate.
    gold, nasdaq : Mapping[date, float]
        Monthly changes by month, from :func:`average_changes` and
        :func:`month_end_changes`.
    first, last : date
        First days of the first and last months of the panel, inclusive.

    Returns
    -------
    MonthlyPanel
        The four series on those months.

    Raises
    ------
    ValueError
        If a series has no value for a month of the range: a hole is refused,
        never filled.
    """
    growth = _column(industries, growth_column)
    risk_free = _column(factors, "RF")
    months = []
    month = first
    while month <= last:
        months.append(month)
        month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    series: dict[str, list[float]] = {"growth": [], "gold": [], "nasdaq": [], "risk_free": []}
    sources: dict[str, Mapping[date, float | None]] = {
        "growth": growth,
        "gold": gold,
        "nasdaq": nasdaq,
        "risk_free": risk_free,
    }
    for month in months:
        for name, source in sources.items():
            value = source.get(month)
            if value is None:
                raise ValueError(f"{name} has no value for {month:%Y-%m}")
            series[name].append(value)
    return MonthlyPanel(
        tuple(months),
        tuple(series["growth"]),
        tuple(series["gold"]),
        tuple(series["nasdaq"]),
        tuple(series["risk_free"]),
    )


def annualised_volatility(
    changes: Sequence[float], periods_per_year: int, variance_scale: float = 1.0
) -> float:
    """Return the annualised volatility of log changes.

    Parameters
    ----------
    changes : Sequence[float]
        Fractional changes, each above -1; at least two.
    periods_per_year : int
        Changes in a year (12 for months).
    variance_scale : float
        Factor applied to the variance before the square root: 1 for
        month-end changes, the declared correction for changes of averages.

    Returns
    -------
    float
        Sample standard deviation (``ddof=1``) of ``ln(1 + change)``, times
        the square roots of ``variance_scale`` and ``periods_per_year``.
    """
    if len(changes) < 2:
        raise ValueError("a volatility needs at least two changes")
    logs = [math.log1p(value) for value in changes]
    mean = math.fsum(logs) / len(logs)
    variance = math.fsum((value - mean) ** 2 for value in logs) / (len(logs) - 1)
    return math.sqrt(variance * variance_scale * periods_per_year)


def budget_weights(
    growth_volatility: float, gold_volatility: float, growth_budget: float, floor: float
) -> dict[str, float]:
    """Return SA16's risk-budget weights of the two assets.

    ``w_growth ~ b / vol_growth`` and ``w_gold ~ (1 - b) / vol_gold``, scaled
    to add up to one; each volatility is floored first, as in
    :class:`~quant_backtester.strategies.SA16_risk_budget.SA16RiskBudget`.
    """
    if not 0.0 < growth_budget < 1.0:
        raise ValueError("the growth budget lies strictly in (0, 1)")
    growth = growth_budget / max(growth_volatility, floor)
    gold = (1.0 - growth_budget) / max(gold_volatility, floor)
    return {GROWTH: growth / (growth + gold), GOLD: gold / (growth + gold)}


def budget_target(
    panel: MonthlyPanel,
    volatility_months: int,
    growth_budget: float,
    floor: float,
    gold_variance_scale: float,
    periods_per_year: int,
) -> Callable[[int], dict[str, float]]:
    """Return the rule giving the target held over a month from the months before it.

    The returned function takes the position of a holding month and reads the
    ``volatility_months`` changes ending the month before it.
    """

    def target(position: int) -> dict[str, float]:
        if position < volatility_months:
            raise ValueError(
                f"{panel.months[position]:%Y-%m} has fewer than {volatility_months} months "
                "before it"
            )
        window = slice(position - volatility_months, position)
        return budget_weights(
            annualised_volatility(panel.growth[window], periods_per_year),
            annualised_volatility(panel.gold[window], periods_per_year, gold_variance_scale),
            growth_budget,
            floor,
        )

    return target


def fixed_target(weights: Mapping[str, float]) -> Callable[[int], dict[str, float]]:
    """Return the rule of a book held at constant weights."""
    if set(weights) != {GROWTH, GOLD} or abs(sum(weights.values()) - 1.0) > 1e-9:
        raise ValueError("constant weights name both assets and add up to one")
    return lambda _position: dict(weights)


def run_book(
    panel: MonthlyPanel,
    first_holding: date,
    last_holding: date,
    target: Callable[[int], Mapping[str, float]],
    band: float,
    cost_rate: float,
) -> list[BookMonth]:
    """Hold the two assets from ``first_holding`` to ``last_holding``.

    Before each month the rule gives a target. The book starts on its first
    target at no cost, as the references it is compared with are bought at no
    cost. Afterwards the weights drift with the months' changes, and the book
    is brought back to the target, whole, when a weight is further than
    ``band`` from it. That trade costs ``cost_rate`` times the sum of the
    absolute weight changes, taken from the month's return.

    Parameters
    ----------
    panel : MonthlyPanel
        The monthly series.
    first_holding, last_holding : date
        First and last months held, inclusive.
    target : Callable[[int], Mapping[str, float]]
        The target held over the month at a position, from data before it.
    band : float
        Largest gap between a held weight and its target that sends no trade.
    cost_rate : float
        One-way cost, as a fraction of traded value.

    Returns
    -------
    list[BookMonth]
        One record per held month.
    """
    start, stop = panel.position(first_holding), panel.position(last_holding)
    if start > stop:
        raise ValueError("the first holding month is after the last")
    held: dict[str, float] | None = None
    book = []
    for position in range(start, stop + 1):
        wanted = dict(target(position))
        turnover = 0.0
        traded = False
        if held is None:
            held = wanted
        elif max(abs(held[name] - wanted[name]) for name in wanted) > band:
            turnover = math.fsum(abs(held[name] - wanted[name]) for name in wanted)
            held = wanted
            traded = True
        changes = {GROWTH: panel.growth[position], GOLD: panel.gold[position]}
        gross = math.fsum(held[name] * changes[name] for name in held)
        net = (1.0 - cost_rate * turnover) * (1.0 + gross) - 1.0 if traded else gross
        book.append(BookMonth(panel.months[position], dict(held), traded, turnover, gross, net))
        held = {name: held[name] * (1.0 + changes[name]) / (1.0 + gross) for name in held}
    return book


def beats(
    candidate: Mapping[str, float | None],
    reference: Mapping[str, float | None],
    drawdown_tolerance: float,
) -> bool:
    """Return whether the candidate's CAGR and Sharpe are higher and its drawdown no deeper.

    The drawdown may be at most ``drawdown_tolerance`` deeper than the
    reference's.

    Raises
    ------
    ValueError
        If a measure is missing on either side.
    """
    for values in (candidate, reference):
        missing = [key for key in ("cagr", "sharpe", "max_drawdown") if values.get(key) is None]
        if missing:
            raise ValueError(f"the criterion cannot be read: a book has no {missing}")
    return bool(
        candidate["cagr"] > reference["cagr"]  # type: ignore[operator]
        and candidate["sharpe"] > reference["sharpe"]  # type: ignore[operator]
        and candidate["max_drawdown"] >= reference["max_drawdown"] - drawdown_tolerance  # type: ignore[operator]
    )


def reading(beats_declared: bool, beats_stressed: bool, holm_p: float, alpha: float) -> Reading:
    """Apply the frozen rule to the comparison with one reference.

    ``NOT_SUPPORTED`` when the criterion of :func:`beats` fails at declared
    costs; ``SUPPORTED_RETROSPECTIVE`` when it holds at declared and doubled
    costs and the Holm-adjusted p-value of the Sharpe difference is below
    ``alpha``; ``UNCERTAIN`` otherwise.
    """
    if not beats_declared:
        return Reading.NOT_SUPPORTED
    if beats_stressed and holm_p < alpha:
        return Reading.SUPPORTED_RETROSPECTIVE
    return Reading.UNCERTAIN
