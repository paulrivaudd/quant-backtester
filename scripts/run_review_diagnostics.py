"""Measure what the review of the 2026-10-10 analyses left open.

The analyses of ``research/reports/2026-10-10`` say, strategy by strategy, what
their figures do not establish. This script measures those points, from the
exports of ``scripts/run_garch_study.py`` and from a few more runs of the same
engine on the same period, cash and costs:

- the result and the costs of each **episode** a rarely invested rule was in
  the market (``SA1``, ``SA4``, ``SA9``);
- the signed **price gap** between a decision's close and its fill at the next
  open, at the quantities filled, for every book;
- an approximate **attribution** of ``SA2`` and ``SA5`` against the even split
  of the same two funds - exposure, choice between the funds, the residual of
  the approximation, costs - and how the tilt of ``SA5`` relates to what the
  funds did next;
- each exposure-moving rule beside a **constant-target control** aiming at the
  average weights that rule was seen to hold;
- ``SA10`` **without each of its rules**, and without its risk control;
- ``SA6`` against the EWMA control (paired bootstrap), and the EWMA rule at two
  other decays fixed here in advance (0.90 and 0.97);
- ``ML1`` beside a constant-target allocation, its announced sensitivities
  (seeds 43 and 44, doubled costs - the frozen model run dearer, and the model
  recalibrated under those costs, two different questions), and the inputs
  its network read.

From the repository root, after the study:

    uv run python scripts/run_review_diagnostics.py \
        --study results/garch_study --output results/review_diagnostics \
        --report research/reports/2026-10-10/diagnostics_10102026.md

Everything here is **descriptive**. A control built from the weights a rule
was seen to hold is chosen after the fact; an ablation or another decay is a
variant looked at after a backtest. None of them is a candidate: adopting one
would be a new hypothesis, written before its run, and each would count as a
trial in the register that deflates a Sharpe ratio.

The closes used to split a return into exposure and choice are closing
prices: such a split ignores that orders are filled at the open, and leaves
what it cannot place in a residual line. That residual is not a measure of
execution: it also holds the day's return on whatever was bought or sold that
morning, which is part of what the signal did.

The new runs are compared with the exports of the study only when they read
the same store, the same cash and the same costs: :func:`require_same_provenance`
refuses anything else.

The tests are in ``tests/scripts/test_run_review_diagnostics.py``.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from run_etf_strategies_comparison import (
    COMMON_PERIOD,
    HELD,
    SPLIT,
    STORE,
    UNIVERSE,
    build_runner,
)
from run_garch_study import COST_STRESS, EWMA, FUND, GARCH, VOL_CONTROL, sharpe_difference
from scipy.stats import pearsonr, spearmanr
from write_strategy_reports import (
    OTHER_FUND,
    exposure_of,
    points,
    read_history,
    underwater_episodes,
)

from quant_backtester.analytics.uncertainty import PairedBootstrap
from quant_backtester.backtest.runner import StrategyResult, StrategyRunner
from quant_backtester.signals.context import SignalContext
from quant_backtester.strategies import ETFEnsemble, EwmaVolControl, FixedWeights
from quant_backtester.strategies.base import Strategy
from quant_backtester.strategies.catalogue import entry

EPISODE_BOOKS = tuple(entry(code).display_name for code in ("SA1", "SA4", "SA9"))
"""The rules whose result is the sum of separate stays in the market."""

BASKET_BOOKS = tuple(entry(code).display_name for code in ("SA2", "SA5"))
"""The rules holding both funds, read against their even split."""

CONTROLLED_BOOKS = (
    entry("SA3").display_name,
    VOL_CONTROL,
    entry("SA10").display_name,
    GARCH,
    EWMA,
)
"""The rules that move their exposure, each given a constant-target control."""

ENSEMBLE = entry("SA10").display_name
ENSEMBLE_RULES = ("momentum", "trend", "pullback", "relative", "relief")
"""The budgeted rules of the ensemble as it is run here, each removed in turn."""

COST_TERMS = ("commission_rate", "minimum_commission", "half_spread_rate", "slippage_rate")
"""The terms of a cost model: what two runs must share to be compared."""

_COST_TERM = re.compile(r"'(\w+)': ([0-9.eE+-]+)")
"""One ``'name': number`` of a cost model written out as text."""

EWMA_DECAYS = (0.90, 0.97)
"""The other decays of the EWMA rule, fixed here before their runs."""

PANIC_GAP_SESSIONS = 20
"""Stays of ``SA9`` closer than this many valuations belong to one panic."""

FROZEN = "graine 42, modèle figé du test, coûts x2 (moteur seul)"
RECALIBRATED = "graine 42, recalibrée sous coûts x2"
"""The two rows of ``ML1`` at doubled costs: the same artifact run dearer, and
the calibration redone under those costs. Two questions, two labels."""

NO_RISK_CONTROL_TARGET = 10.0
"""A risk target no book reaches: the ensemble's control then never scales."""


# --- episodes ----------------------------------------------------------------------------


def episodes(history: pd.DataFrame, fills: pd.DataFrame) -> pd.DataFrame:
    """Return each stay of a book in the market, with its result and its costs.

    Parameters
    ----------
    history : pd.DataFrame
        The book's history: ``net_equity``, ``close_<fund>`` and ``held_<fund>``.
    fills : pd.DataFrame
        Its executions: ``session_date`` and ``total_cost``.

    Returns
    -------
    pd.DataFrame
        One row per maximal run of valuations at which something was held:
        ``entry`` (the first of them), ``exit`` (the first valuation back in
        cash; the last session, with ``open`` set, for a stay still running),
        ``valuations_held``, the net return from the valuation before the
        entry to the exit - so both fills and their costs are inside it - the
        change of the fund most held over the same dates, the orders filled
        and their costs.
    """
    values = points(pd.Series(history["net_equity"]))
    exposure = [float(value) for value in exposure_of(history)]
    weights = history[[column for column in history.columns if column.startswith("held_")]]
    days = [day for day, _ in values]
    rows: list[dict[str, object]] = []
    index = 0
    while index < len(days):
        if exposure[index] <= 0.0:
            index += 1
            continue
        first = index
        while index < len(days) and exposure[index] > 0.0:
            index += 1
        still_open = index == len(days)
        last = len(days) - 1 if still_open else index
        before = max(first - 1, 0)
        held = weights.iloc[first:index].fillna(0.0).mean()
        fund = str(held.idxmax()).removeprefix("held_")
        closes = history[f"close_{fund}"]
        after, until = fills["session_date"] > days[before], fills["session_date"] <= days[last]
        inside = fills.loc[after & until]
        rows.append(
            {
                "entry": days[first],
                "exit": days[last],
                "open": still_open,
                "valuations_held": index - first,
                "net_return": values[last][1] / values[before][1] - 1.0,
                "fund": fund,
                "fund_change": float(closes.iloc[last]) / float(closes.iloc[before]) - 1.0,
                "mean_weight": float(held.sum()),
                "orders": len(inside),
                "costs_eur": float(inside["total_cost"].sum()),
            }
        )
    return pd.DataFrame(rows)


def panics(stays: pd.DataFrame, history: pd.DataFrame) -> pd.DataFrame:
    """Group the stays of a rule into panics: stays a few sessions apart are one."""
    days = [day for day, _ in points(pd.Series(history["net_equity"]))]
    place = {day: rank for rank, day in enumerate(days)}
    groups: list[list[int]] = []
    for row in range(len(stays)):
        entry_rank = place[stays["entry"].iloc[row]]
        if groups and entry_rank - place[stays["exit"].iloc[groups[-1][-1]]] <= PANIC_GAP_SESSIONS:
            groups[-1].append(row)
        else:
            groups.append([row])
    rows = []
    for members in groups:
        part = stays.iloc[members]
        rows.append(
            {
                "first_entry": part["entry"].iloc[0],
                "last_exit": part["exit"].iloc[-1],
                "stays": len(part),
                "net_return": float(np.prod(1.0 + part["net_return"].to_numpy(dtype="float64")))
                - 1.0,
                "costs_eur": float(part["costs_eur"].sum()),
            }
        )
    return pd.DataFrame(rows)


def episode_summary(stays: pd.DataFrame) -> dict[str, object]:
    """Return the count, the share of gains and the spread of a set of stays.

    Returns
    -------
    dict[str, object]
        Over every stay - one still running at the last session is marked to
        that session's value, with no final sale: ``stays``, ``gains``,
        ``losses``, ``share_of_gains``, the mean, median, worst, best and
        ``compounded`` net return, which reconstitutes the whole curve. And
        over the stays that were closed, the only ones that hold both of their
        fills: ``completed``, ``open``, ``completed_gains``,
        ``completed_losses`` and ``completed_share_of_gains`` (``None``
        without a closed stay).
    """
    if stays.empty:
        return {"stays": 0}
    returns = stays["net_return"].to_numpy(dtype="float64")
    running = stays["open"].to_numpy(dtype=bool)
    closed = returns[~running]
    return {
        "stays": len(returns),
        "completed": len(closed),
        "open": int(running.sum()),
        "gains": int((returns > 0.0).sum()),
        "losses": int((returns < 0.0).sum()),
        "share_of_gains": float((returns > 0.0).mean()),
        "completed_gains": int((closed > 0.0).sum()),
        "completed_losses": int((closed < 0.0).sum()),
        "completed_share_of_gains": float((closed > 0.0).mean()) if len(closed) else None,
        "mean_net_return": float(returns.mean()),
        "median_net_return": float(np.median(returns)),
        "worst": float(returns.min()),
        "best": float(returns.max()),
        "compounded": float(np.prod(1.0 + returns)) - 1.0,
        "mean_valuations_held": float(stays["valuations_held"].to_numpy(dtype="float64").mean()),
        "orders": int(stays["orders"].to_numpy(dtype="int64").sum()),
        "costs_eur": float(stays["costs_eur"].to_numpy(dtype="float64").sum()),
    }


# --- the delay between the decision and the fill ----------------------------------------


def delay_effect(
    history: pd.DataFrame,
    fills: pd.DataFrame,
    initial_cash: float,
    *,
    ex_dates: Mapping[str, frozenset[date]] | None = None,
) -> dict[str, object]:
    """Return the signed close-to-open price gap of a book's orders, at the quantities filled.

    Parameters
    ----------
    history : pd.DataFrame
        The book's history, for the raw closes of the funds.
    fills : pd.DataFrame
        Its executions: ``session_date``, ``instrument_id``, ``side``,
        ``quantity`` and ``market_price`` (the open it was filled at, before
        spread and slippage).
    initial_cash : float
        What the run started with, to state the gap as a share of it.
    ex_dates : Mapping[str, frozenset[date]] | None
        Per fund, the ex-dates of its corporate actions. An order filled on
        one is left out and counted: the raw close before and the raw open
        after are not on one basis.

    Returns
    -------
    dict[str, object]
        ``orders`` counted; ``effect_eur``, the sum over them of ``-sign *
        quantity * (open - previous close)`` with ``sign`` +1 for a buy and -1
        for a sell - positive when the overnight move went the order's way;
        the same split into ``helped_eur`` and ``hurt_eur``; ``effect_share``
        of the initial cash; ``excluded_ex_date``.

    Notes
    -----
    A price gap at given quantities, the explicit costs left apart - the
    market price is used, not the fill price that carries the spread and the
    slippage. It is not the result of another backtest filled at the close:
    the signal reads that close, and another fill price would have changed
    every quantity that followed.
    """
    total = helped = hurt = 0.0
    counted = excluded = 0
    for record in fills.to_dict(orient="records"):
        instrument = str(record["instrument_id"])
        if ex_dates is not None and record["session_date"] in ex_dates.get(instrument, ()):
            excluded += 1
            continue
        closes = history[f"close_{instrument}"]
        before = closes.loc[closes.index < record["session_date"]].dropna()
        if before.empty:
            continue
        sign = 1.0 if record["side"] == "BUY" else -1.0
        gap = float(record["market_price"]) - float(before.iloc[-1])
        effect = -sign * float(record["quantity"]) * gap
        total += effect
        helped += max(effect, 0.0)
        hurt += min(effect, 0.0)
        counted += 1
    return {
        "orders": counted,
        "effect_eur": total,
        "helped_eur": helped,
        "hurt_eur": hurt,
        "effect_share": total / initial_cash,
        "excluded_ex_date": excluded,
    }


# --- attribution against a basket --------------------------------------------------------


def close_returns(history: pd.DataFrame, funds: Sequence[str]) -> pd.DataFrame:
    """Return the close-to-close simple return of each fund, by session."""
    closes = history[[f"close_{fund}" for fund in funds]]
    returns = closes / closes.shift(1) - 1.0
    returns.columns = list(funds)
    return returns.iloc[1:]


def basket_attribution(
    history: pd.DataFrame, basket: Mapping[str, float], basket_net: float | None
) -> dict[str, float | None]:
    """Split a book's return against a constant basket of the same funds, in log points.

    Parameters
    ----------
    history : pd.DataFrame
        The book's history: closes, ``held_`` weights, net and gross equity.
    basket : Mapping[str, float]
        The basket's weights by fund, summing to one: ``0.5 / 0.5``.
    basket_net : float | None
        Net total return of the basket run by the engine, when there is one.

    Returns
    -------
    dict[str, float | None]
        Every figure a log return over the period, so that the lines add up:

        ``basket_closes`` - the basket rebalanced at every close, no cost;
        ``exposure`` - what holding the book's *total* closing weight of the
        day before in that basket adds to it: the timing of the exposure;
        ``choice`` - what holding the book's own closing weights *by fund*
        adds to that: the choice between the funds;
        ``residual`` - the book's gross equity less that close-based figure:
        what the approximation on closing weights cannot place;
        ``costs`` - net less gross;
        ``book_net`` - the sum of the five; and ``basket_net``, for the
        comparison with the engine's own run of the basket.

    Notes
    -----
    The first three lines are computed on closing prices and on the weights
    held at the close of the day before, which is not how the book traded.
    The ``residual`` is what that leaves over, and it is **not** a measure of
    execution: besides the gap between the close and the fill, the band and
    whole shares, it holds the day's return on whatever was bought or sold
    that morning - a book in cash that buys at the open, at the price of the
    close before, and gains 10% by the close has that whole gain in its
    residual. Part of what the signal did is therefore in this line, and
    neither ``exposure`` nor ``choice`` is the whole contribution of a
    timing. An exact attribution needs the quantities before and after each
    fill and the opens; it is not computed here.
    """
    funds = list(basket)
    returns = close_returns(history, funds)
    held = history[[f"held_{fund}" for fund in funds]].fillna(0.0).shift(1).iloc[1:]
    held.columns = funds
    weights = pd.Series(basket, dtype="float64")
    basket_return = (returns * weights).sum(axis=1)
    by_exposure = held.sum(axis=1) * basket_return
    by_weights = (held * returns).sum(axis=1)

    def log_total(series: pd.Series) -> float:  # type: ignore[type-arg]
        return float(np.log1p(series.to_numpy(dtype="float64")).sum())

    gross = history["gross_equity"]
    net = history["net_equity"]
    gross_log = math.log(float(gross.iloc[-1]) / float(gross.iloc[0]))
    net_log = math.log(float(net.iloc[-1]) / float(net.iloc[0]))
    base, exposure, choice = log_total(basket_return), log_total(by_exposure), log_total(by_weights)
    return {
        "basket_closes": base,
        "exposure": exposure - base,
        "choice": choice - exposure,
        "residual": gross_log - choice,
        "costs": net_log - gross_log,
        "book_net": net_log,
        "basket_net": None if basket_net is None else math.log1p(basket_net),
    }


def tilt_diagnostics(history: pd.DataFrame, signal: str, first: str, second: str) -> dict:  # type: ignore[type-arg]
    """Return how a tilt signal behaves and how it relates to what the funds did next.

    Parameters
    ----------
    history : pd.DataFrame
        The book's history: the signal's column and the closes of both funds.
    signal : str
        The column of the tilt signal, positive when ``first`` lagged.
    first, second : str
        The two funds.

    Returns
    -------
    dict
        ``decisions`` with a value; ``sign_changes`` of the signal and the
        ``mean_run`` of valuations it keeps one sign for; then the Pearson and
        the Spearman correlation of the signal of ``t`` with the return of
        ``first`` less that of ``second``, close to close, over three
        horizons, each with its count of pairs: the session ``t + 1``
        (``next_1`` - partly before the fill at its open), the session ``t +
        2`` (``after_fill_1``), and the five sessions ``t + 2`` to ``t + 6``
        (``after_fill_5``), each fund's return compounded over them. A signal
        that predicted the relative return it leans on would show a positive
        one.

    Notes
    -----
    Every decision that has its future closes makes a pair, the first one
    included. The returns are close to close: they are not the open-to-open
    interval an order decided at ``t`` is actually held over, which this
    function does not measure. A linear or a rank correlation near zero does
    not rule out every other relation.
    """
    closes = history[[f"close_{first}", f"close_{second}"]]
    daily = closes / closes.shift(1) - 1.0
    relative = daily[f"close_{first}"] - daily[f"close_{second}"]
    five = closes.shift(-6) / closes.shift(-1) - 1.0
    value = history[signal]
    signs = np.sign(value.dropna().to_numpy(dtype="float64"))
    signs = signs[signs != 0.0]
    changes = int((signs[1:] != signs[:-1]).sum())
    horizons = {
        "next_1": relative.shift(-1),
        "after_fill_1": relative.shift(-2),
        "after_fill_5": five[f"close_{first}"] - five[f"close_{second}"],
    }
    outcome: dict[str, object] = {
        "decisions": len(signs),
        "sign_changes": changes,
        "mean_run": len(signs) / (changes + 1),
    }
    for name, ahead in horizons.items():
        paired = pd.concat([value, ahead], axis=1).dropna()
        pair = paired.to_numpy(dtype="float64")
        outcome[f"pearson_{name}"] = float(np.asarray(pearsonr(pair[:, 0], pair[:, 1]))[0])
        outcome[f"spearman_{name}"] = float(np.asarray(spearmanr(pair[:, 0], pair[:, 1]))[0])
        outcome[f"pairs_{name}"] = len(pair)
        outcome[f"first_pair_{name}"] = paired.index[0]
        outcome[f"last_pair_{name}"] = paired.index[-1]
    return outcome


def require_same_provenance(
    config: Mapping[str, object], result: StrategyResult, *, same_period: bool = True
) -> None:
    """Raise unless a new run can be put beside the exports of the study.

    Parameters
    ----------
    config : Mapping[str, object]
        The study's ``config.json``.
    result : StrategyResult
        A run made by this script.
    same_period : bool
        ``False`` for a run that is on another period by design - ``ML1`` on
        its test period - whose store and cash must still be the study's.

    Raises
    ------
    RuntimeError
        If the store read is not the one the study read, or the cash, the
        costs or - when asked - the dates differ: a table would then set side
        by side figures that do not follow from the same data.
    """
    problems: list[str] = []
    digest = result.data_state.digest
    if str(config["data_state"]) != digest:
        problems.append(
            f"the study read the store {str(config['data_state'])[:12]} and this run {digest[:12]}"
        )
    cash = result.configuration.get("initial_cash")
    if cash is None or float(config["initial_cash"]) != float(cash):  # type: ignore[arg-type]
        problems.append(f"initial cash {config['initial_cash']} in the study, {cash} here")
    if same_period:
        period = config["period"]
        assert isinstance(period, Mapping)
        if (str(period["start"]), str(period["end"])) != (str(result.start), str(result.end)):
            problems.append(
                f"period {period['start']} to {period['end']} in the study, "
                f"{result.start} to {result.end} here"
            )
        if cost_terms(result.configuration["execution"]) != cost_terms(config["execution"]):
            problems.append("the execution costs are not those of the study")
    if problems:
        raise RuntimeError(
            "this run does not compare with the exports of the study: " + "; ".join(problems)
        )


def cost_terms(execution: object) -> dict[str, float]:
    """Return the four cost terms of a recorded execution model.

    A run holds them in a mapping; a study's ``config.json`` holds the same
    mapping written out as text. Both are read through their text, so that
    the two can be compared.
    """
    found = dict(_COST_TERM.findall(str(execution)))
    return {name: float(found[name]) for name in COST_TERMS if name in found}


# --- measured rows of a run --------------------------------------------------------------


def recovery_days(curve: pd.Series) -> tuple[float, str]:  # type: ignore[type-arg]
    """Return the deepest drawdown of a curve and the days from its peak back to it."""
    found = underwater_episodes(curve)
    if not found:
        return 0.0, "0"
    deepest = min(found, key=lambda item: item.depth)
    last = points(curve)[-1][0]
    if deepest.recovery is None:
        return deepest.depth, f"{(last - deepest.peak).days} (en cours)"
    return deepest.depth, str((deepest.recovery - deepest.peak).days)


def run_row(result: StrategyResult) -> dict[str, object]:
    """Return the figures of one run that the comparisons of this script read."""
    net = result.report().net
    depth, days = recovery_days(result.equity())
    return {
        "net_return": net.total_return,
        "annualised_return": net.annualised_return,
        "volatility": net.annualised_volatility,
        "sharpe": net.sharpe_ratio,
        "max_drawdown": depth,
        "recovery_days": days,
        "average_exposure": float(result.weights().sum(axis=1).mean()),
        "fills": len(result.fills()),
        "costs_eur": result.backtest.total_cost,
    }


def history_row(history: pd.DataFrame, summary: Mapping[str, object]) -> dict[str, object]:
    """Return the same figures for a book of the study, from its exports."""
    depth, days = recovery_days(pd.Series(history["net_equity"]))
    return {
        "net_return": summary["net_return"],
        "annualised_return": summary["annualised_return"],
        "volatility": summary["volatility"],
        "sharpe": summary["sharpe"],
        "max_drawdown": depth,
        "recovery_days": days,
        "average_exposure": summary["average_exposure"],
        "fills": summary["fills"],
        "costs_eur": summary["costs_eur"],
    }


def mean_weights(history: pd.DataFrame) -> tuple[tuple[str, float], ...]:
    """Return the average closing weight of each fund a book held, as a constant target."""
    held = history[[column for column in history.columns if column.startswith("held_")]]
    means = held.fillna(0.0).mean()
    return tuple(
        (str(column).removeprefix("held_"), round(float(weight), 4))
        for column, weight in means.items()
        if weight > 0.0
    )


def control_of(name: str, history: pd.DataFrame) -> FixedWeights:
    """Return the constant-target control of a book: aimed at the weights it held on average."""
    slug = "".join(character if character.isalnum() else "_" for character in name.lower())
    return FixedWeights(weights=mean_weights(history), strategy_id=f"research_control_{slug}")


def exposure_gaps(controls: pd.DataFrame) -> tuple[float, float]:
    """Return the smallest and the largest gap of realised exposure, control minus rule.

    Parameters
    ----------
    controls : pd.DataFrame
        The table of the controls: a rule, then its control, row after row, with
        the ``average_exposure`` of each as a fraction of the book.

    Returns
    -------
    tuple[float, float]
        The two extremes of ``control - rule``, in points of exposure.

    Raises
    ------
    ValueError
        If the table is empty or leaves a rule without its control.
    """
    exposure = controls["average_exposure"].to_numpy(dtype="float64")
    if exposure.size == 0 or exposure.size % 2:
        raise ValueError("each rule must be followed by its control")
    gaps = (exposure[1::2] - exposure[0::2]) * 100.0
    return float(gaps.min()), float(gaps.max())


def ensemble_variants() -> dict[str, Strategy]:
    """Return the ensemble without each of its rules, and without its risk control."""
    base = ETFEnsemble(enable_factors=False, enable_monetary=False)
    variants: dict[str, Strategy] = {
        f"sans {rule}": replace(
            base, **{f"{rule}_budget": 0.0}, strategy_id=f"research_sa10_without_{rule}"
        )  # type: ignore[arg-type]
        for rule in ENSEMBLE_RULES
    }
    variants["sans contrôle de risque"] = replace(
        base,
        target_volatility=NO_RISK_CONTROL_TARGET,
        strategy_id="research_sa10_without_risk_control",
    )
    return variants


def ewma_variants() -> dict[str, Strategy]:
    """Return the EWMA rule at the other decays, each under its own identifier."""
    return {
        f"EWMA {decay:.2f}": EwmaVolControl(
            decay=decay, strategy_id=f"research_ewma{round(decay * 100)}_vol_control"
        )
        for decay in EWMA_DECAYS
    }


# --- the written diagnostics -------------------------------------------------------------


def _cell(value: object, pattern: str) -> str:
    """Return one cell, ``n/a`` for a figure that does not exist."""
    if value is None or value is pd.NA:
        return "n/a"
    if isinstance(value, float) and math.isnan(value):
        return "n/a"
    return pattern.format(value)


def table(frame: pd.DataFrame, columns: Sequence[tuple[str, str, str]], index: str) -> str:
    """Return a frame as a Markdown table of ``(column, heading, pattern)``, index first."""
    lines = [
        "| " + " | ".join([index, *[heading for _, heading, _ in columns]]) + " |",
        "|---|" + "---:|" * len(columns),
    ]
    for name, row in frame.iterrows():
        cells = [_cell(row[column], pattern) for column, _, pattern in columns]
        lines.append("| " + " | ".join([str(name), *cells]) + " |")
    return "\n".join(lines)


def open_stays_lines(frames: Mapping[str, pd.DataFrame]) -> list[str]:
    """Return one sentence per stay still running at the last session, by strategy."""
    lines: list[str] = []
    for name in EPISODE_BOOKS:
        stays = frames[f"episodes_{name.split(' - ')[0].lower()}"]
        if stays.empty:
            continue
        for row in stays.loc[stays["open"]].to_dict(orient="records"):
            lines.append(
                f"- {name} : un séjour encore ouvert, entré à la valorisation du "
                f"{row['entry']}, valorisé {float(row['net_return']):+.2%} au "
                f"{row['exit']}, sans vente finale."
            )
    return [*lines, ""] if lines else []


RUN_COLUMNS = (
    ("net_return", "Net", "{:+.2%}"),
    ("annualised_return", "Net/an", "{:+.2%}"),
    ("volatility", "Vol.", "{:.2%}"),
    ("sharpe", "Sharpe", "{:+.2f}"),
    ("max_drawdown", "Perte max.", "{:.2%}"),
    ("recovery_days", "Retour au sommet (j)", "{}"),
    ("average_exposure", "Expo. moy.", "{:.1%}"),
    ("fills", "Ordres", "{:.0f}"),
    ("costs_eur", "Coûts EUR", "{:,.0f}"),
)
"""The columns every table of runs shows."""

HEADER = """# Diagnostics complémentaires — résultats du 10 octobre 2026

Ce document mesure ce que les analyses de ce dossier listaient comme « restant à
mesurer », à la demande de la revue indépendante du 10 octobre. Il est écrit par
`scripts/run_review_diagnostics.py`, à partir des exports de l'étude et de
quelques runs supplémentaires du même moteur, sur la même période
(2021-04-01 → 2026-10-09), avec le même capital et les mêmes coûts.

**Tout ce qui suit est descriptif.** Un témoin à cible constante, dont la cible
est le poids qu'une règle a détenu en moyenne, est choisi après coup : il décrit
le passé de cette règle, ce n'est pas un paramètre qu'on aurait pu fixer à
l'avance, et son exposition réalisée n'est pas celle de la règle. Une ablation
de `SA10` ou un autre coefficient d'EWMA est une variante
regardée après un backtest. Aucune n'est candidate : en retenir une serait une
nouvelle hypothèse, à écrire avant son run, et chacune compterait comme un
essai dans le registre qui déflate les Sharpe. Les estimations sont ponctuelles
sauf mention d'un intervalle. Rien ici n'est un échantillon vierge.

Version 2 du 10 octobre 2026, après la vérification indépendante faite sur le
commit `ad310bc`. Ont changé : l'écart de prix clôture-ouverture est mesuré à
quantités données, sur le prix de marché et non sur le montant exécuté ; la
colonne « exécution » de l'attribution est renommée en résidu, parce qu'elle
n'isole pas l'exécution ; les séjours clos et le séjour encore ouvert sont
comptés à part ; les corrélations de `SA5` gardent leur première décision et
composent leurs rendements à cinq séances ; les témoins sont dits « à cible
constante » ; `ML1` est rejoué avec son modèle figé à coûts doublés ; un run
n'est comparé aux exports que s'il a lu le même magasin.
"""


def main(arguments: Sequence[str] | None = None) -> int:
    """Compute every diagnostic and write the exports and the document."""
    parser = argparse.ArgumentParser(description="Measure what the review left open.")
    parser.add_argument("--study", type=Path, default=Path("results/garch_study"))
    parser.add_argument("--output", type=Path, default=Path("results/review_diagnostics"))
    parser.add_argument(
        "--report", type=Path, default=Path("research/reports/2026-10-10/diagnostics_10102026.md")
    )
    parser.add_argument("--store", type=Path, default=STORE)
    parser.add_argument("--artifacts", type=Path, default=Path("artifacts/neural/world_vix"))
    parser.add_argument("--skip-ml1", action="store_true")
    options = parser.parse_args(arguments)
    study: Path = options.study
    output: Path = options.output

    summary = pd.read_csv(study / "summary.csv", index_col="book")
    fills = pd.read_csv(study / "fills.csv")
    fills["session_date"] = [date.fromisoformat(str(day)) for day in fills["session_date"]]
    histories = {str(name): read_history(study, str(name)) for name in summary.index}
    equity = pd.read_csv(study / "equity.csv", index_col="session_date")
    for name, history in histories.items():
        history["gross_equity"] = equity[f"{name} (gross)"].to_numpy(dtype="float64")
    initial = float(histories[HELD]["net_equity"].iloc[0])
    sections: list[str] = [HEADER]
    frames: dict[str, pd.DataFrame] = {}

    # 1. Episodes of the rarely invested rules.
    sections += ["## 1. Résultat par séjour dans le marché (SA1, SA4, SA9)", ""]
    summaries: dict[str, dict[str, object]] = {}
    for name in EPISODE_BOOKS:
        stays = episodes(histories[name], fills.loc[fills["book"] == name])
        frames[f"episodes_{name.split(' - ')[0].lower()}"] = stays
        summaries[name] = episode_summary(stays)
    frames["episodes_summary"] = pd.DataFrame.from_dict(summaries, orient="index")
    sections += [
        table(
            frames["episodes_summary"],
            [
                ("stays", "Séjours", "{:.0f}"),
                ("completed", "Clos", "{:.0f}"),
                ("open", "Ouvert", "{:.0f}"),
                ("completed_gains", "Clos gagnants", "{:.0f}"),
                ("completed_losses", "Clos perdants", "{:.0f}"),
                ("completed_share_of_gains", "Part gagnante (clos)", "{:.1%}"),
                ("mean_net_return", "Net moyen", "{:+.2%}"),
                ("median_net_return", "Net médian", "{:+.2%}"),
                ("worst", "Pire", "{:+.2%}"),
                ("best", "Meilleur", "{:+.2%}"),
                ("compounded", "Composé", "{:+.2%}"),
                ("mean_valuations_held", "Durée moy. (valo.)", "{:.1f}"),
                ("costs_eur", "Coûts EUR", "{:,.0f}"),
            ],
            "Stratégie",
        ),
        "",
        "Un séjour est une suite de valorisations où une position est détenue. Le "
        "résultat net d'un séjour **clos** va de la valorisation qui précède l'entrée à "
        "la première valorisation revenue en cash : ses deux exécutions et leurs coûts "
        "sont dedans. Un séjour **ouvert** court encore à la dernière séance : il est "
        "valorisé au marché à cette séance, sans vente finale ni son coût. Les gagnants "
        "et les perdants sont comptés sur les seuls séjours clos. Le net moyen, le "
        "médian, le pire, le meilleur et « Composé » portent sur tous les séjours, "
        "l'ouvert compris : « Composé » en est le produit et retrouve le rendement net "
        "de la stratégie, puisque le cash ne rapporte rien.",
        "",
        *open_stays_lines(frames),
    ]
    relief = entry("SA9").display_name
    grouped = panics(frames["episodes_sa9"], histories[relief])
    frames["episodes_sa9_panics"] = grouped
    sections += [
        f"### SA9 : ses {len(frames['episodes_sa9'])} séjours en {len(grouped)} groupes "
        f"(convention : {PANIC_GAP_SESSIONS} valorisations)",
        "",
        table(
            grouped.set_index("first_entry"),
            [
                ("last_exit", "Dernière sortie", "{}"),
                ("stays", "Séjours", "{:.0f}"),
                ("net_return", "Net", "{:+.2%}"),
                ("costs_eur", "Coûts EUR", "{:,.0f}"),
            ],
            "Première entrée",
        ),
        "",
        f"Deux séjours séparés par {PANIC_GAP_SESSIONS} valorisations ou moins sont "
        "rattachés au même groupe. C'est un regroupement automatique par cette "
        "convention, pas l'identification économique d'autant de paniques "
        "indépendantes ; un groupe gagnant peut compter plusieurs entrées, comme un "
        "groupe perdant.",
        "",
    ]

    # 2. The price gap between the decision's close and the fill at the open.
    runner = build_runner(options.store)
    config = json.loads((study / "config.json").read_text(encoding="utf-8"))
    last_decision = runner.timetable.decision_instant(date.fromisoformat(COMMON_PERIOD[1]))
    market = runner.reader.at(last_decision)
    ex_dates = {fund: frozenset(market.corporate_actions(fund)["ex_date"]) for fund in UNIVERSE}
    delays = {
        name: delay_effect(history, fills.loc[fills["book"] == name], initial, ex_dates=ex_dates)
        for name, history in histories.items()
    }
    frames["delay_effect"] = pd.DataFrame.from_dict(delays, orient="index")
    sections += [
        "## 2. Écart de prix signé clôture-ouverture, à quantités données",
        "",
        table(
            frames["delay_effect"],
            [
                ("orders", "Ordres", "{:.0f}"),
                ("helped_eur", "Écarts favorables EUR", "{:+,.0f}"),
                ("hurt_eur", "Écarts défavorables EUR", "{:+,.0f}"),
                ("effect_eur", "Écart net EUR", "{:+,.0f}"),
                ("effect_share", "En % du capital initial", "{:+.2%}"),
                ("excluded_ex_date", "Ordres exclus (date de détachement)", "{:.0f}"),
            ],
            "Livre",
        ),
        "",
        "Pour chaque ordre : `-signe x quantité x (ouverture - clôture précédente)`, "
        "signe +1 pour un achat, sur le prix de marché de l'ouverture et non sur le prix "
        "exécuté : le spread, le slippage et la commission restent dans les coûts. "
        "Positif : le mouvement de la nuit est allé dans le sens de l'ordre. Un ordre "
        "exécuté à une date de détachement est exclu, les deux prix n'étant pas sur la "
        "même base.",
        "",
        "C'est un **écart de prix à quantités données**, pas le résultat d'un autre "
        "backtest exécuté à la clôture : le signal lit cette clôture, donc l'ordre ne "
        "pouvait pas y être exécuté, et un autre prix d'exécution aurait changé toutes "
        "les quantités suivantes. Il ne se lit ni comme un coût payé ni comme un manque "
        "à gagner exact.",
        "",
    ]

    # 3. SA2 and SA5 against the even split.
    basket: dict[str, float] = {fund: 0.5 for fund in UNIVERSE}
    basket_net = float(summary.loc[SPLIT, "net_return"])
    attribution = {
        name: basket_attribution(histories[name], basket, basket_net) for name in BASKET_BOOKS
    }
    frames["basket_attribution"] = pd.DataFrame.from_dict(attribution, orient="index")
    sections += [
        "## 3. SA2 et SA5 contre le panier 50/50 des deux mêmes fonds",
        "",
        table(
            frames["basket_attribution"],
            [
                ("basket_closes", "Panier (clôtures)", "{:+.4f}"),
                ("exposure", "Exposition totale", "{:+.4f}"),
                ("choice", "Choix entre fonds", "{:+.4f}"),
                ("residual", "Résidu de l'approximation aux poids de clôture", "{:+.4f}"),
                ("costs", "Coûts", "{:+.4f}"),
                ("book_net", "= Net de la stratégie", "{:+.4f}"),
                ("basket_net", "Panier 50/50 exécuté, net", "{:+.4f}"),
            ],
            "Stratégie",
        ),
        "",
        "Rendements logarithmiques sur la période, qui s'additionnent ligne à ligne. "
        "« Exposition totale » : ce que détenir le poids total de la veille dans le "
        "panier ajoute au panier. « Choix entre fonds » : ce que détenir les poids par "
        "fonds de la veille ajoute à cela. Ces trois premières colonnes sont une "
        "**approximation** : elles valorisent les poids détenus à la clôture précédente "
        "avec le rendement de clôture à clôture, ce qui n'est pas la façon dont le livre "
        "a traité.",
        "",
        "Le **résidu** est l'écart entre cette approximation et la comptabilité brute du "
        "moteur. Ce n'est pas une mesure de l'exécution : outre l'écart entre la clôture "
        "et le prix exécuté, la bande et les quantités entières, il contient le rendement "
        "de la journée sur ce qui a été acheté ou vendu le matin même - une partie de "
        "l'effet du signal. Un livre en cash qui achète à l'ouverture, au prix de la "
        "clôture précédente, et gagne 10 % dans la journée voit tout ce gain dans le "
        "résidu, avec une « exposition » négative d'autant. Les colonnes « exposition » "
        "et « choix » ne sont donc pas l'apport complet d'un timing, et le résidu n'est "
        "pas un handicap d'exécution. Une attribution exacte demande les quantités avant "
        "et après chaque exécution et les prix d'ouverture ; elle n'est pas produite ici.",
        "",
    ]
    tilt_book = entry("SA5").display_name
    tilt_column = next(c for c in histories[tilt_book].columns if c.startswith("residual_"))
    tilt = tilt_diagnostics(histories[tilt_book], tilt_column, FUND, OTHER_FUND)
    frames["sa5_tilt"] = pd.DataFrame([tilt])
    sections += [
        "### SA5 : le signal d'inclinaison et ce que les fonds ont fait ensuite",
        "",
        f"- {tilt['decisions']} décisions avec un résidu non nul ; le résidu change de "
        f"signe **{tilt['sign_changes']} fois**, soit un signe tenu en moyenne "
        f"{tilt['mean_run']:.1f} valorisations.",
        "- Corrélation du résidu (positif quand le fonds monde a pris du retard, donc "
        "surpondéré) avec le rendement relatif monde moins S&P 500 :",
        "",
        "| Horizon | Pearson | Spearman | Paires |",
        "|---|---:|---:|---:|",
        *[
            f"| {label} | {tilt[f'pearson_{key}']:+.3f} | {tilt[f'spearman_{key}']:+.3f} | "
            f"{tilt[f'pairs_{key}']} |"
            for key, label in (
                ("next_1", "séance t + 1 (en partie avant l'exécution à son ouverture)"),
                ("after_fill_1", "séance t + 2, la première entière après l'exécution"),
                ("after_fill_5", "séances t + 2 à t + 6, rendements composés"),
            )
        ],
        "",
        "Un signal qui prévoirait le rendement relatif sur lequel il mise montrerait une "
        "corrélation positive. Ces coefficients sont donnés sans intervalle, sur des "
        "rendements de clôture à clôture : ils ne mesurent pas l'intervalle d'ouverture à "
        "ouverture réellement porté après la décision, qui n'est pas calculé ici, et une "
        "corrélation proche de zéro n'exclut pas toute relation non linéaire.",
        "",
    ]

    # 4. More runs: constant-target controls, ablations, other decays.
    source = runner.source.definition()
    sections.insert(
        1,
        f"Exports de l'étude : commit `{str(config['source']['git_commit'])[:12]}` "
        f"({config['source']['source_state']}), magasin `{str(config['data_state'])[:12]}`. "
        f"Runs de ce document : commit `{str(source.get('git_commit'))[:12]}` "
        f"({source.get('source_state')}).\n",
    )
    controls: dict[str, dict[str, object]] = {}
    for name in CONTROLLED_BOOKS:
        control = control_of(name, histories[name])
        print(f"running the constant-target control of {name} ...", file=sys.stderr)
        result = runner.run(control, UNIVERSE, *COMMON_PERIOD)
        require_same_provenance(config, result)
        weights = ", ".join(f"{fund} {weight:.1%}" for fund, weight in control.weights)
        controls[name] = history_row(histories[name], summary.loc[name].to_dict())
        controls[f"↳ témoin à cible constante ({weights})"] = run_row(result)
    frames["constant_weight_controls"] = pd.DataFrame.from_dict(controls, orient="index")
    low, high = exposure_gaps(frames["constant_weight_controls"])
    sections += [
        "## 4. Chaque règle à exposition variable à côté d'un témoin à cible constante",
        "",
        table(frames["constant_weight_controls"], RUN_COLUMNS, "Livre"),
        "",
        "Témoin à **cible constante** égale aux poids moyens historiques de la règle, "
        "avec la même bande de rééquilibrage de 3 points et les mêmes coûts : il ne "
        "traite que lorsque la dérive des cours l'écarte de sa cible de 3 points. Son "
        "exposition **réalisée** diffère donc de celle de la règle, comme la colonne "
        f"« Expo. moy. » le montre (témoin moins règle : de {low:+.1f} à {high:+.1f} "
        "points ici). "
        "La comparaison décrit le résultat de deux règles exécutables ; elle n'isole pas, "
        "à exposition exactement identique, la valeur du timing : le niveau d'exposition, "
        "la composition, les coûts et la trajectoire changent aussi. Ces poids étant "
        "connus après coup, elle est descriptive.",
        "",
    ]

    variants: dict[str, dict[str, object]] = {
        ENSEMBLE: history_row(histories[ENSEMBLE], summary.loc[ENSEMBLE].to_dict())
    }
    for label, strategy in ensemble_variants().items():
        print(f"running SA10 {label} ...", file=sys.stderr)
        ablated = runner.run(strategy, UNIVERSE, *COMMON_PERIOD)
        require_same_provenance(config, ablated)
        variants[f"SA10 {label}"] = run_row(ablated)
    frames["sa10_ablations"] = pd.DataFrame.from_dict(variants, orient="index")
    sections += [
        "## 5. SA10 sans chacune de ses règles, et sans son contrôle de risque",
        "",
        table(frames["sa10_ablations"], RUN_COLUMNS, "Version"),
        "",
        "Chaque ligne « sans » remet le budget d'une règle à zéro : ce budget reste en "
        "cash, il n'est pas redistribué. « Sans contrôle de risque » fixe la cible de "
        "risque à un niveau jamais atteint, donc le facteur de réduction vaut toujours "
        "1. Toutes ces versions sont, comme SA10 ici, sans fonds de style ni monétaire.",
        "",
        "L'écart entre SA10 et sa version sans contrôle de risque mesure l'**effet "
        "agrégé** de ce contrôle sur ce run. Il ne dit pas combien de fois le facteur de "
        "réduction a été inférieur à 1, ni à quelles dates : ce facteur et les décisions "
        "forcées par le risque du portefeuille détenu ne sont pas exportés.",
        "",
    ]

    decays: dict[str, dict[str, object]] = {
        EWMA: history_row(histories[EWMA], summary.loc[EWMA].to_dict()),
        VOL_CONTROL: history_row(histories[VOL_CONTROL], summary.loc[VOL_CONTROL].to_dict()),
    }
    for label, strategy in ewma_variants().items():
        print(f"running {label} ...", file=sys.stderr)
        slower = runner.run(strategy, UNIVERSE, *COMMON_PERIOD)
        require_same_provenance(config, slower)
        decays[label] = run_row(slower)
    frames["ewma_decays"] = pd.DataFrame.from_dict(decays, orient="index")
    curves = pd.read_csv(study / "equity.csv", index_col="session_date")
    measured = sharpe_difference(pd.Series(curves[VOL_CONTROL]), pd.Series(curves[EWMA]))
    sections += [
        "## 6. SA6 contre le témoin EWMA, et l'EWMA à d'autres coefficients",
        "",
        (
            f"Différence de Sharpe SA6 moins EWMA 0,94 : **{measured.estimate:+.3f}**, "
            f"intervalle bootstrap à {measured.level:.0%} "
            f"[{measured.low:+.3f} ; {measured.high:+.3f}] (blocs de {measured.block} "
            f"séances, {measured.draws} tirages, graine {measured.seed}). "
            + (
                "L'intervalle inclut zéro : les deux témoins ne sont pas départagés."
                if measured.low <= 0.0 <= measured.high
                else "L'intervalle exclut zéro."
            )
            if isinstance(measured, PairedBootstrap)
            else f"Différence de Sharpe SA6 moins EWMA : bootstrap {measured}."
        ),
        "",
        table(frames["ewma_decays"], RUN_COLUMNS, "Livre"),
        "",
        "Les coefficients 0,90 et 0,97 ont été fixés dans le script avant leur run, de "
        "part et d'autre de 0,94 ; ils ne sont pas le résultat d'une recherche du "
        "meilleur coefficient, et ne doivent pas le devenir sur ce même historique. "
        "L'ordre de ces trois EWMA ne vaut que pour elles : il ne définit pas une "
        "« vitesse » du GARCH réestimé chaque soir et n'établit pas une règle générale "
        "selon laquelle un estimateur plus lent serait meilleur.",
        "",
    ]

    if not options.skip_ml1:
        sections += ml1_section(options.store, options.artifacts, COMMON_PERIOD[1], frames, config)

    output.mkdir(parents=True, exist_ok=True)
    for name, frame in frames.items():
        frame.to_csv(output / f"{name}.csv")
    options.report.parent.mkdir(parents=True, exist_ok=True)
    options.report.write_text("\n".join(sections) + "\n", encoding="utf-8")
    print(f"wrote {options.report} and {len(frames)} tables in {output}")
    return 0


def ml1_section(
    store: Path,
    artifacts: Path,
    end: str,
    frames: dict[str, pd.DataFrame],
    study: Mapping[str, object],
) -> list[str]:
    """Return the section on ML1: a constant-target allocation, its sensitivities, its inputs.

    Raises
    ------
    ImportError
        If the ``ml`` extra is not installed.
    RuntimeError
        If the store read is not the one the exports of the study were made from.
    """
    # Imported on use: the script and the model need PyTorch, an optional dependency.
    import run_neural_strategy as neural

    from quant_backtester.ml.artifacts import NeuralArtifact
    from quant_backtester.ml.features import NeuralFeatureBuilder
    from quant_backtester.strategies.ml.neural_allocation import NeuralAllocationStrategy

    runner: StrategyRunner = neural.build_runner(store)
    config = neural.neural_config(42)
    artifact = NeuralArtifact.load(artifacts / "seed42_costs_x1", expected=config)
    strategy = NeuralAllocationStrategy.from_artifact(artifact)
    start, last = neural.TEST_PERIOD[0], date.fromisoformat(end)
    neural.validate_test_period(strategy, runner, start, last)
    print(f"running {neural.ML1} on {start} to {last} ...", file=sys.stderr)
    result = runner.run(strategy, neural.TRADABLE, start, last)
    require_same_provenance(study, result, same_period=False)
    held = result.weights().fillna(0.0)
    weights = tuple(
        (str(fund), round(float(weight), 4)) for fund, weight in held.mean().items() if weight > 0
    )
    control = FixedWeights(weights=weights, strategy_id="research_control_ml1")
    print("running the constant allocation of ML1 ...", file=sys.stderr)
    fixed = runner.run(control, neural.TRADABLE, start, last)
    rows = {
        neural.ML1: run_row(result),
        "↳ témoin à cible constante ("
        + ", ".join(f"{fund} {weight:.1%}" for fund, weight in weights)
        + ")": run_row(fixed),
        HELD: run_row(runner.run(neural.references()[neural.HELD], neural.TRADABLE, start, last)),
    }
    frames["ml1_constant_allocation"] = pd.DataFrame.from_dict(rows, orient="index")
    exposure = held.sum(axis=1).iloc[1:]
    share = (held[OTHER_FUND] / held.sum(axis=1)).iloc[1:]

    builder = NeuralFeatureBuilder(config)
    names = list(config.feature_names())
    inputs: dict[date, dict[str, object]] = {}
    with result.reading() as reader:
        for record in result.records():
            if record.decision_time is None:
                continue
            context = SignalContext(
                market=reader.at(record.decision_time),
                instruments=result.reader.instruments,
                calendars=result.reader.calendars,
            )
            vector = builder.build(context)
            row: dict[str, object] = {"status": vector.status.value}
            numbers = vector.values  # noqa: PD011 - a field of FeatureVector, not a frame
            if numbers is not None:
                row.update(dict(zip(names, numbers, strict=True)))
            inputs[record.session_date] = row
    features = pd.DataFrame.from_dict(inputs, orient="index").rename_axis("session_date")
    frames["ml1_inputs"] = features
    usable = int((features["status"] == "OK").sum())

    sensitivities: dict[str, dict[str, object]] = {}
    for label, arguments in (
        ("graine 42, coûts x1 (le test préinscrit)", ["--seed", "42"]),
        ("graine 43, coûts x1", ["--seed", "43"]),
        ("graine 44, coûts x1", ["--seed", "44"]),
        (RECALIBRATED, ["--seed", "42", "--cost-multiplier", "2"]),
    ):
        target = Path("results/ml1_sensitivities")
        print(f"ML1 sensitivity: {label} ...", file=sys.stderr)
        neural.main(
            [
                *arguments,
                "--output",
                str(target),
                "--store",
                str(store),
                "--artifacts",
                str(artifacts),
            ]
        )
        multiplier = "2" if "--cost-multiplier" in arguments else "1"
        written = pd.read_csv(
            target / f"seed{arguments[1]}_costs_x{multiplier}" / "summary.csv", index_col="book"
        )
        sensitivities[label] = written.loc[neural.ML1].to_dict()
        sensitivities[label]["held_sharpe"] = float(written.loc[neural.HELD, "sharpe"])
        manifest = json.loads(
            (artifacts / f"seed{arguments[1]}_costs_x{multiplier}" / "manifest.json").read_text(
                encoding="utf-8"
            )
        )
        sensitivities[label]["model"] = str(manifest["model_id"])[:12]
        sensitivities[label]["epoch"] = manifest["selected_epoch"]
    # The same frozen model, its normalisation, its weights and its epoch unchanged, with
    # only the costs of the engine doubled: what the first model becomes when it is dearer
    # to trade - another question than a recalibration under those costs.
    dearer: StrategyRunner = neural.build_runner(store, COST_STRESS)
    neural.validate_test_period(strategy, dearer, *neural.TEST_PERIOD)
    print(f"ML1 sensitivity: {FROZEN} ...", file=sys.stderr)
    frozen = {
        name: dearer.run(book, neural.TRADABLE, *neural.TEST_PERIOD)
        for name, book in {neural.ML1: strategy, **neural.references()}.items()
    }
    require_same_provenance(study, frozen[neural.ML1], same_period=False)
    same_model: dict[str, object] = dict(
        neural.summary_row(
            frozen[neural.ML1],
            frozen[neural.SA1].equity(),
            None,
            frozen[neural.HELD].equity(),
        )
    )
    same_model["held_sharpe"] = frozen[neural.HELD].report().net.sharpe_ratio
    same_model["model"] = artifact.model_id[:12]
    same_model["epoch"] = artifact.selected_epoch
    # The frozen model sits just above its recalibration, the two never under one label.
    ordered: dict[str, dict[str, object]] = {}
    for label, found in sensitivities.items():
        if label == RECALIBRATED:
            ordered[FROZEN] = same_model
        ordered[label] = found
    sensitivities = ordered
    frames["ml1_sensitivities"] = pd.DataFrame.from_dict(sensitivities, orient="index")
    below = all(
        float(row["sharpe"]) < float(row["held_sharpe"]) and float(row["quality"]) < 0.5  # type: ignore[arg-type]
        for row in sensitivities.values()
    )

    return [
        "## 7. ML1",
        "",
        f"Période de test prolongée, {start} → {last}, modèle figé `{artifact.model_id[:12]}`.",
        "",
        "### Contre une allocation constante",
        "",
        table(frames["ml1_constant_allocation"], RUN_COLUMNS, "Livre"),
        "",
        "Témoin à cible constante égale aux poids moyens de ML1 sur ces dates, avec la "
        "même bande de 3 points et les mêmes coûts : c'est le témoin exécutable que le "
        "produit « 65 % fois le rendement du fonds » ne remplaçait pas. Son exposition "
        "réalisée n'est pas exactement celle de ML1 (colonne « Expo. moy. ») : la "
        "comparaison décrit deux règles exécutables et n'isole pas la valeur du timing à "
        "exposition identique. Choisi après coup, il est descriptif.",
        "",
        f"Sur ces dates, hors la première séance, le poids total détenu par ML1 va de "
        f"{float(exposure.min()):.1%} à {float(exposure.max()):.1%} (écart-type "
        f"{float(exposure.std()):.1%}), et la part du fonds S&P 500 dans ce qui est "
        f"investi va de {float(share.min()):.1%} à {float(share.max()):.1%} (moyenne "
        f"{float(share.mean()):.1%}).",
        "",
        "### Sensibilités annoncées par l'hypothèse (période de test d'origine, "
        f"{neural.TEST_PERIOD[0]} → {neural.TEST_PERIOD[1]})",
        "",
        table(
            frames["ml1_sensitivities"],
            [
                ("model", "Modèle", "`{}`"),
                ("epoch", "Époque retenue", "{:.0f}"),
                ("quality", "Score", "{:.1%}"),
                ("net_return", "Net", "{:+.2%}"),
                ("sharpe", "Sharpe", "{:+.2f}"),
                ("held_sharpe", "Sharpe du fonds détenu", "{:+.2f}"),
                ("max_drawdown", "Perte max.", "{:.2%}"),
                ("average_exposure", "Expo. moy.", "{:.1%}"),
                ("costs_eur", "Coûts EUR", "{:,.0f}"),
            ],
            "Variante",
        ),
        "",
        "Les graines 43 et 44 et les coûts doublés sont rapportés à côté de la graine 42 "
        "et ne la remplacent pas : une graine n'est jamais choisie sur son résultat de "
        "test. Toutes les lignes portent sur la même période d'origine. Deux lignes à "
        "coûts doublés répondent à deux questions différentes. « Modèle figé » rejoue le "
        "**même artefact** que le test préinscrit - même normalisation, mêmes poids, même "
        "époque - en doublant seulement les coûts du moteur : ce que devient le modèle "
        "initial s'il coûte deux fois plus cher à exécuter. « Recalibrée » refait la "
        "calibration de `scripts/run_neural_strategy.py` sous ces coûts : sa validation "
        "peut retenir une autre époque, et c'est alors un autre modèle - ce que produit "
        "la procédure de calibration sous un autre coût. "
        + (
            "Dans chaque variante le Sharpe reste sous celui du fonds détenu et le score sous 50 %."
            if below
            else "Les variantes ne sont pas toutes sous le fonds détenu et sous 50 % : voir "
            "le tableau."
        ),
        "",
        "### Entrées du réseau",
        "",
        f"Les {len(names)} caractéristiques lues par le réseau à chacune des "
        f"{len(features)} décisions sont exportées dans `ml1_inputs.csv` (dossier des "
        f"diagnostics), avec leur statut : {usable} décisions ont un vecteur complet. "
        "Elles sont reconstruites par le `NeuralFeatureBuilder` du modèle sur un lecteur "
        "figé à l'instant de chaque décision.",
        "",
    ]


if __name__ == "__main__":
    raise SystemExit(main())
