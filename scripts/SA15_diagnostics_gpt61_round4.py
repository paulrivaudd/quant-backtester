"""Freeze descriptive R4 risk/activity companions before any new final-period read.

The fifty numbered strategies and the winner remain defined by the immutable R4
runner. This tool independently describes two qualified extrema; it creates no
new design and cannot alter or replace the selected winner. Each existing policy
is replayed under the official engine, dates and costs. Importing runs nothing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import SA15_run_gpt61_round4 as study

from quant_backtester.backtest.runner import StrategyRunner

CRITERIA = {
    "eligible": "qualified candidates only, from the same fifty verified choice runs",
    "minimum_interventions": [
        "trade_days_per_year ascending",
        "score descending",
        "trial ascending",
    ],
    "minimum_drawdown": ["drawdown_depth ascending", "score descending", "trial ascending"],
    "deduplication": (
        "choose extrema independently; remove winner and duplicates; never force another"
    ),
    "role": "descriptive only; neither companion can replace the main winner",
}
MANIFEST = "companions_frozen.json"
CHECKSUM = "companions_frozen.sha256"


def diagnostics_source_sha256() -> str:
    """Hash this separate, frozen diagnostic implementation."""
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def rank_companions(trials: pd.DataFrame) -> dict[str, Any]:
    """Select qualified extrema independently, then remove winner and duplicates.

    This pure function reads only verified 2019-2024 choice scores. It never sees
    final or full results, and a missing qualified set produces no companions.
    """
    columns = {"trial", "qualified", "score", "trade_days_per_year", "drawdown_depth"}
    if not columns <= set(trials.columns) or trials.empty:
        raise ValueError("companion ranking needs completed trial scores")
    if trials["trial"].duplicated().any():
        raise ValueError("trial numbers must be unique")
    for row in trials.to_dict("records"):
        number = row["trial"]
        if isinstance(number, bool) or not isinstance(number, int) or not 31 <= number <= 80:
            raise ValueError("trial numbers must belong to the fifty announced designs")
        if not isinstance(row["qualified"], bool):
            raise ValueError("qualification must be a boolean")
        for name in ("score", "trade_days_per_year", "drawdown_depth"):
            value = row[name]
            if (
                isinstance(value, bool)
                or not isinstance(value, int | float)
                or not math.isfinite(value)
            ):
                raise ValueError("companion preferences need finite numeric scores")
        if row["trade_days_per_year"] < 0 or not 0 <= row["drawdown_depth"] <= 1:
            raise ValueError("companion risk and activity must be nonnegative fractions")
    winner = int(
        trials.sort_values(["qualified", "score", "trial"], ascending=[False, False, True]).iloc[0][
            "trial"
        ]
    )
    qualified = trials.loc[trials["qualified"]]
    extrema: dict[str, int | None] = {}
    for criterion, column in (
        ("minimum_interventions", "trade_days_per_year"),
        ("minimum_drawdown", "drawdown_depth"),
    ):
        extrema[criterion] = (
            int(
                qualified.sort_values(
                    [column, "score", "trial"], ascending=[True, False, True]
                ).iloc[0]["trial"]
            )
            if not qualified.empty
            else None
        )
    companions = list(
        dict.fromkeys(
            number for number in extrema.values() if number is not None and number != winner
        )
    )
    return {
        "expected_winner": winner,
        "criterion_winners": extrema,
        "companions": companions,
        "qualified_count": len(qualified),
    }


def candidate_evidence(output: Path, number: int) -> dict[str, Any]:
    """Read a numbered policy and hash its already completed choice evidence."""
    folder = output / f"trial_{number:02d}"
    candidate, policy = study.read_spec(folder / "candidate.json")
    if candidate["number"] != number:
        raise ValueError("candidate folder and announced number differ")
    return {
        "number": number,
        "candidate": candidate,
        "fingerprint": policy.fingerprint(),
        "candidate_sha256": hashlib.sha256((folder / "candidate.json").read_bytes()).hexdigest(),
        "selection_sha256": hashlib.sha256((folder / "selection.json").read_bytes()).hexdigest(),
    }


def freeze_companions(runner: StrategyRunner, output: Path = study.OUTPUT) -> None:
    """Freeze descriptive extrema after all fifty designs and before the winner.

    Only existing verified choice results are read. No final-period function or
    policy replay is called. Existing companion or main selections are refused.
    """
    manifest, checksum = output / MANIFEST, output / CHECKSUM
    if manifest.exists() or checksum.exists():
        raise FileExistsError("companion description is already frozen")
    if (output / "selected.json").exists() or (output / "selected.sha256").exists():
        raise ValueError("companions must be frozen before the main final selection")
    trials = study.verified_trials(runner, output)
    if set(trials["trial"]) != set(range(31, 81)):
        raise ValueError("companions require all fifty completed designs")
    ranking = rank_companions(trials)
    companions = []
    for number in ranking["companions"]:
        companions.append(
            {
                **candidate_evidence(output, number),
                "criteria": [
                    name
                    for name, chosen in ranking["criterion_winners"].items()
                    if chosen == number
                ],
            }
        )
    record = {
        "format": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "role": "descriptive_only_no_winner_replacement",
        "criteria": CRITERIA,
        "ranking": ranking,
        "expected_winner": candidate_evidence(output, ranking["expected_winner"]),
        "companions": companions,
        "trial_scores": trials.to_dict("records"),
        "driver_sha256": study.freeze_driver(output),
        "source_finance_hashes": study.source_finance_hashes(candidate=True),
        "diagnostics_source_sha256": diagnostics_source_sha256(),
    }
    if (output / "selected.json").exists() or (output / "selected.sha256").exists():
        raise ValueError("main selection appeared before companion freeze completed")
    study.write_json(manifest, record)
    checksum.write_text(hashlib.sha256(manifest.read_bytes()).hexdigest() + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "frozen_companions": ranking["companions"],
                "expected_winner": ranking["expected_winner"],
            }
        ),
        flush=True,
    )


def frozen_companions(output: Path = study.OUTPUT) -> dict[str, Any]:
    """Reject changed tool, source, manifest, ranks or archived policy evidence."""
    manifest, checksum = output / MANIFEST, output / CHECKSUM
    if not manifest.is_file() or not checksum.is_file():
        raise FileNotFoundError("companion diagnostics need their pre-final frozen description")
    if checksum.read_text().strip() != hashlib.sha256(manifest.read_bytes()).hexdigest():
        raise ValueError("companion manifest integrity differs")
    saved = json.loads(manifest.read_text(encoding="utf-8"))
    if saved.get("format") != 1 or saved.get("role") != "descriptive_only_no_winner_replacement":
        raise ValueError("unsupported companion description")
    if saved.get("diagnostics_source_sha256") != diagnostics_source_sha256():
        raise ValueError("diagnostic tool source differs from its frozen version")
    if saved.get("driver_sha256") != study.freeze_driver(output) or (
        saved.get("source_finance_hashes") != study.source_finance_hashes(candidate=True)
    ):
        raise ValueError("companion financial source differs")
    ranking = rank_companions(pd.DataFrame(saved["trial_scores"]))
    if saved.get("ranking") != ranking or saved.get("criteria") != CRITERIA:
        raise ValueError("companion preferences differ from the frozen choice ranking")
    if saved.get("expected_winner") != candidate_evidence(output, ranking["expected_winner"]):
        raise ValueError("expected winner evidence differs")
    expected = []
    for number in ranking["companions"]:
        expected.append(
            {
                **candidate_evidence(output, number),
                "criteria": [
                    name
                    for name, chosen in ranking["criterion_winners"].items()
                    if chosen == number
                ],
            }
        )
    if saved.get("companions") != expected:
        raise ValueError("companion archived evidence differs")
    return saved


@dataclass(frozen=True, slots=True)
class CompanionJob:
    """One immutable full/final replay at ordinary or doubled execution costs."""

    number: int
    period: str
    multiplier: float
    folder: Path
    candidate: Path


def build_jobs(output: Path = study.OUTPUT) -> tuple[CompanionJob, ...]:
    """Require the same frozen main winner, then describe at most eight replays."""
    saved = frozen_companions(output)
    winner, policy = study.frozen_winner(output)
    expected = saved["expected_winner"]
    if winner["number"] != expected["number"] or policy.fingerprint() != expected["fingerprint"]:
        raise ValueError("main winner differs; descriptive companions cannot replace it")
    jobs = []
    for companion in saved["companions"]:
        number = companion["number"]
        for period in ("full", "final"):
            for multiplier in (1.0, 2.0):
                label = period if multiplier == 1 else f"{period}_costs_x2"
                jobs.append(
                    CompanionJob(
                        number,
                        period,
                        multiplier,
                        output / "companions" / f"trial_{number:02d}" / label,
                        output / f"trial_{number:02d}/candidate.json",
                    )
                )
    return tuple(jobs)


def run_companions(store: Path = study.STORE, output: Path = study.OUTPUT) -> None:
    """Replay existing descriptive policies and leave all selection files untouched."""
    jobs = build_jobs(output)
    runners = {
        multiplier: study.build_runner(store, multiplier)
        for multiplier in {job.multiplier for job in jobs}
    }
    rows = []
    for job in jobs:
        candidate, policy = study.read_spec(job.candidate)
        metrics = study.run_cached(
            runners[job.multiplier],
            policy,
            study.SCHEDULES[candidate["schedule"]](),
            *study.PERIODS[job.period],
            job.folder,
            candidate=True,
        )
        rows.append(
            {
                "trial": job.number,
                "period": job.period,
                "cost_multiplier": job.multiplier,
                **metrics,
            }
        )
    folder = output / "companions"
    folder.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(folder / "summary.csv", index=False)


def parse_arguments(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    """Choose exactly one phase before opening the shared market store."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, default=study.STORE)
    parser.add_argument("--output", type=Path, default=study.OUTPUT)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--freeze-companions", action="store_true")
    mode.add_argument("--run", action="store_true")
    return parser.parse_args(arguments)


def main(arguments: Sequence[str] | None = None) -> None:
    """Run only the authorized companion phase, without modifying the main winner."""
    options = parse_arguments(arguments)
    if options.freeze_companions:
        freeze_companions(study.build_runner(options.store), options.output)
    else:
        run_companions(options.store, options.output)


if __name__ == "__main__":
    main()
