"""Paper trading: the one out-of-sample test the history has left.

Every year from 2018 to 2026 has been looked at, printed in the README and
has shaped a choice, so no stretch of that history is out of sample for the
rotation any more - a holdout carved from it now would be a holdout in name.
What is left is the future. A plan fixes a strategy, by its fingerprint, and a
start date; from then on the strategy is run every session on the data as it
arrives, and what it decided is appended to a log that is never rewritten.

Two things are refused, because either would quietly turn the test back into
a backtest:

- a strategy whose fingerprint is not the plan's: a rule tuned after the start
  is a new plan, with a new start;
- a past that changes: every run re-decides the whole period, and a session
  already logged must come out exactly as it was logged. When it does not, a
  provider has revised a price the plan already acted on - the log keeps what
  was decided at the time, and the run stops until someone looks.
"""

from __future__ import annotations

import json
import tomllib
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from quant_backtester.backtest.runner import StrategyResult, StrategyRunner
from quant_backtester.backtest.schedule import DecisionSchedule
from quant_backtester.signals.types import require_identifier
from quant_backtester.strategies.base import Strategy


class PaperPlanBroken(RuntimeError):
    """Raised when a run would no longer be the plan that was committed to."""


@dataclass(frozen=True, slots=True)
class PaperPlan:
    """A strategy committed to before its test period starts.

    Attributes
    ----------
    name : str
        Name of the plan, and of its log.
    start : date
        First session of the test. Chosen before it, and never moved.
    universe : str
        Id of the committed universe the strategy trades.
    strategy_fingerprint : str
        The fingerprint of the strategy committed to.
    note : str
        What is being tested, and what would count as a failure.
    """

    name: str
    start: date
    universe: str
    strategy_fingerprint: str
    note: str

    def __post_init__(self) -> None:
        """Reject a plan that does not say what it commits to."""
        require_identifier(self.name, "name")
        require_identifier(self.universe, "universe")
        require_identifier(self.strategy_fingerprint, "strategy_fingerprint")
        if not self.note.strip():
            raise ValueError(f"plan {self.name} does not say what it tests")

    @classmethod
    def from_toml(cls, path: Path) -> PaperPlan:
        """Load a committed plan."""
        with path.open("rb") as handle:
            table = tomllib.load(handle)
        expected = {"name", "start", "universe", "strategy_fingerprint", "note"}
        if set(table) != expected:
            raise ValueError(f"{path}: a plan has exactly the keys {sorted(expected)}")
        return cls(**table)


@dataclass(frozen=True, slots=True)
class PaperEntry:
    """What the plan did on one session, as it was first logged.

    Attributes
    ----------
    session_date : str
        ISO date of the session.
    decided : bool
        Whether the strategy was asked on it.
    target : dict[str, float]
        The weights accepted at its decision, empty when none was taken.
    net_equity : float
        The book's worth at its close.
    fills : int
        Orders done at its open.
    """

    session_date: str
    decided: bool
    target: dict[str, float]
    net_equity: float
    fills: int

    def as_json(self) -> str:
        """Return the entry as one canonical JSON line."""
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))


def entries_of(result: StrategyResult) -> list[PaperEntry]:
    """Return one log entry per session of a run."""
    return [
        PaperEntry(
            session_date=record.session_date.isoformat(),
            decided=record.decided,
            target=(
                {name: float(weight) for name, weight in record.decision.accepted_weights.items()}
                if record.decision is not None
                else {}
            ),
            net_equity=float(record.net_equity),
            fills=len(record.fills),
        )
        for record in result.records()
    ]


def run_plan(
    plan: PaperPlan,
    runner: StrategyRunner,
    strategy: Strategy,
    schedule: DecisionSchedule,
    until: date,
) -> StrategyResult | None:
    """Run the plan from its start to ``until``.

    Returns
    -------
    StrategyResult | None
        The run, or ``None`` before the plan starts.

    Raises
    ------
    PaperPlanBroken
        If the strategy is not the one the plan committed to.
    """
    if strategy.fingerprint() != plan.strategy_fingerprint:
        raise PaperPlanBroken(
            f"the strategy's fingerprint {strategy.fingerprint()} is not the "
            f"{plan.strategy_fingerprint} plan {plan.name} committed to: a changed rule "
            "is a new plan, with a new start"
        )
    if until < plan.start:
        return None
    return runner.run(strategy, plan.universe, plan.start, until, schedule=schedule)


class PaperLog:
    """The append-only log of a plan, one JSON line per session.

    Parameters
    ----------
    path : Path
        The log file, committed with the plan.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def entries(self) -> list[PaperEntry]:
        """Return every logged session, in order."""
        if not self.path.exists():
            return []
        return [
            PaperEntry(**json.loads(line))
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def extend(self, entries: Sequence[PaperEntry]) -> list[PaperEntry]:
        """Append the sessions not logged yet, after checking the others did not change.

        Parameters
        ----------
        entries : Sequence[PaperEntry]
            What today's run says about every session since the start.

        Returns
        -------
        list[PaperEntry]
            The entries appended.

        Raises
        ------
        PaperPlanBroken
            If a session already logged comes out differently, or today's run
            covers fewer sessions than were logged.
        """
        logged = self.entries()
        if len(entries) < len(logged):
            raise PaperPlanBroken(
                f"today's run covers {len(entries)} session(s) and {len(logged)} were logged"
            )
        for before, now in zip(logged, entries, strict=False):
            if before != now:
                raise PaperPlanBroken(
                    f"session {before.session_date} was logged as {before.as_json()} and "
                    f"comes out today as {now.as_json()}: the data it was decided on has "
                    "changed. The log keeps what was decided; review before going on."
                )
        new = list(entries[len(logged) :])
        if new:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                for entry in new:
                    handle.write(entry.as_json() + "\n")
        return new
