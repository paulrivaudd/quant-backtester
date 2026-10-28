"""Offline contracts for the single fixed mechanism pilot and its ablations.

No test runs a market backtest. Stubbed engine calls verify that preregistration,
immutable source/data capture and matched conditions precede all thirty replays.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
try:
    _spec = importlib.util.spec_from_file_location(
        "SA15_mechanism_pilot_tested", SCRIPTS / "SA15_mechanism_pilot.py"
    )
    assert _spec is not None and _spec.loader is not None
    SCRIPT = importlib.util.module_from_spec(_spec)
    sys.modules[_spec.name] = SCRIPT
    _spec.loader.exec_module(SCRIPT)
finally:
    sys.path.remove(str(SCRIPTS))


def definition(value):
    """Expose a tiny deterministic component definition."""
    return SimpleNamespace(definition=lambda: value)


class FakeRunner:
    """Record orchestration without accessing market data or calling signals."""

    def __init__(self, multiplier, state, events, output) -> None:
        self.multiplier = multiplier
        self.state = state
        self.events = events
        self.output = output
        self.execution = definition({"cost_multiplier": multiplier})
        self.initial_cash = 100_000.0
        self.base_currency = "EUR"
        self.reference_calendar_id = "XPAR"
        self.timetable = definition({"decision": "23:00 Europe/Paris"})
        self.analytics = definition({"sessions_per_year": 252})
        self.limits = definition({"long_only": True})
        self.reader = SimpleNamespace(pinned=self.pinned)
        self.on_run = lambda: None

    @contextmanager
    def pinned(self):
        """Yield mutable test state through the reader's real pin interface."""
        yield SimpleNamespace(digest=self.state["digest"], files=self.state["files"])

    def run(self, policy, universe, start, end, *, schedule):
        """Require complete immutable evidence before recording a fake replay."""
        assert (self.output / "manifest.json").is_file()
        assert (self.output / "source/source.zip").is_file()
        assert (self.output / "hypothesis.json").is_file()
        assert universe == ("ETF_NASDAQ", "ETF_MONETARY_EUR")
        assert schedule.definition() == SCRIPT.round4.MonthlyFromStart().definition()
        self.events.append(("run", self.multiplier, start, end, policy.fingerprint()))
        self.on_run()
        return SimpleNamespace(
            data_state=SimpleNamespace(digest=self.state["digest"]),
            fingerprint=policy.fingerprint(),
        )


@pytest.fixture
def harness(tmp_path, monkeypatch):
    """Provide deterministic source/data identities and a nonfinancial fake engine."""
    hypothesis = tmp_path / "hypothesis.json"
    hypothesis.write_text('{"statement": "fixed mechanism before any run"}', encoding="utf-8")
    output = tmp_path / "output"
    state = {"digest": "data-before", "files": {"bars.parquet": "fixed-price-hash"}}
    sources = {"engine.py": "fixed-source-hash"}
    events = []
    runners = {
        multiplier: FakeRunner(multiplier, state, events, output) for multiplier in (1.0, 2.0)
    }

    def build(_store, multiplier) -> FakeRunner:
        events.append(("build", multiplier))
        return runners[multiplier]

    def archive(folder, _store) -> None:
        events.append(("archive",))
        (folder / "source").mkdir()
        (folder / "source/source.zip").write_bytes(b"frozen source archive")

    def save(folder, result, *, details) -> dict[str, float | int]:
        assert details is True
        events.append(("save",))
        folder.mkdir(parents=True, exist_ok=False)
        values = {"net_return": 0.1, "trade_days": 1}
        SCRIPT.round4.write_json(folder / "metrics.json", values)
        return values

    monkeypatch.setattr(SCRIPT.round4, "build_runner", build)
    monkeypatch.setattr(SCRIPT.round4, "archive_sources", archive)
    monkeypatch.setattr(SCRIPT.round4, "save_run", save)
    monkeypatch.setattr(SCRIPT, "financial_source_hashes", lambda: dict(sources))
    return SimpleNamespace(
        hypothesis=hypothesis,
        output=output,
        state=state,
        sources=sources,
        events=events,
        runners=runners,
        store=tmp_path / "unchanged-store",
    )


def test_full_policy_is_explicit_and_uses_only_the_fixed_two_funds():
    books = SCRIPT.policies()
    full = books["full"]
    values = asdict(full)
    assert SCRIPT.round4.plain_configuration(values) == full.parameters()
    assert full.risky_ids == ("ETF_NASDAQ",)
    assert full.defensive_ids == full.canary_ids == ()
    assert full.monetary_id == "ETF_MONETARY_EUR"
    assert full.mode == "ensemble"
    assert full.momentum_lookbacks == (200,)
    assert full.momentum_weights == (1.0,)
    assert full.trend_kind == "moving_average"
    assert full.target_volatility == 0.20
    assert full.volatility_windows == (20, 60)
    assert full.volatility_floor == 0.05
    assert full.core_floor == full.recovery_lookback == 0
    assert full.rebalance_band == 0.10
    assert full.monetary_lookback == 21
    assert full.max_age_sessions == 1
    assert len({book.strategy_id for name, book in books.items() if name != "Nasdaq_buy_hold"}) == 1


@pytest.mark.parametrize(
    "left,right,expected",
    [
        ("full", "trend_only", {"target_volatility"}),
        ("full", "volatility_only", {"mode"}),
        ("trend_only", "neither", {"mode"}),
        ("volatility_only", "neither", {"mode", "target_volatility"}),
    ],
)
def test_ablations_change_only_the_declared_switches(left, right, expected):
    books = SCRIPT.policies()
    a, b = asdict(books[left]), asdict(books[right])
    assert {key for key in a if a[key] != b[key]} == expected
    # The volatility-only family rejects a zero cap, hence its second switch
    # when disabling the remaining block in the neither control.
    assert books["neither"].mode == "balanced"
    assert books["neither"].target_volatility == 0
    assert books["Nasdaq_buy_hold"].instruments == ("ETF_NASDAQ",)


def test_all_thirty_jobs_are_matched_real_cost_and_cash_restart_replays(tmp_path):
    jobs = SCRIPT.build_jobs(tmp_path)
    assert len(jobs) == len({job.folder for job in jobs}) == 30
    for period, dates in SCRIPT.PERIODS.items():
        period_jobs = [job for job in jobs if job.period == period]
        assert len(period_jobs) == 10
        assert {(job.start, job.end) for job in period_jobs} == {dates}
        for multiplier in (1.0, 2.0):
            assert {job.policy for job in period_jobs if job.cost_multiplier == multiplier} == set(
                SCRIPT.BLOCKS
            )
    assert SCRIPT.PERIODS == {
        "choice": ("2019-06-03", "2024-12-31"),
        "control": ("2025-01-02", "2026-10-09"),
        "full": ("2019-06-03", "2026-10-09"),
    }


@pytest.mark.parametrize("content", [None, "{}", "[]", '"text"'])
def test_missing_or_empty_hypothesis_stops_before_runner_creation(harness, content):
    if content is None:
        harness.hypothesis.unlink()
    else:
        harness.hypothesis.write_text(content, encoding="utf-8")
    with pytest.raises((ValueError, FileNotFoundError)):
        SCRIPT.run_pilot(harness.store, harness.output, harness.hypothesis)
    assert harness.events == []
    assert not harness.output.exists()


def test_existing_output_is_never_reused_or_overwritten(harness):
    harness.output.mkdir()
    marker = harness.output / "old-result.json"
    marker.write_text("immutable", encoding="utf-8")
    with pytest.raises(FileExistsError, match="immutable"):
        SCRIPT.run_pilot(harness.store, harness.output, harness.hypothesis)
    assert marker.read_text() == "immutable"
    assert harness.events == []


def test_archive_and_thirty_contracts_exist_before_first_engine_call(harness):
    SCRIPT.run_pilot(harness.store, harness.output, harness.hypothesis)
    events = harness.events
    assert events.index(("archive",)) < next(
        index for index, event in enumerate(events) if event[0] == "run"
    )
    assert sum(event[0] == "run" for event in events) == 30
    assert sum(event[0] == "save" for event in events) == 30
    frozen = json.loads((harness.output / "manifest.json").read_text())
    assert len(frozen["contracts"]) == 30
    assert frozen["candidate_count"] == 1 and frozen["control_count"] == 4
    assert frozen["data_state"] == harness.state
    assert frozen["selection"].startswith("none;")
    assert "not_out_of_sample" in frozen["historical_status"]
    expected_sha = hashlib.sha256((harness.output / "manifest.json").read_bytes()).hexdigest()
    assert (harness.output / "manifest.sha256").read_text().strip() == expected_sha
    for identity in frozen["contracts"]:
        assert identity["cash_restart"] is True
        assert identity["universe"] == list(SCRIPT.UNIVERSE)
        assert identity["data_state"] == harness.state
        assert identity["initial_cash"] == 100_000
        assert identity["schedule"] == SCRIPT.round4.MonthlyFromStart().definition()
    completed = json.loads((harness.output / "completed.json").read_text())
    assert completed["real_backtest_count"] == 30
    assert completed["manifest_sha256"] == expected_sha
    frame = pd.read_csv(harness.output / "metrics.csv")
    assert len(frame) == 30
    for job in SCRIPT.build_jobs(harness.output):
        artifacts = json.loads((job.folder / "artifacts.json").read_text())
        for filename, digest in artifacts.items():
            assert hashlib.sha256((job.folder / filename).read_bytes()).hexdigest() == digest
    with pytest.raises(FileExistsError):
        SCRIPT.run_pilot(harness.store, harness.output, harness.hypothesis)


@pytest.mark.parametrize("mutation", ["source", "data", "hypothesis"])
def test_mid_run_change_is_detected_before_saving_any_result(harness, mutation):
    def alter() -> None:
        if mutation == "source":
            harness.sources["engine.py"] = "changed"
        elif mutation == "data":
            harness.state["digest"] = "revised-price-data"
        else:
            harness.hypothesis.write_text('{"changed": true}', encoding="utf-8")

    harness.runners[1.0].on_run = alter
    with pytest.raises(ValueError, match="differs from"):
        SCRIPT.run_pilot(harness.store, harness.output, harness.hypothesis)
    assert sum(event[0] == "run" for event in harness.events) == 1
    assert not any(event[0] == "save" for event in harness.events)
    assert not (harness.output / "completed.json").exists()
    assert not SCRIPT.build_jobs(harness.output)[0].folder.exists()


def test_archive_failure_retains_manifest_and_prevents_any_engine_call(harness, monkeypatch):
    def fail_archive(*_: object) -> None:
        raise OSError("archive could not be written")

    monkeypatch.setattr(SCRIPT.round4, "archive_sources", fail_archive)
    with pytest.raises(OSError, match="archive could not"):
        SCRIPT.run_pilot(harness.store, harness.output, harness.hypothesis)
    assert (harness.output / "manifest.json").is_file()
    assert not any(event[0] == "run" for event in harness.events)
    with pytest.raises(FileExistsError):
        SCRIPT.run_pilot(harness.store, harness.output, harness.hypothesis)


def test_result_identity_mismatch_prevents_publishing(harness, monkeypatch):
    def mismatched(policy, *_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            data_state=SimpleNamespace(digest="other-data"), fingerprint=policy.fingerprint()
        )

    monkeypatch.setattr(harness.runners[1.0], "run", mismatched)
    with pytest.raises(ValueError, match="result data identity"):
        SCRIPT.run_pilot(harness.store, harness.output, harness.hypothesis)
    assert not any(event[0] == "save" for event in harness.events)
    assert not (harness.output / "completed.json").exists()


def test_cli_requires_explicit_run_and_can_be_imported_without_work(harness, monkeypatch):
    calls = []
    monkeypatch.setattr(SCRIPT, "run_pilot", lambda *args: calls.append(args))
    with pytest.raises(SystemExit):
        SCRIPT.main(["--output", str(harness.output)])
    assert calls == []
    SCRIPT.main(
        [
            "--run",
            "--store",
            str(harness.store),
            "--output",
            str(harness.output),
            "--hypothesis",
            str(harness.hypothesis),
        ]
    )
    assert calls == [(harness.store, harness.output, harness.hypothesis)]
