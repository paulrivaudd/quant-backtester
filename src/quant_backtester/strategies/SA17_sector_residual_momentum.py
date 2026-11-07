"""SA17: the sectors that most beat their usual sensitivity to the market, risk-scaled.

Status: ``PROPOSED / NOT_TESTED`` (``research/SA17/proposal.md``). This module
implements the rule the proposal describes; it holds no result, and no
instrument, window or cost assumption is frozen by it.

At each decision, every sector is scored on its USD NAV monthly returns: regressed
on the market's over the last ``estimation_months`` months, its residuals of
the months ``t - skip - score + 1 .. t - skip`` are averaged and divided by
their sample standard deviation (:class:`MonthlyMomentumSignal`). The
``top_n`` best scores are held in equal parts of an equity sleeve; ties go to
the smaller identifier. The sleeve is scaled by ``g = min(1, target / sigma)``,
with ``sigma = sqrt(annualization * w' C w)``, ``w`` the equal weights and ``C``
the sample covariance of the last ``risk_returns`` daily simple returns of the
selected funds, on the same consecutive sessions. ``1 - g`` goes to the EUR
monetary fund. The book is restated to its target at every decision: there
is no band.

What is not a score is settled explicitly, as the proposal states it:

- a sector that is not listed, not in the session's universe, or whose
  history has not yet reached the oldest month end is **not yet eligible**,
  and is left out;
- any other unreadable input of a sector - a month end the provider did not
  serve, a stale close, a fit with no dispersion - or a covariance that cannot
  be read **cancels the whole decision**: the book is kept and no order is
  sent. A reduced universe is never ranked silently;
- fewer than ``top_n`` eligible sectors leave the whole book in the monetary
  fund (in cash when none is declared or it cannot be held yet).

``signal_input_ids`` must explicitly name USD LEVEL NAV against a USD SP500TR
market on identical XNYS observation dates. ``risk_input_ids`` separately name
NAV for EUR risk: USD NAV divided by synchronized USD-per-EUR FX, or explicitly
validated synchronous EUR NAV. WM16 London EUR reference NAV is not equivalent.
The default shared cutoff is the previous completed calendar month; an explicit
observation_cutoff may override it. Missing expected dates are never backfilled.
The decision still controls publication availability. Valuation at 22:15 Dublin
is not publication, and a 23:00 Paris decision cannot use that day's NAV.
Historical publication and synchronous FX are upstream admission requirements;
this module cannot infer them from downloaded values or currency labels.
"""

from __future__ import annotations

import dataclasses
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from enum import Enum
from types import MappingProxyType
from typing import Final

from quant_backtester.backtest.context import Selection, StrategyContext
from quant_backtester.numbers import require_finite_positive
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.signals.base import Signal
from quant_backtester.signals.cross_asset.residual_momentum import (
    MomentumMeasure,
    MonthlyMomentumSignal,
)
from quant_backtester.signals.engine import SignalRequest
from quant_backtester.signals.risk.nav_returns import NavRiskReturnsSignal
from quant_backtester.signals.types import (
    PriceBasis,
    SignalStatus,
    require_identifier,
    require_non_negative_int,
    require_positive_int,
)
from quant_backtester.strategies.base import Strategy

NOT_YET_ELIGIBLE: Final[frozenset[SignalStatus]] = frozenset(
    {SignalStatus.NOT_LISTED, SignalStatus.INSUFFICIENT_HISTORY}
)
"""Statuses that leave a sector out of the ranking instead of stopping it."""


class SectorRanking(Enum):
    """How the sectors held are chosen."""

    RESIDUAL = "RESIDUAL"
    """The candidate: the ``top_n`` best market-adjusted residual scores."""

    TOTAL = "TOTAL"
    """A control: the ``top_n`` best compounded returns over the same months."""

    NONE = "NONE"
    """A control: every eligible sector, in equal parts."""


def equal_weight_volatility(returns: Sequence[Sequence[float]], annualization: int) -> float:
    """Return the annualised volatility of an equally weighted basket.

    Parameters
    ----------
    returns : Sequence[Sequence[float]]
        One sequence of daily returns per fund, on the same sessions.
    annualization : int
        Sessions per year the daily variance is scaled by.

    Returns
    -------
    float
        ``sqrt(annualization * w' C w)``, with ``w_i = 1 / n`` and ``C`` the
        sample covariance (``ddof=1``) of the returns. A fraction per year.

    Raises
    ------
    ValueError
        If no fund is given, the funds hold different numbers of returns, or
        fewer than two returns each.

    Notes
    -----
    With equal weights, ``w' C w`` is exactly the sample variance of the
    basket's own daily return, the mean of the funds' returns each session;
    that is how it is computed. The tests compare it with ``w' C w`` built
    from ``numpy.cov``.
    """
    count = len(returns)
    if count == 0:
        raise ValueError("a basket needs at least one fund")
    length = len(returns[0])
    if any(len(series) != length for series in returns):
        raise ValueError("every fund of the basket must hold the same sessions")
    if length < 2:
        raise ValueError("a covariance needs at least two returns per fund")
    basket = [math.fsum(series[t] for series in returns) / count for t in range(length)]
    mean = math.fsum(basket) / length
    variance = math.fsum((value - mean) ** 2 for value in basket) / (length - 1)
    return math.sqrt(annualization * variance)


@dataclass(frozen=True, slots=True)
class SectorPlan:
    """What one decision read and the target it computed.

    Attributes
    ----------
    scores : Mapping[str, float]
        Score of each eligible sector, by fund traded.
    eligible : tuple[str, ...]
        Sectors with a score, in identifier order.
    selected : tuple[str, ...]
        Sectors held, best first; empty when fewer than ``top_n`` are eligible.
    volatility : float | None
        Annualised volatility of the equally weighted selection; ``None``
        when no target is declared or nothing was selected.
    exposure : float
        Share of the book given to the sectors, ``g``.
    weights : Mapping[str, float]
        Complete target, the monetary fund included; empty when the decision
        is cancelled or everything stays in cash.
    ineligible : Mapping[str, SignalStatus]
        Sectors not yet eligible, and why.
    unusable : Mapping[str, SignalStatus]
        Inputs whose failure cancels the decision, and why.
    """

    scores: Mapping[str, float]
    eligible: tuple[str, ...]
    selected: tuple[str, ...]
    volatility: float | None
    exposure: float
    weights: Mapping[str, float]
    ineligible: Mapping[str, SignalStatus]
    unusable: Mapping[str, SignalStatus]

    @property
    def complete(self) -> bool:
        """Return whether the decision could be taken."""
        return not self.unusable


@dataclass(frozen=True, slots=True)
class SA17SectorResidualMomentum(Strategy):
    """Hold the sectors with the strongest market-adjusted momentum, scaled to a risk target.

    Parameters
    ----------
    sector_ids : tuple[str, ...]
        The sector funds the book may hold, one per sector.
    market_id : str | None
        The market the residuals are taken against; required for
        ``RESIDUAL``. The other rankings read it only as a gate - a sector is
        refused with the market's status when the market cannot be read - so
        that a control and its candidate invest from the same dates; ``None``
        drops the gate.
    monetary_id : str | None
        The EUR monetary fund that receives what the sectors do not; ``None``
        leaves it in cash.
    ranking : SectorRanking
        How the sectors held are chosen; ``RESIDUAL`` is the candidate.
    signal_input_ids : tuple[str, ...]
        Explicit USD LEVEL NAV, aligned with ``sector_ids``.
    risk_input_ids : tuple[str, ...]
        Explicit LEVEL NAV for EUR risk, aligned with ``sector_ids``.
    risk_input_currency : str
        USD requires synchronized USD-per-EUR FX; EUR requires independently
        validated synchronous EUR NAV, not WM16 London reference NAV.
    usd_per_eur_fx_id : str | None
        Validated synchronous FX, quoting USD per EUR, required for USD risk NAV.
    observation_cutoff : date | None
        Shared last observation date; None uses the previous completed month.
    top_n : int
        Number of sectors held. Also the fewest eligible sectors the book
        invests with, for every ranking.
    estimation_months : int
        Monthly returns ending at the shared observation cutoff.
    score_months : int
        Months whose residuals (or compounded return) make the score.
    skip_months : int
        Most recent months left out of the score.
    risk_returns : int
        Daily simple returns the covariance of the selection is estimated on.
    target_volatility : float | None
        Annualised volatility the equity sleeve is scaled down to, as a
        fraction; ``None`` holds the sectors at the whole book.
    annualization : int
        Sessions per year the daily covariance is scaled by.
    max_age_sessions : int
        Legacy generic-signal parameter recorded for compatibility. SA17's
        exact-date contract requires every cutoff endpoint regardless of age.
    strategy_id : str
        Identity of the strategy in its results.

    Raises
    ------
    ValueError
        If the configuration cannot describe the rule: no sector, a name
        repeated or shared between roles, a residual ranking with no market,
        fewer sectors than ``top_n``, a window that does not hold its score, a
        target that is not positive.

    Notes
    -----
    Long only, no leverage: the weights add up to one before whole units and
    costs. Correcting the signal for beta does not neutralise the book's beta,
    and a volatility target does not bound the drawdown: the covariance is
    read monthly and can lag a fall.
    """

    sector_ids: tuple[str, ...]
    market_id: str | None
    monetary_id: str | None
    ranking: SectorRanking = SectorRanking.RESIDUAL
    signal_input_ids: tuple[str, ...] = ()
    risk_input_ids: tuple[str, ...] = ()
    risk_input_currency: str = "USD"
    usd_per_eur_fx_id: str | None = None
    observation_cutoff: date | None = None
    top_n: int = 3
    estimation_months: int = 36
    score_months: int = 11
    skip_months: int = 1
    risk_returns: int = 63
    target_volatility: float | None = 0.15
    annualization: int = 252
    max_age_sessions: int = 1
    strategy_id: str = "SA17_sector_residual_momentum"

    def __post_init__(self) -> None:
        """Refuse a configuration that does not describe the rule."""
        object.__setattr__(self, "sector_ids", tuple(self.sector_ids))
        object.__setattr__(self, "signal_input_ids", tuple(self.signal_input_ids))
        object.__setattr__(self, "risk_input_ids", tuple(self.risk_input_ids))
        require_identifier(self.strategy_id, "strategy_id")
        if not isinstance(self.ranking, SectorRanking):
            raise ValueError(f"ranking must be a SectorRanking, got {self.ranking!r}")
        if not self.sector_ids:
            raise ValueError("hold what? name at least one sector fund")
        for name in (*self.sector_ids, *self.signal_input_ids):
            require_identifier(name, "a sector")
        for what, names in (("sector", self.sector_ids), ("signal input", self.signal_input_ids)):
            repeated = sorted(name for name, seen in Counter(names).items() if seen > 1)
            if repeated:
                raise ValueError(f"{', '.join(repeated)} is named twice as a {what}")
        if len(self.signal_input_ids) != len(self.sector_ids):
            raise ValueError("give one explicit USD NAV signal input per sector")
        if len(self.risk_input_ids) != len(self.sector_ids):
            raise ValueError("give one explicit NAV risk input per sector")
        for name in self.risk_input_ids:
            require_identifier(name, "risk input")
        if len(set(self.risk_input_ids)) != len(self.risk_input_ids):
            raise ValueError("risk inputs must be distinct")
        if set(self.sector_ids) & {*self.signal_input_ids, *self.risk_input_ids}:
            raise ValueError("NAV inputs must be separate from traded sector funds")
        require_positive_int(self.top_n, "top_n")
        if len(self.sector_ids) < self.top_n:
            raise ValueError(f"{len(self.sector_ids)} sectors cannot fill {self.top_n} places")
        if self.market_id is not None:
            require_identifier(self.market_id, "market_id")
        else:
            raise ValueError("SA17 requires an explicit USD SP500TR market for every ranking")
        if self.monetary_id is not None:
            require_identifier(self.monetary_id, "monetary_id")
        roles = [name for name in (self.market_id, self.monetary_id) if name is not None]
        shared = sorted(
            set(roles) & {*self.sector_ids, *self.signal_input_ids, *self.risk_input_ids}
        )
        if shared or len(set(roles)) != len(roles):
            raise ValueError("the market, the monetary fund and the sectors must be distinct")
        if self.usd_per_eur_fx_id in {
            *roles,
            *self.sector_ids,
            *self.signal_input_ids,
            *self.risk_input_ids,
        }:
            raise ValueError("FX must be separate from the market, funds and NAV inputs")
        require_positive_int(self.risk_returns, "risk_returns")
        if self.risk_returns < 2:
            raise ValueError("a covariance needs at least two returns")
        if self.target_volatility is not None:
            require_finite_positive(self.target_volatility, "target_volatility")
        require_positive_int(self.annualization, "annualization")
        require_non_negative_int(self.max_age_sessions, "max_age_sessions")
        self.momentum()  # the window and its score are checked by the signal
        self.risk_signal()
        self.validate()

    def momentum(self) -> MonthlyMomentumSignal:
        """Return the monthly signal the sectors are ranked, or made eligible, on.

        The ``NONE`` ranking reads the total-return measure only to know which
        sectors have the history the ranked books need. With the market as a
        gate, every book of the study then invests in the same sectors from
        the same dates; only a residual with no dispersion, which the
        candidate alone computes, can stop the candidate and not a control.
        """
        months = f"{self.estimation_months}m_{self.score_months}m_skip{self.skip_months}"
        residual = self.ranking is SectorRanking.RESIDUAL
        market = None if self.market_id is None else self.market_id.lower()
        if residual:
            signal_id = f"sa17_residual_vs_{market}_{months}"
        elif market is not None:
            signal_id = f"sa17_total_gated_by_{market}_{months}"
        else:
            signal_id = f"sa17_total_{months}"
        return MonthlyMomentumSignal(
            signal_id=signal_id,
            measure=MomentumMeasure.RESIDUAL if residual else MomentumMeasure.TOTAL,
            market_id=self.market_id,
            estimation_months=self.estimation_months,
            score_months=self.score_months,
            skip_months=self.skip_months,
            price_basis=PriceBasis.ADJUSTED,
            max_age_sessions=self.max_age_sessions,
            required_currency="USD",
            observation_calendar_id="XNYS",
            observation_cutoff=self.observation_cutoff,
            completed_months_only=True,
            require_nav=True,
        )

    def inputs(self) -> tuple[str, ...]:
        """Return the series each sector is scored on, aligned with ``sector_ids``."""
        return self.signal_input_ids

    def risk_signal(self) -> NavRiskReturnsSignal:
        """Return the separately declared EUR NAV covariance inputs."""
        return NavRiskReturnsSignal(
            signal_id="sa17_eur_nav_risk_returns",
            risk_returns=self.risk_returns,
            input_currency=self.risk_input_currency,
            usd_per_eur_fx_id=self.usd_per_eur_fx_id,
            observation_cutoff=self.observation_cutoff,
        )

    def required_signals(self) -> Sequence[Signal | SignalRequest]:
        """Declare the monthly signal over the sectors' signal inputs."""
        requests = [SignalRequest(self.momentum(), self.inputs())]
        if self.target_volatility is not None:
            requests.append(SignalRequest(self.risk_signal(), self.risk_input_ids))
        return tuple(requests)

    def controls(self) -> Mapping[str, SA17SectorResidualMomentum]:
        """Return the books that each remove one mechanism of this candidate.

        Returns
        -------
        Mapping[str, SA17SectorResidualMomentum]
            ``total_momentum`` ranks on the compounded return instead of the
            residual; ``no_volatility_target`` keeps the residual ranking and
            holds the sectors at the whole book; ``equal_sectors`` holds every
            eligible sector in equal parts; ``equal_sectors_volatility_target``
            does the same under the candidate's target. Every other parameter
            is the candidate's, the market included: it gates the controls'
            signal, so a sector is eligible on the same dates in every book.

        Raises
        ------
        ValueError
            If this book is not a residual ranking with a volatility target:
            the controls are defined around the candidate.

        Notes
        -----
        A control carries a research identifier and no catalogue code. It is a
        run of its own, never a replacement chosen after reading results.
        """
        if self.ranking is not SectorRanking.RESIDUAL or self.target_volatility is None:
            raise ValueError("controls are defined around a residual ranking with a target")
        replace = dataclasses.replace
        return MappingProxyType(
            {
                "total_momentum": replace(
                    self, ranking=SectorRanking.TOTAL, strategy_id="SA17_control_total_momentum"
                ),
                "no_volatility_target": replace(
                    self, target_volatility=None, strategy_id="SA17_control_no_volatility_target"
                ),
                "equal_sectors": replace(
                    self,
                    ranking=SectorRanking.NONE,
                    target_volatility=None,
                    strategy_id="SA17_control_equal_sectors",
                ),
                "equal_sectors_volatility_target": replace(
                    self,
                    ranking=SectorRanking.NONE,
                    strategy_id="SA17_control_equal_sectors_volatility_target",
                ),
            }
        )

    def plan(self, ctx: StrategyContext) -> SectorPlan:
        """Compute the target of one decision, or why it cannot be had."""
        signal_id = self.momentum().signal_id
        scores: dict[str, float] = {}
        ineligible: dict[str, SignalStatus] = {}
        unusable: dict[str, SignalStatus] = {}
        for fund, source in zip(self.sector_ids, self.inputs(), strict=True):
            if fund not in ctx.universe:
                ineligible[fund] = SignalStatus.NOT_LISTED
                continue
            status = ctx.signal_status(signal_id, source)
            if status is SignalStatus.OK:
                scores[fund] = ctx.signal_value(signal_id, source)
            elif status in NOT_YET_ELIGIBLE:
                ineligible[fund] = status
            else:
                unusable[fund] = status
        eligible = tuple(sorted(scores))
        if unusable:
            return self._plan(scores, eligible, ineligible=ineligible, unusable=unusable)
        if len(eligible) < self.top_n:
            return self._plan(
                scores, eligible, ineligible=ineligible, weights=self._sleeve(ctx, (), 0.0)
            )
        if self.ranking is SectorRanking.NONE:
            selected = eligible
        else:
            ranked = sorted(eligible, key=lambda name: (-scores[name], name))
            selected = tuple(ranked[: self.top_n])
        volatility: float | None = None
        exposure = 1.0
        if self.target_volatility is not None:
            volatility, failures = self._volatility(ctx, selected)
            if volatility is None:
                return self._plan(
                    scores, eligible, selected=selected, ineligible=ineligible, unusable=failures
                )
            exposure = 1.0 if volatility == 0.0 else min(1.0, self.target_volatility / volatility)
        return self._plan(
            scores,
            eligible,
            selected=selected,
            volatility=volatility,
            exposure=exposure,
            ineligible=ineligible,
            weights=self._sleeve(ctx, selected, exposure),
        )

    def decide(self, ctx: StrategyContext) -> TargetAllocation:
        """Restate the book to its target, or keep it when an input cannot be read."""
        plan = self.plan(ctx)
        skipped: dict[str, SignalStatus] = {**plan.ineligible, **plan.unusable}
        if not plan.complete:
            # The count of a held book is what a target must not fall below;
            # TargetAllocation raises a count of zero to it anyway.
            considered = max(len(plan.eligible), len(ctx.portfolio.weights))
            return self._keep(ctx, Selection(names=(), considered=considered, skipped=skipped))
        thin = len(plan.eligible) < self.top_n
        for name in plan.eligible:
            if name not in plan.selected:
                skipped[name] = SignalStatus.INSUFFICIENT_CROSS_SECTION if thin else SignalStatus.OK
        monetary = 1 if self.monetary_id in plan.weights else 0
        among = Selection(names=(), considered=len(plan.eligible) + monetary, skipped=skipped)
        if not plan.weights:
            return ctx.cash(among=among)
        return ctx.weights(dict(plan.weights), among=among)

    @staticmethod
    def _keep(ctx: StrategyContext, among: Selection) -> TargetAllocation:
        """Keep the book with no order, exiting only lines the universe no longer holds.

        A cancelled decision keeps what it holds. A line that has left the
        session's universe cannot be kept - the book may not hold it - so it
        is sold, and the lines that remain are kept as they stand, sending no
        order: nothing is restated to the weights of the close.
        """
        held = dict(ctx.portfolio.weights)
        if all(name in ctx.universe for name in held):
            return ctx.hold_positions(among=among)
        remaining = {name: weight for name, weight in held.items() if name in ctx.universe}
        if not remaining:
            return ctx.cash(among=among)
        return dataclasses.replace(ctx.weights(remaining, among=among), kept=frozenset(remaining))

    def _sleeve(
        self, ctx: StrategyContext, selected: tuple[str, ...], exposure: float
    ) -> dict[str, float]:
        """Return the sectors at ``exposure`` in equal parts, the rest in the monetary fund."""
        weights = {name: exposure / len(selected) for name in selected}
        rest = 1.0 - exposure
        if rest > 0.0 and self.monetary_id is not None and self.monetary_id in ctx.universe:
            weights[self.monetary_id] = rest
        return weights

    def _volatility(
        self, ctx: StrategyContext, selected: tuple[str, ...]
    ) -> tuple[float | None, dict[str, SignalStatus]]:
        """Return EUR NAV basket volatility from the separate dated risk signal."""
        frame = ctx.signal(self.risk_signal().signal_id)
        sources = dict(zip(self.sector_ids, self.risk_input_ids, strict=True))
        refused = {
            fund: frame.loc[sources[fund], "status"]
            for fund in selected
            if frame.loc[sources[fund], "status"] is not SignalStatus.OK
        }
        if refused:
            return None, refused
        dates = [frame.loc[sources[fund], "dates"] for fund in selected]
        if any(days != dates[0] for days in dates):
            return None, dict.fromkeys(selected, SignalStatus.MISSING_INPUT)
        returns = [frame.loc[sources[fund], "returns"] for fund in selected]
        if any(len(series) != self.risk_returns for series in returns):
            return None, dict.fromkeys(selected, SignalStatus.MISSING_INPUT)
        return equal_weight_volatility(returns, self.annualization), {}

    @staticmethod
    def _plan(
        scores: Mapping[str, float],
        eligible: tuple[str, ...],
        *,
        selected: tuple[str, ...] = (),
        volatility: float | None = None,
        exposure: float = 0.0,
        weights: Mapping[str, float] | None = None,
        ineligible: Mapping[str, SignalStatus],
        unusable: Mapping[str, SignalStatus] | None = None,
    ) -> SectorPlan:
        """Return a plan with read-only mappings."""
        return SectorPlan(
            scores=MappingProxyType(dict(scores)),
            eligible=eligible,
            selected=selected,
            volatility=volatility,
            exposure=exposure,
            weights=MappingProxyType(dict(weights or {})),
            ineligible=MappingProxyType(dict(ineligible)),
            unusable=MappingProxyType(dict(unusable or {})),
        )
