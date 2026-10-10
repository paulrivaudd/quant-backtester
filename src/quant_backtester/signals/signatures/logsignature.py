"""The log-signature of a path, and the feature vector a model reads at one decision.

The signature of a path is the collection of its iterated integrals; its
log-signature is the logarithm of that object in the tensor algebra - not the
logarithm of each coefficient - written in a basis of Lie brackets. Truncated
at order 3, a path of three coordinates has 14 coefficients: 3 displacements,
3 areas and 8 brackets of order 3. The displacement of time is always one and
is removed; its *interactions* - ``[1,3]``, ``[1,[1,3]]`` and the others - are
kept. 13 coefficients are left, 5 at order 2.

Nothing is reimplemented here: the coefficients come from ``esig`` with the
``roughpy`` backend, in the Hall basis that backend returns, whose keys are
checked against :data:`HALL_KEYS` at every call. ``1``, ``2`` and ``3`` are
price, volume and time. ``esig.stream2logsig`` takes the *points* of a path,
not its increments.

A truncated log-signature is a compression: it does not reconstruct the path
in general, and a model on its coefficients is not a universal approximator.

:class:`SignatureFeatureBuilder` is the one builder of calibration and of
inference: it reads through a reader fixed at one decision, so the features of
an old origin are those that were knowable then, never a window recomputed
with what is known at the end of a backtest.

``esig`` and ``roughpy`` are optional dependencies (the ``signatures`` extra),
imported when a log-signature is asked for.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Final

import numpy as np
from numpy.typing import NDArray

from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.models.garch import MissingDependency
from quant_backtester.signals.signatures.path import (
    CLASSICAL_NAMES,
    PathInputs,
    SignaturePathConfig,
    UnusablePath,
    build_signature_path,
    classical_indicators,
    load_path_inputs,
    raw_trajectory,
)
from quant_backtester.signals.types import SignalStatus

PATH_WIDTH: Final[int] = 3
"""Coordinates of a path: price, volume, time."""

TIME_KEY: Final[str] = "3"
"""The displacement of time, constant, and the only coefficient removed."""

BACKEND: Final[str] = "esig_roughpy"
"""The backend the coefficients come from, as it is recorded."""

HALL_KEYS: Final[dict[int, tuple[str, ...]]] = {
    2: ("1", "2", "3", "[1,2]", "[1,3]", "[2,3]"),
    3: (
        "1",
        "2",
        "3",
        "[1,2]",
        "[1,3]",
        "[2,3]",
        "[1,[1,2]]",
        "[1,[1,3]]",
        "[2,[1,2]]",
        "[2,[1,3]]",
        "[2,[2,3]]",
        "[3,[1,2]]",
        "[3,[1,3]]",
        "[3,[2,3]]",
    ),
}
"""The Hall basis of three letters at orders 2 and 3, in the backend's order.
A backend that answers anything else is refused: a coefficient is identified by
its key, never by its position alone, and never re-sorted."""


class BackendMismatch(RuntimeError):
    """Raised when the backend is not the one recorded, or its basis is not the expected one."""


def require_esig() -> None:
    """Raise unless ``esig`` and ``roughpy`` can be imported.

    Raises
    ------
    MissingDependency
        If either is missing: asked before a run or a calibration starts.
    """
    for package in ("esig", "roughpy"):
        if importlib.util.find_spec(package) is None:
            raise MissingDependency(
                f"log-signatures need the {package!r} package, an optional dependency: "
                "install the signatures extra (uv sync --extra signatures)"
            )


def select_backend() -> str:
    """Select the ``roughpy`` backend of ``esig`` and return its name as recorded.

    Returns
    -------
    str
        :data:`BACKEND`.

    Raises
    ------
    MissingDependency
        If the libraries are not installed.
    BackendMismatch
        If the backend selected is not ``roughpy``.

    Notes
    -----
    A process-wide setting of the library: it is set to the one value this
    project uses and checked, at the start of a run or of a calibration and
    before every computation, so that it cannot differ between two decisions.
    """
    require_esig()
    import esig

    if "roughpy" not in str(esig.get_backend()).lower():
        esig.set_backend("roughpy")
    if "roughpy" not in str(esig.get_backend()).lower():
        raise BackendMismatch(f"esig runs on {esig.get_backend()!r}, not on roughpy")
    return BACKEND


def kept_keys(depth: int) -> tuple[str, ...]:
    """Return the keys a model reads at one order: the Hall basis without the time displacement.

    Raises
    ------
    ValueError
        If the order is not 2 or 3.
    """
    if depth not in HALL_KEYS:
        raise ValueError(f"the log-signature is used at order 2 or 3, got {depth!r}")
    return tuple(key for key in HALL_KEYS[depth] if key != TIME_KEY)


def log_signature(path: NDArray[np.float64], depth: int) -> NDArray[np.float64]:
    """Return the log-signature of a path, the displacement of time removed.

    Parameters
    ----------
    path : numpy.ndarray
        The points of the path, shape ``(n, 3)`` with ``n >= 2``, finite, with
        a time coordinate that strictly increases. Points, not increments.
    depth : int
        The order of truncation, 2 or 3.

    Returns
    -------
    numpy.ndarray
        The coefficients of :func:`kept_keys`, in that order: 5 at order 2,
        13 at order 3.

    Raises
    ------
    ValueError
        If the path is not one this adapter accepts.
    BackendMismatch
        If the backend's keys or the number of coefficients are not the
        expected ones.
    MissingDependency
        If the libraries are not installed.
    """
    expected = HALL_KEYS.get(depth)
    if expected is None:
        raise ValueError(f"the log-signature is used at order 2 or 3, got {depth!r}")
    points = np.ascontiguousarray(path, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != PATH_WIDTH or points.shape[0] < 2:
        raise ValueError(f"a path is (n, {PATH_WIDTH}) points with n >= 2, got {points.shape}")
    if not np.isfinite(points).all():
        raise ValueError("a path holds a value that is not finite")
    if not bool((np.diff(points[:, 2]) > 0.0).all()):
        raise ValueError("the time coordinate of a path must strictly increase")
    select_backend()
    import esig

    keys = tuple(str(esig.logsigkeys(PATH_WIDTH, depth)).split())
    if keys != expected:
        raise BackendMismatch(f"the backend's basis at order {depth} is {keys}, not {expected}")
    values = np.asarray(esig.stream2logsig(points, depth), dtype=np.float64)
    if values.shape != (int(esig.logsigdim(PATH_WIDTH, depth)),) or len(values) != len(keys):
        raise BackendMismatch(f"the backend returned {values.shape} coefficients for {len(keys)}")
    keep = [index for index, key in enumerate(keys) if key != TIME_KEY]
    return values[keep]


class FeatureKind(Enum):
    """What representation of the window a model reads."""

    LOGSIGNATURE = "LOGSIGNATURE"
    """The log-signature of the path, the time displacement removed."""

    CLASSICAL = "CLASSICAL"
    """Nine classical indicators of the same window: the control of the representation."""

    RAW_TRAJECTORY = "RAW_TRAJECTORY"
    """The returns and the activities of each session: the control of the compression."""


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    """Which features are built, from which processes, in which order.

    Attributes
    ----------
    kind : FeatureKind
        The representation.
    path : SignaturePathConfig
        The conventions of the window, the same for every process.
    depth : int
        The order of the log-signature; ignored for the two controls.
    context_instruments : tuple[str, ...]
        The explanatory processes, in order: one block of features each,
        concatenated. Distinct from the instrument a strategy holds.

    Raises
    ------
    ValueError
        If no process is named, one is named twice, or the order is not 2 or 3.

    Notes
    -----
    Blocks are concatenated: the interactions of price, volume and time inside
    each process are there, the iterated integrals *between* two processes are
    not. A joint signature would be another representation.
    """

    kind: FeatureKind
    path: SignaturePathConfig
    depth: int
    context_instruments: tuple[str, ...]

    def __post_init__(self) -> None:
        """Reject a specification no vector can be built from."""
        object.__setattr__(self, "context_instruments", tuple(self.context_instruments))
        if not isinstance(self.kind, FeatureKind):
            raise ValueError(f"kind must be a FeatureKind, got {self.kind!r}")
        if not self.context_instruments:
            raise ValueError("name at least one process to describe")
        if len(set(self.context_instruments)) != len(self.context_instruments):
            raise ValueError("a process is named once")
        if self.depth not in HALL_KEYS:
            raise ValueError(f"the log-signature is used at order 2 or 3, got {self.depth!r}")

    def block_names(self) -> tuple[str, ...]:
        """Return the names of one process's features, unqualified."""
        if self.kind is FeatureKind.LOGSIGNATURE:
            return kept_keys(self.depth)
        if self.kind is FeatureKind.CLASSICAL:
            return CLASSICAL_NAMES
        steps = self.path.steps
        return (
            *(f"log_return_{index + 1}" for index in range(steps)),
            *(f"relative_activity_{index + 1}" for index in range(steps)),
        )

    def names(self) -> tuple[str, ...]:
        """Return every feature's name, qualified by its process: ``ETF_WORLD:[1,2]``."""
        return tuple(
            f"{instrument}:{name}"
            for instrument in self.context_instruments
            for name in self.block_names()
        )

    def definition(self) -> dict[str, object]:
        """Return the specification, serialisable; the backend is named for a log-signature."""
        described: dict[str, object] = {
            "kind": self.kind.value,
            "path": self.path.definition(),
            "context_instruments": list(self.context_instruments),
            "names": list(self.names()),
        }
        if self.kind is FeatureKind.LOGSIGNATURE:
            described.update(
                {"depth": self.depth, "backend": BACKEND, "basis": "HALL", "drop_keys": [TIME_KEY]}
            )
        return described


@dataclass(frozen=True, slots=True)
class SignatureFeatures:
    """The feature vector of one decision, or the reason there is none.

    Attributes
    ----------
    status : SignalStatus
        ``OK`` when every block was built.
    values : tuple[float, ...] | None
        The raw features, in the order of :meth:`FeatureSpec.names`. ``None``
        as soon as one block is unusable: a variant does not fall back on the
        blocks it has.
    names : tuple[str, ...]
        Their names.
    window_start, window_end : date | None
        The span of sessions read.
    age_sessions : int | None
        Age of the freshest bar read.
    reason : str | None
        What was wrong, beyond the status, with the process it came from.
    zero_volume_sessions : int
        Sessions, over every block, that traded nothing: observed zeros.
    """

    status: SignalStatus
    values: tuple[float, ...] | None
    names: tuple[str, ...]
    window_start: date | None = None
    window_end: date | None = None
    age_sessions: int | None = None
    reason: str | None = None
    zero_volume_sessions: int = 0


@dataclass(frozen=True, slots=True)
class SignatureFeatureBuilder:
    """Builds the features of one decision from the processes of a specification.

    Attributes
    ----------
    spec : FeatureSpec
        What is built, from what.
    """

    spec: FeatureSpec

    def build(self, context: SignalContext) -> SignatureFeatures:
        """Return the features of the decision a context is fixed at.

        Parameters
        ----------
        context : SignalContext
            The reader of one decision instant, the registry and the calendars.

        Returns
        -------
        SignatureFeatures
            The concatenated blocks when every process gave a complete, fresh
            and valid window; otherwise no vector, with the status and the
            reason of the first process that did not. A reference activity of
            zero or a window without any trade is ``INVALID_INPUT``.
        """
        spec = self.spec
        names = spec.names()
        values: list[float] = []
        zeros = 0
        first: PathInputs | None = None
        for instrument_id in spec.context_instruments:
            inputs = load_path_inputs(context, instrument_id, spec.path)
            first = inputs if first is None else first
            if inputs.status is not SignalStatus.OK:
                why = inputs.reason or inputs.status.value
                return _unusable(inputs, names, inputs.status, f"{instrument_id}:{why}")
            zeros += inputs.zero_volume_sessions
            try:
                values.extend(float(value) for value in self._block(inputs))
            except UnusablePath as refused:
                return _unusable(
                    inputs, names, SignalStatus.INVALID_INPUT, f"{instrument_id}:{refused.reason}"
                )
        assert first is not None
        return SignatureFeatures(
            status=SignalStatus.OK,
            values=tuple(values),
            names=names,
            window_start=first.dates[0],
            window_end=first.dates[-1],
            age_sessions=first.age_sessions,
            zero_volume_sessions=zeros,
        )

    def _block(self, inputs: PathInputs) -> Sequence[float] | NDArray[np.float64]:
        """Return one process's features from its checked inputs."""
        spec = self.spec
        series = (inputs.adjusted_closes, inputs.raw_closes, inputs.volumes)
        if spec.kind is FeatureKind.CLASSICAL:
            return classical_indicators(*series, spec.path)
        if spec.kind is FeatureKind.RAW_TRAJECTORY:
            return raw_trajectory(*series, spec.path)
        return log_signature(build_signature_path(*series, spec.path), spec.depth)


def _unusable(
    inputs: PathInputs, names: tuple[str, ...], status: SignalStatus, reason: str
) -> SignatureFeatures:
    """Return the result of a decision whose features could not be built."""
    return SignatureFeatures(
        status=status,
        values=None,
        names=names,
        window_start=inputs.dates[0] if inputs.dates else None,
        window_end=inputs.dates[-1] if inputs.dates else None,
        age_sessions=inputs.age_sessions,
        reason=reason,
    )
