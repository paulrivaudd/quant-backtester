"""Price momentum between two exact venue-session endpoints.

Only endpoint prices enter the return; absent intermediate bars are irrelevant.
The latest expected venue close must nevertheless be known and fresh at the
UTC decision instant. Adjusted prices may contain provider restatements rather
than historical provider vintages.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from zoneinfo import ZoneInfo

from quant_backtester.data.calendars import CalendarCoverageError
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
from quant_backtester.signals.windows import LoadedWindow, load_window


@dataclass(frozen=True, slots=True)
class EndpointMomentumSignal(Signal):
    """Return ``P[t-S] / P[t-L] - 1`` on exact own-venue session dates.

    Attributes
    ----------
    signal_id : str
        Stable identifier of this endpoint rule.
    lookback_sessions, skip_recent_sessions : int
        ``L`` and ``S`` sessions before the latest expected available close,
        with ``0 <= S < L``. Internal missing prices never change those dates.
    price_basis : PriceBasis
        Adjusted closes by default; raw closes may be explicitly requested.
    bar_field : BarField
        Close only, whose availability is checked against the venue calendar.
    max_age_sessions : int
        Maximum age of the latest close on the reader's reference calendar.

    Notes
    -----
    The common freshness loader requires a minimum ``WindowSpec`` of two
    available observations. Its preliminary history-length verdict is not an
    endpoint verdict: exact dates are checked separately, and an absent
    required endpoint gives ``MISSING_INPUT``. Calendar coverage or listing
    history too short for ``L`` gives ``INSUFFICIENT_HISTORY``.

    Successful diagnostics contain exactly the old and recent endpoint dates
    and two consumed observations. Freshness describes the latest available
    anchor, including when ``S`` skips it from the return itself.
    """

    signal_id: str
    lookback_sessions: int
    skip_recent_sessions: int = 0
    price_basis: PriceBasis = PriceBasis.ADJUSTED
    bar_field: BarField = BarField.CLOSE
    max_age_sessions: int = 1

    def __post_init__(self) -> None:
        """Reject invalid counts or a price field with different availability."""
        require_identifier(self.signal_id, "signal_id")
        require_positive_int(self.lookback_sessions, "lookback_sessions")
        require_non_negative_int(self.skip_recent_sessions, "skip_recent_sessions")
        require_non_negative_int(self.max_age_sessions, "max_age_sessions")
        if self.skip_recent_sessions >= self.lookback_sessions:
            raise ValueError("skip_recent_sessions must be below lookback_sessions")
        if not isinstance(self.price_basis, PriceBasis):
            raise ValueError("price_basis must be a PriceBasis")
        if self.bar_field is not BarField.CLOSE:
            raise ValueError("endpoint momentum requires bar_field=CLOSE")

    def definition(self) -> Mapping[str, object]:
        """Describe exact endpoint selection and the separate freshness anchor."""
        return {
            "type": "EndpointMomentumSignal",
            "lookback_sessions": self.lookback_sessions,
            "skip_recent_sessions": self.skip_recent_sessions,
            "price_basis": self.price_basis.value,
            "bar_field": self.bar_field.value,
            "max_age_sessions": self.max_age_sessions,
            "window_mode": WindowMode.AVAILABLE_OBSERVATIONS.value,
            "endpoint_mode": "EXACT_VENUE_SESSION_OFFSETS",
            "endpoint_session_offsets": [self.lookback_sessions, self.skip_recent_sessions],
            "observations_consumed": 2,
            "freshness_anchor": "LATEST_EXPECTED_AVAILABLE_VENUE_CLOSE",
            "freshness_loader_observations": 2,
            "unit": SignalUnit.FRACTION.value,
        }

    def compute(self, context: SignalContext, instrument_ids: Sequence[str]) -> SignalResult:
        """Compute endpoint returns using only data available at ``context.as_of``."""
        rows: dict[str, Mapping[str, object]] = {}
        for name in instrument_ids:
            window = self._endpoints(context, name)
            value: float | None = None
            if window.status is SignalStatus.OK:
                if any(not math.isfinite(price) or price <= 0.0 for price in window.points):
                    window = replace(window, status=SignalStatus.INVALID_INPUT)
                else:
                    value = window.last / window.first - 1.0
                    if not math.isfinite(value):
                        value = None
                        window = replace(window, status=SignalStatus.INVALID_INPUT)
            rows[name] = result_row(value, window)
        return SignalResult(
            signal_id=self.signal_id,
            as_of=context.as_of,
            _frame=build_result_frame(rows),
            definition=self.definition(),
        )

    def _endpoints(self, context: SignalContext, name: str) -> LoadedWindow:
        """Check freshness, count real venue sessions and require exact prices."""
        instrument = context.instruments.get(name)
        if instrument.data_type is not DataType.BAR or instrument.calendar_id is None:
            raise ValueError("endpoint momentum requires a BAR instrument with a venue calendar")
        latest = load_window(
            context,
            name,
            spec=WindowSpec(2, WindowMode.AVAILABLE_OBSERVATIONS),
            bar_field=self.bar_field,
            basis=self.price_basis,
            max_age_sessions=self.max_age_sessions,
        )
        if latest.status not in {SignalStatus.OK, SignalStatus.INSUFFICIENT_HISTORY}:
            return latest
        if not latest.dates:
            return latest
        calendar = context.calendars.get(instrument.calendar_id)
        anchor = latest.dates[-1]
        try:
            local_day = context.as_of.astimezone(ZoneInfo(calendar.timezone)).date()
            expected = calendar.session(local_day)
            if expected is None or expected.close_utc > context.as_of:
                expected = calendar.previous_session(local_day)
        except CalendarCoverageError:
            return LoadedWindow(
                status=SignalStatus.INSUFFICIENT_HISTORY, age_sessions=latest.age_sessions
            )
        if anchor != expected.session_date:
            return LoadedWindow(status=SignalStatus.MISSING_INPUT, age_sessions=latest.age_sessions)
        old, recent = anchor, anchor
        try:
            for offset in range(1, self.lookback_sessions + 1):
                old = calendar.previous_session(old).session_date
                if offset == self.skip_recent_sessions:
                    recent = old
        except CalendarCoverageError:
            return LoadedWindow(
                status=SignalStatus.INSUFFICIENT_HISTORY,
                age_sessions=latest.age_sessions,
            )
        if not instrument.is_listed(old):
            return LoadedWindow(
                status=SignalStatus.INSUFFICIENT_HISTORY,
                age_sessions=latest.age_sessions,
            )
        series = context.series(name, self.bar_field, self.price_basis)
        dates = tuple(day for day in (old, recent) if day in series.index)
        points = tuple(float(series.loc[day]) for day in dates)
        return LoadedWindow(
            status=(SignalStatus.OK if len(dates) == 2 else SignalStatus.MISSING_INPUT),
            points=points,
            dates=dates,
            age_sessions=latest.age_sessions,
        )
