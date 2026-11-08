"""Tests of the SA17 executable study runner: its frozen checks and its reading rules."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from dataclasses import replace
from datetime import date
from pathlib import Path
from unittest.mock import Mock

import pytest

from quant_backtester.backtest.schedule import EverySession, ListedSessions, Weekly
from quant_backtester.data.calendars import CalendarRegistry
from quant_backtester.provenance import SourceState
from quant_backtester.strategies.SA17_sector_residual_momentum import (
    SA17SectorResidualMomentum,
    SectorRanking,
)
from scripts import SA17_run_study as study_run

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def study() -> dict:
    return study_run.load_study()


@pytest.fixture
def study_calendars(tmp_path: Path) -> CalendarRegistry:
    """Return the store's calendars: the venues and SA17's two study calendars."""
    folder = tmp_path / "calendars"
    shutil.copytree(ROOT / "market_data" / "metadata" / "calendars", folder)
    for name in ("XNYS_XLON", "XLON"):
        shutil.copy2(ROOT / "research" / "SA17" / "calendars" / f"{name}.toml", folder)
    return CalendarRegistry.from_directory(folder)


def test_the_schedule_is_the_frozen_one(study, study_calendars) -> None:
    schedule = study_run.checked_schedule(study, study_calendars)
    assert isinstance(schedule, ListedSessions)
    assert len(schedule.dates) == 99
    assert schedule.dates[0] == date(2018, 8, 1)
    assert schedule.dates[-1] == date(2026, 10, 1)
    assert date(2021, 5, 4) in schedule.dates


def test_a_schedule_the_calendars_do_not_give_is_refused(study, study_calendars) -> None:
    altered = dict(study)
    altered["schedule"] = dict(study["schedule"])
    decisions = [list(row) for row in study["schedule"]["decisions"]]
    decisions[33][2] = date(2021, 5, 3)  # May 2021: the first Paris session, before the release
    altered["schedule"]["decisions"] = decisions
    with pytest.raises(ValueError, match="frozen schedule"):
        study_run.checked_schedule(altered, study_calendars)


def test_every_traded_fund_has_its_own_cost_model_and_x2_doubles_every_term(study) -> None:
    once = study_run.cost_models(study, 1.0)
    twice = study_run.cost_models(study, 2.0)
    assert set(once) == set(study_run.universe_of(study))
    assert once["ETF_NASDAQ"].half_spread_rate == pytest.approx(0.0005)
    assert once["SA17_ETF_TECHNOLOGY"].half_spread_rate == pytest.approx(0.0015)
    for name, model in once.items():
        doubled = twice[name]
        assert doubled.commission_rate == pytest.approx(2 * model.commission_rate)
        assert doubled.minimum_commission == pytest.approx(2 * model.minimum_commission)
        assert doubled.half_spread_rate == pytest.approx(2 * model.half_spread_rate)
        assert doubled.slippage_rate == pytest.approx(2 * model.slippage_rate)
    with pytest.raises(ValueError, match="declared cost level"):
        study_run.cost_models(study, 3.0)


def test_the_books_are_the_frozen_ones(study) -> None:
    schedule = ListedSessions((date(2018, 8, 1),), rule="test")
    books = study_run.books_of(study, schedule)
    assert [book.name for book in books] == [
        "SA17_sector_residual_momentum",
        "total_momentum",
        "no_volatility_target",
        "equal_sectors",
        "equal_sectors_volatility_target",
        "SA16_it2",
        "Nasdaq_buy_hold",
        "SA16_it2_C1_constant_two_thirds",
    ]
    candidate = books[0].strategy
    assert isinstance(candidate, SA17SectorResidualMomentum)
    assert candidate.ranking is SectorRanking.RESIDUAL
    assert candidate.annualization == 247
    assert candidate.observation_calendar_id == "XNYS_XLON"
    assert candidate.usd_per_eur_fx_id == "SA17_FX_EURUSD_US_CLOSE"
    assert candidate.risk_input_ids == candidate.signal_input_ids
    assert all(book.schedule is schedule for book in books[:5])
    assert isinstance(books[5].schedule, Weekly)
    assert isinstance(books[6].schedule, EverySession)
    assert [book.role for book in books] == [
        "candidate",
        *["control"] * 4,
        "reference",
        "reference",
        "descriptive",
    ]


def test_a_run_signature_changes_with_costs_data_and_schedule(study) -> None:
    schedule = ListedSessions((date(2018, 8, 1),), rule="test")
    book = study_run.books_of(study, schedule)[0]
    provenance = ("content-a", {"numpy": "test"})
    base = study_run.signature(book, study, 1.0, "digest", *provenance)
    assert study_run.signature(book, study, 1.0, "digest", *provenance) == base
    assert study_run.signature(book, study, 2.0, "digest", *provenance) != base
    assert study_run.signature(book, study, 1.0, "other", *provenance) != base
    moved = replace(book, schedule=ListedSessions((date(2018, 8, 2),), rule="test"))
    assert study_run.signature(moved, study, 1.0, "digest", *provenance) != base


def metrics(cagr: float, sharpe: float, drawdown: float) -> dict[str, float]:
    return {"cagr": cagr, "sharpe": sharpe, "max_drawdown": drawdown}


def test_cache_identity_covers_code_and_installed_environment(study) -> None:
    book = study_run.books_of(study, ListedSessions((date(2018, 8, 1),), rule="test"))[0]
    source = "content-a"
    environment = {"numpy": "1", "lockfile_sha256": "lock-a"}
    key = study_run.signature(book, study, 1.0, "digest", source, environment)
    assert study_run.signature(book, study, 1.0, "digest", "content-b", environment) != key
    for change in ({"numpy": "2"}, {"lockfile_sha256": "lock-b"}):
        assert study_run.signature(book, study, 1.0, "digest", source, environment | change) != key


@pytest.mark.parametrize(
    "fault", ["valid", "no_marker", "missing", "changed", "identity", "environment"]
)
def test_run_book_refuses_incomplete_or_changed_cache(study, tmp_path, monkeypatch, fault) -> None:
    book = study_run.books_of(study, ListedSessions((date(2018, 8, 1),), rule="test"))[0]
    source = "content-a"
    monkeypatch.setattr(study_run, "environment_state", lambda _: {"numpy": "1"})
    key = study_run.signature(book, study, 1.0, "digest", source, {"numpy": "1"})
    folder = tmp_path / f"{book.name}_x1"
    folder.mkdir()
    for name in study_run.RUN_ARTIFACTS:
        (folder / name).write_text(json.dumps({"signature": key}))
    hashes = {
        name: hashlib.sha256((folder / name).read_bytes()).hexdigest()
        for name in study_run.RUN_ARTIFACTS
    }
    if fault != "no_marker":
        study_run.write_json(folder / "complete.json", {"signature": key, "sha256": hashes})
    if fault == "missing":
        (folder / "equity.csv").unlink()
    elif fault == "changed":
        (folder / "fills.csv").write_text("changed")
    elif fault == "identity":
        source = "content-b"
    elif fault == "environment":
        monkeypatch.setattr(study_run, "environment_state", lambda _: {"numpy": "2"})
    runner = Mock(spec=StrategyRunner)
    environment = {"numpy": "2" if fault == "environment" else "1"}
    if fault == "valid":
        assert study_run.run_book(
            book, study, runner, 1.0, "digest", tmp_path, source, environment
        ) == {"signature": key}
        return
    # No run method: a rejected cache must not trigger an implicit replacement run.
    expected_error = OSError if fault in ("no_marker", "missing") else FileExistsError
    with pytest.raises(expected_error):
        study_run.run_book(book, study, runner, 1.0, "digest", tmp_path, source, environment)


def test_interrupted_save_does_not_publish_a_run(tmp_path, monkeypatch) -> None:
    folder = tmp_path / "book"

    def interrupted(staged: Path, *args: object) -> None:
        (staged / "metrics.json").write_text("partial output")
        raise OSError("simulated interruption")

    monkeypatch.setattr(study_run, "_write_run", interrupted)
    with pytest.raises(OSError, match="simulated interruption"):
        study_run.save_run(
            folder,
            Mock(spec=StrategyResult),
            Mock(spec=study_run.BookSpec),
            "key",
            Mock(spec=AnalyticsConfig),
            {},
            {},
        )
    assert folder.is_dir()
    assert not (folder / "complete.json").exists()


def test_save_preserves_existing_output(tmp_path) -> None:
    folder = tmp_path / "book"
    folder.mkdir()
    artifact = folder / "metrics.json"
    artifact.write_text("existing output")
    with pytest.raises(FileExistsError, match="already exists"):
        study_run.save_run(
            folder,
            Mock(spec=StrategyResult),
            Mock(spec=study_run.BookSpec),
            "key",
            Mock(spec=AnalyticsConfig),
            {},
            {},
        )
    assert artifact.read_text() == "existing output"


def test_content_identity_survives_reports_and_docs_commits(study, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(study_run, "ROOT", tmp_path)
    for path in study_run.producing_files(study):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("input")
    code = tmp_path / "src/quant_backtester/example.py"
    code.parent.mkdir(parents=True)
    code.write_text("x = 1")

    def git(*args: str) -> None:
        subprocess.run(
            [
                "git",
                "-C",
                str(tmp_path),
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.test",
                *args,
            ],
            check=True,
            capture_output=True,
        )

    git("init", "-q")
    git("add", ".")
    git("commit", "-qm", "inputs")
    inputs = study_run.producing_files(study)
    original = study_run.producing_digest(inputs)
    output = tmp_path / "results/SA17/executable"
    report = tmp_path / "results/SA17/study.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("generated report")
    assert study_run.checked_source(output, report, inputs).dirty
    git("add", ".")
    git("commit", "-qm", "report only")
    assert study_run.producing_digest(study_run.producing_files(study)) == original
    report.write_text("regenerated report")
    assert study_run.checked_source(output, report, inputs).dirty
    code.write_text("x = 2")
    assert study_run.producing_digest(inputs) != original
    with pytest.raises(SystemExit, match="commit changes"):
        study_run.checked_source(output, report, inputs)
    code.write_text("x = 1")
    extra = code.with_name("added.py")
    extra.write_text("x = 3")
    assert study_run.producing_digest(study_run.producing_files(study)) != original


def test_main_captures_environment_once_and_accepts_external_report(
    study, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(study_run, "load_study", lambda: study)
    monkeypatch.setattr(study_run, "producing_files", lambda _: ())
    monkeypatch.setattr(study_run, "checked_source", lambda *args: SourceState.unrecorded())
    monkeypatch.setattr(study_run, "calendars_of", lambda _: Mock())
    monkeypatch.setattr(study_run, "checked_schedule", lambda *args: Mock())
    monkeypatch.setattr(study_run, "checked_digest", lambda *args: "data")
    monkeypatch.setattr(study_run, "books_of", lambda *args: [Mock()])
    environment = {"numpy": "test"}
    captured = Mock(return_value=environment)
    monkeypatch.setattr(study_run, "environment_state", captured)
    build = Mock(return_value=Mock(spec=StrategyRunner))
    run = Mock()
    monkeypatch.setattr(study_run, "build_runner", build)
    monkeypatch.setattr(study_run, "run_book", run)
    monkeypatch.setattr(study_run, "analyse", lambda *args: {})
    monkeypatch.setattr(study_run, "markdown", lambda *args: "report")
    report = tmp_path / "external/nested/study.md"
    assert study_run.main(["--output", str(tmp_path / "output"), "--report", str(report)]) == 0
    assert report.read_text() == "report"
    captured.assert_called_once()
    assert build.call_count == run.call_count == 2
    assert all(call.args[-1] is environment for call in build.call_args_list + run.call_args_list)


def test_run_reserves_directory_before_computation(study, tmp_path) -> None:
    book = study_run.books_of(study, ListedSessions((date(2018, 8, 1),), rule="test"))[0]
    folder = tmp_path / f"{book.name}_x1"
    runner = Mock(spec=StrategyRunner)

    def competing_writer(*args: object, **kwargs: object) -> None:
        assert folder.is_dir()
        with pytest.raises(FileExistsError, match="already exists"):
            study_run.reserve_run(folder)
        raise RuntimeError("stop synthetic run")

    runner.run.side_effect = competing_writer
    with pytest.raises(RuntimeError, match="stop synthetic run"):
        study_run.run_book(book, study, runner, 1.0, "data", tmp_path, "content", {})
    assert not (folder / "complete.json").exists()


def test_run_refuses_a_configuration_environment_mismatch(study, tmp_path) -> None:
    book = study_run.books_of(study, ListedSessions((date(2018, 8, 1),), rule="test"))[0]
    runner = Mock(spec=StrategyRunner)
    runner.run.return_value.configuration = {"environment": {"numpy": "different"}}
    with pytest.raises(ValueError, match="environment differs"):
        study_run.run_book(book, study, runner, 1.0, "data", tmp_path, "content", {"numpy": "one"})
    assert not (tmp_path / f"{book.name}_x1/complete.json").exists()


@pytest.mark.parametrize(
    ("candidate", "holm", "stressed", "expected"),
    [
        (
            metrics(0.12, 1.0, -0.20),
            {"A": 0.01, "B": 0.02},
            metrics(0.11, 0.9, -0.21),
            "SUPPORTED_PROVISIONAL",
        ),
        # A drawdown 2 points deeper is allowed, 2.1 is not.
        (
            metrics(0.12, 1.0, -0.22),
            {"A": 0.01, "B": 0.02},
            metrics(0.11, 0.9, -0.21),
            "SUPPORTED_PROVISIONAL",
        ),
        (
            metrics(0.12, 1.0, -0.221),
            {"A": 0.01, "B": 0.02},
            metrics(0.11, 0.9, -0.21),
            "NOT_SUPPORTED",
        ),
        (metrics(0.12, 1.0, -0.20), {"A": 0.01, "B": 0.06}, metrics(0.11, 0.9, -0.21), "UNCERTAIN"),
        (metrics(0.12, 1.0, -0.20), {"A": 0.01, "B": 0.02}, metrics(0.09, 0.9, -0.21), "UNCERTAIN"),
        (
            metrics(0.10, 1.0, -0.20),
            {"A": 0.01, "B": 0.02},
            metrics(0.11, 0.9, -0.21),
            "NOT_SUPPORTED",
        ),
    ],
)
def test_the_reading_against_references_follows_the_frozen_criterion(
    candidate, holm, stressed, expected
) -> None:
    references = {"A": metrics(0.10, 0.8, -0.20), "B": metrics(0.11, 0.7, -0.20)}
    stressed_references = {"A": metrics(0.095, 0.75, -0.20), "B": metrics(0.10, 0.65, -0.20)}
    reading = study_run.reading_against_references(
        candidate, references, stressed, stressed_references, holm, 0.02, 0.05
    )
    assert reading["reading"] == expected


@pytest.mark.parametrize(
    ("difference", "holm_p", "stressed", "expected"),
    [
        (0.2, 0.01, 0.1, "SUPPORTED_PROVISIONAL"),
        (0.2, 0.05, 0.1, "UNCERTAIN"),
        (0.2, 0.01, 0.0, "UNCERTAIN"),
        (0.0, 0.01, 0.1, "NOT_SUPPORTED"),
        (-0.1, 0.01, 0.1, "NOT_SUPPORTED"),
    ],
)
def test_the_reading_against_a_control_follows_the_frozen_rule(
    difference, holm_p, stressed, expected
) -> None:
    assert study_run.reading_against_control(difference, holm_p, stressed, 0.05) == expected


# -- end to end on the synthetic market of the strategy's tests ----------------------

from tests.strategies.test_SA17_sector_residual_momentum import (  # noqa: E402
    MONETARY,
    SECTORS,
    SHORT,
    build_market,  # noqa: F401 - fixtures the synthetic market is built from
    candidate,
    holes,  # noqa: F401
    instruments,  # noqa: F401
    market,  # noqa: F401
)

from quant_backtester.analytics.config import AnalyticsConfig  # noqa: E402
from quant_backtester.backtest.runner import StrategyResult, StrategyRunner  # noqa: E402
from quant_backtester.backtest.schedule import Monthly  # noqa: E402
from quant_backtester.execution.costs import CostModel  # noqa: E402
from quant_backtester.execution.model import ExecutionModel, Sizing  # noqa: E402
from quant_backtester.research.references import BuyAndHold  # noqa: E402


@pytest.mark.slow
def test_runs_are_saved_compared_and_reported(
    market,  # noqa: F811 - the imported fixture, requested by name
    calendars,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole chain after the runner, on a drawn market: save, analyse, report."""
    config = AnalyticsConfig(sessions_per_year=252, risk_free_rate=0.0, minimum_sessions=20)
    model = CostModel(
        commission_rate=0.0005,
        minimum_commission=1.0,
        half_spread_rate=0.0005,
        slippage_rate=0.0005,
    )
    traded = (*SECTORS, MONETARY)
    captured_environment = {"numpy": "captured once"}
    unexpected_capture = Mock(side_effect=AssertionError("environment was sampled again"))
    monkeypatch.setattr("quant_backtester.backtest.runner.environment_state", unexpected_capture)
    strategy = candidate(**SHORT)
    books = [
        study_run.BookSpec(study_run.CANDIDATE, strategy, Monthly(), "candidate"),
        *(
            study_run.BookSpec(name, control, Monthly(), "control")
            for name, control in strategy.controls().items()
        ),
        study_run.BookSpec("Hold_S_A", BuyAndHold(("S_A",)), EverySession(), "reference"),
    ]
    study = {
        "status": "PROVISIONAL_NOT_ADMITTED",
        "formal_verdict": "INSUFFICIENT_EVIDENCE",
        "gates": {"2c": "PARTIAL"},
        "strategy": {"sector_ids": list(SECTORS)},
        "costs": {"multipliers": [1.0, 2.0]},
        "inference": {
            "primary_statistic": "SHARPE",
            "secondary_statistic": "MEAN_RETURN",
            "mean_block_sessions": 20,
            "sensitivity_blocks": [5, 60],
            "draws": 200,
            "seed": 20261107,
            "level": 0.95,
            "holm_families": {
                "references": ["Hold_S_A"],
                "controls": list(strategy.controls()),
            },
            "significance": 0.05,
            "deflated_sharpe_trials": 5,
            "max_drawdown_tolerance": 0.02,
        },
        "regimes": {"periods": [["2026-07-01", "2026-09-30"], ["2026-10-01", "2026-12-31"]]},
    }
    for multiplier in (1.0, 2.0):
        scaled = model.scaled(multiplier)
        models = {name: scaled for name in traded}
        runner = StrategyRunner(
            reader=market,
            calendars=calendars,
            reference_calendar_id="XPAR",
            base_currency="EUR",
            analytics=config,
            execution=ExecutionModel(
                costs=scaled, sizing=Sizing.AT_DECISION, costs_by_instrument=models
            ),
            initial_cash=100_000.0,
            environment=captured_environment,
        )
        for book in books:
            result = runner.run(
                book.strategy, traded, "2026-06-01", "2026-12-31", schedule=book.schedule
            )
            assert result.configuration["environment"] == captured_environment
            saved = study_run.save_run(
                tmp_path / f"{book.name}_x{multiplier:g}",
                result,
                book,
                "key",
                config,
                models,
                study,
            )
            assert saved["net"]["sharpe"] is not None
            folder = tmp_path / f"{book.name}_x{multiplier:g}"
            assert study_run.checked_saved_run(folder, "key")["run_id"] == saved["run_id"]
            assert saved["costs_eur"] == pytest.approx(
                saved["spread_eur"] + saved["commission_eur"] + saved["slippage_eur"]
            )
    summary = study_run.analyse(
        study
        | {"analytics": {"sessions_per_year": 252, "risk_free_rate": 0.0, "minimum_sessions": 20}},
        books,
        tmp_path,
    )
    readings = {"NOT_SUPPORTED", "UNCERTAIN", "SUPPORTED_PROVISIONAL"}
    assert summary["against_references"]["reading"] in readings
    assert {values["reading"] for values in summary["against_controls"].values()} <= readings
    assert set(summary["holm"]["controls"]) == set(strategy.controls())
    assert 0.0 <= summary["deflated_sharpe"]["probability"] <= 1.0
    assert summary["metrics"][f"{study_run.CANDIDATE}_x1"]["mean_sector_exposure_at_decisions"] > 0
    report = study_run.markdown(summary, books)
    assert "## Admission gates" in report
    assert "INSUFFICIENT_EVIDENCE" in report
    study_run.write_json(tmp_path / "summary.json", summary)
    unexpected_capture.assert_not_called()
