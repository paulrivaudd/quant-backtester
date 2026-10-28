"""Replay one fixed quantitative mechanism and its matched block ablations.

The sole candidate combines MA200 with a 20 percent annual offensive volatility
cap. Controls are diagnostics, not a search for a winning allocation. All books
share two ETFs, cash, evening availability, monthly decisions and execution.
History is already explored; no period is out of sample. Importing runs nothing.
Hypothesis, source/data hashes and thirty contracts are archived before any run.
Existing output is refused; no data is downloaded, changed or imputed here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import SA15_run_gpt61_round4 as round4

from quant_backtester.backtest.runner import StrategyRunner
from quant_backtester.research.references import BuyAndHold
from quant_backtester.strategies.base import Strategy
from quant_backtester.strategies.SA15_gpt61_riskaware import SA15RiskAwareRotation

ROOT = round4.ROOT
STORE = round4.STORE
OUTPUT = ROOT / "results/SA15_GPT-6.1_mechanism_pilot"
HYPOTHESIS = ROOT / "research/SA15_GPT-6.1/mechanism_pilot/hypothesis.json"
UNIVERSE = ("ETF_NASDAQ", "ETF_MONETARY_EUR")
STRATEGY_ID = "SA15_GPT-6.1_mechanism_pilot"
PERIODS = {
    "choice": ("2019-06-03", "2024-12-31"),
    "control": ("2025-01-02", "2026-10-09"),
    "full": ("2019-06-03", "2026-10-09"),
}
BLOCKS = {
    "full": {"trend_ma200": True, "volatility_cap_20pct": True},
    "trend_only": {"trend_ma200": True, "volatility_cap_20pct": False},
    "volatility_only": {"trend_ma200": False, "volatility_cap_20pct": True},
    "neither": {"trend_ma200": False, "volatility_cap_20pct": False},
    "Nasdaq_buy_hold": {"trend_ma200": False, "volatility_cap_20pct": False},
}


def policies() -> dict[str, Strategy]:
    """Build one candidate and four fixed controls without fitting any parameter."""
    full = SA15RiskAwareRotation(
        core_id="ETF_NASDAQ",
        risky_ids=("ETF_NASDAQ",),
        defensive_ids=(),
        monetary_id="ETF_MONETARY_EUR",
        mode="ensemble",
        momentum_lookbacks=(200,),
        momentum_weights=(1.0,),
        trend_kind="moving_average",
        core_floor=0.0,
        top_k=1,
        allocation_mode="equal",
        fixed_weights=(),
        absolute_filter=True,
        core_preference=0.0,
        switch_buffer=0.0,
        rebalance_band=0.10,
        canary_ids=(),
        canary_lookbacks=(21, 63, 126),
        canary_weights=(1.0, 1.0, 1.0),
        canary_min_breadth=0.5,
        volatility_windows=(20, 60),
        volatility_floor=0.05,
        target_volatility=0.20,
        recovery_lookback=0,
        recovery_threshold=0.0,
        defensive_top_k=1,
        monetary_lookback=21,
        max_age_sessions=1,
        strategy_id=STRATEGY_ID,
    )
    return {
        "full": full,
        "trend_only": replace(full, target_volatility=0.0),
        "volatility_only": replace(full, mode="vol_control"),
        "neither": replace(full, mode="balanced", target_volatility=0.0),
        "Nasdaq_buy_hold": BuyAndHold(instruments=("ETF_NASDAQ",), strategy_id="Nasdaq_buy_hold"),
    }


@dataclass(frozen=True, slots=True)
class PilotJob:
    """One preannounced cash-start replay, identified before reading any result."""

    policy: str
    period: str
    start: str
    end: str
    cost_multiplier: float
    folder: Path


def build_jobs(output: Path) -> tuple[PilotJob, ...]:
    """Declare five policies, three matched periods and two real cost runs."""
    return tuple(
        PilotJob(
            policy,
            period,
            start,
            end,
            multiplier,
            output / period / f"costs_x{int(multiplier)}" / policy,
        )
        for period, (start, end) in PERIODS.items()
        for multiplier in (1.0, 2.0)
        for policy in BLOCKS
    )


def read_hypothesis(path: Path) -> dict[str, Any]:
    """Require a nonempty written hypothesis before constructing any runner."""
    if not path.is_file():
        raise FileNotFoundError("write the mechanism hypothesis before its first backtest")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not value:
        raise ValueError("the mechanism hypothesis must be a nonempty JSON object")
    return value


def financial_source_hashes() -> dict[str, str]:
    """Include unchanged R4 financial dependencies and this pilot's bytes."""
    hashes = round4.source_finance_hashes(candidate=True)
    path = Path(__file__).resolve()
    hashes[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return dict(sorted(hashes.items()))


def data_state(runner: StrategyRunner) -> dict[str, Any]:
    """Capture exact immutable reader state, including its per-file digests."""
    with runner.reader.pinned() as state:
        return {"digest": state.digest, "files": dict(state.files)}


def contract(
    runner: StrategyRunner, job: PilotJob, policy: Strategy, state: Mapping[str, Any]
) -> dict[str, Any]:
    """Record complete engine conditions and explicit policy for one replay."""
    return round4.plain_configuration(
        {
            "policy": job.policy,
            "role": "candidate" if job.policy == "full" else "matched_control",
            "blocks": BLOCKS[job.policy],
            "period": job.period,
            "start": job.start,
            "end": job.end,
            "cash_restart": True,
            "cost_multiplier": job.cost_multiplier,
            "universe": list(UNIVERSE),
            "schedule": round4.MonthlyFromStart().definition(),
            "strategy": policy.definition(),
            "parameters": asdict(policy),
            "fingerprint": policy.fingerprint(),
            "data_state": state,
            "execution": runner.execution.definition(),
            "initial_cash": runner.initial_cash,
            "base_currency": runner.base_currency,
            "reference_calendar": runner.reference_calendar_id,
            "timetable": runner.timetable.definition(),
            "analytics": runner.analytics.definition(),
            "portfolio_limits": runner.limits.definition(),
        }
    )


def verify_freeze(runner: StrategyRunner, frozen: Mapping[str, Any], hypothesis: Path) -> None:
    """Stop before writing a result if hypothesis, source or data changed."""
    if financial_source_hashes() != frozen["source_finance_hashes"]:
        raise ValueError("financial source differs from the pre-run mechanism freeze")
    if hashlib.sha256(hypothesis.read_bytes()).hexdigest() != frozen["hypothesis_sha256"]:
        raise ValueError("hypothesis differs from the pre-run mechanism freeze")
    if data_state(runner) != frozen["data_state"]:
        raise ValueError("data differs from the pre-run mechanism freeze")


def freeze_output(
    output: Path,
    store: Path,
    hypothesis: Path,
    written_hypothesis: Mapping[str, Any],
    runners: Mapping[float, StrategyRunner],
    books: Mapping[str, Strategy],
    jobs: Sequence[PilotJob],
) -> dict[str, Any]:
    """Archive all contracts and immutable inputs before the first engine call.

    Existing output, including an incomplete prior attempt, is refused. Failed
    attempts are retained for review; choosing a new output path is explicit.
    """
    state = data_state(runners[1.0])
    if data_state(runners[2.0]) != state:
        raise ValueError("cost runners do not share the same data state")
    frozen = round4.plain_configuration(
        {
            "format": 1,
            "created_at_utc": datetime.now(UTC).isoformat(),
            "study_kind": "one_fixed_candidate_with_matched_block_ablations",
            "candidate_count": 1,
            "control_count": 4,
            "real_backtest_count": len(jobs),
            "selection": "none; all declared policies and periods are reported",
            "historical_status": "retrospective_already_explored_not_out_of_sample",
            "hypothesis": written_hypothesis,
            "hypothesis_sha256": hashlib.sha256(hypothesis.read_bytes()).hexdigest(),
            "data_state": state,
            "source_finance_hashes": financial_source_hashes(),
            "contracts": [
                contract(runners[job.cost_multiplier], job, books[job.policy], state)
                for job in jobs
            ],
        }
    )
    output.mkdir(parents=True, exist_ok=False)
    round4.write_json(output / "manifest.json", frozen)
    (output / "manifest.sha256").write_text(
        hashlib.sha256((output / "manifest.json").read_bytes()).hexdigest() + "\n",
        encoding="utf-8",
    )
    (output / "hypothesis.json").write_bytes(hypothesis.read_bytes())
    round4.archive_sources(output, store)
    return frozen


def run_pilot(store: Path, output: Path, hypothesis: Path) -> None:
    """Run thirty declared diagnostics without selecting or changing a policy."""
    written_hypothesis = read_hypothesis(hypothesis)
    if output.exists():
        raise FileExistsError("mechanism output already exists; historical results are immutable")
    books = policies()
    jobs = build_jobs(output)
    runners = {multiplier: round4.build_runner(store, multiplier) for multiplier in (1.0, 2.0)}
    frozen = freeze_output(output, store, hypothesis, written_hypothesis, runners, books, jobs)
    rows = []
    for job, identity in zip(jobs, frozen["contracts"], strict=True):
        runner, book = runners[job.cost_multiplier], books[job.policy]
        verify_freeze(runner, frozen, hypothesis)
        print(f"run {job.period} x{job.cost_multiplier:g} {job.policy}", flush=True)
        result = runner.run(book, UNIVERSE, job.start, job.end, schedule=round4.MonthlyFromStart())
        verify_freeze(runner, frozen, hypothesis)
        if result.data_state.digest != frozen["data_state"]["digest"]:
            raise ValueError("result data identity differs from the pre-run mechanism freeze")
        if result.fingerprint != identity["fingerprint"]:
            raise ValueError("result policy differs from the pre-run mechanism freeze")
        if job.folder.exists():
            raise FileExistsError("refusing to overwrite a mechanism result")
        values = round4.save_run(job.folder, result, details=True)
        round4.write_json(job.folder / "contract.json", identity)
        artifacts = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(job.folder.iterdir())
            if path.is_file()
        }
        round4.write_json(job.folder / "artifacts.json", artifacts)
        rows.append(
            {
                "policy": job.policy,
                "period": job.period,
                "start": job.start,
                "end": job.end,
                "cost_multiplier": job.cost_multiplier,
                **values,
            }
        )
    verify_freeze(runners[1.0], frozen, hypothesis)
    pd.DataFrame(rows).to_csv(output / "metrics.csv", index=False)
    round4.write_json(
        output / "completed.json",
        {
            "real_backtest_count": len(rows),
            "candidate_count": 1,
            "control_count": 4,
            "manifest_sha256": hashlib.sha256((output / "manifest.json").read_bytes()).hexdigest(),
            "metrics_sha256": hashlib.sha256((output / "metrics.csv").read_bytes()).hexdigest(),
        },
    )


def main(arguments: Sequence[str] | None = None) -> None:
    """Execute only the explicitly requested, preannounced mechanism pilot."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", required=True)
    parser.add_argument("--store", type=Path, default=STORE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--hypothesis", type=Path, default=HYPOTHESIS)
    options = parser.parse_args(arguments)
    run_pilot(options.store, options.output, options.hypothesis)


if __name__ == "__main__":
    main()
