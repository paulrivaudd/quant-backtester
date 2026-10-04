"""The configuration of a model: its layout, its record and what it refuses."""

from __future__ import annotations

from datetime import date

import pytest

from quant_backtester.ml.config import NeuralStrategyConfig


def changed(config: NeuralStrategyConfig, **changes: object) -> NeuralStrategyConfig:
    """Return a configuration with some fields replaced, validated again."""
    return NeuralStrategyConfig.from_definition(config.definition() | changes)


def test_the_layout_is_one_block_a_series_and_the_level(neural_config) -> None:
    names = neural_config.feature_names()

    # 6 observations, 3 trends, 2 volatilities and the age: 12 a series.
    assert neural_config.indicator_count == 6
    assert neural_config.block_size == 12
    assert neural_config.input_size == 3 * 12 + 1 == len(names)
    assert names[:12] == (
        *(f"ETF_EU.history_{index}" for index in range(6)),
        "ETF_EU.trend_2",
        "ETF_EU.trend_3",
        "ETF_EU.trend_6",
        "ETF_EU.vol_2",
        "ETF_EU.vol_4",
        "ETF_EU.age_sessions",
    )
    assert names[-1] == "RATE_US.level"


def test_the_specified_model_reads_106_numbers_a_series() -> None:
    config = NeuralStrategyConfig(
        calibration_start="2019-01-02",  # type: ignore[arg-type]
        validation_start="2024-01-02",  # type: ignore[arg-type]
        calibration_end="2024-12-31",  # type: ignore[arg-type]
        feature_ids=("ETF_WORLD", "ETF_SP500_PEA", "VIX"),
        tradable_ids=("ETF_WORLD", "ETF_SP500_PEA"),
        history_sessions=100,
        ma_windows=(20, 50, 100),
        vol_windows=(20, 60),
        max_asset_weight=1.0,
        min_asset_weight=0.01,
        rebalance_band=0.03,
        risk_aversion=5.0,
        seed=42,
    )

    assert config.block_size == 106
    assert config.input_size == 3 * 106 + 1
    assert config.calibration_start == date(2019, 1, 2)


def test_a_definition_is_plain_and_reads_back_to_the_same_configuration(neural_config) -> None:
    definition = neural_config.definition()

    assert definition["calibration_start"] == "2026-01-12"
    assert definition["tradable_ids"] == ["ETF_EU", "ETF_OTHER"]
    assert NeuralStrategyConfig.from_definition(definition) == neural_config
    with pytest.raises(ValueError, match="missing"):
        NeuralStrategyConfig.from_definition({"seed": 42})


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"validation_start": "2026-01-12"}, "calibration_start < validation_start"),
        ({"calibration_end": "2026-06-30"}, "validation_start <= calibration_end"),
        ({"tradable_ids": ["ETF_EU", "ETF_LATE"]}, "tradable and not observed"),
        ({"tradable_ids": ["ETF_EU", "ETF_EU"]}, "more than once"),
        ({"tradable_ids": []}, "at least one"),
        ({"level_id": "VIX"}, "must be in feature_ids"),
        ({"tradable_ids": ["ETF_EU", "RATE_US"]}, "not a fund to buy"),
        ({"ma_windows": [2, 7]}, "between 2 and 6"),
        ({"vol_windows": [6]}, "between 2 and 5"),
        ({"vol_windows": []}, "at least one window"),
        ({"max_asset_weight": 0.0}, "max_asset_weight"),
        ({"max_asset_weight": 1.5}, "max_asset_weight"),
        ({"rebalance_band": -0.1}, "rebalance_band"),
        ({"dropout": 1.0}, "dropout"),
        ({"learning_rate": 0.0}, "learning_rate"),
        ({"max_epochs": 0}, "max_epochs"),
        ({"seed": -1}, "seed"),
        ({"calibration_start": "January"}, "ISO date"),
    ],
)
def test_a_configuration_that_cannot_be_calibrated_is_refused(
    neural_config, changes, message
) -> None:
    with pytest.raises(ValueError, match=message):
        changed(neural_config, **changes)
