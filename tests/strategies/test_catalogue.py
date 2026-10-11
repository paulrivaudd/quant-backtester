"""The catalogue: every kept strategy has one code, one label, and carries them."""

from __future__ import annotations

import dataclasses

import pytest

from quant_backtester.research.references import BuyAndHold
from quant_backtester.strategies import ETFEnsemble, WorldMA20Benchmark
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
    assert entry("SA14").display_name == "SA14 - neural allocation"
    with pytest.raises(KeyError, match="SA99"):
        entry("SA99")


def test_the_catalogue_runs_from_sa1_to_sa14_and_names_the_one_that_needs_an_extra() -> None:
    assert [item.code for item in family(Family.SA)] == [f"SA{n}" for n in range(1, 15)]
    assert family(Family.SA) == CATALOGUE
    assert [(item.code, item.extra) for item in CATALOGUE if item.extra] == [("SA14", "ml")]
    assert entry("SA13").display_name == "SA13 - Signatures Neurons"
    assert entry("SA12").display_name == "SA12 - ARIMA GARCH"
    assert entry("SA11").display_name == "SA11 - GARCH vol control"
    # The network was ML1 until 2026-10-11: that code is retired, not given again.
    with pytest.raises(KeyError, match="ML1"):
        entry("ML1")
    assert len({item.strategy_id for item in CATALOGUE}) == len(CATALOGUE)
    assert entry_of(WorldMA20Benchmark).code == "SA1"
    assert entry_of(ETFEnsemble(enable_factors=False, enable_monetary=False)).code == "SA10"
    with pytest.raises(KeyError, match="not in the catalogue"):
        entry_of(BuyAndHold)


@pytest.mark.parametrize(
    "item", [item for item in CATALOGUE if item.extra is None], ids=lambda item: item.code
)
def test_a_strategy_that_needs_no_extra_is_recorded_under_its_catalogue_id(
    item: CatalogueEntry,
) -> None:
    kind = item.load()

    assert issubclass(kind, Strategy)
    defaults = {field.name: field.default for field in dataclasses.fields(kind)}  # type: ignore[arg-type]
    assert defaults["strategy_id"] == item.strategy_id
    assert entry_of(kind) is item


def test_the_neural_strategy_is_recorded_under_its_catalogue_id() -> None:
    pytest.importorskip("torch")
    from quant_backtester.strategies.SA14_neural_allocation import STRATEGY_ID

    assert entry("SA14").strategy_id == STRATEGY_ID
    assert entry("SA14").load().__name__ == "NeuralAllocationStrategy"


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
