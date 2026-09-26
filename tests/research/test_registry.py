"""Every experiment is counted, and only a run of committed code is evidence."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from quant_backtester.backtest.runner import StrategyRunner
from quant_backtester.provenance import SourceState, SourceStatus
from quant_backtester.research.hypotheses import Hypotheses, Hypothesis, HypothesisStatus
from quant_backtester.research.registry import (
    ExperimentRecord,
    ExperimentRegistry,
    UnrecordableRun,
    Verdict,
    record_of,
)
from quant_backtester.strategies.examples import BuyAndHold

AT = datetime(2026, 9, 26, 18, 0, tzinfo=UTC)


def hypothesis(
    hypothesis_id: str,
    status: HypothesisStatus = HypothesisStatus.PREREGISTERED,
    written_on: date = date(2026, 9, 26),
) -> Hypothesis:
    """Return a written hypothesis."""
    return Hypothesis(
        hypothesis_id=hypothesis_id,
        status=status,
        written_on=written_on,
        statement="an idea",
        universe="ROTATION_TEST",
        prediction="a result",
        refutation="another result",
    )


HYPOTHESES = Hypotheses([hypothesis("hold"), hypothesis("h")])


def a_run(runner: StrategyRunner, name: str = "ETF_EU"):
    return runner.run(BuyAndHold(instruments=(name,)), [name], "2026-09-09", "2026-09-14")


def test_a_run_becomes_one_line_that_reads_back_the_same(
    research_runner: StrategyRunner, tmp_path: Path
) -> None:
    registry = ExperimentRegistry(tmp_path / "registry.jsonl", HYPOTHESES)
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
    registry = ExperimentRegistry(tmp_path / "registry.jsonl", HYPOTHESES)
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
    registry = ExperimentRegistry(tmp_path / "registry.jsonl", HYPOTHESES)
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
            ExperimentRegistry(tmp_path / "registry.jsonl", HYPOTHESES).register(record)
        except UnrecordableRun as error:
            refused.append(error)

    writers = [threading.Thread(target=write) for _ in range(4)]
    for writer in writers:
        writer.start()
    for writer in writers:
        writer.join()

    registry = ExperimentRegistry(tmp_path / "registry.jsonl", HYPOTHESES)
    assert len(registry.records()) == 1
    assert registry.variants() == {"h": 1}
    assert len(refused) == 3


def test_a_run_is_filed_under_a_written_hypothesis_or_not_at_all(
    research_runner: StrategyRunner, tmp_path: Path
) -> None:
    registry = ExperimentRegistry(tmp_path / "registry.jsonl", HYPOTHESES)
    record = record_of(
        a_run(research_runner), experiment_id="x", hypothesis="unwritten", recorded_at=AT
    )

    with pytest.raises(UnrecordableRun, match="no hypothesis"):
        registry.register(record)


def test_a_hypothesis_written_after_its_run_is_not_a_preregistration(
    research_runner: StrategyRunner, tmp_path: Path
) -> None:
    """C02: a document written today does not preregister yesterday's run."""
    late = Hypotheses([hypothesis("late", written_on=date(2026, 9, 27))])
    registry = ExperimentRegistry(tmp_path / "registry.jsonl", late)
    record = record_of(a_run(research_runner), experiment_id="x", hypothesis="late", recorded_at=AT)

    with pytest.raises(UnrecordableRun, match="not a preregistration"):
        registry.register(record)

    exploratory = Hypotheses(
        [hypothesis("late", HypothesisStatus.EXPLORATORY, written_on=date(2026, 9, 27))]
    )
    ExperimentRegistry(tmp_path / "registry.jsonl", exploratory).register(record)


def test_a_verdict_is_added_without_rewriting_the_run_or_counting_a_variant(
    research_runner: StrategyRunner, tmp_path: Path
) -> None:
    """C02: verdicts are events beside the run, never a second line for it."""
    registry = ExperimentRegistry(tmp_path / "registry.jsonl", HYPOTHESES)
    registry.register(
        record_of(a_run(research_runner), experiment_id="x", hypothesis="h", recorded_at=AT)
    )
    before = (tmp_path / "registry.jsonl").read_bytes()

    registry.judge("x", Verdict.REJECTED, "beaten by the control", AT)
    registry.judge("x", Verdict.KEPT, "reviewed again with the costs doubled", AT)

    assert (tmp_path / "registry.jsonl").read_bytes() == before
    assert registry.variants() == {"h": 1}
    assert registry.verdict_of("x") is Verdict.KEPT
    assert [event.verdict for event in registry.verdicts()] == [Verdict.REJECTED, Verdict.KEPT]


def test_a_verdict_needs_a_run_a_judgement_and_a_reason(
    research_runner: StrategyRunner, tmp_path: Path
) -> None:
    registry = ExperimentRegistry(tmp_path / "registry.jsonl", HYPOTHESES)
    registry.register(
        record_of(a_run(research_runner), experiment_id="x", hypothesis="h", recorded_at=AT)
    )

    with pytest.raises(UnrecordableRun, match="not registered"):
        registry.judge("y", Verdict.KEPT, "why", AT)
    with pytest.raises(UnrecordableRun, match="PENDING"):
        registry.judge("x", Verdict.PENDING, "why", AT)
    with pytest.raises(UnrecordableRun, match="without a reason"):
        registry.judge("x", Verdict.KEPT, " ", AT)


def test_the_committed_register_is_filed_under_the_committed_hypotheses() -> None:
    """Every line of research/registry.jsonl names a written hypothesis."""
    root = Path(__file__).resolve().parents[2] / "research"
    written = Hypotheses.from_toml(root / "hypotheses.toml")
    registry = ExperimentRegistry(root / "registry.jsonl", written)

    for record in registry.records():
        written.get(record.hypothesis)
