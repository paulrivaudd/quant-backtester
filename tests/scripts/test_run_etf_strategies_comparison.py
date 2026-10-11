"""The comparison script: its books, its helpers and its figures, on written curves."""

from __future__ import annotations

import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path
from types import ModuleType

import numpy as np
import pandas as pd
import pytest
from matplotlib.figure import Figure

REPOSITORY = Path(__file__).resolve().parents[2]


def load_script() -> ModuleType:
    """Import ``scripts/run_etf_strategies_comparison.py`` by its path."""
    path = REPOSITORY / "scripts" / "run_etf_strategies_comparison.py"
    spec = importlib.util.spec_from_file_location("run_etf_strategies_comparison", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SCRIPT = load_script()
SESSIONS = [date(2026, 1, 5) + timedelta(days=i) for i in range(90)]


def curve(daily: float, start: float = 100_000.0) -> pd.Series:
    """Return a curve growing by ``daily`` a session, with a small wobble."""
    wobble = 0.002 * np.sin(np.arange(len(SESSIONS)))
    values = start * np.cumprod(1.0 + daily + wobble)
    return pd.Series(values, index=pd.Index(SESSIONS, dtype="object"), dtype="float64")


@pytest.fixture
def curves() -> dict[str, pd.Series]:
    """Return a written curve per book of the script, in its order."""
    return {name: curve(0.0002 * (rank + 1)) for rank, name in enumerate(SCRIPT.books())}


def test_the_books_are_the_runnable_strategies_and_the_three_references() -> None:
    books = SCRIPT.books()

    assert list(books)[:3] == [SCRIPT.BENCHMARK, SCRIPT.HELD, SCRIPT.SPLIT]
    assert SCRIPT.BENCHMARK == "SA1 - std MA20"
    assert list(books)[3:] == [
        "SA2 - dual momentum",
        "SA3 - smooth MA",
        "SA4 - pullback",
        "SA5 - relative tilt",
        "SA6 - vol control",
        "SA7 - factor blend",
        "SA8 - monetary carry",
        "SA9 - VIX relief",
        "SA10 - ensemble",
        # Run when its estimator is installed, left out - and said so - otherwise.
        *(["SA11 - GARCH vol control"] if SCRIPT.garch_available() else []),
        *(["SA12 - ARIMA GARCH"] if SCRIPT.arima_available() else []),
    ]
    for name, strategy in list(books.items())[3:]:
        assert strategy.strategy_id.startswith(name.split(" - ")[0] + "_")
    for strategy in books.values():
        strategy.validate()
    ensemble = books[SCRIPT.ENSEMBLE]
    assert ensemble.enable_factors is False
    assert ensemble.enable_monetary is False


def test_the_assumptions_are_those_of_the_specification() -> None:
    costs = SCRIPT.EXECUTION.costs

    assert (costs.commission_rate, costs.minimum_commission) == (0.0005, 1.0)
    assert (costs.half_spread_rate, costs.slippage_rate) == (0.0003, 0.0002)
    assert SCRIPT.ANALYTICS.sessions_per_year == 252
    assert SCRIPT.ANALYTICS.risk_free_rate == 0.0
    assert SCRIPT.INITIAL_CASH == 100_000.0


def test_a_curve_is_rebased_to_one_hundred() -> None:
    rebased = SCRIPT.indexed(curve(0.001, start=250.0))

    assert rebased.iloc[0] == 100.0
    assert rebased.iloc[-1] / rebased.iloc[0] == pytest.approx(
        curve(0.001).iloc[-1] / curve(0.001).iloc[0]
    )


def test_the_last_third_starts_two_thirds_of_the_way_in() -> None:
    assert SCRIPT.holdout_start(SESSIONS) == SESSIONS[60]
    assert SCRIPT.holdout_start(SESSIONS[:2]) == SESSIONS[1]


def test_a_total_return_is_the_last_value_over_the_first() -> None:
    series = pd.Series([100.0, 90.0, 120.0])

    assert SCRIPT.total_return(series) == pytest.approx(0.20)


def test_the_summary_keeps_one_row_per_book_and_prints_a_missing_figure_as_such() -> None:
    table = SCRIPT.summary_table(
        {
            "a": {"net_return": 0.10, "sharpe": 0.5, "fills": 3.0},
            "b": {"net_return": -0.02, "sharpe": None, "fills": 0.0},
        }
    )
    for column in (
        "quality",
        "annualised_return",
        "volatility",
        "max_drawdown",
        "average_exposure",
    ):
        table[column] = 0.1
    for column in ("costs_eur", "beta_vs_benchmark", "alpha_vs_benchmark"):
        table[column] = 1.0
    table["net_return_first_two_thirds"] = table["net_return_last_third"] = 0.0

    text = SCRIPT.render_summary(table).splitlines()

    assert list(table.index) == ["a", "b"]
    assert len(text) == 3
    assert "+10.0%" in text[1]
    assert "n/a" in text[2]


def test_each_panel_figure_has_one_panel_per_book_it_shows(curves) -> None:
    def shown(figure: Figure) -> list[str]:
        return [axes.get_title(loc="left") for axes in figure.axes if axes.get_visible()]

    equity = shown(SCRIPT.equity_panels(curves))
    relative = shown(SCRIPT.relative_panels(curves))
    drawdowns = shown(SCRIPT.drawdown_panels(curves))

    assert equity == [name for name in curves if name not in (SCRIPT.BENCHMARK, SCRIPT.HELD)]
    assert relative == [name for name in curves if name != SCRIPT.BENCHMARK]
    assert len(drawdowns) == len(curves) - 1
    assert all("worst" in title for title in drawdowns)


def test_every_panel_spans_the_run_and_nothing_else(curves) -> None:
    """The time axis is the sessions of the run: no empty decades beside the curves."""
    from matplotlib.dates import num2date

    for figure in (SCRIPT.equity_panels(curves), SCRIPT.drawdown_panels(curves)):
        low, high = figure.axes[0].get_xlim()
        assert num2date(low).date() == SESSIONS[0]
        assert num2date(high).date() == SESSIONS[-1]


def test_the_overview_names_every_book_at_the_end_of_its_curve(curves) -> None:
    figure = SCRIPT.overview_figure(curves)
    labels = [text.get_text() for text in figure.axes[0].texts]

    assert len(labels) == len(curves)
    for name in curves:
        assert any(label.startswith(name) for label in labels)


def test_the_outputs_are_written_and_the_curves_can_be_read_back(curves, tmp_path: Path) -> None:
    table = SCRIPT.summary_table({name: {"net_return": 0.1} for name in curves})

    written = SCRIPT.save_outputs(tmp_path / "out", table, curves)

    assert sorted(path.name for path in written) == [
        "drawdowns.png",
        "equity.csv",
        "equity_panels.png",
        "overview.png",
        "relative_to_benchmark.png",
        "summary.csv",
    ]
    assert all(path.stat().st_size > 0 for path in written)
    read_back = pd.read_csv(tmp_path / "out" / "equity.csv", index_col="session_date")
    assert list(read_back.columns) == list(curves)
    assert len(read_back) == len(SESSIONS)


def test_a_book_name_becomes_a_file_name() -> None:
    assert SCRIPT.slug("SA1 - std MA20") == "sa1_std_ma20"
    assert SCRIPT.slug("50/50 rebalanced") == "50_50_rebalanced"
    assert SCRIPT.slug("buy & hold World") == "buy_hold_world"


def fills_of(rows: list[tuple[int, str, str, float, float]]) -> pd.DataFrame:
    """Return executions from ``(session, instrument, side, price, value)``."""
    return pd.DataFrame(
        [
            {
                "session_date": SESSIONS[session],
                "instrument_id": instrument_id,
                "side": side,
                "market_price": price,
                "traded_value": value,
            }
            for session, instrument_id, side, price, value in rows
        ],
        columns=["session_date", "instrument_id", "side", "market_price", "traded_value"],
    )


def orders_inputs() -> tuple[dict[str, pd.Series], pd.DataFrame]:
    """Return the closes of the two funds and the weights of a book holding the first."""
    closes = {"ETF_WORLD": curve(0.001, 300.0), "ETF_SP500_PEA": curve(0.001, 12.0)}
    weights = pd.DataFrame(
        {"ETF_WORLD": 0.5, "ETF_SP500_PEA": 0.0}, index=pd.Index(SESSIONS, dtype="object")
    )
    return closes, weights


def test_every_order_is_a_cross_on_the_price_of_its_fund() -> None:
    closes, weights = orders_inputs()
    fills = fills_of(
        [
            (1, "ETF_WORLD", "BUY", 301.0, 50_000.0),
            (20, "ETF_WORLD", "SELL", 305.0, 10_000.0),
            (40, "ETF_WORLD", "BUY", 310.0, 10_000.0),
        ]
    )

    figure = SCRIPT.orders_figure("a book", closes, fills, weights, curve(0.0005), curve(0.001))

    # One price panel, for the only fund traded, then the weights and the equity.
    assert len(figure.axes) == 3
    crosses = figure.axes[0].collections
    assert [len(marks.get_offsets()) for marks in crosses] == [2, 1]
    labels = figure.axes[0].get_legend_handles_labels()[1]
    assert labels == ["ETF_WORLD close", "buy (2)", "sell (1)"]
    # A larger order is a larger cross.
    sizes = list(crosses[0].get_sizes())
    assert sizes[0] > sizes[1]
    assert "3 orders" in figure.axes[0].get_title(loc="left")


def test_a_book_trading_both_funds_gets_a_price_panel_for_each() -> None:
    closes, weights = orders_inputs()
    fills = fills_of(
        [(1, "ETF_WORLD", "BUY", 301.0, 50_000.0), (1, "ETF_SP500_PEA", "BUY", 12.0, 50_000.0)]
    )

    figure = SCRIPT.orders_figure("a book", closes, fills, weights, curve(0.0005), curve(0.001))

    assert len(figure.axes) == 4


def test_a_book_without_an_order_still_shows_a_price() -> None:
    closes, weights = orders_inputs()

    figure = SCRIPT.orders_figure(
        "a book", closes, fills_of([]), weights, curve(0.0005), curve(0.001)
    )

    assert len(figure.axes) == 3
    assert "0 orders" in figure.axes[0].get_title(loc="left")


def test_a_book_is_run_on_the_funds_it_may_hold() -> None:
    books = SCRIPT.books()

    # The style funds and the money-market fund are the ones the registry declares.
    assert SCRIPT.universe_of(books["SA7 - factor blend"]) == SCRIPT.FACTOR_FUNDS
    assert SCRIPT.FACTOR_FUNDS == ("ETF_VALUE_WORLD", "ETF_QUALITY_WORLD", "ETF_MINVOL_WORLD")
    assert SCRIPT.universe_of(books["SA8 - monetary carry"]) == ("ETF_MONETARY_EUR",)
    # Every other book trades the two funds of the comparison, the references included.
    others = [name for name in books if not name.startswith(("SA7", "SA8"))]
    assert {SCRIPT.universe_of(books[name]) for name in others} == {SCRIPT.UNIVERSE}
    # A fund has a colour wherever a figure may draw it.
    assert set(SCRIPT.FACTOR_FUNDS) | {SCRIPT.MONETARY_FUND} <= set(SCRIPT.FUND_COLOURS)
    assert len({SCRIPT.FUND_COLOURS[fund] for fund in SCRIPT.FACTOR_FUNDS}) == 3


def test_a_fund_keeps_its_place_whatever_order_it_comes_in() -> None:
    assert SCRIPT.ordered_funds(["ETF_SP500_PEA", "ETF_WORLD"]) == ["ETF_WORLD", "ETF_SP500_PEA"]
    # A fund without a colour of its own comes after those that have one, by name.
    assert SCRIPT.ordered_funds(["ZZZ", "ETF_SP500_PEA", "AAA"]) == ["ETF_SP500_PEA", "AAA", "ZZZ"]
    assert SCRIPT.ordered_funds([]) == []


def test_the_weights_are_stacked_fund_by_fund_and_what_is_left_is_cash() -> None:
    _, weights = orders_inputs()
    # The columns come in any order: a fund keeps its place and its colour.
    weights = weights.assign(ETF_SP500_PEA=0.3)[["ETF_SP500_PEA", "ETF_WORLD"]]

    figure = SCRIPT.weights_figure("a book", weights)

    axes = figure.axes[0]
    assert axes.get_legend_handles_labels()[1] == ["ETF_WORLD", "ETF_SP500_PEA"]
    assert axes.get_ylim() == (0.0, 100.0)
    # The two bands add up to the 80% held: the 20 above them are cash.
    tops = [float(band.get_paths()[0].vertices[:, 1].max()) for band in axes.collections]
    assert tops == pytest.approx([50.0, 80.0])
    assert axes.get_title(loc="left") == "a book: weight held in each fund"


def test_a_book_of_one_fund_is_named_by_its_title_and_needs_no_legend() -> None:
    _, weights = orders_inputs()

    figure = SCRIPT.weights_figure("a book", weights[["ETF_WORLD"]])

    assert figure.axes[0].get_legend() is None
    assert figure.axes[0].get_title(loc="left") == "a book: weight held in ETF_WORLD"
    with pytest.raises(ValueError, match="nothing to draw"):
        SCRIPT.weights_figure("a book", weights.iloc[:0])
    with pytest.raises(ValueError, match="nothing to draw"):
        SCRIPT.weights_figure("a book", weights[[]])


def test_the_costs_are_one_bar_per_book_with_the_dearest_on_top() -> None:
    figure = SCRIPT.costs_figure({"cheap": 100.0, "dear": 20_517.4, "middle": 1_445.0})

    axes = figure.axes[0]
    # Bars are drawn bottom up, so the dearest book is the last one.
    assert [tick.get_text() for tick in axes.get_yticklabels()] == ["cheap", "middle", "dear"]
    assert [bar.get_width() for bar in axes.patches] == [100.0, 1_445.0, 20_517.4]
    assert [note.get_text() for note in axes.texts] == ["100", "1,445", "20,517"]
    with pytest.raises(ValueError, match="no book"):
        SCRIPT.costs_figure({})


def test_every_book_but_the_market_fund_is_scored_against_it() -> None:
    days = [date(2024, 1, 1) + timedelta(days=i) for i in range(400)]
    rng = np.random.default_rng(4)
    market = rng.normal(0.0003, 0.01, 399)

    def written(returns: np.ndarray) -> pd.Series:
        values = 100_000.0 * np.concatenate([[1.0], np.cumprod(1.0 + returns)])
        return pd.Series(values, index=pd.Index(days, dtype="object"), dtype="float64")

    ahead = market + 0.0005 + rng.normal(0.0, 0.001, 399)
    behind = market - 0.0005 + rng.normal(0.0, 0.001, 399)
    net = {
        SCRIPT.HELD: written(market),
        SCRIPT.BENCHMARK: written(ahead),
        SCRIPT.ENSEMBLE: written(behind),
    }

    scores = SCRIPT.quality_scores(net, net)

    assert list(scores) == list(net)
    assert scores[SCRIPT.HELD] is None  # the yardstick is not scored against itself
    assert scores[SCRIPT.BENCHMARK] > 0.5
    assert scores[SCRIPT.ENSEMBLE] == 0.0
