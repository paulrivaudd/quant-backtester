"""Run the committed paper plans forward, and log what each one decided.

Run under WSL/POSIX from the repository root, after an update of the paper
store::

    uv run python scripts/paper_update_store.py
    uv run python scripts/paper_trade.py
    git add research/paper/*.jsonl && git commit -m "paper: sessions to <date>"

Each plan of ``research/paper/`` is run from its start to its last ready
session, under the conventions of the SA16 study (``scripts/SA16_run_study.py``:
Paris calendar, euro book of 100 000 EUR, its costs, sizing at the 23:00
Paris decision, fill at the next open). Every session not yet logged is
appended to the plan's log, next to the plan. Before a plan's start only its
contract is checked.

A session is ready when its decision instant has passed, every fund of the
plan has a close of that session, and the store holds every series up to what
was published at that instant - so that nothing arriving later can change
what the plan decided on it. The store shows it by holding an observation at
or after that point: after a day without one (a weekend for a rate released
the next day, a publisher's holiday) a session waits for the next observation
and is logged a day or so late. The script names the series it waits for.

Uncommitted code, a run under another contract, or a logged past that comes
out differently stops the script: see ``research/PROTOCOL.md``. The logs
themselves may be uncommitted: they are what this script writes. Running it
twice changes nothing. It performs no network I/O.

``--contracts`` prints the contract id of each book on the last complete
session and logs nothing: it is how a plan file is written, before its start.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from paper_update_store import STORE  # noqa: E402
from SA16_download_data import INSTRUMENT_IDS, STUDY_END, build_updater  # noqa: E402
from SA16_run_study import (  # noqa: E402
    OUTPUT,
    SCHEDULES,
    UNIVERSE,
    build_runner,
    build_strategy,
    sa15_reference,
)

from quant_backtester.backtest.runner import StrategyRunner  # noqa: E402
from quant_backtester.backtest.schedule import DecisionSchedule, EverySession  # noqa: E402
from quant_backtester.data.repository import MarketDataRepository  # noqa: E402
from quant_backtester.provenance import SourceState, SourceStatus, git_source_state  # noqa: E402
from quant_backtester.research.paper import (  # noqa: E402
    PaperLog,
    PaperPlan,
    PaperPlanBroken,
    contract_id,
    entries_of,
    last_complete_session,
    last_ready_session,
    run_plan,
    session_held_back,
)
from quant_backtester.research.references import BuyAndHold  # noqa: E402
from quant_backtester.strategies.base import Strategy  # noqa: E402

PLANS = ROOT / "research" / "paper"
"""Where the committed plans and their logs live."""

SELECTED = OUTPUT / "selected.json"
"""The configuration the SA16 study retained, frozen with its fingerprint."""


def books() -> dict[str, tuple[Strategy, DecisionSchedule]]:
    """Return the strategy each plan names, as code. The plan's contract checks it.

    Raises
    ------
    ValueError
        If SA16_it2 rebuilt from ``results/SA16/selected.json`` does not have
        the fingerprint the study recorded.
    """
    selected = json.loads(SELECTED.read_text(encoding="utf-8"))
    candidate = build_strategy(selected["class"], selected["parameters"])
    if candidate.fingerprint() != selected["fingerprint"]:
        raise ValueError("SA16_it2 rebuilt from selected.json does not match its fingerprint")
    reference = sa15_reference()
    return {
        "SA16_IT2": (candidate, SCHEDULES[selected["schedule"]]()),
        "NASDAQ_BUY_HOLD": (BuyAndHold(("ETF_NASDAQ",)), EverySession()),
        "SA15_R4_TRIAL71": (reference.strategy, reference.schedule),
    }


def code_state(root: Path, logs: Path) -> SourceState:
    """Return the checkout's state, lines appended to the plans' logs not counting as a change.

    A log is what this script appends to, and it is committed after the run:
    between the two it is a modified file. Only that is let through: a log
    not committed yet, or a committed log whose committed bytes are still the
    beginning of the file. A log deleted, shortened or edited is a change like
    any other, so the run stops instead of writing the missing sessions again
    from today's store. Anything else changed or untracked leaves the state
    as git reports it.
    """
    state = git_source_state(root)
    if state.status is not SourceStatus.DIRTY:
        return state
    changed: set[Path] = set()
    for arguments in (
        ["diff", "HEAD", "--no-renames", "--name-only", "-z"],
        ["ls-files", "--others", "--exclude-standard", "-z"],
    ):
        result = subprocess.run(
            ["git", "-C", str(root), *arguments], check=True, capture_output=True
        )
        changed.update(
            (root / name.decode()).resolve() for name in result.stdout.split(b"\0") if name
        )
    folder = logs.resolve()
    if all(
        path.parent == folder and path.suffix == ".jsonl" and _only_appended(root, path)
        for path in changed
    ):
        return SourceState(SourceStatus.CLEAN, state.git_commit)
    return state


def _only_appended(root: Path, log: Path) -> bool:
    """Return whether a log still starts with the bytes committed for it, if any were."""
    if not log.is_file():
        return False
    name = log.relative_to(root.resolve()).as_posix()
    committed = subprocess.run(
        ["git", "-C", str(root), "show", f"HEAD:{name}"], check=False, capture_output=True
    )
    if committed.returncode != 0:
        # Not in the commit: the first sessions of a plan, not committed yet.
        return True
    return log.read_bytes().startswith(committed.stdout)


def complete_until(runner: StrategyRunner, store: Path, now: datetime, not_before: date) -> date:
    """Return the last session the store is complete for, saying what a later one waits for.

    Raises
    ------
    SystemExit
        If no session since ``not_before`` is complete in the store.
    """
    updater = build_updater(store, STUDY_END, clock=lambda: now)
    repository = MarketDataRepository(store)
    arguments = (
        runner.calendars.get(runner.reference_calendar_id),
        runner.timetable,
        INSTRUMENT_IDS,
        updater.published_until,
        repository.last_date,
        now,
        not_before,
    )
    held_back = session_held_back(*arguments)
    if held_back is not None:
        print(waiting_line(*held_back), flush=True)
    complete = last_complete_session(*arguments)
    if complete is None:
        raise SystemExit(
            f"no session since {not_before} is complete in {store}: update the store, or "
            "wait for the series named above"
        )
    return complete


def waiting_line(session: date, short: Mapping[str, tuple[date | None, date]]) -> str:
    """Say which series hold a decided session back, and what each has to reach.

    A series is waited for until the store holds an observation of it at or
    after the date given, which may be a day or so after the store is in fact
    whole: see :func:`quant_backtester.research.paper.series_short_of`.
    """
    series = "; ".join(
        f"{name} stored to {last if last is not None else 'nothing'}, waits for {needed} or later"
        for name, (last, needed) in short.items()
    )
    return f"session {session} is held back: {series}"


def advance(
    plan: PaperPlan,
    log: PaperLog,
    runner: StrategyRunner,
    strategy: Strategy,
    schedule: DecisionSchedule,
    complete: date,
    now: datetime,
) -> str:
    """Run one plan to its last ready session, extend its log, and say what was done.

    The contract is checked at every call, whether or not a session is logged.

    Parameters
    ----------
    plan : PaperPlan
        The committed plan.
    log : PaperLog
        Its log.
    runner : StrategyRunner
        The runner of the study, on the paper store, with the checkout's state.
    strategy, schedule : Strategy, DecisionSchedule
        The book the plan names, as code.
    complete : date
        The last session of the reference calendar the store is complete for.
    now : datetime
        Timezone-aware wall-clock instant; logged with each new line.

    Returns
    -------
    str
        One line saying what was done.

    Raises
    ------
    PaperPlanBroken
        If the code is not committed or records no commit, the run is under
        another contract, or a logged session comes out differently.
    """
    ready = last_ready_session(runner, plan, complete, now)
    result = run_plan(plan, runner, strategy, schedule, complete if ready is None else ready)
    if ready is None and complete >= plan.start:
        return f"{plan.name:<18} no session is ready yet; contract checked"
    if result is None:
        return f"{plan.name:<18} starts on {plan.start}; complete to {complete}; contract checked"
    commit = runner.source.git_commit
    if commit is None:
        raise PaperPlanBroken(
            f"plan {plan.name} has sessions to log and the checkout records no commit to log "
            "them with"
        )
    appended = log.extend(entries_of(result), git_commit=commit, logged_at=now)
    return (
        f"{plan.name:<18} {len(log.entries())} session(s) logged, {len(appended)} new, "
        f"up to {ready}"
    )


def main(arguments: Sequence[str] | None = None) -> int:
    """Run every plan up to its last ready session, and extend its log."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--store", type=Path, default=STORE)
    parser.add_argument("--contracts", action="store_true")
    parsed = parser.parse_args(arguments)
    store = parsed.store.resolve()
    now = datetime.now(UTC)
    runner = replace(build_runner(store), source=code_state(ROOT, PLANS))
    strategies = books()
    if parsed.contracts:
        day = complete_until(runner, store, now, STUDY_END)
        for name, (strategy, schedule) in strategies.items():
            probe = runner.run(strategy, list(UNIVERSE), day, day, schedule=schedule)
            print(f"{name:<18} {contract_id(probe)}", flush=True)
        return 0
    plans = [PaperPlan.from_toml(path) for path in sorted(PLANS.glob("*.toml"))]
    if not plans:
        raise SystemExit(f"no plan in {PLANS}")
    complete = complete_until(runner, store, now, min(STUDY_END, *(p.start for p in plans)))
    for plan in plans:
        strategy, schedule = strategies[plan.name]
        log = PaperLog(PLANS / f"{plan.name}.jsonl", plan)
        print(advance(plan, log, runner, strategy, schedule, complete, now), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
