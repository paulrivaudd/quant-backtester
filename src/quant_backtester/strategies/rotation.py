"""Hold the best-ranked instruments of a universe, and nothing else.

The simplest strategy that is still a strategy, and it is here to prove one
thing: that a decision needs the signals and nothing underneath them. This
module imports no reader, no repository, no calendar and no provider. It cannot
open a file, it cannot know what a corporate action is, and it cannot ask what
happened the day after the decision - because the only thing it is given is a
:class:`~quant_backtester.signals.snapshot.SignalSnapshot`.

What it does is deliberately thin. Read a ranking, keep the top few, weight them
equally. A cap per position, a gross limit, a turnover budget: those are the
portfolio layer's, and they are applied to what comes out of here rather than
folded into it, so that a report can say what each of them cost.
"""

from __future__ import annotations

from dataclasses import dataclass

from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.signals.snapshot import SignalSnapshot
from quant_backtester.signals.types import SignalStatus


@dataclass(frozen=True, slots=True)
class TopRankRotation:
    """Hold the ``top_n`` best-ranked instruments, equally weighted.

    Attributes
    ----------
    signal_id : str
        The ranking to read from the snapshot. A ranking rather than a raw
        signal on purpose: a rank already excludes the instruments whose data
        is not usable, and already says how many it was taken among.
    top_n : int
        How many instruments to hold.

    Raises
    ------
    ValueError
        If ``top_n`` is not a positive integer.

    Notes
    -----
    Each held position gets ``1 / top_n`` of the capital, not ``1 / len(held)``.
    A rotation meant to hold two names that can only find one holds that one at
    half the capital and leaves the rest in cash, rather than doubling a bet
    because a provider was late. Concentrating on the survivors is a decision,
    and it is not one a data problem should take.
    """

    signal_id: str
    top_n: int

    def __post_init__(self) -> None:
        """Reject a rotation that cannot hold anything."""
        if isinstance(self.top_n, bool) or not isinstance(self.top_n, int) or self.top_n < 1:
            raise ValueError(f"top_n must be a positive integer, got {self.top_n!r}")

    def decide(self, signals: SignalSnapshot) -> TargetAllocation:
        """Return what to hold, given the signals of one decision instant.

        Parameters
        ----------
        signals : SignalSnapshot
            Every signal computed for this decision. The only argument, and
            deliberately so.

        Returns
        -------
        TargetAllocation
            The instruments to hold and their weights, with the reason every
            other one was left out.

        Raises
        ------
        KeyError
            If the snapshot holds no such signal. A strategy naming a signal
            the engine was not given is a wiring mistake, not an empty day.
        """
        frame = signals.values(self.signal_id)
        usable = frame.loc[frame["status"] == SignalStatus.OK]
        # A rank of 1.0 is the best of its cross-section, so the sort is
        # descending. Ties keep the order the universe was asked in, which is
        # the only tie-break available here and is recorded by the ranking
        # itself rather than invented at this level.
        ordered = usable.sort_values("value", ascending=False, kind="stable")
        selected = tuple(str(name) for name in ordered.index[: self.top_n])
        weight = 1.0 / self.top_n
        skipped: dict[str, SignalStatus] = {}
        for name, status in zip(frame.index, frame["status"], strict=True):
            if str(name) not in selected:
                assert isinstance(status, SignalStatus)
                skipped[str(name)] = status
        return TargetAllocation(
            as_of=signals.as_of,
            weights={name: weight for name in selected},
            selected=selected,
            considered=len(usable),
            skipped=skipped,
        )
