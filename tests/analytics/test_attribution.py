"""Where the gap between the two books went, and what a run had to make do on."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from quant_backtester.analytics.attribution import CostAttribution, RunQuality
from quant_backtester.backtest.engine import BacktestResult

RunBuilder = Callable[..., BacktestResult]


def test_the_two_terms_are_added_up_and_kept_apart(run: RunBuilder) -> None:
    """A commission and a spread are not the same problem, so they are not one number.

    Sixty-five cheap rebalancings and one expensive trade cost the same and
    call for opposite fixes; only the split says which happened.
    """
    result = run(
        [100.0, 99.0, 98.0],
        commission=[0.0, 1.0, 2.0],
        market_cost=[0.0, 0.5, 0.25],
    )

    costs = CostAttribution.of(result)

    assert costs.commission == pytest.approx(3.0)
    assert costs.market_cost == pytest.approx(0.75)
    assert costs.total == pytest.approx(3.75)


def test_the_drag_is_the_distance_between_the_two_books(run: RunBuilder) -> None:
    """The costs, in the unit a return is read in."""
    result = run([100.0, 112.0], gross=[100.0, 117.0])

    assert CostAttribution.of(result).drag == pytest.approx(0.05)


def test_the_share_of_the_gross_return_the_costs_took(run: RunBuilder) -> None:
    """Seventeen gross, twelve net: costs took five of the seventeen."""
    result = run([100.0, 112.0], gross=[100.0, 117.0])

    assert CostAttribution.of(result).cost_share_of_gross == pytest.approx(5.0 / 17.0)


def test_a_losing_gross_book_has_no_such_share(run: RunBuilder) -> None:
    """A percentage of a loss reads like a good number and means nothing."""
    result = run([100.0, 88.0], gross=[100.0, 90.0])

    assert CostAttribution.of(result).cost_share_of_gross is None


def test_only_the_sessions_that_traded_are_rebalancings(run: RunBuilder) -> None:
    """A strategy that keeps its book pays nothing on the sessions it does nothing."""
    result = run(
        [100.0, 100.0, 100.0, 100.0],
        traded_value=[0.0, 50.0, 0.0, 30.0],
        commission=[0.0, 1.0, 0.0, 1.0],
    )

    costs = CostAttribution.of(result)

    assert costs.rebalancings == 2
    assert costs.average_cost_per_rebalancing == pytest.approx(1.0)


def test_a_run_that_never_traded_has_no_average(run: RunBuilder) -> None:
    """Dividing by no rebalancing would be a number about nothing."""
    costs = CostAttribution.of(run([100.0, 101.0]))

    assert costs.rebalancings == 0
    assert costs.average_cost_per_rebalancing is None
    assert costs.turnover == 0.0


def test_turnover_is_what_changed_hands_against_what_was_held(run: RunBuilder) -> None:
    """A book of 100 that exchanged 200 turned over twice."""
    result = run([100.0, 100.0, 100.0], traded_value=[0.0, 100.0, 100.0])

    costs = CostAttribution.of(result)

    assert costs.turnover == pytest.approx(2.0)
    assert costs.annual_turnover == pytest.approx(2.0 * 365.25 / 2)


def test_turnover_a_year_needs_a_run_that_covers_time(run: RunBuilder) -> None:
    """One session is not a rate."""
    assert CostAttribution.of(run([100.0], traded_value=[10.0])).annual_turnover is None


def test_a_run_says_where_it_was_stretched(run: RunBuilder) -> None:
    """The caveats belong beside the figures, not in a log nobody opens."""
    result = run(
        [100.0, 100.0, 100.0],
        priced_from_earlier=[(), ("ETF_EU",), ()],
        untradable=[(), (), ("IDX_US",)],
    )

    quality = RunQuality.of(result)

    assert quality.sessions == 3
    assert quality.estimated_valuations == 1
    assert quality.untradable_sessions == 1
    assert quality.sessions_with_nothing_to_choose == 0


def test_a_run_with_nothing_to_choose_from_is_not_a_flat_strategy(run: RunBuilder) -> None:
    """A universe that went empty is a data hole, and reads as one."""
    quality = RunQuality.of(run([100.0, 100.0], considered=0))

    assert quality.sessions_with_nothing_to_choose == 2


def test_a_book_that_ended_on_borrowed_cash_is_counted(run: RunBuilder) -> None:
    """A target of a whole book overspends it by what execution charged.

    The order is sized on the reference price and filled at a worse one, so the
    difference is borrowed and no interest is ever charged on it. It is a
    property of the execution model rather than of a report, and a report that
    hid it would let it compound unseen.
    """
    result = run([100.0, 100.0, 100.0], cash=[0.0, -30.02, -30.02])

    assert RunQuality.of(result).sessions_on_borrowed_cash == 2


def test_rounding_dust_is_not_an_overdraft(run: RunBuilder) -> None:
    """A cash balance of minus a billionth is a float, not a loan."""
    assert RunQuality.of(run([100.0], cash=[-1e-12])).sessions_on_borrowed_cash == 0


def test_a_purchase_the_cash_could_not_carry_is_a_caveat(run: RunBuilder) -> None:
    """Expected on the session a strategy goes fully invested, and telling in bulk.

    One session is the entry paying for itself. A run where most sessions are
    here is a strategy asking, day after day, for more than it holds.
    """
    result = run([100.0, 100.0, 100.0], unfunded=[(), ("ETF_EU",), ()])

    assert RunQuality.of(result).unfunded_sessions == 1
