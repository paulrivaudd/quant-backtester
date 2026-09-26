"""Run the committed paper plans forward, and log what each one decided.

Run it from the repository root after an update of the store::

    uv run python scripts/update_market_data.py
    uv run python scripts/paper_trade.py

Each plan of ``research/paper/`` is run from its start to its last ready
session - one whose decision instant (23:00 Paris) has passed and whose
universe has a close of that session - and every session not yet logged is
appended to its log, next to the plan. Before a plan's start only its contract
is checked. Uncommitted code, a run under another contract, or a logged past
that comes out differently stops the script: see ``research/PROTOCOL.md``.
Running it twice changes nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime

from run_baselines import REPOSITORY, STORE, runner

from quant_backtester.backtest.schedule import DecisionSchedule, EverySession
from quant_backtester.data.repository import MarketDataRepository
from quant_backtester.research.paper import (
    PaperLog,
    PaperPlan,
    entries_of,
    last_ready_session,
    run_plan,
)
from quant_backtester.strategies.base import Strategy
from quant_backtester.strategies.examples import BuyAndHold, MomentumRotation

PLANS = REPOSITORY / "research" / "paper"
"""Where the committed plans and their logs live."""

STRATEGIES: dict[str, tuple[Strategy, DecisionSchedule]] = {
    "ROTATION_2_MOMENTUM_60": (MomentumRotation(lookback_sessions=60, top_n=1), EverySession()),
    "ROTATION_2_BUY_AND_HOLD": (BuyAndHold(instruments=("ETF_WORLD",)), EverySession()),
}
"""The strategy each plan names, as code. The plan's fingerprint checks it."""

CLOCK_INSTRUMENT = "ETF_WORLD"
"""The series whose last stored session is how far a plan can be run."""


def main() -> None:
    """Run every plan up to its last ready session, and extend its log."""
    now = datetime.now(UTC)
    stored_until = MarketDataRepository(STORE).last_date(CLOCK_INSTRUMENT)
    if stored_until is None:
        raise SystemExit(f"{CLOCK_INSTRUMENT} has no stored session: update the store first")
    runs = runner()
    commit = runs.source.git_commit
    for path in sorted(PLANS.glob("*.toml")):
        plan = PaperPlan.from_toml(path)
        strategy, schedule = STRATEGIES[plan.name]
        ready = last_ready_session(runs, plan, stored_until, now)
        if ready is None:
            print(f"{plan.name:<26} no session is ready yet")
            continue
        result = run_plan(plan, runs, strategy, schedule, ready)
        if result is None or commit is None:
            print(f"{plan.name:<26} starts on {plan.start}; ready up to {ready}; contract checked")
            continue
        log = PaperLog(path.with_suffix(".jsonl"), plan)
        appended = log.extend(entries_of(result), git_commit=commit, logged_at=now)
        print(
            f"{plan.name:<26} {len(log.entries())} session(s) logged, {len(appended)} new, "
            f"up to {ready}, net equity {result.equity().iloc[-1]:,.2f}"
        )


if __name__ == "__main__":
    main()
