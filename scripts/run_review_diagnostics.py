"""Measure what the review of the 2026-10-10 analyses left open.

The analyses of ``research/reports/2026-10-10`` say, strategy by strategy, what
their figures do not establish. This script measures those points, from the
exports of ``scripts/run_garch_study.py`` and from a few more runs of the same
engine on the same period, cash and costs:

- the result and the costs of each **episode** a rarely invested rule was in
  the market (``SA1``, ``SA4``, ``SA9``);
- the effect of the **delay** between a decision's close and its fill at the
  next open, for every book;
- the **attribution** of ``SA2`` and ``SA5`` against the even split of the same
  two funds - exposure, choice between the funds, execution, costs - and how
  the tilt of ``SA5`` relates to what the funds did next;
- each exposure-moving rule beside a **constant-weight control** holding the
  average weights that rule was seen to hold;
- ``SA10`` **without each of its rules**, and without its risk control;
- ``SA6`` against the EWMA control (paired bootstrap), and the EWMA rule at two
  other decays fixed here in advance (0.90 and 0.97);
- ``ML1`` beside a constant allocation, its announced sensitivities (seeds 43
  and 44, doubled costs), and the inputs its network read.

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
prices: such a split ignores that orders are filled at the open, and says so
in a residual line rather than hiding it.

The tests are in ``tests/scripts/test_run_review_diagnostics.py``.
"""

from __future__ import annotations

import argparse
import json
import math
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
from run_garch_study import EWMA, FUND, GARCH, VOL_CONTROL, sharpe_difference
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
"""The rules that move their exposure, each given a constant-weight control."""

ENSEMBLE = entry("SA10").display_name
ENSEMBLE_RULES = ("momentum", "trend", "pullback", "relative", "relief")
"""The budgeted rules of the ensemble as it is run here, each removed in turn."""

EWMA_DECAYS = (0.90, 0.97)
"""The other decays of the EWMA rule, fixed here before their runs."""

PANIC_GAP_SESSIONS = 20
"""Stays of ``SA9`` closer than this many valuations belong to one panic."""

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
    """Return the count, the share of gains and the spread of a set of stays."""
    if stays.empty:
        return {"stays": 0}
    returns = stays["net_return"].to_numpy(dtype="float64")
    return {
        "stays": len(returns),
        "gains": int((returns > 0.0).sum()),
        "losses": int((returns < 0.0).sum()),
        "share_of_gains": float((returns > 0.0).mean()),
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


def delay_effect(history: pd.DataFrame, fills: pd.DataFrame, initial_cash: float) -> dict:  # type: ignore[type-arg]
    """Return what filling at the next open, and not at the decision's close, was worth.

    Parameters
    ----------
    history : pd.DataFrame
        The book's history, for the raw closes of the funds.
    fills : pd.DataFrame
        Its executions: ``session_date``, ``instrument_id``, ``side``,
        ``market_price`` (the open it was filled at) and ``traded_value``.
    initial_cash : float
        What the run started with, to state the effect as a share of it.

    Returns
    -------
    dict
        ``orders``; ``effect_eur``, the sum over the orders of ``-sign * value
        * (open / previous close - 1)`` with ``sign`` +1 for a buy and -1 for
        a sell - positive when the overnight move helped; the same split into
        ``helped_eur`` and ``hurt_eur``; and ``effect_share`` of the initial
        cash. A first-order figure on quoted prices: it ignores that another
        fill price would have changed the quantities that followed.
    """
    total = helped = hurt = 0.0
    counted = 0
    for record in fills.to_dict(orient="records"):
        closes = history[f"close_{record['instrument_id']}"]
        before = closes.loc[closes.index < record["session_date"]].dropna()
        if before.empty:
            continue
        gap = float(record["market_price"]) / float(before.iloc[-1]) - 1.0
        sign = 1.0 if record["side"] == "BUY" else -1.0
        effect = -sign * float(record["traded_value"]) * gap
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
        ``execution`` - the book's gross equity less that close-based figure:
        fills at the open, the band, whole shares;
        ``costs`` - net less gross;
        ``book_net`` - the sum of the five; and ``basket_net``, for the
        comparison with the engine's own run of the basket.

    Notes
    -----
    The first three lines are computed on closing prices and closing weights,
    which is not how the book traded; the residual of that approximation is
    the ``execution`` line, shown rather than spread over the others.
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
        "execution": gross_log - choice,
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
        ``mean_run`` of valuations it keeps one sign for; then, for the return
        of ``first`` less that of ``second`` over the session after the
        decision (``next_1`` - partly before the fill at the open), the one
        after it (``after_fill_1``) and the five after the fill
        (``after_fill_5``), the Pearson and the Spearman correlation with the
        signal. A signal that predicted the relative return it leans on would
        show a positive one.
    """
    returns = close_returns(history, (first, second))
    relative = returns[first] - returns[second]
    value = history[signal]
    signs = np.sign(value.dropna().to_numpy(dtype="float64"))
    signs = signs[signs != 0.0]
    changes = int((signs[1:] != signs[:-1]).sum())
    horizons = {
        "next_1": relative.shift(-1),
        "after_fill_1": relative.shift(-2),
        "after_fill_5": relative.rolling(5).sum().shift(-6),
    }
    outcome: dict[str, object] = {
        "decisions": len(signs),
        "sign_changes": changes,
        "mean_run": len(signs) / (changes + 1),
    }
    for name, ahead in horizons.items():
        pair = pd.concat([value, ahead], axis=1).dropna().to_numpy(dtype="float64")
        outcome[f"pearson_{name}"] = float(np.asarray(pearsonr(pair[:, 0], pair[:, 1]))[0])
        outcome[f"spearman_{name}"] = float(np.asarray(spearmanr(pair[:, 0], pair[:, 1]))[0])
        outcome[f"pairs_{name}"] = len(pair)
    return outcome


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
    """Return the constant-weight control of a book: the weights it held on average."""
    slug = "".join(character if character.isalnum() else "_" for character in name.lower())
    return FixedWeights(weights=mean_weights(history), strategy_id=f"research_control_{slug}")


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

**Tout ce qui suit est descriptif.** Un témoin à poids constants construit sur
les poids qu'une règle a détenus en moyenne est choisi après coup : il décrit
le passé de cette règle, ce n'est pas un paramètre qu'on aurait pu fixer à
l'avance. Une ablation de `SA10` ou un autre coefficient d'EWMA est une variante
regardée après un backtest. Aucune n'est candidate : en retenir une serait une
nouvelle hypothèse, à écrire avant son run, et chacune compterait comme un
essai dans le registre qui déflate les Sharpe. Les estimations sont ponctuelles
sauf mention d'un intervalle. Rien ici n'est un échantillon vierge.
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
                ("gains", "Gagnants", "{:.0f}"),
                ("losses", "Perdants", "{:.0f}"),
                ("share_of_gains", "Part gagnante", "{:.0%}"),
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
        "Un séjour est une suite de valorisations où une position est détenue. Son "
        "résultat net va de la valorisation qui précède l'entrée à la première "
        "valorisation revenue en cash : les deux exécutions et leurs coûts sont dedans. "
        "« Composé » est le produit des séjours et retrouve le rendement net de la "
        "stratégie, puisque le cash ne rapporte rien.",
        "",
    ]
    relief = entry("SA9").display_name
    grouped = panics(frames["episodes_sa9"], histories[relief])
    frames["episodes_sa9_panics"] = grouped
    sections += [
        f"### SA9 : ses {len(frames['episodes_sa9'])} séjours regroupés en {len(grouped)} paniques",
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
        "rattachés à la même panique.",
        "",
    ]

    # 2. The delay between the decision and the fill.
    delays = {
        name: delay_effect(history, fills.loc[fills["book"] == name], initial)
        for name, history in histories.items()
    }
    frames["delay_effect"] = pd.DataFrame.from_dict(delays, orient="index")
    sections += [
        "## 2. Effet du délai entre la clôture de la décision et l'exécution à l'ouverture",
        "",
        table(
            frames["delay_effect"],
            [
                ("orders", "Ordres", "{:.0f}"),
                ("helped_eur", "Gaps favorables EUR", "{:+,.0f}"),
                ("hurt_eur", "Gaps défavorables EUR", "{:+,.0f}"),
                ("effect_eur", "Effet net EUR", "{:+,.0f}"),
                ("effect_share", "En % du capital initial", "{:+.2%}"),
            ],
            "Livre",
        ),
        "",
        "Pour chaque ordre : `-signe x montant x (ouverture / clôture précédente - 1)`, "
        "signe +1 pour un achat. Positif : le mouvement de la nuit a aidé. C'est une "
        "mesure de premier ordre sur les prix cotés ; elle ne rejoue pas les quantités "
        "qu'un autre prix d'exécution aurait données.",
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
                ("execution", "Exécution (résidu)", "{:+.4f}"),
                ("costs", "Coûts", "{:+.4f}"),
                ("book_net", "= Net de la stratégie", "{:+.4f}"),
                ("basket_net", "Panier 50/50 exécuté, net", "{:+.4f}"),
            ],
            "Stratégie",
        ),
        "",
        "Rendements logarithmiques sur la période, qui s'additionnent ligne à ligne. "
        "« Exposition totale » : ce que détenir le poids total de la veille dans le "
        "panier ajoute au panier (le timing de l'exposition). « Choix entre fonds » : ce "
        "que détenir les poids par fonds de la veille ajoute à cela. Ces trois premières "
        "colonnes sont calculées sur des clôtures, pas sur les prix d'exécution : l'écart "
        "avec la comptabilité brute du moteur est laissé visible dans « exécution ».",
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
                ("next_1", "séance suivant la décision (en partie avant l'exécution)"),
                ("after_fill_1", "première séance entière après l'exécution"),
                ("after_fill_5", "cinq séances après l'exécution"),
            )
        ],
        "",
        "Un signal qui prévoirait le rendement relatif sur lequel il mise montrerait une "
        "corrélation positive. Ces coefficients sont donnés sans intervalle.",
        "",
    ]

    # 4. More runs: constant-weight controls, ablations, other decays.
    runner = build_runner(options.store)
    config = json.loads((study / "config.json").read_text(encoding="utf-8"))
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
        print(f"running the constant-weight control of {name} ...", file=sys.stderr)
        result = runner.run(control, UNIVERSE, *COMMON_PERIOD)
        weights = ", ".join(f"{fund} {weight:.1%}" for fund, weight in control.weights)
        controls[name] = history_row(histories[name], summary.loc[name].to_dict())
        controls[f"↳ poids constants ({weights})"] = run_row(result)
    frames["constant_weight_controls"] = pd.DataFrame.from_dict(controls, orient="index")
    sections += [
        "## 4. Chaque règle à exposition variable à côté d'un témoin à poids constants",
        "",
        table(frames["constant_weight_controls"], RUN_COLUMNS, "Livre"),
        "",
        "Le témoin détient en permanence les poids que la règle a détenus en moyenne, "
        "avec la même bande de 3 points et les mêmes coûts. Une règle qui ne fait pas "
        "mieux que lui n'a rien gagné à faire varier son exposition sur cette période. "
        "Ces poids étant connus après coup, la comparaison est descriptive.",
        "",
    ]

    variants: dict[str, dict[str, object]] = {
        ENSEMBLE: history_row(histories[ENSEMBLE], summary.loc[ENSEMBLE].to_dict())
    }
    for label, strategy in ensemble_variants().items():
        print(f"running SA10 {label} ...", file=sys.stderr)
        variants[f"SA10 {label}"] = run_row(runner.run(strategy, UNIVERSE, *COMMON_PERIOD))
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
    ]

    decays: dict[str, dict[str, object]] = {
        EWMA: history_row(histories[EWMA], summary.loc[EWMA].to_dict()),
        VOL_CONTROL: history_row(histories[VOL_CONTROL], summary.loc[VOL_CONTROL].to_dict()),
    }
    for label, strategy in ewma_variants().items():
        print(f"running {label} ...", file=sys.stderr)
        decays[label] = run_row(runner.run(strategy, UNIVERSE, *COMMON_PERIOD))
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
        "meilleur coefficient, et ne doivent pas le devenir sur ce même historique.",
        "",
    ]

    if not options.skip_ml1:
        sections += ml1_section(options.store, options.artifacts, COMMON_PERIOD[1], frames)

    output.mkdir(parents=True, exist_ok=True)
    for name, frame in frames.items():
        frame.to_csv(output / f"{name}.csv")
    options.report.parent.mkdir(parents=True, exist_ok=True)
    options.report.write_text("\n".join(sections) + "\n", encoding="utf-8")
    print(f"wrote {options.report} and {len(frames)} tables in {output}")
    return 0


def ml1_section(
    store: Path, artifacts: Path, end: str, frames: dict[str, pd.DataFrame]
) -> list[str]:
    """Return the section on ML1: a constant allocation, its sensitivities, its inputs.

    Raises
    ------
    ImportError
        If the ``ml`` extra is not installed.
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
    held = result.weights().fillna(0.0)
    weights = tuple(
        (str(fund), round(float(weight), 4)) for fund, weight in held.mean().items() if weight > 0
    )
    control = FixedWeights(weights=weights, strategy_id="research_control_ml1")
    print("running the constant allocation of ML1 ...", file=sys.stderr)
    fixed = runner.run(control, neural.TRADABLE, start, last)
    rows = {
        neural.ML1: run_row(result),
        "↳ allocation constante ("
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
        ("graine 42, coûts x2", ["--seed", "42", "--cost-multiplier", "2"]),
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
    frames["ml1_sensitivities"] = pd.DataFrame.from_dict(sensitivities, orient="index")

    return [
        "## 7. ML1",
        "",
        f"Période de test prolongée, {start} → {last}, modèle figé `{artifact.model_id[:12]}`.",
        "",
        "### Contre une allocation constante",
        "",
        table(frames["ml1_constant_allocation"], RUN_COLUMNS, "Livre"),
        "",
        "L'allocation constante détient les poids moyens de ML1 sur ces dates, avec la "
        "même bande et les mêmes coûts : c'est le témoin exécutable que le produit "
        "« 65 % fois le rendement du fonds » ne remplaçait pas. Choisie après coup, elle est "
        "descriptive.",
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
        "test. Chaque variante est calibrée par `scripts/run_neural_strategy.py` avec "
        "son propre artefact, puis testée une fois sur la période d'origine.",
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
