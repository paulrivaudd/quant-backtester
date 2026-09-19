"""What a strategy receives: every signal of one decision, and nothing else.

A strategy that held the reader could write its own ``tail(20)`` and get a
window that is not twenty sessions. It receives a snapshot instead - numbers
already computed, under window rules that are the same for every instrument and
recorded in each signal's definition.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

import pandas as pd

from quant_backtester.signals.base import SignalResult
from quant_backtester.signals.types import SignalStatus


@dataclass(frozen=True, slots=True)
class SignalSnapshot:
    """Every signal of one decision instant, keyed by signal id.

    Attributes
    ----------
    as_of : datetime
        The instant every result in it was computed at.
    results : Mapping[str, SignalResult]
        One entry per signal, in the order they were computed. The mapping is
        frozen, and so is each result: a strategy cannot change what it was
        handed, neither the set of signals nor a number inside one.
    """

    as_of: datetime
    results: Mapping[str, SignalResult]

    def __post_init__(self) -> None:
        """Freeze the mapping and refuse a result that does not belong to its key.

        Raises
        ------
        ValueError
            If a result was computed at another instant, or is filed under a
            name that is not its own. The engine builds the mapping correctly,
            but this constructor is public: a snapshot whose key and whose
            result disagree would answer ``result("momentum").signal_id ==
            "return_20d"``, and every log and report built on it would be
            wrong about what it was reading.
        """
        for signal_id, result in self.results.items():
            if result.as_of != self.as_of:
                raise ValueError(
                    f"{signal_id} was computed at {result.as_of}, "
                    f"not at the snapshot's {self.as_of}"
                )
            if result.signal_id != signal_id:
                raise ValueError(
                    f"A result named {result.signal_id!r} is filed under {signal_id!r}"
                )
        object.__setattr__(self, "results", MappingProxyType(dict(self.results)))

    def __iter__(self) -> Iterator[str]:
        """Iterate over the signal ids this snapshot holds."""
        return iter(self.results)

    def __contains__(self, signal_id: str) -> bool:
        """Return whether this snapshot holds that signal."""
        return signal_id in self.results

    def result(self, signal_id: str) -> SignalResult:
        """Return one signal's whole result.

        Raises
        ------
        KeyError
            If this snapshot holds no such signal - a strategy asking for one
            the engine was not given is a configuration mistake, not an empty
            answer.
        """
        try:
            return self.results[signal_id]
        except KeyError:
            known = ", ".join(sorted(self.results)) or "none"
            raise KeyError(f"No signal {signal_id!r} in this snapshot; it holds: {known}") from None

    def values(self, signal_id: str) -> pd.DataFrame:
        """Return one signal's frame, diagnostics included.

        Returns
        -------
        pd.DataFrame
            A frame of the caller's own. Writing into it, adding a column to
            it or sorting it changes nothing in the snapshot, so two strategies
            reading the same one cannot interfere.
        """
        return self.result(signal_id).frame

    def value(self, signal_id: str, instrument_id: str) -> float:
        """Return one number, ``NaN`` when that instrument has none."""
        return self.result(signal_id).value(instrument_id)

    def status(self, signal_id: str, instrument_id: str) -> SignalStatus:
        """Return why that number is what it is."""
        return self.result(signal_id).status(instrument_id)
