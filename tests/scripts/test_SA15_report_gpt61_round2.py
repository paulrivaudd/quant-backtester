"""Saved-results tests for the second SA15 report; no market store or backtest."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import numpy as np
import pandas as pd
import pytest

from quant_backtester.backtest.runner import StrategyRunner

ROOT = Path(__file__).resolve().parents[2]


def load_script() -> ModuleType:
    """Import only the report under test, without invoking its CLI."""
    path = ROOT / "scripts/SA15_report_gpt61_round2.py"
    spec = importlib.util.spec_from_file_location("SA15_report_gpt61_round2", path)
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
    """Return a varying positive path spanning two calendar years."""
    returns = growth + 0.002 * np.sin(np.arange(79) / 4.0)
    values = 100_000.0 * np.r_[1.0, np.cumprod(1.0 + returns)]
    return pd.Series(
        values,
        index=pd.bdate_range("2024-11-01", periods=80, name="session_date"),
        name="net_equity",
    )


def saved_metrics(equity: pd.Series, fills: int = 3) -> dict:
    """Provide ordinary saved-run fields, calculated without a runner."""
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    returns = equity.pct_change(fill_method=None).iloc[1:]
    drawdown = float((equity / equity.cummax() - 1).min())
    cagr = float((equity.iloc[-1] / equity.iloc[0]) ** (1.0 / years) - 1.0)
    return {
        "net_return": float(equity.iloc[-1] / equity.iloc[0] - 1.0),
        "gross_return": float(equity.iloc[-1] / equity.iloc[0] - 1.0 + 0.001),
        "cagr": cagr,
        "volatility": float(returns.std() * np.sqrt(252)),
        "sharpe": float(returns.mean() / returns.std() * np.sqrt(252)),
        "max_drawdown": drawdown,
        "costs_eur": 120.0,
        "turnover_per_year": 0.6,
        "fills": fills,
        "rejects": 0,
        "decisions_with_skipped_inputs": 0,
        "sessions": len(equity),
    }


def write_run(folder: Path, equity: pd.Series, *, details: bool = True) -> None:
    """Write synthetic curves, metrics and optional actual-order/position details."""
    write_json(folder / "metrics.json", saved_metrics(equity))
    equity.to_csv(folder / "equity.csv")
    if not details:
        return
    pd.DataFrame({"session_date": [equity.index[1], equity.index[1], equity.index[30]]}).to_csv(
        folder / "fills.csv", index=False
    )
    pd.DataFrame(
        {
            "ETF_SP500_PEA": 0.73,
            "ETF_NASDAQ": 0.27,
            "ETF_MONETARY_EUR": 0.0,
        },
        index=equity.index,
    ).to_csv(folder / "weights.csv")


def saved_study(output: Path) -> dict:
    """Create two completed candidates and all four periods of frozen saved results."""
    parameters = {
        "core_id": "ETF_SP500_PEA",
        "monetary_id": "ETF_MONETARY_EUR",
        "satellite_ids": ["ETF_NASDAQ"],
        "core_fraction": 0.73,
        "top_k": 1,
    }
    specs = {
        number: {
            "number": number,
            "reason": f"Reason for candidate {number}",
            "schedule": "monthly",
            "parameters": {"core_fraction": 0.73},
        }
        for number in (11, 12)
    }
    for number in specs:
        write_json(output / f"trial_{number:02d}/candidate.json", specs[number])
        for period in ("development", "validation"):
            write_run(
                output / f"trial_{number:02d}" / period,
                curve(0.001 if number == 12 else 0.0006),
            )
    for period in SCRIPT.PERIODS:
        for name, growth in (
            ("SP500_buy_hold", 0.0008),
            ("Nasdaq_buy_hold", 0.0014),
            ("static_50_50", 0.0011),
        ):
            folder = (
                output / "full" / name
                if period == "full"
                else output / "references" / period / name
            )
            write_run(folder, curve(growth), details=False)
    write_run(output / "final" / SCRIPT.BOOK, curve())
    write_run(output / "full" / SCRIPT.BOOK, curve())
    definition = {
        "class": "tests.FrozenRelativeMomentum",
        "strategy_id": SCRIPT.BOOK,
        "parameters": parameters,
        "signals": [],
    }
    canonical = json.dumps(definition, sort_keys=True, separators=(",", ":"))
    selected = {
        "candidate": specs[12],
        "fingerprint": hashlib.sha256(canonical.encode()).hexdigest(),
        "parameters": parameters,
        "total_trials": 20,
        "round_trials": 2,
    }
    write_json(output / "selected.json", selected)
    write_json(output / "final" / SCRIPT.BOOK / "strategy.json", definition)
    write_json(
        output / "final" / SCRIPT.BOOK / "configuration.json",
        {
            "initial_cash": 100_000.0,
            "timetable": {
                "decision_time": "23:00:00",
                "execution_time": "09:01:00",
                "timezone": "Europe/Paris",
            },
        },
    )
    stress = saved_metrics(curve())
    stress["net_return"] -= 0.005
    write_json(output / "final/costs_x2/metrics.json", stress)
    return selected


@pytest.mark.parametrize(
    ("full", "final", "stress", "lower", "expected"),
    [
        (0.02, 0.01, 0.005, 0.001, "SUPPORTED_RETROSPECTIVE"),
        (0.0, 0.01, 0.005, 0.001, "NOT_SUPPORTED"),
        (0.02, -0.01, 0.005, 0.001, "NOT_SUPPORTED"),
        (0.02, 0.01, 0.0, 0.001, "UNCERTAIN"),
        (0.02, 0.01, 0.005, 0.0, "UNCERTAIN"),
    ],
)
def test_status_requires_both_benchmark_wins_before_uncertainty_checks(
    full, final, stress, lower, expected
) -> None:
    assert SCRIPT.hypothesis_status(full, final, stress, lower)[0] == expected


def test_actual_trade_dates_count_one_intervention_for_multiple_orders(tmp_path) -> None:
    equity = curve()
    write_run(tmp_path, equity)
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    result = SCRIPT.operational_metrics(tmp_path, equity, {"satellite_ids": ["ETF_NASDAQ"]})
    assert result["trade_days"] == 2
    assert result["trade_days_per_year"] == pytest.approx(2 / years)
    assert result["fills_per_year"] == pytest.approx(3 / years)
    assert result["average_core_weight"] == pytest.approx(0.73)
    assert result["average_satellite_weight"] == pytest.approx(0.27)
    assert result["average_cash_weight"] == pytest.approx(0.0)


def test_reference_without_detail_does_not_invent_zero_interventions(tmp_path) -> None:
    equity = curve()
    write_run(tmp_path, equity, details=False)
    result = SCRIPT.operational_metrics(tmp_path, equity, {})
    assert result["trade_days"] is None
    assert result["trade_days_per_year"] is None
    assert result["average_core_weight"] is None
    assert result["fills_per_year"] > 0


def test_analytics_date_conversion_leaves_plot_index_and_values_unchanged() -> None:
    original = curve()
    saved = original.copy()
    converted = SCRIPT.analytics_copy(original)
    assert isinstance(original.index, pd.DatetimeIndex)
    assert type(converted.index[0]).__name__ == "date"
    assert converted.iloc[-1] == original.iloc[-1]
    pd.testing.assert_series_equal(original, saved)


def test_paired_bootstrap_is_seeded_and_identical_books_have_zero_active_return() -> None:
    original = curve()
    result = SCRIPT.bootstrap_interval(original, original.copy())
    assert result["annualised_mean_active_return"] == result["lower_95"] == result["upper_95"] == 0
    assert result["seed"] == 61152
    assert result["block_sessions"] == 20
    assert result["replications"] == 2_000
    different = SCRIPT.bootstrap_interval(original, curve(0.0008))
    assert different == SCRIPT.bootstrap_interval(original, curve(0.0008))


def test_frozen_definition_is_authoritative_over_candidate_overrides(tmp_path) -> None:
    selected = saved_study(tmp_path)
    _selection, definition, _configuration = SCRIPT.frozen_selection(tmp_path)
    assert "top_k" not in selected["candidate"]["parameters"]
    assert definition["parameters"]["top_k"] == 1
    changed = {**selected, "parameters": {**selected["parameters"], "core_fraction": 0.5}}
    write_json(tmp_path / "selected.json", changed)
    with pytest.raises(ValueError, match="fingerprint differ"):
        SCRIPT.frozen_selection(tmp_path)


def test_dsr_uses_all_ten_first_round_curves_or_declares_fallback(tmp_path) -> None:
    saved_study(tmp_path)
    trials = SCRIPT.trial_rows(tmp_path)
    first_round = tmp_path / "round_one"
    fallback = SCRIPT.selection_diagnostics(tmp_path, trials, first_round)
    assert fallback["total_trials_declared"] == 20
    assert fallback["dispersion_curves"] == 2
    assert fallback["dispersion_source"].startswith("R2_validation_curves_only")
    for trial in range(1, 11):
        folder = first_round / f"trial_{trial:02d}/validation"
        folder.mkdir(parents=True)
        curve(0.0003 + trial * 0.0001).to_csv(folder / "equity.csv")
    combined = SCRIPT.selection_diagnostics(tmp_path, trials, first_round)
    assert combined["total_trials_declared"] == 20
    assert combined["dispersion_curves"] == 12
    assert combined["dispersion_source"] == "R1_and_R2_validation_curves"


def test_complete_report_exports_saved_results_without_running_a_strategy(
    tmp_path, monkeypatch
) -> None:
    saved_study(tmp_path)
    evidence = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}

    def forbidden(*_args: object, **_kwargs: object) -> None:
        pytest.fail("a report must never execute a backtest")

    monkeypatch.setattr(StrategyRunner, "run", forbidden)
    SCRIPT.report(tmp_path, r1_output=tmp_path / "missing_round_one")
    for path, content in evidence.items():
        assert path.read_bytes() == content
    for period in SCRIPT.PERIODS:
        folder = tmp_path / "comparison" / period
        assert (folder / "comparison.png").is_file()
        assert (folder / "summary.csv").is_file()
        assert (folder / "equity.csv").is_file()
        yearly = pd.read_csv(folder / "yearly.csv")
        assert list(yearly["year"]) == [2024, 2025]
        relative = pd.read_csv(folder / "relative_wealth.csv")
        assert relative["SP500_buy_hold"].eq(1.0).all()
    text = (tmp_path / "study.md").read_text()
    assert "prototype" in text and "| top_k | 1 |" in text
    assert "20 essais correles" in text
    assert "aucune de ces periodes n'est un echantillon vierge" in text
    assert "Reason for candidate 11" in text and "Reason for candidate 12" in text
    assert "Nasdaq conserve" in text and "50/50 initial" in text
    assert "61152" in text and "Jours d'ordres/an" in text
    assert (tmp_path / "final/uncertainty.json").is_file()
    assert (tmp_path / "reported_iterations.csv").is_file()


def test_comparison_refuses_a_missing_session_without_filling(tmp_path) -> None:
    selected = saved_study(tmp_path)
    folder = tmp_path / "references/final/SP500_buy_hold"
    equity = SCRIPT.load_equity(folder / "equity.csv").iloc[:-1]
    equity.to_csv(folder / "equity.csv")
    with pytest.raises(ValueError, match="comparison dates differ"):
        SCRIPT.render_comparison(tmp_path, "final", 12, selected["parameters"])
