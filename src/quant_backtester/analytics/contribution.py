"""What each instrument contributed, and what it cost to hold it.

A run says the book made sixteen percent. It does not say which of the two
funds made it, which one paid for the switching, or whether a single name
carried the whole result - and those are the questions that decide what to do
next. A rotation whose gain came entirely from one leg is not a rotation that
works; it is a strategy that was right once.

The arithmetic is deliberately closed. For one instrument on one session::

    pnl = quantity_after * close        (what the position is worth tonight)
        - quantity_before * close_before  (what it was worth last night)
        + cash_flow of the fills          (what changed hands at the open)

Summed over every instrument and every session, that is exactly the change in
the book's equity - cash has no other way in or out. The reconciliation is not
decoration: :attr:`InstrumentAttribution.unexplained` is computed and tested,
because an attribution that does not add up to the result it explains is a
table of plausible numbers.

Nothing here re-reads the market data. Every price used is one the run itself
recorded at the close it valued the book at, stale marks included and named as
such by the record. An attribution that went back to the store could quietly
use a price the run never saw, which would make it a different backtest wearing
the same figures.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import pandas as pd

from quant_backtester.backtest.result import BacktestResult


@dataclass(frozen=True, slots=True)
class InstrumentPnL:
    """One instrument's share of a run.

    Attributes
    ----------
    instrument_id : str
        The instrument.
    pnl : float
        What holding it added to the book, in currency units, after everything
        execution charged on it.
    commission : float
        Paid to the broker on its orders.
    market_cost : float
        Paid to the market on its orders: the half spread and the slippage.
    traded_value : float
        Value exchanged in it, both directions counted.
    fills : int
        Orders actually done in it.
    sessions_held : int
        Sessions the book ended holding a position in it.
    """

    instrument_id: str
    pnl: float
    commission: float
    market_cost: float
    traded_value: float
    fills: int
    sessions_held: int

    @property
    def cost(self) -> float:
        """Return everything execution took on this instrument."""
        return self.commission + self.market_cost

    @property
    def gross_pnl(self) -> float:
        """Return what it would have contributed at the market price and no fee.

        Returns
        -------
        float
            :attr:`pnl` plus :attr:`cost`. The same trades, with execution
            handed back - which is the one comparison that says whether an
            instrument was worth trading rather than worth holding.
        """
        return self.pnl + self.cost


@dataclass(frozen=True, slots=True)
class InstrumentAttribution:
    """A finished run taken apart by instrument.

    Attributes
    ----------
    instruments : tuple[InstrumentPnL, ...]
        One entry per instrument the run ever held or traded, best first.
    unexplained : float
        The book's total change minus the sum of the parts. Floating-point
        dust, and nothing else: the decomposition is exact by construction, so
        a figure of any size here means the record no longer describes what the
        engine did.
    """

    instruments: tuple[InstrumentPnL, ...]
    unexplained: float

    @classmethod
    def of(cls, result: BacktestResult) -> InstrumentAttribution:
        """Take a run apart into what each instrument contributed.

        Parameters
        ----------
        result : BacktestResult
            A finished run.

        Returns
        -------
        InstrumentAttribution
            One entry per instrument, ordered by contribution, and what the
            decomposition failed to explain.

        Notes
        -----
        A position opened at one session's open and closed at another's is
        followed across every session in between, so an instrument's figure is
        the whole of what it did rather than the sum of its round trips.
        """
        pnl: dict[str, float] = {}
        commission: dict[str, float] = {}
        market_cost: dict[str, float] = {}
        traded: dict[str, float] = {}
        fill_count: dict[str, int] = {}
        held: dict[str, int] = {}
        previous_quantities: Mapping[str, float] = {}
        previous_closes: Mapping[str, float] = {}

        for record in result.records:
            names = (
                set(record.quantities)
                | set(previous_quantities)
                | {fill.instrument_id for fill in record.fills}
            )
            for name in names:
                tonight = record.quantities.get(name, 0.0) * record.valuation_prices.get(name, 0.0)
                last_night = previous_quantities.get(name, 0.0) * previous_closes.get(name, 0.0)
                pnl[name] = pnl.get(name, 0.0) + tonight - last_night
            for fill in record.fills:
                name = fill.instrument_id
                pnl[name] = pnl.get(name, 0.0) + fill.cash_flow
                commission[name] = commission.get(name, 0.0) + fill.commission
                market_cost[name] = market_cost.get(name, 0.0) + fill.market_cost
                traded[name] = traded.get(name, 0.0) + fill.traded_value
                fill_count[name] = fill_count.get(name, 0) + 1
            for name in record.quantities:
                held[name] = held.get(name, 0) + 1
            previous_quantities = record.quantities
            previous_closes = record.valuation_prices

        instruments = tuple(
            sorted(
                (
                    InstrumentPnL(
                        instrument_id=name,
                        pnl=pnl[name],
                        commission=commission.get(name, 0.0),
                        market_cost=market_cost.get(name, 0.0),
                        traded_value=traded.get(name, 0.0),
                        fills=fill_count.get(name, 0),
                        sessions_held=held.get(name, 0),
                    )
                    for name in pnl
                ),
                key=lambda entry: (-entry.pnl, entry.instrument_id),
            )
        )
        moved = (
            result.records[-1].net_equity - result.records[0].net_equity if result.records else 0.0
        )
        return cls(
            instruments=instruments,
            unexplained=moved - sum(entry.pnl for entry in instruments),
        )

    @property
    def total_pnl(self) -> float:
        """Return what every instrument contributed together."""
        return sum(entry.pnl for entry in self.instruments)

    @property
    def total_cost(self) -> float:
        """Return what execution took across every instrument."""
        return sum(entry.cost for entry in self.instruments)

    def get(self, instrument_id: str) -> InstrumentPnL:
        """Return one instrument's share.

        Parameters
        ----------
        instrument_id : str
            Instrument to look up.

        Returns
        -------
        InstrumentPnL
            Its contribution.

        Raises
        ------
        KeyError
            If the run never held or traded it. Not a zero: a name the run
            never touched and a name that earned nothing are different facts.
        """
        for entry in self.instruments:
            if entry.instrument_id == instrument_id:
                return entry
        raise KeyError(f"{instrument_id} was never held or traded in this run")

    def as_frame(self) -> pd.DataFrame:
        """Return the attribution as a frame, indexed by instrument.

        Returns
        -------
        pd.DataFrame
            One row per instrument, best first, with the net and gross
            contributions, what execution took, and how much of the run each
            one was actually held for.
        """
        rows = [
            {
                "pnl": entry.pnl,
                "gross_pnl": entry.gross_pnl,
                "commission": entry.commission,
                "market_cost": entry.market_cost,
                "cost": entry.cost,
                "traded_value": entry.traded_value,
                "fills": entry.fills,
                "sessions_held": entry.sessions_held,
            }
            for entry in self.instruments
        ]
        index = pd.Index(
            [entry.instrument_id for entry in self.instruments],
            dtype="object",
            name="instrument_id",
        )
        return pd.DataFrame(rows, index=index)
