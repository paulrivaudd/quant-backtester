"""Drawing a run, without deciding anything about it.

A figure is the fastest way to see a shape a table hides - a drawdown that
lasted a year, a curve that only moves in one month of four - and the slowest
way to lose an argument about what was measured. So the rule here is narrow:
these functions draw what the analytics computed and compute nothing of their
own. A benchmark curve, an equity curve, a drawdown: each is built elsewhere,
tested elsewhere, and passed in.

They return a :class:`matplotlib.figure.Figure` and never call ``show``. A
notebook displays it, a test inspects it, a script saves it, and none of them
has to work around a window trying to open.

Nothing here reads the market data, and nothing here is point-in-time: a plot
is drawn after a run, from what the run recorded.
"""

from __future__ import annotations

import matplotlib
import pandas as pd

matplotlib.use("Agg", force=False)

from matplotlib.figure import Figure

_NET = "#1f4e79"
"""The strategy's own curve: the one a reader should follow first."""

_GROSS = "#9cb7cf"
"""The same trades without what execution took, drawn behind it."""

_BENCHMARK = "#c05621"
"""Whatever the strategy is being measured against."""


def equity_figure(
    net: pd.Series,  # type: ignore[type-arg]
    *,
    title: str,
    gross: pd.Series | None = None,  # type: ignore[type-arg]
    benchmark: pd.Series | None = None,  # type: ignore[type-arg]
) -> Figure:
    """Draw one or more equity curves on one scale.

    Parameters
    ----------
    net : pd.Series
        The strategy's own worth, session by session.
    title : str
        What the figure is of. A plot of an unnamed run over an unnamed period
        is a picture, not a result, so the caller has to give one.
    gross : pd.Series | None
        The same trades having paid the market price and no fee. Drawn
        behind the net curve when given: the gap between them is what
        execution took.
    benchmark : pd.Series | None
        What could have been held instead, already normalised to the same
        starting value by :func:`~quant_backtester.analytics.comparison.benchmark_curve`.

    Returns
    -------
    Figure
        Ready to be displayed, saved or inspected. ``show`` is never called.

    Raises
    ------
    ValueError
        If the curve holds no session: there is nothing to draw, and an empty
        figure in a report reads as a flat strategy.
    """
    if len(net) == 0:
        raise ValueError("there is nothing to draw: the curve holds no session")
    figure = Figure(figsize=(10, 5), layout="constrained")
    axes = figure.add_subplot()
    if gross is not None and len(gross):
        axes.plot(list(gross.index), list(gross), color=_GROSS, linewidth=1.2, label="gross")
    axes.plot(list(net.index), list(net), color=_NET, linewidth=1.6, label="net")
    if benchmark is not None and len(benchmark):
        axes.plot(
            list(benchmark.index),
            list(benchmark),
            color=_BENCHMARK,
            linewidth=1.4,
            linestyle="--",
            label=str(benchmark.name or "benchmark"),
        )
    axes.set_title(title)
    axes.set_ylabel("equity")
    axes.grid(visible=True, alpha=0.25)
    axes.legend(loc="upper left", frameon=False)
    return figure


def drawdown_figure(drawdown: pd.Series, *, title: str) -> Figure:  # type: ignore[type-arg]
    """Draw a drawdown curve, filled under zero.

    Parameters
    ----------
    drawdown : pd.Series
        Fractions at or below zero, measured against the running peak.
    title : str
        What the figure is of.

    Returns
    -------
    Figure
        The curve, with its axis in percent.

    Raises
    ------
    ValueError
        If the curve holds no session.
    """
    if len(drawdown) == 0:
        raise ValueError("there is nothing to draw: the curve holds no session")
    figure = Figure(figsize=(10, 3.2), layout="constrained")
    axes = figure.add_subplot()
    days = list(drawdown.index)
    values = [float(value) * 100.0 for value in drawdown]
    axes.fill_between(days, values, 0.0, color=_NET, alpha=0.25)
    axes.plot(days, values, color=_NET, linewidth=1.2)
    axes.set_title(title)
    axes.set_ylabel("drawdown (%)")
    axes.grid(visible=True, alpha=0.25)
    return figure
