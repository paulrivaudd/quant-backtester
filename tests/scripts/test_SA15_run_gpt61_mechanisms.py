"""Offline contracts for sequential mechanism research and immutable replay reuse.

No test executes a market backtest or accesses the network. Deterministic fake
books exercise cache provenance, chronological gates and passive observation.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from quant_backtester.strategies.base import Strategy
from quant_backtester.strategies.SA15_gpt61_mechanisms import SA15Mechanisms

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def load_script() -> ModuleType:
    """Import the command without invoking any phase."""
    spec = importlib.util.spec_from_file_location(
        "SA15_run_gpt61_mechanisms", SCRIPTS / "SA15_run_gpt61_mechanisms.py"
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


def write(path: Path, value: object) -> Path:
    """Write deterministic isolated JSON evidence."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def baseline() -> dict:
    """Return the explicit fixed pilot parent."""
    return {
        "id": "M00",
        "reason": "Pilot to correct after its measured reentry lag",
        "schedule": "monthly",
        "parameters": dict(SA15Mechanisms().parameters()),
    }


def candidate(**changes: object) -> dict:
    """Return one fully written recovery-block experiment."""
    parameters = dict(SA15Mechanisms(recovery_rule="positive21").parameters())
    return {
        "id": "M01",
        "parent": "M00",
        "reason": "Correct delayed trend reentry",
        "changed_block": "recovery",
        "expected_benefit": "Capture a positive short recovery",
        "expected_cost": "Additional false recoveries",
        "refutation": "More cost without compensating active return",
        "schedule": "monthly",
        "parameters": parameters,
        **changes,
    }


@pytest.mark.parametrize(
    "identifier", ["M00", "M51", "M1", "m01", "M001", 1, True, None, "M-1", "X01"]
)
def test_candidate_identifiers_are_exact_and_bounded(identifier):
    with pytest.raises(ValueError, match="M01 through M50"):
        SCRIPT.design_number(identifier)


def test_baseline_identifier_is_explicitly_separate():
    assert SCRIPT.design_number("M00", baseline=True) == 0
    assert SCRIPT.design_number("M50") == 50


@pytest.mark.parametrize(
    "changes",
    [
        {"id": "M51"},
        {"parent": "M01"},
        {"parent": "M20"},
        {"schedule": "daily"},
        {"schedule": []},
        {"reason": ""},
        {"expected_cost": " "},
        {"refutation": None},
        {"parameters": []},
        {"extra": 1},
    ],
)
def test_candidate_requires_full_preregistered_hypothesis(tmp_path, changes):
    with pytest.raises(ValueError):
        SCRIPT.read_spec(write(tmp_path / "candidate.json", candidate(**changes)))


def test_policy_has_no_implicit_parameter_defaults(tmp_path):
    spec = candidate()
    del spec["parameters"]["fast_sessions"]
    with pytest.raises(ValueError, match="every strategy parameter"):
        SCRIPT.read_spec(write(tmp_path / "candidate.json", spec))


@pytest.mark.parametrize(
    "changes", [{"strategy_id": "other"}, {"core_id": "OTHER"}, {"monetary_id": "OTHER"}]
)
def test_policy_identity_and_instruments_are_fixed(tmp_path, changes):
    spec = candidate()
    spec["parameters"].update(changes)
    with pytest.raises(ValueError):
        SCRIPT.read_spec(write(tmp_path / "candidate.json", spec))


def test_baseline_requires_full_parameters_and_m00(tmp_path):
    saved, policy = SCRIPT.read_baseline(write(tmp_path / "baseline.json", baseline()))
    assert saved["id"] == "M00"
    assert policy.recovery_rule == "off"
    for changes in ({"id": "M01"}, {"extra": 1}, {"reason": ""}):
        with pytest.raises(ValueError):
            SCRIPT.read_baseline(write(tmp_path / "bad.json", {**baseline(), **changes}))


def test_exactly_one_categorical_mechanism_changes():
    SCRIPT.validate_single_change(baseline(), candidate())
    child = candidate()
    child["parameters"]["risk_rule"] = "off"
    with pytest.raises(ValueError, match="exactly the declared block"):
        SCRIPT.validate_single_change(baseline(), child)


def test_numeric_constants_cannot_be_searched_even_inside_one_block():
    child = candidate()
    child["parameters"]["target_volatility"] = 0.23
    with pytest.raises(ValueError, match="fixed or ambiguous"):
        SCRIPT.validate_single_change(baseline(), child)


def test_cadence_is_a_separate_declared_mechanism():
    child = candidate(
        changed_block="cadence", schedule="weekly", parameters=baseline()["parameters"]
    )
    SCRIPT.validate_single_change(baseline(), child)
    child["parameters"] = candidate()["parameters"]
    with pytest.raises(ValueError, match="exactly the declared block"):
        SCRIPT.validate_single_change(baseline(), child)


def test_unchanged_policy_cannot_count_as_a_new_design():
    with pytest.raises(ValueError, match="exactly the declared block"):
        SCRIPT.validate_single_change(baseline(), candidate(parameters=baseline()["parameters"]))


def test_every_active_block_has_its_own_complete_removal():
    spec = candidate()
    policy = SCRIPT.make_policy(spec["parameters"])
    books = SCRIPT.comparison_books(spec, policy, baseline())
    assert set(books) == {
        "candidate",
        "parent",
        "Nasdaq_buy_hold",
        *(f"without_{block}" for block in policy.active_blocks()),
    }
    assert set(SCRIPT.UNIVERSE) == {"ETF_NASDAQ", "ETF_MONETARY_EUR", "ETF_GOLD", "ETF_EURO_GOV"}
    for block in policy.active_blocks():
        ablation, schedule = books[f"without_{block}"]
        assert ablation.fingerprint() == policy.without_block(block).fingerprint()
        assert schedule.definition() == books["candidate"][1].definition()
    assert books["Nasdaq_buy_hold"][0].instruments == ("ETF_NASDAQ",)


def test_monthly_and_weekly_schedules_keep_true_ends_and_initial_decision():
    sessions = (
        date(2024, 1, 29),
        date(2024, 1, 30),
        date(2024, 1, 31),
        date(2024, 2, 1),
        date(2024, 2, 2),
    )
    following = date(2024, 2, 5)
    monthly = SCRIPT.SCHEDULES["monthly"]()
    weekly = SCRIPT.SCHEDULES["weekly"]()
    assert monthly.decision_sessions(sessions, following) == {date(2024, 1, 29), date(2024, 1, 31)}
    assert weekly.decision_sessions(sessions, following) == {date(2024, 1, 29), date(2024, 2, 2)}
    assert date(2024, 1, 30) not in monthly.decision_sessions(sessions[:2], sessions[2])


@dataclass(frozen=True, slots=True)
class ObservablePolicy(Strategy):
    """Hand-checkable pure policy; its plan cannot see another timestamp."""

    strategy_id: str = "observer_test"

    def plan(self, ctx):
        """Return only the value available in the supplied context."""
        value = ctx.available
        return SimpleNamespace(
            audit_dict=lambda: {
                "core_weight": value,
                "signals": {"available": value},
                "weights": {"ETF_NASDAQ": value},
                "skipped": {},
            }
        )

    def decide(self, ctx):
        """Produce the unmodified target independently of any log."""
        return {"ETF_NASDAQ": ctx.available}


def test_observer_has_identical_fingerprint_targets_and_required_signals():
    policy = ObservablePolicy()
    observer = SCRIPT.AuditPolicy(policy)
    ctx = SimpleNamespace(
        as_of=datetime(2024, 1, 31, 22, tzinfo=UTC), available=0.6, future_value=999
    )
    assert observer.definition() == policy.definition()
    assert observer.fingerprint() == policy.fingerprint()
    assert observer.required_signals() == policy.required_signals()
    assert observer.decide(ctx) == policy.decide(ctx)
    observer.rows[0]["core_weight"] = 0.0
    ctx.future_value = -999
    assert observer.decide(ctx) == policy.decide(ctx) == {"ETF_NASDAQ": 0.6}
    assert observer.rows[-1]["signals"] == {"available": 0.6}


def fake_runner(multiplier=1):
    """Expose deterministic configuration without an engine or store."""

    def definition() -> dict:
        return {"multiplier": multiplier}

    common = SimpleNamespace(definition=definition)
    return SimpleNamespace(
        execution=common,
        initial_cash=100_000.0,
        base_currency="EUR",
        reference_calendar_id="XPAR",
        timetable=common,
        analytics=common,
        limits=common,
    )


def frozen():
    """Return hand-built immutable input identities."""
    return {
        "data_state": {"digest": "data", "files": {"bars": "sha"}},
        "source_finance_hashes": {"policy.py": "sha"},
    }


def fake_cache(folder: Path, expected: dict, metrics: dict | None = None):
    """Write a complete, internally consistent replay provenance fixture."""
    values = {"cagr": 0.20, "max_drawdown": -0.25, **(metrics or {})}
    contents = {name: "evidence\n" for name in SCRIPT.ARTIFACTS}
    contents["metrics.json"] = json.dumps(values)
    contents["configuration.json"] = json.dumps(expected["configuration"])
    contents["strategy.json"] = json.dumps(expected["strategy"])
    contents["identity.json"] = json.dumps(
        {"fingerprint": expected["fingerprint"], "data_state": {"digest": expected["data_state"]}}
    )
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in contents.items():
        (folder / name).write_text(text, encoding="utf-8")
    write(
        folder / "cache.json",
        {
            "signature": expected,
            "artifacts": {name: SCRIPT.sha256(folder / name) for name in SCRIPT.ARTIFACTS},
        },
    )
    return values


def test_cache_key_changes_with_costs_dates_cadence_sources_and_data():
    policy = ObservablePolicy()
    monthly = SCRIPT.SCHEDULES["monthly"]()
    start, end = SCRIPT.PERIODS["choice"]
    reference = SCRIPT.signature(fake_runner(), policy, monthly, start, end, frozen())
    changed = [
        SCRIPT.signature(fake_runner(2), policy, monthly, start, end, frozen()),
        SCRIPT.signature(fake_runner(), policy, monthly, "2020-01-02", end, frozen()),
        SCRIPT.signature(fake_runner(), policy, SCRIPT.SCHEDULES["weekly"](), start, end, frozen()),
        SCRIPT.signature(
            fake_runner(),
            policy,
            monthly,
            start,
            end,
            {**frozen(), "source_finance_hashes": {"policy.py": "changed"}},
        ),
        SCRIPT.signature(
            fake_runner(),
            policy,
            monthly,
            start,
            end,
            {**frozen(), "data_state": {"digest": "changed"}},
        ),
    ]
    assert all(
        SCRIPT.canonical_hash(value) != SCRIPT.canonical_hash(reference) for value in changed
    )


def test_matching_cache_reused_without_engine_call_and_role_copy_is_verified(tmp_path):
    policy = ObservablePolicy()
    runner = fake_runner()
    runner.run = lambda *_args, **_kwargs: pytest.fail("matching book must not run twice")
    schedule = SCRIPT.SCHEDULES["monthly"]()
    expected = SCRIPT.signature(runner, policy, schedule, *SCRIPT.PERIODS["choice"], frozen())
    key = SCRIPT.canonical_hash(expected)
    values = fake_cache(tmp_path / "cache" / key, expected)
    role = tmp_path / "M01/choice/costs_x1/candidate"
    actual, actual_key, physical = SCRIPT.run_cached(
        runner, policy, schedule, *SCRIPT.PERIODS["choice"], tmp_path, role, frozen()
    )
    assert actual == values and actual_key == key and physical is False
    assert (role / "cache_link.json").is_file()
    (role / "equity.csv").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="role evidence differs"):
        SCRIPT.run_cached(
            runner, policy, schedule, *SCRIPT.PERIODS["choice"], tmp_path, role, frozen()
        )


@pytest.mark.parametrize(
    "filename",
    [
        "metrics.json",
        "equity.csv",
        "gross_equity.csv",
        "decisions.csv",
        "configuration.json",
        "attempt.json",
    ],
)
def test_cache_artifact_changes_cannot_be_reused(tmp_path, filename):
    expected = SCRIPT.signature(
        fake_runner(),
        ObservablePolicy(),
        SCRIPT.SCHEDULES["monthly"](),
        *SCRIPT.PERIODS["choice"],
        frozen(),
    )
    fake_cache(tmp_path, expected)
    (tmp_path / filename).write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="cache artifact differs"):
        SCRIPT.validate_cache(tmp_path, expected)


def test_cache_refuses_partial_results_and_changed_sources(tmp_path):
    expected = SCRIPT.signature(
        fake_runner(),
        ObservablePolicy(),
        SCRIPT.SCHEDULES["monthly"](),
        *SCRIPT.PERIODS["choice"],
        frozen(),
    )
    assert SCRIPT.validate_cache(tmp_path, expected) is None
    write(tmp_path / "metrics.json", {})
    with pytest.raises(ValueError, match="incomplete"):
        SCRIPT.validate_cache(tmp_path, expected)
    fake_cache(tmp_path, expected)
    with pytest.raises(ValueError, match="conditions differ"):
        SCRIPT.validate_cache(tmp_path, {**expected, "source_finance_hashes": {"changed": "sha"}})


def test_missing_analysis_blocks_next_iteration_before_any_runner(tmp_path, monkeypatch):
    write(tmp_path / "M01/completed.json", {"result": "bad"})
    monkeypatch.setattr(
        SCRIPT.previous,
        "build_runner",
        lambda *_: pytest.fail("analysis gate precedes financial work"),
    )
    config = write(tmp_path / "input.json", candidate(id="M02", parent="M01"))
    with pytest.raises(ValueError, match="analyze M01"):
        SCRIPT.iterate(config, tmp_path, tmp_path, tmp_path, tmp_path)


def test_analysis_must_reference_exact_completed_evidence(tmp_path):
    folder = tmp_path / "M01"
    write(folder / "completed.json", {"result": "retained"})
    analysis = {
        "id": "M01",
        "completed_sha256": SCRIPT.sha256(folder / "completed.json"),
        "decision": "Reject recovery",
        "findings": ["Protection lost"],
        "next_defect": "Try a confirmation gate",
    }
    path = write(folder / "analysis.json", analysis)
    assert SCRIPT.require_analysis(tmp_path, "M01") == {"id": "M01", "sha256": SCRIPT.sha256(path)}
    write(folder / "completed.json", {"result": "changed"})
    with pytest.raises(ValueError, match="not bound"):
        SCRIPT.require_analysis(tmp_path, "M01")


def test_write_once_refuses_overwriting_bad_history(tmp_path):
    path = tmp_path / "evidence.json"
    SCRIPT.write_once(path, {"bad_result": True})
    SCRIPT.write_once(path, {"bad_result": True})
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        SCRIPT.write_once(path, {"bad_result": False})


def test_freeze_refuses_insufficient_designs_without_final_backtest(tmp_path, monkeypatch):
    monkeypatch.setattr(SCRIPT.previous, "build_runner", lambda *_: object())
    monkeypatch.setattr(SCRIPT, "freeze_inputs", lambda *_args, **_kwargs: frozen())
    with pytest.raises(ValueError, match="analyze M01"):
        SCRIPT.freeze_selection(tmp_path, tmp_path, tmp_path, tmp_path)


def test_choice_contract_cannot_see_2025_before_selection():
    assert SCRIPT.PERIODS["choice"] == ("2019-06-03", "2024-12-31")
    assert SCRIPT.PERIODS["final"] == ("2025-01-02", "2026-10-09")
    assert len(SCRIPT.START_DATES) == 4


def test_physical_replays_and_logical_contracts_are_distinct(tmp_path):
    write(tmp_path / "M01/contract.json", {"contracts": [1, 2, 3, 4]})
    write(tmp_path / "cache/key/attempt.json", {})
    write(tmp_path / "cache/key/cache.json", {})
    write(tmp_path / "cache/failed/attempt.json", {})
    counts = SCRIPT.cache_counts(tmp_path)
    assert counts == {
        "physical_replays": 2,
        "completed_physical_replays": 1,
        "logical_contracts": 4,
    }


def test_cli_requires_exactly_one_authorized_phase(monkeypatch):
    calls = []
    monkeypatch.setattr(SCRIPT, "run_diagnostics", lambda kind, *_: calls.append(kind))
    monkeypatch.setattr(SCRIPT, "cache_counts", lambda *_: {})
    SCRIPT.main(["--final"])
    SCRIPT.main(["--robustness"])
    assert calls == ["final", "robustness"]
    with pytest.raises(SystemExit):
        SCRIPT.main(["--final", "--freeze"])


def test_frozen_selection_digest_prevents_winner_replacement(tmp_path):
    write(tmp_path / "selected.json", {"id": "M01"})
    (tmp_path / "selected.sha256").write_text("wrong", encoding="utf-8")
    with pytest.raises(ValueError, match="integrity differs"):
        SCRIPT.frozen_winner(tmp_path)


def test_passive_audit_keeps_preband_plan_and_postband_official_targets(tmp_path, monkeypatch):
    """A band may keep a target different from the newly computed pure plan."""
    import pandas as pd

    observer = SCRIPT.AuditPolicy(ObservablePolicy())
    ctx = SimpleNamespace(as_of=datetime(2024, 1, 31, 22, tzinfo=UTC), available=0.6)
    observer.decide(ctx)

    def save(folder, _result, **_: object) -> dict:
        folder.mkdir(parents=True)
        pd.DataFrame(
            [
                {
                    "session_date": "2024-01-31",
                    "decision_time": ctx.as_of,
                    "weights": '{"ETF_NASDAQ": 0.65}',
                    "skipped": "{}",
                    "hold_positions": True,
                }
            ]
        ).to_csv(folder / "decisions.csv", index=False)
        return {"cagr": 0.2}

    monkeypatch.setattr(SCRIPT.previous, "save_run", save)
    folder = tmp_path / "book"
    SCRIPT.save_evidence(folder, object(), observer)
    row = pd.read_csv(folder / "decisions.csv").iloc[0]
    assert row["core_weight"] == 0.6
    assert json.loads(row["plan_weights"]) == {"ETF_NASDAQ": 0.6}
    assert json.loads(row["weights"]) == {"ETF_NASDAQ": 0.65}
    assert json.loads(row["signals"]) == {"available": 0.6}


def test_new_book_runs_once_and_double_cost_is_a_separate_physical_replay(tmp_path, monkeypatch):
    calls = []
    policy = ObservablePolicy()
    schedule = SCRIPT.SCHEDULES["monthly"]()
    expected_by_folder = {}

    def save(folder, result, _observer) -> dict:
        expected = expected_by_folder[folder]
        values = fake_cache(folder, expected)
        (folder / "cache.json").unlink()
        return values

    monkeypatch.setattr(SCRIPT, "save_evidence", save)
    for cost in (1, 2):
        runner = fake_runner(cost)
        expected = SCRIPT.signature(runner, policy, schedule, *SCRIPT.PERIODS["choice"], frozen())
        key = SCRIPT.canonical_hash(expected)
        expected_by_folder[tmp_path / "cache" / key] = expected

        def run(book, universe, start, end, *, schedule, cost=cost) -> SimpleNamespace:
            calls.append((book.fingerprint(), cost, universe, start, end))
            return SimpleNamespace(
                data_state=SimpleNamespace(digest="data"), fingerprint=book.fingerprint()
            )

        runner.run = run
        first = SCRIPT.run_cached(
            runner,
            policy,
            schedule,
            *SCRIPT.PERIODS["choice"],
            tmp_path,
            tmp_path / f"role_x{cost}",
            frozen(),
        )
        second = SCRIPT.run_cached(
            runner,
            policy,
            schedule,
            *SCRIPT.PERIODS["choice"],
            tmp_path,
            tmp_path / f"parent_x{cost}",
            frozen(),
        )
        assert first[2] is True and second[2] is False
    assert len(calls) == 2
    assert [row[1] for row in calls] == [1, 2]
    assert SCRIPT.cache_counts(tmp_path)["physical_replays"] == 2


def test_freeze_detects_financial_code_and_data_changes(tmp_path, monkeypatch):
    source = {"financial.py": "before"}
    state = frozen()["data_state"]
    monkeypatch.setattr(SCRIPT, "source_hashes", lambda: source.copy())
    monkeypatch.setattr(SCRIPT, "data_state", lambda _: state.copy())
    monkeypatch.setattr(SCRIPT.previous, "archive_sources", lambda *_: None)
    baseline_path = write(tmp_path / "baseline.json", baseline())
    hypothesis = write(
        tmp_path / "hypothesis.json", {"question": "Correct reentry with a mechanism"}
    )
    output = tmp_path / "output"
    runners = {1.0: object(), 2.0: object()}
    original = SCRIPT.freeze_inputs(
        output, tmp_path, baseline_path, hypothesis, runners, create=True
    )
    assert SCRIPT.freeze_inputs(output, tmp_path, baseline_path, hypothesis, runners) == original
    source["financial.py"] = "changed"
    with pytest.raises(ValueError, match="differs from M01 freeze"):
        SCRIPT.freeze_inputs(output, tmp_path, baseline_path, hypothesis, runners)
    source["financial.py"] = "before"
    state["digest"] = "changed"
    with pytest.raises(ValueError, match="differs from M01 freeze"):
        SCRIPT.freeze_inputs(output, tmp_path, baseline_path, hypothesis, runners)


def test_selection_ranks_fifty_candidates_and_never_an_ablation(tmp_path, monkeypatch):
    write(tmp_path / "frozen_inputs.json", {})
    monkeypatch.setattr(SCRIPT.previous, "build_runner", lambda *_: object())
    monkeypatch.setattr(SCRIPT, "freeze_inputs", lambda *_args, **_kwargs: frozen())
    monkeypatch.setattr(
        SCRIPT,
        "require_analysis",
        lambda _output, identifier: {"id": identifier, "sha256": "analysis"},
    )
    policy = ObservablePolicy()
    monkeypatch.setattr(SCRIPT, "read_spec", lambda path: ({"id": path.parent.name}, policy))
    for number in range(1, 51):
        folder = tmp_path / f"M{number:02d}"
        write(folder / "candidate.json", {"id": folder.name})
        write(folder / "contract.json", {})
        write(
            folder / "completed.json",
            {
                "contract_sha256": SCRIPT.sha256(folder / "contract.json"),
                "score": {"score": number / 100, "qualified": number == 10},
            },
        )
    monkeypatch.setattr(
        SCRIPT,
        "verify_completed",
        lambda output, identifier, **_: SCRIPT.read_json(output / identifier / "completed.json"),
    )
    SCRIPT.freeze_selection(tmp_path, tmp_path, tmp_path, tmp_path)
    selected = SCRIPT.read_json(tmp_path / "selected.json")
    assert selected["id"] == "M10"
    assert selected["candidate_count"] == 50
    assert len(selected["ranking"]) == 50
    assert selected["ranking"][1]["id"] == "M50"
    assert (tmp_path / "selected.sha256").read_text().strip() == SCRIPT.sha256(
        tmp_path / "selected.json"
    )


def test_quarterly_cadence_preserves_true_quarter_end():
    sessions = (date(2024, 3, 27), date(2024, 3, 28), date(2024, 4, 2))
    schedule = SCRIPT.SCHEDULES["quarterly"]()
    assert schedule.decision_sessions(sessions, date(2024, 4, 3)) == {
        date(2024, 3, 27),
        date(2024, 3, 28),
    }
    assert date(2024, 4, 2) not in schedule.decision_sessions(sessions, date(2024, 4, 3))


def test_neighbor_profiles_change_only_predeclared_horizons_and_cannot_be_candidates():
    policy = SA15Mechanisms(recovery_rule="positive21")
    profiles = SCRIPT.sensitivity_policies(policy)
    assert set(profiles) == {"neighbor_short", "neighbor_long"}
    windows = {
        "fast_sessions",
        "medium_sessions",
        "slow_sessions",
        "ma_fast_sessions",
        "ma_slow_sessions",
        "vol_fast_returns",
        "vol_slow_returns",
        "drawdown_sessions",
        "defensive_sessions",
        "monetary_sessions",
    }
    for name, neighbor in profiles.items():
        parameters = neighbor.parameters()
        factor = 0.8 if name == "neighbor_short" else 1.2
        changed = {key for key in parameters if parameters[key] != policy.parameters()[key]}
        assert changed == windows
        assert parameters["fast_sessions"] == round(policy.fast_sessions * factor)
        assert parameters["max_age_sessions"] == policy.max_age_sessions
        assert parameters["target_volatility"] == policy.target_volatility
        with pytest.raises(ValueError, match="fixed or ambiguous"):
            SCRIPT.validate_single_change(candidate(), candidate(parameters=dict(parameters)))


def test_robustness_contracts_keep_neighbors_nonselectable_and_both_actual_costs(
    tmp_path, monkeypatch
):
    policy = SA15Mechanisms(recovery_rule="positive21")
    selected = {"candidate": candidate()}
    write(tmp_path / "selected.json", {"id": "M01"})
    monkeypatch.setattr(SCRIPT, "frozen_winner", lambda _: (selected, policy))
    monkeypatch.setattr(SCRIPT.previous, "build_runner", lambda _store, cost: fake_runner(cost))
    monkeypatch.setattr(SCRIPT, "freeze_inputs", lambda *_args, **_kwargs: frozen())
    calls = []

    def replay(runner, book, schedule, start, end, output, folder, inputs) -> tuple:
        calls.append((book, folder, start, end))
        return {"cagr": 0.1}, "cache-key", True

    monkeypatch.setattr(SCRIPT, "run_cached", replay)
    SCRIPT.run_diagnostics("robustness", tmp_path, tmp_path, tmp_path, tmp_path)
    jobs = SCRIPT.read_json(tmp_path / "robustness_contracts.json")["contracts"]
    assert len(jobs) == len(calls) == 24
    neighbors = [job for job in jobs if job["period"].startswith("neighbor_")]
    assert len(neighbors) == 8
    assert all(job["nonselectable"] for job in neighbors)
    assert {job["cost_multiplier"] for job in neighbors} == {1.0, 2.0}
    assert all((job["start"], job["end"]) == SCRIPT.PERIODS["choice"] for job in neighbors)
    assert all(job["folder"] == f"robustness/{job['period']}" for job in jobs)
    assert not (tmp_path / "M51").exists()


@pytest.mark.parametrize(
    ("observed_time", "official_time", "raises"),
    [
        ("2024-07-31T23:00:00+02:00", "2024-07-31T21:00:00+00:00", False),
        ("2024-07-31T23:00:00", "2024-07-31T21:00:00+00:00", True),
        ("2024-07-31T23:00:00+02:00", "2024-07-31T21:00:00", True),
    ],
)
def test_audit_join_uses_aware_instants_across_different_offsets(
    tmp_path, monkeypatch, observed_time, official_time, raises
):
    """Offset spellings may differ; a missing timezone must never be inferred."""
    import pandas as pd

    observer = SCRIPT.AuditPolicy(ObservablePolicy())
    ctx = SimpleNamespace(as_of=pd.Timestamp(observed_time).to_pydatetime(), available=0.6)
    expected_target = observer.policy.decide(ctx)
    assert observer.decide(ctx) == expected_target
    fingerprint = observer.fingerprint()

    def save(folder, _result, **_: object) -> dict:
        folder.mkdir(parents=True)
        pd.DataFrame(
            [
                {
                    "session_date": "2024-07-31",
                    "decision_time": official_time,
                    "weights": '{"ETF_NASDAQ": 0.6}',
                    "skipped": "{}",
                }
            ]
        ).to_csv(folder / "decisions.csv", index=False)
        return {"cagr": 0.2}

    monkeypatch.setattr(SCRIPT.previous, "save_run", save)
    folder = tmp_path / "book"
    if raises:
        with pytest.raises(ValueError, match="timezone-aware"):
            SCRIPT.save_evidence(folder, object(), observer)
    else:
        SCRIPT.save_evidence(folder, object(), observer)
        row = pd.read_csv(folder / "decisions.csv").iloc[0]
        assert row["core_weight"] == 0.6
        assert json.loads(row["weights"]) == expected_target
        assert row["decision_time"] == official_time
    assert observer.fingerprint() == fingerprint == observer.policy.fingerprint()
