"""Saved-evidence tests for the fourth SA15 report, without market access."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]


def load_script() -> ModuleType:
    """Load the report without invoking a financial driver."""
    spec = importlib.util.spec_from_file_location(
        "SA15_report_gpt61_round4", ROOT / "scripts/SA15_report_gpt61_round4.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SCRIPT = load_script()


def write_json(path: Path, value: object) -> None:
    """Write a synthetic saved artifact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def curve(growth: float = 0.001) -> pd.Series:
    """Produce a varying path with sufficient saved 2023 validation sessions."""
    returns = growth + 0.002 * np.sin(np.arange(79) / 4)
    return pd.Series(
        100_000 * np.r_[1, np.cumprod(1 + returns)],
        index=pd.bdate_range("2023-10-02", periods=80, name="session_date"),
        name="net_equity",
    )


def metrics(equity: pd.Series) -> dict:
    """Calculate fields used by the report from a small curve."""
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    returns = equity.pct_change(fill_method=None).iloc[1:]
    return {
        "net_return": float(equity.iloc[-1] / equity.iloc[0] - 1),
        "gross_return": float(equity.iloc[-1] / equity.iloc[0] - 1),
        "cagr": float((equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1),
        "max_drawdown": float((equity / equity.cummax() - 1).min()),
        "volatility": float(returns.std() * np.sqrt(252)),
        "sharpe": float(returns.mean() / returns.std() * np.sqrt(252)),
        "costs_eur": 20.0,
        "fills": 3,
        "rejects": 0,
        "turnover_per_year": 1.0,
        "trade_days": 2,
        "trade_days_per_year": 2 / years,
        "decision_days_per_year": 12.0,
        "sessions": len(equity),
    }


def write_run(folder: Path, equity: pd.Series) -> dict:
    """Save actual intervention dates and net/gross curves."""
    values = metrics(equity)
    write_json(folder / "metrics.json", values)
    equity.to_csv(folder / "equity.csv")
    equity.rename("gross_equity").to_csv(folder / "gross_equity.csv")
    pd.DataFrame({"session_date": [equity.index[1], equity.index[1], equity.index[30]]}).to_csv(
        folder / "fills.csv", index=False
    )
    pd.DataFrame({"ETF_NASDAQ": 0.6, "ETF_GOLD": 0.4}, index=equity.index).to_csv(
        folder / "weights.csv"
    )
    return values


def study(output: Path) -> dict:
    """Create fifty designs and a deliberately fixed winner distinct from best return."""
    parameters = {
        "mode": "balanced",
        "core_id": "ETF_NASDAQ",
        "risky_ids": ["ETF_NASDAQ", "ETF_GOLD"],
        "allocation_mode": "fixed",
        "fixed_weights": [0.6, 0.4],
        "top_k": 2,
        "momentum_lookbacks": [63, 126],
        "momentum_weights": [1, 1],
        "core_floor": 0,
        "defensive_ids": [],
        "defensive_top_k": 1,
        "rebalance_band": 0.1,
        "switch_buffer": 0.02,
        "canary_ids": [],
        "target_volatility": 0,
    }
    reference = metrics(curve(0.001))
    for trial in range(31, 81):
        folder = output / f"trial_{trial:02d}"
        spec = {
            "number": trial,
            "reason": f"Design {trial}",
            "schedule": "quarterly",
            "parameters": parameters,
        }
        write_json(folder / "candidate.json", spec)
        choice = write_run(folder / "choice", curve(0.0002 + trial * 0.00001))
        write_run(folder / "costs_x2/choice", curve(0.0001 + trial * 0.00001))
        evidence = {
            "score": trial / 1000,
            "qualified": False,
            "excess_choice": choice["cagr"] - reference["cagr"],
            "excess_validation": choice["cagr"] - reference["cagr"],
            "drawdown_depth": abs(choice["max_drawdown"]),
            "trade_days_per_year": choice["trade_days_per_year"],
            "candidate_sha256": hashlib.sha256(
                (folder / "candidate.json").read_bytes()
            ).hexdigest(),
            "metrics": {name: choice for name in ("choice", "development", "validation")},
        }
        write_json(folder / "selection.json", evidence)
    for period in SCRIPT.PERIODS:
        for name in SCRIPT.REFERENCES:
            write_run(SCRIPT.result_folder(output, period, name, 31), curve())
    for period in ("full", "final"):
        folder = output / period / SCRIPT.BOOK
        write_run(folder, curve(0.00051))
        write_run(output / period / "costs_x2", curve(0.00041))
    definition = {
        "class": "tests.FrozenRiskAware",
        "strategy_id": SCRIPT.BOOK,
        "parameters": parameters,
        "signals": [],
    }
    write_json(output / "final" / SCRIPT.BOOK / "strategy.json", definition)
    write_json(
        output / "final" / SCRIPT.BOOK / "configuration.json",
        {
            "initial_cash": 100_000,
            "timetable": {
                "decision_time": "23:00:00",
                "execution_time": "09:01:00",
                "timezone": "Europe/Paris",
            },
        },
    )
    winner_folder = output / "trial_31"
    selected = {
        "candidate": SCRIPT.read_json(winner_folder / "candidate.json"),
        "parameters": parameters,
        "fingerprint": hashlib.sha256(
            json.dumps(definition, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "total_trials": 80,
        "round_trials": 50,
        "score": 0.031,
        "candidate_sha256": hashlib.sha256(
            (winner_folder / "candidate.json").read_bytes()
        ).hexdigest(),
        "selection_sha256": hashlib.sha256(
            (winner_folder / "selection.json").read_bytes()
        ).hexdigest(),
    }
    write_json(output / "selected.json", selected)
    (output / "selected.sha256").write_text(
        hashlib.sha256((output / "selected.json").read_bytes()).hexdigest()
    )
    starts = []
    for start in ("2020-01-02", "2021-01-04", "2022-01-03", "2023-01-02"):
        for name in (SCRIPT.BOOK, *SCRIPT.REFERENCES):
            starts.append({"start": start, "book": name, **metrics(curve())})
    (output / "robustness").mkdir()
    pd.DataFrame(starts).to_csv(output / "robustness/starts.csv", index=False)
    return selected


def test_report_imports_no_runner_or_policy() -> None:
    tree = ast.parse((ROOT / "scripts/SA15_report_gpt61_round4.py").read_text())
    modules = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any(
        module and (".backtest." in module or "strategies" in module or "SA15_run" in module)
        for module in modules
    )


def test_pareto_requires_a_strict_improvement_and_keeps_equal_points() -> None:
    rows = [
        {"trial": 31, "choice_cagr": 0.2, "drawdown_depth": 0.2, "trade_days_per_year": 2},
        {"trial": 32, "choice_cagr": 0.19, "drawdown_depth": 0.21, "trade_days_per_year": 3},
        {"trial": 33, "choice_cagr": 0.18, "drawdown_depth": 0.1, "trade_days_per_year": 1},
        {"trial": 34, "choice_cagr": 0.2, "drawdown_depth": 0.2, "trade_days_per_year": 2},
    ]
    assert SCRIPT.pareto_front(rows) == [31, 33, 34]


def test_actual_interventions_count_one_date_for_multiple_orders(tmp_path) -> None:
    equity = curve()
    write_run(tmp_path, equity)
    result = SCRIPT.operational_metrics(tmp_path, equity, {})
    assert result["trade_days"] == 2
    assert result["fills_per_year"] / result["trade_days_per_year"] == pytest.approx(1.5)


def test_bootstrap_is_seeded_and_identical_returns_have_zero_interval() -> None:
    result = SCRIPT.bootstrap_interval(curve(), curve())
    assert result["seed"] == 61154
    assert result["lower_95"] == result["upper_95"] == 0
    assert SCRIPT.bootstrap_interval(curve(), curve(0.0008)) == SCRIPT.bootstrap_interval(
        curve(), curve(0.0008)
    )


def test_validation_slice_preserves_previous_close_anchor() -> None:
    equity = pd.Series(
        [100, 110, 121, 133.1],
        index=pd.to_datetime(["2022-12-29", "2022-12-30", "2023-01-02", "2023-01-03"]),
    )
    sliced = SCRIPT.validation_slice(equity)
    assert sliced.index[0] == pd.Timestamp("2022-12-30")
    assert sliced.iloc[-1] / sliced.iloc[0] - 1 == pytest.approx(0.21)


@pytest.mark.parametrize(
    ("excess", "stress", "drawdown", "trades", "lower", "status"),
    [
        (-0.01, 0.01, -0.2, 2, 0.01, "NOT_SUPPORTED"),
        (0.01, -0.01, -0.2, 2, 0.01, "UNCERTAIN"),
        (0.01, 0.01, -0.26, 2, 0.01, "UNCERTAIN"),
        (0.01, 0.01, -0.2, 5, 0.01, "UNCERTAIN"),
        (0.01, 0.01, -0.2, 2, 0.0, "UNCERTAIN"),
        (0.01, 0.01, -0.25, 4, 0.001, "SUPPORTED_RETROSPECTIVE"),
    ],
)
def test_joint_verdict(excess, stress, drawdown, trades, lower, status) -> None:
    value = {"excess": excess, "max_drawdown": drawdown, "trade_days_per_year": trades}
    assert (
        SCRIPT.hypothesis_status(value, value, {"excess": stress}, {"excess": stress}, lower)[0]
        == status
    )


def test_saved_financial_checksum_and_gross_dates_are_enforced(tmp_path) -> None:
    write_run(tmp_path, curve())
    SCRIPT.verify_run(tmp_path)
    path = tmp_path / "equity.csv"
    write_json(
        tmp_path / "cache.json",
        {"artifacts": {"equity.csv": hashlib.sha256(path.read_bytes()).hexdigest()}},
    )
    with path.open("a") as stream:
        stream.write("\n")
    with pytest.raises(ValueError, match="artifact differs"):
        SCRIPT.verify_run(tmp_path)


def test_complete_report_preserves_financial_evidence_and_fixed_winner(tmp_path) -> None:
    selected = study(tmp_path)
    paths = [path for path in tmp_path.rglob("*") if path.is_file()]
    before = {path: path.read_bytes() for path in paths}
    previous = tuple(tmp_path / name for name in ("R1", "R2", "R3"))
    SCRIPT.report(tmp_path, previous_outputs=previous)
    assert all(path.read_bytes() == value for path, value in before.items())
    assert SCRIPT.read_json(tmp_path / "verdict.json")["selected_trial"] == 31
    assert SCRIPT.read_json(tmp_path / "selected.json") == selected
    assert len(pd.read_csv(tmp_path / "reported_iterations.csv")) == 50
    assert SCRIPT.read_json(tmp_path / "selection_diagnostics.json")["total_trials_declared"] == 80
    assert SCRIPT.read_json(tmp_path / "selection_diagnostics.json")[
        "previous_trials_missing"
    ] == list(range(1, 31))
    assert SCRIPT.read_json(tmp_path / "final/uncertainty.json")["seed"] == 61154
    text = (tmp_path / "study.md").read_text()
    assert "80 cumulés" in text and "aucun 81e design" in text
    assert "Meilleur rendement" in text and "Choix gelé" in text
    assert "0.6, 0.4" in text
    for period in SCRIPT.PERIODS:
        assert (tmp_path / f"comparison/{period}/comparison.png").is_file()
    assert (tmp_path / "frontier.png").is_file()


def test_frozen_parameter_tampering_is_rejected(tmp_path) -> None:
    study(tmp_path)
    definition = SCRIPT.read_json(tmp_path / "final" / SCRIPT.BOOK / "strategy.json")
    definition["parameters"]["fixed_weights"] = [0.5, 0.5]
    write_json(tmp_path / "final" / SCRIPT.BOOK / "strategy.json", definition)
    with pytest.raises(ValueError, match="fingerprint"):
        SCRIPT.frozen_selection(tmp_path)


def test_incomplete_fifty_design_report_is_rejected(tmp_path) -> None:
    study(tmp_path)
    (tmp_path / "trial_80/selection.json").unlink()
    with pytest.raises(ValueError, match="fifty"):
        SCRIPT.trial_rows(tmp_path)


def test_announced_batch_candidates_must_match_archived_designs(tmp_path) -> None:
    study(tmp_path)
    rows = SCRIPT.trial_rows(tmp_path)[:10]
    batch = {
        "numbers": list(range(31, 41)),
        "candidates": [
            SCRIPT.read_json(tmp_path / f"trial_{trial:02d}/candidate.json")
            for trial in range(31, 41)
        ],
    }
    path = tmp_path / "batches/batch_01.json"
    write_json(path, batch)
    assert SCRIPT.verify_batch_manifests(tmp_path, rows)["candidates_verified"] == 10
    batch["candidates"][0]["reason"] = "Changed after announcement"
    write_json(path, batch)
    with pytest.raises(ValueError, match="preannounced"):
        SCRIPT.verify_batch_manifests(tmp_path, rows)


def test_empty_companion_manifest_is_descriptive_and_checksum_protected(tmp_path) -> None:
    manifest = {"expected_winner": {"number": 31}, "companions": []}
    path = tmp_path / "companions_frozen.json"
    write_json(path, manifest)
    checksum = tmp_path / "companions_frozen.sha256"
    checksum.write_text("wrong")
    with pytest.raises(ValueError, match="checksum"):
        SCRIPT.companion_section(tmp_path, 31)
    checksum.write_text(hashlib.sha256(path.read_bytes()).hexdigest())
    assert "Aucun compagnon distinct" in SCRIPT.companion_section(tmp_path, 31)
    with pytest.raises(ValueError, match="disagree"):
        SCRIPT.companion_section(tmp_path, 32)


def test_missing_window_reasons_remain_distinct_from_market_risk(tmp_path) -> None:
    folder = tmp_path / "trial_71/choice"
    folder.mkdir(parents=True)
    pd.DataFrame(
        {
            "session_date": ["2023-01-31", "2023-02-28", "2023-03-31"],
            "skipped": [
                "{}",
                json.dumps({"ETF_US_TECH": "NON_CONSECUTIVE_HISTORY"}),
                json.dumps({"ETF_US_TECH": "NON_CONSECUTIVE_HISTORY"}),
            ],
        }
    ).to_csv(folder / "decisions.csv", index=False)
    text = SCRIPT.availability_section(tmp_path, 71)
    assert "NON_CONSECUTIVE_HISTORY" in text
    assert "pas une volatilité économique élevée" in text
    assert "| 2 |" in text
    assert "2023-02-28, 2023-03-31" in text
    assert "Traces indisponibles" in text


def test_companion_comparisons_keep_the_main_winner_and_local_parameters(tmp_path) -> None:
    manifest = {
        "expected_winner": {"number": 71},
        "companions": [
            {
                "number": 79,
                "candidate": {"parameters": {"core_id": "ETF_US_TECH", "mode": "balanced"}},
            }
        ],
    }
    path = tmp_path / "companions_frozen.json"
    write_json(path, manifest)
    (tmp_path / "companions_frozen.sha256").write_text(
        hashlib.sha256(path.read_bytes()).hexdigest()
    )
    main = {"core_id": "ETF_NASDAQ", "mode": "rotate"}
    runs = SCRIPT.comparison_runs(tmp_path, "full", 71, main)
    assert list(runs)[:4] == [SCRIPT.BENCHMARK, "Tech_buy_hold", "Companion_79", SCRIPT.BOOK]
    assert runs[SCRIPT.BOOK][1] == main
    assert runs["Companion_79"][1]["mode"] == "balanced"
    assert runs["Companion_79"][0] == tmp_path / "companions/trial_79/full"
    assert SCRIPT.book_label("Companion_79") == "Compagnon 79"
    choice = SCRIPT.comparison_runs(tmp_path, "choice", 71, main)
    assert "Companion_79" not in choice
