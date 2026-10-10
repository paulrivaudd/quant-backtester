"""The monthly calibration of a signature model: blocks, purge, fit, frozen artifact.

At a month's end ``c`` the model of the next month is fitted on what was known
at the evening of ``c``:

1. the last ``validation_candidate_origins`` sessions ending at ``c`` are the
   candidate validation block, the ``training_candidate_origins`` before them
   the candidate training block;
2. a training origin whose label ends at or after the first validation session
   is purged, and so is a validation origin whose label is not known at ``c``:
   a label runs from the open after its origin to the open after that, so two
   origins go at each boundary when no session is missing - but it is the
   calendar and the label's own dates that decide, not a count of rows;
3. the features of every origin are those built *at that origin's own
   instant*, never recomputed with the reader of ``c``;
4. the normalisation and the weights are fitted on the training block alone;
   the validation block chooses the epoch and nothing else; the model is not
   refitted on both;
5. the artifact is frozen with its information cutoff and its availability.

A month whose blocks do not hold enough valid examples gets no model and says
why. A loss that is not finite stops the calibration: a broken fit is never
replaced by a forecast.

The fit of the additive network needs PyTorch (the ``ml`` extra); it runs on
the CPU, in ``float64``, on one thread, from a seed set again at every
calibration.
"""

from __future__ import annotations

import importlib.metadata
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime

import numpy as np
import torch
from numpy.typing import NDArray
from torch import nn

from quant_backtester.backtest.timetable import BacktestTimetable
from quant_backtester.data.calendars import CalendarRegistry, TradingCalendar
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.ml.dataset import ForwardOpenReturnBuilder, purge
from quant_backtester.ml.features import FeatureScaler
from quant_backtester.ml.signatures.artifacts import ScheduleEntry, SignatureArtifact
from quant_backtester.ml.signatures.config import (
    ModelKind,
    SignatureModelConfig,
    SignatureTrainingConfig,
    SignatureVariant,
)
from quant_backtester.ml.signatures.models import (
    AdditiveWeights,
    Weights,
    fit_ridge,
    internal_contributions,
)
from quant_backtester.ml.training import seed_everything
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.signatures.logsignature import (
    BACKEND,
    FeatureKind,
    SignatureFeatureBuilder,
    SignatureFeatures,
)
from quant_backtester.signals.types import SignalStatus

Vector = NDArray[np.float64]


class SignatureAdditiveRegressor(nn.Module):
    """One small network per feature, each centred at zero, summed with a bias.

    Parameters
    ----------
    n_features : int
        Normalised features read.
    width : int
        Hidden units of each feature's network.

    Notes
    -----
    Each part is ``Linear(1, width)``, ``Tanh``, ``Linear(width, 1,
    bias=False)``; its output at zero is subtracted, so that a feature at its
    reference contributes nothing. ``3 * width`` parameters per feature and
    one bias: 157 for 13 features of 4 units. The output is in the internal
    unit of the fit, the percentage point.
    """

    def __init__(self, n_features: int, width: int) -> None:
        super().__init__()
        self.parts = nn.ModuleList(
            [
                nn.Sequential(nn.Linear(1, width), nn.Tanh(), nn.Linear(width, 1, bias=False))
                for _ in range(n_features)
            ]
        )
        self.bias = nn.Parameter(torch.zeros((), dtype=torch.float64))

    def contributions(self, inputs: torch.Tensor) -> torch.Tensor:
        """Return each feature's contribution, one column per feature."""
        if inputs.ndim != 2 or inputs.shape[1] != len(self.parts):
            raise ValueError(
                f"the model reads (n, {len(self.parts)}) features, got {tuple(inputs.shape)}"
            )
        columns = []
        for index, part in enumerate(self.parts):
            column = inputs[:, index : index + 1]
            columns.append(part(column) - part(torch.zeros_like(column)))
        return torch.cat(columns, dim=1)

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        """Return the forecast of each input, in the internal unit."""
        return self.bias + self.contributions(inputs).sum(dim=1)


def additive_weights(model: SignatureAdditiveRegressor) -> AdditiveWeights:
    """Return a network's weights as the plain arrays inference is written with."""
    hidden_weight, hidden_bias, output_weight = [], [], []
    for part in model.parts:
        first, last = part[0], part[2]  # type: ignore[index]
        hidden_weight.append(first.weight.detach().numpy().reshape(-1).copy())
        hidden_bias.append(first.bias.detach().numpy().reshape(-1).copy())
        output_weight.append(last.weight.detach().numpy().reshape(-1).copy())
    return AdditiveWeights(
        np.asarray(hidden_weight, dtype=np.float64),
        np.asarray(hidden_bias, dtype=np.float64),
        np.asarray(output_weight, dtype=np.float64),
        float(model.bias.detach()),
    )


def fit_additive(
    train_inputs: Vector,
    train_targets: Vector,
    validation_inputs: Vector,
    validation_targets: Vector,
    config: SignatureModelConfig,
) -> tuple[AdditiveWeights, list[dict[str, float]], int]:
    """Fit the additive network and return the weights of its best validation epoch.

    Parameters
    ----------
    train_inputs, validation_inputs : numpy.ndarray
        Normalised features, one per row.
    train_targets, validation_targets : numpy.ndarray
        Targets in the internal unit: the return times the target's scale.
    config : SignatureModelConfig
        The network and its optimiser.

    Returns
    -------
    tuple[AdditiveWeights, list[dict[str, float]], int]
        The weights of the selected epoch, the losses of every epoch run -
        the training loss of its forward pass and the validation loss after
        its step - and the epoch selected, from 1.

    Raises
    ------
    FloatingPointError
        If a loss is not finite: the calibration stops.

    Notes
    -----
    Full batch, ``MSELoss``, ``AdamW``, the gradient clipped. An epoch is
    kept when its validation loss is below the best so far by more than
    ``minimum_improvement``, so the first of two equal epochs wins; the fit
    stops after ``patience`` epochs without one. The epoch is chosen on the
    validation loss and never on a result in the engine.
    """
    seed_everything(config.seed)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    model = SignatureAdditiveRegressor(train_inputs.shape[1], config.hidden_units).double()
    optimiser = torch.optim.AdamW(
        model.parameters(), lr=config.learning_rate, weight_decay=config.weight_decay
    )
    loss_of = nn.MSELoss(reduction="mean")
    inputs, targets = torch.from_numpy(train_inputs), torch.from_numpy(train_targets)
    held_inputs = torch.from_numpy(validation_inputs)
    held_targets = torch.from_numpy(validation_targets)
    history: list[dict[str, float]] = []
    best: tuple[float, int, AdditiveWeights] | None = None
    stale = 0
    for epoch in range(1, config.max_epochs + 1):
        model.train()
        optimiser.zero_grad()
        loss = loss_of(model(inputs), targets)
        fitted = float(loss.detach())
        if not math.isfinite(fitted):
            raise FloatingPointError(f"the training loss is {fitted} at epoch {epoch}")
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), config.gradient_clip_norm)
        optimiser.step()
        model.eval()
        with torch.inference_mode():
            held = float(loss_of(model(held_inputs), held_targets))
        if not math.isfinite(held):
            raise FloatingPointError(f"the validation loss is {held} at epoch {epoch}")
        history.append({"epoch": float(epoch), "training_loss": fitted, "validation_loss": held})
        if best is None or held < best[0] - config.minimum_improvement:
            best, stale = (held, epoch, additive_weights(model)), 0
        else:
            stale += 1
            if stale >= config.patience:
                break
    assert best is not None
    return best[2], history, best[1]


@dataclass(frozen=True, slots=True)
class MonthBlocks:
    """The two purged blocks of one calibration.

    Attributes
    ----------
    training, validation : tuple[date, ...]
        The origins kept in each block after the purge.
    training_purged, validation_purged : tuple[date, ...]
        The origins purged at each boundary.
    complete : bool
        Whether the calendar handed in reached far enough back to cut both
        candidate blocks whole.
    """

    training: tuple[date, ...]
    validation: tuple[date, ...]
    training_purged: tuple[date, ...]
    validation_purged: tuple[date, ...]
    complete: bool


def month_blocks(
    sessions: Sequence[date],
    cutoff: date,
    calendar: TradingCalendar,
    training: SignatureTrainingConfig,
) -> MonthBlocks:
    """Cut and purge the blocks of the calibration whose information stops at ``cutoff``.

    Parameters
    ----------
    sessions : Sequence[date]
        The sessions of the calendar in order, the cutoff among them.
    cutoff : date
        The last session whose evening the calibration may read.
    calendar : TradingCalendar
        What dates the end of a label: a holiday is not an increment of a date.
    training : SignatureTrainingConfig
        The sizes of the two candidate blocks.

    Returns
    -------
    MonthBlocks
        The validation block is the last candidates ending at the cutoff, less
        those whose label ends after it; the training block the candidates
        before, less those whose label ends at or after the first validation
        session.

    Raises
    ------
    ValueError
        If the cutoff is not one of the sessions.
    """
    ordered = list(sessions)
    if cutoff not in ordered:
        raise ValueError(f"the cutoff {cutoff} is not one of the sessions")
    last = ordered.index(cutoff)
    first_validation = last - training.validation_candidate_origins + 1
    first_training = first_validation - training.training_candidate_origins
    validation_candidates = ordered[max(first_validation, 0) : last + 1]
    training_candidates = ordered[max(first_training, 0) : max(first_validation, 0)]
    if not validation_candidates:
        return MonthBlocks((), (), (), (), False)
    after_cutoff = calendar.next_session(cutoff).session_date
    validation_kept, validation_purged = purge(validation_candidates, calendar, after_cutoff)
    training_kept, training_purged = purge(training_candidates, calendar, validation_candidates[0])
    return MonthBlocks(
        training_kept, validation_kept, training_purged, validation_purged, first_training >= 0
    )


def feature_histories(
    reader: MarketDataReader,
    calendars: CalendarRegistry,
    timetable: BacktestTimetable,
    sessions: Sequence[date],
    builders: Mapping[str, SignatureFeatureBuilder],
) -> dict[str, dict[date, SignatureFeatures]]:
    """Build each representation's features at every session, each at its own instant.

    Parameters
    ----------
    reader : MarketDataReader
        The store.
    calendars : CalendarRegistry
        The venue calendars.
    timetable : BacktestTimetable
        Gives the decision instant of a session.
    sessions : Sequence[date]
        The origins to build for.
    builders : Mapping[str, SignatureFeatureBuilder]
        The representations, by name.

    Returns
    -------
    dict[str, dict[date, SignatureFeatures]]
        Per representation, the features of each origin - usable or not - as
        a decision taken that evening would have built them: the reader is
        fixed at that origin's decision instant, not at the end of the
        history. The same builder serves the calibration and the inference.
    """
    histories: dict[str, dict[date, SignatureFeatures]] = {name: {} for name in builders}
    for session in sessions:
        context = SignalContext(
            market=reader.at(timetable.decision_instant(session)),
            instruments=reader.instruments,
            calendars=calendars,
        )
        for name, builder in builders.items():
            histories[name][session] = builder.build(context)
    return histories


def calibration_environment(kind: ModelKind, features: FeatureKind) -> dict[str, str]:
    """Return the backend and the versions a calibration depends on."""
    packages = ["numpy"]
    packages += ["torch"] if kind is ModelKind.NEURAL_ADDITIVE else ["scikit-learn"]
    environment = {name: importlib.metadata.version(name) for name in packages}
    if features is FeatureKind.LOGSIGNATURE:
        environment.update(
            {
                "backend": BACKEND,
                "esig": importlib.metadata.version("esig"),
                "roughpy": importlib.metadata.version("roughpy"),
            }
        )
    return environment


def _valid(origins: Sequence[date], features: Mapping[date, SignatureFeatures]) -> list[date]:
    """Return the origins whose features were built and are usable."""
    return [
        origin
        for origin in origins
        if origin in features and features[origin].status is SignalStatus.OK
    ]


def _matrix(origins: Sequence[date], features: Mapping[date, SignatureFeatures]) -> Vector:
    """Return the raw features of valid origins, one per row."""
    rows = []
    for origin in origins:
        values = features[origin].values
        assert values is not None
        rows.append(values)
    return np.asarray(rows, dtype=np.float64)


def calibrate_month(
    variant: SignatureVariant,
    *,
    month: str,
    cutoff: date,
    sessions: Sequence[date],
    calendar: TradingCalendar,
    features: Mapping[date, SignatureFeatures],
    labels: ForwardOpenReturnBuilder,
    information_cutoff: datetime,
    available_at: datetime,
) -> tuple[ScheduleEntry, list[dict[str, object]]]:
    """Calibrate the model one month will use, or say why it has none.

    Parameters
    ----------
    variant : SignatureVariant
        What is fitted, on what.
    month : str
        The month the model applies to, ``"YYYY-MM"``.
    cutoff : date
        The last session of the month before: the calibration reads nothing
        after its evening.
    sessions : Sequence[date]
        The sessions of the calendar in order.
    calendar : TradingCalendar
        What dates the labels.
    features : Mapping[date, SignatureFeatures]
        The features of each origin, each built at its own instant.
    labels : ForwardOpenReturnBuilder
        Reads the open-to-open returns, on a reader fixed at the cutoff.
    information_cutoff, available_at : datetime
        The cutoff's decision instant and the instant the model may be used from.

    Returns
    -------
    tuple[ScheduleEntry, list[dict[str, object]]]
        The entry of the month - a frozen artifact, or no model with the
        reason - and one row of training history per epoch (one row for a
        model without epochs), each carrying the month, the counts of the
        blocks and of the purge.

    Raises
    ------
    MissingForwardOpen
        If an open a label needs is absent: it is not replaced by zero.
    FloatingPointError
        If a loss is not finite.
    """
    cut = variant.training
    blocks = month_blocks(sessions, cutoff, calendar, cut)
    training, validation = _valid(blocks.training, features), _valid(blocks.validation, features)
    counts: dict[str, object] = {
        "month": month,
        "variant_id": variant.variant_id,
        "cutoff": cutoff,
        "training_candidates_after_purge": len(blocks.training),
        "training_purged": len(blocks.training_purged),
        "training_valid": len(training),
        "validation_candidates_after_purge": len(blocks.validation),
        "validation_purged": len(blocks.validation_purged),
        "validation_valid": len(validation),
    }
    expected_training = cut.training_candidate_origins - len(blocks.training_purged)
    expected_validation = cut.validation_candidate_origins - len(blocks.validation_purged)
    shares = (
        len(training) / expected_training if expected_training > 0 else 0.0,
        len(validation) / expected_validation if expected_validation > 0 else 0.0,
    )
    refusal = None
    if len(training) < cut.minimum_training_examples:
        refusal = f"TRAINING_EXAMPLES:{len(training)}<{cut.minimum_training_examples}"
    elif len(validation) < cut.minimum_validation_examples:
        refusal = f"VALIDATION_EXAMPLES:{len(validation)}<{cut.minimum_validation_examples}"
    elif min(shares) < cut.minimum_valid_share:
        refusal = f"VALID_SHARE:{min(shares):.4f}<{cut.minimum_valid_share}"
    if refusal is not None:
        return ScheduleEntry(month, None, refusal), [{**counts, "status": refusal}]

    model = variant.model
    targets = labels.build([*training, *validation], [variant.instrument_id], known_until=cutoff)
    train_targets = np.ascontiguousarray(targets[: len(training), 0])
    held_targets = np.ascontiguousarray(targets[len(training) :, 0])
    raw_training = _matrix(training, features)
    scaler = FeatureScaler.fit(raw_training, model.input_clip)
    train_inputs, train_clipped = scaler.transform(raw_training)
    held_inputs, held_clipped = scaler.transform(_matrix(validation, features))
    scale = model.target_scale
    weights: Weights
    epoch: int | None
    if model.kind is ModelKind.RIDGE:
        weights = fit_ridge(train_inputs, scale * train_targets, alpha=model.ridge_alpha)
        epoch = None
        losses = [
            {
                "epoch": float("nan"),
                "training_loss": _mse(weights, train_inputs, scale * train_targets),
                "validation_loss": _mse(weights, held_inputs, scale * held_targets),
            }
        ]
    else:
        weights, losses, epoch = fit_additive(
            np.ascontiguousarray(train_inputs),
            scale * train_targets,
            np.ascontiguousarray(held_inputs),
            scale * held_targets,
            model,
        )
    artifact = SignatureArtifact(
        variant=variant.definition(),
        weights=weights,
        scaler_mean=scaler.mean,
        scaler_std=scaler.std,
        feature_names=variant.features.names(),
        month=month,
        information_cutoff=information_cutoff,
        available_at=available_at,
        training_start=training[0],
        training_end=training[-1],
        validation_start=validation[0],
        validation_end=validation[-1],
        training_examples=len(training),
        validation_examples=len(validation),
        selected_epoch=epoch,
        training_label_mean=float(train_targets.mean()),
        environment=calibration_environment(model.kind, variant.features.kind),
    )
    shared = {
        **counts,
        "status": "CALIBRATED",
        "model_id": artifact.model_id,
        "selected_epoch": epoch,
        "training_clipped_share": train_clipped / train_inputs.size,
        "validation_clipped_share": held_clipped / held_inputs.size,
    }
    return ScheduleEntry(month, artifact), [{**shared, **row} for row in losses]


def _mse(weights: Weights, inputs: Vector, targets: Vector) -> float:
    """Return the mean squared error of a fitted model, in the internal unit."""
    forecast = weights.bias + internal_contributions(weights, inputs).sum(axis=-1)
    return float(np.mean((forecast - targets) ** 2))
