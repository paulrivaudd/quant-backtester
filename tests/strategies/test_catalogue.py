"""The catalogue: every kept strategy has one code, one label, and carries them."""

from __future__ import annotations

import dataclasses

import pytest

from quant_backtester.strategies import BuyAndHold, ETFEnsemble, WorldMA20Benchmark
from quant_backtester.strategies.base import Strategy
from quant_backtester.strategies.catalogue import (
    CATALOGUE,
    CatalogueEntry,
    Family,
    entry,
    entry_of,
    family,
)


def test_a_code_gives_the_three_spellings_of_a_name() -> None:
    first = entry("SA1")

    assert first.display_name == "SA1 - std MA20"
    assert first.strategy_id == "SA1_std_ma20"
    assert first.slug == "sa1_std_ma20"
    assert entry("ML1").display_name == "ML1 - neural allocation"
    with pytest.raises(KeyError, match="SA99"):
        entry("SA99")


def test_the_statistical_rules_are_sa1_to_sa11_and_the_network_is_ml1() -> None:
    assert [item.code for item in family(Family.SA)] == [f"SA{n}" for n in range(1, 12)]
    assert entry("SA11").display_name == "SA11 - GARCH vol control"
    assert [item.code for item in family(Family.ML)] == ["ML1"]
    assert len({item.strategy_id for item in CATALOGUE}) == len(CATALOGUE)
    assert entry_of(WorldMA20Benchmark).code == "SA1"
    assert entry_of(ETFEnsemble(enable_factors=False, enable_monetary=False)).code == "SA10"
    with pytest.raises(KeyError, match="not in the catalogue"):
        entry_of(BuyAndHold)


@pytest.mark.parametrize("item", family(Family.SA), ids=lambda item: item.code)
def test_a_rule_based_strategy_is_recorded_under_its_catalogue_id(item: CatalogueEntry) -> None:
    kind = item.load()

    assert issubclass(kind, Strategy)
    defaults = {field.name: field.default for field in dataclasses.fields(kind)}  # type: ignore[arg-type]
    assert defaults["strategy_id"] == item.strategy_id
    assert entry_of(kind) is item


def test_the_neural_strategy_is_recorded_under_its_catalogue_id() -> None:
    pytest.importorskip("torch")
    from quant_backtester.strategies.ml.neural_allocation import STRATEGY_ID

    assert entry("ML1").strategy_id == STRATEGY_ID
    assert entry("ML1").load().__name__ == "NeuralAllocationStrategy"


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"number": 0}, "positive integer"),
        ({"label": ""}, "label"),
        ({"label": "smooth  MA"}, "label"),
        ({"label": "50/50"}, "label"),
        ({"target": "no_class_here"}, "module:Class"),
    ],
)
def test_an_entry_that_cannot_be_named_is_refused(changes, message) -> None:
    fields = {"family": Family.SA, "number": 1, "label": "std MA20", "target": "a.b:C"}

    with pytest.raises(ValueError, match=message):
        CatalogueEntry(**(fields | changes))


def test_a_target_that_is_not_a_strategy_is_refused_when_loaded() -> None:
    with pytest.raises(TypeError, match="not a Strategy"):
        CatalogueEntry(Family.SA, 1, "x", "pathlib:Path").load()
