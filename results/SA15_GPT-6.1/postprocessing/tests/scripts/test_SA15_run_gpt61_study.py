"""The bounded SA15 study's selection and caches, without market data or backtests."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import date
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pandas as pd
import pytest

from quant_backtester.analytics.benchmark_comparison import BenchmarkAlpha
from quant_backtester.backtest.timetable import BacktestTimetable
from quant_backtester.execution.costs import CostModel
from quant_backtester.execution.model import ExecutionModel
from quant_backtester.portfolio.limits import PortfolioLimits

REPOSITORY = Path(__file__).resolve().parents[2]


def load_script() -> ModuleType:
    """Import the study's command-line module without running its entry point."""
    path = REPOSITORY / "scripts" / "SA15_run_gpt61_study.py"
    spec = importlib.util.spec_from_file_location("SA15_run_gpt61_study", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SCRIPT = load_script()


def candidate(number: object = 1, **changes: object) -> dict[str, object]:
    """Return a numbered configuration with explicit research intent."""
    return {
        "number": number,
        "reason": "Test the announced momentum allocation",
        "parameters": {},
        "schedule": "weekly",
        **changes,
    }


def write_json(path: Path, value: object) -> Path:
    """Write a small research artifact in the test's isolated directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


@pytest.mark.parametrize("number", [0, 11, -1, True, False, 1.0, "1", None])
def test_candidate_number_must_be_an_integer_between_one_and_ten(tmp_path, number) -> None:
    path = write_json(tmp_path / "candidate.json", candidate(number))
    with pytest.raises(ValueError, match="integer from 1 to 10"):
        SCRIPT.read_candidate(path)


@pytest.mark.parametrize("number", [1, 10])
def test_both_announced_trial_boundaries_are_accepted(tmp_path, number) -> None:
    path = write_json(tmp_path / "candidate.json", candidate(number))
    spec, strategy = SCRIPT.read_candidate(path)
    assert spec["number"] == number
    assert strategy.strategy_id == "SA15_GPT-6.1"


@pytest.mark.parametrize("changes", [{"schedule": "hourly"}, {"reason": " \n\t"}])
def test_a_candidate_needs_an_executable_schedule_and_written_reason(tmp_path, changes) -> None:
    path = write_json(tmp_path / "candidate.json", candidate(**changes))
    with pytest.raises(ValueError, match="valid schedule and a written reason"):
        SCRIPT.read_candidate(path)


def test_selection_score_penalizes_drawdown_and_instability_before_final() -> None:
    development = {"cagr": 0.20, "max_drawdown": -0.20}
    validation = {"cagr": 0.10, "max_drawdown": -0.10}
    assert SCRIPT.selection_score(development, validation) == pytest.approx(0.1025)
    worse_drawdown = {**validation, "max_drawdown": -0.30}
    assert SCRIPT.selection_score(development, worse_drawdown) < SCRIPT.selection_score(
        development, validation
    )
    stable = {"cagr": 0.15, "max_drawdown": -0.15}
    assert SCRIPT.selection_score(stable, stable) > SCRIPT.selection_score(development, validation)


def test_final_results_cannot_break_a_selection_tie_and_freeze_precedes_reading(
    tmp_path, monkeypatch
) -> None:
    output = tmp_path / "study"
    for number, final_cagr in ((1, -0.90), (2, 9.0)):
        folder = output / f"trial_{number:02d}"
        write_json(folder / "candidate.json", candidate(number))
        write_json(folder / "selection.json", {"score": 0.12, "metrics": {}})
        write_json(folder / "final/metrics.json", {"cagr": final_cagr})

    events = []

    def archive_before_selection(destination, _store) -> None:
        assert not (destination / "selected.json").exists()
        events.append("archived")

    monkeypatch.setattr(SCRIPT, "archive_sources", archive_before_selection)

    class FinalPeriodReached(Exception):
        """Stop at the first final-period read, before a runner is called."""

    def read_final(_runner, _strategy, period, destination) -> None:
        assert period == "final"
        assert events == ["archived"]
        selected = json.loads((destination / "selected.json").read_text())
        assert selected["candidate"]["number"] == 1
        assert selected["selection_uses"] == ["development", "validation"]
        assert selected["trials"] == 2
        raise FinalPeriodReached

    monkeypatch.setattr(SCRIPT, "run_references", read_final)
    with pytest.raises(FinalPeriodReached):
        SCRIPT.finalise(object(), output, tmp_path / "unused_store")


def test_frozen_selection_refuses_a_new_trial_before_reading_its_config(tmp_path) -> None:
    write_json(tmp_path / "selected.json", {"candidate": candidate()})
    with pytest.raises(ValueError, match="selection is already frozen"):
        SCRIPT.iterate(tmp_path / "absent_config.json", object(), tmp_path)


def test_frozen_selection_cannot_be_finalized_again(tmp_path) -> None:
    write_json(tmp_path / "selected.json", {"candidate": candidate()})
    with pytest.raises(FileExistsError, match="final selection already exists"):
        SCRIPT.finalise(object(), tmp_path, tmp_path / "unused_store")


def test_an_existing_trial_is_never_overwritten(tmp_path) -> None:
    config = write_json(tmp_path / "candidate.json", candidate())
    previous = {"reason": "Original evidence must be retained"}
    saved = write_json(tmp_path / "trial_01/candidate.json", previous)
    with pytest.raises(FileExistsError, match="will not be overwritten"):
        SCRIPT.iterate(config, object(), tmp_path)
    assert json.loads(saved.read_text()) == previous


def test_universe_includes_a_separate_core_and_all_comparison_instruments() -> None:
    allocation = SCRIPT.SA15GPT61(risky_ids=("TACTICAL",), core_id="CORE", core_fraction=0.25)
    names = SCRIPT.universe(allocation)
    assert set(names) == {
        "TACTICAL",
        "CORE",
        allocation.monetary_id,
        "ETF_WORLD",
        "ETF_SP500_PEA",
    }
    assert len(names) == len(set(names))


@pytest.fixture
def reference_runner():
    """Expose conditions and a mutable data digest; refuse every attempted run."""
    state = SimpleNamespace(digest="snapshot_a")

    @contextmanager
    def pinned() -> Iterator[SimpleNamespace]:
        yield state

    def refuse_run(*_args: object, **_kwargs: object) -> None:
        pytest.fail("cache tests must never execute a backtest")

    return SimpleNamespace(
        reader=SimpleNamespace(pinned=pinned),
        execution=ExecutionModel(costs=CostModel(commission_rate=0.0005)),
        initial_cash=100_000.0,
        base_currency="EUR",
        reference_calendar_id="XPAR",
        timetable=BacktestTimetable(),
        analytics=SCRIPT.ANALYTICS,
        limits=PortfolioLimits(),
        state=state,
        run=refuse_run,
    )


def legacy_references(output: Path, runner, strategy) -> Path:
    """Write the complete metadata of four unsigned, already completed references."""
    period = "development"
    signature = SCRIPT.reference_signature(runner, strategy, period)
    books = {
        "World_buy_hold": SCRIPT.BuyAndHold(instruments=("ETF_WORLD",)),
        "SA1_MA20": SCRIPT.WorldMA20Benchmark(),
        "SP500_buy_hold": SCRIPT.BuyAndHold(instruments=("ETF_SP500_PEA",)),
        "equal_weight": SCRIPT.EqualWeightRebalance(instruments=strategy.risky_ids),
    }
    for name, book in books.items():
        folder = output / "references" / period / name
        schedule = SCRIPT.Weekly() if name == "equal_weight" else SCRIPT.EverySession()
        configuration = {
            "requested_start": signature["period"][0],
            "requested_end": signature["period"][1],
            "data_state": signature["data_state"],
            "execution": signature["execution"],
            "initial_cash": signature["initial_cash"],
            "base_currency": signature["base_currency"],
            "reference_calendar": signature["reference_calendar"],
            "timetable": signature["timetable"],
            "analytics": signature["analytics"],
            "schedule": schedule.definition(),
            "portfolio": {"limits": signature["limits"]},
            "universe": {"type": "StaticUniverse", "members": signature["universe"]},
        }
        write_json(folder / "configuration.json", configuration)
        write_json(folder / "identity.json", {"data_state": {"digest": signature["data_state"]}})
        write_json(folder / "strategy.json", SCRIPT.plain_configuration(book.definition()))
        write_json(folder / "metrics.json", {"cagr": 0.10})
    return output / "references" / period / "World_buy_hold"


def test_matching_legacy_references_are_verified_signed_and_reused(
    tmp_path, reference_runner
) -> None:
    strategy = SCRIPT.SA15GPT61()
    folder = legacy_references(tmp_path, reference_runner, strategy)
    result = SCRIPT.run_references(reference_runner, strategy, "development", tmp_path)
    assert len(result) == 4
    cache = json.loads((folder / "cache.json").read_text())
    assert cache["signature"]["data_state"] == "snapshot_a"
    assert "not original execution" in cache["legacy_migration"]
    assert SCRIPT.run_references(reference_runner, strategy, "development", tmp_path) == result


@pytest.mark.parametrize("change", ["data", "costs", "cash", "universe", "sources"])
def test_signed_cache_refuses_changed_conditions(
    tmp_path, reference_runner, monkeypatch, change
) -> None:
    strategy = SCRIPT.SA15GPT61()
    legacy_references(tmp_path, reference_runner, strategy)
    SCRIPT.run_references(reference_runner, strategy, "development", tmp_path)
    if change == "data":
        reference_runner.state.digest = "snapshot_b"
    elif change == "costs":
        reference_runner.execution = replace(
            reference_runner.execution, costs=CostModel(commission_rate=0.001)
        )
    elif change == "cash":
        reference_runner.initial_cash = 200_000.0
    elif change == "universe":
        strategy = replace(strategy, risky_ids=strategy.risky_ids[:-1])
    else:
        signature = SCRIPT.reference_signature(reference_runner, strategy, "development")
        signature["baseline_sources"] = {"changed.py": "different"}
        monkeypatch.setattr(SCRIPT, "reference_signature", lambda *_args: signature)
    with pytest.raises(ValueError, match="reference cache conditions differ"):
        SCRIPT.run_references(reference_runner, strategy, "development", tmp_path)


@pytest.mark.parametrize("artifact", ["configuration.json", "identity.json", "strategy.json"])
def test_legacy_migration_refuses_mismatched_archived_evidence(
    tmp_path, reference_runner, artifact
) -> None:
    strategy = SCRIPT.SA15GPT61()
    folder = legacy_references(tmp_path, reference_runner, strategy)
    path = folder / artifact
    content = json.loads(path.read_text())
    if artifact == "configuration.json":
        content["initial_cash"] = 500_000.0
    elif artifact == "identity.json":
        content["data_state"]["digest"] = "other_snapshot"
    else:
        content["strategy_id"] = "different_book"
    write_json(path, content)
    with pytest.raises(ValueError, match="legacy reference conditions differ"):
        SCRIPT.run_references(reference_runner, strategy, "development", tmp_path)
    assert not (folder / "cache.json").exists()


def test_source_archive_is_deterministic_and_excludes_market_data(tmp_path, monkeypatch) -> None:
    root = tmp_path / "project"
    store = tmp_path / "store"
    files = {
        "src/package/strategy.py": b"VALUE = 1\n",
        "src/package/not_source.txt": b"exclude",
        "scripts/SA15_run.py": b"print('source')\n",
        "scripts/unrelated.py": b"exclude",
        "pyproject.toml": b"[project]\nname = 'archive-test'\n",
        "uv.lock": b"version = 1\n",
        "research/SA15_GPT-6.1/protocol.md": b"Frozen protocol\n",
        "research/SA15_GPT-6.1/nested/candidate.json": b"{}\n",
        "research/SA15_GPT-6.1/image.png": b"\x89PNG\r\n\x1a\n",
        "research/SA15_GPT-6.1/binary.dat": b"text\x00binary",
        "research/another-study.md": b"exclude",
    }
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    metadata = store / "metadata/instruments.toml"
    metadata.parent.mkdir(parents=True)
    metadata.write_bytes(b"[instruments]\n")
    for tree in ("raw", "clean", "checked", "reports"):
        path = store / tree / "private_market_data.parquet"
        path.parent.mkdir()
        path.write_bytes(b"market data must never enter the source archive")
    monkeypatch.setattr(SCRIPT, "ROOT", root)
    first, second = tmp_path / "first", tmp_path / "second"
    SCRIPT.archive_sources(first, store)
    for name in files:
        (root / name).touch()
    SCRIPT.archive_sources(second, store)
    archive_bytes = (first / "source/source.zip").read_bytes()
    assert archive_bytes == (second / "source/source.zip").read_bytes()
    manifest = json.loads((first / "source/manifest.json").read_text())
    assert manifest == json.loads((second / "source/manifest.json").read_text())
    assert manifest["archive_sha256"] == hashlib.sha256(archive_bytes).hexdigest()
    expected = {
        "src/package/strategy.py",
        "scripts/SA15_run.py",
        "pyproject.toml",
        "uv.lock",
        "research/SA15_GPT-6.1/protocol.md",
        "research/SA15_GPT-6.1/nested/candidate.json",
        "store/metadata/instruments.toml",
    }
    with zipfile.ZipFile(first / "source/source.zip") as archive:
        assert set(archive.namelist()) == expected == set(manifest["files"])
        assert archive.namelist() == sorted(expected)
        for item in archive.infolist():
            content = archive.read(item.filename)
            assert item.date_time == (1980, 1, 1, 0, 0, 0)
            assert manifest["files"][item.filename] == {
                "sha256": hashlib.sha256(content).hexdigest(),
                "bytes": len(content),
            }


@pytest.mark.parametrize("period", ["validation", "full"])
def test_render_converts_only_analytics_copies_to_python_dates(
    tmp_path, monkeypatch, period
) -> None:
    strategy_curve = pd.Series(
        [100_000.0, 100_200.0, 100_100.0, 101_000.0],
        index=pd.date_range("2024-12-27", periods=4, freq="B", name="session_date"),
        name="net_equity",
    )
    curves = {}
    folders = [
        tmp_path / "full/SA15_GPT-6.1" if period == "full" else tmp_path / "trial_01" / period
    ] + [
        tmp_path / "full" / name if period == "full" else tmp_path / "references" / period / name
        for name in ("World_buy_hold", "SA1_MA20", "SP500_buy_hold", "equal_weight")
    ]
    for index, folder in enumerate(folders):
        write_json(folder / "metrics.json", {"net_return": 0.01})
        curve = strategy_curve.copy()
        curve.iloc[1:] += index * pd.Series([30.0, -10.0, 20.0]).to_numpy()
        curves[folder / "equity.csv"] = curve
    original = {path: curve.copy() for path, curve in curves.items()}
    monkeypatch.setattr(SCRIPT, "load_equity", lambda path: curves[path])
    actual_alpha = SCRIPT.alpha_vs_benchmark
    calls = []

    def checked_alpha(left, right, config) -> BenchmarkAlpha:
        assert all(type(day) is date for day in left.index)
        assert all(type(day) is date for day in right.index)
        calls.append((left.copy(), right.copy()))
        return actual_alpha(left, right, config)

    monkeypatch.setattr(SCRIPT, "alpha_vs_benchmark", checked_alpha)
    SCRIPT.render_comparison(tmp_path, period, 1)
    assert len(calls) == 5
    for path, curve in curves.items():
        pd.testing.assert_series_equal(curve, original[path])
        assert isinstance(curve.index, pd.DatetimeIndex)
    yearly = pd.read_csv(tmp_path / "comparison" / period / "yearly.csv")
    assert list(yearly["year"]) == [2024, 2025]
    assert (tmp_path / "comparison" / period / "comparison.png").is_file()


def frozen_saved_selection(output: Path) -> tuple[dict, object]:
    """Write a frozen candidate and final definition, without any market runs."""
    spec = candidate()
    strategy = SCRIPT.SA15GPT61()
    selected = {
        "candidate": spec,
        "candidate_fingerprint": strategy.fingerprint(),
        "selection_uses": ["development", "validation"],
        "trials": 1,
    }
    write_json(output / "selected.json", selected)
    write_json(output / "trial_01/candidate.json", spec)
    write_json(
        output / "final/SA15_GPT-6.1/strategy.json",
        SCRIPT.plain_configuration(strategy.definition()),
    )
    return selected, strategy


@pytest.mark.parametrize("include_full", [False, True])
def test_render_only_cli_reads_saved_runs_without_runner_or_reselection(
    tmp_path, monkeypatch, include_full
) -> None:
    frozen_saved_selection(tmp_path)
    if include_full:
        write_json(tmp_path / "full/SA15_GPT-6.1/metrics.json", {})
    before = (tmp_path / "selected.json").read_bytes()
    calls = []

    def forbidden(*_args: object, **_kwargs: object) -> None:
        pytest.fail("render-only must not select, construct a runner, archive, or backtest")

    for name in (
        "build_runner",
        "iterate",
        "finalise",
        "update_trials",
        "run_references",
        "archive_sources",
    ):
        monkeypatch.setattr(SCRIPT, name, forbidden)

    def render(output, period, trial) -> None:
        calls.append((period, trial))
        folder = output / "comparison" / period
        folder.mkdir(parents=True)
        pd.DataFrame(
            {
                "SA15_GPT-6.1": [100_000.0, 100_100.0, 99_900.0],
                "World_buy_hold": [100_000.0, 100_300.0, 100_400.0],
            },
            index=pd.date_range("2025-01-02", periods=3),
        ).to_csv(folder / "equity.csv", index_label="session_date")
        pd.DataFrame({"book": ["SA15_GPT-6.1"], "net_return": [-0.001]}).to_csv(
            folder / "summary.csv", index=False
        )

    monkeypatch.setattr(SCRIPT, "render_comparison", render)
    monkeypatch.setattr(
        sys,
        "argv",
        ["SA15_run_gpt61_study.py", "--render-only", "--output", str(tmp_path)],
    )
    SCRIPT.main()
    expected_periods = [*SCRIPT.PERIODS, *(["full"] if include_full else [])]
    assert calls == [(period, 1) for period in expected_periods]
    assert (tmp_path / "selected.json").read_bytes() == before
    assert (tmp_path / "final/uncertainty.json").is_file()


def test_render_only_requires_an_existing_frozen_selection(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match=r"requires an existing frozen selected\.json"):
        SCRIPT.render_saved(tmp_path)


@pytest.mark.parametrize("mismatch", ["fingerprint", "candidate", "final_definition"])
def test_render_only_refuses_changed_selection_before_rendering(
    tmp_path, monkeypatch, mismatch
) -> None:
    selected, _strategy = frozen_saved_selection(tmp_path)
    if mismatch == "fingerprint":
        selected["candidate_fingerprint"] = "other"
        write_json(tmp_path / "selected.json", selected)
    elif mismatch == "candidate":
        write_json(tmp_path / "trial_01/candidate.json", candidate(reason="changed"))
    else:
        write_json(tmp_path / "final/SA15_GPT-6.1/strategy.json", {})

    def forbidden(*_args: object, **_kwargs: object) -> None:
        pytest.fail("a changed frozen selection cannot render")

    monkeypatch.setattr(SCRIPT, "render_comparison", forbidden)
    with pytest.raises(ValueError, match="differs from the frozen selection"):
        SCRIPT.render_saved(tmp_path)
