"""The input of the network, built one way for training and for a decision.

One builder turns a decision instant into a vector, and the training set is
that builder called once per past decision: there is no second, vectorised
path that could drift from the first. Everything is read through
:func:`~quant_backtester.signals.windows.load_window`, on a reader fixed at
the decision instant, so an input is made of values available at or before it
and nothing else.

Each series is described by the path of its last ``H`` observations and a few
indicators taken on them, all relative, so that a fund quoted at 30 and one
quoted at 500 give comparable inputs. Bars are adjusted closes over
consecutive sessions of their own venue; a published series is its raw last
observations, whenever they were published. The windows of two series are not
aligned on common dates and are not presented as if they were.

The normalisation is fitted on training inputs and applied unchanged
afterwards. It is here, beside the builder, because the two are one
transformation: a vector is never handed to the network without it.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

import numpy as np
from numpy.typing import NDArray

from quant_backtester.data.instruments import DataType
from quant_backtester.data.schemas import BarField
from quant_backtester.ml.config import NeuralStrategyConfig
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.types import PriceBasis, SignalStatus, WindowMode, WindowSpec
from quant_backtester.signals.windows import LoadedWindow, load_window

Vector = NDArray[np.float64]

STD_FLOOR = 1e-8
"""A training standard deviation below this divides by one instead."""

LEVEL_SCALE = 100.0
"""The absolute level input is the index divided by this: a VIX of 30 is 0.30."""


def series_block(
    points: Sequence[float],
    *,
    ma_windows: Sequence[int],
    vol_windows: Sequence[int],
    annualization: int,
) -> list[float] | None:
    """Return the history and the indicators of one series, without its age.

    Parameters
    ----------
    points : Sequence[float]
        The observations ``P[0] ... P[H-1]``, oldest first.
    ma_windows : Sequence[int]
        Lengths ``n`` of the averages, each at most ``H``.
    vol_windows : Sequence[int]
        Numbers ``n`` of log returns, each at most ``H - 1``.
    annualization : int
        Sessions per year the volatilities are scaled by.

    Returns
    -------
    list[float] | None
        ``ln(P[k] / P[0])`` for every ``k``, then ``P[H-1] / mean(last n P) -
        1`` per average, then ``sqrt(annualization) * std(last n log returns,
        ddof=1)`` per volatility. ``None`` when an observation is not a finite
        positive number: a logarithm has no meaning then, and no constant is
        added to make it have one.
    """
    if any(not math.isfinite(point) or point <= 0.0 for point in points):
        return None
    history = [math.log(point / points[0]) for point in points]
    trends = [points[-1] / (math.fsum(points[-window:]) / window) - 1.0 for window in ma_windows]
    returns = [math.log(points[index] / points[index - 1]) for index in range(1, len(points))]
    volatilities = [
        math.sqrt(annualization) * float(np.std(returns[-window:], ddof=1))
        for window in vol_windows
    ]
    return [*history, *trends, *volatilities]


@dataclass(frozen=True, slots=True)
class SeriesInput:
    """What one series contributed to an input, or why it could not.

    Attributes
    ----------
    instrument_id : str
        The series.
    status : SignalStatus
        ``OK`` when its block was built.
    first_date, last_date : date | None
        Observation dates of the window actually read, on the series' own
        calendar.
    age_sessions : int | None
        Sessions of the reference calendar between its latest observation and
        the decision.
    observations : int
        Observations read.
    """

    instrument_id: str
    status: SignalStatus
    first_date: date | None = None
    last_date: date | None = None
    age_sessions: int | None = None
    observations: int = 0


@dataclass(frozen=True, slots=True)
class FeatureVector:
    """One input of the network before normalisation, or the reason there is none.

    Attributes
    ----------
    as_of : datetime
        The decision instant every value was available at.
    values : tuple[float, ...] | None
        The input, in the order of
        :meth:`~quant_backtester.ml.config.NeuralStrategyConfig.feature_names`.
        ``None`` as soon as one series is unusable: a prediction is made on
        every required series or not at all.
    series : tuple[SeriesInput, ...]
        What each series contributed, in the order of ``feature_ids``.
    """

    as_of: datetime
    values: tuple[float, ...] | None
    series: tuple[SeriesInput, ...]

    @property
    def faulty(self) -> tuple[SeriesInput, ...]:
        """Return the series that could not be used."""
        return tuple(item for item in self.series if item.status is not SignalStatus.OK)

    @property
    def status(self) -> SignalStatus:
        """Return ``OK``, or the status of the first series that could not be used."""
        faulty = self.faulty
        return faulty[0].status if faulty else SignalStatus.OK


@dataclass(frozen=True, slots=True)
class NeuralFeatureBuilder:
    """Builds the input of one decision from the series of a configuration.

    Attributes
    ----------
    config : NeuralStrategyConfig
        The ordered series, the history length and the windows.
    """

    config: NeuralStrategyConfig

    def build(self, context: SignalContext) -> FeatureVector:
        """Return the input of the decision a context is fixed at.

        Parameters
        ----------
        context : SignalContext
            The reader of one decision instant, the registry and the calendars.

        Returns
        -------
        FeatureVector
            The vector when every series gave a complete, fresh, positive
            window; otherwise no vector and the status of each series.

        Raises
        ------
        KeyError
            If a series is not registered.
        ValueError
            If the level series is not a published series. Both are
            configuration mistakes and stop the run.
        """
        config = self.config
        if context.instruments.get(config.level_id).data_type is not DataType.LEVEL:
            raise ValueError(
                f"{config.level_id} is declared as the level series and is not a published "
                "series: its absolute level would be a price"
            )
        values: list[float] = []
        series: list[SeriesInput] = []
        level: float | None = None
        for instrument_id in config.feature_ids:
            window = self._window(context, instrument_id)
            block = None
            if window.status is SignalStatus.OK:
                block = series_block(
                    window.points,
                    ma_windows=config.ma_windows,
                    vol_windows=config.vol_windows,
                    annualization=config.annualization,
                )
            status = window.status
            if status is SignalStatus.OK and block is None:
                status = SignalStatus.INVALID_INPUT
            series.append(
                SeriesInput(
                    instrument_id=instrument_id,
                    status=status,
                    first_date=window.dates[0] if window.dates else None,
                    last_date=window.dates[-1] if window.dates else None,
                    age_sessions=window.age_sessions,
                    observations=len(window.points),
                )
            )
            if block is None or window.age_sessions is None:
                continue
            values.extend(block)
            values.append(float(window.age_sessions))
            if instrument_id == config.level_id:
                level = window.last / LEVEL_SCALE
        usable = all(item.status is SignalStatus.OK for item in series) and level is not None
        return FeatureVector(
            as_of=context.as_of,
            values=(*values, level) if usable and level is not None else None,
            series=tuple(series),
        )

    def _window(self, context: SignalContext, instrument_id: str) -> LoadedWindow:
        """Return the window of one series: adjusted bars, or raw published levels."""
        config = self.config
        instrument = context.instruments.get(instrument_id)
        if instrument.data_type is DataType.BAR:
            own_calendar = instrument.calendar_id == context.market.reference_calendar_id
            return load_window(
                context,
                instrument_id,
                spec=WindowSpec(config.history_sessions, WindowMode.CONSECUTIVE_SESSIONS),
                bar_field=BarField.CLOSE,
                basis=PriceBasis.ADJUSTED,
                max_age_sessions=0 if own_calendar else config.foreign_max_age_sessions,
            )
        return load_window(
            context,
            instrument_id,
            spec=WindowSpec(config.history_sessions, WindowMode.AVAILABLE_OBSERVATIONS),
            bar_field=BarField.CLOSE,
            basis=PriceBasis.RAW,
            max_age_sessions=config.foreign_max_age_sessions,
        )


class FeatureScaler:
    """The normalisation fitted on training inputs, applied unchanged afterwards.

    Parameters
    ----------
    mean, std : numpy.ndarray
        Per component, the mean and the population standard deviation
        (``ddof=0``) of the valid training inputs.
    clip : float
        A normalised component is clipped to ``[-clip, clip]``.

    Raises
    ------
    ValueError
        If the two arrays are not one-dimensional, of one length and finite.
    """

    __slots__ = ("clip", "mean", "std")

    def __init__(self, mean: Vector, std: Vector, clip: float) -> None:
        self.mean: Vector = np.asarray(mean, dtype=np.float64)
        self.std: Vector = np.asarray(std, dtype=np.float64)
        self.clip = float(clip)
        if self.mean.ndim != 1 or self.mean.shape != self.std.shape:
            raise ValueError(
                f"mean and std must be two vectors of one length, got shapes "
                f"{self.mean.shape} and {self.std.shape}"
            )
        if not (np.isfinite(self.mean).all() and np.isfinite(self.std).all()):
            raise ValueError("a normalisation holds a value that is not finite")

    @classmethod
    def fit(cls, inputs: Vector, clip: float) -> FeatureScaler:
        """Return the normalisation of a set of training inputs.

        Parameters
        ----------
        inputs : numpy.ndarray
            Valid training inputs, one per row. Nothing from the validation or
            the test period may be among them.
        clip : float
            Bound of a normalised component.

        Returns
        -------
        FeatureScaler
            Mean and standard deviation of each column.

        Raises
        ------
        ValueError
            If there is no row, or a value is not finite.
        """
        if inputs.ndim != 2 or inputs.shape[0] == 0:
            raise ValueError("a normalisation is fitted on at least one input")
        if not np.isfinite(inputs).all():
            raise ValueError("a normalisation is fitted on valid inputs only")
        return cls(inputs.mean(axis=0), inputs.std(axis=0, ddof=0), clip)

    def transform(self, inputs: Vector) -> tuple[Vector, int]:
        """Return inputs normalised and clipped, and how many components were clipped.

        Parameters
        ----------
        inputs : numpy.ndarray
            One input, or one per row.

        Returns
        -------
        tuple[numpy.ndarray, int]
            ``clip((x - mean) / divisor, -clip, clip)`` where the divisor is
            the training standard deviation, or one when that is below
            :data:`STD_FLOOR`; and the number of components the clip moved.

        Raises
        ------
        ValueError
            If the last dimension is not the one the normalisation was fitted
            on.
        """
        if inputs.shape[-1] != self.mean.shape[0]:
            raise ValueError(
                f"an input holds {inputs.shape[-1]} components and the normalisation was "
                f"fitted on {self.mean.shape[0]}"
            )
        divisor = np.where(self.std < STD_FLOOR, 1.0, self.std)
        scaled = (inputs - self.mean) / divisor
        clipped = int(np.count_nonzero(np.abs(scaled) > self.clip))
        return np.clip(scaled, -self.clip, self.clip), clipped
