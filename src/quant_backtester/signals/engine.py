"""Running several signals over one decision, and nothing more.

The engine is deliberately thin. It checks that the signals are distinguishable,
computes each of them against the same context, refuses a result that does not
answer the question asked, and returns an immutable snapshot. It trains nothing,
ranks nothing, sizes nothing and never advances time - only the backtest engine
does that, and this one is called once per step of it.

Checking the answers is the part that is not obvious. The signals here all go
through one window loader and cannot get it wrong; a fitted model, later, will
build its own frame, and a row quietly missing from it would leave a strategy
ranking a universe it believes is complete.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from quant_backtester.signals.base import Signal, SignalResult
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.snapshot import SignalSnapshot


@dataclass(frozen=True, slots=True)
class SignalEngine:
    """Computes a set of signals over a set of instruments, at one instant."""

    def compute(
        self,
        context: SignalContext,
        signals: Sequence[Signal],
        instrument_ids: Sequence[str],
    ) -> SignalSnapshot:
        """Compute every signal and return them as one snapshot.

        Parameters
        ----------
        context : SignalContext
            Environment of the decision; every signal sees the same one.
        signals : Sequence[Signal]
            Signals to compute, in order.
        instrument_ids : Sequence[str]
            Instruments to compute them for.

        Returns
        -------
        SignalSnapshot
            Immutable, keyed by signal id.

        Raises
        ------
        ValueError
            If two signals share an id, an instrument is asked for twice, or a
            signal returns a result that is not an answer to what was asked -
            another instant, another name, or another set of instruments. All
            of them are configuration or implementation mistakes, and none of
            them is a data problem, so none becomes a status.
        """
        seen: set[str] = set()
        for signal in signals:
            if signal.signal_id in seen:
                raise ValueError(
                    f"Two signals share the id {signal.signal_id!r}; one would hide the other"
                )
            seen.add(signal.signal_id)
        repeated = sorted(name for name, count in Counter(instrument_ids).items() if count > 1)
        if repeated:
            raise ValueError(f"Instrument(s) asked for twice: {', '.join(repeated)}")

        results: dict[str, SignalResult] = {}
        for signal in signals:
            result = signal.compute(context, instrument_ids)
            self._require_an_answer(signal, result, context, instrument_ids)
            results[signal.signal_id] = result
        return SignalSnapshot(as_of=context.as_of, results=results)

    @staticmethod
    def _require_an_answer(
        signal: Signal,
        result: SignalResult,
        context: SignalContext,
        instrument_ids: Sequence[str],
    ) -> None:
        """Refuse a result that does not answer the question that was asked.

        Parameters
        ----------
        signal : Signal
            Signal that produced it.
        result : SignalResult
            What it returned.
        context : SignalContext
            The decision it was asked about.
        instrument_ids : Sequence[str]
            The universe it was asked about.

        Raises
        ------
        ValueError
            If the result is stamped at another instant, names another signal,
            or speaks about another set of instruments.

        Notes
        -----
        A result whose index is missing an instrument would leave a strategy
        ranking a universe it believes is complete, and one carrying a name
        nobody asked about would put that instrument in a portfolio. The shape
        of the frame itself - the required columns, a unique index, real
        statuses - is checked by :class:`SignalResult` when it is built, so it
        holds for a result nothing here produced too.
        """
        if result.as_of != context.as_of:
            raise ValueError(
                f"{signal.signal_id} returned a result stamped {result.as_of}, "
                f"not the context's {context.as_of}"
            )
        if result.signal_id != signal.signal_id:
            raise ValueError(f"{signal.signal_id} returned a result named {result.signal_id!r}")
        answered = result.instruments()
        if answered != tuple(instrument_ids):
            missing = sorted(set(instrument_ids) - set(answered))
            extra = sorted(set(answered) - set(instrument_ids))
            detail = []
            if missing:
                detail.append(f"missing {', '.join(missing)}")
            if extra:
                detail.append(f"unasked for {', '.join(extra)}")
            if not detail:
                detail.append("the same instruments in another order")
            raise ValueError(
                f"{signal.signal_id} answered about another universe: {'; '.join(detail)}"
            )
