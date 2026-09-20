"""A rotation that stands aside when a gauge it does not trade says so.

The first cross-asset decision in the project, and it is the reason a signal
can carry a universe of its own: the funds being rotated and the gauge gating
them are not the same universe, and a level signal asked about a fund is a
wiring mistake rather than a number. Both are computed for the same instant and
arrive in the same snapshot; the strategy reads one to decide what to do with
the other.

Nothing here reads a price, a calendar or a store. Two signal ids, one
instrument id and a threshold: what the gate *is* - a volatility index, a
yield, a spread - is a question for the configuration, and this module never
learns the answer.
"""

from __future__ import annotations

from dataclasses import dataclass

from quant_backtester.numbers import require_finite
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.signals.snapshot import SignalSnapshot
from quant_backtester.signals.types import SignalStatus
from quant_backtester.strategies.rotation import TopRankRotation


@dataclass(frozen=True, slots=True)
class RiskGatedRotation:
    """Hold the rotation's choice while a gauge stays at or below a threshold.

    Attributes
    ----------
    rotation : TopRankRotation
        What to hold when the gate is open. Composed rather than reimplemented:
        the rule about ranks belongs to one place, and this one only decides
        whether it applies today.
    gate_signal_id : str
        Signal to read the gauge from, e.g. a z-score of a volatility index.
    gate_instrument_id : str
        The instrument that signal is read for. It is never held, and it need
        not be tradable at all.
    maximum : float
        The rotation runs while the gauge is at or below this. Above it, the
        book goes to cash. A number in the gauge's own unit, which for a
        z-score is spreads from its own recent mean.
    flat_when_unknown : bool
        What to do when the gauge has no usable value - not published yet, too
        old, a window that is not one. ``True`` stands aside, ``False`` lets
        the rotation run ungated. No default: a risk filter that silently
        becomes no filter the day its input is late is the kind of thing that
        is only noticed afterwards, so the choice is made in the config and
        written down.

    Raises
    ------
    ValueError
        If ``maximum`` is not a finite number, or ``flat_when_unknown`` is not
        a boolean.

    Notes
    -----
    A gated day is not a day with nothing to choose from, and the record keeps
    them apart without needing a new field: a flat day with ``considered``
    above zero is the gate, and a flat day with ``considered`` at zero is a
    hole in the data. Both are flat, and they mean opposite things about the
    strategy.

    The gate is read at the same decision instant as everything else, so it
    cannot know today's move before deciding on it. Whether the *gauge itself*
    is fresh at that instant is a separate question, and it is the one
    ``max_age_sessions`` answers on the signal.
    """

    rotation: TopRankRotation
    gate_signal_id: str
    gate_instrument_id: str
    maximum: float
    flat_when_unknown: bool

    def __post_init__(self) -> None:
        """Reject a gate that cannot be applied."""
        # An infinite threshold is a gate that never closes, or never opens:
        # both are a parameter written wrong rather than a decision.
        require_finite(self.maximum, "maximum")
        if not isinstance(self.flat_when_unknown, bool):
            raise ValueError(
                f"flat_when_unknown must be said explicitly as a boolean, got "
                f"{self.flat_when_unknown!r}"
            )

    def decide(self, signals: SignalSnapshot) -> TargetAllocation:
        """Return what to hold, given every signal of one decision instant.

        Parameters
        ----------
        signals : SignalSnapshot
            The snapshot, holding both the ranking and the gauge. They need not
            speak about the same instruments - that is what a per-signal
            universe is for - but they do speak about the same instant.

        Returns
        -------
        TargetAllocation
            The rotation's choice, or an allocation of nothing when the gate is
            shut.

        Raises
        ------
        KeyError
            If the snapshot holds no such signal, or the gauge's signal was not
            computed for ``gate_instrument_id``. A strategy naming something
            the engine was not given is a wiring mistake, not a flat day.
        """
        wanted = self.rotation.decide(signals)
        if self._gate_is_open(signals):
            return wanted
        return TargetAllocation(
            as_of=wanted.as_of,
            weights={},
            selected=(),
            considered=wanted.considered,
            skipped=wanted.skipped,
        )

    def _gate_is_open(self, signals: SignalSnapshot) -> bool:
        """Return whether the rotation may run today."""
        status = signals.status(self.gate_signal_id, self.gate_instrument_id)
        if status is not SignalStatus.OK:
            return not self.flat_when_unknown
        return signals.value(self.gate_signal_id, self.gate_instrument_id) <= self.maximum
