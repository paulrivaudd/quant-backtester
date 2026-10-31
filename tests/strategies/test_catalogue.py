"""The catalogue: every kept strategy has one code, one label, and carries them."""

from __future__ import annotations

import dataclasses

import pytest

from quant_backtester.research.references import BuyAndHold
from quant_backtester.strategies import SA15GPT61, ETFEnsemble, WorldMA20Benchmark
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


def test_the_catalogue_runs_from_sa1_to_sa16_and_names_the_one_that_needs_an_extra() -> None:
    assert [item.code for item in family(Family.SA)] == [f"SA{n}" for n in range(1, 17)]
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
        ({"recorded_id": ""}, "recorded_id"),
        ({"recorded_id": "   "}, "recorded_id"),
        ({"recorded_id": True}, "recorded_id"),
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


def test_explicit_recorded_id_preserves_the_requested_sa15_name() -> None:
    item = entry("SA15")

    assert item.display_name == "SA15 - GPT 6 1"
    assert item.recorded_id == "SA15_GPT-6.1"
    assert item.strategy_id == SA15GPT61().strategy_id == "SA15_GPT-6.1"
    assert item.slug == "sa15_gpt-6.1"
    assert item.load() is SA15GPT61
    assert entry_of(SA15GPT61) is item


def test_recorded_id_override_does_not_change_the_display_name() -> None:
    item = CatalogueEntry(Family.SA, 1, "readable label", "a.b:C", recorded_id="SA1-kept.id")

    assert item.strategy_id == "SA1-kept.id"
    assert item.display_name == "SA1 - readable label"
    assert item.slug == "sa1-kept.id"


def test_sa16_is_the_growth_gold_risk_budget() -> None:
    from quant_backtester.strategies.SA16_risk_budget import SA16RiskBudget

    item = entry("SA16")
    assert item.display_name == "SA16 - growth gold budget"
    assert item.strategy_id == SA16RiskBudget().strategy_id == "SA16_growth_gold_budget"
    assert item.load() is SA16RiskBudget
    assert entry_of(SA16RiskBudget) is item
