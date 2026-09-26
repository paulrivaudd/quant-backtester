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

And it is the last session of the *market's* month, not of the run's. Each
schedule is told the calendar's session after the run as well as the run's
own: a run stopped on 4 September has not reached the end of September, and
its last session is not a month end (audit A18). Stopping a run earlier
changes nothing it decided before its end: a short run's decisions are a
prefix of a long one's.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, fields
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

    def definition(self) -> dict[str, object]:
        """Return what identifies this schedule, for the record of a run."""
        return _definition_of(self)

    def decision_sessions(
        self, sessions: Sequence[date], following: date | None
    ) -> frozenset[date]:
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

    def definition(self) -> dict[str, object]:
        """Return what identifies this schedule, ``n`` included.

        Returns
        -------
        dict[str, object]
            The type and the parameters. Deciding every five sessions and
            every twenty are different experiments, and a result recording only
            the class name could not tell them apart.
        """
        return _definition_of(self)

    def decision_sessions(
        self, sessions: Sequence[date], following: date | None
    ) -> frozenset[date]:
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

    def definition(self) -> dict[str, object]:
        """Return what identifies this schedule, for the record of a run."""
        return _definition_of(self)

    def decision_sessions(
        self, sessions: Sequence[date], following: date | None
    ) -> frozenset[date]:
        """Return the last session of each ISO week, of those inside the run.

        Parameters
        ----------
        sessions : Sequence[date]
            The run's sessions, in order.
        following : date | None
            The calendar's first session after the run. When it falls in the
            same week as the run's last session, that week has not ended.
            ``None`` when the calendar's coverage stops at the run's end: then
            nobody knows, and the last week is not called ended.

        Returns
        -------
        frozenset[date]
            The week ends the run reaches.
        """
        return _last_of(sessions, following, lambda day: day.isocalendar()[:2])


@dataclass(frozen=True, slots=True)
class Monthly:
    """Decide once a month, on the last session of each month.

    Notes
    -----
    Same reasoning as :class:`Weekly`, and the reason a calendar is data here:
    the last session of December is the 24th in a year whose 25th and 31st are
    holidays, and no arithmetic on dates knows that.
    """

    def definition(self) -> dict[str, object]:
        """Return what identifies this schedule, for the record of a run."""
        return _definition_of(self)

    def decision_sessions(
        self, sessions: Sequence[date], following: date | None
    ) -> frozenset[date]:
        """Return the last session of each month, of those inside the run.

        Parameters
        ----------
        sessions : Sequence[date]
            The run's sessions, in order.
        following : date | None
            The calendar's first session after the run. When it falls in the
            same month as the run's last session, that month has not ended.
            ``None`` when the calendar's coverage stops at the run's end: then
            nobody knows, and the last month is not called ended.

        Returns
        -------
        frozenset[date]
            The month ends the run reaches.
        """
        return _last_of(sessions, following, lambda day: (day.year, day.month))


def _definition_of(schedule: object) -> dict[str, object]:
    """Return a schedule as its type and its parameters.

    Parameters
    ----------
    schedule : object
        Any schedule of this module; they are all frozen dataclasses.

    Returns
    -------
    dict[str, object]
        ``{"type": ..., "parameters": {...}}``. The parameters are what makes
        two schedules of one type different, and a run that recorded only the
        type could not be told from a run rebalanced four times as often.
    """
    return {
        "type": type(schedule).__name__,
        "parameters": {
            field.name: getattr(schedule, field.name)
            for field in fields(schedule)  # type: ignore[arg-type]
        },
    }


def _last_of(
    sessions: Sequence[date], following: date | None, period: Callable[[date], object]
) -> frozenset[date]:
    """Return the last session of each period, dropping one the run cut short.

    A last period whose end cannot be known - the calendar stops with the run
    - is dropped as well: a decision on it would be the invented period end
    this rule exists to prevent, and that decision is never executed anyway.
    """
    if following is not None and sessions and following <= sessions[-1]:
        raise ValueError(f"the session after the run, {following}, is not after {sessions[-1]}")
    last: dict[object, date] = {}
    for session in sessions:
        last[period(session)] = session
    if sessions and (following is None or period(following) == period(sessions[-1])):
        del last[period(sessions[-1])]
    return frozenset(last.values())


DecisionSchedule = EverySession | EveryNSessions | Weekly | Monthly
"""Every schedule a run may be given.

A union rather than a protocol: there are four of them, they are all data, and
a reader of a configuration should be able to see the whole list at once.
"""
