"""Realised volatility over the last available closes, each return scaled by its span.

A Xetra fund whose provider failed to serve one session has no window of 127
consecutive closes for the next 126 sessions, and a volatility asked of
consecutive sessions is then refused for half a year. That refusal is right for
a quantity defined on consecutive sessions. This signal declares another
contract, ``AVAILABLE_OBSERVATIONS``: it takes the last ``N + 1`` closes the
series holds and divides each log return by the square root of the number of
venue sessions it spans, which is the one-session volatility a return over
``k`` sessions estimates when daily returns are independent. A return that
spans more than ``max_span_sessions`` sessions makes the window
``NON_CONSECUTIVE_HISTORY``: a long hole is not filled by a scale.

Nothing is filled or interpolated: the span is counted on the venue calendar,
and the closes are the ones published at the decision instant.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from quant_backtester.data.instruments import DataType
from quant_backtester.data.schemas import BarField
from quant_backtester.signals.base import Signal, SignalResult, build_result_frame, result_row
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.types import (
    PriceBasis,
    SignalStatus,
    SignalUnit,
    WindowMode,
    WindowSpec,
    require_identifier,
    require_non_negative_int,
    require_positive_int,
)
from quant_backtester.signals.windows import load_window


@dataclass(frozen=True, slots=True)
class SpanScaledVolatilitySignal(Signal):
    """Annualised standard deviation of ``N`` span-scaled log returns.

    Attributes
    ----------
    signal_id : str
        Stable name of this estimator.
    window_returns : int
        ``N``, the number of returns; the window holds ``N + 1`` available
        closes, whatever sessions separate them.
    annualization : int
        Sessions per year the one-session deviation is scaled by, declared.
    max_span_sessions : int
        Largest number of venue sessions one return may span: ``1`` is the
        consecutive-session estimator, ``3`` accepts two missing sessions in
        a row.
    price_basis : PriceBasis
        Adjusted or raw closes, said explicitly.
    max_age_sessions : int
        Largest age of the freshest close, on the reader's reference calendar.

    Notes
    -----
    For a return ``r_i = ln(P_i / P_{i-1})`` spanning ``k_i`` sessions of the
    instrument's own calendar (``k_i = 1`` for two consecutive sessions), the
    value is ``stdev(r_i / sqrt(k_i)) * sqrt(annualization)``, the sample
    deviation (``ddof = 1``). Without a gap it equals
    ``RealizedVolatilitySignal`` on the same closes.
    """

    signal_id: str
    window_returns: int
    annualization: int
    max_span_sessions: int
    price_basis: PriceBasis = PriceBasis.ADJUSTED
    max_age_sessions: int = 1

    def __post_init__(self) -> None:
        """Reject a configuration that cannot describe a sample deviation."""
        require_identifier(self.signal_id, "signal_id")
        require_positive_int(self.window_returns, "window_returns")
        require_positive_int(self.annualization, "annualization")
        require_positive_int(self.max_span_sessions, "max_span_sessions")
        require_non_negative_int(self.max_age_sessions, "max_age_sessions")
        if self.window_returns < 2:
            raise ValueError("a sample deviation needs at least two returns")
        if not isinstance(self.price_basis, PriceBasis):
            raise ValueError("price_basis must be a PriceBasis")

    def definition(self) -> Mapping[str, object]:
        """Return every parameter that changes the number."""
        return {
            "type": "SpanScaledVolatilitySignal",
            "window_returns": self.window_returns,
            "annualization": self.annualization,
            "max_span_sessions": self.max_span_sessions,
            "logarithmic": True,
            "ddof": 1,
            "bar_field": BarField.CLOSE.value,
            "price_basis": self.price_basis.value,
            "max_age_sessions": self.max_age_sessions,
            "window_mode": WindowMode.AVAILABLE_OBSERVATIONS.value,
            "unit": SignalUnit.ANNUALIZED_VOLATILITY.value,
        }

    def compute(self, context: SignalContext, instrument_ids: Sequence[str]) -> SignalResult:
        """Compute each instrument's span-scaled volatility at ``context.as_of``."""
        rows: dict[str, Mapping[str, object]] = {}
        for name in instrument_ids:
            instrument = context.instruments.get(name)
            if instrument.data_type is not DataType.BAR or instrument.calendar_id is None:
                raise ValueError(f"{name} holds no venue sessions to count a span on")
            window = load_window(
                context,
                name,
                spec=WindowSpec(self.window_returns + 1, WindowMode.AVAILABLE_OBSERVATIONS),
                bar_field=BarField.CLOSE,
                basis=self.price_basis,
                max_age_sessions=self.max_age_sessions,
            )
            if window.status is not SignalStatus.OK:
                rows[name] = result_row(None, window)
                continue
            calendar = context.calendars.get(instrument.calendar_id)
            spans = [
                calendar.sessions_between(window.dates[index - 1], window.dates[index])
                for index in range(1, len(window.dates))
            ]
            if max(spans) > self.max_span_sessions or min(spans) < 1:
                rows[name] = result_row(
                    None, replace(window, status=SignalStatus.NON_CONSECUTIVE_HISTORY)
                )
                continue
            if any(not math.isfinite(point) or point <= 0.0 for point in window.points):
                rows[name] = result_row(None, replace(window, status=SignalStatus.INVALID_INPUT))
                continue
            scaled = [
                math.log(window.points[index] / window.points[index - 1]) / math.sqrt(span)
                for index, span in enumerate(spans, start=1)
            ]
            rows[name] = result_row(
                statistics.stdev(scaled) * math.sqrt(self.annualization), window
            )
        return SignalResult(
            signal_id=self.signal_id,
            as_of=context.as_of,
            _frame=build_result_frame(rows),
            definition=self.definition(),
        )
