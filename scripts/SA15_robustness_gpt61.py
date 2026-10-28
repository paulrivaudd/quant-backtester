"""Replay completed SA15 designs for cost and cash-start diagnostics, without selection.

The store is read only. Cost stress keeps each completed design and its schedule
unchanged. Start-date tests require the already frozen winner, restart from
100,000 EUR cash, and stop before the final evaluation period.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from SA15_run_gpt61_study import (
    DEFAULT_OUTPUT,
    DEFAULT_STORE,
    PERIODS,
    ROOT,
    SCHEDULES,
    build_runner,
    load_equity,
    plain_configuration,
    read_candidate,
    save_run,
    universe,
    write_json,
)

from quant_backtester.backtest.runner import StrategyRunner
from quant_backtester.backtest.schedule import DecisionSchedule, EverySession, Weekly
from quant_backtester.research.references import BuyAndHold, EqualWeightRebalance
from quant_backtester.strategies.base import Strategy
from quant_backtester.strategies.SA1_world_ma20_benchmark import WorldMA20Benchmark
from quant_backtester.strategies.SA15_gpt61 import SA15GPT61

START_DATES = ("2020-01-02", "2021-01-04", "2022-01-03", "2023-01-02")
START_END = "2024-12-31"
FULL_PERIOD = ("2019-06-03", "2026-10-09")
FULL_BOOKS = ("SA15_GPT-6.1", "World_buy_hold", "SA1_MA20", "SP500_buy_hold", "equal_weight")


@dataclass(frozen=True, slots=True)
class DiagnosticJob:
    """One independent replay, safe to send to a worker process.

    Attributes
    ----------
    candidate : Path
        Archived candidate parameters; never a newly generated design.
    store, folder : Path
        Read-only market store and distinct result destination.
    diagnostic, period : str
        Diagnostic family and descriptive period label.
    start, end : str
        Requested ISO session bounds.
    multiplier : float
        Transaction-cost multiplier with all policy parameters unchanged.
    book : str
        Candidate or explicitly named descriptive reference.
    """

    candidate: Path
    store: Path
    folder: Path
    diagnostic: str
    period: str
    start: str
    end: str
    multiplier: float
    book: str = "SA15_GPT-6.1"


def parse_arguments(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse exclusive diagnostic modes and a bounded worker count."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, default=2)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--costs-only", action="store_const", const="costs", dest="mode")
    modes.add_argument("--starts-only", action="store_const", const="starts", dest="mode")
    modes.add_argument("--full-only", action="store_const", const="full", dest="mode")
    parser.set_defaults(mode="both")
    options = parser.parse_args(arguments)
    if not 1 <= options.workers <= 3:
        parser.error("--workers must be an integer between 1 and 3")
    return options


def selected_candidate(output: Path) -> Path:
    """Require a frozen selection and verify it against the archived candidate."""
    selected = json.loads((output / "selected.json").read_text(encoding="utf-8"))
    number = selected["candidate"]["number"]
    if isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= 10:
        raise ValueError("selected candidate number must be an integer from 1 to 10")
    candidate = output / f"trial_{number:02d}" / "candidate.json"
    spec, allocation = read_candidate(candidate)
    if (
        spec != selected["candidate"]
        or allocation.fingerprint() != selected["candidate_fingerprint"]
        or not (candidate.parent / "selection.json").is_file()
    ):
        raise ValueError("frozen winner differs from the completed archived design")
    return candidate


def build_jobs(store: Path, output: Path, mode: str) -> tuple[DiagnosticJob, ...]:
    """Describe replays from completed artifacts without running any backtest."""
    if mode not in {"both", "costs", "starts", "full"}:
        raise ValueError("unknown diagnostic mode")
    store, output = store.resolve(), output.resolve()
    # Validate the frozen winner before starting any jobs in a combined run.
    selected = selected_candidate(output) if mode in {"both", "starts", "full"} else None
    jobs: list[DiagnosticJob] = []
    if mode in {"both", "costs"}:
        for completion in sorted(output.glob("trial_*/selection.json")):
            candidate = completion.parent / "candidate.json"
            spec, _ = read_candidate(candidate)
            if completion.parent.name != f"trial_{spec['number']:02d}":
                raise ValueError("trial folder and archived candidate number differ")
            for period in ("development", "validation"):
                start, end = PERIODS[period]
                jobs.append(
                    DiagnosticJob(
                        candidate,
                        store,
                        completion.parent / "costs_x2" / period,
                        "costs_x2",
                        period,
                        start,
                        end,
                        2.0,
                    )
                )
    if mode in {"both", "starts"}:
        assert selected is not None
        for start in START_DATES:
            jobs.append(
                DiagnosticJob(
                    selected,
                    store,
                    output / "robustness" / "starts" / start,
                    "starts",
                    start,
                    start,
                    START_END,
                    1.0,
                )
            )
    if mode == "full":
        assert selected is not None
        for book in FULL_BOOKS:
            jobs.append(
                DiagnosticJob(
                    selected,
                    store,
                    output / "full" / book,
                    "full",
                    "full",
                    *FULL_PERIOD,
                    1.0,
                    book,
                )
            )
    if not jobs:
        raise ValueError("no completed candidate is available for these diagnostics")
    return tuple(jobs)


def book_and_schedule(
    job: DiagnosticJob, spec: Mapping[str, object], allocation: SA15GPT61
) -> tuple[Strategy, DecisionSchedule]:
    """Reconstruct the identical policy or an explicitly named reference."""
    if job.book == "SA15_GPT-6.1":
        return allocation, SCHEDULES[str(spec["schedule"])]()
    books: dict[str, Strategy] = {
        "World_buy_hold": BuyAndHold(instruments=("ETF_WORLD",)),
        "SA1_MA20": WorldMA20Benchmark(),
        "SP500_buy_hold": BuyAndHold(instruments=("ETF_SP500_PEA",)),
        "equal_weight": EqualWeightRebalance(instruments=allocation.risky_ids),
    }
    if job.book not in books or job.diagnostic != "full":
        raise ValueError("references are accepted only in the descriptive full-period diagnostic")
    schedule = Weekly() if job.book == "equal_weight" else EverySession()
    return books[job.book], schedule


def source_hashes() -> dict[str, str]:
    """Hash executable package sources and both diagnostic/study scripts."""
    paths = set((ROOT / "src/quant_backtester").rglob("*.py"))
    paths.update(
        ROOT / "scripts" / name
        for name in (
            "SA15_run_gpt61_study.py",
            "SA15_robustness_gpt61.py",
        )
    )
    return {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(paths)
    }


def expected_signature(
    job: DiagnosticJob,
    runner: StrategyRunner,
    allocation: SA15GPT61,
    book: Strategy,
    schedule: DecisionSchedule,
    data_digest: str,
) -> dict:
    """Describe conditions sufficient to reject stale or mismatched saved results."""
    return plain_configuration(
        {
            "diagnostic": job.diagnostic,
            "book": job.book,
            "candidate_fingerprint": allocation.fingerprint(),
            "fingerprint": book.fingerprint(),
            "strategy": book.definition(),
            "data_state": data_digest,
            "source_hashes": source_hashes(),
            "configuration": {
                "requested_start": job.start,
                "requested_end": job.end,
                "initial_cash": runner.initial_cash,
                "base_currency": runner.base_currency,
                "reference_calendar": runner.reference_calendar_id,
                "execution": runner.execution.definition(),
                "schedule": schedule.definition(),
                "timetable": runner.timetable.definition(),
                "analytics": runner.analytics.definition(),
                "portfolio": {"limits": runner.limits.definition()},
                "universe": {"type": "StaticUniverse", "members": sorted(universe(allocation))},
                "data_state": data_digest,
            },
        }
    )


def cached_metrics(folder: Path, expected: Mapping) -> dict | None:
    """Reuse only complete metrics with matching identity, policy and execution."""
    artifacts = (
        "metrics.json",
        "identity.json",
        "strategy.json",
        "configuration.json",
        "equity.csv",
        "diagnostic.json",
    )
    present = [(folder / name).is_file() for name in artifacts]
    if not any(present):
        return None
    if not all(present):
        raise ValueError(f"incomplete diagnostic artifacts; refusing partial reuse: {folder}")
    signature = json.loads((folder / "diagnostic.json").read_text(encoding="utf-8"))
    identity = json.loads((folder / "identity.json").read_text(encoding="utf-8"))
    definition = json.loads((folder / "strategy.json").read_text(encoding="utf-8"))
    configuration = json.loads((folder / "configuration.json").read_text(encoding="utf-8"))
    identity_state = identity.get("data_state")
    if (
        signature != expected
        or identity.get("fingerprint") != expected["fingerprint"]
        or not isinstance(identity_state, Mapping)
        or identity_state.get("digest") != expected["data_state"]
        or definition != expected["strategy"]
        or any(configuration.get(key) != value for key, value in expected["configuration"].items())
    ):
        raise ValueError(f"diagnostic conditions differ from saved evidence: {folder}")
    return json.loads((folder / "metrics.json").read_text(encoding="utf-8"))


def execute_job(job: DiagnosticJob) -> dict:
    """Run one policy afresh from cash or reuse fully verified diagnostic evidence."""
    spec, allocation = read_candidate(job.candidate)
    book, schedule = book_and_schedule(job, spec, allocation)
    runner = build_runner(job.store, job.multiplier)
    with runner.reader.pinned() as state:
        data_digest = state.digest
    signature = expected_signature(job, runner, allocation, book, schedule, data_digest)
    values = cached_metrics(job.folder, signature)
    reused = values is not None
    if values is None:
        print(
            f"diagnostic {job.diagnostic}: trial {spec['number']} {job.period} {job.book}",
            flush=True,
        )
        result = runner.run(book, universe(allocation), job.start, job.end, schedule=schedule)
        if result.data_state.digest != data_digest or result.fingerprint != book.fingerprint():
            raise ValueError("diagnostic inputs changed after its signature was captured")
        values = save_run(job.folder, result)
        write_json(job.folder / "diagnostic.json", signature)
    row = {
        "trial": spec["number"],
        "diagnostic": job.diagnostic,
        "period": job.period,
        "book": job.book,
        "start": job.start,
        "end": job.end,
        "cost_multiplier": job.multiplier,
        "reused": reused,
        **values,
    }
    if job.diagnostic == "costs_x2":
        base_path = job.candidate.parent / job.period / "metrics.json"
        if base_path.is_file():
            baseline = json.loads(base_path.read_text(encoding="utf-8"))
            for key in ("cagr", "net_return", "max_drawdown", "costs_eur"):
                row[f"base_{key}"] = baseline.get(key)
                if values.get(key) is not None and baseline.get(key) is not None:
                    row[f"delta_{key}"] = values[key] - baseline[key]
    return row


def save_summaries(output: Path, rows: Sequence[Mapping[str, object]]) -> None:
    """Publish diagnostics separately from selection artifacts and scores."""
    table = pd.DataFrame(rows)
    folder = output / "robustness"
    folder.mkdir(parents=True, exist_ok=True)
    for diagnostic in table["diagnostic"].unique():
        subset = table.loc[table["diagnostic"] == diagnostic].sort_values(
            ["trial", "start", "book"]
        )
        subset.to_csv(folder / f"{diagnostic}.csv", index=False)
    if set(table["diagnostic"]) == {"full"}:
        destination = output / "comparison/full"
        destination.mkdir(parents=True, exist_ok=True)
        table.set_index("book").to_csv(destination / "summary.csv")
        curves = pd.DataFrame(
            {book: load_equity(output / "full" / book / "equity.csv") for book in FULL_BOOKS}
        )
        if curves.isna().any().any():
            raise ValueError("full-period calendars differ; no filling is allowed")
        curves.to_csv(destination / "equity.csv", index_label="session_date")
        returns = curves.pct_change().fillna(0.0)
        yearly = (1.0 + returns).groupby(returns.index.year).prod() - 1.0
        yearly.to_csv(destination / "yearly.csv", index_label="year")
        write_json(
            destination / "interpretation.json",
            {
                "purpose": "Descriptive optimized full-history replay; never used for selection",
                "period": list(FULL_PERIOD),
            },
        )


def main(arguments: Sequence[str] | None = None) -> int:
    """Execute independent diagnostics using one to three read-only workers."""
    options = parse_arguments(arguments)
    jobs = build_jobs(options.store, options.output, options.mode)
    if options.workers == 1:
        rows = [execute_job(job) for job in jobs]
    else:
        with ProcessPoolExecutor(max_workers=options.workers) as executor:
            rows = list(executor.map(execute_job, jobs))
    save_summaries(options.output, rows)
    print(f"saved {len(rows)} {options.mode} diagnostic replays under {options.output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
