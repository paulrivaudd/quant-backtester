"""The three instants of a session, declared rather than assumed.

A daily backtest is full of "the price of the day", and there is no such thing.
There is the price a decision reads, the price an order is filled at and the
price a book is valued at, and each belongs to its own instant. Collapse two
of them and the run either trades on a number it has not seen yet or values a
book at a number nobody traded at.

So every session of a run has three instants, all declared here and recorded
with the result:

- **execution**: just after the opening auction, the order decided at the
  previous decision is sent and filled at that auction's price;
- **valuation**: after the close, the book is marked at the closing prices
  knowable by then;
- **decision**: after that - late enough in Paris that the New York close of
  the same day is published - the signals are computed and the next target is
  decided, on the book as it was just valued.

The order is enforced: execution before valuation, valuation no later than the
decision. A decision taken before its own book was valued would be handed a
portfolio from the future of the decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from quant_backtester.data.schemas import BarField


@dataclass(frozen=True, slots=True)
class ExecutionTiming:
    """Which price a decision is filled at, and how many sessions later.

    Attributes
    ----------
    field : BarField
        The bar field an order is filled at.
    session_offset : int
        Sessions of the reference calendar between the decision session and
        the execution session.

    Raises
    ------
    ValueError
        If the timing is anything but the opening auction of the next session.
        That is the only one this version implements, and it is declared
        rather than hard-wired so that a result says which one it used. A
        close of the same session is the price the decision was computed from;
        two sessions later needs a queue of decisions in flight that nothing
        here models.
    """

    field: BarField = BarField.OPEN
    session_offset: int = 1

    def __post_init__(self) -> None:
        """Refuse a timing this version does not implement."""
        if self.field is not BarField.OPEN or self.session_offset != 1:
            raise ValueError(
                f"only the opening auction of the next session is implemented, got "
                f"{self.field!r} at an offset of {self.session_offset!r}"
            )

    def definition(self) -> dict[str, object]:
        """Return the timing as it is recorded with a run."""
        return {"field": self.field.value, "session_offset": self.session_offset}


@dataclass(frozen=True, slots=True)
class BacktestTimetable:
    """When, on each session, an order is filled, the book valued and a target decided.

    Attributes
    ----------
    decision_time : time
        Local time at which the signals are computed and the next target is
        decided. Late enough that every close the strategy reads is published:
        23:00 in Paris is after New York's close, which is the case the
        project is built for.
    execution_time : time
        Local time at which the order decided at the previous decision is sent
        and filled. Just after the opening auction, since that is the price it
        is filled at - and the price must be knowable when the order is sized.
    valuation_time : time
        Local time at which the book is marked at the closing prices. After the
        execution, and no later than the decision, which is handed the book as
        it was valued.
    timezone : str
        IANA zone the three times are expressed in. The reference calendar's
        own zone, normally, so that a run is stated in the hours its decisions
        are actually taken in.
    execution : ExecutionTiming
        Which price, how many sessions later.

    Raises
    ------
    ValueError
        If a time carries a fixed offset, the zone is unknown, or the three
        instants are not in the order execution, valuation, decision. A
        wall-clock time plus a zone survives a DST switch; a time with an
        offset baked in does not, and the decision would move by an hour
        twice a year.
    """

    decision_time: time = time(23, 0)
    execution_time: time = time(9, 1)
    valuation_time: time = time(23, 0)
    timezone: str = "Europe/Paris"
    execution: ExecutionTiming = field(default_factory=ExecutionTiming)

    def __post_init__(self) -> None:
        """Reject a timetable whose instants are ambiguous or out of order."""
        for name, value in (
            ("decision_time", self.decision_time),
            ("execution_time", self.execution_time),
            ("valuation_time", self.valuation_time),
        ):
            if not isinstance(value, time):
                raise ValueError(f"{name} must be a time, got {value!r}")
            if value.tzinfo is not None:
                raise ValueError(f"{name} must be a naive local time, got {value!r}")
        ZoneInfo(self.timezone)
        if not self.execution_time < self.valuation_time:
            raise ValueError(
                f"the book is valued at {self.valuation_time} and orders are filled at "
                f"{self.execution_time}: a session's fills must come before its valuation"
            )
        if not self.valuation_time <= self.decision_time:
            raise ValueError(
                f"the decision at {self.decision_time} would be handed a book valued at "
                f"{self.valuation_time}, after it"
            )
        if not isinstance(self.execution, ExecutionTiming):
            raise ValueError(f"execution must be an ExecutionTiming, got {self.execution!r}")

    def definition(self) -> dict[str, object]:
        """Return the timetable as it is recorded with a run."""
        return {
            "decision_time": self.decision_time.isoformat(),
            "execution_time": self.execution_time.isoformat(),
            "valuation_time": self.valuation_time.isoformat(),
            "timezone": self.timezone,
            "execution": self.execution.definition(),
        }

    def decision_instant(self, session_date: date) -> datetime:
        """Return the timezone-aware instant a decision is taken on that session."""
        return self._on(session_date, self.decision_time)

    def execution_instant(self, session_date: date) -> datetime:
        """Return the timezone-aware instant an order is filled on that session."""
        return self._on(session_date, self.execution_time)

    def valuation_instant(self, session_date: date) -> datetime:
        """Return the timezone-aware instant the book is valued on that session."""
        return self._on(session_date, self.valuation_time)

    def _on(self, session_date: date, local: time) -> datetime:
        """Return a local wall-clock time on a session date, in the timetable's zone."""
        return datetime.combine(session_date, local, tzinfo=ZoneInfo(self.timezone))
