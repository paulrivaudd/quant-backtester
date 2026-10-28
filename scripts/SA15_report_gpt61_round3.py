"""Render the frozen third SA15 study without constructing a runner or trading.

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
DEFAULT_OUTPUT = ROOT / "results/SA15_GPT-6.1_R3"
R1_OUTPUT = ROOT / "results/SA15_GPT-6.1"
R2_OUTPUT = ROOT / "results/SA15_GPT-6.1_R2"
BOOK = "SA15_GPT-6.1_R3"
BENCHMARK = "Nasdaq_buy_hold"
REFERENCES = (BENCHMARK, "SP500_buy_hold", "static_50_50")
PERIODS = ("development", "validation", "final", "full")
ANALYTICS = AnalyticsConfig(sessions_per_year=252, risk_free_rate=0.0, minimum_sessions=60)
LABELS = {
    BOOK: "SA15 retenue",
    BENCHMARK: "Nasdaq conserve",
    "SP500_buy_hold": "S&P 500 conserve",
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
    if isinstance(trial, bool) or not isinstance(trial, int) or not 21 <= trial <= 30:
        raise ValueError("round three requires a frozen trial number from 21 to 30")
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
    """Locate existing runs in the runner's declared round-three layout."""
    if period == "full":
        return output / "full" / name
    if name == BOOK:
        return (
            output / "final" / name if period == "final" else output / f"trial_{trial:02d}" / period
        )
    return output / "references" / period / name


def operational_metrics(folder: Path, curve: pd.Series, parameters: dict) -> dict:
    """Count actual trading dates and expose the realized Nasdaq/defensive allocation.

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
        "average_defensive_weight": None,
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
        core_id = parameters.get("core_id", "ETF_NASDAQ")
        monetary_id = parameters.get("monetary_id", "ETF_MONETARY_EUR")
        zero = pd.Series(0.0, index=weights.index)
        core = weights.get(core_id, zero)
        money = weights.get(monetary_id, zero)
        invested = weights.sum(axis=1)
        defensive_ids = parameters.get(
            "defensive_ids", [name for name in weights if name not in (core_id, monetary_id)]
        )
        defensive = weights.reindex(columns=list(defensive_ids), fill_value=0.0).sum(axis=1)
        result.update(
            average_core_weight=float(core.mean()),
            average_defensive_weight=float(defensive.mean()),
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
            alpha_vs_nasdaq=comparison.alpha_annualised,
            beta_vs_nasdaq=comparison.beta,
            outperformance_vs_nasdaq=comparison.outperformance,
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
    axes[0].set(title=f"SA15_GPT-6.1 R3 — {period} — net des frais", ylabel="Capital, base 100")
    axes[0].legend(fontsize=8)
    axes[1].set(ylabel="Patrimoine / Nasdaq")
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
    rng = np.random.default_rng(61153)
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
        "seed": 61153,
        "block_sessions": block,
        "replications": replications,
    }


def trial_rows(output: Path) -> list[dict]:
    """Read every completed round-three candidate directly from its period metrics."""
    references = {
        period: read_json(output / "references" / period / BENCHMARK / "metrics.json")
        for period in ("development", "validation")
    }
    rows = []
    for trial in range(21, 31):
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
        raise ValueError("no completed round-three trials were saved")
    return rows


def selection_diagnostics(
    output: Path, trials: list[dict], r1_output: Path, r2_output: Path
) -> dict:
    """Deflate Sharpe for 30 declared designs using every available saved validation curve."""
    round_curves = {
        row["trial"]: load_equity(output / f"trial_{row['trial']:02d}/validation/equity.csv")
        for row in trials
    }
    previous = [
        (number, root / f"trial_{number:02d}/validation/equity.csv")
        for root, numbers in ((r1_output, range(1, 11)), (r2_output, range(11, 21)))
        for number in numbers
    ]
    available = [(number, path) for number, path in previous if path.is_file()]
    missing = [number for number, path in previous if not path.is_file()]
    dispersion_curves = [
        *(load_equity(path) for _number, path in available),
        *round_curves.values(),
    ]
    sharpes = [session_sharpe(curve, ANALYTICS) for curve in dispersion_curves]
    usable = [value for value in sharpes if value is not None]
    dispersion = float(np.std(usable, ddof=1)) if len(usable) >= 2 else 0.0
    probabilities = {
        str(trial): deflated_sharpe_probability(
            curve, ANALYTICS, trials=30, trial_sharpe_std=dispersion
        )
        for trial, curve in round_curves.items()
    }
    return {
        "total_trials_declared": 30,
        "round_three_trials": len(round_curves),
        "dispersion_curves": len(dispersion_curves),
        "usable_session_sharpes": len(usable),
        "previous_trials_available": [number for number, _path in available],
        "previous_trials_missing": missing,
        "dispersion_source": (
            "R1_R2_R3_validation_curves"
            if not missing
            else "available_R1_R2_and_R3_validation_curves_previous_rounds_incomplete"
        ),
        "session_sharpe_std": dispersion,
        "validation_dsr": probabilities,
        "note": (
            "30 correlated designs; the estimate does not account for every historical "
            "project choice or the retrospective universe. No DSR acceptance threshold is added. "
            "Missing earlier curves reduce available dispersion evidence, not the declared trials."
        ),
    }


def hypothesis_status(
    full_excess: float, final_excess: float, stressed_final_excess: float, lower_95: float
) -> tuple[str, list[str]]:
    """Apply the full-and-final Nasdaq growth objective, then cautious stress/uncertainty checks."""
    failures = []
    if full_excess <= 0.0:
        failures.append("pas de surperformance nette du Nasdaq sur l'historique continu")
    if final_excess <= 0.0:
        failures.append("pas de surperformance nette du Nasdaq sur le controle chronologique")
    if failures:
        return "NOT_SUPPORTED", failures
    if stressed_final_excess <= 0.0:
        failures.append("l'avantage disparait aux frais doubles face au Nasdaq standard")
    if lower_95 <= 0.0:
        failures.append("l'intervalle bootstrap de rendement actif moyen contient zero")
    return ("UNCERTAIN", failures) if failures else ("SUPPORTED_RETROSPECTIVE", [])


ASSET_NAMES = {
    "ETF_NASDAQ": "Nasdaq 100",
    "ETF_SP500_PEA": "S&P 500",
    "ETF_GOLD": "or (ETC Xetra-Gold)",
    "ETF_EMERGING": "actions emergentes",
    "ETF_COMMODITY": "matieres premieres",
    "ETF_EURO_GOV": "obligations souveraines EUR",
    "ETF_MONETARY_EUR": "monetaire EUR",
    "ETF_WORLD": "actions mondiales",
}


def asset_name(instrument_id: str) -> str:
    """Keep unrecognized saved identifiers visible instead of inventing a holding."""
    return ASSET_NAMES.get(instrument_id, instrument_id)


def retained_rule(parameters: dict) -> str:
    """Explain saved adaptive-policy settings; never hardcode a winning trial or defaults."""
    required = {
        "core_id",
        "defensive_ids",
        "monetary_id",
        "guard_mode",
        "fast_lookback",
        "slow_lookback",
        "fast_entry_threshold",
        "slow_entry_threshold",
        "recovery_threshold",
        "core_floor",
        "defensive_lookbacks",
        "defensive_weights",
        "top_k",
        "relative_rotation",
        "relative_threshold",
        "monetary_lookback",
    }
    if not required <= parameters.keys():
        return (
            "La definition sauvee ne contient pas tous les champs de SA15NasdaqAdaptive. "
            "Le tableau gele reste la seule description complete ; aucune regle du prototype "
            "ou d'un ancien gagnant n'est substituee."
        )
    core = asset_name(parameters["core_id"])
    defensive = ", ".join(asset_name(name) for name in parameters["defensive_ids"]) or "aucun"
    fast = parameters["fast_lookback"]
    slow = parameters["slow_lookback"]
    mode = parameters["guard_mode"]
    if mode == "momentum":
        weakness = (
            f"le rendement de {core} sur {slow} seances est inferieur ou egal a "
            f"{percent(parameters['slow_entry_threshold'])}"
        )
    elif mode == "trend":
        weakness = (
            f"le prix de {core} est inferieur ou egal a sa moyenne mobile sur "
            f"{parameters.get('trend_sessions', 'n.d.')} seances"
        )
    else:
        raise ValueError(f"unknown saved adaptive guard mode: {mode}")
    horizons = parameters["defensive_lookbacks"]
    weights = parameters["defensive_weights"]
    score = " + ".join(
        f"{weight} * log(P_t / P_(t-{horizon}))"
        for horizon, weight in zip(horizons, weights, strict=True)
    )
    relative = (
        f"Hors crise, une rotation relative est aussi active : le meilleur score defensif "
        f"positif doit depasser celui du coeur de "
        f"{number(parameters['relative_threshold'], 4)} en unites de log-rendement. "
        f"Pour une ligne deja detenue, le seuil relatif est reduit du tampon "
        f"{number(parameters.get('switch_buffer'), 4)}. "
        f"Cette poche utilise le meme budget de defense."
        if parameters["relative_rotation"]
        else "Hors crise, la rotation relative est desactivee : la cible normale reste le coeur."
    )
    return (
        f"La cible normale est **100 % {core}**. Le signal rapide est le rendement simple "
        f"sur **{fast} seances**. Une crise est ouverte lorsque {weakness} **et** que le "
        f"signal rapide est inferieur ou egal a "
        f"**{percent(parameters['fast_entry_threshold'])}**, tout en restant strictement sous "
        f"le seuil de reprise **{percent(parameters['recovery_threshold'])}**. "
        f"Une position defensive deja "
        f"detenue reste reconnue tant que le regime est faible et que le signal rapide "
        f"reste sous **{percent(parameters['recovery_threshold'])}**. Le retour au coeur "
        f"est donc possible avant le retablissement de la tendance lente.\n\n"
        f"En defense, la cible du coeur devient **{percent(parameters['core_floor'])}** ; "
        f"le budget restant peut etre alloue a **{defensive}**. "
        f"Le score defensif est ({score}) / somme des poids. "
        f"Jusqu'a **{parameters['top_k']}** lignes de score strictement positif sont retenues. "
        f"Le budget est partage a parts egales entre les lignes retenues. "
        f"A defaut, le repli est {asset_name(parameters['monetary_id'])} seulement si son "
        f"rendement sur {parameters['monetary_lookback']} seances est positif ; sinon cash. "
        f"{relative}\n\n"
        f"Le tampon de remplacement vaut {number(parameters.get('switch_buffer'), 4)} "
        f"en unites de log-rendement : les lignes admissibles deja detenues proches du "
        f"score de coupure sont prioritaires. La bande de reequilibrage vaut "
        f"{percent(parameters.get('rebalance_band'))}. "
        f"Une reprise force le retour complet au coeur lorsque la rotation relative ne "
        f"retient pas de defense ; la bande ne bloque pas ce retour. "
        f"Les positions effectivement detenues servent a reconnaitre l'etat defensif : "
        f"une poche relative peut aussi jouer ce role si le coeur devient faible. "
        f"Un poids positif du coeur inferieur a (1 + core_floor) / 2 reconnait egalement "
        f"une defense partiellement restee en cash. "
        f"Un portefeuille entierement en cash reevalue les conditions d'entree sans memoire. "
        f"Un signal obligatoire du coeur absent cible le cash ; une defense sans signal "
        f"est exclue individuellement. "
        f"Les prix ajustes servent aux signaux ; les ordres, les parts entieres et les frais "
        f"expliquent les ecarts entre cibles et positions. Aucun levier ni vente a decouvert."
    )


def average_position_table(output: Path, trial: int) -> str:
    """Show actual held asset names, including any configured defensive alternative."""
    rows = []
    for period, label in (("full", "Historique continu"), ("final", "Controle chronologique")):
        path = result_folder(output, period, BOOK, trial) / "weights.csv"
        if not path.is_file():
            continue
        weights = pd.read_csv(path, index_col=0, parse_dates=True)
        for instrument_id in weights:
            average = float(weights[instrument_id].mean())
            if average != 0.0:
                rows.append([label, asset_name(instrument_id), instrument_id, percent(average)])
    return markdown_table(["Periode", "Position", "Identifiant", "Poids moyen"], rows)


def financial_table(table: pd.DataFrame) -> str:
    """Print the same principal financial columns for each executable reference."""
    return markdown_table(
        [
            "Livre",
            "Net total",
            "Brut total",
            "CAGR",
            "Volatilite",
            "Sharpe",
            "Drawdown",
            "Frais EUR",
        ],
        [
            [
                LABELS[name],
                percent(row["net_return"]),
                percent(row["gross_return"]),
                percent(row["cagr"]),
                percent(row["volatility"]),
                number(row["sharpe"]),
                percent(row["max_drawdown"]),
                number(row["costs_eur"], 0),
            ]
            for name, row in table.iterrows()
        ],
    )


def report(output: Path, *, r1_output: Path = R1_OUTPUT, r2_output: Path = R2_OUTPUT) -> None:
    """Render saved round-three evidence; do not select or run any policy."""
    selected, definition, configuration = frozen_selection(output)
    parameters = definition["parameters"]
    trial = selected["candidate"]["number"]
    trials = trial_rows(output)
    if trial not in {row["trial"] for row in trials}:
        raise ValueError("the frozen winner is not a completed round-three candidate")
    diagnostics = selection_diagnostics(output, trials, r1_output, r2_output)
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
            "benchmark": BENCHMARK,
            "reasons": reasons,
            "full_excess_total_return": full_excess,
            "final_excess_total_return": final_excess,
            "stressed_final_excess_vs_standard_nasdaq": stress_excess,
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
            f"{asset_name(parameters.get('core_id', 'ETF_NASDAQ'))} moyen",
            "Defense hors monetaire",
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
                percent(tables[period].loc[BOOK, "average_defensive_weight"]),
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
        ["Annee", "SA15", "Nasdaq", "S&P 500", "50/50 initial"],
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
    rule_explanation = retained_rule(parameters)
    position_table = average_position_table(output, trial)
    full_equity = load_equity(output / "full" / BOOK / "equity.csv")
    full_years = max((full_equity.index[-1] - full_equity.index[0]).days / 365.25, 1 / 252)
    final_years = max((final_equity.index[-1] - final_equity.index[0]).days / 365.25, 1 / 252)
    evaluations_per_year = {"monthly": 12, "weekly": 52, "daily": 252}.get(
        selected["candidate"]["schedule"]
    )
    validation = output / "validation.md"
    economic_audit = ""
    if validation.is_file():
        _before, marker, audited = validation.read_text(encoding="utf-8").partition(
            "## R\u00e9sultat \u00e9conomique"
        )
        if marker and audited.strip():
            economic_audit = (
                "## Lecture des transactions et des rebonds\n\n"
                + audited.strip()
                + "\n\nSource : [verification economique archivee](validation.md).\n"
            )
    generated_date = datetime.now(UTC).date().isoformat()
    text = f"""# SA15_GPT-6.1 — troisieme serie — {generated_date}

Objectif : battre la croissance nette du **Nasdaq 100 achete et conserve**, sans levier.
Statut : **{status}**. Configuration gelee : **essai {trial}** parmi
{len(trials)} configurations de cette serie, soit **30 designs cumules annonces**.
Motif : {justification}.

L'ecart de rendement net total au Nasdaq conserve est **{full_excess * 100:.2f} points**
sur l'historique continu et **{final_excess * 100:.2f} points** sur le controle chronologique.
Pour {configuration["initial_cash"]:,.0f} EUR au depart, l'ecart de capital terminal vaut
respectivement **{full_extra_eur:,.0f} EUR** et **{final_extra_eur:,.0f} EUR**.
Les resultats sont nets des frais simules, avant fiscalite personnelle.
Un meilleur Sharpe ou un drawdown plus faible ne remplace pas cet objectif de croissance.

## Historique continu : 3 juin 2019 au 9 octobre 2026

{financial_table(full)}

![Capital, patrimoine relatif au Nasdaq et drawdown quotidiens](comparison/full/comparison.png)

Ce parcours comprend developpement, selection et controle : il decrit le gagnant retrospectif.
Le S&P 500 conserve et le 50/50 initial S&P 500/Nasdaq apportent du contexte.
Le 50/50 derive apres l'achat initial ; il n'est pas reequilibre.

## Controle chronologique : 2 janvier 2025 au 9 octobre 2026

{financial_table(final)}

![Capital, patrimoine relatif au Nasdaq et drawdown quotidiens](comparison/final/comparison.png)

L'alpha annuel de regression au Nasdaq vaut **{percent(final.loc[BOOK, "alpha_vs_nasdaq"])}**,
avec beta **{number(final.loc[BOOK, "beta_vs_nasdaq"])}**.
Le patrimoine relatif termine a **{number(1.0 + final.loc[BOOK, "relative_wealth_return"], 4)}**
fois celui du Nasdaq. L'alpha, la difference des rendements totaux et le ratio de patrimoines
sont trois mesures distinctes. L'alpha face a un seul indice ne prouve pas une capacite de timing.

## Configuration effectivement retenue

Classe sauvegardee : {definition["class"]}.
Les valeurs par defaut de la classe sont un prototype ; elles ne remplacent pas la configuration
selectionnee. Le tableau utilise tous les parametres effectifs de strategy.json final,
verifies contre selected.json et l'empreinte **{selected["fingerprint"]}**.
Le candidat contient seulement les changements demandes, le tableau inclut les champs herites.

{parameter_table}

{rule_explanation}

Cadence : **{selected["candidate"]["schedule"]}**.
Premiere decision des la premiere seance, puis fins de mois ou de semaine selon la cadence ;
une cadence quotidienne evalue chaque seance.
Decision : **{timetable["decision_time"]}, {timetable["timezone"]}**, apres les clotures.
Execution : ouverture negociable suivante, instant moteur **{timetable["execution_time"]}**.
L'allocation initiale immediate evite une attente mensuelle artificielle face au Nasdaq conserve.
Les signaux de momentum utilisent les endpoints exacts des horizons de seances ajustes.
Un endpoint absent refuse le signal ; les moyennes mobiles requierent les seances consecutives
exactes. Ce rapport ne comble aucun trou de donnees.

## Dix iterations : essais 21 a 30

Les exces sont les differences de CAGR au **Nasdaq conserve** sur les memes dates.
Priorite aux deux exces strictement positifs, puis score decroissant, puis premier numero.
Score = moyenne(exces developpement, exces selection) - 0.25 * ecart absolu des deux exces.
Le rapport lit les calculs sauves ; il ne choisit pas de nouveau gagnant.

{trial_table}

{motivations}

Developpement : 2019-06-03/2022-12-30. Selection : 2023-01-02/2024-12-31.
Le [protocole R3](../../research/SA15_GPT-6.1/round3/protocol.md) fixe ces conditions.
Toute l'histoire 2019-2026 avait deja ete examinee : aucune de ces periodes n'est un echantillon
vierge. Le controle final est retrospectif. Les calculs et archives des deux series precedentes
restent conserves.

Le DSR annonce **30 essais correles**, avec dispersion estimee sur
**{diagnostics["dispersion_curves"]} courbes** de selection
(source : {diagnostics["dispersion_source"]} ; ecart-type des Sharpe par seance :
{number(diagnostics["session_sharpe_std"], 6)}).
Anciens essais manquants : {diagnostics["previous_trials_missing"]}.
Chaque courbe R1/R2 disponible est utilisee ; une absence ne ramene jamais le nombre annonce
sous 30. Le DSR reste un diagnostic sans seuil supplementaire et ne corrige pas tous les choix
historiques du projet, dont l'univers et le changement successif des references.

## Interventions, frais et positions

{operations}

Un jour d'ordres est une date de fills distincte ; plusieurs transactions le meme jour
restent plusieurs ordres. L'entree initiale est incluse.
L'annualisation utilise le temps calendaire ecoule.
Les references sans details n'ont pas de dates d'ordres reconstituees.
Sur l'historique continu : **{number(full.loc[BOOK, "trade_days"], 0)} dates d'ordres
en {full_years:.2f} ans**. Sur le controle : **{number(final.loc[BOOK, "trade_days"], 0)}
dates en {final_years:.2f} ans**.
La cadence demande environ **{number(evaluations_per_year, 0)} evaluations par an**,
plus la premiere decision, meme lorsqu'aucun ordre n'est necessaire.

Poids reellement detenus, moyens sur toutes les seances, y compris l'attente du premier achat :

{position_table}

Les fractions moyennes ne sont pas des mesures de beta. Le cash residuel peut venir des parts
entieres et des frais ; une poche de cash tactique depend des signaux effectivement disponibles.

{economic_audit}
## Couts, incertitude et sensibilite

Aux frais doubles, le gagnant donne un rendement final net de **{percent(stress["net_return"])}**,
CAGR **{percent(stress["cagr"])}**, drawdown **{percent(stress["max_drawdown"])}** et
**{number(stress["costs_eur"], 0)} EUR** de frais.
L'ecart au Nasdaq aux frais standards devient **{stress_excess * 100:.2f} points**.
Ce test conservateur ne reestime aucun seuil ni aucun gagnant.

Bootstrap apparie du rendement actif moyen annualise final contre Nasdaq :
**{percent(uncertainty["annualised_mean_active_return"])}**,
intervalle 95 % **[{percent(uncertainty["lower_95"])} ; {percent(uncertainty["upper_95"])}]**.
Blocs circulaires de 20 seances, 2000 tirages, seed 61153.
Ce n'est ni un intervalle de CAGR ni une preuve independante : les periodes ont deja servi
aux recherches, et cet intervalle ne corrige pas les trente essais.

SUPPORTED_RETROSPECTIVE demande une surperformance nette sur continu ET controle,
un avantage persistant aux frais doubles et une borne bootstrap positive.
Un echec de croissance sur continu ou controle vaut NOT_SUPPORTED ;
un doute lie aux frais ou a l'intervalle vaut UNCERTAIN lorsque les deux exces sont positifs.
Aucun de ces statuts ne garantit une performance future.

[Frais doubles des configurations](robustness/costs_x2.csv) —
[Redemarrages depuis cash](robustness/starts.csv) —
[Diagnostic continu](robustness/full.csv).

## Rendements annuels de l'historique continu

{yearly_table}

La premiere et la derniere annee sont partielles. Les drawdowns sont quotidiens meme avec
decisions mensuelles. Chaque run commence en cash et n'herite pas des positions d'un autre run.
Le continu porte ensuite ses positions entre les annees : une egalite avec Nasdaq dans
la selection redemarree depuis cash ne signifie pas une egalite sur ces memes annees
du continu. Le garde-fou utilise le portefeuille effectivement detenu.

## Limites et sources

La concentration du Nasdaq peut dominer une allocation defensive pendant une longue hausse.
Sortir apres une baisse puis revenir apres un rebond consomme du capital et des frais.
Une rotation vers l'or peut profiter d'un regime particulier sans prouver un avantage durable.
L'or n'est pas un refuge garanti ; Xetra-Gold est un ETC et non un ETF UCITS.
Le petit univers de fonds encore disponibles a ete choisi retrospectivement.
Les cotations en EUR ne suppriment pas les risques de devises sous-jacents.
Les prix ajustes telecharges aujourd'hui peuvent etre revises ; ce ne sont pas des archives
de cours disponibles a chaque date historique. Le Sharpe utilise un taux sans risque nul.
Les trous et refus de signaux restent documentes dans les calculs sauvegardes.

Voir la [revue de litterature R3](../../research/SA15_GPT-6.1/round3/literature.md) :
[Clare et al., tendance et frequence](https://pure.york.ac.uk/portal/en/publications/breaking-into-the-blackbox-trend-following-stop-losses-and-the-fr/),
[Faber, allocation tactique](https://papers.ssrn.com/sol3/Papers.cfm?abstract_id=962461),
[Levine et Pedersen, filtres et couts](https://www.aqr.com/Insights/Research/Journal-Article/Which-Trend-Is-Your-Friend),
[Baur et Lucey, or et refuge](https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6288.2010.00244.x),
[forum sur les faux signaux et rebonds](https://www.reddit.com/r/TQQQ/comments/1q2nr5z/9sig_vs_dca_vs_200sma_one_shot_strategy_backtest/).
Ces sources motivent des hypotheses ; aucun de leurs rendements n'est attribue a SA15 R3.
Le forum fournit des objections pratiques, pas une validation scientifique.

## Reproduction

Depuis WSL/POSIX, dans un NOUVEAU dossier et avec le magasin isole deja valide :

    OUT=runs/sa15_r3_reproduction
    CANDIDATES=research/SA15_GPT-6.1/round3/candidates
    for N in $(seq 21 30); do
        SPEC=$(printf "%s/trial_%02d.json" "$CANDIDATES" "$N")
        uv run python scripts/SA15_run_gpt61_round3.py --candidate "$SPEC" --output "$OUT"
    done
    uv run python scripts/SA15_run_gpt61_round3.py --final --output "$OUT"
    uv run python scripts/SA15_run_gpt61_round3.py --robustness --output "$OUT" --workers 2
    uv run python scripts/SA15_report_gpt61_round3.py --output "$OUT"

Pour regenerer les exports seuls, sans nouveau backtest :

    uv run python scripts/SA15_report_gpt61_round3.py --output results/SA15_GPT-6.1_R3

Ce rapport ne modifie aucun candidat, aucune selection, aucun ordre ni aucune archive
financiere. reporting_manifest.json date le rendu et donne l'empreinte du source de rapport,
distinct du source financier archive avant les diagnostics.

[Tableau complet](comparison/full/summary.csv) — [Tableau final](comparison/final/summary.csv) —
[Courbes sauvegardees](comparison/full/equity.csv) — [Iterations](reported_iterations.csv) —
[Selection gelee](selected.json) — [Diagnostic DSR](selection_diagnostics.json) —
[Verdict machine](verdict.json).
"""
    validation = output / "validation.md"
    if validation.is_file():
        text += "\n[Verification et limites](validation.md).\n"
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
            "validation_note_sha256": (
                hashlib.sha256(validation.read_bytes()).hexdigest()
                if validation.is_file()
                else None
            ),
            "note": (
                "Saved-results reporting only; includes the existing validation economic "
                "section when present. Financial source archive remains untouched."
            ),
        },
    )
    print(f"wrote {output / 'study.md'}: {status}")


def main() -> None:
    """Render completed saved R3 results without a runner or market-data reader."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    report(parser.parse_args().output)


if __name__ == "__main__":
    main()
