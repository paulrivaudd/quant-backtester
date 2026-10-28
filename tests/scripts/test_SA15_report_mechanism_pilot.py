"""Offline tests for matched mechanism attribution, never running a backtest."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import math
import sys
from dataclasses import replace
from pathlib import Path
from types import ModuleType

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]


def load_script() -> ModuleType:
    """Import the report CLI without executing it."""
    spec = importlib.util.spec_from_file_location(
        "SA15_report_mechanism_pilot", ROOT / "scripts/SA15_report_mechanism_pilot.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SCRIPT = load_script()


def curve(count: int = 180) -> pd.Series:
    """Build a nonconstant, positive synthetic archived NAV."""
    returns = 0.001 + 0.005 * np.sin(np.arange(count - 1) / 7)
    return pd.Series(
        100000 * np.r_[1, np.cumprod(1 + returns)],
        index=pd.bdate_range("2023-01-02", periods=count, name="session_date"),
        name="net_equity",
    )


def metrics(equity: pd.Series, gain: float | None = None) -> dict:
    """Provide all required archived scalar metrics."""
    result = float(equity.iloc[-1] / equity.iloc[0] - 1) if gain is None else gain
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    return {
        "net_return": result,
        "gross_return": result + 0.001,
        "cagr": (1 + result) ** (1 / years) - 1,
        "max_drawdown": float((equity / equity.cummax() - 1).min()),
        "costs_eur": 10.0,
        "fills": 1,
        "sessions": len(equity),
    }


def conditions() -> dict:
    """Return execution conditions shared by all five synthetic policies."""
    return {
        "start": "2023-01-02",
        "end": "2023-09-08",
        "initial_cash": 100000,
        "base_currency": "EUR",
        "reference_calendar": "XPAR",
        "schedule": {"type": "MonthlyFromStart"},
        "timetable": {"decision_time": "23:00", "execution": "next open"},
        "universe": ["ETF_NASDAQ", "ETF_MONETARY_EUR"],
        "portfolio": {"long_only": True},
        "execution": {"costs": 1},
        "quantity_steps": {"ETF_NASDAQ": 1},
    }


def saved_run(policy: str = "full", equity: pd.Series | None = None) -> object:
    """Make an in-memory saved run to test pure diagnostics."""
    equity = curve() if equity is None else equity
    weights = pd.DataFrame({"ETF_NASDAQ": 1.0}, index=equity.index)
    fills = pd.DataFrame(
        {"session_date": [equity.index[1]], "total_cost": [10.0], "traded_value": [1000.0]}
    )
    decisions = pd.DataFrame({"session_date": [equity.index[0]], "skipped": ["{}"]})
    return SCRIPT.SavedRun(
        policy,
        "full",
        1,
        Path("fixture"),
        metrics(equity),
        equity,
        weights,
        fills,
        decisions,
        conditions(),
        {"data_state": {"digest": "fixture"}},
    )


def write_json(path: Path, value: object) -> None:
    """Save a synthetic JSON artifact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def save_run(output: Path, policy: str = "full") -> Path:
    """Write a hand-built archive with valid artifact checksums."""
    run = saved_run(policy)
    folder = SCRIPT.run_folder(output, "full", 1, policy)
    write_json(folder / "metrics.json", run.metrics)
    write_json(folder / "configuration.json", run.configuration)
    write_json(folder / "identity.json", run.identity)
    write_json(folder / "contract.json", {"policy": policy})
    run.equity.to_csv(folder / "equity.csv")
    run.weights.to_csv(folder / "weights.csv")
    run.fills.to_csv(folder / "fills.csv", index=False)
    run.decisions.to_csv(folder / "decisions.csv", index=False)
    write_json(
        folder / "artifacts.json",
        {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in folder.iterdir()},
    )
    return folder


def pair_metrics() -> dict:
    """Make block effects with an explicit nonzero interaction."""
    gains = {
        "full": 0.30,
        "trend_only": 0.12,
        "volatility_only": 0.08,
        "neither": 0.10,
        "Nasdaq_buy_hold": 0.09,
    }
    return {
        name: {
            "net_return": value,
            "cagr": value / 2,
            "max_drawdown": -0.1 - value / 10,
            "costs_eur": value * 100,
        }
        for name, value in gains.items()
    }


def test_paired_contrasts_are_conditional_and_standalone() -> None:
    """Trend and volatility are measured against the correct matched policy."""
    rows = {row["effect"]: row for row in SCRIPT.contrasts(pair_metrics())}
    assert rows["trend_conditional"]["net_return_difference"] == pytest.approx(0.22)
    assert rows["volatility_conditional"]["net_return_difference"] == pytest.approx(0.18)
    assert rows["trend_standalone"]["net_return_difference"] == pytest.approx(0.02)
    assert rows["volatility_standalone"]["net_return_difference"] == pytest.approx(-0.02)
    assert rows["complete_vs_hold"]["left"] == "full"


def test_log_growth_interaction_is_not_sum_of_drawdown_changes() -> None:
    """The additive scale is log wealth; DD remains a paired scalar contrast."""
    values = pair_metrics()
    expected = math.log(1.30) - math.log(1.12) - math.log(1.08) + math.log(1.10)
    assert SCRIPT.log_growth_interaction(values) == pytest.approx(expected)
    effects = SCRIPT.contrasts(values)
    assert all("interaction_drawdown" not in row for row in effects)
    assert SCRIPT.log_growth_interaction(values) != pytest.approx(
        values["full"]["net_return"]
        - values["trend_only"]["net_return"]
        - values["volatility_only"]["net_return"]
        + values["neither"]["net_return"]
    )


def test_interaction_zero_for_multiplicatively_independent_blocks() -> None:
    """Known multiplicative block effects give exactly zero log interaction."""
    values = pair_metrics()
    for name, gain in {
        "neither": 0,
        "trend_only": 0.1,
        "volatility_only": 0.2,
        "full": 0.32,
    }.items():
        values[name]["net_return"] = gain
    assert SCRIPT.log_growth_interaction(values) == pytest.approx(0, abs=1e-14)


def test_regime_uses_only_previous_close_and_declares_warmup() -> None:
    """Current and future shocks cannot change the current descriptive label."""
    original = pd.Series(
        np.linspace(100, 200, 200), index=pd.bdate_range("2020-01-02", periods=200)
    )
    labels = SCRIPT.diagnostic_regimes(original)
    assert labels.iloc[:127].eq("unclassified").all()
    assert labels.iloc[127] == "rise"
    shocked = original.copy()
    shocked.iloc[150:] *= 0.01
    changed = SCRIPT.diagnostic_regimes(shocked)
    pd.testing.assert_series_equal(labels.iloc[:151], changed.iloc[:151])
    assert changed.iloc[151] == "fall"


def test_recovery_priority_is_strictly_lagged_and_requires_stress() -> None:
    """A past stress plus positive short return overrides the long trend."""
    nav = pd.Series(
        [100, 100, 100, 80, 81, 82, 83, 84, 85, 86], index=pd.bdate_range("2020-01-02", periods=10)
    )
    labels = SCRIPT.diagnostic_regimes(nav, lookback=5, recovery=2, stress=0.1)
    assert labels.iloc[6] == "recovery"
    changed = nav.copy()
    changed.iloc[6:] = 1
    assert (
        SCRIPT.diagnostic_regimes(changed, lookback=5, recovery=2, stress=0.1).iloc[6] == "recovery"
    )
    assert SCRIPT.diagnostic_regimes(nav, lookback=5, recovery=2, stress=0.5).iloc[6] == "fall"


def test_regime_means_do_not_claim_weight_times_return_pnl() -> None:
    """Active return is the actual saved NAV difference, independent of weights."""
    baseline = saved_run("Nasdaq_buy_hold")
    run = saved_run("full", baseline.equity * np.linspace(1, 1.1, len(baseline.equity)))
    run.weights.loc[:, "ETF_NASDAQ"] = 0.0
    labels = pd.Series("rise", index=run.equity.index)
    rows = SCRIPT.regime_summary(run, baseline, labels)
    row = next(row for row in rows if row["regime"] == "rise")
    assert row["sessions"] == len(run.equity) - 1
    assert row["mean_active_daily_bp"] > 0
    assert row["mean_nasdaq_closing_weight"] == 0
    assert next(row for row in rows if row["regime"] == "fall")["mean_active_daily_bp"] is None


def test_episodes_publish_every_reduction_and_observed_costs_separately() -> None:
    """Cash warmup is excluded and reentry fills are not hidden in an episode."""
    run = saved_run()
    run.weights.iloc[0] = 0
    run.weights.iloc[3:6] = 0.5
    run.weights.iloc[8:10] = 0.8
    fills = pd.DataFrame(
        {
            "session_date": run.equity.index[[1, 3, 6, 8, 10]],
            "total_cost": [1, 2, 3, 4, 5],
            "traded_value": [100] * 5,
        }
    )
    run = replace(run, fills=fills)
    rows = SCRIPT.reduced_episodes(run, saved_run("Nasdaq_buy_hold"))
    assert len(rows) == 2
    assert rows[0]["sessions"] == 3
    assert rows[0]["anchor_close"] == run.equity.index[2].date().isoformat()
    assert rows[0]["observed_costs_eur"] == 2
    assert rows[0]["reentry_day_observed_costs_eur"] == 3
    assert "block_attribution" not in rows[0]


@pytest.mark.parametrize("field", SCRIPT.REQUIRED_METRICS)
def test_missing_metrics_are_refused(field: str) -> None:
    """An absent outcome never becomes an invented zero."""
    values = metrics(curve())
    del values[field]
    with pytest.raises(ValueError, match="required metric"):
        SCRIPT.validate_metrics(values, curve())


def test_inconsistent_saved_curve_is_refused() -> None:
    """The report checks archived metrics against their actual NAV."""
    values = metrics(curve())
    values["net_return"] += 0.1
    with pytest.raises(ValueError, match="return differ"):
        SCRIPT.validate_metrics(values, curve())


def test_matched_policy_set_is_required() -> None:
    """No contrast silently omits an unfavourable or unfinished control."""
    group = {name: saved_run(name) for name in SCRIPT.POLICIES}
    SCRIPT.validate_matched(group)
    del group["trend_only"]
    with pytest.raises(ValueError, match="all five"):
        SCRIPT.validate_matched(group)


@pytest.mark.parametrize("mismatch", ["data", "cost", "sessions", "execution"])
def test_unmatched_policy_conditions_are_refused(mismatch: str) -> None:
    """Data revisions, fees, calendars and execution are paired explicitly."""
    group = {name: saved_run(name) for name in SCRIPT.POLICIES}
    run = group["full"]
    if mismatch == "data":
        run = replace(run, identity={"data_state": {"digest": "changed"}})
    elif mismatch == "cost":
        run = replace(run, cost_multiplier=2)
    elif mismatch == "sessions":
        run = replace(run, equity=run.equity.iloc[:-1])
    else:
        run = replace(run, configuration={**run.configuration, "execution": {"costs": 2}})
    group["full"] = run
    with pytest.raises(ValueError, match="different"):
        SCRIPT.validate_matched(group)


def test_archive_checksum_and_missing_evidence_are_refused(tmp_path: Path) -> None:
    """Only complete immutable archived financial artifacts are consumed."""
    folder = save_run(tmp_path)
    loaded = SCRIPT.load_run(tmp_path, "full", 1, "full")
    assert len(loaded.equity) == 180
    (folder / "metrics.json").write_text("{}")
    with pytest.raises(ValueError, match="checksum"):
        SCRIPT.load_run(tmp_path, "full", 1, "full")


def test_completion_requires_thirty_runs_and_matching_manifest(tmp_path: Path) -> None:
    """The renderer refuses incomplete runs before creating any report."""
    write_json(tmp_path / "manifest.json", {})
    (tmp_path / "metrics.csv").write_text("fixture\n")
    counts = {
        "real_backtest_count": 29,
        "candidate_count": 1,
        "control_count": 4,
        "manifest_sha256": SCRIPT.sha256(tmp_path / "manifest.json"),
        "metrics_sha256": SCRIPT.sha256(tmp_path / "metrics.csv"),
    }
    write_json(tmp_path / "completed.json", counts)
    with pytest.raises(ValueError, match="incomplete"):
        SCRIPT.verify_completion(tmp_path)
    counts["real_backtest_count"] = 30
    write_json(tmp_path / "completed.json", counts)
    assert SCRIPT.verify_completion(tmp_path) == {}
    (tmp_path / "manifest.json").write_text('{"changed":true}')
    with pytest.raises(ValueError, match="checksum"):
        SCRIPT.verify_completion(tmp_path)


def test_principal_verdict_never_promotes_a_winning_ablation() -> None:
    """A successful control does not rescue a refuted complete policy."""
    rows = []
    for period in SCRIPT.PERIODS:
        for policy in SCRIPT.POLICIES:
            rows.append(
                {
                    "period": period,
                    "policy": policy,
                    "cost_multiplier": 1,
                    "net_return": 0.1 if policy == "full" else 0.2,
                    "max_drawdown": -0.1,
                    "trade_dates_per_year": 2,
                }
            )
    verdict = SCRIPT.hypothesis_verdict(pd.DataFrame(rows))
    assert verdict["status"] == "NOT_SUPPORTED"
    assert verdict["main_policy"] == "full"
    assert verdict["cumulative_trials_declared"] == 85
    assert verdict["base_simulations"] == 30


def test_positive_principal_result_remains_uncertain_without_other_checks() -> None:
    """A retrospective pilot cannot alone demonstrate robustness."""
    rows = [
        {
            "period": period,
            "policy": policy,
            "cost_multiplier": 1,
            "net_return": 0.3 if policy == "full" else 0.2,
            "max_drawdown": -0.1,
            "trade_dates_per_year": 2,
        }
        for period in SCRIPT.PERIODS
        for policy in SCRIPT.POLICIES
    ]
    assert SCRIPT.hypothesis_verdict(pd.DataFrame(rows))["status"] == "UNCERTAIN"


def test_report_has_no_financial_runner_or_network_import() -> None:
    """Presentation cannot invoke a backtest, provider, policy or network call."""
    tree = ast.parse((ROOT / "scripts/SA15_report_mechanism_pilot.py").read_text())
    modules = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    modules += [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    ]
    forbidden = (
        "quant_backtester.backtest",
        "quant_backtester.strategies",
        "quant_backtester.data",
        "urllib",
        "requests",
    )
    assert not any(name.startswith(forbidden) for name in modules)
