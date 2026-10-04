"""The network and its objective: shapes, the cap, the costs and a reference simulation."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("torch")

import torch

from quant_backtester.ml.config import NeuralStrategyConfig
from quant_backtester.ml.features import FeatureScaler
from quant_backtester.ml.network import (
    NeuralAllocator,
    NeuralRuntime,
    capped_fund_weights,
    proxy_returns,
    risk_adjusted_objective,
)


def tensor(values: object) -> torch.Tensor:
    """Return values as a float64 tensor."""
    return torch.tensor(values, dtype=torch.float64)


def naive_proxy_returns(weights: np.ndarray, forward: np.ndarray, cost: float) -> list[float]:
    """Return the proxy returns one decision at a time, as the specification writes them."""
    before = np.zeros(weights.shape[1])
    earned = []
    for row, returns in zip(weights, forward, strict=True):
        traded = float(np.abs(row - before).sum())
        earned.append(float(row @ returns) - cost * traded)
        before = row * (1.0 + returns) / (1.0 + float(row @ returns))
    return earned


def test_the_specified_architecture_has_2459_parameters(neural_config) -> None:
    config = NeuralStrategyConfig.from_definition(
        neural_config.definition()
        | {
            "feature_ids": ["A", "B", "C", "D", "E", "F", "VIX"],
            "tradable_ids": ["A", "B"],
            "level_id": "VIX",
            "history_sessions": 100,
            "ma_windows": [20, 50, 100],
            "vol_windows": [20, 60],
            "encoder_width": 8,
            "hidden_width": 16,
        }
    )

    model = NeuralAllocator(config)

    # Encoder 100*8+8, hidden (14*7+1)*16+16, output 16*3+3.
    assert sum(values.numel() for values in model.parameters()) == 808 + 1600 + 51 == 2459
    assert {values.dtype for values in model.parameters()} == {torch.float64}


def test_the_outputs_are_positive_weights_of_sum_one_funds_then_cash(neural_config) -> None:
    torch.manual_seed(0)
    model = NeuralAllocator(neural_config).eval()

    weights = model(torch.randn(5, neural_config.input_size, dtype=torch.float64))

    assert weights.shape == (5, 3)
    assert bool((weights > 0).all())
    assert weights.sum(dim=1).tolist() == pytest.approx([1.0] * 5)
    with pytest.raises(ValueError, match="rows of 37"):
        model(torch.zeros(5, 36, dtype=torch.float64))


def test_the_encoder_is_shared_by_every_series(neural_config) -> None:
    """Two series swapping their histories swap their encodings: one set of parameters."""
    model = NeuralAllocator(neural_config).eval()
    inputs = torch.randn(1, neural_config.input_size, dtype=torch.float64)
    blocks = inputs[:, :-1].reshape(1, 3, 12)

    encoded = torch.tanh(model.encoder(blocks[:, :, :6]))
    swapped = torch.tanh(model.encoder(blocks[:, [1, 0, 2], :6]))

    assert torch.equal(swapped[:, 0], encoded[:, 1])
    assert model.encoder.weight.shape == (3, 6)


def test_a_cap_sends_what_it_removes_to_cash_and_not_to_the_other_funds() -> None:
    weights = tensor([[0.70, 0.20, 0.10]])

    funds = capped_fund_weights(weights, 0.50)

    assert funds.tolist() == [[0.50, 0.20]]
    assert 1.0 - funds.sum().item() == pytest.approx(0.30)


def test_the_first_purchase_and_both_sides_of_a_switch_pay_costs() -> None:
    weights = tensor([[1.0, 0.0], [0.0, 1.0]])
    flat = tensor([[0.0, 0.0], [0.0, 0.0]])

    earned = proxy_returns(weights, flat, cost_rate=0.001)

    # Cash to 100% of a fund trades 100%; a full switch trades 200%.
    assert earned.tolist() == pytest.approx([-0.001, -0.002])


def test_weights_drift_with_the_returns_before_the_next_order() -> None:
    weights = tensor([[0.5, 0.5], [0.5, 0.5]])
    forward = tensor([[0.10, 0.00], [0.00, 0.00]])

    earned = proxy_returns(weights, forward, cost_rate=0.01)

    # After +10% on the first fund the book is 0.55/1.05 and 0.50/1.05.
    drifted = [0.55 / 1.05, 0.50 / 1.05]
    traded = abs(0.5 - drifted[0]) + abs(0.5 - drifted[1])
    assert earned.tolist() == pytest.approx([0.05 - 0.01 * 1.0, -0.01 * traded])


def test_the_vectorised_returns_are_those_of_a_naive_loop() -> None:
    rng = np.random.default_rng(3)
    raw = rng.random((40, 3))
    weights = raw[:, :2] / raw.sum(axis=1, keepdims=True)
    forward = rng.normal(0.0, 0.01, (40, 2))

    earned = proxy_returns(tensor(weights), tensor(forward), cost_rate=0.001)

    assert earned.tolist() == pytest.approx(naive_proxy_returns(weights, forward, 0.001))


def test_without_costs_the_returns_compound_to_a_simulation_on_the_same_opens() -> None:
    """Fractional shares, no fee, weights reached at each open: the proxy is exact there."""
    rng = np.random.default_rng(11)
    opens = 100.0 * np.cumprod(1.0 + rng.normal(0.0, 0.01, (31, 2)), axis=0)
    raw = rng.random((30, 3))
    weights = raw[:, :2] / raw.sum(axis=1, keepdims=True)
    forward = opens[1:] / opens[:-1] - 1.0

    # The reference: a book rebalanced to the weights at each open, in units.
    equity = 1.0
    for step in range(30):
        units = equity * weights[step] / opens[step]
        cash = equity * (1.0 - weights[step].sum())
        equity = float(units @ opens[step + 1]) + cash

    earned = proxy_returns(tensor(weights), tensor(forward), cost_rate=0.0)

    assert float(torch.prod(1.0 + earned)) == pytest.approx(equity)


def test_the_objective_is_the_annualised_mean_less_the_variance_penalty() -> None:
    returns = [0.01, -0.02, 0.03, 0.00]

    value = risk_adjusted_objective(tensor(returns), risk_aversion=5.0, annualization=252)

    expected = 252 * np.mean(returns) - 2.5 * 252 * np.var(returns, ddof=1)
    assert value.item() == pytest.approx(expected)


def test_a_runtime_proposes_the_networks_weights_on_normalised_inputs(neural_artifact) -> None:
    runtime = neural_artifact.runtime()
    values = np.linspace(-0.5, 0.5, neural_artifact.config.input_size)
    scaled, clipped = neural_artifact.scaler.transform(values)

    weights, counted = runtime.propose(values)

    expected = runtime.model(torch.from_numpy(scaled).reshape(1, -1))[0]
    assert weights.tolist() == pytest.approx(expected.tolist())
    assert weights.sum() == pytest.approx(1.0)
    assert counted == clipped > 0
    assert not runtime.model.training


def test_a_runtime_refuses_a_broken_model_instead_of_proposing(neural_artifact) -> None:
    config = neural_artifact.config
    state = {
        name: torch.from_numpy(values.copy()) for name, values in neural_artifact.state.items()
    }
    state["output.bias"] = torch.full_like(state["output.bias"], float("nan"))
    broken = NeuralRuntime(config, state, neural_artifact.scaler)

    with pytest.raises(ValueError, match="not finite"):
        broken.propose(np.zeros(config.input_size))
    with pytest.raises(ValueError, match="fitted on 3"):
        NeuralRuntime(config, state, FeatureScaler(np.zeros(3), np.ones(3), 5.0))
    with pytest.raises(ValueError, match="fitted on 37"):
        broken.propose(np.zeros(5))
