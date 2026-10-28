"""Saved-results tests for the third SA15 report; no market store or backtest."""

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
    path = ROOT / "scripts/SA15_report_gpt61_round3.py"
    spec = importlib.util.spec_from_file_location("SA15_report_gpt61_round3", path)
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
            "ETF_NASDAQ": 0.73,
            "ETF_GOLD": 0.27,
            "ETF_MONETARY_EUR": 0.0,
        },
        index=equity.index,
    ).to_csv(folder / "weights.csv")


def policy_parameters() -> dict:
    """Return an explicit saved policy fixture rather than importing live class defaults."""
    return {
        "core_id": "ETF_NASDAQ",
        "defensive_ids": ["ETF_GOLD"],
        "monetary_id": "ETF_MONETARY_EUR",
        "guard_mode": "momentum",
        "trend_sessions": 0,
        "fast_lookback": 21,
        "slow_lookback": 126,
        "fast_entry_threshold": -0.04,
        "slow_entry_threshold": 0.0,
        "recovery_threshold": 0.0,
        "core_floor": 0.73,
        "defensive_lookbacks": [63, 126],
        "defensive_weights": [1.0, 1.0],
        "top_k": 1,
        "switch_buffer": 0.02,
        "rebalance_band": 0.08,
        "relative_rotation": False,
        "relative_threshold": 0.02,
        "monetary_lookback": 21,
        "max_age_sessions": 1,
    }


def saved_study(output: Path) -> dict:
    """Create two completed candidates and all four periods of frozen saved results."""
    parameters = policy_parameters()
    specs = {
        number: {
            "number": number,
            "reason": f"Reason for candidate {number}",
            "schedule": "monthly",
            "parameters": {"core_floor": 0.73},
        }
        for number in (21, 22)
    }
    for number in specs:
        write_json(output / f"trial_{number:02d}/candidate.json", specs[number])
        for period in ("development", "validation"):
            write_run(
                output / f"trial_{number:02d}" / period,
                curve(0.001 if number == 22 else 0.0006),
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
        "class": "tests.FrozenNasdaqAdaptive",
        "strategy_id": SCRIPT.BOOK,
        "parameters": parameters,
        "signals": [],
    }
    canonical = json.dumps(definition, sort_keys=True, separators=(",", ":"))
    selected = {
        "candidate": specs[22],
        "fingerprint": hashlib.sha256(canonical.encode()).hexdigest(),
        "parameters": parameters,
        "total_trials": 30,
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
    result = SCRIPT.operational_metrics(tmp_path, equity, {"defensive_ids": ["ETF_GOLD"]})
    assert result["trade_days"] == 2
    assert result["trade_days_per_year"] == pytest.approx(2 / years)
    assert result["fills_per_year"] == pytest.approx(3 / years)
    assert result["average_core_weight"] == pytest.approx(0.73)
    assert result["average_defensive_weight"] == pytest.approx(0.27)
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
    assert result["seed"] == 61153
    assert result["block_sessions"] == 20
    assert result["replications"] == 2_000
    different = SCRIPT.bootstrap_interval(original, curve(0.0008))
    assert different == SCRIPT.bootstrap_interval(original, curve(0.0008))


def test_frozen_definition_is_authoritative_over_candidate_overrides(tmp_path) -> None:
    selected = saved_study(tmp_path)
    _selection, definition, _configuration = SCRIPT.frozen_selection(tmp_path)
    assert "top_k" not in selected["candidate"]["parameters"]
    assert definition["parameters"]["top_k"] == 1
    changed = {**selected, "parameters": {**selected["parameters"], "core_floor": 0.5}}
    write_json(tmp_path / "selected.json", changed)
    with pytest.raises(ValueError, match="fingerprint differ"):
        SCRIPT.frozen_selection(tmp_path)


def test_dsr_declares_thirty_even_when_prior_rounds_are_partially_missing(tmp_path) -> None:
    saved_study(tmp_path)
    trials = SCRIPT.trial_rows(tmp_path)
    first_round = tmp_path / "round_one"
    second_round = tmp_path / "round_two"
    fallback = SCRIPT.selection_diagnostics(tmp_path, trials, first_round, second_round)
    assert fallback["total_trials_declared"] == 30
    assert fallback["dispersion_curves"] == 2
    assert fallback["previous_trials_missing"] == list(range(1, 21))
    for number in range(1, 21):
        root = first_round if number <= 10 else second_round
        folder = root / f"trial_{number:02d}/validation"
        folder.mkdir(parents=True)
        curve(0.0003 + number * 0.0001).to_csv(folder / "equity.csv")
    combined = SCRIPT.selection_diagnostics(tmp_path, trials, first_round, second_round)
    assert combined["total_trials_declared"] == 30
    assert combined["dispersion_curves"] == 22
    assert combined["dispersion_source"] == "R1_R2_R3_validation_curves"
    assert combined["previous_trials_missing"] == []
    (second_round / "trial_17/validation/equity.csv").unlink()
    partial = SCRIPT.selection_diagnostics(tmp_path, trials, first_round, second_round)
    assert partial["dispersion_curves"] == 21
    assert partial["previous_trials_missing"] == [17]
    assert partial["total_trials_declared"] == 30


def test_complete_report_exports_saved_results_without_running_a_strategy(
    tmp_path, monkeypatch
) -> None:
    saved_study(tmp_path)
    evidence = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}

    def forbidden(*_args: object, **_kwargs: object) -> None:
        pytest.fail("a report must never execute a backtest")

    monkeypatch.setattr(StrategyRunner, "run", forbidden)
    SCRIPT.report(
        tmp_path,
        r1_output=tmp_path / "missing_round_one",
        r2_output=tmp_path / "missing_round_two",
    )
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
        assert relative["Nasdaq_buy_hold"].eq(1.0).all()
    text = (tmp_path / "study.md").read_text()
    assert "prototype" in text and "| top_k | 1 |" in text
    assert "30 essais correles" in text
    assert "aucune de ces periodes n'est un echantillon\nvierge" in text
    assert "Reason for candidate 21" in text and "Reason for candidate 22" in text
    assert "Nasdaq conserve" in text and "50/50 initial" in text
    assert "61153" in text and "Jours d'ordres/an" in text
    assert (tmp_path / "final/uncertainty.json").is_file()
    assert (tmp_path / "reported_iterations.csv").is_file()


def test_comparison_refuses_a_missing_session_without_filling(tmp_path) -> None:
    selected = saved_study(tmp_path)
    folder = tmp_path / "references/final/SP500_buy_hold"
    equity = SCRIPT.load_equity(folder / "equity.csv").iloc[:-1]
    equity.to_csv(folder / "equity.csv")
    with pytest.raises(ValueError, match="comparison dates differ"):
        SCRIPT.render_comparison(tmp_path, "final", 22, selected["parameters"])


def test_selection_excess_and_verdict_compare_nasdaq_even_when_sp500_is_beaten(tmp_path) -> None:
    saved_study(tmp_path)
    rows = SCRIPT.trial_rows(tmp_path)
    references = SCRIPT.read_json(tmp_path / "references/development/Nasdaq_buy_hold/metrics.json")
    assert rows[1]["development_excess_cagr"] == pytest.approx(
        rows[1]["development_cagr"] - references["cagr"]
    )
    SCRIPT.report(tmp_path, r1_output=tmp_path / "missing_one", r2_output=tmp_path / "missing_two")
    verdict = SCRIPT.read_json(tmp_path / "verdict.json")
    assert verdict["status"] == "NOT_SUPPORTED"
    assert verdict["benchmark"] == "Nasdaq_buy_hold"
    final = pd.read_csv(tmp_path / "comparison/final/summary.csv", index_col="book")
    assert final.loc[SCRIPT.BOOK, "net_return"] > final.loc["SP500_buy_hold", "net_return"]
    assert final.loc[SCRIPT.BOOK, "net_return"] < final.loc["Nasdaq_buy_hold", "net_return"]
    assert "alpha_vs_nasdaq" in final.columns
    assert "alpha_vs_sp500" not in final.columns


@pytest.mark.parametrize("guard", ["momentum", "trend"])
@pytest.mark.parametrize("relative", [False, True])
def test_retained_rule_describes_saved_modes_and_names_without_old_winner(guard, relative) -> None:
    parameters = policy_parameters()
    parameters.update(
        guard_mode=guard,
        trend_sessions=200 if guard == "trend" else 0,
        relative_rotation=relative,
        defensive_ids=["ETF_EURO_GOV"],
        defensive_lookbacks=[42],
        defensive_weights=[2.0],
        fast_lookback=7,
        slow_lookback=84,
        core_floor=0.25,
    )
    text = SCRIPT.retained_rule(parameters)
    assert "7 seances" in text and "25.00 %" in text
    assert "obligations souveraines EUR" in text
    assert "Xetra-Gold" not in text and "S&P 500" not in text
    assert "log(P_t / P_(t-42))" in text
    assert ("rotation relative est aussi active" in text) == relative
    assert ("moyenne mobile sur 200 seances" in text) == (guard == "trend")
    assert ("rendement de Nasdaq 100 sur 84 seances" in text) == (guard == "momentum")


def test_incomplete_saved_policy_does_not_substitute_live_defaults() -> None:
    text = SCRIPT.retained_rule({"core_id": "ETF_NASDAQ"})
    assert "ne contient pas tous les champs" in text
    assert "100 %" not in text


def test_report_manifest_tracks_source_selection_and_preserves_financial_archive(tmp_path) -> None:
    saved_study(tmp_path)
    archive = tmp_path / "source/source.zip"
    archive.parent.mkdir()
    archive.write_bytes(b"original-financial-archive")
    validation = tmp_path / "validation.md"
    validation.write_text(
        "# Verification\n\n## R\u00e9sultat \u00e9conomique\n\n"
        "Le detour defensif manque le rebond verifie dans le journal.\n",
        encoding="utf-8",
    )
    SCRIPT.report(tmp_path, r1_output=tmp_path / "missing_one", r2_output=tmp_path / "missing_two")
    manifest = SCRIPT.read_json(tmp_path / "reporting_manifest.json")
    assert archive.read_bytes() == b"original-financial-archive"
    assert (
        manifest["financial_source_archive_sha256"]
        == hashlib.sha256(archive.read_bytes()).hexdigest()
    )
    assert (
        manifest["report_source_sha256"]
        == hashlib.sha256(Path(SCRIPT.__file__).read_bytes()).hexdigest()
    )
    assert (
        manifest["study_sha256"] == hashlib.sha256((tmp_path / "study.md").read_bytes()).hexdigest()
    )
    text = (tmp_path / "study.md").read_text(encoding="utf-8")
    assert "\u2014" in text
    assert " ? " not in text
    assert "or (ETC Xetra-Gold)" in text
    assert "ETF_GOLD" in text
    assert "trial_%02d.json" in text and "$(seq 21 30)" in text
    assert "report_gpt61_round2.py" not in text
    assert "Le detour defensif manque le rebond verifie dans le journal." in text
    assert manifest["validation_note_sha256"] == hashlib.sha256(validation.read_bytes()).hexdigest()


@pytest.mark.parametrize("number", [1, 20, 31, True])
def test_frozen_selection_refuses_trial_outside_third_round(tmp_path, number) -> None:
    saved = saved_study(tmp_path)
    saved["candidate"]["number"] = number
    write_json(tmp_path / "selected.json", saved)
    with pytest.raises(ValueError, match="21 to 30"):
        SCRIPT.frozen_selection(tmp_path)
