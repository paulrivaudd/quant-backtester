"""Tests of the SA17 executable study runner: its frozen checks and its reading rules."""

from __future__ import annotations

import shutil
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from quant_backtester.backtest.schedule import EverySession, ListedSessions, Weekly
from quant_backtester.data.calendars import CalendarRegistry
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
    base = study_run.signature(book, study, 1.0, "digest")
    assert study_run.signature(book, study, 1.0, "digest") == base
    assert study_run.signature(book, study, 2.0, "digest") != base
    assert study_run.signature(book, study, 1.0, "other") != base
    moved = replace(book, schedule=ListedSessions((date(2018, 8, 2),), rule="test"))
    assert study_run.signature(moved, study, 1.0, "digest") != base


def metrics(cagr: float, sharpe: float, drawdown: float) -> dict[str, float]:
    return {"cagr": cagr, "sharpe": sharpe, "max_drawdown": drawdown}


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
from quant_backtester.backtest.runner import StrategyRunner  # noqa: E402
from quant_backtester.backtest.schedule import Monthly  # noqa: E402
from quant_backtester.execution.costs import CostModel  # noqa: E402
from quant_backtester.execution.model import ExecutionModel, Sizing  # noqa: E402
from quant_backtester.research.references import BuyAndHold  # noqa: E402


@pytest.mark.slow
def test_runs_are_saved_compared_and_reported(
    market,  # noqa: F811 - the imported fixture, requested by name
    calendars,
    tmp_path: Path,
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
        )
        for book in books:
            result = runner.run(
                book.strategy, traded, "2026-06-01", "2026-12-31", schedule=book.schedule
            )
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
