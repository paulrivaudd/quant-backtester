"""A paper plan is committed to before it starts, and its log is never rewritten."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from quant_backtester.backtest.runner import StrategyRunner
from quant_backtester.backtest.schedule import EverySession
from quant_backtester.research.paper import (
    PaperLog,
    PaperPlan,
    PaperPlanBroken,
    entries_of,
    run_plan,
)
from quant_backtester.strategies.examples import BuyAndHold

STRATEGY = BuyAndHold(instruments=("ETF_EU",))


def plan(start: date = date(2026, 9, 9)) -> PaperPlan:
    return PaperPlan(
        name="hold_eu",
        start=start,
        universe="ROTATION_TEST",
        strategy_fingerprint=STRATEGY.fingerprint(),
        note="buy and hold, measured forward",
    )


@pytest.fixture
def plan_runner(research_runner: StrategyRunner) -> StrategyRunner:
    """Return the research runner, with the plan's universe declared."""
    from quant_backtester.data.universes import Membership, Universe, UniverseRegistry

    registry = UniverseRegistry(
        [Universe("ROTATION_TEST", "a one-fund test universe", (Membership("ETF_EU"),))]
    )
    return replace(research_runner, universes=registry)


def test_a_plan_runs_from_its_start_and_logs_every_session(
    plan_runner: StrategyRunner, tmp_path: Path
) -> None:
    result = run_plan(plan(), plan_runner, STRATEGY, EverySession(), date(2026, 9, 14))
    assert result is not None
    log = PaperLog(tmp_path / "hold_eu.jsonl")

    appended = log.extend(entries_of(result))

    assert [entry.session_date for entry in appended] == [
        "2026-09-09",
        "2026-09-10",
        "2026-09-11",
        "2026-09-14",
    ]
    assert log.entries() == appended


def test_a_plan_does_nothing_before_it_starts(plan_runner: StrategyRunner) -> None:
    assert (
        run_plan(plan(date(2026, 10, 1)), plan_runner, STRATEGY, EverySession(), date(2026, 9, 14))
        is None
    )


def test_a_changed_rule_is_not_the_plan(plan_runner: StrategyRunner) -> None:
    """Tuned after the start, it is a new plan with a new start."""
    other = BuyAndHold(instruments=("ETF_OTHER",))

    with pytest.raises(PaperPlanBroken, match="new plan"):
        run_plan(plan(), plan_runner, other, EverySession(), date(2026, 9, 14))


def test_a_log_grows_and_keeps_what_it_logged(plan_runner: StrategyRunner, tmp_path: Path) -> None:
    log = PaperLog(tmp_path / "hold_eu.jsonl")
    first = run_plan(plan(), plan_runner, STRATEGY, EverySession(), date(2026, 9, 10))
    later = run_plan(plan(), plan_runner, STRATEGY, EverySession(), date(2026, 9, 14))
    assert first is not None and later is not None

    log.extend(entries_of(first))
    appended = log.extend(entries_of(later))

    assert [entry.session_date for entry in appended] == ["2026-09-11", "2026-09-14"]
    assert len(log.entries()) == 4


def test_a_past_that_comes_out_differently_stops_the_plan(
    plan_runner: StrategyRunner, tmp_path: Path
) -> None:
    """A revised price the plan already acted on: the log keeps what was decided."""
    log = PaperLog(tmp_path / "hold_eu.jsonl")
    result = run_plan(plan(), plan_runner, STRATEGY, EverySession(), date(2026, 9, 14))
    assert result is not None
    entries = entries_of(result)
    log.extend(entries)
    revised = [replace(entries[0], net_equity=entries[0].net_equity + 1.0), *entries[1:]]

    with pytest.raises(PaperPlanBroken, match="has changed"):
        log.extend(revised)
    assert log.entries() == entries


def test_a_plan_says_what_it_tests(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="does not say"):
        replace(plan(), note=" ")
