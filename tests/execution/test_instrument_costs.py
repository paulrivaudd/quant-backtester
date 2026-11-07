"""Instrument cost overrides apply to sizing, fills and cash constraints."""

from __future__ import annotations

import copy
import json
import pickle

import pytest
from tests.execution.test_model import book, reasons, trade

from quant_backtester.execution.costs import CostModel
from quant_backtester.execution.fills import ExecutionRejectReason
from quant_backtester.execution.model import ExecutionModel, Sizing


@pytest.mark.parametrize(
    "overrides", [{1: CostModel()}, {"": CostModel()}, {" ": CostModel()}, {"A": 1}, None, []]
)
def test_invalid_overrides(overrides) -> None:
    with pytest.raises(ValueError, match="costs_by_instrument"):
        ExecutionModel(CostModel(), costs_by_instrument=overrides)


def test_override_copy_is_frozen_and_definition_is_sorted() -> None:
    overrides = {"B": CostModel(minimum_commission=2), "A": CostModel()}
    model = ExecutionModel(CostModel(), costs_by_instrument=overrides)
    overrides.clear()
    definition = model.definition()["costs_by_instrument"]
    assert isinstance(definition, dict)
    assert list(definition) == ["A", "B"]
    with pytest.raises(TypeError):
        model.costs_by_instrument["A"] = CostModel(minimum_commission=5)  # pyright: ignore[reportIndexIssue] -- test immutability
    assert definition["B"] == CostModel(minimum_commission=2).definition()


@pytest.mark.parametrize("sizing", list(Sizing))
def test_empty_overrides_preserve_definition_and_execution(sizing) -> None:
    costs = CostModel(commission_rate=0.01, minimum_commission=3, half_spread_rate=0.02)
    legacy = ExecutionModel(costs, sizing=sizing)
    empty = ExecutionModel(costs, sizing=sizing, costs_by_instrument={})
    expected = {
        "fill_model": "OPEN_AUCTION_NOTIONAL"
        if sizing is Sizing.AT_AUCTION
        else "DECISION_CLOSE_QUANTITIES",
        "fill": "market order at the opening auction, sized at its price",
        "costs": costs.definition(),
        "minimum_trade_value": 0.0,
    }
    assert json.dumps(empty.definition()) == json.dumps(expected)
    args = (book(1000, A=2), {"B": 1.0}, {"A": 100.0, "B": 50.0})
    closes = {"A": 90.0, "B": 45.0}
    assert trade(legacy, *args, decision_closes=closes) == trade(
        empty, *args, decision_closes=closes
    )
    uniform = ExecutionModel(costs, sizing=sizing, costs_by_instrument={"A": costs, "B": costs})
    assert trade(legacy, *args, decision_closes=closes) == trade(
        uniform, *args, decision_closes=closes
    )


def test_heterogeneous_buy_and_sell_costs_with_global_fallback() -> None:
    model = ExecutionModel(
        CostModel(minimum_commission=2),
        costs_by_instrument={
            "A": CostModel(commission_rate=0.01, half_spread_rate=0.1, slippage_rate=0.02)
        },
    )
    bought = trade(model, book(1000), {"A": 0.4, "B": 0.4}, {"A": 100.0, "B": 100.0})
    a, b = bought.fills
    assert a.quantity == pytest.approx(400 / 112)
    assert a.commission == pytest.approx(4)
    assert a.spread_cost == pytest.approx(a.quantity * 10)
    assert a.slippage_cost == pytest.approx(a.quantity * 2)
    assert b.quantity == 4
    assert b.commission == 2
    assert bought.state.cash == pytest.approx(194)
    sold = trade(model, bought.state, {}, {"A": 100.0, "B": 100.0})
    a, b = sold.fills
    assert a.cash_flow == pytest.approx(a.quantity * 88 * 0.99)
    assert b.cash_flow == 398


@pytest.mark.parametrize("step_names", [("A", "B"), ("W", "V")])
def test_shared_cash_scaling_pays_each_commission(step_names) -> None:
    first, second = step_names
    model = ExecutionModel(
        CostModel(),
        costs_by_instrument={
            first: CostModel(minimum_commission=100),
            second: CostModel(commission_rate=0.1),
        },
    )
    result = trade(model, book(1000), {first: 0.5, second: 0.5}, {first: 100.0, second: 100.0})
    expected = 900 / 210 if first == "A" else 4
    assert result.state.quantity(first) == pytest.approx(expected)
    assert result.state.quantity(second) == pytest.approx(expected)
    assert result.state.cash >= 0
    assert set(reasons(result).values()) == {ExecutionRejectReason.INSUFFICIENT_CASH}
    assert result.commission == pytest.approx(100 + expected * 10)


@pytest.mark.parametrize("sizing", list(Sizing))
def test_cash_share_budget_includes_override_and_opening_gap(sizing) -> None:
    model = ExecutionModel(
        CostModel(),
        sizing=sizing,
        costs_by_instrument={"W": CostModel(minimum_commission=30, half_spread_rate=0.1)},
    )
    result = trade(
        model,
        book(1000),
        {"W": 0.5},
        {"W": 100.0},
        cash_shares={"W": 0.5},
        decision_closes={"W": 50.0},
    )
    assert result.state.quantity("W") == 4
    assert result.state.cash == pytest.approx(530)
    if sizing is Sizing.AT_DECISION:
        assert reasons(result)["W"] is ExecutionRejectReason.CASH_SHARE_BUDGET


def test_sale_rejected_when_override_floor_exceeds_proceeds() -> None:
    model = ExecutionModel(
        CostModel(), costs_by_instrument={"A": CostModel(minimum_commission=101)}
    )
    result = trade(model, book(0, A=1), {}, {"A": 100.0})
    assert not result.fills
    assert result.state.quantity("A") == 1
    assert reasons(result)["A"] is ExecutionRejectReason.INSUFFICIENT_CASH


def test_override_spread_controls_minimum_sale_value() -> None:
    model = ExecutionModel(
        CostModel(),
        minimum_trade_value=95,
        costs_by_instrument={"A": CostModel(half_spread_rate=0.1)},
    )
    result = trade(model, book(0, A=1, B=1), {}, {"A": 100.0, "B": 100.0})
    assert [fill.instrument_id for fill in result.fills] == ["B"]
    assert reasons(result)["A"] is ExecutionRejectReason.BELOW_MINIMUM_TRADE


def test_scaled_purchase_minimum_uses_override_fill_price() -> None:
    model = ExecutionModel(
        CostModel(),
        minimum_trade_value=105,
        costs_by_instrument={"W": CostModel(minimum_commission=30, half_spread_rate=0.1)},
    )
    result = trade(model, book(249), {"W": 1.0}, {"W": 100.0})
    assert result.state.quantity("W") == 1
    assert result.state.cash == pytest.approx(109)


def test_a_model_hashes_pickles_and_copies_by_value_with_or_without_overrides() -> None:
    # A model was hashable, picklable and deep-copyable before overrides
    # existed; the frozen view of the overrides must not take that away.
    costs = CostModel(commission_rate=0.001, minimum_commission=1.0)
    override = CostModel(half_spread_rate=0.002)
    for overrides in ({}, {"A": override}):
        model = ExecutionModel(costs, minimum_trade_value=5.0, costs_by_instrument=overrides)
        twin = ExecutionModel(costs, minimum_trade_value=5.0, costs_by_instrument=dict(overrides))
        assert hash(model) == hash(twin)
        for copied in (pickle.loads(pickle.dumps(model)), copy.deepcopy(model), copy.copy(model)):
            assert copied == model
            assert hash(copied) == hash(model)
            assert copied.definition() == model.definition()
            with pytest.raises(TypeError):
                copied.costs_by_instrument["B"] = override  # pyright: ignore[reportIndexIssue] -- still frozen
    assert ExecutionModel(costs) != ExecutionModel(costs, costs_by_instrument={"A": override})


def test_scaled_stresses_the_default_and_every_override() -> None:
    # replace(execution, costs=...) would leave every override at 1x.
    costs = CostModel(commission_rate=0.0005, minimum_commission=1.0, slippage_rate=0.0005)
    override = CostModel(
        commission_rate=0.0005,
        minimum_commission=1.0,
        half_spread_rate=0.0012,
        slippage_rate=0.0005,
    )
    model = ExecutionModel(
        costs,
        minimum_trade_value=10.0,
        sizing=Sizing.AT_DECISION,
        costs_by_instrument={"A": override},
    )
    stressed = model.scaled(2.0)
    assert stressed.costs == costs.scaled(2.0)
    assert stressed.costs_by_instrument["A"].definition() == pytest.approx(
        {
            term: 2 * value
            for term, value in override.definition().items()
            if isinstance(value, float)
        }
    )
    assert stressed.minimum_trade_value == model.minimum_trade_value
    assert stressed.sizing is model.sizing
    assert model.costs_by_instrument["A"] == override  # the original is untouched
    for factor in (0.0, -1.0, float("nan")):
        with pytest.raises(ValueError, match="factor"):
            model.scaled(factor)
