"""The environment of one signal computation, at one instant.

A context is built by whatever advances time - the engine of a backtest, or a
script - and handed to the signals. It carries the reader already fixed at the
decision instant, and nothing a signal could use to move off it.

It also memoises the series it hands out. A momentum over 60 sessions, a
volatility over 20 and a drawdown over 60 all read the same closes of the same
fund; reading them once per decision rather than once per signal is the only
optimisation this layer needs, and it lives and dies with the decision, so no
invalidation problem can outlive it.

What it hands out is a copy. A shared pandas object is a shared mutable object,
and a signal that wrote into one - to normalise it in place, say - would change
what every signal computed after it sees, making a snapshot depend on the order
its signals were listed in. The copy costs microseconds on a daily series and
removes the question; the expensive part, reading the store and adjusting for
corporate actions, still happens once.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from quant_backtester.data.calendars import CalendarRegistry
from quant_backtester.data.instruments import InstrumentRegistry
from quant_backtester.data.reader import PointInTimeReader
from quant_backtester.data.schemas import BarField
from quant_backtester.signals.types import PriceBasis

SeriesKey = tuple[str, str, PriceBasis]
"""What identifies a series inside one decision: instrument, field, basis."""


@dataclass(frozen=True, slots=True)
class SignalContext:
    """Everything a signal may read, and nothing else.

    Attributes
    ----------
    market : PointInTimeReader
        The reader of one decision instant. It takes no ``as_of`` argument, so
        there is no expression a signal can write that reads the future.
    instruments : InstrumentRegistry
        Static description of each series: its venue calendar, its listing
        window, whether it is bars or a published level.
    calendars : CalendarRegistry
        The venue calendars, used to tell a missing session from a weekend.

    Notes
    -----
    The three are injected. A signal reaches for no global, opens no file and
    makes no request: its whole view of the world is this object.
    """

    market: PointInTimeReader
    instruments: InstrumentRegistry
    calendars: CalendarRegistry
    _series: dict[SeriesKey, pd.Series] = field(  # type: ignore[type-arg]
        default_factory=dict, compare=False, repr=False
    )

    @property
    def as_of(self) -> datetime:
        """Return the decision instant every signal of this context shares."""
        return self.market.as_of

    def series(self, instrument_id: str, bar_field: BarField, basis: PriceBasis) -> pd.Series:  # type: ignore[type-arg]
        """Return one price series, read once per decision.

        Parameters
        ----------
        instrument_id : str
            Instrument to read.
        bar_field : BarField
            Field to read; ignored for a published series, and refused with
            ``ADJUSTED``, which is a closing series by construction.
        basis : PriceBasis
            Raw quoted prices, or prices adjusted for the actions known now.

        Returns
        -------
        pd.Series
            Indexed by observation date, oldest first, truncated at the
            decision instant, and the caller's own to do as it likes with.

        Raises
        ------
        ValueError
            If ``ADJUSTED`` is asked for a field other than the close.
            A configuration mistake, not a data problem, so it stops the run.
        """
        if basis is PriceBasis.ADJUSTED and bar_field is not BarField.CLOSE:
            raise ValueError(f"ADJUSTED adjusts a closing series; it has no {bar_field.value}")
        key: SeriesKey = (instrument_id, bar_field.value, basis)
        cached = self._series.get(key)
        if cached is None:
            cached = (
                self.market.adjusted_history(instrument_id)
                if basis is PriceBasis.ADJUSTED
                else self.market.history(instrument_id, bar_field)
            )
            self._series[key] = cached
        return cached.copy(deep=True)
