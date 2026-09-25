"""Measuring a strategy against something else that could have been held.

A return means very little on its own. Sixteen percent over twenty-one months
is good against cash, ordinary against the fund the strategy was picking from,
and bad against the one it kept passing over - and the only way to know which
is to put the two curves side by side.

The benchmark is an analysis tool and never an input: it is built after the
run, from the same period, and nothing in it reaches a decision.

This module holds what a comparison *is* and computes nothing from the market.
Valuing a benchmark needs prices, and prices need a reader, so that step lives
in the runner - the one module allowed to hold both. It reads at each session's
valuation instant, the one the strategy's own book was valued at, so a
comparison sees exactly what the run could have seen, and data arriving after
the run changes none of its figures.

One rule is refused rather than approximated, and the refusal is declared here:
a benchmark quoted in another currency than the book is not comparable with it.
Without an FX conversion, an excess return between a euro book and a dollar
index is the euro-dollar rate with a strategy's name on it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from quant_backtester.analytics.config import AnalyticsConfig
from quant_backtester.analytics.curves import elapsed_years
from quant_backtester.analytics.performance import PerformanceStats
from quant_backtester.signals.types import PriceBasis, require_identifier


class BenchmarkCurrencyMismatch(ValueError):
    """Raised when a benchmark cannot be compared with the book in its own terms.

    A separate type because it is the one comparison mistake that produces a
    plausible number: everything lines up, the curves are drawn, and the
    difference between them is an exchange rate.
    """


@dataclass(frozen=True, slots=True)
class BenchmarkSpec:
    """What to compare a run against.

    Attributes
    ----------
    instrument_id : str
        The instrument to hold instead. It need not be tradable: an index is a
        legitimate yardstick even when nobody can buy it, as long as the report
        does not pretend the comparison is executable.
    price_basis : PriceBasis
        ``TOTAL_RETURN`` counts the distributions the holder would have
        received, which is what makes a fund comparable with a strategy that
        reinvests. ``RAW`` compares the quoted prices alone.
    label : str | None
        What to call it in a report; the instrument's own id by default.
    """

    instrument_id: str
    price_basis: PriceBasis = PriceBasis.TOTAL_RETURN
    label: str | None = None

    def __post_init__(self) -> None:
        """Reject a benchmark nobody could look up."""
        require_identifier(self.instrument_id, "instrument_id")
        if self.label is not None:
            require_identifier(self.label, "label")

    @property
    def name(self) -> str:
        """Return the label a report prints, or the instrument id."""
        return self.label or self.instrument_id

    @classmethod
    def of(cls, benchmark: BenchmarkSpec | str) -> BenchmarkSpec:
        """Return a specification, building one from a bare instrument id."""
        return benchmark if isinstance(benchmark, BenchmarkSpec) else cls(instrument_id=benchmark)

    def definition(self) -> dict[str, object]:
        """Return the benchmark as it is recorded with a run."""
        return {
            "instrument_id": self.instrument_id,
            "price_basis": self.price_basis.value,
            "label": self.label,
        }


@dataclass(frozen=True, slots=True)
class BenchmarkCurve:
    """A benchmark valued over a run's sessions, and how it had to be valued.

    Attributes
    ----------
    spec : BenchmarkSpec
        What was held.
    equity : pd.Series
        Its worth, session by session, starting at the run's own initial value
        so that the two curves are read on one scale.
    marked_from_earlier : tuple[date, ...]
        Sessions valued at a close from before them, because the benchmark's
        own venue was shut while the strategy's was open. Named rather than
        filled in silently: a curve with a flat week in it should say why.
    """

    spec: BenchmarkSpec
    equity: pd.Series  # type: ignore[type-arg]
    marked_from_earlier: tuple[date, ...] = ()


@dataclass(frozen=True, slots=True)
class Comparison:
    """A strategy and something else, measured the same way over the same days.

    Attributes
    ----------
    label : str
        What the other side is called.
    strategy : PerformanceStats
        The run's own statistics, over the common period.
    benchmark : PerformanceStats
        The same statistics for what was held instead.
    sessions : int
        Sessions both curves cover.
    marked_from_earlier : tuple[date, ...]
        Sessions the benchmark had to be valued at an earlier close on.

    Notes
    -----
    Every figure is computed on the same dates for both sides. Comparing a
    strategy's Sharpe ratio over one period with a benchmark's over another is
    how a comparison becomes a sales document.
    """

    label: str
    strategy: PerformanceStats
    benchmark: PerformanceStats
    sessions: int
    marked_from_earlier: tuple[date, ...] = ()

    @property
    def excess_return(self) -> float:
        """Return how much more the strategy made over the whole period."""
        return self.strategy.total_return - self.benchmark.total_return

    def as_frame(self) -> pd.DataFrame:
        """Return the two sides as a frame, one column each."""
        rows = {
            "total_return": (self.strategy.total_return, self.benchmark.total_return),
            "annualised_return": (
                self.strategy.annualised_return,
                self.benchmark.annualised_return,
            ),
            "annualised_volatility": (
                self.strategy.annualised_volatility,
                self.benchmark.annualised_volatility,
            ),
            "max_drawdown": (self.strategy.drawdown.depth, self.benchmark.drawdown.depth),
            "sharpe_ratio": (self.strategy.sharpe_ratio, self.benchmark.sharpe_ratio),
        }
        return pd.DataFrame(
            [{"strategy": pair[0], self.label: pair[1]} for pair in rows.values()],
            index=pd.Index(list(rows), dtype="object", name="statistic"),
        )

    def render(self) -> str:
        """Return the comparison laid out for a terminal.

        Percentages where the figure is one, and a plain number where it is
        not: a Sharpe ratio printed as ``54%`` is the kind of unit slip that
        makes a report unreadable and, read quickly, flattering.
        """
        lines = [
            f"{self.sessions} sessions, strategy against {self.label}",
            "",
            f"{'':<24}{'strategy':>12}{self.label[:12]:>14}",
        ]
        frame = self.as_frame()
        for name in frame.index:
            left, right = frame.loc[name, "strategy"], frame.loc[name, self.label]
            percent = str(name) != "sharpe_ratio"
            label = str(name).replace("_", " ")
            lines.append(f"{label:<24}{_number(left, percent):>12}{_number(right, percent):>14}")
        lines.append(f"{'excess return':<24}{_number(self.excess_return):>12}")
        return "\n".join(lines)


def compare(
    equity: pd.Series,  # type: ignore[type-arg]
    curve: BenchmarkCurve,
    config: AnalyticsConfig,
) -> Comparison:
    """Measure a curve against a benchmark over the days they share.

    Parameters
    ----------
    equity : pd.Series
        The strategy's own worth, session by session.
    curve : BenchmarkCurve
        What was held instead, already valued over the same sessions.
    config : AnalyticsConfig
        The annualisation convention, applied to both sides.

    Returns
    -------
    Comparison
        The same statistics for both, over the same sessions.

    Raises
    ------
    ValueError
        If the two curves share no session.

    Notes
    -----
    Both sides are measured on the intersection of their dates. Comparing a
    strategy's Sharpe ratio over one period with a benchmark's over another is
    how a comparison becomes a sales document.
    """
    common = equity.index.intersection(curve.equity.index)
    if len(common) == 0:
        raise ValueError("the strategy and the benchmark share no session")
    strategy = equity.loc[common]
    other = curve.equity.loc[common]
    return Comparison(
        label=curve.spec.name,
        strategy=PerformanceStats.from_equity(strategy, config),
        benchmark=PerformanceStats.from_equity(other, config),
        sessions=len(common),
        marked_from_earlier=tuple(day for day in curve.marked_from_earlier if day in set(common)),
    )


def common_period(first: pd.Series, second: pd.Series) -> pd.Index:  # type: ignore[type-arg]
    """Return the sessions two curves share, in order.

    Parameters
    ----------
    first, second : pd.Series
        Curves indexed by session date.

    Returns
    -------
    pd.Index
        The intersection. Comparing two runs over different periods without
        saying so is how a strategy that was lucky in one year is presented as
        better than one that was not.
    """
    return first.index.intersection(second.index)


def _number(value: float | None, as_percent: bool = True) -> str:
    """Return a figure as a report prints it, or a dash when there is none."""
    if value is None:
        return "-"
    return f"{value:.2%}" if as_percent else f"{value:.2f}"


__all__ = [
    "BenchmarkCurrencyMismatch",
    "BenchmarkCurve",
    "BenchmarkSpec",
    "Comparison",
    "common_period",
    "compare",
    "elapsed_years",
]
