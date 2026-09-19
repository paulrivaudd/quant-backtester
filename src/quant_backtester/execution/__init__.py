"""Execution modelling: turn target positions into fills.

Owns the fill-price assumptions (e.g. next European open), slippage models and
the explicit transaction-cost model. Every cost charged to a backtest must
originate here.

The fill assumption is stated once, in :mod:`quant_backtester.execution.fills`,
and not buried in a loop: an order decided after the close of one session is
filled at the opening auction of the next. The three costs are named separately
in :mod:`quant_backtester.execution.costs`, because a commission, a spread and
an order's own impact behave differently and a report has to be able to say
which of them ate a return.
"""

from __future__ import annotations

from quant_backtester.execution.costs import CostModel, Side
from quant_backtester.execution.fills import Execution, ExecutionModel, Fill

__all__ = ["CostModel", "Execution", "ExecutionModel", "Fill", "Side"]
