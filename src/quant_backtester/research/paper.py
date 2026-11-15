"""Paper trading: the one out-of-sample test the history has left.

Every year from 2018 to 2026 has been looked at, printed in the README and
has shaped a choice, so no stretch of that history is out of sample for the
rotation any more - a holdout carved from it now would be a holdout in name.
What is left is the future. A plan fixes a strategy and the conditions it is
run under, and a start date; from then on the strategy is run every session on
the data as it arrives, and what it did is appended to a log that is never
rewritten.

What is refused, because each would quietly turn the test back into a
backtest:

- **another experiment under the same name.** A plan commits to a contract -
  the strategy's fingerprint and every condition of its run: execution and
  costs, starting cash, schedule, timetable, universe, limits, lot sizes,
  benchmark (decision D19 of the audit of archive 9). Its ``contract_id`` is
  written in the plan and at the head of its log, and checked before anything
  is computed. Only committed code may advance a plan; the commit is logged
  with every session, so a fix to the code is visible, and the check below
  catches any change it makes to what was done;
- **a past that changes.** Every run re-decides the whole period, and a
  session already logged must come out exactly as it was logged - the
  decision, the orders, the fills with their prices and costs, the rejects,
  the book and the cash, not a summary of them (D18): a revised price once let
  100 shares bought at 100 become 200 bought at 50 behind an unchanged equity.
  The log keeps what was done at the time, and the run stops until someone
  looks;
- **a session logged before it happened.** A session is logged once its
  decision instant has passed, every instrument the plan trades has a close
  of that session (D24), and the store can be shown to hold every series up
  to what was published at that instant. The proof is an observation stored
  at or after that point, so a session followed by a day without one - a
  weekend for a rate released the next day, a publisher's holiday - is logged
  a day or so late rather than on a guess (:func:`series_short_of`);
- **two writers.** Reading the log, checking it and appending to it hold an
  exclusive lock on it, and a session already logged identically is simply
  already done: running twice changes nothing (D22);
- **a line half written.** A run's new lines are written in one call and
  flushed to disk before the lock is released. What an interrupted append
  left after the last line break was never a logged session: it is ignored on
  reading and removed by the next append, which logs that session whole. A
  complete line that cannot be read is another matter, and stops the run.
"""

from __future__ import annotations

import hashlib
import json
import os
import tomllib
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from quant_backtester.backtest.runner import StrategyResult, StrategyRunner, plain_configuration
from quant_backtester.backtest.schedule import DecisionSchedule
from quant_backtester.backtest.timetable import BacktestTimetable
from quant_backtester.data.calendars import TradingCalendar
from quant_backtester.provenance import SourceStatus
from quant_backtester.research.journal import exclusive
from quant_backtester.signals.types import require_identifier
from quant_backtester.strategies.base import Strategy

CONTRACT_KEYS: tuple[str, ...] = (
    "initial_cash",
    "base_currency",
    "reference_calendar",
    "schedule",
    "timetable",
    "universe",
    "signals",
    "portfolio",
    "execution",
    "quantity_steps",
    "decision_lifetime",
    "analytics",
    "benchmark",
)
"""The parts of a run's configuration a plan commits to.

Left out, on purpose, is what changes from one day's run to the next without
the experiment changing: the period, the state of the store and of the code,
and the digests of the registries - a calendar gains a year of holidays every
December, and an instrument's note can be reworded. What the strategy does
with them is still checked, session by session, by the log.
"""


class PaperPlanBroken(RuntimeError):
    """Raised when a run would no longer be the plan that was committed to."""


def contract_of(result: StrategyResult) -> dict[str, object]:
    """Return the conditions of a run a plan commits to, and the strategy's fingerprint."""
    configuration = plain_configuration(result.configuration)
    assert isinstance(configuration, dict)
    return {
        "fingerprint": result.fingerprint,
        **{key: configuration.get(key) for key in CONTRACT_KEYS},
    }


def contract_id(result: StrategyResult) -> str:
    """Return the SHA-256 of a run's contract, rendered as canonical JSON."""
    canonical = json.dumps(contract_of(result), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class PaperPlan:
    """A strategy, and the conditions it is run under, committed to before its test starts.

    Attributes
    ----------
    name : str
        Name of the plan, and of its log.
    start : date
        First session of the test. Chosen before it, and never moved.
    universe : tuple[str, ...]
        Ids of the instruments the strategy may hold. A plain list is honest
        here: a plan runs forward from its start, on instruments that exist
        at it.
    contract_id : str
        :func:`contract_id` of a run of the plan: the strategy's fingerprint
        and every condition of :data:`CONTRACT_KEYS`.
    note : str
        What is being tested, and what would count as a failure.
    """

    name: str
    start: date
    universe: tuple[str, ...]
    contract_id: str
    note: str

    def __post_init__(self) -> None:
        """Reject a plan that does not say what it commits to."""
        require_identifier(self.name, "name")
        if not self.universe or len(set(self.universe)) != len(self.universe):
            raise ValueError(f"plan {self.name} names no instrument, or one twice")
        for member in self.universe:
            require_identifier(member, "universe")
        require_identifier(self.contract_id, "contract_id")
        if not self.note.strip():
            raise ValueError(f"plan {self.name} does not say what it tests")

    @classmethod
    def from_toml(cls, path: Path) -> PaperPlan:
        """Load a committed plan."""
        with path.open("rb") as handle:
            table = tomllib.load(handle)
        expected = {"name", "start", "universe", "contract_id", "note"}
        if set(table) != expected:
            raise ValueError(f"{path}: a plan has exactly the keys {sorted(expected)}")
        return cls(**{**table, "universe": tuple(table["universe"])})


@dataclass(frozen=True, slots=True)
class PaperEntry:
    """What the plan did on one session - all of it, as it was first logged.

    Attributes
    ----------
    session_date : str
        ISO date of the session.
    decided : bool
        Whether the strategy was asked on it.
    decision : dict[str, object] | None
        The decision taken at its close: accepted weights, the lines kept, the
        lines bought with cash, and whether the book was held. ``None`` when
        none was taken.
    orders : list[dict[str, object]]
        Orders sent at its open: instrument, side, quantity.
    fills : list[dict[str, object]]
        Fills: instrument, side, quantity, market and fill prices, commission,
        spread and slippage.
    rejects : list[dict[str, object]]
        Refusals: instrument, reason, side, requested quantity.
    holdings : dict[str, float]
        Units held after the session.
    cash : float
        Cash after the session.
    net_equity : float
        The book's worth at its close.
    """

    session_date: str
    decided: bool
    decision: dict[str, object] | None
    orders: list[dict[str, object]]
    fills: list[dict[str, object]]
    rejects: list[dict[str, object]]
    holdings: dict[str, float]
    cash: float
    net_equity: float

    def as_json(self) -> str:
        """Return the entry as canonical JSON."""
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))


def entries_of(result: StrategyResult) -> list[PaperEntry]:
    """Return one log entry per session of a run, with the whole economic state."""
    entries: list[PaperEntry] = []
    for record in result.records():
        decision = record.decision
        entries.append(
            PaperEntry(
                session_date=record.session_date.isoformat(),
                decided=record.decided,
                decision=(
                    None
                    if decision is None
                    else {
                        "weights": {
                            name: float(weight)
                            for name, weight in sorted(decision.accepted_weights.items())
                        },
                        "kept": sorted(decision.kept),
                        "cash_shares": {
                            name: float(share)
                            for name, share in sorted(decision.cash_shares.items())
                        },
                        "hold": decision.holds_positions,
                    }
                ),
                orders=[
                    {
                        "instrument_id": order.instrument_id,
                        "side": order.side.value,
                        "quantity": float(order.quantity),
                    }
                    for order in record.orders
                ],
                fills=[
                    {
                        "instrument_id": fill.instrument_id,
                        "side": fill.side.value,
                        "quantity": float(fill.quantity),
                        "market_price": float(fill.market_price),
                        "fill_price": float(fill.fill_price),
                        "commission": float(fill.commission),
                        "spread_cost": float(fill.spread_cost),
                        "slippage_cost": float(fill.slippage_cost),
                    }
                    for fill in record.fills
                ],
                rejects=[
                    {
                        "instrument_id": reject.instrument_id,
                        "reason": reject.reason.value,
                        "side": None if reject.side is None else reject.side.value,
                        "requested_quantity": reject.requested_quantity,
                    }
                    for reject in record.rejects
                ],
                holdings={
                    name: float(quantity) for name, quantity in sorted(record.quantities.items())
                },
                cash=float(record.cash),
                net_equity=float(record.net_equity),
            )
        )
    return entries


def last_ready_session(
    runner: StrategyRunner, plan: PaperPlan, stored_until: date, now: datetime
) -> date | None:
    """Return the last session a plan may be run to at ``now``.

    Parameters
    ----------
    runner : StrategyRunner
        The runner the plan is run with: its calendar and timetable.
    plan : PaperPlan
        The plan; its universe names what must have a close.
    stored_until : date
        The last session the caller allows: the store holds nothing later, or
        is not known to be complete later.
    now : datetime
        Timezone-aware wall-clock instant, passed in by the script.

    Returns
    -------
    date | None
        The latest session no later than ``stored_until`` whose decision
        instant has passed and on which every member of the universe has a
        close of that very session; ``None`` if there is none.
    """
    if now.tzinfo is None:
        raise ValueError(f"now must be timezone-aware, got {now!r}")
    calendar = runner.calendars.get(runner.reference_calendar_id)
    session = calendar.session(stored_until) or calendar.previous_session(stored_until)
    while session is not None:
        day = session.session_date
        decided_at = runner.timetable.decision_instant(day)
        if decided_at <= now:
            members = list(plan.universe)
            market = runner.reader.at(decided_at)
            frame = market.values(members)
            if all(frame.loc[name, "observation_date"] == day for name in members):
                return day
        if day <= plan.start:
            return None
        session = calendar.previous_session(day)
    return None


def series_short_of(
    instruments: Sequence[str],
    published_until: Callable[[str, datetime], date],
    stored_until: Callable[[str], date | None],
    decided_at: datetime,
) -> dict[str, tuple[date | None, date]]:
    """Return the series a store cannot show to be whole at a decision instant.

    Parameters
    ----------
    instruments : Sequence[str]
        Every series the plans read, traded or not.
    published_until : Callable[[str, datetime], date]
        For an instrument and an instant, the latest date an observation
        published at it can carry
        (:meth:`~quant_backtester.data.updater.MarketDataUpdater.published_until`).
    stored_until : Callable[[str], date | None]
        The latest observation date the store holds for an instrument.
    decided_at : datetime
        Timezone-aware decision instant of the session.

    Returns
    -------
    dict[str, tuple[date | None, date]]
        For each series stored short of that date: where it stops in the
        store (``None`` if it is empty) and the date it has to reach. Empty
        when nothing is waited for.

    Notes
    -----
    The date a series has to reach need not carry an observation. A rate
    released the next business day has, on a Monday evening, a bound of
    Sunday; an index has no value on its publisher's holiday. The store then
    stops on the last real observation, short of the bound, and nothing here
    can tell a day that has no observation from one a provider serves late -
    and a provider does serve late. So the series is counted as waited for,
    and stops being so when a later observation is stored. The session is
    logged a day or so after it could have been; it is never logged before a
    value its decision could read.
    """
    short: dict[str, tuple[date | None, date]] = {}
    for name in instruments:
        last, needed = stored_until(name), published_until(name, decided_at)
        if last is None or last < needed:
            short[name] = (last, needed)
    return short


def _decided_sessions(
    calendar: TradingCalendar, timetable: BacktestTimetable, now: datetime, not_before: date
) -> Iterator[tuple[date, datetime]]:
    """Yield, latest first, each session since ``not_before`` whose decision instant has passed."""
    if now.tzinfo is None:
        raise ValueError(f"now must be timezone-aware, got {now!r}")
    today = now.astimezone(UTC).date()
    session = calendar.session(today) or calendar.previous_session(today)
    while session is not None and session.session_date >= not_before:
        decided_at = timetable.decision_instant(session.session_date)
        if decided_at <= now:
            yield session.session_date, decided_at
        session = calendar.previous_session(session.session_date)


def last_complete_session(
    calendar: TradingCalendar,
    timetable: BacktestTimetable,
    instruments: Sequence[str],
    published_until: Callable[[str, datetime], date],
    stored_until: Callable[[str], date | None],
    now: datetime,
    not_before: date,
) -> date | None:
    """Return the last session whose decision the store can no longer change.

    A plan re-decides its whole period at every run, and a session already
    logged must come out as it was logged. A session logged before the store
    held everything its decision could read - a US close, a rate released the
    next morning - would come out differently the day that value arrives. So
    a session is logged only once nothing published at its decision instant
    can still be missing.

    Parameters
    ----------
    calendar : TradingCalendar
        The reference calendar the plans decide on.
    timetable : BacktestTimetable
        Gives each session's decision instant.
    instruments : Sequence[str]
        Every series the plans read, traded or not.
    published_until : Callable[[str, datetime], date]
        For an instrument and an instant, the latest date an observation
        published at it can carry, on the instrument's own calendar and
        publication rule
        (:meth:`~quant_backtester.data.updater.MarketDataUpdater.published_until`).
    stored_until : Callable[[str], date | None]
        The latest observation date the store holds for an instrument.
    now : datetime
        Timezone-aware wall-clock instant, passed in by the script.
    not_before : date
        Where to stop looking: sessions before it are of no use to the caller.

    Returns
    -------
    date | None
        The latest session, no earlier than ``not_before``, whose decision
        instant has passed and for which :func:`series_short_of` is empty;
        ``None`` if there is none.

    Notes
    -----
    The proof that a series is whole is an observation stored at or after its
    bound. Where the bound falls on a day without an observation, that proof
    arrives with the next observation: see :func:`series_short_of`. The
    session waits; it is not skipped, and :func:`session_held_back` names
    what it waits for.

    The end of each series is compared, not its inside: a bar a provider
    skipped and serves later is not seen here. It is caught where it matters,
    by the log, which refuses a logged session that comes out differently.
    """
    stored = {name: stored_until(name) for name in instruments}
    for session_date, decided_at in _decided_sessions(calendar, timetable, now, not_before):
        if not series_short_of(instruments, published_until, stored.__getitem__, decided_at):
            return session_date
    return None


def session_held_back(
    calendar: TradingCalendar,
    timetable: BacktestTimetable,
    instruments: Sequence[str],
    published_until: Callable[[str, datetime], date],
    stored_until: Callable[[str], date | None],
    now: datetime,
    not_before: date,
) -> tuple[date, dict[str, tuple[date | None, date]]] | None:
    """Return the latest decided session and the series it waits for, if it waits.

    Parameters are those of :func:`last_complete_session`.

    Returns
    -------
    tuple[date, dict[str, tuple[date | None, date]]] | None
        The latest session, no earlier than ``not_before``, whose decision
        instant has passed, with :func:`series_short_of` at that instant;
        ``None`` if that session is complete or there is no such session.
    """
    for session_date, decided_at in _decided_sessions(calendar, timetable, now, not_before):
        short = series_short_of(instruments, published_until, stored_until, decided_at)
        return (session_date, short) if short else None
    return None


def run_plan(
    plan: PaperPlan,
    runner: StrategyRunner,
    strategy: Strategy,
    schedule: DecisionSchedule,
    until: date,
) -> StrategyResult | None:
    """Run the plan from its start to ``until``, after checking it is still the plan.

    Returns
    -------
    StrategyResult | None
        The run, or ``None`` before the plan starts - its contract checked all
        the same, on a run of the last session, so a plan misconfigured before
        its start fails before its start.

    Raises
    ------
    PaperPlanBroken
        If the code is not committed, or the run is not under the contract the
        plan committed to.
    """
    if runner.source.status is not SourceStatus.CLEAN:
        raise PaperPlanBroken(
            f"plan {plan.name} is advanced by committed code only; this tree is "
            f"{runner.source.status.value}"
        )
    first = until if until < plan.start else plan.start
    result = runner.run(strategy, list(plan.universe), first, until, schedule=schedule)
    found = contract_id(result)
    if found != plan.contract_id:
        raise PaperPlanBroken(
            f"plan {plan.name} committed to contract {plan.contract_id} and this run is "
            f"{found}: a changed rule, cost, capital, schedule or universe is a new plan, "
            "with a new start"
        )
    return None if until < plan.start else result


class PaperLog:
    """The append-only log of a plan: a header naming its contract, then one line per session.

    Parameters
    ----------
    path : Path
        The log file, committed with the plan.
    plan : PaperPlan
        The plan it logs. A log whose header names another contract is refused.
    """

    def __init__(self, path: Path, plan: PaperPlan) -> None:
        self.path = path
        self.plan = plan

    def entries(self) -> list[PaperEntry]:
        """Return every logged session, in order."""
        return [entry for entry, _ in self._lines()]

    def _lines(self) -> list[tuple[PaperEntry, Mapping[str, object]]]:
        """Return the logged sessions with what each was logged with."""
        return self._read()[0]

    def _read(self) -> tuple[list[tuple[PaperEntry, Mapping[str, object]]], int]:
        """Return the logged sessions, and how many bytes of the log they and its header fill.

        The file is read once. Every line is written with its line break, so
        bytes after the last one are what an interrupted append left: not a
        logged session. A log with no line - absent, empty, or blank - fills
        no byte: its header is still to be written.
        """
        if not self.path.exists():
            return [], 0
        content = self.path.read_bytes()
        whole = content.rfind(b"\n") + 1
        try:
            lines = [line for line in content[:whole].decode("utf-8").splitlines() if line]
            if not lines:
                return [], 0
            header = json.loads(lines[0])
            rows = [json.loads(line) for line in lines[1:]]
            logged = [(PaperEntry(**row["entry"]), row["logged_with"]) for row in rows]
        except (ValueError, KeyError, TypeError) as error:
            raise PaperPlanBroken(
                f"{self.path} holds a complete line that is not a log line ({error}): the log "
                "was edited or damaged. Restore it from its last commit; nothing is appended "
                "to it meanwhile."
            ) from error
        if header != self._header():
            raise PaperPlanBroken(
                f"{self.path} was started under {header} and the plan is {self._header()}"
            )
        return logged, whole

    def _header(self) -> dict[str, object]:
        """Return the line a log of this plan starts with."""
        return {
            "plan": self.plan.name,
            "start": self.plan.start.isoformat(),
            "contract_id": self.plan.contract_id,
        }

    def extend(
        self, entries: Sequence[PaperEntry], *, git_commit: str, logged_at: datetime
    ) -> list[PaperEntry]:
        """Append the sessions not logged yet, after checking the others did not change.

        Parameters
        ----------
        entries : Sequence[PaperEntry]
            What today's run says about every session since the start.
        git_commit : str
            The commit today's run was produced by, logged with each new line.
        logged_at : datetime
            Timezone-aware instant of the logging.

        Returns
        -------
        list[PaperEntry]
            The entries appended; empty when every one was already logged.

        Raises
        ------
        PaperPlanBroken
            If a session already logged comes out differently, or today's run
            covers fewer sessions than were logged.
        """
        if logged_at.tzinfo is None:
            raise ValueError(f"logged_at must be timezone-aware, got {logged_at!r}")
        with exclusive(self.path):
            # Read again under the lock: what another writer appended a moment
            # ago is part of the past this run has to agree with.
            read, whole = self._read()
            logged = [entry for entry, _ in read]
            if len(entries) < len(logged):
                raise PaperPlanBroken(
                    f"today's run covers {len(entries)} session(s) and {len(logged)} were logged"
                )
            for before, now in zip(logged, entries, strict=False):
                if before != now:
                    raise PaperPlanBroken(
                        f"session {before.session_date} was logged as {before.as_json()} and "
                        f"comes out today as {now.as_json()}: what the plan did has changed. "
                        "The log keeps what was done; review before going on."
                    )
            new = list(entries[len(logged) :])
            if new:
                lines = [] if whole else [json.dumps(self._header(), sort_keys=True)]
                lines += [
                    json.dumps(
                        {
                            "entry": asdict(entry),
                            "logged_with": {
                                "git_commit": git_commit,
                                "logged_at": logged_at.isoformat(),
                            },
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    for entry in new
                ]
                payload = "".join(line + "\n" for line in lines).encode("utf-8")
                with self.path.open("ab") as handle:
                    # Drop what an interrupted append left (or the blank
                    # lines of a log with no header), then write this run's
                    # lines in one call and have them on disk before the
                    # lock is released.
                    handle.truncate(whole)
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
            return new
