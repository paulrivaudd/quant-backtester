"""Write one results-and-analysis report per strategy, from the exports of the SA11 study.

Each catalogued strategy that was run gets a Markdown file
``strategy<CODE>_ResultsAndAnalysis_<DDMMYYYY>.md`` with three sections:

1. every global indicator, beside the fund bought and held;
2. an analysis - the measured facts of its worst and best stretches, then the
   strengths, the weaknesses and the market situations that hurt it most;
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
from datetime import date
from pathlib import Path

import pandas as pd
from run_etf_strategies_comparison import (
    HELD,
    closes_of,
    quality_details,
    slug,
)
from run_garch_study import EWMA, FUND, summary_frame, yearly_frame

from quant_backtester.analytics.curves import Book
from quant_backtester.strategies.catalogue import CATALOGUE

OTHER_FUND = "ETF_SP500_PEA"
"""The second fund some strategies hold."""

WINDOW_SESSIONS = 63
"""Length of the rolling window the best and worst stretches are also measured on: a quarter."""

GLOBAL_ROWS: tuple[tuple[str, str, str], ...] = (
    ("rank", "Rang au classement commun (QUALITY_V1)", "{:.0f}"),
    ("quality", "Score de qualité QUALITY_V1 (0-100 %)", "{:.1%}"),
    ("block_market", "- bloc marché (IR et alpha contre le fonds détenu)", "{:.2f}"),
    ("block_significance", "- bloc significativité (Sharpe déflaté)", "{:.2f}"),
    ("block_risk", "- bloc risque (drawdown relatif)", "{:.2f}"),
    ("block_robustness", "- bloc robustesse (sous-périodes, coûts doublés)", "{:.2f}"),
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
    ("net_return_costs_x2", "Rendement net, coûts doublés (second run réel)", "{:+.2%}"),
    ("sharpe_costs_x2", "Sharpe net, coûts doublés (second run réel)", "{:+.2f}"),
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
    return {
        "Période": label,
        "Du": episode.start,
        "Au": episode.end,
        "Séances": len(inside),
        "Stratégie": change_over(pd.Series(history["net_equity"]), episode),
        f"{FUND} (clôture)": change_over(pd.Series(history[f"close_{FUND}"]), episode),
        "Fonds détenu (net)": change_over(market, episode),
        "Exposition moyenne": float(exposure.mean()),
        "Exposition min.": float(exposure.min()),
        "Exposition max.": float(exposure.max()),
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
        largest rise - with the book's return, the fund's, and the exposure
        held.
    """
    equity = pd.Series(history["net_equity"])
    relative = pd.Series(equity / market)
    stretches = (
        ("Plus forte baisse de la stratégie", deepest_fall(equity)),
        ("Plus forte hausse de la stratégie", largest_rise(equity)),
        (
            f"Pires {WINDOW_SESSIONS} séances de la stratégie",
            extreme_window(equity, WINDOW_SESSIONS, best=False),
        ),
        (
            f"Meilleures {WINDOW_SESSIONS} séances de la stratégie",
            extreme_window(equity, WINDOW_SESSIONS, best=True),
        ),
        ("Plus fort retard sur le fonds détenu", deepest_fall(relative)),
        ("Plus forte avance sur le fonds détenu", largest_rise(relative)),
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
        "Exposition moyenne": "{:.0%}",
        "Exposition min.": "{:.0%}",
        "Exposition max.": "{:.0%}",
    }
    columns = list(facts.columns)
    lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    for record in facts.to_dict(orient="records"):
        cells = [_cell(record[column], patterns.get(column, "{}")) for column in columns]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def calendar_markdown(
    equity: pd.Series,
    market: pd.Series,
    yearly: pd.DataFrame,
    name: str,  # type: ignore[type-arg]
) -> str:
    """Return the yearly returns beside the fund's, and the best and worst months."""
    lines = ["| Année | Stratégie | Fonds détenu | Séances |", "|---|---:|---:|---:|"]
    for year in yearly.columns:
        lines.append(
            f"| {year} | {_cell(yearly.loc[name, year], '{:+.2%}')} | "
            f"{_cell(yearly.loc[HELD, year], '{:+.2%}')} | "
            f"{_cell(yearly.loc['sessions', year], '{:.0f}')} |"
        )
    months, reference = monthly_returns(equity), monthly_returns(market)
    worst, best = months.idxmin(), months.idxmax()
    lines += [
        "",
        f"Pire mois : **{worst}** ({months[worst]:+.2%}, fonds détenu {reference[worst]:+.2%}). "
        f"Meilleur mois : **{best}** ({months[best]:+.2%}, fonds détenu {reference[best]:+.2%}). "
        f"Mois positifs : {int((months > 0).sum())} sur {len(months)}.",
    ]
    return "\n".join(lines)


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
) -> str:
    """Return the whole report of one strategy: indicators, analysis, then history."""
    facts = facts_table(history, market)
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
            "Le score QUALITY_V1 est un indice composite (marché 30 %, significativité 25 %, "
            "risque 15 %, robustesse 20 %, implémentation 10 %), pas une probabilité de gain. "
            "Le fonds détenu est l'étalon du score et n'est donc pas noté. « n/a » : la "
            "mesure n'existe pas pour cette colonne ; elle n'est jamais remplacée par zéro.",
            "",
            "## 2. Analyse",
            "",
            "### Faits mesurés",
            "",
            facts_markdown(facts),
            "",
            "Chaque ligne va de la valeur de la séance « Du » à celle de la séance « Au ». "
            "L'exposition est la part de l'actif net détenue en fonds, le reste étant du cash "
            "non rémunéré.",
            "",
            calendar_markdown(pd.Series(history["net_equity"]), market, yearly, name),
            "",
            commentary_markdown(notes),
            "",
            "## 3. Historique : sous-jacent, indicateurs utilisés et valeur de la stratégie",
            "",
            "Une ligne par séance. Les indicateurs sont ceux que la stratégie a lus à sa "
            "décision du soir (23:00 Paris), recalculés par ses propres signaux sur le magasin "
            "tel que le run l'a lu ; l'ordre qui en découle est exécuté à l'ouverture suivante. "
            "Une case vide est un indicateur sans valeur ce jour-là.",
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
        code = names.get(str(name))
        if code is None and name != EWMA:
            continue  # the fund held and the even split are references, not strategies
        code = "EWMA94control" if code is None else code
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
