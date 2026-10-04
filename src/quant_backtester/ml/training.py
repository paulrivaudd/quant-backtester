"""Calibrating a neural allocation: train on one period, select on the next, freeze.

The order is the whole point. The data is extracted while the store is held;
the normalisation is fitted on the valid training inputs only; the network is
trained on the purged training sequence, in time order, one update per pass;
every few epochs the current network is frozen and run by the real engine over
the validation period, with the real costs, lots and decision rule; the best
of those runs is kept, the earliest on a tie. Nothing is refitted on training
plus validation afterwards: that would be another model than the one scored.

What comes out carries the instant its information stops at. The candidates
run during the validation know the training period only; the selected one
knows the validation too, since the validation chose it, and its cutoff is the
decision instant of ``calibration_end``.

A seed makes a calibration repeatable on one machine and one set of library
versions. It does not make it identical across versions or hardware, which is
why the versions are recorded with the artifact.
"""

from __future__ import annotations

import platform
import random
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from numpy.typing import NDArray

from quant_backtester.backtest.runner import StrategyResult, StrategyRunner
from quant_backtester.data.calendars import CalendarRegistry
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.ml.artifacts import NeuralArtifact
from quant_backtester.ml.config import NeuralStrategyConfig
from quant_backtester.ml.dataset import NeuralDataset, build_training_dataset
from quant_backtester.ml.features import FeatureScaler
from quant_backtester.ml.network import (
    NeuralAllocator,
    capped_fund_weights,
    proxy_returns,
    risk_adjusted_objective,
)
from quant_backtester.strategies.ml.neural_allocation import NeuralAllocationStrategy

TRAINING_METRICS_FILE = "training_metrics.csv"
VALIDATION_METRICS_FILE = "validation_metrics.csv"


class StoreChangedDuringCalibration(RuntimeError):
    """Raised when a validation run read another state of the store than the training set."""


@dataclass(frozen=True, eq=False)
class Calibration:
    """A finished calibration: the selected model and how it was reached.

    Attributes
    ----------
    artifact : NeuralArtifact
        The selected model, its information cutoff at ``calibration_end``.
    training_metrics : pandas.DataFrame
        One row per epoch: the loss, the proxy objective and its parts, the
        mean cash weight and the data quality of the training set.
    validation_metrics : pandas.DataFrame
        One row per validation run in the engine: its score, its net return
        and whether it is the one selected.
    dataset : NeuralDataset
        The training sequence, with what was purged and what was invalid.
    """

    artifact: NeuralArtifact
    training_metrics: pd.DataFrame
    validation_metrics: pd.DataFrame
    dataset: NeuralDataset


def seed_everything(seed: int) -> None:
    """Seed the Python, NumPy and PyTorch generators a training draws from.

    Parameters
    ----------
    seed : int
        The seed of the configuration.

    Notes
    -----
    The one place this project sets a global generator: PyTorch initialises
    its layers and draws its dropout masks from its own, and a training that
    left it unseeded would not be repeatable at all.
    """
    random.seed(seed)
    np.random.seed(seed)  # noqa: NPY002 - the legacy global is what a library may draw from
    torch.manual_seed(seed)


def validation_score(result: StrategyResult, config: NeuralStrategyConfig) -> float:
    """Return ``A*mean(R) - gamma/2 * A*var(R, ddof=1)`` of a run's net session returns.

    Parameters
    ----------
    result : StrategyResult
        A validation run in the engine.
    config : NeuralStrategyConfig
        Gives ``gamma`` and the annualisation ``A``.

    Returns
    -------
    float
        The score a candidate is selected on, from the net equity the engine
        produced: costs, lots and rejected orders included.
    """
    equity = result.equity().to_numpy(dtype=np.float64)
    returns = torch.from_numpy(equity[1:] / equity[:-1] - 1.0)
    return risk_adjusted_objective(returns, config.risk_aversion, config.annualization).item()


def proportional_cost_rate(runner: StrategyRunner) -> float:
    """Return the cost of one euro traded: commission, half-spread and slippage rates."""
    costs = runner.execution.costs
    return costs.commission_rate + costs.half_spread_rate + costs.slippage_rate


def calibrate_neural_strategy(
    config: NeuralStrategyConfig,
    *,
    reader: MarketDataReader,
    calendars: CalendarRegistry,
    validation_runner: StrategyRunner,
    output_dir: Path,
    provenance: Mapping[str, object] | None = None,
) -> Calibration:
    """Train a network on the training part, select it on the validation part, and keep it.

    Parameters
    ----------
    config : NeuralStrategyConfig
        The periods, the series, the architecture and the training parameters.
    reader : MarketDataReader
        The store. Held against writers while the training set is extracted.
    calendars : CalendarRegistry
        The venue calendars.
    validation_runner : StrategyRunner
        The runner of the final test: same currency, calendar, timetable,
        execution model and starting cash. Each candidate is run with it over
        the validation period.
    output_dir : Path
        The folder the artifact and the two metric files are written to.
    provenance : Mapping[str, object] | None
        What the caller knows of the code's state, recorded with the artifact.

    Returns
    -------
    Calibration
        The selected artifact, saved, and the metrics of the calibration.

    Raises
    ------
    InsufficientCalibrationData
        If the periods do not hold enough valid data.
    MissingForwardOpen
        If an open needed by a label is absent.
    StoreChangedDuringCalibration
        If a validation run read another state of the store than the training
        set was extracted from.
    ArtifactError
        If ``output_dir`` already holds another model.
    ValueError
        If the runner does not read the given store.

    Notes
    -----
    The objective of the training is an approximation and is reported as one.
    The validation score is not: it is computed on the engine's net returns.
    No number of the test period is read here.
    """
    if validation_runner.reader is not reader:
        raise ValueError("the validation runner must read the store the model is trained on")
    timetable = validation_runner.timetable
    with reader.pinned() as state:
        dataset = build_training_dataset(config, reader, calendars, timetable)
    scaler = FeatureScaler.fit(dataset.inputs[dataset.valid], config.clip)
    scaled_valid, clipped = scaler.transform(dataset.inputs[dataset.valid])
    clipped_share = clipped / scaled_valid.size
    scaled = np.zeros_like(dataset.inputs)
    scaled[dataset.valid] = scaled_valid
    inputs = torch.from_numpy(scaled)
    valid = torch.from_numpy(dataset.valid.astype(np.float64)).unsqueeze(1)
    forward = torch.from_numpy(dataset.forward_returns)
    cost_rate = proportional_cost_rate(validation_runner)
    training_cutoff = timetable.decision_instant(dataset.decisions[-1])
    run_provenance = {
        **dict(provenance or {}),
        "python": platform.python_version(),
        "torch": torch.__version__,
        "numpy": np.__version__,
        "device": "cpu",
        "data_state": state.digest,
        "cost_rate": cost_rate,
        "training_decisions": len(dataset.decisions),
        "valid_training_decisions": int(dataset.valid.sum()),
        "purged_decisions": [day.isoformat() for day in dataset.purged],
        "clipped_training_share": clipped_share,
    }

    seed_everything(config.seed)
    model = NeuralAllocator(config)
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=config.learning_rate, weight_decay=config.weight_decay
    )
    training_rows: list[dict[str, object]] = []
    validation_rows: list[dict[str, object]] = []
    best: tuple[float, int, dict[str, NDArray[np.float64]]] | None = None
    stale = 0
    for epoch in range(1, config.max_epochs + 1):
        model.train()
        optimizer.zero_grad()
        # An invalid day stays in the sequence, forced to cash whatever the
        # network says, so that its transitions are still paid for.
        funds = capped_fund_weights(model(inputs), config.max_asset_weight) * valid
        returns = proxy_returns(funds, forward, cost_rate)
        objective = risk_adjusted_objective(returns, config.risk_aversion, config.annualization)
        (-objective).backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), config.gradient_clip_norm)
        optimizer.step()
        earned, held = returns.detach(), funds.detach()
        training_rows.append(
            {
                "epoch": epoch,
                "loss": -objective.item(),
                "proxy_objective": objective.item(),
                "proxy_annualised_mean": config.annualization * earned.mean().item(),
                "proxy_annualised_variance": config.annualization * earned.var().item(),
                "mean_cash_weight": 1.0 - held.sum(dim=1).mean().item(),
                "valid_share": dataset.valid_share,
                "clipped_share": clipped_share,
            }
        )
        if epoch % config.validation_every != 0 and epoch != config.max_epochs:
            continue
        parameters = _snapshot(model)
        candidate = NeuralArtifact(
            config, parameters, scaler, training_cutoff, epoch, run_provenance
        )
        result = validation_runner.run(
            NeuralAllocationStrategy.from_artifact(candidate),
            config.tradable_ids,
            config.validation_start,
            config.calibration_end,
        )
        if result.data_state.digest != state.digest:
            raise StoreChangedDuringCalibration(
                "the store changed between the extraction of the training set and a "
                "validation run; calibrate again on one state of the data"
            )
        score = validation_score(result, config)
        improved = best is None or score > best[0] + config.minimum_improvement
        validation_rows.append(
            {
                "epoch": epoch,
                "score": score,
                "net_return": result.backtest.net_return,
                "total_cost": result.backtest.total_cost,
                "sessions": len(result.records()),
                "improved": improved,
            }
        )
        if improved:
            best, stale = (score, epoch, parameters), 0
        else:
            stale += 1
            if stale >= config.patience:
                break

    assert best is not None  # max_epochs >= 1 always ends on a validation
    score, selected_epoch, parameters = best
    artifact = NeuralArtifact(
        config=config,
        state=parameters,
        scaler=scaler,
        information_cutoff=_selection_cutoff(config, validation_runner),
        selected_epoch=selected_epoch,
        provenance={**run_provenance, "validation_score": score},
    )
    artifact.save(output_dir)
    training_metrics = pd.DataFrame(training_rows)
    validation_metrics = pd.DataFrame(validation_rows)
    validation_metrics["selected"] = validation_metrics["epoch"] == selected_epoch
    training_metrics.to_csv(output_dir / TRAINING_METRICS_FILE, index=False)
    validation_metrics.to_csv(output_dir / VALIDATION_METRICS_FILE, index=False)
    return Calibration(artifact, training_metrics, validation_metrics, dataset)


def _snapshot(model: NeuralAllocator) -> dict[str, NDArray[np.float64]]:
    """Return a copy of a network's parameters, detached from its training."""
    return {
        name: values.detach().cpu().numpy().copy() for name, values in model.state_dict().items()
    }


def _selection_cutoff(config: NeuralStrategyConfig, runner: StrategyRunner) -> datetime:
    """Return the decision instant of the last validation session actually run."""
    calendar = runner.calendars.get(runner.reference_calendar_id)
    last = calendar.sessions(config.validation_start, config.calibration_end)[-1].session_date
    return runner.timetable.decision_instant(last)
