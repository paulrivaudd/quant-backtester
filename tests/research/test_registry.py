"""Every experiment is counted, and only a run of committed code is evidence."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from quant_backtester.backtest.runner import StrategyRunner
from quant_backtester.provenance import SourceState, SourceStatus
from quant_backtester.research.registry import (
    ExperimentRecord,
    ExperimentRegistry,
    UnrecordableRun,
    Verdict,
    record_of,
)
from quant_backtester.strategies.examples import BuyAndHold

AT = datetime(2026, 9, 26, 18, 0, tzinfo=UTC)


def a_run(runner: StrategyRunner, name: str = "ETF_EU"):
    return runner.run(BuyAndHold(instruments=(name,)), [name], "2026-09-09", "2026-09-14")


def test_a_run_becomes_one_line_that_reads_back_the_same(
    research_runner: StrategyRunner, tmp_path: Path
) -> None:
    registry = ExperimentRegistry(tmp_path / "registry.jsonl")
    result = a_run(research_runner)
    record = record_of(result, experiment_id="bh-eu", hypothesis="hold", recorded_at=AT)

    registry.register(record)

    assert registry.records() == [record]
    assert record.run_id == result.run_id
    assert record.net_return == pytest.approx(result.report().net.total_return)
    assert ExperimentRecord.from_json(record.as_json()) == record


def test_every_variant_is_counted_under_its_hypothesis_the_rejected_ones_included(
    research_runner: StrategyRunner, tmp_path: Path
) -> None:
    """The count is what tells a search from an idea."""
    registry = ExperimentRegistry(tmp_path / "registry.jsonl")
    registry.register(
        record_of(
            a_run(research_runner),
            experiment_id="bh-eu",
            hypothesis="hold",
            recorded_at=AT,
            verdict=Verdict.REJECTED,
            note="beaten by the other fund",
        )
    )
    registry.register(
        record_of(
            a_run(research_runner, "ETF_OTHER"),
            experiment_id="bh-other",
            hypothesis="hold",
            recorded_at=AT,
        )
    )

    assert registry.variants() == {"hold": 2}
    assert [record.experiment_id for record in registry.of("hold")] == ["bh-eu", "bh-other"]


@pytest.mark.parametrize(
    "state",
    [
        SourceState(SourceStatus.DIRTY, "0123456789abcdef0123456789abcdef01234567"),
        SourceState(SourceStatus.UNVERSIONED),
        SourceState.unrecorded(),
    ],
    ids=["dirty", "unversioned", "unrecorded"],
)
def test_a_run_of_uncommitted_code_is_not_evidence(
    research_runner: StrategyRunner, state: SourceState
) -> None:
    result = a_run(replace(research_runner, source=state))

    with pytest.raises(UnrecordableRun, match="committed code"):
        record_of(result, experiment_id="x", hypothesis="h", recorded_at=AT)


def test_a_judgement_says_why(research_runner: StrategyRunner) -> None:
    with pytest.raises(UnrecordableRun, match="without a reason"):
        record_of(
            a_run(research_runner),
            experiment_id="x",
            hypothesis="h",
            recorded_at=AT,
            verdict=Verdict.KEPT,
        )


def test_the_same_run_or_the_same_name_is_not_registered_twice(
    research_runner: StrategyRunner, tmp_path: Path
) -> None:
    """Twice the same run would be counted twice; a renamed one, as a new idea."""
    registry = ExperimentRegistry(tmp_path / "registry.jsonl")
    result = a_run(research_runner)
    registry.register(record_of(result, experiment_id="a", hypothesis="h", recorded_at=AT))

    with pytest.raises(UnrecordableRun, match="already registered"):
        registry.register(record_of(result, experiment_id="a", hypothesis="h", recorded_at=AT))
    with pytest.raises(UnrecordableRun, match="the run a already registered"):
        registry.register(record_of(result, experiment_id="b", hypothesis="h", recorded_at=AT))
    assert len(registry.records()) == 1


def test_two_writers_at_once_register_a_run_once(
    research_runner: StrategyRunner, tmp_path: Path
) -> None:
    """Audit N07: both read before either wrote, and variants() counted the run twice."""
    import threading

    record = record_of(a_run(research_runner), experiment_id="same", hypothesis="h", recorded_at=AT)
    start = threading.Barrier(4)
    refused: list[UnrecordableRun] = []

    def write() -> None:
        start.wait()
        try:
            ExperimentRegistry(tmp_path / "registry.jsonl").register(record)
        except UnrecordableRun as error:
            refused.append(error)

    writers = [threading.Thread(target=write) for _ in range(4)]
    for writer in writers:
        writer.start()
    for writer in writers:
        writer.join()

    registry = ExperimentRegistry(tmp_path / "registry.jsonl")
    assert len(registry.records()) == 1
    assert registry.variants() == {"h": 1}
    assert len(refused) == 3
