"""Write one results-and-analysis report per strategy, from the exports of the SA11 study.

Each catalogued strategy that was run gets a Markdown file
``strategy<CODE>_ResultsAndAnalysis_<DDMMYYYY>.md``; so do the control of
``SA11`` and the two references - the fund held and the even split - since a
strategy holding both funds cannot be read without the second. Three sections:

1. every global indicator, beside the fund bought and held;
2. an analysis - the measured facts of its worst and best stretches, its
   drawdowns with the date each peak was reached again, its years and months,
   then the strengths, the weaknesses and the market situations that hurt it
   most;
3. the history: the closes of the funds, the signals the strategy read, the
   weights it targeted and held, and its value, session by session.

From the repository root, after ``scripts/run_garch_study.py``:

    uv run python scripts/write_strategy_reports.py \
        --study results/garch_study --output research/reports/2026-10-10

Nothing here computes a performance of its own for the ``SA`` strategies:
every figure is read from the study's exports, so a report cannot disagree
with the table it comes from. The measured facts of the analysis (dates and
sizes of the falls and rises, exposure held through them) are computed here
from those exports. The written commentary is not computed: it is read from
``commentary.toml`` in the output folder, by strategy code, and a strategy
without one says so instead of inventing a text.

``ML1`` is not in the study: its information stops at 2024-12-31, so it is run
here, once, on its test period extended to the study's last session, beside
the fund held and ``SA1`` over the same sessions (``--skip-ml1`` leaves it
out; it needs the ``ml`` extra and its calibrated artifact). Its figures are
on another period than the others' and are not comparable with them.

The tests are in ``tests/scripts/test_write_strategy_reports.py``.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from run_etf_strategies_comparison import (
    HELD,
    SPLIT,
    closes_of,
    quality_details,
    slug,
)
from run_garch_study import EWMA, FUND, summary_frame, yearly_frame

from quant_backtester.analytics.curves import Book
from quant_backtester.strategies.catalogue import CATALOGUE

UNCATALOGUED = {EWMA: "EWMA94control", HELD: "REF_WorldBuyHold", SPLIT: "REF_5050Rebalanced"}
"""The code, in a file name, of each book that has no catalogue code: the control of
``SA11`` and the two references every strategy is read against."""

OTHER_FUND = "ETF_SP500_PEA"
"""The second fund some strategies hold."""

MONTH_TOLERANCE = 1e-12
"""Monthly return at or under which, in absolute value, a month is counted as unchanged."""

WINDOW_SESSIONS = 63
"""Length of the rolling window the best and worst stretches are also measured on: a quarter."""

GLOBAL_ROWS: tuple[tuple[str, str, str], ...] = (
    ("rank", "Rang au classement commun (QUALITY_V1)", "{:.0f}"),
    ("quality", "Score de qualité QUALITY_V1 (0-100 %)", "{:.1%}"),
    ("block_market", "- bloc marché (IR et alpha contre le fonds détenu)", "{:.2f}"),
    ("block_significance", "- bloc significativité (Sharpe déflaté)", "{:.2f}"),
    ("block_risk", "- bloc risque (drawdown relatif)", "{:.2f}"),
    ("block_robustness", "- bloc robustesse (sous-périodes ; stress approché des coûts)", "{:.2f}"),
    ("block_implementation", "- bloc implémentation (poids des coûts)", "{:.2f}"),
    ("net_return", "Rendement net total", "{:+.2%}"),
    ("gross_return", "Rendement brut total (mêmes ordres, sans coûts)", "{:+.2%}"),
    ("annualised_return", "Rendement net annualisé", "{:+.2%}"),
    ("volatility", "Volatilité annualisée", "{:.2%}"),
    ("sharpe", "Ratio de Sharpe net (taux sans risque 0)", "{:+.2f}"),
    ("max_drawdown", "Perte maximale (max drawdown)", "{:.2%}"),
    ("alpha_vs_market", "Alpha annualisé contre le fonds détenu", "{:+.2%}"),
    ("beta_vs_market", "Bêta contre le fonds détenu", "{:.2f}"),
    ("information_ratio_vs_market", "Ratio d'information contre le fonds détenu", "{:+.2f}"),
    ("alpha_vs_benchmark", "Alpha annualisé contre SA1 (MA20)", "{:+.2%}"),
    ("beta_vs_benchmark", "Bêta contre SA1 (MA20)", "{:.2f}"),
    ("average_exposure", "Exposition moyenne (part investie)", "{:.1%}"),
    ("fills", "Ordres exécutés", "{:.0f}"),
    ("costs_eur", "Coûts payés (EUR)", "{:,.0f}"),
    ("turnover_per_year", "Rotation annuelle (multiple de l'actif moyen)", "{:.2f}"),
    ("net_return_first_two_thirds", "Rendement net, deux premiers tiers", "{:+.2%}"),
    ("net_return_last_third", "Rendement net, dernier tiers", "{:+.2%}"),
    ("net_return_costs_x2", "Rendement net, second run réel à coûts doublés", "{:+.2%}"),
    ("sharpe_costs_x2", "Sharpe net, second run réel à coûts doublés", "{:+.2f}"),
)
"""The global indicators, in order: column of the study, French label, format."""


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
        "| Rang | Sommet | Creux | Profondeur | Retour au sommet | Jours calendaires |",
        "|---:|---|---|---:|---|---:|",
    ]
    for rank, episode in enumerate(sorted(found, key=lambda item: item.depth)[:episodes], 1):
        end = last_day if episode.recovery is None else episode.recovery
        back = f"non récupéré au {last_day}" if episode.recovery is None else str(episode.recovery)
        length = f"{(end - episode.peak).days}" + (
            " (en cours)" if episode.recovery is None else ""
        )
        lines.append(
            f"| {rank} | {episode.peak} | {episode.trough} | {episode.depth:.2%} | {back} | "
            f"{length} |"
        )
    if not found:
        lines.append("| - | - | - | 0.00% | aucune baisse sous un sommet | 0 |")
    peak = max(value for _, value in values)
    current = values[-1][1] / peak - 1.0
    lines += ["", f"Drawdown au {last_day} : **{current:.2%}** sous le plus haut de la période."]
    if found:
        longest = max(found, key=lambda item: ((item.recovery or last_day) - item.peak).days)
        end = longest.recovery or last_day
        state = "en cours" if longest.recovery is None else "récupérée"
        lines.append(
            f"Plus longue période sous un sommet : **{(end - longest.peak).days} jours "
            f"calendaires**, du {longest.peak} au {end} ({state}, creux à {longest.depth:.2%})."
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
        "Période": label,
        "Du": episode.start,
        "Au": episode.end,
        "Valorisations": len(inside),
        "Rendements": len(inside) - 1,
        "Stratégie": own,
        f"{FUND} (clôture)": change_over(pd.Series(history[f"close_{FUND}"]), episode),
        "Fonds détenu (net)": held,
        "Écart relatif": (1.0 + own) / (1.0 + held) - 1.0,
        "Poids de clôture moyen": float(exposure.mean()),
        "Poids de clôture min.": float(exposure.min()),
        "Poids de clôture max.": float(exposure.max()),
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
        ("Plus forte baisse (sommet → creux)", deepest_fall(equity)),
        ("Plus forte hausse (creux → sommet ultérieur, durée libre)", largest_rise(equity)),
        (
            f"Pires {WINDOW_SESSIONS} rendements consécutifs",
            extreme_window(equity, WINDOW_SESSIONS, best=False),
        ),
        (
            f"Meilleurs {WINDOW_SESSIONS} rendements consécutifs",
            extreme_window(equity, WINDOW_SESSIONS, best=True),
        ),
        ("Plus fort retard relatif sur le fonds détenu", deepest_fall(relative)),
        ("Plus forte avance relative sur le fonds détenu", largest_rise(relative)),
        ("Plus forte baisse du fonds détenu", deepest_fall(market)),
        ("Plus forte hausse du fonds détenu", largest_rise(market)),
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
        "| Indicateur | Stratégie | Fonds détenu (buy & hold ETF_WORLD) |",
        "|---|---:|---:|",
        f"| Période mesurée | {own['first_session']} → {own['last_session']} "
        f"({int(float(own['sessions']))} séances) | idem |",  # type: ignore[arg-type]
    ]
    for key, label, pattern in GLOBAL_ROWS:
        lines.append(
            f"| {label} | {_cell(own.get(key), pattern)} | {_cell(other.get(key), pattern)} |"
        )
    diagnostics = own.get("diagnostics")
    if isinstance(diagnostics, str) and diagnostics:
        lines.append(f"| Diagnostics du score | {diagnostics} | |")
    return "\n".join(lines)


def facts_markdown(facts: pd.DataFrame) -> str:
    """Return the table of facts as Markdown."""
    patterns = {
        "Stratégie": "{:+.2%}",
        f"{FUND} (clôture)": "{:+.2%}",
        "Fonds détenu (net)": "{:+.2%}",
        "Écart relatif": "{:+.2%}",
        "Poids de clôture moyen": "{:.0%}",
        "Poids de clôture min.": "{:.0%}",
        "Poids de clôture max.": "{:.0%}",
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
    head = "| Année | Stratégie | Fonds détenu |" + (" 50/50 rebalancé |" if shown else "")
    lines = [head + " Séances |", "|---|---:|---:|" + ("---:|" if shown else "") + "---:|"]
    for year in yearly.columns:
        label = str(year)
        if int(year) == first.year and (first.month, first.day) > (1, 7):
            label += f" (partielle, depuis le {first})"
        if int(year) == last.year and (last.month, last.day) < (12, 24):
            label += f" (partielle, au {last})"
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
        partial.append(f"{first.year}-{first.month:02d} commence le {first}")
    if (last + timedelta(days=4)).month == last.month:
        partial.append(f"{last.year}-{last.month:02d} s'arrête au {last}")
    lines += [
        "",
        f"Mois : **{positive} positifs, {negative} négatifs, "
        f"{len(months) - positive - negative} sans variation** sur {len(months)}"
        + (f" (mois incomplets : {' ; '.join(partial)})" if partial else "")
        + f". Pire mois : **{worst}** ({months[worst]:+.2%}, fonds détenu "
        f"{reference[worst]:+.2%}). Meilleur mois : **{best}** ({months[best]:+.2%}, fonds "
        f"détenu {reference[best]:+.2%}).",
    ]
    return "\n".join(lines)


def activity_markdown(history: pd.DataFrame) -> str:
    """Return how often the book held anything at a close, and between which weights."""
    exposure = [float(value) for value in exposure_of(history)]
    invested = [value for value in exposure if value > 0.0]
    if not invested:
        return (
            f"Activité : aucune position détenue à une clôture sur {len(exposure)} valorisations."
        )
    return (
        f"Activité : une position est détenue à la clôture de **{len(invested)} valorisations "
        f"sur {len(exposure)}** ; le poids total détenu y va de {min(invested):.1%} à "
        f"{max(invested):.1%} (moyenne sur toutes les valorisations : "
        f"{math.fsum(exposure) / len(exposure):.1%})."
    )


def history_markdown(history: pd.DataFrame) -> str:
    """Return the history as one Markdown table, a row per session.

    The closes of the funds, each signal the strategy read, the weights
    targeted and held, and the net value. A signal without a value at a
    decision is left empty. The second fund's close is shown only when the
    strategy reads or holds it.
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
        f"close_{FUND}": f"Clôture {FUND}",
        f"close_{OTHER_FUND}": f"Clôture {OTHER_FUND}",
        "net_equity": "Valeur nette (EUR)",
    }

    def heading(column: str) -> str:
        if column in headings:
            return headings[column]
        if column.startswith("target_"):
            return f"Poids cible {column.removeprefix('target_')}"
        if column.startswith("held_"):
            return f"Poids détenu {column.removeprefix('held_')}"
        if column.startswith("proposed_"):
            return f"Poids proposé {column.removeprefix('proposed_')}"
        return f"`{column}`"

    def pattern(column: str) -> str:
        if column.startswith("close_"):
            return "{:.2f}"
        if column == "net_equity":
            return "{:,.2f}"
        if column.startswith(("target_", "held_", "proposed_")):
            return "{:.1%}"
        return "{:.4f}"

    lines = [
        "| Séance | " + " | ".join(heading(column) for column in columns) + " |",
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
            "_Aucun commentaire n'a été rédigé pour cette stratégie : seuls les faits "
            "mesurés ci-dessus sont disponibles._"
        )
    sections = (
        ("summary", "En résumé", False),
        ("strengths", "Points forts", True),
        ("weaknesses", "Points faibles", True),
        ("worst", "Ce qui s'est passé pendant la période où la stratégie a le plus perdu", False),
        ("best", "Ce qui s'est passé pendant la période où la stratégie a le plus gagné", False),
        ("risks", "Situations de marché les plus risquées pour cette stratégie", True),
        ("measured", "Mesures complémentaires (voir diagnostics_10102026.md)", True),
        ("to_test", "Ce que ces résultats n'établissent pas, et ce qui reste à mesurer", True),
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


SCORE_NOTE = (
    "Le score QUALITY_V1 est une **moyenne géométrique pondérée** de cinq blocs bornés entre 0 "
    "et 1 (marché 30 %, significativité 25 %, risque 15 %, robustesse 20 %, implémentation "
    "10 %) : un seul bloc à zéro donne un score nul. Un score nul n'est donc ni une probabilité "
    "de gain nulle, ni une égalité économique entre deux stratégies ; le bloc implémentation, "
    "par exemple, tombe à zéro dès que les coûts atteignent 30 % du gain brut. Le bloc "
    "robustesse contient un **stress approché** des coûts, `net - (brut - net)` sur les mêmes "
    "ordres ; les deux dernières lignes du tableau viennent d'un **second run réel** à coûts "
    "doublés, où les quantités et la trajectoire changent, et n'entrent pas dans le score. Le "
    "score est déflaté par les essais de cette étude seulement, pas par la recherche "
    "antérieure : le classement est exploratoire, et un écart de quelques points entre deux "
    "scores n'est pas un test de supériorité. Les alphas sont des estimations ponctuelles sans "
    "intervalle, avec un taux sans risque nul ; l'alpha contre SA1 compare à une règle active, "
    "ce n'est pas un alpha de marché. Le fonds détenu est l'étalon du score et n'est pas "
    "noté. « n/a » : la mesure n'existe pas ; elle n'est jamais remplacée par zéro."
)
"""What the score and the alphas of the first table do and do not say."""

READING_NOTE = (
    "Chaque ligne va de la valeur de la séance « Du » à celle de la séance « Au » : N "
    "valorisations, donc N - 1 rendements. « Plus forte hausse » est la plus grande hausse "
    "d'un creux à un sommet ultérieur, de durée libre : ce n'est ni une position ni un trade. "
    "Les deux périodes relatives sont choisies sur le rapport de la stratégie au fonds "
    "détenu, dont l'« écart relatif » `(1 + stratégie) / (1 + fonds) - 1` est la variation. "
    "Le « poids de clôture » est la part de l'actif net détenue en fonds à la valorisation du "
    "soir, le reste étant du cash non rémunéré : il a pu dériver avec les cours, et le "
    "multiplier par le rendement du fonds ne reconstitue pas le résultat. Une décision prise "
    "le soir de t (signal et poids cible de la ligne t) est exécutée à l'ouverture de t + 1 "
    "et n'apparaît dans le poids détenu qu'à la ligne t + 1."
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
    """
    equity = pd.Series(history["net_equity"])
    return "\n".join(
        [
            f"# {name} — résultats et analyse",
            "",
            *provenance,
            "",
            "## 1. Indicateurs de résultat globaux",
            "",
            global_table(row, market_row, stressed),
            "",
            SCORE_NOTE,
            "",
            "## 2. Analyse",
            "",
            "### Faits mesurés",
            "",
            facts_markdown(facts_table(history, market)),
            "",
            READING_NOTE,
            "",
            "### Baisses sous un sommet et retour à ce sommet",
            "",
            drawdown_markdown(equity),
            "",
            "### Par année et par mois",
            "",
            calendar_markdown(equity, market, yearly, name, control),
            "",
            activity_markdown(history),
            "",
            commentary_markdown(notes),
            "",
            "## 3. Historique : sous-jacent, indicateurs utilisés et valeur de la stratégie",
            "",
            "Une ligne par séance. Les indicateurs sont ceux que la stratégie a lus à sa "
            "décision du soir (23:00 Paris), recalculés par ses propres signaux sur le magasin "
            "tel que le run l'a lu. Le poids cible de la ligne t est décidé ce soir-là et "
            "exécuté à l'ouverture de t + 1 ; le poids détenu de la ligne t est celui du "
            "portefeuille à la valorisation de t. Une case vide est un indicateur sans valeur "
            "ce jour-là. Les ordres, les prix d'exécution et les coûts de chaque séance ne "
            "sont pas dans ce tableau : ils sont dans `fills.csv` de l'étude.",
            *([] if history_note is None else ["", history_note]),
            "",
            history_markdown(history),
            "",
        ]
    )


def file_name(code: str, stamp: str) -> str:
    """Return the name of a strategy's report: ``strategySA11_ResultsAndAnalysis_10102026.md``."""
    return f"strategy{code}_ResultsAndAnalysis_{stamp}.md"


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


def study_provenance(config: Mapping[str, object]) -> list[str]:
    """Return the lines saying what a report of the study was produced from."""
    source = config["source"]
    period = config["period"]
    assert isinstance(source, dict) and isinstance(period, dict)
    return [
        f"Période commune {period['start']} → {period['end']} · capital 100 000 EUR · "
        "commission 5 pb (minimum 1 EUR), demi-spread 3 pb, slippage 2 pb · quantités "
        "fixées à la décision, exécution à l'ouverture suivante · cash non rémunéré · "
        "252 séances par an.",
        "",
        f"Source : commit `{str(source.get('git_commit'))[:12]}` ({source.get('source_state')}), "
        f"magasin `{str(config['data_state'])[:12]}`, données à jour au {period['end']}. "
        "Évaluation rétrospective : l'historique d'ETF_WORLD a déjà été regardé dans les "
        "exercices précédents, ce n'est pas un échantillon vierge.",
    ]


def ml1_report(
    store: Path, artifacts: Path, end: str, stamp: str, notes: Mapping[str, object] | None
) -> tuple[str, str]:
    """Run ML1 on its test period up to ``end`` and return its file name and report.

    Raises
    ------
    ImportError
        If the ``ml`` extra is not installed.
    ArtifactError
        If the calibrated artifact of seed 42 is not in ``artifacts``.
    """
    # Imported on use: the script and the model need PyTorch, an optional dependency.
    import run_neural_strategy as neural

    from quant_backtester.ml.artifacts import NeuralArtifact
    from quant_backtester.strategies.ml.neural_allocation import NeuralAllocationStrategy

    runner = neural.build_runner(store)
    artifact = NeuralArtifact.load(artifacts / "seed42_costs_x1", expected=neural.neural_config(42))
    strategy = NeuralAllocationStrategy.from_artifact(artifact)
    start, last = neural.TEST_PERIOD[0], date.fromisoformat(end)
    neural.validate_test_period(strategy, runner, start, last)
    books = {neural.ML1: strategy, **neural.references()}
    results = {}
    for name, book in books.items():
        print(f"running {name} on {start} to {last} ...", file=sys.stderr)
        results[name] = runner.run(book, neural.TRADABLE, start, last)
    net = {name: result.equity() for name, result in results.items()}
    gross = {name: result.equity(Book.GROSS) for name, result in results.items()}
    # One trial, as its hypothesis states: the frozen model of seed 42.
    kept = {name: net[name] for name in (neural.ML1, HELD)}
    details = {
        **dict.fromkeys(results),
        **quality_details(
            kept, {name: gross[name] for name in kept}, trials=1, trial_sharpe_std=0.0
        ),
    }
    summary = summary_frame(results, details)
    decisions = neural.neural_decisions(results[neural.ML1], strategy).set_index("session_date")
    closes = closes_of(results[neural.ML1])
    parts = [
        pd.DataFrame({f"close_{fund}": series for fund, series in closes.items()}),
        decisions[[column for column in decisions if column.startswith("proposed_")]],
        results[neural.ML1].target_weights().add_prefix("target_"),
        results[neural.ML1].weights().add_prefix("held_"),
        net[neural.ML1].rename("net_equity"),
    ]
    history = pd.concat(parts, axis=1).reindex(net[neural.ML1].index)
    source = results[neural.ML1].source.definition()
    provenance = [
        f"Période de test {summary['first_session'].iloc[0]} → {summary['last_session'].iloc[0]} "
        "(après la date limite d'information du modèle, "
        f"{artifact.information_cutoff.date().isoformat()}) · modèle figé "
        f"`{artifact.model_id[:12]}` (graine 42) · mêmes capital, coûts et conventions que les "
        "autres stratégies.",
        "",
        f"Source : commit `{str(source.get('git_commit'))[:12]}` ({source.get('source_state')}), "
        f"magasin `{results[neural.ML1].data_state.digest[:12]}`. **Période différente de celle "
        "des stratégies SA** (qui commence en 2021) : ces chiffres ne se comparent pas aux "
        "leurs, et ML1 n'a pas de rang dans le classement commun. Le test a déjà été lu une "
        "fois le 2026-10-04 jusqu'au 2026-09-30 ; ce run le prolonge avec le même modèle. Le "
        "score est déflaté pour un seul essai.",
    ]
    # Alone in its table, on its own period: it has no place in the common ranking.
    own = {**summary.loc[neural.ML1].to_dict(), "rank": None}
    text = report(
        neural.ML1,
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
            "Pour ML1, les colonnes « poids proposé » sont la **sortie** du réseau, pas ses "
            "entrées : les caractéristiques qu'il lit (rendements, moyennes, volatilités des "
            "deux fonds et du VIX sur 100 séances) ne sont pas dans ce tableau."
        ),
    )
    return file_name("ML1", stamp), text


def main(arguments: Sequence[str] | None = None) -> int:
    """Write the report of every catalogued strategy the study ran, and of ML1."""
    parser = argparse.ArgumentParser(description="Write one report per strategy.")
    parser.add_argument("--study", type=Path, default=Path("results/garch_study"))
    parser.add_argument("--output", type=Path, default=Path("research/reports/2026-10-10"))
    parser.add_argument("--stamp", default="10102026", help="date in the file names, DDMMYYYY")
    parser.add_argument("--store", type=Path, default=Path("market_data"))
    parser.add_argument("--artifacts", type=Path, default=Path("artifacts/neural/world_vix"))
    parser.add_argument("--skip-ml1", action="store_true")
    options = parser.parse_args(arguments)

    inputs = study_inputs(options.study)
    summary, stressed, yearly = inputs["summary"], inputs["stressed"], inputs["yearly"]
    config = inputs["config"]
    assert isinstance(summary, pd.DataFrame) and isinstance(stressed, pd.DataFrame)
    assert isinstance(yearly, pd.DataFrame) and isinstance(config, dict)
    commentary_path = options.output / "commentary.toml"
    commentary: dict[str, object] = {}
    if commentary_path.exists():
        commentary = tomllib.loads(commentary_path.read_text(encoding="utf-8"))
    market = pd.Series(read_history(options.study, HELD)["net_equity"])
    names = {item.display_name: item.code for item in CATALOGUE}
    written: dict[str, str] = {}
    for name in summary.index:
        # The control and the two references carry no catalogue code: a name of their own.
        code = names.get(str(name)) or UNCATALOGUED[str(name)]
        notes = commentary.get(code)
        written[file_name(code, options.stamp)] = report(
            str(name),
            summary.loc[name].to_dict(),
            summary.loc[HELD].to_dict(),
            stressed.loc[name].to_dict(),
            read_history(options.study, str(name)),
            market,
            yearly,
            notes if isinstance(notes, dict) else None,
            study_provenance(config),
            control=SPLIT,
        )
    if not options.skip_ml1:
        notes = commentary.get("ML1")
        period = config["period"]
        assert isinstance(period, dict)
        target, text = ml1_report(
            options.store,
            options.artifacts,
            str(period["end"]),
            options.stamp,
            notes if isinstance(notes, dict) else None,
        )
        written[target] = text
    options.output.mkdir(parents=True, exist_ok=True)
    for target, text in written.items():
        (options.output / target).write_text(text, encoding="utf-8")
        print(f"wrote {options.output / target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
