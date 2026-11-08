"""Tests of the SA17 study store builder: its registry entries and its refusals."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, time
from pathlib import Path

import pandas as pd
import pytest

from quant_backtester.data.instruments import AssetType, DataType, InstrumentRegistry
from scripts import SA17_build_study_store as builder

RECORD = {
    "isin": "IE00BWBXM492",
    "ticker": "zpde-gy",
    "first_observation": "2015-07-07",
}


def registry_of(tmp_path: Path, text: str) -> InstrumentRegistry:
    path = tmp_path / "instruments.toml"
    path.write_text(text, encoding="utf-8")
    return InstrumentRegistry.from_toml(path)


def test_a_nav_entry_carries_the_declared_release_and_no_floor(tmp_path: Path) -> None:
    study = builder.load_study()
    text = builder.nav_instrument_toml("SA17_ETF_ENERGY", RECORD, study["nav_publication"])
    nav = registry_of(tmp_path, text).get("SA17_NAV_ENERGY")
    assert nav.data_type is DataType.LEVEL
    assert not nav.tradable
    assert nav.currency == "USD"
    assert nav.first_session == date(2015, 7, 7)
    rule = nav.publication_rule
    assert rule is not None
    assert rule.publication_time == time(23)
    assert rule.timezone == "Europe/Paris"
    assert rule.lag_sessions == 1
    assert rule.calendar_id == "XLON"
    assert rule.not_before_utc is None


def test_the_fx_entry_is_a_non_tradable_usd_rate_released_at_the_us_close(tmp_path: Path) -> None:
    study = builder.load_study()
    text = builder.fx_instrument_toml(study["fx"], date(2015, 7, 1))
    fx = registry_of(tmp_path, text).get("SA17_FX_EURUSD_US_CLOSE")
    assert fx.asset_type is AssetType.FX
    assert fx.data_type is DataType.LEVEL
    assert fx.currency == "USD"
    assert fx.primary_source == "DUKASCOPY"
    assert fx.source_symbol == "EURUSD"
    assert not fx.tradable
    assert fx.history_basis is not None
    assert fx.history_basis.value == "RESTATED"
    rule = fx.publication_rule
    assert rule is not None
    assert (rule.publication_time, rule.timezone, rule.lag_sessions) == (
        time(16),
        "America/New_York",
        0,
    )


def table() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "observation_date": [date(2025, 11, 26), date(2025, 11, 28), date(2025, 12, 1)],
            "instant_utc": pd.to_datetime(
                ["2025-11-26T21:00Z", "2025-11-28T18:00Z", "2025-12-01T21:00Z"], utc=True
            ),
            "usd_per_eur": [1.15995, 1.16005, 1.16105],
            "bid": [1.1599, 1.1600, 1.1610],
            "ask": [1.1600, 1.1601, 1.1611],
            "bar_end_utc": pd.to_datetime(
                ["2025-11-26T21:00Z", "2025-11-28T18:00Z", "2025-12-01T21:00Z"], utc=True
            ),
        }
    )


def test_the_archived_table_serves_its_rows_inside_the_range(tmp_path: Path) -> None:
    fx = registry_of(
        tmp_path, builder.fx_instrument_toml(builder.load_study()["fx"], date(2025, 11, 26))
    ).get("SA17_FX_EURUSD_US_CLOSE")
    retrieved = datetime(2026, 11, 8, 12, tzinfo=UTC)
    source = builder.ArchivedTable(table(), retrieved, {"pair": "EURUSD", "quote": "USD_PER_EUR"})
    assert source.available_from(fx) == date(2025, 11, 26)
    raw = source.download(fx, date(2025, 11, 27), date(2025, 12, 31))
    assert [pd.Timestamp(day).date() for day in raw.frame["observation_date"]] == [
        date(2025, 11, 28),
        date(2025, 12, 1),
    ]
    assert raw.source == "DUKASCOPY"
    assert raw.retrieved_at_utc == retrieved
    assert raw.request["pair"] == "EURUSD"
    assert source.download_corporate_actions(fx, date.min, date.max) is None


def archive(tmp_path: Path, agree: bool = True, holes: bool = False) -> Path:
    folder = tmp_path / "sa17_fx_test"
    derived = folder / "derived"
    derived.mkdir(parents=True)
    path = derived / "eurusd_us_close.parquet"
    table().to_parquet(path, index=False)
    days = [
        {"date": day, "agree": True, "hourly": 1.1, "minute": 1.1, "minute_staleness_seconds": 0}
        for day in builder.fx_verification_days()
    ]
    days[-1]["agree"] = agree
    coverage = {
        "table_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "verification": {"sample": 24, "seed": 20261107, "tolerance": 1e-9, "days": days},
        "max_staleness_seconds": 300,
        "missing_months": ["2016-01"] if holes else [],
        "without_rate": [],
    }
    (derived / "coverage.json").write_text(json.dumps(coverage), encoding="utf-8")
    manifest = [
        {"retrieved_at_utc": "2026-11-08T10:00:00+00:00"},
        {"retrieved_at_utc": "2026-11-08T11:00:00+00:00"},
    ]
    (folder / "manifest.jsonl").write_text(
        "\n".join(json.dumps(row) for row in manifest) + "\n", encoding="utf-8"
    )
    return folder


def test_a_verified_table_is_read_with_its_last_retrieval(tmp_path: Path) -> None:
    frame, coverage, retrieved = builder.checked_fx_table(archive(tmp_path))
    assert len(frame) == 3
    assert coverage["verification"]["sample"] == 24
    assert retrieved == datetime(2026, 11, 8, 11, tzinfo=UTC)


def test_gate_2d_must_have_passed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="2d has not passed"):
        builder.checked_fx_table(archive(tmp_path, agree=False))


def test_verification_dates_match_the_acquisition() -> None:
    from scripts import SA17_acquire_fx as acquisition

    expected = acquisition.sample(acquisition.xnys().sessions(acquisition.START, acquisition.END))
    assert builder.fx_verification_days() == [day.session_date.isoformat() for day in expected]
    design = json.loads((builder.ROOT / "research/SA17/fx_verification.json").read_text())
    assert design["seed"] == acquisition.SAMPLE_SEED
    assert design["sample"] == acquisition.SAMPLE_SIZE
    assert design["range"] == [acquisition.START.isoformat(), acquisition.END.isoformat()]
    assert design["tolerance"] == acquisition.TOLERANCE
    assert design["max_staleness_seconds"] == acquisition.MAX_STALENESS.total_seconds()


def test_archive_refuses_missing_observation_dates(tmp_path: Path) -> None:
    fx = registry_of(
        tmp_path, builder.fx_instrument_toml(builder.load_study()["fx"], date(2025, 11, 26))
    ).get("SA17_FX_EURUSD_US_CLOSE")
    frame = table()
    frame.loc[0, "observation_date"] = pd.NaT
    source = builder.ArchivedTable(frame, datetime(2026, 11, 8, tzinfo=UTC), {})
    with pytest.raises(ValueError, match="observation date is missing"):
        source.available_from(fx)


@pytest.mark.parametrize("fault", ["empty", "short", "duplicate", "wrong_date", "seed"])
def test_gate_refuses_an_unprescribed_sample(tmp_path: Path, fault: str) -> None:
    folder = archive(tmp_path)
    path = folder / "derived/coverage.json"
    coverage = json.loads(path.read_text())
    verification = coverage["verification"]
    if fault == "empty":
        verification.update(sample=0, days=[])
    elif fault == "short":
        verification["days"].pop()
        verification["sample"] = 23
    elif fault == "duplicate":
        verification["days"][-1] = verification["days"][0]
    elif fault == "wrong_date":
        verification["days"][0]["date"] = "2000-01-03"
    else:
        verification["seed"] += 1
    path.write_text(json.dumps(coverage))
    with pytest.raises(ValueError, match="verification design mismatch"):
        builder.checked_fx_table(folder)


@pytest.mark.parametrize("field,value", [("tolerance", 1e-3), ("max_staleness_seconds", 3600)])
def test_gate_refuses_loosened_limits(tmp_path: Path, field: str, value: float) -> None:
    folder = archive(tmp_path)
    path = folder / "derived/coverage.json"
    coverage = json.loads(path.read_text())
    target = coverage["verification"] if field == "tolerance" else coverage
    target[field] = value
    path.write_text(json.dumps(coverage))
    with pytest.raises(ValueError, match="verification design mismatch"):
        builder.checked_fx_table(folder)


@pytest.mark.parametrize(
    "field,value",
    [
        ("minute", 1.2),
        ("hourly", None),
        ("minute", float("nan")),
        ("hourly", float("inf")),
        ("minute", "1.1"),
        ("minute", True),
        ("minute_staleness_seconds", 301),
        ("minute_staleness_seconds", -1),
    ],
)
def test_gate_recomputes_evidence_despite_agree_true(
    tmp_path: Path, field: str, value: object
) -> None:
    folder = archive(tmp_path)
    path = folder / "derived/coverage.json"
    coverage = json.loads(path.read_text())
    coverage["verification"]["days"][0][field] = value
    path.write_text(json.dumps(coverage))
    with pytest.raises(ValueError, match="invalid verification values"):
        builder.checked_fx_table(folder)


def test_a_table_with_holes_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="holes"):
        builder.checked_fx_table(archive(tmp_path, holes=True))


def test_an_altered_table_is_refused(tmp_path: Path) -> None:
    folder = archive(tmp_path)
    table().iloc[:2].to_parquet(folder / "derived" / "eurusd_us_close.parquet", index=False)
    with pytest.raises(ValueError, match="hash"):
        builder.checked_fx_table(folder)


def test_an_existing_or_misplaced_store_is_refused(tmp_path: Path) -> None:
    study = builder.load_study()
    with pytest.raises(ValueError, match="runs/sa17_study_"):
        builder.build(tmp_path / "sa17_study_x", study)
    with pytest.raises(ValueError, match="runs/sa17_study_"):
        builder.build(builder.ROOT / "runs" / "elsewhere", study)
