"""Render the frozen second SA15 study without constructing a runner or trading.

The class defaults are only a prototype. This report uses the complete frozen
parameters in the saved final strategy definition and verifies its fingerprint.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter

from quant_backtester.analytics.benchmark_comparison import alpha_vs_benchmark
from quant_backtester.analytics.config import AnalyticsConfig
from quant_backtester.analytics.quality import deflated_sharpe_probability, session_sharpe

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "results/SA15_GPT-6.1_R2"
R1_OUTPUT = ROOT / "results/SA15_GPT-6.1"
BOOK = "SA15_GPT-6.1_R2"
BENCHMARK = "SP500_buy_hold"
REFERENCES = (BENCHMARK, "Nasdaq_buy_hold", "static_50_50")
PERIODS = ("development", "validation", "final", "full")
ANALYTICS = AnalyticsConfig(sessions_per_year=252, risk_free_rate=0.0, minimum_sessions=60)
LABELS = {
    BOOK: "SA15 retenue",
    BENCHMARK: "S&P 500 conserve",
    "Nasdaq_buy_hold": "Nasdaq conserve",
    "static_50_50": "50/50 initial S&P 500/Nasdaq conserve",
}


def read_json(path: Path) -> dict:
    """Read one saved research artifact; never infer missing financial results."""
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: object) -> None:
    """Write finite, readable diagnostics without modifying source artifacts."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def percent(value: object) -> str:
    """Format a fractional statistic, making unavailable estimates explicit."""
    if value is None or not math.isfinite(float(value)):
        return "n.d."
    return f"{float(value) * 100:.2f} %"


def number(value: object, digits: int = 2) -> str:
    """Format one optional finite number."""
    if value is None or not math.isfinite(float(value)):
        return "n.d."
    return f"{float(value):.{digits}f}"


def markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    """Render small tables while preventing free-text reasons from breaking cells."""

    def clean(cell: object) -> str:
        return str(cell).replace("|", "/").replace("\n", " ")

    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(clean(cell) for cell in row) + " |" for row in rows)
    return "\n".join(lines)


def load_equity(path: Path) -> pd.Series:
    """Load a saved curve with Timestamp dates retained for plots and calendar years."""
    frame = pd.read_csv(path, index_col=0, parse_dates=True)
    if frame.shape[1] != 1 or frame.empty:
        raise ValueError(f"expected one nonempty saved equity curve: {path}")
    curve = frame.iloc[:, 0].astype(float)
    if not isinstance(curve.index, pd.DatetimeIndex) or curve.index.has_duplicates:
        raise ValueError(f"invalid saved equity dates: {path}")
    if not curve.index.is_monotonic_increasing:
        raise ValueError(f"saved equity dates are out of order: {path}")
    if not np.isfinite(curve.to_numpy()).all() or (curve <= 0).any():
        raise ValueError(f"saved equity values must be finite and positive: {path}")
    return curve


def analytics_copy(curve: pd.Series) -> pd.Series:
    """Convert a copy to the analytics contract of Python datetime.date sessions."""
    copied = curve.copy()
    copied.index = pd.Index(pd.DatetimeIndex(curve.index).date, dtype="object", name="session_date")
    return copied


def frozen_selection(output: Path) -> tuple[dict, dict, dict]:
    """Verify the candidate and complete final parameters without instantiating defaults."""
    selected = read_json(output / "selected.json")
    spec = selected["candidate"]
    trial = spec["number"]
    if isinstance(trial, bool) or not isinstance(trial, int) or not 11 <= trial <= 20:
        raise ValueError("round two requires a frozen trial number from 11 to 20")
    if read_json(output / f"trial_{trial:02d}/candidate.json") != spec:
        raise ValueError("candidate differs from the frozen selection")
    definition = read_json(output / "final" / BOOK / "strategy.json")
    canonical = json.dumps(definition, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if digest != selected["fingerprint"] or definition["parameters"] != selected["parameters"]:
        raise ValueError(
            "final strategy parameters or fingerprint differ from the frozen selection"
        )
    configuration = read_json(output / "final" / BOOK / "configuration.json")
    return selected, definition, configuration


def result_folder(output: Path, period: str, name: str, trial: int) -> Path:
    """Locate existing runs in the runner's declared round-two layout."""
    if period == "full":
        return output / "full" / name
    if name == BOOK:
        return (
            output / "final" / name if period == "final" else output / f"trial_{trial:02d}" / period
        )
    return output / "references" / period / name


def operational_metrics(folder: Path, curve: pd.Series, parameters: dict) -> dict:
    """Count actual trading dates and expose the realized core/satellite allocation.

    One intervention date may contain several orders. Reference runs saved
    without fills or weights have unavailable dates/exposures, never invented
    zeros. Annualization uses elapsed calendar time.
    """
    years = max((curve.index[-1] - curve.index[0]).days / 365.25, 1 / 252)
    metrics = read_json(folder / "metrics.json")
    fills_count = int(metrics["fills"])
    result = {
        "fills_per_year": fills_count / years,
        "trade_days": None,
        "trade_days_per_year": None,
        "average_core_weight": None,
        "average_satellite_weight": None,
        "average_monetary_weight": None,
        "average_cash_weight": None,
    }
    path = folder / "fills.csv"
    if path.is_file():
        try:
            fills = pd.read_csv(path)
        except pd.errors.EmptyDataError:
            fills = pd.DataFrame(columns=["session_date"])
        if len(fills) != fills_count:
            raise ValueError(f"saved fills count differs from metrics: {folder}")
        days = pd.to_datetime(fills["session_date"]).dt.normalize()
        if len(days) and not days.isin(curve.index).all():
            raise ValueError(f"fill dates outside the saved equity period: {folder}")
        result["trade_days"] = int(days.nunique())
        result["trade_days_per_year"] = result["trade_days"] / years
    path = folder / "weights.csv"
    if path.is_file():
        weights = pd.read_csv(path, index_col=0, parse_dates=True)
        if not weights.index.equals(curve.index):
            raise ValueError(f"saved positions and equity dates differ: {folder}")
        core_id = parameters.get("core_id", "ETF_SP500_PEA")
        monetary_id = parameters.get("monetary_id", "ETF_MONETARY_EUR")
        zero = pd.Series(0.0, index=weights.index)
        core = weights.get(core_id, zero)
        money = weights.get(monetary_id, zero)
        invested = weights.sum(axis=1)
        satellites = parameters.get(
            "satellite_ids", [name for name in weights if name not in (core_id, monetary_id)]
        )
        satellite = weights.reindex(columns=list(satellites), fill_value=0.0).sum(axis=1)
        result.update(
            average_core_weight=float(core.mean()),
            average_satellite_weight=float(satellite.mean()),
            average_monetary_weight=float(money.mean()),
            average_cash_weight=float((1.0 - invested).clip(lower=0.0).mean()),
        )
    return result


def render_comparison(output: Path, period: str, trial: int, parameters: dict) -> pd.DataFrame:
    """Render existing NAV, relative wealth and daily drawdown with no market-data access."""
    if period not in PERIODS:
        raise ValueError("unknown study period")
    curves = {}
    rows = {}
    for name in (BOOK, *REFERENCES):
        folder = result_folder(output, period, name, trial)
        curves[name] = load_equity(folder / "equity.csv")
        rows[name] = read_json(folder / "metrics.json")
        rows[name].update(operational_metrics(folder, curves[name], parameters))
    benchmark = curves[BENCHMARK]
    if any(not curve.index.equals(benchmark.index) for curve in curves.values()):
        raise ValueError("comparison dates differ; no filling or intersection is allowed")
    equity = pd.DataFrame(curves)
    relative_wealth = equity.div(equity.iloc[0]).div(benchmark / benchmark.iloc[0], axis=0)
    benchmark_for_alpha = analytics_copy(benchmark)
    for name, curve in curves.items():
        comparison = alpha_vs_benchmark(analytics_copy(curve), benchmark_for_alpha, ANALYTICS)
        rows[name].update(
            alpha_vs_sp500=comparison.alpha_annualised,
            beta_vs_sp500=comparison.beta,
            outperformance_vs_sp500=comparison.outperformance,
            relative_wealth_return=float(relative_wealth[name].iloc[-1] - 1.0),
        )
    table = pd.DataFrame.from_dict(rows, orient="index").rename_axis("book")
    folder = output / "comparison" / period
    folder.mkdir(parents=True, exist_ok=True)
    table.to_csv(folder / "summary.csv")
    equity.to_csv(folder / "equity.csv", index_label="session_date")
    relative_wealth.to_csv(folder / "relative_wealth.csv", index_label="session_date")
    returns = equity.pct_change(fill_method=None).fillna(0.0)
    yearly = (1.0 + returns).groupby(returns.index.year).prod() - 1.0
    yearly.to_csv(folder / "yearly.csv", index_label="year")
    figure, axes = plt.subplots(3, 1, figsize=(12, 10), sharex=True, height_ratios=[2, 1, 1])
    for name in equity:
        axes[0].plot(equity.index, equity[name] / equity[name].iloc[0] * 100, label=LABELS[name])
        axes[1].plot(relative_wealth.index, relative_wealth[name])
        axes[2].plot(equity.index, equity[name] / equity[name].cummax() - 1.0)
    axes[0].set(title=f"SA15_GPT-6.1 R2 — {period} — net des frais", ylabel="Capital, base 100")
    axes[0].legend(fontsize=8)
    axes[1].set(ylabel="Patrimoine / S&P 500")
    axes[1].axhline(1.0, color="black", linewidth=0.7, alpha=0.5)
    axes[2].set(ylabel="Drawdown quotidien")
    axes[2].yaxis.set_major_formatter(PercentFormatter(1.0))
    for axis in axes:
        axis.grid(alpha=0.2)
    figure.tight_layout()
    figure.savefig(folder / "comparison.png", dpi=160)
    plt.close(figure)
    return table


def bootstrap_interval(strategy: pd.Series, benchmark: pd.Series) -> dict:
    """Bootstrap paired active returns in circular 20-session blocks, with a fixed seed."""
    if not strategy.index.equals(benchmark.index):
        raise ValueError("bootstrap curves need identical saved sessions")
    active = (
        (strategy.pct_change(fill_method=None) - benchmark.pct_change(fill_method=None))
        .iloc[1:]
        .to_numpy(dtype=float)
    )
    if len(active) == 0 or not np.isfinite(active).all():
        raise ValueError("bootstrap requires finite paired returns")
    rng = np.random.default_rng(61152)
    n, block, replications = len(active), 20, 2_000
    estimates = np.empty(replications)
    for index in range(replications):
        starts = rng.integers(0, n, size=math.ceil(n / block))
        positions = ((starts[:, None] + np.arange(block)) % n).ravel()[:n]
        estimates[index] = active[positions].mean() * 252
    return {
        "annualised_mean_active_return": float(active.mean() * 252),
        "lower_95": float(np.quantile(estimates, 0.025)),
        "upper_95": float(np.quantile(estimates, 0.975)),
        "seed": 61152,
        "block_sessions": block,
        "replications": replications,
    }


def trial_rows(output: Path) -> list[dict]:
    """Read every completed round-two candidate directly from its period metrics."""
    references = {
        period: read_json(output / "references" / period / BENCHMARK / "metrics.json")
        for period in ("development", "validation")
    }
    rows = []
    for trial in range(11, 21):
        folder = output / f"trial_{trial:02d}"
        if not (folder / "candidate.json").exists():
            continue
        spec = read_json(folder / "candidate.json")
        if spec["number"] != trial:
            raise ValueError("candidate number disagrees with its saved folder")
        development = read_json(folder / "development/metrics.json")
        validation = read_json(folder / "validation/metrics.json")
        first = development["cagr"] - references["development"]["cagr"]
        second = validation["cagr"] - references["validation"]["cagr"]
        rows.append(
            {
                "trial": trial,
                "reason": spec["reason"],
                "schedule": spec["schedule"],
                "development_cagr": development["cagr"],
                "validation_cagr": validation["cagr"],
                "development_excess_cagr": first,
                "validation_excess_cagr": second,
                "development_drawdown": development["max_drawdown"],
                "validation_drawdown": validation["max_drawdown"],
                "both_excess_positive": first > 0.0 and second > 0.0,
                "score": (first + second) / 2.0 - 0.25 * abs(first - second),
            }
        )
    if not rows:
        raise ValueError("no completed round-two trials were saved")
    return rows


def selection_diagnostics(output: Path, trials: list[dict], r1_output: Path) -> dict:
    """Describe Sharpe deflation for 20 declared configurations, without a new selection."""
    round_curves = {
        row["trial"]: load_equity(output / f"trial_{row['trial']:02d}/validation/equity.csv")
        for row in trials
    }
    first_paths = [r1_output / f"trial_{trial:02d}/validation/equity.csv" for trial in range(1, 11)]
    has_first_round = all(path.is_file() for path in first_paths)
    dispersion_curves = [
        *(load_equity(path) for path in first_paths if has_first_round),
        *round_curves.values(),
    ]
    sharpes = [session_sharpe(curve, ANALYTICS) for curve in dispersion_curves]
    usable = [value for value in sharpes if value is not None]
    dispersion = float(np.std(usable, ddof=1)) if len(usable) >= 2 else 0.0
    probabilities = {
        str(trial): deflated_sharpe_probability(
            curve, ANALYTICS, trials=20, trial_sharpe_std=dispersion
        )
        for trial, curve in round_curves.items()
    }
    return {
        "total_trials_declared": 20,
        "round_two_trials": len(round_curves),
        "dispersion_curves": len(dispersion_curves),
        "usable_session_sharpes": len(usable),
        "dispersion_source": (
            "R1_and_R2_validation_curves"
            if has_first_round
            else "R2_validation_curves_only_R1_incomplete_or_unavailable"
        ),
        "session_sharpe_std": dispersion,
        "validation_dsr": probabilities,
        "note": (
            "20 correlated configurations; the estimate does not account for every historical "
            "project choice or the retrospective universe. No DSR acceptance threshold is added."
        ),
    }


def hypothesis_status(
    full_excess: float, final_excess: float, stressed_final_excess: float, lower_95: float
) -> tuple[str, list[str]]:
    """Apply the full-and-final S&P 500 objective, then cautious stress/uncertainty checks."""
    failures = []
    if full_excess <= 0.0:
        failures.append("pas de surperformance nette du S&P 500 sur l'historique continu")
    if final_excess <= 0.0:
        failures.append("pas de surperformance nette du S&P 500 sur le controle chronologique")
    if failures:
        return "NOT_SUPPORTED", failures
    if stressed_final_excess <= 0.0:
        failures.append("l'avantage disparait aux frais doubles face au S&P 500 standard")
    if lower_95 <= 0.0:
        failures.append("l'intervalle bootstrap de rendement actif moyen contient zero")
    return ("UNCERTAIN", failures) if failures else ("SUPPORTED_RETROSPECTIVE", [])


def retained_rule(parameters: dict) -> str:
    """Explain the exact simple binary case, keeping other configurations generic."""
    weights = list(parameters.get("momentum_weights", ()))
    simple_binary = (
        parameters.get("core_id") == "ETF_SP500_PEA"
        and parameters.get("core_fraction") == 0
        and parameters.get("top_k") == 1
        and list(parameters.get("satellite_ids", ())) == ["ETF_NASDAQ"]
        and list(parameters.get("momentum_lookbacks", ())) == [126, 252]
        and len(weights) == 2
        and weights[0] == weights[1]
        and weights[0] > 0
        and parameters.get("skip_recent_sessions") == 0
        and parameters.get("minimum_relative_momentum") == 0
        and parameters.get("absolute_filter") is True
        and parameters.get("satellite_cap") == 1
        and parameters.get("core_crash_threshold") == -1
    )
    if simple_binary:
        return (
            "La regle retenue est une rotation entre le Nasdaq 100 et le S&P 500. "
            "Lorsque les endpoints sont disponibles, on calcule pour chaque indice :\n\n"
            "S_actif(t) = 0.5 * [log(P_t / P_(t-126)) + log(P_t / P_(t-252))], "
            "sur les cours ajustes.\n\n"
            "**Si S_Nasdaq > 0 et S_Nasdaq > S_SP500, la cible est 100 % Nasdaq. "
            "Sinon, la cible est 100 % S&P 500.** "
            "L'evaluation a lieu au demarrage puis apres la derniere cloture de chaque mois ; "
            "les ordres partent pour l'ouverture suivante. Avec ce seul satellite, le tampon "
            "de remplacement entre satellites n'ajoute pas de seuil d'entree. "
            "Aucun levier ni poche de cash tactique n'est active dans cette configuration ; "
            "le cash residuel vient des parts entieres, des frais et de l'attente initiale "
            "avant execution. Les refus de signaux restent soumis au contrat du moteur."
        )
    return (
        "La configuration utilise un budget de coeur de "
        + percent(parameters.get("core_fraction"))
        + " et retient jusqu'a "
        + str(parameters.get("top_k", "n.d."))
        + " satellite(s). Les horizons, seuils, plafonds et protections exacts sont ceux "
        "du tableau gele ; la regle binaire Nasdaq/S&P 500 n'est pas appliquee par defaut "
        "aux autres configurations."
    )


def financial_table(table: pd.DataFrame) -> str:
    """Print the same principal financial columns for each executable reference."""
    return markdown_table(
        ["Livre", "Net total", "CAGR", "Volatilite", "Sharpe", "Drawdown", "Frais EUR"],
        [
            [
                LABELS[name],
                percent(row["net_return"]),
                percent(row["cagr"]),
                percent(row["volatility"]),
                number(row["sharpe"]),
                percent(row["max_drawdown"]),
                number(row["costs_eur"], 0),
            ]
            for name, row in table.iterrows()
        ],
    )


def report(output: Path, *, r1_output: Path = R1_OUTPUT) -> None:
    """Publish the frozen study using saved runs only, leaving all run evidence intact."""
    selected, definition, configuration = frozen_selection(output)
    parameters = definition["parameters"]
    trial = selected["candidate"]["number"]
    trials = trial_rows(output)
    if trial not in {row["trial"] for row in trials}:
        raise ValueError("the frozen winner is not a completed round-two candidate")
    diagnostics = selection_diagnostics(output, trials, r1_output)
    tables = {period: render_comparison(output, period, trial, parameters) for period in PERIODS}
    final_equity = pd.read_csv(
        output / "comparison/final/equity.csv", index_col=0, parse_dates=True
    )
    uncertainty = bootstrap_interval(final_equity[BOOK], final_equity[BENCHMARK])
    stress = read_json(output / "final/costs_x2/metrics.json")
    final, full = tables["final"], tables["full"]
    final_excess = float(final.loc[BOOK, "net_return"] - final.loc[BENCHMARK, "net_return"])
    full_excess = float(full.loc[BOOK, "net_return"] - full.loc[BENCHMARK, "net_return"])
    stress_excess = float(stress["net_return"] - final.loc[BENCHMARK, "net_return"])
    status, reasons = hypothesis_status(
        full_excess, final_excess, stress_excess, uncertainty["lower_95"]
    )
    write_json(output / "selection_diagnostics.json", diagnostics)
    write_json(output / "final/uncertainty.json", uncertainty)
    write_json(
        output / "verdict.json",
        {
            "status": status,
            "reasons": reasons,
            "full_excess_total_return": full_excess,
            "final_excess_total_return": final_excess,
            "stressed_final_excess_vs_standard_sp500": stress_excess,
        },
    )
    pd.DataFrame(trials).to_csv(output / "reported_iterations.csv", index=False)
    parameter_table = markdown_table(
        ["Parametre gele", "Valeur effective"],
        [[name, json.dumps(value, ensure_ascii=False)] for name, value in parameters.items()],
    )
    trial_table = markdown_table(
        [
            "Essai",
            "CAGR dev.",
            "Exces dev.",
            "CAGR selection",
            "Exces selection",
            "Deux positifs",
            "Score",
            "DSR",
        ],
        [
            [
                str(row["trial"]),
                percent(row["development_cagr"]),
                percent(row["development_excess_cagr"]),
                percent(row["validation_cagr"]),
                percent(row["validation_excess_cagr"]),
                "oui" if row["both_excess_positive"] else "non",
                number(row["score"], 4),
                number(diagnostics["validation_dsr"][str(row["trial"])], 3),
            ]
            for row in trials
        ],
    )
    operations = markdown_table(
        [
            "Periode",
            "Jours d'ordres/an",
            "Ordres/an",
            "Rotation/an",
            "Frais EUR",
            "S&P 500 moyen",
            "Satellites moyens",
            "Monetaire moyen",
            "Cash moyen",
        ],
        [
            [
                label,
                number(tables[period].loc[BOOK, "trade_days_per_year"]),
                number(tables[period].loc[BOOK, "fills_per_year"]),
                number(tables[period].loc[BOOK, "turnover_per_year"]),
                number(tables[period].loc[BOOK, "costs_eur"], 0),
                percent(tables[period].loc[BOOK, "average_core_weight"]),
                percent(tables[period].loc[BOOK, "average_satellite_weight"]),
                percent(tables[period].loc[BOOK, "average_monetary_weight"]),
                percent(tables[period].loc[BOOK, "average_cash_weight"]),
            ]
            for period, label in (
                ("full", "Historique continu"),
                ("final", "Controle chronologique"),
            )
        ],
    )
    yearly = pd.read_csv(output / "comparison/full/yearly.csv", index_col="year")
    yearly_table = markdown_table(
        ["Annee", "SA15", "S&P 500", "Nasdaq", "50/50 initial"],
        [
            [str(year)] + [percent(row[name]) for name in (BOOK, *REFERENCES)]
            for year, row in yearly.iterrows()
        ],
    )
    motivations = "\n".join(f"{row['trial']}. {row['reason']}" for row in trials)
    justification = (
        "; ".join(reasons) if reasons else "criteres retrospectifs remplis, sans preuve prospective"
    )
    timetable = configuration["timetable"]
    full_extra_eur = full_excess * float(configuration["initial_cash"])
    final_extra_eur = final_excess * float(configuration["initial_cash"])
    asset_names = {
        "ETF_NASDAQ": "Nasdaq 100",
        "ETF_GOLD": "or (ETC Xetra-Gold)",
        "ETF_EMERGING": "actions emergentes",
        "ETF_COMMODITY": "matieres premieres",
    }
    satellite_names = (
        ", ".join(asset_names.get(name, name) for name in parameters.get("satellite_ids", ()))
        or "aucun"
    )
    rule_explanation = retained_rule(parameters)
    full_equity = load_equity(output / "full" / BOOK / "equity.csv")
    full_years = max((full_equity.index[-1] - full_equity.index[0]).days / 365.25, 1 / 252)
    final_years = max((final_equity.index[-1] - final_equity.index[0]).days / 365.25, 1 / 252)
    evaluations_per_year = {"monthly": 12, "weekly": 52, "daily": 252}.get(
        selected["candidate"]["schedule"]
    )
    text = f"""# SA15_GPT-6.1 — seconde serie — 15 octobre 2026

Statut de l'objectif de surperformance nette du S&P 500 conserve : **{status}**.
Configuration gelee : **essai {trial}**, parmi {len(trials)} configurations de cette serie,
soit **20 configurations annoncees au total** avec la premiere serie.
Motif du statut : {justification}.

L'ecart net total au S&P 500 est **{full_excess * 100:.2f} points** sur l'historique
continu et **{final_excess * 100:.2f} points** sur le controle chronologique.
Pour {configuration["initial_cash"]:,.0f} EUR de depart, cela represente respectivement
**{full_extra_eur:,.0f} EUR** et **{final_extra_eur:,.0f} EUR** de capital terminal
supplementaire ou manquant. Les resultats sont nets des frais simules, avant fiscalite personnelle.

## Historique continu : 3 juin 2019 au 9 octobre 2026

{financial_table(full)}

![Capital, patrimoine relatif au S&P 500 et drawdown quotidiens](comparison/full/comparison.png)

Ce parcours inclut developpement, selection et controle. Il decrit le gagnant retrospectif.
Le Nasdaq conserve et le 50/50 initial conserve servent a distinguer une prime de concentration
d'une contribution de la rotation. Le 50/50 n'est pas reequilibre apres l'achat initial.

## Controle chronologique : 2 janvier 2025 au 9 octobre 2026

{financial_table(final)}

![Capital, patrimoine relatif au S&P 500 et drawdown quotidiens](comparison/final/comparison.png)

L'alpha annuel de regression au S&P 500 vaut **{percent(final.loc[BOOK, "alpha_vs_sp500"])}**,
avec beta **{number(final.loc[BOOK, "beta_vs_sp500"])}**. Le patrimoine relatif termine a
**{number(1.0 + final.loc[BOOK, "relative_wealth_return"], 4)}** fois celui du S&P 500.
Alpha, difference de rendements totaux et ratio de patrimoines ne mesurent pas la meme chose.
Une exposition plus forte a la croissance et aux grandes valeurs technologiques peut expliquer
une surperformance ; un alpha contre un seul indice ne prouve pas une capacite de timing.

## Configuration effectivement retenue

Classe sauvegardee : {definition["class"]}.
Les valeurs par defaut de la classe sont un prototype ; elles ne remplacent pas la configuration
selectionnee. Le tableau vient des parametres complets de la definition finale gelee, verifies
contre selected.json et son empreinte **{selected["fingerprint"]}**.
Le fichier candidat enregistre les changements demandes ; le tableau inclut aussi les valeurs
heritees du prototype.

{parameter_table}

{rule_explanation}

Frequence : **{selected["candidate"]["schedule"]}**.
L'allocation initiale est decidee des la premiere seance du backtest, puis la cadence
mensuelle reprend aux fins de mois ; la variante hebdomadaire suit le meme principe.
Les parts sont achetees a l'ouverture negociable suivante : aucune attente artificielle
d'un mois en cash n'est ajoutee face au S&P 500 conserve.
Decision : **{timetable["decision_time"]}, {timetable["timezone"]}**.
Execution : ouverture de la seance suivante, instant moteur **{timetable["execution_time"]}**.
Les ordres sont prepares apres les clotures, sans levier ni vente a decouvert.
Le coeur S&P 500 reste le point de repli lorsque les satellites ne montrent pas d'avantage relatif.
Le momentum relatif utilise les prix ajustes aux endpoints exacts des horizons de seances :
un trou interieur n'est pas comble, et un endpoint absent refuse le signal.
Ce contrat differe du signal a fenetres strictement consecutives de la premiere serie.

## Dix iterations autorisees : tous les essais termines

Les exces sont des differences de CAGR au S&P 500 sur les memes dates.
Priorite aux deux exces strictement positifs, puis score decroissant, puis premier numero.
Score = moyenne(exces developpement, exces selection) - 0.25 * ecart absolu des deux exces.
Le rapport lit les resultats sauves ; il ne choisit pas de nouveau gagnant.

{trial_table}

{motivations}

Developpement : 2019-06-03/2022-12-30. Selection : 2023-01-02/2024-12-31.
Le [protocole de la seconde serie](../../research/SA15_GPT-6.1/round2/protocol.md)
fixe l'objectif avant ces essais. Toute l'histoire 2019-2026 avait deja ete examinee :
aucune de ces periodes n'est un echantillon vierge et le controle final est retrospectif.
La premiere serie et ses archives restent conservees.

Le DSR annonce **20 essais correles**, avec dispersion estimee sur
**{diagnostics["dispersion_curves"]} courbes** de selection
(source : {diagnostics["dispersion_source"]} ; ecart-type des Sharpe par seance :
{number(diagnostics["session_sharpe_std"], 6)}).
Si les dix courbes R1 sont indisponibles, le nombre reste 20 mais la dispersion est estimee
sur R2 seulement et cette approximation est declaree. Le DSR reste un diagnostic ; aucun seuil
supplementaire n'est ajoute. Il ne corrige pas tous les choix historiques du projet.

## Travail et capital mobilise

{operations}

Un jour d'ordres est une date de fills distincte ; plusieurs achats ou ventes ce jour-la
constituent plusieurs ordres. Ces nombres incluent les entrees initiales.
L'annualisation utilise le temps calendaire ecoule, pas seulement les seances.
La frequence de verification du signal et le nombre effectif de jours d'ordres sont distincts.
Les references sauvegardees sans detail des fills n'ont pas de nombre de jours reconstitue.
Les poids sont les positions reellement detenues, moyennes sur toutes les seances.
Satellite(s) configure(s) dans le gagnant : **{satellite_names}**.
Les poids moyens de ces lignes ne sont pas une mesure de beta actions.
Les liquidites initiales avant premier achat sont incluses.

Sur l'historique continu, il y a **{number(full.loc[BOOK, "trade_days"], 0)} dates d'ordres
en {full_years:.2f} ans**.
Sur le controle chronologique : **{number(final.loc[BOOK, "trade_days"], 0)}
dates en {final_years:.2f} ans**. Une rotation rare ne supprime pas le suivi :
la cadence retenue demande environ **{number(evaluations_per_year, 0)} evaluations par an**,
plus l'allocation initiale, meme les mois sans transaction.

## Couts, incertitude et sensibilite

Aux frais doubles, le gagnant donne un rendement final net de **{percent(stress["net_return"])}**,
CAGR **{percent(stress["cagr"])}**, drawdown **{percent(stress["max_drawdown"])}** et
**{number(stress["costs_eur"], 0)} EUR** de frais. L'ecart face au S&P 500 aux frais standards
est alors **{stress_excess * 100:.2f} points**. Cette comparaison est volontairement prudente :
le test de stress ne reestime aucun seuil et ne se substitue pas au comparatif standard.

Bootstrap apparie du rendement actif moyen annualise final contre S&P 500 :
**{percent(uncertainty["annualised_mean_active_return"])}**,
intervalle 95 % **[{percent(uncertainty["lower_95"])} ; {percent(uncertainty["upper_95"])}]**.
Blocs circulaires de 20 seances, 2000 tirages, seed 61152.
Ce n'est ni un intervalle de CAGR ni une preuve independante ; les observations ont deja servi
aux choix retrospectifs et les essais multiples ne sont pas corriges par cet intervalle.

Le statut SUPPORTED_RETROSPECTIVE demande un exces net positif sur historique continu ET
controle chronologique, un avantage conservateur aux frais doubles et une borne bootstrap
positive. Un echec de l'objectif continu ou chronologique vaut NOT_SUPPORTED ; une incertitude
sur les deux derniers diagnostics vaut UNCERTAIN. Aucun verdict ne garantit une performance future.

[Frais doubles des configurations](robustness/costs_x2.csv) —
[Redemarrages depuis cash](robustness/starts.csv) —
[Diagnostic continu](robustness/full.csv).

## Rendements par annee de l'historique continu

{yearly_table}

La premiere et la derniere annee sont partielles. Les drawdowns sont mesures quotidiennement,
meme lorsque les decisions sont mensuelles. Chaque periode recommence avec le meme capital
en cash ; elle n'herite pas des positions de la periode precedente.

## Limites et sources

Un resultat contre S&P 500 peut provenir d'une concentration Nasdaq persistante :
les controles Nasdaq conserve et 50/50 initial sont essentiels.
Le petit univers de fonds encore disponibles a ete choisi retrospectivement.
Les cotations EUR ne suppriment pas les risques de devises sous-jacents.
Xetra-Gold est un ETC et non un ETF UCITS ; XDBC a change d'indice le 21 mai 2021.
Les prix ajustes telecharges aujourd'hui peuvent avoir ete revises : ce ne sont pas des
vintages disponibles a chaque date historique. Les trous de donnees et refus de signaux
restent documentes dans les runs ; aucun cours n'est invente par ce rapport.
Le Sharpe utilise le taux sans risque nul du projet.

- [Antonacci : momentum relatif et absolu](https://ssrn.com/abstract=2042750).
- [Garleanu et Pedersen : transactions et couts](https://www.nber.org/papers/w15205).
- [MSCI : transition graduelle et rotation](https://app2.msci.com/webapp/index_ann/DocGet?format=html&lang=en&pub_key=vXBeNkI7Sxg%3D).
- [Forum : objection du simple Nasdaq conserve](https://www.reddit.com/r/algotrading/comments/1v0ov4w/turbo_ldm_2x_leveraged_dual_momentum_w_fast/).

Ces sources motivent des composants ; leurs resultats ne sont pas attribues a cette strategie.
Le forum apporte des objections pratiques et non une validation scientifique.
Les archives de calcul et les empreintes restent celles du runner ; ce rapport ne lance
aucun backtest et ne modifie aucun candidat, aucune selection ni aucune transaction.

Reproduction complete sous WSL/POSIX dans un NOUVEAU dossier,
a partir du magasin isole deja valide :

    OUT=runs/sa15_r2_reproduction
    CANDIDATES=research/SA15_GPT-6.1/round2/candidates
    for N in $(seq 11 20); do
        SPEC=$(printf "%s/trial_%02d.json" "$CANDIDATES" "$N")
        uv run python scripts/SA15_run_gpt61_round2.py --candidate "$SPEC" --output "$OUT"
    done
    uv run python scripts/SA15_run_gpt61_round2.py --final --output "$OUT"
    uv run python scripts/SA15_run_gpt61_round2.py --robustness --output "$OUT" --workers 2
    uv run python scripts/SA15_report_gpt61_round2.py --output "$OUT"

Pour regenerer seulement les exports existants, sans nouveau backtest :

    uv run python scripts/SA15_report_gpt61_round2.py --output results/SA15_GPT-6.1_R2

Les archives financieres de la premiere et de la seconde serie sont conservees.
Le fichier reporting_manifest.json date le rendu et donne l'empreinte du source de rapport
actuel, distinct du source financier archive avant evaluation.

[Tableau complet](comparison/full/summary.csv) — [Tableau final](comparison/final/summary.csv) —
[Courbes sauvees](comparison/full/equity.csv) — [Toutes les iterations](reported_iterations.csv) —
[Selection gelee](selected.json) — [Diagnostic DSR](selection_diagnostics.json) —
[Verdict machine](verdict.json) — [Verification et limites](validation.md).
"""
    (output / "study.md").write_text(text, encoding="utf-8")
    source_path = Path(__file__).resolve()
    financial_archive = output / "source/source.zip"
    write_json(
        output / "reporting_manifest.json",
        {
            "generated_at_utc": datetime.now(UTC).isoformat(),
            "report_source": source_path.relative_to(ROOT).as_posix(),
            "report_source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
            "study_sha256": hashlib.sha256((output / "study.md").read_bytes()).hexdigest(),
            "selected_json_sha256": hashlib.sha256(
                (output / "selected.json").read_bytes()
            ).hexdigest(),
            "financial_source_archive_sha256": (
                hashlib.sha256(financial_archive.read_bytes()).hexdigest()
                if financial_archive.is_file()
                else None
            ),
            "note": "Presentation-only polish after financial source archival; no backtest rerun.",
        },
    )
    print(f"wrote {output / 'study.md'}: {status}")


def main() -> None:
    """Render an already completed frozen study, without a runner or market-data reader."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    report(parser.parse_args().output)


if __name__ == "__main__":
    main()
