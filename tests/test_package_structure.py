"""Smoke tests: the package layout imports cleanly and stays layered.

The layering is a rule about dependencies, so it is checked as one. Reading a
module and finding no forbidden import is worth more than trusting that nobody
added one: an import of the repository into a signal would look harmless in a
diff, and would put a file read behind every number a strategy sees.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.backtest.market import StrategyMarketView

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "quant_backtester"
"""Source of the package, read rather than imported."""

SIGNALS = PACKAGE / "signals"
"""Source of the signals layer."""

STRATEGIES = PACKAGE / "strategies"
"""Source of the strategies layer."""

ANALYTICS = PACKAGE / "analytics"
"""Source of the analytics layer."""

FORBIDDEN_IN_SIGNALS = (
    "quant_backtester.data.sources",
    "quant_backtester.data.updater",
    "quant_backtester.data.repository",
    "quant_backtester.data.crosscheck",
    "quant_backtester.data.normalizer",
    "quant_backtester.data.validator",
    "quant_backtester.data.revisions",
)
"""What a signal must not reach for.

The store, the adapters and the ingestion. A signal's whole view of the market
is the point-in-time reader it is handed; anything else here would be a second
way in, with its own rules about what is visible when.
"""


def imported_modules(path: Path) -> set[str]:
    """Return every module name a file imports, dotted and absolute."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module)
    return names


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


@pytest.mark.parametrize("path", sorted(SIGNALS.rglob("*.py")), ids=lambda path: path.stem)
def test_signals_never_reach_past_the_reader(path: Path):
    """No module of the signals layer imports the store, an adapter or the updater."""
    forbidden = sorted(
        name
        for name in imported_modules(path)
        if any(name.startswith(banned) for banned in FORBIDDEN_IN_SIGNALS)
    )

    assert not forbidden, f"{path.name} imports {', '.join(forbidden)}"


def test_signals_import_no_network_library():
    """The layer downloads nothing, and cannot start to by accident."""
    network = {"urllib", "urllib.request", "requests", "httpx", "yfinance"}
    for path in SIGNALS.rglob("*.py"):
        assert not imported_modules(path) & network, f"{path.name} imports a network library"


@pytest.mark.parametrize("path", sorted(STRATEGIES.rglob("*.py")), ids=lambda path: path.stem)
def test_strategies_see_signals_and_nothing_below(path: Path):
    """A strategy reaches the market through the signals, or not at all.

    Given a reader it could write its own ``history(...).tail(20)`` and get
    twenty observations spanning twenty-six sessions - the one mistake the
    window loader exists to make impossible. Given a repository it could read a
    price nobody decided was knowable yet. So it is given neither: every import
    of the data layer is refused here, not only the ones the signals layer
    refuses.
    """
    reaching_down = sorted(
        name for name in imported_modules(path) if name.startswith("quant_backtester.data")
    )

    assert not reaching_down, f"{path.name} imports {', '.join(reaching_down)}"


@pytest.mark.parametrize("path", sorted(ANALYTICS.rglob("*.py")), ids=lambda path: path.stem)
def test_analytics_describes_a_finished_run_and_fetches_nothing(path: Path):
    """A report is a function of a run, not a second way into the market.

    Given a reader, a statistic could quietly be computed against prices the
    run never saw - a benchmark read at today's revision, a close the engine
    had not been handed - and nobody reading the number would know. So the
    layer is handed a finished result and nothing else.
    """
    reaching_down = sorted(
        name for name in imported_modules(path) if name.startswith("quant_backtester.data")
    )

    assert not reaching_down, f"{path.name} imports {', '.join(reaching_down)}"


def test_strategies_import_no_network_library():
    """A strategy that fetched a price would be reading today, not the decision's day.

    The layer above the reader is the one a user writes in, so it is the one
    where a stray ``yfinance`` import is most likely - and it would put the
    prices of this morning inside a decision dated years ago.
    """
    network = {"urllib", "urllib.request", "requests", "httpx", "yfinance"}
    for path in STRATEGIES.rglob("*.py"):
        assert not imported_modules(path) & network, f"{path.name} imports a network library"


def test_a_strategy_is_never_handed_the_reader():
    """The façade holds a reader; the API a strategy writes against must not expose it.

    Checked on the public surface rather than on the imports, because the
    context is built for the strategy rather than imported by it: what matters
    is that there is no attribute, property or method to reach it through.
    """
    surface = {
        name
        for owner in (StrategyContext, StrategyMarketView)
        for name in dir(owner)
        if not name.startswith("_")
    }

    assert "reader" not in surface
    assert "repository" not in surface
    assert "context" not in surface
    assert "at" not in surface


LAYER_RANK = {layer: rank for rank, layer in enumerate(LAYERS)}
"""Each layer's place in the one direction dependencies flow in."""

COMPOSITION_FACADES = {PACKAGE / "backtest" / "runner.py"}
"""Modules allowed to reach upwards, because composing the layers is their whole job.

The runner builds an engine, runs a strategy and hands back the report of it:
it imports the analytics that describe a run and the strategy contract that
produces one, and says so in its own docstring. Nothing else may.
"""


def _layer_of(module: str) -> str | None:
    """Return the layer a dotted module name belongs to, if it is one of ours."""
    parts = module.split(".")
    if len(parts) < 2 or parts[0] != "quant_backtester":
        return None
    return parts[1] if parts[1] in LAYER_RANK else None


@pytest.mark.parametrize(
    "path",
    sorted(path for layer in LAYERS for path in (PACKAGE / layer).rglob("*.py")),
    ids=lambda path: f"{path.parent.name}.{path.stem}",
)
def test_a_lower_layer_never_imports_a_higher_one(path: Path) -> None:
    """``data -> signals -> portfolio -> execution -> backtest -> analytics -> strategies``.

    A layer that needs something from above takes it as an argument. Checked on
    every module rather than trusted, because an upward import looks harmless in
    a diff and quietly turns the layering into a knot.
    """
    if path in COMPOSITION_FACADES:
        return
    own = path.relative_to(PACKAGE).parts[0]
    upwards = sorted(
        module
        for module in imported_modules(path)
        if (layer := _layer_of(module)) is not None and LAYER_RANK[layer] > LAYER_RANK[own]
    )
    assert not upwards, f"{path.relative_to(PACKAGE)} imports {', '.join(upwards)}"
