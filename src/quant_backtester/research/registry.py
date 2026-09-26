"""The register of every experiment run, the ones that did not work included.

A backtest that is shown is one of many that were run. Twenty variants of a
rotation, and the best of them printed, is a selection, and its Sharpe ratio
carries the selection with it: without the count of what was tried, nobody can
say how much of the figure is the idea and how much is the search. So every
experiment that is run for research is appended here - one JSON line, never
edited, never removed - whether it is kept or thrown away, and a hypothesis
can always be asked how many variants it took.

A line is a fact about a finished run: its ``run_id`` (code, data, registries
and configuration together), the strategy's fingerprint, the headline figures
and the decision made about it. Only a run of committed code is registered: a
result nobody can check out again is not evidence of anything.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

from quant_backtester.backtest.runner import StrategyResult
from quant_backtester.provenance import SourceStatus
from quant_backtester.research.hypotheses import Hypotheses, HypothesisStatus
from quant_backtester.research.journal import exclusive
from quant_backtester.signals.types import require_identifier


class Verdict(Enum):
    """What was decided about an experiment once it was run."""

    KEPT = "KEPT"
    """Carried forward: a candidate for the next stage."""

    REJECTED = "REJECTED"
    """Looked at and dropped. Still counted: it was tried."""

    PENDING = "PENDING"
    """Run, not yet judged."""


class UnrecordableRun(ValueError):
    """Raised when a run cannot be registered as evidence."""


@dataclass(frozen=True, slots=True)
class ExperimentRecord:
    """One line of the register.

    Attributes
    ----------
    experiment_id : str
        Unique name of this experiment.
    hypothesis : str
        The hypothesis it tests, shared by every variant of it: what the
        variants of a search are counted by.
    recorded_at : str
        ISO instant the line was written, passed in rather than read from a
        clock so that the register can be rebuilt by a test.
    run_id : str
        Identity of the run: code, data, registries, configuration.
    fingerprint : str
        Identity of the strategy's definition alone.
    strategy : str
        The strategy's id.
    git_commit : str
        The commit the run was produced by.
    start, end : str
        The measured period, ISO dates.
    net_return, gross_return : float
        Total returns over the period.
    sharpe_ratio, max_drawdown : float | None
        Net figures; ``None`` where the run does not support them.
    costs : float
        What execution took.
    verdict : Verdict
        What was decided about it.
    note : str
        Why - a line, required for anything but ``PENDING``.
    """

    experiment_id: str
    hypothesis: str
    recorded_at: str
    run_id: str
    fingerprint: str
    strategy: str
    git_commit: str
    start: str
    end: str
    net_return: float
    gross_return: float
    sharpe_ratio: float | None
    max_drawdown: float | None
    costs: float
    verdict: Verdict
    note: str

    def as_json(self) -> str:
        """Return the record as one canonical JSON line."""
        values = asdict(self)
        values["verdict"] = self.verdict.value
        return json.dumps(values, sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, line: str) -> ExperimentRecord:
        """Read a record back from its line."""
        values = json.loads(line)
        values["verdict"] = Verdict(values["verdict"])
        return cls(**values)


def record_of(
    result: StrategyResult,
    *,
    experiment_id: str,
    hypothesis: str,
    recorded_at: datetime,
    verdict: Verdict = Verdict.PENDING,
    note: str = "",
) -> ExperimentRecord:
    """Return the register line of a finished run.

    Parameters
    ----------
    result : StrategyResult
        The run.
    experiment_id, hypothesis : str
        Its name, and the hypothesis its variants are counted under.
    recorded_at : datetime
        Timezone-aware instant of the registration.
    verdict : Verdict
        What was decided about it; ``PENDING`` until judged.
    note : str
        Why. Required unless the verdict is ``PENDING``.

    Returns
    -------
    ExperimentRecord
        The line.

    Raises
    ------
    UnrecordableRun
        If the run was not produced by committed code - a dirty tree, no git,
        or nobody said - or a judged verdict carries no note.
    ValueError
        If a name is empty or ``recorded_at`` is naive.
    """
    require_identifier(experiment_id, "experiment_id")
    require_identifier(hypothesis, "hypothesis")
    if recorded_at.tzinfo is None:
        raise ValueError(f"recorded_at must be timezone-aware, got {recorded_at!r}")
    source = result.source
    if source.status is not SourceStatus.CLEAN or source.git_commit is None:
        raise UnrecordableRun(
            f"{experiment_id} was run from a {source.status.value} tree: only a run of "
            "committed code can be registered, since nobody could check the rest out again"
        )
    if verdict is not Verdict.PENDING and not note.strip():
        raise UnrecordableRun(f"{experiment_id} is {verdict.value} without a reason")
    net = result.report().net
    gross = result.report().gross
    return ExperimentRecord(
        experiment_id=experiment_id,
        hypothesis=hypothesis,
        recorded_at=recorded_at.isoformat(),
        run_id=result.run_id,
        fingerprint=result.fingerprint,
        strategy=result.strategy_id,
        git_commit=source.git_commit,
        start=result.start.isoformat(),
        end=result.end.isoformat(),
        net_return=net.total_return,
        gross_return=gross.total_return,
        sharpe_ratio=net.sharpe_ratio,
        max_drawdown=net.drawdown.depth,
        costs=result.report().costs.total,
        verdict=verdict,
        note=note,
    )


@dataclass(frozen=True, slots=True)
class VerdictEvent:
    """A judgement of a registered experiment, added after it and never in place of it.

    Attributes
    ----------
    experiment_id : str
        The experiment judged.
    verdict : Verdict
        ``KEPT`` or ``REJECTED``.
    note : str
        Why. Required.
    decided_at : str
        ISO instant of the judgement.
    """

    experiment_id: str
    verdict: Verdict
    note: str
    decided_at: str

    def as_json(self) -> str:
        """Return the event as one canonical JSON line."""
        values = asdict(self)
        values["verdict"] = self.verdict.value
        return json.dumps(values, sort_keys=True, separators=(",", ":"))


class ExperimentRegistry:
    """The append-only register, one JSON line per experiment, and its verdicts.

    Parameters
    ----------
    path : Path
        The register file, committed with the code. Created by the first
        registration. Verdicts are appended to ``verdicts.jsonl`` beside it.
    hypotheses : Hypotheses
        The written hypotheses. A run is filed under one of them or not at
        all, and a preregistered one must have been written by the day the
        run is registered.
    """

    def __init__(self, path: Path, hypotheses: Hypotheses) -> None:
        self.path = path
        self.hypotheses = hypotheses

    @property
    def verdicts_path(self) -> Path:
        """Return the file the verdicts are appended to."""
        return self.path.with_name("verdicts.jsonl")

    def records(self) -> list[ExperimentRecord]:
        """Return every registered experiment, in the order it was registered."""
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()
        return [ExperimentRecord.from_json(line) for line in lines if line.strip()]

    def register(self, record: ExperimentRecord) -> None:
        """Append one experiment.

        Raises
        ------
        UnrecordableRun
            If its hypothesis is not written, or is preregistered and was
            written after the run; if its ``experiment_id`` is already
            registered, or its ``run_id`` is: the same run registered twice
            would be counted twice, and an experiment renamed would be counted
            as a new idea.
        """
        try:
            hypothesis = self.hypotheses.get(record.hypothesis)
        except KeyError as error:
            raise UnrecordableRun(str(error)) from None
        recorded_on = datetime.fromisoformat(record.recorded_at).date()
        if (
            hypothesis.status is HypothesisStatus.PREREGISTERED
            and hypothesis.written_on > recorded_on
        ):
            raise UnrecordableRun(
                f"{record.experiment_id} was run on {recorded_on} and its hypothesis was "
                f"written on {hypothesis.written_on}: that is not a preregistration"
            )
        # Checked and appended under one lock: two writers that both read
        # before either wrote registered the same run twice (audit N07).
        with exclusive(self.path):
            for known in self.records():
                if known.experiment_id == record.experiment_id:
                    raise UnrecordableRun(f"{record.experiment_id} is already registered")
                if known.run_id == record.run_id:
                    raise UnrecordableRun(
                        f"{record.experiment_id} is the run {known.experiment_id} already "
                        "registered"
                    )
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(record.as_json() + "\n")

    def judge(
        self, experiment_id: str, verdict: Verdict, note: str, decided_at: datetime
    ) -> VerdictEvent:
        """Append a judgement of a registered experiment.

        Parameters
        ----------
        experiment_id : str
            The experiment.
        verdict : Verdict
            ``KEPT`` or ``REJECTED``.
        note : str
            Why - required.
        decided_at : datetime
            Timezone-aware instant of the judgement.

        Returns
        -------
        VerdictEvent
            The event appended. The experiment's own line is untouched, and
            no variant is added: a verdict is not a new run (C02).

        Raises
        ------
        UnrecordableRun
            If the experiment is not registered, the verdict is ``PENDING``,
            or the note is blank.
        """
        if decided_at.tzinfo is None:
            raise ValueError(f"decided_at must be timezone-aware, got {decided_at!r}")
        if verdict is Verdict.PENDING:
            raise UnrecordableRun("a verdict is KEPT or REJECTED; PENDING is the absence of one")
        if not note.strip():
            raise UnrecordableRun(f"{experiment_id} is judged {verdict.value} without a reason")
        if experiment_id not in {record.experiment_id for record in self.records()}:
            raise UnrecordableRun(f"{experiment_id} is not registered")
        event = VerdictEvent(experiment_id, verdict, note, decided_at.isoformat())
        with (
            exclusive(self.verdicts_path),
            self.verdicts_path.open("a", encoding="utf-8") as handle,
        ):
            handle.write(event.as_json() + "\n")
        return event

    def verdicts(self) -> list[VerdictEvent]:
        """Return every judgement, in the order it was made."""
        if not self.verdicts_path.exists():
            return []
        events = []
        for line in self.verdicts_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                values = json.loads(line)
                values["verdict"] = Verdict(values["verdict"])
                events.append(VerdictEvent(**values))
        return events

    def verdict_of(self, experiment_id: str) -> Verdict:
        """Return an experiment's standing verdict: its latest judgement, or its own."""
        judged = [event for event in self.verdicts() if event.experiment_id == experiment_id]
        if judged:
            return judged[-1].verdict
        for record in self.records():
            if record.experiment_id == experiment_id:
                return record.verdict
        raise KeyError(f"{experiment_id} is not registered")

    def variants(self) -> Mapping[str, int]:
        """Return how many experiments each hypothesis took, rejected ones included."""
        return dict(Counter(record.hypothesis for record in self.records()))

    def of(self, hypothesis: str) -> Iterator[ExperimentRecord]:
        """Yield the experiments of one hypothesis, in the order they were run."""
        return (record for record in self.records() if record.hypothesis == hypothesis)
