"""A paper plan is committed to before it starts, and its log keeps what was done."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from quant_backtester.backtest.runner import StrategyRunner
from quant_backtester.backtest.schedule import EverySession
from quant_backtester.data.calendars import TradingCalendar
from quant_backtester.data.repository import MarketDataRepository
from quant_backtester.data.universes import Membership, Universe, UniverseRegistry
from quant_backtester.execution.costs import CostModel
from quant_backtester.execution.model import ExecutionModel
from quant_backtester.provenance import SourceState, SourceStatus
from quant_backtester.research.paper import (
    PaperLog,
    PaperPlan,
    PaperPlanBroken,
    contract_id,
    entries_of,
    last_ready_session,
    run_plan,
)
from quant_backtester.strategies.examples import BuyAndHold

STRATEGY = BuyAndHold(instruments=("ETF_EU",))
AT = datetime(2026, 9, 26, 22, 0, tzinfo=UTC)
COMMIT = "0123456789abcdef0123456789abcdef01234567"
PARIS = ZoneInfo("Europe/Paris")


@pytest.fixture
def plan_runner(research_runner: StrategyRunner) -> StrategyRunner:
    """Return the research runner, with the plan's universe declared."""
    registry = UniverseRegistry(
        [Universe("ROTATION_TEST", "a one-fund test universe", (Membership("ETF_EU"),))]
    )
    return replace(research_runner, universes=registry)


@pytest.fixture
def plan(plan_runner: StrategyRunner) -> PaperPlan:
    """Return a plan committed to the plan runner's own contract."""
    probe = plan_runner.run(STRATEGY, "ROTATION_TEST", "2026-09-14", "2026-09-14")
    return PaperPlan(
        name="hold_eu",
        start=date(2026, 9, 9),
        universe="ROTATION_TEST",
        contract_id=contract_id(probe),
        note="buy and hold, measured forward",
    )


def log_of(plan: PaperPlan, tmp_path: Path) -> PaperLog:
    return PaperLog(tmp_path / f"{plan.name}.jsonl", plan)


def test_a_plan_runs_from_its_start_and_logs_every_session(
    plan: PaperPlan, plan_runner: StrategyRunner, tmp_path: Path
) -> None:
    result = run_plan(plan, plan_runner, STRATEGY, EverySession(), date(2026, 9, 14))
    assert result is not None
    log = log_of(plan, tmp_path)

    appended = log.extend(entries_of(result), git_commit=COMMIT, logged_at=AT)

    assert [entry.session_date for entry in appended] == [
        "2026-09-09",
        "2026-09-10",
        "2026-09-11",
        "2026-09-14",
    ]
    assert log.entries() == appended
    bought = appended[1]
    assert bought.fills[0]["instrument_id"] == "ETF_EU"
    assert bought.holdings["ETF_EU"] == pytest.approx(bought.fills[0]["quantity"])


def test_a_plan_checks_its_contract_before_it_starts(
    plan: PaperPlan, plan_runner: StrategyRunner
) -> None:
    """Misconfigured before its start, it fails before its start."""
    early = replace(plan, start=date(2026, 10, 1))
    assert run_plan(early, plan_runner, STRATEGY, EverySession(), date(2026, 9, 14)) is None

    charged = replace(plan_runner, execution=ExecutionModel(CostModel(commission_rate=0.01)))
    with pytest.raises(PaperPlanBroken, match="new plan"):
        run_plan(early, charged, STRATEGY, EverySession(), date(2026, 9, 14))


@pytest.mark.parametrize(
    "change",
    ["costs", "cash", "schedule", "strategy"],
)
def test_the_same_fingerprint_is_not_the_same_experiment(
    plan: PaperPlan, plan_runner: StrategyRunner, change: str
) -> None:
    """Audit N03: costs going from 0 to 1% under one fingerprint used to be accepted."""
    runner, strategy = plan_runner, STRATEGY
    if change == "costs":
        runner = replace(runner, execution=ExecutionModel(CostModel(commission_rate=0.01)))
    elif change == "cash":
        runner = replace(runner, initial_cash=20_000.0)
    elif change == "schedule":
        from quant_backtester.backtest.schedule import Weekly

        with pytest.raises(PaperPlanBroken, match="new plan"):
            run_plan(plan, runner, strategy, Weekly(), date(2026, 9, 14))
        return
    else:
        strategy = BuyAndHold(instruments=("ETF_EU",), strategy_id="another")

    with pytest.raises(PaperPlanBroken, match="new plan"):
        run_plan(plan, runner, strategy, EverySession(), date(2026, 9, 14))


@pytest.mark.parametrize(
    "state",
    [SourceState(SourceStatus.DIRTY, COMMIT), SourceState.unrecorded()],
    ids=["dirty", "unrecorded"],
)
def test_only_committed_code_advances_a_plan(
    plan: PaperPlan, plan_runner: StrategyRunner, state: SourceState
) -> None:
    with pytest.raises(PaperPlanBroken, match="committed code"):
        run_plan(
            plan, replace(plan_runner, source=state), STRATEGY, EverySession(), date(2026, 9, 14)
        )


def test_a_rewritten_position_is_caught_behind_an_unchanged_equity(
    plan: PaperPlan,
    plan_runner: StrategyRunner,
    repository: MarketDataRepository,
    make_bars: Callable[..., pd.DataFrame],
    xpar: TradingCalendar,
    tmp_path: Path,
) -> None:
    """Audit N02: 100 shares at 100 became 200 at 50, and every logged equity stayed 10 000."""
    days = [date(2026, 9, 9), date(2026, 9, 10), date(2026, 9, 11), date(2026, 9, 14)]
    repository.save_checked_bars("ETF_EU", make_bars("ETF_EU", xpar, dict.fromkeys(days, 100.0)))
    log = log_of(plan, tmp_path)
    first = run_plan(plan, plan_runner, STRATEGY, EverySession(), days[2])
    assert first is not None
    log.extend(entries_of(first), git_commit=COMMIT, logged_at=AT)
    assert [entry.net_equity for entry in log.entries()] == pytest.approx([10_000.0] * 3)

    revised = dict.fromkeys(days[:3], 50.0) | {days[3]: 100.0}
    repository.save_checked_bars("ETF_EU", make_bars("ETF_EU", xpar, revised))
    later = run_plan(plan, plan_runner, STRATEGY, EverySession(), days[3])
    assert later is not None
    assert [entry.net_equity for entry in entries_of(later)[:3]] == pytest.approx([10_000.0] * 3)

    with pytest.raises(PaperPlanBroken, match="has changed"):
        log.extend(entries_of(later), git_commit=COMMIT, logged_at=AT)
    assert len(log.entries()) == 3


def test_a_log_grows_and_a_second_run_changes_nothing(
    plan: PaperPlan, plan_runner: StrategyRunner, tmp_path: Path
) -> None:
    log = log_of(plan, tmp_path)
    first = run_plan(plan, plan_runner, STRATEGY, EverySession(), date(2026, 9, 10))
    later = run_plan(plan, plan_runner, STRATEGY, EverySession(), date(2026, 9, 14))
    assert first is not None and later is not None

    log.extend(entries_of(first), git_commit=COMMIT, logged_at=AT)
    appended = log.extend(entries_of(later), git_commit=COMMIT, logged_at=AT)
    again = log.extend(entries_of(later), git_commit=COMMIT, logged_at=AT)

    assert [entry.session_date for entry in appended] == ["2026-09-11", "2026-09-14"]
    assert again == []
    assert len(log.entries()) == 4


def test_two_writers_at_once_log_each_session_once(
    plan: PaperPlan, plan_runner: StrategyRunner, tmp_path: Path
) -> None:
    """Audit N07: both read before either wrote, and a session was logged twice."""
    result = run_plan(plan, plan_runner, STRATEGY, EverySession(), date(2026, 9, 14))
    assert result is not None
    entries = entries_of(result)
    start = threading.Barrier(4)

    def write() -> None:
        start.wait()
        PaperLog(tmp_path / "hold_eu.jsonl", plan).extend(entries, git_commit=COMMIT, logged_at=AT)

    writers = [threading.Thread(target=write) for _ in range(4)]
    for writer in writers:
        writer.start()
    for writer in writers:
        writer.join()

    dates = [entry.session_date for entry in log_of(plan, tmp_path).entries()]
    assert dates == sorted(set(dates))
    assert len(dates) == 4


def test_a_log_started_under_another_contract_is_refused(
    plan: PaperPlan, plan_runner: StrategyRunner, tmp_path: Path
) -> None:
    result = run_plan(plan, plan_runner, STRATEGY, EverySession(), date(2026, 9, 14))
    assert result is not None
    log_of(plan, tmp_path).extend(entries_of(result), git_commit=COMMIT, logged_at=AT)

    other = replace(plan, contract_id="f" * 64)

    with pytest.raises(PaperPlanBroken, match="was started under"):
        log_of(other, tmp_path).entries()


def test_a_session_is_ready_once_its_decision_instant_has_passed(
    plan: PaperPlan, plan_runner: StrategyRunner
) -> None:
    """C06: decided at 23:00 Paris, so not at 22:59, and yes at 23:01."""
    monday = date(2026, 9, 14)
    before = datetime(2026, 9, 14, 22, 59, tzinfo=PARIS)
    after = datetime(2026, 9, 14, 23, 1, tzinfo=PARIS)

    assert last_ready_session(plan_runner, plan, monday, before) == date(2026, 9, 11)
    assert last_ready_session(plan_runner, plan, monday, after) == monday


def test_a_session_without_a_close_of_its_own_is_not_ready(
    plan: PaperPlan,
    plan_runner: StrategyRunner,
    repository: MarketDataRepository,
    make_bars: Callable[..., pd.DataFrame],
    xpar: TradingCalendar,
) -> None:
    """The store has Friday and nothing of Monday yet: Monday is not logged."""
    days = [date(2026, 9, 9), date(2026, 9, 10), date(2026, 9, 11)]
    repository.save_checked_bars("ETF_EU", make_bars("ETF_EU", xpar, dict.fromkeys(days, 100.0)))
    late = datetime(2026, 9, 15, 12, 0, tzinfo=PARIS)

    assert last_ready_session(plan_runner, plan, date(2026, 9, 14), late) == date(2026, 9, 11)


def test_a_plan_says_what_it_tests(plan: PaperPlan) -> None:
    with pytest.raises(ValueError, match="does not say"):
        replace(plan, note=" ")
