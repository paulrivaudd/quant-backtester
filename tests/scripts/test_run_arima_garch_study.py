"""The SA12 study: its controls, its forecasts frame, its quality checks and its statuses."""

from __future__ import annotations

import importlib.util
import math
import sys
from datetime import date, timedelta
from pathlib import Path
from types import ModuleType

import numpy as np
import pandas as pd
import pytest

from quant_backtester.signals.types import SignalStatus
from quant_backtester.strategies import ArimaGarch

pytest.importorskip("arch")
pytest.importorskip("statsmodels")

REPOSITORY = Path(__file__).resolve().parents[2]


def load_script() -> ModuleType:
    """Import ``scripts/run_arima_garch_study.py``, its folder on the path as when run."""
    scripts = REPOSITORY / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    path = scripts / "run_arima_garch_study.py"
    spec = importlib.util.spec_from_file_location("run_arima_garch_study", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SCRIPT = load_script()
DAYS = [date(2026, 3, 2) + timedelta(days=index) for index in range(6)]


def test_the_controls_change_one_thing_each_and_carry_no_catalogue_code() -> None:
    controls = SCRIPT.controls()
    base = ArimaGarch()

    assert list(controls) == [SCRIPT.D0, SCRIPT.D1, SCRIPT.D2]
    assert controls[SCRIPT.D0] == ArimaGarch(
        direction_filter=False, strategy_id="research_sa12_d0_no_filter"
    )
    assert controls[SCRIPT.D0].forecast_signal() == base.forecast_signal()  # same forecast
    assert controls[SCRIPT.D1].volatility_model == "EWMA"
    assert (controls[SCRIPT.D2].ar_order, controls[SCRIPT.D2].ma_order) == (0, 0)
    # The thresholds and the sizing are those of SA12 in every control.
    for control in controls.values():
        assert control.strategy_id.startswith("research_sa12_")
        assert (control.entry_threshold, control.exit_threshold) == (0.002, 0.0)
        assert (control.target_volatility, control.rebalance_band) == (0.12, 0.03)


def test_the_participants_are_the_comparison_books_and_four_controls() -> None:
    books = SCRIPT.participants()

    assert SCRIPT.SA12 == "SA12 - ARIMA GARCH" and SCRIPT.SA12 in books
    assert list(books)[-4:] == ["EWMA 0.94 control", SCRIPT.D0, SCRIPT.D1, SCRIPT.D2]
    for name in ("SA11 - GARCH vol control", "SA6 - vol control", "buy & hold World"):
        assert name in books
    assert books[SCRIPT.SA12] == ArimaGarch()  # the frozen configuration, unchanged


def test_doubled_costs_leave_the_policy_alone() -> None:
    """The second run doubles what the engine charges, never the entry threshold."""
    assert SCRIPT.COST_STRESS == 2.0
    assert all(book.entry_threshold == 0.002 for book in SCRIPT.controls().values())
    assert (SCRIPT.MINIMUM_FORECAST_PAIRS, SCRIPT.MINIMUM_COMPLETED_EPISODES) == (252, 30)
    assert (SCRIPT.MINIMUM_USABLE_SHARE, SCRIPT.FALLBACK_ALERT_SHARE) == (0.95, 0.05)
    assert SCRIPT.FORECAST_VARIANCE_FLOOR == 1e-12


def captured_row(status: SignalStatus, **fields: object) -> dict[str, object]:
    """Return the row a joint signal gives at one decision."""
    row: dict[str, object] = {"status": status, "value": float("nan")}
    row.update(fields)
    return row


def forecasts() -> pd.DataFrame:
    """Return six decisions: no window, a refused mean, a fallback and three GARCH fits."""
    usable = {"annualized_volatility": 0.2, "return_variance_h2": 1.6e-4}
    captured = {
        DAYS[0]: captured_row(SignalStatus.INSUFFICIENT_HISTORY),
        DAYS[1]: captured_row(
            SignalStatus.INVALID_INPUT, failure_stage="ARIMA", failure_code="ARIMA_NOT_CONVERGED"
        ),
        DAYS[2]: captured_row(
            SignalStatus.OK, value=0.003, volatility_source="EWMA_FALLBACK", **usable
        ),
        **{
            day: captured_row(SignalStatus.OK, value=0.001, volatility_source="GARCH", **usable)
            for day in DAYS[3:]
        },
    }
    return SCRIPT.forecast_frame(captured, DAYS)


def test_every_decision_has_a_row_with_its_execution_and_target_sessions() -> None:
    frame = forecasts()

    assert list(frame.index) == DAYS
    assert frame.loc[DAYS[2], "execution_session"] == DAYS[3]
    assert frame.loc[DAYS[2], "target_exit_session"] == DAYS[4]
    assert frame.loc[DAYS[5], "execution_session"] is None  # nothing after the last session
    assert frame.loc[DAYS[4], "target_exit_session"] is None  # its target is not known yet
    assert math.isnan(frame.loc[DAYS[1], "mu_h2"])  # an unusable row has nothing to act on
    assert frame.loc[DAYS[2], "mu_h2"] == 0.003
    assert frame.loc[DAYS[0], "status"] == "INSUFFICIENT_HISTORY"


def test_the_quality_gives_each_share_with_its_numerator_and_denominator() -> None:
    quality = SCRIPT.operational_quality(forecasts())

    assert quality["decisions"] == 6
    # A window that was not served is not a fit that failed.
    assert quality["admissible_windows"] == 5 and quality["usable"] == 4
    assert quality["usable_share"] == pytest.approx(0.8)
    assert quality["arima_accepted"] == quality["volatility_fits"] == 4
    assert (quality["garch_accepted"], quality["ewma_fallbacks"]) == (3, 1)
    assert quality["fallback_share"] == pytest.approx(0.25)
    assert quality["failures"] == {"ARIMA:ARIMA_NOT_CONVERGED": 1}


def test_a_share_without_a_denominator_does_not_exist() -> None:
    nothing = SCRIPT.forecast_frame(
        {DAYS[0]: captured_row(SignalStatus.INSUFFICIENT_HISTORY)}, DAYS
    )

    quality = SCRIPT.operational_quality(nothing)

    assert quality["usable_share"] is None and quality["fallback_share"] is None


def comparison(**overrides: object) -> pd.DataFrame:
    """Return the two rows against D0 of a study in which the filter clearly helped."""
    rows = []
    for costs, difference in (("x1", 0.30), ("x2", 0.25)):
        row: dict[str, object] = {
            "costs": costs,
            "control": SCRIPT.D0,
            "sharpe_difference": difference,
            "interval_low": 0.05,
            "interval_high": 0.55,
            "max_drawdown_sa12": -0.10,
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


GOOD = {"usable_share": 1.0, "fallback_share": 0.0}


def status(frame: pd.DataFrame, **settings: object) -> tuple[str, list[str]]:
    """Return the status of a study with enough pairs, episodes and quality, unless overridden."""
    arguments: dict[str, object] = {
        "forecast_pairs": 1000,
        "completed_episodes": 40,
        "quality": GOOD,
    }
    arguments.update(settings)
    return SCRIPT.hypothesis_status(frame, **arguments)


def test_the_hypothesis_is_supported_only_when_every_criterion_holds() -> None:
    assert status(comparison()) == ("SUPPORTED_RETROSPECTIVE", [])


@pytest.mark.parametrize(
    ("settings", "reason"),
    [
        ({"forecast_pairs": 251}, "evaluable forecast pairs"),
        ({"completed_episodes": 29}, "completed position episodes"),
        ({"quality": {"usable_share": 0.94, "fallback_share": 0.0}}, "usable joint forecasts"),
        ({"quality": {"usable_share": 1.0, "fallback_share": 0.06}}, "EWMA fallbacks"),
        ({"quality": {"usable_share": None, "fallback_share": None}}, "usable joint forecasts"),
    ],
)
def test_sufficiency_and_quality_are_judged_before_anything_else(
    settings: dict[str, object], reason: str
) -> None:
    """Even a study the filter would have won says nothing on too thin a sample."""
    outcome, reasons = status(comparison(), **settings)

    assert outcome == "INSUFFICIENT_EVIDENCE"
    assert any(reason in item for item in reasons)


def test_a_difference_at_or_below_zero_is_not_supported_at_either_cost_level() -> None:
    assert status(comparison(sharpe_difference=0.0))[0] == "NOT_SUPPORTED"
    assert status(comparison(sharpe_difference=-0.2))[0] == "NOT_SUPPORTED"
    outcome, reasons = status(comparison(x2_sharpe_difference=-0.01))
    assert outcome == "NOT_SUPPORTED" and "doubled costs" in reasons[0]


def test_a_positive_difference_that_is_not_told_from_zero_is_uncertain() -> None:
    outcome, reasons = status(comparison(interval_low=-0.05))
    deeper = status(comparison(max_drawdown_sa12=-0.15))
    refused = status(comparison(sharpe_difference=None, bootstrap="refused: flat book"))

    assert outcome == "UNCERTAIN" and "includes zero" in reasons[0]
    assert deeper == ("UNCERTAIN", ["maximum drawdown deeper than D0's"])
    assert refused[0] == "UNCERTAIN" and "refused" in refused[1][0]


def test_the_entry_signals_say_how_often_the_thresholds_were_cleared() -> None:
    pairs = pd.DataFrame(
        {
            "forecast_mean": [0.003, 0.0025, 0.001, -0.001, 0.002],
            "realised": [0.01, -0.02, 0.005, 0.0, 0.03],
        }
    )

    signals = SCRIPT.entry_signals(pairs, 0.002)
    never = SCRIPT.entry_signals(pairs, 0.01)

    assert signals["forecast_above_entry"] == 2  # 20 bp exactly does not enter
    assert signals["share_above_entry"] == pytest.approx(0.4)
    assert signals["forecast_positive"] == 4
    assert signals["mean_realised_after_entry_signal"] == pytest.approx(-0.005)
    assert signals["mean_realised_all"] == pytest.approx(0.005)
    # A threshold nothing clears is a fact to publish, not a number to invent.
    assert never["forecast_above_entry"] == 0
    assert never["mean_realised_after_entry_signal"] is None


def test_a_book_that_never_fell_has_no_sortino_ratio() -> None:
    days = pd.Index([date(2025, 1, 1) + timedelta(days=i) for i in range(5)], dtype="object")
    rising = pd.Series([100.0, 101.0, 102.0, 103.0, 104.0], index=days)
    flat = pd.Series([100.0] * 5, index=days)
    mixed = pd.Series([100.0, 102.0, 101.0, 103.0, 102.0], index=days)

    assert SCRIPT.sortino(rising) is None and SCRIPT.sortino(flat) is None
    returns = mixed.to_numpy()[1:] / mixed.to_numpy()[:-1] - 1.0
    downside = math.sqrt(float(np.mean(np.minimum(returns, 0.0) ** 2)))
    assert SCRIPT.sortino(mixed) == pytest.approx(float(returns.mean()) / downside * math.sqrt(252))


def test_the_history_shows_the_gate_on_the_weight_held_and_the_target_before_the_band() -> None:
    strategy = ArimaGarch()
    column = f"{strategy.forecast_signal().signal_id}[ETF_WORLD]"
    index = pd.Index(DAYS[:4], dtype="object")
    history = pd.DataFrame(
        {
            "close_ETF_WORLD": [100.0, 101.0, 102.0, 103.0],
            column: [0.003, 0.0008, 0.0, float("nan")],
            "held_ETF_WORLD": [0.0, 0.6, 0.6, 0.0],
            "net_equity": [100.0, 100.5, 101.0, 101.0],
        },
        index=index,
    )
    frame = pd.DataFrame(
        {
            "mu_h2": [0.003, 0.0008, 0.0, float("nan")],
            "annualized_volatility": [0.2, 0.2, 0.2, None],
            "volatility_source": ["GARCH", "EWMA_FALLBACK", "GARCH", None],
        },
        index=index,
    )
    opens = pd.Series([99.5, 100.5, 101.5, 102.5], index=index)

    shown = SCRIPT.joint_history(history, frame, opens, strategy)

    assert column not in shown.columns and "target_ETF_WORLD" in shown.columns
    assert list(shown["mu_h2_bp"].iloc[:3]) == pytest.approx([30.0, 8.0, 0.0])
    # In cash and above 20 bp: enters. Held and positive: kept. Held and at zero: out.
    assert list(shown["gate"].iloc[:3]) == [1.0, 1.0, 0.0]
    assert list(shown["theoretical_weight"].iloc[:3]) == pytest.approx([0.6, 0.6, 0.0])
    assert math.isnan(shown["theoretical_weight"].iloc[3])  # no forecast, no target to show
    assert list(shown["ewma_fallback"]) == [0.0, 1.0, 0.0, 0.0]
    assert list(shown["open_ETF_WORLD"]) == [99.5, 100.5, 101.5, 102.5]
    assert list(shown.columns[:2]) == ["close_ETF_WORLD", "open_ETF_WORLD"]
