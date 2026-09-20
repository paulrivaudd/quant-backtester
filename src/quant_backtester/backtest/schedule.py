"""How often a strategy is asked what to hold.

A momentum rotation rebalanced every session and the same rotation rebalanced
once a month are not the same strategy: they hold different books, pay
different costs, and one of them can be run by a person. The rebalancing
calendar is therefore part of the experiment and is declared like everything
else - and it is declared *beside* the strategy rather than inside it, so that
one rule can be tested at several frequencies without being written twice.

A schedule says nothing about what to hold. It answers one question - is this
session a decision session - and the engine does the rest: on a session that is
not, the strategy is not called, no order is sent, and the record carries the
target that is still standing.

Every schedule here is a function of the session list of the reference
calendar, never of the calendar days. "The last session of the month" is a
session that exists; the 31st is not, and neither is a Sunday.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date

from quant_backtester.signals.types import require_positive_int


@dataclass(frozen=True, slots=True)
class EverySession:
    """Decide on every session of the run.

    Notes
    -----
    The default, and the most expensive: a strategy that restates its target
    daily pays whatever the execution layer charges for the drift, which is
    exactly what the cost report is for.
    """

    def decision_sessions(self, sessions: Sequence[date]) -> frozenset[date]:
        """Return every session as a decision session."""
        return frozenset(sessions)


@dataclass(frozen=True, slots=True)
class EveryNSessions:
    """Decide once every ``n`` sessions, starting with the first of the run.

    Attributes
    ----------
    n : int
        Sessions between two decisions. ``1`` is every session.

    Raises
    ------
    ValueError
        If ``n`` is not a positive whole number of sessions.
    """

    n: int

    def __post_init__(self) -> None:
        """Reject a period that is not a number of sessions."""
        require_positive_int(self.n, "n")

    def decision_sessions(self, sessions: Sequence[date]) -> frozenset[date]:
        """Return every ``n``-th session, counted from the start of the run."""
        return frozenset(sessions[:: self.n])


@dataclass(frozen=True, slots=True)
class Weekly:
    """Decide once a week, on the last session of each week.

    Notes
    -----
    The last session that exists rather than "Friday": a week whose Friday is a
    holiday still has a last session, and a strategy that waited for a Friday
    would silently skip that week.
    """

    def decision_sessions(self, sessions: Sequence[date]) -> frozenset[date]:
        """Return the last session of each ISO week in the run."""
        return _last_of(sessions, lambda day: day.isocalendar()[:2])


@dataclass(frozen=True, slots=True)
class Monthly:
    """Decide once a month, on the last session of each month.

    Notes
    -----
    Same reasoning as :class:`Weekly`, and the reason a calendar is data here:
    the last session of December is the 24th in a year whose 25th and 31st are
    holidays, and no arithmetic on dates knows that.
    """

    def decision_sessions(self, sessions: Sequence[date]) -> frozenset[date]:
        """Return the last session of each month in the run."""
        return _last_of(sessions, lambda day: (day.year, day.month))


def _last_of(sessions: Sequence[date], period: Callable[[date], object]) -> frozenset[date]:
    """Return the last session of each period the sessions fall into."""
    last: dict[object, date] = {}
    for session in sessions:
        last[period(session)] = session
    return frozenset(last.values())


DecisionSchedule = EverySession | EveryNSessions | Weekly | Monthly
"""Every schedule a run may be given.

A union rather than a protocol: there are four of them, they are all data, and
a reader of a configuration should be able to see the whole list at once.
"""
