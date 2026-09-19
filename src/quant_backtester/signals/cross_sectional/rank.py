"""Ranking a signal across instruments, on the instruments that have one."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import pandas as pd

from quant_backtester.signals.base import (
    RESULT_COLUMNS,
    Signal,
    SignalResult,
    require_positive_int,
)
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.types import SignalStatus, SignalUnit

CROSS_SECTION_SIZE = "cross_section_size"
"""Extra diagnostic column: how many instruments the ranking was made among.

A rank of 1.00 out of nine and a rank of 1.00 out of two are not the same
statement, and a strategy that sizes on ranks has to be able to tell them apart.
"""


@dataclass(frozen=True, slots=True)
class CrossSectionalRank(Signal):
    """Position within a cross-section, normalised to ``[0, 1]``.

    Attributes
    ----------
    signal_id : str
        Stable name, e.g. ``"momentum_60d_rank"``.
    source : Signal
        The signal being ranked. It is computed first, over the same
        instruments and the same instant, and its diagnostics are carried
        through: a rank is only as good as the window under it.
    ascending : bool
        ``False``, the default, gives ``1.0`` to the largest value - the usual
        reading of a momentum ranking. ``True`` gives it to the smallest, which
        is what ranking a volatility or a drawdown wants.
    min_instruments : int
        Fewest usable instruments a ranking may be made among. Below it the
        ranking is refused rather than computed: a cross-section of one says
        only that the one instrument is both the best and the worst.

    Raises
    ------
    ValueError
        If ``min_instruments`` is below two. One instrument is not a
        cross-section.

    Notes
    -----
    An instrument whose own signal is not ``OK`` is left out of the sample and
    keeps its own status. It never receives a rank of ``0.0``: that would read
    as "the worst of the universe" when what happened is "we do not know", and
    a strategy selling the bottom of a ranking would be selling the instruments
    whose data is late.

    Ties share the average of the ranks they span, so two identical values
    cannot be separated by the order they happened to be asked for.
    """

    signal_id: str
    source: Signal
    ascending: bool = False
    min_instruments: int = 2

    def __post_init__(self) -> None:
        """Reject a cross-section too small to be one."""
        require_positive_int(self.min_instruments, "min_instruments")
        if self.min_instruments < 2:
            raise ValueError(
                f"min_instruments must be at least 2, got {self.min_instruments}: one "
                f"instrument is both the best and the worst of itself"
            )

    def definition(self) -> Mapping[str, object]:
        """Return every parameter that changes the number, the source's included."""
        return {
            "type": "CrossSectionalRank",
            "ascending": self.ascending,
            "min_instruments": self.min_instruments,
            "unit": SignalUnit.RANK.value,
            "source": dict(self.source.definition()),
        }

    def compute(self, context: SignalContext, instrument_ids: Sequence[str]) -> SignalResult:
        """Compute the source signal, then rank the instruments that have a number."""
        inner = self.source.compute(context, instrument_ids)
        frame = inner.frame.copy()
        usable = frame["status"] == SignalStatus.OK
        size = int(usable.sum())
        frame[CROSS_SECTION_SIZE] = size

        if size < self.min_instruments:
            # Not a ranking anyone can act on. The instruments that had no
            # number keep their own reason; the ones that had one are told the
            # cross-section was too thin, rather than handed a rank of 1.0.
            frame.loc[usable, "status"] = SignalStatus.INVALID_INPUT
            frame["value"] = float("nan")
            return self._result(inner, frame)

        ranks = frame.loc[usable, "value"].rank(method="average", ascending=not self.ascending)
        frame["value"] = float("nan")
        frame.loc[usable, "value"] = (ranks - 1.0) / (size - 1)
        return self._result(inner, frame)

    def _result(self, inner: SignalResult, frame: pd.DataFrame) -> SignalResult:
        """Wrap a ranked frame, keeping the source's columns in their order."""
        ordered = frame.loc[:, [*RESULT_COLUMNS, CROSS_SECTION_SIZE]]
        return SignalResult(
            signal_id=self.signal_id,
            as_of=inner.as_of,
            _frame=ordered,
            definition=self.definition(),
        )
