"""A stored model: its identity is its content, and a folder that lies is refused."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("torch")

from quant_backtester.ml.artifacts import (
    MANIFEST_FILE,
    SCALER_FILE,
    WEIGHTS_FILE,
    ArtifactError,
    NeuralArtifact,
)
from quant_backtester.ml.config import NeuralStrategyConfig
from quant_backtester.ml.features import FeatureScaler


def variant(artifact: NeuralArtifact, **changes: object) -> NeuralArtifact:
    """Return an artifact with some of its parts replaced."""
    parts: dict[str, object] = {
        "config": artifact.config,
        "state": dict(artifact.state),
        "scaler": artifact.scaler,
        "information_cutoff": artifact.information_cutoff,
        "selected_epoch": artifact.selected_epoch,
        "provenance": dict(artifact.provenance),
    }
    return NeuralArtifact(**(parts | changes))  # type: ignore[arg-type]


def test_a_saved_model_reads_back_identical_and_proposes_the_same(
    neural_artifact: NeuralArtifact, tmp_path: Path
) -> None:
    folder = neural_artifact.save(tmp_path / "model")
    values = np.linspace(-1.0, 1.0, neural_artifact.config.input_size)

    loaded = NeuralArtifact.load(folder, expected=neural_artifact.config)

    assert sorted(path.name for path in folder.iterdir()) == [
        MANIFEST_FILE,
        SCALER_FILE,
        WEIGHTS_FILE,
    ]
    assert loaded.model_id == neural_artifact.model_id
    assert loaded.config == neural_artifact.config
    assert loaded.config.tradable_ids == ("ETF_EU", "ETF_OTHER")
    assert loaded.information_cutoff == neural_artifact.information_cutoff
    assert np.array_equal(loaded.scaler.mean, neural_artifact.scaler.mean)
    first, _ = neural_artifact.runtime().propose(values)
    second, _ = loaded.runtime().propose(values)
    assert np.array_equal(first, second)


def test_the_manifest_says_what_the_model_is_and_in_which_order(
    neural_artifact: NeuralArtifact, tmp_path: Path
) -> None:
    folder = neural_artifact.save(tmp_path / "model")

    manifest = json.loads((folder / MANIFEST_FILE).read_text(encoding="utf-8"))

    assert manifest["model_id"] == neural_artifact.model_id
    assert manifest["output_order"] == ["ETF_EU", "ETF_OTHER", "cash"]
    assert manifest["feature_names"] == list(neural_artifact.config.feature_names())
    assert manifest["config"]["seed"] == 42
    assert manifest["information_cutoff"] == neural_artifact.information_cutoff.isoformat()
    # Encoder 6*3+3, hidden (3*(3+6)+1)*4+4, output 4*3+3.
    assert manifest["architecture"]["parameters"] == 21 + 116 + 15


def test_the_identity_follows_the_content_and_not_the_provenance(
    neural_artifact: NeuralArtifact,
) -> None:
    moved = dict(neural_artifact.state)
    moved["output.bias"] = moved["output.bias"] + 1e-9
    size = neural_artifact.config.input_size
    later = datetime.fromisoformat("2026-09-30T21:00:00+00:00")

    assert variant(neural_artifact, provenance={"torch": "x"}).model_id == neural_artifact.model_id
    assert variant(neural_artifact, selected_epoch=9).model_id == neural_artifact.model_id
    assert variant(neural_artifact, state=moved).model_id != neural_artifact.model_id
    assert variant(neural_artifact, information_cutoff=later).model_id != neural_artifact.model_id
    assert (
        variant(neural_artifact, scaler=FeatureScaler(np.zeros(size), np.ones(size), 5.0)).model_id
        != neural_artifact.model_id
    )


def test_a_folder_is_never_written_over_with_another_model(
    neural_artifact: NeuralArtifact, tmp_path: Path
) -> None:
    folder = neural_artifact.save(tmp_path / "model")
    other = variant(
        neural_artifact,
        selected_epoch=3,
        state={name: values + 0.5 for name, values in neural_artifact.state.items()},
    )

    # The same model again is left alone; another one is refused.
    assert neural_artifact.save(folder) == folder
    with pytest.raises(ArtifactError, match="already holds"):
        other.save(folder)
    assert NeuralArtifact.load(folder).model_id == neural_artifact.model_id


def test_files_that_do_not_hash_to_the_manifest_are_refused(
    neural_artifact: NeuralArtifact, tmp_path: Path
) -> None:
    folder = neural_artifact.save(tmp_path / "model")
    np.savez(
        folder / SCALER_FILE,
        mean=neural_artifact.scaler.mean + 1.0,
        std=neural_artifact.scaler.std,
    )

    with pytest.raises(ArtifactError, match="does not hold the model its manifest names"):
        NeuralArtifact.load(folder)


def test_a_model_of_another_configuration_or_architecture_is_refused(
    neural_artifact: NeuralArtifact, tmp_path: Path
) -> None:
    folder = neural_artifact.save(tmp_path / "model")
    wider = NeuralStrategyConfig.from_definition(
        neural_artifact.config.definition() | {"hidden_width": 8}
    )

    with pytest.raises(ArtifactError, match="another configuration"):
        NeuralArtifact.load(folder, expected=wider)
    with pytest.raises(ArtifactError, match="configured architecture"):
        variant(neural_artifact, config=wider)
    with pytest.raises(FileNotFoundError):
        NeuralArtifact.load(tmp_path / "nowhere")


def test_a_cutoff_without_a_timezone_is_refused(neural_artifact: NeuralArtifact) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        variant(neural_artifact, information_cutoff=datetime(2026, 8, 31, 23, 0))


def test_the_parameters_of_an_artifact_cannot_be_edited(neural_artifact: NeuralArtifact) -> None:
    with pytest.raises(ValueError, match="read-only"):
        neural_artifact.state["output.bias"][0] = 1.0
    with pytest.raises(TypeError):
        neural_artifact.state["new"] = np.zeros(1)  # type: ignore[index]
