"""The training set: one input per past decision, and what that decision earned.

The inputs are the ones a backtest would compute: each is built by the feature
builder on a reader fixed at that decision's own instant. The labels are the
only future values anywhere in the project, and they are read here and nowhere
else: the return of each tradable fund from the open after the decision to the
open after that, which is the first interval a decision is actually invested
over. A close-to-close return of the decision's own session would reward the
network for a move it could not have bought.

Two rules keep the future of the training period out of it. A decision is kept
only if its label ends before the validation starts - the others are purged,
before the normalisation is fitted - and every open is read on a reader fixed
at the last training session, which cannot serve a later one. The windows of
*past* observations may reach before the calibration starts or overlap the
validation's: those values were known.

Nothing is repaired. An open that is missing stops the calibration and names
the sessions; a day whose inputs are invalid is kept in the sequence, in cash.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
from numpy.typing import NDArray

from quant_backtester.analytics.comparison import BenchmarkBasis
from quant_backtester.backtest.runner import session_growth
from quant_backtester.backtest.timetable import BacktestTimetable
from quant_backtester.data.calendars import CalendarRegistry, TradingCalendar
from quant_backtester.data.instruments import DataType
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.data.schemas import BarField
from quant_backtester.ml.config import NeuralStrategyConfig
from quant_backtester.ml.features import NeuralFeatureBuilder
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.types import SignalStatus


class MissingForwardOpen(ValueError):
    """Raised when an open a label needs is absent: the calibration stops on it."""


class InsufficientCalibrationData(ValueError):
    """Raised when the periods asked for do not hold enough valid decisions."""


def purge(
    sessions: Sequence[date], calendar: TradingCalendar, boundary: date
) -> tuple[tuple[date, ...], tuple[date, ...]]:
    """Split decision sessions into those whose label ends before a boundary and the rest.

    Parameters
    ----------
    sessions : Sequence[date]
        Decision sessions, oldest first.
    calendar : TradingCalendar
        The calendar the decisions and their executions are dated on.
    boundary : date
        First day of the next part. A label ends at the open two sessions
        after its decision.

    Returns
    -------
    tuple[tuple[date, ...], tuple[date, ...]]
        The decisions kept - label ending strictly before the boundary - and
        the decisions purged.
    """
    kept: list[date] = []
    purged: list[date] = []
    for session in sessions:
        (kept if exit_session(session, calendar) < boundary else purged).append(session)
    return tuple(kept), tuple(purged)


def entry_session(decision: date, calendar: TradingCalendar) -> date:
    """Return the session a decision is executed at the open of."""
    return calendar.next_session(decision).session_date


def exit_session(decision: date, calendar: TradingCalendar) -> date:
    """Return the session at whose open the label of a decision ends."""
    return calendar.next_session(entry_session(decision, calendar)).session_date


@dataclass(frozen=True, slots=True)
class ForwardOpenReturnBuilder:
    """Reads what one unit of a fund earned from an open to the next. Training only.

    Attributes
    ----------
    reader : MarketDataReader
        The store.
    calendar : TradingCalendar
        The calendar decisions and executions are dated on.
    timetable : BacktestTimetable
        Gives the instant the opens are read at.
    """

    reader: MarketDataReader
    calendar: TradingCalendar
    timetable: BacktestTimetable

    def build(
        self, decisions: Sequence[date], instrument_ids: Sequence[str], *, known_until: date
    ) -> NDArray[np.float64]:
        """Return ``y[t, i] = O[i, t+2] / O[i, t+1] - 1`` for each decision and fund.

        Parameters
        ----------
        decisions : Sequence[date]
            Decision sessions ``t``, already purged.
        instrument_ids : Sequence[str]
            The tradable funds, in output order.
        known_until : date
            The last session whose prices the labels may use. Every open is
            read on a reader fixed at this session's decision instant, so a
            later one cannot be served.

        Returns
        -------
        numpy.ndarray
            One row per decision, one column per fund, as fractions. The
            return is that of one unit held over the interval, raw open to raw
            open: a split with its ex-date in ``(t+1, t+2]`` multiplies the
            units and a distribution adds its cash, by the convention the
            benchmark is valued with, so a split alone earns nothing.

        Raises
        ------
        ValueError
            If a label would end after ``known_until``, or on a corporate
            action the convention refuses.
        MissingForwardOpen
            If an open is absent or not positive, naming every fund and
            session. It is not replaced by a close or by a return of zero.
        """
        market = self.reader.at(self.timetable.decision_instant(known_until))
        intervals = [
            (entry_session(day, self.calendar), exit_session(day, self.calendar))
            for day in decisions
        ]
        late = [
            day for day, (_, out) in zip(decisions, intervals, strict=True) if out > known_until
        ]
        if late:
            raise ValueError(
                f"the label of {late[0]} ends after {known_until}; purge the decisions first"
            )
        returns = np.empty((len(decisions), len(instrument_ids)), dtype=np.float64)
        missing: list[str] = []
        for column, instrument_id in enumerate(instrument_ids):
            opens = market.history(instrument_id, BarField.OPEN).to_dict()
            actions = market.corporate_actions(instrument_id)
            for row, (entry, out) in enumerate(intervals):
                first, last = opens.get(entry), opens.get(out)
                absent = [
                    f"{instrument_id} {day}"
                    for day, price in ((entry, first), (out, last))
                    if price is None or not price > 0.0
                ]
                if absent or first is None or last is None:
                    missing.extend(absent)
                    continue
                inside = (actions["ex_date"] > entry) & (actions["ex_date"] <= out)
                returns[row, column] = (
                    session_growth(
                        instrument_id,
                        previous_close=float(first),
                        close=float(last),
                        events=actions.loc[inside],
                        basis=BenchmarkBasis.TOTAL_RETURN,
                    )
                    - 1.0
                )
        if missing:
            unique = sorted(set(missing))
            raise MissingForwardOpen(
                f"{len(unique)} opening price(s) needed by a label are absent: "
                f"{', '.join(unique)}. Correct the store; an open is not replaced by a close"
            )
        return returns


@dataclass(frozen=True, eq=False)
class NeuralDataset:
    """The training sequence, in time order, nothing shuffled.

    Attributes
    ----------
    decisions : tuple[date, ...]
        Decision sessions kept after the purge.
    inputs : numpy.ndarray
        One raw input per decision. A row of ``NaN`` where the inputs were
        invalid: the day stays in the sequence, forced to cash.
    valid : numpy.ndarray
        Whether each decision's inputs were usable.
    forward_returns : numpy.ndarray
        One row per decision, one column per tradable fund.
    purged : tuple[date, ...]
        Decisions of the training period whose label crossed into the
        validation.
    anomalies : tuple[tuple[date, str, str], ...]
        ``(decision, series, status)`` for every series that made an input
        invalid.
    """

    decisions: tuple[date, ...]
    inputs: NDArray[np.float64]
    valid: NDArray[np.bool_]
    forward_returns: NDArray[np.float64]
    purged: tuple[date, ...]
    anomalies: tuple[tuple[date, str, str], ...]

    @property
    def valid_share(self) -> float:
        """Return the share of decisions whose inputs were usable."""
        return float(self.valid.mean()) if len(self.decisions) else 0.0


def require_tradable_on_reference(config: NeuralStrategyConfig, reader: MarketDataReader) -> None:
    """Raise unless every series is registered and every fund can be bought.

    Parameters
    ----------
    config : NeuralStrategyConfig
        The series a model reads and the funds it buys.
    reader : MarketDataReader
        The store, for its registry and reference calendar.

    Raises
    ------
    KeyError
        If a series is not registered: it is added to the registry, not
        dropped from the model.
    ValueError
        If a tradable fund is not a tradable bar instrument of the reference
        calendar.
    """
    for instrument_id in config.feature_ids:
        reader.instruments.get(instrument_id)
    for instrument_id in config.tradable_ids:
        instrument = reader.instruments.get(instrument_id)
        if (
            not instrument.tradable
            or instrument.data_type is not DataType.BAR
            or instrument.calendar_id != reader.reference_calendar_id
        ):
            raise ValueError(
                f"{instrument_id} must be a tradable bar instrument of "
                f"{reader.reference_calendar_id} to be bought by the model"
            )


def build_training_dataset(
    config: NeuralStrategyConfig,
    reader: MarketDataReader,
    calendars: CalendarRegistry,
    timetable: BacktestTimetable,
) -> NeuralDataset:
    """Build the inputs and the labels of the training part, purged at its boundary.

    Parameters
    ----------
    config : NeuralStrategyConfig
        The periods, the series and the transformations.
    reader : MarketDataReader
        The store. Each input is built on ``reader.at`` its decision instant.
    calendars : CalendarRegistry
        The venue calendars, the reader's reference calendar among them.
    timetable : BacktestTimetable
        The decision time of the runs this model is meant for.

    Returns
    -------
    NeuralDataset
        Every decision session from ``calibration_start`` whose label ends
        before ``validation_start``.

    Raises
    ------
    InsufficientCalibrationData
        If the validation part holds too few sessions, too few training
        decisions are valid after the purge, or too small a share of them is.
        The periods asked for are not replaced by others.
    MissingForwardOpen
        If an open needed by a label is absent.
    """
    require_tradable_on_reference(config, reader)
    calendar = calendars.get(reader.reference_calendar_id)
    validation = calendar.sessions(config.validation_start, config.calibration_end)
    if len(validation) < config.minimum_validation_sessions:
        raise InsufficientCalibrationData(
            f"the validation part holds {len(validation)} session(s) and "
            f"{config.minimum_validation_sessions} are required"
        )
    training = [
        session.session_date
        for session in calendar.sessions(
            config.calibration_start, config.validation_start - timedelta(days=1)
        )
    ]
    decisions, purged = purge(training, calendar, config.validation_start)
    if not decisions:
        raise InsufficientCalibrationData("no training decision is left after the purge")
    forward = ForwardOpenReturnBuilder(reader, calendar, timetable).build(
        decisions, config.tradable_ids, known_until=training[-1]
    )
    builder = NeuralFeatureBuilder(config)
    inputs = np.full((len(decisions), config.input_size), np.nan, dtype=np.float64)
    anomalies: list[tuple[date, str, str]] = []
    for row, day in enumerate(decisions):
        context = SignalContext(
            market=reader.at(timetable.decision_instant(day)),
            instruments=reader.instruments,
            calendars=calendars,
        )
        vector = builder.build(context)
        if vector.values is not None:
            inputs[row] = vector.values
        anomalies.extend(
            (day, item.instrument_id, item.status.value)
            for item in vector.series
            if item.status is not SignalStatus.OK
        )
    dataset = NeuralDataset(
        decisions=decisions,
        inputs=inputs,
        valid=np.isfinite(inputs).all(axis=1),
        forward_returns=forward,
        purged=purged,
        anomalies=tuple(anomalies),
    )
    valid = int(dataset.valid.sum())
    if valid < config.minimum_training_decisions:
        raise InsufficientCalibrationData(
            f"{valid} training decision(s) have valid inputs after the purge and "
            f"{config.minimum_training_decisions} are required"
        )
    if dataset.valid_share < config.minimum_valid_share:
        raise InsufficientCalibrationData(
            f"{dataset.valid_share:.1%} of the training decisions have valid inputs and "
            f"{config.minimum_valid_share:.0%} is required; first anomalies: {anomalies[:5]}"
        )
    return dataset
