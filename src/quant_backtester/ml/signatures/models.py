"""The fitted weights of a signature model, and what they forecast - in NumPy.

A decision needs no optimiser: it needs the weights a calibration left and the
arithmetic of a forward pass. Both models are kept here as plain arrays, so
that a strategy running on models already calibrated imports neither PyTorch
nor scikit-learn.

**The additive model.** For normalised features ``z_j``,

    100 * forecast = b + sum_j g_j(z_j),
    g_j(z) = a_j . [tanh(w_j z + c_j) - tanh(c_j)],       a_j, w_j, c_j in R^h,

so ``g_j(0) = 0``: the forecast at the reference ``z = 0`` is ``b / 100`` and
each ``g_j(z_j) / 100`` is the exact contribution of one feature. The model is
additive in its features: it learns no interaction between two coefficients
beyond those the coefficients already are.

**The ridge regression** is ``100 * forecast = b + sum_j beta_j z_j``, with the
same reading.

**Units.** Weights are in the internal unit of the fit, the percentage point;
:func:`contributions` and :func:`reference` return decimal returns, the
division by the target's scale applied exactly once. A contribution explains
how a forecast was computed. It is not a contribution to a P&L, and it says
nothing causal about the market.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from quant_backtester.ml.signatures.config import ModelKind

Vector = NDArray[np.float64]


@dataclass(frozen=True, eq=False)
class AdditiveWeights:
    """The weights of a neural additive model, one row per feature.

    Attributes
    ----------
    hidden_weight, hidden_bias, output_weight : numpy.ndarray
        ``w``, ``c`` and ``a``: shape ``(features, hidden_units)`` each.
    bias : float
        ``b``, the forecast at the reference, in the internal unit.

    Raises
    ------
    ValueError
        If the three arrays do not share one two-dimensional shape or a
        weight is not finite.
    """

    hidden_weight: Vector
    hidden_bias: Vector
    output_weight: Vector
    bias: float

    def __post_init__(self) -> None:
        """Refuse weights that do not describe the model."""
        arrays = (self.hidden_weight, self.hidden_bias, self.output_weight)
        if any(array.ndim != 2 or array.shape != arrays[0].shape for array in arrays):
            raise ValueError("the three weight arrays must share one (features, units) shape")
        if not (all(np.isfinite(array).all() for array in arrays) and np.isfinite(self.bias)):
            raise ValueError("a weight of the model is not finite")

    @property
    def features(self) -> int:
        """Return how many features the model reads."""
        return int(self.hidden_weight.shape[0])

    @property
    def parameters(self) -> int:
        """Return the number of parameters: ``3 * units`` per feature and the bias."""
        return int(3 * self.hidden_weight.size + 1)

    def arrays(self) -> dict[str, Vector]:
        """Return the weights by name, as they are stored."""
        return {
            "hidden_weight": self.hidden_weight,
            "hidden_bias": self.hidden_bias,
            "output_weight": self.output_weight,
            "bias": np.asarray([self.bias], dtype=np.float64),
        }


@dataclass(frozen=True, eq=False)
class LinearWeights:
    """The coefficients of a ridge regression on normalised features.

    Attributes
    ----------
    coefficients : numpy.ndarray
        ``beta``, one per feature, in the internal unit.
    bias : float
        The intercept: the forecast at the reference.

    Raises
    ------
    ValueError
        If the coefficients are not one finite vector.
    """

    coefficients: Vector
    bias: float

    def __post_init__(self) -> None:
        """Refuse coefficients that do not describe the model."""
        if self.coefficients.ndim != 1:
            raise ValueError("the coefficients of a ridge regression are one vector")
        if not (np.isfinite(self.coefficients).all() and np.isfinite(self.bias)):
            raise ValueError("a coefficient of the model is not finite")

    @property
    def features(self) -> int:
        """Return how many features the model reads."""
        return int(self.coefficients.shape[0])

    @property
    def parameters(self) -> int:
        """Return the number of parameters: one per feature and the intercept."""
        return self.features + 1

    def arrays(self) -> dict[str, Vector]:
        """Return the weights by name, as they are stored."""
        return {
            "coefficients": self.coefficients,
            "bias": np.asarray([self.bias], dtype=np.float64),
        }


Weights = AdditiveWeights | LinearWeights


def kind_of(weights: Weights) -> ModelKind:
    """Return which model a set of weights belongs to."""
    return ModelKind.NEURAL_ADDITIVE if isinstance(weights, AdditiveWeights) else ModelKind.RIDGE


def weights_from(kind: ModelKind, arrays: dict[str, Vector]) -> Weights:
    """Return the weights of a model from its stored arrays.

    Raises
    ------
    KeyError
        If an array the model needs is not there.
    """
    bias = float(np.asarray(arrays["bias"], dtype=np.float64).reshape(-1)[0])
    if kind is ModelKind.RIDGE:
        return LinearWeights(np.asarray(arrays["coefficients"], dtype=np.float64), bias)
    return AdditiveWeights(
        np.asarray(arrays["hidden_weight"], dtype=np.float64),
        np.asarray(arrays["hidden_bias"], dtype=np.float64),
        np.asarray(arrays["output_weight"], dtype=np.float64),
        bias,
    )


def internal_contributions(weights: Weights, normalised: Vector) -> Vector:
    """Return each feature's contribution to the forecast, in the internal unit.

    Parameters
    ----------
    weights : AdditiveWeights | LinearWeights
        A fitted model.
    normalised : numpy.ndarray
        Normalised features: one vector, or one per row.

    Returns
    -------
    numpy.ndarray
        The same shape as the input. Every contribution is zero at ``z = 0``.

    Raises
    ------
    ValueError
        If the last dimension is not the model's number of features.
    """
    inputs = np.asarray(normalised, dtype=np.float64)
    if inputs.shape[-1] != weights.features:
        raise ValueError(
            f"the model reads {weights.features} features and was given {inputs.shape[-1]}"
        )
    if isinstance(weights, LinearWeights):
        return inputs * weights.coefficients
    activated = np.tanh(inputs[..., None] * weights.hidden_weight + weights.hidden_bias)
    centred = activated - np.tanh(weights.hidden_bias)
    return np.sum(centred * weights.output_weight, axis=-1)


def contributions(weights: Weights, normalised: Vector, *, target_scale: float) -> Vector:
    """Return each feature's contribution to the forecast, as a decimal return."""
    return internal_contributions(weights, normalised) / target_scale


def reference(weights: Weights, *, target_scale: float) -> float:
    """Return the forecast at ``z = 0``, as a decimal return: ``b / target_scale``."""
    return weights.bias / target_scale


def predict(weights: Weights, normalised: Vector, *, target_scale: float) -> Vector:
    """Return the forecast of each input, as a decimal return.

    The reference plus the sum of the contributions, the division by the
    target's scale applied once.
    """
    total = weights.bias + internal_contributions(weights, normalised).sum(axis=-1)
    return np.asarray(total / target_scale, dtype=np.float64)


def fit_ridge(inputs: Vector, targets: Vector, *, alpha: float) -> LinearWeights:
    """Fit a ridge regression on normalised features, in the internal unit.

    Parameters
    ----------
    inputs : numpy.ndarray
        Normalised training features, one per row.
    targets : numpy.ndarray
        The targets already multiplied by the target's scale.
    alpha : float
        The penalty, fixed before any run: no grid is searched.

    Returns
    -------
    LinearWeights
        The coefficients and the intercept of ``Ridge(alpha, fit_intercept=True,
        solver="svd")``.

    Raises
    ------
    ImportError
        If scikit-learn (the ``signatures`` extra) is not installed.
    """
    # Imported on use: an optional dependency, needed by a calibration only.
    from sklearn.linear_model import Ridge

    model = Ridge(alpha=alpha, fit_intercept=True, solver="svd")
    model.fit(inputs, targets)
    return LinearWeights(np.asarray(model.coef_, dtype=np.float64), float(model.intercept_))
