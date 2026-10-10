"""The review diagnostics: stays in the market, the fill delay, the split against a basket."""

from __future__ import annotations

import importlib.util
import math
import sys
from datetime import date, timedelta
from pathlib import Path
from types import MappingProxyType, ModuleType, SimpleNamespace

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
    """Return executions from ``(day, side, open, quantity, cost)``.

    The traded value is the quantity at a fill price one per cent away from
    the open, on the side that costs: what a spread and a slippage do.
    """
    columns = [
        "session_date",
        "instrument_id",
        "side",
        "quantity",
        "market_price",
        "traded_value",
        "total_cost",
    ]
    return pd.DataFrame(
        [
            {
                "session_date": DAYS[day],
                "instrument_id": "ETF_WORLD",
                "side": side,
                "quantity": quantity,
                "market_price": price,
                "traded_value": quantity * price * (1.01 if side == "BUY" else 0.99),
                "total_cost": cost,
            }
            for day, side, price, quantity, cost in rows
        ],
        columns=columns,
    )


BOOK = history(
    held=[0.0, 0.5, 0.5, 0.0, 0.0, 1.0, 1.0, 1.0],
    equity=[100.0, 99.0, 104.0, 103.0, 103.0, 102.0, 110.0, 108.0],
    closes=[100.0, 100.0, 110.0, 108.0, 108.0, 108.0, 116.0, 114.0],
)
FILLS = fills_of(
    [(1, "BUY", 102.0, 0.5, 0.5), (3, "SELL", 108.0, 0.5, 0.5), (5, "BUY", 109.0, 1.0, 1.0)]
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
    # One stay was closed, with both of its fills; the other still runs at the last
    # session and is marked to it, without a final sale: they are counted apart.
    assert (summary["completed"], summary["open"]) == (1, 1)
    assert (summary["completed_gains"], summary["completed_losses"]) == (1, 0)
    assert summary["completed_share_of_gains"] == 1.0
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


def test_the_gap_is_the_overnight_move_at_the_quantity_of_each_order() -> None:
    effect = SCRIPT.delay_effect(BOOK, FILLS, 100.0)

    # Half a share bought 2 above the close, half a share sold 2 under it, a share
    # bought 1 above it: three gaps against the order, in euros of price, not of value.
    total = -0.5 * (102.0 - 100.0) + 0.5 * (108.0 - 110.0) - 1.0 * (109.0 - 108.0)
    assert effect["orders"] == 3 and effect["excluded_ex_date"] == 0
    assert effect["hurt_eur"] == pytest.approx(total) == pytest.approx(-3.0)
    assert effect["helped_eur"] == 0.0
    assert effect["effect_eur"] == pytest.approx(total)
    assert effect["effect_share"] == pytest.approx(total / 100.0)
    helped = SCRIPT.delay_effect(BOOK, fills_of([(3, "SELL", 115.5, 2.0, 0.0)]), 100.0)
    assert helped["effect_eur"] == pytest.approx(2.0 * 5.5)  # sold 5.5 above the close


def test_the_gap_is_measured_on_the_price_and_leaves_the_costs_apart() -> None:
    """One share bought at 110 after a close at 100 is a gap of 10, not of 11.

    The traded value holds the fill price, spread and slippage included: taking
    it for the quantity counted the explicit costs a second time.
    """
    closes = [100.0, 100.0, 110.0, 108.0, 108.0, 108.0, 116.0, 114.0]
    book = history([0.0] * 8, [100.0] * 8, closes)
    one_share = fills_of([(3, "BUY", 121.0, 1.0, 0.0)])
    assert one_share["traded_value"].iloc[0] == pytest.approx(122.21)  # not what is measured

    effect = SCRIPT.delay_effect(book, one_share, 100.0)

    assert effect["effect_eur"] == pytest.approx(-(121.0 - 110.0))
    assert effect["effect_eur"] != pytest.approx(-one_share["traded_value"].iloc[0] * 0.1)


def test_an_order_filled_on_an_ex_date_is_left_out_and_counted() -> None:
    """A raw close before a detachment and a raw open after it are not on one basis."""
    ex_dates = {"ETF_WORLD": frozenset({DAYS[3]})}

    effect = SCRIPT.delay_effect(BOOK, FILLS, 100.0, ex_dates=ex_dates)

    assert (effect["orders"], effect["excluded_ex_date"]) == (2, 1)
    assert effect["effect_eur"] == pytest.approx(-0.5 * 2.0 - 1.0 * 1.0)


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

    parts = ("basket_closes", "exposure", "choice", "residual", "costs")
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


def test_the_residual_of_the_split_is_not_a_measure_of_execution() -> None:
    """A book in cash buys one share at the open, at the close of the day before.

    No gap, no fee, and the fund gains 10% by the close. The split on closing
    weights sees a book that held nothing the day before: it calls the whole
    gain a residual and gives the exposure a loss of as much. That residual is
    the effect of the purchase, not a quality of its execution.
    """
    days = pd.Index([date(2025, 1, 1), date(2025, 1, 2)], dtype="object")
    frame = pd.DataFrame(
        {
            "close_ETF_WORLD": [100.0, 110.0],
            "held_ETF_WORLD": [0.0, 1.0],
            "gross_equity": [100.0, 110.0],
            "net_equity": [100.0, 110.0],
        },
        index=days,
    )

    split = SCRIPT.basket_attribution(frame, {"ETF_WORLD": 1.0}, None)

    gain = math.log(1.1)
    assert split["basket_closes"] == pytest.approx(gain)
    assert split["exposure"] == pytest.approx(-gain)
    assert split["choice"] == pytest.approx(0.0, abs=1e-15)
    assert split["residual"] == pytest.approx(gain)
    assert split["costs"] == 0.0 and split["book_net"] == pytest.approx(gain)
    assert "execution" not in split  # the line no longer carries a name it cannot bear


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


def test_every_decision_with_its_future_closes_makes_a_pair_the_first_included() -> None:
    """The pairs are checked by their dates and their number, not by a correlation."""
    rng = np.random.default_rng(6)
    days = [date(2025, 1, 1) + timedelta(days=index) for index in range(300)]
    frame = pd.DataFrame(
        {
            "close_ETF_WORLD": 100.0 * np.cumprod(1.0 + rng.normal(0.0, 0.01, 300)),
            "close_ETF_SP500_PEA": 50.0 * np.cumprod(1.0 + rng.normal(0.0, 0.01, 300)),
            "signal": rng.normal(0.0, 1.0, 300),
        },
        index=pd.Index(days, dtype="object"),
    )

    found = SCRIPT.tilt_diagnostics(frame, "signal", "ETF_WORLD", "ETF_SP500_PEA")

    # A decision at t needs the close of t + 1, of t + 2, or of t + 6: 299, 298, 294 pairs.
    assert (found["pairs_next_1"], found["pairs_after_fill_1"], found["pairs_after_fill_5"]) == (
        299,
        298,
        294,
    )
    for horizon, last in (("next_1", 298), ("after_fill_1", 297), ("after_fill_5", 293)):
        assert found[f"first_pair_{horizon}"] == days[0]  # the first decision is evaluated
        assert found[f"last_pair_{horizon}"] == days[last]


def test_the_five_session_return_is_compounded_fund_by_fund() -> None:
    rng = np.random.default_rng(8)
    days = [date(2025, 1, 1) + timedelta(days=index) for index in range(200)]
    world = 100.0 * np.cumprod(1.0 + rng.normal(0.0, 0.02, 200))
    other = 50.0 * np.cumprod(1.0 + rng.normal(0.0, 0.02, 200))
    frame = pd.DataFrame(
        {"close_ETF_WORLD": world, "close_ETF_SP500_PEA": other},
        index=pd.Index(days, dtype="object"),
    )
    compounded = [
        world[t + 6] / world[t + 1] - other[t + 6] / other[t + 1] if t + 6 < 200 else np.nan
        for t in range(200)
    ]
    frame["foresees"] = compounded

    found = SCRIPT.tilt_diagnostics(frame, "foresees", "ETF_WORLD", "ETF_SP500_PEA")

    assert found["pearson_after_fill_5"] == pytest.approx(1.0)
    assert found["pairs_after_fill_5"] == 194


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


# --- what the second verification asked for ----------------------------------------------


def run_like(**changes: object) -> SimpleNamespace:
    """Return what a new run exposes of its provenance, as the study recorded its own."""
    costs = MappingProxyType(
        {
            "commission_rate": 0.0005,
            "minimum_commission": 1.0,
            "half_spread_rate": 0.0003,
            "slippage_rate": 0.0002,
        }
    )
    fields: dict[str, object] = {
        "data_state": SimpleNamespace(digest="750c23dfffc3" + "0" * 52),
        "configuration": {"initial_cash": 100_000.0, "execution": {"costs": costs}},
        "start": date(2021, 4, 1),
        "end": date(2026, 10, 9),
    }
    fields.update(changes)
    return SimpleNamespace(**fields)


STUDY = {
    "data_state": "750c23dfffc3" + "0" * 52,
    "initial_cash": 100000.0,
    "period": {"start": "2021-04-01", "end": "2026-10-09"},
    # A study writes its execution model out as text, mappingproxy and all.
    "execution": (
        "{'fill_model': 'DECISION_CLOSE_QUANTITIES', 'costs': mappingproxy({'commission_rate': "
        "0.0005, 'minimum_commission': 1.0, 'half_spread_rate': 0.0003, 'slippage_rate': "
        "0.0002}), 'minimum_trade_value': 0.0}"
    ),
}


def test_a_run_on_the_store_and_the_costs_of_the_study_is_compared() -> None:
    SCRIPT.require_same_provenance(STUDY, run_like())

    assert SCRIPT.cost_terms(STUDY["execution"]) == SCRIPT.cost_terms(
        run_like().configuration["execution"]
    )
    assert SCRIPT.cost_terms(STUDY["execution"]) == {
        "commission_rate": 0.0005,
        "minimum_commission": 1.0,
        "half_spread_rate": 0.0003,
        "slippage_rate": 0.0002,
    }


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"data_state": SimpleNamespace(digest="f" * 64)}, "read the store 750c23dfffc3"),
        ({"configuration": {"initial_cash": 50_000.0, "execution": {}}}, "initial cash"),
        ({"end": date(2026, 9, 30)}, "period 2021-04-01 to 2026-10-09 in the study"),
        (
            {
                "configuration": {
                    "initial_cash": 100_000.0,
                    "execution": {"costs": {"commission_rate": 0.001}},
                }
            },
            "execution costs",
        ),
    ],
)
def test_a_run_that_does_not_follow_from_the_same_data_is_refused(
    changes: dict[str, object], message: str
) -> None:
    """Another store, another cash, other dates or other costs: no table is assembled."""
    with pytest.raises(RuntimeError, match=message):
        SCRIPT.require_same_provenance(STUDY, run_like(**changes))


def test_a_run_on_another_period_by_design_must_still_read_the_same_store() -> None:
    elsewhere = run_like(start=date(2025, 1, 2), end=date(2026, 9, 30))

    SCRIPT.require_same_provenance(STUDY, elsewhere, same_period=False)
    with pytest.raises(RuntimeError, match="read the store"):
        SCRIPT.require_same_provenance(
            STUDY,
            run_like(data_state=SimpleNamespace(digest="e" * 64)),
            same_period=False,
        )


def test_a_stay_still_running_is_named_with_its_dates_and_no_final_sale() -> None:
    stays = SCRIPT.episodes(BOOK, FILLS)
    frames = {"episodes_sa1": stays, "episodes_sa4": stays.iloc[:1], "episodes_sa9": stays.iloc[:0]}

    lines = SCRIPT.open_stays_lines(frames)

    assert len(lines) == 2 and lines[-1] == ""
    assert lines[0].startswith("- SA1 - std MA20 : un séjour encore ouvert")
    assert str(DAYS[5]) in lines[0] and "+4.85%" in lines[0] and "sans vente finale" in lines[0]
    assert SCRIPT.open_stays_lines({name: stays.iloc[:1] for name in frames}) == []


def test_the_frozen_model_and_its_recalibration_never_share_a_label() -> None:
    assert SCRIPT.FROZEN != SCRIPT.RECALIBRATED
    assert "modèle figé" in SCRIPT.FROZEN and "recalibrée" in SCRIPT.RECALIBRATED
    assert SCRIPT.COST_STRESS == 2.0
