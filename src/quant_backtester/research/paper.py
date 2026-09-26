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
  decision instant has passed and every instrument the plan trades has a close
  of that session (D24);
- **two writers.** Reading the log, checking it and appending to it hold an
  exclusive lock on it, and a session already logged identically is simply
  already done: running twice changes nothing (D22).
"""

from __future__ import annotations

import hashlib
import json
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path

from quant_backtester.backtest.runner import StrategyResult, StrategyRunner, plain_configuration
from quant_backtester.backtest.schedule import DecisionSchedule
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
    universe : str
        Id of the committed universe the strategy trades.
    contract_id : str
        :func:`contract_id` of a run of the plan: the strategy's fingerprint
        and every condition of :data:`CONTRACT_KEYS`.
    note : str
        What is being tested, and what would count as a failure.
    """

    name: str
    start: date
    universe: str
    contract_id: str
    note: str

    def __post_init__(self) -> None:
        """Reject a plan that does not say what it commits to."""
        require_identifier(self.name, "name")
        require_identifier(self.universe, "universe")
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
        return cls(**table)


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
        The last session the store holds anything for.
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
    if runner.universes is None:
        raise ValueError(f"the runner declares no universes, so {plan.universe} is unknown")
    universe = runner.universes.get(plan.universe)
    session = calendar.session(stored_until) or calendar.previous_session(stored_until)
    while session is not None:
        day = session.session_date
        decided_at = runner.timetable.decision_instant(day)
        if decided_at <= now:
            members = list(universe.members_at(day))
            market = runner.reader.at(decided_at)
            frame = market.values(members)
            if all(frame.loc[name, "observation_date"] == day for name in members):
                return day
        if day <= plan.start:
            return None
        session = calendar.previous_session(day)
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
    result = runner.run(strategy, plan.universe, first, until, schedule=schedule)
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
        if not self.path.exists():
            return []
        lines = [line for line in self.path.read_text(encoding="utf-8").splitlines() if line]
        header = json.loads(lines[0])
        if header != self._header():
            raise PaperPlanBroken(
                f"{self.path} was started under {header} and the plan is {self._header()}"
            )
        rows = [json.loads(line) for line in lines[1:]]
        return [(PaperEntry(**row["entry"]), row["logged_with"]) for row in rows]

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
            logged = self.entries()
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
                with self.path.open("a", encoding="utf-8") as handle:
                    if not logged and self.path.stat().st_size == 0:
                        handle.write(json.dumps(self._header(), sort_keys=True) + "\n")
                    for entry in new:
                        line = {
                            "entry": asdict(entry),
                            "logged_with": {
                                "git_commit": git_commit,
                                "logged_at": logged_at.isoformat(),
                            },
                        }
                        handle.write(json.dumps(line, sort_keys=True, separators=(",", ":")))
                        handle.write("\n")
            return new
