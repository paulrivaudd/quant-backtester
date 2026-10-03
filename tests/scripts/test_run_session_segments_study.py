"""The session segments study: what its figure draws and what its printout says."""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path
from types import ModuleType

import pandas as pd
import pytest

from quant_backtester.analytics.segments import segment_books, segment_returns, segment_summary

REPOSITORY = Path(__file__).resolve().parents[2]
D1, D2, D3 = date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)


def load_script() -> ModuleType:
    """Import ``scripts/run_session_segments_study.py`` by its path.

    The script imports the golden cross one beside it by name, as it does when
    it is run, so its folder is put on the path first. The module is registered
    before it is executed: its dataclass looks its own module up by name.
    """
    scripts = REPOSITORY / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    path = scripts / "run_session_segments_study.py"
    spec = importlib.util.spec_from_file_location("run_session_segments_study", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def three_days_of_returns() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return the prices of three sessions and the segments of the last two."""
    index = pd.Index([D1, D2, D3], dtype="object")
    opens = pd.Series([100.0, 110.0, 99.0], index=index)
    closes = pd.Series([100.0, 99.0, 108.9], index=index)
    returns = segment_returns(opens, closes, closes, [D1, D2, D3])
    return pd.DataFrame({"open": opens, "close": closes}), returns


def three_days() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return the prices of three sessions and the free books of the last two."""
    prices, returns = three_days_of_returns()
    return prices, segment_books(returns, initial=100.0, cost_rate=0.0)


def test_the_cost_of_a_leg_is_the_commission_the_half_spread_and_the_slippage() -> None:
    cost_rate = load_script().COST_RATE
    assert cost_rate == pytest.approx(0.0008)


def test_the_validation_window_ends_before_the_discovery_window_starts() -> None:
    windows = {window.role: window for window in load_script().WINDOWS}
    assert windows["validation"].end < windows["discovery"].start
    assert windows["validation"].instrument_id != windows["discovery"].instrument_id


def test_the_figure_draws_the_price_above_the_profit_of_the_five_books() -> None:
    script = load_script()
    prices, books = three_days()
    figure = script.segments_figure(prices, books, initial=100.0, title="a title", trades=False)
    price_axes, pnl_axes = figure.axes
    assert price_axes.get_title() == "a title"
    assert price_axes.get_legend_handles_labels()[1] == ["close"]
    assert len(price_axes.collections) == 0
    assert pnl_axes.get_legend_handles_labels()[1] == [
        "held throughout",
        "night only, gross",
        "night only, net",
        "session only, gross",
        "session only, net",
    ]
    hold = pnl_axes.lines[0]
    assert [float(value) for value in hold.get_ydata()] == pytest.approx([-1.0, 8.9])


def test_trades_are_green_crosses_on_the_closes_and_red_crosses_on_the_opens() -> None:
    script = load_script()
    prices, books = three_days()
    figure = script.segments_figure(prices, books, initial=100.0, title="zoom", trades=True)
    buys, sells = figure.axes[0].collections
    assert [point[1] for point in buys.get_offsets()] == [99.0, 108.9]
    assert [point[1] for point in sells.get_offsets()] == [110.0, 99.0]
    assert buys.get_label() == "buy at the close"
    assert sells.get_label() == "sell at the open"


def test_a_figure_of_no_session_is_refused() -> None:
    script = load_script()
    prices, books = three_days()
    with pytest.raises(ValueError, match="nothing to draw"):
        script.segments_figure(prices, books.iloc[:0], initial=100.0, title="empty", trades=False)


def test_the_printout_names_the_window_its_segments_and_every_book(
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = load_script()
    _, books = three_days()
    _, returns = three_days_of_returns()
    window = script.Window("discovery", "FUND", D1, D3)
    script.print_window(window, 3, segment_summary(returns), books)
    printed = capsys.readouterr().out
    assert "discovery: FUND  2024-01-02 to 2024-01-04" in printed
    assert "sessions served        2 of 3 expected" in printed
    assert "share of the night" in printed
    for column in books.columns:
        assert column in printed
