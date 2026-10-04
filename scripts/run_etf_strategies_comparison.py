"""Run the ETF strategies on the store, on the same dates and costs, and compare them.

Every book is run by the same engine over the same period: the benchmark
(``SA1``), ``SA2`` to ``SA6`` and ``SA9``, the ensemble (``SA10``) without its
style funds and money-market fund - neither is registered yet, so ``SA7`` and
``SA8`` are not run and the ensemble's factor budget stays in cash - and two
references, ``ETF_WORLD`` bought and held and an even split of the two funds
rebalanced. A strategy is named by its catalogue code and label
(:mod:`quant_backtester.strategies.catalogue`). From the repository root, once the store is filled:

    uv run python scripts/run_etf_strategies_comparison.py --output results/etf_strategies

Each book also gets a quality score between 0 and 100%
(:mod:`quant_backtester.analytics.quality`, version 1): how well it beat
``ETF_WORLD`` bought and held, and how far that can be trusted.

What is written: ``summary.csv``, the net equity of every book in
``equity.csv``, every fill in ``fills.csv``, four figures of comparison - every
book against the benchmark and the fund held, the same as a ratio to the
benchmark, the drawdowns, and one overview - and one figure per book,
``orders_<book>.png``, with its orders on the prices they were filled at.

The period starts once the longest window (253 closes of ``ETF_WORLD``) is
full. Parameters are those of the specification and none was fitted here. The
last third of the period is marked on every figure and reported apart; it is
not an untouched sample, since the two funds' history was already looked at in
earlier exercises.

Costs are an opening assumption (5 bp commission with a 1 EUR floor, 3 bp of
half-spread, 2 bp of slippage), quantities are fixed at the decision, cash
earns nothing and the risk-free rate of the ratios is zero.

The tests are in ``tests/scripts/test_run_etf_strategies_comparison.py``.
"""

from __future__ import annotations

import argparse
import math
import statistics
import sys
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path

import pandas as pd
from matplotlib.axes import Axes
from matplotlib.dates import date2num
from matplotlib.figure import Figure

from quant_backtester.analytics.benchmark_comparison import alpha_vs_benchmark
from quant_backtester.analytics.config import AnalyticsConfig
from quant_backtester.analytics.curves import Book, drawdown_curve
from quant_backtester.analytics.quality import QUALITY_V1, quality_score, session_sharpe
from quant_backtester.backtest.runner import StrategyResult, StrategyRunner
from quant_backtester.backtest.schedule import EverySession
from quant_backtester.data.calendars import CalendarRegistry
from quant_backtester.data.instruments import InstrumentRegistry
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.data.repository import MarketDataRepository
from quant_backtester.data.schemas import BarField
from quant_backtester.execution.costs import CostModel
from quant_backtester.execution.model import ExecutionModel, Sizing
from quant_backtester.provenance import git_source_state
from quant_backtester.strategies import (
    BufferedDualMomentum,
    BuyAndHold,
    EqualWeightRebalance,
    ETFEnsemble,
    RealizedVolControl,
    RelativeResidualTilt,
    SmoothMovingAverage,
    TrendFilteredPullback,
    VixReliefEntry,
    WorldMA20Benchmark,
)
from quant_backtester.strategies.base import Strategy
from quant_backtester.strategies.catalogue import entry, entry_of

REPOSITORY = Path(__file__).resolve().parents[1]
STORE = REPOSITORY / "market_data"

UNIVERSE = ("ETF_WORLD", "ETF_SP500_PEA")
"""What every book may hold."""

PERIOD = ("2019-05-02", "2026-09-30")
"""Measured period, bounds included: 253 closes of ``ETF_WORLD`` sit before it."""

INITIAL_CASH = 100_000.0

EXECUTION = ExecutionModel(
    costs=CostModel(
        commission_rate=0.0005,
        minimum_commission=1.0,
        half_spread_rate=0.0003,
        slippage_rate=0.0002,
    ),
    sizing=Sizing.AT_DECISION,
)
"""The opening cost assumption of the specification; quantities fixed at the decision."""

ANALYTICS = AnalyticsConfig(sessions_per_year=252, risk_free_rate=0.0, minimum_sessions=60)
"""252 sessions a year and cash earning nothing: a Sharpe against unpaid cash."""

BENCHMARK, HELD, SPLIT = entry("SA1").display_name, "buy & hold World", "50/50 rebalanced"
"""The yardstick and the two references, as they are named in every output."""

HOLDOUT_SHARE = 1.0 / 3.0
"""Share of the sessions, at the end, reported apart."""

FIGURE_DPI = 160
SURFACE, INK, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
STRATEGY_COLOUR, BENCHMARK_COLOUR, HELD_COLOUR = "#2a78d6", "#eb6834", "#8a8983"
"""The book of a panel, the benchmark, and the fund held: the same in every figure."""

FUND_COLOURS = {"ETF_WORLD": "#2a78d6", "ETF_SP500_PEA": "#eb6834"}
"""The two funds, in the figures of orders: the same colour for a fund's price and weight."""

BUY_COLOUR, SELL_COLOUR = "#2f855a", "#c53030"
"""A buy is a green cross and a sell a red one, as in the exercises."""

ENSEMBLE = entry("SA10").display_name


def books() -> dict[str, Strategy]:
    """Return every book of the comparison, by display name, parameters of the specification.

    A catalogued strategy is named ``"<code> - <label>"`` from its catalogue
    entry; the two references keep a plain name.
    """
    catalogued: tuple[Strategy, ...] = (
        BufferedDualMomentum(),
        SmoothMovingAverage(),
        TrendFilteredPullback(),
        RelativeResidualTilt(),
        RealizedVolControl(),
        VixReliefEntry(),
        ETFEnsemble(enable_factors=False, enable_monetary=False),
    )
    return {
        BENCHMARK: WorldMA20Benchmark(),
        HELD: BuyAndHold(instruments=("ETF_WORLD",)),
        SPLIT: EqualWeightRebalance(instruments=UNIVERSE),
        **{entry_of(strategy).display_name: strategy for strategy in catalogued},
    }


def build_runner(root: Path) -> StrategyRunner:
    """Return the runner every book shares: XPAR, EUR, the costs and analytics above."""
    instruments = InstrumentRegistry.from_toml(root / "metadata" / "instruments.toml")
    calendars = CalendarRegistry.from_directory(root / "metadata" / "calendars")
    reader = MarketDataReader(
        repository=MarketDataRepository(root),
        instruments=instruments,
        calendars=calendars,
        reference_calendar_id="XPAR",
    )
    return StrategyRunner(
        reader=reader,
        calendars=calendars,
        reference_calendar_id="XPAR",
        base_currency="EUR",
        analytics=ANALYTICS,
        execution=EXECUTION,
        initial_cash=INITIAL_CASH,
        schedule=EverySession(),
        source=git_source_state(REPOSITORY),
        lockfile=REPOSITORY / "uv.lock",
    )


def indexed(curve: pd.Series, base: float = 100.0) -> pd.Series:  # type: ignore[type-arg]
    """Return a curve rescaled so that its first session is worth ``base``."""
    return curve / float(curve.iloc[0]) * base


def sessions_of(curve: pd.Series) -> list[date]:  # type: ignore[type-arg]
    """Return the session dates a curve is indexed by, oldest first."""
    return [day for day in curve.index if isinstance(day, date)]


def holdout_start(sessions: Sequence[date]) -> date:
    """Return the first session of the last third of a run."""
    return sessions[len(sessions) - max(1, round(len(sessions) * HOLDOUT_SHARE))]


def total_return(curve: pd.Series) -> float:  # type: ignore[type-arg]
    """Return the last value of a curve over its first, less one."""
    return float(curve.iloc[-1] / curve.iloc[0]) - 1.0


def summary_row(
    result: StrategyResult,
    benchmark: pd.Series,  # type: ignore[type-arg]
) -> dict[str, float | None]:
    """Return one book's figures, net of costs, and its relation to the benchmark.

    Parameters
    ----------
    result : StrategyResult
        The finished run of the book.
    benchmark : pd.Series
        Net equity of the benchmark's run over the same sessions.

    Returns
    -------
    dict[str, float | None]
        Returns, risk, exposure, trading, the beta and annualised alpha
        against the benchmark, the plain outperformance, and the net return
        before and inside the last third. ``None`` where the sample does not
        support a figure.
    """
    net = result.report().net
    equity = result.equity()
    split = holdout_start(sessions_of(equity))
    relative = alpha_vs_benchmark(equity, benchmark, ANALYTICS)
    return {
        "net_return": net.total_return,
        "gross_return": result.report().gross.total_return,
        "annualised_return": net.annualised_return,
        "volatility": net.annualised_volatility,
        "sharpe": net.sharpe_ratio,
        "max_drawdown": net.drawdown.depth,
        "average_exposure": float(result.weights().sum(axis=1).mean()),
        "fills": float(len(result.fills())),
        "costs_eur": result.backtest.total_cost,
        "beta_vs_benchmark": relative.beta,
        "alpha_vs_benchmark": relative.alpha_annualised,
        "outperformance": relative.outperformance,
        "net_return_first_two_thirds": total_return(equity.loc[:split]),
        "net_return_last_third": total_return(equity.loc[split:]),
    }


def quality_scores(
    net: Mapping[str, pd.Series],  # type: ignore[type-arg]
    gross: Mapping[str, pd.Series],  # type: ignore[type-arg]
) -> dict[str, float | None]:
    """Return the version 1 quality score of every book but the market fund itself.

    Parameters
    ----------
    net : Mapping[str, pd.Series]
        Net equity of every book, :data:`HELD` among them, on the same sessions.
    gross : Mapping[str, pd.Series]
        Gross equity of the same books.

    Returns
    -------
    dict[str, float | None]
        A score in ``[0, 1]`` per book, measured against :data:`HELD` over the
        whole period - no parameter was fitted on it. The Sharpe ratio is
        deflated by the number of catalogued strategies run here and the
        dispersion of their Sharpe ratios; the two references are not trials.
        ``None`` for the market fund, which is the yardstick, and for a sample
        too short to score.
    """
    tried = [
        sharpe
        for name, curve in net.items()
        if name not in (HELD, SPLIT) and (sharpe := session_sharpe(curve, ANALYTICS)) is not None
    ]
    spread = statistics.stdev(tried) if len(tried) > 1 else 0.0
    scores: dict[str, float | None] = {}
    for name, curve in net.items():
        if name == HELD:
            scores[name] = None
            continue
        scores[name] = quality_score(
            curve,
            gross[name],
            net[HELD],
            ANALYTICS,
            trials=max(1, len(tried)),
            trial_sharpe_std=spread,
            rules=QUALITY_V1,
        ).score
    return scores


def summary_table(rows: Mapping[str, Mapping[str, float | None]]) -> pd.DataFrame:
    """Return the summary as a frame, one book per row, a missing figure as ``NaN``."""
    return pd.DataFrame.from_dict(dict(rows), orient="index", dtype="float64").rename_axis("book")


def render_summary(table: pd.DataFrame) -> str:
    """Return the summary as fixed-width text."""
    columns = (
        ("quality", "score", "{:.0%}"),
        ("net_return", "net", "{:+.1%}"),
        ("annualised_return", "net/yr", "{:+.2%}"),
        ("volatility", "vol", "{:.1%}"),
        ("sharpe", "sharpe", "{:+.2f}"),
        ("max_drawdown", "max dd", "{:.1%}"),
        ("average_exposure", "expo", "{:.0%}"),
        ("fills", "fills", "{:.0f}"),
        ("costs_eur", "costs", "{:,.0f}"),
        ("beta_vs_benchmark", "beta", "{:.2f}"),
        ("alpha_vs_benchmark", "alpha/yr", "{:+.2%}"),
        ("net_return_first_two_thirds", "first 2/3", "{:+.1%}"),
        ("net_return_last_third", "last 1/3", "{:+.1%}"),
    )
    lines = [f"{'book':<22}" + "".join(f"{label:>10}" for _, label, _ in columns)]
    for name, row in table.to_dict(orient="index").items():
        values = [(float(row[key]), pattern) for key, _, pattern in columns]
        cells = ["n/a" if math.isnan(value) else pattern.format(value) for value, pattern in values]
        lines.append(f"{name!s:<22}" + "".join(f"{cell:>10}" for cell in cells))
    return "\n".join(lines)


# --- figures ---------------------------------------------------------------------------


def _style(axes: Axes) -> None:
    """Make the frame of a panel recede behind its curves."""
    axes.set_facecolor(SURFACE)
    axes.grid(axis="y", color=GRID, linewidth=0.8)
    axes.set_axisbelow(True)
    for side in ("top", "right", "left"):
        axes.spines[side].set_visible(False)
    axes.spines["bottom"].set_color(GRID)
    axes.tick_params(colors=MUTED, labelsize=8, length=0)


def _panels(count: int, title: str, note: str) -> tuple[Figure, list[Axes]]:
    """Return a figure of ``count`` panels on shared axes, three or four to a row."""
    columns = 3 if count % 3 == 0 else 4
    rows = math.ceil(count / columns)
    figure = Figure(figsize=(16, 3.6 * rows + 1.1), layout="constrained", facecolor=SURFACE)
    grid = figure.subplots(rows, columns, sharex=True, sharey=True, squeeze=False)
    axes = [panel for row in grid for panel in row]
    for panel in axes[count:]:
        panel.set_visible(False)
    figure.suptitle(title, x=0.01, ha="left", fontsize=14, color=INK, fontweight="bold")
    figure.supxlabel(note, x=0.01, ha="left", fontsize=9, color=MUTED)
    return figure, axes[:count]


def _day(session: date) -> float:
    """Return a session as the number matplotlib places it at on a time axis."""
    return float(date2num(session))


def _mark_holdout(axes: Axes, sessions: Sequence[date]) -> None:
    """Shade the last third of the period, and fit the time axis to the run."""
    first, last = _day(sessions[0]), _day(sessions[-1])
    axes.axvspan(_day(holdout_start(sessions)), last, color=GRID, alpha=0.45, linewidth=0, zorder=0)
    axes.set_xlim(first, last)


def _plot(axes: Axes, curve: pd.Series, colour: str, width: float, label: str) -> None:  # type: ignore[type-arg]
    """Draw one curve against its sessions."""
    axes.plot(list(curve.index), list(curve), color=colour, linewidth=width, label=label)


def equity_panels(curves: Mapping[str, pd.Series]) -> Figure:  # type: ignore[type-arg]
    """Draw each book's net equity beside the benchmark's and the fund held.

    Parameters
    ----------
    curves : Mapping[str, pd.Series]
        Net equity per book, indexed by session, on the same sessions. Must
        hold :data:`BENCHMARK` and :data:`HELD`.

    Returns
    -------
    Figure
        One panel per other book, all on one logarithmic scale, each curve
        rescaled to 100 at the first session, with the final value written at
        the end of the book's own curve.
    """
    names = [name for name in curves if name not in (BENCHMARK, HELD)]
    sessions = sessions_of(curves[BENCHMARK])
    figure, panels = _panels(
        len(names),
        "Net equity of each book, against the benchmark and the fund held",
        "Rebased to 100 at the first session, logarithmic scale. Shaded: last third of the "
        "period. Net of costs; cash earns nothing.",
    )
    for axes, name in zip(panels, names, strict=True):
        _style(axes)
        axes.set_yscale("log")
        _plot(axes, indexed(curves[HELD]), HELD_COLOUR, 1.2, HELD)
        _plot(axes, indexed(curves[BENCHMARK]), BENCHMARK_COLOUR, 1.4, BENCHMARK)
        book = indexed(curves[name])
        _plot(axes, book, STRATEGY_COLOUR, 2.0, "this book")
        axes.annotate(
            f"{book.iloc[-1]:.0f}",
            (book.index[-1], book.iloc[-1]),
            xytext=(4, 0),
            textcoords="offset points",
            fontsize=9,
            color=INK,
            va="center",
        )
        axes.set_title(name, loc="left", fontsize=11, color=INK)
        _mark_holdout(axes, sessions)
    ticks = [75, 100, 150, 200, 250]
    panels[0].set_yticks(ticks, [str(tick) for tick in ticks])
    panels[0].minorticks_off()
    panels[0].legend(loc="upper left", fontsize=8, frameon=False, labelcolor=MUTED)
    return figure


def relative_panels(curves: Mapping[str, pd.Series]) -> Figure:  # type: ignore[type-arg]
    """Draw each book's net equity as a ratio to the benchmark's.

    Returns
    -------
    Figure
        One panel per book other than the benchmark. Above 100 the book is
        ahead of the benchmark since the first session; a rising line is a
        stretch over which it gained on it.
    """
    names = [name for name in curves if name != BENCHMARK]
    sessions = sessions_of(curves[BENCHMARK])
    figure, panels = _panels(
        len(names),
        "Each book relative to the benchmark (SA1)",
        "Net equity of the book over net equity of the benchmark, 100 at the first session. "
        "Shaded: last third of the period.",
    )
    for axes, name in zip(panels, names, strict=True):
        _style(axes)
        ratio = indexed(curves[name]) / indexed(curves[BENCHMARK]) * 100.0
        axes.axhline(100.0, color=MUTED, linewidth=0.8)
        _plot(axes, ratio, STRATEGY_COLOUR, 1.8, name)
        axes.annotate(
            f"{ratio.iloc[-1]:.0f}",
            (ratio.index[-1], ratio.iloc[-1]),
            xytext=(4, 0),
            textcoords="offset points",
            fontsize=9,
            color=INK,
            va="center",
        )
        axes.set_title(name, loc="left", fontsize=11, color=INK)
        _mark_holdout(axes, sessions)
    return figure


def drawdown_panels(curves: Mapping[str, pd.Series]) -> Figure:  # type: ignore[type-arg]
    """Draw each book's drawdown over the benchmark's.

    Returns
    -------
    Figure
        One panel per book other than the benchmark, in percent below the
        running peak of the net equity.
    """
    names = [name for name in curves if name != BENCHMARK]
    sessions = sessions_of(curves[BENCHMARK])
    figure, panels = _panels(
        len(names),
        "Drawdown of each book, over the benchmark's",
        "Percent below the running peak of net equity. Shaded: last third of the period.",
    )
    reference = drawdown_curve(curves[BENCHMARK]) * 100.0
    for axes, name in zip(panels, names, strict=True):
        _style(axes)
        depth = drawdown_curve(curves[name]) * 100.0
        axes.fill_between(list(depth.index), list(depth), 0.0, color=STRATEGY_COLOUR, alpha=0.25)
        _plot(axes, depth, STRATEGY_COLOUR, 1.4, "this book")
        _plot(axes, reference, BENCHMARK_COLOUR, 1.1, BENCHMARK)
        axes.set_title(f"{name}   (worst {depth.min():.0f}%)", loc="left", fontsize=11, color=INK)
        _mark_holdout(axes, sessions)
    panels[0].legend(loc="lower right", fontsize=8, frameon=False, labelcolor=MUTED)
    return figure


def overview_figure(curves: Mapping[str, pd.Series]) -> Figure:  # type: ignore[type-arg]
    """Draw every book's net equity on one scale, three of them in colour.

    Returns
    -------
    Figure
        The benchmark, the fund held and the ensemble are coloured and named
        in the legend; the other books are thin grey lines. Every curve is
        named, with its final value, at its right end.
    """
    figure = Figure(figsize=(13, 7), layout="constrained", facecolor=SURFACE)
    axes = figure.add_subplot()
    _style(axes)
    axes.set_yscale("log")
    highlighted = {BENCHMARK: BENCHMARK_COLOUR, HELD: INK, ENSEMBLE: STRATEGY_COLOUR}
    ends: list[tuple[float, str]] = []
    for name, curve in curves.items():
        book = indexed(curve)
        if name in highlighted:
            _plot(axes, book, highlighted[name], 2.2, name)
        else:
            _plot(axes, book, HELD_COLOUR, 0.9, "_other")
        ends.append((float(book.iloc[-1]), name))
    last = next(iter(curves.values())).index[-1]
    # Labels spread apart on the logarithmic scale so that close finishes stay readable.
    placed = 0.0
    for value, name in sorted(ends):
        position = max(value, placed * 1.035)
        placed = position
        axes.annotate(
            f"{name}  {value:.0f}",
            (last, value),
            xytext=(last, position),
            textcoords="data",
            fontsize=8.5,
            color=INK if name in highlighted else MUTED,
            va="center",
            annotation_clip=False,
            arrowprops={"arrowstyle": "-", "color": GRID, "linewidth": 0.6},
        )
    ticks = [75, 100, 150, 200, 250]
    axes.set_yticks(ticks, [str(tick) for tick in ticks])
    axes.minorticks_off()
    sessions = sessions_of(next(iter(curves.values())))
    _mark_holdout(axes, sessions)
    # Room on the right for the names written at the end of the curves.
    first, end = _day(sessions[0]), _day(sessions[-1])
    axes.set_xlim(first, end + (end - first) * 0.13)
    axes.legend(loc="upper left", fontsize=9, frameon=False, labelcolor=MUTED)
    axes.set_title(
        "Net equity of every book, rebased to 100",
        loc="left",
        fontsize=14,
        color=INK,
        fontweight="bold",
    )
    figure.supxlabel(
        "Logarithmic scale. Grey: the other books, named at their right end. Shaded: last "
        "third of the period. Net of costs; cash earns nothing.",
        x=0.01,
        ha="left",
        fontsize=9,
        color=MUTED,
    )
    return figure


def slug(name: str) -> str:
    """Return a book's name as a file name: lower case, words joined by underscores."""
    kept = "".join(character if character.isalnum() else " " for character in name.lower())
    return "_".join(kept.split())


def orders_figure(
    name: str,
    closes: Mapping[str, pd.Series],  # type: ignore[type-arg]
    fills: pd.DataFrame,
    weights: pd.DataFrame,
    equity: pd.Series,  # type: ignore[type-arg]
    held: pd.Series,  # type: ignore[type-arg]
) -> Figure:
    """Draw one book's orders on the prices they were filled at, and what they did to it.

    Parameters
    ----------
    name : str
        The book.
    closes : Mapping[str, pd.Series]
        Raw close of each fund the book may hold, indexed by session.
    fills : pd.DataFrame
        The executions of the run: ``session_date``, ``instrument_id``,
        ``side``, ``market_price`` and ``traded_value``.
    weights : pd.DataFrame
        Fraction of equity held in each fund at every valuation.
    equity : pd.Series
        Net equity of the book.
    held : pd.Series
        Net equity of the fund bought and held, over the same sessions.

    Returns
    -------
    Figure
        Panels on one time axis. One per fund the book traded: its close with
        a green cross at every buy and a red one at every sell, at the price
        of the open it was filled at; a cross grows with the share of the book
        the order traded. Then the weight held in each fund, the rest being
        cash, and the net equity against the fund held, rebased to 100.
    """
    sessions = sessions_of(equity)
    # One price panel per fund the book traded, each on its own scale: the two
    # funds are quoted an order of magnitude apart.
    traded = [name_ for name_ in closes if (fills["instrument_id"] == name_).any()]
    traded = traded or list(closes)[:1]
    figure = Figure(figsize=(15, 4.2 * len(traded) + 5.6), layout="constrained", facecolor=SURFACE)
    panels = list(
        figure.subplots(
            len(traded) + 2, 1, sharex=True, height_ratios=(*[3.0] * len(traded), 1.2, 1.6)
        )
    )
    price_panels, weight_axes, equity_axes = panels[:-2], panels[-2], panels[-1]
    for axes in panels:
        _style(axes)
    worth = equity.to_dict()
    for price_axes, instrument_id in zip(price_panels, traded, strict=True):
        colour = FUND_COLOURS.get(instrument_id, HELD_COLOUR)
        _plot(price_axes, closes[instrument_id], colour, 1.3, f"{instrument_id} close")
        own = fills.loc[fills["instrument_id"] == instrument_id]
        for side, mark in (("BUY", BUY_COLOUR), ("SELL", SELL_COLOUR)):
            done = own.loc[own["side"] == side]
            share = [
                value / worth.get(day, INITIAL_CASH)
                for day, value in zip(done["session_date"], done["traded_value"], strict=True)
            ]
            price_axes.scatter(
                list(done["session_date"]),
                list(done["market_price"]),
                s=[14.0 + 110.0 * min(1.0, part) for part in share],
                marker="x",
                color=mark,
                linewidths=1.3,
                zorder=3,
                label=f"{side.lower()} ({len(done)})",
            )
        price_axes.set_ylabel("EUR", fontsize=9, color=MUTED)
        price_axes.legend(loc="upper left", fontsize=9, frameon=False, labelcolor=MUTED, ncols=3)
    price_panels[0].set_title(
        f"{name}: {len(fills)} orders filled, on the prices of the funds",
        loc="left",
        fontsize=14,
        color=INK,
        fontweight="bold",
    )

    columns = [column for column in closes if column in weights.columns]
    stacked = [list(weights[column].fillna(0.0) * 100.0) for column in columns]
    weight_axes.stackplot(
        list(weights.index),
        *stacked,
        colors=[FUND_COLOURS.get(column, HELD_COLOUR) for column in columns],
        alpha=0.75,
        linewidth=0,
    )
    weight_axes.set_ylim(0.0, 100.0)
    weight_axes.set_ylabel("% of equity held", fontsize=9, color=MUTED)

    _plot(equity_axes, indexed(held), HELD_COLOUR, 1.2, HELD)
    _plot(equity_axes, indexed(equity), INK, 1.8, name)
    equity_axes.set_ylabel("net equity, 100 at start", fontsize=9, color=MUTED)
    equity_axes.legend(loc="upper left", fontsize=9, frameon=False, labelcolor=MUTED)
    for axes in panels:
        _mark_holdout(axes, sessions)
    figure.supxlabel(
        "A cross is one order, at the open it was filled at; its size grows with the share "
        "of the book traded. Unshaded part of the weights: cash. Shaded: last third.",
        x=0.01,
        ha="left",
        fontsize=9,
        color=MUTED,
    )
    return figure


def closes_of(result: StrategyResult) -> dict[str, pd.Series]:  # type: ignore[type-arg]
    """Return the raw closes of the tradable funds over a run, as the run could read them."""
    reader = result.reader.at(result.records()[-1].valuation_time)
    closes: dict[str, pd.Series] = {}  # type: ignore[type-arg]
    for instrument_id in UNIVERSE:
        series = reader.history(instrument_id, BarField.CLOSE)
        inside = [
            isinstance(day, date) and result.start <= day <= result.end for day in series.index
        ]
        closes[instrument_id] = series.loc[inside]
    return closes


def save_orders(output: Path, results: Mapping[str, StrategyResult]) -> list[Path]:
    """Write every fill of every book, and one figure of orders per book."""
    output.mkdir(parents=True, exist_ok=True)
    frames = [result.fills().assign(book=name) for name, result in results.items()]
    written = [output / "fills.csv"]
    pd.concat(frames, ignore_index=True).to_csv(written[0], index=False)
    held = results[HELD].equity()
    for name, result in results.items():
        figure = orders_figure(
            name, closes_of(result), result.fills(), result.weights(), result.equity(), held
        )
        path = output / f"orders_{slug(name)}.png"
        figure.savefig(path, dpi=FIGURE_DPI, facecolor=SURFACE)
        written.append(path)
    return written


def save_outputs(
    output: Path,
    table: pd.DataFrame,
    curves: Mapping[str, pd.Series],  # type: ignore[type-arg]
) -> list[Path]:
    """Write the summary, the curves and the four figures; return the paths written."""
    output.mkdir(parents=True, exist_ok=True)
    written = [output / "summary.csv", output / "equity.csv"]
    table.to_csv(written[0])
    pd.DataFrame(dict(curves)).rename_axis("session_date").to_csv(written[1])
    figures = {
        "overview.png": overview_figure(curves),
        "equity_panels.png": equity_panels(curves),
        "relative_to_benchmark.png": relative_panels(curves),
        "drawdowns.png": drawdown_panels(curves),
    }
    for name, figure in figures.items():
        figure.savefig(output / name, dpi=FIGURE_DPI, facecolor=SURFACE)
        written.append(output / name)
    return written


def main(arguments: Sequence[str] | None = None) -> int:
    """Run every book, print the comparison and write the outputs."""
    parser = argparse.ArgumentParser(description="Compare the ETF strategies on the store.")
    parser.add_argument("--output", type=Path, default=Path("results/etf_strategies"))
    parser.add_argument("--store", type=Path, default=STORE)
    options = parser.parse_args(arguments)

    runner = build_runner(options.store)
    results: dict[str, StrategyResult] = {}
    for name, strategy in books().items():
        print(f"running {name} ...", file=sys.stderr)
        results[name] = runner.run(strategy, UNIVERSE, *PERIOD)
    curves = {name: result.equity() for name, result in results.items()}
    gross = {name: result.equity(Book.GROSS) for name, result in results.items()}
    scores = quality_scores(curves, gross)
    rows = {
        name: {"quality": scores[name], **summary_row(result, curves[BENCHMARK])}
        for name, result in results.items()
    }
    table = summary_table(rows)

    first, last = curves[BENCHMARK].index[0], curves[BENCHMARK].index[-1]
    split = holdout_start(sessions_of(curves[BENCHMARK]))
    print(f"{first} to {last}, {len(curves[BENCHMARK])} sessions; last third from {split}")
    print(render_summary(table))
    written = save_outputs(options.output, table, curves) + save_orders(options.output, results)
    for path in written:
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
