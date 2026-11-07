from pathlib import Path

import pytest
from scripts.SA17_acquire_research_inputs import acquire, acquire_ken_french
from scripts.SA17_build_nav_store import build


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
