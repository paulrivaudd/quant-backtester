"""Run the bounded, chronological SA15_GPT-6.1 research study.

Each candidate is supplied as a JSON file with number, reason, parameters and
schedule. The final phase freezes the best development/validation score before
reading the final period. Only the data download script accesses the network.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import zipfile
from collections.abc import Mapping
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from quant_backtester.analytics.benchmark_comparison import alpha_vs_benchmark
from quant_backtester.analytics.config import AnalyticsConfig
from quant_backtester.backtest.runner import StrategyResult, StrategyRunner, plain_configuration
from quant_backtester.backtest.schedule import DecisionSchedule, EverySession, Monthly, Weekly
from quant_backtester.data.calendars import CalendarRegistry
from quant_backtester.data.instruments import InstrumentRegistry
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.data.repository import MarketDataRepository
from quant_backtester.execution.costs import CostModel
from quant_backtester.execution.model import ExecutionModel, Sizing
from quant_backtester.provenance import git_source_state
from quant_backtester.research.references import BuyAndHold, EqualWeightRebalance
from quant_backtester.strategies.base import Strategy
from quant_backtester.strategies.SA1_world_ma20_benchmark import WorldMA20Benchmark
from quant_backtester.strategies.SA15_gpt61 import SA15GPT61

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STORE = ROOT / "runs/sa15_gpt61_store"
DEFAULT_OUTPUT = ROOT / "results/SA15_GPT-6.1"
ANALYTICS = AnalyticsConfig(sessions_per_year=252, risk_free_rate=0.0, minimum_sessions=60)
PERIODS = {
    "development": ("2019-06-03", "2022-12-30"),
    "validation": ("2023-01-02", "2024-12-31"),
    "final": ("2025-01-02", "2026-10-09"),
}
SCHEDULES = {"weekly": Weekly, "monthly": Monthly, "daily": EverySession}


def write_json(path: Path, value: object) -> None:
    """Write a readable JSON document without nonstandard NaN values."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(plain_configuration(value), indent=2, ensure_ascii=False, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def archive_sources(output: Path, store: Path) -> None:
    """Archive exact source and metadata bytes with deterministic ZIP metadata.

    Research text must decode as UTF-8 and contain no NUL bytes. Market price
    trees are never traversed. The caller keeps source files unchanged during
    the final run; this archive captures their bytes before selection is frozen.
    """
    contents: dict[str, bytes] = {}
    source_paths = set((ROOT / "src").rglob("*.py"))
    source_paths.update((ROOT / "scripts").glob("SA15*.py"))
    source_paths.update((ROOT / "pyproject.toml", ROOT / "uv.lock"))
    for path in sorted(source_paths):
        if path.is_file() and not path.is_symlink():
            contents[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    research = ROOT / "research/SA15_GPT-6.1"
    for path in sorted(research.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        content = path.read_bytes()
        try:
            content.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if b"\x00" not in content:
            contents[path.relative_to(ROOT).as_posix()] = content
    metadata = store / "metadata"
    if not metadata.is_dir():
        raise ValueError("the source archive requires the study store metadata")
    for path in sorted(metadata.rglob("*")):
        if path.is_file() and not path.is_symlink():
            contents["store/metadata/" + path.relative_to(metadata).as_posix()] = path.read_bytes()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, content in sorted(contents.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_STORED
            archive.writestr(info, content)
    payload = buffer.getvalue()
    folder = output / "source"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "source.zip").write_bytes(payload)
    write_json(
        folder / "manifest.json",
        {
            "format": 1,
            "archive_sha256": hashlib.sha256(payload).hexdigest(),
            "files": {
                name: {"sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}
                for name, content in sorted(contents.items())
            },
        },
    )


def build_runner(store: Path, multiplier: float = 1.0) -> StrategyRunner:
    """Wire the official EUR runner with decision-sized opening orders."""
    instruments = InstrumentRegistry.from_toml(store / "metadata/instruments.toml")
    calendars = CalendarRegistry.from_directory(store / "metadata/calendars")
    reader = MarketDataReader(
        repository=MarketDataRepository(store),
        instruments=instruments,
        calendars=calendars,
        reference_calendar_id="XPAR",
    )
    return StrategyRunner(
        reader=reader,
        calendars=calendars,
        reference_calendar_id="XPAR",
        base_currency="EUR",
        analytics=ANALYTICS,
        execution=ExecutionModel(
            costs=CostModel(
                commission_rate=0.0005 * multiplier,
                minimum_commission=1.0 * multiplier,
                half_spread_rate=0.0003 * multiplier,
                slippage_rate=0.0002 * multiplier,
            ),
            sizing=Sizing.AT_DECISION,
        ),
        initial_cash=100_000.0,
        schedule=Weekly(),
        source=git_source_state(ROOT),
        lockfile=ROOT / "uv.lock",
    )


def read_candidate(path: Path) -> tuple[dict, SA15GPT61]:
    """Load one numbered candidate, refusing more than ten possible trials."""
    spec = json.loads(path.read_text(encoding="utf-8"))
    number = spec["number"]
    if isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= 10:
        raise ValueError("candidate number must be an integer from 1 to 10")
    if spec["schedule"] not in SCHEDULES or not spec["reason"].strip():
        raise ValueError("candidate needs a valid schedule and a written reason")
    parameters = dict(spec["parameters"])
    for key in ("risky_ids", "momentum_lookbacks", "momentum_weights"):
        if key in parameters:
            parameters[key] = tuple(parameters[key])
    return spec, SA15GPT61(**parameters)


def universe(strategy: SA15GPT61) -> tuple[str, ...]:
    """Include every possible holding and both traded comparison instruments."""
    return tuple(
        dict.fromkeys(
            (*strategy.investment_ids(), strategy.monetary_id, "ETF_WORLD", "ETF_SP500_PEA")
        )
    )


def metrics(result: StrategyResult) -> dict[str, float | int | None]:
    """Read net/gross returns and execution diagnostics from a finished run."""
    report = result.report()
    net = report.net
    fills = result.fills()
    traded = math.fsum(float(value) for value in fills["traded_value"])
    equity = result.equity()
    years = max((result.end - result.start).days / 365.25, 1 / 252)
    skipped = sum(
        bool(record.decision.requested.skipped)
        for record in result.records()
        if record.decision is not None
    )
    return {
        "net_return": net.total_return,
        "gross_return": report.gross.total_return,
        "cagr": net.annualised_return,
        "volatility": net.annualised_volatility,
        "sharpe": net.sharpe_ratio,
        "max_drawdown": net.drawdown.depth,
        "calmar": (
            None
            if not net.drawdown.depth or net.annualised_return is None
            else net.annualised_return / abs(net.drawdown.depth)
        ),
        "costs_eur": result.backtest.total_cost,
        "traded_value_eur": traded,
        "turnover_per_year": traded / float(equity.mean()) / years,
        "average_exposure": float(result.weights().sum(axis=1).mean()),
        "fills": len(fills),
        "rejects": len(result.rejects()),
        "decisions_with_skipped_inputs": skipped,
        "sessions": len(equity),
    }


def save_run(folder: Path, result: StrategyResult, *, details: bool = True) -> dict:
    """Save exact metrics, curve and provenance, optionally all trading records."""
    folder.mkdir(parents=True, exist_ok=True)
    values = metrics(result)
    write_json(folder / "metrics.json", values)
    write_json(folder / "configuration.json", dict(result.configuration))
    write_json(folder / "strategy.json", dict(result.definition))
    write_json(
        folder / "identity.json",
        {
            "run_id": result.run_id,
            "fingerprint": result.fingerprint,
            "data_state": {
                "digest": result.data_state.digest,
                "files": dict(result.data_state.files),
            },
        },
    )
    result.equity().rename("net_equity").to_csv(folder / "equity.csv", index_label="session_date")
    if details:
        result.weights().to_csv(folder / "weights.csv", index_label="session_date")
        result.fills().to_csv(folder / "fills.csv", index=False)
        result.rejects().to_csv(folder / "rejects.csv", index=False)
        rows = []
        for record in result.records():
            if record.decision is None:
                continue
            requested = record.decision.requested
            rows.append(
                {
                    "session_date": record.session_date,
                    "decision_time": record.decision_time,
                    "hold_positions": requested.hold_positions,
                    "weights": json.dumps(dict(requested.weights), sort_keys=True),
                    "skipped": json.dumps(
                        {key: value.value for key, value in requested.skipped.items()},
                        sort_keys=True,
                    ),
                }
            )
        pd.DataFrame(rows).to_csv(folder / "decisions.csv", index=False)
    return values


def reference_signature(runner: StrategyRunner, strategy: SA15GPT61, period: str) -> dict:
    """Describe the data, baseline code and execution conditions behind a cache."""
    with runner.reader.pinned() as state:
        data_digest = state.digest
    package = ROOT / "src/quant_backtester"
    source_files = {
        package / "research/references.py",
        package / "strategies/SA1_world_ma20_benchmark.py",
        package / "strategies/base.py",
        package / "numbers.py",
    }
    for name in ("analytics", "backtest", "data", "execution", "portfolio", "signals"):
        source_files.update((package / name).rglob("*.py"))
    source_files.update((package / "strategies/adaptive").rglob("*.py"))
    baseline_sources = {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(source_files)
    }
    return plain_configuration(
        {
            "universe": sorted(universe(strategy)),
            "risky_ids": list(strategy.risky_ids),
            "period": list(PERIODS[period]),
            "data_state": data_digest,
            "execution": runner.execution.definition(),
            "initial_cash": runner.initial_cash,
            "base_currency": runner.base_currency,
            "reference_calendar": runner.reference_calendar_id,
            "timetable": runner.timetable.definition(),
            "analytics": runner.analytics.definition(),
            "limits": runner.limits.definition(),
            "baseline_sources": baseline_sources,
        }
    )


def _require_legacy_reference(
    folder: Path, expected: Mapping, book: Strategy, schedule: DecisionSchedule
) -> None:
    """Accept an unsigned reference only when its archived conditions match."""
    identity = json.loads((folder / "identity.json").read_text())
    configuration = json.loads((folder / "configuration.json").read_text())
    definition = json.loads((folder / "strategy.json").read_text())
    checks = {
        "requested_start": expected["period"][0],
        "requested_end": expected["period"][1],
        "data_state": expected["data_state"],
        "execution": expected["execution"],
        "initial_cash": expected["initial_cash"],
        "base_currency": expected["base_currency"],
        "reference_calendar": expected["reference_calendar"],
        "timetable": expected["timetable"],
        "analytics": expected["analytics"],
        "schedule": schedule.definition(),
        "portfolio": {"limits": expected["limits"]},
        "universe": {"type": "StaticUniverse", "members": expected["universe"]},
    }
    if (
        identity.get("data_state", {}).get("digest") != expected["data_state"]
        or definition != plain_configuration(book.definition())
        or any(configuration.get(key) != value for key, value in checks.items())
    ):
        raise ValueError(f"legacy reference conditions differ: {folder}")


def run_references(
    runner: StrategyRunner, strategy: SA15GPT61, period: str, output: Path
) -> dict[str, dict]:
    """Run baselines once and reject reuse under changed research conditions."""
    books = {
        "World_buy_hold": BuyAndHold(instruments=("ETF_WORLD",)),
        "SA1_MA20": WorldMA20Benchmark(),
        "SP500_buy_hold": BuyAndHold(instruments=("ETF_SP500_PEA",)),
        "equal_weight": EqualWeightRebalance(instruments=strategy.risky_ids),
    }
    signature = reference_signature(runner, strategy, period)
    rows = {}
    for name, book in books.items():
        folder = output / "references" / period / name
        schedule = EverySession() if name != "equal_weight" else Weekly()
        expected = {
            **signature,
            "book": plain_configuration(book.definition()),
            "schedule": schedule.definition(),
        }
        cache = folder / "cache.json"
        if (folder / "metrics.json").exists():
            if cache.exists():
                if json.loads(cache.read_text()).get("signature") != expected:
                    raise ValueError(f"reference cache conditions differ: {folder}")
            else:
                _require_legacy_reference(folder, expected, book, schedule)
                write_json(
                    cache,
                    {
                        "signature": expected,
                        "legacy_migration": (
                            "Archived data digest, strategy and execution conditions verified; "
                            "baseline source hashes recorded at migration, not original execution."
                        ),
                    },
                )
            rows[name] = json.loads((folder / "metrics.json").read_text())
            continue
        if cache.exists():
            raise ValueError(f"reference cache has no metrics: {folder}")
        print(f"reference {period} {name}", flush=True)
        result = runner.run(book, universe(strategy), *PERIODS[period], schedule=schedule)
        if result.data_state.digest != signature["data_state"]:
            raise ValueError("reference data changed after the cache signature was captured")
        rows[name] = save_run(folder, result, details=False)
        write_json(cache, {"signature": expected})
    return rows


def selection_score(development: Mapping[str, float], validation: Mapping[str, float]) -> float:
    """Score only the two periods announced in the research protocol."""
    first, second = development["cagr"], validation["cagr"]
    return (
        (first + second) / 2
        - 0.25 * (abs(development["max_drawdown"]) + abs(validation["max_drawdown"])) / 2
        - 0.10 * abs(first - second)
    )


def iterate(config: Path, runner: StrategyRunner, output: Path) -> None:
    """Run a single new configuration on development and selection validation."""
    if (output / "selected.json").exists():
        raise ValueError("selection is already frozen; no further candidates are accepted")
    spec, strategy = read_candidate(config)
    folder = output / f"trial_{spec['number']:02d}"
    if (folder / "candidate.json").exists():
        raise FileExistsError(f"{folder} already contains a trial; it will not be overwritten")
    folder.mkdir(parents=True, exist_ok=True)
    write_json(folder / "candidate.json", spec)
    rows = {}
    for period in ("development", "validation"):
        run_references(runner, strategy, period, output)
        print(f"trial {spec['number']} {period}: {spec['reason']}", flush=True)
        result = runner.run(
            strategy,
            universe(strategy),
            *PERIODS[period],
            schedule=SCHEDULES[spec["schedule"]](),
        )
        rows[period] = save_run(folder / period, result)
        print(json.dumps(rows[period]), flush=True)
    score = selection_score(rows["development"], rows["validation"])
    write_json(folder / "selection.json", {"score": score, "metrics": rows})
    update_trials(output)
    print(f"trial {spec['number']} selection score {score:.6f}", flush=True)


def update_trials(output: Path) -> pd.DataFrame:
    """Publish every completed candidate without concealing unsuccessful ones."""
    rows = []
    for folder in sorted(output.glob("trial_*")):
        if not (folder / "selection.json").exists():
            continue
        spec = json.loads((folder / "candidate.json").read_text())
        selection = json.loads((folder / "selection.json").read_text())
        row = {"trial": spec["number"], "reason": spec["reason"], "score": selection["score"]}
        for period, values in selection["metrics"].items():
            row.update({f"{period}_{key}": value for key, value in values.items()})
        rows.append(row)
    table = pd.DataFrame(rows).sort_values("trial")
    table.to_csv(output / "iterations.csv", index=False)
    return table


def load_equity(path: Path) -> pd.Series:
    """Read a saved equity curve retaining exactly its dated sessions."""
    return pd.read_csv(path, index_col=0, parse_dates=True).iloc[:, 0]


def render_comparison(output: Path, period: str, trial: int) -> pd.DataFrame:
    """Save aligned curves, annual returns and a net comparison table."""
    book_folder = (
        output / "full/SA15_GPT-6.1"
        if period == "full"
        else output / f"trial_{trial:02d}" / period
        if period != "final"
        else output / "final/SA15_GPT-6.1"
    )
    curves = {"SA15_GPT-6.1": load_equity(book_folder / "equity.csv")}
    rows = {"SA15_GPT-6.1": json.loads((book_folder / "metrics.json").read_text())}
    for name in ("World_buy_hold", "SA1_MA20", "SP500_buy_hold", "equal_weight"):
        folder = (
            output / "full" / name if period == "full" else output / "references" / period / name
        )
        curves[name] = load_equity(folder / "equity.csv")
        rows[name] = json.loads((folder / "metrics.json").read_text())
    equity = pd.DataFrame(curves)
    if equity.isna().any().any():
        raise ValueError("comparison calendars differ; no filling is allowed")
    # Analytics requires Python session dates; exports and plots retain DatetimeIndex.
    benchmark_for_alpha = curves["World_buy_hold"].copy()
    benchmark_for_alpha.index = pd.Index(
        pd.DatetimeIndex(benchmark_for_alpha.index).date, dtype="object", name="session_date"
    )
    for name, curve in curves.items():
        curve_for_alpha = curve.copy()
        curve_for_alpha.index = pd.Index(
            pd.DatetimeIndex(curve_for_alpha.index).date, dtype="object", name="session_date"
        )
        relative = alpha_vs_benchmark(curve_for_alpha, benchmark_for_alpha, ANALYTICS)
        rows[name]["alpha_vs_world"] = relative.alpha_annualised
        rows[name]["beta_vs_world"] = relative.beta
        rows[name]["outperformance_vs_world"] = relative.outperformance
    table = pd.DataFrame.from_dict(rows, orient="index").rename_axis("book")
    folder = output / "comparison" / period
    folder.mkdir(parents=True, exist_ok=True)
    table.to_csv(folder / "summary.csv")
    equity.to_csv(folder / "equity.csv", index_label="session_date")
    returns = equity.pct_change().fillna(0.0)
    yearly = (1 + returns).groupby(returns.index.year).prod() - 1
    yearly.to_csv(folder / "yearly.csv", index_label="year")
    figure, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True, height_ratios=[2, 1])
    for name in equity:
        axes[0].plot(equity.index, equity[name] / 100_000 * 100, label=name, linewidth=1.5)
        axes[1].plot(equity.index, equity[name] / equity[name].cummax() - 1, linewidth=1.2)
    axes[0].set(title=f"SA15_GPT-6.1 — {period} — net, base 100", ylabel="Capital net")
    axes[0].legend(ncol=2, fontsize=9)
    axes[1].set(ylabel="Drawdown")
    for axis in axes:
        axis.grid(alpha=0.2)
    figure.tight_layout()
    figure.savefig(folder / "comparison.png", dpi=160)
    plt.close(figure)
    return table


def block_bootstrap_interval(
    strategy: pd.Series, benchmark: pd.Series, seed: int = 6115
) -> dict[str, float]:
    """Describe sampling uncertainty of annualised mean active returns.

    Paired circular 20-session blocks preserve short return dependence.
    This interval does not correct for universe selection or strategy trials.
    """
    active = (strategy.pct_change() - benchmark.pct_change()).dropna().to_numpy()
    rng = np.random.default_rng(seed)
    n, block = len(active), 20
    estimates = np.empty(2_000)
    for index in range(len(estimates)):
        starts = rng.integers(0, n, size=math.ceil(n / block))
        chosen = ((starts[:, None] + np.arange(block)) % n).ravel()[:n]
        estimates[index] = active[chosen].mean() * 252
    return {
        "annualised_mean_active_return": float(active.mean() * 252),
        "lower_95": float(np.quantile(estimates, 0.025)),
        "upper_95": float(np.quantile(estimates, 0.975)),
        "seed": seed,
        "block_sessions": block,
        "replications": len(estimates),
    }


def finalise(runner: StrategyRunner, output: Path, store: Path) -> None:
    """Freeze selection, run the final period once, and diagnose doubled costs."""
    if (output / "selected.json").exists():
        raise FileExistsError("final selection already exists; use the saved final results")
    trials = update_trials(output)
    chosen = int(trials.sort_values(["score", "trial"], ascending=[False, True]).iloc[0]["trial"])
    path = output / f"trial_{chosen:02d}/candidate.json"
    spec, strategy = read_candidate(path)
    archive_sources(output, store)
    write_json(
        output / "selected.json",
        {
            "candidate": spec,
            "selection_score": float(trials.loc[trials["trial"] == chosen, "score"].iloc[0]),
            "selection_uses": ["development", "validation"],
            "final_period": PERIODS["final"],
            "candidate_fingerprint": strategy.fingerprint(),
            "trials": len(trials),
        },
    )
    run_references(runner, strategy, "final", output)
    print(f"FROZEN trial {chosen}: reading final period once", flush=True)
    schedule = SCHEDULES[spec["schedule"]]()
    result = runner.run(strategy, universe(strategy), *PERIODS["final"], schedule=schedule)
    save_run(output / "final/SA15_GPT-6.1", result)
    stressed = build_runner(store, 2.0).run(
        strategy,
        universe(strategy),
        *PERIODS["final"],
        schedule=schedule,
    )
    save_run(output / "final/costs_x2", stressed)
    for period in PERIODS:
        render_comparison(output, period, chosen)
    equity = pd.read_csv(output / "comparison/final/equity.csv", index_col=0, parse_dates=True)
    interval = block_bootstrap_interval(equity["SA15_GPT-6.1"], equity["World_buy_hold"])
    write_json(output / "final/uncertainty.json", interval)
    print(pd.read_csv(output / "comparison/final/summary.csv").to_string(index=False), flush=True)
    print("uncertainty", json.dumps(interval), flush=True)


def render_saved(output: Path) -> None:
    """Render completed runs after checking the frozen candidate, without a backtest."""
    selected_path = output / "selected.json"
    if not selected_path.is_file():
        raise FileNotFoundError("render-only requires an existing frozen selected.json")
    selected = json.loads(selected_path.read_text())
    trial = selected["candidate"]["number"]
    spec, strategy = read_candidate(output / f"trial_{trial:02d}/candidate.json")
    if spec != selected["candidate"] or strategy.fingerprint() != selected["candidate_fingerprint"]:
        raise ValueError("saved candidate differs from the frozen selection")
    definition = json.loads((output / "final/SA15_GPT-6.1/strategy.json").read_text())
    if definition != plain_configuration(strategy.definition()):
        raise ValueError("saved final strategy differs from the frozen selection")
    periods = list(PERIODS)
    if (output / "full/SA15_GPT-6.1/metrics.json").is_file():
        periods.append("full")
    for period in periods:
        render_comparison(output, period, trial)
    equity = pd.read_csv(output / "comparison/final/equity.csv", index_col=0, parse_dates=True)
    interval = block_bootstrap_interval(equity["SA15_GPT-6.1"], equity["World_buy_hold"])
    write_json(output / "final/uncertainty.json", interval)
    print(pd.read_csv(output / "comparison/final/summary.csv").to_string(index=False), flush=True)
    print("uncertainty", json.dumps(interval), flush=True)


def main() -> None:
    """Execute exactly one candidate or freeze and evaluate the selection."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--candidate", type=Path)
    mode.add_argument("--final", action="store_true")
    mode.add_argument("--render-only", action="store_true")
    options = parser.parse_args()
    if options.render_only:
        render_saved(options.output)
        return
    runner = build_runner(options.store)
    if options.final:
        finalise(runner, options.output, options.store)
    else:
        iterate(options.candidate, runner, options.output)


if __name__ == "__main__":
    main()
