"""Offline contracts for the fifty-design R4 orchestration and continuous slices.

No test executes a backtest or performs network I/O. The hand-built curves check
that validation retains the preceding close and ignores later observations.
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

import pandas as pd
import pytest

from quant_backtester.strategies.base import Strategy

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def load_script() -> ModuleType:
    """Import the CLI without invoking its entry point or candidate policy."""
    spec = importlib.util.spec_from_file_location(
        "SA15_run_gpt61_round4", SCRIPTS / "SA15_run_gpt61_round4.py"
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
    """Expose enough policy fields to test orchestration without running signals."""

    core_id: str = "ETF_NASDAQ"
    risky_ids: tuple[str, ...] = ("ETF_NASDAQ", "ETF_US_TECH")
    defensive_ids: tuple[str, ...] = ("ETF_GOLD",)
    canary_ids: tuple[str, ...] = ()
    monetary_id: str = "ETF_MONETARY_EUR"
    fixed_weights: tuple[float, ...] = ()
    momentum_lookbacks: tuple[int, ...] = (63, 126)
    momentum_weights: tuple[float, ...] = (1.0, 1.0)
    top_k: int = 1
    strategy_id: str = "SA15_GPT-6.1_R4"

    def decide(self, _ctx):
        """Forbid policy execution in orchestration tests."""
        raise AssertionError("no backtest is permitted")


@pytest.fixture(autouse=True)
def policy_import(monkeypatch):
    """Inject a deterministic constructor and fixed financial source identity."""
    module = ModuleType("quant_backtester.strategies.SA15_gpt61_riskaware")
    module.SA15RiskAwareRotation = MockPolicy
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(SCRIPT, "source_finance_hashes", lambda **_: {"core.py": "fixed"})


def spec(number=31, **changes: object):
    """Return a complete, explicit candidate configuration."""
    return {
        "number": number,
        "reason": "Evaluate the predeclared low-intervention allocation",
        "schedule": "monthly",
        "parameters": MockPolicy().parameters(),
        **changes,
    }


def write(path: Path, value: object) -> Path:
    """Write isolated JSON evidence."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


@pytest.mark.parametrize("number", [1, 30, 81, True, False, 31.0, "31", None])
def test_design_numbers_have_the_authorized_integer_bounds(tmp_path, number):
    with pytest.raises(ValueError, match="integer from 31 to 80"):
        SCRIPT.read_spec(write(tmp_path / "spec.json", spec(number)))


@pytest.mark.parametrize(
    "changes",
    [{"schedule": "daily"}, {"schedule": []}, {"reason": " "}, {"parameters": []}, {"extra": 1}],
)
def test_malformed_candidates_fail_before_runner_access(tmp_path, changes):
    with pytest.raises(ValueError):
        SCRIPT.read_spec(write(tmp_path / "spec.json", spec(**changes)))


def test_parameters_are_explicit_and_sequences_are_normalized(tmp_path):
    path = write(tmp_path / "spec.json", spec())
    saved, policy = SCRIPT.read_spec(path)
    assert policy.risky_ids == ("ETF_NASDAQ", "ETF_US_TECH")
    assert saved["parameters"]["momentum_lookbacks"] == [63, 126]
    candidate = spec()
    del candidate["parameters"]["top_k"]
    with pytest.raises(ValueError, match="every strategy parameter"):
        SCRIPT.read_spec(write(path, candidate))
    candidate = spec()
    candidate["parameters"]["risky_ids"] = ["UNKNOWN"]
    with pytest.raises(ValueError, match="fixed R4 universe"):
        SCRIPT.read_spec(write(path, candidate))


def test_reference_controls_are_initial_buy_and_hold_and_phase_is_lazy(tmp_path, monkeypatch):
    books = SCRIPT.reference_books()
    assert set(books) == {
        "Nasdaq_buy_hold",
        "SP500_buy_hold",
        "Gold_buy_hold",
        "Nasdaq_Gold_50_50",
        "Tech_buy_hold",
    }
    assert all(isinstance(book, SCRIPT.BuyAndHold) for book in books.values())
    assert books["Nasdaq_Gold_50_50"].instruments == ("ETF_NASDAQ", "ETF_GOLD")
    calls = []
    monkeypatch.setattr(SCRIPT, "read_spec", lambda *_: pytest.fail("no candidate import"))
    monkeypatch.setattr(SCRIPT, "build_runner", lambda _: object())
    monkeypatch.setattr(SCRIPT, "run_references", lambda _, period, output: calls.append(period))
    SCRIPT.main(["--references-only", "--output", str(tmp_path)])
    assert calls == ["choice"]


def score_inputs(**changes: object):
    """Give a hand-checkable two-point excess and eleven-point risk improvement."""
    choice = {"cagr": 0.22, "max_drawdown": -0.20, "trade_days_per_year": 3.0, **changes}
    return choice, {"cagr": 0.21}, {"cagr": 0.20, "max_drawdown": -0.31}, {"cagr": 0.20}


def test_score_exactly_rewards_nasdaq_excess_risk_and_sparse_trades():
    result = SCRIPT.selection_score(*score_inputs())
    assert result["excess_choice"] == pytest.approx(0.02)
    assert result["score"] == pytest.approx(0.02 + 0.20 * 0.11)
    assert result["qualified"] is True
    result = SCRIPT.selection_score(*score_inputs(max_drawdown=-0.30, trade_days_per_year=7.0))
    assert result["score"] == pytest.approx(0.02 + 0.20 * 0.01 - 0.50 * 0.05 - 0.001 * 3)
    assert result["qualified"] is False
    values = list(score_inputs())
    values[1] = {"cagr": 0.16}
    assert SCRIPT.selection_score(*values)["score"] == pytest.approx(0.042 - 0.25 * 0.04)


@pytest.mark.parametrize(
    "change",
    [
        {"cagr": float("nan")},
        {"max_drawdown": 0.1},
        {"trade_days_per_year": -1},
        {"trade_days_per_year": True},
        {"cagr": None},
    ],
)
def test_invalid_selection_evidence_is_refused(change):
    with pytest.raises(ValueError):
        SCRIPT.selection_score(*score_inputs(**change))


@pytest.mark.parametrize(
    "depth,trades,qualified", [(-0.25, 4.0, True), (-0.250001, 4, False), (-0.25, 4.0001, False)]
)
def test_qualification_uses_the_frozen_risk_and_intervention_boundaries(depth, trades, qualified):
    assert (
        SCRIPT.selection_score(*score_inputs(max_drawdown=depth, trade_days_per_year=trades))[
            "qualified"
        ]
        is qualified
    )


def test_slice_keeps_preceding_close_ignores_future_and_never_resets_cash(tmp_path):
    dates = ["2022-12-30", "2023-01-02", "2023-12-29", "2024-12-31", "2025-01-02"]
    pd.DataFrame({"session_date": dates, "net_equity": [200, 220, 180, 240, 1e9]}).to_csv(
        tmp_path / "equity.csv", index=False
    )
    pd.DataFrame({"session_date": dates, "gross_equity": [210, 230, 190, 260, 2e9]}).to_csv(
        tmp_path / "gross_equity.csv", index=False
    )
    pd.DataFrame(
        {
            "session_date": ["2022-12-30", "2023-01-02", "2023-01-02", "2025-01-02"],
            "total_cost": [20, 5, 7, 10000],
        }
    ).to_csv(tmp_path / "fills.csv", index=False)
    values = SCRIPT.period_metrics(tmp_path, "2023-01-02", "2024-12-31")
    assert values["net_return"] == pytest.approx(0.20)
    assert values["gross_return"] == pytest.approx(260 / 210 - 1)
    assert values["max_drawdown"] == pytest.approx(180 / 220 - 1)
    assert values["costs_eur"] == 12
    assert values["trade_days"] == 1
    assert values["fills"] == 2
    assert values["anchor"] == "2022-12-30"
    assert values["continuous_book"] is True


@pytest.fixture
def runner(monkeypatch):
    """Expose mutable provenance while prohibiting all real backtest calls."""
    state = SimpleNamespace(digest="data-a")

    @contextmanager
    def pinned() -> Iterator[SimpleNamespace]:
        yield state

    component = SimpleNamespace(definition=lambda: {"explicit": True})
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
        run=lambda *_, **__: pytest.fail("never execute a backtest"),
    )


def populate_cache(folder: Path, signature):
    """Write immutable, internally consistent fake result artifacts."""
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
    for name in SCRIPT.BASE_ARTIFACTS:
        if not (folder / name).exists():
            (folder / name).write_text("synthetic\n", encoding="utf-8")
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


def test_complete_cache_reused_without_run_and_all_trading_evidence_is_required(tmp_path, runner):
    book = SCRIPT.reference_books()["Nasdaq_buy_hold"]
    schedule = SCRIPT.EverySession()
    signature = SCRIPT.expected_signature(runner, book, schedule, *SCRIPT.PERIODS["choice"])
    assert SCRIPT.cached_metrics(tmp_path, signature) is None
    populate_cache(tmp_path, signature)
    assert SCRIPT.run_cached(runner, book, schedule, *SCRIPT.PERIODS["choice"], tmp_path) == {
        "cagr": 0.15
    }
    (tmp_path / "fills.csv").unlink()
    with pytest.raises(ValueError, match="incomplete"):
        SCRIPT.cached_metrics(tmp_path, signature)


@pytest.mark.parametrize("change", ["cash", "data", "schedule", "costs", "source", "policy"])
def test_cache_rejects_changed_financial_conditions(tmp_path, runner, monkeypatch, change):
    book = SCRIPT.reference_books()["Nasdaq_buy_hold"]
    schedule = SCRIPT.EverySession()
    signature = SCRIPT.expected_signature(runner, book, schedule, *SCRIPT.PERIODS["choice"])
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
        book = SCRIPT.reference_books()["Tech_buy_hold"]
    expected = SCRIPT.expected_signature(runner, book, schedule, *SCRIPT.PERIODS["choice"])
    with pytest.raises(ValueError, match="conditions differ"):
        SCRIPT.cached_metrics(tmp_path, expected)


def test_cache_rejects_tampered_gross_curve(tmp_path, runner):
    signature = SCRIPT.expected_signature(
        runner, MockPolicy(), SCRIPT.MonthlyFromStart(), *SCRIPT.PERIODS["choice"], candidate=True
    )
    populate_cache(tmp_path, signature)
    (tmp_path / "gross_equity.csv").write_text("revised\n")
    with pytest.raises(ValueError, match="artifact differs"):
        SCRIPT.cached_metrics(tmp_path, signature)


def complete_trial(output: Path, number: int, *, score=0.01, qualified=True):
    """Write the announced evidence of a test-only candidate."""
    candidate = spec(number)
    candidate["parameters"]["top_k"] = number
    folder = output / f"trial_{number:02d}"
    write(folder / "candidate.json", candidate)
    write(
        folder / "selection.json",
        {
            "score": score,
            "qualified": qualified,
            "excess_choice": 0.01,
            "excess_validation": 0.01,
            "drawdown_depth": 0.2,
            "trade_days_per_year": 3.0,
            "metrics": {},
        },
    )
    return folder / "candidate.json"


def freeze(output: Path):
    """Construct an integrity-protected test winner without any policy execution."""
    path = output / "trial_31/candidate.json"
    if not path.exists():
        complete_trial(output, 31)
    candidate, policy = SCRIPT.read_spec(path)
    SCRIPT.write_frozen_selection(
        output,
        {
            "candidate": candidate,
            "fingerprint": policy.fingerprint(),
            "parameters": SCRIPT.plain_configuration(policy.definition())["parameters"],
            "driver_sha256": SCRIPT.freeze_driver(output, create=True),
            "candidate_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "selection_sha256": hashlib.sha256(
                (path.parent / "selection.json").read_bytes()
            ).hexdigest(),
        },
    )


def test_final_needs_all_fifty_designs_even_if_one_is_exceptional(tmp_path):
    SCRIPT.freeze_driver(tmp_path, create=True)
    complete_trial(tmp_path, 31, score=100)
    with pytest.raises(ValueError, match="all fifty"):
        SCRIPT.finalise(object(), tmp_path, tmp_path)
    assert not (tmp_path / "selected.json").exists()


def test_freeze_and_archive_precede_any_final_read(tmp_path, monkeypatch):
    for number in range(31, 81):
        complete_trial(
            tmp_path, number, score=0.5 if number == 31 else 0.01, qualified=number != 31
        )
    SCRIPT.freeze_driver(tmp_path, create=True)
    monkeypatch.setattr(SCRIPT, "verified_trials", lambda *_: SCRIPT.update_trials(tmp_path))
    events = []

    def archive(output, _store) -> None:
        selected = json.loads((output / "selected.json").read_text())
        assert selected["candidate"]["number"] == 32
        assert selected["round_trials"] == 50
        assert selected["total_trials"] == 80
        assert selected["benchmark"] == "Nasdaq_buy_hold"
        assert (output / "selected.sha256").exists()
        events.append("archived")

    class FinalReached(Exception):
        """Stop before any final-period data can be accessed."""

    def final_read(_runner, period, _output) -> None:
        assert period == "final"
        assert events == ["archived"]
        raise FinalReached

    monkeypatch.setattr(SCRIPT, "archive_sources", archive)
    monkeypatch.setattr(SCRIPT, "run_references", final_read)
    with pytest.raises(FinalReached):
        SCRIPT.finalise(object(), tmp_path, tmp_path / "store")


def test_announced_diagnostics_are_81_replays_and_no_extra_candidates(tmp_path):
    for number in range(31, 81):
        complete_trial(tmp_path, number)
    freeze(tmp_path)
    jobs = SCRIPT.build_jobs(tmp_path / "store", tmp_path)
    assert len(jobs) == 81
    costs = [job for job in jobs if job.diagnostic == "costs_x2"]
    assert len(costs) == 50
    assert all(job.multiplier == 2 and job.period == "choice" for job in costs)
    starts = [job for job in jobs if job.diagnostic == "starts"]
    assert len(starts) == 24
    assert {job.book for job in starts} == {SCRIPT.STRATEGY_NAME, *SCRIPT.REFERENCES}
    assert {job.start for job in starts} == set(SCRIPT.START_DATES)
    full = [job for job in jobs if job.diagnostic == "full"]
    assert len(full) == 7
    assert sum(job.multiplier == 2 for job in full) == 1
    assert len(list(tmp_path.glob("trial_*"))) == 50


def test_source_and_selection_freezes_refuse_revisions(tmp_path, monkeypatch):
    freeze(tmp_path)
    original = (tmp_path / "driver_frozen.json").read_bytes()
    monkeypatch.setattr(SCRIPT, "source_finance_hashes", lambda **_: {"core.py": "changed"})
    with pytest.raises(ValueError, match="financial code differs"):
        SCRIPT.freeze_driver(tmp_path)
    assert (tmp_path / "driver_frozen.json").read_bytes() == original
    selected = json.loads((tmp_path / "selected.json").read_text())
    selected["parameters"]["top_k"] = 99
    write(tmp_path / "selected.json", selected)
    with pytest.raises(ValueError, match="integrity differs"):
        SCRIPT.frozen_winner(tmp_path)


def test_ten_design_batch_is_archived_before_first_candidate_and_cannot_change(
    tmp_path, monkeypatch
):
    paths = []
    for number in range(31, 41):
        paths.append(write(tmp_path / "configs" / f"{number}.json", spec(number)))
    calls = []

    def iterate(path, _runner, output) -> None:
        manifest = json.loads((output / "batches/batch_01.json").read_text())
        assert manifest["numbers"] == list(range(31, 41))
        calls.append(path)

    monkeypatch.setattr(SCRIPT, "iterate", iterate)
    SCRIPT.iterate_many(paths, object(), tmp_path)
    assert calls == paths
    changed = spec(31, reason="changed after announcement")
    write(paths[0], changed)
    with pytest.raises(ValueError, match="cannot be changed"):
        SCRIPT.iterate_many(paths, object(), tmp_path)


@pytest.mark.parametrize("numbers", [range(31, 40), range(32, 42), range(41, 51)])
def test_invalid_or_premature_batch_is_rejected(tmp_path, numbers):
    paths = [write(tmp_path / f"{number}.json", spec(number)) for number in numbers]
    with pytest.raises(ValueError):
        SCRIPT.iterate_many(paths, object(), tmp_path)


@pytest.mark.parametrize(
    "schedule", [SCRIPT.MonthlyFromStart(), SCRIPT.WeeklyFromStart(), SCRIPT.QuarterlyFromStart()]
)
def test_inception_schedules_are_prefix_invariant(schedule):
    sessions = [
        date(2023, 3, 29),
        date(2023, 3, 30),
        date(2023, 3, 31),
        date(2023, 4, 3),
        date(2023, 4, 28),
        date(2023, 5, 2),
    ]
    full = schedule.decision_sessions(sessions, date(2023, 5, 3))
    assert sessions[0] in full
    for stop in range(1, len(sessions)):
        assert schedule.decision_sessions(sessions[:stop], sessions[stop]) == full.intersection(
            sessions[:stop]
        )
    assert schedule.decision_sessions([], None) == frozenset()


def test_quarterly_has_true_quarter_end_but_no_other_month_end():
    sessions = [date(2023, 3, 29), date(2023, 3, 31), date(2023, 4, 3), date(2023, 4, 28)]
    assert SCRIPT.QuarterlyFromStart().decision_sessions(sessions, date(2023, 5, 2)) == frozenset(
        [date(2023, 3, 29), date(2023, 3, 31)]
    )


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["--candidate", "a", "--final"],
        ["--candidates", "a", "--robustness"],
        ["--robustness", "--workers", "4"],
    ],
)
def test_invalid_cli_fails_before_store_access(arguments):
    with pytest.raises(SystemExit) as error:
        SCRIPT.parse_arguments(arguments)
    assert error.value.code == 2
