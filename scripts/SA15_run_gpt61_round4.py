"""Run SA15 round four: fifty numbered designs and immutable diagnostic replays.

Importing this module never imports the new candidate policy or runs a backtest.
References are buy-and-hold books, including an initially equal, drifting basket.
Only the continuous 2019-2024 book and its validation slice influence selection;
final/full and cost/start diagnostics cannot create or replace a candidate. All dates use the
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
    write_json,
)
from SA15_run_gpt61_study import (
    load_equity as load_equity,
)
from SA15_run_gpt61_study import (
    metrics as metrics,
)
from SA15_run_gpt61_study import (
    save_run as base_save_run,
)

from quant_backtester.analytics.curves import Book
from quant_backtester.analytics.performance import PerformanceStats
from quant_backtester.backtest.runner import StrategyResult, StrategyRunner
from quant_backtester.backtest.schedule import DecisionSchedule, EverySession, Monthly, Weekly
from quant_backtester.research.references import BuyAndHold
from quant_backtester.strategies.base import Strategy

STORE = ROOT / "runs/sa15_gpt61_r4_store"
OUTPUT = ROOT / "results/SA15_GPT-6.1_R4"
STRATEGY_NAME = "SA15_GPT-6.1_R4"
PERIODS = {
    "development": ("2019-06-03", "2022-12-30"),
    "validation": ("2023-01-02", "2024-12-31"),
    "final": ("2025-01-02", "2026-10-09"),
    "choice": ("2019-06-03", "2024-12-31"),
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
    "ETF_US_TECH",
    "ETF_WORLD_HEALTH",
    "ETF_WORLD_UTILITIES",
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


@dataclass(frozen=True, slots=True)
class QuarterlyFromStart(Monthly):
    """Decide at inception and genuine March, June, September, December ends."""

    initial_decision: bool = field(default=True, init=False)

    def definition(self) -> dict[str, object]:
        """Record both the quarter months and the inception decision."""
        return {"type": "QuarterlyFromStart", "parameters": {"initial_decision": True}}

    def decision_sessions(
        self, sessions: Sequence[date], following: date | None
    ) -> frozenset[date]:
        """Keep prefix invariance even when the requested period stops midquarter."""
        regular = Monthly.decision_sessions(self, sessions, following)
        return frozenset(day for day in regular if day.month in (3, 6, 9, 12)) | frozenset(
            sessions[:1]
        )


SCHEDULES = {
    "weekly": WeeklyFromStart,
    "monthly": MonthlyFromStart,
    "quarterly": QuarterlyFromStart,
}
START_DATES = ("2020-01-02", "2021-01-04", "2022-01-03", "2023-01-02")
REFERENCE_INSTRUMENTS = {
    "SP500_buy_hold": ("ETF_SP500_PEA",),
    "Nasdaq_buy_hold": ("ETF_NASDAQ",),
    "Gold_buy_hold": ("ETF_GOLD",),
    "Nasdaq_Gold_50_50": ("ETF_NASDAQ", "ETF_GOLD"),
    "Tech_buy_hold": ("ETF_US_TECH",),
}
REFERENCES = REFERENCE_INSTRUMENTS
BASE_ARTIFACTS = (
    "metrics.json",
    "configuration.json",
    "strategy.json",
    "identity.json",
    "equity.csv",
    "gross_equity.csv",
    "weights.csv",
    "fills.csv",
    "rejects.csv",
    "decisions.csv",
)


def universe(_strategy: Strategy | None = None) -> tuple[str, ...]:
    """Return the same eleven EUR instruments for every candidate and reference."""
    return UNIVERSE


def read_spec(path: Path) -> tuple[dict[str, Any], Strategy]:
    """Validate one fully explicit design before constructing its frozen policy."""
    spec = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(spec, dict) or set(spec) != {"number", "reason", "schedule", "parameters"}:
        raise ValueError("candidate needs exactly number, reason, schedule and parameters")
    number = spec["number"]
    if isinstance(number, bool) or not isinstance(number, int) or not 31 <= number <= 80:
        raise ValueError("candidate number must be an integer from 31 to 80")
    if (
        not isinstance(spec["schedule"], str)
        or spec["schedule"] not in SCHEDULES
        or not isinstance(spec["reason"], str)
        or not spec["reason"].strip()
        or not isinstance(spec["parameters"], dict)
    ):
        raise ValueError("candidate needs a valid schedule, written reason and parameters")
    parameters = dict(spec["parameters"])
    for key in (
        "risky_ids",
        "defensive_ids",
        "momentum_lookbacks",
        "momentum_weights",
        "canary_ids",
        "canary_lookbacks",
        "canary_weights",
        "volatility_windows",
        "fixed_weights",
    ):
        if key in parameters:
            if not isinstance(parameters[key], list | tuple):
                raise ValueError(f"{key} must be a list or tuple")
            parameters[key] = tuple(parameters[key])
    from quant_backtester.strategies.SA15_gpt61_riskaware import SA15RiskAwareRotation

    strategy = SA15RiskAwareRotation(**parameters)
    if set(parameters) != set(strategy.parameters()):
        raise ValueError("every strategy parameter must be explicit in the candidate")
    if strategy.strategy_id != STRATEGY_NAME:
        raise ValueError("candidate strategy_id must identify the R4 study")
    names = (
        *strategy.risky_ids,
        *strategy.defensive_ids,
        *strategy.canary_ids,
        strategy.core_id,
        strategy.monetary_id,
    )
    if any(name not in UNIVERSE for name in names):
        raise ValueError("candidate instruments must belong to the fixed R4 universe")
    return spec, strategy


def reference_books() -> dict[str, BuyAndHold]:
    """Return five initially purchased books, with no subsequent rebalancing."""
    return {
        name: BuyAndHold(instruments=names, strategy_id=name)
        for name, names in REFERENCE_INSTRUMENTS.items()
    }


def source_finance_hashes(*, candidate: bool = False) -> dict[str, str]:
    """Hash financial dependencies without unfinished reporting or runner scripts.

    Buy-and-hold does not use candidate indicators. Reference caches therefore
    ignore new signal/policy files, while candidate caches include those bytes.
    The R4 driver defines local metrics and reference wiring, so its bytes are
    included for every book.
    """
    package = ROOT / "src/quant_backtester"
    paths = {
        ROOT / "scripts/SA15_run_gpt61_study.py",
        Path(__file__).resolve(),
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
        paths.add(package / "strategies/SA15_gpt61_riskaware.py")
    return {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(paths)
        if path.is_file()
    }


def canonical_sha256(value: object) -> str:
    """Hash a JSON-compatible research object independent of formatting."""
    payload = json.dumps(plain_configuration(value), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def freeze_driver(output: Path, *, create: bool = False) -> str:
    """Freeze all financial source bytes before candidate31; refuse later edits."""
    current = source_finance_hashes(candidate=True)
    path = output / "driver_frozen.json"
    if not path.is_file():
        if not create:
            raise FileNotFoundError("the R4 driver must be frozen before candidate31")
        write_json(path, {"source_finance_hashes": current, "sha256": canonical_sha256(current)})
    saved = json.loads(path.read_text(encoding="utf-8"))
    if saved != {"source_finance_hashes": current, "sha256": canonical_sha256(current)}:
        raise ValueError("financial code differs from the driver frozen before candidate31")
    return saved["sha256"]


def write_frozen_selection(output: Path, selected: Mapping[str, Any]) -> None:
    """Write an irreversible selection record and its independent integrity digest."""
    path = output / "selected.json"
    if path.exists() or (output / "selected.sha256").exists():
        raise FileExistsError("final selection already exists")
    write_json(path, selected)
    (output / "selected.sha256").write_text(
        hashlib.sha256(path.read_bytes()).hexdigest() + "\n", encoding="utf-8"
    )


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
            "format": 4,
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
    if not details:
        raise ValueError("R4 requires complete trading evidence for every book")
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
    artifacts = BASE_ARTIFACTS
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


def save_run(folder: Path, result: StrategyResult, *, details: bool = True) -> dict[str, Any]:
    """Save the official result plus both curves and actual intervention dates."""
    values = base_save_run(folder, result, details=details)
    fills = result.fills()
    years = max((result.end - result.start).days / 365.25, 1 / 252)
    trade_days = int(fills["session_date"].nunique()) if not fills.empty else 0
    decision_days = sum(record.decision is not None for record in result.records())
    values.update(
        trade_days=trade_days,
        trade_days_per_year=trade_days / years,
        decision_days=decision_days,
        decision_days_per_year=decision_days / years,
    )
    write_json(folder / "metrics.json", values)
    result.equity(Book.GROSS).rename("gross_equity").to_csv(
        folder / "gross_equity.csv", index_label="session_date"
    )
    return values


def period_metrics(folder: Path, start: str, end: str) -> dict[str, Any]:
    """Describe a slice of one continuous book, preserving its opening position.

    The preceding close is retained as the return anchor when available. No
    order is simulated, and cash or shares are never reset at a slice boundary.
    All calculations use the existing analytics annualisation conventions.
    """
    lower, upper = date.fromisoformat(start), date.fromisoformat(end)
    curves = []
    for filename in ("equity.csv", "gross_equity.csv"):
        frame = pd.read_csv(folder / filename)
        dates = pd.Index([date.fromisoformat(value) for value in frame["session_date"]])
        equity = pd.Series(frame.iloc[:, 1].to_numpy(dtype=float), index=dates)
        before = equity[equity.index < lower]
        selected = equity[(equity.index >= lower) & (equity.index <= upper)]
        if selected.empty:
            raise ValueError("continuous slice has no observations")
        if not before.empty:
            selected = pd.concat([before.iloc[-1:], selected])
        curves.append(selected)
    net, gross = [PerformanceStats.from_equity(curve, ANALYTICS) for curve in curves]
    fills = pd.read_csv(folder / "fills.csv")
    if not fills.empty:
        fills = fills[(fills["session_date"] >= start) & (fills["session_date"] <= end)]
    trade_days = int(fills["session_date"].nunique()) if not fills.empty else 0
    return {
        "net_return": net.total_return,
        "gross_return": gross.total_return,
        "cagr": net.annualised_return,
        "volatility": net.annualised_volatility,
        "sharpe": net.sharpe_ratio,
        "max_drawdown": net.drawdown.depth,
        "calmar": (
            net.annualised_return / abs(net.drawdown.depth)
            if net.drawdown.depth and net.annualised_return is not None
            else None
        ),
        "costs_eur": float(fills["total_cost"].sum()) if not fills.empty else 0.0,
        "fills": len(fills),
        "trade_days": trade_days,
        "trade_days_per_year": trade_days / max(net.years, 1 / 252),
        "sessions": net.sessions,
        "anchor": curves[0].index[0].isoformat(),
        "continuous_book": True,
    }


def run_references(
    runner: StrategyRunner, period: str, output: Path = OUTPUT
) -> dict[str, dict[str, Any]]:
    """Run the five reference books, which are never selection candidates."""
    if period not in PERIODS:
        raise ValueError(f"unknown period {period}")
    return {
        name: run_cached(
            runner,
            book,
            EverySession(),
            *PERIODS[period],
            output / "references" / period / name,
            details=True,
        )
        for name, book in reference_books().items()
    }


def selection_score(
    choice: Mapping[str, Any],
    validation: Mapping[str, Any],
    choice_reference: Mapping[str, Any],
    validation_reference: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply the preregistered net Nasdaq, drawdown and intervention preference.

    Choice spans June 2019 to December 2024 continuously. Validation is the
    2023-2024 slice of that same portfolio, with the preceding close as anchor.
    Qualification demands positive excess CAGR, at most 25% historical maximum
    drawdown and at most four actual transaction dates per calendar year.
    """
    raw = (
        choice["cagr"],
        validation["cagr"],
        choice_reference["cagr"],
        validation_reference["cagr"],
        choice["max_drawdown"],
        choice_reference["max_drawdown"],
        choice["trade_days_per_year"],
    )
    if any(isinstance(value, bool) or not isinstance(value, int | float) for value in raw):
        raise ValueError("selection requires finite numeric CAGR, drawdown and trade frequency")
    values = [float(value) for value in raw]
    if not all(math.isfinite(value) for value in values):
        raise ValueError("selection requires finite CAGR, drawdown and trade frequency")
    cagr, validation_cagr, reference, validation_ref, dd, reference_dd, trades = values
    if dd > 0 or reference_dd > 0 or trades < 0:
        raise ValueError("drawdowns must be nonpositive and transaction frequency nonnegative")
    excess, validation_excess = cagr - reference, validation_cagr - validation_ref
    depth, reference_depth = abs(dd), abs(reference_dd)
    return {
        "excess_choice": excess,
        "excess_validation": validation_excess,
        "drawdown_depth": depth,
        "trade_days_per_year": trades,
        "qualified": excess > 0.0 and depth <= 0.25 and trades <= 4.0,
        "score": (
            excess
            + 0.20 * (reference_depth - depth)
            - 0.50 * max(0.0, depth - 0.25)
            - 0.001 * max(0.0, trades - 4.0)
            - 0.25 * max(0.0, -validation_excess)
        ),
    }


def update_trials(output: Path) -> pd.DataFrame:
    """Publish every completed numbered candidate, retaining failed designs."""
    rows = []
    for number in range(31, 81):
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
                    "qualified",
                    "excess_choice",
                    "excess_validation",
                    "drawdown_depth",
                    "trade_days_per_year",
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


def choice_evidence(folder: Path) -> dict[str, dict[str, Any]]:
    """Read choice metrics and derive disjoint diagnostics from the same book."""
    return {
        "choice": json.loads((folder / "metrics.json").read_text()),
        **{
            period: period_metrics(folder, *PERIODS[period])
            for period in ("development", "validation")
        },
    }


def iterate(config: Path, runner: StrategyRunner, output: Path = OUTPUT) -> None:
    """Execute one announced design, preserving state throughout 2019-2024."""
    if (output / "selected.json").exists():
        raise ValueError("selection is already frozen; no further candidates")
    spec, strategy = read_spec(config)
    number = spec["number"]
    folder = output / f"trial_{number:02d}"
    used = [
        item for item in range(31, 81) if (output / f"trial_{item:02d}/candidate.json").exists()
    ]
    complete = [item for item in used if (output / f"trial_{item:02d}/selection.json").exists()]
    if used != list(range(31, 31 + len(used))) or complete != list(range(31, number)):
        raise ValueError("candidate numbers must progress from 31 through 80")
    if number not in (31 + len(used), used[-1] if used else 31):
        raise ValueError("complete the existing candidate before starting another")
    if folder.exists() and any(folder.iterdir()):
        archived = folder / "candidate.json"
        if not archived.is_file() or json.loads(archived.read_text()) != spec:
            raise FileExistsError(f"{folder} will not be overwritten")
        if (folder / "selection.json").exists():
            raise FileExistsError(f"{folder} is already complete")
    for previous in used:
        if previous == number:
            continue
        previous_spec, previous_strategy = read_spec(
            output / f"trial_{previous:02d}/candidate.json"
        )
        if previous_strategy.fingerprint() == strategy.fingerprint() and (
            previous_spec["schedule"] == spec["schedule"]
        ):
            raise ValueError("a candidate with identical policy and schedule already exists")
    freeze_driver(output, create=number == 31)
    if not (folder / "candidate.json").exists():
        write_json(folder / "candidate.json", spec)
    run_references(runner, "choice", output)
    run_cached(
        runner,
        strategy,
        SCHEDULES[spec["schedule"]](),
        *PERIODS["choice"],
        folder / "choice",
        candidate=True,
    )
    rows = choice_evidence(folder / "choice")
    references = choice_evidence(output / "references/choice/Nasdaq_buy_hold")
    selection = selection_score(
        rows["choice"], rows["validation"], references["choice"], references["validation"]
    )
    write_json(
        folder / "selection.json",
        {
            **selection,
            "fingerprint": strategy.fingerprint(),
            "metrics": rows,
            "references": references,
            "candidate_sha256": hashlib.sha256(
                (folder / "candidate.json").read_bytes()
            ).hexdigest(),
            "driver_sha256": freeze_driver(output),
        },
    )
    update_trials(output)
    print(json.dumps({"trial": number, **selection}), flush=True)


def iterate_many(configs: Sequence[Path], runner: StrategyRunner, output: Path = OUTPUT) -> None:
    """Archive one ten-design batch before running it with a shared readonly reader."""
    if len(configs) != 10:
        raise ValueError("an adaptive batch must contain exactly ten candidates")
    specs = [read_spec(path)[0] for path in configs]
    numbers = [spec["number"] for spec in specs]
    first = numbers[0]
    if first not in (31, 41, 51, 61, 71) or numbers != list(range(first, first + 10)):
        raise ValueError("batch numbers must be one of the five announced consecutive tens")
    if (output / "selected.json").exists():
        raise ValueError("selection is already frozen; no further batches")
    if any(
        not (output / f"trial_{number:02d}/selection.json").exists() for number in range(31, first)
    ):
        raise ValueError("previous batch must finish before the next is archived")
    freeze_driver(output, create=first == 31)
    manifest = output / "batches" / f"batch_{(first - 31) // 10 + 1:02d}.json"
    evidence = {"numbers": numbers, "candidates": specs, "driver_sha256": freeze_driver(output)}
    if manifest.exists():
        if json.loads(manifest.read_text()) != evidence:
            raise ValueError("an archived batch cannot be changed")
    else:
        write_json(manifest, evidence)
    for path, spec in zip(configs, specs, strict=True):
        folder = output / f"trial_{spec['number']:02d}"
        if (folder / "selection.json").exists():
            if json.loads((folder / "candidate.json").read_text()) != spec:
                raise ValueError("completed batch candidate differs")
            continue
        iterate(path, runner, output)


def frozen_winner(output: Path) -> tuple[dict[str, Any], Strategy]:
    """Read the frozen winner and reject changed selection, policy or evidence."""
    selected_path = output / "selected.json"
    digest_path = output / "selected.sha256"
    if not selected_path.is_file():
        raise FileNotFoundError("diagnostics require a frozen selected.json")
    if (
        not digest_path.is_file()
        or digest_path.read_text().strip() != hashlib.sha256(selected_path.read_bytes()).hexdigest()
    ):
        raise ValueError("frozen selection integrity differs")
    selected = json.loads(selected_path.read_text())
    if selected["driver_sha256"] != freeze_driver(output):
        raise ValueError("frozen driver identity differs")
    number = selected["candidate"]["number"]
    folder = output / f"trial_{number:02d}"
    spec, strategy = read_spec(folder / "candidate.json")
    if spec != selected["candidate"] or strategy.fingerprint() != selected["fingerprint"]:
        raise ValueError("frozen winner differs from its archived candidate")
    if plain_configuration(strategy.definition())["parameters"] != selected["parameters"]:
        raise ValueError("frozen winner parameters differ")
    for name in ("candidate", "selection"):
        if (
            hashlib.sha256((folder / f"{name}.json").read_bytes()).hexdigest()
            != selected[f"{name}_sha256"]
        ):
            raise ValueError(f"frozen {name} evidence differs")
    return spec, strategy


def verified_trials(runner: StrategyRunner, output: Path) -> pd.DataFrame:
    """Recompute all fifty scores from checked continuous Nasdaq-relative evidence."""
    freeze_driver(output)
    expected_numbers = set(range(31, 81))
    actual = {
        int(path.name.removeprefix("trial_"))
        for path in output.glob("trial_*")
        if path.is_dir() and path.name.removeprefix("trial_").isdigit()
    }
    if actual != expected_numbers or any(
        not (output / f"trial_{number:02d}/selection.json").is_file() for number in expected_numbers
    ):
        raise ValueError("all fifty candidates31 through80 must complete before final selection")
    book = reference_books()["Nasdaq_buy_hold"]
    expected = expected_signature(runner, book, EverySession(), *PERIODS["choice"])
    reference_folder = output / "references/choice/Nasdaq_buy_hold"
    if cached_metrics(reference_folder, expected) is None:
        raise ValueError("selection requires verified Nasdaq reference results")
    references = choice_evidence(reference_folder)
    rows = []
    for number in range(31, 81):
        folder = output / f"trial_{number:02d}"
        spec, strategy = read_spec(folder / "candidate.json")
        if spec["number"] != number:
            raise ValueError("folder and archived candidate number differ")
        saved = json.loads((folder / "selection.json").read_text())
        if saved.get("fingerprint") != strategy.fingerprint():
            raise ValueError("saved selection policy fingerprint differs")
        if saved.get("candidate_sha256") != hashlib.sha256(
            (folder / "candidate.json").read_bytes()
        ).hexdigest() or saved.get("driver_sha256") != freeze_driver(output):
            raise ValueError("saved selection candidate or driver evidence differs")
        expected = expected_signature(
            runner, strategy, SCHEDULES[spec["schedule"]](), *PERIODS["choice"], candidate=True
        )
        if cached_metrics(folder / "choice", expected) is None:
            raise ValueError("completed candidate has no verified continuous result")
        values = choice_evidence(folder / "choice")
        score = selection_score(
            values["choice"], values["validation"], references["choice"], references["validation"]
        )
        if saved.get("metrics") != values or saved.get("references") != references:
            raise ValueError("saved selection metrics or Nasdaq reference evidence differs")
        for key, value in score.items():
            if isinstance(value, bool):
                matches = saved.get(key) is value
            else:
                matches = isinstance(saved.get(key), int | float) and math.isclose(
                    saved[key], value, rel_tol=0.0, abs_tol=1e-14
                )
            if not matches:
                raise ValueError("saved selection score differs from verified Nasdaq evidence")
        rows.append({"trial": number, **score})
    return pd.DataFrame(rows)


def finalise(runner: StrategyRunner, output: Path = OUTPUT, store: Path = STORE) -> None:
    """Freeze after all fifty designs, before any final-period reference or policy run."""
    if (output / "selected.json").exists():
        raise FileExistsError("final selection already exists")
    trials = verified_trials(runner, output)
    ranked = trials.sort_values(["qualified", "score", "trial"], ascending=[False, False, True])
    chosen = ranked.iloc[0]
    number = int(chosen["trial"])
    folder = output / f"trial_{number:02d}"
    spec, strategy = read_spec(folder / "candidate.json")
    write_frozen_selection(
        output,
        {
            "candidate": spec,
            "score": float(chosen["score"]),
            "fingerprint": strategy.fingerprint(),
            "parameters": plain_configuration(strategy.definition())["parameters"],
            "qualified": bool(chosen["qualified"]),
            "selection_uses": ["choice_continuous_2019_2024", "validation_slice_same_book"],
            "benchmark": "Nasdaq_buy_hold",
            "total_trials": 80,
            "round_trials": 50,
            "final_period": PERIODS["final"],
            "driver_sha256": freeze_driver(output),
            "candidate_sha256": hashlib.sha256(
                (folder / "candidate.json").read_bytes()
            ).hexdigest(),
            "selection_sha256": hashlib.sha256(
                (folder / "selection.json").read_bytes()
            ).hexdigest(),
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
    """Build fifty cost, twenty-four matched cash-start and seven full-history jobs."""
    spec, _ = frozen_winner(output)
    winner = output / f"trial_{spec['number']:02d}/candidate.json"
    jobs = []
    for number in range(31, 81):
        folder = output / f"trial_{number:02d}"
        if not (folder / "selection.json").is_file():
            raise ValueError("cost diagnostics require all fifty completed candidates")
        saved, _ = read_spec(folder / "candidate.json")
        if saved["number"] != number:
            raise ValueError("folder and archived candidate number differ")
        jobs.append(
            DiagnosticJob(
                store,
                folder / "costs_x2/choice",
                *PERIODS["choice"],
                "costs_x2",
                "choice",
                STRATEGY_NAME,
                folder / "candidate.json",
                2.0,
            )
        )
    for start in START_DATES:
        for name in (STRATEGY_NAME, *REFERENCE_INSTRUMENTS):
            jobs.append(
                DiagnosticJob(
                    store,
                    output / "robustness/starts" / start / name,
                    start,
                    "2024-12-31",
                    "starts",
                    start,
                    name,
                    winner if name == STRATEGY_NAME else None,
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
    jobs.append(
        DiagnosticJob(
            store,
            output / "full/costs_x2",
            *PERIODS["full"],
            "full",
            "full",
            STRATEGY_NAME,
            winner,
            2.0,
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
        details=True,
    )
    return {
        "diagnostic": job.diagnostic,
        "period": job.period,
        "book": job.book,
        "trial": None if spec is None else spec["number"],
        "start": job.start,
        "end": job.end,
        "cost_multiplier": job.multiplier,
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
    mode.add_argument(
        "--candidates", type=Path, nargs="+", help="one preannounced ten-design batch"
    )
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
        run_references(runner, "choice", options.output)
    elif options.candidates:
        iterate_many(options.candidates, runner, options.output)
    elif options.final:
        finalise(runner, options.output, options.store)
    else:
        iterate(options.candidate, runner, options.output)


if __name__ == "__main__":
    main()
