"""The SA11 study: its participants, its ranking, its register, its verdict and its exports."""

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

from quant_backtester.backtest.runner import StoreChanged, StrategyRunner
from quant_backtester.data.repository import MarketDataRepository
from quant_backtester.demo import demo_runner
from quant_backtester.signals.models import garch
from quant_backtester.strategies import EwmaVolControl, GarchVolControl, RealizedVolControl

pytest.importorskip("arch")

REPOSITORY = Path(__file__).resolve().parents[2]


def load_script(name: str) -> ModuleType:
    """Import a script by its path, its folder on the path as when it is run."""
    scripts = REPOSITORY / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    spec = importlib.util.spec_from_file_location(name, scripts / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


COMPARISON = load_script("run_etf_strategies_comparison")
SCRIPT = load_script("run_garch_study")
DAYS = [date(2024, 1, 1) + timedelta(days=i) for i in range(400)]


def written(returns: np.ndarray) -> pd.Series:
    """Return an equity curve of written session returns."""
    values = 100_000.0 * np.concatenate([[1.0], np.cumprod(1.0 + returns)])
    return pd.Series(values, index=pd.Index(DAYS, dtype="object"), dtype="float64")


# --- participants and conventions --------------------------------------------------------


def test_the_participants_are_the_comparison_books_and_the_control() -> None:
    books = SCRIPT.participants()

    assert SCRIPT.GARCH == "SA11 - GARCH vol control"
    assert SCRIPT.VOL_CONTROL == "SA6 - vol control"
    assert list(books)[:-1] == list(COMPARISON.books())
    assert list(books)[-1] == SCRIPT.EWMA
    assert isinstance(books[SCRIPT.GARCH], GarchVolControl)
    assert isinstance(books[SCRIPT.VOL_CONTROL], RealizedVolControl)
    assert isinstance(books[SCRIPT.EWMA], EwmaVolControl)
    assert books[SCRIPT.GARCH] == GarchVolControl()  # the frozen configuration, unchanged
    for name in ("SA1 - std MA20", "buy & hold World"):
        assert name in books
    assert not any(name.startswith(("SA7", "SA8", "ML1")) for name in books)


def test_without_the_estimator_sa11_is_left_out_and_the_others_still_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(garch.importlib.util, "find_spec", lambda name: None)

    books = COMPARISON.books()

    assert not COMPARISON.garch_available()
    assert "SA11 - GARCH vol control" not in books
    assert "SA6 - vol control" in books and "SA10 - ensemble" in books
    for strategy in books.values():
        strategy.validate()


def test_the_conventions_are_those_fixed_before_the_runs() -> None:
    assert COMPARISON.COMMON_PERIOD == ("2021-04-01", "2026-10-09")
    assert (SCRIPT.BOOTSTRAP_BLOCK, SCRIPT.BOOTSTRAP_DRAWS) == (20, 5000)
    assert (SCRIPT.BOOTSTRAP_SEED, SCRIPT.BOOTSTRAP_LEVEL) == (20261010, 0.95)
    assert SCRIPT.QLIKE_VARIANCE_FLOOR == 1e-12
    assert SCRIPT.FALLBACK_ALERT_SHARE == 0.05


def test_the_stress_doubles_the_three_rates_and_the_commission_floor() -> None:
    base = COMPARISON.EXECUTION
    stressed = SCRIPT.doubled(base)

    assert stressed.costs.commission_rate == 2 * base.costs.commission_rate
    assert stressed.costs.minimum_commission == 2 * base.costs.minimum_commission
    assert stressed.costs.half_spread_rate == 2 * base.costs.half_spread_rate
    assert stressed.costs.slippage_rate == 2 * base.costs.slippage_rate
    assert stressed.sizing is base.sizing


# --- the ranking and the register --------------------------------------------------------


def test_the_ranking_is_dense_keeps_zeros_and_leaves_the_unscored_out() -> None:
    ranks = SCRIPT.ranking(
        {"a": 0.61234, "b": 0.61235, "tie": 0.61235, "zero": 0.0, "market": None, "short": None}
    )

    assert ranks == {"a": 2, "b": 1, "tie": 1, "zero": 3, "market": None, "short": None}
    assert SCRIPT.ranking({}) == {}
    # Unrounded: two scores a display would both print 61% are still ordered.
    assert SCRIPT.ranking({"x": 0.6101, "y": 0.6099}) == {"x": 1, "y": 2}


def curves() -> dict[str, pd.Series]:
    """Return written curves for the fund held, the split, two rules and a flat one."""
    rng = np.random.default_rng(7)
    market = rng.normal(0.0003, 0.01, 399)
    return {
        SCRIPT.HELD: written(market),
        SCRIPT.SPLIT: written(market * 0.9),
        SCRIPT.GARCH: written(market * 0.7 + 0.0002),
        SCRIPT.VOL_CONTROL: written(market * 0.6),
        "flat": written(np.zeros(399)),
    }


def test_the_register_counts_every_trial_and_never_reads_an_undefined_sharpe_as_zero() -> None:
    register = SCRIPT.trial_register(curves())

    assert register["names"] == [SCRIPT.GARCH, SCRIPT.VOL_CONTROL, "flat"]
    assert register["trials"] == 3  # the references are not trials; the flat rule is one
    assert register["excluded"] == ["flat"]
    assert set(register["sharpes"]) == {SCRIPT.GARCH, SCRIPT.VOL_CONTROL}
    assert register["trial_sharpe_std"] > 0.0
    assert register["complete"] is False


def test_one_trial_has_no_dispersion_and_several_without_one_have_no_significance() -> None:
    every = curves()
    single = {SCRIPT.HELD: every[SCRIPT.HELD], SCRIPT.GARCH: every[SCRIPT.GARCH]}
    undefined = {
        SCRIPT.HELD: every[SCRIPT.HELD],
        SCRIPT.GARCH: every[SCRIPT.GARCH],
        "flat": every["flat"],
    }

    assert SCRIPT.trial_register(single)["trial_sharpe_std"] == 0.0
    assert SCRIPT.trial_register(undefined)["trial_sharpe_std"] is None


def test_explicit_trials_reach_the_score_and_are_given_together() -> None:
    every = curves()
    net = {name: every[name] for name in (SCRIPT.HELD, SCRIPT.GARCH, SCRIPT.VOL_CONTROL)}

    few = COMPARISON.quality_details(net, net, trials=1, trial_sharpe_std=0.0)
    many = COMPARISON.quality_details(net, net, trials=200, trial_sharpe_std=0.05)

    assert few[SCRIPT.HELD] is None
    assert many[SCRIPT.GARCH].blocks["significance"] < few[SCRIPT.GARCH].blocks["significance"]
    table = COMPARISON.quality_table(many, trials=200, trial_sharpe_std=0.05)
    assert list(table.index) == list(net)
    assert math.isnan(float(table.loc[SCRIPT.HELD, "score"]))
    assert table.loc[SCRIPT.HELD, "diagnostics"] == "market_fund_not_scored"
    assert set(table["trials"]) == {200} and set(table["version"]) == {"v1"}
    assert {"block_market", "block_significance", "deflated_sharpe_probability"} <= set(table)
    with pytest.raises(ValueError, match="together"):
        COMPARISON.quality_details(net, net, trials=3)


# --- the economic test -------------------------------------------------------------------


def comparison_row(**overrides: object) -> dict[str, object]:
    """Return a row in which SA11 clearly beat its control, unless overridden."""
    row: dict[str, object] = {
        "costs": "x1",
        "control": SCRIPT.VOL_CONTROL,
        "sharpe_sa11": 0.9,
        "sharpe_control": 0.6,
        "max_drawdown_sa11": -0.10,
        "max_drawdown_control": -0.12,
        "interval_low": 0.05,
        "interval_high": 0.55,
        "bootstrap": "ok",
    }
    row.update(overrides)
    return row


def test_the_hypothesis_is_supported_only_when_every_criterion_holds() -> None:
    clear = pd.DataFrame([comparison_row(), comparison_row(control=SCRIPT.EWMA, costs="x2")])

    assert SCRIPT.verdict(clear) == ("SUPPORTED", [])


def test_an_interval_that_includes_zero_is_uncertain_not_a_confirmation() -> None:
    frame = pd.DataFrame([comparison_row(interval_low=-0.1)])

    outcome, reasons = SCRIPT.verdict(frame)

    assert outcome == "UNCERTAIN"
    assert "interval includes zero" in reasons[0]


def test_a_refused_bootstrap_is_reported_and_never_read_as_zero() -> None:
    frame = pd.DataFrame([comparison_row(bootstrap="refused: no Sharpe ratio")])

    outcome, reasons = SCRIPT.verdict(frame)

    assert outcome == "UNCERTAIN"
    assert "refused" in reasons[0]


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"sharpe_sa11": 0.6}, "net Sharpe not above"),
        ({"sharpe_sa11": 0.5}, "net Sharpe not above"),
        ({"max_drawdown_sa11": -0.15}, "maximum drawdown deeper"),
        ({"costs": "x2", "sharpe_sa11": 0.1}, "at costs x2"),
    ],
)
def test_one_criterion_of_refutation_refutes(overrides: dict[str, object], reason: str) -> None:
    frame = pd.DataFrame([comparison_row(), comparison_row(**overrides)])

    outcome, reasons = SCRIPT.verdict(frame)

    assert outcome == "REFUTED"
    assert any(reason in item for item in reasons)


def test_the_fund_held_is_reported_and_is_not_part_of_the_test() -> None:
    frame = pd.DataFrame([comparison_row(), comparison_row(control=SCRIPT.HELD, sharpe_sa11=0.1)])

    assert SCRIPT.verdict(frame)[0] == "SUPPORTED"


def test_a_sharpe_difference_on_a_flat_book_is_refused_with_its_cause(monkeypatch) -> None:
    monkeypatch.setattr(SCRIPT, "BOOTSTRAP_DRAWS", 100)
    every = curves()

    refused = SCRIPT.sharpe_difference(every[SCRIPT.GARCH], every["flat"])
    measured = SCRIPT.sharpe_difference(every[SCRIPT.GARCH], every[SCRIPT.VOL_CONTROL])

    assert isinstance(refused, str) and refused.startswith("refused:")
    assert measured.block == 20 and measured.seed == 20261010 and measured.level == 0.95
    assert measured.low <= measured.estimate <= measured.high


# --- small helpers -----------------------------------------------------------------------


def test_every_calendar_year_is_reported_with_its_sessions() -> None:
    days = [date(2024, 12, 30), date(2024, 12, 31), date(2025, 1, 2), date(2025, 1, 3)]
    curve = pd.Series([100.0, 110.0, 99.0, 121.0], index=pd.Index(days, dtype="object"))

    table = SCRIPT.yearly_frame({"a": curve})

    assert table.loc["a", "2024"] == pytest.approx(0.10)
    assert table.loc["a", "2025"] == pytest.approx(0.10)  # from the last close of 2024
    assert list(table.loc["sessions"]) == [2.0, 2.0]


def test_an_annualised_volatility_becomes_a_daily_variance() -> None:
    variance = SCRIPT.daily_variance(pd.Series([0.20, 0.0]))

    assert variance.iloc[0] == pytest.approx(0.04 / 252)
    assert variance.iloc[1] == 0.0


def test_a_missing_figure_is_printed_as_such_in_a_table() -> None:
    frame = pd.DataFrame(
        {"score": [0.5, None], "rank": pd.array([1, None], dtype="Int64")}, index=["a", "b"]
    ).rename_axis("book")

    text = SCRIPT.markdown_table(frame, [("rank", "rank", "{}"), ("score", "score", "{:.0%}")])

    assert text.splitlines()[0] == "| book | rank | score |"
    assert text.splitlines()[2] == "| a | 1 | 50% |"
    assert text.splitlines()[3] == "| b | n/a | n/a |"


def test_a_book_is_named_by_its_code() -> None:
    assert SCRIPT.code_of("SA11 - GARCH vol control") == "SA11"
    assert SCRIPT.code_of("buy & hold World") == "buy & hold World"


# --- diagnostics and exports, on the offline demo market ---------------------------------

DEMO_PERIOD = ("2025-09-01", "2025-12-31")
SHORT = GarchVolControl(
    instrument_id="FUND_A", estimation_returns=120, ewma_seed_returns=20, target_volatility=0.05
)


@pytest.fixture(scope="module")
def demo(tmp_path_factory: pytest.TempPathFactory) -> StrategyRunner:
    """Return a runner over the offline synthetic market."""
    return demo_runner(tmp_path_factory.mktemp("garch_study") / "store", seed=20240101)


def test_the_diagnostics_reproduce_each_decision_and_never_see_its_target(
    demo: StrategyRunner,
) -> None:
    result = demo.run(SHORT, ("FUND_A", "FUND_B"), *DEMO_PERIOD)

    diagnostics = SCRIPT.forecast_diagnostics(result, SHORT)
    summary = SCRIPT.fallback_summary(diagnostics)

    assert len(diagnostics) == len(result.records())
    assert list(diagnostics["origin"]) == [record.session_date for record in result.records()]
    assert set(diagnostics["window_status"]) == {"OK"}
    # The window ends on the session decided on: nothing of the target is in it.
    assert (diagnostics["fit_end"] == diagnostics["origin"]).all()
    assert set(diagnostics["window_closes"]) == {121} and set(diagnostics["n_returns"]) == {120}
    assert set(diagnostics["forecast_source"]) <= {"GARCH", "EWMA_FALLBACK"}
    accepted = diagnostics.loc[diagnostics["forecast_source"] == "GARCH"]
    assert (accepted["persistence"] < 1.0).all() and (accepted["nu"] > 2.0).all()
    recomputed = np.sqrt(252.0 * diagnostics["forecast_variance"].astype("float64"))
    assert np.allclose(recomputed, diagnostics["annualized_volatility"].astype("float64"))
    assert summary["valid_windows"] == len(diagnostics)
    assert summary["garch"] + summary["fallback"] == len(diagnostics)
    assert summary["reserve"] == (summary["fallback_share"] > 0.05)
    assert sum(count for _, _, count in summary["episodes"]) == summary["fallback"]


def test_the_history_of_a_book_holds_what_it_read_held_and_was_worth(
    demo: StrategyRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    funds = ("FUND_A", "FUND_B")
    monkeypatch.setattr(COMPARISON, "UNIVERSE", funds)
    monkeypatch.setattr(SCRIPT, "UNIVERSE", funds)
    control = EwmaVolControl(
        instrument_id="FUND_A", window_returns=120, seed_returns=20, target_volatility=0.05
    )
    strategies = {"garch": SHORT, "ewma": control}
    results = {name: demo.run(book, funds, *DEMO_PERIOD) for name, book in strategies.items()}

    histories = SCRIPT.book_histories(results, strategies)
    diagnostics = SCRIPT.forecast_diagnostics(results["garch"], SHORT)

    history = histories["garch"]
    assert list(history.index) == list(results["garch"].equity().index)
    assert {"close_FUND_A", "garch11_t_vol_120r[FUND_A]", "target_FUND_A", "held_FUND_A"} <= set(
        history.columns
    )
    assert "ewma94_vol_120r[FUND_A]" in histories["ewma"].columns
    assert np.allclose(history["net_equity"], results["garch"].equity())
    # The signal exported is the forecast the diagnostics give, decision by decision.
    assert np.allclose(
        history["garch11_t_vol_120r[FUND_A]"].to_numpy(dtype="float64"),
        diagnostics["annualized_volatility"].to_numpy(dtype="float64"),
    )


def test_reading_a_run_back_on_a_revised_store_is_refused(
    tmp_path: Path,
) -> None:
    runner = demo_runner(tmp_path / "store", seed=20240101)
    result = runner.run(SHORT, ("FUND_A", "FUND_B"), "2025-12-01", "2025-12-31")
    repository = MarketDataRepository(tmp_path / "store")
    revised = repository.load_checked_bars("FUND_A")
    revised.loc[revised.index[-1], "close"] = revised["close"].iloc[-1] * 1.01
    repository.save_checked_bars("FUND_A", revised)

    with pytest.raises(StoreChanged, match="no longer holds"):
        SCRIPT.forecast_diagnostics(result, SHORT)
