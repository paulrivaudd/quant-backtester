"""Tests of the paper run's scripts: the plans, the books, the code state, the store's seed."""

from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.research.conftest import research_runner  # noqa: F401

from quant_backtester.backtest.runner import StrategyRunner
from quant_backtester.backtest.schedule import EverySession, Weekly
from quant_backtester.provenance import SourceState, SourceStatus
from quant_backtester.research.paper import PaperLog, PaperPlan, PaperPlanBroken, contract_id
from quant_backtester.research.references import BuyAndHold
from scripts import SA16_run_study as study
from scripts import paper_trade, paper_update_store

NOW = datetime(2026, 9, 15, 8, 0, tzinfo=UTC)
STRATEGY = BuyAndHold(instruments=("ETF_EU",))


def test_every_committed_plan_names_a_book_of_the_script_and_the_studys_universe() -> None:
    plans = [PaperPlan.from_toml(path) for path in sorted(paper_trade.PLANS.glob("*.toml"))]
    books = paper_trade.books()
    assert {plan.name for plan in plans} == set(books)
    assert {plan.universe for plan in plans} == {tuple(study.UNIVERSE)}
    # One start for the three: they are compared on the same sessions.
    assert len({plan.start for plan in plans}) == 1
    assert len({plan.contract_id for plan in plans}) == len(plans)


def test_the_books_are_the_studys_retained_configuration_and_its_two_references() -> None:
    books = paper_trade.books()
    selected = json.loads(paper_trade.SELECTED.read_text(encoding="utf-8"))
    candidate, schedule = books["SA16_IT2"]
    assert candidate.fingerprint() == selected["fingerprint"]
    assert isinstance(schedule, Weekly)
    held, daily = books["NASDAQ_BUY_HOLD"]
    assert held.fingerprint() == BuyAndHold(("ETF_NASDAQ",)).fingerprint()
    assert isinstance(daily, EverySession)
    reference = study.sa15_reference()
    assert books["SA15_R4_TRIAL71"][0].fingerprint() == reference.strategy.fingerprint()
    assert books["SA15_R4_TRIAL71"][1] == reference.schedule


def test_a_retained_configuration_that_was_edited_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    selected = json.loads(paper_trade.SELECTED.read_text(encoding="utf-8"))
    selected["parameters"]["growth_risk_budget"] = 0.8
    edited = tmp_path / "selected.json"
    edited.write_text(json.dumps(selected))
    monkeypatch.setattr(paper_trade, "SELECTED", edited)
    with pytest.raises(ValueError, match="does not match its fingerprint"):
        paper_trade.books()


def git(root: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
         "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", *arguments],
        check=True,
        capture_output=True,
    )  # fmt: skip


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    """Return a committed checkout holding a plan's log and a module."""
    root = tmp_path / "checkout"
    (root / "research" / "paper").mkdir(parents=True)
    (root / "research" / "paper" / "PLAN.jsonl").write_text("{}\n")
    (root / "code.py").write_text("x = 1\n")
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "start")
    return root


def test_only_a_plans_log_may_differ_from_the_commit(checkout: Path) -> None:
    logs = checkout / "research" / "paper"
    assert paper_trade.code_state(checkout, logs).status is SourceStatus.CLEAN

    with (logs / "PLAN.jsonl").open("a") as stream:
        stream.write("{}\n")
    (logs / "OTHER.jsonl").write_text("{}\n")
    state = paper_trade.code_state(checkout, logs)
    assert state.status is SourceStatus.CLEAN and state.git_commit is not None

    others = ("code.py", "research/paper/PLAN.toml", "research/paper/deeper/x.jsonl", "x.jsonl")
    for name in others:
        path = checkout / name
        before = path.read_text() if path.exists() else None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("changed\n")
        assert paper_trade.code_state(checkout, logs).status is SourceStatus.DIRTY, name
        if before is None:
            path.unlink()
        else:
            path.write_text(before)
    assert paper_trade.code_state(checkout, logs).status is SourceStatus.CLEAN


def test_a_committed_log_may_only_grow(checkout: Path) -> None:
    """Deleted, shortened or edited, a log is a change: its sessions are not written again."""
    logs = checkout / "research" / "paper"
    log = logs / "PLAN.jsonl"
    committed = log.read_text()

    log.unlink()
    assert paper_trade.code_state(checkout, logs).status is SourceStatus.DIRTY
    log.write_text("")
    assert paper_trade.code_state(checkout, logs).status is SourceStatus.DIRTY
    log.write_text("{ }\n")
    assert paper_trade.code_state(checkout, logs).status is SourceStatus.DIRTY
    log.write_text('{"other": 1}\n' + committed)
    assert paper_trade.code_state(checkout, logs).status is SourceStatus.DIRTY

    log.write_text(committed + '{"appended": 1}\n')
    assert paper_trade.code_state(checkout, logs).status is SourceStatus.CLEAN
    # A folder named like a log is not one.
    (logs / "FOLDER.jsonl").mkdir()
    (logs / "FOLDER.jsonl" / "x.jsonl").write_text("{}\n")
    assert paper_trade.code_state(checkout, logs).status is SourceStatus.DIRTY


@pytest.fixture
def plan(research_runner: StrategyRunner) -> PaperPlan:  # noqa: F811
    probe = research_runner.run(STRATEGY, ["ETF_EU"], "2026-09-14", "2026-09-14")
    return PaperPlan("hold_eu", date(2026, 9, 9), ("ETF_EU",), contract_id(probe), "held forward")


def test_a_plan_advances_to_what_is_complete_and_a_second_run_adds_nothing(
    plan: PaperPlan,
    research_runner: StrategyRunner,  # noqa: F811
    tmp_path: Path,
) -> None:
    log = PaperLog(tmp_path / "hold_eu.jsonl", plan)

    def advance(complete: date) -> str:
        return paper_trade.advance(
            plan, log, research_runner, STRATEGY, EverySession(), complete, NOW
        )

    assert "3 session(s) logged, 3 new, up to 2026-09-11" in advance(date(2026, 9, 11))
    assert "4 session(s) logged, 1 new, up to 2026-09-14" in advance(date(2026, 9, 14))
    assert "4 session(s) logged, 0 new, up to 2026-09-14" in advance(date(2026, 9, 14))
    logged_with = json.loads(log.path.read_text().splitlines()[1])["logged_with"]
    assert logged_with == {
        "git_commit": research_runner.source.git_commit,
        "logged_at": NOW.isoformat(),
    }


def test_before_its_start_a_plan_only_has_its_contract_checked(
    plan: PaperPlan,
    research_runner: StrategyRunner,  # noqa: F811
    tmp_path: Path,
) -> None:
    later = replace(plan, start=date(2026, 9, 21))
    log = PaperLog(tmp_path / "hold_eu.jsonl", later)
    said = paper_trade.advance(
        later, log, research_runner, STRATEGY, EverySession(), date(2026, 9, 14), NOW
    )
    assert "starts on 2026-09-21" in said and "contract checked" in said
    assert not log.path.exists()
    with pytest.raises(PaperPlanBroken, match="new plan"):
        paper_trade.advance(later, log, research_runner, STRATEGY, Weekly(), date(2026, 9, 14), NOW)


def store_like(root: Path) -> Path:
    for name in ("metadata", "raw", "clean", "validation", "reports"):
        (root / name).mkdir(parents=True)
        (root / name / "file.txt").write_text(name)
    (root / "metadata_sha256.json").write_text("{}\n")
    (root / ".lock").write_text("")
    return root


def test_the_paper_store_is_seeded_once_from_the_studys(tmp_path: Path) -> None:
    seed, store = store_like(tmp_path / "seed"), tmp_path / "paper"
    assert paper_update_store.seed_store(store, seed) is True
    assert sorted(path.name for path in store.iterdir()) == sorted(paper_update_store.SEEDED)
    assert (store / "clean" / "file.txt").read_text() == "clean"
    # The seed is read, never written, and a store that exists is left alone.
    (store / "clean" / "file.txt").write_text("extended")
    assert paper_update_store.seed_store(store, seed) is False
    assert (store / "clean" / "file.txt").read_text() == "extended"
    assert (seed / "clean" / "file.txt").read_text() == "clean"


def test_a_seed_that_is_not_a_built_store_is_refused(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="SA16_download_data"):
        paper_update_store.seed_store(tmp_path / "paper", tmp_path / "missing")
    assert not (tmp_path / "paper").exists()


def test_every_instrument_is_extended_and_a_failure_is_recorded_not_swallowed() -> None:
    class Updater:
        def update(self, instrument_id: str) -> SimpleNamespace:
            if instrument_id == "DOWN":
                raise RuntimeError("provider is down")
            return SimpleNamespace(
                valid=instrument_id != "REFUSED", errors=[], warnings=[], issues=[]
            )

    outcomes = paper_update_store.update_store(Updater(), ("FINE", "DOWN", "REFUSED"))  # type: ignore[arg-type]

    assert [outcome["instrument_id"] for outcome in outcomes] == ["FINE", "DOWN", "REFUSED"]
    assert outcomes[0]["valid"] is True and "provider is down" in outcomes[1]["exception"]
    assert paper_update_store.failed(outcomes) is True
    assert paper_update_store.failed(outcomes[:1]) is False
    assert paper_update_store.failed(outcomes[2:]) is True


def test_a_clean_checkout_always_names_the_commit_a_session_is_logged_with() -> None:
    """A plan is advanced by a CLEAN source only, and a CLEAN source cannot lack its commit."""
    with pytest.raises(ValueError, match="names its full commit"):
        SourceState(SourceStatus.CLEAN, None)


def test_the_contract_is_checked_on_a_day_no_session_is_ready(
    plan: PaperPlan,
    research_runner: StrategyRunner,  # noqa: F811
    tmp_path: Path,
) -> None:
    """The store is complete to Monday but it is not yet 23:00 on the plan's first session."""
    first_evening = datetime(2026, 9, 9, 18, 0, tzinfo=UTC)
    log = PaperLog(tmp_path / "hold_eu.jsonl", plan)
    said = paper_trade.advance(
        plan, log, research_runner, STRATEGY, EverySession(), date(2026, 9, 14), first_evening
    )
    assert "no session is ready yet; contract checked" in said
    assert not log.path.exists()
    with pytest.raises(PaperPlanBroken, match="new plan"):
        paper_trade.advance(
            plan, log, research_runner, STRATEGY, Weekly(), date(2026, 9, 14), first_evening
        )


def test_the_series_a_session_waits_for_are_said_with_what_they_have_to_reach() -> None:
    line = paper_trade.waiting_line(
        date(2026, 11, 16),
        {"US10Y": (date(2026, 11, 13), date(2026, 11, 15)), "VIX": (None, date(2026, 11, 16))},
    )
    assert line == (
        "session 2026-11-16 is held back: US10Y stored to 2026-11-13, waits for 2026-11-15 "
        "or later; VIX stored to nothing, waits for 2026-11-16 or later"
    )
