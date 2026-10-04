"""The ML1 script: its configuration, its preparation step and its decision export."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path
from types import ModuleType

import pandas as pd
import pytest

pytest.importorskip("torch")

from quant_backtester.backtest.runner import StrategyRunner
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.ml.artifacts import ArtifactError
from quant_backtester.ml.config import NeuralStrategyConfig
from quant_backtester.strategies.ml.neural_allocation import (
    InformationCutoffError,
    NeuralAllocationStrategy,
)

REPOSITORY = Path(__file__).resolve().parents[2]
TEST_START, TEST_END = date(2026, 9, 1), date(2026, 12, 18)


def load_script() -> ModuleType:
    """Import ``scripts/run_neural_strategy.py`` by its path."""
    path = REPOSITORY / "scripts" / "run_neural_strategy.py"
    spec = importlib.util.spec_from_file_location("run_neural_strategy", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SCRIPT = load_script()


def test_the_configuration_is_the_one_of_the_specification() -> None:
    config = SCRIPT.neural_config()

    assert config.feature_ids == ("ETF_WORLD", "ETF_SP500_PEA", "VIX")
    assert config.tradable_ids == ("ETF_WORLD", "ETF_SP500_PEA")
    assert (config.calibration_start, config.validation_start, config.calibration_end) == (
        date(2019, 1, 2),
        date(2024, 1, 2),
        date(2024, 12, 31),
    )
    assert (config.history_sessions, config.ma_windows, config.vol_windows) == (
        100,
        (20, 50, 100),
        (20, 60),
    )
    assert (config.max_asset_weight, config.min_asset_weight, config.rebalance_band) == (
        1.0,
        0.01,
        0.03,
    )
    assert (config.risk_aversion, config.seed, SCRIPT.neural_config(44).seed) == (5.0, 42, 44)
    assert (config.learning_rate, config.weight_decay, config.max_epochs) == (1e-3, 1e-3, 100)
    assert (config.minimum_training_decisions, config.minimum_validation_sessions) == (1000, 252)
    assert config.calibration_end < SCRIPT.TEST_PERIOD[0] <= SCRIPT.TEST_PERIOD[1]


def test_the_costs_are_the_opening_assumption_and_double_as_a_whole() -> None:
    costs = SCRIPT.execution_model().costs
    doubled = SCRIPT.execution_model(2.0).costs

    assert (costs.commission_rate, costs.minimum_commission) == (0.0005, 1.0)
    assert (costs.half_spread_rate, costs.slippage_rate) == (0.0003, 0.0002)
    assert (doubled.commission_rate, doubled.minimum_commission) == (0.001, 2.0)
    assert (doubled.half_spread_rate, doubled.slippage_rate) == (0.0006, 0.0004)
    assert SCRIPT.ANALYTICS.sessions_per_year == 252
    assert SCRIPT.INITIAL_CASH == 100_000.0


def test_the_books_are_named_by_the_catalogue() -> None:
    assert SCRIPT.ML1 == "ML1 - neural allocation"
    assert list(SCRIPT.references()) == ["SA1 - std MA20", "buy & hold World", "equal weight"]
    for strategy in SCRIPT.references().values():
        strategy.validate()


@pytest.mark.slow
def test_a_model_is_calibrated_once_then_loaded_and_exported_decision_by_decision(
    neural_config: NeuralStrategyConfig,
    neural_market: MarketDataReader,
    make_neural_runner: Callable[..., StrategyRunner],
    tmp_path: Path,
) -> None:
    runner = make_neural_runner(neural_market)
    folder = tmp_path / "artifact"

    calibrated = SCRIPT.prepare(neural_config, runner, folder)
    loaded = SCRIPT.prepare(neural_config, runner, folder)
    other = NeuralStrategyConfig.from_definition(neural_config.definition() | {"seed": 43})

    assert loaded.model_id == calibrated.model_id
    assert "source" in loaded.provenance
    with pytest.raises(ArtifactError, match="another configuration"):
        SCRIPT.prepare(other, runner, folder)

    strategy = NeuralAllocationStrategy.from_artifact(loaded)
    SCRIPT.validate_test_period(strategy, runner, TEST_START, TEST_END)
    with pytest.raises(InformationCutoffError):
        SCRIPT.validate_test_period(strategy, runner, date(2026, 8, 3), TEST_END)

    result = runner.run(strategy, neural_config.tradable_ids, TEST_START, TEST_END)
    decisions = SCRIPT.neural_decisions(result, strategy)
    row = SCRIPT.summary_row(result, result.equity(), 0)
    scored = SCRIPT.summary_row(result, result.equity(), 0, result.equity())

    assert len(decisions) == len(result.records())
    assert set(decisions["model_id"]) == {loaded.model_id}
    assert set(decisions["action"]) <= {"WEIGHTS", "CASH", "HOLD"}
    assert decisions["action"].iloc[0] == "WEIGHTS"  # from cash, the first target is bought
    # The reason recomputed from the recorded book agrees with the recorded action.
    agrees = {"INSIDE_BAND": "HOLD", "OUTSIDE_BAND": "WEIGHTS", "FULL_EXIT": "WEIGHTS"}
    assert all(
        agrees.get(reason, action) == action
        for reason, action in zip(decisions["reason"], decisions["action"], strict=True)
    )
    proposed = decisions[["proposed_ETF_EU", "proposed_ETF_OTHER", "proposed_cash"]].sum(axis=1)
    assert proposed.tolist() == pytest.approx([1.0] * len(decisions))
    # A book measured against itself: beta one, alpha zero.
    assert row["beta_vs_sa1"] == pytest.approx(1.0)
    assert row["alpha_vs_sa1"] == pytest.approx(0.0, abs=1e-9)
    assert row["cash_share"] == pytest.approx(1.0 - row["average_exposure"])
    assert row["missing_data_decisions"] == 0.0
    # 77 sessions are under the year the score asks for: not scored, and said so.
    assert row["quality"] is None and scored["quality"] is None

    written = SCRIPT.save_outputs(
        tmp_path / "out",
        pd.DataFrame.from_dict({SCRIPT.ML1: row}, orient="index"),
        {SCRIPT.ML1: result},
        decisions,
    )
    assert sorted(path.name for path in written) == [
        "equity.csv",
        "fills.csv",
        "neural_decisions.csv",
        "rejects.csv",
        "summary.csv",
        "weights.csv",
    ]
