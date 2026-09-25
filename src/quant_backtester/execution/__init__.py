"""Execution modelling: turn an admissible target into orders, fills and rejects.

Owns the fill assumption, the lot rounding, the cash constraint and the
explicit transaction-cost model. Every cost charged to a backtest originates
here, and every order the target called for ends in this layer as a fill, a
reject with its reason, or both.

The fill assumption is stated once, in :mod:`quant_backtester.execution.model`,
and not buried in a loop: an order is sent just after the opening auction of
the execution session and filled at that auction's price, moved against the
trader by the half spread and the slippage. The three costs are named
separately in :mod:`quant_backtester.execution.costs`, because a commission, a
spread and an order's own impact behave differently and a report has to be
able to say which of them ate a return.
"""

from __future__ import annotations

from quant_backtester.execution.costs import CostBreakdown, CostModel
from quant_backtester.execution.fills import (
    ExecutionReject,
    ExecutionRejectReason,
    Fill,
    OrderStatus,
)
from quant_backtester.execution.model import Execution, ExecutionModel
from quant_backtester.execution.orders import Order, Side
from quant_backtester.execution.rounding import (
    LOT_TOLERANCE,
    is_whole_lots,
    round_down_to_lot,
    target_quantity,
    whole_lots,
)

__all__ = [
    "LOT_TOLERANCE",
    "CostBreakdown",
    "CostModel",
    "Execution",
    "ExecutionModel",
    "ExecutionReject",
    "ExecutionRejectReason",
    "Fill",
    "Order",
    "OrderStatus",
    "Side",
    "is_whole_lots",
    "round_down_to_lot",
    "target_quantity",
    "whole_lots",
]
