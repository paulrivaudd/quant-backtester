"""Offline matched-attribution tests using synthetic saved evidence only."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location(
    "SA15_report_gpt61_mechanisms", ROOT / "scripts/SA15_report_gpt61_mechanisms.py"
)
assert SPEC and SPEC.loader
SCRIPT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SCRIPT
SPEC.loader.exec_module(SCRIPT)


def curve(count=180):
    returns = 0.001 + 0.005 * np.sin(np.arange(count - 1) / 7)
    return pd.Series(
        100_000 * np.r_[1, np.cumprod(1 + returns)],
        index=pd.bdate_range("2023-01-02", periods=count, name="session_date"),
        name="net_equity",
    )


def conditions():
    return {
        "start": "2023-01-02",
        "end": "2023-09-08",
        "initial_cash": 100_000,
        "base_currency": "EUR",
        "reference_calendar": "XPAR",
        "schedule": {"type": "MonthlyFromStart"},
        "timetable": {"decision_time": "23:00", "execution": "next open"},
        "universe": ["ETF_NASDAQ", "ETF_MONETARY_EUR"],
        "portfolio": {"long_only": True},
        "execution": {"costs": dict(SCRIPT.BASE_COSTS)},
        "quantity_steps": {"ETF_NASDAQ": 1},
    }


def saved_run(policy="candidate", equity=None):
    equity = curve() if equity is None else equity
    gain = float(equity.iloc[-1] / equity.iloc[0] - 1)
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    metrics = {
        "net_return": gain,
        "gross_return": gain + 0.001,
        "cagr": (1 + gain) ** (1 / years) - 1,
        "max_drawdown": float((equity / equity.cummax() - 1).min()),
        "costs_eur": 10.0,
        "fills": 1,
        "sessions": len(equity),
    }
    return SCRIPT.SavedRun(
        policy,
        "choice",
        1,
        Path("fixture"),
        metrics,
        equity,
        pd.DataFrame({"ETF_NASDAQ": 1.0}, index=equity.index),
        pd.DataFrame(
            {"session_date": [equity.index[1]], "total_cost": [10.0], "traded_value": [1000.0]}
        ),
        pd.DataFrame({"session_date": [equity.index[0]], "skipped": ["{}"]}),
        conditions(),
        {"data_state": {"digest": "fixture"}, "fingerprint": policy},
    )


def group():
    return {
        name: saved_run(name)
        for name in ("candidate", "parent", "Nasdaq_buy_hold", "without_trend")
    }


def save_run(folder, run):
    folder.mkdir(parents=True)
    config = dict(run.configuration)
    start, end = run.equity.index[0].date().isoformat(), run.equity.index[-1].date().isoformat()
    config.update(
        start=start, end=end, requested_start=start, requested_end=end, data_state="fixture"
    )
    config["execution"] = {
        "costs": {key: value * run.cost_multiplier for key, value in SCRIPT.BASE_COSTS.items()}
    }
    parameters = run.identity.get("test_parameters", {"fixture_policy": run.policy})
    strategy = {
        "strategy_id": run.policy,
        "class": "fixture",
        "parameters": parameters,
        "signals": [],
    }
    identity = {"fingerprint": SCRIPT.canonical_hash(strategy), "data_state": {"digest": "fixture"}}
    for name, value in (
        ("metrics", run.metrics),
        ("configuration", config),
        ("identity", identity),
        ("strategy", strategy),
    ):
        (folder / f"{name}.json").write_text(json.dumps(value))
    run.equity.to_csv(folder / "equity.csv")
    gross = run.equity.copy()
    gross.iloc[-1] = gross.iloc[0] * (1 + run.metrics["gross_return"])
    gross.to_csv(folder / "gross_equity.csv")
    run.weights.to_csv(folder / "weights.csv")
    run.fills.to_csv(folder / "fills.csv", index=False)
    run.decisions.to_csv(folder / "decisions.csv", index=False)
    signature = {
        "format": 5,
        "data_state": "fixture",
        "source_finance_hashes": {"fixture": "frozen"},
        "fingerprint": identity["fingerprint"],
        "strategy": strategy,
        "configuration": config,
    }
    (folder / "cache.json").write_text(json.dumps({"signature": signature, "artifacts": {}}))
    refresh_hashes(folder)
    key = SCRIPT.canonical_hash(signature)
    (folder / "cache_link.json").write_text(json.dumps({"cache_key": key, "cache": f"cache/{key}"}))
    return key


def refresh_hashes(folder):
    cache = json.loads((folder / "cache.json").read_text())
    cache["artifacts"] = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in folder.iterdir()
        if path.name not in ("cache.json", "cache_link.json")
    }
    (folder / "cache.json").write_text(json.dumps(cache))


def profile_parameters():
    return {
        "fixture_policy": "candidate",
        **dict(
            zip(SCRIPT.TEMPORAL_FIELDS, (21, 63, 126, 50, 200, 20, 60, 63, 63, 21), strict=True)
        ),
    }


def period_curve(start, end):
    data = curve(64)
    data.index = pd.date_range(start, end, periods=len(data), name="session_date").normalize()
    return data


def frozen_fixture(output):
    path = output / "frozen_inputs.json"
    if not path.is_file():
        output.mkdir(exist_ok=True)
        frozen = {
            "data_state": {"digest": "fixture"},
            "source_finance_hashes": {"fixture": "frozen"},
            "periods": {
                "choice": ["2019-06-03", "2024-12-31"],
                "final": ["2025-01-02", "2026-10-09"],
                "full": ["2019-06-03", "2026-10-09"],
            },
        }
        path.write_text(json.dumps(frozen))
    return json.loads(path.read_text())


def archive_run(output, folder, run):
    import os
    import shutil

    key = save_run(folder, run)
    physical = output / "cache" / key
    if not physical.exists():
        physical.parent.mkdir(exist_ok=True)
        shutil.copytree(folder, physical, copy_function=os.link)
    return key


def iteration_fixture(output, identifier="M01"):
    frozen = frozen_fixture(output)
    folder = output / identifier
    folder.mkdir()
    parameters = profile_parameters()
    spec = {
        "id": identifier,
        "parent": "M00",
        "changed_block": "trend",
        "reason": "fixed trend",
        "expected_benefit": "less DD",
        "expected_cost": "late rebound",
        "refutation": "loses growth",
        "schedule": "monthly",
        "parameters": parameters,
    }
    (folder / "candidate.json").write_text(json.dumps(spec))
    parent = {
        "id": "M00",
        "schedule": "monthly",
        "parameters": {**parameters, "fixture_policy": "parent"},
    }
    jobs = []
    for cost in (1, 2):
        for role in ("candidate", "parent", "Nasdaq_buy_hold", "without_trend"):
            policy_parameters = parent["parameters"] if role == "parent" else parameters
            if role == "Nasdaq_buy_hold":
                policy_parameters = {"instruments": ["ETF_NASDAQ"], "strategy_id": role}
            elif role == "without_trend":
                policy_parameters = {**parameters, "fixture_policy": "without_trend"}
            run = saved_run(role, period_curve(*frozen["periods"]["choice"]))
            run = replace(
                run,
                cost_multiplier=cost,
                identity={**run.identity, "test_parameters": policy_parameters},
            )
            key = archive_run(output, folder / "choice" / f"costs_x{cost}" / role, run)
            jobs.append({"role": role, "cost_multiplier": cost, "cache_key": key})
    contract = {
        "candidate": spec,
        "parent": parent,
        "start": frozen["periods"]["choice"][0],
        "end": frozen["periods"]["choice"][1],
        "contracts": jobs,
        "candidate_sha256": SCRIPT.sha256(folder / "candidate.json"),
        "frozen_inputs_sha256": SCRIPT.sha256(output / "frozen_inputs.json"),
    }
    (folder / "contract.json").write_text(json.dumps(contract))
    completed = {
        "contract_sha256": SCRIPT.sha256(folder / "contract.json"),
        "logical_contract_count": len(jobs),
        "score": {"qualified": True},
    }
    (folder / "completed.json").write_text(json.dumps(completed))
    (folder / "analysis.json").write_text(
        json.dumps(
            {
                "id": identifier,
                "completed_sha256": SCRIPT.sha256(folder / "completed.json"),
                "decision": "reject",
                "findings": ["costs growth"],
                "next_defect": "late rebound",
            }
        )
    )
    return spec


def final_fixture(output):
    frozen = frozen_fixture(output)
    spec = json.loads((output / "M01/candidate.json").read_text())
    fingerprint = json.loads((output / "M01/choice/costs_x1/candidate/identity.json").read_text())[
        "fingerprint"
    ]
    selected = {
        "id": "M01",
        "qualified": True,
        "candidate": spec,
        "fingerprint": fingerprint,
        "completed_sha256": SCRIPT.sha256(output / "M01/completed.json"),
        "frozen_inputs_sha256": SCRIPT.sha256(output / "frozen_inputs.json"),
        "analysis": {"id": "M01", "sha256": SCRIPT.sha256(output / "M01/analysis.json")},
    }
    (output / "selected.json").write_text(json.dumps(selected))
    (output / "selected.sha256").write_text(SCRIPT.sha256(output / "selected.json"))
    periods = {
        "final": {name: frozen["periods"][name] for name in ("final", "full")},
        "robustness": {
            **{
                f"start_{start[:4]}": [start, "2024-12-31"]
                for start in ("2020-01-02", "2021-01-04", "2022-01-03", "2023-01-02")
            },
            "neighbor_short": frozen["periods"]["choice"],
            "neighbor_long": frozen["periods"]["choice"],
        },
    }
    for kind, items in periods.items():
        jobs = []
        for period, (start, end) in items.items():
            prefix = f"robustness/{period}" if kind == "robustness" else period
            for cost in (1, 2):
                for role in ("candidate", "Nasdaq_buy_hold"):
                    parameters = dict(spec["parameters"])
                    if role == "Nasdaq_buy_hold":
                        parameters = {"instruments": ["ETF_NASDAQ"], "strategy_id": role}
                    elif period in ("neighbor_short", "neighbor_long"):
                        factor = 0.8 if period == "neighbor_short" else 1.2
                        for name in SCRIPT.TEMPORAL_FIELDS:
                            parameters[name] = round(parameters[name] * factor)
                    run = saved_run(role, period_curve(start, end))
                    run = replace(
                        run,
                        cost_multiplier=cost,
                        identity={**run.identity, "test_parameters": parameters},
                    )
                    key = archive_run(output, output / prefix / f"costs_x{cost}" / role, run)
                    jobs.append(
                        {
                            "period": period,
                            "folder": prefix,
                            "start": start,
                            "end": end,
                            "cost_multiplier": cost,
                            "role": role,
                            "cache_key": key,
                            "parameters": parameters,
                            "nonselectable": True,
                        }
                    )
        (output / f"{kind}_contracts.json").write_text(
            json.dumps(
                {"selection_sha256": SCRIPT.sha256(output / "selected.json"), "contracts": jobs}
            )
        )
        (output / f"{kind}_completed.json").write_text(
            json.dumps(
                {
                    "contract_sha256": SCRIPT.sha256(output / f"{kind}_contracts.json"),
                    "logical_contract_count": len(jobs),
                }
            )
        )


def test_regime_labels_use_only_prior_close():
    equity = pd.Series(np.linspace(100, 200, 200), index=pd.bdate_range("2020-01-02", periods=200))
    original = SCRIPT.diagnostic_regimes(equity)
    changed = equity.copy()
    changed.iloc[150:] *= 0.01
    modified = SCRIPT.diagnostic_regimes(changed)
    pd.testing.assert_series_equal(original.iloc[:151], modified.iloc[:151])
    assert original.iloc[:127].eq("unclassified").all()
    assert modified.iloc[151] == "fall"


def test_regime_recovery_requires_past_stress():
    equity = pd.Series(
        np.r_[np.linspace(100, 140, 100), np.linspace(140, 80, 40), np.linspace(80, 130, 60)],
        index=pd.bdate_range("2020-01-02", periods=200),
    )
    labels = SCRIPT.diagnostic_regimes(equity)
    assert labels.eq("recovery").any()
    assert labels.eq("fall").any()


def test_block_effect_signs_and_matching_controls():
    runs = group()
    candidate = runs["candidate"]
    runs["candidate"] = replace(
        candidate, metrics={**candidate.metrics, "cagr": 0.15, "max_drawdown": -0.10}
    )
    parent = runs["parent"]
    runs["parent"] = replace(
        parent, metrics={**parent.metrics, "cagr": 0.20, "max_drawdown": -0.25}
    )
    effects = {row["control"]: row for row in SCRIPT.block_effects(runs)}
    assert effects["parent"]["cagr_difference"] == pytest.approx(-0.05)
    assert effects["parent"]["cagr_cost_of_protection"] == pytest.approx(0.05)
    assert effects["parent"]["drawdown_improvement"] == pytest.approx(0.15)
    assert effects["without_trend"]["effect"] == "trend"
    assert effects["parent"]["trade_dates_difference"] == 0


def test_matching_refuses_different_data_cash_dates_costs():
    SCRIPT.validate_matched(group())
    for change in (
        {"identity": {"data_state": {"digest": "other"}}},
        {"cost_multiplier": 2},
        {"equity": curve().iloc[:-1]},
        {"configuration": {**conditions(), "initial_cash": 999}},
    ):
        runs = group()
        runs["candidate"] = replace(runs["candidate"], **change)
        with pytest.raises(ValueError):
            SCRIPT.validate_matched(runs)


def test_only_explicit_execution_experiment_may_change_schedule():
    runs = group()
    parent = runs["parent"]
    runs["parent"] = replace(parent, configuration={**conditions(), "schedule": {"type": "Weekly"}})
    with pytest.raises(ValueError, match="execution conditions"):
        SCRIPT.validate_matched(runs)
    SCRIPT.validate_matched(runs, allow_schedule_change=True)


def test_unavailable_inputs_are_kept_with_exact_status():
    run = saved_run()
    decisions = pd.DataFrame(
        {
            "session_date": [run.equity.index[0]],
            "skipped": ['{"vol_20": "NON_CONSECUTIVE_HISTORY"}'],
            "core_weight": [0.0],
            "missing_core": [True],
        }
    )
    rows = SCRIPT.rejected_inputs(replace(run, decisions=decisions))
    assert len(rows) == 1
    assert rows[0]["status"] == "NON_CONSECUTIVE_HISTORY"
    assert rows[0]["core_weight"] == 0
    assert rows[0]["input"] == "vol_20"


def test_malformed_skipped_is_not_silently_ignored():
    run = saved_run()
    run.decisions.loc[0, "skipped"] = "[]"
    with pytest.raises(ValueError, match="JSON object"):
        SCRIPT.rejected_inputs(run)


def test_all_reduced_episodes_include_short_and_unfinished():
    run = saved_run()
    weights = run.weights.copy()
    weights.iloc[3:8] = 0.5
    weights.iloc[170:] = 0.7
    rows = SCRIPT.reduced_episodes(replace(run, weights=weights), saved_run("Nasdaq_buy_hold"))
    assert len(rows) == 2
    assert rows[0]["sessions"] == 5
    assert rows[0]["first_restored_close"] == run.equity.index[8].date().isoformat()
    assert rows[1]["first_restored_close"] is None
    assert rows[0]["short_reduction_at_most_21_sessions"]


def test_regime_active_returns_do_not_depend_on_closing_weights():
    run = saved_run()
    reference = saved_run("Nasdaq_buy_hold")
    labels = SCRIPT.diagnostic_regimes(reference.equity)
    altered = replace(run, weights=run.weights * 0.25)
    a = SCRIPT.regime_metrics(run, reference, labels)
    b = SCRIPT.regime_metrics(altered, reference, labels)
    assert [row["mean_active_daily_bp"] for row in a] == [row["mean_active_daily_bp"] for row in b]
    assert (
        a[-1]["mean_nasdaq_closing_weight"] != b[-1]["mean_nasdaq_closing_weight"]
        or a[1]["mean_nasdaq_closing_weight"] != b[1]["mean_nasdaq_closing_weight"]
    )


def test_underwater_duration_hand_computable():
    curve_ = pd.Series([100.0, 90.0, 95.0, 100.0, 99.0, 101.0])
    assert SCRIPT.max_underwater_sessions(curve_) == 2
    assert SCRIPT.max_underwater_sessions(pd.Series([100.0, 101.0])) == 0


def test_bootstrap_is_paired_seeded_and_not_cagr():
    run = curve()
    result = SCRIPT.bootstrap_active(run, run)
    assert result["lower_95"] == result["upper_95"] == 0
    assert result == SCRIPT.bootstrap_active(run, run)
    with pytest.raises(ValueError, match="paired"):
        SCRIPT.bootstrap_active(run, run.iloc[:-1])


def test_saved_run_reconciles_fill_costs_and_nav(tmp_path):
    folder = tmp_path / "run"
    save_run(folder, saved_run())
    observed = SCRIPT.load_run(folder, "candidate", "choice", 1)
    assert observed.metrics["fills"] == 1
    metrics = json.loads((folder / "metrics.json").read_text())
    metrics["costs_eur"] = 99
    (folder / "metrics.json").write_text(json.dumps(metrics))
    refresh_hashes(folder)
    with pytest.raises(ValueError, match="fill costs"):
        SCRIPT.load_run(folder, "candidate", "choice", 1)


def test_incomplete_iteration_is_refused(tmp_path):
    with pytest.raises(ValueError, match="completed"):
        SCRIPT.load_iteration(tmp_path, "M01")


@pytest.mark.parametrize("label", ["M51", "M-1", "M001", "../M01", "Maa"])
def test_iteration_path_validation(label):
    with pytest.raises(ValueError):
        SCRIPT.validate_label(label)


def test_report_imports_no_policy_runner_or_market_store():
    tree = ast.parse(Path(SCRIPT.__file__).read_text())
    imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any(
        value
        and any(
            part in value
            for part in (
                "quant_backtester.strategies",
                "quant_backtester.backtest",
                "quant_backtester.data",
            )
        )
        for value in imports
    )


def test_trial_count_keeps_distinct_ablations_and_all_50_designs(tmp_path):
    for number in range(1, 51):
        base = tmp_path / f"M{number:02d}"
        base.mkdir()
        (base / "completed.json").write_text("{}")
        folder = base / "choice/costs_x1/without_trend"
        folder.mkdir(parents=True)
        (folder / "identity.json").write_text(json.dumps({"fingerprint": str(number % 2)}))
        (folder / "configuration.json").write_text(json.dumps({"schedule": {"type": "Monthly"}}))
    counts = SCRIPT.observed_trial_counts(tmp_path)
    assert counts["distinct_viewed_ablation_fingerprints"] == 2
    assert counts["trials_declared"] == 139


def test_changed_financial_artifact_is_refused(tmp_path):
    folder = tmp_path / "run"
    save_run(folder, saved_run())
    with (folder / "metrics.json").open("a") as handle:
        handle.write(" ")
    with pytest.raises(ValueError, match="checksum"):
        SCRIPT.load_run(folder, "candidate", "choice", 1)


def test_full_iteration_render_is_read_only_for_financial_evidence(tmp_path):
    iteration_fixture(tmp_path)
    folder = tmp_path / "M01"
    before = {
        path: path.read_bytes() for path in folder.glob("choice/costs_x*/candidate/metrics.json")
    }
    analysis = (folder / "analysis.json").read_bytes()
    result = SCRIPT.report_iteration(tmp_path, "M01")
    assert len(result["block_effects"]) == 6
    assert result["parent_profile"]["id"] == "M00"
    assert (folder / "analysis.json").read_bytes() == analysis
    assert all(path.read_bytes() == value for path, value in before.items())
    assert (folder / "reduced_episodes.csv").is_file()
    assert (folder / "reporting_manifest.json").is_file()


def test_unavailable_observer_is_counted_even_when_band_holds():
    run = saved_run()
    decisions = run.decisions.copy()
    decisions["plan_skipped"] = ['{"ma_200":"MISSING_EXPECTED_SESSION"}']
    result = SCRIPT.rejected_inputs(replace(run, decisions=decisions))
    assert result[0]["input"] == "ma_200"


def verdict_operations(gain=0.30, passive=0.20):
    return [
        {
            "period": period,
            "cost_multiplier": cost,
            "policy": role,
            "net_return": gain if role == "candidate" else passive,
            "max_drawdown": -0.20,
            "trade_dates_per_year": 2.0,
        }
        for period in ("full", "final")
        for cost in (1, 2)
        for role in ("candidate", "Nasdaq_buy_hold")
    ]


def test_final_failure_does_not_promote_an_ablation():
    result = SCRIPT.validation_verdict(verdict_operations(gain=0.10), True)
    assert result["status"] == "NOT_SUPPORTED"
    assert not result["automatic_promotion_of_ablation_or_runner_up"]
    assert result["default_reference"] == "Nasdaq_buy_hold"


def test_retrospective_success_is_uncertain_and_no_qualified_is_rejected():
    assert SCRIPT.validation_verdict(verdict_operations(), True)["status"] == "UNCERTAIN"
    assert SCRIPT.validation_verdict(verdict_operations(), False)["status"] == "UNCERTAIN"


def test_final_report_refuses_fewer_than_fifty_iterations(tmp_path):
    with pytest.raises(ValueError, match="fifty"):
        SCRIPT.report_final(tmp_path)


def test_dsr_is_descriptive_with_observed_curve_dispersion():
    a = curve()
    b = a.copy()
    b.iloc[1:] *= np.linspace(1, 1.15, len(b) - 1)
    diagnostic = SCRIPT.descriptive_dsr(a, [a, b], 140)
    assert diagnostic["trials_declared"] == 140
    assert diagnostic["available_dispersion_curves"] == 2
    assert diagnostic["session_sharpe_std"] > 0
    assert 0 <= diagnostic["absolute_sharpe_dsr"] <= 1


@pytest.mark.slow
def test_final_renderer_uses_frozen_evidence_without_running_engine(tmp_path):
    for number in range(1, 51):
        iteration_fixture(tmp_path, f"M{number:02d}")
    final_fixture(tmp_path)
    result = SCRIPT.report_final(tmp_path)
    assert result["status"] == "NOT_SUPPORTED"
    assert result["trials_declared"] == 138
    assert len(pd.read_csv(tmp_path / "reported_iterations.csv")) == 50
    assert (tmp_path / "full_curves.png").is_file()
    assert (tmp_path / "mechanism_frontier.png").is_file()
    assert "Gain brut | Gain net | CAGR net" in (tmp_path / "study.md").read_text()
    reporting = json.loads((tmp_path / "reporting_manifest.json").read_text())
    assert reporting["files"]["mechanism_frontier.png"] == SCRIPT.sha256(
        tmp_path / "mechanism_frontier.png"
    )
    assert (tmp_path / "diagnostic_unavailable_inputs.csv").is_file()


def test_historical_technical_attempts_never_add_designs(tmp_path):
    path = tmp_path / "history.json"
    path.write_text(
        json.dumps(
            {
                "physical_failed_serialization_replays": 0,
                "additional_candidate_designs": 0,
                "attempts": [],
            }
        )
    )
    assert SCRIPT.historical_replays(path)["additional_candidate_designs"] == 0
    path.write_text(
        json.dumps(
            {
                "physical_failed_serialization_replays": -1,
                "additional_candidate_designs": 0,
                "attempts": [],
            }
        )
    )
    with pytest.raises(ValueError, match="invalid"):
        SCRIPT.historical_replays(path)
    path.write_text(
        json.dumps(
            {
                "physical_failed_serialization_replays": 0,
                "additional_candidate_designs": 1,
                "attempts": [],
            }
        )
    )
    with pytest.raises(ValueError, match="additional"):
        SCRIPT.historical_replays(path)


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0.05, "5.00 pp"), (-0.0185, "-1.85 pp"), (0, "0.00 pp"), (None, "n.d.")],
)
def test_percentage_point_units_are_explicit(value, expected):
    assert SCRIPT.percentage_points(value) == expected


def test_iteration_displays_deltas_in_percentage_points():
    evidence = {
        "iteration": "M01",
        "block_effects": [
            {
                "cost_multiplier": 1,
                "control": "parent",
                "cagr_difference": -0.05,
                "drawdown_improvement": 0.15,
                "cost_difference_eur": 10.0,
                "trade_dates_difference": -2,
            }
        ],
    }
    rendered = SCRIPT.format_iteration({"parent": "M00", "changed_block": "trend"}, evidence)
    assert "-5.00 pp" in rendered
    assert "15.00 pp" in rendered
    assert "points de pourcentage" in rendered


def frontier_rows():
    return [
        {
            "id": f"M{number:02d}",
            "cagr": 0.08 + number / 500,
            "max_drawdown": -0.12 - number / 400,
            "trade_dates_per_year": number / 3,
        }
        for number in range(1, 51)
    ]


def test_frontier_draws_every_candidate_and_only_frozen_highlight(tmp_path, monkeypatch):
    calls = []
    original = SCRIPT.plt.Axes.scatter

    def capture(axis, x, y, *args: object, **kwargs: object) -> object:
        calls.append((np.asarray(x), np.asarray(y)))
        return original(axis, x, y, *args, **kwargs)

    monkeypatch.setattr(SCRIPT.plt.Axes, "scatter", capture)
    rows = frontier_rows()
    path = tmp_path / "frontier.png"
    SCRIPT.plot_mechanism_frontier(rows, 0.238, "M17", path)
    assert [len(call[0]) for call in calls] == [50, 1]
    np.testing.assert_allclose(calls[0][0], [abs(row["max_drawdown"]) for row in rows])
    np.testing.assert_allclose(calls[0][1], [row["cagr"] for row in rows])
    assert calls[1][1][0] == rows[16]["cagr"]
    assert path.is_file()


@pytest.mark.parametrize(
    "defect", ["missing_design", "duplicate_id", "nonfinite", "negative_dates"]
)
def test_frontier_refuses_filtered_or_invalid_evidence(tmp_path, defect):
    rows = frontier_rows()
    if defect == "missing_design":
        rows.pop()
    elif defect == "duplicate_id":
        rows[0]["id"] = "M02"
    elif defect == "nonfinite":
        rows[0]["cagr"] = float("nan")
    else:
        rows[0]["trade_dates_per_year"] = -1
    with pytest.raises(ValueError):
        SCRIPT.plot_mechanism_frontier(rows, 0.238, "M17", tmp_path / "invalid.png")


def complete_verdict_operations():
    periods = (
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
    return [
        {
            "period": period,
            "cost_multiplier": cost,
            "policy": role,
            "net_return": 0.30 if role == "candidate" else 0.20,
            "max_drawdown": -0.20 if role == "candidate" else -0.30,
            "trade_dates_per_year": 2.0,
        }
        for period in periods
        for cost in (1, 2)
        for role in ("candidate", "Nasdaq_buy_hold")
    ]


def positive_intervals():
    return {"full": {"lower_95": 0.01}, "final": {"lower_95": 0.01}}


def modify_verdict_row(rows, period, cost, **values: object):
    row = next(
        row
        for row in rows
        if row["period"] == period
        and row["cost_multiplier"] == cost
        and row["policy"] == "candidate"
    )
    row.update(values)


@pytest.mark.parametrize("period", ["final", "full"])
def test_only_main_normal_cost_failure_is_not_supported(period):
    rows = complete_verdict_operations()
    modify_verdict_row(rows, period, 1, net_return=0.20)
    result = SCRIPT.validation_verdict(rows, True, positive_intervals())
    assert result["status"] == "NOT_SUPPORTED"


def test_choice_qualification_failure_is_only_uncertain():
    result = SCRIPT.validation_verdict(complete_verdict_operations(), False, positive_intervals())
    assert result["status"] == "UNCERTAIN"
    assert not result["independent_future_validation"]


def test_cost_stress_failure_is_only_uncertain():
    rows = complete_verdict_operations()
    modify_verdict_row(rows, "full", 2, net_return=0.10)
    result = SCRIPT.validation_verdict(rows, True, positive_intervals())
    assert result["status"] == "UNCERTAIN"
    assert len(result["cost_stress_failures"]) == 1


@pytest.mark.parametrize("values", [{"max_drawdown": -0.251}, {"trade_dates_per_year": 4.1}])
def test_neighbor_risk_or_intervention_failure_is_only_uncertain(values):
    rows = complete_verdict_operations()
    modify_verdict_row(rows, "neighbor_short", 1, **values)
    result = SCRIPT.validation_verdict(rows, True, positive_intervals())
    assert result["status"] == "UNCERTAIN"
    assert not result["risk_and_intervention_targets_met"]


@pytest.mark.parametrize("lower", [None, -0.01, 0.0])
def test_active_interval_failure_is_only_uncertain(lower):
    intervals = positive_intervals()
    intervals["final"]["lower_95"] = lower
    result = SCRIPT.validation_verdict(complete_verdict_operations(), True, intervals)
    assert result["status"] == "UNCERTAIN"
    assert len(result["active_interval_failures"]) == 1


def test_cash_start_stability_failure_is_only_uncertain():
    rows = complete_verdict_operations()
    modify_verdict_row(rows, "start_2022", 1, net_return=0.10)
    result = SCRIPT.validation_verdict(rows, True, positive_intervals())
    assert result["status"] == "UNCERTAIN"
    assert len(result["stability_failures"]) == 1


def test_all_favorable_controls_allow_retrospective_support_only():
    result = SCRIPT.validation_verdict(complete_verdict_operations(), True, positive_intervals())
    assert result["status"] == "SUPPORTED_RETROSPECTIVE"
    assert not result["independent_future_validation"]
    assert result["dsr_is_descriptive_not_gating"]


def test_trial_identity_includes_cadence_with_same_policy_fingerprint(tmp_path):
    for number in range(1, 51):
        base = tmp_path / f"M{number:02d}"
        base.mkdir()
        (base / "completed.json").write_text("{}")
        folder = base / "choice/costs_x1/without_trend"
        folder.mkdir(parents=True)
        (folder / "identity.json").write_text(json.dumps({"fingerprint": "same-policy"}))
        schedule = "Monthly" if number % 2 else "Weekly"
        (folder / "configuration.json").write_text(json.dumps({"schedule": {"type": schedule}}))
    counts = SCRIPT.observed_trial_counts(tmp_path)
    assert counts["distinct_viewed_ablation_fingerprints"] == 1
    assert counts["distinct_viewed_ablation_profiles"] == 2
    assert counts["trials_declared"] == 139
    run = saved_run()
    weekly = replace(run, configuration={**run.configuration, "schedule": {"type": "Weekly"}})
    assert SCRIPT.policy_profile(run) != SCRIPT.policy_profile(weekly)


@pytest.mark.parametrize("name", list(SCRIPT.BASE_COSTS))
def test_every_actual_cost_component_is_checked(name):
    config = conditions()
    config["execution"] = {"costs": {key: value * 2 for key, value in SCRIPT.BASE_COSTS.items()}}
    config["execution"]["costs"][name] = SCRIPT.BASE_COSTS[name]
    with pytest.raises(ValueError, match=name):
        SCRIPT.validate_costs(config, 2)


def test_x1_archive_mislabeled_as_x2_is_rejected(tmp_path):
    folder = tmp_path / "saved"
    save_run(folder, saved_run())
    with pytest.raises(ValueError, match="cost multiplier"):
        SCRIPT.load_run(folder, "candidate", "choice", 2)


def test_iteration_contract_cannot_substitute_another_canonical_signature(tmp_path):
    iteration_fixture(tmp_path)
    folder = tmp_path / "M01"
    contract = json.loads((folder / "contract.json").read_text())
    contract["contracts"][0]["cache_key"] = "0" * 64
    (folder / "contract.json").write_text(json.dumps(contract))
    completed = json.loads((folder / "completed.json").read_text())
    completed["contract_sha256"] = SCRIPT.sha256(folder / "contract.json")
    (folder / "completed.json").write_text(json.dumps(completed))
    with pytest.raises(ValueError, match="canonical financial signature"):
        SCRIPT.load_iteration(tmp_path, "M01")


def test_final_cache_link_is_mandatory(tmp_path):
    iteration_fixture(tmp_path)
    final_fixture(tmp_path)
    (tmp_path / "final/costs_x1/candidate/cache_link.json").unlink()
    with pytest.raises(ValueError, match="cache link is missing"):
        SCRIPT.final_evidence(tmp_path)


@pytest.mark.parametrize("defect", ["duplicate", "wrong_dates", "wrong_parameters"])
def test_final_contract_grid_dates_and_profiles_are_checked(tmp_path, defect):
    iteration_fixture(tmp_path)
    final_fixture(tmp_path)
    path = tmp_path / "final_contracts.json"
    contracts = json.loads(path.read_text())
    if defect == "duplicate":
        contracts["contracts"].append(contracts["contracts"][0])
    elif defect == "wrong_dates":
        contracts["contracts"][0]["start"] = "2025-01-03"
    else:
        contracts["contracts"][0]["parameters"]["fast_sessions"] = 22
    path.write_text(json.dumps(contracts))
    completed = json.loads((tmp_path / "final_completed.json").read_text())
    completed.update(
        contract_sha256=SCRIPT.sha256(path), logical_contract_count=len(contracts["contracts"])
    )
    (tmp_path / "final_completed.json").write_text(json.dumps(completed))
    with pytest.raises(ValueError):
        SCRIPT.final_evidence(tmp_path)


def test_audit_links_are_conditional_and_keep_scope_limits(tmp_path):
    assert SCRIPT.audit_note_links(tmp_path) == ""
    (tmp_path / "causality_readonly.md").write_text("local computer causality check")
    (tmp_path / "audit_readonly_M16.md").write_text("archived evidence integrity")
    text = SCRIPT.audit_note_links(tmp_path)
    assert "(causality_readonly.md)" in text
    assert "(audit_readonly_M16.md)" in text
    assert "surajustement" in text and "point-in-time" in text
    assert "ne changent pas les effectifs" in text
