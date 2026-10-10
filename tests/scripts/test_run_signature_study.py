"""The SA13 study: its variants, its monthly schedules, its forecasts and its statuses.

The whole route - features, calibrations, books, forecasts, labels, errors,
comparisons, the written study - is walked once on a small drawn market. It
shows that the pieces fit and that nothing leaks; it says nothing about any
fund, and no test here asks a model fitted on noise to be any good.
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from types import ModuleType

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("torch")
pytest.importorskip("esig")
pytest.importorskip("roughpy")
pytest.importorskip("sklearn")
pytest.importorskip("arch")
pytest.importorskip("statsmodels")

from quant_backtester.backtest.runner import StrategyRunner
from quant_backtester.data.calendars import CalendarRegistry, TradingCalendar
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.data.schemas import BarField
from quant_backtester.ml.signatures.artifacts import SignatureArtifact
from quant_backtester.ml.signatures.config import (
    ModelKind,
    SignatureModelConfig,
    SignatureTrainingConfig,
)
from quant_backtester.signals.signatures.logsignature import FeatureKind
from quant_backtester.signals.signatures.path import SignaturePathConfig
from quant_backtester.signals.types import SignalStatus
from quant_backtester.strategies import BuyAndHold, EqualWeightRebalance

REPOSITORY = Path(__file__).resolve().parents[2]


def load_script() -> ModuleType:
    """Import ``scripts/run_signature_study.py``, its folder on the path as when run."""
    scripts = REPOSITORY / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    path = scripts / "run_signature_study.py"
    spec = importlib.util.spec_from_file_location("run_signature_study", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SCRIPT = load_script()
FUND, OTHER = "ETF_EU", "ETF_OTHER"
SMALL_PATH = SignaturePathConfig(
    steps=60, volume_reference_sessions=10, price_scale=100.0, use_volume=True, max_age_sessions=0
)
"""Sixty increments, the fewest the classical indicators describe, after ten of reference."""

SMALL_CUT = SignatureTrainingConfig(80, 30, 60, 20, 0.9)
PERIOD = ("2026-10-01", "2026-12-30")


# --- what is frozen ----------------------------------------------------------------------


def test_the_eight_variants_are_those_registered_and_change_one_thing_each() -> None:
    chosen = SCRIPT.variants()
    core = chosen[SCRIPT.CORE_VARIANT]

    assert list(chosen) == [SCRIPT.CORE_VARIANT, *SCRIPT.MODEL_CONTROLS.values()]
    assert {name: len(variant.features.names()) for name, variant in chosen.items()} == {
        "sa13_nam_logsig3": 13,
        "research_sa13_ridge_logsig3": 13,
        "research_sa13_nam_logsig2": 5,
        "research_sa13_nam_no_volume": 13,
        "research_sa13_nam_classical": 9,
        "research_sa13_ridge_raw_trajectory": 120,
        "research_sa13_nam_context_sp500": 26,
        "research_sa13_ridge_context_sp500": 26,
    }
    assert core.model.kind is ModelKind.NEURAL_ADDITIVE and core.instrument_id == "ETF_WORLD"
    assert (core.features.path.steps, core.features.path.volume_reference_sessions) == (60, 60)
    assert core.features.path.required_history_sessions == 120 and core.features.depth == 3
    assert (core.model.hidden_units, core.model.max_epochs, core.model.patience) == (4, 300, 30)
    assert (core.model.learning_rate, core.model.weight_decay) == (1e-3, 1e-3)
    assert (core.model.seed, core.model.input_clip, core.model.target_scale) == (
        20261010,
        5.0,
        100.0,
    )
    assert core.training == SignatureTrainingConfig(1008, 126, 900, 100, 0.95)
    # Every control keeps the fund, the cut and the path's window, and changes one thing.
    ridge = chosen["research_sa13_ridge_logsig3"]
    assert ridge.features == core.features and ridge.model.kind is ModelKind.RIDGE
    assert ridge.model.ridge_alpha == 10.0
    assert chosen["research_sa13_nam_logsig2"].features == replace(core.features, depth=2)
    silent = chosen["research_sa13_nam_no_volume"].features
    assert silent.path == replace(core.features.path, use_volume=False)
    assert chosen["research_sa13_nam_classical"].features.kind is FeatureKind.CLASSICAL
    assert chosen["research_sa13_ridge_raw_trajectory"].features.kind is FeatureKind.RAW_TRAJECTORY
    context = chosen["research_sa13_nam_context_sp500"].features
    assert context.context_instruments == ("ETF_WORLD", "ETF_SP500_PEA")
    assert all(variant.instrument_id == "ETF_WORLD" for variant in chosen.values())
    assert all(variant.training == core.training for variant in chosen.values())
    assert len({variant.fingerprint() for variant in chosen.values()}) == 8
    # A control carries a research identifier, never a catalogue code.
    assert all(name.startswith("research_sa13_") for name in SCRIPT.MODEL_CONTROLS.values())


def test_the_criteria_are_those_written_before_the_first_fit() -> None:
    assert SCRIPT.STUDY_PERIOD == ("2023-01-02", "2026-10-09")
    assert (SCRIPT.BOOTSTRAP_BLOCK, SCRIPT.SENSITIVITY_BLOCKS) == (60, (20, 120))
    assert (SCRIPT.BOOTSTRAP_DRAWS, SCRIPT.BOOTSTRAP_SEED) == (5000, 20261010)
    assert (SCRIPT.MINIMUM_TEST_SESSIONS, SCRIPT.MINIMUM_COMPLETED_EPISODES) == (504, 30)
    assert SCRIPT.MINIMUM_USABLE_SHARE == 0.95 and SCRIPT.COST_STRESS == 2.0
    assert timedelta(hours=12) == SCRIPT.MODEL_AVAILABILITY_DELAY
    assert SCRIPT.SA13 == "SA13 - Signatures Neurons"
    assert len(SCRIPT.MSE_COMPARISONS) == 9 and len(SCRIPT.SECONDARY_QUESTIONS) == 6


def test_a_months_model_stops_at_the_last_session_before_the_month(
    xpar: TradingCalendar,
) -> None:
    sessions = [day.session_date for day in xpar.sessions(date(2026, 1, 5), date(2026, 12, 31))]

    months = SCRIPT.calibration_months(sessions, date(2026, 3, 16), date(2026, 5, 15))
    first = SCRIPT.calibration_months(sessions, date(2026, 1, 5), date(2026, 2, 10))

    # 1 May is a holiday in Paris and 3 and 6 April too: the cutoff is a session, not a date.
    assert months == [
        ("2026-03", date(2026, 2, 27)),
        ("2026-04", date(2026, 3, 31)),
        ("2026-05", date(2026, 4, 30)),
    ]
    # A month no session comes before can have no model: said, not guessed.
    assert first == [("2026-01", None), ("2026-02", date(2026, 1, 30))]
    assert SCRIPT.calibration_months(sessions, date(2027, 1, 1), date(2027, 2, 1)) == []


def test_a_contribution_is_summed_in_the_group_of_its_coefficient() -> None:
    assert SCRIPT.group_of("ETF_WORLD:1") == SCRIPT.group_of("ETF_WORLD:2") == "displacements"
    assert SCRIPT.group_of("ETF_WORLD:[1,2]") == "price_volume"
    assert SCRIPT.group_of("ETF_WORLD:[1,3]") == "price_time"
    assert SCRIPT.group_of("ETF_SP500_PEA:[2,3]") == "volume_time"
    assert SCRIPT.group_of("ETF_WORLD:[1,[1,2]]") == SCRIPT.group_of("X:[3,[2,3]]") == "order_3"
    assert SCRIPT.group_of("ETF_WORLD:log_return_20") == "other"
    assert set(SCRIPT.GROUPS) >= {"reference", "displacements", "order_3", "other"}


# --- the statuses ------------------------------------------------------------------------


def comparison(**overrides: object) -> pd.DataFrame:
    """Return the two rows against C0 of a study in which the filter clearly helped."""
    rows = []
    for costs, difference in (("x1", 0.30), ("x2", 0.25)):
        row: dict[str, object] = {
            "costs": costs,
            "control": SCRIPT.C0,
            "sharpe_difference": difference,
            "interval_low": 0.05,
            "interval_high": 0.55,
            "max_drawdown_sa13": -0.10,
            "max_drawdown_control": -0.12,
            "bootstrap": "ok",
        }
        row.update({key: value for key, value in overrides.items() if not key.startswith("x2_")})
        if costs == "x2":
            row.update(
                {
                    key.removeprefix("x2_"): value
                    for key, value in overrides.items()
                    if key.startswith("x2_")
                }
            )
        rows.append(row)
    return pd.DataFrame(rows)


def status(frame: pd.DataFrame, **settings: object) -> tuple[str, list[str]]:
    """Return the status of a study with enough sessions, episodes and coverage, unless said."""
    arguments: dict[str, object] = {
        "test_sessions": 960,
        "completed_episodes": 40,
        "usable_share": 1.0,
    }
    arguments.update(settings)
    return SCRIPT.hypothesis_status(frame, **arguments)


def test_the_hypothesis_is_supported_only_when_every_criterion_holds() -> None:
    assert status(comparison()) == ("SUPPORTED_RETROSPECTIVE", [])


@pytest.mark.parametrize(
    ("settings", "reason"),
    [
        ({"test_sessions": 503}, "test sessions"),
        ({"completed_episodes": 29}, "completed position episodes"),
        ({"usable_share": 0.949}, "usable features"),
        ({"usable_share": None}, "undefined"),
    ],
)
def test_sufficiency_is_judged_before_anything_else(
    settings: dict[str, object], reason: str
) -> None:
    """Even a study the filter would have won says nothing on too thin a sample."""
    outcome, reasons = status(comparison(), **settings)

    assert outcome == "INSUFFICIENT_EVIDENCE"
    assert any(reason in item for item in reasons)


def test_a_main_difference_at_or_below_zero_is_not_supported() -> None:
    assert status(comparison(sharpe_difference=0.0))[0] == "NOT_SUPPORTED"
    outcome, reasons = status(comparison(sharpe_difference=-0.2))
    assert outcome == "NOT_SUPPORTED" and "-0.200" in reasons[0]


def test_a_positive_difference_is_uncertain_until_every_criterion_holds() -> None:
    interval = status(comparison(interval_low=-0.05))
    doubled = status(comparison(x2_sharpe_difference=-0.01))
    deeper = status(comparison(max_drawdown_sa13=-0.15))
    refused = status(comparison(sharpe_difference=None, bootstrap="refused: flat book"))
    everything = status(
        comparison(interval_low=-0.05, x2_sharpe_difference=0.0, max_drawdown_sa13=-0.15)
    )

    assert interval[0] == "UNCERTAIN" and "includes zero" in interval[1][0]
    assert doubled[0] == "UNCERTAIN" and "doubled costs" in doubled[1][0]
    assert deeper == ("UNCERTAIN", ["maximum drawdown deeper than C0's"])
    assert refused[0] == "UNCERTAIN" and "refused" in refused[1][0]
    assert everything[0] == "UNCERTAIN" and len(everything[1]) == 3


def test_each_secondary_question_is_concluded_on_its_own_difference() -> None:
    labels = [label for _, label, _ in SCRIPT.SECONDARY_QUESTIONS]
    rows = [
        {
            "comparison": labels[0],
            "estimate": -1e-7,
            "low": -2e-7,
            "high": -1e-8,
            "bootstrap": "ok",
        },
        {"comparison": labels[1], "estimate": -1e-7, "low": -2e-7, "high": 1e-8, "bootstrap": "ok"},
        {"comparison": labels[2], "estimate": 0.0, "low": -1e-7, "high": 1e-7, "bootstrap": "ok"},
        {"comparison": labels[3], "estimate": 2e-7, "low": 1e-7, "high": 3e-7, "bootstrap": "ok"},
        {"comparison": labels[4], "pairs": 1, "bootstrap": "refused"},
        {
            "comparison": labels[5],
            "estimate": -3e-7,
            "low": -4e-7,
            "high": -2e-7,
            "bootstrap": "ok",
        },
    ]

    assert SCRIPT.secondary_conclusions(pd.DataFrame(rows)) == {
        "neurons": "LOWER_MSE_INTERVAL_EXCLUDES_ZERO",
        "order_3": "LOWER_MSE_NOT_TOLD_FROM_ZERO",
        "volume": "NOT_LOWER",
        "signature_vs_classical": "NOT_LOWER",
        "compression_vs_raw": "NOT_MEASURED",
        "second_process": "LOWER_MSE_INTERVAL_EXCLUDES_ZERO",
    }
    assert set(SCRIPT.SECONDARY_FRENCH) == {name for name, _, _ in SCRIPT.SECONDARY_QUESTIONS}


# --- small pieces ------------------------------------------------------------------------


def test_an_origin_is_invested_when_the_fund_was_held_over_its_interval() -> None:
    days = [date(2026, 3, 2) + timedelta(days=index) for index in range(5)]
    held = pd.Series([0.0, 0.6, 0.6, 0.0, 0.5], index=pd.Index(days, dtype="object"))

    # Decided at t, held at the valuation of t + 1: origins 0, 1 and 3. The last has no t + 1.
    assert SCRIPT.invested_origins(held, days) == {days[0], days[1], days[3]}


def test_the_decisions_of_an_episode_are_those_of_the_evenings_before() -> None:
    days = [date(2026, 3, 2) + timedelta(days=index) for index in range(8)]
    stays = pd.DataFrame(
        {
            "entry": [days[1], days[5]],
            "exit": [days[3], days[7]],
            "open": [False, True],
        }
    )

    entries, exits = SCRIPT.episode_decisions(stays, days)

    assert entries == [days[0], days[4]]
    assert exits == [days[2]]  # the stay still running was closed by no decision


def test_the_exported_forecasts_must_be_those_the_run_computed() -> None:
    days = pd.Index(
        [date(2026, 3, 2) + timedelta(days=index) for index in range(3)], dtype="object"
    )
    history = pd.DataFrame({"signal[F]": [0.001, float("nan"), 0.002]}, index=days)
    same = pd.DataFrame({"forecast": [0.001, float("nan"), 0.002]}, index=days)
    other = pd.DataFrame({"forecast": [0.001, float("nan"), 0.0021]}, index=days)
    filled = pd.DataFrame({"forecast": [0.001, 0.0, 0.002]}, index=days)

    SCRIPT.require_same_forecasts(same, history, "signal[F]")
    with pytest.raises(RuntimeError, match="not the one the run computed"):
        SCRIPT.require_same_forecasts(other, history, "signal[F]")
    with pytest.raises(RuntimeError, match="not the one the run computed"):
        SCRIPT.require_same_forecasts(filled, history, "signal[F]")


def test_a_function_that_keeps_its_sign_across_months_is_said_stable() -> None:
    rows = [
        {"month": month, "feature": "F:1", "z": point, "contribution_bp": value * point}
        for month, value in (("2026-01", 1.0), ("2026-02", 3.0), ("2026-03", -1.0))
        for point in (-5.0, -1.0, 1.0, 2.0)
    ]

    stability = SCRIPT.function_stability(pd.DataFrame(rows)).set_index("z")

    assert list(stability.index) == [-1.0, 1.0, 2.0]  # the grid points reported, no other
    assert stability.loc[1.0, "mean_bp"] == pytest.approx(1.0)
    assert stability.loc[1.0, "std_across_months_bp"] == pytest.approx(2.0)
    assert stability.loc[2.0, "share_of_months_with_the_sign_of_the_mean"] == pytest.approx(2 / 3)
    assert SCRIPT.function_stability(pd.DataFrame()).empty


# --- the whole route, on a small drawn market --------------------------------------------


def short_models() -> dict[ModelKind, SignatureModelConfig]:
    """Return the models of the study with a fit of a few epochs."""
    return {kind: replace(SCRIPT.model_of(kind), max_epochs=25, patience=5) for kind in ModelKind}


def test_the_whole_route_holds_together_and_leaks_nothing(
    make_signature_market: Callable[..., MarketDataReader],
    make_neural_runner: Callable[..., StrategyRunner],
    calendars: CalendarRegistry,
    xpar: TradingCalendar,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    for name in ("run_signature_study", "run_garch_study", "run_etf_strategies_comparison"):
        monkeypatch.setattr(sys.modules[name], "UNIVERSE", (FUND, OTHER))
    reader = make_signature_market()
    runner = make_neural_runner(reader)
    timetable = runner.timetable
    end = date.fromisoformat(PERIOD[1])
    sessions = SCRIPT.calendar_sessions(reader, xpar, timetable, FUND, end)
    months = SCRIPT.calibration_months(sessions, date.fromisoformat(PERIOD[0]), end)
    chosen = SCRIPT.variants(
        fund=FUND, context=OTHER, path=SMALL_PATH, training=SMALL_CUT, models=short_models()
    )

    features = SCRIPT.feature_cache(reader, calendars, timetable, sessions, chosen)
    schedules, planned, training_history = SCRIPT.calibrate_schedules(
        chosen,
        months,
        reader=reader,
        calendar=xpar,
        timetable=timetable,
        sessions=sessions,
        features=features,
    )

    # Six representations for eight variants; three months, a model for each.
    assert sessions[0] == date(2026, 1, 5) and len(features) == 6
    assert [month for month, _ in months] == ["2026-10", "2026-11", "2026-12"]
    assert len(planned) == 24 and (planned["status"] == "CALIBRATED").all()
    assert set(planned["training_examples"]) == {78} and set(planned["validation_examples"]) == {28}
    assert set(training_history["status"]) == {"CALIBRATED"}
    core = schedules[SCRIPT.CORE_VARIANT]
    for found, (_, cutoff) in zip(core.entries, months, strict=True):
        assert found.artifact is not None and cutoff is not None
        assert found.artifact.information_cutoff == timetable.decision_instant(cutoff)
        assert found.artifact.validation_end < cutoff
    summary = SCRIPT.calibration_summary(planned, chosen)
    assert summary.loc[SCRIPT.CORE_VARIANT, "months_with_model"] == 3
    assert pd.isna(summary.loc["research_sa13_ridge_logsig3", "at_epoch_cap"])  # no epochs

    family = SCRIPT.study_books(schedules, chosen)
    assert list(family) == [SCRIPT.SA13, SCRIPT.C0, *SCRIPT.MODEL_CONTROLS]
    assert family[SCRIPT.SA13].strategy_id == "SA13_signatures_neurons"
    assert family[SCRIPT.C0].schedule_id == family[SCRIPT.SA13].schedule_id
    assert not family[SCRIPT.C0].direction_filter
    assert all(book.direction_filter for name, book in family.items() if name != SCRIPT.C0)
    # The thresholds are entered on any positive forecast here, so that the books trade on
    # a quarter of noise; the study itself never changes them.
    family = {name: replace(book, entry_threshold=1e-9) for name, book in family.items()}
    strategies = {
        SCRIPT.BENCHMARK: BuyAndHold(instruments=(FUND,), strategy_id="test_benchmark"),
        SCRIPT.HELD: BuyAndHold(instruments=(FUND,)),
        SCRIPT.SPLIT: EqualWeightRebalance(instruments=(FUND, OTHER)),
        **family,
    }
    base = {name: runner.run(book, (FUND, OTHER), *PERIOD) for name, book in strategies.items()}
    stressed_runner = replace(runner, execution=SCRIPT.doubled(runner.execution))
    stressed = {
        name: stressed_runner.run(book, (FUND, OTHER), *PERIOD) for name, book in strategies.items()
    }
    histories = SCRIPT.book_histories(base, strategies)
    own = base[SCRIPT.SA13]
    test_sessions = [record.session_date for record in own.records()]
    assert len(test_sessions) == 64 and float(own.equity().iloc[0]) == 100_000.0

    forecasts = {}
    for name, book in family.items():
        if name == SCRIPT.C0:
            continue
        frame = SCRIPT.forecast_frame(
            schedules[book.variant_id],
            features[SCRIPT.spec_key(chosen[book.variant_id].features)],
            test_sessions,
            timetable,
        )
        # What is exported from the cache of the calibration is what the run's signal
        # computed at each decision: the same features at the same instant.
        SCRIPT.require_same_forecasts(
            frame, histories[name], f"{book.forecast_signal().signal_id}[{FUND}]"
        )
        forecasts[name] = frame
    mine = forecasts[SCRIPT.SA13]
    assert (mine["status"] == SignalStatus.OK.value).all() and len(mine) == 64
    assert list(mine["model_month"].drop_duplicates()) == ["2026-10", "2026-11", "2026-12"]
    parts = mine[[column for column in mine.columns if column.startswith("contribution[")]]
    groups = mine[[f"group[{group}]" for group in SCRIPT.GROUPS]]
    assert parts.shape[1] == 13
    assert np.allclose(mine["reference"] + parts.sum(axis=1), mine["forecast"], atol=1e-15)
    assert np.allclose(groups.sum(axis=1), mine["forecast"], atol=1e-15)
    assert len(forecasts[SCRIPT.C6].filter(like="contribution[").columns) == 26
    assert float(forecasts[SCRIPT.C4]["group[other]"].abs().sum()) > 0.0  # no key of a signature

    with own.reading() as store:
        opens = store.at(own.records()[-1].valuation_time).history(FUND, BarField.OPEN)
        realised = SCRIPT.realised_labels(store, xpar, timetable, test_sessions, FUND)
    # A label is the open-to-open return, indexed by the session it ends at; the two last
    # origins have none yet and are pending, not invented.
    assert len(realised) == 62 and realised.index[0] == test_sessions[2]
    first_exit = test_sessions[2]
    assert float(realised.loc[first_exit]) == pytest.approx(
        float(opens.loc[first_exit]) / float(opens.loc[test_sessions[1]]) - 1.0
    )
    evaluations, pairings, invested = {}, {}, {}
    for name, frame in forecasts.items():
        evaluations[name], pairings[name] = SCRIPT.evaluation_frame(frame, realised, test_sessions)
        histories[name] = SCRIPT.signature_history(histories[name], frame, opens, family[name])
        invested[name] = SCRIPT.invested_origins(
            pd.Series(histories[name][f"held_{FUND}"]), test_sessions
        )
    histories[SCRIPT.C0] = SCRIPT.signature_history(
        histories[SCRIPT.C0], mine, opens, family[SCRIPT.C0]
    )
    pairs = evaluations[SCRIPT.SA13]
    assert len(pairs) == 62 and pairings[SCRIPT.SA13].exclusions["target_pending"] == 2
    month_of = dict(zip(mine.index, mine["model_month"], strict=True))
    for origin, reference in pairs["reference_train_mean"].items():
        artifact = core.entries[["2026-10", "2026-11", "2026-12"].index(month_of[origin])].artifact
        assert isinstance(artifact, SignatureArtifact)
        assert reference == artifact.training_label_mean  # frozen with the model, not the test's
    errors = SCRIPT.forecast_summary(evaluations, pairings, invested)
    assert set(errors["sample"]) == {"all valid forecasts", "invested"} and len(errors) == 16
    everything = errors.set_index(["book", "sample"]).loc[(SCRIPT.SA13, "all valid forecasts")]
    assert everything["pairs"] == 62 and everything["mse"] > 0.0
    assert everything["mse_zero"] == pytest.approx(float((pairs["realised"] ** 2).mean()))
    differences = SCRIPT.mse_differences(evaluations)
    assert list(differences["comparison"]) == [label for label, _, _ in SCRIPT.MSE_COMPARISONS]
    assert (differences["bootstrap"] == "ok").all() and (differences["pairs"] == 62).all()

    history = histories[SCRIPT.SA13]
    assert list(history.columns[:3]) == [f"close_{FUND}", f"close_{OTHER}", f"open_{FUND}"]
    assert {"model_month", "forecast_bp", "reference_bp", "order_3_bp", "gate"} <= set(history)
    assert set(history["model_month"]) == {202610.0, 202611.0, 202612.0}
    assert np.allclose(history["forecast_bp"], mine["forecast"] * 1e4)
    assert history.to_numpy(dtype="float64").shape == (64, len(history.columns))  # all numeric
    # The control holds whenever SA13's forecast exists; SA13 only when its gate is open.
    control = histories[SCRIPT.C0]
    assert float(control["theoretical_weight"].min()) > 0.0
    assert set(history.loc[history["gate"] == 0.0, "theoretical_weight"]) <= {0.0}

    functions = SCRIPT.component_functions(core)
    assert len(functions) == 3 * 13 * 21
    at_zero = functions.loc[functions["z"] == 0.0, "contribution_bp"]
    assert (at_zero == 0.0).all()  # every component is centred at the reference
    assert SCRIPT.component_functions(schedules["research_sa13_ridge_logsig3"]).empty
    domain = SCRIPT.feature_domain(
        core,
        features[SCRIPT.spec_key(chosen[SCRIPT.CORE_VARIANT].features)],
        test_sessions,
        timetable,
    )
    assert len(domain) == 13 and set(domain["decisions"]) == {64}
    assert ((domain["q01"] <= domain["median"]) & (domain["median"] <= domain["q99"])).all()

    fills = own.fills()
    stays = SCRIPT.episodes(history, fills)
    entries, exits = SCRIPT.episode_decisions(stays, test_sessions) if len(stays) else ([], [])
    contributions = SCRIPT.contribution_summary(
        mine,
        {
            "every usable decision": list(mine.index),
            "decisions that opened a position": entries,
            "decisions that closed a position": exits,
        },
    )
    assert contributions.loc["every usable decision", "decisions"] == 64
    assert contributions.loc["every usable decision", "forecast_bp"] == pytest.approx(
        float(mine["forecast"].mean() * 1e4)
    )
    coverage = SCRIPT.coverage_frame(planned, forecasts)
    assert coverage.loc[SCRIPT.SA13, "usable_share"] == 1.0
    assert coverage.loc[SCRIPT.SA13, "months_with_model"] == 3
    comparison_table = SCRIPT.comparison_frame(base, stressed)
    assert list(comparison_table["control"].iloc[:8]) == [SCRIPT.C0, *SCRIPT.MODEL_CONTROLS]
    assert set(comparison_table["costs"]) == {"x1", "x2"} and len(comparison_table) == 20
    sensitivity = SCRIPT.sensitivity_frame(base, stressed)
    assert list(sensitivity["block"]) == [20, 60, 120, 20, 60, 120]
    outcome, reasons = SCRIPT.hypothesis_status(
        comparison_table,
        test_sessions=len(test_sessions),
        completed_episodes=int((~stays["open"]).sum()) if len(stays) else 0,
        usable_share=float(coverage.loc[SCRIPT.SA13, "usable_share"]),
    )
    assert outcome == "INSUFFICIENT_EVIDENCE" and "64 test sessions" in reasons[0]
    secondary = SCRIPT.secondary_conclusions(differences)
    assert set(secondary) == {name for name, _, _ in SCRIPT.SECONDARY_QUESTIONS}

    details, register = SCRIPT.scored(base)
    assert register["trials"] == 10  # SA13, its eight controls and the stand-in benchmark
    table = SCRIPT.summary_frame(base, details)
    table["sortino"] = [SCRIPT.sortino(base[str(name)].equity()) for name in table.index]
    stays_summary = dict(SCRIPT.episode_summary(stays))
    written = SCRIPT.study_markdown(
        table,
        table,
        comparison_table,
        sensitivity,
        coverage,
        summary,
        errors,
        differences,
        contributions,
        stays_summary,
        (outcome, reasons),
        secondary,
        register,
        {"everything": 1.0},
    )
    french = SCRIPT.report_extra(
        coverage,
        summary,
        errors,
        differences,
        contributions,
        comparison_table,
        sensitivity,
        stays_summary,
        (outcome, reasons),
        secondary,
    )
    assert "**INSUFFICIENT_EVIDENCE.**" in written and "C0 to C7 are controls" in written
    assert "Statut de l'hypothèse préinscrite `sa13_signatures_neurons`" in french
    assert "Toutes les décisions utilisables" in french and " nan" not in french.lower()

    # The models come back from their folders the very models that were used.
    for found in core.entries:
        assert found.artifact is not None
        folder = found.artifact.save(tmp_path / "artifacts" / found.month)
        assert SignatureArtifact.load(folder).model_id == found.artifact.model_id


def test_the_test_period_changes_nothing_of_the_schedule_built_before_it(
    make_signature_market: Callable[..., MarketDataReader],
    make_neural_runner: Callable[..., StrategyRunner],
    calendars: CalendarRegistry,
    xpar: TradingCalendar,
) -> None:
    """The look-ahead guard of the study: the month a model is for is rewritten, the model stays."""
    cutoff = date(2026, 9, 30)

    def later(frames: dict[str, pd.DataFrame]) -> None:
        for frame in frames.values():
            after = frame["session_date"] > cutoff
            frame.loc[after, ["open", "high", "low", "close"]] *= 1.25
            frame.loc[after, "volume"] *= 2.0

    def schedule_of(name: str, mutate: Callable[..., None] | None) -> str:
        reader = make_signature_market(name, mutate=mutate)
        timetable = make_neural_runner(reader).timetable
        sessions = SCRIPT.calendar_sessions(reader, xpar, timetable, FUND, date(2026, 10, 30))
        months = SCRIPT.calibration_months(sessions, date(2026, 10, 1), date(2026, 10, 30))
        chosen = {
            key: variant
            for key, variant in SCRIPT.variants(
                fund=FUND,
                context=OTHER,
                path=SMALL_PATH,
                training=SMALL_CUT,
                models=short_models(),
            ).items()
            if key in (SCRIPT.CORE_VARIANT, "research_sa13_ridge_context_sp500")
        }
        features = SCRIPT.feature_cache(reader, calendars, timetable, sessions, chosen)
        schedules, _, _ = SCRIPT.calibrate_schedules(
            chosen,
            months,
            reader=reader,
            calendar=xpar,
            timetable=timetable,
            sessions=sessions,
            features=features,
        )
        return "|".join(schedule.schedule_id for schedule in schedules.values())

    assert schedule_of("base", None) == schedule_of("changed", later)
