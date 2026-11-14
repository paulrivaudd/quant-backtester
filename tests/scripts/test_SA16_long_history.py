"""Tests of SA16's long-history scripts: the archive, its replay and the report."""

from __future__ import annotations

import io
import json
import random
from datetime import UTC, date, datetime
from pathlib import Path
from zipfile import ZipFile

import pytest
from tests.data.sources.test_world_bank import workbook

from quant_backtester.data.sources.base import ProviderResponseError
from quant_backtester.data.sources.ken_french import KenFrenchDataset, KenFrenchSource
from quant_backtester.data.sources.world_bank import WorldBankPinkSheetSource
from scripts import SA16_acquire_long_history as acquisition
from scripts import SA16_run_long_history as runner

NOW = datetime(2026, 11, 14, tzinfo=UTC)
FIRST, LAST = date(1972, 1, 1), date(2025, 6, 1)


def month_labels(first: date = FIRST) -> list[date]:
    labels, month = [], first
    while month <= LAST:
        labels.append(month)
        month = date(month.year + month.month // 12, month.month % 12 + 1, 1)
    return labels


def french_zip(dataset: KenFrenchDataset, generator: random.Random) -> bytes:
    labels = month_labels(acquisition.FRENCH_FIRST_MONTH)
    if dataset is KenFrenchDataset.FACTORS:
        rows = "".join(f"{m:%Y%m},{generator.gauss(0.6, 4.5):.2f},0,0,{0.30:.2f}\n" for m in labels)
        text = "Preamble\n\n,Mkt-RF,SMB,HML,RF\n" + rows
    else:
        names = [
            "NoDur", "Durbl", "Manuf", "Enrgy", "Chems", "BusEq",
            "Telcm", "Utils", "Shops", "Hlth", "Money", "Other",
        ]  # fmt: skip
        rows = "".join(
            f"{m:%Y%m}," + ",".join(f"{generator.gauss(1.0, 7.0):.2f}" for _ in names) + "\n"
            for m in labels
        )
        text = "Layout\n\nAverage Value Weighted Returns -- Monthly\n," + ",".join(names) + "\n"
        text += rows
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr(f"{dataset.value}.csv", text)
    return buffer.getvalue()


@pytest.fixture
def archive(tmp_path: Path) -> tuple[Path, dict]:
    """Return an archive of drawn series built by the acquisition script itself."""
    generator = random.Random(20261114)
    payloads = {
        f"{dataset.value}_CSV.zip": french_zip(dataset, generator)
        for dataset in (KenFrenchDataset.INDUSTRY_12, KenFrenchDataset.FACTORS)
    }
    price, prices = 100.0, {}
    for month in month_labels():
        price *= 1.0 + generator.gauss(0.004, 0.04)
        prices[f"{month:%Y}M{month:%m}"] = round(price, 2)
    level, lines = 100.0, ["observation_date,NASDAQCOM"]
    for month in month_labels():
        level *= 1.0 + generator.gauss(0.008, 0.06)
        lines.append(f"{month.replace(day=27)},{level:.3f}")
    gold = workbook(prices)
    study = acquisition.load_study()
    folder = tmp_path / "inputs"
    acquisition.acquire(
        folder,
        study,
        french=KenFrenchSource(
            clock=lambda: NOW, fetch_bytes=lambda url: payloads[url.rsplit("/", 1)[1]]
        ),
        pink_sheet=WorldBankPinkSheetSource(clock=lambda: NOW, fetch_bytes=lambda _url: gold),
        fetch_text=lambda _url: "\n".join(lines) + "\n",
        today=lambda: date(2025, 6, 30),
    )
    return folder, study


def test_the_archive_records_coverage_and_hashes_only(archive) -> None:
    folder, _study = archive
    coverage = json.loads((folder / "coverage.json").read_text())
    assert [entry["file"] for entry in coverage] == [
        "12_Industry_Portfolios.zip",
        "F-F_Research_Data_Factors.zip",
        "CMO-Historical-Data-Monthly.xlsx",
        "NASDAQCOM.csv",
    ]
    assert coverage[0]["first_month"] == "192607" and coverage[0]["last_month"] == "202506"
    assert coverage[2]["updated"].startswith("Updated on")
    assert coverage[3]["first_day"] == "1972-01-27"
    # Identity and coverage: no price, return or weight is recorded.
    assert not any("return" in key or "price" in key for entry in coverage for key in entry)


def test_an_existing_archive_is_refused_before_anything_is_fetched(archive) -> None:
    folder, study = archive

    def unreachable(_url: str) -> bytes:
        raise AssertionError("fetched into an existing archive")

    with pytest.raises(FileExistsError):
        acquisition.acquire(
            folder,
            study,
            french=KenFrenchSource(clock=lambda: NOW, fetch_bytes=unreachable),
        )


def test_a_failed_acquisition_leaves_no_archive_behind(tmp_path: Path) -> None:
    """Half an archive would be refused as existing by the next attempt."""
    generator = random.Random(1)
    payloads = {
        f"{dataset.value}_CSV.zip": french_zip(dataset, generator)
        for dataset in (KenFrenchDataset.INDUSTRY_12, KenFrenchDataset.FACTORS)
    }

    def refused(_url: str) -> bytes:
        raise ProviderResponseError("HTTP 403")

    folder = tmp_path / "inputs"
    with pytest.raises(ProviderResponseError):
        acquisition.acquire(
            folder,
            acquisition.load_study(),
            french=KenFrenchSource(
                clock=lambda: NOW, fetch_bytes=lambda url: payloads[url.rsplit("/", 1)[1]]
            ),
            pink_sheet=WorldBankPinkSheetSource(clock=lambda: NOW, fetch_bytes=refused),
        )
    assert not folder.exists()


def test_the_nasdaq_address_names_the_series_and_its_inclusive_range() -> None:
    url = acquisition.nasdaq_url("NASDAQCOM", date(1971, 2, 5), date(2026, 11, 14))
    assert url.endswith("id=NASDAQCOM&cosd=1971-02-05&coed=2026-11-14")


def test_an_altered_file_is_refused_at_replay(archive) -> None:
    folder, study = archive
    coverage = json.loads((folder / "coverage.json").read_text())
    (folder / "NASDAQCOM.csv").write_text("observation_date,NASDAQCOM\n1972-01-27,1\n")
    with pytest.raises(ValueError, match=r"NASDAQCOM\.csv"):
        runner.load_panel(folder, coverage, study)


@pytest.mark.slow
def test_the_study_runs_and_reports_on_drawn_series(archive, tmp_path: Path) -> None:
    """The whole chain after acquisition: replay, books, inference, reading, report."""
    folder, study = archive
    study = dict(study) | {"inference": dict(study["inference"]) | {"draws": 200}}
    coverage = json.loads((folder / "coverage.json").read_text())
    panel = runner.load_panel(folder, coverage, study)
    # The longest volatility window (24 months) before the first held month.
    assert panel.months[0] == date(1973, 1, 1)
    assert panel.months[-1] == study["replication"]["last_holding_month"]

    report = runner.study_report(panel, study)

    assert report["months"] == 523
    declared = report["books"]["declared"]
    assert set(declared) == set(runner.BOOKS)
    candidate = declared[runner.CANDIDATE]
    assert candidate["cagr_gross"] >= candidate["cagr"]
    assert report["books"]["stressed"][runner.CANDIDATE]["cagr"] <= candidate["cagr"]
    assert 0.0 < candidate["min_growth_weight"] <= candidate["max_growth_weight"] < 1.0
    # A book bought and held pays nothing and trades nothing.
    held = declared[runner.GROWTH_HELD]
    assert held["cagr_gross"] == held["cagr"] and "trades" not in held
    assert set(report["readings"]) == {runner.GROWTH_HELD, runner.NASDAQ_HELD}
    names = {"SUPPORTED_RETROSPECTIVE", "UNCERTAIN", "NOT_SUPPORTED"}
    assert {values["reading"] for values in report["readings"].values()} <= names
    assert set(report["regimes"]) == {r["name"] for r in study["regimes"]}
    assert set(report["sensitivities"]) == {
        "volatility_months=6",
        "volatility_months=24",
        "gold_variance_scale=1",
    }
    assert len(report["weights"]) == 523

    output = tmp_path / "out"
    runner.write_outputs(output, report, study, "0" * 40)
    text = (output / "study.md").read_text()
    assert "## Out of sample: 1975-01 to 2018-07 (523 months), net" in text
    assert "block6 interval" in text and "block24 interval" in text
    verdict = json.loads((output / "verdict.json").read_text())
    assert verdict["readings"] == report["readings"]
    assert (output / "metrics.csv").read_text().startswith("scope,book,measure,value\n")
