"""The two books side by side, which is the only way either one means anything.

A gross return is what the idea was worth; a net return is what an investor
would have been left with. Printing one without the other is how a strategy
that does not survive its own turnover gets published, so this layer has no way
of rendering a single column.

The report is a value, not a printout: :meth:`PerformanceReport.as_frame` is
what a notebook or a test reads, and :meth:`render` only lays the same numbers
out for a terminal.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import pandas as pd

from quant_backtester.analytics.attribution import CostAttribution, RunQuality
from quant_backtester.analytics.config import AnalyticsConfig
from quant_backtester.analytics.contribution import InstrumentAttribution
from quant_backtester.analytics.curves import Book, equity_curve
from quant_backtester.analytics.performance import PerformanceStats
from quant_backtester.backtest.result import BacktestResult

_NOT_AVAILABLE = "-"
"""What a figure the run does not support is printed as.

Not ``0``, not ``nan``: both read as measurements. A dash reads as an absence,
which is what it is.
"""


@dataclass(frozen=True, slots=True)
class PerformanceReport:
    """Everything a finished run can honestly be said to have done.

    Attributes
    ----------
    gross : PerformanceStats
        The book that made the same trades at the market price and paid no fee.
    net : PerformanceStats
        The book that paid what execution charged.
    costs : CostAttribution
        The difference between the two, taken apart.
    quality : RunQuality
        The caveats the figures above have to be read with.
    instruments : InstrumentAttribution
        What each instrument contributed and what it cost. A total says whether
        the idea worked; this says which part of it did, and a rotation whose
        whole gain came from one leg is not the strategy its name describes.
    config : AnalyticsConfig
        The conventions every annualised figure depends on, carried along so
        that a report can be reproduced from itself.
    assumptions : tuple[str, ...]
        What the figures take for granted about the simulation, one line each:
        how orders were filled, what "gross" is, what cash earns, what a limit
        caps and how long a decision lives. Read from the run's configuration,
        so a report states the model it was produced under rather than leaving
        a reader to assume a stronger one (audit, section 5).
    """

    gross: PerformanceStats
    net: PerformanceStats
    costs: CostAttribution
    quality: RunQuality
    instruments: InstrumentAttribution
    config: AnalyticsConfig
    assumptions: tuple[str, ...] = ()

    @classmethod
    def of(cls, result: BacktestResult, config: AnalyticsConfig) -> PerformanceReport:
        """Build the report of a finished run.

        Parameters
        ----------
        result : BacktestResult
            A finished run. Read only: nothing here advances time, reads market
            data or touches the run's records.
        config : AnalyticsConfig
            The annualisation convention and the rate to compare against.

        Returns
        -------
        PerformanceReport
            Gross and net, the costs between them, and what the run had to make
            do on.
        """
        return cls(
            gross=PerformanceStats.from_equity(equity_curve(result, Book.GROSS), config),
            net=PerformanceStats.from_equity(equity_curve(result, Book.NET), config),
            costs=CostAttribution.of(result),
            quality=RunQuality.of(result),
            instruments=InstrumentAttribution.of(result),
            config=config,
            assumptions=_assumptions(result),
        )

    def as_frame(self) -> pd.DataFrame:
        """Return the performance statistics as a frame, one column per book.

        Returns
        -------
        pd.DataFrame
            Indexed by statistic, with a ``gross`` and a ``net`` column. The
            figures a run does not support are ``NaN`` here, and a dash in
            :meth:`render`.
        """
        rows = {
            "total_return": (self.gross.total_return, self.net.total_return),
            "annualised_return": (self.gross.annualised_return, self.net.annualised_return),
            "annualised_volatility": (
                self.gross.annualised_volatility,
                self.net.annualised_volatility,
            ),
            "sharpe_ratio": (self.gross.sharpe_ratio, self.net.sharpe_ratio),
            "max_drawdown": (self.gross.drawdown.depth, self.net.drawdown.depth),
            "best_session": (self.gross.best_session, self.net.best_session),
            "worst_session": (self.gross.worst_session, self.net.worst_session),
        }
        return pd.DataFrame(
            [{"gross": gross, "net": net} for gross, net in rows.values()],
            index=pd.Index(list(rows), dtype="object", name="statistic"),
            columns=["gross", "net"],
            dtype="float64",
        )

    def render(self) -> str:
        """Return the report laid out for a terminal.

        Returns
        -------
        str
            Four blocks - performance, costs, instruments, caveats - with
            gross and net in two columns wherever both exist. Percentages are printed as such,
            which is the one place in the project where a fraction is not the
            unit: a report is read by a person.
        """
        lines = [
            f"{self.net.sessions} sessions, {self.net.years:.2f} years, "
            f"{self.config.sessions_per_year} sessions/year, "
            f"risk-free {self.config.risk_free_rate:.2%}",
            "",
            f"{'':<24}{'gross':>12}{'net':>12}",
        ]
        lines.extend(
            f"{label:<24}{_percent(gross):>12}{_percent(net):>12}"
            for label, gross, net in (
                ("total return", self.gross.total_return, self.net.total_return),
                ("annualised return", self.gross.annualised_return, self.net.annualised_return),
                (
                    "annualised volatility",
                    self.gross.annualised_volatility,
                    self.net.annualised_volatility,
                ),
                ("max drawdown", self.gross.drawdown.depth, self.net.drawdown.depth),
            )
        )
        lines.append(
            f"{'sharpe ratio':<24}{_number(self.gross.sharpe_ratio):>12}"
            f"{_number(self.net.sharpe_ratio):>12}"
        )
        lines.extend(
            ("", self._cost_block(), "", self._instrument_block(), "", self._quality_block())
        )
        if self.assumptions:
            lines.extend(("", "assumptions", *(f"  {line}" for line in self.assumptions)))
        return "\n".join(lines)

    def _instrument_block(self) -> str:
        """Return the per-instrument lines of the rendered report."""
        header = f"{'by instrument':<24}{'net':>12}{'gross':>12}{'cost':>12}{'held':>8}"
        rows = [
            f"{'  ' + entry.instrument_id:<24}{entry.pnl:>12,.2f}"
            f"{entry.gross_pnl:>12,.2f}{entry.cost:>12,.2f}{entry.sessions_held:>8}"
            for entry in self.instruments.instruments
        ]
        return "\n".join([header, *rows]) if rows else f"{'by instrument':<24}nothing was held"

    def _cost_block(self) -> str:
        """Return the cost lines of the rendered report."""
        costs = self.costs
        return "\n".join(
            (
                f"costs{'':<19}{costs.total:>12,.2f}",
                f"{'  commission':<24}{costs.commission:>12,.2f}",
                f"{'  spread':<24}{costs.spread_cost:>12,.2f}",
                f"{'  slippage':<24}{costs.slippage_cost:>12,.2f}",
                f"{'  drag on the return':<24}{_percent(costs.drag):>12}",
                f"{'  share of gross':<24}{_percent(costs.cost_share_of_gross):>12}",
                f"{'  rebalancings':<24}{costs.rebalancings:>12}",
                f"{'  per rebalancing':<24}"
                f"{_number(costs.average_cost_per_rebalancing, '{:,.2f}'):>12}",
                f"{'  turnover':<24}{_number(costs.turnover, '{:.2f}x'):>12}",
                f"{'  turnover a year':<24}{_number(costs.annual_turnover, '{:.2f}x'):>12}",
            )
        )

    def _quality_block(self) -> str:
        """Return the caveat lines of the rendered report."""
        quality = self.quality
        lines = [
            f"{'sessions valued on an older price':<40}{quality.estimated_valuations:>8}",
            f"{'sessions without an execution price':<40}"
            f"{quality.sessions_without_execution_price:>8}",
            f"{'purchases cut for want of cash':<40}{quality.insufficient_cash_adjustments:>8}",
            f"{'sessions with nothing to choose from':<40}"
            f"{quality.sessions_with_nothing_to_choose:>8}",
            f"{'sessions missing a line of the target':<40}"
            f"{quality.sessions_partially_invested:>8}",
            f"{'average cash':<40}{_percent(quality.average_cash_share):>8}",
            f"{'largest weight held':<40}{_percent(quality.max_realised_weight):>8}",
            f"{'orders, fills, rejects':<32}"
            f"{f'{quality.orders}, {quality.fills}, {quality.rejects}':>16}",
        ]
        lines.extend(
            f"{'  ' + reason:<40}{count:>8}" for reason, count in quality.rejects_by_reason.items()
        )
        return "\n".join(lines)


def _assumptions(result: BacktestResult) -> tuple[str, ...]:
    """Return the simulation's assumptions as a report states them.

    Parameters
    ----------
    result : BacktestResult
        A finished run; only its recorded configuration is read.

    Returns
    -------
    tuple[str, ...]
        One line per assumption, in a fixed order.
    """
    configuration = result.configuration
    execution = configuration.get("execution")
    fill_model = execution.get("fill_model") if isinstance(execution, Mapping) else None
    portfolio = configuration.get("portfolio")
    limits = portfolio.get("limits") if isinstance(portfolio, Mapping) else None
    applies_to = limits.get("applies_to") if isinstance(limits, Mapping) else None
    lifetime = configuration.get("decision_lifetime")
    return (
        f"fills: {fill_model or 'not recorded'} - sized and filled at the next opening price",
        "gross: the same fills with no cost taken out - not a separate cost-free run",
        "cash: earns nothing; the risk-free rate is used by the Sharpe ratio only",
        f"limits: cap {applies_to or 'not recorded'}",
        f"a decision lives: {lifetime or 'not recorded'}; a refused order is not retried",
    )


def _percent(value: float | None) -> str:
    """Return a fraction as a percentage, or a dash when there is none."""
    return _NOT_AVAILABLE if value is None else f"{value:.2%}"


def _number(value: float | None, template: str = "{:.2f}") -> str:
    """Return a number in ``template``, or a dash when there is none."""
    return _NOT_AVAILABLE if value is None else template.format(value)
