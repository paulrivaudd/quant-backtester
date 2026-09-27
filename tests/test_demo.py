"""The offline demo: invented prices, the project's own reader and engine.

What matters is that the demo is honest about being a demo - reproducible from
its seed, never overwriting a directory it did not make, never letting a longer
history rewrite a shorter one - and that it runs the real engine end to end.
"""

from __future__ import annotations

import importlib.util
import math
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from quant_backtester.data.calendars import CalendarCoverageError
from quant_backtester.data.schemas import BarField
from quant_backtester.demo import (
    DEMO_FUNDS,
    DEMO_INITIAL_CASH,
    SyntheticFund,
    build_demo_market,
    demo_calendar,
    demo_runner,
    draw_bars,
)
from quant_backtester.strategies.examples import BuyAndHold

SEED = 20240101
"""The seed every demo in these tests is drawn from."""

PARIS = ZoneInfo("Europe/Paris")


def sessions_between(start: date, end: date) -> tuple[date, ...]:
    """Return the ``DEMO`` sessions from ``start`` to ``end``, inclusive."""
    return tuple(day.session_date for day in demo_calendar().sessions(start, end))


def closes(root: Path, instrument_id: str, *, seed: int = SEED) -> pd.Series:  # type: ignore[type-arg]
    """Return every close of one demo fund, as read after the last session."""
    reader = build_demo_market(root, seed=seed)
    at = datetime(2025, 12, 31, 23, 0, tzinfo=PARIS)
    return reader.at(at).history(instrument_id, BarField.CLOSE)


def test_a_fund_without_volatility_compounds_its_drift_by_hand() -> None:
    fund = SyntheticFund("FLAT", start_price=100.0, annual_drift=0.255, annual_volatility=0.0)
    days = sessions_between(date(2025, 1, 2), date(2025, 1, 6))
    bars = draw_bars(fund, days, np.random.default_rng(SEED))
    # 0.255 a year over 255 sessions is 0.001 of log return a session, no noise.
    first_close = round(100.0 * math.exp(0.001), 4)
    assert bars[days[0]] == (100.0, first_close, 100.0, first_close)
    assert bars[days[1]][3] == round(100.0 * math.exp(0.002), 4)
    assert bars[days[2]][3] == round(100.0 * math.exp(0.003), 4)


def test_every_drawn_bar_is_a_coherent_bar() -> None:
    days = sessions_between(date(2024, 1, 2), date(2025, 12, 31))
    for fund in DEMO_FUNDS:
        bars = draw_bars(fund, days, np.random.default_rng(SEED))
        assert len(bars) == len(days)
        for opening, high, low, closing in bars.values():
            assert 0.0 < low <= min(opening, closing)
            assert high >= max(opening, closing)


def test_the_same_seed_writes_the_same_prices_bit_for_bit(tmp_path: Path) -> None:
    first = closes(tmp_path / "first", "FUND_B")
    second = closes(tmp_path / "second", "FUND_B")
    assert first.equals(second)
    assert not first.equals(closes(tmp_path / "other", "FUND_B", seed=SEED + 1))


def test_a_longer_history_leaves_the_past_as_it_was() -> None:
    short = sessions_between(date(2024, 1, 2), date(2024, 6, 28))
    long = sessions_between(date(2024, 1, 2), date(2025, 12, 31))
    for fund in DEMO_FUNDS:
        before = draw_bars(fund, short, np.random.default_rng(SEED))
        after = draw_bars(fund, long, np.random.default_rng(SEED))
        assert {day: after[day] for day in short} == before


def test_a_close_is_not_served_before_the_session_closes(tmp_path: Path) -> None:
    reader = build_demo_market(tmp_path / "store", seed=SEED)
    midday = reader.at(datetime(2025, 6, 2, 12, 0, tzinfo=PARIS))
    evening = reader.at(datetime(2025, 6, 2, 23, 0, tzinfo=PARIS))
    assert midday.history("FUND_A", BarField.CLOSE).index[-1] == date(2025, 5, 30)
    assert evening.history("FUND_A", BarField.CLOSE).index[-1] == date(2025, 6, 2)
    # The open of the same session is knowable from the open.
    assert midday.history("FUND_A", BarField.OPEN).index[-1] == date(2025, 6, 2)


def test_the_demo_never_writes_over_a_directory_it_did_not_make(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("mine")
    with pytest.raises(ValueError, match="not empty"):
        build_demo_market(tmp_path, seed=SEED)
    assert (tmp_path / "notes.txt").read_text() == "mine"


def test_the_demo_calendar_refuses_a_date_it_does_not_cover() -> None:
    with pytest.raises(CalendarCoverageError):
        demo_calendar().sessions(date(2026, 1, 2), date(2026, 1, 9))


@pytest.mark.parametrize(
    ("price", "drift", "volatility"),
    [(0.0, 0.0, 0.1), (-1.0, 0.0, 0.1), (100.0, math.nan, 0.1), (100.0, 0.0, -0.1)],
)
def test_an_impossible_fund_is_refused(price: float, drift: float, volatility: float) -> None:
    with pytest.raises(ValueError):
        SyntheticFund("BAD", start_price=price, annual_drift=drift, annual_volatility=volatility)


def test_the_demo_runs_the_real_engine_end_to_end_and_reproducibly(tmp_path: Path) -> None:
    runs = [
        demo_runner(tmp_path / name, seed=SEED).run(
            BuyAndHold(instruments=("FUND_A",)), ("FUND_A", "FUND_B"), "2025-01-02", "2025-12-31"
        )
        for name in ("first", "second")
    ]
    first, second = runs
    assert len(first.records()) == 255
    assert first.records()[0].cash == DEMO_INITIAL_CASH
    assert len(first.fills()) == 1
    assert first.equity().equals(second.equity())
    assert "FUND_A" in first.compare().render()


def test_the_demo_script_prints_both_reports_and_writes_its_figures(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "demo.py"
    spec = importlib.util.spec_from_file_location("demo_script", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main(["--figures", str(tmp_path / "figures")]) == 0
    printed = capsys.readouterr().out
    assert "invented prices, not market data" in printed
    assert "Momentum rotation" in printed and "Control: buy and hold FUND_A" in printed
    assert (tmp_path / "figures" / "equity.png").stat().st_size > 0
    assert (tmp_path / "figures" / "drawdown.png").stat().st_size > 0
