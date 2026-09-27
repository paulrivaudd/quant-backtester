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

import math
from dataclasses import dataclass
from datetime import date
from enum import Enum

import pandas as pd

from quant_backtester.analytics.config import AnalyticsConfig
from quant_backtester.analytics.curves import Book, aligned_equity_curves, elapsed_years
from quant_backtester.analytics.performance import PerformanceStats
from quant_backtester.analytics.relative import STATISTICS, RelativePerformanceStats
from quant_backtester.signals.types import require_identifier


class BenchmarkCurrencyMismatch(ValueError):
    """Raised when a benchmark cannot be compared with the book in its own terms.

    A separate type because it is the one comparison mistake that produces a
    plausible number: everything lines up, the curves are drawn, and the
    difference between them is an exchange rate.
    """


class BenchmarkBasis(Enum):
    """What holding the benchmark is taken to have earned.

    Both are a wealth index: one share held, its worth chained session by
    session from raw closes and the corporate actions known at each valuation
    instant. They differ only in what a distribution does.
    """

    PRICE_RETURN = "PRICE_RETURN"
    """A split multiplies the shares held; a distribution is not counted. What
    an index's price level measures."""

    TOTAL_RETURN = "TOTAL_RETURN"
    """As ``PRICE_RETURN``, and a dividend is received at its ex-date and
    reinvested at that session's close: a session earns
    ``(shares x close + dividends) / previous close``. What a holder who
    reinvests earns, and what a strategy that reinvests is fairly measured
    against."""


@dataclass(frozen=True, slots=True)
class BenchmarkSpec:
    """What to compare a run against.

    Attributes
    ----------
    instrument_id : str
        The instrument to hold instead. It need not be tradable: an index is a
        legitimate yardstick even when nobody can buy it, as long as the report
        does not pretend the comparison is executable.
    basis : BenchmarkBasis
        ``TOTAL_RETURN`` counts the distributions the holder would have
        received and reinvested, which is what makes a fund comparable with a
        strategy that reinvests; ``PRICE_RETURN`` leaves them out. Neither
        is the adjusted series a signal reads: gluing the last point of each
        day's adjusted history together is not a wealth (audit A01).
    label : str | None
        What to call it in a report; the instrument's own id by default.
    """

    instrument_id: str
    basis: BenchmarkBasis = BenchmarkBasis.TOTAL_RETURN
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
            "basis": self.basis.value,
            "label": self.label,
        }


@dataclass(frozen=True, slots=True, init=False)
class BenchmarkCurve:
    """A benchmark valued over a run's sessions, and how it had to be valued.

    Parameters
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

    Notes
    -----
    The values are kept as a tuple and :attr:`equity` builds a new series on
    every read. A frozen dataclass holding a ``pd.Series`` froze the attribute
    and not the series: ``curve.equity.iloc[-1] = 99999`` rewrote the
    benchmark a finished run keeps, and every later comparison with it
    (audit R06).
    """

    spec: BenchmarkSpec
    values: tuple[float, ...]
    sessions: tuple[date, ...]
    marked_from_earlier: tuple[date, ...]

    def __init__(
        self,
        spec: BenchmarkSpec,
        equity: pd.Series,  # type: ignore[type-arg]
        marked_from_earlier: tuple[date, ...] = (),
    ) -> None:
        object.__setattr__(self, "spec", spec)
        object.__setattr__(self, "values", tuple(float(value) for value in equity))
        object.__setattr__(self, "sessions", tuple(equity.index))
        object.__setattr__(self, "marked_from_earlier", tuple(marked_from_earlier))

    @property
    def equity(self) -> pd.Series:  # type: ignore[type-arg]
        """Return the curve as a series of its own, indexed by session date."""
        return pd.Series(
            list(self.values),
            index=pd.Index(list(self.sessions), dtype="object", name="session_date"),
            name=self.spec.name,
            dtype="float64",
        )


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
        Sessions the benchmark had to be valued at an earlier close on. Kept
        in the sample - dropping them would move the return intervals - and
        counted in the rendering: the benchmark may react a session late.
    relative : RelativePerformanceStats | None
        Alpha, beta, tracking error and information ratio over the same
        sessions. Always set by :func:`compare`; ``None`` only on a comparison
        built by hand, and then rendered as not computed.
    benchmark_spec : BenchmarkSpec | None
        What the benchmark was, basis included.
    book : Book | None
        Which of the run's books the strategy side is. A label of provenance:
        it does not turn a gross curve into a net one.

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
    relative: RelativePerformanceStats | None = None
    benchmark_spec: BenchmarkSpec | None = None
    book: Book | None = None

    def __post_init__(self) -> None:
        """Refuse a book that is not a :class:`Book`."""
        if self.book is not None and not isinstance(self.book, Book):
            raise ValueError(f"book must be a Book or None, got {self.book!r}")

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

    def relative_frame(self) -> pd.DataFrame:
        """Return the seven relative figures as a one-column frame.

        Returns
        -------
        pd.DataFrame
            :meth:`RelativePerformanceStats.as_frame`, or the same rows with
            no value on a comparison built without them.
        """
        if self.relative is not None:
            return self.relative.as_frame()
        return pd.DataFrame(
            {"value": [None] * len(STATISTICS)},
            index=pd.Index(list(STATISTICS), dtype="object", name="statistic"),
            dtype="float64",
        )

    def render(self) -> str:
        """Return the comparison laid out for a terminal.

        Percentages where the figure is one, and a plain number where it is
        not: a Sharpe ratio printed as ``54%`` is the kind of unit slip that
        makes a report unreadable and, read quickly, flattering. Beta and the
        information ratio are numbers too.
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
        lines.extend(("", *self._relative_block()))
        lines.extend(
            (
                "",
                f"{self.label} is a yardstick, not an alternative that was traded: one share",
                "held from the first close, with no cost, no lot and no cash left over. The",
                "strategy starts in cash and trades at the next open on its own schedule.",
            )
        )
        return "\n".join(lines)

    def _relative_block(self) -> list[str]:
        """Return the lines of the relative figures, or why there are none."""
        if self.relative is None:
            return ["relative figures not computed"]
        relative = self.relative
        book = self.book.value.lower() if self.book is not None else "unlabelled"
        lines = [
            *relative_context(relative, self.label, self.benchmark_spec),
            f"{'book':<28}{book:>12}",
        ]
        lines.extend(
            f"{relative_label(name):<28}{relative_value(name, getattr(relative, name)):>12}"
            for name in RENDERED_STATISTICS
        )
        lines.extend(relative_notes(relative.diagnostics, len(self.marked_from_earlier)))
        return lines


def compare(
    equity: pd.Series,  # type: ignore[type-arg]
    curve: BenchmarkCurve,
    config: AnalyticsConfig,
    *,
    book: Book | None = None,
) -> Comparison:
    """Measure a curve against a benchmark over one period with no hole in it.

    Parameters
    ----------
    equity : pd.Series
        The strategy's own worth, session by session, in the benchmark's
        currency.
    curve : BenchmarkCurve
        What was held instead, already valued over the same sessions.
    config : AnalyticsConfig
        The annualisation convention, applied to both sides.
    book : Book | None
        Which book ``equity`` is, recorded with the comparison. The caller
        passes the matching curve: this labels it and converts nothing.

    Returns
    -------
    Comparison
        The same absolute statistics for both sides and the relative ones,
        all over the same sessions.

    Raises
    ------
    ValueError
        If the curves are invalid, share no session, or one lacks a session
        the other holds inside their shared span (see
        :func:`~quant_backtester.analytics.curves.aligned_equity_curves`), or
        if ``book`` is not a :class:`Book`.

    Notes
    -----
    The period runs from the first to the last session both curves hold, and
    inside it both must hold every session: an intersection would bridge a
    missing Tuesday with a Monday-to-Wednesday return counted as one session.
    """
    if book is not None and not isinstance(book, Book):
        raise ValueError(f"book must be a Book or None, got {book!r}")
    strategy, other = aligned_equity_curves(equity, curve.equity)
    kept = set(strategy.index)
    return Comparison(
        label=curve.spec.name,
        strategy=PerformanceStats.from_equity(strategy, config),
        benchmark=PerformanceStats.from_equity(other, config),
        sessions=len(strategy),
        marked_from_earlier=tuple(day for day in curve.marked_from_earlier if day in kept),
        relative=RelativePerformanceStats.from_equity(strategy, other, config),
        benchmark_spec=curve.spec,
        book=book,
    )


RENDERED_STATISTICS: tuple[str, ...] = tuple(
    name for name in STATISTICS if name != "alpha_per_session"
)
"""The relative figures a report prints; the alpha per session stays in the frames."""

_RELATIVE_LABELS: dict[str, str] = {
    "alpha_per_session": "alpha per session",
    "alpha_annualised": "regression alpha, a year",
    "beta": "beta",
    "active_return_annualised": "active return, a year",
    "tracking_error_annualised": "tracking error, a year",
    "information_ratio": "information ratio",
    "r_squared": "r squared",
}

_DIAGNOSTIC_NOTES: dict[str, str] = {
    "insufficient_observations": "too few sessions for the declared minimum: nothing is estimated",
    "zero_benchmark_variance": "the benchmark's returns do not vary: no alpha, beta or r squared",
    "zero_strategy_variance": "the strategy's returns do not vary: no r squared",
    "zero_tracking_error": "the active return does not vary: no information ratio",
}


def relative_label(name: str) -> str:
    """Return how a report labels one relative figure."""
    return _RELATIVE_LABELS[name]


def relative_value(name: str, value: float | None) -> str:
    """Return one relative figure as a report prints it.

    Alpha, active return, tracking error and alpha per session are fractions
    a year (or a session) and print as percentages; r squared prints as a
    percentage to one decimal; beta and the information ratio are plain
    numbers to three decimals. A missing figure is a dash.
    """
    if value is None or not math.isfinite(value):
        return "-"
    if name == "alpha_per_session":
        return f"{value:.4%}"
    if name == "r_squared":
        return f"{value:.1%}"
    if name in ("beta", "information_ratio"):
        return f"{value:.3f}"
    return f"{value:.2%}"


def relative_context(
    relative: RelativePerformanceStats, label: str, spec: BenchmarkSpec | None
) -> list[str]:
    """Return the lines that say what the relative figures are measured on."""
    basis = spec.basis.value if spec is not None else "basis not recorded"
    config = relative.config
    lines = [
        f"relative to {label} ({basis}), {relative.sample_start} to {relative.sample_end}",
        f"  {relative.sessions} valuations, {relative.observations} returns, "
        f"{config.sessions_per_year} sessions/year, risk-free {config.risk_free_rate:.2%}",
    ]
    if spec is not None and spec.basis is BenchmarkBasis.PRICE_RETURN:
        lines.append("  price return: the benchmark's distributions are left out")
    return lines


def relative_notes(diagnostics: tuple[str, ...], marked_from_earlier: int) -> list[str]:
    """Return the caveats of the relative figures, one line each."""
    lines = [f"  unavailable: {_DIAGNOSTIC_NOTES.get(code, code)}" for code in diagnostics]
    if marked_from_earlier:
        lines.append(
            f"  {marked_from_earlier} benchmark valuation(s) on an earlier close: "
            "it may react a session late"
        )
    lines.append(
        "  alpha is A x the intercept, not a compounded return; the ratios scale by sqrt(A)"
    )
    return lines


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
    """Return a figure as a report prints it, or a dash when there is none.

    A frame stores a missing figure as ``NaN``; it is printed as the absence it
    is, never as ``nan``.
    """
    if value is None or not math.isfinite(value):
        return "-"
    return f"{value:.2%}" if as_percent else f"{value:.2f}"


__all__ = [
    "RENDERED_STATISTICS",
    "BenchmarkBasis",
    "BenchmarkCurrencyMismatch",
    "BenchmarkCurve",
    "BenchmarkSpec",
    "Comparison",
    "common_period",
    "compare",
    "elapsed_years",
]
