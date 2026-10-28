"""Run SA15 round two: ten numbered designs and immutable diagnostic replays.

Importing this module never imports the new candidate policy or runs a backtest.
References are buy-and-hold books, including an initially equal, drifting basket.
Only development and validation influence the frozen selection; final/full and
cost/start diagnostics cannot create or replace a candidate. All dates use the
existing runner's explicit market calendars and evening availability rules.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
from SA15_run_gpt61_study import (
    ANALYTICS as ANALYTICS,
)
from SA15_run_gpt61_study import (
    ROOT,
    archive_sources,
    build_runner,
    plain_configuration,
    save_run,
    write_json,
)
from SA15_run_gpt61_study import (
    load_equity as load_equity,
)
from SA15_run_gpt61_study import (
    metrics as metrics,
)

from quant_backtester.backtest.runner import StrategyRunner
from quant_backtester.backtest.schedule import DecisionSchedule, EverySession, Monthly, Weekly
from quant_backtester.research.references import BuyAndHold
from quant_backtester.strategies.base import Strategy

STORE = ROOT / "runs/sa15_gpt61_store"
OUTPUT = ROOT / "results/SA15_GPT-6.1_R2"
STRATEGY_NAME = "SA15_GPT-6.1_R2"
PERIODS = {
    "development": ("2019-06-03", "2022-12-30"),
    "validation": ("2023-01-02", "2024-12-31"),
    "final": ("2025-01-02", "2026-10-09"),
    "full": ("2019-06-03", "2026-10-09"),
}
UNIVERSE = (
    "ETF_SP500_PEA",
    "ETF_NASDAQ",
    "ETF_EMERGING",
    "ETF_GOLD",
    "ETF_EURO_GOV",
    "ETF_COMMODITY",
    "ETF_MONETARY_EUR",
    "ETF_WORLD",
)
UNIVERSE_IDS = UNIVERSE


@dataclass(frozen=True, slots=True)
class MonthlyFromStart(Monthly):
    """Decide on the first run session and on genuine subsequent month ends."""

    initial_decision: bool = field(default=True, init=False)

    def definition(self) -> dict[str, object]:
        """Record the initial decision in the schedule's immutable identity."""
        return {"type": "MonthlyFromStart", "parameters": {"initial_decision": True}}

    def decision_sessions(
        self, sessions: Sequence[date], following: date | None
    ) -> frozenset[date]:
        """Add the first session without inventing an end for a truncated month."""
        regular = Monthly.decision_sessions(self, sessions, following)
        return regular | frozenset(sessions[:1])


@dataclass(frozen=True, slots=True)
class WeeklyFromStart(Weekly):
    """Decide on the first run session and on genuine subsequent week ends."""

    initial_decision: bool = field(default=True, init=False)

    def definition(self) -> dict[str, object]:
        """Record the initial decision in the schedule's immutable identity."""
        return {"type": "WeeklyFromStart", "parameters": {"initial_decision": True}}

    def decision_sessions(
        self, sessions: Sequence[date], following: date | None
    ) -> frozenset[date]:
        """Add the first session without inventing an end for a truncated week."""
        regular = Weekly.decision_sessions(self, sessions, following)
        return regular | frozenset(sessions[:1])


SCHEDULES = {"weekly": WeeklyFromStart, "monthly": MonthlyFromStart}
START_DATES = ("2020-01-02", "2021-01-04", "2022-01-03", "2023-01-02")
REFERENCE_INSTRUMENTS = {
    "SP500_buy_hold": ("ETF_SP500_PEA",),
    "Nasdaq_buy_hold": ("ETF_NASDAQ",),
    "static_50_50": ("ETF_SP500_PEA", "ETF_NASDAQ"),
}
REFERENCES = REFERENCE_INSTRUMENTS
BASE_ARTIFACTS = (
    "metrics.json",
    "configuration.json",
    "strategy.json",
    "identity.json",
    "equity.csv",
)


def universe(_strategy: Strategy | None = None) -> tuple[str, ...]:
    """Return the same eight EUR instruments for every candidate and reference."""
    return UNIVERSE


def read_spec(path: Path) -> tuple[dict[str, Any], Strategy]:
    """Validate a numbered design, then lazily construct its frozen policy."""
    spec = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(spec, dict) or set(spec) != {"number", "reason", "schedule", "parameters"}:
        raise ValueError("candidate needs exactly number, reason, schedule and parameters")
    number = spec["number"]
    if isinstance(number, bool) or not isinstance(number, int) or not 11 <= number <= 20:
        raise ValueError("candidate number must be an integer from 11 to 20")
    if (
        spec["schedule"] not in SCHEDULES
        or not isinstance(spec["reason"], str)
        or not spec["reason"].strip()
        or not isinstance(spec["parameters"], dict)
    ):
        raise ValueError("candidate needs a valid schedule, written reason and parameters")
    parameters = dict(spec["parameters"])
    for key in ("satellite_ids", "momentum_lookbacks", "momentum_weights"):
        if key in parameters:
            if not isinstance(parameters[key], list | tuple):
                raise ValueError(f"{key} must be a list or tuple")
            parameters[key] = tuple(parameters[key])
    from quant_backtester.strategies.SA15_gpt61_relative import SA15RelativeMomentum

    strategy = SA15RelativeMomentum(**parameters)
    names = (*strategy.satellite_ids, strategy.core_id, strategy.monetary_id)
    if any(name not in UNIVERSE for name in names):
        raise ValueError("candidate holdings must belong to the fixed eight-instrument universe")
    return spec, strategy


def reference_books() -> dict[str, BuyAndHold]:
    """Return three initially purchased books, with no subsequent rebalancing."""
    return {
        name: BuyAndHold(instruments=names, strategy_id=name)
        for name, names in REFERENCE_INSTRUMENTS.items()
    }


def source_finance_hashes(*, candidate: bool = False) -> dict[str, str]:
    """Hash financial dependencies without unfinished reporting or runner scripts.

    Buy-and-hold does not use candidate indicators. Reference caches therefore
    ignore new signal/policy files, while candidate caches include those bytes.
    """
    package = ROOT / "src/quant_backtester"
    paths = {
        ROOT / "scripts/SA15_run_gpt61_study.py",
        ROOT / "uv.lock",
        package / "research/references.py",
        package / "strategies/base.py",
        package / "numbers.py",
        package / "provenance.py",
    }
    for tree in ("analytics", "backtest", "data", "execution", "portfolio"):
        paths.update((package / tree).rglob("*.py"))
    for name in ("base.py", "engine.py", "types.py"):
        paths.add(package / "signals" / name)
    if candidate:
        paths.add(Path(__file__).resolve())
        paths.update((package / "signals").rglob("*.py"))
        paths.update((package / "strategies/adaptive").rglob("*.py"))
        paths.add(package / "strategies/SA15_gpt61_relative.py")
    return {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(paths)
        if path.is_file()
    }


def expected_signature(
    runner: StrategyRunner,
    book: Strategy,
    schedule: DecisionSchedule,
    start: str,
    end: str,
    *,
    candidate: bool = False,
) -> dict[str, Any]:
    """Record inputs required to reuse a result, excluding unrelated source edits."""
    with runner.reader.pinned() as state:
        data_digest = state.digest
    return plain_configuration(
        {
            "format": 1,
            "data_state": data_digest,
            "fingerprint": book.fingerprint(),
            "strategy": book.definition(),
            "source_finance_hashes": source_finance_hashes(candidate=candidate),
            "configuration": {
                "requested_start": start,
                "requested_end": end,
                "data_state": data_digest,
                "execution": runner.execution.definition(),
                "initial_cash": runner.initial_cash,
                "base_currency": runner.base_currency,
                "reference_calendar": runner.reference_calendar_id,
                "timetable": runner.timetable.definition(),
                "analytics": runner.analytics.definition(),
                "portfolio": {"limits": runner.limits.definition()},
                "schedule": schedule.definition(),
                "universe": {"type": "StaticUniverse", "members": sorted(UNIVERSE)},
            },
        }
    )


def cached_metrics(folder: Path, expected: Mapping[str, Any]) -> dict[str, Any] | None:
    """Reuse only complete, internally consistent results with matching inputs."""
    cache = folder / "cache.json"
    present = [name for name in (*BASE_ARTIFACTS, "cache.json") if (folder / name).exists()]
    if not present:
        return None
    if len(present) != len(BASE_ARTIFACTS) + 1:
        raise ValueError(f"incomplete result cache: {folder}")
    saved = json.loads(cache.read_text(encoding="utf-8"))
    if saved.get("signature") != expected:
        raise ValueError(f"cache conditions differ: {folder}")
    for name, digest in saved.get("artifacts", {}).items():
        path = folder / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f"cache artifact differs: {path}")
    if not set(BASE_ARTIFACTS) <= set(saved.get("artifacts", {})):
        raise ValueError(f"incomplete result cache checksums: {folder}")
    identity = json.loads((folder / "identity.json").read_text())
    configuration = json.loads((folder / "configuration.json").read_text())
    strategy = json.loads((folder / "strategy.json").read_text())
    if (
        identity.get("fingerprint") != expected["fingerprint"]
        or identity.get("data_state", {}).get("digest") != expected["data_state"]
        or strategy != expected["strategy"]
        or any(configuration.get(key) != value for key, value in expected["configuration"].items())
    ):
        raise ValueError(f"cache conditions differ in saved evidence: {folder}")
    return json.loads((folder / "metrics.json").read_text())


def run_cached(
    runner: StrategyRunner,
    book: Strategy,
    schedule: DecisionSchedule,
    start: str,
    end: str,
    folder: Path,
    *,
    candidate: bool = False,
    details: bool = True,
) -> dict[str, Any]:
    """Run an announced book or validate and reuse its immutable saved result."""
    expected = expected_signature(runner, book, schedule, start, end, candidate=candidate)
    cached = cached_metrics(folder, expected)
    if cached is not None:
        return cached
    print(f"run {folder}: {start} -> {end}", flush=True)
    result = runner.run(book, UNIVERSE, start, end, schedule=schedule)
    if result.data_state.digest != expected["data_state"]:
        raise ValueError("data changed after result signature was captured")
    if result.fingerprint != expected["fingerprint"]:
        raise ValueError("strategy changed after result signature was captured")
    values = save_run(folder, result, details=details)
    artifacts = BASE_ARTIFACTS + (
        ("weights.csv", "fills.csv", "rejects.csv", "decisions.csv") if details else ()
    )
    write_json(
        folder / "cache.json",
        {
            "signature": expected,
            "artifacts": {
                name: hashlib.sha256((folder / name).read_bytes()).hexdigest() for name in artifacts
            },
        },
    )
    return values


def run_references(
    runner: StrategyRunner, period: str, output: Path = OUTPUT
) -> dict[str, dict[str, Any]]:
    """Run the three reference books, which are never selection candidates."""
    if period not in PERIODS:
        raise ValueError(f"unknown period {period}")
    return {
        name: run_cached(
            runner,
            book,
            EverySession(),
            *PERIODS[period],
            output / "references" / period / name,
            details=False,
        )
        for name, book in reference_books().items()
    }


def selection_score(
    development: Mapping[str, Any],
    validation: Mapping[str, Any],
    development_reference: Mapping[str, Any],
    validation_reference: Mapping[str, Any],
) -> dict[str, Any]:
    """Score excess CAGR on development/validation only, with stability priority."""
    values = [
        float(row["cagr"])
        for row in (development, validation, development_reference, validation_reference)
    ]
    if not all(math.isfinite(value) for value in values):
        raise ValueError("selection requires finite CAGR in both periods")
    first, second = values[0] - values[2], values[1] - values[3]
    return {
        "excess_development": first,
        "excess_validation": second,
        "both_excess_positive": first > 0.0 and second > 0.0,
        "score": (first + second) / 2.0 - 0.25 * abs(first - second),
    }


def update_trials(output: Path) -> pd.DataFrame:
    """Publish every completed numbered candidate, retaining failed designs."""
    rows = []
    for number in range(11, 21):
        folder = output / f"trial_{number:02d}"
        if not (folder / "selection.json").is_file():
            continue
        spec = json.loads((folder / "candidate.json").read_text())
        if spec["number"] != number:
            raise ValueError("folder and archived candidate number differ")
        selection = json.loads((folder / "selection.json").read_text())
        row = {
            "trial": number,
            "reason": spec["reason"],
            **{
                key: selection[key]
                for key in (
                    "score",
                    "both_excess_positive",
                    "excess_development",
                    "excess_validation",
                )
            },
        }
        for period, values in selection["metrics"].items():
            row.update({f"{period}_{key}": value for key, value in values.items()})
        rows.append(row)
    table = pd.DataFrame(rows)
    output.mkdir(parents=True, exist_ok=True)
    table.to_csv(output / "iterations.csv", index=False)
    return table


def iterate(config: Path, runner: StrategyRunner, output: Path = OUTPUT) -> None:
    """Execute one of ten progressively numbered designs before selection freezes."""
    if (output / "selected.json").exists():
        raise ValueError("selection is already frozen; no further candidates")
    spec, strategy = read_spec(config)
    folder = output / f"trial_{spec['number']:02d}"
    if folder.exists() and any(folder.iterdir()):
        raise FileExistsError(f"{folder} will not be overwritten")
    used = [
        number
        for number in range(11, 21)
        if (output / f"trial_{number:02d}/candidate.json").exists()
    ]
    if spec["number"] != 11 + len(used) or used != list(range(11, 11 + len(used))):
        raise ValueError("candidate numbers must progress from 11 through 20")
    if any(not (output / f"trial_{number:02d}/selection.json").is_file() for number in used):
        raise ValueError("complete the existing candidate before starting another")
    write_json(folder / "candidate.json", spec)
    rows, references = {}, {}
    for period in ("development", "validation"):
        references[period] = run_references(runner, period, output)["SP500_buy_hold"]
        rows[period] = run_cached(
            runner,
            strategy,
            SCHEDULES[spec["schedule"]](),
            *PERIODS[period],
            folder / period,
            candidate=True,
        )
    selection = selection_score(
        rows["development"], rows["validation"], references["development"], references["validation"]
    )
    write_json(
        folder / "selection.json",
        {
            **selection,
            "fingerprint": strategy.fingerprint(),
            "metrics": rows,
            "references": references,
        },
    )
    update_trials(output)
    print(json.dumps({"trial": spec["number"], **selection}), flush=True)


def frozen_winner(output: Path) -> tuple[dict[str, Any], Strategy]:
    """Read the already frozen winner and refuse a changed archived design."""
    selected = json.loads((output / "selected.json").read_text())
    number = selected["candidate"]["number"]
    spec, strategy = read_spec(output / f"trial_{number:02d}/candidate.json")
    if spec != selected["candidate"] or strategy.fingerprint() != selected["fingerprint"]:
        raise ValueError("frozen winner differs from its archived candidate")
    if plain_configuration(strategy.definition())["parameters"] != selected["parameters"]:
        raise ValueError("frozen winner parameters differ")
    return spec, strategy


def finalise(runner: StrategyRunner, output: Path = OUTPUT, store: Path = STORE) -> None:
    """Freeze the winning design before any final-period reference or policy run."""
    if (output / "selected.json").exists():
        raise FileExistsError("final selection already exists")
    trials = update_trials(output)
    if trials.empty:
        raise ValueError("no completed candidate to select")
    ranked = trials.sort_values(
        ["both_excess_positive", "score", "trial"], ascending=[False, False, True]
    )
    chosen = ranked.iloc[0]
    number = int(chosen["trial"])
    spec, strategy = read_spec(output / f"trial_{number:02d}/candidate.json")
    for row in trials.itertuples():
        path = output / f"trial_{row.trial:02d}"
        checked_spec, checked_book = read_spec(path / "candidate.json")
        for period in ("development", "validation"):
            expected = expected_signature(
                runner,
                checked_book,
                SCHEDULES[checked_spec["schedule"]](),
                *PERIODS[period],
                candidate=True,
            )
            if cached_metrics(path / period, expected) is None:
                raise ValueError(f"completed trial has no verified result: {path}")
    write_json(
        output / "selected.json",
        {
            "candidate": spec,
            "score": float(chosen["score"]),
            "fingerprint": strategy.fingerprint(),
            "parameters": plain_configuration(strategy.definition())["parameters"],
            "both_excess_positive": bool(chosen["both_excess_positive"]),
            "selection_uses": ["development", "validation"],
            "total_trials": 20,
            "round_trials": len(trials),
            "final_period": PERIODS["final"],
        },
    )
    archive_sources(output, store)
    run_references(runner, "final", output)
    run_cached(
        runner,
        strategy,
        SCHEDULES[spec["schedule"]](),
        *PERIODS["final"],
        output / "final" / STRATEGY_NAME,
        candidate=True,
    )
    run_cached(
        build_runner(store, 2.0),
        strategy,
        SCHEDULES[spec["schedule"]](),
        *PERIODS["final"],
        output / "final/costs_x2",
        candidate=True,
    )


@dataclass(frozen=True, slots=True)
class DiagnosticJob:
    """One predefined replay; workers only read the shared market data store."""

    store: Path
    folder: Path
    start: str
    end: str
    diagnostic: str
    period: str
    book: str
    candidate: Path | None = None
    multiplier: float = 1.0


def build_jobs(store: Path, output: Path) -> tuple[DiagnosticJob, ...]:
    """Build twenty cost, four cash-start and four full-history jobs at most."""
    spec, _ = frozen_winner(output)
    winner = output / f"trial_{spec['number']:02d}/candidate.json"
    jobs = []
    for number in range(11, 21):
        folder = output / f"trial_{number:02d}"
        if not (folder / "selection.json").is_file():
            continue
        saved, _ = read_spec(folder / "candidate.json")
        if saved["number"] != number:
            raise ValueError("folder and archived candidate number differ")
        for period in ("development", "validation"):
            jobs.append(
                DiagnosticJob(
                    store,
                    folder / "costs_x2" / period,
                    *PERIODS[period],
                    "costs_x2",
                    period,
                    STRATEGY_NAME,
                    folder / "candidate.json",
                    2.0,
                )
            )
    for start in START_DATES:
        jobs.append(
            DiagnosticJob(
                store,
                output / "robustness/starts" / start,
                start,
                "2024-12-31",
                "starts",
                start,
                STRATEGY_NAME,
                winner,
            )
        )
    for name in (STRATEGY_NAME, *REFERENCE_INSTRUMENTS):
        jobs.append(
            DiagnosticJob(
                store,
                output / "full" / name,
                *PERIODS["full"],
                "full",
                "full",
                name,
                winner if name == STRATEGY_NAME else None,
            )
        )
    return tuple(jobs)


def run_job(job: DiagnosticJob) -> dict[str, Any]:
    """Execute one immutable diagnostic, or verify its existing cached result."""
    runner = build_runner(job.store, job.multiplier)
    if job.candidate is not None:
        spec, book = read_spec(job.candidate)
        schedule = SCHEDULES[spec["schedule"]]()
    else:
        spec = None
        book = reference_books()[job.book]
        schedule = EverySession()
    values = run_cached(
        runner,
        book,
        schedule,
        job.start,
        job.end,
        job.folder,
        candidate=job.candidate is not None,
        details=job.candidate is not None,
    )
    return {
        "diagnostic": job.diagnostic,
        "period": job.period,
        "book": job.book,
        "trial": None if spec is None else spec["number"],
        "start": job.start,
        "end": job.end,
        **values,
    }


def robustness(store: Path, output: Path, workers: int = 2) -> None:
    """Replay previously chosen policies with bounded independent read workers."""
    if workers not in (2, 3):
        raise ValueError("workers must be 2 or 3")
    jobs = build_jobs(store, output)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(run_job, jobs))
    folder = output / "robustness"
    folder.mkdir(parents=True, exist_ok=True)
    for diagnostic in ("costs_x2", "starts", "full"):
        pd.DataFrame([row for row in rows if row["diagnostic"] == diagnostic]).to_csv(
            folder / f"{diagnostic}.csv", index=False
        )


def parse_arguments(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    """Validate mutually exclusive phases before opening the store."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, default=STORE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--workers", type=int, choices=(2, 3), default=2)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--candidate", type=Path)
    mode.add_argument("--references-only", action="store_true")
    mode.add_argument("--final", action="store_true")
    mode.add_argument("--robustness", action="store_true")
    return parser.parse_args(arguments)


def main(arguments: Sequence[str] | None = None) -> None:
    """Execute one announced phase; never render or select a reference book."""
    options = parse_arguments(arguments)
    if options.robustness:
        robustness(options.store, options.output, options.workers)
        return
    runner = build_runner(options.store)
    if options.references_only:
        for period in ("development", "validation"):
            run_references(runner, period, options.output)
    elif options.final:
        finalise(runner, options.output, options.store)
    else:
        iterate(options.candidate, runner, options.output)


if __name__ == "__main__":
    main()
