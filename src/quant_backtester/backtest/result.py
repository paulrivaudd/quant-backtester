"""A finished run: every session, and everything it was run with.

The records are the source of truth - one immutable object per session, kept
whole - and everything else here is a view of them, built on demand. A frame
is convenient and mutable; a frame handed out as *the* result would let a
reader edit a run into a different one, so none is kept.

Beside the records, the result carries what the numbers depend on: the
configuration of the run, the definition and fingerprint of the strategy, and
the state of the code that produced it. A Sharpe ratio without those is a
number nobody can reproduce, and the object refuses to be separated from them.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from itertools import pairwise

import pandas as pd

from quant_backtester.backtest.config import BacktestConfig
from quant_backtester.backtest.records import BacktestRecord
from quant_backtester.execution.fills import OrderStatus
from quant_backtester.provenance import SourceState
from quant_backtester.signals.base import freeze
from quant_backtester.signals.types import require_identifier


def _session_index(dates: list[date]) -> pd.Index:
    """Return an index of session dates, named as every frame of a run names it."""
    return pd.Index(dates, dtype="object", name="session_date")


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """Every session of a run, and what it was run with.

    Attributes
    ----------
    records : tuple[BacktestRecord, ...]
        One per session of the reference calendar inside the run, in order.
    config : BacktestConfig
        The period, the cash, the currency, the calendar, the schedule and the
        timetable.
    configuration : Mapping[str, object]
        Everything the numbers depend on, as built-ins: the configuration
        above, the trading universe, the declared signals, the portfolio
        limits, the execution and cost models and the lot size of every
        instrument the book could hold.
    strategy_definition : Mapping[str, object]
        What the strategy was: its class, its parameters, its signals.
    strategy_fingerprint : str
        Hash of that definition.
    source : SourceState
        The state of the code that produced the run, as the caller gave it.

    Raises
    ------
    ValueError
        If the records are not in strictly increasing session order, fall
        outside the configured period, or the fingerprint is empty.

    Notes
    -----
    Frozen all the way down: the mappings are deep-frozen at construction. A
    record of an experiment that can be edited afterwards is a record of
    nothing.
    """

    records: tuple[BacktestRecord, ...]
    config: BacktestConfig
    configuration: Mapping[str, object]
    strategy_definition: Mapping[str, object]
    strategy_fingerprint: str
    source: SourceState = field(default_factory=SourceState.unrecorded)

    def __post_init__(self) -> None:
        """Check the run is one run, and freeze its audit trail."""
        records = tuple(self.records)
        for earlier, later in pairwise(records):
            if not earlier.session_date < later.session_date:
                raise ValueError(
                    f"records must be in session order, got {earlier.session_date} "
                    f"then {later.session_date}"
                )
        if records and (
            records[0].session_date < self.config.start
            or records[-1].session_date > self.config.end
        ):
            raise ValueError(
                f"the records run from {records[0].session_date} to {records[-1].session_date}, "
                f"outside the configured {self.config.start} to {self.config.end}"
            )
        require_identifier(self.strategy_fingerprint, "strategy_fingerprint")
        object.__setattr__(self, "records", records)
        for name in ("configuration", "strategy_definition"):
            frozen = freeze(dict(getattr(self, name)))
            assert isinstance(frozen, Mapping)
            object.__setattr__(self, name, frozen)

    # -- what the run is ----------------------------------------------------------

    @property
    def initial_cash(self) -> float:
        """Return what the run started with."""
        return self.config.initial_cash

    @property
    def code_version(self) -> str | None:
        """Return the commit the run was produced from, when it was recorded."""
        return self.source.git_commit

    @property
    def total_cost(self) -> float:
        """Return everything execution took over the whole run."""
        return math.fsum(record.total_cost for record in self.records)

    @property
    def net_return(self) -> float:
        """Return the run's return after costs, as a fraction."""
        return self._return(self.records[-1].net_equity) if self.records else 0.0

    @property
    def gross_return(self) -> float:
        """Return what the same trades would have returned having paid nothing."""
        return self._return(self.records[-1].gross_equity) if self.records else 0.0

    def _return(self, final: float) -> float:
        """Return the growth from the starting cash to ``final``."""
        return final / self.initial_cash - 1.0

    # -- views, built on demand ---------------------------------------------------

    def frame(self) -> pd.DataFrame:
        """Return the run as a frame, one row per session.

        Returns
        -------
        pd.DataFrame
            Indexed by session date: the three instants, gross and net side
            by side, target against actual, the costs term by term and the
            counts of orders, fills and rejects.
        """
        rows = [
            {
                "execution_time": record.execution_time,
                "valuation_time": record.valuation_time,
                "decision_time": record.decision_time,
                "decided": record.decided,
                "net_equity": record.net_equity,
                "gross_equity": record.gross_equity,
                "cash": record.cash,
                "target_invested": record.target_invested,
                "actual_invested": record.actual_invested,
                "considered": record.considered,
                "orders": len(record.orders),
                "fills": len(record.fills),
                "rejects": len(record.rejects),
                "traded_value": record.traded_value,
                "commission_cost": record.commission_cost,
                "spread_cost": record.spread_cost,
                "slippage_cost": record.slippage_cost,
                "total_cost": record.total_cost,
                "estimated": ",".join(record.estimated_valuation_instruments),
            }
            for record in self.records
        ]
        index = _session_index([record.session_date for record in self.records])
        return pd.DataFrame(rows, index=index)

    def equity(self) -> pd.DataFrame:
        """Return the net and the gross book, one row per session."""
        return pd.DataFrame(
            {
                "net_equity": [record.net_equity for record in self.records],
                "gross_equity": [record.gross_equity for record in self.records],
            },
            index=_session_index([record.session_date for record in self.records]),
        )

    def costs(self) -> pd.DataFrame:
        """Return what execution took on each session, term by term."""
        return pd.DataFrame(
            {
                "traded_value": [record.traded_value for record in self.records],
                "commission_cost": [record.commission_cost for record in self.records],
                "spread_cost": [record.spread_cost for record in self.records],
                "slippage_cost": [record.slippage_cost for record in self.records],
                "total_cost": [record.total_cost for record in self.records],
            },
            index=_session_index([record.session_date for record in self.records]),
        )

    def holdings(self) -> pd.DataFrame:
        """Return the units held of every instrument, and the cash, after each session.

        Returns
        -------
        pd.DataFrame
            One row per session, one column per instrument ever held - in id
            order - and a ``cash`` column. An instrument not held on a
            session is ``0.0`` there: a position of none, which is a fact,
            rather than a missing number.
        """
        names = sorted({name for record in self.records for name in record.holdings})
        columns: dict[str, list[float]] = {
            name: [record.quantities.get(name, 0.0) for record in self.records] for name in names
        }
        columns["cash"] = [record.cash for record in self.records]
        return pd.DataFrame(
            columns, index=_session_index([record.session_date for record in self.records])
        )

    def weights(self) -> pd.DataFrame:
        """Return the fraction of net equity each instrument actually was, per session."""
        names = sorted({name for record in self.records for name in record.holdings})
        return pd.DataFrame(
            {
                name: [record.actual_weights.get(name, 0.0) for record in self.records]
                for name in names
            },
            index=_session_index([record.session_date for record in self.records]),
            columns=names,
            dtype="float64",
        )

    def target_weights(self) -> pd.DataFrame:
        """Return the target standing after each session, as the portfolio accepted it.

        Returns
        -------
        pd.DataFrame
            One row per session, one column per instrument ever targeted.
            On a session the schedule does not decide on, the target standing
            is the last one decided, and the row repeats it; before the first
            decision, nothing is targeted.
        """
        standing: dict[str, float] = {}
        rows: list[dict[str, float]] = []
        for record in self.records:
            if record.decision is not None:
                standing = dict(record.decision.accepted_weights)
            rows.append(dict(standing))
        names = sorted({name for row in rows for name in row})
        return pd.DataFrame(
            {name: [row.get(name, 0.0) for row in rows] for name in names},
            index=_session_index([record.session_date for record in self.records]),
            columns=names,
            dtype="float64",
        )

    def fills(self) -> pd.DataFrame:
        """Return every fill of the run, one row each, in the order they were done."""
        rows = [
            {
                "session_date": record.session_date,
                "executed_at": fill.executed_at,
                "instrument_id": fill.instrument_id,
                "side": fill.side.value,
                "quantity": fill.quantity,
                "market_price": fill.market_price,
                "fill_price": fill.fill_price,
                "traded_value": fill.traded_value,
                "commission": fill.commission,
                "spread_cost": fill.spread_cost,
                "slippage_cost": fill.slippage_cost,
                "total_cost": fill.total_cost,
            }
            for record in self.records
            for fill in record.fills
        ]
        return pd.DataFrame(rows, columns=_FILL_COLUMNS)

    def orders(self) -> pd.DataFrame:
        """Return every order of the run with what became of it."""
        rows: list[dict[str, object]] = []
        for record in self.records:
            for order in record.orders:
                done = sum(
                    fill.quantity
                    for fill in record.fills
                    if fill.instrument_id == order.instrument_id and fill.side is order.side
                )
                status = (
                    OrderStatus.REJECTED
                    if done == 0.0
                    else OrderStatus.PARTIALLY_FILLED
                    if done < order.quantity
                    else OrderStatus.FILLED
                )
                rows.append(
                    {
                        "session_date": record.session_date,
                        "submitted_at": order.submitted_at,
                        "decided_on": record.executed_decision,
                        "instrument_id": order.instrument_id,
                        "side": order.side.value,
                        "quantity": order.quantity,
                        "filled_quantity": done,
                        "status": status.value,
                    }
                )
        return pd.DataFrame(rows, columns=_ORDER_COLUMNS)

    def rejects(self) -> pd.DataFrame:
        """Return every reject of the run, with its reason."""
        rows = [
            {
                "session_date": record.session_date,
                "instrument_id": reject.instrument_id,
                "reason": reject.reason.value,
                "side": reject.side.value if reject.side is not None else None,
                "requested_quantity": reject.requested_quantity,
            }
            for record in self.records
            for reject in record.rejects
        ]
        return pd.DataFrame(rows, columns=_REJECT_COLUMNS)


_FILL_COLUMNS = [
    "session_date",
    "executed_at",
    "instrument_id",
    "side",
    "quantity",
    "market_price",
    "fill_price",
    "traded_value",
    "commission",
    "spread_cost",
    "slippage_cost",
    "total_cost",
]
"""Columns of :meth:`BacktestResult.fills`, in order."""

_ORDER_COLUMNS = [
    "session_date",
    "submitted_at",
    "decided_on",
    "instrument_id",
    "side",
    "quantity",
    "filled_quantity",
    "status",
]
"""Columns of :meth:`BacktestResult.orders`, in order."""

_REJECT_COLUMNS = ["session_date", "instrument_id", "reason", "side", "requested_quantity"]
"""Columns of :meth:`BacktestResult.rejects`, in order."""
