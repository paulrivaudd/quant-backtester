"""How a fund's returns have moved with the changes of a published series."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from quant_backtester.data.instruments import DataType
from quant_backtester.data.reader import ObservationStatus
from quant_backtester.data.schemas import BarField
from quant_backtester.signals.base import Signal, SignalResult, build_result_frame, result_row
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.level.change import require_published
from quant_backtester.signals.types import (
    PriceBasis,
    SignalStatus,
    SignalUnit,
    WindowMode,
    require_identifier,
    require_non_negative_int,
    require_positive_int,
)
from quant_backtester.signals.windows import LoadedWindow

_REFUSED = {
    ObservationStatus.NOT_LISTED: SignalStatus.NOT_LISTED,
    ObservationStatus.MISSING: SignalStatus.MISSING_INPUT,
}
"""How the reader's verdict on a freshest observation becomes this signal's."""


def correlation(first: Sequence[float], second: Sequence[float]) -> float | None:
    """Return the Pearson correlation of two samples of the same length.

    Parameters
    ----------
    first, second : Sequence[float]
        Paired values, in the same order.

    Returns
    -------
    float | None
        In ``[-1, 1]``, or ``None`` when one sample does not vary or fewer
        than two pairs are given: a correlation with a constant is not zero,
        it is undefined.

    Raises
    ------
    ValueError
        If the two samples do not hold the same number of values.
    """
    if len(first) != len(second):
        raise ValueError(f"paired samples of {len(first)} and {len(second)} values")
    count = len(first)
    if count < 2:
        return None
    mean_first = math.fsum(first) / count
    mean_second = math.fsum(second) / count
    spread_first = math.fsum((value - mean_first) ** 2 for value in first)
    spread_second = math.fsum((value - mean_second) ** 2 for value in second)
    if spread_first <= 0.0 or spread_second <= 0.0:
        return None
    together = math.fsum(
        (a - mean_first) * (b - mean_second) for a, b in zip(first, second, strict=True)
    )
    return max(-1.0, min(1.0, together / math.sqrt(spread_first * spread_second)))


@dataclass(frozen=True, slots=True)
class ReturnLevelCorrelationSignal(Signal):
    """Correlation of a fund's log returns with the changes of a published series.

    Attributes
    ----------
    signal_id : str
        Stable name, e.g. ``"sp500_us10y_corr_60p"``.
    level_id : str
        The published series - a yield, a volatility index - whose changes the
        returns are set against.
    window_pairs : int
        Number of paired moves the correlation is taken over. At least three.
    price_basis : PriceBasis
        Basis of the fund's closes. ``ADJUSTED`` keeps a dividend from being
        read as a fall on the day a yield happened to rise.
    max_age_sessions : int
        Largest accepted age of the freshest observation of **either** input,
        in sessions of the reference calendar. A yield published the day after
        it was fixed is one session old on the evening it is read.

    Raises
    ------
    ValueError
        If a name is empty, ``window_pairs`` is below three,
        ``max_age_sessions`` is not a non-negative integer, the instrument
        asked about is not a bars instrument or ``level_id`` is not a published
        series.
    KeyError
        If an instrument is not registered.

    Notes
    -----
    The window is counted in **available observations**, on the dates both
    series hold: the last ``window_pairs + 1`` of them. It cannot be counted in
    sessions in a row, because the two series do not keep the same days - the
    bond market is shut on Columbus Day and the stock market is not. Each move
    is taken between two successive common dates, on both series alike, so a
    return over a long weekend is set against the yield change over the same
    long weekend and never against one day of it. The diagnostics carry the
    first and last common date.

    The result is positive when the fund rises as the series rises. For shares
    against a yield that is the regime in which bonds hedge shares; negative is
    the one in which they fall together.
    """

    signal_id: str
    level_id: str
    window_pairs: int
    price_basis: PriceBasis
    max_age_sessions: int = 1

    def __post_init__(self) -> None:
        """Reject a configuration that cannot describe a correlation."""
        require_identifier(self.signal_id, "signal_id")
        require_identifier(self.level_id, "level_id")
        require_positive_int(self.window_pairs, "window_pairs")
        require_non_negative_int(self.max_age_sessions, "max_age_sessions")
        if self.window_pairs < 3:
            raise ValueError(
                f"window_pairs must be at least 3, got {self.window_pairs}: two pairs are "
                f"always perfectly correlated"
            )

    def definition(self) -> Mapping[str, object]:
        """Return every parameter that changes the number."""
        return {
            "type": "ReturnLevelCorrelationSignal",
            "level_id": self.level_id,
            "window_pairs": self.window_pairs,
            "price_basis": self.price_basis.value,
            "max_age_sessions": self.max_age_sessions,
            "window_mode": WindowMode.AVAILABLE_OBSERVATIONS.value,
            "unit": SignalUnit.CORRELATION.value,
        }

    def compute(self, context: SignalContext, instrument_ids: Sequence[str]) -> SignalResult:
        """Compute, for each fund, the correlation of its returns with the series' changes."""
        require_published(context, [self.level_id], type(self).__name__)
        rows: dict[str, Mapping[str, object]] = {}
        for instrument_id in instrument_ids:
            instrument = context.instruments.get(instrument_id)
            if instrument.data_type is not DataType.BAR:
                raise ValueError(
                    f"{type(self).__name__} takes the returns of a bars instrument; "
                    f"{instrument_id} is a {instrument.data_type.value} series"
                )
            window = self._paired_window(context, instrument_id)
            value = self._correlation(context, window) if window.status is SignalStatus.OK else None
            if window.status is SignalStatus.OK and value is None:
                window = LoadedWindow(
                    SignalStatus.INVALID_INPUT, window.points, window.dates, window.age_sessions
                )
            rows[instrument_id] = result_row(value, window)
        return SignalResult(
            signal_id=self.signal_id,
            as_of=context.as_of,
            _frame=build_result_frame(rows),
            definition=self.definition(),
        )

    def _paired_window(self, context: SignalContext, instrument_id: str) -> LoadedWindow:
        """Return the fund's closes on the last common dates, or why there are none."""
        ages: list[int] = []
        for name in (instrument_id, self.level_id):
            latest = context.market.values([name], BarField.CLOSE).loc[name]
            refused = _REFUSED.get(latest["status"])
            if refused is not None:
                return LoadedWindow(status=refused)
            ages.append(int(latest["age_sessions"]))
        age = max(ages)
        if age > self.max_age_sessions:
            return LoadedWindow(status=SignalStatus.STALE_INPUT, age_sessions=age)
        prices = context.series(instrument_id, BarField.CLOSE, self.price_basis)
        published = set(context.series(self.level_id, BarField.CLOSE, PriceBasis.RAW).index)
        common = [day for day in prices.index if isinstance(day, date) and day in published]
        dates = tuple(common[-(self.window_pairs + 1) :])
        points = tuple(float(prices.loc[day]) for day in dates)
        status = (
            SignalStatus.OK
            if len(dates) == self.window_pairs + 1
            else SignalStatus.INSUFFICIENT_HISTORY
        )
        return LoadedWindow(status=status, points=points, dates=dates, age_sessions=age)

    def _correlation(self, context: SignalContext, window: LoadedWindow) -> float | None:
        """Return the correlation over an ``OK`` window, or ``None`` when it has no meaning."""
        if any(point <= 0.0 for point in window.points):
            return None
        levels = context.series(self.level_id, BarField.CLOSE, PriceBasis.RAW)
        published = [float(levels.loc[day]) for day in window.dates]
        returns = [
            math.log(window.points[index] / window.points[index - 1])
            for index in range(1, len(window.points))
        ]
        changes = [published[index] - published[index - 1] for index in range(1, len(published))]
        return correlation(returns, changes)
