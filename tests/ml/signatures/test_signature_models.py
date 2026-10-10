"""The fitted weights of a signature model: an exact, additive forecast in decimal units."""

from __future__ import annotations

import numpy as np
import pytest

from quant_backtester.ml.signatures.config import ModelKind
from quant_backtester.ml.signatures.models import (
    AdditiveWeights,
    LinearWeights,
    contributions,
    fit_ridge,
    internal_contributions,
    kind_of,
    predict,
    reference,
    weights_from,
)


def additive(features: int = 13, units: int = 4, seed: int = 1) -> AdditiveWeights:
    """Return an additive model with drawn weights."""
    rng = np.random.default_rng(seed)
    return AdditiveWeights(
        rng.normal(0.0, 1.0, (features, units)),
        rng.normal(0.0, 0.5, (features, units)),
        rng.normal(0.0, 0.3, (features, units)),
        0.04,
    )


def test_the_model_of_the_specification_has_157_parameters() -> None:
    assert additive(13).parameters == 157  # 13 x 12 + 1
    assert additive(5).parameters == 61
    assert additive(26).parameters == 313
    assert additive(9).parameters == 109
    assert LinearWeights(np.zeros(13), 0.0).parameters == 14


def test_every_contribution_is_zero_at_the_reference() -> None:
    weights = additive()

    assert not internal_contributions(weights, np.zeros(13)).any()
    assert predict(weights, np.zeros(13), target_scale=100.0) == pytest.approx(0.0004)
    assert reference(weights, target_scale=100.0) == pytest.approx(0.0004)


def test_the_reference_and_the_contributions_recompose_each_forecast() -> None:
    weights = additive()
    inputs = np.random.default_rng(2).normal(0.0, 1.5, (50, 13))

    parts = contributions(weights, inputs, target_scale=100.0)
    forecasts = predict(weights, inputs, target_scale=100.0)

    assert parts.shape == (50, 13) and forecasts.shape == (50,)
    assert np.allclose(reference(weights, target_scale=100.0) + parts.sum(axis=1), forecasts)
    # One vector or one per row: the same numbers.
    assert np.allclose(contributions(weights, inputs[7], target_scale=100.0), parts[7])


def test_the_division_by_the_target_scale_is_applied_exactly_once() -> None:
    weights = additive()
    inputs = np.random.default_rng(3).normal(0.0, 1.0, 13)

    internal = weights.bias + float(internal_contributions(weights, inputs).sum())

    assert float(predict(weights, inputs, target_scale=100.0)) == pytest.approx(internal / 100.0)
    assert float(predict(weights, inputs, target_scale=1.0)) == pytest.approx(internal)


def test_the_additive_model_is_the_formula_of_its_definition() -> None:
    weights = additive(features=2, units=3)
    inputs = np.array([0.7, -1.2])

    by_hand = [
        float(
            np.sum(
                weights.output_weight[j]
                * (
                    np.tanh(weights.hidden_weight[j] * inputs[j] + weights.hidden_bias[j])
                    - np.tanh(weights.hidden_bias[j])
                )
            )
        )
        for j in range(2)
    ]

    assert list(internal_contributions(weights, inputs)) == pytest.approx(by_hand)


def test_a_feature_changes_its_own_contribution_and_no_other() -> None:
    """Additive in its features: no interaction is learnt between two coefficients."""
    weights = additive()
    inputs = np.random.default_rng(4).normal(0.0, 1.0, 13)
    moved = inputs.copy()
    moved[5] += 2.0

    before = internal_contributions(weights, inputs)
    after = internal_contributions(weights, moved)

    assert after[5] != before[5]
    assert np.array_equal(np.delete(after, 5), np.delete(before, 5))


def test_a_linear_contribution_is_its_coefficient_times_its_feature() -> None:
    weights = LinearWeights(np.array([0.5, -2.0, 0.0]), 0.1)
    inputs = np.array([1.0, 0.5, 9.0])

    assert list(contributions(weights, inputs, target_scale=100.0)) == pytest.approx(
        [0.005, -0.01, 0.0]
    )
    assert float(predict(weights, inputs, target_scale=100.0)) == pytest.approx(0.001 - 0.005)


def test_weights_are_stored_as_plain_arrays_and_come_back_the_same() -> None:
    for weights in (additive(), LinearWeights(np.array([0.5, -2.0]), 0.1)):
        kind = kind_of(weights)
        again = weights_from(kind, weights.arrays())

        assert kind_of(again) is kind and again.bias == weights.bias
        for name, values in weights.arrays().items():
            assert np.array_equal(again.arrays()[name], values)
    assert kind_of(additive()) is ModelKind.NEURAL_ADDITIVE
    with pytest.raises(KeyError):
        weights_from(ModelKind.RIDGE, {"bias": np.zeros(1)})


@pytest.mark.parametrize(
    "build",
    [
        lambda: AdditiveWeights(np.zeros((3, 4)), np.zeros((3, 4)), np.zeros((3, 5)), 0.0),
        lambda: AdditiveWeights(np.zeros(4), np.zeros(4), np.zeros(4), 0.0),
        lambda: AdditiveWeights(np.full((3, 4), np.nan), np.zeros((3, 4)), np.zeros((3, 4)), 0.0),
        lambda: LinearWeights(np.zeros((2, 2)), 0.0),
        lambda: LinearWeights(np.zeros(2), float("inf")),
    ],
)
def test_weights_that_do_not_describe_a_model_are_refused(build) -> None:
    with pytest.raises(ValueError):
        build()


def test_a_vector_of_another_size_is_refused() -> None:
    with pytest.raises(ValueError, match="reads 13 features"):
        internal_contributions(additive(), np.zeros(12))


def test_the_ridge_regression_is_fitted_once_with_its_fixed_penalty() -> None:
    pytest.importorskip("sklearn")
    rng = np.random.default_rng(5)
    inputs = rng.normal(0.0, 1.0, (400, 3))
    targets = 0.3 + inputs @ np.array([1.0, -0.5, 0.0]) + rng.normal(0.0, 0.01, 400)

    weights = fit_ridge(inputs, targets, alpha=10.0)
    again = fit_ridge(inputs, targets, alpha=10.0)
    shrunk = fit_ridge(inputs, targets, alpha=10_000.0)

    assert np.array_equal(weights.coefficients, again.coefficients)
    assert weights.bias == pytest.approx(0.3, abs=0.01)
    assert list(weights.coefficients) == pytest.approx([1.0, -0.5, 0.0], abs=0.05)
    assert abs(shrunk.coefficients[0]) < abs(weights.coefficients[0])  # the penalty shrinks
