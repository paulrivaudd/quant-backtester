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

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "quant_backtester"
"""Source of the package, read rather than imported."""

SIGNALS = PACKAGE / "signals"
"""Source of the signals layer."""

STRATEGIES = PACKAGE / "strategies"
"""Source of the strategies layer."""

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
