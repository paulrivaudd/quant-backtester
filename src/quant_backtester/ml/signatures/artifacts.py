"""The frozen model of one month, and the schedule that says which model a decision may use.

A model is calibrated at a month's end, on what was known at its *information
cutoff*, and used during the month that follows. Two rules keep that honest:

- **an artifact is identified by its content**: weights, normalisation, the
  ordered names of its features, the definition of the variant - path, basis,
  backend, model, cut - its periods, its cutoff and its seed. Two artifacts of
  one dimension are not the same model, and a folder whose content does not
  hash to its recorded identity is refused;
- **a decision takes the model of its month, and only if it could have had
  it**: the schedule is built before a backtest, a decision never loads "the
  latest model", and a model whose cutoff or availability is not before the
  decision stops the run.

A month without enough data to calibrate has an entry too, with no model and
the reason: the decisions of that month are in cash, and stay in the results.

Weights and normalisation are stored as NumPy arrays without pickle, beside a
JSON manifest. Loading one needs neither PyTorch nor scikit-learn.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from types import MappingProxyType
from zoneinfo import ZoneInfo

import numpy as np
from numpy.typing import NDArray

from quant_backtester.ml.features import FeatureScaler
from quant_backtester.ml.signatures.config import ModelKind
from quant_backtester.ml.signatures.models import (
    Weights,
    contributions,
    kind_of,
    reference,
    weights_from,
)

MANIFEST_FILE = "manifest.json"
"""The description of an artifact, its identity included."""

ARRAYS_FILE = "arrays.npz"
"""Its weights and its normalisation, without pickle."""

NO_MODEL = "NO_MODEL"
"""The status of a month no model could be calibrated for."""

Vector = NDArray[np.float64]


class ArtifactMismatch(ValueError):
    """Raised when a stored artifact is not the one its manifest describes."""


class ModelCausalityError(RuntimeError):
    """Raised when a decision would use a model it could not have had, or has none planned."""


@dataclass(frozen=True, slots=True)
class SignaturePrediction:
    """One forecast and its exact decomposition.

    Attributes
    ----------
    mean : float
        The forecast simple return, decimal: the reference plus the
        contributions.
    reference : float
        The forecast at ``z = 0``, decimal.
    contributions : tuple[float, ...]
        Each feature's contribution, decimal, in the order of the features.
    clipped : int
        Normalised features the clip moved.
    """

    mean: float
    reference: float
    contributions: tuple[float, ...]
    clipped: int


def _digest(values: Vector) -> str:
    """Return the SHA-256 of an array's shape and bytes, as float64 in C order."""
    array = np.ascontiguousarray(values, dtype=np.float64)
    return hashlib.sha256(str(array.shape).encode() + array.tobytes()).hexdigest()


@dataclass(frozen=True, eq=False)
class SignatureArtifact:
    """A calibrated model, frozen: what it is, what it saw, when it may be used.

    Attributes
    ----------
    variant : Mapping[str, object]
        The definition of the variant it was calibrated for.
    weights : AdditiveWeights | LinearWeights
        The fitted model, in the internal unit.
    scaler_mean, scaler_std : numpy.ndarray
        The normalisation fitted on the training features only.
    feature_names : tuple[str, ...]
        The ordered names of the features, qualified by their process.
    month : str
        The month the model applies to, ``"YYYY-MM"``.
    information_cutoff : datetime
        The decision instant of the last session the calibration could read.
    available_at : datetime
        The instant from which the model may be used.
    training_start, training_end, validation_start, validation_end : date
        The first and last origins of each purged block.
    training_examples, validation_examples : int
        Valid examples in each.
    selected_epoch : int | None
        The epoch whose weights are kept; ``None`` for a model without epochs.
    training_label_mean : float
        Mean of the training targets, decimal: the naive forecast frozen with
        the model, against which an out-of-sample R-squared is measured.
    environment : Mapping[str, str]
        The backend and the versions the calibration ran with.
    model_id : str
        SHA-256 of everything above.
    """

    variant: Mapping[str, object]
    weights: Weights
    scaler_mean: Vector
    scaler_std: Vector
    feature_names: tuple[str, ...]
    month: str
    information_cutoff: datetime
    available_at: datetime
    training_start: date
    training_end: date
    validation_start: date
    validation_end: date
    training_examples: int
    validation_examples: int
    selected_epoch: int | None
    training_label_mean: float
    environment: Mapping[str, str]
    model_id: str = ""

    def __post_init__(self) -> None:
        """Check the artifact and give it, or verify, its identity."""
        object.__setattr__(self, "variant", MappingProxyType(dict(self.variant)))
        object.__setattr__(self, "environment", MappingProxyType(dict(self.environment)))
        object.__setattr__(self, "feature_names", tuple(self.feature_names))
        count = len(self.feature_names)
        if self.weights.features != count or self.scaler_mean.shape != (count,):
            raise ArtifactMismatch("weights, normalisation and feature names disagree on a count")
        if self.scaler_std.shape != (count,):
            raise ArtifactMismatch("the normalisation does not match the features")
        for instant in (self.information_cutoff, self.available_at):
            if instant.tzinfo is None:
                raise ValueError("an artifact's instants are timezone-aware")
        if self.available_at < self.information_cutoff:
            raise ValueError("a model cannot be available before its information cutoff")
        if not math.isfinite(self.training_label_mean):
            raise ValueError("the mean of the training targets is not finite")
        identity = self._identity()
        if not self.model_id:
            object.__setattr__(self, "model_id", identity)
        elif self.model_id != identity:
            raise ArtifactMismatch(
                f"the artifact's content hashes to {identity[:12]}, not to its recorded "
                f"identity {self.model_id[:12]}"
            )

    # -- identity -----------------------------------------------------------

    @property
    def kind(self) -> ModelKind:
        """Return which model the weights belong to."""
        return kind_of(self.weights)

    @property
    def variant_id(self) -> str:
        """Return the identifier of the variant."""
        return str(self.variant["variant_id"])

    @property
    def input_clip(self) -> float:
        """Return the bound of a normalised feature."""
        model = self.variant["model"]
        assert isinstance(model, Mapping)
        return float(model["input_clip"])

    @property
    def target_scale(self) -> float:
        """Return what the target was multiplied by for the fit."""
        model = self.variant["model"]
        assert isinstance(model, Mapping)
        return float(model["target_scale"])

    def description(self) -> dict[str, object]:
        """Return everything but the arrays, serialisable, with the arrays' digests."""
        arrays = {
            **self.weights.arrays(),
            "scaler_mean": self.scaler_mean,
            "scaler_std": self.scaler_std,
        }
        return {
            "variant": json.loads(json.dumps(dict(self.variant), default=str)),
            "kind": self.kind.value,
            "feature_names": list(self.feature_names),
            "month": self.month,
            "information_cutoff": self.information_cutoff.isoformat(),
            "available_at": self.available_at.isoformat(),
            "training_start": self.training_start.isoformat(),
            "training_end": self.training_end.isoformat(),
            "validation_start": self.validation_start.isoformat(),
            "validation_end": self.validation_end.isoformat(),
            "training_examples": self.training_examples,
            "validation_examples": self.validation_examples,
            "selected_epoch": self.selected_epoch,
            "training_label_mean": self.training_label_mean,
            "parameters": self.weights.parameters,
            "environment": dict(self.environment),
            "arrays": {name: _digest(values) for name, values in sorted(arrays.items())},
        }

    def _identity(self) -> str:
        """Return the SHA-256 of the description, arrays included by their digests."""
        canonical = json.dumps(self.description(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    # -- inference ----------------------------------------------------------

    def predict(self, values: Sequence[float]) -> SignaturePrediction:
        """Return the forecast of one vector of raw features, decomposed.

        Parameters
        ----------
        values : Sequence[float]
            The raw features, in the order of ``feature_names``.

        Returns
        -------
        SignaturePrediction
            The forecast as a decimal return, the reference and each
            feature's contribution. Their sum is the forecast.

        Raises
        ------
        ValueError
            If the vector is not the model's, or the forecast is not finite: a
            broken model stops the run, it is not replaced by anything.
        """
        raw = np.asarray(values, dtype=np.float64)
        if raw.shape != (len(self.feature_names),) or not np.isfinite(raw).all():
            raise ValueError(
                f"the model reads {len(self.feature_names)} finite features, got {raw.shape}"
            )
        scaler = FeatureScaler(self.scaler_mean, self.scaler_std, self.input_clip)
        normalised, clipped = scaler.transform(raw)
        parts = contributions(self.weights, normalised, target_scale=self.target_scale)
        base = reference(self.weights, target_scale=self.target_scale)
        mean = base + float(parts.sum())
        if not math.isfinite(mean):
            raise ValueError(
                f"the model {self.model_id[:12]} returned a forecast that is not finite"
            )
        return SignaturePrediction(mean, base, tuple(float(part) for part in parts), clipped)

    # -- storage ------------------------------------------------------------

    def save(self, directory: Path) -> Path:
        """Write the artifact into a folder of its own and return the folder."""
        directory.mkdir(parents=True, exist_ok=True)
        arrays = {
            **self.weights.arrays(),
            "scaler_mean": self.scaler_mean,
            "scaler_std": self.scaler_std,
        }
        np.savez(directory / ARRAYS_FILE, **arrays)  # type: ignore[arg-type]
        manifest = {**self.description(), "model_id": self.model_id}
        (directory / MANIFEST_FILE).write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return directory

    @classmethod
    def load(cls, directory: Path) -> SignatureArtifact:
        """Return the artifact stored in a folder, its identity verified.

        Raises
        ------
        ArtifactMismatch
            If the arrays are not those the manifest describes: a corrupted
            or mixed-up folder is refused, never loaded on its dimensions.
        """
        manifest = json.loads((directory / MANIFEST_FILE).read_text(encoding="utf-8"))
        with np.load(directory / ARRAYS_FILE, allow_pickle=False) as stored:
            arrays = {name: np.asarray(stored[name], dtype=np.float64) for name in stored.files}
        kind = ModelKind(manifest["kind"])
        try:
            weights = weights_from(kind, arrays)
            mean, std = arrays["scaler_mean"], arrays["scaler_std"]
        except KeyError as missing:
            raise ArtifactMismatch(f"the stored arrays lack {missing}") from missing
        return cls(
            variant=manifest["variant"],
            weights=weights,
            scaler_mean=mean,
            scaler_std=std,
            feature_names=tuple(manifest["feature_names"]),
            month=manifest["month"],
            information_cutoff=datetime.fromisoformat(manifest["information_cutoff"]),
            available_at=datetime.fromisoformat(manifest["available_at"]),
            training_start=date.fromisoformat(manifest["training_start"]),
            training_end=date.fromisoformat(manifest["training_end"]),
            validation_start=date.fromisoformat(manifest["validation_start"]),
            validation_end=date.fromisoformat(manifest["validation_end"]),
            training_examples=int(manifest["training_examples"]),
            validation_examples=int(manifest["validation_examples"]),
            selected_epoch=manifest["selected_epoch"],
            training_label_mean=float(manifest["training_label_mean"]),
            environment=manifest["environment"],
            model_id=manifest["model_id"],
        )


@dataclass(frozen=True, slots=True)
class ScheduleEntry:
    """What one month is given: a model, or the reason it has none.

    Attributes
    ----------
    month : str
        ``"YYYY-MM"``.
    artifact : SignatureArtifact | None
        The model of the month.
    reason : str | None
        Why there is none: the decisions of the month are then in cash.
    """

    month: str
    artifact: SignatureArtifact | None
    reason: str | None = None

    def __post_init__(self) -> None:
        """Refuse an entry that has neither a model nor a reason, or another month's model."""
        if (self.artifact is None) == (self.reason is None):
            raise ValueError("an entry holds a model or the reason it has none, not both")
        if self.artifact is not None and self.artifact.month != self.month:
            raise ValueError(f"the model of {self.artifact.month} is planned for {self.month}")

    @property
    def identity(self) -> str:
        """Return the model's identity, or ``NO_MODEL`` with its reason."""
        return f"{NO_MODEL}:{self.reason}" if self.artifact is None else self.artifact.model_id


@dataclass(frozen=True, slots=True)
class SignatureModelSchedule:
    """Which model each month uses, fixed before a backtest.

    Attributes
    ----------
    variant_id : str
        The variant every model belongs to.
    timezone : str
        The zone decisions are dated in: a decision belongs to the month of
        its local date.
    entries : tuple[ScheduleEntry, ...]
        One entry per month, in order.

    Raises
    ------
    ValueError
        If a month appears twice, the months are not in order, or a model
        belongs to another variant.
    """

    variant_id: str
    timezone: str
    entries: tuple[ScheduleEntry, ...]

    def __post_init__(self) -> None:
        """Refuse a schedule a decision could read two ways."""
        object.__setattr__(self, "entries", tuple(self.entries))
        months = [entry.month for entry in self.entries]
        if months != sorted(set(months)):
            raise ValueError("a schedule holds each month once, in order")
        ZoneInfo(self.timezone)
        for entry in self.entries:
            if entry.artifact is not None and entry.artifact.variant_id != self.variant_id:
                raise ValueError(
                    f"the model of {entry.month} belongs to {entry.artifact.variant_id}, "
                    f"not to {self.variant_id}"
                )

    @property
    def schedule_id(self) -> str:
        """Return a hash of the months and of the identities of their models."""
        content = [[entry.month, entry.identity] for entry in self.entries]
        canonical = json.dumps([self.variant_id, self.timezone, content], separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def month_of(self, decision: datetime) -> str:
        """Return the month a decision instant belongs to, in the schedule's zone."""
        if decision.tzinfo is None:
            raise ValueError("a decision instant is timezone-aware")
        local = decision.astimezone(ZoneInfo(self.timezone))
        return f"{local.year:04d}-{local.month:02d}"

    def entry_at(self, decision: datetime) -> ScheduleEntry:
        """Return the entry a decision uses: its month's, and only if it could have had it.

        Parameters
        ----------
        decision : datetime
            The decision instant, timezone-aware.

        Returns
        -------
        ScheduleEntry
            The model of the decision's month, or the entry saying there is none.

        Raises
        ------
        ModelCausalityError
            If the month is not planned, or its model's information cutoff or
            availability is not before the decision.
        """
        month = self.month_of(decision)
        for entry in self.entries:
            if entry.month != month:
                continue
            artifact = entry.artifact
            if artifact is not None and not (
                artifact.information_cutoff < decision and artifact.available_at <= decision
            ):
                raise ModelCausalityError(
                    f"the model planned for {month} (cutoff "
                    f"{artifact.information_cutoff.isoformat()}, available "
                    f"{artifact.available_at.isoformat()}) cannot be used at "
                    f"{decision.isoformat()}"
                )
            return entry
        raise ModelCausalityError(
            f"no model is planned for {month}: the schedule does not cover it"
        )

    def definition(self) -> dict[str, object]:
        """Return the schedule as it is recorded: every month and its model's identity."""
        return {
            "variant_id": self.variant_id,
            "timezone": self.timezone,
            "schedule_id": self.schedule_id,
            "months": {entry.month: entry.identity for entry in self.entries},
        }
