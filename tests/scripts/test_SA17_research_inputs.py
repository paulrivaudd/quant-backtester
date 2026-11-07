from pathlib import Path

import pytest
from scripts.SA17_acquire_research_inputs import acquire, acquire_ken_french
from scripts.SA17_build_nav_store import build

from quant_backtester.data.sources.ssga_nav import SsgaNavSource
from scripts import SA17_acquire_research_inputs as acquisition


def test_acquisition_never_overwrites_an_archive(tmp_path):
    marker = tmp_path / "untouched"
    marker.write_text("original")
    with pytest.raises(FileExistsError):
        acquire(tmp_path, Path("unused.toml"))
    with pytest.raises(FileExistsError):
        acquire_ken_french(tmp_path)
    assert marker.read_text() == "original"


def test_builder_cannot_write_to_original_store_or_outside_runs(tmp_path):
    with pytest.raises(ValueError, match="new runs/sa17_"):
        build(tmp_path, tmp_path / "sa17_store")


class RecordingSource(SsgaNavSource):
    """Record every address asked for; serve a page that links no NAV file."""

    def __init__(self) -> None:
        super().__init__(fetch_bytes=self._serve)
        self.urls: list[str] = []

    def _serve(self, url: str) -> bytes:
        self.urls.append(url)
        return b"<html>no workbook link here</html>"


def test_acquisition_fetches_only_through_the_adapter(tmp_path):
    # CLAUDE.md: anything outside data/ performs no network I/O.
    registry = tmp_path / "registry.toml"
    registry.write_text(
        "".join(
            f"# ISIN IE00BWBXM49{n}; fund {n}\n"
            f"# https://www.ssga.com/uk/en_gb/etfs/fund-{n}-zpd{n}-gy\n"
            for n in range(10)
        )
    )
    source = RecordingSource()
    with pytest.raises(ValueError, match="does not link expected NAV file"):
        acquire(tmp_path / "archive", registry, source)
    assert source.urls == ["https://www.ssga.com/uk/en_gb/etfs/fund-0-zpd0-gy"]
    assert "http_get" not in Path(acquisition.__file__).read_text(encoding="utf-8")
