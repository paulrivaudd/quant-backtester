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

from quant_backtester.data.instruments import Instrument, InstrumentRegistry
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
def project(tmp_path):
    metadata = acquisition.ROOT / "market_data" / "metadata"
    shutil.copytree(metadata, tmp_path / "market_data/metadata")
    research = tmp_path / "research" / "SA17"
    research.mkdir(parents=True)
    shutil.copyfile(acquisition.SOURCE_REGISTRY, research / "source_instruments.toml")
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
    assert len(InstrumentRegistry.from_toml(store / "metadata/instruments.toml")) == 10


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
