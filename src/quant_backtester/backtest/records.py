"""What happened on one session, kept whole.

A record answers, for one session and without re-reading anything, the
questions an audit asks of a backtest:

- what the strategy wanted, and what the portfolio allowed of it;
- which orders that produced, which were filled, at what price and with what
  costs, and which were refused and why;
- what the book held afterwards, how it was valued, and which of those prices
  were estimates.

It follows the session's own timeline - fills at the open, valuation at the
close, decision after it - so the orders in a record are those of the
*previous* decision, filled this morning, and the decision in it is the one
that will be filled tomorrow. Each carries its own instant, and the record
names the decision its fills belong to, so the two are never confused.

Everything that can be derived is derived rather than stored: the equity is the
cash plus the positions at the valuation prices, the costs are the sums of the
fills. A record therefore cannot contradict itself, and it is frozen all the
way down, so it cannot be edited into a different run afterwards.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from types import MappingProxyType

from quant_backtester.execution.fills import ExecutionReject, Fill
from quant_backtester.execution.orders import Order
from quant_backtester.numbers import require_finite_non_negative, require_finite_positive
from quant_backtester.portfolio.allocation import ConstrainedTarget, PortfolioDecision
from quant_backtester.portfolio.holdings import Holding
from quant_backtester.portfolio.targets import WEIGHT_SUM_TOLERANCE, TargetAllocation


def _require_aware(instant: datetime | None, name: str) -> None:
    """Raise unless ``instant`` is ``None`` or a timezone-aware datetime."""
    if instant is None:
        return
    if not isinstance(instant, datetime) or instant.tzinfo is None:
        raise ValueError(f"{name} must be a timezone-aware datetime, got {instant!r}")


@dataclass(frozen=True, slots=True)
class BacktestRecord:
    """One session of a run: the open, the close, and the decision after it.

    Attributes
    ----------
    session_date : date
        The session of the reference calendar this record is about.
    valuation_time : datetime
        When the book was valued.
    cash : float
        Cash of the book that pays its costs, after this session's fills.
    gross_cash : float
        Cash of the book that made the same trades at the market price and
        paid no fee. The two books hold the same positions; this is the only
        place they differ.
    holdings : Mapping[str, Holding]
        Positions after this session's fills, with their average costs.
    valuation_prices : Mapping[str, float]
        The price each position was valued at.
    target_invested : float
        Fraction of capital the target standing after this session asks to
        put to work: the one decided at this session's close, or the last one
        decided before it. What was *reached* is :attr:`actual_invested` - an
        order that could not be sent, a purchase cut for want of cash and a
        lot rounded down all sit between the two.
    estimated_valuation_instruments : tuple[str, ...]
        Held instruments valued at an older price than this session's close,
        because none was published for it.
    execution_time : datetime | None
        When this session's orders were sent and filled. ``None`` when no
        decision was waiting to be executed at this open.
    executed_decision : date | None
        The session whose decision this session's orders carry out.
    orders : tuple[Order, ...]
        The orders that decision called for, in the order they were executed.
    fills : tuple[Fill, ...]
        What was done.
    rejects : tuple[ExecutionReject, ...]
        What was not, or not in full, and why.
    decision_time : datetime | None
        When the strategy was asked, on a decision session. ``None`` on a
        session the schedule does not decide on.
    decision : PortfolioDecision | None
        What the strategy asked for and what the portfolio allowed, on a
        decision session.

    Raises
    ------
    ValueError
        If an instant is naive, the cash is negative, a position has no
        valuation price, an estimate names a position not held, an execution
        or a decision is half described, or a fill is dated at another instant
        than the execution it belongs to.
    """

    session_date: date
    valuation_time: datetime
    cash: float
    gross_cash: float
    holdings: Mapping[str, Holding]
    valuation_prices: Mapping[str, float]
    target_invested: float
    estimated_valuation_instruments: tuple[str, ...] = ()
    execution_time: datetime | None = None
    executed_decision: date | None = None
    orders: tuple[Order, ...] = ()
    fills: tuple[Fill, ...] = ()
    rejects: tuple[ExecutionReject, ...] = ()
    decision_time: datetime | None = None
    decision: PortfolioDecision | None = None

    def __post_init__(self) -> None:
        """Check the record describes one coherent session, then freeze it."""
        _require_aware(self.valuation_time, "valuation_time")
        _require_aware(self.execution_time, "execution_time")
        _require_aware(self.decision_time, "decision_time")
        require_finite_non_negative(self.cash, "cash")
        require_finite_non_negative(self.gross_cash, "gross_cash")
        if not 0.0 <= self.target_invested <= 1.0 + WEIGHT_SUM_TOLERANCE:
            raise ValueError(f"target_invested must be a fraction, got {self.target_invested}")
        holdings = {name: self.holdings[name] for name in sorted(self.holdings)}
        for name, holding in holdings.items():
            if holding.instrument_id != name:
                raise ValueError(f"a holding of {holding.instrument_id} is filed under {name}")
            if name not in self.valuation_prices:
                raise ValueError(f"{name} is held and was not valued")
        prices = {name: self.valuation_prices[name] for name in sorted(self.valuation_prices)}
        for name, price in prices.items():
            require_finite_positive(price, f"the valuation price of {name}")
        estimated = tuple(sorted(self.estimated_valuation_instruments))
        stray = sorted(set(estimated) - set(holdings))
        if stray:
            raise ValueError(f"{', '.join(stray)} is estimated and not held")
        if (self.execution_time is None) != (self.executed_decision is None):
            raise ValueError("an execution names both its instant and the decision it carries out")
        if self.execution_time is None and (self.orders or self.fills or self.rejects):
            raise ValueError("orders, fills and rejects belong to an execution")
        for fill in self.fills:
            if fill.executed_at != self.execution_time:
                raise ValueError(
                    f"a fill of {fill.instrument_id} at {fill.executed_at} is recorded with the "
                    f"execution at {self.execution_time}"
                )
        if (self.decision_time is None) != (self.decision is None):
            raise ValueError("a decision names both its instant and what was decided")
        if self.decision is not None and self.decision.as_of != self.decision_time:
            raise ValueError(
                f"the decision answers for {self.decision.as_of} and is recorded at "
                f"{self.decision_time}"
            )
        object.__setattr__(self, "holdings", MappingProxyType(holdings))
        object.__setattr__(self, "valuation_prices", MappingProxyType(prices))
        object.__setattr__(self, "estimated_valuation_instruments", estimated)
        object.__setattr__(self, "orders", tuple(self.orders))
        object.__setattr__(self, "fills", tuple(self.fills))
        object.__setattr__(self, "rejects", tuple(self.rejects))

    # -- the decision -------------------------------------------------------

    @property
    def decided(self) -> bool:
        """Return whether the strategy was asked on this session."""
        return self.decision is not None

    @property
    def decision_date(self) -> date | None:
        """Return this session's date if a decision was taken on it."""
        return self.session_date if self.decision is not None else None

    @property
    def requested_target(self) -> TargetAllocation | None:
        """Return what the strategy asked for, on a decision session."""
        return self.decision.requested if self.decision is not None else None

    @property
    def constrained_target(self) -> ConstrainedTarget | None:
        """Return what the portfolio allowed, on a decision session."""
        return self.decision.constrained if self.decision is not None else None

    @property
    def considered(self) -> int | None:
        """Return how many instruments the strategy could choose among, if it was asked."""
        return self.decision.considered if self.decision is not None else None

    @property
    def strategy_diagnostics(self) -> Mapping[str, object] | None:
        """Return what the strategy said about its own decision, if it was asked.

        Returns
        -------
        Mapping[str, object] | None
            ``considered``, ``selected`` and ``skipped`` - how many instruments
            were usable, which were chosen, and why the others were not.
        """
        if self.decision is None:
            return None
        return MappingProxyType(
            {
                "considered": self.decision.considered,
                "selected": self.decision.selected,
                "skipped": {name: status.value for name, status in self.decision.skipped.items()},
            }
        )

    # -- the book -------------------------------------------------------------

    @property
    def quantities(self) -> Mapping[str, float]:
        """Return the units held per instrument."""
        return MappingProxyType({name: holding.quantity for name, holding in self.holdings.items()})

    @property
    def positions_value(self) -> float:
        """Return the value of every position at its valuation price."""
        return math.fsum(
            holding.quantity * self.valuation_prices[name]
            for name, holding in self.holdings.items()
        )

    @property
    def net_equity(self) -> float:
        """Return the book's worth after costs: cash plus positions."""
        return math.fsum(
            [self.cash]
            + [
                holding.quantity * self.valuation_prices[name]
                for name, holding in self.holdings.items()
            ]
        )

    @property
    def gross_equity(self) -> float:
        """Return what the same trades would be worth having paid nothing to make them."""
        return math.fsum(
            [self.gross_cash]
            + [
                holding.quantity * self.valuation_prices[name]
                for name, holding in self.holdings.items()
            ]
        )

    @property
    def actual_weights(self) -> Mapping[str, float]:
        """Return the fraction of net equity each position represents.

        Returns
        -------
        Mapping[str, float]
            ``q * P / equity`` per held instrument. Empty for a book worth
            nothing, which has no fractions to speak of.
        """
        equity = self.net_equity
        if equity == 0.0:
            return MappingProxyType({})
        return MappingProxyType(
            {
                name: holding.quantity * self.valuation_prices[name] / equity
                for name, holding in self.holdings.items()
            }
        )

    @property
    def actual_invested(self) -> float:
        """Return the fraction of net equity actually held in positions."""
        equity = self.net_equity
        return self.positions_value / equity if equity != 0.0 else 0.0

    @property
    def is_estimated(self) -> bool:
        """Return whether any position was valued at an older price."""
        return bool(self.estimated_valuation_instruments)

    # -- what execution took ----------------------------------------------------

    @property
    def traded_value(self) -> float:
        """Return the value exchanged at this session's open, at the fill price."""
        return math.fsum(fill.traded_value for fill in self.fills)

    @property
    def commission_cost(self) -> float:
        """Return what the broker took at this session's open."""
        return math.fsum(fill.commission for fill in self.fills)

    @property
    def spread_cost(self) -> float:
        """Return what crossing the spread took at this session's open."""
        return math.fsum(fill.spread_cost for fill in self.fills)

    @property
    def slippage_cost(self) -> float:
        """Return what the orders' own impact took at this session's open."""
        return math.fsum(fill.slippage_cost for fill in self.fills)

    @property
    def market_cost(self) -> float:
        """Return what the market took at this session's open: spread and slippage."""
        return math.fsum(fill.market_cost for fill in self.fills)

    @property
    def total_cost(self) -> float:
        """Return everything this session's rebalancing cost."""
        return math.fsum(fill.total_cost for fill in self.fills)
