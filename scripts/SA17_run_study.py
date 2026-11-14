"""Run SA17's executable study exactly as ``research/SA17/study.toml`` froze it.

Run under WSL/POSIX from the repository root, after
``scripts/SA17_build_study_store.py``::

    uv run python scripts/SA17_run_study.py

Before any run it refuses to go on unless:

- producing inputs are committed; only generated study output may be dirty;
- the decision dates the calendars give under the declared NAV release are
  the 99 listed in ``study.toml``;
- the store's digest is the one its build recorded;
- the runner decides at the declared time.

It then runs eight books, each at x1 and x2 costs: the candidate, its four
controls, SA16_it2 rebuilt from its archived selection, Nasdaq bought and
held, and it2's C1, which is descriptive only. A run whose signature matches a
saved one is read back instead of run again. The signature covers the
strategy and schedule definitions, the window, every cost model, the
universe, the store digest, the analytics, producing file contents and the
captured dependency environment. HEAD remains provenance, not cache identity.
Reuse also requires a completion manifest and matching
hashes for every output artifact. A different or incomplete run is preserved
and refused; use a new output folder for a corrected run.

The comparisons then follow the frozen inference: a paired stationary
bootstrap of the candidate against each reference and control, Holm within
each family, blocks of 5 and 60 as sensitivities, the deflated Sharpe ratio
over five trials, and descriptive regimes. The provisional reading is applied
as written. The formal verdict stays ``INSUFFICIENT_EVIDENCE`` while a gate is
partial.

Outputs: ``results/SA17/executable/`` (one folder per run, ``summary.json``)
and the report ``results/SA17/study.md``.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib
import json
import math
import statistics
import subprocess
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from quant_backtester.analytics.config import AnalyticsConfig
from quant_backtester.analytics.curves import Book
from quant_backtester.analytics.performance import PerformanceStats
from quant_backtester.analytics.quality import deflated_sharpe_probability, session_sharpe
from quant_backtester.analytics.uncertainty import (
    PairedStatistic,
    holm_adjusted,
    paired_stationary_bootstrap,
)
from quant_backtester.backtest.runner import StrategyResult, StrategyRunner
from quant_backtester.backtest.schedule import (
    DecisionSchedule,
    EverySession,
    ListedSessions,
    Weekly,
)
from quant_backtester.data.calendars import CalendarRegistry
from quant_backtester.data.instruments import InstrumentRegistry, PublicationRule
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.data.repository import MarketDataRepository
from quant_backtester.execution.costs import CostModel
from quant_backtester.execution.model import ExecutionModel, Sizing
from quant_backtester.provenance import SourceState, environment_state, git_source_state
from quant_backtester.research.references import BuyAndHold, FixedWeights
from quant_backtester.research.sa17_contract import load_sector_costs, month_end_release_decisions
from quant_backtester.strategies.base import Strategy
from quant_backtester.strategies.SA17_sector_residual_momentum import (
    SA17SectorResidualMomentum,
    SectorRanking,
)

ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / "research" / "SA17" / "study.toml"
OUTPUT = ROOT / "results" / "SA17" / "executable"
REPORT = ROOT / "results" / "SA17" / "study.md"
SA16_SELECTED = ROOT / "results" / "SA16" / "selected.json"
CANDIDATE = "SA17_sector_residual_momentum"
MAX_ORDERS_PER_SESSION = 20
"""Orders a session may carry: research/SA17/protocol.md, "Max 20 orders per session".

A reporting bound of the protocol, not a parameter of any book: each run says
whether its busiest session stayed within it.
"""
COST_MULTIPLIERS = (1.0, 2.0)
"""The two cost levels the readings and the report are written for: declared and doubled."""
SCHEDULE_RULE = (
    "23:00 Paris on the first XPAR session on or after the release of the NAV of the "
    "completed month's last XNYS_XLON session (23:00 Paris, next XLON session), and not "
    "before the following month; research/SA17/study.toml"
)


@dataclass(frozen=True, slots=True)
class BookSpec:
    """A strategy, the schedule it decides on, its name and its role in the study."""

    name: str
    strategy: Strategy
    schedule: DecisionSchedule
    role: str


def load_study(path: Path = STUDY) -> dict[str, Any]:
    """Return the frozen study configuration."""
    with path.open("rb") as stream:
        return tomllib.load(stream)


def producing_files(study: Mapping[str, Any]) -> tuple[Path, ...]:
    """List producing code and configuration; store contents have their own digest."""
    paths = {
        path
        for path in (ROOT / "src/quant_backtester").rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    }
    paths.update(
        ROOT / name
        for name in (
            "scripts/SA17_run_study.py",
            "scripts/SA17_build_study_store.py",
            "research/SA17/study.toml",
            "research/SA17/fx_verification.json",
            "uv.lock",
            "pyproject.toml",
            "results/SA16/selected.json",
            study["costs"]["sector_costs"],
            *study["store"]["study_calendars"],
        )
    )
    return tuple(sorted(paths))


def producing_digest(paths: Sequence[Path]) -> str:
    """Hash paths and bytes of producing inputs, independently of HEAD and reports."""
    hashes = {
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths
    }
    return hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()


def checked_source(output: Path, report: Path, inputs: Sequence[Path]) -> SourceState:
    """Require committed inputs, allowing only generated output to dirty the checkout."""
    source = git_source_state(ROOT)
    if source.dirty is False:
        return source
    if source.dirty is None:
        raise SystemExit("refused: the checkout has no recorded commit")
    changed = set()
    for arguments in (
        ["diff", "HEAD", "--no-renames", "--name-only", "-z"],
        ["ls-files", "--others", "--exclude-standard", "-z"],
    ):
        result = subprocess.run(
            ["git", "-C", str(ROOT), *arguments], check=True, capture_output=True
        )
        changed.update(
            (ROOT / name.decode()).resolve() for name in result.stdout.split(b"\0") if name
        )
    protected = {path.resolve() for path in inputs}
    output, report = output.resolve(), report.resolve()
    if any(
        path in protected or not (path == report or path.is_relative_to(output)) for path in changed
    ):
        raise SystemExit("refused: commit changes outside generated study output first")
    return source


def analytics_of(study: Mapping[str, Any]) -> AnalyticsConfig:
    """Return the books' analytics convention (SA16's)."""
    values = study["analytics"]
    return AnalyticsConfig(
        sessions_per_year=values["sessions_per_year"],
        risk_free_rate=values["risk_free_rate"],
        minimum_sessions=values["minimum_sessions"],
    )


def store_path(study: Mapping[str, Any]) -> Path:
    """Return the study store."""
    return ROOT / study["store"]["path"]


def calendars_of(store: Path) -> CalendarRegistry:
    """Return the store's calendars, SA17's grid and London included."""
    return CalendarRegistry.from_directory(store / "metadata" / "calendars")


def checked_schedule(study: Mapping[str, Any], calendars: CalendarRegistry) -> ListedSessions:
    """Return the frozen decision dates, refused unless the calendars give exactly them.

    Raises
    ------
    ValueError
        If the dates derived from the store's calendars under the declared
        release differ from those listed in ``study.toml``, or the study
        window is not the one those dates cover: a decision outside it, or
        room in it for a decision the list does not hold.
    """
    settings = study["schedule"]
    release = study["nav_publication"]
    rule = PublicationRule(
        publication_time=release["publication_time"],
        timezone=release["timezone"],
        lag_sessions=release["lag_sessions"],
        calendar_id=release["calendar_id"],
    )
    frozen = settings["decisions"]
    derived = month_end_release_decisions(
        calendars.get(settings["observation_calendar_id"]),
        calendars.get(settings["release_calendar_id"]),
        calendars.get(settings["decision_calendar_id"]),
        rule,
        settings["decision_time"],
        date.fromisoformat(frozen[0][0] + "-01"),
        date.fromisoformat(frozen[-1][0] + "-01"),
    )
    listed = [[item.month, item.last_observation, item.decision] for item in derived]
    if listed != frozen:
        differ = [pair for pair in zip(listed, frozen, strict=False) if pair[0] != pair[1]]
        raise ValueError(f"the calendars no longer give the frozen schedule: {differ[:3]}")
    # A listed schedule replays its dates and drops those outside the run, so
    # a window wider than the list would run on with decisions missing.
    start, end = study["window"]["start"], study["window"]["end"]
    first_month = date.fromisoformat(frozen[0][0] + "-01")
    last_month = date.fromisoformat(frozen[-1][0] + "-01")
    before = month_end_release_decisions(
        calendars.get(settings["observation_calendar_id"]),
        calendars.get(settings["release_calendar_id"]),
        calendars.get(settings["decision_calendar_id"]),
        rule,
        settings["decision_time"],
        (first_month - timedelta(days=1)).replace(day=1),
        (first_month - timedelta(days=1)).replace(day=1),
    )[0].decision
    # The month after the last listed one is decided in the month after it, at the earliest.
    after = (last_month + timedelta(days=62)).replace(day=1)
    if derived[0].decision < start or derived[-1].decision > end:
        raise ValueError("a frozen decision lies outside the study window")
    if before >= start or end >= after:
        raise ValueError(
            f"the window {start}..{end} holds a decision the frozen schedule does not list "
            f"(the one before it falls on {before}, the one after it not before {after})"
        )
    return ListedSessions(tuple(item.decision for item in derived), rule=SCHEDULE_RULE)


def reader_of(store: Path, calendars: CalendarRegistry) -> MarketDataReader:
    """Return a reader of the store on the Paris reference calendar."""
    return MarketDataReader(
        repository=MarketDataRepository(store),
        instruments=InstrumentRegistry.from_toml(store / "metadata" / "instruments.toml"),
        calendars=calendars,
        reference_calendar_id="XPAR",
    )


def checked_digest(store: Path, calendars: CalendarRegistry) -> str:
    """Return the store digest, refused unless it is the one its build recorded."""
    recorded = json.loads((store / "study_store.json").read_text(encoding="utf-8"))["digest"]
    with reader_of(store, calendars).pinned() as state:
        digest = state.digest
    if digest != recorded:
        raise ValueError(f"the store digest {digest} is not the built one, {recorded}")
    return digest


def cost_models(study: Mapping[str, Any], multiplier: float) -> dict[str, CostModel]:
    """Return one explicit cost model per traded fund, every term scaled by ``multiplier``."""
    settings = study["costs"]
    if multiplier not in settings["multipliers"]:
        raise ValueError(f"x{multiplier} is not a declared cost level")
    models = load_sector_costs(
        ROOT / settings["sector_costs"], study["strategy"]["sector_ids"], multiplier=multiplier
    )
    other = CostModel(
        commission_rate=settings["other_commission_rate"],
        minimum_commission=settings["other_minimum_commission_eur"],
        half_spread_rate=settings["other_half_spread_rate"],
        slippage_rate=settings["other_slippage_rate"],
    ).scaled(multiplier)
    for name in settings["other_funds"]:
        models[name] = other
    return models


def universe_of(study: Mapping[str, Any]) -> tuple[str, ...]:
    """Return the tradable funds of every book; NAVs, market and FX are read by signals."""
    return (*study["strategy"]["sector_ids"], *study["costs"]["other_funds"])


def build_runner(
    store: Path,
    study: Mapping[str, Any],
    calendars: CalendarRegistry,
    multiplier: float,
    source: SourceState,
    environment: Mapping[str, str],
) -> StrategyRunner:
    """Wire the EUR runner: Paris decisions, next-open fills, every fund's own costs."""
    models = cost_models(study, multiplier)
    other = models[study["costs"]["other_funds"][0]]
    runner = StrategyRunner(
        reader=reader_of(store, calendars),
        calendars=calendars,
        reference_calendar_id="XPAR",
        base_currency="EUR",
        analytics=analytics_of(study),
        execution=ExecutionModel(
            costs=other, sizing=Sizing.AT_DECISION, costs_by_instrument=models
        ),
        initial_cash=study["window"]["initial_cash_eur"],
        schedule=EverySession(),
        source=source,
        lockfile=ROOT / "uv.lock",
        environment=environment,
    )
    if runner.timetable.decision_time != study["schedule"]["decision_time"]:
        raise ValueError("the runner does not decide at the declared time")
    return runner


def candidate_of(study: Mapping[str, Any]) -> SA17SectorResidualMomentum:
    """Return the candidate with the frozen parameters."""
    values = dict(study["strategy"])
    values.pop("class")
    if values.pop("risk_input_ids") != "same as signal_input_ids":
        raise ValueError("study.toml must keep the risk inputs equal to the signal inputs")
    return SA17SectorResidualMomentum(
        sector_ids=tuple(values.pop("sector_ids")),
        signal_input_ids=tuple(values["signal_input_ids"]),
        risk_input_ids=tuple(values.pop("signal_input_ids")),
        ranking=SectorRanking(values.pop("ranking")),
        **values,
    )


def sa16_books() -> tuple[BookSpec, BookSpec]:
    """Return SA16_it2 rebuilt from its archived selection, and its C1."""
    selected = json.loads(SA16_SELECTED.read_text(encoding="utf-8"))
    if selected["candidate"]["id"] != "SA16_it2" or selected["schedule"] != "weekly":
        raise ValueError("results/SA16/selected.json is not the selection this study froze")
    module, _, name = selected["class"].rpartition(".")
    strategy = getattr(importlib.import_module(module), name)(**selected["parameters"])
    if strategy.fingerprint() != selected["fingerprint"]:
        raise ValueError("SA16_it2 rebuilt from selected.json does not match its fingerprint")
    c1 = selected["candidate"]["controls"]["SA16_it2_C1_constant_two_thirds"]["parameters"]
    control = FixedWeights(
        weights=tuple((fund, float(weight)) for fund, weight in c1["weights"]),
        rebalance_band=c1["rebalance_band"],
        strategy_id=c1["strategy_id"],
    )
    return (
        BookSpec("SA16_it2", strategy, Weekly(), "reference"),
        BookSpec("SA16_it2_C1_constant_two_thirds", control, Weekly(), "descriptive"),
    )


def books_of(study: Mapping[str, Any], schedule: ListedSessions) -> list[BookSpec]:
    """Return the eight books, in the order of ``study.toml``."""
    candidate = candidate_of(study)
    controls = candidate.controls()
    if list(controls) != study["books"]["controls"]:
        raise ValueError("the strategy's controls are not the ones study.toml lists")
    it2, c1 = sa16_books()
    return [
        BookSpec(CANDIDATE, candidate, schedule, "candidate"),
        *(BookSpec(name, control, schedule, "control") for name, control in controls.items()),
        it2,
        BookSpec("Nasdaq_buy_hold", BuyAndHold(("ETF_NASDAQ",)), EverySession(), "reference"),
        c1,
    ]


def signature(
    book: BookSpec,
    study: Mapping[str, Any],
    multiplier: float,
    digest: str,
    content_digest: str,
    environment: Mapping[str, str],
) -> str:
    """Hash producing content, run inputs and the captured dependency environment."""
    content = {
        "content_sha256": content_digest,
        "environment": dict(environment),
        "strategy": dict(book.strategy.definition()),
        "schedule": book.schedule.definition(),
        "window": [study["window"]["start"], study["window"]["end"]],
        "initial_cash": study["window"]["initial_cash_eur"],
        "costs_multiplier": multiplier,
        "costs": {
            name: model.definition()
            for name, model in sorted(cost_models(study, multiplier).items())
        },
        "universe": universe_of(study),
        "data_state": digest,
        "analytics": analytics_of(study).definition(),
    }
    return hashlib.sha256(json.dumps(content, sort_keys=True, default=str).encode()).hexdigest()


def write_json(path: Path, value: object) -> None:
    """Write readable JSON with no NaN."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False, default=str) + "\n",
        encoding="utf-8",
    )


def finite(value: float | None) -> float | None:
    """Return ``None`` for a missing or non-finite number."""
    return None if value is None or not math.isfinite(value) else float(value)


def curve_metrics(curve: pd.Series, config: AnalyticsConfig) -> dict[str, Any]:  # type: ignore[type-arg]
    """Return the headline measures of one curve."""
    stats = PerformanceStats.from_equity(curve, config)
    return {
        "start": curve.index[0],
        "end": curve.index[-1],
        "total_return": finite(stats.total_return),
        "cagr": finite(stats.annualised_return),
        "volatility": finite(stats.annualised_volatility),
        "sharpe": finite(stats.sharpe_ratio),
        "max_drawdown": finite(stats.drawdown.depth),
    }


def kept_unreadable(decisions: Sequence[Any]) -> int:
    """Count the decisions that kept the positions because an input was unreadable.

    Holding is also the ordinary answer of a book with nothing to change (a
    bought-and-held fund, a weight inside its band); only a hold that names
    an input it could not read counts.
    """
    return sum(
        1
        for decision in decisions
        if decision.requested.hold_positions and decision.requested.skipped
    )


def run_metrics(
    result: StrategyResult, config: AnalyticsConfig, models: Mapping[str, CostModel]
) -> dict[str, Any]:
    """Return gross and net measures, the split costs, orders, rejects and decisions."""
    net, gross = result.equity(), result.equity(Book.GROSS)
    fills, orders, rejects = result.fills(), result.orders(), result.rejects()
    unpriced = sorted(set(fills["instrument_id"]) - set(models)) if len(fills) else []
    if unpriced:
        raise ValueError(f"funds traded without a declared cost model: {unpriced}")
    years = max((result.end - result.start).days / 365.25, 1 / 252)
    traded = math.fsum(float(value) for value in fills["traded_value"]) if len(fills) else 0.0
    per_session = [int(count) for count in orders.groupby("session_date").size().tolist()]
    weights = result.weights()
    decisions = [record.decision for record in result.records() if record.decision is not None]
    cancelled: dict[str, int] = {}
    for record in result.records():
        decision = record.decision
        if decision is None or not decision.requested.hold_positions:
            continue
        for status in decision.requested.skipped.values():
            cancelled[status.value] = cancelled.get(status.value, 0) + 1

    def total(column: str) -> float:
        return math.fsum(float(value) for value in fills[column]) if len(fills) else 0.0

    return {
        "net": curve_metrics(net, config),
        "gross": curve_metrics(gross, config),
        "costs_eur": float(result.backtest.total_cost),
        "spread_eur": total("spread_cost"),
        "commission_eur": total("commission"),
        "slippage_eur": total("slippage_cost"),
        "traded_value_eur": traded,
        "turnover_per_year": traded / float(net.mean()) / years,
        "average_invested": float(weights.sum(axis=1).mean()),
        "orders": len(orders),
        "fills": len(fills),
        "rejects": len(rejects),
        "rejects_by_reason": {
            str(reason): int(count) for reason, count in rejects["reason"].value_counts().items()
        }
        if len(rejects)
        else {},
        "intervention_days": len(per_session),
        "orders_per_intervention_mean": statistics.fmean(per_session) if per_session else 0.0,
        "orders_per_intervention_max": max(per_session, default=0),
        "max_orders_per_session_allowed": MAX_ORDERS_PER_SESSION,
        "orders_per_session_within_limit": max(per_session, default=0) <= MAX_ORDERS_PER_SESSION,
        "decisions": len(decisions),
        "decisions_kept_with_unreadable_inputs": kept_unreadable(decisions),
        "unreadable_input_statuses": cancelled,
        "run_id": result.run_id,
        "data_state": result.data_state.digest,
    }


def sector_exposure(
    result: StrategyResult, sectors: Sequence[str], monetary: str
) -> dict[str, Any]:
    """Return the candidate-family exposure read from the targets of its decisions."""
    targets = result.target_weights()
    decided = [record.session_date for record in result.records() if record.decision is not None]
    rows = targets.loc[[day for day in decided if day in targets.index]]
    held = rows[[name for name in sectors if name in rows.columns]].sum(axis=1)
    in_monetary = rows[monetary] if monetary in rows.columns else pd.Series(0.0, index=rows.index)
    return {
        "mean_sector_exposure_at_decisions": float(held.mean()) if len(held) else None,
        "min_sector_exposure_at_decisions": float(held.min()) if len(held) else None,
        "decisions_wholly_monetary": int(((held <= 1e-12) & (in_monetary > 0.0)).sum()),
    }


def save_run(
    folder: Path,
    result: StrategyResult,
    book: BookSpec,
    key: str,
    config: AnalyticsConfig,
    models: Mapping[str, CostModel],
    study: Mapping[str, Any],
) -> dict[str, Any]:
    """Reserve an output directory exclusively, then publish its completion marker last."""
    reserve_run(folder)
    return _save_reserved_run(folder, result, book, key, config, models, study)


def reserve_run(folder: Path) -> None:
    """Atomically reserve a run directory, preserving even empty existing directories."""
    folder.parent.mkdir(parents=True, exist_ok=True)
    try:
        folder.mkdir()
    except FileExistsError as error:
        raise FileExistsError(f"{folder} already exists; choose a new folder") from error


def _save_reserved_run(
    folder: Path,
    result: StrategyResult,
    book: BookSpec,
    key: str,
    config: AnalyticsConfig,
    models: Mapping[str, CostModel],
    study: Mapping[str, Any],
) -> dict[str, Any]:
    """Finish an exclusively reserved run; interruptions leave it visibly incomplete."""
    values = _write_run(folder, result, book, key, config, models, study)
    write_json(folder / "complete.json", {"signature": key, "sha256": artifact_hashes(folder)})
    return values


RUN_ARTIFACTS = (
    "metrics.json",
    "strategy.json",
    "schedule.json",
    "configuration.json",
    "equity.csv",
    "gross_equity.csv",
    "weights.csv",
    "fills.csv",
    "orders.csv",
    "rejects.csv",
    "decisions.csv",
)
"""Artifacts required to reuse a completed study run."""


def artifact_hashes(folder: Path) -> dict[str, str]:
    """Hash the complete required artifact set, surfacing file I/O failures."""
    return {
        name: hashlib.sha256((folder / name).read_bytes()).hexdigest() for name in RUN_ARTIFACTS
    }


def _write_run(
    folder: Path,
    result: StrategyResult,
    book: BookSpec,
    key: str,
    config: AnalyticsConfig,
    models: Mapping[str, CostModel],
    study: Mapping[str, Any],
) -> dict[str, Any]:
    """Write artifacts inside the reserved directory before its completion marker."""
    values = run_metrics(result, config, models)
    if isinstance(book.strategy, SA17SectorResidualMomentum):
        values.update(sector_exposure(result, study["strategy"]["sector_ids"], "ETF_MONETARY_EUR"))
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


def checked_saved_run(folder: Path, key: str) -> dict[str, Any]:
    """Read a completed run only when its identity and every artifact hash agree."""
    try:
        completion = json.loads((folder / "complete.json").read_text(encoding="utf-8"))
        if completion["signature"] != key:
            raise ValueError("different run identity")
        hashes = completion["sha256"]
        if set(hashes) != set(RUN_ARTIFACTS):
            raise ValueError("incomplete artifact manifest")
        if artifact_hashes(folder) != hashes:
            raise ValueError("artifact hashes changed")
        values = json.loads((folder / "metrics.json").read_text(encoding="utf-8"))
        if values["signature"] != key:
            raise ValueError("different metrics identity")
    except FileNotFoundError as error:
        raise FileExistsError(
            f"{folder} is incomplete ({Path(error.filename or '').name or error} is missing): "
            "a run was interrupted there; choose a new folder"
        ) from error
    except OSError as error:
        raise OSError(f"cannot read saved run {folder}: {error}") from error
    except (ValueError, KeyError, TypeError) as error:
        raise FileExistsError(
            f"{folder} is incomplete, changed or holds a different run; choose a new folder"
        ) from error
    return values


def release_run(folder: Path) -> None:
    """Give back a reservation nothing was written into; a folder with content is kept."""
    with contextlib.suppress(OSError):
        folder.rmdir()


def checked_unchanged(
    study: Mapping[str, Any], content_digest: str, environment: Mapping[str, str]
) -> None:
    """Refuse a run during which the code or the installed environment changed.

    The runner stamps every run with the snapshot taken once by ``main``, so
    comparing a run's record with that snapshot can never fail. This samples
    both again, after the run.

    Raises
    ------
    ValueError
        If the installed environment or a producing file is no longer what
        the run's identity says.
    """
    if environment_state(ROOT / "uv.lock") != dict(environment):
        raise ValueError("the installed environment changed during the run")
    if producing_digest(producing_files(study)) != content_digest:
        raise ValueError("a producing file changed during the run")


def run_book(
    book: BookSpec,
    study: Mapping[str, Any],
    runner: StrategyRunner,
    multiplier: float,
    digest: str,
    output: Path,
    content_digest: str,
    environment: Mapping[str, str],
) -> dict[str, Any]:
    """Run one book, or read it back if the same run is already saved."""
    folder = output / f"{book.name}_x{multiplier:g}"
    key = signature(book, study, multiplier, digest, content_digest, environment)
    if folder.exists():
        values = checked_saved_run(folder, key)
        print(f"  reused {folder}", flush=True)
        return values
    reserve_run(folder)
    window = study["window"]
    print(f"  running {book.name} x{multiplier:g}", flush=True)
    try:
        result = runner.run(
            book.strategy,
            universe_of(study),
            window["start"].isoformat(),
            window["end"].isoformat(),
            schedule=book.schedule,
        )
        if result.configuration["environment"] != dict(environment):
            raise ValueError("the run environment differs from its cache identity")
        checked_unchanged(study, content_digest, environment)
    except BaseException:
        release_run(folder)
        raise
    result = replace(
        result,
        configuration=dict(result.configuration)
        | {
            "run_content_sha256": content_digest,
        },
    )
    models = cost_models(study, multiplier)
    return _save_reserved_run(folder, result, book, key, analytics_of(study), models, study)


def load_curve(folder: Path, name: str = "equity.csv") -> pd.Series:  # type: ignore[type-arg]
    """Read a saved curve with date labels."""
    frame = pd.read_csv(folder / name)
    index = pd.Index([date.fromisoformat(value) for value in frame["session_date"]])
    return pd.Series(frame.iloc[:, 1].to_numpy(dtype=float), index=index)


def slice_metrics(
    curve: pd.Series,  # type: ignore[type-arg]
    start: str,
    end: str,
    config: AnalyticsConfig,
) -> dict[str, Any] | None:
    """Measure a slice of a continuous book, anchored on the close before it."""
    lower, upper = date.fromisoformat(start), date.fromisoformat(end)
    days: list[date] = list(curve.index)
    kept = [index for index, day in enumerate(days) if lower <= day <= upper]
    if len(kept) < 3:
        return None
    if kept[0] > 0:
        kept.insert(0, kept[0] - 1)
    return curve_metrics(curve.iloc[kept], config)


def comparison(
    candidate: pd.Series,  # type: ignore[type-arg]
    other: pd.Series,  # type: ignore[type-arg]
    inference: Mapping[str, Any],
    config: AnalyticsConfig,
) -> dict[str, Any]:
    """Return the paired bootstrap of the candidate against one book, every declared block."""
    values: dict[str, Any] = {}
    blocks = [inference["mean_block_sessions"], *inference["sensitivity_blocks"]]
    for statistic_name in (inference["primary_statistic"], inference["secondary_statistic"]):
        statistic = PairedStatistic[statistic_name]
        for block in blocks:
            outcome = paired_stationary_bootstrap(
                candidate,
                other,
                statistic=statistic,
                mean_block=block,
                draws=inference["draws"],
                seed=inference["seed"],
                level=inference["level"],
                config=config,
            )
            values[f"{statistic_name.lower()}_block{block}"] = outcome.definition()
    return values


def reading_against_references(
    candidate: Mapping[str, Any],
    references: Mapping[str, Mapping[str, Any]],
    stressed_candidate: Mapping[str, Any],
    stressed: Mapping[str, Mapping[str, Any]],
    holm: Mapping[str, float],
    tolerance: float,
    alpha: float,
) -> dict[str, Any]:
    """Apply the frozen criterion against the reference family.

    Net CAGR and net Sharpe above each reference, with a maximum drawdown at
    most ``tolerance`` deeper: ``NOT_SUPPORTED`` when that fails at x1;
    ``UNCERTAIN`` when it holds but a Holm p-value is at or above ``alpha`` or
    it fails at x2; ``SUPPORTED_PROVISIONAL`` otherwise.

    Raises
    ------
    ValueError
        If a book has no CAGR, Sharpe ratio or maximum drawdown to compare.
    """

    def holds(mine: Mapping[str, Any], theirs: Mapping[str, Any]) -> bool:
        for values in (mine, theirs):
            missing = [key for key in ("cagr", "sharpe", "max_drawdown") if values[key] is None]
            if missing:
                raise ValueError(f"the criterion cannot be read: a book has no {missing}")
        return (
            mine["cagr"] > theirs["cagr"]
            and mine["sharpe"] > theirs["sharpe"]
            and mine["max_drawdown"] >= theirs["max_drawdown"] - tolerance
        )

    at_x1 = {name: holds(candidate, values) for name, values in references.items()}
    at_x2 = {name: holds(stressed_candidate, values) for name, values in stressed.items()}
    significant = {name: holm[name] < alpha for name in references}
    if not all(at_x1.values()):
        verdict = "NOT_SUPPORTED"
    elif not all(significant.values()) or not all(at_x2.values()):
        verdict = "UNCERTAIN"
    else:
        verdict = "SUPPORTED_PROVISIONAL"
    return {
        "criterion_x1": at_x1,
        "criterion_x2": at_x2,
        "holm_significant": significant,
        "reading": verdict,
    }


def reading_against_control(difference: float, holm_p: float, stressed: float, alpha: float) -> str:
    """Apply the frozen per-control rule to a Sharpe difference."""
    if difference <= 0.0:
        return "NOT_SUPPORTED"
    if holm_p >= alpha or stressed <= 0.0:
        return "UNCERTAIN"
    return "SUPPORTED_PROVISIONAL"


def checked_multipliers(study: Mapping[str, Any]) -> None:
    """Refuse cost levels other than the two the readings and the report are written for."""
    if tuple(study["costs"]["multipliers"]) != COST_MULTIPLIERS:
        raise ValueError(
            f"the readings compare costs x1 with x2; study.toml declares "
            f"{study['costs']['multipliers']}"
        )


def gates_at_run(study: Mapping[str, Any], store: Path) -> dict[str, str]:
    """Return the admission gates as they stood at the run.

    ``study.toml`` was frozen while 2d was still to pass, and says so. The
    store cannot be built unless 2d's verification passed, and its record
    names the verified table; 2d is read from that record, and the other
    gates from ``study.toml``.

    Raises
    ------
    ValueError
        If the store's record does not carry 2d's evidence.
    """
    gates = dict(study["gates"])
    record = json.loads((store / "study_store.json").read_text(encoding="utf-8")).get("fx", {})
    sample, table = record.get("verification_sample"), record.get("table_sha256")
    if type(sample) is not int or sample < 1 or not isinstance(table, str) or not table:
        raise ValueError("the store does not record gate 2d's verification")
    gates["2d_synchronous_fx"] = (
        f"PASSED: {sample} of {sample} sampled sessions agree; table {table[:12]}, "
        "checked when the store was built"
    )
    return gates


def analyse(
    study: Mapping[str, Any],
    books: Sequence[BookSpec],
    output: Path,
    gates: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Compare the saved runs under the frozen inference and readings.

    ``gates`` is the admission status at the run, from :func:`gates_at_run`;
    ``None`` reports the statuses ``study.toml`` froze before it.
    """
    checked_multipliers(study)
    config = analytics_of(study)
    inference = study["inference"]
    curves = {
        (book.name, multiplier): load_curve(output / f"{book.name}_x{multiplier:g}")
        for book in books
        for multiplier in study["costs"]["multipliers"]
    }
    common = None
    for curve in curves.values():
        common = curve.index if common is None else common.intersection(curve.index)
    assert common is not None
    curves = {key: curve.loc[common] for key, curve in curves.items()}
    metrics = {
        f"{name}_x{multiplier:g}": json.loads(
            (output / f"{name}_x{multiplier:g}" / "metrics.json").read_text(encoding="utf-8")
        )
        for name, multiplier in curves
    }
    on_common = {
        f"{name}_x{multiplier:g}": curve_metrics(curve, config)
        for (name, multiplier), curve in curves.items()
    }
    candidate_x1 = curves[(CANDIDATE, 1.0)]
    families = inference["holm_families"]
    tests: dict[str, Any] = {}
    for family in families.values():
        for name in family:
            tests[name] = comparison(candidate_x1, curves[(name, 1.0)], inference, config)
    primary = f"{inference['primary_statistic'].lower()}_block{inference['mean_block_sessions']}"
    holm = {
        family: holm_adjusted({name: tests[name][primary]["p_value"] for name in members})
        for family, members in families.items()
    }

    def sharpe(key: tuple[str, float]) -> float:
        value = curve_metrics(curves[key], config)["sharpe"]
        if value is None:
            raise ValueError(f"{key} has no Sharpe ratio")
        return float(value)

    stressed_difference = {
        name: sharpe((CANDIDATE, 2.0)) - sharpe((name, 2.0))
        for members in families.values()
        for name in members
    }
    alpha = inference["significance"]
    references = families["references"]
    against_references = reading_against_references(
        on_common[f"{CANDIDATE}_x1"],
        {name: on_common[f"{name}_x1"] for name in references},
        on_common[f"{CANDIDATE}_x2"],
        {name: on_common[f"{name}_x2"] for name in references},
        holm["references"],
        inference["max_drawdown_tolerance"],
        alpha,
    )
    against_controls = {
        name: {
            "sharpe_difference": tests[name][primary]["estimate"],
            "holm_p": holm["controls"][name],
            "sharpe_difference_x2": stressed_difference[name],
            "reading": reading_against_control(
                tests[name][primary]["estimate"],
                holm["controls"][name],
                stressed_difference[name],
                alpha,
            ),
        }
        for name in families["controls"]
    }
    trials = [CANDIDATE, *families["controls"]]
    if len(trials) != inference["deflated_sharpe_trials"]:
        raise ValueError("the deflated Sharpe trial count is not the frozen one")
    sampled = [session_sharpe(curves[(name, 1.0)], config) for name in trials]
    per_session = [float(value) for value in sampled if value is not None]
    if len(per_session) != len(trials):
        raise ValueError("a trial has no per-session Sharpe ratio")
    deflated = deflated_sharpe_probability(
        candidate_x1,
        config,
        trials=len(trials),
        trial_sharpe_std=statistics.stdev(per_session),
    )
    regimes = {
        f"{start}..{end}": {
            name: slice_metrics(curves[(name, 1.0)], start, end, config)
            for name in (book.name for book in books)
        }
        for start, end in study["regimes"]["periods"]
    }
    return {
        "status": study["status"],
        "formal_verdict": study["formal_verdict"],
        "gates": dict(study["gates"]) if gates is None else dict(gates),
        "gates_frozen": dict(study["gates"]),
        "blocks": {
            "primary_statistic": inference["primary_statistic"].lower(),
            "secondary_statistic": inference["secondary_statistic"].lower(),
            "main": inference["mean_block_sessions"],
            "sensitivities": list(inference["sensitivity_blocks"]),
            "level": inference["level"],
        },
        "sessions": len(common),
        "start": common[0],
        "end": common[-1],
        "metrics": metrics,
        "on_common_sessions": on_common,
        "tests": tests,
        "holm": holm,
        "sharpe_difference_x2": stressed_difference,
        "against_references": against_references,
        "against_controls": against_controls,
        "deflated_sharpe": {"trials": len(trials), "probability": deflated},
        "regimes": regimes,
    }


def pct(value: float | None, digits: int = 1) -> str:
    """Format a fraction as a percentage."""
    return "—" if value is None else f"{value * 100:.{digits}f} %"


def num(value: float | None, digits: int = 2) -> str:
    """Format a number."""
    return "—" if value is None else f"{value:.{digits}f}"


def markdown(summary: Mapping[str, Any], books: Sequence[BookSpec]) -> str:
    """Return the factual report of the run; interpretation is written beside it."""
    lines = [
        "# SA17 — executable study (provisional)",
        "",
        f"Status: **{summary['status']}**. Formal verdict of "
        f"`sa17_usd_nav_residual_momentum`: **{summary['formal_verdict']}**.",
        "",
        "Frozen in [research/SA17/protocol.md](../../research/SA17/protocol.md) "
        '("Executable run: frozen schedule and assumptions") and '
        "[study.toml](../../research/SA17/study.toml) before any run. "
        "Generated by `scripts/SA17_run_study.py`.",
        "",
        "## Admission gates",
        "",
        "| Gate | Status |",
        "| --- | --- |",
    ]
    for gate, status in summary["gates"].items():
        lines.append(f"| {gate} | {status} |")
    lines += [
        "",
        "Statuses at the run. `study.toml`, frozen before it, lists 2d as a gate that had "
        "to pass first.",
        "",
        f"Common sessions: {summary['sessions']}, {summary['start']} to {summary['end']} "
        "(XPAR, 252 a year, zero risk-free rate).",
        "",
        "## Books, net and gross",
        "",
        "| Book | Role | Net CAGR | Gross CAGR | Net Sharpe | Volatility | Max drawdown "
        "| Net CAGR x2 | Net Sharpe x2 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for book in books:
        one = summary["metrics"][f"{book.name}_x1"]
        two = summary["metrics"][f"{book.name}_x2"]
        lines.append(
            f"| {book.name} | {book.role} | {pct(one['net']['cagr'])} | "
            f"{pct(one['gross']['cagr'])} | {num(one['net']['sharpe'])} | "
            f"{pct(one['net']['volatility'])} | {pct(one['net']['max_drawdown'])} | "
            f"{pct(two['net']['cagr'])} | {num(two['net']['sharpe'])} |"
        )
    lines += [
        "",
        "## Costs, orders and refusals (x1)",
        "",
        "| Book | Costs EUR | Spread | Commission | Slippage | Turnover/yr | Orders "
        "| Mean/max per day | Rejects | Decisions kept, input unreadable |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: |",
    ]
    for book in books:
        one = summary["metrics"][f"{book.name}_x1"]
        lines.append(
            f"| {book.name} | {one['costs_eur']:,.0f} | {one['spread_eur']:,.0f} | "
            f"{one['commission_eur']:,.0f} | {one['slippage_eur']:,.0f} | "
            f"{num(one['turnover_per_year'])} | {one['orders']} | "
            f"{num(one['orders_per_intervention_mean'], 1)} / "
            f"{one['orders_per_intervention_max']} | {one['rejects']} | "
            f"{one['decisions_kept_with_unreadable_inputs']} |"
        )
    candidate = summary["metrics"][f"{CANDIDATE}_x1"]
    blocks = summary["blocks"]
    lines += [
        "",
        f"Candidate: mean sector exposure at decisions "
        f"{pct(candidate.get('mean_sector_exposure_at_decisions'))}, minimum "
        f"{pct(candidate.get('min_sector_exposure_at_decisions'))}; "
        f"{candidate.get('decisions_wholly_monetary')} decisions wholly in XEON; "
        f"rejects by reason {candidate['rejects_by_reason']}; unreadable inputs "
        f"{candidate['unreadable_input_statuses']}.",
        "",
        "## Candidate against references and controls (x1, paired stationary bootstrap)",
        "",
        f"| Against | Sharpe diff | {blocks['level'] * 100:g} % interval | p | Holm p | Diff x2 | "
        + "".join(f"Block {block} interval | " for block in blocks["sensitivities"])
        + "Mean-return diff (ann.) |",
        "| --- | ---: | --- | ---: | ---: | ---: | "
        + "--- | " * len(blocks["sensitivities"])
        + "---: |",
    ]
    for family, members in summary["holm"].items():
        for name, holm_p in members.items():
            test = summary["tests"][name]
            main = test[f"{blocks['primary_statistic']}_block{blocks['main']}"]
            mean = test[f"{blocks['secondary_statistic']}_block{blocks['main']}"]
            sensitivities = "".join(
                f"[{num(interval['low'], 3)}, {num(interval['high'], 3)}] | "
                for interval in (
                    test[f"{blocks['primary_statistic']}_block{block}"]
                    for block in blocks["sensitivities"]
                )
            )
            lines.append(
                f"| {name} ({family}) | {num(main['estimate'], 3)} | "
                f"[{num(main['low'], 3)}, {num(main['high'], 3)}] | {num(main['p_value'], 3)} | "
                f"{num(holm_p, 3)} | {num(summary['sharpe_difference_x2'][name], 3)} | "
                f"{sensitivities}{pct(mean['estimate'])} |"
            )
    refs = summary["against_references"]
    lines += [
        "",
        "## Provisional reading (rules frozen before the run)",
        "",
        f"- Against the references: **{refs['reading']}** (criterion at x1 "
        f"{refs['criterion_x1']}, at x2 {refs['criterion_x2']}, Holm significant "
        f"{refs['holm_significant']}).",
    ]
    for name, values in summary["against_controls"].items():
        lines.append(f"- Against `{name}`: **{values['reading']}**.")
    deflated = summary["deflated_sharpe"]
    lines += [
        "",
        f"Deflated Sharpe probability of the candidate over {deflated['trials']} trials: "
        f"{num(deflated['probability'], 3)} (ignores the SA15 and SA16 searches on "
        "overlapping data).",
        "",
        "These readings are descriptive while a gate is partial; they do not replace the "
        "formal verdict.",
        "",
        "## Regimes (x1, descriptive)",
        "",
        "| Period | " + " | ".join(book.name for book in books) + " |",
        "| --- | " + " | ".join("---:" for _ in books) + " |",
    ]
    for period, values in summary["regimes"].items():
        cells = []
        for book in books:
            item = values[book.name]
            cells.append("—" if item is None else pct(item["total_return"]))
        lines.append(f"| {period} | " + " | ".join(cells) + " |")
    lines.append("")
    return "\n".join(lines)


def main(arguments: list[str] | None = None) -> int:
    """Check the frozen inputs, run every book at both cost levels, then report."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--report", type=Path, default=REPORT)
    parsed = parser.parse_args(arguments)
    study = load_study()
    output = parsed.output if parsed.output.is_absolute() else ROOT / parsed.output
    report = parsed.report if parsed.report.is_absolute() else ROOT / parsed.report
    checked_multipliers(study)
    inputs = producing_files(study)
    source = checked_source(output, report, inputs)
    content_digest = producing_digest(inputs)
    environment = environment_state(ROOT / "uv.lock")
    store = store_path(study)
    calendars = calendars_of(store)
    schedule = checked_schedule(study, calendars)
    digest = checked_digest(store, calendars)
    books = books_of(study, schedule)
    for multiplier in study["costs"]["multipliers"]:
        runner = build_runner(store, study, calendars, multiplier, source, environment)
        for book in books:
            run_book(book, study, runner, multiplier, digest, output, content_digest, environment)
    summary = analyse(study, books, output, gates_at_run(study, store))
    write_json(output / "summary.json", summary)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(markdown(summary, books), encoding="utf-8")
    print(f"report: {report}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
