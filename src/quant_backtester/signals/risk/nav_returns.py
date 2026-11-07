"""SA17 EUR risk returns on synchronized NAV observations, known at the decision.

The supplied FX series must quote USD per EUR at the NAV's US-close valuation
basis. A calendar or publication time alone cannot prove that basis; source
validation belongs to ingestion. ECB reference fixings are not this series.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date

from quant_backtester.data.instruments import AssetType, DataType
from quant_backtester.signals.base import Signal, SignalResult, build_result_frame, result_row
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.cross_asset.residual_momentum import simple_returns
from quant_backtester.signals.types import (
    PriceBasis,
    SignalStatus,
    require_identifier,
    require_positive_int,
)
from quant_backtester.signals.windows import (
    completed_month_cutoff,
    load_dated_window,
    require_previous_month_cutoff,
)


@dataclass(frozen=True, slots=True)
class NavRiskReturnsSignal(Signal):
    """Return EUR NAV returns and their exact dates for covariance estimation.

    ``value`` is the latest daily return; immutable ``returns`` and ``dates``
    diagnostic columns hold the full risk sample. Missing dates cancel the
    sample, rather than extending it backward to find enough observations.
    """

    signal_id: str
    risk_returns: int
    input_currency: str
    usd_per_eur_fx_id: str | None = None
    observation_calendar_id: str = "XNYS"
    observation_cutoff: date | None = None

    def __post_init__(self) -> None:
        """Refuse ambiguous currency conversion or an invalid window."""
        require_identifier(self.signal_id, "signal_id")
        require_identifier(self.observation_calendar_id, "observation_calendar_id")
        if self.observation_cutoff is not None and type(self.observation_cutoff) is not date:
            raise ValueError("observation_cutoff must be a date")
        if self.usd_per_eur_fx_id is not None:
            require_identifier(self.usd_per_eur_fx_id, "usd_per_eur_fx_id")
        require_positive_int(self.risk_returns, "risk_returns")
        if self.risk_returns < 2:
            raise ValueError("risk_returns must be at least two")
        if self.input_currency not in ("EUR", "USD"):
            raise ValueError("NAV risk inputs must be EUR or USD")
        if (self.input_currency == "USD") != (self.usd_per_eur_fx_id is not None):
            raise ValueError("USD risk NAV requires explicit synchronized USD-per-EUR FX")

    def definition(self) -> Mapping[str, object]:
        """Return the complete dated EUR return contract."""
        return {
            "type": "NavRiskReturnsSignal",
            "risk_returns": self.risk_returns,
            "input_currency": self.input_currency,
            "output_currency": "EUR",
            "usd_per_eur_fx_id": self.usd_per_eur_fx_id,
            "conversion": (
                "USD_NAV_DIVIDED_BY_SYNCHRONIZED_USD_PER_EUR"
                if self.input_currency == "USD"
                else "SYNCHRONIZED_EUR_NAV"
            ),
            "observation_calendar_id": self.observation_calendar_id,
            "observation_cutoff": self.observation_cutoff.isoformat()
            if self.observation_cutoff
            else "PREVIOUS_COMPLETED_MONTH",
            "window": "EXACT_EXPECTED_SESSIONS_NO_BACKFILL",
        }

    def referenced_instruments(self) -> tuple[str, ...]:
        """Return the FX series every NAV is converted with, read beside them."""
        return () if self.usd_per_eur_fx_id is None else (self.usd_per_eur_fx_id,)

    def compute(self, context: SignalContext, instrument_ids: Sequence[str]) -> SignalResult:
        """Read known NAV and FX on exactly the same expected observation dates.

        Raises
        ------
        ValueError
            If the FX series is not a non-tradable USD FX series on the
            observation calendar, or is an ECB fixing; if an input is not a
            non-tradable LEVEL ETF series in ``input_currency``; or if a fixed
            ``observation_cutoff`` does not end the month before the
            decision's (:func:`require_previous_month_cutoff`): the sample
            always ends at a completed month. The registry does not change between
            decisions, so each is a configuration mistake: it stops the run
            rather than leave every decision without a risk estimate.
        """
        calendar = context.calendars.get(self.observation_calendar_id)
        if self.observation_cutoff is not None:
            cutoff = require_previous_month_cutoff(context, self.observation_cutoff, calendar)
        else:
            cutoff = completed_month_cutoff(context)
        session = calendar.session(cutoff) or calendar.previous_session(cutoff)
        days = [session.session_date]
        for _ in range(self.risk_returns):
            days.append(calendar.previous_session(days[-1]).session_date)
        dates = tuple(reversed(days))
        fx = None
        if self.usd_per_eur_fx_id is not None:
            instrument = context.instruments.get(self.usd_per_eur_fx_id)
            if (
                instrument.currency != "USD"
                or instrument.asset_type is not AssetType.FX
                or instrument.tradable
                or instrument.primary_source.upper() == "ECB"
                or (
                    instrument.data_type is DataType.BAR
                    and instrument.calendar_id != self.observation_calendar_id
                    and calendar.subset_of != instrument.calendar_id
                )
            ):
                raise ValueError(
                    f"{self.usd_per_eur_fx_id} cannot convert {self.signal_id}'s NAVs: a "
                    "non-tradable, non-ECB USD FX series on "
                    f"{self.observation_calendar_id} or the venue it restricts is required"
                )
            fx = load_dated_window(
                context, self.usd_per_eur_fx_id, dates=dates, basis=PriceBasis.RAW
            )
        rows = {}
        samples = []
        sample_dates = []
        for name in instrument_ids:
            instrument = context.instruments.get(name)
            if (
                instrument.data_type is not DataType.LEVEL
                or instrument.currency != self.input_currency
                or instrument.asset_type is not AssetType.ETF
                or instrument.tradable
            ):
                raise ValueError(
                    f"{self.signal_id} reads {self.input_currency} fund NAVs and {name} is not "
                    "one: a non-tradable LEVEL ETF series in that currency is required"
                )
            window = load_dated_window(context, name, dates=dates, basis=PriceBasis.RAW, nav=True)
            if window.status is SignalStatus.OK and fx is not None:
                if fx.status is not SignalStatus.OK:
                    window = replace(window, status=fx.status)
                else:
                    window = replace(
                        window,
                        points=tuple(
                            nav / rate for nav, rate in zip(window.points, fx.points, strict=True)
                        ),
                    )
            returns = simple_returns(window.points) if window.status is SignalStatus.OK else None
            if window.status is SignalStatus.OK and returns is None:
                window = replace(window, status=SignalStatus.INVALID_INPUT)
            rows[name] = result_row(returns[-1] if returns else None, window)
            samples.append(tuple(returns or ()))
            sample_dates.append(window.dates)
        frame = build_result_frame(rows)
        frame["returns"] = samples
        frame["dates"] = sample_dates
        return SignalResult(self.signal_id, context.as_of, frame, self.definition())
