"""Running several signals over one decision, and nothing more.

The engine is deliberately thin. It checks that the signals are distinguishable,
computes each of them against the same context, refuses a result stamped at
another instant, and returns an immutable snapshot. It trains nothing, ranks
nothing, sizes nothing and never advances time - only the backtest engine does
that, and this one is called once per step of it.
"""

from __future__ import annotations

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
            signal returns a result stamped at another instant. All three are
            configuration or implementation mistakes: one would silently
            replace another's numbers, and none of them is a data problem.
        """
        seen: set[str] = set()
        for signal in signals:
            if signal.signal_id in seen:
                raise ValueError(
                    f"Two signals share the id {signal.signal_id!r}; one would hide the other"
                )
            seen.add(signal.signal_id)
        repeated = sorted({name for name in instrument_ids if list(instrument_ids).count(name) > 1})
        if repeated:
            raise ValueError(f"Instrument(s) asked for twice: {', '.join(repeated)}")

        results: dict[str, SignalResult] = {}
        for signal in signals:
            result = signal.compute(context, instrument_ids)
            if result.as_of != context.as_of:
                raise ValueError(
                    f"{signal.signal_id} returned a result stamped {result.as_of}, "
                    f"not the context's {context.as_of}"
                )
            if result.signal_id != signal.signal_id:
                raise ValueError(f"{signal.signal_id} returned a result named {result.signal_id!r}")
            results[signal.signal_id] = result
        return SignalSnapshot(as_of=context.as_of, results=results)
