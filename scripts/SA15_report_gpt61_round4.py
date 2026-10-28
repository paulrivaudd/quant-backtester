"""Render fifty frozen SA15 R4 designs from saved evidence only.

No runner, market store or trading policy is imported. Figures and diagnostics
cannot change the archived financial selection. All periods are retrospective.
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
DEFAULT_OUTPUT = ROOT / "results/SA15_GPT-6.1_R4"
PREVIOUS_OUTPUTS = (
    ROOT / "results/SA15_GPT-6.1",
    ROOT / "results/SA15_GPT-6.1_R2",
    ROOT / "results/SA15_GPT-6.1_R3",
)
BOOK = "SA15_GPT-6.1_R4"
BENCHMARK = "Nasdaq_buy_hold"
REFERENCES = (BENCHMARK, "SP500_buy_hold", "Gold_buy_hold", "Nasdaq_Gold_50_50", "Tech_buy_hold")
PERIODS = ("choice", "final", "full")
ANALYTICS = AnalyticsConfig(sessions_per_year=252, risk_free_rate=0.0, minimum_sessions=60)
LABELS = {
    BOOK: "SA15 retenue",
    BENCHMARK: "Nasdaq conservé",
    "SP500_buy_hold": "S&P 500 conservé",
    "Gold_buy_hold": "Or conservé (ETC)",
    "Nasdaq_Gold_50_50": "50/50 initial Nasdaq/or",
    "Tech_buy_hold": "Technologie conservée",
}
ASSET_NAMES = {
    "ETF_NASDAQ": "Nasdaq 100",
    "ETF_GOLD": "Or (ETC Xetra-Gold)",
    "ETF_SP500_PEA": "S&P 500",
    "ETF_MONETARY_EUR": "Monétaire EUR",
    "ETF_EURO_GOV": "Souverains mondiaux couverts EUR",
    "ETF_WORLD": "Actions mondiales",
    "ETF_EMERGING": "Actions émergentes",
    "ETF_COMMODITY": "Matières premières",
    "ETF_US_TECH": "Technologie américaine",
    "ETF_WORLD_HEALTH": "Santé mondiale",
    "ETF_WORLD_UTILITIES": "Services collectifs mondiaux",
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


def percentage_points(value: object) -> str:
    """Format a difference of fractional returns in percentage points."""
    if value is None or not math.isfinite(float(value)):
        return "n.d."
    return f"{float(value) * 100:.2f} pp"


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
    rng = np.random.default_rng(61154)
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
        "seed": 61154,
        "block_sessions": block,
        "replications": replications,
    }


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
                book_label(name),
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


def verify_run(folder: Path) -> None:
    """Verify saved financial checksums and both curves, without market access."""
    cache_path = folder / "cache.json"
    if cache_path.is_file():
        artifacts = read_json(cache_path).get("artifacts", {})
        if not artifacts:
            raise ValueError(f"missing saved financial checksums: {folder}")
        for name, digest in artifacts.items():
            path = folder / name
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError(f"saved financial artifact differs: {path}")
    net = load_equity(folder / "equity.csv")
    gross = load_equity(folder / "gross_equity.csv")
    if not net.index.equals(gross.index):
        raise ValueError("gross and net saved sessions differ")
    metrics = read_json(folder / "metrics.json")
    for name, curve in (("net_return", net), ("gross_return", gross)):
        if not math.isclose(
            float(metrics[name]),
            float(curve.iloc[-1] / curve.iloc[0] - 1.0),
            rel_tol=0.0,
            abs_tol=1e-10,
        ):
            raise ValueError(f"saved {name} differs from its curve: {folder}")


def frozen_selection(output: Path) -> tuple[dict, dict, dict]:
    """Verify the frozen candidate, raw evidence hashes and complete parameters."""
    selected = read_json(output / "selected.json")
    if selected["total_trials"] != 80 or selected["round_trials"] != 50:
        raise ValueError("R4 must declare fifty new and eighty cumulative designs")
    digest = hashlib.sha256((output / "selected.json").read_bytes()).hexdigest()
    if (output / "selected.sha256").read_text(encoding="utf-8").strip() != digest:
        raise ValueError("frozen selection checksum differs")
    spec = selected["candidate"]
    trial = spec["number"]
    if isinstance(trial, bool) or not isinstance(trial, int) or not 31 <= trial <= 80:
        raise ValueError("R4 frozen trial must be from 31 to 80")
    folder = output / f"trial_{trial:02d}"
    if read_json(folder / "candidate.json") != spec:
        raise ValueError("candidate differs from frozen selection")
    for name in ("candidate", "selection"):
        if (
            hashlib.sha256((folder / f"{name}.json").read_bytes()).hexdigest()
            != selected[f"{name}_sha256"]
        ):
            raise ValueError(f"frozen {name} checksum differs")
    definition = read_json(output / "final" / BOOK / "strategy.json")
    canonical = json.dumps(definition, sort_keys=True, separators=(",", ":"))
    if hashlib.sha256(canonical.encode()).hexdigest() != selected["fingerprint"]:
        raise ValueError("final strategy fingerprint differs")
    if (
        definition["parameters"] != selected["parameters"]
        or spec["parameters"] != selected["parameters"]
    ):
        raise ValueError("complete frozen parameters differ")
    return selected, definition, read_json(output / "final" / BOOK / "configuration.json")


def result_folder(output: Path, period: str, name: str, trial: int) -> Path:
    """Resolve only the R4 layout; choice is a single continuous portfolio."""
    if period not in PERIODS:
        raise ValueError("unknown comparison period")
    if period == "full":
        return output / "full" / name
    if name == BOOK:
        return (
            output / f"trial_{trial:02d}/choice" if period == "choice" else output / "final" / BOOK
        )
    return output / "references" / period / name


def book_label(name: str) -> str:
    """Name frozen companions explicitly without relabeling them as winners."""
    if name.startswith("Companion_"):
        return "Compagnon " + name.removeprefix("Companion_")
    return LABELS.get(name, name)


def comparison_runs(
    output: Path, period: str, trial: int, parameters: dict
) -> dict[str, tuple[Path, dict]]:
    """Include independently frozen companions in final/full descriptive views."""
    runs = {
        name: (result_folder(output, period, name, trial), parameters)
        for name in (BOOK, *REFERENCES)
    }
    path = output / "companions_frozen.json"
    if period == "choice" or not path.is_file():
        return runs
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if (output / "companions_frozen.sha256").read_text().strip() != digest:
        raise ValueError("frozen companion checksum differs")
    saved = read_json(path)
    if saved["expected_winner"]["number"] != trial:
        raise ValueError("companion comparison disagrees with the frozen main winner")
    names = []
    for item in saved["companions"]:
        name = f"Companion_{item['number']}"
        names.append(name)
        runs[name] = (
            output / f"companions/trial_{item['number']:02d}" / period,
            item["candidate"]["parameters"],
        )
    order = [BENCHMARK, "Tech_buy_hold", *names, BOOK]
    order.extend(name for name in runs if name not in order)
    return {name: runs[name] for name in order}


def render_comparison(output: Path, period: str, trial: int, parameters: dict) -> pd.DataFrame:
    """Plot saved net NAV, relative Nasdaq wealth and actual daily drawdown."""
    curves, gross_curves, rows = {}, {}, {}
    for name, (folder, local_parameters) in comparison_runs(
        output, period, trial, parameters
    ).items():
        verify_run(folder)
        curves[name] = load_equity(folder / "equity.csv")
        gross_curves[name] = load_equity(folder / "gross_equity.csv")
        rows[name] = read_json(folder / "metrics.json")
        rows[name].update(operational_metrics(folder, curves[name], local_parameters))
    benchmark = curves[BENCHMARK]
    if any(not curve.index.equals(benchmark.index) for curve in curves.values()):
        raise ValueError("comparison dates differ; no filling or intersection")
    equity, gross = pd.DataFrame(curves), pd.DataFrame(gross_curves)
    relative = equity.div(equity.iloc[0]).div(benchmark / benchmark.iloc[0], axis=0)
    for name, curve in curves.items():
        comparison = alpha_vs_benchmark(analytics_copy(curve), analytics_copy(benchmark), ANALYTICS)
        rows[name].update(
            alpha_vs_nasdaq=comparison.alpha_annualised,
            beta_vs_nasdaq=comparison.beta,
            relative_wealth_return=float(relative[name].iloc[-1] - 1.0),
            outperformance_vs_nasdaq=comparison.outperformance,
        )
    table = pd.DataFrame.from_dict(rows, orient="index").rename_axis("book")
    folder = output / "comparison" / period
    folder.mkdir(parents=True, exist_ok=True)
    table.to_csv(folder / "summary.csv")
    equity.to_csv(folder / "equity.csv", index_label="session_date")
    gross.to_csv(folder / "gross_equity.csv", index_label="session_date")
    relative.to_csv(folder / "relative_wealth.csv", index_label="session_date")
    returns = equity.pct_change(fill_method=None).fillna(0.0)
    ((1 + returns).groupby(returns.index.year).prod() - 1).to_csv(
        folder / "yearly.csv", index_label="year"
    )
    figure, axes = plt.subplots(3, 1, figsize=(12, 10), sharex=True, height_ratios=[2, 1, 1])
    for name in equity:
        axes[0].plot(
            equity.index, equity[name] / equity[name].iloc[0] * 100, label=book_label(name)
        )
        axes[1].plot(relative.index, relative[name])
        axes[2].plot(equity.index, equity[name] / equity[name].cummax() - 1)
    axes[0].set(title=f"SA15 R4 — {period} — net des frais", ylabel="Capital, base 100")
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


def trial_rows(output: Path, *, require_complete: bool = True) -> list[dict]:
    """Read saved scores and continuous choice metrics, including every loser."""
    rows = []
    for trial in range(31, 81):
        folder = output / f"trial_{trial:02d}"
        if not (folder / "selection.json").is_file():
            continue
        spec, saved = read_json(folder / "candidate.json"), read_json(folder / "selection.json")
        if spec["number"] != trial:
            raise ValueError("candidate number differs from folder")
        verify_run(folder / "choice")
        if saved["metrics"]["choice"] != read_json(folder / "choice/metrics.json"):
            raise ValueError("choice metrics differ from archived selection")
        if (
            saved["candidate_sha256"]
            != hashlib.sha256((folder / "candidate.json").read_bytes()).hexdigest()
        ):
            raise ValueError("candidate checksum differs from selection evidence")
        row = {
            "trial": trial,
            "reason": spec["reason"],
            "schedule": spec["schedule"],
            "mode": spec["parameters"]["mode"],
            **{
                key: saved[key]
                for key in (
                    "score",
                    "qualified",
                    "excess_choice",
                    "excess_validation",
                    "drawdown_depth",
                    "trade_days_per_year",
                )
            },
        }
        for period in ("choice", "development", "validation"):
            row.update(
                {f"{period}_{key}": value for key, value in saved["metrics"][period].items()}
            )
        rows.append(row)
    if not rows or (require_complete and len(rows) != 50):
        raise ValueError("report requires all fifty completed R4 candidates")
    return rows


def pareto_front(rows: list[dict]) -> list[int]:
    """Keep nondominated CAGR, drawdown depth and actual intervention frequency."""
    result = []
    for row in rows:
        dominated = any(
            other["choice_cagr"] >= row["choice_cagr"]
            and other["drawdown_depth"] <= row["drawdown_depth"]
            and other["trade_days_per_year"] <= row["trade_days_per_year"]
            and (
                other["choice_cagr"] > row["choice_cagr"]
                or other["drawdown_depth"] < row["drawdown_depth"]
                or other["trade_days_per_year"] < row["trade_days_per_year"]
            )
            for other in rows
        )
        if not dominated:
            result.append(row["trial"])
    return result


def render_frontier(output: Path, rows: list[dict], trial: int) -> list[int]:
    """Show all fifty designs and Pareto points without replacing the winner."""
    table = pd.DataFrame(rows)
    front = pareto_front(rows)
    table["pareto"] = table["trial"].isin(front)
    table.to_csv(output / "reported_iterations.csv", index=False)
    table.loc[table["pareto"]].to_csv(output / "pareto.csv", index=False)
    figure, axis = plt.subplots(figsize=(11, 7))
    points = axis.scatter(
        table["drawdown_depth"],
        table["choice_cagr"],
        c=table["trade_days_per_year"],
        cmap="viridis_r",
        s=55,
        alpha=0.85,
    )
    frontier = table[table["pareto"]]
    axis.scatter(
        frontier["drawdown_depth"],
        frontier["choice_cagr"],
        facecolors="none",
        edgecolors="black",
        s=120,
        label="Frontière de Pareto (3 critères)",
    )
    annotation_ids = {trial}
    manifest = output / "companions_frozen.json"
    if manifest.is_file():
        annotation_ids.update(item["number"] for item in read_json(manifest)["companions"])
    annotation_ids.update(
        [
            int(table.loc[table["choice_cagr"].idxmax(), "trial"]),
            int(table.loc[table["drawdown_depth"].idxmin(), "trial"]),
            int(table.loc[table["trade_days_per_year"].idxmin(), "trial"]),
        ]
    )
    annotated = table.loc[table["trial"].isin(annotation_ids)]
    for _, row in annotated.iterrows():
        axis.annotate(
            str(int(row["trial"])),
            (row["drawdown_depth"], row["choice_cagr"]),
            xytext=(5, 5),
            textcoords="offset points",
            fontsize=8,
        )
    winner = table.set_index("trial").loc[trial]
    axis.scatter(
        [winner["drawdown_depth"]],
        [winner["choice_cagr"]],
        marker="*",
        s=280,
        c="crimson",
        label=f"Choix gelé : {trial}",
    )
    reference = read_json(output / "references/choice" / BENCHMARK / "metrics.json")
    axis.scatter(
        [abs(reference["max_drawdown"])],
        [reference["cagr"]],
        marker="X",
        c="black",
        s=90,
        label="Nasdaq conservé",
    )
    axis.axvline(0.25, color="crimson", linestyle=":", linewidth=1, label="Cible drawdown 25 %")
    axis.set(
        title="SA15 R4 — 50 designs — portefeuille continu 2019-2024",
        xlabel="Profondeur du drawdown quotidien",
        ylabel="CAGR net",
    )
    axis.xaxis.set_major_formatter(PercentFormatter(1.0))
    axis.yaxis.set_major_formatter(PercentFormatter(1.0))
    axis.grid(alpha=0.2)
    axis.legend(fontsize=8)
    figure.colorbar(points, ax=axis, label="Dates de transactions / an")
    figure.tight_layout()
    figure.savefig(output / "frontier.png", dpi=160)
    plt.close(figure)
    return front


def validation_slice(curve: pd.Series) -> pd.Series:
    """Retain the preceding close as anchor without resetting shares or costs."""
    before = curve[curve.index < pd.Timestamp("2023-01-02")]
    selected = curve[
        (curve.index >= pd.Timestamp("2023-01-02")) & (curve.index <= pd.Timestamp("2024-12-31"))
    ]
    if selected.empty:
        raise ValueError("no 2023-2024 observations for DSR")
    return pd.concat([before.iloc[-1:], selected]) if not before.empty else selected


def selection_diagnostics(
    output: Path, rows: list[dict], previous_outputs: tuple[Path, ...] = PREVIOUS_OUTPUTS
) -> dict:
    """Declare eighty correlated designs, with prior resets disclosed explicitly."""
    round_curves = {
        row["trial"]: validation_slice(
            load_equity(output / f"trial_{row['trial']:02d}/choice/equity.csv")
        )
        for row in rows
    }
    previous = [
        (number, root / f"trial_{number:02d}/validation/equity.csv")
        for root, numbers in zip(
            previous_outputs, (range(1, 11), range(11, 21), range(21, 31)), strict=True
        )
        for number in numbers
    ]
    available = [(number, path) for number, path in previous if path.is_file()]
    missing = [number for number, path in previous if not path.is_file()]
    curves = [*(load_equity(path) for _, path in available), *round_curves.values()]
    sharpes = [session_sharpe(curve, ANALYTICS) for curve in curves]
    usable = [value for value in sharpes if value is not None]
    dispersion = float(np.std(usable, ddof=1)) if len(usable) > 1 else 0.0
    return {
        "total_trials_declared": 80,
        "round_four_trials": len(round_curves),
        "dispersion_curves": len(curves),
        "usable_session_sharpes": len(usable),
        "previous_trials_available": [number for number, _ in available],
        "previous_trials_missing": missing,
        "session_sharpe_std": dispersion,
        "dispersion_source": "available_R1_R2_R3_reset_validation_plus_R4_continuous_slices",
        "validation_dsr": {
            str(trial): deflated_sharpe_probability(
                curve, ANALYTICS, trials=80, trial_sharpe_std=dispersion
            )
            for trial, curve in round_curves.items()
        },
        "note": (
            "80 correlated designs. R1-R3 validation books reset from cash; "
            "R4 validation slices the continuous choice book. This approximate "
            "dispersion mixes different start conventions. DSR concerns absolute "
            "Sharpe, not Nasdaq outperformance; missing curves do not reduce "
            "the declared trial count. Historical design and universe choices "
            "remain uncorrected."
        ),
    }


def hypothesis_status(
    full: dict, final: dict, stress_full: dict, stress_final: dict, lower_95: float
) -> tuple[str, list[str]]:
    """Apply the preregistered joint growth, risk and operational objective."""
    failures = []
    for name, values in (("continu", full), ("contrôle chronologique", final)):
        if values["excess"] <= 0:
            failures.append(f"pas de surperformance nette du Nasdaq sur {name}")
    if failures:
        return "NOT_SUPPORTED", failures
    for name, values in (("continu", full), ("contrôle chronologique", final)):
        if abs(values["max_drawdown"]) > 0.25:
            failures.append(f"drawdown supérieur à 25 % sur {name}")
        if values["trade_days_per_year"] > 4:
            failures.append(f"plus de quatre dates de transactions par an sur {name}")
    for name, values in (("continu", stress_full), ("contrôle chronologique", stress_final)):
        if values["excess"] <= 0:
            failures.append(f"avantage absent aux frais doubles sur {name}")
    if lower_95 <= 0:
        failures.append("intervalle bootstrap actif comprenant zéro")
    return ("UNCERTAIN", failures) if failures else ("SUPPORTED_RETROSPECTIVE", [])


def retained_rule(parameters: dict) -> str:
    """Explain the saved mode and modifiers, without loading live defaults."""
    required = {"mode", "core_id", "risky_ids", "allocation_mode"}
    if not required <= parameters.keys():
        return "Les paramètres complets sauvegardés ci-dessous définissent la règle."

    def names(ids: list[str]) -> str:
        return ", ".join(ASSET_NAMES.get(name, name) for name in ids)

    descriptions = {
        "balanced": (
            "Le bloc offensif détient les lignes disponibles sans filtre de signe du momentum."
        ),
        "rotate": (
            "Le bloc offensif classe les lignes admissibles par momentum logarithmique "
            "pondéré ; préférence pour le cœur et bonus aux positions réellement "
            "détenues affectent le classement."
        ),
        "ensemble": (
            "La fraction du cœur dépend des votes positifs pondérés de tendance, "
            "avec plancher déclaré et éventuelle reprise courte."
        ),
        "vol_control": (
            "Le bloc offensif part du cœur puis réduit son poids selon le plafond de risque estimé."
        ),
    }
    core = ASSET_NAMES.get(parameters["core_id"], parameters["core_id"])
    mode = parameters["mode"]
    pieces = [
        f"Mode **{mode}**. {descriptions.get(mode, 'Voir la définition sauvegardée.')}",
        f"Cœur : {core}. Univers offensif : {names(parameters['risky_ids'])}.",
        f"Allocation : {parameters['allocation_mode']}.",
    ]
    if parameters.get("allocation_mode") == "fixed":
        pieces.append(f"Poids fixes alignés sur cet univers : {parameters.get('fixed_weights')}.")
    pieces.extend(
        [
            f"Horizons : {parameters.get('momentum_lookbacks')} ; "
            f"poids : {parameters.get('momentum_weights')}.",
            "Le nombre et les poids réellement détenus sont publiés plus bas.",
            f"Défense : {names(parameters.get('defensive_ids', [])) or 'aucune ligne classée'}, "
            f"jusqu'à {parameters.get('defensive_top_k')} lignes de momentum positif ; "
            "repli monétaire si le rendement déclaré est positif, sinon cash.",
        ]
    )
    if mode == "balanced":
        pieces.append(
            f"Les {len(parameters['risky_ids'])} lignes offensives configurées sont "
            "détenues si disponibles ; top_k et core_floor ne pilotent pas ce mode."
        )
        if (
            parameters.get("target_volatility", 0) == 0
            and not parameters.get("defensive_ids")
            and not parameters.get("canary_ids")
        ):
            pieces.append(
                "Dans cette configuration, horizons de classement, votes, bonus "
                "de maintien et défense classée sont inactifs ; la cible de "
                "volatilité nulle désactive aussi le contrôle de risque. "
                "Les poids fixes et la bande de dérive pilotent les transactions."
            )
    elif mode == "rotate":
        pieces.append(
            f"Jusqu'à {parameters.get('top_k')} lignes sont classées ; "
            f"le cœur réserve {percent(parameters.get('core_floor', 0))} avant "
            "le canari et le plafond de risque, avec au plus trois lignes offensives."
        )
    elif mode == "ensemble":
        pieces.append(
            f"Votes : {parameters.get('trend_kind')}, plancher du cœur "
            f"{percent(parameters.get('core_floor', 0))} avant canari et risque."
        )
        if parameters.get("recovery_lookback", 0) > 0:
            pieces.append(
                f"Un rendement sur {parameters['recovery_lookback']} séances "
                f"strictement supérieur à {percent(parameters.get('recovery_threshold', 0))} "
                "rétablit les votes avant canari et réduction du risque."
            )
    if parameters.get("canary_ids"):
        pieces.append(
            f"Canaris : {names(parameters['canary_ids'])} ; largeur minimale "
            f"{percent(parameters.get('canary_min_breadth'))}. "
            "Un canari manquant compte comme négatif."
        )
    if parameters.get("target_volatility", 0) > 0:
        pieces.extend(
            [
                "Plafond de risque du bloc offensif "
                f"{percent(parameters['target_volatility'])}, fenêtres "
                f"{parameters.get('volatility_windows')}.",
                "L'estimation somme poids x maximum des volatilités historiques ; "
                "elle exclut la défense et n'est pas une cible de volatilité totale.",
            ]
        )
    pieces.extend(
        [
            f"Bande de rééquilibrage {percent(parameters.get('rebalance_band'))}, "
            f"bonus de maintien {parameters.get('switch_buffer')}.",
            "Les lignes absentes sont exclues selon les contrats de signaux, "
            "sans imputation. Aucun modèle ajusté, short ou levier.",
        ]
    )
    return " ".join(pieces)


def position_table(output: Path, trial: int) -> str:
    """Report observed weights, including residual cash, for the retained book."""
    rows = []
    for period in PERIODS:
        weights = pd.read_csv(
            result_folder(output, period, BOOK, trial) / "weights.csv", index_col=0
        )
        for name in weights:
            if weights[name].abs().max() > 0:
                rows.append(
                    [period, ASSET_NAMES.get(name, name), name, percent(weights[name].mean())]
                )
        rows.append(
            [
                period,
                "Cash résiduel",
                "CASH",
                percent((1 - weights.sum(axis=1)).clip(lower=0).mean()),
            ]
        )
    return markdown_table(["Période", "Position", "Identifiant", "Poids moyen"], rows)


def robustness_tables(output: Path, rows: list[dict]) -> tuple[str, str]:
    """Read all fifty cost replays and twenty-four genuinely restarted portfolios."""
    cost_rows = []
    reference = read_json(output / "references/choice" / BENCHMARK / "metrics.json")
    for row in rows:
        folder = output / f"trial_{row['trial']:02d}/costs_x2/choice"
        verify_run(folder)
        metrics = read_json(folder / "metrics.json")
        cost_rows.append(
            {
                "trial": row["trial"],
                "normal_net_return": row["choice_net_return"],
                "stress_net_return": metrics["net_return"],
                "stress_excess_vs_standard_nasdaq": metrics["net_return"] - reference["net_return"],
                "stress_costs_eur": metrics["costs_eur"],
            }
        )
    pd.DataFrame(cost_rows).to_csv(output / "reported_costs_x2.csv", index=False)
    starts = pd.read_csv(output / "robustness/starts.csv")
    expected = {BOOK, *REFERENCES}
    display = []
    for start, frame in starts.groupby("start"):
        if set(frame["book"]) != expected or len(frame) != 6:
            raise ValueError("cash-start diagnostic needs the winner and five matched references")
        winner = frame.set_index("book").loc[BOOK]
        nasdaq = frame.set_index("book").loc[BENCHMARK]
        display.append(
            [
                str(start),
                percent(winner["net_return"]),
                percent(nasdaq["net_return"]),
                percentage_points(winner["net_return"] - nasdaq["net_return"]),
                percent(winner["max_drawdown"]),
                number(winner["trade_days_per_year"]),
            ]
        )
    if len(display) != 4:
        raise ValueError("four matched cash-start dates are required")
    return markdown_table(
        ["Départ cash", "SA15 net", "Nasdaq net", "Écart", "DD SA15", "Dates/an"], display
    ), "[50 replays aux frais doubles](reported_costs_x2.csv)"


def verify_batch_manifests(output: Path, rows: list[dict]) -> dict:
    """Check preannounced batch candidates against their archived run definitions."""
    paths = sorted((output / "batches").glob("batch_*.json"))
    if not paths:
        return {"batches_available": 0, "candidates_verified": 0}
    seen = set()
    for path in paths:
        batch = read_json(path)
        candidates = batch["candidates"]
        numbers = batch["numbers"]
        if len(candidates) != 10 or len(numbers) != 10:
            raise ValueError("each announced batch must contain exactly ten designs")
        if [candidate["number"] for candidate in candidates] != numbers:
            raise ValueError("batch numbers differ from its candidate definitions")
        for candidate in candidates:
            number = candidate["number"]
            if number in seen:
                raise ValueError("candidate appears in multiple announced batches")
            seen.add(number)
            if candidate != read_json(output / f"trial_{number:02d}/candidate.json"):
                raise ValueError("archived candidate differs from preannounced batch")
    if seen != {row["trial"] for row in rows}:
        raise ValueError("announced batches do not cover the reported candidates")
    return {"batches_available": len(paths), "candidates_verified": len(seen)}


def companion_section(output: Path, winner: int) -> str:
    """Describe independently frozen risk/frequency companions without selection."""
    path = output / "companions_frozen.json"
    if not path.is_file():
        return "Aucun portefeuille compagnon archivé ; le choix gelé reste seul évalué."
    saved = read_json(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if (output / "companions_frozen.sha256").read_text().strip() != digest:
        raise ValueError("frozen companion checksum differs")
    if saved["expected_winner"]["number"] != winner:
        raise ValueError("descriptive companions disagree with the frozen winner")
    companions = saved["companions"]
    numbers = [item["number"] for item in companions]
    if len(numbers) > 2 or len(set(numbers)) != len(numbers) or winner in numbers:
        raise ValueError("companions must be distinct from each other and the winner")
    display, exports, descriptions = [], [], []
    for item in companions:
        trial = item["number"]
        original = output / f"trial_{trial:02d}"
        for name in ("candidate", "selection"):
            if (
                hashlib.sha256((original / f"{name}.json").read_bytes()).hexdigest()
                != item[f"{name}_sha256"]
            ):
                raise ValueError("companion source evidence differs from frozen manifest")
        if read_json(original / "candidate.json") != item["candidate"]:
            raise ValueError("companion candidate differs from frozen manifest")
        descriptions.append(
            f"Essai {trial}, cadence {item['candidate']['schedule']}, "
            + retained_rule(item["candidate"]["parameters"])
        )
        for period in ("full", "final"):
            regular = output / f"companions/trial_{trial:02d}" / period
            doubled = output / f"companions/trial_{trial:02d}" / f"{period}_costs_x2"
            verify_run(regular)
            verify_run(doubled)
            definition = read_json(regular / "strategy.json")
            canonical = json.dumps(definition, sort_keys=True, separators=(",", ":"))
            if hashlib.sha256(canonical.encode()).hexdigest() != item["fingerprint"]:
                raise ValueError("companion replay fingerprint differs")
            normal, stress = (
                read_json(regular / "metrics.json"),
                read_json(doubled / "metrics.json"),
            )
            benchmark = read_json(result_folder(output, period, BENCHMARK, winner) / "metrics.json")
            if period == "full" and normal["trade_days"] == 1:
                descriptions.append(
                    f"Essai {trial} : une seule date de transactions sur le continu, "
                    "l'achat initial. Le résultat équivaut donc à conserver "
                    "l'allocation achetée ; ce n'est pas un alpha de rotation active."
                )
            if (
                period == "full"
                and abs(normal["max_drawdown"]) <= 0.25
                and abs(stress["max_drawdown"]) > 0.25
            ):
                descriptions.append(
                    f"Essai {trial} : le drawdown normal vaut "
                    f"{normal['max_drawdown'] * 100:.5f} %, contre "
                    f"{stress['max_drawdown'] * 100:.5f} % aux frais doubles. "
                    "La borne historique de 25 % est donc fragile et franchie "
                    "strictement sous ce stress, même si l'avantage de rendement demeure."
                )
            display.append(
                [
                    str(trial),
                    ", ".join(item["criteria"]),
                    period,
                    percent(normal["net_return"]),
                    percentage_points(normal["net_return"] - benchmark["net_return"]),
                    percent(normal["max_drawdown"]),
                    number(normal["trade_days_per_year"]),
                    percent(stress["net_return"]),
                    percentage_points(stress["net_return"] - benchmark["net_return"]),
                    percent(stress["max_drawdown"]),
                ]
            )
            for multiplier, metrics in ((1, normal), (2, stress)):
                exports.append(
                    {"trial": trial, "period": period, "cost_multiplier": multiplier, **metrics}
                )
    pd.DataFrame(exports).to_csv(output / "reported_companions.csv", index=False)
    explanation = (
        "Ces portefeuilles décrivent les extrema risque/interventions parmi les candidats "
        "qualifiés sur le choix 2019-2024. Ils ont été gelés indépendamment avant les "
        "contrôles, ne remplacent jamais le gagnant et ne modifient pas son verdict. "
        "Leurs replays ne sont pas de nouveaux designs. Les critères anglais signifient "
        "minimum_interventions = moins de dates de fills ; minimum_drawdown = moindre baisse."
    )
    if not companions:
        return explanation + " Aucun compagnon distinct du gagnant."
    table = markdown_table(
        [
            "Essai",
            "Critère gelé",
            "Période",
            "Net x1",
            "Écart Nasdaq",
            "DD x1",
            "Dates/an",
            "Net x2",
            "Écart x2",
            "DD x2",
        ],
        display,
    )
    return explanation + "\n\n" + table + "\n\n" + "\n\n".join(descriptions)


def availability_section(output: Path, trial: int) -> str:
    """Distinguish unavailable historical windows from economic risk signals."""
    rows = []
    unavailable = []
    for period in PERIODS:
        path = result_folder(output, period, BOOK, trial) / "decisions.csv"
        if not path.is_file():
            unavailable.append(period)
            continue
        decisions = pd.read_csv(path)
        events: dict[tuple[str, str], list[str]] = {}
        for _, record in decisions.iterrows():
            skipped = json.loads(record["skipped"])
            for instrument, status in skipped.items():
                events.setdefault((instrument, str(status)), []).append(str(record["session_date"]))
        for (instrument, status), dates in events.items():
            rows.append(
                [
                    period,
                    ASSET_NAMES.get(instrument, instrument),
                    status,
                    str(len(dates)),
                    ", ".join(dates),
                ]
            )
    explanation = (
        "NON_CONSECUTIVE_HISTORY indique une fenêtre historique incomplète, "
        "pas une volatilité économique élevée. La politique figée exclut la ligne "
        "dont les entrées obligatoires manquent et peut donc déplacer le capital "
        "vers la défense. Les mouvements qui en résultent ne sont pas attribués "
        "à une prévision de marché. Aucun trou n'est comblé et aucun résultat rejoué."
    )
    if unavailable:
        explanation += " Traces indisponibles dans les archives : " + ", ".join(unavailable) + "."
    if rows:
        explanation += "\n\n" + markdown_table(
            ["Période", "Instrument", "Motif sauvegardé", "Décisions", "Dates"],
            rows,
        )
    else:
        explanation += " Aucun motif de rejet de signal présent dans les traces disponibles."
    audit = output / "operational_audit.md"
    if audit.is_file():
        explanation += (
            "\n\n[Audit des transactions et des fenêtres manquantes](operational_audit.md)."
        )
    return explanation


def report(output: Path, *, previous_outputs: tuple[Path, ...] = PREVIOUS_OUTPUTS) -> None:
    """Render the complete frozen study with no runner, signal or market-data call."""
    selected, definition, configuration = frozen_selection(output)
    trial, parameters = selected["candidate"]["number"], definition["parameters"]
    rows = trial_rows(output)
    batches = verify_batch_manifests(output, rows)
    write_json(output / "batch_manifest_validation.json", batches)
    winner_row = next(row for row in rows if row["trial"] == trial)
    if not math.isclose(winner_row["score"], selected["score"], rel_tol=0, abs_tol=1e-14):
        raise ValueError("frozen winner score differs from archived trial")
    diagnostics = selection_diagnostics(output, rows, previous_outputs)
    front = render_frontier(output, rows, trial)
    tables = {period: render_comparison(output, period, trial, parameters) for period in PERIODS}
    final_curves = pd.read_csv(
        output / "comparison/final/equity.csv", index_col=0, parse_dates=True
    )
    uncertainty = bootstrap_interval(final_curves[BOOK], final_curves[BENCHMARK])
    stress = {}
    plain = {}
    for period in ("full", "final"):
        folder = output / period / "costs_x2"
        verify_run(folder)
        stress[period] = read_json(folder / "metrics.json")
        plain[period] = tables[period].loc[BOOK].to_dict()
        benchmark_return = float(tables[period].loc[BENCHMARK, "net_return"])
        stress[period]["excess"] = stress[period]["net_return"] - benchmark_return
        plain[period]["excess"] = plain[period]["net_return"] - benchmark_return
    status, reasons = hypothesis_status(
        plain["full"], plain["final"], stress["full"], stress["final"], uncertainty["lower_95"]
    )
    write_json(output / "selection_diagnostics.json", diagnostics)
    write_json(output / "final/uncertainty.json", uncertainty)
    write_json(
        output / "verdict.json",
        {
            "status": status,
            "benchmark": BENCHMARK,
            "reasons": reasons,
            "full_excess_total_return": plain["full"]["excess"],
            "final_excess_total_return": plain["final"]["excess"],
            "stressed_full_excess_vs_standard_nasdaq": stress["full"]["excess"],
            "stressed_final_excess_vs_standard_nasdaq": stress["final"]["excess"],
            "selected_trial": trial,
        },
    )
    best_return = min(rows, key=lambda row: (-row["choice_cagr"], row["trial"]))
    lowest_risk = min(
        rows, key=lambda row: (row["drawdown_depth"], -row["choice_cagr"], row["trial"])
    )
    fewest_trades = min(
        rows, key=lambda row: (row["trade_days_per_year"], -row["choice_cagr"], row["trial"])
    )
    alternatives = markdown_table(
        ["Lecture du choix", "Essai", "CAGR net", "Drawdown", "Dates/an", "Qualifié"],
        [
            [
                label,
                str(row["trial"]),
                percent(row["choice_cagr"]),
                percent(-row["drawdown_depth"]),
                number(row["trade_days_per_year"]),
                "oui" if row["qualified"] else "non",
            ]
            for label, row in (
                ("Choix gelé", winner_row),
                ("Meilleur rendement", best_return),
                ("Plus faible drawdown", lowest_risk),
                ("Moins de dates d'ordres", fewest_trades),
            )
        ],
    )
    trial_table = markdown_table(
        [
            "Essai",
            "Mode",
            "Cadence",
            "CAGR choix",
            "Excès Nasdaq",
            "DD",
            "Dates/an",
            "Excès 2023-24",
            "Qualifié",
            "Score",
            "DSR",
        ],
        [
            [
                str(row["trial"]),
                row["mode"],
                row["schedule"],
                percent(row["choice_cagr"]),
                percentage_points(row["excess_choice"]),
                percent(-row["drawdown_depth"]),
                number(row["trade_days_per_year"]),
                percentage_points(row["excess_validation"]),
                "oui" if row["qualified"] else "non",
                number(row["score"], 4),
                number(diagnostics["validation_dsr"][str(row["trial"])], 3),
            ]
            for row in rows
        ],
    )
    parameter_table = markdown_table(
        ["Paramètre gelé", "Valeur effective"],
        [[name, json.dumps(value, ensure_ascii=False)] for name, value in parameters.items()],
    )
    operations = markdown_table(
        [
            "Période",
            "Jours de fills",
            "Dates/an",
            "Ordres/an",
            "Vérifications/an",
            "Rotation/an",
            "Frais EUR",
            "Rejets",
        ],
        [
            [
                period,
                str(int(table.loc[BOOK, "trade_days"])),
                number(table.loc[BOOK, "trade_days_per_year"]),
                number(table.loc[BOOK, "fills_per_year"]),
                number(table.loc[BOOK].get("decision_days_per_year")),
                number(table.loc[BOOK, "turnover_per_year"]),
                number(table.loc[BOOK, "costs_eur"], 0),
                str(int(table.loc[BOOK, "rejects"])),
            ]
            for period, table in tables.items()
        ],
    )
    stress_table = markdown_table(
        ["Période", "Net x1", "Net x2", "Nasdaq x1", "Écart x2", "DD x2", "Frais x2 EUR"],
        [
            [
                period,
                percent(plain[period]["net_return"]),
                percent(stress[period]["net_return"]),
                percent(tables[period].loc[BENCHMARK, "net_return"]),
                percentage_points(stress[period]["excess"]),
                percent(stress[period]["max_drawdown"]),
                number(stress[period]["costs_eur"], 0),
            ]
            for period in ("full", "final")
        ],
    )
    starts_table, costs_link = robustness_tables(output, rows)
    companions = companion_section(output, trial)
    yearly = pd.read_csv(output / "comparison/full/yearly.csv", index_col=0)
    yearly_table = markdown_table(
        ["Année", *[book_label(name) for name in yearly]],
        [[str(year), *[percent(value) for value in row]] for year, row in yearly.iterrows()],
    )
    reasons_text = (
        "; ".join(reasons)
        if reasons
        else "Tous les critères rétrospectifs déclarés sont satisfaits."
    )
    timetable = configuration.get("timetable", {})
    candidate_command = (
        "        uv run python scripts/SA15_run_gpt61_round4.py --candidate "
        '"research/SA15_GPT-6.1/round4/candidates/trial_$N.json" --output "$OUT"'
    )
    text = f"""# SA15_GPT-6.1 — cinquante itérations supplémentaires — 16 octobre 2026

Objectif : battre Nasdaq acheté puis conservé, en favorisant **drawdown ≤25 %** et **au plus
quatre dates de transactions par an**.
Statut : **{status}**. Choix gelé : **essai {trial}**, parmi **50 nouveaux designs, 80 cumulés**.
Motif : {reasons_text}

L'écart net au Nasdaq vaut **{percentage_points(plain["full"]["excess"])}** sur le continu et
**{percentage_points(plain["final"]["excess"])}** sur le contrôle chronologique.
Les rendements sont en EUR, nets des frais simulés, avant fiscalité personnelle.
Toute l'histoire était déjà connue : cette recherche est rétrospective.

## Historique continu — 3 juin 2019 au 9 octobre 2026

{financial_table(tables["full"])}

![Capital, patrimoine relatif au Nasdaq et drawdown](comparison/full/comparison.png)

Le contrôle technologie conservée montre si une meilleure composition explique l'avantage. Or =
ETC Xetra-Gold, pas ETF UCITS.
Le 50/50 Nasdaq/or est acheté à parts égales puis laissé dériver ; aucun rééquilibrage après
l'entrée.
Le meilleur rendement ou la plus faible baisse des contrôles ne remplace pas le gagnant gelé.

## Contrôle chronologique — 2 janvier 2025 au 9 octobre 2026

{financial_table(tables["final"])}

![Contrôle chronologique](comparison/final/comparison.png)

Sur le contrôle chronologique 2025-2026, alpha annuel de régression au Nasdaq :
{percent(tables["final"].loc[BOOK, "alpha_vs_nasdaq"])} ;
bêta : {number(tables["final"].loc[BOOK, "beta_vs_nasdaq"])}.
L'alpha face à un indice ne démontre pas une capacité de timing.

## Choix continu — juin 2019 à décembre 2024

{financial_table(tables["choice"])}

Un vrai portefeuille continu, sans reset en 2023. Le segment 2023-2024 conserve les positions et
coûts ; la dernière clôture 2022 ancre son premier rendement.
Le contrôle 2025-2026 et le parcours complet ont été exécutés après gel du gagnant. Ils ne
modifient pas son classement.

Le brut conserve les mêmes transactions en retirant les frais ; il ne recalcule pas
un portefeuille contrefactuel sans frais. Une tranche 2023-2024 possède des ancres brut/net
différentes à cause des coûts antérieurs ; son rendement brut normalisé peut donc être
légèrement inférieur au net sans frais dans cette tranche.

{alternatives}

Les lignes ci-dessus décrivent des compromis de choix et ne remplacent jamais l'essai {trial}.
Frontière de Pareto : {", ".join(map(str, front))}. Dominance simultanée en CAGR, drawdown et
dates de transactions.

![Frontière rendement, risque et interventions](frontier.png)

## Compagnons descriptifs gelés avant contrôle

{companions}

## Configuration effectivement retenue

Classe sauvegardée : {definition["class"]}. Empreinte : {selected["fingerprint"]}.
Les valeurs par défaut de la classe ne sont pas utilisées pour ce récit : les paramètres complets
ci-dessous sont vérifiés contre selected.json, candidate.json et strategy.json.

{retained_rule(parameters)}

{parameter_table}

Cadence : **{selected["candidate"]["schedule"]}**, première décision dès la première séance.
Décision {timetable.get("decision_time", "selon configuration")}
{timetable.get("timezone", "Europe/Paris")}, après clôtures ; exécution
{timetable.get("execution_time", "ouverture suivante")} à l'ouverture négociable suivante.
Les signaux lisent les endpoints exacts de leur calendrier ; moyenne mobile et volatilité
demandent les séances consécutives déclarées. Aucun remplissage.

## Les cinquante essais — 31 à 80

Priorité : qualification (excès CAGR positif, DD ≤25 %, dates/an ≤4), puis score, puis premier
numéro.
Score = excès CAGR choix +0,20x(DD Nasdaq-DD candidat) -0,50xmax(0,DD-0,25)
-0,001xmax(0,dates/an-4) -0,25xmax(0,-excès CAGR 2023-24).
Les DD de cette formule sont des profondeurs positives. Le rapport lit les scores archivés, sans
sélectionner un nouveau gagnant.

{trial_table}

{chr(10).join(f"{row['trial']}. {row['reason']}" for row in rows)}

Manifestes de lots vérifiés : {batches["batches_available"]}, candidats vérifiés :
{batches["candidates_verified"]}.
Les cinq lots de dix sont adaptatifs sur les seuls résultats de choix déjà calculés. Tous les JSON
d'un lot sont archivés avant son premier run.
Tous les essais, y compris les perdants et voisins, restent publiés ;
aucun 81e design ajouté pour sauver le résultat.

## Interventions et positions

{operations}

Un jour de fills est une date d'exécution distincte ; plusieurs achats/ventes le même jour restent
plusieurs ordres.
L'entrée initiale est comptée. Les vérifications sont les décisions effectivement enregistrées,
même sans ordre.
Mensuel ≈12 contrôles/an, trimestriel ≈4, hebdomadaire ≈52, avec la décision initiale. Aucune
cadence n'impose des ordres tous les soirs.

Les références conservées achètent une fois ; leur cadence moteur quotidienne permet seulement
de compléter une entrée rejetée et ne signifie pas un travail quotidien de trading.

{position_table(output, trial)}

Les poids moyens sont observés sur toutes les séances ; ils ne représentent pas des bêtas. Cash
résiduel : parts entières, frais et éventuelle allocation tactique.

## Disponibilité des signaux et décisions de défense

{availability_section(output, trial)}

## Coûts, redémarrages et incertitude

{stress_table}

{costs_link}. Les 50 politiques sont rejouées, pas réestimées ; la comparaison x2 face au Nasdaq
x1 est volontairement conservatrice.

{starts_table}

Les quatre dates sont de vrais redémarrages depuis cash jusqu'à fin 2024. Le gagnant et les cinq
références sont simulés sur les mêmes dates : aucun simple rebasage de courbe.
[Tous les redémarrages](robustness/starts.csv).

Bootstrap du rendement actif moyen annuel final :
**{percent(uncertainty["annualised_mean_active_return"])}**, intervalle 95 %
**[{percent(uncertainty["lower_95"])} ; {percent(uncertainty["upper_95"])}]**.
Blocs circulaires de 20 séances, 2000 tirages, seed 61154. Ce n'est pas un intervalle de CAGR ni
une preuve indépendante ; les 80 essais ne sont pas corrigés par ce bootstrap.

DSR : **80 designs corrélés** annoncés, dispersion sur **{diagnostics["dispersion_curves"]}
courbes**, anciens manquants {diagnostics["previous_trials_missing"]}.
R1-R3 recommencent en cash en validation ; R4 utilise le segment du choix continu. Leur mélange
donne une approximation de dispersion, signalée dans selection_diagnostics.json.
Le DSR mesure un Sharpe absolu, pas la probabilité de battre Nasdaq ; il ne corrige pas tous les
choix historiques de l'univers ou du projet.

NOT_SUPPORTED : croissance non supérieure au Nasdaq sur continu ou contrôle.
UNCERTAIN : les deux excès sont positifs mais coûts, intervalle ou cibles de risque/interventions
échouent.
SUPPORTED_RETROSPECTIVE : tous les critères déclarés passent. Aucun statut ne garantit le futur.

## Rendements annuels du parcours continu

{yearly_table}

Première et dernière années partielles. Drawdowns calculés quotidiennement malgré une cadence de
décision réduite.
Aucun reset aux frontières annuelles du parcours continu.

## Limites et sources

Univers actuel choisi rétrospectivement ; concentration du Nasdaq et de la technologie ; prix
fournisseur restatés, absence de millésimes point-in-time ; source historique unique pour les
nouvelles séries.
La cotation EUR ne supprime pas les devises sous-jacentes. Une défense en or ou obligations peut
également perdre.
Le plafond de volatilité éventuel concerne le bloc offensif décrit, pas la volatilité totale ni un
drawdown garanti.
Pas de levier, short, modèle appris ou ordre réel. Le Sharpe utilise un taux sans risque nul.

[Protocole](../../research/SA15_GPT-6.1/round4/protocol.md) · [Littérature et fiches
émetteurs](../../research/SA15_GPT-6.1/round4/literature.md) ·
[Données](../../research/SA15_GPT-6.1/round4/data.md).
Les sources motivent les mécanismes ; aucun rendement académique ou de forum n'est transféré à
SA15.

## Reproduction

Dans un NOUVEAU dossier, avec le magasin R4 isolé et gelé :

    OUT=runs/sa15_r4_reproduction
    for N in $(seq 31 80); do
{candidate_command}
    done
    uv run python scripts/SA15_diagnostics_gpt61_round4.py --freeze-companions --output "$OUT"
    uv run python scripts/SA15_run_gpt61_round4.py --final --output "$OUT"
    uv run python scripts/SA15_run_gpt61_round4.py --robustness --output "$OUT" --workers 2
    uv run python scripts/SA15_diagnostics_gpt61_round4.py --run --output "$OUT"
    uv run python scripts/SA15_report_gpt61_round4.py --output "$OUT"

Régénérer seulement ce rapport, sans backtest :

    uv run python scripts/SA15_report_gpt61_round4.py --output results/SA15_GPT-6.1_R4

[50 essais](reported_iterations.csv) · [Pareto](pareto.csv) · [Sélection gelée](selected.json) ·
[Verdict](verdict.json) · [Diagnostic DSR](selection_diagnostics.json) ·
[Vérifications](validation.md).

Ce rendu ne modifie ni candidat, ni sélection, ni ordre, ni archive financière.
reporting_manifest.json date les exports et identifie le source de présentation séparément du
source financier gelé."""
    (output / "study.md").write_text(text, encoding="utf-8")
    write_json(
        output / "reporting_manifest.json",
        {
            "rendered_at_utc": datetime.now(UTC).isoformat(),
            "report_source": Path(__file__).name,
            "report_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "financial_selection_sha256": hashlib.sha256(
                (output / "selected.json").read_bytes()
            ).hexdigest(),
            "presentation_only": True,
        },
    )


def main() -> None:
    """Render saved results only; the CLI exposes no backtest phase."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    options = parser.parse_args()
    report(options.output)


if __name__ == "__main__":
    main()
