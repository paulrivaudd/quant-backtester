"""Offline checks for the pre-final, descriptive R4 companion protocol.

No test runs the backtest engine or opens a market-data store. Synthetic rankings
verify the independent extrema, ties and deduplication; corrupt evidence stops
all replay before any result can be read.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pandas as pd
import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def load_script() -> ModuleType:
    """Import the optional CLI without invoking either phase."""
    spec = importlib.util.spec_from_file_location(
        "SA15_diagnostics_gpt61_round4", SCRIPTS / "SA15_diagnostics_gpt61_round4.py"
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


def trials() -> pd.DataFrame:
    """Describe a main winner and two distinct qualified preference extrema."""
    rows = [
        {
            "trial": 31,
            "qualified": True,
            "score": 0.10,
            "trade_days_per_year": 2.0,
            "drawdown_depth": 0.20,
        },
        {
            "trial": 32,
            "qualified": True,
            "score": 0.09,
            "trade_days_per_year": 0.5,
            "drawdown_depth": 0.22,
        },
        {
            "trial": 33,
            "qualified": True,
            "score": 0.08,
            "trade_days_per_year": 1.0,
            "drawdown_depth": 0.15,
        },
    ]
    rows.extend(
        {
            "trial": number,
            "qualified": False,
            "score": 100.0,
            "trade_days_per_year": 0.01,
            "drawdown_depth": 0.01,
        }
        for number in range(34, 81)
    )
    return pd.DataFrame(rows)


def write(path: Path, value: object) -> Path:
    """Create isolated JSON evidence."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


@pytest.fixture
def evidence(tmp_path, monkeypatch):
    """Inject fifty verified choice rows and prohibit all engine/data calls."""
    frame = trials()
    for number in range(31, 81):
        folder = tmp_path / f"trial_{number:02d}"
        write(folder / "candidate.json", {"number": number, "schedule": "monthly"})
        write(folder / "selection.json", {"choice_score": number})

    def read_spec(path) -> tuple[dict[str, object], SimpleNamespace]:
        candidate = json.loads(path.read_text())
        policy = SimpleNamespace(fingerprint=lambda: f"fingerprint-{candidate['number']}")
        return candidate, policy

    monkeypatch.setattr(SCRIPT.study, "verified_trials", lambda *_: frame)
    monkeypatch.setattr(SCRIPT.study, "read_spec", read_spec)
    monkeypatch.setattr(SCRIPT.study, "freeze_driver", lambda *_: "driver-fixed")
    monkeypatch.setattr(SCRIPT.study, "source_finance_hashes", lambda **_: {"finance.py": "fixed"})
    monkeypatch.setattr(SCRIPT, "diagnostics_source_sha256", lambda: "diagnostic-fixed")
    monkeypatch.setattr(SCRIPT.study, "build_runner", lambda *_: pytest.fail("no market store"))
    monkeypatch.setattr(SCRIPT.study, "run_cached", lambda *_a, **_k: pytest.fail("no replay"))
    monkeypatch.setattr(
        SCRIPT.study, "run_references", lambda *_a, **_k: pytest.fail("no final read")
    )
    return tmp_path, frame


def test_extrema_are_independent_and_unqualified_high_scores_cannot_enter():
    ranked = SCRIPT.rank_companions(trials())
    assert ranked == {
        "expected_winner": 31,
        "criterion_winners": {"minimum_interventions": 32, "minimum_drawdown": 33},
        "companions": [32, 33],
        "qualified_count": 3,
    }


def test_independent_criteria_deduplicate_and_never_force_an_alternative():
    frame = trials()
    frame.loc[frame.trial == 32, "drawdown_depth"] = 0.10
    assert SCRIPT.rank_companions(frame)["companions"] == [32]
    frame.loc[frame.trial == 31, ["drawdown_depth", "trade_days_per_year"]] = [0.05, 0.1]
    assert SCRIPT.rank_companions(frame)["companions"] == []


def test_ties_use_score_then_first_number_before_deduplication():
    frame = trials()
    frame.loc[frame.trial.isin([32, 33]), ["drawdown_depth", "trade_days_per_year"]] = [0.10, 0.5]
    assert SCRIPT.rank_companions(frame)["companions"] == [32]
    frame.loc[frame.trial == 33, "score"] = 0.09
    assert SCRIPT.rank_companions(frame)["companions"] == [32]
    frame.loc[frame.trial == 33, "score"] = 0.095
    assert SCRIPT.rank_companions(frame)["companions"] == [33]


def test_no_qualified_candidates_means_no_descriptive_companion():
    frame = trials()
    frame["qualified"] = False
    ranked = SCRIPT.rank_companions(frame)
    assert ranked["qualified_count"] == 0
    assert ranked["companions"] == []
    assert ranked["criterion_winners"] == {"minimum_interventions": None, "minimum_drawdown": None}


@pytest.mark.parametrize("change", ["nan", "negative_activity", "duplicate", "bad_boolean"])
def test_invalid_choice_scores_are_refused(change):
    frame = trials()
    if change == "nan":
        frame.loc[0, "score"] = float("nan")
    elif change == "negative_activity":
        frame.loc[0, "trade_days_per_year"] = -1
    elif change == "duplicate":
        frame.loc[1, "trial"] = 31
    else:
        frame = frame.astype({"qualified": "object"})
        frame.loc[0, "qualified"] = "True"
    with pytest.raises(ValueError):
        SCRIPT.rank_companions(frame)


def test_freeze_uses_only_fifty_choice_rows_and_leaves_main_selection_absent(evidence):
    output, _frame = evidence
    SCRIPT.freeze_companions(object(), output)
    saved = SCRIPT.frozen_companions(output)
    assert saved["ranking"]["companions"] == [32, 33]
    assert saved["expected_winner"]["number"] == 31
    assert [item["number"] for item in saved["companions"]] == [32, 33]
    assert saved["companions"][0]["criteria"] == ["minimum_interventions"]
    assert saved["companions"][1]["criteria"] == ["minimum_drawdown"]
    assert len(saved["trial_scores"]) == 50
    assert not (output / "selected.json").exists()
    assert not (output / "final").exists()
    assert (output / SCRIPT.CHECKSUM).read_text().strip() == hashlib.sha256(
        (output / SCRIPT.MANIFEST).read_bytes()
    ).hexdigest()


def test_incomplete_series_and_late_freeze_are_refused(evidence, monkeypatch):
    output, frame = evidence
    monkeypatch.setattr(SCRIPT.study, "verified_trials", lambda *_: frame.iloc[:-1])
    with pytest.raises(ValueError, match="all fifty"):
        SCRIPT.freeze_companions(object(), output)
    write(output / "selected.json", {"retained": True})
    with pytest.raises(ValueError, match="before the main"):
        SCRIPT.freeze_companions(object(), output)
    assert not (output / SCRIPT.MANIFEST).exists()


def test_frozen_description_cannot_be_overwritten(evidence):
    output, _frame = evidence
    SCRIPT.freeze_companions(object(), output)
    before = (output / SCRIPT.MANIFEST).read_bytes()
    with pytest.raises(FileExistsError):
        SCRIPT.freeze_companions(object(), output)
    assert (output / SCRIPT.MANIFEST).read_bytes() == before


@pytest.mark.parametrize("change", ["manifest", "candidate", "selection", "source", "finance"])
def test_corruption_is_rejected_before_any_replay(evidence, monkeypatch, change):
    output, _frame = evidence
    SCRIPT.freeze_companions(object(), output)
    if change == "manifest":
        saved = json.loads((output / SCRIPT.MANIFEST).read_text())
        saved["companions"][0]["number"] = 80
        write(output / SCRIPT.MANIFEST, saved)
    elif change == "candidate":
        write(output / "trial_32/candidate.json", {"number": 32, "schedule": "quarterly"})
    elif change == "selection":
        write(output / "trial_32/selection.json", {"choice_score": 9999})
    elif change == "source":
        monkeypatch.setattr(SCRIPT, "diagnostics_source_sha256", lambda: "edited")
    else:
        monkeypatch.setattr(
            SCRIPT.study, "source_finance_hashes", lambda **_: {"finance.py": "edited"}
        )
    with pytest.raises(ValueError):
        SCRIPT.run_companions(output=output)


def announce_main_winner(output, monkeypatch, number=31):
    """Stand in for the independently frozen R4 main winner."""
    write(output / "selected.json", {"candidate": {"number": number}, "retained": "verbatim"})
    write(output / "selected.sha256", {"independent": "retained"})
    monkeypatch.setattr(
        SCRIPT.study,
        "frozen_winner",
        lambda *_: (
            {"number": number},
            SimpleNamespace(fingerprint=lambda: f"fingerprint-{number}"),
        ),
    )


def test_eight_existing_policy_replays_have_exact_dates_costs_and_paths(evidence, monkeypatch):
    output, _frame = evidence
    SCRIPT.freeze_companions(object(), output)
    announce_main_winner(output, monkeypatch)
    jobs = SCRIPT.build_jobs(output)
    assert len(jobs) == 8
    assert {job.number for job in jobs} == {32, 33}
    assert {(job.period, job.multiplier) for job in jobs} == {
        ("full", 1.0),
        ("full", 2.0),
        ("final", 1.0),
        ("final", 2.0),
    }
    assert {job.folder.name for job in jobs} == {"full", "full_costs_x2", "final", "final_costs_x2"}
    assert all(job.candidate == output / f"trial_{job.number:02d}/candidate.json" for job in jobs)


def test_main_winner_cannot_be_replaced_by_a_companion(evidence, monkeypatch):
    output, _frame = evidence
    SCRIPT.freeze_companions(object(), output)
    announce_main_winner(output, monkeypatch, number=32)
    before = (output / "selected.json").read_bytes()
    with pytest.raises(ValueError, match="cannot replace"):
        SCRIPT.build_jobs(output)
    assert (output / "selected.json").read_bytes() == before


def test_running_descriptive_jobs_preserves_every_choice_and_main_selection(evidence, monkeypatch):
    output, _frame = evidence
    SCRIPT.freeze_companions(object(), output)
    announce_main_winner(output, monkeypatch)
    selection_paths = [output / "selected.json", output / "selected.sha256"]
    selection_paths.extend(output.glob("trial_*/selection.json"))
    selection_paths.extend(output.glob("trial_*/candidate.json"))
    selection_paths.extend([output / SCRIPT.MANIFEST, output / SCRIPT.CHECKSUM])
    before = {path: path.read_bytes() for path in selection_paths}
    calls = []
    monkeypatch.setattr(SCRIPT.study, "build_runner", lambda _store, multiplier: multiplier)

    def replay(runner, policy, schedule, start, end, folder, **kwargs: object) -> dict[str, float]:
        assert kwargs == {"candidate": True}
        calls.append((runner, policy.fingerprint(), start, end, folder))
        return {"cagr": 0.10, "max_drawdown": -0.20, "trade_days_per_year": 1.0}

    monkeypatch.setattr(SCRIPT.study, "run_cached", replay)
    SCRIPT.run_companions(output=output)
    assert len(calls) == 8
    assert {(start, end) for _cost, _fp, start, end, _folder in calls} == {
        SCRIPT.study.PERIODS["full"],
        SCRIPT.study.PERIODS["final"],
    }
    assert {path: path.read_bytes() for path in selection_paths} == before
    assert len(pd.read_csv(output / "companions/summary.csv")) == 8
    assert len(list(output.glob("trial_*"))) == 50


@pytest.mark.parametrize("arguments", [[], ["--freeze-companions", "--run"]])
def test_cli_requires_exactly_one_phase(arguments):
    with pytest.raises(SystemExit) as error:
        SCRIPT.parse_arguments(arguments)
    assert error.value.code == 2
