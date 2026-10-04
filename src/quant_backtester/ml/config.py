"""Everything a neural allocation is calibrated and run with, in one frozen record."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from datetime import date

from quant_backtester.numbers import (
    require_finite_non_negative,
    require_finite_positive,
    require_unit_fraction,
)
from quant_backtester.signals.types import (
    require_identifier,
    require_non_negative_int,
    require_positive_int,
)

_DATE_FIELDS = ("calibration_start", "validation_start", "calibration_end")
_TUPLE_FIELDS = ("feature_ids", "tradable_ids", "ma_windows", "vol_windows")


@dataclass(frozen=True, slots=True)
class NeuralStrategyConfig:
    """Periods, ordered series, transformations and training parameters of one model.

    Attributes
    ----------
    calibration_start : date
        First decision session of the training part, on the reference calendar.
    validation_start : date
        First session of the validation part. Training decisions whose label
        ends on or after it are purged.
    calibration_end : date
        Last session of the validation part, and the session the selected
        model's information stops at.
    feature_ids : tuple[str, ...]
        The series the network reads, in the order its inputs are laid out.
    tradable_ids : tuple[str, ...]
        The funds it may buy, in the order of its outputs; cash comes last.
        All of them are in ``feature_ids``.
    history_sessions : int
        Observations of each series in one input, the latest included.
    ma_windows : tuple[int, ...]
        Lengths of the moving averages the latest price is compared with.
    vol_windows : tuple[int, ...]
        Numbers of log returns each volatility is taken over.
    max_asset_weight : float
        Largest weight of one fund, a fraction of equity.
    min_asset_weight : float
        A fund's weight strictly below this is brought to zero; what is
        removed stays in cash.
    rebalance_band : float
        The book is kept when no weight, cash included, is this far from its
        target: ``0.03`` is three percentage points.
    risk_aversion : float
        ``gamma`` of ``252*mean(R) - gamma/2*252*var(R)``, the objective of
        the training and the score of the validation.
    seed : int
        Seed of the Python, NumPy and PyTorch generators before training.
    level_id : str
        The published series whose absolute level, divided by 100, is one more
        input. Required among ``feature_ids``.
    foreign_max_age_sessions : int
        Largest accepted age, in sessions of the reference calendar, of the
        latest observation of a series that is not a bar of that calendar. A
        bar of the reference calendar must be the session's own (age 0).
    annualization : int
        Sessions per year the volatilities, the objective and the score are
        scaled by.
    encoder_width, hidden_width : int
        Outputs of the shared history encoder and of the hidden layer.
    dropout : float
        Dropout probability after the hidden layer, in training only.
    clip : float
        A normalised input is clipped to ``[-clip, clip]``.
    learning_rate, weight_decay : float
        Parameters of AdamW.
    gradient_clip_norm : float
        Largest norm of the gradient of one update.
    max_epochs : int
        Largest number of passes over the training sequence.
    validation_every : int
        Epochs between two validations in the engine.
    patience : int
        Validations without improvement after which training stops.
    minimum_improvement : float
        What a validation score must gain to count as an improvement.
    minimum_training_decisions : int
        Fewest valid training decisions, after the purge, a calibration accepts.
    minimum_validation_sessions : int
        Fewest sessions of the validation part.
    minimum_valid_share : float
        Smallest share of training decisions whose inputs are valid.

    Raises
    ------
    ValueError
        If the dates are not ordered ``calibration_start < validation_start <=
        calibration_end``, a list is empty or repeats a name, a tradable fund
        or the level series is not observed, a window does not fit in the
        history, or a number is outside its range.

    Notes
    -----
    A date may be given as an ISO string; it is stored as a date. The test
    period is not here: it belongs to the run, and is checked against the
    artifact's information cutoff when the run starts.
    """

    calibration_start: date
    validation_start: date
    calibration_end: date
    feature_ids: tuple[str, ...]
    tradable_ids: tuple[str, ...]
    history_sessions: int
    ma_windows: tuple[int, ...]
    vol_windows: tuple[int, ...]
    max_asset_weight: float
    min_asset_weight: float
    rebalance_band: float
    risk_aversion: float
    seed: int
    level_id: str = "VIX"
    foreign_max_age_sessions: int = 1
    annualization: int = 252
    encoder_width: int = 8
    hidden_width: int = 16
    dropout: float = 0.10
    clip: float = 5.0
    learning_rate: float = 1e-3
    weight_decay: float = 1e-3
    gradient_clip_norm: float = 1.0
    max_epochs: int = 100
    validation_every: int = 5
    patience: int = 3
    minimum_improvement: float = 1e-4
    minimum_training_decisions: int = 1000
    minimum_validation_sessions: int = 252
    minimum_valid_share: float = 0.95

    def __post_init__(self) -> None:
        """Normalise the dates and the lists, then refuse what cannot be calibrated."""
        for name in _DATE_FIELDS:
            object.__setattr__(self, name, _as_date(getattr(self, name), name))
        for name in _TUPLE_FIELDS:
            object.__setattr__(self, name, tuple(getattr(self, name)))
        if not self.calibration_start < self.validation_start <= self.calibration_end:
            raise ValueError(
                "the periods must satisfy calibration_start < validation_start <= "
                f"calibration_end, got {self.calibration_start}, {self.validation_start}, "
                f"{self.calibration_end}"
            )
        self._require_series()
        self._require_windows()
        self._require_numbers()

    def _require_series(self) -> None:
        """Refuse lists that are empty, repeat a name or do not nest."""
        for name in ("feature_ids", "tradable_ids"):
            values: tuple[str, ...] = getattr(self, name)
            if not values:
                raise ValueError(f"{name} must name at least one series")
            for value in values:
                require_identifier(value, name)
            repeated = sorted(value for value, seen in Counter(values).items() if seen > 1)
            if repeated:
                raise ValueError(f"{name} holds {', '.join(repeated)} more than once")
        unobserved = [name for name in self.tradable_ids if name not in self.feature_ids]
        if unobserved:
            raise ValueError(
                f"{', '.join(unobserved)} is tradable and not observed: every tradable fund "
                "must be in feature_ids"
            )
        require_identifier(self.level_id, "level_id")
        if self.level_id not in self.feature_ids:
            raise ValueError(f"the level series {self.level_id} must be in feature_ids")
        if self.level_id in self.tradable_ids:
            raise ValueError(f"the level series {self.level_id} is a level, not a fund to buy")

    def _require_windows(self) -> None:
        """Refuse a window the history cannot hold."""
        require_positive_int(self.history_sessions, "history_sessions")
        for name, longest in (
            ("ma_windows", self.history_sessions),
            ("vol_windows", self.history_sessions - 1),
        ):
            windows: tuple[int, ...] = getattr(self, name)
            if not windows:
                raise ValueError(f"{name} must hold at least one window")
            if len(set(windows)) != len(windows):
                raise ValueError(f"{name} holds a window more than once: {windows}")
            for window in windows:
                require_positive_int(window, name)
                if not 2 <= window <= longest:
                    raise ValueError(
                        f"a window of {name} must be between 2 and {longest} for a history "
                        f"of {self.history_sessions} observations, got {window}"
                    )

    def _require_numbers(self) -> None:
        """Refuse a parameter outside its range."""
        require_unit_fraction(self.max_asset_weight, "max_asset_weight")
        require_finite_positive(self.max_asset_weight, "max_asset_weight")
        require_unit_fraction(self.min_asset_weight, "min_asset_weight")
        require_unit_fraction(self.rebalance_band, "rebalance_band")
        require_finite_non_negative(self.risk_aversion, "risk_aversion")
        require_non_negative_int(self.seed, "seed")
        require_non_negative_int(self.foreign_max_age_sessions, "foreign_max_age_sessions")
        for name in (
            "annualization",
            "encoder_width",
            "hidden_width",
            "max_epochs",
            "validation_every",
            "patience",
            "minimum_training_decisions",
            "minimum_validation_sessions",
        ):
            require_positive_int(getattr(self, name), name)
        require_unit_fraction(self.dropout, "dropout")
        if self.dropout >= 1.0:
            raise ValueError("dropout must be below 1: nothing would be left of the layer")
        for name in ("clip", "learning_rate", "gradient_clip_norm"):
            require_finite_positive(getattr(self, name), name)
        require_finite_non_negative(self.weight_decay, "weight_decay")
        require_finite_non_negative(self.minimum_improvement, "minimum_improvement")
        require_unit_fraction(self.minimum_valid_share, "minimum_valid_share")

    @property
    def series_count(self) -> int:
        """Return ``M``, the number of observed series."""
        return len(self.feature_ids)

    @property
    def indicator_count(self) -> int:
        """Return the indicators of one series: trends, volatilities and the age."""
        return len(self.ma_windows) + len(self.vol_windows) + 1

    @property
    def block_size(self) -> int:
        """Return the inputs of one series: its history, then its indicators."""
        return self.history_sessions + self.indicator_count

    @property
    def input_size(self) -> int:
        """Return the length of one input: every series' block, then the level."""
        return self.series_count * self.block_size + 1

    def feature_names(self) -> tuple[str, ...]:
        """Return the name of every input, in the order of the vector.

        Returns
        -------
        tuple[str, ...]
            For each series of ``feature_ids``: ``history_0`` to
            ``history_{H-1}``, one ``trend_n`` per moving average, one
            ``vol_n`` per volatility and ``age_sessions``, each prefixed by
            the series; then ``<level_id>.level``.
        """
        names: list[str] = []
        for series in self.feature_ids:
            names.extend(f"{series}.history_{index}" for index in range(self.history_sessions))
            names.extend(f"{series}.trend_{window}" for window in self.ma_windows)
            names.extend(f"{series}.vol_{window}" for window in self.vol_windows)
            names.append(f"{series}.age_sessions")
        names.append(f"{self.level_id}.level")
        return tuple(names)

    def definition(self) -> dict[str, object]:
        """Return the configuration as built-ins JSON can render, every field included."""
        plain: dict[str, object] = {}
        for item in fields(self):
            value = getattr(self, item.name)
            if isinstance(value, date):
                plain[item.name] = value.isoformat()
            elif isinstance(value, tuple):
                plain[item.name] = list(value)
            else:
                plain[item.name] = value
        return plain

    @classmethod
    def from_definition(cls, definition: Mapping[str, object]) -> NeuralStrategyConfig:
        """Return the configuration a definition was written from.

        Parameters
        ----------
        definition : Mapping[str, object]
            What :meth:`definition` returned, read back from a manifest.

        Returns
        -------
        NeuralStrategyConfig
            Equal to the one it was written from.

        Raises
        ------
        ValueError
            If a field is missing or unknown: a manifest of another version is
            not read as if it were this one.
        """
        known = {item.name for item in fields(cls)}
        missing, unknown = sorted(known - set(definition)), sorted(set(definition) - known)
        if missing or unknown:
            raise ValueError(
                f"not a NeuralStrategyConfig definition: missing {missing}, unknown {unknown}"
            )
        values = dict(definition)
        for name in _TUPLE_FIELDS:
            sequence = values[name]
            if not isinstance(sequence, Sequence) or isinstance(sequence, str):
                raise ValueError(f"{name} must be a list, got {sequence!r}")
            values[name] = tuple(sequence)
        return cls(**values)  # type: ignore[arg-type]


def _as_date(value: object, name: str) -> date:
    """Return a bound as a date, read from an ISO string if it is one."""
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            raise ValueError(f"{name} must be an ISO date, got {value!r}") from None
    if isinstance(value, date):
        return value
    raise ValueError(f"{name} must be a date or an ISO date string, got {value!r}")
