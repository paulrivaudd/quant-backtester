"""Where the difference between the gross and the net book went.

A report that says a strategy returned twelve percent net against seventeen
gross has already said the interesting thing; what it has not said is why. Five
points can be one expensive trade, or sixty-five cheap rebalancings, or a
commission floor that a small book pays on every line it touches. Those are
three different strategies and three different fixes, and only the split tells
them apart.

The engine records a commission and a market cost per session, the second being
the spread and the slippage together - it is the sum that the fill price moves
by, so the two cannot be separated after the fact. They are reported as the two
terms that exist rather than as three that would be invented.
"""

from __future__ import annotations

from dataclasses import dataclass

from quant_backtester.analytics.curves import Book, elapsed_years, equity_curve
from quant_backtester.backtest.engine import BacktestResult

_CASH_DUST = 1e-9
"""Below this, a negative cash balance is rounding and not a loan."""


@dataclass(frozen=True, slots=True)
class CostAttribution:
    """What execution took over a run, and what it was taken on.

    Attributes
    ----------
    commission : float
        Paid to the broker over the whole run, in currency units.
    market_cost : float
        Paid to the market over the whole run: the half spread and the
        slippage, which the fill price moves by together.
    total : float
        The two of them.
    drag : float
        Gross return minus net return, as a fraction. What the costs cost, in
        the units a return is read in.
    traded_value : float
        Value exchanged over the run, both directions counted.
    turnover : float
        Traded value over the average equity of the run. A turnover of two is
        a book that changed hands twice, counting a sell and the buy that
        replaces it as two.
    annual_turnover : float | None
        The same, per year of calendar time. ``None`` for a run that covers no
        time to speak of.
    rebalancings : int
        Sessions on which something was actually traded.
    average_cost_per_rebalancing : float | None
        ``total`` over ``rebalancings``, and ``None`` when nothing traded. The
        number that says whether a commission floor is doing the damage.
    cost_share_of_gross : float | None
        The drag as a share of the gross return, when that return is positive:
        the fraction of what the strategy earned that never reached its
        holder. ``None`` when the gross book lost money, where the ratio would
        read as a percentage of a loss and mean nothing.
    """

    commission: float
    market_cost: float
    total: float
    drag: float
    traded_value: float
    turnover: float
    annual_turnover: float | None
    rebalancings: int
    average_cost_per_rebalancing: float | None
    cost_share_of_gross: float | None

    @classmethod
    def of(cls, result: BacktestResult) -> CostAttribution:
        """Take a run apart into what it paid and what it paid it on.

        Parameters
        ----------
        result : BacktestResult
            A finished run.

        Returns
        -------
        CostAttribution
            The split, over the whole run.
        """
        commission = sum(record.commission for record in result.records)
        market_cost = sum(record.market_cost for record in result.records)
        traded_value = sum(record.traded_value for record in result.records)
        rebalancings = sum(1 for record in result.records if record.traded_value > 0.0)
        equity = equity_curve(result, Book.NET)
        average_equity = float(equity.mean()) if not equity.empty else 0.0
        years = elapsed_years(equity.index)
        turnover = traded_value / average_equity if average_equity > 0.0 else 0.0
        gross_return = result.gross_return
        return cls(
            commission=commission,
            market_cost=market_cost,
            total=commission + market_cost,
            drag=gross_return - result.net_return,
            traded_value=traded_value,
            turnover=turnover,
            annual_turnover=turnover / years if years > 0.0 else None,
            rebalancings=rebalancings,
            average_cost_per_rebalancing=(
                (commission + market_cost) / rebalancings if rebalancings else None
            ),
            cost_share_of_gross=(
                (gross_return - result.net_return) / gross_return if gross_return > 0.0 else None
            ),
        )


@dataclass(frozen=True, slots=True)
class RunQuality:
    """How much of a run rests on something other than a printed price.

    A performance figure is only as good as the prices it was valued at, and a
    run tells you where it was stretched. These counts are not statistics about
    the strategy: they are the caveats a result has to be read with, and they
    belong beside it rather than in a log nobody opens.

    Attributes
    ----------
    sessions : int
        Sessions the run walked.
    estimated_valuations : int
        Sessions where at least one held instrument had no price of its own
        and was valued at an older close. The equity of those sessions is an
        estimate, and so is every statistic computed across them.
    untradable_sessions : int
        Sessions where an order was not sent because no opening price was
        knowable. The book stayed as it was, which is the honest outcome and
        also a difference from what the strategy asked for.
    sessions_with_nothing_to_choose : int
        Sessions where the strategy had no instrument with a usable signal.
        A run full of them is not a flat strategy, it is a data hole.
    sessions_on_borrowed_cash : int
        Sessions the book ended with less than no cash. An order is sized on
        the reference price and filled at a worse one, so a target of a whole
        book overspends it by what execution charged: the difference is
        borrowed, and nothing in the model charges interest on it. Small on one
        entry, and not small for a strategy that rebalances every week. Counted
        here rather than corrected, because correcting it means changing how an
        order is sized, which is a decision about the execution model and not
        about a report.
    """

    sessions: int
    estimated_valuations: int
    untradable_sessions: int
    sessions_with_nothing_to_choose: int
    sessions_on_borrowed_cash: int

    @classmethod
    def of(cls, result: BacktestResult) -> RunQuality:
        """Count the sessions a run had to make do on.

        Parameters
        ----------
        result : BacktestResult
            A finished run.

        Returns
        -------
        RunQuality
            The caveats, counted.
        """
        return cls(
            sessions=len(result.records),
            estimated_valuations=sum(1 for r in result.records if r.priced_from_earlier),
            untradable_sessions=sum(1 for r in result.records if r.untradable),
            sessions_with_nothing_to_choose=sum(1 for r in result.records if r.considered == 0),
            # A hair below zero, so that floating-point dust is not an overdraft.
            sessions_on_borrowed_cash=sum(1 for r in result.records if r.cash < -_CASH_DUST),
        )
