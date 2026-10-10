"""The review diagnostics: stays in the market, the fill delay, the split against a basket."""

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

from quant_backtester.strategies import ETFEnsemble, EwmaVolControl, FixedWeights

pytest.importorskip("arch")

REPOSITORY = Path(__file__).resolve().parents[2]


def load_script() -> ModuleType:
    """Import ``scripts/run_review_diagnostics.py``, its folder on the path as when run."""
    scripts = REPOSITORY / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    path = scripts / "run_review_diagnostics.py"
    spec = importlib.util.spec_from_file_location("run_review_diagnostics", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SCRIPT = load_script()
DAYS = [date(2026, 3, 2) + timedelta(days=index) for index in range(8)]


def history(held: list[float], equity: list[float], closes: list[float]) -> pd.DataFrame:
    """Return the history of a book holding one fund at the given closing weights."""
    return pd.DataFrame(
        {
            "close_ETF_WORLD": closes,
            "close_ETF_SP500_PEA": [10.0] * len(DAYS),
            "held_ETF_WORLD": held,
            "net_equity": equity,
            "gross_equity": equity,
        },
        index=pd.Index(DAYS, dtype="object", name="session_date"),
    )


def fills_of(rows: list[tuple[int, str, float, float, float]]) -> pd.DataFrame:
    """Return executions from ``(day, side, open, value, cost)``."""
    return pd.DataFrame(
        [
            {
                "session_date": DAYS[day],
                "instrument_id": "ETF_WORLD",
                "side": side,
                "market_price": price,
                "traded_value": value,
                "total_cost": cost,
            }
            for day, side, price, value, cost in rows
        ],
        columns=[
            "session_date",
            "instrument_id",
            "side",
            "market_price",
            "traded_value",
            "total_cost",
        ],
    )


BOOK = history(
    held=[0.0, 0.5, 0.5, 0.0, 0.0, 1.0, 1.0, 1.0],
    equity=[100.0, 99.0, 104.0, 103.0, 103.0, 102.0, 110.0, 108.0],
    closes=[100.0, 100.0, 110.0, 108.0, 108.0, 108.0, 116.0, 114.0],
)
FILLS = fills_of(
    [(1, "BUY", 102.0, 50.0, 0.5), (3, "SELL", 108.0, 52.0, 0.5), (5, "BUY", 109.0, 103.0, 1.0)]
)


def test_a_stay_runs_from_the_valuation_before_its_entry_to_the_first_one_back_in_cash() -> None:
    stays = SCRIPT.episodes(BOOK, FILLS)

    first, second = stays.to_dict(orient="records")
    assert (first["entry"], first["exit"], first["open"]) == (DAYS[1], DAYS[3], False)
    assert first["valuations_held"] == 2
    # From 100 before the buy to 103 after the sale: both fills and their costs inside.
    assert first["net_return"] == pytest.approx(0.03)
    assert first["fund_change"] == pytest.approx(0.08)
    assert (first["orders"], first["costs_eur"]) == (2, 1.0)
    # A stay still running at the last session is measured to it, and said to be open.
    assert (second["entry"], second["exit"], second["open"]) == (DAYS[5], DAYS[7], True)
    assert second["net_return"] == pytest.approx(108.0 / 103.0 - 1.0)
    assert second["orders"] == 1


def test_the_stays_compound_to_the_return_of_a_book_whose_cash_earns_nothing() -> None:
    summary = SCRIPT.episode_summary(SCRIPT.episodes(BOOK, FILLS))

    assert summary["stays"] == 2 and summary["gains"] == 2 and summary["losses"] == 0
    assert summary["compounded"] == pytest.approx(108.0 / 100.0 - 1.0)
    assert summary["costs_eur"] == 2.0
    assert SCRIPT.episode_summary(SCRIPT.episodes(BOOK.assign(held_ETF_WORLD=0.0), FILLS)) == {
        "stays": 0
    }


def test_stays_a_few_sessions_apart_are_one_panic() -> None:
    stays = SCRIPT.episodes(BOOK, FILLS)

    together = SCRIPT.panics(stays, BOOK)

    assert len(together) == 1
    assert together["stays"].iloc[0] == 2
    assert together["net_return"].iloc[0] == pytest.approx(1.03 * 108.0 / 103.0 - 1.0)
    assert (together["first_entry"].iloc[0], together["last_exit"].iloc[0]) == (DAYS[1], DAYS[7])


def test_the_delay_is_what_the_overnight_move_did_to_each_order() -> None:
    effect = SCRIPT.delay_effect(BOOK, FILLS, 100.0)

    # A buy filled 2% above the close hurt; so did a sale 108/110 under it and a
    # buy 109/108 above it.
    bought_high = -50.0 * 0.02
    sold_low = 52.0 * (108.0 / 110.0 - 1.0)
    bought_higher = -103.0 * (109.0 / 108.0 - 1.0)
    total = bought_high + sold_low + bought_higher
    assert effect["orders"] == 3
    assert effect["hurt_eur"] == pytest.approx(total)
    assert effect["helped_eur"] == 0.0
    assert effect["effect_eur"] == pytest.approx(total)
    assert effect["effect_share"] == pytest.approx(total / 100.0)
    helped = SCRIPT.delay_effect(BOOK, fills_of([(3, "SELL", 115.5, 50.0, 0.0)]), 100.0)
    assert helped["effect_eur"] == pytest.approx(50.0 * 0.05)  # sold 5% above the close


def test_the_split_against_a_basket_adds_up_to_the_net_return() -> None:
    rng = np.random.default_rng(2)
    days = [date(2025, 1, 1) + timedelta(days=index) for index in range(60)]
    world = 100.0 * np.cumprod(1.0 + rng.normal(0.001, 0.01, 60))
    other = 20.0 * np.cumprod(1.0 + rng.normal(0.001, 0.012, 60))
    frame = pd.DataFrame(
        {
            "close_ETF_WORLD": world,
            "close_ETF_SP500_PEA": other,
            "held_ETF_WORLD": 0.5,
            "held_ETF_SP500_PEA": 0.3,
            "gross_equity": 100.0 * np.cumprod(1.0 + rng.normal(0.0008, 0.008, 60)),
        },
        index=pd.Index(days, dtype="object"),
    )
    frame["net_equity"] = frame["gross_equity"] * np.linspace(1.0, 0.99, 60)
    basket = {"ETF_WORLD": 0.5, "ETF_SP500_PEA": 0.5}

    split = SCRIPT.basket_attribution(frame, basket, 0.05)

    parts = ("basket_closes", "exposure", "choice", "execution", "costs")
    assert math.fsum(split[part] for part in parts) == pytest.approx(split["book_net"])
    assert split["book_net"] == pytest.approx(
        math.log(frame["net_equity"].iloc[-1] / frame["net_equity"].iloc[0])
    )
    assert split["costs"] == pytest.approx(math.log(0.99))
    assert split["basket_net"] == pytest.approx(math.log(1.05))
    # The basket itself, fully held at its own weights, has nothing to attribute.
    same = frame.assign(held_ETF_WORLD=0.5, held_ETF_SP500_PEA=0.5)
    neutral = SCRIPT.basket_attribution(same, basket, None)
    assert neutral["exposure"] == pytest.approx(0.0, abs=1e-12)
    assert neutral["choice"] == pytest.approx(0.0, abs=1e-12)
    assert neutral["basket_net"] is None


def test_a_tilt_that_foresaw_the_relative_return_would_show_it() -> None:
    rng = np.random.default_rng(4)
    days = [date(2025, 1, 1) + timedelta(days=index) for index in range(300)]
    relative = rng.normal(0.0, 0.01, 300)
    frame = pd.DataFrame(
        {
            "close_ETF_WORLD": 100.0 * np.cumprod(1.0 + relative),
            "close_ETF_SP500_PEA": 50.0,
        },
        index=pd.Index(days, dtype="object"),
    )
    returns = frame["close_ETF_WORLD"] / frame["close_ETF_WORLD"].shift(1) - 1.0
    frame["foresees"] = returns.shift(-2)  # the first whole session after the fill
    frame["noise"] = rng.normal(0.0, 1.0, 300)

    seen = SCRIPT.tilt_diagnostics(frame, "foresees", "ETF_WORLD", "ETF_SP500_PEA")
    blind = SCRIPT.tilt_diagnostics(frame, "noise", "ETF_WORLD", "ETF_SP500_PEA")

    assert seen["pearson_after_fill_1"] == pytest.approx(1.0)
    assert abs(blind["pearson_after_fill_1"]) < 0.2
    assert blind["decisions"] == 300
    assert blind["mean_run"] == pytest.approx(300 / (blind["sign_changes"] + 1))


def test_a_control_holds_the_average_weights_a_book_was_seen_to_hold() -> None:
    control = SCRIPT.control_of("SA6 - vol control", BOOK)

    assert isinstance(control, FixedWeights)
    assert control.weights == (("ETF_WORLD", 0.5),)
    assert control.strategy_id == "research_control_sa6___vol_control"
    assert control.rebalance_band == 0.03


def test_the_recovery_is_counted_from_the_peak_and_left_open_when_it_has_not_come() -> None:
    recovered = pd.Series([100.0, 90.0, 100.0], index=pd.Index(DAYS[:3], dtype="object"))
    still_under = pd.Series([100.0, 90.0, 95.0], index=pd.Index(DAYS[:3], dtype="object"))

    assert SCRIPT.recovery_days(recovered) == (pytest.approx(-0.10), "2")
    assert SCRIPT.recovery_days(still_under) == (pytest.approx(-0.10), "2 (en cours)")
    assert SCRIPT.recovery_days(recovered.iloc[:1]) == (0.0, "0")


def test_the_variants_are_the_ensemble_less_one_rule_and_the_other_decays() -> None:
    base = ETFEnsemble(enable_factors=False, enable_monetary=False)

    variants = SCRIPT.ensemble_variants()
    decays = SCRIPT.ewma_variants()

    assert list(variants) == [
        "sans momentum",
        "sans trend",
        "sans pullback",
        "sans relative",
        "sans relief",
        "sans contrôle de risque",
    ]
    without = variants["sans trend"]
    assert isinstance(without, ETFEnsemble)
    assert without.trend_budget == 0.0 and without.momentum_budget == base.momentum_budget
    # The budget removed stays in cash: nothing else is raised to fill it.
    assert without.relative_budget == base.relative_budget
    uncontrolled = variants["sans contrôle de risque"]
    assert isinstance(uncontrolled, ETFEnsemble)
    assert uncontrolled.target_volatility == 10.0 and uncontrolled.trend_budget == base.trend_budget
    ids = {strategy.strategy_id for strategy in (*variants.values(), *decays.values())}
    assert len(ids) == 8 and all(name.startswith("research_") for name in ids)
    assert [
        strategy.decay for strategy in decays.values() if isinstance(strategy, EwmaVolControl)
    ] == [
        0.90,
        0.97,
    ]
    for strategy in (*variants.values(), *decays.values()):
        strategy.validate()


def test_a_missing_figure_is_printed_as_such() -> None:
    frame = pd.DataFrame({"a": [0.5, float("nan")]}, index=["x", "y"])

    lines = SCRIPT.table(frame, [("a", "A", "{:.0%}")], "Livre").splitlines()

    assert lines[0] == "| Livre | A |"
    assert lines[2:] == ["| x | 50% |", "| y | n/a |"]
