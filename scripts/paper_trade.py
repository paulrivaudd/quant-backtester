"""Run the committed paper plans forward, and log what each one decided.

Run it from the repository root after an update of the store::

    uv run python scripts/update_market_data.py
    uv run python scripts/paper_trade.py

Each plan of ``research/paper/`` is run from its start to the last session the
store holds, and every session not yet logged is appended to its log, next to
the plan. Before a plan's start nothing is run. A plan whose strategy no longer
has the committed fingerprint, or whose logged past comes out differently, stops
the script: see ``research/PROTOCOL.md``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from run_baselines import REPOSITORY, STORE, runner

from quant_backtester.backtest.schedule import DecisionSchedule, EverySession
from quant_backtester.data.repository import MarketDataRepository
from quant_backtester.research.paper import PaperLog, PaperPlan, entries_of, run_plan
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
    """Run every plan up to the last stored session, and extend its log."""
    until = MarketDataRepository(STORE).last_date(CLOCK_INSTRUMENT)
    today = datetime.now(UTC).date()
    if until is None:
        raise SystemExit(f"{CLOCK_INSTRUMENT} has no stored session: update the store first")
    until = min(until, today)
    runs = runner()
    for path in sorted(PLANS.glob("*.toml")):
        plan = PaperPlan.from_toml(path)
        strategy, schedule = STRATEGIES[plan.name]
        result = run_plan(plan, runs, strategy, schedule, until)
        if result is None:
            print(f"{plan.name:<26} starts on {plan.start}; the store reaches {until}")
            continue
        log = PaperLog(path.with_suffix(".jsonl"))
        appended = log.extend(entries_of(result))
        print(
            f"{plan.name:<26} {len(log.entries())} session(s) logged, {len(appended)} new, "
            f"net equity {result.equity().iloc[-1]:,.2f}"
        )


if __name__ == "__main__":
    main()
