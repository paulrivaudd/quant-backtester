"""A calibrated model as it is kept: its weights, its normalisation and what made it.

An artifact is identified by its content - the parameters, the normalisation,
the configuration and the instant its information stops at - never by where
it is stored. A path says nothing about what a file holds, and "the latest
model in this folder" is a model nobody chose.

A folder holds one artifact:

- ``weights.pt``: the network's ``state_dict``, read back with
  ``weights_only=True``;
- ``scaler.npz``: means and standard deviations, read back without pickle;
- ``manifest.json``: the configuration, the architecture, the order of the
  inputs and outputs, the information cutoff, the selected epoch, and the
  versions, data digest and code state it was calibrated with.

Loading recomputes the identity from what was read and refuses a folder whose
manifest claims another one.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType

import numpy as np
import torch
from numpy.typing import NDArray

from quant_backtester.ml.config import NeuralStrategyConfig
from quant_backtester.ml.features import FeatureScaler
from quant_backtester.ml.network import NeuralRuntime

WEIGHTS_FILE = "weights.pt"
SCALER_FILE = "scaler.npz"
MANIFEST_FILE = "manifest.json"


class ArtifactError(ValueError):
    """Raised when a stored model is not what it claims, or not the one asked for."""


@dataclass(frozen=True, eq=False)
class NeuralArtifact:
    """One calibrated network, its normalisation and its provenance.

    Attributes
    ----------
    config : NeuralStrategyConfig
        The configuration it was calibrated with.
    state : Mapping[str, numpy.ndarray]
        The parameters of the network, by name.
    scaler : FeatureScaler
        The normalisation fitted on the training inputs.
    information_cutoff : datetime
        The last instant whose information reached this model, timezone-aware.
        For a selected model, the decision instant of ``calibration_end``:
        the validation chose its epoch. A decision at or before it is refused.
        Not the date the files were written.
    selected_epoch : int
        The training epoch these parameters are from.
    provenance : Mapping[str, object]
        Library versions, the digest of the store and the state of the code
        the calibration ran with, JSON-serialisable. Recorded, not part of the
        identity: the same parameters are the same model.

    Raises
    ------
    ValueError
        If the cutoff is naive, or the parameters and the normalisation are
        not those of the configured architecture.
    """

    config: NeuralStrategyConfig
    state: Mapping[str, NDArray[np.float64]]
    scaler: FeatureScaler
    information_cutoff: datetime
    selected_epoch: int
    provenance: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Freeze the parameters and check they fit the architecture."""
        if self.information_cutoff.tzinfo is None:
            raise ValueError("information_cutoff must be a timezone-aware datetime")
        object.__setattr__(self, "information_cutoff", self.information_cutoff.astimezone(UTC))
        frozen = {}
        for name, values in self.state.items():
            copy = np.array(values, dtype=np.float64)
            copy.setflags(write=False)
            frozen[name] = copy
        object.__setattr__(self, "state", MappingProxyType(frozen))
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))
        self.runtime()

    @property
    def model_id(self) -> str:
        """Return the SHA-256 of the configuration, the cutoff, the parameters and the scaler."""
        digest = hashlib.sha256()
        header = {
            "config": self.config.definition(),
            "information_cutoff": self.information_cutoff.isoformat(),
            "clip": self.scaler.clip,
        }
        digest.update(json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        arrays = {f"state.{name}": values for name, values in self.state.items()}
        arrays["scaler.mean"], arrays["scaler.std"] = self.scaler.mean, self.scaler.std
        for name in sorted(arrays):
            values = np.ascontiguousarray(arrays[name], dtype="<f8")
            digest.update(f"{name}:{values.shape}".encode())
            digest.update(values.tobytes())
        return digest.hexdigest()

    def runtime(self) -> NeuralRuntime:
        """Return the frozen network ready for inference, built from these parameters."""
        state = {name: torch.from_numpy(values.copy()) for name, values in self.state.items()}
        try:
            return NeuralRuntime(self.config, state, self.scaler)
        except RuntimeError as error:
            raise ArtifactError(
                f"the parameters are not those of the configured architecture: {error}"
            ) from error

    def manifest(self) -> dict[str, object]:
        """Return what the folder says about this model, JSON-serialisable."""
        config = self.config
        combined = config.series_count * (config.encoder_width + config.indicator_count) + 1
        return {
            "model_id": self.model_id,
            "config": config.definition(),
            "architecture": {
                "encoder": f"Linear({config.history_sessions}, {config.encoder_width}) -> Tanh",
                "hidden": (
                    f"Linear({combined}, {config.hidden_width}) -> Tanh -> "
                    f"Dropout({config.dropout})"
                ),
                "output": (
                    f"Linear({config.hidden_width}, {len(config.tradable_ids) + 1}) -> Softmax"
                ),
                "parameters": int(sum(values.size for values in self.state.values())),
                "dtype": "float64",
            },
            "feature_names": list(config.feature_names()),
            "output_order": [*config.tradable_ids, "cash"],
            "information_cutoff": self.information_cutoff.isoformat(),
            "selected_epoch": self.selected_epoch,
            "provenance": dict(self.provenance),
        }

    def save(self, directory: Path) -> Path:
        """Write the artifact into a folder of its own.

        Parameters
        ----------
        directory : Path
            Where to write. Created if missing.

        Returns
        -------
        Path
            The folder.

        Raises
        ------
        ArtifactError
            If the folder already holds another model. The same model found
            there is left as it is.
        """
        manifest_path = directory / MANIFEST_FILE
        if manifest_path.exists():
            stored = NeuralArtifact.load(directory)
            if stored.model_id != self.model_id:
                raise ArtifactError(
                    f"{directory} already holds the model {stored.model_id[:12]}; the model "
                    f"{self.model_id[:12]} is not written over it"
                )
            return directory
        directory.mkdir(parents=True, exist_ok=True)
        torch.save(
            {name: torch.from_numpy(values.copy()) for name, values in self.state.items()},
            directory / WEIGHTS_FILE,
        )
        np.savez(directory / SCALER_FILE, mean=self.scaler.mean, std=self.scaler.std)
        manifest_path.write_text(
            json.dumps(self.manifest(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return directory

    @classmethod
    def load(cls, directory: Path, expected: NeuralStrategyConfig | None = None) -> NeuralArtifact:
        """Read an artifact back and check it is what its manifest says.

        Parameters
        ----------
        directory : Path
            The folder of one artifact, named explicitly.
        expected : NeuralStrategyConfig | None
            The configuration the caller means to run. When given, a model
            calibrated with another one is refused.

        Returns
        -------
        NeuralArtifact
            The model, its identity recomputed from the files.

        Raises
        ------
        FileNotFoundError
            If a file of the artifact is missing.
        ArtifactError
            If the content does not hash to the manifest's ``model_id``, the
            parameters do not fit the architecture, or the configuration is
            not the expected one.
        """
        manifest = json.loads((directory / MANIFEST_FILE).read_text(encoding="utf-8"))
        config = NeuralStrategyConfig.from_definition(manifest["config"])
        if expected is not None and expected != config:
            raise ArtifactError(
                f"{directory} holds a model calibrated with another configuration than the "
                "one asked for; recalibrate, or name the artifact of this configuration"
            )
        tensors = torch.load(directory / WEIGHTS_FILE, weights_only=True, map_location="cpu")
        with np.load(directory / SCALER_FILE, allow_pickle=False) as stored:
            scaler = FeatureScaler(stored["mean"], stored["std"], config.clip)
        artifact = cls(
            config=config,
            state={name: tensor.numpy() for name, tensor in tensors.items()},
            scaler=scaler,
            information_cutoff=datetime.fromisoformat(manifest["information_cutoff"]),
            selected_epoch=int(manifest["selected_epoch"]),
            provenance=manifest.get("provenance", {}),
        )
        if artifact.model_id != manifest["model_id"]:
            raise ArtifactError(
                f"{directory} does not hold the model its manifest names: the files hash to "
                f"{artifact.model_id[:12]} and the manifest says {manifest['model_id'][:12]}"
            )
        return artifact
