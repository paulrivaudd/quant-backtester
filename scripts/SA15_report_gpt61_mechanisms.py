"""Report matched R5 mechanism replays from saved evidence only.

This reader never imports a policy, market-data store or backtest runner.
Every regime uses only the preceding Nasdaq buy-and-hold NAV. Conditional
ablation differences are simulated counterfactuals, not causal market effects
or an additive accounting attribution. Presentation output cannot select a rule.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
import pandas as pd
import SA15_report_mechanism_pilot as pilot

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter

from quant_backtester.analytics.config import AnalyticsConfig
from quant_backtester.analytics.quality import deflated_sharpe_probability, session_sharpe

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "results/SA15_GPT-6.1_R5"
BENCHMARK = "Nasdaq_buy_hold"
REGIMES = ("unclassified", "rise", "fall", "recovery")
ANALYTICS = AnalyticsConfig(sessions_per_year=252, risk_free_rate=0.0, minimum_sessions=60)


@dataclass(frozen=True)
class SavedRun:
    """One archived replay with immutable financial evidence and role metadata."""

    policy: str
    period: str
    cost_multiplier: int
    folder: Path
    metrics: dict[str, Any]
    equity: pd.Series
    weights: pd.DataFrame
    fills: pd.DataFrame
    decisions: pd.DataFrame
    configuration: dict[str, Any]
    identity: dict[str, Any]


def read_json(path: Path) -> dict[str, Any]:
    """Require one saved JSON object, without inventing absent evidence."""
    return pilot.read_json(path)


def write_json(path: Path, value: object) -> None:
    """Write a finite presentation artifact while retaining all source evidence."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


def sha256(path: Path) -> str:
    """Return the SHA-256 of an existing evidence file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_label(label: str) -> None:
    """Restrict iteration labels to the fifty declared designs or their parent."""
    if len(label) != 3 or label[0] != "M" or not label[1:].isdigit():
        raise ValueError("iteration must be M00 through M50")
    if not 0 <= int(label[1:]) <= 50:
        raise ValueError("iteration must be M00 through M50")


def verify_artifacts(folder: Path) -> None:
    """Reject altered or incomplete financial cache files before reading results."""
    archived = read_json(folder / "cache.json")
    hashes = archived.get("artifacts")
    required = {
        "metrics.json",
        "equity.csv",
        "weights.csv",
        "fills.csv",
        "decisions.csv",
        "gross_equity.csv",
        "configuration.json",
        "identity.json",
    }
    if not isinstance(hashes, dict) or not required.issubset(hashes):
        raise ValueError("required financial artifact hashes are missing")
    for filename, digest in hashes.items():
        if Path(filename).name != filename or sha256(folder / filename) != digest:
            raise ValueError(f"financial artifact checksum differs: {filename}")


BASE_COSTS = {
    "commission_rate": 0.0005,
    "minimum_commission": 1.0,
    "half_spread_rate": 0.0003,
    "slippage_rate": 0.0002,
}
SCHEDULE_TYPES = {
    "monthly": "MonthlyFromStart",
    "weekly": "WeeklyFromStart",
    "quarterly": "QuarterlyFromStart",
}
TEMPORAL_FIELDS = (
    "fast_sessions",
    "medium_sessions",
    "slow_sessions",
    "ma_fast_sessions",
    "ma_slow_sessions",
    "vol_fast_returns",
    "vol_slow_returns",
    "drawdown_sessions",
    "defensive_sessions",
    "monetary_sessions",
)


def canonical_hash(value: object) -> str:
    """Hash already plain saved JSON with the financial archive's convention."""
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_costs(configuration: dict[str, Any], cost: int) -> None:
    """Check all four actual cost terms instead of trusting a folder label."""
    if isinstance(cost, bool) or cost not in (1, 2):
        raise ValueError("cost multiplier must be one or two")
    actual = configuration.get("execution", {}).get("costs", {})
    if not isinstance(actual, dict):
        raise ValueError("actual saved costs are missing")
    for name, base in BASE_COSTS.items():
        value = actual.get(name)
        if not isinstance(value, int | float) or not math.isfinite(value):
            raise ValueError(f"actual saved cost term is unavailable: {name}")
        if not math.isclose(value, base * cost, rel_tol=1e-12, abs_tol=1e-15):
            raise ValueError(f"actual saved cost multiplier differs: {name}")


def validate_signature(folder: Path, cost: int) -> dict[str, Any]:
    """Reconcile the signed policy, configuration, data identity and real costs."""
    archived = read_json(folder / "cache.json")
    signature = archived.get("signature")
    if not isinstance(signature, dict):
        raise ValueError("financial cache signature is absent")
    configuration = read_json(folder / "configuration.json")
    identity = read_json(folder / "identity.json")
    strategy = read_json(folder / "strategy.json")
    validate_costs(configuration, cost)
    if strategy != signature.get("strategy"):
        raise ValueError("saved strategy and cache signature differ")
    fingerprint = canonical_hash(strategy)
    if fingerprint != identity.get("fingerprint") or fingerprint != signature.get("fingerprint"):
        raise ValueError("saved policy fingerprint differs from its definition")
    if identity.get("data_state", {}).get("digest") != signature.get("data_state"):
        raise ValueError("saved data identity and signature differ")
    signed_configuration = signature.get("configuration")
    if not isinstance(signed_configuration, dict) or not signed_configuration:
        raise ValueError("signed execution configuration is absent")
    if any(configuration.get(key) != value for key, value in signed_configuration.items()):
        raise ValueError("saved configuration and cache signature differ")
    return signature


def verify_run_contract(
    output: Path,
    run: SavedRun,
    job: dict[str, Any],
    frozen: dict[str, Any],
    *,
    parameters: dict[str, Any] | None = None,
    schedule: str | None = None,
) -> None:
    """Bind one saved role to its announced canonical cache and physical evidence."""
    signature = validate_signature(run.folder, run.cost_multiplier)
    key = canonical_hash(signature)
    if key != job.get("cache_key"):
        raise ValueError("canonical financial signature differs from declared cache key")
    if not (run.folder / "cache_link.json").is_file():
        raise ValueError("financial cache link is missing")
    linked = read_json(run.folder / "cache_link.json")
    if linked != {"cache_key": key, "cache": f"cache/{key}"}:
        raise ValueError("financial cache link differs from its declared identity")
    physical = output / "cache" / key
    verify_artifacts(physical)
    if (physical / "cache.json").read_bytes() != (run.folder / "cache.json").read_bytes():
        raise ValueError("saved role and physical cache manifest differ")
    if signature.get("data_state") != frozen["data_state"]["digest"]:
        raise ValueError("financial signature differs from frozen data")
    if signature.get("source_finance_hashes") != frozen["source_finance_hashes"]:
        raise ValueError("financial signature differs from frozen sources")
    if int(job.get("cost_multiplier", 0)) != run.cost_multiplier or job.get("role") != run.policy:
        raise ValueError("saved replay role or cost differs from contract")
    start, end = job["start"], job["end"]
    config = run.configuration
    if config.get("requested_start") != start or config.get("requested_end") != end:
        raise ValueError("saved requested period differs from declared contract")
    if config.get("start") != start or config.get("end") != end:
        raise ValueError("saved realised period differs from declared contract")
    if (
        run.equity.index[0].date().isoformat() != start
        or run.equity.index[-1].date().isoformat() != end
    ):
        raise ValueError("saved NAV endpoints differ from declared period")
    if parameters is not None and signature["strategy"].get("parameters") != parameters:
        raise ValueError("saved policy parameters differ from declared profile")
    if schedule is not None and config["schedule"].get("type") != SCHEDULE_TYPES[schedule]:
        raise ValueError("saved policy cadence differs from declared profile")


def policy_profile(run: SavedRun) -> str:
    """Identify a policy together with its decision cadence for trial counting."""
    return canonical_hash(
        {
            "fingerprint": run.identity["fingerprint"],
            "schedule": run.configuration["schedule"],
        }
    )


def load_run(folder: Path, policy: str, period: str, cost: int) -> SavedRun:
    """Load one complete saved replay and reconcile NAV, fill costs and counts."""
    verify_artifacts(folder)
    validate_signature(folder, cost)
    curve = pilot.load_curve(folder / "equity.csv")
    metrics = read_json(folder / "metrics.json")
    pilot.validate_metrics(metrics, curve)
    gross = pilot.load_curve(folder / "gross_equity.csv")
    if not gross.index.equals(curve.index):
        raise ValueError("saved gross and net NAV sessions differ")
    if not math.isclose(
        float(gross.iloc[-1] / gross.iloc[0] - 1),
        metrics["gross_return"],
        abs_tol=1e-10,
    ):
        raise ValueError("saved gross NAV and return metric differ")
    weights = pd.read_csv(folder / "weights.csv", index_col=0, parse_dates=True)
    if not weights.index.equals(curve.index):
        raise ValueError("saved weights and NAV have different sessions")
    if not np.isfinite(weights.to_numpy(dtype=float)).all():
        raise ValueError("nonfinite saved position weights")
    if (weights < -1e-10).any().any() or (weights.sum(axis=1) > 1 + 1e-8).any():
        raise ValueError("saved positions violate long-only cash funding")
    fills = pd.read_csv(folder / "fills.csv")
    for key in ("session_date", "total_cost", "traded_value"):
        if key not in fills:
            raise ValueError(f"missing saved fill field: {key}")
    fills["session_date"] = pd.to_datetime(fills["session_date"])
    if len(fills) != metrics["fills"] or not fills.session_date.isin(curve.index).all():
        raise ValueError("saved fills and NAV/metrics differ")
    if not math.isclose(float(fills.total_cost.sum()), metrics["costs_eur"], abs_tol=1e-7):
        raise ValueError("saved fill costs and metrics differ")
    decisions = pd.read_csv(folder / "decisions.csv")
    if not {"session_date", "skipped"}.issubset(decisions):
        raise ValueError("saved decision fields are missing")
    decisions["session_date"] = pd.to_datetime(decisions["session_date"])
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


def validate_matched(runs: Mapping[str, SavedRun], *, allow_schedule_change: bool = False) -> None:
    """Require exact paired sessions, initial cash, prices and execution costs.

    A declared execution-block experiment may change the parent's schedule;
    this explicit experimental difference is not silently treated as a match.
    """
    if not {"candidate", "parent", BENCHMARK}.issubset(runs):
        raise ValueError("candidate, parent and Nasdaq hold are all required")
    baseline = runs[BENCHMARK]
    keys = (
        "start",
        "end",
        "initial_cash",
        "base_currency",
        "reference_calendar",
        "timetable",
        "universe",
        "portfolio",
        "execution",
        "quantity_steps",
    )
    for run in runs.values():
        validate_costs(run.configuration, run.cost_multiplier)
        if "schedule" not in run.configuration:
            raise ValueError("required schedule condition is absent")
        if (
            not allow_schedule_change
            and run.policy != BENCHMARK
            and run.configuration.get("schedule") != runs["candidate"].configuration.get("schedule")
        ):
            raise ValueError("paired execution conditions differ: schedule")
        if run.period != baseline.period or run.cost_multiplier != baseline.cost_multiplier:
            raise ValueError("paired periods or cost multipliers differ")
        if not run.equity.index.equals(baseline.equity.index):
            raise ValueError("paired NAV sessions differ")
        if run.equity.iloc[0] != baseline.equity.iloc[0]:
            raise ValueError("paired initial wealth differs")
        if not set(keys).issubset(run.configuration):
            raise ValueError("required paired execution conditions are absent")
        if any(run.configuration[key] != baseline.configuration[key] for key in keys):
            raise ValueError("paired execution conditions differ")
        if "data_state" not in run.identity or run.identity["data_state"] != baseline.identity.get(
            "data_state"
        ):
            raise ValueError("paired data vintages differ or are unavailable")


def diagnostic_regimes(benchmark: pd.Series) -> pd.Series:
    """Classify return day t using only the preceding saved Nasdaq NAV.

    Fixed conventions match the mechanism pilot: 126-session momentum;
    recovery requires positive 21-session momentum after a trailing 10 percent
    stress, otherwise rise/fall uses long momentum. The initial 127 rows are
    unclassified. NAV includes passive fund trading costs and integer lots;
    it is a common descriptive proxy, never an order-generation input.
    """
    return pilot.diagnostic_regimes(benchmark, lookback=126, recovery=21, stress=0.10)


def max_underwater_sessions(curve: pd.Series) -> int:
    """Count the longest consecutive sequence strictly below a past NAV peak."""
    underwater = curve < curve.cummax() - 1e-9
    groups = underwater.ne(underwater.shift()).cumsum()
    return int(underwater.groupby(groups).sum().max()) if len(curve) else 0


def operational_metrics(run: SavedRun) -> dict[str, Any]:
    """Summarize observed fills, signal checks, exposures and rejected inputs."""
    years = max((run.equity.index[-1] - run.equity.index[0]).days / 365.25, 1 / 252)
    cash = 1 - run.weights.sum(axis=1)
    rows = rejected_inputs(run)
    result = {
        "policy": run.policy,
        "period": run.period,
        "cost_multiplier": run.cost_multiplier,
        **run.metrics,
        "trade_dates": int(run.fills.session_date.nunique()),
        "trade_dates_per_year": float(run.fills.session_date.nunique() / years),
        "decision_dates": len(run.decisions),
        "decision_dates_per_year": len(run.decisions) / years,
        "mean_cash_weight": float(cash.mean()),
        "mean_nasdaq_weight": float(
            run.weights.get("ETF_NASDAQ", pd.Series(0.0, index=cash.index)).mean()
        ),
        "max_underwater_sessions": max_underwater_sessions(run.equity),
        "unavailable_input_rows": len(rows),
        "unavailable_decision_dates": len({row["session_date"] for row in rows}),
    }
    for asset in run.weights:
        result[f"mean_weight_{asset}"] = float(run.weights[asset].mean())
    return result


def rejected_inputs(run: SavedRun) -> list[dict[str, Any]]:
    """Publish every unavailable decision input with its archived status."""
    rows = []
    for _, row in run.decisions.iterrows():
        raw = row.get("plan_skipped", row["skipped"])
        skipped = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(skipped, dict):
            raise ValueError("decision skipped inputs must be a JSON object")
        for key, status in skipped.items():
            rows.append(
                {
                    "policy": run.policy,
                    "period": run.period,
                    "cost_multiplier": run.cost_multiplier,
                    "session_date": row["session_date"].date().isoformat(),
                    "input": key,
                    "status": str(status),
                    "core_weight": finite_or_none(row.get("core_weight")),
                    "missing_core": str(row.get("missing_core", "unavailable")),
                }
            )
    return rows


def finite_or_none(value: object) -> float | None:
    """Represent unavailable scalar diagnostics explicitly instead of as zero."""
    if value is None or pd.isna(value):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def block_effects(runs: Mapping[str, SavedRun]) -> list[dict[str, Any]]:
    """Measure complete candidate minus each real parent/ablation replay.

    Positive drawdown improvement means a shallower drawdown; positive CAGR
    cost means that protection sacrificed CAGR. Neither is additive across
    blocks, and no discarded ablation becomes an unregistered candidate.
    """
    candidate = runs["candidate"]
    a = operational_metrics(candidate)
    rows = []
    for role, run in runs.items():
        if role == "candidate":
            continue
        b = operational_metrics(run)
        rows.append(
            {
                "effect": role.removeprefix("without_") if role.startswith("without_") else role,
                "comparison": f"candidate_minus_{role}",
                "control": role,
                "period": candidate.period,
                "cost_multiplier": candidate.cost_multiplier,
                "net_return_difference": a["net_return"] - b["net_return"],
                "gross_return_difference": a["gross_return"] - b["gross_return"],
                "cagr_difference": a["cagr"] - b["cagr"],
                "cagr_cost_of_protection": b["cagr"] - a["cagr"],
                "drawdown_improvement": abs(b["max_drawdown"]) - abs(a["max_drawdown"]),
                "cost_difference_eur": a["costs_eur"] - b["costs_eur"],
                "trade_dates_difference": a["trade_dates"] - b["trade_dates"],
                "fills_difference": a["fills"] - b["fills"],
                "turnover_difference": a.get("turnover_per_year", 0)
                - b.get("turnover_per_year", 0),
                "underwater_sessions_difference": a["max_underwater_sessions"]
                - b["max_underwater_sessions"],
                "mean_nasdaq_weight_difference": a["mean_nasdaq_weight"] - b["mean_nasdaq_weight"],
                "unavailable_dates_difference": a["unavailable_decision_dates"]
                - b["unavailable_decision_dates"],
            }
        )
    return rows


def regime_metrics(run: SavedRun, reference: SavedRun, labels: pd.Series) -> list[dict[str, Any]]:
    """Compare actual paired NAV returns, never closing weights times returns."""
    if not run.equity.index.equals(reference.equity.index) or not labels.index.equals(
        run.equity.index
    ):
        raise ValueError("regime inputs need identical observed sessions")
    active = run.equity.pct_change(fill_method=None) - reference.equity.pct_change(fill_method=None)
    core = run.weights.get("ETF_NASDAQ", pd.Series(0.0, index=run.equity.index))
    rows = []
    for regime in REGIMES:
        mask = labels.eq(regime) & active.notna()
        dates = labels.index[mask]
        fills = run.fills[run.fills.session_date.isin(dates)]
        rows.append(
            {
                "policy": run.policy,
                "reference": reference.policy,
                "period": run.period,
                "cost_multiplier": run.cost_multiplier,
                "regime": regime,
                "sessions": int(mask.sum()),
                "mean_active_daily_bp": float(active[mask].mean() * 10_000) if mask.any() else None,
                "mean_nasdaq_closing_weight": float(core[mask].mean()) if mask.any() else None,
                "mean_cash_closing_weight": float((1 - run.weights.sum(axis=1))[mask].mean())
                if mask.any()
                else None,
                "trade_dates": int(fills.session_date.nunique()),
                "fills": len(fills),
                "costs_eur": float(fills.total_cost.sum()),
            }
        )
    return rows


def reduced_episodes(run: SavedRun, reference: SavedRun) -> list[dict[str, Any]]:
    """Publish every episode below 95 percent Nasdaq, including short reversals.

    Endpoints use observed closing positions, with the previous NAV as anchor.
    Episode return gaps and costs are descriptive, not causal block PnL. A
    short episode means at most 21 saved sessions, not proof of a false signal.
    """
    rows = pilot.reduced_episodes(run, reference, threshold=0.95)
    labels = diagnostic_regimes(reference.equity)
    for row in rows:
        first, last = (
            pd.Timestamp(row["first_reduced_close"]),
            pd.Timestamp(row["last_reduced_close"]),
        )
        subset = labels.loc[first:last]
        row["observed_return_difference"] = row["strategy_net_return"] - row["benchmark_net_return"]
        row["short_reduction_at_most_21_sessions"] = row["sessions"] <= 21
        row["recovery_sessions"] = int(subset.eq("recovery").sum())
        row["rise_sessions"] = int(subset.eq("rise").sum())
        row["fall_sessions"] = int(subset.eq("fall").sum())
    return rows


def load_iteration(output: Path, iteration: str) -> tuple[dict, dict[int, dict[str, SavedRun]]]:
    """Read declared matched cost sets, bound to frozen physical cache identities."""
    validate_label(iteration)
    folder = output / iteration
    if not (folder / "completed.json").is_file():
        raise ValueError("iteration has no completed evidence marker")
    spec = read_json(folder / "candidate.json")
    completed = read_json(folder / "completed.json")
    contract = read_json(folder / "contract.json")
    if completed.get("contract_sha256") != sha256(folder / "contract.json"):
        raise ValueError("iteration completed contract checksum differs")
    if contract.get("candidate") != spec or contract.get("candidate_sha256") != sha256(
        folder / "candidate.json"
    ):
        raise ValueError("iteration candidate and archived contract differ")
    frozen = read_json(output / "frozen_inputs.json")
    if contract.get("frozen_inputs_sha256") != sha256(output / "frozen_inputs.json"):
        raise ValueError("iteration frozen-input contract checksum differs")
    jobs = contract["contracts"]
    keys = {(int(job["cost_multiplier"]), job["role"]) for job in jobs}
    if len(keys) != len(jobs) or completed["logical_contract_count"] != len(jobs):
        raise ValueError("iteration contracts are duplicated or incomplete")
    runs = {}
    for cost in (1, 2):
        base = folder / "choice" / f"costs_x{cost}"
        roles = sorted(path.name for path in base.iterdir() if path.is_dir())
        if not {"candidate", "parent", BENCHMARK}.issubset(roles):
            raise ValueError("matched saved roles are incomplete")
        if {role for multiplier, role in keys if multiplier == cost} != set(roles):
            raise ValueError("saved matched roles differ from announced contracts")
        runs[cost] = {role: load_run(base / role, role, "choice", cost) for role in roles}
        validate_matched(
            runs[cost], allow_schedule_change=spec.get("changed_block") in ("execution", "cadence")
        )
        for role, run in runs[cost].items():
            job = next(
                item for item in jobs if item["role"] == role and item["cost_multiplier"] == cost
            )
            declared = {**job, "start": contract["start"], "end": contract["end"]}
            if [declared["start"], declared["end"]] != frozen["periods"]["choice"]:
                raise ValueError("choice period differs from frozen period")
            profile = (
                spec if role == "candidate" else contract["parent"] if role == "parent" else None
            )
            verify_run_contract(
                output,
                run,
                declared,
                frozen,
                parameters=profile["parameters"] if profile else None,
                schedule=profile["schedule"] if profile else None,
            )
    if set(runs[1]) != set(runs[2]):
        raise ValueError("cost stress is missing one paired policy")
    return spec, runs


def pct(value: object) -> str:
    """Format an optional fractional return as a percentage."""
    return "n.d." if value is None else f"{float(value) * 100:.2f} %"


def percentage_points(value: object) -> str:
    """Format a difference of fractional returns in percentage points."""
    return "n.d." if value is None else f"{float(value) * 100:.2f} pp"


def format_iteration(spec: dict, evidence: dict) -> str:
    """Render all block tradeoffs without selecting an attractive ablation."""
    lines = [
        f"# {evidence['iteration']} - analyse des mecanismes",
        "",
        f"Parent : {spec.get('parent')}. Bloc change : {spec.get('changed_block')}. ",
        "",
        str(spec.get("reason", "")),
        "",
        f"Benefice attendu : {spec.get('expected_benefit', '')}",
        "",
        f"Cout attendu : {spec.get('expected_cost', '')}",
        "",
        f"Refutation annoncee : {spec.get('refutation', '')}",
        "",
        "Comparaisons de vrais parcours continus 2019-2024 ; memes donnees et frais. "
        "Les deux niveaux de frais sont reellement simules. Histoire deja exploree.",
        "",
        "| Cout | Controle retire/parent | Delta CAGR | Amelioration DD | Delta frais EUR | "
        "Delta dates |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in evidence["block_effects"]:
        lines.append(
            f"| x{row['cost_multiplier']} | {row['control']} | "
            f"{percentage_points(row['cagr_difference'])} "
            f"| {percentage_points(row['drawdown_improvement'])} | "
            f"{row['cost_difference_eur']:.2f} "
            f"| {row['trade_dates_difference']} |"
        )
    lines.extend(
        [
            "",
            "Une amelioration DD positive signifie une perte maximale reduite. "
            "Les deltas CAGR/DD sont en points de pourcentage (pp). "
            "Un delta CAGR negatif est le prix en croissance de cette protection. "
            "Les effets conditionnels ne s'additionnent pas.",
            "",
            "Les CSV publient tous les regimes, episodes sous 95 % Nasdaq et inputs refuses. "
            "Les poids de cloture decrivent l'exposition ; ils ne servent jamais a reconstruire "
            "un PnL exact a partir de rendements deja realises. Les regimes de rendement t "
            "utilisent seulement le NAV Nasdaq connu a t-1 (126/21 seances, stress 10 %). "
            "Les 127 premieres observations restent non classees.",
            "",
            "La decision suivante est ecrite separement dans analysis.json par le chercheur. "
            "Aucune ablation n'est promue automatiquement.",
            "",
        ]
    )
    return "\n".join(lines)


def report_iteration(output: Path, iteration: str) -> dict[str, Any]:
    """Create presentation diagnostics for one completed iteration only."""
    spec, runs = load_iteration(output, iteration)
    operations, effects, regimes, episodes, unavailable = [], [], [], [], []
    for cost in (1, 2):
        group = runs[cost]
        labels = diagnostic_regimes(group[BENCHMARK].equity)
        effects.extend(block_effects(group))
        for run in group.values():
            operations.append(operational_metrics(run))
            regimes.extend(regime_metrics(run, group[BENCHMARK], labels))
            episodes.extend(reduced_episodes(run, group[BENCHMARK]))
            unavailable.extend(rejected_inputs(run))
        for role, control in group.items():
            if role not in ("candidate", BENCHMARK):
                regimes.extend(regime_metrics(group["candidate"], control, labels))
    evidence = {
        "iteration": iteration,
        "historical_status": "retrospective_already_explored",
        "candidate_sha256": sha256(output / iteration / "candidate.json"),
        "completed_sha256": sha256(output / iteration / "completed.json"),
        "candidate": spec,
        "parent_profile": read_json(output / iteration / "contract.json")["parent"],
        "financial_run_cache_sha256": {
            f"x{cost}/{role}": sha256(run.folder / "cache.json")
            for cost, group in runs.items()
            for role, run in group.items()
        },
        "operations": operations,
        "block_effects": effects,
        "regimes": regimes,
        "reduced_episodes": episodes,
        "unavailable_inputs": unavailable,
        "attribution": "conditional replay comparisons; no additive exact block PnL",
    }
    folder = output / iteration
    generated = []
    for name, rows in (
        ("operational_metrics", operations),
        ("block_effects", effects),
        ("regime_effects", regimes),
        ("reduced_episodes", episodes),
        ("rejected_inputs", unavailable),
    ):
        filename = f"{name}.csv"
        pd.DataFrame(rows).to_csv(folder / filename, index=False)
        generated.append(filename)
    write_json(folder / "attribution.json", evidence)
    (folder / "study.md").write_text(format_iteration(spec, evidence), encoding="utf-8")
    generated.extend(("attribution.json", "study.md"))
    write_json(
        folder / "reporting_manifest.json",
        {
            "reader_source_sha256": sha256(Path(__file__)),
            "reader_dependency_sha256": sha256(Path(pilot.__file__)),
            "files": {name: sha256(folder / name) for name in generated},
            "source_evidence_untouched": True,
        },
    )
    return evidence


def bootstrap_active(strategy: pd.Series, benchmark: pd.Series) -> dict[str, Any]:
    """Bootstrap paired mean active returns in circular fixed 20-session blocks."""
    if not strategy.index.equals(benchmark.index):
        raise ValueError("bootstrap curves require exact paired sessions")
    active = (strategy.pct_change(fill_method=None) - benchmark.pct_change(fill_method=None)).iloc[
        1:
    ]
    values = active.to_numpy(dtype=float)
    if not len(values) or not np.isfinite(values).all():
        raise ValueError("bootstrap needs finite paired returns")
    rng = np.random.default_rng(61155)
    estimates = np.empty(2000)
    for index in range(len(estimates)):
        starts = rng.integers(0, len(values), size=math.ceil(len(values) / 20))
        positions = ((starts[:, None] + np.arange(20)) % len(values)).ravel()[: len(values)]
        estimates[index] = values[positions].mean() * 252
    return {
        "annualised_mean_active_return": float(values.mean() * 252),
        "lower_95": float(np.quantile(estimates, 0.025)),
        "upper_95": float(np.quantile(estimates, 0.975)),
        "replications": 2000,
        "block_sessions": 20,
        "seed": 61155,
        "interpretation": "paired arithmetic mean active return, not CAGR or future probability",
    }


def observed_trial_counts(output: Path) -> dict[str, Any]:
    """Declare prior research plus all fifty designs and distinct viewed ablations."""
    ablations, fingerprints = set(), set()
    for number in range(1, 51):
        folder = output / f"M{number:02d}"
        if not (folder / "completed.json").is_file():
            raise ValueError("all fifty completed designs are required for final reporting")
        base = folder / "choice" / "costs_x1"
        for path in base.glob("without_*/*identity.json"):
            identity = read_json(path)
            if "fingerprint" not in identity:
                raise ValueError("ablation identity has no policy fingerprint")
            fingerprints.add(identity["fingerprint"])
            configuration = read_json(path.parent / "configuration.json")
            ablations.add(
                canonical_hash(
                    {
                        "fingerprint": identity["fingerprint"],
                        "schedule": configuration["schedule"],
                    }
                )
            )
    return {
        "prior_designs_and_pilot_policies": 85,
        "r5_designs": 50,
        "distinct_viewed_ablation_fingerprints": len(fingerprints),
        "distinct_viewed_ablation_profiles": len(ablations),
        "predeclared_parameter_sensitivities": 2,
        "trials_declared": 85 + 50 + len(ablations) + 2,
        "interpretation": "conservative diagnostic count; duplicates with designs may remain",
    }


def descriptive_dsr(curve: pd.Series, all_curves: list[pd.Series], trials: int) -> dict[str, Any]:
    """Deflate absolute Sharpe using observed dispersion and conservative trials."""
    sharpes = []
    for observed in all_curves:
        copy = observed.copy()
        copy.index = pd.Index(copy.index.date, dtype="object", name="session_date")
        value = session_sharpe(copy, ANALYTICS)
        if value is not None and math.isfinite(value):
            sharpes.append(value)
    if len(sharpes) < 2:
        raise ValueError("DSR requires at least two observed finite policy Sharpes")
    dispersion = float(np.std(sharpes, ddof=1))
    copy = curve.copy()
    copy.index = pd.Index(copy.index.date, dtype="object", name="session_date")
    return {
        "trials_declared": trials,
        "available_dispersion_curves": len(sharpes),
        "session_sharpe_std": dispersion,
        "absolute_sharpe_dsr": deflated_sharpe_probability(
            copy,
            ANALYTICS,
            trials=trials,
            trial_sharpe_std=dispersion,
        ),
        "interpretation": (
            "approximate absolute Sharpe diagnostic, not probability of beating Nasdaq"
        ),
    }


def plot_curves(curves: Mapping[str, pd.Series], path: Path) -> None:
    """Plot complete observed NAV and drawdown without selecting subperiods."""
    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True, layout="constrained")
    for name, curve in curves.items():
        axes[0].plot(curve.index, curve / curve.iloc[0], label=name)
        axes[1].plot(curve.index, curve / curve.cummax() - 1, label=name)
    axes[0].set_ylabel("Capital initial = 1, net")
    axes[1].set_ylabel("Drawdown")
    axes[1].yaxis.set_major_formatter(PercentFormatter(1))
    for axis in axes:
        axis.grid(alpha=0.25)
    axes[0].legend(loc="upper left")
    fig.savefig(path, dpi=160)
    plt.close(fig)


def plot_mechanism_frontier(
    rows: list[dict[str, Any]],
    benchmark_cagr: float,
    selected_id: str,
    path: Path,
) -> None:
    """Plot all fifty saved designs without computing a new portfolio ranking.

    Coordinates are the net annual return and absolute maximum drawdown of
    each complete choice replay. Color encodes actual fill dates per calendar
    year. Only the already frozen candidate receives an individual highlight.
    """
    frame = pd.DataFrame(rows)
    expected = {f"M{number:02d}" for number in range(1, 51)}
    required = {"id", "cagr", "max_drawdown", "trade_dates_per_year"}
    if not required.issubset(frame) or len(frame) != 50 or set(frame["id"]) != expected:
        raise ValueError("the scientific frontier requires all fifty unique designs")
    if selected_id not in expected or not math.isfinite(benchmark_cagr):
        raise ValueError("frontier frozen selection or Nasdaq reference is invalid")
    numbers = frame[["cagr", "max_drawdown", "trade_dates_per_year"]].to_numpy(dtype=float)
    if not np.isfinite(numbers).all() or (frame["trade_dates_per_year"] < 0).any():
        raise ValueError("frontier metrics must be finite with nonnegative trading dates")
    absolute_dd = frame["max_drawdown"].abs()
    if (absolute_dd > 1).any():
        raise ValueError("frontier drawdown must be a fractional loss")
    fig, axis = plt.subplots(figsize=(11, 8), layout="constrained")
    dots = axis.scatter(
        absolute_dd,
        frame["cagr"],
        c=frame["trade_dates_per_year"],
        cmap="viridis",
        s=62,
        edgecolors="white",
        linewidths=0.5,
        alpha=0.9,
    )
    chosen = frame.loc[frame["id"].eq(selected_id)].iloc[0]
    axis.scatter(
        [abs(chosen["max_drawdown"])],
        [chosen["cagr"]],
        marker="*",
        s=330,
        facecolors="none",
        edgecolors="black",
        linewidths=1.5,
        label=f"Candidat deja fige : {selected_id}",
        zorder=4,
    )
    axis.annotate(
        selected_id,
        (abs(chosen["max_drawdown"]), chosen["cagr"]),
        xytext=(9, 7),
        textcoords="offset points",
        weight="bold",
    )
    axis.axhline(
        benchmark_cagr,
        color="#a13d2d",
        linestyle="--",
        linewidth=1.2,
        label="CAGR Nasdaq conserve, memes frais",
    )
    axis.axvline(
        0.25,
        color="#555555",
        linestyle=":",
        linewidth=1.2,
        label="Preference de recherche : drawdown 25 %",
    )
    colorbar = fig.colorbar(dots, ax=axis, pad=0.025)
    colorbar.set_label("Dates avec transactions par an (achat initial compris)")
    axis.set_xlabel("Drawdown maximal absolu")
    axis.set_ylabel("CAGR net annuel")
    axis.xaxis.set_major_formatter(PercentFormatter(1))
    axis.yaxis.set_major_formatter(PercentFormatter(1))
    axis.set_title("R5 : les 50 mecanismes testes sur 2019-2024")
    axis.text(
        0.01,
        -0.15,
        "Recherche retrospective ; couleur = interventions observees. "
        "Aucune selection supplementaire.",
        transform=axis.transAxes,
        fontsize=9,
    )
    axis.grid(alpha=0.22)
    axis.legend(loc="best", fontsize=9)
    fig.savefig(path, dpi=170)
    plt.close(fig)


def validation_verdict(
    operations: list[dict[str, Any]],
    selected_qualified: bool,
    bootstrap_intervals: Mapping[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Apply the frozen refutation and the pre-final operational clarification.

    Only normal-cost final/full underperformance implies NOT_SUPPORTED.
    Missed targets or controls imply UNCERTAIN; all favorable controls allow
    SUPPORTED_RETROSPECTIVE while independent future evidence remains absent.
    No DSR threshold was preregistered, so that diagnostic cannot gate status.
    """
    indexed = {(row["period"], row["cost_multiplier"], row["policy"]): row for row in operations}
    main_failures, cost_failures, stability_failures, target_failures = [], [], [], []
    uncertainties = []
    expected_periods = (
        "choice",
        "full",
        "final",
        "start_2020",
        "start_2021",
        "start_2022",
        "start_2023",
        "neighbor_short",
        "neighbor_long",
    )
    drawdown_reduced = True
    for period in expected_periods:
        for cost in (1, 2):
            candidate = indexed.get((period, cost, "candidate"))
            hold = indexed.get((period, cost, BENCHMARK))
            if candidate is None or hold is None:
                if period in ("final", "full") and cost == 1:
                    raise ValueError("normal-cost final/full evidence is required for verdict")
                uncertainties.append(f"required control unavailable: {period} costs_x{cost}")
                continue
            if candidate["net_return"] <= hold["net_return"]:
                reason = f"frozen candidate does not beat Nasdaq on {period} costs_x{cost}"
                if period in ("final", "full") and cost == 1:
                    main_failures.append(reason)
                elif cost == 2:
                    cost_failures.append(reason)
                else:
                    stability_failures.append(reason)
            if abs(candidate["max_drawdown"]) > 0.25 or candidate["trade_dates_per_year"] > 4:
                target_failures.append(f"risk/intervention target missed: {period} costs_x{cost}")
            if period in ("final", "full"):
                drawdown_reduced = drawdown_reduced and (
                    abs(candidate["max_drawdown"]) < abs(hold["max_drawdown"])
                )
    if not selected_qualified:
        uncertainties.append("selected design missed the predeclared choice qualification")
    interval_failures = []
    for period in ("full", "final"):
        lower = (bootstrap_intervals or {}).get(period, {}).get("lower_95")
        if lower is None or not math.isfinite(float(lower)) or float(lower) <= 0:
            interval_failures.append(f"paired active mean interval not strictly positive: {period}")
    uncertainties.extend(cost_failures + stability_failures + target_failures + interval_failures)
    status = (
        "NOT_SUPPORTED"
        if main_failures
        else "UNCERTAIN"
        if uncertainties
        else "SUPPORTED_RETROSPECTIVE"
    )
    return {
        "status": status,
        "reasons": main_failures
        or uncertainties
        or ["all declared retrospective controls favorable"],
        "cost_stress_failures": cost_failures,
        "stability_failures": stability_failures,
        "risk_intervention_failures": target_failures,
        "active_interval_failures": interval_failures,
        "risk_and_intervention_targets_met": not target_failures,
        "drawdown_reduced_vs_benchmark_all_final_comparisons": drawdown_reduced,
        "independent_future_validation": False,
        "default_reference": BENCHMARK,
        "automatic_promotion_of_ablation_or_runner_up": False,
        "dsr_is_descriptive_not_gating": True,
        "operational_clarification": "reporting_review.md, written before final/robustness results",
    }


def clean_cell(value: object) -> str:
    """Keep multiline research reasons inside one Markdown cell."""
    if isinstance(value, list):
        value = "; ".join(str(item) for item in value)
    return str(value).replace("|", "/").replace("\n", " ")


def final_evidence(output: Path) -> tuple[dict, list[SavedRun]]:
    """Require exactly the frozen candidate's announced post-selection controls."""
    selected = read_json(output / "selected.json")
    if (output / "selected.sha256").read_text().strip() != sha256(output / "selected.json"):
        raise ValueError("frozen selection checksum differs")
    validate_label(selected["id"])
    chosen_folder = output / selected["id"]
    if selected["completed_sha256"] != sha256(chosen_folder / "completed.json"):
        raise ValueError("frozen selected evidence differs")
    frozen = read_json(output / "frozen_inputs.json")
    if selected["frozen_inputs_sha256"] != sha256(output / "frozen_inputs.json"):
        raise ValueError("selected frozen inputs differ")
    if selected["candidate"] != read_json(chosen_folder / "candidate.json"):
        raise ValueError("frozen candidate specification differs")
    if selected["analysis"] != {
        "id": selected["id"],
        "sha256": sha256(chosen_folder / "analysis.json"),
    }:
        raise ValueError("selected mechanism diagnosis differs")
    chosen_run = load_run(chosen_folder / "choice/costs_x1/candidate", "candidate", "choice", 1)
    if selected["fingerprint"] != chosen_run.identity["fingerprint"]:
        raise ValueError("selected policy fingerprint differs from chosen evidence")
    starts = ("2020-01-02", "2021-01-04", "2022-01-03", "2023-01-02")
    periods = {
        "final": {name: frozen["periods"][name] for name in ("final", "full")},
        "robustness": {
            **{f"start_{start[:4]}": [start, frozen["periods"]["choice"][1]] for start in starts},
            "neighbor_short": frozen["periods"]["choice"],
            "neighbor_long": frozen["periods"]["choice"],
        },
    }
    runs = []
    for kind in ("final", "robustness"):
        completed = read_json(output / f"{kind}_completed.json")
        contracts = read_json(output / f"{kind}_contracts.json")
        if completed["contract_sha256"] != sha256(output / f"{kind}_contracts.json"):
            raise ValueError("diagnostic completion contract differs")
        if contracts["selection_sha256"] != sha256(output / "selected.json"):
            raise ValueError("diagnostics did not use this frozen selection")
        jobs = contracts["contracts"]
        expected = {
            (name, cost, role)
            for name in periods[kind]
            for cost in (1, 2)
            for role in ("candidate", BENCHMARK)
        }
        observed = {(job["period"], job["cost_multiplier"], job["role"]) for job in jobs}
        if (
            observed != expected
            or len(jobs) != len(expected)
            or completed["logical_contract_count"] != len(jobs)
        ):
            raise ValueError("diagnostic contract grid is incomplete or duplicated")
        pairs = {}
        for job in jobs:
            period, cost, role = job["period"], int(job["cost_multiplier"]), job["role"]
            if [job["start"], job["end"]] != periods[kind][period] or job.get(
                "nonselectable"
            ) is not True:
                raise ValueError("diagnostic period or nonselectable status differs")
            prefix = f"robustness/{period}" if kind == "robustness" else period
            if job.get("folder") != prefix:
                raise ValueError("diagnostic folder differs from declared layout")
            folder = output / prefix / f"costs_x{cost}" / role
            run = load_run(folder, role, period, cost)
            parameters = dict(selected["candidate"]["parameters"])
            if role == BENCHMARK:
                parameters = {"instruments": ["ETF_NASDAQ"], "strategy_id": BENCHMARK}
            elif period in ("neighbor_short", "neighbor_long"):
                factor = 0.8 if period == "neighbor_short" else 1.2
                for name in TEMPORAL_FIELDS:
                    parameters[name] = round(parameters[name] * factor)
            if job.get("parameters") != parameters:
                raise ValueError("diagnostic parameters differ from the frozen profile")
            verify_run_contract(
                output,
                run,
                job,
                frozen,
                parameters=parameters,
                schedule=selected["candidate"]["schedule"] if role == "candidate" else None,
            )
            if (
                role == "candidate"
                and period not in ("neighbor_short", "neighbor_long")
                and run.identity["fingerprint"] != selected["fingerprint"]
            ):
                raise ValueError("diagnostic candidate differs from the frozen winner")
            runs.append(run)
            pairs.setdefault((period, cost), {})[role] = run
        for pair in pairs.values():
            validate_matched({**pair, "parent": pair["candidate"]})
    return selected, runs


def historical_replays(path: Path | None) -> dict[str, Any]:
    """Retain technical attempts as physical work without inventing new designs."""
    if path is None:
        return {
            "physical_failed_serialization_replays": 0,
            "additional_candidate_designs": 0,
            "attempts": [],
        }
    value = read_json(path)
    count = value.get("physical_failed_serialization_replays")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ValueError("historical failed serialization replay count is invalid")
    if value.get("additional_candidate_designs") != 0:
        raise ValueError("unexpected additional historical candidate designs")
    if sum(item["failed_physical_replays"] for item in value["attempts"]) != count:
        raise ValueError("historical attempt counts do not reconcile")
    for attempt in value["attempts"]:
        base = (ROOT / attempt["path"]).resolve()
        if not base.is_relative_to(ROOT.resolve()):
            raise ValueError("historical attempt path escapes workspace")
        for name, digest in attempt.get("source_archives", {}).items():
            source = (base / name).resolve()
            if not source.is_relative_to(base) or sha256(source) != digest:
                raise ValueError("historical source archive checksum differs")
    return {**value, "manifest_sha256": sha256(path)}


def audit_note_links(output: Path) -> str:
    """Link existing audit notes without using their counts in statistical logic."""
    causal = output / "causality_readonly.md"
    notes = ([causal] if causal.is_file() else []) + sorted(output.glob("*audit*.md"))
    if not notes:
        return ""
    links = []
    for path in notes:
        label = (
            "Controle causal informatique ponctuel"
            if path == causal
            else path.stem.replace("_", " ")
        )
        links.append(f"[{label}]({path.name})")
    return (
        "Tracabilite des verifications en lecture seule : " + ", ".join(links) + ". "
        "Leur perimetre est precise dans chaque note. Ces controles informatiques ponctuels "
        "ne prouvent ni l'absence de surajustement, ni des prix fournisseur effectivement "
        "point-in-time. Ils ne changent pas les effectifs ou criteres statistiques du rapport."
    )


def report_final(output: Path, historical_attempts: Path | None = None) -> dict[str, Any]:
    """Summarize fifty mechanism designs without performing any selection."""
    counts = observed_trial_counts(output)
    history = historical_replays(historical_attempts)
    selected, diagnostic_runs = final_evidence(output)
    iteration_rows, curves, fingerprints = [], [], set()
    operations = [operational_metrics(run) for run in diagnostic_runs]
    final_regimes, final_episodes, final_unavailable = [], [], []
    for run in diagnostic_runs:
        hold = next(
            item
            for item in diagnostic_runs
            if item.period == run.period
            and item.cost_multiplier == run.cost_multiplier
            and item.policy == BENCHMARK
        )
        labels = diagnostic_regimes(hold.equity)
        final_regimes.extend(regime_metrics(run, hold, labels))
        final_episodes.extend(reduced_episodes(run, hold))
        final_unavailable.extend(rejected_inputs(run))
        if run.period in ("neighbor_short", "neighbor_long") and run.cost_multiplier == 1:
            fingerprint = policy_profile(run)
            if fingerprint not in fingerprints:
                curves.append(run.equity)
                fingerprints.add(fingerprint)
    for number in range(1, 51):
        identifier = f"M{number:02d}"
        spec, groups = load_iteration(output, identifier)
        analysis = read_json(output / identifier / "analysis.json")
        if analysis.get("completed_sha256") != sha256(output / identifier / "completed.json"):
            raise ValueError("mechanism diagnosis is not bound to its evidence")
        candidate = groups[1]["candidate"]
        parent = groups[1]["parent"]
        hold = groups[1][BENCHMARK]
        stats = operational_metrics(candidate)
        effect = next(row for row in block_effects(groups[1]) if row["control"] == "parent")
        completed = read_json(output / identifier / "completed.json")
        iteration_rows.append(
            {
                "id": identifier,
                "parent": spec["parent"],
                "changed_block": spec["changed_block"],
                "reason": spec["reason"],
                "expected_benefit": spec["expected_benefit"],
                "expected_cost": spec["expected_cost"],
                "refutation": spec["refutation"],
                "decision": analysis["decision"],
                "findings": clean_cell(analysis["findings"]),
                "next_defect": clean_cell(analysis["next_defect"]),
                "cagr": candidate.metrics["cagr"],
                "cagr_excess_vs_nasdaq": candidate.metrics["cagr"] - hold.metrics["cagr"],
                "cagr_change_vs_parent": candidate.metrics["cagr"] - parent.metrics["cagr"],
                "max_drawdown": candidate.metrics["max_drawdown"],
                "drawdown_improvement_vs_parent": effect["drawdown_improvement"],
                "trade_dates": stats["trade_dates"],
                "trade_dates_per_year": stats["trade_dates_per_year"],
                "costs_eur": stats["costs_eur"],
                "qualified": completed["score"]["qualified"],
            }
        )
        for run in groups[1].values():
            fingerprint = policy_profile(run)
            if fingerprint not in fingerprints:
                curves.append(run.equity)
                fingerprints.add(fingerprint)
        if identifier == selected["id"]:
            operations.extend(
                operational_metrics(run) for group in groups.values() for run in group.values()
            )
    pd.DataFrame(iteration_rows).to_csv(output / "reported_iterations.csv", index=False)
    pd.DataFrame(operations).to_csv(output / "reported_metrics.csv", index=False)
    bootstraps = {}
    for period in ("full", "final"):
        group = {
            run.policy: run
            for run in diagnostic_runs
            if run.period == period and run.cost_multiplier == 1
        }
        bootstraps[period] = bootstrap_active(group["candidate"].equity, group[BENCHMARK].equity)
    verdict = validation_verdict(operations, bool(selected["qualified"]), bootstraps)
    verdict.update(counts)
    verdict["completed_physical_replays"] = sum(1 for _ in (output / "cache").glob("*/cache.json"))
    verdict["physical_attempts"] = sum(1 for _ in (output / "cache").glob("*/attempt.json"))
    verdict["logical_contracts"] = sum(
        len(read_json(path)["contracts"])
        for path in [
            *output.glob("M[0-9][0-9]/contract.json"),
            output / "final_contracts.json",
            output / "robustness_contracts.json",
        ]
    )
    verdict["historical_failed_serialization_replays"] = history[
        "physical_failed_serialization_replays"
    ]
    verdict["physical_attempts_including_archived"] = (
        verdict["physical_attempts"] + history["physical_failed_serialization_replays"]
    )
    verdict["historical_additional_candidate_designs"] = history["additional_candidate_designs"]
    verdict["selected_id"] = selected["id"]
    write_json(output / "verdict.json", verdict)
    dsr = None
    generated = ["reported_iterations.csv", "reported_metrics.csv", "verdict.json"]
    for name, rows in (
        ("diagnostic_regimes", final_regimes),
        ("diagnostic_reduced_episodes", final_episodes),
        ("diagnostic_unavailable_inputs", final_unavailable),
    ):
        pd.DataFrame(rows).to_csv(output / f"{name}.csv", index=False)
        generated.append(f"{name}.csv")
    selected_hold = next(
        row
        for row in operations
        if row["period"] == "choice" and row["cost_multiplier"] == 1 and row["policy"] == BENCHMARK
    )
    plot_mechanism_frontier(
        iteration_rows,
        selected_hold["cagr"],
        selected["id"],
        output / "mechanism_frontier.png",
    )
    generated.append("mechanism_frontier.png")
    for period in ("full", "final"):
        group = {
            run.policy: run
            for run in diagnostic_runs
            if run.period == period and run.cost_multiplier == 1
        }
        plot_curves(
            {selected["id"]: group["candidate"].equity, BENCHMARK: group[BENCHMARK].equity},
            output / f"{period}_curves.png",
        )
        generated.append(f"{period}_curves.png")
    chosen = pilot.load_curve(output / selected["id"] / "choice/costs_x1/candidate/equity.csv")
    dsr = descriptive_dsr(chosen, curves, counts["trials_declared"])
    write_json(output / "bootstrap_active.json", bootstraps)
    write_json(output / "descriptive_dsr.json", {**counts, **dsr})
    generated.extend(("bootstrap_active.json", "descriptive_dsr.json"))
    lines = [
        "# SA15 R5 - cinquante iterations par mecanismes",
        "",
        f"Verdict : **{verdict['status']}**. Candidat fige : **{selected['id']}**.",
        "",
        "Chaque iteration declare un seul mecanisme change puis rejoue candidat, parent, "
        "Nasdaq conserve et chaque bloc retire, aux frais normaux et doubles. Les poids "
        "proviennent des indicateurs disponibles au moment de la decision ; aucune grille "
        "de melanges permanents ni selection de meilleurs morceaux historiques.",
        "",
        f"Simulations physiques completes : {verdict['completed_physical_replays']}; "
        f"comparaisons logiques archivees : {verdict['logical_contracts']}. "
        f"Tentatives physiques avec archives : {verdict['physical_attempts_including_archived']}, "
        f"dont {verdict['historical_failed_serialization_replays']} echec de serialisation "
        "de journal conserve separement, sans nouveau design. Les copies de "
        "cache identiques ne sont pas comptees comme de nouveaux calculs.",
        "",
        "L'histoire 2019-2026 etait deja exploree. Les controles chronologiques et departs "
        "depuis cash restent retrospectifs. L'adaptation des mecanismes peut surajuster.",
        "",
        "| Periode | Cout | Regle | Gain brut | Gain net | CAGR net | Drawdown net | "
        "Dates ordres | Frais EUR |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in operations:
        if row["period"] in ("full", "final"):
            lines.append(
                f"| {row['period']} | x{row['cost_multiplier']} | {row['policy']} "
                f"| {pct(row['gross_return'])} | {pct(row['net_return'])} "
                f"| {pct(row['cagr'])} "
                f"| {pct(row['max_drawdown'])} | {row['trade_dates']} "
                f"| {row['costs_eur']:.2f} |"
            )
    lines.extend(
        [
            "",
            "Dates avec transactions, achat initial compris. Une date peut contenir plusieurs "
            "ordres. Le nombre de verifications de signaux est distinct dans reported_metrics.csv. "
            "Montants en EUR, avant fiscalite. Gain brut : memes transactions sans frais. "
            "Gain net, CAGR et drawdown : apres commission, spread et slippage simules. "
            "Les lignes x2 sont de vrais replays avec frais doubles.",
            "",
            "![Parcours complet](full_curves.png)",
            "",
            "![Controle recent](final_curves.png)",
            "",
            "![Les cinquante mecanismes](mechanism_frontier.png)",
            "",
            "| Iteration | Parent | Bloc | Raison avant calcul | Delta CAGR parent | "
            "Gain DD parent | Decision | Defaut suivant |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in iteration_rows:
        lines.append(
            "| "
            + " | ".join(
                clean_cell(value)
                for value in (
                    f"[{row['id']}]({row['id']}/study.md)",
                    row["parent"],
                    row["changed_block"],
                    row["reason"],
                    percentage_points(row["cagr_change_vs_parent"]),
                    percentage_points(row["drawdown_improvement_vs_parent"]),
                    row["decision"],
                    row["next_defect"],
                )
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "Les analyses individuelles conservent effets conditionnels des blocs, effets "
            "negatifs, regimes communs, expositions pendant les reprises, tous les episodes "
            "de reduction et les inputs indisponibles. Les effets d'ablations ne sont ni une "
            "attribution comptable additive, ni une preuve de causalite economique.",
            "",
            f"Nombre d'essais declare au diagnostic DSR : {counts['trials_declared']} = 85 "
            f"anterieurs/pilote + 50 designs + {counts['distinct_viewed_ablation_profiles']} "
            "profils d'ablation distincts (politique + cadence) + 2 sensibilites predeclarees. "
            "Frais doubles et "
            "repetitions de cache ne sont pas "
            "de nouvelles idees. Le DSR est une approximation du Sharpe absolu ; ce n'est pas "
            "une probabilite de battre Nasdaq.",
            "",
            "Le bootstrap est appaire (blocs circulaires de 20 seances, 2 000 tirages, graine "
            "61155). Il mesure la moyenne arithmetique annualisee des rendements actifs, "
            "pas le CAGR ni un resultat futur. Voir bootstrap_active.json et descriptive_dsr.json.",
            "",
            "La [revue du rapport](../../research/SA15_GPT-6.1/round5/reporting_review.md) "
            "distingue le contrat initial de sa precision operationnelle conservatrice, ecrite "
            "avant les replays finaux : cibles appliquees aux departs et voisins, intervalles "
            "actifs strictement positifs, DSR descriptif sans seuil. Aucun parametre ni selection "
            "n'a ete change par cette precision.",
            "",
            "Nasdaq conserve reste la reference simple. Aucun autre candidat ou ablation n'est "
            "promu apres lecture des controles. Une eventualite prometteuse necessite une "
            "regle figee et une observation future independante.",
            "",
        ]
    )
    traceability = audit_note_links(output)
    if traceability:
        lines.extend(["", traceability, ""])
    (output / "study.md").write_text("\n".join(lines), encoding="utf-8")
    generated.append("study.md")
    write_json(
        output / "reporting_manifest.json",
        {
            "reader_source_sha256": sha256(Path(__file__)),
            "reader_dependency_sha256": sha256(Path(pilot.__file__)),
            "selection_sha256": sha256(output / "selected.json"),
            "files": {name: sha256(output / name) for name in generated},
            "financial_evidence_untouched": True,
        },
    )
    return verdict


def brief_iteration(evidence: dict[str, Any]) -> dict[str, Any]:
    """Expose compact tradeoffs for the next explicitly written mechanism diagnosis."""
    performance_keys = (
        "policy",
        "cagr",
        "net_return",
        "max_drawdown",
        "trade_dates",
        "costs_eur",
        "mean_nasdaq_weight",
        "unavailable_decision_dates",
    )
    effect_keys = (
        "cost_multiplier",
        "control",
        "cagr_difference",
        "drawdown_improvement",
        "cost_difference_eur",
        "trade_dates_difference",
    )
    return {
        "iteration": evidence["iteration"],
        "performance_x1": [
            {key: row[key] for key in performance_keys}
            for row in evidence["operations"]
            if row["cost_multiplier"] == 1
        ],
        "block_effects": [
            {key: row[key] for key in effect_keys} for row in evidence["block_effects"]
        ],
        "candidate_regimes_x1": [
            row
            for row in evidence["regimes"]
            if row["policy"] == "candidate"
            and row["reference"] in ("parent", BENCHMARK)
            and row["cost_multiplier"] == 1
        ],
        "all_evidence": f"{evidence['iteration']}/attribution.json",
    }


def main() -> None:
    """Read one completed iteration; never launch a financial simulation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--iteration")
    mode.add_argument("--final", action="store_true")
    parser.add_argument(
        "--historical-attempts",
        type=Path,
        default=ROOT / "research/SA15_GPT-6.1/round5/historical_attempts.json",
    )
    args = parser.parse_args()
    if args.final:
        print(json.dumps(report_final(args.output, args.historical_attempts), indent=2))
    else:
        result = report_iteration(args.output, args.iteration)
        print(json.dumps(brief_iteration(result), indent=2))


if __name__ == "__main__":
    main()
