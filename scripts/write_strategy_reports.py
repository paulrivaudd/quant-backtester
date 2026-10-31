"""Write the results folder: one folder per strategy, and one that compares them.

Each catalogued strategy a study ran gets ``results/<CODE>/``:

- ``analysis.md``: every global indicator beside the fund bought and held;
  the measured facts of its worst and best stretches, its drawdowns with the
  date each peak was reached again, its years and months, then the strengths,
  the weaknesses and the market situations that hurt it most; and its history,
  session by session;
- ``metrics.csv``, ``yearly.csv``, ``history.csv`` and ``fills.csv``: the same
  figures as tables - at the declared costs and at twice them, by calendar
  year, by session, and order by order;
- ``equity.png``, ``drawdown.png``, ``weights.png`` and ``orders.png``: its
  value against the fund held, how far it stood below its own peak, what it
  held, and its orders on the prices of the funds.

The control of ``SA11`` and the two references - the fund held and the even
split - have no catalogue code: their folders are under ``results/summary/``,
beside what compares the books of the study: ``ranking.csv``,
``ranking_costs_x2.csv``, ``yearly.csv`` and the figures of all of them
(``overview.png``, ``equity_all.png``, ``drawdowns_all.png``, ``costs.png``).
``results/summary/README.md`` is written by hand and is never touched here.

From the repository root, after ``scripts/SA11_run_garch_study.py``:

    uv run python scripts/write_strategy_reports.py --study runs/garch_study

A strategy studied on its own (``SA12``, ``SA13``) is written from its own
study with ``--only``; the document that study wrote, ``study.md``, is copied
into its folder, as are the figures the study named after it.

Nothing here computes a performance of its own for a strategy of a study:
every figure is read from the study's exports, so a folder cannot disagree
with the table it comes from. The measured facts of the analysis (dates and
sizes of the falls and rises, exposure held through them) are computed here
from those exports. The written commentary is not computed: it is read from
``research/commentary.toml``, by strategy code, and a strategy without one
says so instead of inventing a text.

``SA14`` is not in the study: its information stops at 2024-12-31, so it is run
here, once, on its test period extended to the study's last session, beside
the fund held and ``SA1`` over the same sessions (``--skip-sa14`` leaves it
out; it needs the ``ml`` extra and its calibrated artifact). Its figures are
on another period than the others' and are not comparable with them.

The tests are in ``tests/scripts/test_write_strategy_reports.py``.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from matplotlib.figure import Figure
from run_etf_strategies_comparison import (
    BENCHMARK,
    HELD,
    SPLIT,
    SURFACE,
    closes_of,
    costs_figure,
    drawdown_panels,
    equity_panels,
    ordered_funds,
    orders_figure,
    overview_figure,
    quality_details,
    slug,
    weights_figure,
)
from SA11_run_garch_study import EWMA, FUND, summary_frame, yearly_frame

from quant_backtester.analytics.curves import Book, drawdown_curve
from quant_backtester.analytics.plots import drawdown_figure, equity_figure
from quant_backtester.strategies.catalogue import CATALOGUE

UNCATALOGUED = {EWMA: "EWMA94control", HELD: "REF_WorldBuyHold", SPLIT: "REF_5050Rebalanced"}
"""The folder name of each book that has no catalogue code: the control of
``SA11`` and the two references every strategy is read against."""

SUMMARY = "summary"
"""The folder of what compares the books, and of the books that have no code."""

FIGURE_DPI = 110
"""Resolution of the figures of ``results/``: they are committed, so lighter than
the 160 a study draws its own at."""

DIAGNOSTICS = "results/summary/diagnostics.md"
"""Where the complementary measures of a strategy are, unless its commentary names
the document of its own study."""

OTHER_FUND = "ETF_SP500_PEA"
"""The second fund some strategies hold."""

MONTH_TOLERANCE = 1e-12
"""Monthly return at or under which, in absolute value, a month is counted as unchanged."""

WINDOW_SESSIONS = 63
"""Length of the rolling window the best and worst stretches are also measured on: a quarter."""

GLOBAL_ROWS: tuple[tuple[str, str, str], ...] = (
    ("rank", "Rank in the common ranking (QUALITY_V1)", "{:.0f}"),
    ("quality", "QUALITY_V1 quality score (0-100%)", "{:.1%}"),
    ("block_market", "- market block (IR and alpha against the fund held)", "{:.2f}"),
    ("block_significance", "- significance block (deflated Sharpe)", "{:.2f}"),
    ("block_risk", "- risk block (relative drawdown)", "{:.2f}"),
    ("block_robustness", "- robustness block (sub-periods; approximate cost stress)", "{:.2f}"),
    ("block_implementation", "- implementation block (weight of costs)", "{:.2f}"),
    ("net_return", "Total net return", "{:+.2%}"),
    ("gross_return", "Total gross return (same orders, no costs)", "{:+.2%}"),
    ("annualised_return", "Annualised net return", "{:+.2%}"),
    ("volatility", "Annualised volatility", "{:.2%}"),
    ("sharpe", "Net Sharpe ratio (risk-free rate 0)", "{:+.2f}"),
    ("sortino", "Net Sortino ratio (risk-free rate 0)", "{:+.2f}"),
    ("max_drawdown", "Maximum drawdown", "{:.2%}"),
    ("alpha_vs_market", "Annualised alpha against the fund held", "{:+.2%}"),
    ("beta_vs_market", "Beta against the fund held", "{:.2f}"),
    ("information_ratio_vs_market", "Information ratio against the fund held", "{:+.2f}"),
    ("alpha_vs_benchmark", "Annualised alpha against SA1 (MA20)", "{:+.2%}"),
    ("beta_vs_benchmark", "Beta against SA1 (MA20)", "{:.2f}"),
    ("average_exposure", "Average exposure (share invested)", "{:.1%}"),
    ("fills", "Orders filled", "{:.0f}"),
    ("costs_eur", "Costs paid (EUR)", "{:,.0f}"),
    ("turnover_per_year", "Annual turnover (multiple of average assets)", "{:.2f}"),
    ("net_return_first_two_thirds", "Net return, first two thirds", "{:+.2%}"),
    ("net_return_last_third", "Net return, last third", "{:+.2%}"),
    ("net_return_costs_x2", "Net return, second actual run at doubled costs", "{:+.2%}"),
    ("sharpe_costs_x2", "Net Sharpe, second actual run at doubled costs", "{:+.2f}"),
)
"""The global indicators, in order: column of the study, label, format."""

OPTIONAL_ROWS = frozenset({"sortino"})
"""Indicators only some studies measure: shown when the study exports them, left
out - not printed as missing - when it does not."""

PEER_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("rank", "Rank", "{:.0f}"),
    ("quality", "Score", "{:.1%}"),
    ("net_return", "Net", "{:+.2%}"),
    ("net_return_costs_x2", "Net, costs x2", "{:+.2%}"),
    ("sharpe", "Sharpe", "{:+.2f}"),
    ("max_drawdown", "Max. drawdown", "{:.2%}"),
    ("alpha_vs_market", "Alpha/yr", "{:+.2%}"),
    ("average_exposure", "Exposure", "{:.0%}"),
    ("costs_eur", "Costs (EUR)", "{:,.0f}"),
)
"""The columns of the table of every book of a study: column, label, format."""

HISTORY_COLUMNS: dict[str, tuple[str, str]] = {
    "mu_h2_bp": ("Forecast mu_2 (bp)", "{:+.2f}"),
    "forecast_volatility": ("Forecast volatility (annualised)", "{:.1%}"),
    "ewma_fallback": ("EWMA fallback (1 = yes)", "{:.0f}"),
    "gate": ("Gate (1 = open)", "{:.0f}"),
    "theoretical_weight": ("Weight before the band", "{:.1%}"),
    "model_month": ("Model of the month (YYYYMM)", "{:.0f}"),
    "forecast_bp": ("Forecast (bp)", "{:+.2f}"),
    "reference_bp": ("Reference (bp)", "{:+.2f}"),
    "displacements_bp": ("Displacements (bp)", "{:+.2f}"),
    "price_volume_bp": ("Price-volume (bp)", "{:+.2f}"),
    "price_time_bp": ("Price-time (bp)", "{:+.2f}"),
    "volume_time_bp": ("Volume-time (bp)", "{:+.2f}"),
    "order_3_bp": ("Order 3 (bp)", "{:+.2f}"),
}
"""The columns a study adds to a history beside the signals: heading and format."""


@dataclass(frozen=True, slots=True)
class Episode:
    """A stretch of sessions between two dates, and what changed over it.

    Attributes
    ----------
    start, end : date
        Its first and last session; the change is from the value of ``start``
        to the value of ``end``.
    change : float
        ``value(end) / value(start) - 1``.
    """

    start: date
    end: date
    change: float


def points(curve: pd.Series) -> list[tuple[date, float]]:  # type: ignore[type-arg]
    """Return a curve as ``(session, value)`` pairs, oldest first."""
    return [(day, float(value)) for day, value in curve.items() if isinstance(day, date)]


def deepest_fall(curve: pd.Series) -> Episode:  # type: ignore[type-arg]
    """Return the largest fall of a curve from a peak to a later trough."""
    values = points(curve)
    peak_day, peak = values[0]
    best = Episode(peak_day, peak_day, 0.0)
    for day, value in values:
        if value > peak:
            peak_day, peak = day, value
        change = value / peak - 1.0
        if change < best.change:
            best = Episode(peak_day, day, change)
    return best


def largest_rise(curve: pd.Series) -> Episode:  # type: ignore[type-arg]
    """Return the largest rise of a curve from a trough to a later peak."""
    values = points(curve)
    low_day, low = values[0]
    best = Episode(low_day, low_day, 0.0)
    for day, value in values:
        if value < low:
            low_day, low = day, value
        change = value / low - 1.0
        if change > best.change:
            best = Episode(low_day, day, change)
    return best


def extreme_window(curve: pd.Series, sessions: int, *, best: bool) -> Episode:  # type: ignore[type-arg]
    """Return the window of ``sessions`` session returns over which a curve changed most.

    Parameters
    ----------
    curve : pd.Series
        A value by session.
    sessions : int
        Length of the window, in session returns: 63 is about three months.
    best : bool
        ``True`` for the largest gain, ``False`` for the largest loss.

    Returns
    -------
    Episode
        From the session before the window's first return to its last one.
        The whole curve when it is shorter than the window.
    """
    values = points(curve)
    span = min(sessions, len(values) - 1)
    chosen = Episode(values[0][0], values[span][0], values[span][1] / values[0][1] - 1.0)
    for first in range(1, len(values) - span):
        change = values[first + span][1] / values[first][1] - 1.0
        if (change > chosen.change) if best else (change < chosen.change):
            chosen = Episode(values[first][0], values[first + span][0], change)
    return chosen


@dataclass(frozen=True, slots=True)
class Underwater:
    """A stretch a curve spent under one of its peaks.

    Attributes
    ----------
    peak : date
        The session of the peak the curve fell from.
    trough : date
        The session of its lowest value before that peak was reached again.
    depth : float
        ``value(trough) / value(peak) - 1``.
    recovery : date | None
        The first session whose value is at or above the peak's; ``None``
        when the curve ends before it is reached.
    """

    peak: date
    trough: date
    depth: float
    recovery: date | None


def underwater_episodes(curve: pd.Series) -> list[Underwater]:  # type: ignore[type-arg]
    """Return every stretch a curve spent under a peak, oldest first."""
    values = points(curve)
    peak_day, peak = values[0]
    trough_day, trough = values[0]
    under = False
    episodes: list[Underwater] = []
    for day, value in values[1:]:
        if value >= peak:
            if under:
                episodes.append(Underwater(peak_day, trough_day, trough / peak - 1.0, day))
            peak_day, peak, trough_day, trough, under = day, value, day, value, False
        else:
            under = True
            if value < trough:
                trough_day, trough = day, value
    if under:
        episodes.append(Underwater(peak_day, trough_day, trough / peak - 1.0, None))
    return episodes


def drawdown_markdown(curve: pd.Series, *, episodes: int = 3) -> str:  # type: ignore[type-arg]
    """Return the deepest drawdowns of a curve with their recovery, and where it stands now.

    The deepest stretches under a peak, each with the first valuation back at
    that peak and the calendar days from the peak to it; then the drawdown at
    the last session and the longest stretch spent under a peak. A stretch not
    recovered at the last session is said to be so, and its length is counted
    to that session.
    """
    values = points(curve)
    last_day = values[-1][0]
    found = underwater_episodes(curve)
    lines = [
        "| Rank | Peak | Trough | Depth | Back at the peak | Calendar days |",
        "|---:|---|---|---:|---|---:|",
    ]
    for rank, episode in enumerate(sorted(found, key=lambda item: item.depth)[:episodes], 1):
        end = last_day if episode.recovery is None else episode.recovery
        back = f"not recovered at {last_day}" if episode.recovery is None else str(episode.recovery)
        length = f"{(end - episode.peak).days}" + (
            " (ongoing)" if episode.recovery is None else ""
        )
        lines.append(
            f"| {rank} | {episode.peak} | {episode.trough} | {episode.depth:.2%} | {back} | "
            f"{length} |"
        )
    if not found:
        lines.append("| - | - | - | 0.00% | no fall below a peak | 0 |")
    peak = max(value for _, value in values)
    current = values[-1][1] / peak - 1.0
    lines += ["", f"Drawdown at {last_day}: **{current:.2%}** below the high of the period."]
    if found:
        longest = max(found, key=lambda item: ((item.recovery or last_day) - item.peak).days)
        end = longest.recovery or last_day
        state = "ongoing" if longest.recovery is None else "recovered"
        lines.append(
            f"Longest stretch below a peak: **{(end - longest.peak).days} calendar "
            f"days**, from {longest.peak} to {end} ({state}, trough at {longest.depth:.2%})."
        )
    return "\n".join(lines)


def change_over(curve: pd.Series, episode: Episode) -> float:  # type: ignore[type-arg]
    """Return the change of a curve between the two sessions of an episode."""
    return float(curve.loc[episode.end]) / float(curve.loc[episode.start]) - 1.0


def exposure_of(history: pd.DataFrame) -> pd.Series:  # type: ignore[type-arg]
    """Return the share of the book held in funds at each session."""
    held = [column for column in history.columns if column.startswith("held_")]
    return history[held].fillna(0.0).sum(axis=1)


def monthly_returns(curve: pd.Series) -> pd.Series:  # type: ignore[type-arg]
    """Return the return of each calendar month, from the last value of the month before."""
    days = [day for day in curve.index if isinstance(day, date)]
    last: dict[str, float] = {}
    for day in days:
        last[f"{day.year}-{day.month:02d}"] = float(curve.loc[day])
    months = list(last)
    values = [float(curve.iloc[0]), *last.values()]
    returns = {month: values[rank + 1] / values[rank] - 1.0 for rank, month in enumerate(months)}
    return pd.Series(returns, dtype="float64")


def episode_facts(
    label: str,
    episode: Episode,
    history: pd.DataFrame,
    market: pd.Series,  # type: ignore[type-arg]
) -> dict[str, object]:
    """Return one row of the table of facts: the strategy, the fund and the exposure over it."""
    inside = history.loc[episode.start : episode.end]
    exposure = exposure_of(inside)
    own = change_over(pd.Series(history["net_equity"]), episode)
    held = change_over(market, episode)
    return {
        "Stretch": label,
        "From": episode.start,
        "To": episode.end,
        "Valuations": len(inside),
        "Returns": len(inside) - 1,
        "Strategy": own,
        f"{FUND} (close)": change_over(pd.Series(history[f"close_{FUND}"]), episode),
        "Fund held (net)": held,
        "Relative gap": (1.0 + own) / (1.0 + held) - 1.0,
        "Average close weight": float(exposure.mean()),
        "Min. close weight": float(exposure.min()),
        "Max. close weight": float(exposure.max()),
    }


def facts_table(history: pd.DataFrame, market: pd.Series) -> pd.DataFrame:  # type: ignore[type-arg]
    """Return the measured stretches of one book: its own falls and rises, and the market's.

    Parameters
    ----------
    history : pd.DataFrame
        The book's history: ``net_equity``, the closes and the ``held_`` weights.
    market : pd.Series
        Net equity of the fund bought and held over the same sessions.

    Returns
    -------
    pd.DataFrame
        One row per stretch - the book's deepest fall, its largest rise, its
        worst and best windows of :data:`WINDOW_SESSIONS` sessions, the
        stretch over which it lost most ground to the fund held, the one over
        which it gained most on it, and the market's own deepest fall and
        largest rise - with the number of valuations and of returns it holds,
        the book's return, the fund's, their geometric relative return
        ``(1 + book) / (1 + fund) - 1`` - what the two relative stretches are
        selected on - and the weight held in funds at the closes.
    """
    equity = pd.Series(history["net_equity"])
    relative = pd.Series(equity / market)
    stretches = (
        ("Deepest fall (peak → trough)", deepest_fall(equity)),
        ("Largest rise (trough → later peak, any length)", largest_rise(equity)),
        (
            f"Worst {WINDOW_SESSIONS} consecutive returns",
            extreme_window(equity, WINDOW_SESSIONS, best=False),
        ),
        (
            f"Best {WINDOW_SESSIONS} consecutive returns",
            extreme_window(equity, WINDOW_SESSIONS, best=True),
        ),
        ("Largest relative lag behind the fund held", deepest_fall(relative)),
        ("Largest relative lead over the fund held", largest_rise(relative)),
        ("Deepest fall of the fund held", deepest_fall(market)),
        ("Largest rise of the fund held", largest_rise(market)),
    )
    rows = [episode_facts(label, episode, history, market) for label, episode in stretches]
    return pd.DataFrame(rows)


def _cell(value: object, pattern: str) -> str:
    """Return one cell, empty for a figure that does not exist."""
    if value is None or value is pd.NA:
        return "n/a"
    if isinstance(value, float) and math.isnan(value):
        return "n/a"
    return pattern.format(value)


def global_table(
    row: Mapping[str, object], market: Mapping[str, object], stressed: Mapping[str, object] | None
) -> str:
    """Return the table of global indicators: the strategy beside the fund held."""
    own, other = dict(row), dict(market)
    if stressed is not None:
        own["net_return_costs_x2"] = stressed.get("net_return")
        own["sharpe_costs_x2"] = stressed.get("sharpe")
    lines = [
        "| Indicator | Strategy | Fund held (buy & hold ETF_WORLD) |",
        "|---|---:|---:|",
        f"| Period measured | {own['first_session']} → {own['last_session']} "
        f"({int(float(own['sessions']))} sessions) | same |",  # type: ignore[arg-type]
    ]
    for key, label, pattern in GLOBAL_ROWS:
        if key in OPTIONAL_ROWS and key not in own:
            continue
        lines.append(
            f"| {label} | {_cell(own.get(key), pattern)} | {_cell(other.get(key), pattern)} |"
        )
    diagnostics = own.get("diagnostics")
    if isinstance(diagnostics, str) and diagnostics:
        lines.append(f"| Score diagnostics | {diagnostics} | |")
    return "\n".join(lines)


def facts_markdown(facts: pd.DataFrame) -> str:
    """Return the table of facts as Markdown."""
    patterns = {
        "Strategy": "{:+.2%}",
        f"{FUND} (close)": "{:+.2%}",
        "Fund held (net)": "{:+.2%}",
        "Relative gap": "{:+.2%}",
        "Average close weight": "{:.0%}",
        "Min. close weight": "{:.0%}",
        "Max. close weight": "{:.0%}",
    }
    columns = list(facts.columns)
    lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    for record in facts.to_dict(orient="records"):
        cells = [_cell(record[column], patterns.get(column, "{}")) for column in columns]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def calendar_markdown(
    equity: pd.Series,  # type: ignore[type-arg]
    market: pd.Series,  # type: ignore[type-arg]
    yearly: pd.DataFrame,
    name: str,
    control: str | None,
) -> str:
    """Return the yearly returns beside the references', and the months by sign.

    Parameters
    ----------
    equity, market : pd.Series
        Net equity of the book and of the fund held.
    yearly : pd.DataFrame
        Returns by calendar year, a row per book and a ``sessions`` row.
    name : str
        The book's row.
    control : str | None
        A second reference's row - the even split of the two funds - shown
        beside the fund held when it is given and is not the book itself.

    Notes
    -----
    A first year that starts after the first days of January and a last year
    that stops before the end of December are marked as partial, with the
    session they start or stop at; so is an unfinished last month. A month in
    which the value did not move is counted apart: for a rule that is rarely
    invested it says "nothing happened", not "nothing was earned".
    """
    days = [day for day, _ in points(equity)]
    first, last = days[0], days[-1]
    shown = control is not None and control != name and control in yearly.index
    head = "| Year | Strategy | Fund held |" + (" 50/50 rebalanced |" if shown else "")
    lines = [head + " Sessions |", "|---|---:|---:|" + ("---:|" if shown else "") + "---:|"]
    for year in yearly.columns:
        label = str(year)
        if int(year) == first.year and (first.month, first.day) > (1, 7):
            label += f" (partial, from {first})"
        if int(year) == last.year and (last.month, last.day) < (12, 24):
            label += f" (partial, to {last})"
        cells = [
            _cell(yearly.loc[name, year], "{:+.2%}"),
            _cell(yearly.loc[HELD, year], "{:+.2%}"),
            *([_cell(yearly.loc[control, year], "{:+.2%}")] if shown else []),
            _cell(yearly.loc["sessions", year], "{:.0f}"),
        ]
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    months, reference = monthly_returns(equity), monthly_returns(market)
    worst, best = str(months.idxmin()), str(months.idxmax())
    positive = int((months > MONTH_TOLERANCE).sum())
    negative = int((months < -MONTH_TOLERANCE).sum())
    partial = []
    if first.day > 7:
        partial.append(f"{first.year}-{first.month:02d} starts on {first}")
    if (last + timedelta(days=4)).month == last.month:
        partial.append(f"{last.year}-{last.month:02d} stops at {last}")
    lines += [
        "",
        f"Months: **{positive} positive, {negative} negative, "
        f"{len(months) - positive - negative} unchanged** out of {len(months)}"
        + (f" (incomplete months: {'; '.join(partial)})" if partial else "")
        + f". Worst month: **{worst}** ({months[worst]:+.2%}, fund held "
        f"{reference[worst]:+.2%}). Best month: **{best}** ({months[best]:+.2%}, fund "
        f"held {reference[best]:+.2%}).",
    ]
    return "\n".join(lines)


def activity_markdown(history: pd.DataFrame) -> str:
    """Return how often the book held anything at a close, and between which weights."""
    exposure = [float(value) for value in exposure_of(history)]
    invested = [value for value in exposure if value > 0.0]
    if not invested:
        return (
            f"Activity: no position held at a close over {len(exposure)} valuations."
        )
    return (
        f"Activity: a position is held at the close of **{len(invested)} valuations "
        f"out of {len(exposure)}**; the total weight held there ranges from {min(invested):.1%} "
        f"to {max(invested):.1%} (average over all valuations: "
        f"{math.fsum(exposure) / len(exposure):.1%})."
    )


def history_markdown(history: pd.DataFrame) -> str:
    """Return the history as one Markdown table, a row per session.

    The closes of the funds, each signal the strategy read, the weights
    targeted and held, and the net value. A signal without a value at a
    decision is left empty. The second fund's close is shown only when the
    strategy reads or holds it; a fund of its own that a book holds (the style
    funds of ``SA7``, the money-market fund of ``SA8``) is shown beside the
    world fund, which every report is read against.
    """
    uses_other = any(
        OTHER_FUND in column for column in history.columns if not column.startswith("close_")
    )
    columns = [
        column
        for column in history.columns
        if column != "gross_equity" and (uses_other or column != f"close_{OTHER_FUND}")
    ]
    headings = {
        f"close_{FUND}": f"Close {FUND}",
        f"close_{OTHER_FUND}": f"Close {OTHER_FUND}",
        "net_equity": "Net value (EUR)",
    }

    def heading(column: str) -> str:
        if column in headings:
            return headings[column]
        if column.startswith("target_"):
            return f"Target weight {column.removeprefix('target_')}"
        if column.startswith("held_"):
            return f"Held weight {column.removeprefix('held_')}"
        if column.startswith("proposed_"):
            return f"Proposed weight {column.removeprefix('proposed_')}"
        if column.startswith("open_"):
            return f"Open {column.removeprefix('open_')}"
        if column.startswith("close_"):
            return f"Close {column.removeprefix('close_')}"
        if column in HISTORY_COLUMNS:
            return HISTORY_COLUMNS[column][0]
        return f"`{column}`"

    def pattern(column: str) -> str:
        if column.startswith(("close_", "open_")):
            return "{:.2f}"
        if column in HISTORY_COLUMNS:
            return HISTORY_COLUMNS[column][1]
        if column == "net_equity":
            return "{:,.2f}"
        if column.startswith(("target_", "held_", "proposed_")):
            return "{:.1%}"
        return "{:.4f}"

    lines = [
        "| Session | " + " | ".join(heading(column) for column in columns) + " |",
        "|---|" + "---:|" * len(columns),
    ]
    table = history[columns].to_numpy(dtype="float64")
    for day, values in zip(history.index, table, strict=True):
        cells = []
        for column, value in zip(columns, values, strict=True):
            if math.isnan(value):
                cells.append("0.0%" if column.startswith(("target_", "held_")) else "")
            else:
                cells.append(pattern(column).format(float(value)))
        lines.append(f"| {day} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def commentary_markdown(notes: Mapping[str, object] | None) -> str:
    """Return the written analysis of one strategy, or say that none was written."""
    if not notes:
        return (
            "_No commentary has been written for this strategy: only the facts measured "
            "above are available._"
        )
    source = notes.get("measured_source", DIAGNOSTICS)
    sections = (
        ("summary", "In short", False),
        ("strengths", "Strengths", True),
        ("weaknesses", "Weaknesses", True),
        ("worst", "What happened over the stretch in which the strategy lost most", False),
        ("best", "What happened over the stretch in which the strategy gained most", False),
        ("risks", "The market situations most risky for this strategy", True),
        ("measured", f"Complementary measures (see {source})", True),
        ("to_test", "What these results do not establish, and what remains to be measured", True),
    )
    lines: list[str] = []
    for key, title, as_list in sections:
        content = notes.get(key)
        if not content:
            continue
        lines += [f"### {title}", ""]
        if as_list:
            assert isinstance(content, list)
            lines += [f"- {item}" for item in content]
        else:
            lines.append(str(content).strip())
        lines.append("")
    return "\n".join(lines).rstrip()


def peers_markdown(summary: pd.DataFrame, stressed: pd.DataFrame | None, name: str) -> str:
    """Return every book of the study in the order of its ranking, the strategy in bold.

    Parameters
    ----------
    summary : pd.DataFrame
        The common table of the study, a row per book, already ordered.
    stressed : pd.DataFrame | None
        The same table of the second real run at doubled costs.
    name : str
        The book the report is about.

    Returns
    -------
    str
        One row per book - the controls and the references among them, which
        are not candidates - on the period and under the costs of this study
        only: a figure of another study, measured from another date, is not
        comparable with these.
    """
    columns = [column for column in PEER_COLUMNS if column[0] != "net_return_costs_x2"]
    if stressed is not None:
        columns = list(PEER_COLUMNS)
    lines = [
        "| Book | " + " | ".join(label for _, label, _ in columns) + " |",
        "|---|" + "---:|" * len(columns),
    ]
    for book in summary.index:
        row = summary.loc[book].to_dict()
        if stressed is not None and book in stressed.index:
            row["net_return_costs_x2"] = stressed.loc[book, "net_return"]
        cells = [_cell(row.get(key), pattern) for key, _, pattern in columns]
        label = f"**{book}**" if str(book) == name else str(book)
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


SCORE_NOTE = (
    "The QUALITY_V1 score is a **weighted geometric mean** of five blocks bounded between 0 "
    "and 1 (market 30%, significance 25%, risk 15%, robustness 20%, implementation 10%): a "
    "single block at zero gives a zero score. A zero score is therefore neither a zero "
    "probability of gain nor an economic tie between two strategies; the implementation "
    "block, for example, falls to zero as soon as costs reach 30% of the gross gain. The "
    "robustness block contains an **approximate stress** of the costs, `net - (gross - net)` "
    "on the same orders; the last two rows of the table come from a **second actual run** at "
    "doubled costs, in which the quantities and the path change, and they do not enter the "
    "score. The score is deflated by the trials of this study only, not by earlier research: "
    "the ranking is exploratory, and a gap of a few points between two scores is not a test "
    "of superiority. The alphas are point estimates without an interval, with a zero "
    "risk-free rate; the alpha against SA1 compares with an active rule and is not a market "
    "alpha. The fund held is the yardstick of the score and is not scored. \"n/a\": the "
    "measure does not exist; it is never replaced by zero."
)
"""What the score and the alphas of the first table do and do not say."""

PEERS_NOTE = (
    "All these books are run by the same engine, over the same period, with the same costs. "
    "The controls (names starting with D or C) and the two references are not candidates. "
    "These figures are not comparable with those of another study, measured from another "
    "date; a rank is not a probability of success."
)
"""How the table of the peers is to be read."""

READING_NOTE = (
    "Each row runs from the value of the \"From\" session to that of the \"To\" session: N "
    "valuations, hence N - 1 returns. \"Largest rise\" is the largest rise from a trough to "
    "a later peak, of any length: it is neither a position nor a trade. The two relative "
    "stretches are selected on the ratio of the strategy to the fund held, whose change is "
    "the \"relative gap\" `(1 + strategy) / (1 + fund) - 1`. The \"close weight\" is the "
    "share of the net assets held in funds at the evening valuation, the rest being cash "
    "that earns nothing: it may have drifted with prices, and multiplying it by the fund's "
    "return does not rebuild the result. A decision taken on the evening of t (signal and "
    "target weight of row t) is executed at the open of t + 1 and appears in the weight held "
    "only at row t + 1."
)
"""How the measured stretches and the weights are to be read."""


def report(
    name: str,
    row: Mapping[str, object],
    market_row: Mapping[str, object],
    stressed: Mapping[str, object] | None,
    history: pd.DataFrame,
    market: pd.Series,  # type: ignore[type-arg]
    yearly: pd.DataFrame,
    notes: Mapping[str, object] | None,
    provenance: Sequence[str],
    *,
    control: str | None = None,
    history_note: str | None = None,
    peers: str | None = None,
    extra: str | None = None,
) -> str:
    """Return the whole report of one strategy: indicators, analysis, then history.

    Parameters
    ----------
    name : str
        The book, as the study names it.
    row, market_row : Mapping[str, object]
        Its row of the common table and the fund held's.
    stressed : Mapping[str, object] | None
        Its row in the second real run at doubled costs, when there is one.
    history : pd.DataFrame
        Its history by session.
    market : pd.Series
        Net equity of the fund held over the same sessions.
    yearly : pd.DataFrame
        Returns by calendar year of every book.
    notes : Mapping[str, object] | None
        Its written commentary.
    provenance : Sequence[str]
        The lines saying what it was produced from.
    control : str | None
        The row of ``yearly`` holding the even split of the two funds.
    history_note : str | None
        A sentence added above the history, for a book whose columns are not
        the signals it read.
    peers : str | None
        The table of every book of the study, shown under the indicators.
    extra : str | None
        The section only the study of this strategy can write - its forecasts,
        its controls, the status of its hypothesis - placed in the analysis,
        above the commentary.
    """
    equity = pd.Series(history["net_equity"])
    return "\n".join(
        [
            f"# {name} — results and analysis",
            "",
            *provenance,
            "",
            "## 1. Global result indicators",
            "",
            global_table(row, market_row, stressed),
            "",
            SCORE_NOTE,
            *(
                []
                if peers is None
                else [
                    "",
                    "### Ranking of every book of the study, over the same period",
                    "",
                    peers,
                    "",
                    PEERS_NOTE,
                ]
            ),
            "",
            "## 2. Analysis",
            "",
            "### Measured facts",
            "",
            facts_markdown(facts_table(history, market)),
            "",
            READING_NOTE,
            "",
            "### Falls below a peak and the return to it",
            "",
            drawdown_markdown(equity),
            "",
            "### By year and by month",
            "",
            calendar_markdown(equity, market, yearly, name, control),
            "",
            activity_markdown(history),
            "",
            *([] if extra is None else [extra.rstrip(), ""]),
            commentary_markdown(notes),
            "",
            "## 3. History: underlying, indicators used and value of the strategy",
            "",
            "One row per session. The indicators are those the strategy read at its evening "
            "decision (23:00 Paris), recomputed by its own signals on the store as the run "
            "read it. The target weight of row t is decided that evening and executed at the "
            "open of t + 1; the weight held of row t is the portfolio's at the valuation of t. "
            "An empty cell is an indicator with no value that day. The orders, the execution "
            "prices and the costs of each session are not in this table: they are in "
            "`fills.csv`, beside this file.",
            *([] if history_note is None else ["", history_note]),
            "",
            history_markdown(history),
            "",
        ]
    )


@dataclass(frozen=True, slots=True)
class BookFolder:
    """Everything the folder of one book holds, before it is written.

    Attributes
    ----------
    code : str
        The catalogue code of the book, or its name in :data:`UNCATALOGUED`.
    name : str
        The book, as its study names it.
    analysis : str
        Its report, as Markdown.
    metrics : pd.DataFrame
        Its row of the study's table, at the declared costs and, when the
        study ran it, at twice them.
    yearly : pd.DataFrame
        Its returns by calendar year, beside the fund held's.
    history : pd.DataFrame
        Its history by session: ``close_<fund>``, the signals it read,
        ``target_<fund>``, ``held_<fund>`` and ``net_equity``.
    fills : pd.DataFrame
        Its executions, one row per order.
    gross : pd.Series | None
        Its equity with no cost taken out, when the study exported it.
    market : pd.Series
        Net equity of the fund held over the same sessions.
    """

    code: str
    name: str
    analysis: str
    metrics: pd.DataFrame
    yearly: pd.DataFrame
    history: pd.DataFrame
    fills: pd.DataFrame
    gross: pd.Series | None  # type: ignore[type-arg]
    market: pd.Series  # type: ignore[type-arg]


def folder_of(output: Path, code: str) -> Path:
    """Return a book's folder: ``results/SA11``, or under ``results/summary`` without a code."""
    catalogued = {item.code for item in CATALOGUE}
    return output / code if code in catalogued else output / SUMMARY / code


def metrics_frame(row: Mapping[str, object], stressed: Mapping[str, object] | None) -> pd.DataFrame:
    """Return a book's indicators as a table: a row at the declared costs, one at twice them.

    Parameters
    ----------
    row : Mapping[str, object]
        Its row of the study's table.
    stressed : Mapping[str, object] | None
        Its row in the second real run at doubled costs, when there is one.
    """
    rows = (
        {"declared": dict(row)}
        if stressed is None
        else {"declared": dict(row), "doubled": dict(stressed)}
    )
    return pd.DataFrame.from_dict(rows, orient="index").rename_axis("costs")


def yearly_rows(yearly: pd.DataFrame, name: str) -> pd.DataFrame:
    """Return the returns by year of a book, of the fund held and the sessions counted."""
    kept = [row for row in dict.fromkeys((name, HELD, "sessions")) if row in yearly.index]
    return yearly.loc[kept]


def fills_of(fills: pd.DataFrame, name: str) -> pd.DataFrame:
    """Return the executions of one book, the column that named it dropped."""
    own = fills.loc[fills["book"] == name]
    return own.drop(columns="book").reset_index(drop=True)


def book_figures(book: BookFolder) -> dict[str, Figure]:
    """Return the figures of one book, by file name.

    Parameters
    ----------
    book : BookFolder
        What the folder holds; the figures are drawn from its history and
        its fills, and compute nothing of their own.

    Returns
    -------
    dict[str, Figure]
        ``equity.png`` and ``drawdown.png`` always; ``weights.png`` and
        ``orders.png`` when the history says what was held.
    """
    net = pd.Series(book.history["net_equity"], dtype="float64")
    # A reference is not drawn against itself.
    against = None if book.name == HELD else book.market.rename("fund held")
    figures: dict[str, Figure] = {
        "equity.png": equity_figure(
            net,
            title=f"{book.name}: net and gross equity"
            + ("" if against is None else ", against the fund held"),
            gross=book.gross,
            benchmark=against,
        ),
        "drawdown.png": drawdown_figure(
            drawdown_curve(net), title=f"{book.name}: drawdown of the net equity"
        ),
    }
    held = [column for column in book.history.columns if column.startswith("held_")]
    if held:
        # One order of the funds for both figures, whatever order the study exported them in.
        funds = ordered_funds([column.removeprefix("held_") for column in held])
        weights = pd.DataFrame({fund: book.history[f"held_{fund}"] for fund in funds})
        closes = {
            fund: pd.Series(book.history[f"close_{fund}"], dtype="float64")
            for fund in weights.columns
            if f"close_{fund}" in book.history.columns
        }
        figures["weights.png"] = weights_figure(book.name, weights)
        if closes:
            figures["orders.png"] = orders_figure(
                book.name, closes, book.fills, weights, net, book.market
            )
    return figures


def write_book(folder: Path, book: BookFolder) -> list[Path]:
    """Write the folder of one book and return the paths written.

    Parameters
    ----------
    folder : Path
        Where it goes; created when missing. Files already there under the
        same names are replaced, and nothing else in the folder is touched.
    book : BookFolder
        What to write.
    """
    folder.mkdir(parents=True, exist_ok=True)
    written = [folder / "analysis.md"]
    written[0].write_text(book.analysis, encoding="utf-8")
    tables = {
        "metrics.csv": book.metrics,
        "yearly.csv": book.yearly,
        "history.csv": book.history,
    }
    for name, table in tables.items():
        table.to_csv(folder / name)
        written.append(folder / name)
    book.fills.to_csv(folder / "fills.csv", index=False)
    written.append(folder / "fills.csv")
    for name, figure in book_figures(book).items():
        figure.savefig(folder / name, dpi=FIGURE_DPI, facecolor=SURFACE)
        written.append(folder / name)
    return written


def owner_of(config: Mapping[str, object]) -> str:
    """Return the code of the strategy a study is about: ``SA11`` for ``sa11_garch_vol_control``."""
    return str(config.get("study", "")).split("_")[0].upper()


def copy_study_files(study: Path, folder: Path, code: str) -> list[Path]:
    """Copy into a strategy's folder what its own study wrote about it.

    Parameters
    ----------
    study : Path
        The folder of the study's exports.
    folder : Path
        The folder of the strategy the study is about.
    code : str
        Its code: the figures the study named after it start with it.

    Returns
    -------
    list[Path]
        ``study.md`` and every ``<CODE>_*.png`` of the study, as copied.
    """
    folder.mkdir(parents=True, exist_ok=True)
    sources = [study / "study.md", *sorted(study.glob(f"{code}_*.png"))]
    written: list[Path] = []
    for source in sources:
        if source.is_file():
            written.append(Path(shutil.copyfile(source, folder / source.name)))
    return written


def read_curves(study: Path) -> dict[str, pd.Series]:  # type: ignore[type-arg]
    """Read the net equity of every book of a study, indexed by session date."""
    frame = pd.read_csv(study / "equity.csv", index_col="session_date")
    frame.index = pd.Index([date.fromisoformat(str(day)) for day in frame.index], dtype="object")
    return {
        str(column): pd.Series(frame[column], dtype="float64")
        for column in frame.columns
        if not str(column).endswith(" (gross)")
    }


def read_fills(study: Path) -> pd.DataFrame:
    """Read the executions of every book of a study, their session as a date."""
    fills = pd.read_csv(study / "fills.csv")
    fills["session_date"] = [date.fromisoformat(str(day)) for day in fills["session_date"]]
    return fills


def write_summary(
    folder: Path,
    summary: pd.DataFrame,
    stressed: pd.DataFrame,
    yearly: pd.DataFrame,
    curves: Mapping[str, pd.Series],  # type: ignore[type-arg]
) -> list[Path]:
    """Write what compares the books of a study and return the paths written.

    Parameters
    ----------
    folder : Path
        ``results/summary``; a ``README.md`` already there is left alone.
    summary, stressed : pd.DataFrame
        The study's table at the declared costs and at twice them, a row per book.
    yearly : pd.DataFrame
        Returns by calendar year of every book.
    curves : Mapping[str, pd.Series]
        Net equity of every book, on the same sessions.

    Returns
    -------
    list[Path]
        The three tables, ``overview.png``, ``costs.png`` when the study
        measured the costs, and the two figures of panels when the study holds
        the benchmark and the fund held they are drawn against.
    """
    folder.mkdir(parents=True, exist_ok=True)
    tables = {"ranking.csv": summary, "ranking_costs_x2.csv": stressed, "yearly.csv": yearly}
    for name, table in tables.items():
        table.to_csv(folder / name)
    figures: dict[str, Figure] = {"overview.png": overview_figure(curves)}
    if BENCHMARK in curves and HELD in curves:
        figures["equity_all.png"] = equity_panels(curves)
        figures["drawdowns_all.png"] = drawdown_panels(curves)
    if "costs_eur" in summary.columns:
        costs = summary["costs_eur"].dropna().to_numpy(dtype="float64")
        names = [str(name) for name in summary["costs_eur"].dropna().index]
        paid = dict(zip(names, (float(value) for value in costs), strict=True))
        if paid:
            figures["costs.png"] = costs_figure(paid)
    for name, figure in figures.items():
        figure.savefig(folder / name, dpi=FIGURE_DPI, facecolor=SURFACE)
    return [folder / name for name in (*tables, *figures)]


def study_inputs(study: Path) -> dict[str, object]:
    """Read the exports of the study a report is written from."""
    config = json.loads((study / "config.json").read_text(encoding="utf-8"))
    return {
        "summary": pd.read_csv(study / "summary.csv", index_col="book"),
        "stressed": pd.read_csv(study / "summary_costs_x2.csv", index_col="book"),
        "yearly": pd.read_csv(study / "yearly.csv", index_col="book"),
        "config": config,
    }


def read_history(study: Path, name: str) -> pd.DataFrame:
    """Read one book's history, indexed by session date."""
    frame = pd.read_csv(study / f"history_{slug(name)}.csv", index_col="session_date")
    frame.index = pd.Index([date.fromisoformat(str(day)) for day in frame.index], dtype="object")
    return frame.rename_axis("session_date")


def study_provenance(
    config: Mapping[str, object], *, period_label: str = "Common period", context: str = ""
) -> list[str]:
    """Return the lines saying what a report of the study was produced from.

    Parameters
    ----------
    config : Mapping[str, object]
        The study's ``config.json``.
    period_label : str
        What the period is called: a test period is not a common period.
    context : str
        A sentence the commentary adds about this study - why its period is
        what it is, what was calibrated - appended to the lines.
    """
    source = config["source"]
    period = config["period"]
    assert isinstance(source, dict) and isinstance(period, dict)
    return [
        *study_lines(source, period, config, period_label),
        *(["", context.strip()] if context.strip() else []),
    ]


def study_lines(
    source: Mapping[str, object],
    period: Mapping[str, object],
    config: Mapping[str, object],
    period_label: str,
) -> list[str]:
    """Return the two lines every report of a study starts with."""
    return [
        f"{period_label} {period['start']} → {period['end']} · capital 100,000 EUR · "
        "commission 5 bp (minimum 1 EUR), half spread 3 bp, slippage 2 bp · quantities "
        "set at the decision, execution at the next open · cash earns nothing · "
        "252 sessions a year.",
        "",
        f"Source: commit `{str(source.get('git_commit'))[:12]}` ({source.get('source_state')}), "
        f"store `{str(config['data_state'])[:12]}`, data up to {period['end']}. "
        "Retrospective evaluation: the history of ETF_WORLD had already been looked at in "
        "earlier exercises; it is not an untouched sample.",
    ]


def sa14_book(
    store: Path, artifacts: Path, end: str, notes: Mapping[str, object] | None
) -> BookFolder:
    """Run SA14 on its test period up to ``end`` and return what its folder holds.

    Raises
    ------
    ImportError
        If the ``ml`` extra is not installed.
    ArtifactError
        If the calibrated artifact of seed 42 is not in ``artifacts``.
    """
    # Imported on use: the script and the model need PyTorch, an optional dependency.
    import SA14_run_neural_strategy as neural

    from quant_backtester.ml.artifacts import NeuralArtifact
    from quant_backtester.strategies.SA14_neural_allocation import NeuralAllocationStrategy

    runner = neural.build_runner(store)
    artifact = NeuralArtifact.load(artifacts / "seed42_costs_x1", expected=neural.neural_config(42))
    strategy = NeuralAllocationStrategy.from_artifact(artifact)
    start, last = neural.TEST_PERIOD[0], date.fromisoformat(end)
    neural.validate_test_period(strategy, runner, start, last)
    books = {neural.SA14: strategy, **neural.references()}
    results = {}
    for name, book in books.items():
        print(f"running {name} on {start} to {last} ...", file=sys.stderr)
        results[name] = runner.run(book, neural.TRADABLE, start, last)
    net = {name: result.equity() for name, result in results.items()}
    gross = {name: result.equity(Book.GROSS) for name, result in results.items()}
    # One trial, as its hypothesis states: the frozen model of seed 42.
    kept = {name: net[name] for name in (neural.SA14, HELD)}
    details = {
        **dict.fromkeys(results),
        **quality_details(
            kept, {name: gross[name] for name in kept}, trials=1, trial_sharpe_std=0.0
        ),
    }
    summary = summary_frame(results, details)
    decisions = neural.neural_decisions(results[neural.SA14], strategy).set_index("session_date")
    closes = closes_of(results[neural.SA14])
    parts = [
        pd.DataFrame({f"close_{fund}": series for fund, series in closes.items()}),
        decisions[[column for column in decisions if column.startswith("proposed_")]],
        results[neural.SA14].target_weights().add_prefix("target_"),
        results[neural.SA14].weights().add_prefix("held_"),
        net[neural.SA14].rename("net_equity"),
    ]
    history = pd.concat(parts, axis=1).reindex(net[neural.SA14].index)
    source = results[neural.SA14].source.definition()
    provenance = [
        f"Test period {summary['first_session'].iloc[0]} → {summary['last_session'].iloc[0]} "
        "(after the information cutoff of the model, "
        f"{artifact.information_cutoff.date().isoformat()}) · frozen model "
        f"`{artifact.model_id[:12]}` (seed 42) · same capital, costs and conventions as the "
        "other strategies.",
        "",
        f"Source: commit `{str(source.get('git_commit'))[:12]}` ({source.get('source_state')}), "
        f"store `{results[neural.SA14].data_state.digest[:12]}`. **A period different from the "
        "other strategies'** (which starts in 2021): these figures are not comparable with "
        "theirs, and SA14 has no rank in the common ranking. The test was already read once, "
        "on 2026-10-04, up to 2026-09-30; this run extends it with the same model. The score "
        "is deflated for a single trial.",
    ]
    # Alone in its table, on its own period: it has no place in the common ranking.
    own = {**summary.loc[neural.SA14].to_dict(), "rank": None}
    text = report(
        neural.SA14,
        own,
        summary.loc[HELD].to_dict(),
        None,
        history,
        net[HELD],
        yearly_frame(net),
        notes,
        provenance,
        control=neural.SPLIT,
        history_note=(
            "For SA14, the \"proposed weight\" columns are the **output** of the network, not "
            "its inputs: the features it reads (returns, averages, volatilities of the two "
            "funds and of the VIX over 100 sessions) are not in this table."
        ),
    )
    return BookFolder(
        code="SA14",
        name=neural.SA14,
        analysis=text,
        metrics=metrics_frame(own, None),
        yearly=yearly_rows(yearly_frame(net), neural.SA14),
        history=history.rename_axis("session_date"),
        fills=results[neural.SA14].fills(),
        gross=gross[neural.SA14],
        market=net[HELD],
    )


def main(arguments: Sequence[str] | None = None) -> int:
    """Write the folder of every catalogued strategy the study ran, of SA14, and the summary."""
    parser = argparse.ArgumentParser(description="Write the results folder of a study.")
    parser.add_argument("--study", type=Path, default=Path("runs/garch_study"))
    parser.add_argument("--output", type=Path, default=Path("results"))
    parser.add_argument("--commentary", type=Path, default=Path("research/commentary.toml"))
    parser.add_argument("--store", type=Path, default=Path("market_data"))
    parser.add_argument("--artifacts", type=Path, default=Path("artifacts/neural/world_vix"))
    parser.add_argument("--skip-sa14", action="store_true")
    parser.add_argument(
        "--only",
        nargs="+",
        metavar="CODE",
        help="write these folders only (SA12, SA13 ...), with the ranking of the study and "
        "the section the study wrote for them; SA14 and the summary are then left alone",
    )
    options = parser.parse_args(arguments)
    study: Path = options.study
    output: Path = options.output

    inputs = study_inputs(study)
    summary, stressed, yearly = inputs["summary"], inputs["stressed"], inputs["yearly"]
    config = inputs["config"]
    assert isinstance(summary, pd.DataFrame) and isinstance(stressed, pd.DataFrame)
    assert isinstance(yearly, pd.DataFrame) and isinstance(config, dict)
    commentary: dict[str, object] = {}
    if options.commentary.exists():
        commentary = tomllib.loads(options.commentary.read_text(encoding="utf-8"))
    market = pd.Series(read_history(study, HELD)["net_equity"])
    fills = read_fills(study)
    names = {item.display_name: item.code for item in CATALOGUE}
    books: list[BookFolder] = []
    for name in summary.index:
        # The control and the two references carry no catalogue code: a name of their own.
        # The controls of a later study (D0, C0 ...) have neither, and no folder.
        code = names.get(str(name)) or UNCATALOGUED.get(str(name))
        if code is None or (options.only and code not in options.only):
            continue
        notes = commentary.get(code)
        notes = notes if isinstance(notes, dict) else None
        dedicated = study / f"report_extra_{code}.md"
        selected = bool(options.only)
        history = read_history(study, str(name))
        row = summary.loc[name].to_dict()
        doubled = stressed.loc[name].to_dict()
        text = report(
            str(name),
            row,
            summary.loc[HELD].to_dict(),
            doubled,
            history,
            market,
            yearly,
            notes,
            study_provenance(
                config,
                period_label=str((notes or {}).get("period_label", "Common period")),
                context=str((notes or {}).get("context", "")),
            ),
            control=SPLIT,
            history_note=str(notes["history_note"])
            if notes and notes.get("history_note")
            else None,
            peers=peers_markdown(summary, stressed, str(name)) if selected else None,
            extra=(
                dedicated.read_text(encoding="utf-8") if selected and dedicated.exists() else None
            ),
        )
        books.append(
            BookFolder(
                code=code,
                name=str(name),
                analysis=text,
                metrics=metrics_frame(row, doubled),
                yearly=yearly_rows(yearly, str(name)),
                history=history,
                fills=fills_of(fills, str(name)),
                gross=pd.Series(history["gross_equity"], dtype="float64")
                if "gross_equity" in history.columns
                else None,
                market=market,
            )
        )
    if options.only:
        missing = sorted(set(options.only) - {book.code for book in books})
        if missing:
            raise SystemExit(f"the study has no book for {', '.join(missing)}")
    if not options.skip_sa14 and not options.only:
        notes = commentary.get("SA14")
        period = config["period"]
        assert isinstance(period, dict)
        books.append(
            sa14_book(
                options.store,
                options.artifacts,
                str(period["end"]),
                notes if isinstance(notes, dict) else None,
            )
        )
    written: list[Path] = []
    for book in books:
        written += write_book(folder_of(output, book.code), book)
    owner = owner_of(config)
    if owner in {book.code for book in books}:
        written += copy_study_files(study, folder_of(output, owner), owner)
    if not options.only:
        written += write_summary(output / SUMMARY, summary, stressed, yearly, read_curves(study))
    for path in written:
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
