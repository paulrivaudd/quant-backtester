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
from dataclasses import dataclass, replace
from datetime import date

from quant_backtester.data.universes import UniverseSource, universe_definition
from quant_backtester.signals.base import Signal, SignalResult, freeze
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.snapshot import SignalSnapshot


@dataclass(frozen=True, slots=True)
class SignalRequest:
    """One signal, and the universe it is to be computed over.

    Attributes
    ----------
    signal : Signal
        The signal.
    instruments : Sequence[str] | UniverseSource | None
        The instruments to compute it for. ``None`` means the snapshot's own
        universe, which is what every signal used to get. A
        :class:`~quant_backtester.data.universes.Universe` may be given
        instead of a list, and then the names are the ones it held on the
        session being decided: a gauge basket changes over the years like any
        other, and a fixed list of the ones that still exist is the same
        survivorship bias the trading universe was dated to remove.

    Notes
    -----
    A snapshot used to be one universe asked several questions, and that is
    wrong as soon as a decision is cross-asset: a rotation between two funds
    filtered by a volatility index needs the index in the same snapshot as the
    funds, and a level signal asked about a fund is a wiring mistake rather
    than a number. So a signal may carry its own universe, and the snapshot
    holds results that do not all speak about the same names.

    What does not change is that they all speak about the same *instant*. That
    is the property the snapshot exists for, and mixing two of them is still
    refused.

    A dated universe is resolved by the layer that knows which session is being
    decided, which is the backtest engine: nothing in ``signals`` chooses its
    own date, and a request that reached :meth:`SignalEngine.compute` still
    holding one stops the run rather than guessing at a session.
    """

    signal: Signal
    instruments: Sequence[str] | UniverseSource | None = None

    def resolved(self, on: date) -> SignalRequest:
        """Return the same request with its universe fixed to one session.

        Parameters
        ----------
        on : date
            Session being decided, on the reference calendar.

        Returns
        -------
        SignalRequest
            This request when its universe is already a list of names, and a
            copy holding the members of that session when it carries a dated
            universe.
        """
        if not isinstance(self.instruments, UniverseSource):
            return self
        return replace(self, instruments=tuple(self.instruments.members_at(on)))

    def definition(self) -> dict[str, object]:
        """Return what identifies this request, universe included.

        Returns
        -------
        dict[str, object]
            The signal's own definition and a description of what it is
            computed for: ``None`` for the snapshot's universe, the names of a
            fixed list, the id and memberships of a dated one.

        Notes
        -----
        The request describes itself so that the layers above it - a strategy
        recording what it ran, an experiment log - never have to reach into the
        data layer to find out what a universe was. Two requests computing one
        signal over two different universes are two different experiments, and
        a definition naming only the class of the universe could not say so.
        """
        return {
            "signal": self.signal.definition_json(),
            "instruments": universe_definition(self.instruments),
        }

    def names(self) -> Sequence[str] | None:
        """Return the instruments this request names, resolved.

        Returns
        -------
        Sequence[str] | None
            The fixed list, or ``None`` for a request that takes the
            snapshot's own universe.

        Raises
        ------
        TypeError
            If the universe is still dated. Resolving it needs a session, and
            this layer never has one - a signal that chose its own date could
            choose one the decision cannot see.
        """
        if isinstance(self.instruments, UniverseSource):
            raise TypeError(
                f"the universe of {self.signal.signal_id} is dated and was not resolved "
                "for a session; only the layer that advances time can do that"
            )
        return self.instruments


@dataclass(frozen=True, slots=True)
class SignalEngine:
    """Computes a set of signals over a set of instruments, at one instant."""

    def compute(
        self,
        context: SignalContext,
        signals: Sequence[Signal | SignalRequest],
        instrument_ids: Sequence[str],
    ) -> SignalSnapshot:
        """Compute every signal and return them as one snapshot.

        Parameters
        ----------
        context : SignalContext
            Environment of the decision; every signal sees the same one.
        signals : Sequence[Signal | SignalRequest]
            Signals to compute, in order. A bare signal is computed over
            ``instrument_ids``; a :class:`SignalRequest` may carry a universe
            of its own, which is what a cross-asset decision needs - a yield
            and a fund are not the same universe, and a level signal asked
            about a fund stops the run rather than answering.
        instrument_ids : Sequence[str]
            Instruments to compute them for, unless a request says otherwise.

        Returns
        -------
        SignalSnapshot
            Immutable, keyed by signal id.

        Raises
        ------
        ValueError
            If two signals share an id, an instrument is asked for twice, or a
            signal returns a result that is not an answer to what was asked -
            another instant, another name, another set of instruments, or a
            definition that is not the one it was configured with. All of them
            are configuration or implementation mistakes, and none of them is a
            data problem, so none becomes a status.
        """
        requests = [
            item if isinstance(item, SignalRequest) else SignalRequest(item) for item in signals
        ]
        seen: set[str] = set()
        for request in requests:
            signal_id = request.signal.signal_id
            if signal_id in seen:
                raise ValueError(
                    f"Two signals share the id {signal_id!r}; one would hide the other"
                )
            seen.add(signal_id)
        _require_each_name_once(instrument_ids, "the snapshot's universe")
        for request in requests:
            names = request.names()
            if names is not None:
                _require_each_name_once(names, f"the universe of {request.signal.signal_id}")

        results: dict[str, SignalResult] = {}
        for request in requests:
            names = request.names()
            universe = list(instrument_ids) if names is None else list(names)
            result = request.signal.compute(context, universe)
            self._require_an_answer(request.signal, result, context, universe)
            results[request.signal.signal_id] = result
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
            speaks about another set of instruments, or carries a definition
            that is not the signal's own.

        Notes
        -----
        A result whose index is missing an instrument would leave a strategy
        ranking a universe it believes is complete, and one carrying a name
        nobody asked about would put that instrument in a portfolio. The shape
        of the frame itself - the required columns, a unique index, real
        statuses, a number that matches what its status says - is checked by
        :class:`SignalResult` when it is built, so it holds for a result
        nothing here produced too.

        The definition is checked because it is the audit trail. A signal that
        computed with a lookback of sixty and recorded twenty would give a
        number nobody could reproduce from what was written down, and a
        fingerprint that says two different experiments were the same. The
        comparison is made on the frozen forms because freezing turns a list
        into a tuple, and a definition holding one - a cross-asset signal
        naming its inputs, soon - would otherwise fail on the shape of its own
        container.
        """
        if result.as_of != context.as_of:
            raise ValueError(
                f"{signal.signal_id} returned a result stamped {result.as_of}, "
                f"not the context's {context.as_of}"
            )
        if result.signal_id != signal.signal_id:
            raise ValueError(f"{signal.signal_id} returned a result named {result.signal_id!r}")
        if result.definition != freeze(signal.definition()):
            raise ValueError(
                f"{signal.signal_id} returned a definition that is not its own; the record "
                f"would describe a calculation that did not happen"
            )
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


def _require_each_name_once(instrument_ids: Sequence[str], what: str) -> None:
    """Raise if a universe holds an instrument twice.

    Parameters
    ----------
    instrument_ids : Sequence[str]
        The universe to check.
    what : str
        How to describe it in the message.

    Raises
    ------
    ValueError
        If a name appears more than once. It would be weighted twice in a
        ranking, which is a configuration mistake rather than a view.
    """
    repeated = sorted(name for name, count in Counter(instrument_ids).items() if count > 1)
    if repeated:
        raise ValueError(f"{what} asks for {', '.join(repeated)} twice")
