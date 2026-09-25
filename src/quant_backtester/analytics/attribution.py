"""Where the difference between the gross and the net book went, and what a run had to make do on.

A report that says a strategy returned twelve percent net against seventeen
gross has already said the interesting thing; what it has not said is why. Five
points can be one expensive trade, or sixty-five cheap rebalancings, or a
commission floor that a small book pays on every line it touches. Those are
three different strategies and three different fixes, and only the split tells
them apart - so the costs are reported as the three terms every fill records:
the broker's commission, the half spread paid to the market, and the slippage
an order's own impact cost.

The second half of this module counts the caveats: sessions valued on an older
price, orders refused and why, purchases cut for want of cash, days the book
held less than its target said. None of them is a statistic about the strategy;
all of them are what its statistics have to be read with.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from quant_backtester.analytics.curves import Book, elapsed_years, equity_curve
from quant_backtester.backtest.result import BacktestResult
from quant_backtester.execution.fills import ExecutionRejectReason


@dataclass(frozen=True, slots=True)
class CostAttribution:
    """What execution took over a run, and what it was taken on.

    Attributes
    ----------
    commission : float
        Paid to the broker over the whole run, in currency units.
    spread_cost : float
        Paid to the market for crossing half the spread.
    slippage_cost : float
        Lost to the orders' own impact.
    market_cost : float
        The spread and the slippage together: what the fill prices moved by.
    total : float
        Everything: commission, spread and slippage.
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
    spread_cost: float
    slippage_cost: float
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
        records = result.records
        commission = math.fsum(record.commission_cost for record in records)
        spread_cost = math.fsum(record.spread_cost for record in records)
        slippage_cost = math.fsum(record.slippage_cost for record in records)
        total = math.fsum(record.total_cost for record in records)
        traded_value = math.fsum(record.traded_value for record in records)
        rebalancings = sum(1 for record in records if record.fills)
        equity = equity_curve(result, Book.NET)
        average_equity = float(equity.mean()) if not equity.empty else 0.0
        years = elapsed_years(equity.index)
        turnover = traded_value / average_equity if average_equity > 0.0 else 0.0
        gross_return = result.gross_return
        return cls(
            commission=commission,
            spread_cost=spread_cost,
            slippage_cost=slippage_cost,
            market_cost=math.fsum(record.market_cost for record in records),
            total=total,
            drag=gross_return - result.net_return,
            traded_value=traded_value,
            turnover=turnover,
            annual_turnover=turnover / years if years > 0.0 else None,
            rebalancings=rebalancings,
            average_cost_per_rebalancing=total / rebalancings if rebalancings else None,
            cost_share_of_gross=(
                (gross_return - result.net_return) / gross_return if gross_return > 0.0 else None
            ),
        )


_NO_PRICE = frozenset(
    {ExecutionRejectReason.NO_EXECUTION_PRICE, ExecutionRejectReason.STALE_EXECUTION_PRICE}
)
"""The reasons that mean an order met no price it could be filled at."""


@dataclass(frozen=True, slots=True)
class RunQuality:
    """How much of a run rests on something other than a printed price and a filled order.

    A performance figure is only as good as the prices it was valued at and the
    trades it assumes, and a run tells you where it was stretched. These counts
    are not statistics about the strategy: they are the caveats a result has to
    be read with, and they belong beside it rather than in a log nobody opens.

    Attributes
    ----------
    sessions : int
        Sessions the run walked.
    decisions : int
        Sessions the strategy was asked on.
    estimated_valuations : int
        Sessions where at least one held position was valued at an older price
        than the session's own close. The equity of those sessions is an
        estimate, and so is every statistic computed across them.
    orders : int
        Orders the targets called for.
    fills : int
        Orders done, in full or in part.
    rejects : int
        Orders refused, or cut, with a reason - all reasons together.
    rejects_by_reason : Mapping[str, int]
        The same, per reason, for every reason that occurred.
    sessions_without_execution_price : int
        Sessions where an order met no opening price of its own session - none
        stored, or only an older one. The line stayed as it was, which is the
        honest outcome and also a difference from what the strategy asked for.
    insufficient_cash_adjustments : int
        Purchases cut down, or dropped, because the book did not hold the cash
        for them. A target of a whole book costs slightly more than the book is
        worth, so the session a strategy goes fully invested on is expected to
        appear; a run where most do is a strategy asking for more than it has.
    sessions_with_nothing_to_choose : int
        Sessions where the strategy was asked and had no instrument with a
        usable signal. A run full of them is not a flat strategy, it is a data
        hole. Counted among the sessions a decision was actually taken on: a
        strategy rebalancing monthly is not asked on the other twenty.
    sessions_partially_invested : int
        Sessions that ended without any of an instrument the target being
        traded towards asked for: a purchase refused, a price that did not
        print, a weight too small for one lot. What the book held was then a
        different portfolio from the one decided, and not just a rounding of
        it.
    average_cash_share : float | None
        Mean fraction of the book held in cash at the close. ``None`` for a run
        with no session.
    """

    sessions: int
    decisions: int
    estimated_valuations: int
    orders: int
    fills: int
    rejects: int
    rejects_by_reason: Mapping[str, int]
    sessions_without_execution_price: int
    insufficient_cash_adjustments: int
    sessions_with_nothing_to_choose: int
    sessions_partially_invested: int
    average_cash_share: float | None

    def __post_init__(self) -> None:
        """Freeze the counts by reason, in reason order."""
        object.__setattr__(
            self,
            "rejects_by_reason",
            MappingProxyType(
                {
                    reason: self.rejects_by_reason[reason]
                    for reason in sorted(self.rejects_by_reason)
                }
            ),
        )

    @classmethod
    def of(cls, result: BacktestResult) -> RunQuality:
        """Count what a run had to make do on.

        Parameters
        ----------
        result : BacktestResult
            A finished run.

        Returns
        -------
        RunQuality
            The caveats, counted.

        Notes
        -----
        A session is partially invested against the target it was *traded
        towards*: the decision executed at its open, or the last one executed
        before it. The target decided at its own close has not been traded
        yet, and a book that does not hold tomorrow's purchase tonight is not
        short of anything.
        """
        records = result.records
        reasons = Counter(reject.reason for record in records for reject in record.rejects)
        traded_towards: Mapping[str, float] = {}
        waiting: Mapping[str, float] = {}
        partially_invested = 0
        for record in records:
            if record.execution_time is not None:
                traded_towards = waiting
            missing = [
                name
                for name, weight in traded_towards.items()
                if weight > 0.0 and name not in record.holdings
            ]
            partially_invested += 1 if missing else 0
            if record.decision is not None:
                waiting = record.decision.accepted_weights
        shares = [record.cash / record.net_equity for record in records if record.net_equity > 0.0]
        return cls(
            sessions=len(records),
            decisions=sum(1 for record in records if record.decided),
            estimated_valuations=sum(1 for record in records if record.is_estimated),
            orders=sum(len(record.orders) for record in records),
            fills=sum(len(record.fills) for record in records),
            rejects=sum(reasons.values()),
            rejects_by_reason={reason.value: count for reason, count in reasons.items()},
            sessions_without_execution_price=sum(
                1
                for record in records
                if any(reject.reason in _NO_PRICE for reject in record.rejects)
            ),
            insufficient_cash_adjustments=reasons[ExecutionRejectReason.INSUFFICIENT_CASH],
            sessions_with_nothing_to_choose=sum(
                1 for record in records if record.decided and record.considered == 0
            ),
            sessions_partially_invested=partially_invested,
            average_cash_share=math.fsum(shares) / len(shares) if shares else None,
        )
