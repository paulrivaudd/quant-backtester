"""The SA17 mechanism study script, end to end on a synthetic archive."""

from __future__ import annotations

import hashlib
import io
import json
from datetime import date
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pytest
from scripts.SA17_run_mechanism_study import study

from quant_backtester.data.sources.ken_french import KenFrenchDataset
from quant_backtester.provenance import SourceState, SourceStatus

MONTHS = [f"{1926 + (6 + i) // 12}{(6 + i) % 12 + 1:02d}" for i in range(66)]  # 1926-07..1931-12


def zipped(text: str, dataset: KenFrenchDataset) -> bytes:
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr(f"{dataset.value}.csv", text)
    return buffer.getvalue()


def industry_text(count: int, generator: np.random.Generator) -> str:
    header = "," + ",".join(f"I{i}" for i in range(count)) + "\n"
    rows = "".join(
        month + "," + ",".join(f"{value:.2f}" for value in generator.normal(0.8, 5.0, count)) + "\n"
        for month in MONTHS
    )
    return "Synthetic\n\nAverage Value Weighted Returns -- Monthly\n" + header + rows


def factor_text(generator: np.random.Generator) -> str:
    rows = "".join(
        f"{month},{generator.normal(0.6, 4.5):.2f},0.00,0.00,{generator.uniform(0, 0.4):.2f}\n"
        for month in MONTHS
    )
    return "Preamble\n\n,Mkt-RF,SMB,HML,RF\n" + rows


def write_archive(folder: Path) -> Path:
    generator = np.random.default_rng(20261107)
    folder.mkdir()
    coverage = []
    for dataset, text in (
        (KenFrenchDataset.INDUSTRY_10, industry_text(10, generator)),
        (KenFrenchDataset.INDUSTRY_49, industry_text(49, generator)),
        (KenFrenchDataset.FACTORS, factor_text(generator)),
    ):
        payload = zipped(text, dataset)
        (folder / f"{dataset.value}.zip").write_bytes(payload)
        coverage.append(
            {
                "dataset": dataset.value,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "retrieved_at_utc": "2026-11-07T16:01:15.882294+00:00",
                "first_month": MONTHS[0],
                "last_month": MONTHS[-1],
                "history_basis": "RESTATED",
            }
        )
    (folder / "coverage.json").write_text(json.dumps(coverage))
    return folder


CONFIG = {
    "first_holding_month": date(1929, 7, 1),
    "last_holding_month": date(1931, 12, 1),
    "score": {"estimation_months": 36, "score_months": 11, "skip_months": 1},
    "universes": {
        "INDUSTRY_10": {"role": "primary", "held": 3},
        "INDUSTRY_49": {"role": "robustness", "held": 15},
    },
    "costs": {"declared_rate": 0.001, "stress_multiplier": 2.0},
    "inference": {
        "seed": 20261107,
        "draws": 100,
        "level": 0.95,
        "mean_block_months": 3,
        "sensitivity_mean_block_months": [2, 6],
        "alpha": 0.05,
        "family": ["C1_MOMENTUM_12_1", "C2_EQUAL_WEIGHT"],
        "periods_per_year": 12,
    },
    "regimes": [
        {"name": "early", "first": date(1929, 7, 1), "last": date(1930, 12, 1)},
        {"name": "late", "first": date(1931, 1, 1), "last": date(1931, 12, 1)},
    ],
}
CLEAN = SourceState(SourceStatus.CLEAN, "a" * 40)


def test_the_study_writes_its_report_and_the_same_bytes_twice(tmp_path: Path) -> None:
    archive = write_archive(tmp_path / "archive")
    report = study(archive, CONFIG, tmp_path / "first", CLEAN, "c" * 64)
    study(archive, CONFIG, tmp_path / "second", CLEAN, "c" * 64)

    names = sorted(path.name for path in (tmp_path / "first").iterdir())
    assert names == [
        "books_INDUSTRY_10.csv",
        "books_INDUSTRY_49.csv",
        "metrics.csv",
        "study.md",
        "verdict.json",
        "weights_INDUSTRY_10.csv",
        "weights_INDUSTRY_49.csv",
    ]
    for name in names:
        assert (tmp_path / "first" / name).read_bytes() == (tmp_path / "second" / name).read_bytes()

    primary = report["universes"]["INDUSTRY_10"]
    assert primary["formations"] == 30
    for control in ("C1_MOMENTUM_12_1", "C2_EQUAL_WEIGHT"):
        assert primary["comparisons"][control]["verdict"] in {
            "SUPPORTED_RETROSPECTIVE",
            "UNCERTAIN",
            "NOT_SUPPORTED",
        }
        assert set(primary["comparisons"][control]["bootstrap"]) == {
            f"{statistic}/block{block}"
            for statistic in ("SHARPE", "MEAN_RETURN")
            for block in (3, 2, 6)
        }
    # The robustness universe is reported and carries no verdict.
    assert all(
        "verdict" not in comparison
        for comparison in report["universes"]["INDUSTRY_49"]["comparisons"].values()
    )
    assert report["provenance"]["git_commit"] == "a" * 40
    assert "## Verdicts" in (tmp_path / "first" / "study.md").read_text()


def test_the_study_never_writes_over_a_folder(tmp_path: Path) -> None:
    archive = write_archive(tmp_path / "archive")
    (tmp_path / "taken").mkdir()
    with pytest.raises(FileExistsError):
        study(archive, CONFIG, tmp_path / "taken", CLEAN, "c" * 64)


def test_bytes_that_differ_from_the_archive_record_are_refused(tmp_path: Path) -> None:
    archive = write_archive(tmp_path / "archive")
    path = archive / f"{KenFrenchDataset.FACTORS.value}.zip"
    path.write_bytes(path.read_bytes() + b"\0")
    with pytest.raises(ValueError, match="hash"):
        study(archive, CONFIG, tmp_path / "out", CLEAN, "c" * 64)
