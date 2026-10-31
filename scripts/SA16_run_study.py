"""Run the SA16 study: its two fixed references, its candidates and their controls.

Run under WSL/POSIX from the repository root, on the store built by
``scripts/SA16_download_data.py``::

    uv run python scripts/SA16_run_study.py reproduce
    uv run python scripts/SA16_run_study.py references
    uv run python scripts/SA16_run_study.py candidate research/SA16/candidates/it01.json
    uv run python scripts/SA16_run_study.py robustness research/SA16/candidates/it07.json

Every book is run under the conventions of SA15, so that the comparison is
made on the same terms: Paris reference calendar, euro book of 100 000 EUR,
whole units, commission 5 bp (minimum 1 EUR), half-spread 3 bp and slippage
2 bp per order, quantities fixed at the 23:00 Paris decision and filled at the
next open of the fund's own venue, Sharpe ratios on 252 sessions a year with a
zero risk-free rate. Doubled costs are a second real run.

The two references are fixed before any candidate: ``ETF_NASDAQ`` bought and
held, and the last selection SA15 archived (``results/SA15_GPT-6.1_R4/
selected.json``, trial 71, with its monthly schedule). A candidate JSON names
its parameters and the controls that remove one mechanism each; every run of a
candidate or a control is a trial of the study register (``register.csv``),
counted in the deflated Sharpe ratio. A run whose signature (strategy and
schedule definitions, window, costs, universe, store digest) matches a saved
one is read back instead of being run again.

This script computes no signal and takes no decision: it wires the runner,
runs, and writes what the runs produced into a new or matching folder.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from SA15_run_gpt61_round4 import MonthlyFromStart  # noqa: E402

from quant_backtester.analytics.config import AnalyticsConfig  # noqa: E402
from quant_backtester.analytics.curves import Book  # noqa: E402
from quant_backtester.analytics.performance import PerformanceStats  # noqa: E402
from quant_backtester.analytics.uncertainty import (  # noqa: E402
    PairedStatistic,
    paired_block_bootstrap,
)
from quant_backtester.backtest.runner import StrategyResult, StrategyRunner  # noqa: E402
from quant_backtester.backtest.schedule import (  # noqa: E402
    DecisionSchedule,
    EverySession,
    Monthly,
    Weekly,
)
from quant_backtester.data.calendars import CalendarRegistry  # noqa: E402
from quant_backtester.data.instruments import InstrumentRegistry  # noqa: E402
from quant_backtester.data.reader import MarketDataReader  # noqa: E402
from quant_backtester.data.repository import MarketDataRepository  # noqa: E402
from quant_backtester.execution.costs import CostModel  # noqa: E402
from quant_backtester.execution.model import ExecutionModel, Sizing  # noqa: E402
from quant_backtester.provenance import git_source_state  # noqa: E402
from quant_backtester.research.references import BuyAndHold  # noqa: E402
from quant_backtester.strategies.base import Strategy  # noqa: E402
from quant_backtester.strategies.SA15_gpt61_riskaware import SA15RiskAwareRotation  # noqa: E402

STORE = ROOT / "runs" / "sa16_store"
OUTPUT = ROOT / "results" / "SA16"
ANALYTICS = AnalyticsConfig(sessions_per_year=252, risk_free_rate=0.0, minimum_sessions=60)
UNIVERSE = (
    "ETF_SP500_PEA",
    "ETF_NASDAQ",
    "ETF_EMERGING",
    "ETF_GOLD",
    "ETF_EURO_GOV",
    "ETF_COMMODITY",
    "ETF_MONETARY_EUR",
    "ETF_WORLD",
    "ETF_US_TECH",
    "ETF_WORLD_HEALTH",
    "ETF_WORLD_UTILITIES",
)
WINDOWS = {
    # The study window: the first month in which every input of both
    # references is readable (the gold archive starts 2018-01-02 and SA15
    # ranks it on 126 sessions), to the last complete session before the study.
    "full": ("2018-08-01", "2026-10-30"),
    # SA15's own continuous window, for the reproduction of its archive.
    "sa15": ("2019-06-03", "2026-10-09"),
}
# Restarts from cash, each run to the end of the study window.
START_DATES = (
    "2019-01-02",
    "2020-01-02",
    "2021-01-04",
    "2022-01-03",
    "2023-01-02",
    "2024-01-02",
    "2025-01-02",
)
# Named episodes, read on the continuous book; they are reading grids written
# before any candidate, not parameters of any rule.
EPISODES = {
    "2018Q4_selloff": ("2018-10-01", "2018-12-31"),
    "2020_covid_crash": ("2020-02-19", "2020-03-31"),
    "2020_rebound": ("2020-04-01", "2020-08-31"),
    "2022_bear": ("2022-01-03", "2022-12-30"),
    "2025_tariff_crash": ("2025-02-19", "2025-04-30"),
    "2025_rebound": ("2025-05-02", "2025-09-30"),
}
SCHEDULES: dict[str, type] = {
    "daily": EverySession,
    "weekly": Weekly,
    "monthly": Monthly,
    "monthly_from_start": MonthlyFromStart,
}
SA15_SELECTED = ROOT / "results" / "SA15_GPT-6.1_R4" / "selected.json"
BOOTSTRAP = {"block": 20, "draws": 2000, "seed": 1616, "level": 0.90}


@dataclass(frozen=True, slots=True)
class BookSpec:
    """A strategy and the schedule it decides on, under a name of the study."""

    name: str
    strategy: Strategy
    schedule: DecisionSchedule
    role: str


def build_runner(store: Path, multiplier: float = 1.0) -> StrategyRunner:
    """Wire the EUR runner of SA15, its costs scaled by ``multiplier``."""
    instruments = InstrumentRegistry.from_toml(store / "metadata" / "instruments.toml")
    calendars = CalendarRegistry.from_directory(store / "metadata" / "calendars")
    reader = MarketDataReader(
        repository=MarketDataRepository(store),
        instruments=instruments,
        calendars=calendars,
        reference_calendar_id="XPAR",
    )
    return StrategyRunner(
        reader=reader,
        calendars=calendars,
        reference_calendar_id="XPAR",
        base_currency="EUR",
        analytics=ANALYTICS,
        execution=ExecutionModel(
            costs=CostModel(
                commission_rate=0.0005 * multiplier,
                minimum_commission=1.0 * multiplier,
                half_spread_rate=0.0003 * multiplier,
                slippage_rate=0.0002 * multiplier,
            ),
            sizing=Sizing.AT_DECISION,
        ),
        initial_cash=100_000.0,
        schedule=Weekly(),
        source=git_source_state(ROOT),
        lockfile=ROOT / "uv.lock",
    )


def sa15_reference() -> BookSpec:
    """Return SA15's last archived selection, rebuilt from its frozen JSON."""
    selected = json.loads(SA15_SELECTED.read_text(encoding="utf-8"))
    candidate = selected["candidate"]
    if candidate["schedule"] != "monthly" or candidate["number"] != 71:
        raise ValueError("the archived SA15 selection is not the one this study froze")
    parameters = dict(candidate["parameters"])
    strategy = SA15RiskAwareRotation(**parameters)
    if strategy.fingerprint() != selected["fingerprint"]:
        raise ValueError("SA15 rebuilt from selected.json does not match its fingerprint")
    return BookSpec("SA15_R4_trial71", strategy, MonthlyFromStart(), "reference")


def reference_books() -> tuple[BookSpec, ...]:
    """Return the two fixed references and the descriptive passive controls."""
    return (
        BookSpec("Nasdaq_buy_hold", BuyAndHold(("ETF_NASDAQ",)), EverySession(), "reference"),
        sa15_reference(),
        BookSpec("Tech_buy_hold", BuyAndHold(("ETF_US_TECH",)), EverySession(), "control"),
        BookSpec("Gold_buy_hold", BuyAndHold(("ETF_GOLD",)), EverySession(), "control"),
        BookSpec(
            "Nasdaq_Gold_buy_hold",
            BuyAndHold(("ETF_NASDAQ", "ETF_GOLD")),
            EverySession(),
            "control",
        ),
    )


def write_json(path: Path, value: object) -> None:
    """Write readable JSON with no NaN."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False, default=str) + "\n",
        encoding="utf-8",
    )


def signature(book: BookSpec, start: str, end: str, multiplier: float, digest: str) -> str:
    """Hash what makes two runs the same run, the code state aside."""
    content = {
        "strategy": dict(book.strategy.definition()),
        "schedule": book.schedule.definition(),
        "start": start,
        "end": end,
        "costs_multiplier": multiplier,
        "universe": UNIVERSE,
        "data_state": digest,
        "analytics": ANALYTICS.definition(),
    }
    return hashlib.sha256(json.dumps(content, sort_keys=True, default=str).encode()).hexdigest()


def finite(value: float | None) -> float | None:
    """Return ``None`` for a missing or non-finite number."""
    return None if value is None or not math.isfinite(value) else float(value)


def curve_metrics(net: pd.Series, gross: pd.Series | None = None) -> dict[str, Any]:  # type: ignore[type-arg]
    """Return the headline measures of one curve under the study convention."""
    stats = PerformanceStats.from_equity(net, ANALYTICS)
    values: dict[str, Any] = {
        "start": net.index[0],
        "end": net.index[-1],
        "net_return": finite(stats.total_return),
        "cagr": finite(stats.annualised_return),
        "volatility": finite(stats.annualised_volatility),
        "sharpe": finite(stats.sharpe_ratio),
        "max_drawdown": finite(stats.drawdown.depth),
    }
    if gross is not None:
        values["gross_return"] = finite(PerformanceStats.from_equity(gross, ANALYTICS).total_return)
    return values


def run_metrics(result: StrategyResult) -> dict[str, Any]:
    """Return the measures, the costs and the order counts of one run."""
    net, gross = result.equity(), result.equity(Book.GROSS)
    values = curve_metrics(net, gross)
    fills, orders = result.fills(), result.orders()
    years = max((result.end - result.start).days / 365.25, 1 / 252)
    traded = math.fsum(float(value) for value in fills["traded_value"]) if len(fills) else 0.0
    per_session = orders.groupby("session_date").size() if len(orders) else pd.Series(dtype=int)
    weights = result.weights()
    values.update(
        costs_eur=float(result.backtest.total_cost),
        traded_value_eur=traded,
        turnover_per_year=traded / float(net.mean()) / years,
        average_exposure=float(weights.sum(axis=1).mean()),
        average_cash=float(1.0 - weights.sum(axis=1).mean()),
        orders=len(orders),
        fills=len(fills),
        rejects=len(result.rejects()),
        intervention_days=len(per_session),
        intervention_days_per_year=len(per_session) / years,
        orders_per_intervention_mean=float(per_session.mean()) if len(per_session) else 0.0,
        orders_per_intervention_max=int(per_session.max()) if len(per_session) else 0,
        decisions=sum(record.decision is not None for record in result.records()),
        decisions_with_unreadable_inputs=sum(
            bool(record.decision.requested.skipped)
            for record in result.records()
            if record.decision is not None
        ),
        run_id=result.run_id,
        data_state=result.data_state.digest,
    )
    return values


def save_run(folder: Path, result: StrategyResult, book: BookSpec, key: str) -> dict[str, Any]:
    """Write one run's measures, curves, trades and decisions."""
    folder.mkdir(parents=True, exist_ok=True)
    values = run_metrics(result)
    values["signature"] = key
    values["role"] = book.role
    write_json(folder / "metrics.json", values)
    write_json(folder / "strategy.json", dict(book.strategy.definition()))
    write_json(folder / "schedule.json", book.schedule.definition())
    write_json(folder / "configuration.json", dict(result.configuration))
    result.equity().rename("net_equity").to_csv(folder / "equity.csv", index_label="session_date")
    result.equity(Book.GROSS).rename("gross_equity").to_csv(
        folder / "gross_equity.csv", index_label="session_date"
    )
    result.weights().round(6).to_csv(folder / "weights.csv", index_label="session_date")
    result.fills().to_csv(folder / "fills.csv", index=False)
    result.orders().to_csv(folder / "orders.csv", index=False)
    result.rejects().to_csv(folder / "rejects.csv", index=False)
    rows = []
    for record in result.records():
        if record.decision is None:
            continue
        requested = record.decision.requested
        rows.append(
            {
                "session_date": record.session_date,
                "hold_positions": requested.hold_positions,
                "weights": json.dumps(dict(requested.weights), sort_keys=True),
                "skipped": json.dumps(
                    {name: status.value for name, status in requested.skipped.items()},
                    sort_keys=True,
                ),
            }
        )
    pd.DataFrame(rows).to_csv(folder / "decisions.csv", index=False)
    return values


def run_book(
    book: BookSpec,
    window: tuple[str, str],
    folder: Path,
    *,
    multiplier: float = 1.0,
    store: Path = STORE,
) -> dict[str, Any]:
    """Run one book, or read it back if the same run is already saved."""
    runner = build_runner(store, multiplier)
    with runner.reader.pinned() as state:
        digest = state.digest
    key = signature(book, window[0], window[1], multiplier, digest)
    saved = folder / "metrics.json"
    if saved.exists():
        values = json.loads(saved.read_text(encoding="utf-8"))
        if values.get("signature") == key:
            print(f"  reused {folder.relative_to(ROOT)}", flush=True)
            return values
        raise FileExistsError(f"{folder} holds a different run; choose a new folder")
    print(f"  running {book.name} x{multiplier:g} {window[0]} -> {window[1]}", flush=True)
    result = runner.run(book.strategy, UNIVERSE, window[0], window[1], schedule=book.schedule)
    return save_run(folder, result, book, key)


def load_curve(folder: Path, name: str = "equity.csv") -> pd.Series:  # type: ignore[type-arg]
    """Read a saved curve with date labels."""
    frame = pd.read_csv(folder / name)
    index = pd.Index([date.fromisoformat(value) for value in frame["session_date"]])
    return pd.Series(frame.iloc[:, 1].to_numpy(dtype=float), index=index)


def slice_metrics(curve: pd.Series, start: str, end: str) -> dict[str, Any] | None:  # type: ignore[type-arg]
    """Measure a slice of a continuous book, anchored on the close before it."""
    lower, upper = date.fromisoformat(start), date.fromisoformat(end)
    before = curve[curve.index < lower]
    inside = curve[(curve.index >= lower) & (curve.index <= upper)]
    if len(inside) < 3:
        return None
    if len(before):
        inside = pd.concat([before.iloc[-1:], inside])
    return curve_metrics(inside)


def yearly_returns(curve: pd.Series) -> dict[str, float]:  # type: ignore[type-arg]
    """Return the calendar-year returns of a continuous book (partial years too)."""
    years: dict[str, float] = {}
    previous = None
    for year in sorted({day.year for day in curve.index}):
        inside = curve[[day.year == year for day in curve.index]]
        anchor = previous if previous is not None else inside.iloc[0]
        years[str(year)] = float(inside.iloc[-1] / anchor - 1.0)
        previous = inside.iloc[-1]
    return years


def compare_books(folders: Mapping[str, Path], target: str) -> dict[str, Any]:
    """Compare ``target`` with every other book: slices, years, bootstrap."""
    curves = {name: load_curve(folder) for name, folder in folders.items()}
    common = curves[target].index
    for curve in curves.values():
        common = common.intersection(curve.index)
    curves = {name: curve.loc[common] for name, curve in curves.items()}
    episodes = {
        name: {book: slice_metrics(curve, *bounds) for book, curve in curves.items()}
        for name, bounds in EPISODES.items()
    }
    years = {book: yearly_returns(curve) for book, curve in curves.items()}
    tests: dict[str, Any] = {}
    for name, curve in curves.items():
        if name == target:
            continue
        tests[name] = {}
        for statistic in (PairedStatistic.SHARPE, PairedStatistic.MEAN_RETURN):
            outcome = paired_block_bootstrap(
                curves[target],
                curve,
                statistic=statistic,
                block=BOOTSTRAP["block"],
                draws=BOOTSTRAP["draws"],
                seed=BOOTSTRAP["seed"],
                level=BOOTSTRAP["level"],
                config=ANALYTICS,
            )
            tests[name][statistic.value] = outcome.definition()
    return {
        "sessions": len(common),
        "start": common[0],
        "end": common[-1],
        "full": {book: curve_metrics(curve) for book, curve in curves.items()},
        "years": years,
        "episodes": episodes,
        "paired_bootstrap": tests,
    }


def references(store: Path, output: Path) -> dict[str, Path]:
    """Run the references and passive controls on the study window, x1 and x2."""
    folders = {}
    for book in reference_books():
        for multiplier in (1.0, 2.0):
            folder = output / "references" / f"x{multiplier:g}" / book.name
            run_book(book, WINDOWS["full"], folder, multiplier=multiplier, store=store)
            if multiplier == 1.0:
                folders[book.name] = folder
    return folders


def reproduce(store: Path, output: Path) -> None:
    """Rerun SA15's selection and Nasdaq on SA15's window; compare with its archive."""
    archive = ROOT / "results" / "SA15_GPT-6.1_R4"
    pairs = {
        "SA15_R4_trial71": archive / "full" / "SA15_GPT-6.1_R4",
        "Nasdaq_buy_hold": archive / "full" / "Nasdaq_buy_hold",
    }
    books = {book.name: book for book in reference_books()}
    report: dict[str, Any] = {}
    for name, archived in pairs.items():
        folder = output / "reproduction" / name
        values = run_book(books[name], WINDOWS["sa15"], folder, store=store)
        mine = load_curve(folder)
        theirs = load_curve(archived) if (archived / "equity.csv").exists() else None
        entry: dict[str, Any] = {"rerun": {k: values[k] for k in ("net_return", "sharpe")}}
        if theirs is not None:
            common = mine.index.intersection(theirs.index)
            gap = (mine.loc[common] / theirs.loc[common] - 1.0).abs()
            entry.update(
                archived_net_return=float(theirs.iloc[-1] / theirs.iloc[0] - 1.0),
                sessions_compared=len(common),
                sessions_only_rerun=len(mine.index.difference(theirs.index)),
                sessions_only_archive=len(theirs.index.difference(mine.index)),
                largest_relative_gap=float(gap.max()),
                first_session_gap_above_1e6=(
                    None if not (gap > 1e-6).any() else gap[gap > 1e-6].index[0]
                ),
                final_value_rerun=float(mine.loc[common].iloc[-1]),
                final_value_archive=float(theirs.loc[common].iloc[-1]),
            )
        report[name] = entry
        print(json.dumps({name: entry}, indent=2, default=str), flush=True)
    write_json(output / "reproduction" / "reproduction.json", report)


def main(arguments: Sequence[str] | None = None) -> None:
    """Run one phase of the study."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("reproduce", "references"))
    parser.add_argument("--store", type=Path, default=STORE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    options = parser.parse_args(arguments)
    if options.phase == "reproduce":
        reproduce(options.store, options.output)
    else:
        folders = references(options.store, options.output)
        summary = compare_books(folders, "SA15_R4_trial71")
        write_json(options.output / "references" / "comparison.json", summary)


if __name__ == "__main__":
    main()
