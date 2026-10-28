"""Diagnose a frozen SA15 mechanism pilot from archived evidence only.

No policy, backtest runner or market-data store is imported. Regime labels use
only the preceding Nasdaq close and never enter a trading decision. Ablations
are matched counterfactual policies inside the simulator, not market causality.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter

from quant_backtester.analytics.config import AnalyticsConfig
from quant_backtester.analytics.quality import deflated_sharpe_probability

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "results/SA15_GPT-6.1_mechanism_pilot"
POLICIES = ("full", "trend_only", "volatility_only", "neither", "Nasdaq_buy_hold")
PERIODS = ("choice", "control", "full")
COSTS = (1, 2)
REGIMES = ("unclassified", "rise", "fall", "recovery")
REQUIRED_METRICS = (
    "net_return",
    "gross_return",
    "cagr",
    "max_drawdown",
    "costs_eur",
    "fills",
    "sessions",
)
LABELS = {
    "full": "Tendance + volatilité",
    "trend_only": "Tendance seule",
    "volatility_only": "Volatilité seule",
    "neither": "Sans les deux blocs",
    "Nasdaq_buy_hold": "Nasdaq conservé",
}


@dataclass(frozen=True)
class SavedRun:
    """One fully saved policy with its execution evidence and matched conditions."""

    policy: str
    period: str
    cost_multiplier: int
    folder: Path
    metrics: dict
    equity: pd.Series
    weights: pd.DataFrame
    fills: pd.DataFrame
    decisions: pd.DataFrame
    configuration: dict
    identity: dict


def read_json(path: Path) -> dict:
    """Read a required JSON object without supplying missing evidence."""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def sha256(path: Path) -> str:
    """Hash an existing artifact without changing it."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_folder(output: Path, period: str, cost: int, policy: str) -> Path:
    """Resolve only the thirty predeclared base simulations."""
    if period not in PERIODS or cost not in COSTS or policy not in POLICIES:
        raise ValueError("unknown pilot period, cost or policy")
    return output / period / f"costs_x{cost}" / policy


def load_curve(path: Path) -> pd.Series:
    """Load a positive saved NAV with unique, increasing session dates."""
    frame = pd.read_csv(path, index_col=0, parse_dates=True)
    if frame.shape[1] != 1 or len(frame) < 2:
        raise ValueError(f"expected a nonempty saved NAV: {path}")
    curve = frame.iloc[:, 0].astype(float)
    if (
        not isinstance(curve.index, pd.DatetimeIndex)
        or curve.index.has_duplicates
        or not curve.index.is_monotonic_increasing
        or not np.isfinite(curve.to_numpy()).all()
        or (curve <= 0).any()
    ):
        raise ValueError(f"invalid saved NAV: {path}")
    return curve


def validate_metrics(metrics: dict, curve: pd.Series) -> None:
    """Refuse absent/nonfinite outcomes and inconsistent saved return counts."""
    for key in REQUIRED_METRICS:
        if key not in metrics or not isinstance(metrics[key], (int, float)):
            raise ValueError(f"required metric is missing or nonnumeric: {key}")
        if not math.isfinite(float(metrics[key])):
            raise ValueError(f"required metric is not finite: {key}")
    expected = float(curve.iloc[-1] / curve.iloc[0] - 1)
    if not math.isclose(float(metrics["net_return"]), expected, abs_tol=1e-10):
        raise ValueError("saved metric and NAV return differ")
    if metrics["sessions"] != len(curve):
        raise ValueError("saved metric and NAV session counts differ")
    if metrics["net_return"] <= -1:
        raise ValueError("nonpositive terminal wealth")


def verify_artifacts(folder: Path) -> None:
    """Check every financial archive checksum before consuming its evidence."""
    hashes = read_json(folder / "artifacts.json")
    required = {
        "metrics.json",
        "equity.csv",
        "weights.csv",
        "fills.csv",
        "decisions.csv",
        "configuration.json",
        "identity.json",
        "contract.json",
    }
    if not required.issubset(hashes):
        raise ValueError(f"required archive checksums are missing: {folder}")
    for filename, digest in hashes.items():
        if Path(filename).name != filename or sha256(folder / filename) != digest:
            raise ValueError(f"financial artifact checksum differs: {filename}")


def verify_completion(output: Path) -> dict:
    """Refuse partial simulations or evidence modified after completion."""
    completed = read_json(output / "completed.json")
    counts = {"real_backtest_count": 30, "candidate_count": 1, "control_count": 4}
    if any(completed.get(key) != value for key, value in counts.items()):
        raise ValueError("the thirty declared base simulations are incomplete")
    for filename, key in (("manifest.json", "manifest_sha256"), ("metrics.csv", "metrics_sha256")):
        if completed.get(key) != sha256(output / filename):
            raise ValueError(f"completion checksum differs: {filename}")
    return read_json(output / "manifest.json")


def load_run(output: Path, period: str, cost: int, policy: str) -> SavedRun:
    """Read one required archive; no missing metrics or journals become zeros."""
    folder = run_folder(output, period, cost, policy)
    verify_artifacts(folder)
    curve = load_curve(folder / "equity.csv")
    metrics = read_json(folder / "metrics.json")
    validate_metrics(metrics, curve)
    weights = pd.read_csv(folder / "weights.csv", index_col=0, parse_dates=True)
    if not weights.index.equals(curve.index):
        raise ValueError(f"weights and NAV sessions differ: {folder}")
    if not np.isfinite(weights.to_numpy(dtype=float)).all():
        raise ValueError(f"nonfinite saved position: {folder}")
    if (weights < -1e-10).any().any() or (weights.sum(axis=1) > 1 + 1e-8).any():
        raise ValueError(f"saved long-only cash-funded weights are invalid: {folder}")
    fills = pd.read_csv(folder / "fills.csv")
    for key in ("session_date", "total_cost", "traded_value"):
        if key not in fills:
            raise ValueError(f"missing fill field {key}: {folder}")
    fills["session_date"] = pd.to_datetime(fills["session_date"])
    if len(fills) != metrics["fills"] or not fills.session_date.isin(curve.index).all():
        raise ValueError(f"fills differ from saved metrics/sessions: {folder}")
    if not math.isclose(float(fills.total_cost.sum()), metrics["costs_eur"], abs_tol=1e-7):
        raise ValueError(f"fills and costs metric differ: {folder}")
    decisions = pd.read_csv(folder / "decisions.csv")
    if "session_date" not in decisions or "skipped" not in decisions:
        raise ValueError(f"missing decision fields: {folder}")
    return SavedRun(
        policy,
        period,
        cost,
        folder,
        metrics,
        curve,
        weights,
        fills,
        decisions,
        read_json(folder / "configuration.json"),
        read_json(folder / "identity.json"),
    )


def common_conditions(run: SavedRun) -> dict:
    """Extract execution conditions that must match in every paired comparison."""
    keys = (
        "start",
        "end",
        "initial_cash",
        "base_currency",
        "reference_calendar",
        "schedule",
        "timetable",
        "universe",
        "portfolio",
        "execution",
        "quantity_steps",
    )
    if not set(keys).issubset(run.configuration):
        raise ValueError("required execution conditions are missing")
    return {key: run.configuration[key] for key in keys}


def validate_matched(runs: dict[str, SavedRun]) -> None:
    """Reject missing policies, unmatched calendars, costs, or data vintages."""
    if set(runs) != set(POLICIES):
        raise ValueError("a matched comparison requires all five frozen policies")
    baseline = runs["Nasdaq_buy_hold"]
    if "data_state" not in baseline.identity:
        raise ValueError("missing saved data identity")
    for policy, run in runs.items():
        if run.policy != policy or run.period != baseline.period:
            raise ValueError("policy/period labels do not match their comparison")
        if run.cost_multiplier != baseline.cost_multiplier:
            raise ValueError("paired policies use different cost multipliers")
        if not run.equity.index.equals(baseline.equity.index):
            raise ValueError("paired policies use different sessions")
        if run.equity.iloc[0] != baseline.equity.iloc[0]:
            raise ValueError("paired policies use different initial cash")
        if common_conditions(run) != common_conditions(baseline):
            raise ValueError("paired policies use different execution conditions")
        if run.identity.get("data_state") != baseline.identity["data_state"]:
            raise ValueError("paired policies use different data vintages")


def contrasts(metrics: dict[str, dict]) -> list[dict]:
    """Compare paired replays; report DD changes without additive attribution."""
    if set(metrics) != set(POLICIES):
        raise ValueError("contrasts require all five policies")
    pairs = (
        ("trend_conditional", "full", "volatility_only"),
        ("volatility_conditional", "full", "trend_only"),
        ("trend_standalone", "trend_only", "neither"),
        ("volatility_standalone", "volatility_only", "neither"),
        ("common_conditions_vs_hold", "neither", "Nasdaq_buy_hold"),
        ("complete_vs_hold", "full", "Nasdaq_buy_hold"),
    )
    rows = []
    for effect, left, right in pairs:
        a, b = metrics[left], metrics[right]
        rows.append(
            {
                "effect": effect,
                "left": left,
                "right": right,
                "net_return_difference": a["net_return"] - b["net_return"],
                "cagr_difference": a["cagr"] - b["cagr"],
                "max_drawdown_difference": a["max_drawdown"] - b["max_drawdown"],
                "cost_difference_eur": a["costs_eur"] - b["costs_eur"],
                "log_growth_difference": math.log1p(a["net_return"]) - math.log1p(b["net_return"]),
            }
        )
    return rows


def log_growth_interaction(metrics: dict[str, dict]) -> float:
    """Measure the two-block interaction in terminal log wealth, not DD."""
    if not {"full", "trend_only", "volatility_only", "neither"}.issubset(metrics):
        raise ValueError("interaction requires four paired mechanism policies")
    return math.fsum(
        sign * math.log1p(metrics[name]["net_return"])
        for name, sign in (("full", 1), ("trend_only", -1), ("volatility_only", -1), ("neither", 1))
    )


def diagnostic_regimes(
    benchmark: pd.Series, *, lookback: int = 126, recovery: int = 21, stress: float = 0.10
) -> pd.Series:
    """Label day t using only benchmark closes through t-1.

    A 126-session return needs 127 closes. After the one-session lag, rows
    zero through 126 are unclassified; row 127 is the first eligible day.
    Stress means a drawdown from the trailing 126-observation peak of at
    least ten percent occurred during the preceding 126 observations.
    Short initial peak/stress windows are allowed, but the 126-return gate
    still applies. These descriptive labels never determine portfolio orders.
    """
    if lookback < 1 or recovery < 1 or not 0 < stress < 1:
        raise ValueError("invalid fixed diagnostic regime parameters")
    prior = benchmark.shift(1)
    long_return = prior / prior.shift(lookback) - 1
    short_return = prior / prior.shift(recovery) - 1
    drawdown = prior / prior.rolling(lookback, min_periods=1).max() - 1
    past_stress = drawdown.rolling(lookback, min_periods=1).min() <= -stress
    labels = pd.Series("unclassified", index=benchmark.index, name="regime")
    known = long_return.notna()
    labels.loc[known & (long_return > 0)] = "rise"
    labels.loc[known & (long_return <= 0)] = "fall"
    labels.loc[known & past_stress & (short_return > 0)] = "recovery"
    return labels


def regime_summary(run: SavedRun, benchmark: SavedRun, labels: pd.Series) -> list[dict]:
    """Summarize observed active daily returns and actual closing exposure.

    The arithmetic mean in basis points is not an exact compounded PnL
    attribution. Closing weights are descriptive and are never multiplied
    by close-to-close returns: orders execute at opens.
    """
    if not run.equity.index.equals(benchmark.equity.index) or not labels.index.equals(
        run.equity.index
    ):
        raise ValueError("regime inputs must share exact saved sessions")
    active = run.equity.pct_change(fill_method=None) - benchmark.equity.pct_change(fill_method=None)
    core = run.weights.get("ETF_NASDAQ", pd.Series(0.0, index=run.equity.index))
    rows = []
    for regime in REGIMES:
        mask = labels.eq(regime) & active.notna()
        rows.append(
            {
                "policy": run.policy,
                "period": run.period,
                "cost_multiplier": run.cost_multiplier,
                "regime": regime,
                "sessions": int(mask.sum()),
                "mean_active_daily_bp": float(active[mask].mean() * 10000) if mask.any() else None,
                "mean_nasdaq_closing_weight": float(core[mask].mean()) if mask.any() else None,
                "mean_cash_closing_weight": float((1 - run.weights.sum(axis=1))[mask].mean())
                if mask.any()
                else None,
            }
        )
    return rows


def reduced_episodes(run: SavedRun, benchmark: SavedRun, threshold: float = 0.95) -> list[dict]:
    """Publish every actual reduced-Nasdaq episode and associated observed fills.

    The initial empty cash observation is excluded. Episode returns go from
    the preceding close through the final reduced-exposure close. Observed
    costs include fills in that interval; reentry-day costs are separate.
    Neither costs nor observed relative returns are assigned to a block.
    """
    if not run.equity.index.equals(benchmark.equity.index):
        raise ValueError("episode policies have different sessions")
    core = run.weights.get("ETF_NASDAQ", pd.Series(0.0, index=run.equity.index))
    mask = core < threshold
    mask.iloc[0] = False
    groups = mask.ne(mask.shift()).cumsum()
    rows = []
    for _, episode in core[mask].groupby(groups[mask]):
        first, last = episode.index[0], episode.index[-1]
        start_i, end_i = run.equity.index.get_loc(first), run.equity.index.get_loc(last)
        anchor = run.equity.index[start_i - 1]
        reentry = run.equity.index[end_i + 1] if end_i + 1 < len(run.equity) else None
        fills = run.fills[run.fills.session_date.between(first, last)]
        reentry_fills = (
            run.fills[run.fills.session_date.eq(reentry)]
            if reentry is not None
            else run.fills.iloc[:0]
        )
        rows.append(
            {
                "policy": run.policy,
                "period": run.period,
                "cost_multiplier": run.cost_multiplier,
                "anchor_close": anchor.date().isoformat(),
                "first_reduced_close": first.date().isoformat(),
                "last_reduced_close": last.date().isoformat(),
                "first_restored_close": reentry.date().isoformat() if reentry is not None else None,
                "sessions": len(episode),
                "mean_nasdaq_weight": float(episode.mean()),
                "strategy_net_return": float(run.equity.loc[last] / run.equity.loc[anchor] - 1),
                "benchmark_net_return": float(
                    benchmark.equity.loc[last] / benchmark.equity.loc[anchor] - 1
                ),
                "observed_costs_eur": float(fills.total_cost.sum()),
                "observed_traded_value_eur": float(fills.traded_value.sum()),
                "observed_fills": len(fills),
                "reentry_day_observed_costs_eur": float(reentry_fills.total_cost.sum()),
            }
        )
    return rows


def run_metrics(run: SavedRun) -> dict:
    """Add actual intervention counts and closing exposures to saved metrics."""
    years = (run.equity.index[-1] - run.equity.index[0]).days / 365.25
    core = run.weights.get("ETF_NASDAQ", pd.Series(0.0, index=run.equity.index))
    return {
        "policy": run.policy,
        "period": run.period,
        "cost_multiplier": run.cost_multiplier,
        **run.metrics,
        "trade_dates": int(run.fills.session_date.nunique()),
        "trade_dates_per_year": run.fills.session_date.nunique() / years,
        "decision_dates": len(run.decisions),
        "mean_nasdaq_weight": float(core.mean()),
        "mean_cash_weight": float((1 - run.weights.sum(axis=1)).mean()),
        "decisions_with_skips": int(run.decisions.skipped.ne("{}").sum()),
    }


def hypothesis_verdict(rows: pd.DataFrame) -> dict:
    """Judge only the complete policy, never promote an ablation as a winner."""
    normal = rows[rows.cost_multiplier.eq(1)].set_index(["period", "policy"])
    failures = []
    for period in ("full", "control"):
        complete = normal.loc[(period, "full")]
        hold = normal.loc[(period, "Nasdaq_buy_hold")]
        if complete.net_return <= hold.net_return:
            failures.append(f"complete policy does not beat Nasdaq on {period}")
    targets = all(
        abs(normal.loc[(period, "full"), "max_drawdown"]) <= 0.25
        and normal.loc[(period, "full"), "trade_dates_per_year"] <= 4
        for period in ("full", "control")
    )
    return {
        "status": "NOT_SUPPORTED" if failures else "UNCERTAIN",
        "reasons": failures
        or [
            "rolling starts, parameter neighbourhoods and independent future "
            "evidence remain unverified"
        ],
        "risk_and_intervention_targets_met": targets,
        "main_policy": "full",
        "ablations_are_not_candidates_for_replacement": True,
        "previous_trials": 80,
        "policies_examined": 5,
        "cumulative_trials_declared": 85,
        "base_simulations": 30,
    }


def descriptive_dsr(run: SavedRun, prior_diagnostics: Path) -> dict:
    """Deflate absolute Sharpe by 85, with explicitly inherited dispersion."""
    prior = read_json(prior_diagnostics)
    dispersion = float(prior["session_sharpe_std"])
    anchor = run.equity[run.equity.index < "2023-01-01"].tail(1)
    sample = pd.concat([anchor, run.equity.loc["2023-01-01":"2024-12-31"]])
    if len(sample) < 60 or len(anchor) != 1:
        raise ValueError("the descriptive DSR requires the anchored 2023-2024 slice")
    sample.index = pd.Index(sample.index.date, dtype="object", name="session_date")
    value = deflated_sharpe_probability(
        sample,
        AnalyticsConfig(sessions_per_year=252, risk_free_rate=0.0, minimum_sessions=60),
        trials=85,
        trial_sharpe_std=dispersion,
    )
    return {
        "trials_declared": 85,
        "dispersion_curves_inherited": 80,
        "session_sharpe_std": dispersion,
        "dispersion_source_sha256": sha256(prior_diagnostics),
        "complete_policy_2023_2024_dsr": value,
        "interpretation": (
            "approximate absolute Sharpe diagnostic; not a probability of beating Nasdaq"
        ),
    }


def draw_curves(runs: dict[str, SavedRun], path: Path, period: str) -> None:
    """Render all five policies on equal-period wealth and drawdown axes."""
    fig, axes = plt.subplots(2, 1, figsize=(12, 9), sharex=True, layout="constrained")
    for policy in POLICIES:
        curve = runs[policy].equity
        axes[0].plot(curve.index, curve / curve.iloc[0] * 100, label=LABELS[policy])
        axes[1].plot(curve.index, curve / curve.cummax() - 1, label=LABELS[policy])
    axes[0].set_title(f"SA15 mécanismes — {period} — frais normaux — rétrospectif")
    axes[0].set_ylabel("Capital initial = 100")
    axes[0].legend(loc="upper left", fontsize=9)
    axes[1].set_ylabel("Drawdown net")
    axes[1].yaxis.set_major_formatter(PercentFormatter(1))
    for ax in axes:
        ax.grid(alpha=0.2)
    fig.savefig(path, dpi=160)
    plt.close(fig)


def markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    """Render compact report tables with explicit column separation."""
    return "\n".join(
        [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
            *("| " + " | ".join(row) + " |" for row in rows),
        ]
    )


def render_report(output: Path) -> dict:
    """Read all thirty required archives before writing any derived report."""
    manifest = verify_completion(output)
    archive = {}
    for period in PERIODS:
        for cost in COSTS:
            group = {policy: load_run(output, period, cost, policy) for policy in POLICIES}
            validate_matched(group)
            archive[period, cost] = group
    rows, effects, interactions, regimes, episodes, daily = [], [], [], [], [], []
    hypothesis = manifest["hypothesis"]
    regime_spec = hypothesis["diagnostic_regimes"]
    for (period, cost), group in archive.items():
        metrics = {policy: run.metrics for policy, run in group.items()}
        effects.extend(
            {"period": period, "cost_multiplier": cost, **row} for row in contrasts(metrics)
        )
        interactions.append(
            {
                "period": period,
                "cost_multiplier": cost,
                "interaction_log_growth": log_growth_interaction(metrics),
            }
        )
        labels = diagnostic_regimes(
            group["Nasdaq_buy_hold"].equity,
            lookback=regime_spec["lookback_sessions"],
            recovery=regime_spec["recovery_sessions"],
            stress=regime_spec["stress_drawdown"],
        )
        for run in group.values():
            rows.append(run_metrics(run))
            regimes.extend(regime_summary(run, group["Nasdaq_buy_hold"], labels))
            episodes.extend(reduced_episodes(run, group["Nasdaq_buy_hold"]))
        daily.extend(
            {
                "period": period,
                "cost_multiplier": cost,
                "session_date": date.date().isoformat(),
                "regime": label,
            }
            for date, label in labels.items()
        )
    table = pd.DataFrame(rows)
    verdict = hypothesis_verdict(table)
    prior_path = ROOT / "results/SA15_GPT-6.1_R4/selection_diagnostics.json"
    dsr = (
        descriptive_dsr(archive["choice", 1]["full"], prior_path) if prior_path.is_file() else None
    )
    frames = {
        "reported_metrics.csv": table,
        "paired_effects.csv": pd.DataFrame(effects),
        "log_growth_interactions.csv": pd.DataFrame(interactions),
        "regime_diagnostics.csv": pd.DataFrame(regimes),
        "reduced_exposure_episodes.csv": pd.DataFrame(episodes),
        "diagnostic_regimes.csv": pd.DataFrame(daily),
    }
    for filename, frame in frames.items():
        frame.to_csv(output / filename, index=False)
    for period in ("full", "control"):
        draw_curves(archive[period, 1], output / f"{period}_curves.png", period)
    reason_labels = {
        "complete policy does not beat Nasdaq on full": (
            "le candidat complet ne bat pas Nasdaq sur le parcours complet"
        ),
        "complete policy does not beat Nasdaq on control": (
            "le candidat complet ne bat pas Nasdaq sur le controle 2025-2026"
        ),
        (
            "rolling starts, parameter neighbourhoods and independent future "
            "evidence remain unverified"
        ): ("les redemarrages, voisinages et donnees futures restent a verifier"),
    }
    reason_text = "; ".join(reason_labels.get(reason, reason) for reason in verdict["reasons"])
    sections = [
        "# SA15 — pilote d'attribution par mécanismes",
        "Une itération principale préspécifiée : MA200 et plafond de volatilité "
        "historique 20 %, décisions mensuelles, bande 10 points, Nasdaq et "
        "monétaire EUR uniquement. Aucun poids n'est choisi pour une date passée "
        "; aucun paramètre n'a été retouché après calcul.",
        "**85 essais déclarés cumulativement** : 80 antérieurs et 5 politiques "
        "examinées ici. **30 simulations de base**, soit 5 politiques x 3 "
        "périodes x 2 barèmes de frais. Les quatre contrôles sont des ablations "
        "descriptives ; aucun ne remplace le candidat complet après lecture.",
        f"**Verdict principal : {verdict['status']}.** " + reason_text + ".",
        "Toutes les périodes sont rétrospectives et avaient déjà été examinées. "
        "Chaque période redémarre depuis 100 000 EUR de cash ; le contrôle "
        "2025-2026 n'est pas un segment rebasé du parcours continu, ni une "
        "validation indépendante. Rendements en EUR, nets des frais simulés, "
        "avant fiscalité.",
    ]
    for period in PERIODS:
        selected = table[table.period.eq(period) & table.cost_multiplier.eq(1)]
        formatted = [
            [
                LABELS[row.policy],
                f"{row.net_return:.2%}",
                f"{row.cagr:.2%}",
                f"{row.max_drawdown:.2%}",
                str(row.trade_dates),
                f"{row.mean_nasdaq_weight:.2%}",
                f"{row.costs_eur:.2f}",
            ]
            for row in selected.itertuples()
        ]
        sections.extend(
            [
                f"## {period} ({archive[period, 1]['full'].equity.index[0].date()} "
                f"au {archive[period, 1]['full'].equity.index[-1].date()}) — frais normaux",
                markdown_table(
                    [
                        "Politique",
                        "Gain net",
                        "CAGR",
                        "Drawdown",
                        "Dates d'ordres",
                        "Nasdaq moyen",
                        "Frais EUR",
                    ],
                    formatted,
                ),
            ]
        )
        if period in ("full", "control"):
            sections.append(f"![Capital et drawdown de toutes les politiques]({period}_curves.png)")
    block_notes = []
    for name, effect in (
        ("Tendance", "trend_conditional"),
        ("Volatilite", "volatility_conditional"),
    ):
        for period in ("full", "control"):
            row = next(
                row
                for row in effects
                if row["effect"] == effect
                and row["period"] == period
                and row["cost_multiplier"] == 1
            )
            block_notes.append(
                f"{name}, {period}: effet conditionnel CAGR "
                f"{row['cagr_difference'] * 100:+.2f} pp/an, drawdown "
                f"{row['max_drawdown_difference'] * 100:+.2f} pp, frais "
                f"{row['cost_difference_eur']:+.2f} EUR. Le signe est observe pour cet "
                "assemblage; les episodes et regimes permettent de localiser les hausses "
                "conservees ou manquees."
            )
    sections.extend(
        [
            "## Effets des blocs et interactions",
            "Les comparaisons appariées sont de vrais rejeux depuis cash avec "
            "mêmes dates, données et conditions : complet-volatilité seule pour "
            "la tendance, complet-tendance seule pour la volatilité ; chaque bloc"
            " seul est aussi comparé au contrôle sans les deux. Le contrôle sans "
            "blocs conserve cadence/bande/fallback communs et est comparé au "
            "Nasdaq conservé.",
            markdown_table(
                ["Période", "Effet", "Delta CAGR", "Delta drawdown", "Delta frais EUR"],
                [
                    [
                        row["period"],
                        row["effect"],
                        f"{row['cagr_difference'] * 100:.2f} pp",
                        f"{row['max_drawdown_difference'] * 100:.2f} pp",
                        f"{row['cost_difference_eur']:.2f}",
                    ]
                    for row in effects
                    if row["cost_multiplier"] == 1
                ],
            ),
            "\n\n".join(block_notes),
            "Un delta de drawdown positif indique une baisse maximale moins "
            "négative. Les drawdowns ne sont pas additifs. L'interaction publiée "
            "est log(croissance complète)-log(croissance tendance)-log(croissance"
            " volatilité)+log(croissance sans blocs). Elle mesure l'interaction "
            "des politiques dans ce simulateur ; elle ne prouve aucune causalité "
            "de marché.",
            markdown_table(
                ["Période", "Frais", "Interaction log-croissance"],
                [
                    [
                        row["period"],
                        f" x {row['cost_multiplier']}",
                        f"{row['interaction_log_growth']:.6f}",
                    ]
                    for row in interactions
                ],
            ),
            "## Régimes et épisodes publiés intégralement",
            "Les labels descriptifs du jour t utilisent seulement la NAV Nasdaq "
            "connue à t-1 : hausse/baisse selon rendement 126 ; reprise "
            "prioritaire si rendement 21 positif et stress drawdown 10 % observé "
            "dans les 126 observations passées. Le drawdown est rapporté au "
            "maximum glissant 126. Il faut 127 closes pour le rendement 126 : les"
            " lignes 0 à 126 sont nonclassées après décalage ; la ligne 127 est "
            "la première classable. Aucun label ne pilote les ordres.",
            "`regime_diagnostics.csv` contient, pour chaque "
            "politique/période/frais/régime, le nombre de rendements quotidiens, "
            "leur surplus moyen arithmétique en points de base et les expositions"
            " moyennes de clôture. Ce surplus moyen n'est pas une attribution "
            "composée de PnL. Aucun produit poids de clôture x rendement "
            "clôture/clôture n'est utilisé : les fills ont lieu à l'ouverture.",
            markdown_table(
                ["Politique (full)", "Regime", "Jours", "Surplus moyen bp/j", "Nasdaq moyen"],
                [
                    [
                        LABELS[row["policy"]],
                        row["regime"],
                        str(row["sessions"]),
                        f"{row['mean_active_daily_bp']:.3f}",
                        f"{row['mean_nasdaq_closing_weight']:.2%}",
                    ]
                    for row in regimes
                    if row["period"] == "full" and row["cost_multiplier"] == 1
                ],
            ),
            "La reduction du drawdown est accompagnee d'une exposition Nasdaq plus faible. "
            "Elle ne demontre pas une creation de performance independante du cash. "
            "Dans les jours classes reprise, les deux blocs peuvent conserver une "
            "exposition reduite alors que Nasdaq monte; les comparaisons appairees "
            "quantifient leur effet net sans les confondre avec une simple observation.",
            "`reduced_exposure_episodes.csv` publie tous les épisodes où "
            "l'exposition Nasdaq réelle de clôture est inférieure à 95 %, hors "
            "observation initiale de cash. Rendements entre clôture précédente et"
            " dernière clôture réduite ; frais observés pendant l'épisode et "
            "frais du jour de retour séparés. Ces frais ne sont pas imputés à un "
            "bloc. Sans journaux pré-bande, le CSV ne permet pas de séparer "
            "exactement seuils, bande et arrondis.",
            markdown_table(
                [
                    "Politique (full)",
                    "Premiere cloture reduite",
                    "Derniere",
                    "Jours",
                    "Gain net",
                    "Nasdaq",
                    "Frais observes EUR",
                ],
                [
                    [
                        LABELS[row["policy"]],
                        row["first_reduced_close"],
                        row["last_reduced_close"],
                        str(row["sessions"]),
                        f"{row['strategy_net_return']:.2%}",
                        f"{row['benchmark_net_return']:.2%}",
                        f"{row['observed_costs_eur']:.2f}",
                    ]
                    for row in episodes
                    if row["period"] == "full" and row["cost_multiplier"] == 1
                ],
            ),
            "## Frais doubles et limites du verdict",
            "Les 30 simulations incluent de vrais rejeux aux frais doubles, sans "
            "changer les règles. Les statistiques complètes sont dans "
            "`reported_metrics.csv` et les contrastes dans `paired_effects.csv`. "
            "Le brut représente les mêmes transactions avec frais réintégrés ; ce"
            " n'est pas une politique qui aurait dimensionné autrement ses ordres"
            " sans frais.",
            "Les redémarrages annuels, les voisinages de paramètres non "
            "sélectionnables et une observation future réellement inconnue "
            "restent à publier avant toute conclusion de robustesse. Aucun "
            "meilleur contrôle ne devient automatiquement une nouvelle stratégie."
            " Une prochaine correction devra expliquer un défaut observé et faire"
            " l'objet d'un nouveau contrat avant son backtest.",
        ]
    )
    if dsr is not None:
        sections.extend(
            [
                "## Diagnostic de selection descriptif",
                "DSR absolu du candidat complet sur la tranche continue 2023-2024 "
                f"avec cloture precedente: {dsr['complete_policy_2023_2024_dsr']}. "
                "Compte 85; dispersion de Sharpe heritee des 80 courbes anterieures "
                f"({dsr['session_sharpe_std']:.8f}), non reestimee sur 85. "
                "C'est une approximation descriptive, pas une probabilite de battre Nasdaq "
                "ni une validation future. Aucun choix de politique ne depend de ce chiffre.",
            ]
        )
        (output / "descriptive_dsr.json").write_text(
            json.dumps(dsr, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
    else:
        sections.append(
            "Le compte85 est declare sans claim statistique; aucun DSR n'est "
            "calcule en l'absence de la dispersion anterieure archivee."
        )
    (output / "study.md").write_text("\n\n".join(sections) + "\n", encoding="utf-8")
    (output / "verdict.json").write_text(
        json.dumps(verdict, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"
    )
    generated = [*frames, "full_curves.png", "control_curves.png", "study.md", "verdict.json"]
    if dsr is not None:
        generated.append("descriptive_dsr.json")
    reporting = {
        "format": 1,
        "reader_source_sha256": sha256(Path(__file__)),
        "financial_manifest_sha256": sha256(output / "manifest.json"),
        "files": {name: sha256(output / name) for name in generated},
    }
    (output / "reporting_manifest.json").write_text(
        json.dumps(reporting, indent=2) + "\n", encoding="utf-8"
    )
    return verdict


def main() -> None:
    """Render only completed saved evidence; this command cannot run a backtest."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(render_report(args.output), indent=2))


if __name__ == "__main__":
    main()
