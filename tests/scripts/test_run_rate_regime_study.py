"""The rate regime study: its windows, its paper registry and what its figure draws."""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path
from types import ModuleType

import pandas as pd
import pytest

from quant_backtester.data.instruments import InstrumentRegistry

REPOSITORY = Path(__file__).resolve().parents[2]
D1, D2, D3 = date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)


def load_script() -> ModuleType:
    """Import ``scripts/run_rate_regime_study.py`` by its path.

    The script imports the golden cross one beside it by name, as it does when
    it is run, so its folder is put on the path first. The module is registered
    before it is executed: its dataclass looks its own module up by name.
    """
    scripts = REPOSITORY / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    path = scripts / "run_rate_regime_study.py"
    spec = importlib.util.spec_from_file_location("run_rate_regime_study", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_validation_window_ends_before_the_discovery_window_starts() -> None:
    windows = {window.role: window for window in load_script().WINDOWS}
    assert windows["validation"].end < windows["discovery"].start
    assert windows["validation"].paper
    assert not windows["discovery"].paper


def test_the_three_books_hold_the_same_fund_with_the_parameters_of_the_hypothesis() -> None:
    script = load_script()
    books = script.strategies("ETF_WORLD")
    assert list(books) == [script.HOLD, script.TREND, script.REGIME]
    regime = books[script.REGIME]
    assert regime.instrument_id == "ETF_WORLD"
    assert (regime.trend_sessions, regime.correlation_pairs) == (200, 60)
    assert (regime.stress_observations, regime.stress_minimum) == (60, 1.5)
    assert books[script.TREND].window_sessions == regime.trend_sessions


def test_a_paper_registry_makes_one_index_tradable_and_leaves_the_original_alone(
    instruments: InstrumentRegistry,
) -> None:
    paper = load_script().paper_registry(instruments, "IDX_US")
    assert paper.get("IDX_US").tradable
    assert not instruments.get("IDX_US").tradable
    assert not paper.get("RATE_US").tradable
    assert [item.id for item in paper.list_all()] == [item.id for item in instruments.list_all()]


def test_a_paper_registry_of_an_unknown_instrument_is_refused(
    instruments: InstrumentRegistry,
) -> None:
    with pytest.raises(KeyError):
        load_script().paper_registry(instruments, "NOWHERE")


def test_the_trailing_average_is_the_mean_of_the_last_closes() -> None:
    closes = pd.Series([10.0, 20.0, 30.0], index=[D1, D2, D3])
    average = load_script().trailing_average(closes, 2)
    assert pd.isna(average.iloc[0])
    assert list(average.iloc[1:]) == [15.0, 25.0]


def test_the_figure_draws_the_price_the_trades_and_the_profit_of_each_book() -> None:
    script = load_script()
    closes = pd.Series([10.0, 20.0, 30.0], index=[D1, D2, D3])
    fills = pd.DataFrame({"session_date": [D1, D3], "side": ["BUY", "SELL"]})
    profits = {
        script.HOLD: pd.Series([0.0, 5.0, 9.0], index=[D1, D2, D3]),
        script.REGIME: pd.Series([0.0, 4.0, 4.0], index=[D1, D2, D3]),
    }
    figure = script.study_figure(
        closes, script.trailing_average(closes, 2), {D1, D2}, fills, profits, title="a title"
    )
    price_axes, pnl_axes = figure.axes
    assert price_axes.get_title() == "a title"
    assert price_axes.get_legend_handles_labels()[1] == [
        "invested",
        "close",
        "MA200",
        "buy",
        "sell",
    ]
    buys, sells = price_axes.collections[1], price_axes.collections[2]
    assert [point[1] for point in buys.get_offsets()] == [10.0]
    assert [point[1] for point in sells.get_offsets()] == [30.0]
    assert pnl_axes.get_legend_handles_labels()[1] == [script.HOLD, script.REGIME]
    assert [float(value) for value in pnl_axes.lines[1].get_ydata()] == [0.0, 4.0, 4.0]


def test_a_figure_of_no_session_is_refused() -> None:
    script = load_script()
    empty = pd.Series([], index=[], dtype="float64")
    fills = pd.DataFrame({"session_date": [], "side": []})
    with pytest.raises(ValueError, match="nothing to draw"):
        script.study_figure(empty, empty, set(), fills, {}, title="empty")
