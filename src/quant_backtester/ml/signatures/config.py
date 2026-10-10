"""The frozen configurations of a signature model: what it reads, how it is fitted.

Three records, none with a research default hidden in the code that uses it:
the model and its optimiser, the blocks a monthly calibration is cut into, and
a *variant* - one representation, one model, one identifier. The strategy
``SA13`` is one variant; each control of its study is another, with its own
identifier, and none replaces another after a test is read.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from enum import Enum

from quant_backtester.numbers import require_finite_positive
from quant_backtester.signals.signatures.logsignature import FeatureSpec
from quant_backtester.signals.types import require_identifier, require_positive_int


class ModelKind(Enum):
    """Which model reads the features."""

    NEURAL_ADDITIVE = "NEURAL_ADDITIVE"
    """One small network per feature, summed: every contribution is exact."""

    RIDGE = "RIDGE"
    """A ridge regression on the same normalised features: the control of the neurons."""


@dataclass(frozen=True, slots=True)
class SignatureModelConfig:
    """The model and everything its fit depends on besides the data.

    Attributes
    ----------
    kind : ModelKind
        The additive network or the ridge regression.
    hidden_units : int
        Units of each feature's network.
    learning_rate, weight_decay : float
        Of AdamW. The decay is the optimiser's, not a penalty added to the loss.
    max_epochs : int
        Epochs at most, each one full batch.
    patience : int
        Epochs without improvement of the validation loss before stopping.
    minimum_improvement : float
        Smallest fall of the validation MSE, in the internal unit, that counts.
    gradient_clip_norm : float
        Largest norm of the gradient.
    seed : int
        Seed every calibration is started from.
    input_clip : float
        A normalised feature is clipped to ``[-input_clip, input_clip]``.
    target_scale : float
        What the target is multiplied by for the fit: 100, so the internal
        unit is the percentage point and the public one a decimal return.
    ridge_alpha : float
        The penalty of the ridge regression, fixed before any run.

    Raises
    ------
    ValueError
        If a count is not a positive integer or a number is not finite and
        positive.
    """

    kind: ModelKind
    hidden_units: int
    learning_rate: float
    weight_decay: float
    max_epochs: int
    patience: int
    minimum_improvement: float
    gradient_clip_norm: float
    seed: int
    input_clip: float
    target_scale: float
    ridge_alpha: float

    def __post_init__(self) -> None:
        """Reject a model that cannot be fitted."""
        if not isinstance(self.kind, ModelKind):
            raise ValueError(f"kind must be a ModelKind, got {self.kind!r}")
        for name in ("hidden_units", "max_epochs", "patience"):
            require_positive_int(getattr(self, name), name)
        for name in (
            "learning_rate",
            "gradient_clip_norm",
            "input_clip",
            "target_scale",
            "ridge_alpha",
        ):
            require_finite_positive(getattr(self, name), name)
        for name in ("weight_decay", "minimum_improvement"):
            value = getattr(self, name)
            if not (math.isfinite(value) and value >= 0.0):
                raise ValueError(f"{name} must be finite and non-negative, got {value!r}")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int) or self.seed < 0:
            raise ValueError(f"seed must be a non-negative integer, got {self.seed!r}")

    def definition(self) -> dict[str, object]:
        """Return the model as it is recorded: only what its kind uses."""
        common: dict[str, object] = {
            "kind": self.kind.value,
            "input_clip": self.input_clip,
            "target": "SIMPLE_TOTAL_RETURN_NEXT_OPEN_TO_FOLLOWING_OPEN",
            "target_scale": self.target_scale,
            "dtype": "float64",
        }
        if self.kind is ModelKind.RIDGE:
            return {**common, "alpha": self.ridge_alpha, "fit_intercept": True, "solver": "svd"}
        return {
            **common,
            "hidden_units_per_feature": self.hidden_units,
            "activation": "tanh",
            "center_each_component_at_zero": True,
            "optimizer": "AdamW",
            "learning_rate": self.learning_rate,
            "weight_decay": self.weight_decay,
            "max_epochs": self.max_epochs,
            "patience": self.patience,
            "minimum_improvement": self.minimum_improvement,
            "gradient_clip_norm": self.gradient_clip_norm,
            "batch": "FULL",
            "selection_metric": "VALIDATION_MSE",
            "refit_on_train_plus_validation": False,
            "device": "cpu",
            "threads": 1,
            "seed": self.seed,
        }


@dataclass(frozen=True, slots=True)
class SignatureTrainingConfig:
    """How the history before a month is cut into training and validation.

    Attributes
    ----------
    training_candidate_origins : int
        Sessions of the training block, before the purge.
    validation_candidate_origins : int
        Sessions of the validation block ending at the cutoff, before the purge.
    minimum_training_examples, minimum_validation_examples : int
        Fewest valid examples each block must hold after the purge.
    minimum_valid_share : float
        Smallest share of valid features in each purged block.

    Raises
    ------
    ValueError
        If a count is not a positive integer, a minimum exceeds its block, or
        the share is not in ``(0, 1]``.
    """

    training_candidate_origins: int
    validation_candidate_origins: int
    minimum_training_examples: int
    minimum_validation_examples: int
    minimum_valid_share: float

    def __post_init__(self) -> None:
        """Reject blocks that cannot be cut."""
        for name in (
            "training_candidate_origins",
            "validation_candidate_origins",
            "minimum_training_examples",
            "minimum_validation_examples",
        ):
            require_positive_int(getattr(self, name), name)
        if self.minimum_training_examples > self.training_candidate_origins:
            raise ValueError("minimum_training_examples exceeds the training block")
        if self.minimum_validation_examples > self.validation_candidate_origins:
            raise ValueError("minimum_validation_examples exceeds the validation block")
        if not (math.isfinite(self.minimum_valid_share) and 0.0 < self.minimum_valid_share <= 1.0):
            raise ValueError(f"minimum_valid_share is in (0, 1], got {self.minimum_valid_share!r}")

    def definition(self) -> dict[str, object]:
        """Return the cut as it is recorded."""
        return {
            "refit_schedule": "MONTHLY",
            "training_candidate_origins": self.training_candidate_origins,
            "validation_candidate_origins": self.validation_candidate_origins,
            "minimum_training_examples": self.minimum_training_examples,
            "minimum_validation_examples": self.minimum_validation_examples,
            "minimum_valid_share": self.minimum_valid_share,
            "purge": "a label ends at the open two sessions after its origin",
        }


@dataclass(frozen=True, slots=True)
class SignatureVariant:
    """One representation, one model, one identifier.

    Attributes
    ----------
    variant_id : str
        The name the variant's artifacts and results are recorded under.
    instrument_id : str
        The fund whose next open-to-open return is forecast.
    features : FeatureSpec
        What the model reads.
    model : SignatureModelConfig
        The model and its fit.
    training : SignatureTrainingConfig
        The monthly cut.

    Raises
    ------
    ValueError
        If a name is empty.
    """

    variant_id: str
    instrument_id: str
    features: FeatureSpec
    model: SignatureModelConfig
    training: SignatureTrainingConfig

    def __post_init__(self) -> None:
        """Reject a variant that cannot be named."""
        require_identifier(self.variant_id, "variant_id")
        require_identifier(self.instrument_id, "instrument_id")

    def definition(self) -> dict[str, object]:
        """Return everything that identifies the variant, serialisable."""
        return {
            "variant_id": self.variant_id,
            "instrument_id": self.instrument_id,
            "features": self.features.definition(),
            "model": self.model.definition(),
            "training": self.training.definition(),
        }

    def fingerprint(self) -> str:
        """Return a stable hash of the definition."""
        canonical = json.dumps(self.definition(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
