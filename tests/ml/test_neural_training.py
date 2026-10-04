"""Calibrating a model: what is trained, what is selected, and what cannot leak into it."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("torch")

from quant_backtester.backtest.runner import StrategyRunner
from quant_backtester.data.calendars import CalendarRegistry
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.ml.artifacts import ArtifactError, NeuralArtifact
from quant_backtester.ml.config import NeuralStrategyConfig
from quant_backtester.ml.training import (
    TRAINING_METRICS_FILE,
    VALIDATION_METRICS_FILE,
    Calibration,
    calibrate_neural_strategy,
    proportional_cost_rate,
    validation_score,
)
from quant_backtester.strategies.ml.neural_allocation import (
    InformationCutoffError,
    NeuralAllocationStrategy,
)

pytestmark = pytest.mark.slow

TEST_START, TEST_END = date(2026, 9, 1), date(2026, 10, 30)

Calibrate = Callable[..., Calibration]


@pytest.fixture
def calibrate(
    neural_config: NeuralStrategyConfig,
    calendars: CalendarRegistry,
    make_neural_runner: Callable[..., StrategyRunner],
    tmp_path: Path,
) -> Calibrate:
    """Return a calibration of the small model on a given store."""

    def run(reader: MarketDataReader, name: str = "artifact", **changes: object) -> Calibration:
        config = NeuralStrategyConfig.from_definition(neural_config.definition() | changes)
        return calibrate_neural_strategy(
            config,
            reader=reader,
            calendars=calendars,
            validation_runner=make_neural_runner(reader),
            output_dir=tmp_path / name,
        )

    return run


def test_a_calibration_keeps_one_artifact_and_says_how_it_got_there(
    calibrate: Calibrate, neural_market: MarketDataReader, tmp_path: Path, xpar
) -> None:
    calibration = calibrate(neural_market)
    artifact = calibration.artifact
    folder = tmp_path / "artifact"

    assert sorted(path.name for path in folder.iterdir()) == [
        "manifest.json",
        "scaler.npz",
        TRAINING_METRICS_FILE,
        VALIDATION_METRICS_FILE,
        "weights.pt",
    ]
    # One update per pass, a validation every second epoch, in the engine.
    assert list(calibration.training_metrics["epoch"]) == list(
        range(1, len(calibration.training_metrics) + 1)
    )
    assert (
        list(calibration.validation_metrics["epoch"])
        == [2, 4, 6][: len(calibration.validation_metrics)]
    )
    assert list(calibration.validation_metrics["selected"]).count(True) == 1
    selected = calibration.validation_metrics.loc[calibration.validation_metrics["selected"]]
    assert list(selected["epoch"]) == [artifact.selected_epoch]
    assert list(selected["score"]) == [artifact.provenance["validation_score"]]
    # The selection read the validation period: the model's information stops
    # at its last decision, not at the end of the training part.
    last_validation = xpar.sessions(date(2026, 7, 1), date(2026, 8, 31))[-1].session_date
    paris_time = artifact.information_cutoff.astimezone(ZoneInfo("Europe/Paris"))
    assert (paris_time.date(), paris_time.hour) == (last_validation, 23)
    assert NeuralArtifact.load(folder).model_id == artifact.model_id


def test_the_earliest_candidate_wins_a_tie_and_training_stops_without_improvement(
    calibrate: Calibrate, neural_market: MarketDataReader
) -> None:
    # No improvement can count: every candidate after the first is a tie at best.
    calibration = calibrate(
        neural_market,
        minimum_improvement=1e9,
        patience=2,
        max_epochs=20,
        validation_every=2,
    )

    assert calibration.artifact.selected_epoch == 2
    assert list(calibration.validation_metrics["epoch"]) == [2, 4, 6]
    assert len(calibration.training_metrics) == 6


def test_the_same_seed_gives_the_same_model_and_another_seed_another(
    calibrate: Calibrate, neural_market: MarketDataReader
) -> None:
    first = calibrate(neural_market, "a").artifact
    again = calibrate(neural_market, "b").artifact
    other = calibrate(neural_market, "c", seed=43).artifact

    assert again.model_id == first.model_id
    assert other.model_id != first.model_id


def test_data_after_the_calibration_changes_nothing_in_the_model(
    calibrate: Calibrate,
    neural_market: MarketDataReader,
    make_neural_market: Callable[..., MarketDataReader],
    neural_config: NeuralStrategyConfig,
) -> None:
    """The look-ahead guard of the whole calibration: the test period is never read."""

    def crash_after_calibration(bars, levels) -> None:
        for prices in bars.values():
            for day in prices:
                if day > neural_config.calibration_end:
                    prices[day] = tuple(value * 0.5 for value in prices[day])
        for day in levels:
            if day > neural_config.calibration_end:
                levels[day] = 80.0

    changed = make_neural_market("changed", mutate=crash_after_calibration)

    original = calibrate(neural_market, "original")
    other = calibrate(changed, "other")

    assert other.artifact.model_id == original.artifact.model_id
    assert np.array_equal(other.artifact.scaler.mean, original.artifact.scaler.mean)
    pd.testing.assert_frame_equal(other.validation_metrics, original.validation_metrics)


def test_a_folder_holding_another_model_is_not_written_over(
    calibrate: Calibrate, neural_market: MarketDataReader
) -> None:
    calibrate(neural_market, "shared")

    with pytest.raises(ArtifactError, match="already holds"):
        calibrate(neural_market, "shared", seed=43)


def test_the_validation_runner_must_read_the_store_the_model_is_trained_on(
    neural_config: NeuralStrategyConfig,
    neural_market: MarketDataReader,
    make_neural_market: Callable[..., MarketDataReader],
    make_neural_runner: Callable[..., StrategyRunner],
    calendars: CalendarRegistry,
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="must read the store"):
        calibrate_neural_strategy(
            neural_config,
            reader=neural_market,
            calendars=calendars,
            validation_runner=make_neural_runner(make_neural_market("elsewhere")),
            output_dir=tmp_path / "artifact",
        )


def test_the_reloaded_model_decides_as_the_calibrated_one_and_only_after_its_cutoff(
    calibrate: Calibrate,
    neural_market: MarketDataReader,
    make_neural_runner: Callable[..., StrategyRunner],
    tmp_path: Path,
) -> None:
    artifact = calibrate(neural_market).artifact
    reloaded = NeuralArtifact.load(tmp_path / "artifact", expected=artifact.config)
    runner = make_neural_runner(neural_market)

    first = runner.run(
        NeuralAllocationStrategy.from_artifact(artifact),
        artifact.config.tradable_ids,
        TEST_START,
        TEST_END,
    )
    second = runner.run(
        NeuralAllocationStrategy.from_artifact(reloaded),
        reloaded.config.tradable_ids,
        TEST_START,
        TEST_END,
    )

    assert second.fingerprint == first.fingerprint
    pd.testing.assert_series_equal(second.equity(), first.equity())
    pd.testing.assert_frame_equal(second.fills(), first.fills())
    # A run reaching back into the validation period would test the model on
    # the very sessions that selected it.
    with pytest.raises(InformationCutoffError):
        runner.run(
            NeuralAllocationStrategy.from_artifact(artifact),
            artifact.config.tradable_ids,
            date(2026, 8, 24),
            TEST_END,
        )


def test_the_score_is_the_risk_adjusted_mean_of_the_engines_net_returns(
    calibrate: Calibrate,
    neural_market: MarketDataReader,
    make_neural_runner: Callable[..., StrategyRunner],
) -> None:
    artifact = calibrate(neural_market).artifact
    runner = make_neural_runner(neural_market)
    result = runner.run(
        NeuralAllocationStrategy.from_artifact(artifact),
        artifact.config.tradable_ids,
        TEST_START,
        TEST_END,
    )
    returns = result.equity().pct_change().dropna().to_numpy()

    expected = 252 * returns.mean() - 2.5 * 252 * returns.var(ddof=1)

    assert validation_score(result, artifact.config) == pytest.approx(expected)
    assert proportional_cost_rate(runner) == pytest.approx(0.001)


def test_outputs_declared_out_of_the_engines_canonical_order_still_run(
    calibrate: Calibrate,
    neural_market: MarketDataReader,
    make_neural_runner: Callable[..., StrategyRunner],
) -> None:
    """The engine asks its signals in sorted order; the outputs keep the declared one."""
    artifact = calibrate(neural_market, tradable_ids=["ETF_OTHER", "ETF_EU"]).artifact
    strategy = NeuralAllocationStrategy.from_artifact(artifact)

    result = make_neural_runner(neural_market).run(
        strategy, artifact.config.tradable_ids, TEST_START, TEST_END
    )

    assert artifact.config.tradable_ids == ("ETF_OTHER", "ETF_EU")
    assert len(result.fills()) > 0
