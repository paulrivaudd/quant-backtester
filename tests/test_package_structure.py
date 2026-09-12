"""Smoke tests: the package layout imports cleanly and stays layered."""

from __future__ import annotations

import importlib

import pytest

LAYERS = [
    "data",
    "signals",
    "portfolio",
    "execution",
    "backtest",
    "analytics",
    "strategies",
]


def test_package_exposes_version():
    package = importlib.import_module("quant_backtester")
    assert package.__version__


@pytest.mark.parametrize("layer", LAYERS)
def test_layer_is_importable(layer):
    module = importlib.import_module(f"quant_backtester.{layer}")
    assert module.__doc__, f"{layer} must document its responsibility"
