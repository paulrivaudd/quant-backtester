"""Offline construction and provenance guards for diagnostic replays."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from quant_backtester.backtest.schedule import EverySession, Weekly
from quant_backtester.strategies.SA15_gpt61 import SA15GPT61

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def load_script() -> ModuleType:
    """Load the CLI module with its adjacent study module importable."""
    path = SCRIPTS / "SA15_robustness_gpt61.py"
    spec = importlib.util.spec_from_file_location("SA15_robustness_gpt61", path)
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


def write_json(path: Path, value: object) -> None:
    """Create a minimal diagnostic artifact in an isolated test directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def complete_trial(output: Path, number: int, *, complete: bool = True) -> Path:
    """Record a bounded candidate; completion never requires a backtest."""
    path = output / f"trial_{number:02d}" / "candidate.json"
    write_json(
        path,
        {
            "number": number,
            "reason": "Diagnose a previously completed design",
            "parameters": {"core_fraction": 0.5},
            "schedule": "weekly",
        },
    )
    if complete:
        write_json(path.parent / "selection.json", {"score": 0.1, "metrics": {}})
    return path


def freeze_winner(output: Path, number: int = 1) -> Path:
    """Record the winner and its exact parameter fingerprint."""
    candidate = complete_trial(output, number)
    spec, allocation = SCRIPT.read_candidate(candidate)
    write_json(
        output / "selected.json",
        {
            "candidate": spec,
            "candidate_fingerprint": allocation.fingerprint(),
        },
    )
    return candidate


@pytest.mark.parametrize(
    "arguments",
    [
        ["--workers", "0"],
        ["--workers", "4"],
        ["--workers", "1.5"],
        ["--costs-only", "--starts-only"],
        ["--starts-only", "--full-only"],
    ],
)
def test_invalid_cli_arguments_fail_before_accessing_any_store(arguments) -> None:
    with pytest.raises(SystemExit) as error:
        SCRIPT.parse_arguments(arguments)
    assert error.value.code == 2


def test_default_mode_and_explicit_paths() -> None:
    options = SCRIPT.parse_arguments(["--store", "market", "--output", "results"])
    assert options.mode == "both"
    assert options.workers == 2
    assert options.store == Path("market")
    assert options.output == Path("results")


def test_cost_jobs_include_only_completed_trials_and_never_final_period(tmp_path) -> None:
    complete_trial(tmp_path, 1)
    complete_trial(tmp_path, 2, complete=False)
    complete_trial(tmp_path, 10)
    jobs = SCRIPT.build_jobs(tmp_path / "store", tmp_path, "costs")
    assert len(jobs) == 4
    assert {job.candidate.parent.name for job in jobs} == {"trial_01", "trial_10"}
    assert {job.period for job in jobs} == {"development", "validation"}
    assert all(job.multiplier == 2.0 and job.diagnostic == "costs_x2" for job in jobs)
    assert jobs[0].folder == tmp_path / "trial_01/costs_x2/development"
    assert (jobs[0].start, jobs[0].end) == SCRIPT.PERIODS["development"]


def test_starts_require_a_frozen_selection_and_use_only_its_archived_design(tmp_path) -> None:
    complete_trial(tmp_path, 1)
    with pytest.raises(FileNotFoundError):
        SCRIPT.build_jobs(tmp_path / "store", tmp_path, "starts")
    selected = freeze_winner(tmp_path, 8)
    jobs = SCRIPT.build_jobs(tmp_path / "store", tmp_path, "starts")
    assert len(jobs) == 4
    assert {job.candidate for job in jobs} == {selected}
    assert {job.start for job in jobs} == set(SCRIPT.START_DATES)
    assert all(job.end == "2024-12-31" and job.multiplier == 1.0 for job in jobs)
    assert jobs[0].folder == tmp_path / "robustness/starts/2020-01-02"


def test_full_replay_contains_winner_and_four_references_without_changing_periods(tmp_path) -> None:
    freeze_winner(tmp_path)
    previous = dict(SCRIPT.PERIODS)
    jobs = SCRIPT.build_jobs(tmp_path / "store", tmp_path, "full")
    assert len(jobs) == 5
    assert {job.book for job in jobs} == set(SCRIPT.FULL_BOOKS)
    assert all((job.start, job.end) == SCRIPT.FULL_PERIOD for job in jobs)
    assert previous == SCRIPT.PERIODS


def test_combined_mode_validates_frozen_selection_before_returning_cost_jobs(tmp_path) -> None:
    complete_trial(tmp_path, 1)
    with pytest.raises(FileNotFoundError):
        SCRIPT.build_jobs(tmp_path / "store", tmp_path, "both")
    freeze_winner(tmp_path)
    assert len(SCRIPT.build_jobs(tmp_path / "store", tmp_path, "both")) == 6


def test_empty_cost_diagnostics_do_not_silently_succeed(tmp_path) -> None:
    with pytest.raises(ValueError, match="no completed candidate"):
        SCRIPT.build_jobs(tmp_path / "store", tmp_path, "costs")
    with pytest.raises(ValueError, match="unknown diagnostic"):
        SCRIPT.build_jobs(tmp_path / "store", tmp_path, "unknown")


def test_mutated_winner_or_trial_number_is_refused(tmp_path) -> None:
    candidate = freeze_winner(tmp_path)
    spec = json.loads(candidate.read_text())
    spec["parameters"]["core_fraction"] = 0.25
    write_json(candidate, spec)
    with pytest.raises(ValueError, match="frozen winner differs"):
        SCRIPT.build_jobs(tmp_path / "store", tmp_path, "starts")
    spec["number"] = 2
    write_json(candidate, spec)
    with pytest.raises(ValueError, match="folder and archived candidate number"):
        SCRIPT.build_jobs(tmp_path / "store", tmp_path, "costs")


def test_jobs_reconstruct_candidate_and_reference_schedules_without_running(tmp_path) -> None:
    freeze_winner(tmp_path)
    jobs = SCRIPT.build_jobs(tmp_path / "store", tmp_path, "full")
    spec, allocation = SCRIPT.read_candidate(jobs[0].candidate)
    candidate, schedule = SCRIPT.book_and_schedule(jobs[0], spec, allocation)
    assert candidate is allocation
    assert isinstance(schedule, Weekly)
    reference, schedule = SCRIPT.book_and_schedule(jobs[1], spec, allocation)
    assert reference.instruments == ("ETF_WORLD",)
    assert isinstance(schedule, EverySession)
    _, schedule = SCRIPT.book_and_schedule(jobs[-1], spec, allocation)
    assert isinstance(schedule, Weekly)


def fake_signature() -> dict:
    """Return enough frozen evidence to exercise cache identity checks."""
    allocation = SA15GPT61()
    return {
        "diagnostic": "costs_x2",
        "data_state": "data-a",
        "source_hashes": {"code.py": "hash"},
        "candidate_fingerprint": allocation.fingerprint(),
        "fingerprint": allocation.fingerprint(),
        "strategy": SCRIPT.plain_configuration(allocation.definition()),
        "configuration": {
            "requested_start": "2023-01-02",
            "requested_end": "2024-12-31",
            "initial_cash": 100000.0,
            "data_state": "data-a",
            "execution": {"costs": {"commission_rate": 0.001}},
            "schedule": Weekly().definition(),
        },
    }


def diagnostic_artifacts(folder: Path, signature: dict) -> None:
    """Write consistent existing results without executing a strategy."""
    write_json(folder / "diagnostic.json", signature)
    write_json(
        folder / "identity.json",
        {
            "fingerprint": signature["fingerprint"],
            "data_state": {"digest": signature["data_state"]},
        },
    )
    write_json(folder / "strategy.json", signature["strategy"])
    write_json(folder / "configuration.json", signature["configuration"])
    write_json(folder / "metrics.json", {"cagr": 0.15})
    (folder / "equity.csv").write_text("session_date,net_equity\n2023-01-02,100000\n")


def test_matching_complete_cache_is_reused_and_empty_folder_means_run_needed(tmp_path) -> None:
    signature = fake_signature()
    assert SCRIPT.cached_metrics(tmp_path, signature) is None
    diagnostic_artifacts(tmp_path, signature)
    assert SCRIPT.cached_metrics(tmp_path, signature) == {"cagr": 0.15}


@pytest.mark.parametrize(
    "artifact,field",
    [
        ("identity.json", "fingerprint"),
        ("identity.json", "data_state"),
        ("configuration.json", "execution"),
        ("configuration.json", "schedule"),
        ("configuration.json", "initial_cash"),
        ("strategy.json", "parameters"),
        ("diagnostic.json", "source_hashes"),
        ("diagnostic.json", "candidate_fingerprint"),
    ],
)
def test_cache_rejects_changed_data_policy_costs_or_source(tmp_path, artifact, field) -> None:
    signature = fake_signature()
    diagnostic_artifacts(tmp_path, signature)
    path = tmp_path / artifact
    changed = json.loads(path.read_text())
    changed[field] = "different"
    write_json(path, changed)
    with pytest.raises(ValueError, match="conditions differ"):
        SCRIPT.cached_metrics(tmp_path, signature)


def test_partial_cache_is_never_silently_reused(tmp_path) -> None:
    write_json(tmp_path / "metrics.json", {"cagr": 0.15})
    with pytest.raises(ValueError, match="incomplete diagnostic"):
        SCRIPT.cached_metrics(tmp_path, fake_signature())


def test_signature_records_cash_costs_calendar_and_policy_without_backtest(
    tmp_path, monkeypatch
) -> None:
    freeze_winner(tmp_path)
    job = SCRIPT.build_jobs(tmp_path / "store", tmp_path, "costs")[0]
    spec, allocation = SCRIPT.read_candidate(job.candidate)
    book, schedule = SCRIPT.book_and_schedule(job, spec, allocation)
    component = SimpleNamespace(definition=lambda: {"explicit": True})
    runner = SimpleNamespace(
        initial_cash=100000.0,
        base_currency="EUR",
        reference_calendar_id="XPAR",
        execution=component,
        timetable=component,
        analytics=component,
        limits=component,
    )
    monkeypatch.setattr(SCRIPT, "source_hashes", lambda: {"strategy.py": "fixed"})
    signature = SCRIPT.expected_signature(job, runner, allocation, book, schedule, "known-data")
    assert signature["data_state"] == "known-data"
    assert signature["candidate_fingerprint"] == allocation.fingerprint()
    assert signature["configuration"]["initial_cash"] == 100000.0
    assert signature["configuration"]["execution"] == {"explicit": True}
    assert signature["configuration"]["schedule"] == Weekly().definition()
