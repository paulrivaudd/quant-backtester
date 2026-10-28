"""Run fifty sequential quantitative designs with matched block ablations.

Only continuous 2019-2024 curves influence selection. Every control is an actual
cash-start replay at normal and doubled costs. Content-addressed immutable books
are reused only under identical financial sources, data and configuration.
Importing runs nothing. Historical controls remain retrospective diagnostics.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import SA15_run_gpt61_round4 as previous

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.backtest.runner import StrategyResult, StrategyRunner
from quant_backtester.backtest.schedule import DecisionSchedule, EverySession
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.research.references import BuyAndHold
from quant_backtester.signals.base import Signal
from quant_backtester.signals.engine import SignalRequest
from quant_backtester.strategies.base import Strategy

ROOT = previous.ROOT
STORE = previous.STORE
OUTPUT = ROOT / "results/SA15_GPT-6.1_R5"
RESEARCH = ROOT / "research/SA15_GPT-6.1/round5"
BASELINE = RESEARCH / "baseline.json"
HYPOTHESIS = RESEARCH / "hypothesis.json"
POLICY_PATH = ROOT / "src/quant_backtester/strategies/SA15_gpt61_mechanisms.py"
STRATEGY_ID = "SA15_GPT-6.1_R5"
UNIVERSE = ("ETF_NASDAQ", "ETF_MONETARY_EUR", "ETF_GOLD", "ETF_EURO_GOV")
PERIODS = {
    "choice": ("2019-06-03", "2024-12-31"),
    "development": ("2019-06-03", "2022-12-30"),
    "validation": ("2023-01-02", "2024-12-31"),
    "final": ("2025-01-02", "2026-10-09"),
    "full": ("2019-06-03", "2026-10-09"),
}
SCHEDULES = {
    "monthly": previous.MonthlyFromStart,
    "weekly": previous.WeeklyFromStart,
    "quarterly": previous.QuarterlyFromStart,
}
START_DATES = previous.START_DATES
ARTIFACTS = (*previous.BASE_ARTIFACTS, "attempt.json")
SPEC_KEYS = {
    "id",
    "parent",
    "reason",
    "changed_block",
    "expected_benefit",
    "expected_cost",
    "refutation",
    "schedule",
    "parameters",
}


def read_json(path: Path) -> dict[str, Any]:
    """Read a required JSON object without inventing missing evidence."""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def sha256(path: Path) -> str:
    """Digest exact archived bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_hash(value: object) -> str:
    """Hash canonical JSON-compatible configuration."""
    return previous.canonical_sha256(value)


def write_once(path: Path, value: object) -> None:
    """Write new evidence or require identical existing JSON evidence."""
    plain = previous.plain_configuration(value)
    if path.exists():
        if read_json(path) != plain:
            raise FileExistsError(f"refusing to overwrite evidence: {path}")
    else:
        previous.write_json(path, plain)


def design_number(identifier: object, *, baseline: bool = False) -> int:
    """Validate M01 through M50, optionally the fixed M00 parent."""
    if not isinstance(identifier, str) or not re.fullmatch(r"M\d{2}", identifier):
        raise ValueError("design id must be M01 through M50")
    number = int(identifier[1:])
    if not (0 if baseline else 1) <= number <= 50:
        raise ValueError("design id must be M01 through M50")
    return number


def make_policy(parameters: Mapping[str, Any]) -> Strategy:
    """Construct the policy lazily and refuse undeclared parameter defaults."""
    from quant_backtester.strategies.SA15_gpt61_mechanisms import SA15Mechanisms

    policy = SA15Mechanisms(**parameters)
    if set(parameters) != set(policy.parameters()):
        raise ValueError("every strategy parameter must be explicit")
    if policy.strategy_id != STRATEGY_ID:
        raise ValueError("strategy_id must identify the R5 study")
    if policy.core_id != "ETF_NASDAQ" or policy.monetary_id != "ETF_MONETARY_EUR":
        raise ValueError("R5 uses the fixed Nasdaq-led universe")
    return policy


def read_baseline(path: Path) -> tuple[dict[str, Any], Strategy]:
    """Read the explicit pilot parent before constructing M01."""
    spec = read_json(path)
    if set(spec) != {"id", "reason", "schedule", "parameters"} or spec["id"] != "M00":
        raise ValueError("baseline needs id M00, reason, schedule and full parameters")
    if (
        spec["schedule"] not in SCHEDULES
        or not isinstance(spec["reason"], str)
        or not spec["reason"].strip()
    ):
        raise ValueError("baseline requires declared cadence and reason")
    return spec, make_policy(spec["parameters"])


def read_spec(path: Path) -> tuple[dict[str, Any], Strategy]:
    """Require a complete one-mechanism hypothesis before any replay."""
    spec = read_json(path)
    if set(spec) != SPEC_KEYS:
        raise ValueError(f"candidate needs exactly {sorted(SPEC_KEYS)}")
    number = design_number(spec["id"])
    if design_number(spec["parent"], baseline=True) >= number:
        raise ValueError("parent must be M00 or an earlier design")
    for key in ("reason", "changed_block", "expected_benefit", "expected_cost", "refutation"):
        if not isinstance(spec[key], str) or not spec[key].strip():
            raise ValueError(f"candidate requires nonempty {key}")
    if (
        not isinstance(spec["schedule"], str)
        or spec["schedule"] not in SCHEDULES
        or not isinstance(spec["parameters"], dict)
    ):
        raise ValueError("candidate needs valid cadence and explicit parameters")
    return spec, make_policy(spec["parameters"])


def changed_groups(parent: Mapping[str, Any], child: Mapping[str, Any]) -> set[str]:
    """Identify a changed block and reject changes to fixed numeric parameters."""
    from quant_backtester.strategies.SA15_gpt61_mechanisms import BLOCK_PARAMETERS

    changed = {
        key for key in parent["parameters"] if parent["parameters"][key] != child["parameters"][key]
    }
    groups: set[str] = set()
    for key in changed:
        owners = [name for name, keys in BLOCK_PARAMETERS.items() if key in keys]
        if len(owners) != 1:
            raise ValueError(f"fixed or ambiguous parameter changed: {key}")
        groups.add(owners[0])
    if parent["schedule"] != child["schedule"]:
        groups.add("cadence")
    return groups


def validate_single_change(parent: Mapping[str, Any], child: Mapping[str, Any]) -> None:
    """Require exactly the preregistered mechanism change from its parent."""
    if set(parent["parameters"]) != set(child["parameters"]):
        raise ValueError("parent and candidate parameters must have identical keys")
    groups = changed_groups(parent, child)
    if groups != {child["changed_block"]}:
        raise ValueError(f"exactly the declared block must change, observed {sorted(groups)}")


def source_hashes() -> dict[str, str]:
    """Hash all financial dependencies, excluding narrative reporting changes."""
    hashes = previous.source_finance_hashes(candidate=True)
    for path in (Path(__file__).resolve(), POLICY_PATH):
        if not path.is_file():
            raise FileNotFoundError(f"financial source missing before freeze: {path}")
        hashes[path.relative_to(ROOT).as_posix()] = sha256(path)
    return dict(sorted(hashes.items()))


def data_state(runner: StrategyRunner) -> dict[str, Any]:
    """Record exact clean-data and metadata file fingerprints."""
    with runner.reader.pinned() as state:
        return {"digest": state.digest, "files": dict(state.files)}


def freeze_inputs(
    output: Path,
    store: Path,
    baseline: Path,
    hypothesis: Path,
    runners: Mapping[float, StrategyRunner],
    *,
    create: bool = False,
) -> dict[str, Any]:
    """Freeze source, data and hypothesis before M01; verify every later phase."""
    state = data_state(runners[1.0])
    if data_state(runners[2.0]) != state:
        raise ValueError("normal and doubled cost runners have different data")
    evidence = previous.plain_configuration(
        {
            "format": 1,
            "design_count": 50,
            "previous_exploratory_designs": 80,
            "previous_mechanism_pilot_books": 5,
            "selection_trials_before_round5": 85,
            "historical_status": "retrospective_already_explored_not_out_of_sample",
            "source_finance_hashes": source_hashes(),
            "data_state": state,
            "hypothesis": read_json(hypothesis),
            "hypothesis_sha256": sha256(hypothesis),
            "baseline": read_baseline(baseline)[0],
            "baseline_sha256": sha256(baseline),
            "universe": list(UNIVERSE),
            "periods": PERIODS,
            "selection_rule": (
                "R4 fixed score; candidate designs only; qualified then score then identifier"
            ),
            "cost_multipliers": [1.0, 2.0],
        }
    )
    path = output / "frozen_inputs.json"
    if not path.exists() and not create:
        raise FileNotFoundError("freeze inputs through M01 before diagnostics")
    if not path.exists():
        write_once(path, evidence)
        previous.archive_sources(output, store)
    elif read_json(path) != evidence:
        raise ValueError("source, data, baseline or hypothesis differs from M01 freeze")
    return evidence


@dataclass(slots=True)
class AuditPolicy(Strategy):
    """Passively record the pure plan without changing identity or decisions."""

    policy: Strategy = field(repr=False)
    rows: list[dict[str, Any]] = field(default_factory=list, repr=False)

    @property
    def strategy_id(self) -> str:
        """Keep the underlying policy name."""
        return self.policy.strategy_id

    def required_signals(self) -> Sequence[Signal | SignalRequest]:
        """Request the underlying policy's identical signals."""
        return self.policy.required_signals()

    def parameters(self) -> Mapping[str, object]:
        """Return unchanged underlying parameters."""
        return self.policy.parameters()

    def definition(self) -> Mapping[str, object]:
        """Keep the exact definition and fingerprint."""
        return self.policy.definition()

    def decide(self, ctx: StrategyContext) -> TargetAllocation:
        """Record available information, then delegate the financial decision."""
        values = previous.plain_configuration(self.policy.plan(ctx).audit_dict())
        values["decision_time"] = ctx.as_of.isoformat()
        self.rows.append(values)
        return self.policy.decide(ctx)


def signature(
    runner: StrategyRunner,
    policy: Strategy,
    schedule: DecisionSchedule,
    start: str,
    end: str,
    frozen: Mapping[str, Any],
) -> dict[str, Any]:
    """Describe complete executable cash-start conditions for cache identity."""
    return previous.plain_configuration(
        {
            "format": 5,
            "data_state": frozen["data_state"]["digest"],
            "source_finance_hashes": frozen["source_finance_hashes"],
            "fingerprint": policy.fingerprint(),
            "strategy": policy.definition(),
            "configuration": {
                "requested_start": start,
                "requested_end": end,
                "data_state": frozen["data_state"]["digest"],
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


def validate_cache(folder: Path, expected: Mapping[str, Any]) -> dict[str, Any] | None:
    """Require matching inputs, provenance and all saved artifact checksums."""
    return previous.cached_metrics(folder, expected)


def _utc_audit_key(value: object) -> str:
    """Compare aware timestamps by instant rather than offset spelling."""
    instant = pd.Timestamp(value)
    if instant.tzinfo is None:
        raise ValueError("passive audit timestamps must be timezone-aware")
    return instant.tz_convert("UTC").isoformat()


def save_evidence(
    folder: Path, result: StrategyResult, observer: AuditPolicy | None
) -> dict[str, Any]:
    """Save official records plus passive mechanism diagnostics by timestamp."""
    values = previous.save_run(folder, result, details=True)
    if observer is not None:
        decisions = pd.read_csv(folder / "decisions.csv")
        if len(decisions) != len(observer.rows):
            raise ValueError("passive audit and official decision counts differ")
        audit = {_utc_audit_key(row["decision_time"]): row for row in observer.rows}
        extra: list[dict[str, Any]] = []
        for _, row in decisions.iterrows():
            key = _utc_audit_key(row["decision_time"])
            if key not in audit:
                raise ValueError("passive audit timestamps differ from official decisions")
            additions = {}
            for name, value in audit[key].items():
                if name == "decision_time":
                    continue
                if name in {"weights", "skipped"}:
                    name = f"plan_{name}"
                additions[name] = (
                    json.dumps(value, sort_keys=True) if isinstance(value, dict | list) else value
                )
            extra.append(additions)
        decisions = pd.concat([decisions.reset_index(drop=True), pd.DataFrame(extra)], axis=1)
        decisions.to_csv(folder / "decisions.csv", index=False)
    return values


def run_cached(
    runner: StrategyRunner,
    policy: Strategy,
    schedule: DecisionSchedule,
    start: str,
    end: str,
    output: Path,
    role_folder: Path,
    frozen: Mapping[str, Any],
) -> tuple[dict[str, Any], str, bool]:
    """Replay a new book or validate an identical immutable cached simulation."""
    expected = signature(runner, policy, schedule, start, end, frozen)
    key = canonical_hash(expected)
    folder = output / "cache" / key
    values = validate_cache(folder, expected)
    physical = values is None
    if physical:
        if folder.exists() and any(folder.iterdir()):
            raise ValueError(f"incomplete cache cannot be overwritten: {folder}")
        write_once(folder / "attempt.json", {"cache_key": key, "signature": expected})
        observer = AuditPolicy(policy) if hasattr(policy, "plan") else None
        result = runner.run(
            observer if observer is not None else policy, UNIVERSE, start, end, schedule=schedule
        )
        if (
            result.data_state.digest != expected["data_state"]
            or result.fingerprint != expected["fingerprint"]
        ):
            raise ValueError("completed result differs from frozen inputs")
        values = save_evidence(folder, result, observer)
        write_once(
            folder / "cache.json",
            {
                "signature": expected,
                "artifacts": {name: sha256(folder / name) for name in ARTIFACTS},
            },
        )
    validate_cache(folder, expected)
    role_folder.mkdir(parents=True, exist_ok=True)
    for name in (*ARTIFACTS, "cache.json"):
        destination = role_folder / name
        if destination.exists():
            if sha256(destination) != sha256(folder / name):
                raise ValueError(f"role evidence differs from immutable cache: {destination}")
        else:
            shutil.copyfile(folder / name, destination)
    write_once(
        role_folder / "cache_link.json",
        {"cache_key": key, "cache": str(folder.relative_to(output))},
    )
    assert values is not None
    return values, key, physical


def require_analysis(output: Path, identifier: str) -> dict[str, Any]:
    """Require a written mechanism diagnosis tied to exact completed evidence."""
    folder = output / identifier
    path = folder / "analysis.json"
    if not path.is_file():
        raise ValueError(f"analyze {identifier} before starting the next design")
    analysis = read_json(path)
    if analysis.get("id") != identifier or analysis.get("completed_sha256") != sha256(
        folder / "completed.json"
    ):
        raise ValueError(f"analysis is not bound to completed evidence: {identifier}")
    for name in ("decision", "findings", "next_defect"):
        value = analysis.get(name)
        if not isinstance(value, str | list) or not value:
            raise ValueError(f"analysis needs nonempty {name}: {identifier}")
    return {"id": identifier, "sha256": sha256(path)}


def verify_completed(output: Path, identifier: str, *, deep: bool = False) -> dict[str, Any]:
    """Verify archived hypotheses and the analysis chain before any later use."""
    folder = output / identifier
    spec, _ = read_spec(folder / "candidate.json")
    contract = read_json(folder / "contract.json")
    completed = read_json(folder / "completed.json")
    if (
        contract["id"] != identifier
        or contract["candidate"] != spec
        or contract["candidate_sha256"] != sha256(folder / "candidate.json")
        or contract["frozen_inputs_sha256"] != sha256(output / "frozen_inputs.json")
        or completed["contract_sha256"] != sha256(folder / "contract.json")
    ):
        raise ValueError(f"archived experiment evidence differs: {identifier}")
    for analysis in contract["preceding_analyses"]:
        if require_analysis(output, analysis["id"]) != analysis:
            raise ValueError("a previously archived analysis was changed")
    if not deep:
        return completed
    frozen = read_json(output / "frozen_inputs.json")
    planned = {(job["role"], job["cost_multiplier"]): job for job in contract["contracts"]}
    actual = {(row["role"], row["cost_multiplier"]): row for row in completed["metrics"]}
    if set(planned) != set(actual) or len(actual) != completed["logical_contract_count"]:
        raise ValueError("completed comparison contracts differ")
    for identity, job in planned.items():
        role, cost = identity
        role_folder = folder / "choice" / f"costs_x{int(cost)}" / role
        cached = read_json(role_folder / "cache.json")
        expected = cached["signature"]
        if (
            canonical_hash(expected) != job["cache_key"]
            or actual[identity]["cache_key"] != job["cache_key"]
            or expected["source_finance_hashes"] != frozen["source_finance_hashes"]
            or expected["data_state"] != frozen["data_state"]["digest"]
        ):
            raise ValueError("completed replay input identity differs")
        metrics = validate_cache(role_folder, expected)
        original = validate_cache(output / "cache" / job["cache_key"], expected)
        if metrics != original or metrics is None:
            raise ValueError("role evidence differs from the physical replay")
        if any(actual[identity].get(key) != value for key, value in metrics.items()):
            raise ValueError("completed metrics differ from the physical replay")
    candidate_folder = folder / "choice/costs_x1/candidate"
    reference_folder = folder / "choice/costs_x1/Nasdaq_buy_hold"
    score = previous.selection_score(
        read_json(candidate_folder / "metrics.json"),
        previous.period_metrics(candidate_folder, *PERIODS["validation"]),
        read_json(reference_folder / "metrics.json"),
        previous.period_metrics(reference_folder, *PERIODS["validation"]),
    )
    if score != completed["score"]:
        raise ValueError("selection score differs from actual completed replays")
    return completed


def parent_spec(
    output: Path, spec: Mapping[str, Any], baseline: Mapping[str, Any]
) -> dict[str, Any]:
    """Read the archived parent rather than a mutable working configuration."""
    return (
        dict(baseline)
        if spec["parent"] == "M00"
        else read_spec(output / spec["parent"] / "candidate.json")[0]
    )


def comparison_books(
    spec: Mapping[str, Any], policy: Strategy, parent: Mapping[str, Any]
) -> dict[str, tuple[Strategy, DecisionSchedule]]:
    """Build candidate, frozen parent, benchmark and all active-block removals."""
    schedule = SCHEDULES[spec["schedule"]]()
    books = {
        "candidate": (policy, schedule),
        "parent": (make_policy(parent["parameters"]), SCHEDULES[parent["schedule"]]()),
        "Nasdaq_buy_hold": (
            BuyAndHold(instruments=("ETF_NASDAQ",), strategy_id="Nasdaq_buy_hold"),
            EverySession(),
        ),
    }
    for block in policy.active_blocks():
        books[f"without_{block}"] = (policy.without_block(block), schedule)
    return books


def iterate(path: Path, store: Path, output: Path, baseline_path: Path, hypothesis: Path) -> None:
    """Run one design and stop before its explicit mechanism diagnosis."""
    if (output / "selected.json").exists():
        raise ValueError("selection is frozen; no further candidates")
    spec, policy = read_spec(path)
    number = design_number(spec["id"])
    folder = output / spec["id"]
    if (folder / "completed.json").exists():
        raise FileExistsError("candidate is complete; refusing overwrite")
    analyses = []
    for earlier in range(1, number):
        identifier = f"M{earlier:02d}"
        if not (output / identifier / "completed.json").is_file():
            raise ValueError("designs must complete sequentially from M01 through M50")
        analyses.append(require_analysis(output, identifier))
        verify_completed(output, identifier)
    if any(
        (output / f"M{later:02d}" / "candidate.json").exists() for later in range(number + 1, 51)
    ):
        raise ValueError("a later design has already been archived")
    runners = {cost: previous.build_runner(store, cost) for cost in (1.0, 2.0)}
    frozen = freeze_inputs(output, store, baseline_path, hypothesis, runners, create=number == 1)
    parent = parent_spec(output, spec, frozen["baseline"])
    validate_single_change(parent, spec)
    for earlier in range(1, number):
        saved, saved_policy = read_spec(output / f"M{earlier:02d}" / "candidate.json")
        if (
            policy.fingerprint() == saved_policy.fingerprint()
            and spec["schedule"] == saved["schedule"]
        ):
            raise ValueError("identical policy and cadence already exists")
    write_once(folder / "candidate.json", spec)
    books = comparison_books(spec, policy, parent)
    planned = [
        {
            "role": role,
            "cost_multiplier": cost,
            "cache_key": canonical_hash(
                signature(runners[cost], book, cadence, *PERIODS["choice"], frozen)
            ),
        }
        for cost in (1.0, 2.0)
        for role, (book, cadence) in books.items()
    ]
    write_once(
        folder / "contract.json",
        {
            "id": spec["id"],
            "candidate": spec,
            "parent": parent,
            "candidate_sha256": sha256(folder / "candidate.json"),
            "frozen_inputs_sha256": sha256(output / "frozen_inputs.json"),
            "preceding_analyses": analyses,
            "period": "choice",
            "start": PERIODS["choice"][0],
            "end": PERIODS["choice"][1],
            "contracts": planned,
            "ablation_blocks": list(policy.active_blocks()),
        },
    )
    rows = []
    new_physical = 0
    for cost in (1.0, 2.0):
        for role, (book, cadence) in books.items():
            print(f"{spec['id']} choice x{cost:g} {role}", flush=True)
            values, key, physical = run_cached(
                runners[cost],
                book,
                cadence,
                *PERIODS["choice"],
                output,
                folder / "choice" / f"costs_x{int(cost)}" / role,
                frozen,
            )
            new_physical += int(physical)
            rows.append({"role": role, "cost_multiplier": cost, "cache_key": key, **values})
    freeze_inputs(output, store, baseline_path, hypothesis, runners)
    candidate_folder = folder / "choice/costs_x1/candidate"
    reference_folder = folder / "choice/costs_x1/Nasdaq_buy_hold"
    score = previous.selection_score(
        read_json(candidate_folder / "metrics.json"),
        previous.period_metrics(candidate_folder, *PERIODS["validation"]),
        read_json(reference_folder / "metrics.json"),
        previous.period_metrics(reference_folder, *PERIODS["validation"]),
    )
    completion = {
        "id": spec["id"],
        "parent": spec["parent"],
        "changed_block": spec["changed_block"],
        "contract_sha256": sha256(folder / "contract.json"),
        "logical_contract_count": len(rows),
        "distinct_cache_contracts": len({row["cache_key"] for row in rows}),
        "new_physical_replays_this_invocation": new_physical,
        "score": score,
        "metrics": rows,
    }
    write_once(folder / "completed.json", completion)
    pd.DataFrame(rows).to_csv(folder / "comparisons.csv", index=False)
    print(
        json.dumps(
            {
                "id": spec["id"],
                "score": score,
                "logical_contract_count": len(rows),
                "new_physical_replays": new_physical,
                "comparisons": rows,
            },
            sort_keys=True,
        ),
        flush=True,
    )


def freeze_selection(store: Path, output: Path, baseline: Path, hypothesis: Path) -> None:
    """Freeze one candidate after all fifty analyses; never select an ablation."""
    if (output / "selected.json").exists():
        raise FileExistsError("selection is already frozen")
    runners = {cost: previous.build_runner(store, cost) for cost in (1.0, 2.0)}
    freeze_inputs(output, store, baseline, hypothesis, runners)
    candidates = []
    for number in range(1, 51):
        identifier = f"M{number:02d}"
        analysis = require_analysis(output, identifier)
        folder = output / identifier
        spec, policy = read_spec(folder / "candidate.json")
        completed = verify_completed(output, identifier, deep=True)
        if completed["contract_sha256"] != sha256(folder / "contract.json"):
            raise ValueError("completed contract integrity differs")
        if not math.isfinite(completed["score"]["score"]):
            raise ValueError("selection score must be finite")
        candidates.append(
            {
                "id": identifier,
                "candidate": spec,
                "fingerprint": policy.fingerprint(),
                "completed_sha256": sha256(folder / "completed.json"),
                "analysis": analysis,
                **completed["score"],
            }
        )
    candidates.sort(key=lambda item: (-int(item["qualified"]), -item["score"], item["id"]))
    selected = {
        **candidates[0],
        "frozen_inputs_sha256": sha256(output / "frozen_inputs.json"),
        "candidate_count": 50,
        "previous_exploratory_designs": 80,
        "previous_mechanism_pilot_books": 5,
        "selection_trials_before_round5": 85,
        "ranking": [
            {"id": item["id"], "qualified": item["qualified"], "score": item["score"]}
            for item in candidates
        ],
    }
    previous.write_frozen_selection(output, selected)
    print(
        json.dumps(
            {
                "selected": selected["id"],
                "qualified": selected["qualified"],
                "score": selected["score"],
            }
        ),
        flush=True,
    )


def frozen_winner(output: Path) -> tuple[dict[str, Any], Strategy]:
    """Verify the frozen candidate and its immutable evidence chain."""
    path = output / "selected.json"
    if not path.is_file() or (output / "selected.sha256").read_text().strip() != sha256(path):
        raise ValueError("selection is missing or its integrity differs")
    selected = read_json(path)
    folder = output / selected["id"]
    if selected["frozen_inputs_sha256"] != sha256(output / "frozen_inputs.json") or selected[
        "completed_sha256"
    ] != sha256(folder / "completed.json"):
        raise ValueError("frozen selection evidence differs")
    spec, policy = read_spec(folder / "candidate.json")
    if (
        spec != selected["candidate"]
        or policy.fingerprint() != selected["fingerprint"]
        or require_analysis(output, selected["id"]) != selected["analysis"]
    ):
        raise ValueError("frozen candidate or analysis differs")
    return selected, policy


def sensitivity_policies(policy: Strategy) -> dict[str, Strategy]:
    """Build two preregistered diagnostic horizon profiles, never candidates.

    All ten temporal windows move together by 0.8 or 1.2 with nearest-integer
    rounding. Numerical risk targets, thresholds, bands and maximum staleness
    remain identical. These profiles cannot enter the fifty-design selection.
    """
    fields = (
        "fast_sessions",
        "medium_sessions",
        "slow_sessions",
        "ma_fast_sessions",
        "ma_slow_sessions",
        "vol_fast_returns",
        "vol_slow_returns",
        "drawdown_sessions",
        "defensive_sessions",
        "monetary_sessions",
    )
    profiles = {}
    for name, factor in (("neighbor_short", 0.8), ("neighbor_long", 1.2)):
        parameters = dict(policy.parameters())
        for key in fields:
            parameters[key] = round(parameters[key] * factor)
        profiles[name] = make_policy(parameters)
    return profiles


def run_diagnostics(kind: str, store: Path, output: Path, baseline: Path, hypothesis: Path) -> None:
    """Replay the frozen policy and announced nonsselectable robustness controls."""
    selected, policy = frozen_winner(output)
    runners = {cost: previous.build_runner(store, cost) for cost in (1.0, 2.0)}
    frozen = freeze_inputs(output, store, baseline, hypothesis, runners)
    if kind == "final":
        periods = {name: PERIODS[name] for name in ("final", "full")}
        policies = {name: policy for name in periods}
    elif kind == "robustness":
        periods = {f"start_{start[:4]}": (start, PERIODS["choice"][1]) for start in START_DATES}
        policies = {name: policy for name in periods}
        neighbors = sensitivity_policies(policy)
        periods.update({name: PERIODS["choice"] for name in neighbors})
        policies.update(neighbors)
    else:
        raise ValueError("unknown diagnostics kind")
    reference = BuyAndHold(instruments=("ETF_NASDAQ",), strategy_id="Nasdaq_buy_hold")
    schedule = SCHEDULES[selected["candidate"]["schedule"]]()
    jobs = []
    for name, (start, end) in periods.items():
        for cost in (1.0, 2.0):
            for role, book, cadence in (
                ("candidate", policies[name], schedule),
                ("Nasdaq_buy_hold", reference, EverySession()),
            ):
                jobs.append(
                    {
                        "period": name,
                        "start": start,
                        "end": end,
                        "cost_multiplier": cost,
                        "role": role,
                        "nonselectable": True,
                        "parameters": dict(book.parameters()),
                        "folder": f"{kind}/{name}" if kind == "robustness" else name,
                        "cache_key": canonical_hash(
                            signature(runners[cost], book, cadence, start, end, frozen)
                        ),
                    }
                )
    write_once(
        output / f"{kind}_contracts.json",
        {
            "selection_sha256": sha256(output / "selected.json"),
            "contracts": jobs,
        },
    )
    rows = []
    for job in jobs:
        role, cost, name = job["role"], job["cost_multiplier"], job["period"]
        book = policies[name] if role == "candidate" else reference
        cadence = schedule if role == "candidate" else EverySession()
        print(f"{kind} {name} x{cost:g} {role}", flush=True)
        values, key, _ = run_cached(
            runners[cost],
            book,
            cadence,
            job["start"],
            job["end"],
            output,
            output / job["folder"] / f"costs_x{int(cost)}" / role,
            frozen,
        )
        rows.append({**job, "cache_key": key, **values})
    freeze_inputs(output, store, baseline, hypothesis, runners)
    write_once(
        output / f"{kind}_completed.json",
        {
            "logical_contract_count": len(rows),
            "metrics": rows,
            "contract_sha256": sha256(output / f"{kind}_contracts.json"),
        },
    )


def cache_counts(output: Path) -> dict[str, int]:
    """Count complete physical simulations separately from logical comparisons."""
    logical = sum(
        len(read_json(path)["contracts"]) for path in output.glob("M[0-9][0-9]/contract.json")
    )
    for name in ("final", "robustness"):
        path = output / f"{name}_contracts.json"
        if path.is_file():
            logical += len(read_json(path)["contracts"])
    return {
        "physical_replays": sum(1 for _ in (output / "cache").glob("*/attempt.json")),
        "completed_physical_replays": sum(1 for _ in (output / "cache").glob("*/cache.json")),
        "logical_contracts": logical,
    }


def main(arguments: Sequence[str] | None = None) -> None:
    """Execute one design or an explicitly requested post-freeze phase."""
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--candidate", type=Path)
    mode.add_argument("--freeze", action="store_true")
    mode.add_argument("--final", action="store_true")
    mode.add_argument("--robustness", action="store_true")
    parser.add_argument("--store", type=Path, default=STORE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    parser.add_argument("--hypothesis", type=Path, default=HYPOTHESIS)
    options = parser.parse_args(arguments)
    if options.candidate is not None:
        iterate(
            options.candidate, options.store, options.output, options.baseline, options.hypothesis
        )
    elif options.freeze:
        freeze_selection(options.store, options.output, options.baseline, options.hypothesis)
    else:
        run_diagnostics(
            "final" if options.final else "robustness",
            options.store,
            options.output,
            options.baseline,
            options.hypothesis,
        )
    print(json.dumps(cache_counts(options.output), sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
