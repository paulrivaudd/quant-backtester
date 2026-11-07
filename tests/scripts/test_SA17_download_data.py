"""SA17 acquisition: an isolated store, pinned metadata, and the existing pipeline."""

from __future__ import annotations

import hashlib
import importlib.util
import shutil
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from types import ModuleType

import pandas as pd
import pytest

from quant_backtester.data.instruments import DataType, Instrument, InstrumentRegistry
from quant_backtester.data.repository import MarketDataRepository
from quant_backtester.data.sources.base import RawDownload
from quant_backtester.data.updater import MarketDataUpdater

REPOSITORY = Path(__file__).resolve().parents[2]


def load_script() -> ModuleType:
    """Import ``scripts/SA17_download_data.py`` by its path, as the other script tests do."""
    path = REPOSITORY / "scripts" / "SA17_download_data.py"
    spec = importlib.util.spec_from_file_location("SA17_download_data", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


acquisition = load_script()
ENERGY = "SA17_ETF_ENERGY"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    metadata = acquisition.ROOT / "market_data" / "metadata"
    shutil.copytree(metadata, tmp_path / "market_data/metadata")
    for part in acquisition.REGISTRY_PARTS:
        (tmp_path / part).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(acquisition.ROOT / part, tmp_path / part)
    return tmp_path


class _Source:
    """A tiny offline Yahoo-shaped source; no external prices enter tests."""

    source_id = "YAHOO"

    def __init__(self, invalid: bool = False) -> None:
        self.invalid = invalid

    def available_from(self, instrument: Instrument) -> None:
        """Declare no provider floor."""
        return None

    def download(self, instrument: Instrument, start: date, end: date) -> RawDownload:
        """Return two invented sessions, optionally with an impossible high."""
        frame = pd.DataFrame(
            {
                "Open": [10.0, 11.0],
                "High": [8.0 if self.invalid else 12.0, 13.0],
                "Low": [9.0, 10.0],
                "Close": [11.0, 12.0],
                "Volume": [100.0, 120.0],
            },
            index=pd.DatetimeIndex(["2015-07-08", "2015-07-09"], tz="Europe/Berlin"),
        )
        return RawDownload(
            instrument.id,
            self.source_id,
            "20261102T090000Z",
            datetime(2026, 11, 2, 9, tzinfo=UTC),
            frame,
            {"start": start.isoformat(), "end_inclusive": end.isoformat()},
        )

    def download_corporate_actions(
        self, instrument: Instrument, start: date, end: date
    ) -> RawDownload:
        """Explicitly return an empty action feed for this accumulating fund."""
        return RawDownload(
            instrument.id,
            self.source_id,
            "20261102T090000Z-actions",
            datetime(2026, 11, 2, 9, tzinfo=UTC),
            pd.DataFrame(),
            {"endpoint": "actions"},
        )


def _updater(
    project: Path, monkeypatch: pytest.MonkeyPatch, *, invalid: bool = False
) -> tuple[Path, MarketDataUpdater]:
    store = acquisition.prepare_store(project / "runs/sa17_test", project)
    monkeypatch.setattr(acquisition, "YahooSource", lambda: _Source(invalid=invalid))
    return store, acquisition.build_updater(store)


@pytest.mark.parametrize(
    "relative", ["market_data", "runs/sa16_store", "runs", "research/sa17_bad"]
)
def test_existing_stores_and_non_research_paths_are_refused(project, relative):
    with pytest.raises(ValueError, match="isolated"):
        acquisition.prepare_store(project / relative, project)


def test_metadata_is_pinned_and_reuse_is_idempotent(project):
    store = acquisition.prepare_store(project / "runs/sa17_test", project)
    before = acquisition.metadata_manifest(store / "metadata")
    assert acquisition.prepare_store(store, project) == store
    assert acquisition.metadata_manifest(store / "metadata") == before
    stored = store / "metadata/instruments.toml"
    assert stored.read_bytes() == acquisition.combined_registry(project).encode("utf-8")
    registry = InstrumentRegistry.from_toml(stored)
    for instrument_id in acquisition.INSTRUMENT_IDS:
        registry.get(instrument_id)


def test_store_registry_does_not_depend_on_line_endings(project):
    part = project / acquisition.REGISTRY_PARTS[0]
    unix = acquisition.combined_registry(project)
    part.write_bytes(part.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    assert acquisition.combined_registry(project) == unix


def test_every_role_is_declared_once_with_its_existing_identifier(project):
    registry = acquisition.check_registry(project)
    assert set(acquisition.ROLES) == set(acquisition.INSTRUMENT_IDS)
    assert {acquisition.ROLES[name] for name in acquisition.SECTOR_IDS} == {"SECTOR_FUND"}
    market = registry.get("SP500TR")
    assert (market.source_symbol, market.currency, market.calendar_id) == (
        "^SP500TR",
        "USD",
        "XNYS",
    )
    assert not market.tradable
    assert registry.get("ETF_MONETARY_EUR").source_symbol == "XEON.DE"
    assert registry.get("ECB_EURUSD").data_type is DataType.LEVEL


def test_identifier_declared_twice_is_refused_before_any_store(project):
    sa17 = project / acquisition.REGISTRY_PARTS[-1]
    monetary = (project / acquisition.REGISTRY_PARTS[0]).read_text(encoding="utf-8")
    entry = monetary[monetary.index('[[instrument]]\nid = "ETF_MONETARY_EUR"') :]
    with sa17.open("a", encoding="utf-8") as stream:
        stream.write("\n" + entry)
    with pytest.raises(ValueError, match="Duplicate instrument id ETF_MONETARY_EUR"):
        acquisition.prepare_store(project / "runs/sa17_test", project)
    assert not (project / "runs/sa17_test").exists()


def test_undeclared_instrument_is_refused_before_any_store(project, monkeypatch):
    monkeypatch.setattr(acquisition, "INSTRUMENT_IDS", (*acquisition.INSTRUMENT_IDS, "NOPE"))
    with pytest.raises(KeyError, match="NOPE"):
        acquisition.prepare_store(project / "runs/sa17_test", project)
    assert not (project / "runs/sa17_test").exists()


@pytest.mark.parametrize(
    ("instrument_id", "start"),
    [
        ("SA17_ETF_ENERGY", date(2015, 7, 8)),
        ("SA17_ETF_COMMUNICATION", date(2018, 8, 16)),
        ("SP500TR", date(2014, 1, 2)),
        ("ETF_MONETARY_EUR", date(2014, 1, 2)),
        ("ECB_EURUSD", date(2014, 1, 2)),
        ("ETF_US_TECH", date(2017, 1, 2)),
        ("ETF_GOLD", date(2018, 1, 2)),
    ],
)
def test_request_start_is_the_latest_of_archive_start_and_listing(project, instrument_id, start):
    registry = acquisition.check_registry(project)
    assert acquisition.request_start(registry.get(instrument_id)) == start


def test_empty_store_reports_unknown_coverage_for_bars_and_levels(project):
    store = acquisition.prepare_store(project / "runs/sa17_test", project)
    gold, fixing = acquisition.coverage_rows(store, ["ETF_GOLD", "ECB_EURUSD"])
    assert (gold["clean_rows"], gold["stored_from"], gold["raw_fetches"]) == (0, None, 0)
    assert gold["requested_start"] == "2018-01-02"
    missing = gold["missing_sessions"]
    assert isinstance(missing, list) and missing[0] == "2018-01-02"
    assert gold["role"] == "EXTERNAL_REFERENCE"
    assert (fixing["clean_rows"], fixing["stored_from"]) == (0, None)
    assert fixing["missing_sessions"] is None
    assert fixing["contested_sessions"] == []
    assert fixing["role"] == "EUR_USD_REFERENCE_RATE"


@pytest.mark.parametrize("change_source", [False, True])
def test_policy_changes_do_not_rewrite_existing_archive(project, change_source):
    store = acquisition.prepare_store(project / "runs/sa17_test", project)
    original = (store / "metadata_sha256.json").read_bytes()
    path = (
        project / "market_data/metadata/crosscheck.toml"
        if change_source
        else store / "metadata/crosscheck.toml"
    )
    with path.open("a", encoding="utf-8") as stream:
        stream.write("\n# changed policy\n")
    with pytest.raises(ValueError, match="metadata changed"):
        acquisition.prepare_store(store, project)
    assert (store / "metadata_sha256.json").read_bytes() == original


def test_unpinned_existing_directory_is_not_adopted(project):
    store = project / "runs/sa17_test"
    store.mkdir(parents=True)
    with pytest.raises(ValueError, match="unpinned"):
        acquisition.prepare_store(store, project)


def test_pipeline_archives_invalid_data_but_does_not_publish_it(project, monkeypatch):
    store, updater = _updater(project, monkeypatch, invalid=True)
    report = updater.download(ENERGY, date(2015, 7, 8), date(2015, 7, 9))
    assert not report.valid
    repository = MarketDataRepository(store)
    assert repository.list_raw_fetches(ENERGY, "YAHOO")
    assert repository.load_bars(ENERGY).empty
    assert repository.load_checked_bars(ENERGY).empty


def test_pipeline_replay_reproduces_clean_bytes_and_reports_trailing_gap(project, monkeypatch):
    store, updater = _updater(project, monkeypatch)
    report = updater.download(ENERGY, date(2015, 7, 8), date(2015, 7, 10))
    assert report.valid
    files = sorted((store / "clean").rglob("*.parquet"))
    assert files
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    assert updater.rebuild_clean(ENERGY).valid
    assert {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in files} == before
    monkeypatch.setattr(acquisition, "CUTOFF", date(2015, 7, 10))
    row = acquisition.coverage_rows(store, [ENERGY])[0]
    assert row["clean_rows"] == 2
    assert row["missing_sessions"] == ["2015-07-10"]
    assert row["contested_sessions"] == []
    assert row["raw_fetches"] >= 1
    assert row["usable_for_sa17"] is False


def test_symlink_cannot_redirect_store_into_another_study(project):
    existing = project / "runs/sa16_store"
    existing.mkdir(parents=True)
    link = project / "runs/sa17_link"
    link.symlink_to(existing, target_is_directory=True)
    with pytest.raises(ValueError, match="isolated"):
        acquisition.prepare_store(link, project)
    assert list(existing.iterdir()) == []
