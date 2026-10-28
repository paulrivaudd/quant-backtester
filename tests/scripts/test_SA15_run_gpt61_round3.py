"""Offline guards for the bounded SA15 round-three orchestration.

Every runner is mocked. These tests execute neither a backtest nor network I/O.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from quant_backtester.strategies.base import Strategy

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def load_script() -> ModuleType:
    """Load the CLI module with its R1 helper available, without its entry point."""
    spec = importlib.util.spec_from_file_location(
        "SA15_run_gpt61_round3", SCRIPTS / "SA15_run_gpt61_round3.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    sys.path.insert(0, str(SCRIPTS))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(SCRIPTS))
    return module


SCRIPT = load_script()


@dataclass(frozen=True, slots=True)
class MockPolicy(Strategy):
    """Expose the policy's public constructor without importing work in progress."""

    core_id: str = "ETF_NASDAQ"
    defensive_ids: tuple[str, ...] = ("ETF_GOLD", "ETF_SP500_PEA")
    monetary_id: str = "ETF_MONETARY_EUR"
    defensive_lookbacks: tuple[int, ...] = (63, 126, 252)
    defensive_weights: tuple[float, ...] = (1.0, 1.0, 1.0)
    core_floor: float = 0.5
    top_k: int = 1
    strategy_id: str = "SA15_GPT-6.1_R3"

    def decide(self, _ctx):
        """Refuse execution: these tests never exercise the backtest engine."""
        raise AssertionError("a mocked policy must never execute")


@pytest.fixture(autouse=True)
def mocked_policy_import(monkeypatch):
    """Keep orchestration tests independent of the real candidate implementation."""
    module = ModuleType("quant_backtester.strategies.SA15_gpt61_nasdaq")
    module.SA15NasdaqAdaptive = MockPolicy
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(SCRIPT, "source_finance_hashes", lambda **_: {"core.py": "fixed"})


def spec(number=21, **changes: object):
    """Return a minimal declared design, including its written hypothesis."""
    return {
        "number": number,
        "reason": "Test the predeclared relative allocation",
        "schedule": "monthly",
        "parameters": {},
        **changes,
    }


def write(path: Path, value: object) -> Path:
    """Write isolated test evidence as UTF-8 JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


@pytest.mark.parametrize("number", [1, 20, 31, True, False, 21.0, "21", None])
def test_numbers_are_integers_in_the_new_bounded_range(tmp_path, number):
    path = write(tmp_path / "spec.json", spec(number))
    with pytest.raises(ValueError, match="integer from 21 to 30"):
        SCRIPT.read_spec(path)


def test_constructor_normalizes_sequences_and_rejects_unknown_holdings(tmp_path):
    parameters = {
        "defensive_ids": ["ETF_NASDAQ"],
        "defensive_lookbacks": [63],
        "defensive_weights": [1.0],
    }
    path = write(tmp_path / "spec.json", spec(30, parameters=parameters))
    original, policy = SCRIPT.read_spec(path)
    assert original["parameters"] == parameters
    assert policy.defensive_ids == ("ETF_NASDAQ",)
    assert policy.defensive_lookbacks == (63,)
    path = write(path, spec(parameters={"defensive_ids": ["UNKNOWN"]}))
    with pytest.raises(ValueError, match="fixed eight"):
        SCRIPT.read_spec(path)


@pytest.mark.parametrize(
    "changes",
    [
        {"schedule": "hourly"},
        {"reason": " "},
        {"parameters": []},
        {"unexpected": 1},
    ],
)
def test_malformed_design_is_refused(tmp_path, changes):
    path = write(tmp_path / "spec.json", spec(**changes))
    with pytest.raises(ValueError):
        SCRIPT.read_spec(path)


def test_reference_basket_is_buy_and_hold_and_reference_phase_is_lazy(tmp_path, monkeypatch):
    books = SCRIPT.reference_books()
    assert tuple(books) == ("SP500_buy_hold", "Nasdaq_buy_hold", "static_50_50")
    assert all(isinstance(book, SCRIPT.BuyAndHold) for book in books.values())
    assert books["static_50_50"].instruments == ("ETF_SP500_PEA", "ETF_NASDAQ")
    calls = []
    monkeypatch.setattr(SCRIPT, "read_spec", lambda *_: pytest.fail("no policy import"))
    monkeypatch.setattr(SCRIPT, "build_runner", lambda _: object())
    monkeypatch.setattr(
        SCRIPT, "run_references", lambda _, period, output: calls.append((period, output))
    )
    SCRIPT.main(["--references-only", "--output", str(tmp_path)])
    assert calls == [("development", tmp_path), ("validation", tmp_path)]


def test_excess_score_and_positive_in_both_periods_priority():
    scored = SCRIPT.selection_score({"cagr": 0.20}, {"cagr": 0.30}, {"cagr": 0.10}, {"cagr": 0.20})
    assert scored["score"] == pytest.approx(0.10)
    assert scored["both_excess_positive"] is True
    one_bad = SCRIPT.selection_score({"cagr": 0.15}, {"cagr": 0.19}, {"cagr": 0.10}, {"cagr": 0.20})
    assert one_bad["score"] == pytest.approx(0.005)
    assert one_bad["both_excess_positive"] is False
    with pytest.raises(ValueError):
        SCRIPT.selection_score({"cagr": float("nan")}, {"cagr": 0.1}, {"cagr": 0.1}, {"cagr": 0.1})


def test_frozen_selection_and_existing_candidate_cannot_be_overwritten(tmp_path):
    write(tmp_path / "selected.json", {})
    with pytest.raises(ValueError, match="already frozen"):
        SCRIPT.iterate(tmp_path / "absent.json", object(), tmp_path)
    with pytest.raises(FileExistsError, match="already exists"):
        SCRIPT.finalise(object(), tmp_path, tmp_path)
    (tmp_path / "selected.json").unlink()
    config = write(tmp_path / "spec.json", spec())
    write(tmp_path / "trial_21/candidate.json", {"retained": True})
    with pytest.raises(FileExistsError, match="will not be overwritten"):
        SCRIPT.iterate(config, object(), tmp_path)
    assert json.loads((tmp_path / "trial_21/candidate.json").read_text()) == {"retained": True}


def test_candidate_numbers_must_progress_before_any_runner_is_called(tmp_path):
    config = write(tmp_path / "spec.json", spec(22))
    with pytest.raises(ValueError, match="progress"):
        SCRIPT.iterate(config, object(), tmp_path)


@pytest.fixture
def runner(monkeypatch):
    """Provide mutable data provenance and components, forbidding any real run."""
    state = SimpleNamespace(digest="data-a")

    @contextmanager
    def pinned() -> Iterator[SimpleNamespace]:
        yield state

    component = SimpleNamespace(definition=lambda: {"explicit": True})
    monkeypatch.setattr(SCRIPT, "source_finance_hashes", lambda **_: {"core.py": "fixed"})
    return SimpleNamespace(
        reader=SimpleNamespace(pinned=pinned),
        state=state,
        execution=component,
        initial_cash=100000.0,
        base_currency="EUR",
        reference_calendar_id="XPAR",
        timetable=component,
        analytics=component,
        limits=component,
        run=lambda *_, **__: pytest.fail("never run a backtest"),
    )


def populate_cache(folder: Path, signature):
    """Create internally consistent cached evidence without executing a policy."""
    write(folder / "metrics.json", {"cagr": 0.15})
    write(folder / "configuration.json", signature["configuration"])
    write(folder / "strategy.json", signature["strategy"])
    write(
        folder / "identity.json",
        {
            "fingerprint": signature["fingerprint"],
            "data_state": {"digest": signature["data_state"]},
        },
    )
    (folder / "equity.csv").write_text("session_date,net_equity\n2023-01-02,100000\n")
    write(
        folder / "cache.json",
        {
            "signature": signature,
            "artifacts": {
                name: hashlib.sha256((folder / name).read_bytes()).hexdigest()
                for name in SCRIPT.BASE_ARTIFACTS
            },
        },
    )


def test_complete_cache_is_reused_and_missing_cache_is_not_run_in_tests(tmp_path, runner):
    book = SCRIPT.reference_books()["SP500_buy_hold"]
    schedule = SCRIPT.EverySession()
    signature = SCRIPT.expected_signature(runner, book, schedule, *SCRIPT.PERIODS["development"])
    assert SCRIPT.cached_metrics(tmp_path, signature) is None
    populate_cache(tmp_path, signature)
    assert SCRIPT.run_cached(runner, book, schedule, *SCRIPT.PERIODS["development"], tmp_path) == {
        "cagr": 0.15
    }


@pytest.mark.parametrize("change", ["cash", "data", "schedule", "costs", "source", "policy"])
def test_cache_rejects_changed_financial_conditions(tmp_path, runner, monkeypatch, change):
    book = SCRIPT.reference_books()["SP500_buy_hold"]
    schedule = SCRIPT.EverySession()
    signature = SCRIPT.expected_signature(runner, book, schedule, *SCRIPT.PERIODS["validation"])
    populate_cache(tmp_path, signature)
    if change == "cash":
        runner.initial_cash *= 2
    elif change == "data":
        runner.state.digest = "data-b"
    elif change == "schedule":
        schedule = SCRIPT.MonthlyFromStart()
    elif change == "costs":
        runner.execution = SimpleNamespace(definition=lambda: {"explicit": False})
    elif change == "source":
        monkeypatch.setattr(SCRIPT, "source_finance_hashes", lambda **_: {"core.py": "changed"})
    else:
        book = SCRIPT.reference_books()["Nasdaq_buy_hold"]
    expected = SCRIPT.expected_signature(runner, book, schedule, *SCRIPT.PERIODS["validation"])
    with pytest.raises(ValueError, match="conditions differ"):
        SCRIPT.cached_metrics(tmp_path, expected)


def test_cache_refuses_partial_and_tampered_artifacts(tmp_path, runner):
    expected = SCRIPT.expected_signature(
        runner,
        MockPolicy(),
        SCRIPT.MonthlyFromStart(),
        *SCRIPT.PERIODS["development"],
        candidate=True,
    )
    write(tmp_path / "metrics.json", {"cagr": 99})
    with pytest.raises(ValueError, match="incomplete"):
        SCRIPT.cached_metrics(tmp_path, expected)
    populate_cache(tmp_path, expected)
    write(tmp_path / "metrics.json", {"cagr": 99})
    with pytest.raises(ValueError, match="artifact differs"):
        SCRIPT.cached_metrics(tmp_path, expected)


def complete_trial(output: Path, number: int, *, score=0.01, both=True):
    """Save a completed numbered design with no fabricated engine execution."""
    folder = output / f"trial_{number:02d}"
    write(folder / "candidate.json", spec(number))
    write(
        folder / "selection.json",
        {
            "score": score,
            "both_excess_positive": both,
            "excess_development": 0.01,
            "excess_validation": 0.01,
            "metrics": {},
        },
    )
    return folder / "candidate.json"


def freeze(output: Path, number=21):
    """Create an integrity-protected winner solely to construct replay jobs."""
    path = complete_trial(output, number)
    saved, policy = SCRIPT.read_spec(path)
    SCRIPT.write_frozen_selection(
        output,
        {
            "candidate": saved,
            "fingerprint": policy.fingerprint(),
            "parameters": SCRIPT.plain_configuration(policy.definition())["parameters"],
            "driver_sha256": SCRIPT.freeze_driver(output, create=True),
            "candidate_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "selection_sha256": hashlib.sha256(
                (path.parent / "selection.json").read_bytes()
            ).hexdigest(),
        },
    )


def test_freeze_precedes_archive_and_any_final_read_and_uses_no_final_metrics(
    tmp_path, monkeypatch
):
    for number in range(21, 31):
        complete_trial(tmp_path, number, score=0.5 if number == 21 else 0.01, both=number != 21)
    write(tmp_path / "trial_21/final/metrics.json", {"cagr": 100})
    SCRIPT.freeze_driver(tmp_path, create=True)
    monkeypatch.setattr(SCRIPT, "verified_trials", lambda *_: SCRIPT.update_trials(tmp_path))
    events = []

    def archive(output, _store) -> None:
        selected = json.loads((output / "selected.json").read_text())
        assert selected["candidate"]["number"] == 22
        assert selected["total_trials"] == 30
        assert selected["round_trials"] == 10
        assert selected["benchmark"] == "Nasdaq_buy_hold"
        assert (output / "selected.sha256").is_file()
        events.append("archived")

    class FinalReached(Exception):
        """Stop before even a mocked final backtest would execute."""

    def final_read(_runner, period, output) -> None:
        assert period == "final"
        assert events == ["archived"]
        assert (output / "selected.json").exists()
        raise FinalReached

    monkeypatch.setattr(SCRIPT, "archive_sources", archive)
    monkeypatch.setattr(SCRIPT, "run_references", final_read)
    with pytest.raises(FinalReached):
        SCRIPT.finalise(object(), tmp_path, tmp_path / "store")


def test_diagnostics_are_exactly_the_announced_replays_and_never_new_trials(tmp_path):
    for number in range(21, 31):
        complete_trial(tmp_path, number)
    freeze(tmp_path)
    jobs = SCRIPT.build_jobs(tmp_path / "store", tmp_path)
    assert len(jobs) == 28
    costs = [job for job in jobs if job.diagnostic == "costs_x2"]
    assert len(costs) == 20
    assert {job.period for job in costs} == {"development", "validation"}
    assert all(job.multiplier == 2 for job in costs)
    assert costs[0].folder == tmp_path / "trial_21/costs_x2/development"
    starts = [job for job in jobs if job.diagnostic == "starts"]
    assert len(starts) == 4
    assert {job.start for job in starts} == set(SCRIPT.START_DATES)
    assert all(job.end == "2024-12-31" for job in starts)
    full = [job for job in jobs if job.diagnostic == "full"]
    assert {job.book for job in full} == {SCRIPT.STRATEGY_NAME, *SCRIPT.REFERENCES}
    assert all((job.start, job.end) == SCRIPT.PERIODS["full"] for job in full)
    assert len(list(tmp_path.glob("trial_*"))) == 10


def test_diagnostics_require_a_frozen_unchanged_winner(tmp_path):
    complete_trial(tmp_path, 21)
    with pytest.raises(FileNotFoundError):
        SCRIPT.build_jobs(tmp_path / "store", tmp_path)
    freeze(tmp_path)
    write(tmp_path / "trial_21/candidate.json", spec(parameters={"core_floor": 0.25}))
    with pytest.raises(ValueError, match="frozen winner differs"):
        SCRIPT.build_jobs(tmp_path / "store", tmp_path)


@pytest.mark.parametrize("schedule", [SCRIPT.MonthlyFromStart(), SCRIPT.WeeklyFromStart()])
def test_start_schedule_adds_first_session_and_keeps_prefix_invariance(schedule):
    sessions = [
        date(2023, 1, 30),
        date(2023, 1, 31),
        date(2023, 2, 1),
        date(2023, 2, 2),
        date(2023, 2, 3),
        date(2023, 2, 6),
    ]
    full = schedule.decision_sessions(sessions, date(2023, 2, 7))
    assert sessions[0] in full
    for stop in range(1, len(sessions)):
        short = schedule.decision_sessions(sessions[:stop], sessions[stop])
        assert short == full.intersection(sessions[:stop])
    assert schedule.decision_sessions([], None) == frozenset()
    assert schedule.definition()["parameters"]["initial_decision"] is True


def test_monthly_first_session_and_true_end_but_not_truncated_last_session():
    schedule = SCRIPT.MonthlyFromStart()
    sessions = [
        date(2023, 1, 2),
        date(2023, 1, 30),
        date(2023, 1, 31),
        date(2023, 2, 1),
        date(2023, 2, 2),
    ]
    assert schedule.decision_sessions(sessions, date(2023, 2, 3)) == frozenset(
        [date(2023, 1, 2), date(2023, 1, 31)]
    )
    assert isinstance(schedule, SCRIPT.Monthly)
    assert isinstance(SCRIPT.WeeklyFromStart(), SCRIPT.Weekly)


@pytest.mark.parametrize(
    "arguments",
    [
        ["--references-only", "--final"],
        ["--candidate", "a", "--robustness"],
        ["--robustness", "--workers", "1"],
        ["--robustness", "--workers", "4"],
        [],
    ],
)
def test_invalid_cli_is_rejected_before_store_access(arguments):
    with pytest.raises(SystemExit) as exc:
        SCRIPT.parse_arguments(arguments)
    assert exc.value.code == 2


def test_source_freeze_rejects_later_edits_before_any_new_trial(tmp_path, monkeypatch):
    SCRIPT.freeze_driver(tmp_path, create=True)
    original = (tmp_path / "driver_frozen.json").read_bytes()
    monkeypatch.setattr(SCRIPT, "source_finance_hashes", lambda **_: {"core.py": "changed"})
    with pytest.raises(ValueError, match="financial code differs"):
        SCRIPT.freeze_driver(tmp_path)
    assert (tmp_path / "driver_frozen.json").read_bytes() == original


def test_selected_json_and_its_candidate_evidence_are_integrity_protected(tmp_path):
    freeze(tmp_path)
    selected = json.loads((tmp_path / "selected.json").read_text())
    selected["parameters"]["core_floor"] = 0.01
    write(tmp_path / "selected.json", selected)
    with pytest.raises(ValueError, match="selection integrity differs"):
        SCRIPT.frozen_winner(tmp_path)


def test_final_requires_all_ten_completed_candidates_even_if_one_looks_exceptional(tmp_path):
    SCRIPT.freeze_driver(tmp_path, create=True)
    complete_trial(tmp_path, 21, score=100)
    with pytest.raises(ValueError, match="all ten"):
        SCRIPT.finalise(object(), tmp_path, tmp_path)
    assert not (tmp_path / "selected.json").exists()


def verified_selection_evidence(output: Path):
    """Build ten results and reference summaries, with no policy execution."""
    driver = SCRIPT.freeze_driver(output, create=True)
    references = {"development": {"cagr": 0.10}, "validation": {"cagr": 0.20}}
    metrics_by_period = {"development": {"cagr": 0.20}, "validation": {"cagr": 0.30}}
    for number in range(21, 31):
        path = complete_trial(output, number)
        _, policy = SCRIPT.read_spec(path)
        selection = SCRIPT.selection_score(
            metrics_by_period["development"],
            metrics_by_period["validation"],
            references["development"],
            references["validation"],
        )
        write(
            path.parent / "selection.json",
            {
                **selection,
                "fingerprint": policy.fingerprint(),
                "metrics": metrics_by_period,
                "references": references,
                "candidate_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "driver_sha256": driver,
            },
        )
    return references, metrics_by_period


def test_final_ranking_is_recomputed_from_verified_nasdaq_evidence(tmp_path, monkeypatch):
    references, values = verified_selection_evidence(tmp_path)
    monkeypatch.setattr(SCRIPT, "expected_signature", lambda *_, **__: {})
    monkeypatch.setattr(
        SCRIPT,
        "cached_metrics",
        lambda folder, _: (
            references[folder.parent.name]
            if folder.name == "Nasdaq_buy_hold"
            else values[folder.name]
        ),
    )
    ranked = SCRIPT.verified_trials(object(), tmp_path)
    assert list(ranked.trial) == list(range(21, 31))
    assert list(ranked.score) == pytest.approx([0.10] * 10)
    assert ranked.both_excess_positive.all()
    path = tmp_path / "trial_30/selection.json"
    corrupted = json.loads(path.read_text())
    corrupted["score"] = 10
    write(path, corrupted)
    with pytest.raises(ValueError, match="score differs"):
        SCRIPT.verified_trials(object(), tmp_path)


def test_daily_schedule_is_explicit_and_uses_every_session():
    schedule = SCRIPT.SCHEDULES["daily"]()
    sessions = [date(2023, 1, 2), date(2023, 1, 3)]
    assert isinstance(schedule, SCRIPT.EverySession)
    assert schedule.decision_sessions(sessions, date(2023, 1, 4)) == frozenset(sessions)
