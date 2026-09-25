"""The three costs, each behaving like itself, and each kept apart."""

from __future__ import annotations

import pytest

from quant_backtester.execution.costs import CostBreakdown, CostModel
from quant_backtester.execution.orders import Side


def test_a_buy_pays_more_than_the_screen_and_a_sale_receives_less() -> None:
    """The spread is not a fee: it is the price being somewhere else."""
    model = CostModel(half_spread_rate=0.001)

    assert model.fill_price(Side.BUY, 100.0) == pytest.approx(100.1)
    assert model.fill_price(Side.SELL, 100.0) == pytest.approx(99.9)


def test_the_spread_and_the_slippage_add_up() -> None:
    """Both move the fill the same way; naming them apart keeps them arguable."""
    model = CostModel(half_spread_rate=0.001, slippage_rate=0.0005)

    assert model.fill_price(Side.BUY, 200.0) == pytest.approx(200.0 * 1.0015)


def test_a_round_trip_crosses_the_spread_twice() -> None:
    """Which is why the parameter is a half spread and not a whole one."""
    model = CostModel(half_spread_rate=0.002)

    bought = model.fill_price(Side.BUY, 50.0)
    sold = model.fill_price(Side.SELL, 50.0)

    assert (bought - sold) / 50.0 == pytest.approx(0.004)


def test_a_model_with_no_costs_fills_on_the_screen() -> None:
    """Free when declared free, so a cost in a report came from a declared term."""
    assert CostModel().fill_price(Side.BUY, 123.45) == 123.45
    assert CostModel().commission(10_000.0) == 0.0


def test_the_commission_is_a_rate_until_the_floor_bites() -> None:
    """The floor is what makes a small rebalancing trade uneconomic.

    A backtest with a pure rate never shows that, and happily rebalances by a
    few currency units every day.
    """
    model = CostModel(commission_rate=0.001, minimum_commission=5.0)

    assert model.commission(100_000.0) == pytest.approx(100.0)
    assert model.commission(1_000.0) == pytest.approx(5.0)


def test_an_order_of_nothing_pays_nothing() -> None:
    """No order was sent, so no floor applies."""
    assert CostModel(minimum_commission=5.0).commission(0.0) == 0.0


@pytest.mark.parametrize("price", [0.0, -1.0, float("nan")])
def test_a_fill_needs_a_positive_market_price(price: float) -> None:
    """A price of zero is not a price this model can move."""
    with pytest.raises(ValueError, match="the market price"):
        CostModel().fill_price(Side.BUY, price)


@pytest.mark.parametrize(
    "overrides",
    [
        {"commission_rate": -0.001},
        {"half_spread_rate": -0.001},
        {"slippage_rate": -0.001},
        {"minimum_commission": -1.0},
    ],
    ids=["commission", "spread", "slippage", "floor"],
)
def test_a_negative_cost_is_refused(overrides: dict[str, float]) -> None:
    """A cost that pays the trader is a sign flipped somewhere."""
    with pytest.raises(ValueError, match="not be negative"):
        CostModel(**overrides)


@pytest.mark.parametrize(
    "overrides",
    [{"commission_rate": 1.0}, {"half_spread_rate": 2.5}, {"slippage_rate": 10.0}],
    ids=["commission", "spread", "slippage"],
)
def test_a_percentage_written_as_one_is_refused(overrides: dict[str, float]) -> None:
    """``10`` meant as ten percent would take ten times every trade."""
    with pytest.raises(ValueError, match="fraction, not a percentage"):
        CostModel(**overrides)


@pytest.mark.parametrize(
    "overrides",
    [
        {"commission_rate": float("nan")},
        {"half_spread_rate": float("inf")},
        {"slippage_rate": float("-inf")},
        {"minimum_commission": float("nan")},
    ],
    ids=["commission", "spread", "slippage", "floor"],
)
def test_a_cost_that_is_not_a_finite_number_is_refused(overrides: dict[str, float]) -> None:
    """NaN passes every ``<`` and every ``>=``, then charges NaN on every trade."""
    with pytest.raises(ValueError, match="must be a finite number"):
        CostModel(**overrides)


@pytest.mark.parametrize(
    "overrides",
    [{"commission_rate": True}, {"minimum_commission": "1.0"}],
    ids=["boolean", "string"],
)
def test_a_cost_that_is_not_a_number_is_refused(overrides: dict[str, object]) -> None:
    """``True`` is an ``int`` to Python, and would charge the whole trade."""
    with pytest.raises(ValueError, match="must be a number"):
        CostModel(**overrides)  # type: ignore[arg-type]


def test_a_spread_and_a_slippage_that_together_reach_the_price_are_refused() -> None:
    """Each is a legal fraction on its own, and the fill price pays both.

    At 0.6 and 0.6 a sale would be done at minus twenty percent of the price on
    the screen: the book would pay to sell, which is not a cost model but a
    parameter written in the wrong units.
    """
    with pytest.raises(ValueError, match="come to"):
        CostModel(half_spread_rate=0.6, slippage_rate=0.6)


def test_a_sale_is_never_done_at_a_price_of_zero_or_less() -> None:
    """The guard above is what makes this true for every pair that is accepted."""
    model = CostModel(half_spread_rate=0.5, slippage_rate=0.49)

    assert model.fill_price(Side.SELL, 100.0) > 0.0


def test_the_breakdown_of_a_purchase_checks_by_hand() -> None:
    """Ten units at 100, ten basis points of commission, twenty of spread, ten of slippage.

    The fill is at 100.3; the commission is charged on the value at the fill
    price, 1003, so 1.003; the spread is 10 x 100 x 0.002 = 2 and the slippage
    10 x 100 x 0.001 = 1. Everything the trade cost is their sum.
    """
    model = CostModel(commission_rate=0.001, half_spread_rate=0.002, slippage_rate=0.001)

    costs = model.breakdown(Side.BUY, 10.0, 100.0)

    assert costs.commission == pytest.approx(1.003)
    assert costs.spread_cost == pytest.approx(2.0)
    assert costs.slippage_cost == pytest.approx(1.0)
    assert costs.market_cost == pytest.approx(3.0)
    assert costs.total == pytest.approx(4.003)


def test_the_breakdown_of_a_sale_charges_the_same_terms() -> None:
    """A sale pays the spread and the slippage too, and the commission on less."""
    model = CostModel(commission_rate=0.001, half_spread_rate=0.002, slippage_rate=0.001)

    costs = model.breakdown(Side.SELL, 10.0, 100.0)

    assert costs.commission == pytest.approx(0.997)
    assert costs.spread_cost == pytest.approx(2.0)
    assert costs.slippage_cost == pytest.approx(1.0)


def test_the_floor_applies_inside_the_breakdown() -> None:
    """A small trade pays the floor, which is the point of declaring one."""
    costs = CostModel(commission_rate=0.001, minimum_commission=5.0).breakdown(Side.BUY, 1.0, 100.0)

    assert costs.commission == 5.0


@pytest.mark.parametrize("quantity", [0.0, -1.0])
def test_a_breakdown_of_nothing_is_refused(quantity: float) -> None:
    """No order of no units is ever costed: it would never have been sent."""
    with pytest.raises(ValueError, match="quantity"):
        CostModel().breakdown(Side.BUY, quantity, 100.0)


@pytest.mark.parametrize("field", ["commission", "spread_cost", "slippage_cost"])
def test_a_cost_that_pays_the_trader_is_refused(field: str) -> None:
    """A negative term is a sign convention gone wrong."""
    terms = {"commission": 0.0, "spread_cost": 0.0, "slippage_cost": 0.0, field: -1.0}

    with pytest.raises(ValueError, match=field):
        CostBreakdown(**terms)


def test_a_traded_value_that_is_not_a_value_is_refused() -> None:
    """A commission on NaN would charge NaN."""
    with pytest.raises(ValueError, match="traded value"):
        CostModel(commission_rate=0.001).commission(float("nan"))


def test_the_model_describes_itself_for_the_record() -> None:
    """A result says which costs it was charged, term by term."""
    model = CostModel(commission_rate=0.0005, minimum_commission=1.0, half_spread_rate=0.0002)

    assert model.definition() == {
        "commission_rate": 0.0005,
        "minimum_commission": 1.0,
        "half_spread_rate": 0.0002,
        "slippage_rate": 0.0,
    }
