"""Tests of SA18's trend-filter script: the replay, the books, the reading and the report."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from tests.scripts.test_SA16_long_history import archive  # noqa: F401

from quant_backtester.research.sa18_trend import above_average, levels
from scripts import SA18_run_trend_long_history as runner

# The drawn French tables of the shared archive end here.
DRAWN_LAST = date(2025, 6, 1)


def drawn_study(draws: int = 200) -> dict[str, Any]:
    frozen = runner.load_study()
    return dict(frozen) | {
        "inference": dict(frozen["inference"]) | {"draws": draws},
        "later": dict(frozen["later"]) | {"last_holding_month": DRAWN_LAST},
    }


def drawn_series(folder: Path, study: dict[str, Any]) -> runner.TrendSeries:
    coverage = json.loads((folder / "coverage.json").read_text())
    return runner.load_series(folder, coverage, study)


def test_the_frozen_design_is_fabers_rule_on_the_window_of_the_earlier_tests() -> None:
    study = runner.load_study()
    assert study["strategy"] == {
        "rule": runner.RULE,
        "signal": runner.GROWTH_SIGNAL,
        "average_months": 10,
    }
    assert study["window"] == {
        "first_holding_month": date(1975, 1, 1),
        "last_holding_month": date(2018, 7, 1),
    }
    assert study["inputs"] == "research/SA16/long_history_inputs.json"
    assert study["inference"]["family"] == [runner.GROWTH_HELD, runner.NASDAQ_HELD]


def test_another_rule_or_signal_is_refused(tmp_path: Path) -> None:
    text = runner.STUDY.read_text(encoding="utf-8")
    other = tmp_path / "study.toml"
    other.write_text(text.replace('signal = "GROWTH_TOTAL_RETURN"', 'signal = "NASDAQ_PRICE"'))
    with pytest.raises(ValueError, match="only rule written"):
        runner.load_study(other)
    other.write_text(text.replace('signal = ["NASDAQ_PRICE"]', 'signal = ["GOLD"]'))
    with pytest.raises(ValueError, match="only other signal"):
        runner.load_study(other)


def test_the_series_start_with_the_french_tables_and_refuse_altered_bytes(archive) -> None:  # noqa: F811
    folder, _ = archive
    study = drawn_study()
    series = drawn_series(folder, study)
    assert series.months[0] == date(1926, 7, 1) and series.months[-1] == DRAWN_LAST
    assert len(series.growth) == len(series.risk_free) == len(series.months)
    # The drawn Nasdaq starts in 1972-01: its first change is February's.
    assert min(series.nasdaq) == date(1972, 2, 1)
    coverage = json.loads((folder / "coverage.json").read_text())
    (folder / "NASDAQCOM.csv").write_text("observation_date,NASDAQCOM\n1972-01-27,1\n")
    with pytest.raises(ValueError, match=r"NASDAQCOM\.csv"):
        runner.load_series(folder, coverage, study)


def test_a_month_the_tables_do_not_hold_is_refused_not_filled(archive) -> None:  # noqa: F811
    folder, _ = archive
    study = drawn_study() | {"later": {"last_holding_month": date(2025, 7, 1)}}
    with pytest.raises(ValueError, match="growth has no value for 2025-07"):
        drawn_series(folder, study)


def test_the_candidate_is_the_rule_applied_month_by_month(archive) -> None:  # noqa: F811
    """The script's book against a naive loop over the raw series."""
    folder, _ = archive
    series = drawn_series(folder, drawn_study())
    first, last = date(1975, 1, 1), date(1976, 12, 1)
    records = runner.trend_records(series, 10, runner.GROWTH_SIGNAL, first, last, 0.001)
    level = levels(series.growth)
    previous = None
    for record in records:
        position = series.months.index(record.month)
        window = level[position - 10 : position]
        invested = window[-1] > sum(window) / 10
        gross = series.growth[position] if invested else series.risk_free[position]
        assert record.invested == invested
        assert record.gross == gross
        assert record.traded == (previous is not None and invested != previous)
        assert record.net == pytest.approx(gross - 0.001 * (1 + gross) * record.traded)
        previous = invested


def test_months_after_the_run_do_not_change_it(archive) -> None:  # noqa: F811
    """The look-ahead guard, through the script: a different future, the same book."""
    folder, _ = archive
    series = drawn_series(folder, drawn_study())
    first, last = date(1975, 1, 1), date(1980, 12, 1)
    stop = series.months.index(last) + 1
    altered = runner.TrendSeries(
        series.months,
        (*series.growth[:stop], *(-0.5 for _ in series.growth[stop:])),
        series.risk_free,
        {month: (value if month <= last else 0.9) for month, value in series.nasdaq.items()},
    )
    for signal in (runner.GROWTH_SIGNAL, runner.NASDAQ_SIGNAL):
        assert runner.trend_records(altered, 10, signal, first, last, 0.001) == (
            runner.trend_records(series, 10, signal, first, last, 0.001)
        )


def test_the_nasdaq_signal_reads_the_composite_and_holds_the_growth_portfolio(archive) -> None:  # noqa: F811
    folder, _ = archive
    series = drawn_series(folder, drawn_study())
    first, last = date(1975, 1, 1), date(1984, 12, 1)
    records = runner.trend_records(series, 10, runner.NASDAQ_SIGNAL, first, last, 0.0)
    start = series.months.index(min(series.nasdaq))
    closes = levels(runner.nasdaq_returns(series, series.months[start], last))
    signal = above_average(closes, 10)
    for record in records:
        position = series.months.index(record.month)
        assert record.invested == signal[position - start - 1]
        held = series.growth[position] if record.invested else series.risk_free[position]
        assert record.gross == held
    with pytest.raises(ValueError, match="unknown signal"):
        runner.trend_records(series, 10, "GOLD", first, last, 0.0)
    with pytest.raises(ValueError, match="no change for 1971-12"):
        runner.nasdaq_returns(series, date(1971, 12, 1), date(1972, 6, 1))


@pytest.mark.slow
def test_the_study_runs_and_reports_on_drawn_series(archive, tmp_path: Path) -> None:  # noqa: F811
    """The whole chain: replay, books, inference, reading, report."""
    folder, _ = archive
    study = drawn_study()
    series = drawn_series(folder, study)

    report = runner.study_report(series, study)

    assert report["months"] == 523
    declared, stressed = report["books"]["declared"], report["books"]["stressed"]
    assert set(declared) == set(runner.BOOKS)
    candidate = declared[runner.CANDIDATE]
    assert candidate["switches"] > 0 and 0.0 < candidate["share_invested"] < 1.0
    assert candidate["cagr_gross"] > candidate["cagr"] > stressed[runner.CANDIDATE]["cagr"]
    # The references pay nothing: the same at both cost levels.
    assert declared[runner.GROWTH_HELD] == stressed[runner.GROWTH_HELD]
    assert candidate["volatility"] < declared[runner.GROWTH_HELD]["volatility"]
    assert set(report["readings"]) == {runner.GROWTH_HELD, runner.NASDAQ_HELD}
    names = {"SUPPORTED_RETROSPECTIVE", "UNCERTAIN", "NOT_SUPPORTED"}
    assert {values["reading"] for values in report["readings"].values()} <= names
    assert set(report["regimes"]) == {regime["name"] for regime in study["regimes"]}
    assert set(report["sensitivities"]) == {
        "average_months=6",
        "average_months=8",
        "average_months=12",
        "signal=NASDAQ_PRICE",
    }
    earlier, later = report["earlier"], report["later"]
    assert earlier["months"] == 570 and set(earlier["books"]) == {
        runner.CANDIDATE,
        runner.GROWTH_HELD,
    }
    assert later["months"] == 83 and set(later["books"]) == set(runner.BOOKS)
    positions = report["positions"]
    assert len(positions) == 523 and positions[0]["month"] == date(1975, 1, 1)
    assert sum(row["traded"] for row in positions) == candidate["switches"]

    output = tmp_path / "out"
    runner.write_outputs(output, report, study, "0" * 40)
    text = (output / "study.md").read_text()
    assert "**Not a blind test**" in text
    assert "## 1975-01 to 2018-07 (523 months), net" in text
    assert "## Earlier months: 1927-07 to 1974-12 (570 months; decide nothing)" in text
    assert "block6 interval" in text and "block24 interval" in text
    verdict = json.loads((output / "verdict.json").read_text())
    assert verdict["readings"] == report["readings"]
    assert verdict["earlier"]["months"] == 570
    assert (output / "metrics.csv").read_text().startswith("scope,book,measure,value\n")
    assert (output / "positions.csv").read_text().startswith("month,invested,traded\n1975-01-01,")
