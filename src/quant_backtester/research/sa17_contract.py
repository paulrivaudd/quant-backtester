"""SA17's preregistered contract: per-fund costs and the executable decision dates."""

from __future__ import annotations

import tomllib
from collections.abc import Collection
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from quant_backtester.data.calendars import TradingCalendar
from quant_backtester.data.instruments import PublicationRule
from quant_backtester.execution.costs import CostModel
from quant_backtester.numbers import require_finite_positive


def load_sector_costs(
    path: Path, sector_ids: Collection[str], *, multiplier: float = 1.0
) -> dict[str, CostModel]:
    """Build explicit sector models, scaling every cost term in stress runs.

    Parameters
    ----------
    path : Path
        The committed ``costs.toml``: rates as fractions of traded value, the
        commission floor in EUR, and one ``[costs.<instrument id>]`` table per
        traded sector fund.
    sector_ids : Collection[str]
        The traded sector funds of the book, exactly. An override missing for
        one of them, or declared for a fund the book does not trade, is a
        mistake: the engine charges an instrument without an override the
        default model, without saying so.
    multiplier : float
        ``1.0`` for the declared costs, or the file's preregistered
        ``stress_multiplier`` for the stress run. Any other value is refused:
        the stress was fixed before the runs.

    Returns
    -------
    dict[str, CostModel]
        One model per sector fund, every term (rates and floor) multiplied by
        ``multiplier``.

    Raises
    ------
    ValueError
        If the funds of the file and ``sector_ids`` differ, or ``multiplier``
        is neither ``1.0`` nor the preregistered stress.

    Notes
    -----
    Quotes in the file are provenance only; crossed quotes are never turned
    into negative costs. Each model uses the separately declared assumption.
    External references and the monetary instrument need their own costs.
    """
    require_finite_positive(multiplier, "multiplier")
    with path.open("rb") as stream:
        config = tomllib.load(stream)
    declared = set(config["costs"])
    expected = set(sector_ids)
    if declared != expected:
        raise ValueError(
            f"{path.name} declares costs for {sorted(declared - expected) or 'no extra fund'} "
            f"and none for {sorted(expected - declared) or 'no missing fund'}: the sector "
            "funds and their cost overrides must match exactly"
        )
    stress = float(config["stress_multiplier"])
    if multiplier not in (1.0, stress):
        raise ValueError(
            f"multiplier {multiplier} is neither the declared costs (1.0) nor the "
            f"preregistered stress ({stress})"
        )
    return {
        name: CostModel(
            commission_rate=config["commission_rate"],
            minimum_commission=config["minimum_commission_eur"],
            half_spread_rate=parameters["half_spread_rate"],
            slippage_rate=config["slippage_rate"],
        ).scaled(multiplier)
        for name, parameters in config["costs"].items()
    }


@dataclass(frozen=True, slots=True)
class ReleaseDecision:
    """One monthly decision of SA17's executable run and the dates it follows from.

    Attributes
    ----------
    month : str
        The completed month the decision reads, ``YYYY-MM``.
    last_observation : date
        That month's last session of the observation grid: the NAV and market
        date both signals read through.
    released : datetime
        UTC instant at which that NAV is public under the declared rule.
    decision : date
        The decision session, on the decision calendar.
    """

    month: str
    last_observation: date
    released: datetime
    decision: date


def month_end_release_decisions(
    observation: TradingCalendar,
    release: TradingCalendar,
    decision: TradingCalendar,
    rule: PublicationRule,
    decision_time: time,
    first_month: date,
    last_month: date,
) -> tuple[ReleaseDecision, ...]:
    """Return the decision of each completed month, after its month-end NAV is released.

    Parameters
    ----------
    observation : TradingCalendar
        The observation grid (``XNYS_XLON``): a month's last session of it is
        the month end both signals read.
    release : TradingCalendar
        The calendar ``rule`` counts its lag on (``XLON``).
    decision : TradingCalendar
        The calendar decisions are taken on (``XPAR``), in its timezone.
    rule : PublicationRule
        When a NAV is public: SA17 declares 23:00 Paris on the next London
        business day.
    decision_time : time
        Local wall-clock time of the decision, in ``decision``'s timezone.
    first_month, last_month : date
        Any day of the first and the last completed month to decide on.

    Returns
    -------
    tuple[ReleaseDecision, ...]
        One per month, in order. The decision is the first session of
        ``decision`` whose decision instant is at or after the release, and
        which is not before the first day of the following month: a decision
        in the month itself would read the month before as the last one
        completed.

    Raises
    ------
    ValueError
        If ``first_month`` is after ``last_month``, or ``rule`` counts its lag
        on another calendar than ``release``.
    CalendarCoverageError
        If a calendar does not cover a date the computation needs.
    """
    if rule.lag_sessions and rule.calendar_id != release.calendar_id:
        raise ValueError(f"the rule counts on {rule.calendar_id}, not on {release.calendar_id}")
    month = first_month.replace(day=1)
    end = last_month.replace(day=1)
    if month > end:
        raise ValueError(f"first month {first_month} is after last month {last_month}")
    zone = ZoneInfo(decision.timezone)
    decisions = []
    while month <= end:
        following = (month + timedelta(days=31)).replace(day=1)
        last = observation.previous_session(following).session_date
        if last < month:
            raise ValueError(f"{month:%Y-%m} has no session of {observation.calendar_id}")
        released = rule.available_at(last, release if rule.lag_sessions else None)
        day = decision.previous_session(following).session_date
        while True:
            day = decision.next_session(day).session_date
            instant = datetime.combine(day, decision_time, tzinfo=zone)
            if instant >= released:
                break
        decisions.append(
            ReleaseDecision(
                month=f"{month:%Y-%m}", last_observation=last, released=released, decision=day
            )
        )
        month = following
    return tuple(decisions)
