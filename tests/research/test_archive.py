"""A kept run reads back without recomputing, and recomputes from what it kept (C01)."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from quant_backtester.backtest.runner import StoreChanged, StrategyRunner
from quant_backtester.data.calendars import TradingCalendar
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.data.repository import MarketDataRepository
from quant_backtester.research.archive import (
    ArchiveError,
    keep,
    read_back,
    same_economics,
)
from quant_backtester.strategies.examples import BuyAndHold

STRATEGY = BuyAndHold(instruments=("ETF_EU",))


def a_run(runner: StrategyRunner):
    return runner.run(STRATEGY, ["ETF_EU"], "2026-09-09", "2026-09-14")


def test_a_kept_run_reads_back_the_same_after_the_store_moved_on(
    research_runner: StrategyRunner,
    repository: MarketDataRepository,
    make_bars: Callable[..., pd.DataFrame],
    xpar: TradingCalendar,
    prices: Callable[..., dict[date, float]],
    tmp_path: Path,
) -> None:
    """The acceptance test of C01: save, change the store, read back, nothing moved."""
    result = a_run(research_runner)
    kept_at = keep(result, tmp_path / "run")
    repository.save_checked_bars("ETF_EU", make_bars("ETF_EU", xpar, prices(999.0, 1.0)))

    kept = read_back(kept_at)

    assert kept.run_id == result.run_id
    assert kept.fingerprint == result.fingerprint
    assert same_economics(kept, result)
    assert list(kept.net) == pytest.approx(list(result.equity()))
    assert kept.report == result.report().render()
    assert kept.store is None


def test_a_kept_file_that_changed_is_refused(
    research_runner: StrategyRunner, tmp_path: Path
) -> None:
    kept_at = keep(a_run(research_runner), tmp_path / "run")
    sessions = kept_at / "sessions.jsonl"
    sessions.write_text(sessions.read_text(encoding="utf-8").replace("10000", "20000"))

    with pytest.raises(ArchiveError, match="not the file that was kept"):
        read_back(kept_at)


def test_a_kept_run_of_another_format_or_unfinished_is_refused(
    research_runner: StrategyRunner, tmp_path: Path
) -> None:
    kept_at = keep(a_run(research_runner), tmp_path / "run")
    manifest = kept_at / "manifest.json"
    stated = json.loads(manifest.read_text(encoding="utf-8"))
    manifest.write_text(json.dumps(stated | {"format": "quant-backtester-run/0"}))

    with pytest.raises(ArchiveError, match="format"):
        read_back(kept_at)
    manifest.unlink()
    with pytest.raises(ArchiveError, match="never finished"):
        read_back(kept_at)


def test_a_kept_run_is_never_overwritten(research_runner: StrategyRunner, tmp_path: Path) -> None:
    result = a_run(research_runner)
    keep(result, tmp_path / "run")

    with pytest.raises(FileExistsError):
        keep(result, tmp_path / "run")


def test_a_run_kept_with_its_store_recomputes_to_the_same_economics(
    research_runner: StrategyRunner,
    repository: MarketDataRepository,
    make_bars: Callable[..., pd.DataFrame],
    xpar: TradingCalendar,
    prices: Callable[..., dict[date, float]],
    tmp_path: Path,
) -> None:
    """Recomputing needs what the run read; the copy is checked against its digest."""
    result = a_run(research_runner)
    kept_at = keep(result, tmp_path / "run", store=repository)
    repository.save_checked_bars("ETF_EU", make_bars("ETF_EU", xpar, prices(999.0, 1.0)))
    kept = read_back(kept_at)
    assert kept.store is not None

    copy = MarketDataRepository(kept.store)
    reader = MarketDataReader(
        repository=copy,
        instruments=research_runner.reader.instruments,
        calendars=research_runner.reader.calendars,
        reference_calendar_id="XPAR",
    )
    again = replace(research_runner, reader=reader).run(
        STRATEGY, ["ETF_EU"], "2026-09-09", "2026-09-14"
    )

    assert same_economics(kept, again)
    assert again.configuration["data_state"] == result.configuration["data_state"]


def test_a_store_that_moved_on_is_not_kept_as_the_run_s_inputs(
    research_runner: StrategyRunner,
    repository: MarketDataRepository,
    make_bars: Callable[..., pd.DataFrame],
    xpar: TradingCalendar,
    prices: Callable[..., dict[date, float]],
    tmp_path: Path,
) -> None:
    result = a_run(research_runner)
    repository.save_checked_bars("ETF_EU", make_bars("ETF_EU", xpar, prices(999.0, 1.0)))

    with pytest.raises(StoreChanged):
        keep(result, tmp_path / "run", store=repository)
    assert not (tmp_path / "run").exists()
