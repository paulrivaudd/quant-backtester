"""Calibrate ML1, the neural allocation, then run its final test beside three references.

The network is trained and selected before any backtest (``prepare``), and the
artifact it leaves is frozen: the test below loads it, checks that the test
period starts after its information cutoff, and runs it once. From the
repository root, once the store is filled and the ``ml`` extra installed
(``uv sync --extra ml``):

    uv run python scripts/run_neural_strategy.py --output results/ml1

The configuration is the one the store can serve today: the two PEA funds and
the VIX are read, the two funds are bought. Bond, oil and gold series are not
registered; adding them means extending ``feature_ids`` and calibrating again,
never reusing this artifact.

| part       | sessions                 | used for                                  |
|------------|--------------------------|-------------------------------------------|
| training   | 2019-01-02 to 2023-12-29 | the network's weights, the normalisation  |
| validation | 2024-01-02 to 2024-12-31 | choosing the epoch that is kept           |
| test       | 2025-01-02 to 2026-09-30 | measuring the frozen model, once          |

The validation figures printed here chose the model: they are not a test. The
test is run beside ``ETF_WORLD`` bought and held, the two funds in equal
weights, and ``SA1`` (the fund held above its 20-session average), on the same
dates, cash and costs. The alpha is the intercept of the regression of the
book's session returns on ``SA1``'s, not a difference of total returns.

The test period is not an untouched sample: the two funds' history up to
2026-09 was looked at in earlier exercises. ``--seed`` and
``--cost-multiplier`` rerun the whole thing under another seed (42, 43 and 44
are the announced ones) or with every cost doubled; a seed is never picked on
its test result. ``--calibrate-only`` stops after the validation: the test
period is then not read at all, which is how a calibration is checked without
spending the test.

What is written: ``summary.csv``, ``equity.csv``, ``weights.csv``,
``fills.csv``, ``rejects.csv`` and ``neural_decisions.csv`` - one row per
decision with the weights proposed, the target after the thresholds, the
weights held, the action taken and its reason, so that a day in cash for want
of data is told from a day in cash by choice.

The tests are in ``tests/scripts/test_run_neural_strategy.py``.
"""

from __future__ import annotations

import argparse
import math
import sys
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path

import pandas as pd

from quant_backtester.analytics.benchmark_comparison import alpha_vs_benchmark
from quant_backtester.analytics.config import AnalyticsConfig
from quant_backtester.analytics.curves import Book
from quant_backtester.analytics.quality import QUALITY_V1, quality_score
from quant_backtester.backtest.runner import StrategyResult, StrategyRunner
from quant_backtester.backtest.schedule import EverySession
from quant_backtester.data.calendars import CalendarRegistry
from quant_backtester.data.instruments import InstrumentRegistry
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.data.repository import MarketDataRepository
from quant_backtester.execution.costs import CostModel
from quant_backtester.execution.model import ExecutionModel, Sizing
from quant_backtester.ml.artifacts import MANIFEST_FILE, NeuralArtifact
from quant_backtester.ml.config import NeuralStrategyConfig
from quant_backtester.ml.training import VALIDATION_METRICS_FILE, calibrate_neural_strategy
from quant_backtester.provenance import git_source_state
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.types import SignalStatus
from quant_backtester.strategies import BuyAndHold, EqualWeightRebalance, WorldMA20Benchmark
from quant_backtester.strategies.base import Strategy
from quant_backtester.strategies.catalogue import entry
from quant_backtester.strategies.ml.neural_allocation import (
    Action,
    NeuralAllocationStrategy,
    neural_decision,
    require_after_cutoff,
)

REPOSITORY = Path(__file__).resolve().parents[1]
STORE = REPOSITORY / "market_data"

TRADABLE = ("ETF_WORLD", "ETF_SP500_PEA")
"""What the network may buy, in the order of its outputs."""

TEST_PERIOD = (date(2025, 1, 2), date(2026, 9, 30))
"""The final test, bounds included: after the validation, run once."""

INITIAL_CASH = 100_000.0

ANALYTICS = AnalyticsConfig(sessions_per_year=252, risk_free_rate=0.0, minimum_sessions=60)
"""252 sessions a year and cash earning nothing, as in the model's own objective."""

ML1, SA1 = entry("ML1").display_name, entry("SA1").display_name
HELD, SPLIT = "buy & hold World", "equal weight"
"""The book under test, its benchmark and the two references, as every output names them."""


def neural_config(seed: int = 42) -> NeuralStrategyConfig:
    """Return the configuration of ML1 on the series the store holds today."""
    return NeuralStrategyConfig(
        calibration_start=date(2019, 1, 2),
        validation_start=date(2024, 1, 2),
        calibration_end=date(2024, 12, 31),
        feature_ids=(*TRADABLE, "VIX"),
        tradable_ids=TRADABLE,
        history_sessions=100,
        ma_windows=(20, 50, 100),
        vol_windows=(20, 60),
        max_asset_weight=1.0,
        min_asset_weight=0.01,
        rebalance_band=0.03,
        risk_aversion=5.0,
        seed=seed,
    )


def execution_model(cost_multiplier: float = 1.0) -> ExecutionModel:
    """Return the opening cost assumption, every term scaled by ``cost_multiplier``."""
    return ExecutionModel(
        costs=CostModel(
            commission_rate=0.0005 * cost_multiplier,
            minimum_commission=1.0 * cost_multiplier,
            half_spread_rate=0.0003 * cost_multiplier,
            slippage_rate=0.0002 * cost_multiplier,
        ),
        sizing=Sizing.AT_DECISION,
    )


def build_runner(root: Path, cost_multiplier: float = 1.0) -> StrategyRunner:
    """Return the runner of the validation and of the test: XPAR, EUR, 23:00 decisions."""
    instruments = InstrumentRegistry.from_toml(root / "metadata" / "instruments.toml")
    calendars = CalendarRegistry.from_directory(root / "metadata" / "calendars")
    reader = MarketDataReader(
        repository=MarketDataRepository(root),
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
        execution=execution_model(cost_multiplier),
        initial_cash=INITIAL_CASH,
        schedule=EverySession(),
        source=git_source_state(REPOSITORY),
        lockfile=REPOSITORY / "uv.lock",
    )


def prepare(
    config: NeuralStrategyConfig, runner: StrategyRunner, artifact_dir: Path
) -> NeuralArtifact:
    """Return the frozen model of a configuration: loaded if it is there, calibrated if not.

    Parameters
    ----------
    config : NeuralStrategyConfig
        The configuration to run.
    runner : StrategyRunner
        The runner of the test; the validation uses it too.
    artifact_dir : Path
        The folder of this configuration's artifact, named explicitly.

    Returns
    -------
    NeuralArtifact
        The artifact found in ``artifact_dir`` when it was calibrated with
        exactly this configuration, a new calibration saved there otherwise.

    Raises
    ------
    ArtifactError
        If the folder holds a model of another configuration: it is neither
        used nor written over.
    """
    if (artifact_dir / MANIFEST_FILE).exists():
        return NeuralArtifact.load(artifact_dir, expected=config)
    source = runner.source.definition()
    calibration = calibrate_neural_strategy(
        config,
        reader=runner.reader,
        calendars=runner.calendars,
        validation_runner=runner,
        output_dir=artifact_dir,
        provenance={"source": dict(source)},
    )
    return calibration.artifact


def validate_test_period(
    strategy: NeuralAllocationStrategy, runner: StrategyRunner, start: date, end: date
) -> None:
    """Raise unless the first decision of a test is after the model's information cutoff."""
    calendar = runner.calendars.get(runner.reference_calendar_id)
    sessions = calendar.sessions(start, end)
    if not sessions:
        raise ValueError(f"{start} to {end} holds no session to test on")
    require_after_cutoff(strategy, runner.timetable.decision_instant(sessions[0].session_date))


def references() -> dict[str, Strategy]:
    """Return the benchmark and the two references ML1 is run beside, by display name."""
    return {
        SA1: WorldMA20Benchmark(),
        HELD: BuyAndHold(instruments=("ETF_WORLD",)),
        SPLIT: EqualWeightRebalance(instruments=TRADABLE),
    }


def neural_decisions(result: StrategyResult, strategy: NeuralAllocationStrategy) -> pd.DataFrame:
    """Return one row per decision of a run of ML1: proposal, target, book, action, reason.

    Parameters
    ----------
    result : StrategyResult
        A finished run of ``strategy``.
    strategy : NeuralAllocationStrategy
        The strategy that was run.

    Returns
    -------
    pd.DataFrame
        ``session_date``, ``model_id``, then per fund ``proposed_``,
        ``target_`` and ``held_`` weights, the proposed cash weight, the
        action the run recorded (``WEIGHTS``, ``CASH`` or ``HOLD``), its
        reason, and the series that made an input unusable. The proposal is
        computed again by the strategy's own signal on a reader fixed at the
        recorded decision instant; the action is the recorded one.
    """
    config = strategy.config
    signal = strategy.signal()
    rows: list[dict[str, object]] = []
    for record in result.records():
        if record.decision is None or record.decision_time is None:
            continue
        context = SignalContext(
            market=result.reader.at(record.decision_time),
            instruments=result.reader.instruments,
            calendars=result.reader.calendars,
        )
        frame = signal.compute(context, config.tradable_ids).frame
        usable = all(status is SignalStatus.OK for status in frame["status"])
        proposed = (
            {name: float(frame.loc[name, "value"]) for name in config.tradable_ids}
            if usable
            else None
        )
        held = {name: weight for name, weight in record.actual_weights.items() if weight > 0.0}
        explained = neural_decision(
            proposed,
            held,
            max_asset_weight=config.max_asset_weight,
            min_asset_weight=config.min_asset_weight,
            rebalance_band=config.rebalance_band,
        )
        requested = record.decision.requested
        if requested.hold_positions:
            action = Action.HOLD
        elif not requested.weights:
            action = Action.CASH
        else:
            action = Action.WEIGHTS
        row: dict[str, object] = {
            "session_date": record.session_date,
            "model_id": strategy.model_id,
        }
        for name in config.tradable_ids:
            row[f"proposed_{name}"] = None if proposed is None else proposed[name]
            row[f"target_{name}"] = explained.target.get(name, 0.0)
            row[f"held_{name}"] = held.get(name, 0.0)
        row["proposed_cash"] = float(frame["cash_weight"].iloc[0])
        row["held_cash"] = 1.0 - sum(held.values())
        row["action"] = action.value
        row["reason"] = explained.reason
        row["faulty_series"] = str(frame["faulty_series"].iloc[0])
        rows.append(row)
    return pd.DataFrame(rows)


def summary_row(
    result: StrategyResult,
    benchmark: pd.Series,  # type: ignore[type-arg]
    missing_data_decisions: int | None = None,
    market: pd.Series | None = None,  # type: ignore[type-arg]
) -> dict[str, float | None]:
    """Return one book's test figures, net of costs, and its relation to ``SA1``.

    Parameters
    ----------
    result : StrategyResult
        The finished run of the book.
    benchmark : pd.Series
        Net equity of ``SA1`` over the same sessions.
    missing_data_decisions : int | None
        Decisions that asked for cash because an input was unusable; ``None``
        for a book that has no such notion.
    market : pd.Series | None
        Net equity of ``ETF_WORLD`` bought and held over the same sessions.
        When given, the book is scored against it (quality score, version 1,
        one trial); left out for the market fund itself.

    Returns
    -------
    dict[str, float | None]
        Returns, risk, costs, traded value, exposure, rejects, and the beta
        and annualised alpha against ``SA1``. ``None`` where the sample does
        not support a figure - an alpha against a benchmark that did not move.
    """
    net = result.report().net
    relative = alpha_vs_benchmark(result.equity(), benchmark, ANALYTICS)
    exposure = float(result.weights().sum(axis=1).mean())
    fills = result.fills()
    quality = (
        None
        if market is None
        else quality_score(
            result.equity(),
            result.equity(Book.GROSS),
            market,
            ANALYTICS,
            trials=1,
            trial_sharpe_std=0.0,
            rules=QUALITY_V1,
        ).score
    )
    return {
        "quality": quality,
        "net_return": net.total_return,
        "gross_return": result.report().gross.total_return,
        "annualised_return": net.annualised_return,
        "volatility": net.annualised_volatility,
        "sharpe": net.sharpe_ratio,
        "max_drawdown": net.drawdown.depth,
        "costs_eur": result.backtest.total_cost,
        "traded_value_eur": math.fsum(float(value) for value in fills["traded_value"]),
        "average_exposure": exposure,
        "cash_share": 1.0 - exposure,
        "rejects": float(len(result.rejects())),
        "missing_data_decisions": (
            None if missing_data_decisions is None else float(missing_data_decisions)
        ),
        "beta_vs_sa1": relative.beta,
        "alpha_vs_sa1": relative.alpha_annualised,
    }


def save_outputs(
    output: Path,
    table: pd.DataFrame,
    results: Mapping[str, StrategyResult],
    decisions: pd.DataFrame,
) -> list[Path]:
    """Write the summary, the curves, ML1's tables and its decisions; return the paths."""
    output.mkdir(parents=True, exist_ok=True)
    book = results[ML1]
    equity = pd.DataFrame({name: result.equity() for name, result in results.items()})
    tables = {
        "summary.csv": table,
        "equity.csv": equity.rename_axis("session_date"),
        "weights.csv": book.weights(),
        "fills.csv": book.fills(),
        "rejects.csv": book.rejects(),
        "neural_decisions.csv": decisions,
    }
    written: list[Path] = []
    for name, frame in tables.items():
        frame.to_csv(output / name, index=name in ("summary.csv", "equity.csv", "weights.csv"))
        written.append(output / name)
    return written


def main(arguments: Sequence[str] | None = None) -> int:
    """Prepare the model, run the final test and the references, print and write."""
    parser = argparse.ArgumentParser(description="Calibrate and test ML1, the neural allocation.")
    parser.add_argument("--output", type=Path, default=Path("results/ml1"))
    parser.add_argument("--store", type=Path, default=STORE)
    parser.add_argument("--artifacts", type=Path, default=Path("artifacts/neural/world_vix"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--cost-multiplier", type=float, default=1.0)
    parser.add_argument(
        "--calibrate-only",
        action="store_true",
        help="train and select the model, print its validation, and leave the test unread",
    )
    options = parser.parse_args(arguments)

    config = neural_config(options.seed)
    runner = build_runner(options.store, options.cost_multiplier)
    variant = f"seed{options.seed}_costs_x{options.cost_multiplier:g}"
    artifact_dir = options.artifacts / variant
    print(f"preparing {ML1} in {artifact_dir} ...", file=sys.stderr)
    artifact = prepare(config, runner, artifact_dir)
    strategy = NeuralAllocationStrategy.from_artifact(artifact)
    validate_test_period(strategy, runner, *TEST_PERIOD)

    print(f"model {artifact.model_id[:12]}, epoch {artifact.selected_epoch}")
    print(f"information cutoff {artifact.information_cutoff.isoformat()}")
    print("validation (chose the epoch; not a test):")
    print(pd.read_csv(artifact_dir / VALIDATION_METRICS_FILE).to_string(index=False))
    if options.calibrate_only:
        print("calibration only: the test period was not read")
        return 0

    results: dict[str, StrategyResult] = {}
    for name, book in {ML1: strategy, **references()}.items():
        print(f"running {name} on the test period ...", file=sys.stderr)
        results[name] = runner.run(book, TRADABLE, *TEST_PERIOD)
    decisions = neural_decisions(results[ML1], strategy)
    missing = int((decisions["reason"] == "MISSING_DATA").sum())
    benchmark, market = results[SA1].equity(), results[HELD].equity()
    table = pd.DataFrame.from_dict(
        {
            name: summary_row(
                result,
                benchmark,
                missing if name == ML1 else None,
                None if name == HELD else market,
            )
            for name, result in results.items()
        },
        orient="index",
        dtype="float64",
    ).rename_axis("book")

    first, last = benchmark.index[0], benchmark.index[-1]
    print(f"final test, {first} to {last}, {len(benchmark)} sessions, {variant}:")
    print(table.T.to_string(float_format=lambda value: f"{value:,.4f}"))
    print("actions of ML1:", decisions["action"].value_counts().to_dict())
    print("reasons of ML1:", decisions["reason"].value_counts().to_dict())
    for path in save_outputs(options.output / variant, table, results, decisions):
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
