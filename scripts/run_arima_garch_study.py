"""Run the SA12 study: an ARIMA direction filter on a GARCH-sized book, against its controls.

Every book is run by the same engine on :data:`COMMON_PERIOD` - the period on
which ``SA12`` has its 757 aligned opens and closes from the first decision -
with 100 000 EUR, the costs of the ETF comparison and quantities fixed at the
decision. From the repository root, once the store is filled and the ``stats``
extra installed (``uv sync --extra stats``):

    OMP_NUM_THREADS=1 uv run python scripts/run_arima_garch_study.py \
        --output results/arima_garch_study

One thread is asked for because the last digits of an optimiser's answer move
with the number of threads the linear algebra uses; the setting is recorded in
the manifest. ``--start`` and ``--end`` state another period, for a check of
the plumbing on a few weeks.

The participants are the books of ``run_etf_strategies_comparison.py`` -
``SA12`` among them - the EWMA control of ``SA11``, and three controls of
``SA12`` that carry no catalogue code:

- **D0**, the same ARIMA, the same innovations, the same two-step variance and
  the same fallbacks, with the direction filter always on: what the filter is
  worth;
- **D1**, the same ARIMA and thresholds with an EWMA variance on the same
  innovations: what GARCH is worth;
- **D2**, a constant mean - ARIMA(0,0,0) - with GARCH: what the ARMA dynamics
  are worth.

Three questions are answered apart: does the filter on the mean help
(``SA12`` against ``D0``, the registered hypothesis, with its statuses), does
GARCH improve on ARIMA-EWMA (``D1``), and is the book useful beside those the
project already has. The forecasts are judged on the return they were made
for - from the open after the decision to the open after that - and the books
on their net equity valued at the close: two measures with two roles.

The history was looked at before: this is a retrospective evaluation with
chronological forecasts. The register of trials holds the configurations run
here - fourteen - and not the variants of earlier exercises.

What is written: ``manifest.json``, ``global_metrics.csv``,
``quality_details.csv``, ``sa12_forecasts.csv``,
``sa12_forecast_evaluation.csv``, ``sa12_history.csv``, ``sa12_orders.csv``,
``sa12_fills.csv``, ``sa12_rejects.csv``, ``sa12_position_episodes.csv``,
``study_comparisons.csv``, ``study.md``, and the files the report writer reads
(``summary.csv``, ``summary_costs_x2.csv``, ``yearly.csv``, ``equity.csv``,
``fills.csv``, ``config.json``, one ``history_<book>.csv`` per book and
``report_extra_SA12.md``).

The tests are in ``tests/scripts/test_run_arima_garch_study.py``.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from run_etf_strategies_comparison import (
    ANALYTICS,
    BENCHMARK,
    COMMON_PERIOD,
    EXECUTION,
    HELD,
    INITIAL_CASH,
    REPOSITORY,
    SPLIT,
    STORE,
    UNIVERSE,
    books,
    build_runner,
    quality_table,
    sessions_of,
    slug,
)
from run_garch_study import (
    BOOTSTRAP_BLOCK,
    BOOTSTRAP_DRAWS,
    BOOTSTRAP_LEVEL,
    BOOTSTRAP_SEED,
    COST_STRESS,
    EWMA,
    FUND,
    GARCH,
    VOL_CONTROL,
    book_histories,
    doubled,
    markdown_table,
    scored,
    sharpe_difference,
    summary_frame,
    yearly_frame,
)
from run_review_diagnostics import episode_summary, episodes

from quant_backtester.analytics.curves import Book
from quant_backtester.analytics.quality import QUALITY_V1
from quant_backtester.analytics.return_forecast import (
    PairedForecasts,
    evaluate_joint,
    evaluate_mean,
    joint_losses,
    pair_at_two_sessions,
    squared_errors,
)
from quant_backtester.analytics.uncertainty import PairedBootstrap
from quant_backtester.analytics.volatility_forecast import paired_loss_difference
from quant_backtester.backtest.runner import StrategyResult, StrategyRunner
from quant_backtester.data.schemas import BarField
from quant_backtester.signals.models.arima_garch import (
    ARIMA_STAGE,
    FORECAST_COLUMNS,
    require_statsmodels,
)
from quant_backtester.signals.models.garch import ForecastSource, require_arch
from quant_backtester.signals.types import SignalStatus
from quant_backtester.strategies import ArimaGarch, EwmaVolControl
from quant_backtester.strategies.adaptive.rules import gated_volatility_rule
from quant_backtester.strategies.base import Strategy
from quant_backtester.strategies.catalogue import entry

SA12 = entry("SA12").display_name
"""The strategy under study."""

D0, D1, D2 = "D0 - same risk no filter", "D1 - ARIMA EWMA", "D2 - constant mean GARCH"
"""The three controls of ``SA12``: research books, no catalogue code."""

FORECAST_VARIANCE_FLOOR = 1e-12
"""Smallest variance the joint loss is evaluated at: a floor of the metric."""

MINIMUM_FORECAST_PAIRS = 252
"""Fewest evaluable forecast pairs the hypothesis is judged on."""

MINIMUM_COMPLETED_EPISODES = 30
"""Fewest completed position episodes the hypothesis is judged on."""

MINIMUM_USABLE_SHARE = 0.95
"""Share of usable joint forecasts, on admissible windows, under which nothing is concluded."""

FALLBACK_ALERT_SHARE = 0.05
"""Share of EWMA fallbacks, among the variance fits attempted, above which nothing is concluded."""

THREAD_VARIABLES = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")
"""The environment variables that set the threads of the linear algebra, recorded with a run."""

INSUFFICIENT, NOT_SUPPORTED = "INSUFFICIENT_EVIDENCE", "NOT_SUPPORTED"
UNCERTAIN, SUPPORTED = "UNCERTAIN", "SUPPORTED_RETROSPECTIVE"
"""The four statuses of the economic hypothesis, sufficiency judged first."""


def controls() -> dict[str, ArimaGarch]:
    """Return the three controls: ``SA12`` with one thing changed in each."""
    return {
        D0: ArimaGarch(direction_filter=False, strategy_id="research_sa12_d0_no_filter"),
        D1: ArimaGarch(volatility_model="EWMA", strategy_id="research_sa12_d1_arima_ewma"),
        D2: ArimaGarch(ar_order=0, ma_order=0, strategy_id="research_sa12_d2_constant_mean"),
    }


def participants() -> dict[str, Strategy]:
    """Return every book of the study: the comparison's, the EWMA control, the three controls."""
    return {**books(), EWMA: EwmaVolControl(), **controls()}


# --- forecasts ---------------------------------------------------------------------------


def forecast_frame(
    captured: Mapping[date, Mapping[str, object]], sessions: Sequence[date]
) -> pd.DataFrame:
    """Return one row per decision of a joint signal, usable or not, with its target dates.

    Parameters
    ----------
    captured : Mapping[date, Mapping[str, object]]
        The whole row of the signal at each decision, as the run's own signal
        computed it on a reader fixed at that decision.
    sessions : Sequence[date]
        The sessions of the run and those after it that exist, in order.

    Returns
    -------
    pd.DataFrame
        Indexed by ``origin``: the status, ``mu_h2``, the diagnostics of both
        fits, the session the decision is executed at the open of and the one
        its target ends at the open of - empty when they do not exist yet.
        Nothing in a row was computed with its target.
    """
    place = {day: rank for rank, day in enumerate(sessions)}
    rows: dict[date, dict[str, object]] = {}
    for origin, row in captured.items():
        rank = place[origin]
        status = row["status"]
        assert isinstance(status, SignalStatus)
        usable = status is SignalStatus.OK
        rows[origin] = {
            "status": status.value,
            "mu_h2": float(row["value"]) if usable else float("nan"),  # type: ignore[arg-type]
            **{column: row.get(column) for column in FORECAST_COLUMNS},
            "window_start": row.get("input_start_date"),
            "window_end": row.get("input_end_date"),
            "execution_session": sessions[rank + 1] if rank + 1 < len(sessions) else None,
            "target_exit_session": sessions[rank + 2] if rank + 2 < len(sessions) else None,
        }
    return pd.DataFrame.from_dict(rows, orient="index").rename_axis("origin")


def operational_quality(forecasts: pd.DataFrame) -> dict[str, object]:
    """Return how often the joint forecast was usable, and how often it fell back.

    Returns
    -------
    dict[str, object]
        ``decisions``; ``admissible_windows`` - decisions whose window of
        opens was served, so a fit was attempted; ``usable`` among them and
        ``usable_share``; ``arima_accepted``; ``volatility_fits`` - variance
        fits attempted, one per accepted mean - with ``garch_accepted``,
        ``ewma_fallbacks`` and ``fallback_share``; and the ``failures`` by
        stage and code. A share whose denominator is zero is ``None``: not a
        success.
    """
    fitted = forecasts["failure_stage"].notna() | (forecasts["status"] == SignalStatus.OK.value)
    admissible = forecasts.loc[fitted]
    usable = int((admissible["status"] == SignalStatus.OK.value).sum())
    accepted = admissible.loc[admissible["failure_stage"] != ARIMA_STAGE]
    source = accepted["volatility_source"]
    fallbacks = int((source == ForecastSource.EWMA_FALLBACK.value).sum())
    failed = admissible.loc[admissible["failure_stage"].notna()]
    reasons = failed["failure_stage"].astype(str) + ":" + failed["failure_code"].astype(str)
    return {
        "decisions": len(forecasts),
        "admissible_windows": len(admissible),
        "usable": usable,
        "usable_share": usable / len(admissible) if len(admissible) else None,
        "arima_accepted": len(accepted),
        "volatility_fits": len(accepted),
        "garch_accepted": int((source == ForecastSource.GARCH.value).sum()),
        "ewma_fallbacks": fallbacks,
        "fallback_share": fallbacks / len(accepted) if len(accepted) else None,
        "failures": {str(key): int(count) for key, count in reasons.value_counts().items()},
    }


def realised_open_returns(result: StrategyResult, instrument_id: str) -> pd.Series:  # type: ignore[type-arg]
    """Return the realised open-to-open log return of each session, on adjusted opens.

    Read once, after the run, on a reader fixed at its last valuation: the
    labels of the forecast evaluation. They are never fed back into a
    forecast, and the factor is the one known at the end, which for a fund
    without corporate actions is one.
    """
    with result.reading() as store:
        market = store.at(result.records()[-1].valuation_time)
        opens = market.history(instrument_id, BarField.OPEN)
        closes = market.history(instrument_id, BarField.CLOSE)
        adjusted = market.adjusted_history(instrument_id)
    common = [day for day in opens.index if day in closes.index and day in adjusted.index]
    series = opens.loc[common] * adjusted.loc[common] / closes.loc[common]
    return pd.Series(np.log(series / series.shift(1)).dropna())


def mean_table(paired: PairedForecasts, rolling_mean: pd.Series) -> pd.DataFrame:  # type: ignore[type-arg]
    """Return the errors of the ARIMA mean beside a forecast of zero and the window's mean.

    The three are measured on the same origins: those where the ARIMA forecast
    has a known target.
    """
    pairs = paired.pairs
    realised = pairs["realised"].to_numpy(dtype="float64")
    window = rolling_mean.reindex(pairs.index).to_numpy(dtype="float64")
    forecasts = {
        "ARIMA mu_h2": pairs["forecast_mean"].to_numpy(dtype="float64"),
        "zero": np.zeros(len(pairs)),
        "mean of the window": window,
    }
    return pd.DataFrame.from_dict(
        {
            name: evaluate_mean(list(realised), list(said)).definition()
            for name, said in forecasts.items()
        },
        orient="index",
    ).rename_axis("forecast")


def entry_signals(pairs: pd.DataFrame, entry_threshold: float) -> dict[str, object]:
    """Return how often the forecast cleared each threshold, and what followed an entry signal."""
    said = pairs["forecast_mean"].to_numpy(dtype="float64")
    realised = pairs["realised"].to_numpy(dtype="float64")
    after = realised[said > entry_threshold]
    count = len(pairs)
    return {
        "pairs": count,
        "forecast_above_entry": len(after),
        "share_above_entry": len(after) / count if count else None,
        "forecast_positive": int((said > 0.0).sum()),
        "share_positive": float((said > 0.0).mean()) if count else None,
        "mean_realised_after_entry_signal": float(after.mean()) if len(after) else None,
        "share_up_after_entry_signal": float((after > 0.0).mean()) if len(after) else None,
        "mean_realised_all": float(realised.mean()) if count else None,
    }


def loss_difference_row(
    label: str,
    first: pd.Series,
    second: pd.Series,  # type: ignore[type-arg]
) -> dict[str, object]:
    """Return one paired difference of losses with its bootstrap interval."""
    measured = paired_loss_difference(
        first,
        second,
        block=BOOTSTRAP_BLOCK,
        draws=BOOTSTRAP_DRAWS,
        seed=BOOTSTRAP_SEED,
        level=BOOTSTRAP_LEVEL,
    )
    return {"comparison": label, **measured.definition()}


# --- the economic test -------------------------------------------------------------------


def sortino(equity: pd.Series) -> float | None:  # type: ignore[type-arg]
    """Return the annualised Sortino ratio of a curve, ``None`` when it never fell.

    Mean session return in excess of the risk-free rate over the root mean
    square of the negative excess returns, annualised like the Sharpe ratio.
    """
    values = equity.to_numpy(dtype="float64")
    excess = values[1:] / values[:-1] - 1.0 - ANALYTICS.risk_free_per_session
    downside = math.sqrt(float(np.mean(np.minimum(excess, 0.0) ** 2))) if len(excess) else 0.0
    if downside <= 0.0:
        return None
    return float(np.mean(excess)) / downside * math.sqrt(ANALYTICS.sessions_per_year)


def comparison_frame(
    base: Mapping[str, StrategyResult], stressed: Mapping[str, StrategyResult]
) -> pd.DataFrame:
    """Return ``SA12`` against each control and reference, at both cost levels.

    One row per control and cost level: the net Sharpe ratios, returns and
    maximum drawdowns, their differences, and the paired block bootstrap of
    the Sharpe difference - or the reason it was refused, never a zero.
    """
    rows: list[dict[str, object]] = []
    for label, results in (("x1", base), (f"x{COST_STRESS:g}", stressed)):
        own = results[SA12].report().net
        for control in (D0, D1, D2, GARCH, VOL_CONTROL, EWMA, HELD):
            other = results[control].report().net
            outcome = sharpe_difference(results[SA12].equity(), results[control].equity())
            row: dict[str, object] = {
                "costs": label,
                "control": control,
                "sharpe_sa12": own.sharpe_ratio,
                "sharpe_control": other.sharpe_ratio,
                "net_return_sa12": own.total_return,
                "net_return_control": other.total_return,
                "max_drawdown_sa12": own.drawdown.depth,
                "max_drawdown_control": other.drawdown.depth,
                "sharpe_difference": None,
                "interval_low": None,
                "interval_high": None,
            }
            if isinstance(outcome, PairedBootstrap):
                row.update(
                    {
                        "sharpe_difference": outcome.estimate,
                        "interval_low": outcome.low,
                        "interval_high": outcome.high,
                        "bootstrap": "ok",
                    }
                )
            else:
                row["bootstrap"] = outcome
            rows.append(row)
    return pd.DataFrame(rows)


def hypothesis_status(
    comparison: pd.DataFrame,
    *,
    forecast_pairs: int,
    completed_episodes: int,
    quality: Mapping[str, object],
) -> tuple[str, list[str]]:
    """Return the status of the registered hypothesis - the filter against ``D0`` - and why.

    Parameters
    ----------
    comparison : pd.DataFrame
        What :func:`comparison_frame` returned.
    forecast_pairs : int
        Forecasts of ``SA12`` paired with a known target.
    completed_episodes : int
        Position episodes of ``SA12`` that were closed.
    quality : Mapping[str, object]
        What :func:`operational_quality` returned.

    Returns
    -------
    tuple[str, list[str]]
        Sufficiency and operational quality first: fewer pairs or episodes
        than required, a share of usable forecasts under 95%, a share of EWMA
        fallbacks above 5%, or a share that does not exist, give
        ``INSUFFICIENT_EVIDENCE``. Then ``NOT_SUPPORTED`` for a Sharpe
        difference at or below zero at either cost level; ``UNCERTAIN`` for a
        positive one whose interval includes zero, a refused bootstrap or a
        drawdown deeper than ``D0``'s; ``SUPPORTED_RETROSPECTIVE`` otherwise.
    """
    reasons: list[str] = []
    if forecast_pairs < MINIMUM_FORECAST_PAIRS:
        reasons.append(f"{forecast_pairs} evaluable forecast pairs, under {MINIMUM_FORECAST_PAIRS}")
    if completed_episodes < MINIMUM_COMPLETED_EPISODES:
        reasons.append(
            f"{completed_episodes} completed position episodes, under {MINIMUM_COMPLETED_EPISODES}"
        )
    usable, fallback = quality["usable_share"], quality["fallback_share"]
    if usable is None or float(usable) < MINIMUM_USABLE_SHARE:  # type: ignore[arg-type]
        reasons.append(f"share of usable joint forecasts {usable}, under {MINIMUM_USABLE_SHARE}")
    if fallback is None or float(fallback) > FALLBACK_ALERT_SHARE:  # type: ignore[arg-type]
        reasons.append(f"share of EWMA fallbacks {fallback}, above {FALLBACK_ALERT_SHARE}")
    if reasons:
        return INSUFFICIENT, reasons
    against = comparison.loc[comparison["control"] == D0].set_index("costs")
    base, stress = against.loc["x1"], against.loc[f"x{COST_STRESS:g}"]
    for label, row in (("base costs", base), ("doubled costs", stress)):
        difference = row["sharpe_difference"]
        if difference is None or pd.isna(difference):
            return UNCERTAIN, [f"Sharpe difference against D0 at {label}: {row['bootstrap']}"]
        if float(difference) <= 0.0:
            reasons.append(f"Sharpe difference against D0 at {label}: {float(difference):+.3f}")
    if reasons:
        return NOT_SUPPORTED, reasons
    if float(base["interval_low"]) <= 0.0:
        reasons.append(
            "interval of the Sharpe difference against D0 includes zero: "
            f"[{float(base['interval_low']):+.3f} ; {float(base['interval_high']):+.3f}]"
        )
    if float(base["max_drawdown_sa12"]) < float(base["max_drawdown_control"]):
        reasons.append("maximum drawdown deeper than D0's")
    return (UNCERTAIN, reasons) if reasons else (SUPPORTED, [])


# --- histories ---------------------------------------------------------------------------


def joint_history(
    history: pd.DataFrame,
    forecasts: pd.DataFrame,
    opens: pd.Series,  # type: ignore[type-arg]
    strategy: ArimaGarch,
) -> pd.DataFrame:
    """Return a book's history with its forecast, its gate and its target before the band.

    Parameters
    ----------
    history : pd.DataFrame
        The generic history of the book: closes, signal value, weights, value.
    forecasts : pd.DataFrame
        What :func:`forecast_frame` returned for the signal the book reads.
    opens : pd.Series
        Raw opens of the fund by session.
    strategy : ArimaGarch
        The book's strategy, for its thresholds and its sizing.

    Returns
    -------
    pd.DataFrame
        Numeric columns only, a row per session: ``open_<fund>``,
        ``mu_h2_bp`` (the forecast mean in basis points), ``forecast_volatility``
        (annualised), ``ewma_fallback`` (1 when the variance is the EWMA's),
        ``gate`` (1 when the mean lets the position be held, read on the
        weight held that evening), ``theoretical_weight`` (the target before
        the band), then the weights targeted and held and the value. The
        signal's own column is replaced by ``mu_h2_bp``.
    """
    fund = strategy.instrument_id
    signal_column = f"{strategy.forecast_signal().signal_id}[{fund}]"
    days = list(history.index)
    # A book that never held the fund has no weight column: it held zero throughout.
    history = history.assign(
        **{
            column: 0.0
            for column in (f"target_{fund}", f"held_{fund}")
            if column not in history.columns
        }
    )
    held = dict(
        zip(days, history[f"held_{fund}"].fillna(0.0).to_numpy(dtype="float64"), strict=True)
    )
    volatility = pd.Series(forecasts["annualized_volatility"].astype("float64")).reindex(days)
    mean = pd.Series(forecasts["mu_h2"].astype("float64")).reindex(days)
    means = dict(zip(days, mean.to_numpy(dtype="float64"), strict=True))
    volatilities = dict(zip(days, volatility.to_numpy(dtype="float64"), strict=True))
    gates, weights = [], []
    for day in days:
        usable = not (math.isnan(means[day]) or math.isnan(volatilities[day]))
        target = gated_volatility_rule(
            fund,
            float(means[day]) if usable else None,
            float(volatilities[day]) if usable else None,
            held=held[day] > 0.0,
            entry_threshold=strategy.entry_threshold,
            exit_threshold=strategy.exit_threshold,
            target_volatility=strategy.target_volatility,
            floor=strategy.volatility_floor,
            gated=strategy.direction_filter,
        )
        gates.append(target.diagnostics.get("gate", float("nan")))
        weights.append(dict(target.weights).get(fund, 0.0) if usable else float("nan"))
    source = forecasts["volatility_source"].reindex(history.index)
    extra = pd.DataFrame(
        {
            f"open_{fund}": opens.reindex(history.index).astype("float64"),
            "mu_h2_bp": mean * 1e4,
            "forecast_volatility": volatility,
            "ewma_fallback": (source == ForecastSource.EWMA_FALLBACK.value).astype("float64"),
            "gate": gates,
            "theoretical_weight": weights,
        },
        index=history.index,
    )
    rest = history.drop(columns=[signal_column])
    closes = [column for column in rest.columns if column.startswith("close_")]
    others = [column for column in rest.columns if column not in closes]
    return pd.concat([rest[closes], extra, rest[others]], axis=1).rename_axis("session_date")


# --- the written study -------------------------------------------------------------------


def _cell(value: object, pattern: str) -> str:
    """Return one cell of a table, ``n/a`` for a figure that does not exist."""
    if value is None or value is pd.NA or (isinstance(value, float) and math.isnan(value)):
        return "n/a"
    return pattern.format(value)


RANKING_COLUMNS = (
    ("rank", "rank", "{}"),
    ("quality", "score", "{:.1%}"),
    ("net_return", "net", "{:+.1%}"),
    ("annualised_return", "net/yr", "{:+.2%}"),
    ("volatility", "vol", "{:.1%}"),
    ("sharpe", "Sharpe", "{:+.2f}"),
    ("sortino", "Sortino", "{:+.2f}"),
    ("max_drawdown", "max DD", "{:.1%}"),
    ("alpha_vs_market", "alpha/yr", "{:+.2%}"),
    ("beta_vs_market", "beta", "{:.2f}"),
    ("information_ratio_vs_market", "IR", "{:+.2f}"),
    ("costs_eur", "costs EUR", "{:,.0f}"),
    ("turnover_per_year", "turnover/yr", "{:.2f}"),
    ("average_exposure", "expo", "{:.0%}"),
)
"""The columns of the ranking tables of the study."""


def study_markdown(
    summary: pd.DataFrame,
    stressed_summary: pd.DataFrame,
    comparison: pd.DataFrame,
    quality: Mapping[str, object],
    means: pd.DataFrame,
    joint: pd.DataFrame,
    losses: pd.DataFrame,
    entries: Mapping[str, object],
    stays: Mapping[str, object],
    coverage: Mapping[str, object],
    status: tuple[str, Sequence[str]],
    register: Mapping[str, object],
    timings: Mapping[str, float],
) -> str:
    """Return the written study: ranking, forecasts, the test of the filter, GARCH, limits."""
    outcome, reasons = status
    first, last = summary["first_session"].iloc[0], summary["last_session"].iloc[0]
    dedicated = comparison.set_index(
        comparison["costs"].astype(str) + " vs " + comparison["control"].astype(str)
    ).rename_axis("costs vs control")
    lines = [
        "# SA12 - ARIMA GARCH: retrospective study",
        "",
        f"Common period {first} to {last}, {int(summary['sessions'].iloc[0])} sessions, "
        f"{INITIAL_CASH:,.0f} EUR, costs of the ETF comparison, quantities fixed at the "
        "decision, cash unpaid. A retrospective evaluation with chronological forecasts; a "
        "sequential two-stage estimation, not a joint ARIMA-GARCH likelihood.",
        "",
        "## Ranking (QUALITY_V1, against ETF_WORLD bought and held)",
        "",
        markdown_table(summary, RANKING_COLUMNS),
        "",
        f"Deflated by {register['trials']} trials: every catalogued strategy run here, the "
        "EWMA control of SA11 and the three controls of SA12; the fund held and the even split "
        "are references. These books are strongly correlated and are not independent "
        "experiments, and the variants of earlier exercises are not in the register: the "
        "ranking is exploratory. D0, D1 and D2 are controls, not candidates.",
        "",
        f"## The same table with every cost paid x{COST_STRESS:g} (second real run, same policy)",
        "",
        markdown_table(stressed_summary, RANKING_COLUMNS),
        "",
        "The entry threshold of SA12 stays at 20 bp in this run: changing it too would test "
        "another strategy.",
        "",
        "## Operational quality of the joint forecast",
        "",
        f"- decisions: {quality['decisions']}; windows of opens served: "
        f"{quality['admissible_windows']}; usable joint forecasts: {quality['usable']} "
        f"({_cell(quality['usable_share'], '{:.2%}')});",
        f"- means accepted: {quality['arima_accepted']}; variance fits attempted: "
        f"{quality['volatility_fits']}, GARCH accepted {quality['garch_accepted']}, EWMA "
        f"fallbacks {quality['ewma_fallbacks']} ({_cell(quality['fallback_share'], '{:.2%}')});",
        f"- failures by stage and code: {quality['failures'] or 'none'};",
        f"- forecast pairs with a known target: {coverage['pairs']} of {coverage['origins']} "
        f"origins; left out: {coverage['exclusions']}.",
        "",
        "## Forecast of the mean (open to open, two steps ahead)",
        "",
        markdown_table(
            means,
            [
                ("pairs", "pairs", "{:.0f}"),
                ("mse", "MSE", "{:.4e}"),
                ("mae", "MAE", "{:.5f}"),
                ("bias", "bias", "{:+.5f}"),
                ("correlation", "corr.", "{:+.3f}"),
                ("sign_accuracy", "sign", "{:.1%}"),
                ("always_up_accuracy", "always up", "{:.1%}"),
                ("balanced_accuracy", "balanced", "{:.1%}"),
                ("forecast_up", "forecasts > 0", "{:.0f}"),
            ],
        ),
        "",
        "The sign is scored on the realisations that are not exactly zero; a forecast of zero "
        "counts as 'not up'. A share of right signs is to be read against 'always up', which "
        "only measures the drift of the fund.",
        "",
        f"Entry signals: the forecast cleared 20 bp on {entries['forecast_above_entry']} of "
        f"{entries['pairs']} origins ({_cell(entries['share_above_entry'], '{:.2%}')}) and was "
        f"positive on {entries['forecast_positive']} "
        f"({_cell(entries['share_positive'], '{:.1%}')}). Mean realised return after an entry "
        f"signal: {_cell(entries['mean_realised_after_entry_signal'], '{:+.4%}')} "
        f"(all origins: {_cell(entries['mean_realised_all'], '{:+.4%}')}).",
        "",
        "## Joint forecast of the mean and the variance",
        "",
        markdown_table(
            joint,
            [
                ("pairs", "pairs", "{:.0f}"),
                ("loss", "loss", "{:.4f}"),
                ("mean_ratio", "mean e2/v", "{:.3f}"),
                ("residual_std", "std z", "{:.3f}"),
                ("residual_kurtosis", "kurtosis z", "{:.2f}"),
                ("residual_autocorrelation", "autocorr. z", "{:+.3f}"),
                ("squared_autocorrelation", "autocorr. z2", "{:+.3f}"),
                ("floor_applications", "floored", "{:.0f}"),
            ],
        ),
        "",
        "Loss = log(v) + e2/v with e the error around the forecast mean; lower is better. "
        "SA12 and D1 share their mean, so their difference compares variances; D2 has another "
        "mean, so its loss is a joint one.",
        "",
        markdown_table(
            losses.set_index("comparison"),
            [
                ("pairs", "pairs", "{:.0f}"),
                ("estimate", "mean difference", "{:+.3e}"),
                ("low", "95% low", "{:+.3e}"),
                ("high", "95% high", "{:+.3e}"),
                ("excludes_zero", "excludes zero", "{}"),
            ],
        ),
        "",
        f"Paired differences on shared origins, negative when the first is the better one; "
        f"moving-block bootstrap, blocks of {BOOTSTRAP_BLOCK}, {BOOTSTRAP_DRAWS} draws, seed "
        f"{BOOTSTRAP_SEED}.",
        "",
        "## SA12 against its controls and the references",
        "",
        markdown_table(
            dedicated,
            [
                ("sharpe_sa12", "Sharpe SA12", "{:+.3f}"),
                ("sharpe_control", "Sharpe control", "{:+.3f}"),
                ("sharpe_difference", "difference", "{:+.3f}"),
                ("interval_low", "95% low", "{:+.3f}"),
                ("interval_high", "95% high", "{:+.3f}"),
                ("net_return_sa12", "net SA12", "{:+.2%}"),
                ("net_return_control", "net control", "{:+.2%}"),
                ("max_drawdown_sa12", "max DD SA12", "{:.2%}"),
                ("max_drawdown_control", "max DD control", "{:.2%}"),
            ],
        ),
        "",
        f"Position episodes of SA12: {stays.get('stays', 0)} "
        f"({stays.get('completed', 0)} completed), {stays.get('gains', 0)} with a net gain; "
        f"mean net return per episode {_cell(stays.get('mean_net_return'), '{:+.2%}')}.",
        "",
        "## Status of the registered hypothesis (`sa12_arima_garch`): the filter against D0",
        "",
        f"**{outcome}.**",
        *[f"- {reason}" for reason in reasons],
        "",
        "The status answers one question - does the direction filter improve the same risk "
        "sizing without it - under the criteria written before the run. It says nothing wider: "
        "`NOT_SUPPORTED` is not 'ARIMA-GARCH never works', and `SUPPORTED_RETROSPECTIVE` would "
        "not be 'ready to trade'. Whether GARCH adds anything is read apart, on the rows "
        "against D1 above and on the difference of losses: a result against D0 does not "
        "justify GARCH if ARIMA-EWMA does as well.",
        "",
        "## Limits",
        "",
        "- The mean and the variance are estimated in two stages; the two-step variance is a "
        "plug-in that ignores the uncertainty of the parameters.",
        "- The forecasts are of open-to-open log returns; the books are valued at the close.",
        "- The store is not a set of provider vintages.",
        "- A prospective observation starts at the first XPAR session after this code is "
        "available, with this configuration frozen; it does not exist yet.",
        "",
        "## Timings",
        "",
        *[f"- {label}: {seconds:.0f} s" for label, seconds in timings.items()],
        "",
    ]
    return "\n".join(lines)


def report_extra(
    quality: Mapping[str, object],
    means: pd.DataFrame,
    entries: Mapping[str, object],
    losses: pd.DataFrame,
    comparison: pd.DataFrame,
    stays: Mapping[str, object],
    coverage: Mapping[str, object],
    status: tuple[str, Sequence[str]],
) -> str:
    """Return the section of the SA12 report that only this study can write, in French."""
    outcome, reasons = status
    arima = means.loc["ARIMA mu_h2"]
    against = comparison.set_index(["costs", "control"])
    rows = []
    for costs in ("x1", f"x{COST_STRESS:g}"):
        for control in (D0, D1, D2, GARCH, VOL_CONTROL, EWMA):
            row = against.loc[(costs, control)]
            rows.append(
                f"| {costs} | {control} | {_cell(row['sharpe_sa12'], '{:+.3f}')} | "
                f"{_cell(row['sharpe_control'], '{:+.3f}')} | "
                f"{_cell(row['sharpe_difference'], '{:+.3f}')} | "
                f"[{_cell(row.get('interval_low'), '{:+.3f}')} ; "
                f"{_cell(row.get('interval_high'), '{:+.3f}')}] | "
                f"{_cell(row['max_drawdown_sa12'], '{:.2%}')} | "
                f"{_cell(row['max_drawdown_control'], '{:.2%}')} |"
            )
    variance = losses.set_index("comparison")
    lines = [
        "### Qualité opérationnelle et prévisions (étude SA12)",
        "",
        f"- **Couverture.** {quality['decisions']} décisions ; fenêtre de 757 ouvertures servie "
        f"{quality['admissible_windows']} fois ; prévision jointe utilisable "
        f"{quality['usable']} fois ({_cell(quality['usable_share'], '{:.2%}')}). Moyennes ARIMA "
        f"acceptées : {quality['arima_accepted']}. Ajustements de variance tentés : "
        f"{quality['volatility_fits']}, dont GARCH accepté {quality['garch_accepted']} et repli "
        f"EWMA {quality['ewma_fallbacks']} ({_cell(quality['fallback_share'], '{:.2%}')}). "
        f"Échecs par étape : {quality['failures'] or 'aucun'}.",
        f"- **Paires évaluables.** {coverage['pairs']} prévisions sur {coverage['origins']} ont "
        f"une cible connue (rendement de l'ouverture t+1 à l'ouverture t+2) ; exclues : "
        f"{coverage['exclusions']}.",
        f"- **Moyenne prévue.** MSE {_cell(arima['mse'], '{:.4e}')} pour ARIMA, "
        f"{_cell(means.loc['zero', 'mse'], '{:.4e}')} pour la prévision nulle et "
        f"{_cell(means.loc['mean of the window', 'mse'], '{:.4e}')} pour la moyenne de la "
        f"fenêtre. Corrélation prévision/réalisation {_cell(arima['correlation'], '{:+.3f}')}. "
        f"Signe juste {_cell(arima['sign_accuracy'], '{:.1%}')}, contre "
        f"{_cell(arima['always_up_accuracy'], '{:.1%}')} pour « toujours en hausse » ; justesse "
        f"équilibrée {_cell(arima['balanced_accuracy'], '{:.1%}')}.",
        f"- **Signaux d'entrée.** La prévision dépasse 20 pb sur "
        f"{entries['forecast_above_entry']} origines sur {entries['pairs']} "
        f"({_cell(entries['share_above_entry'], '{:.2%}')}) et est positive sur "
        f"{entries['forecast_positive']} ({_cell(entries['share_positive'], '{:.1%}')}). "
        f"Rendement réalisé moyen après un signal d'entrée : "
        f"{_cell(entries['mean_realised_after_entry_signal'], '{:+.3%}')}, contre "
        f"{_cell(entries['mean_realised_all'], '{:+.3%}')} sur toutes les origines.",
        f"- **Épisodes de position.** {stays.get('stays', 0)} épisodes, dont "
        f"{stays.get('completed', 0)} terminés ; {stays.get('gains', 0)} gagnants ; net moyen "
        f"{_cell(stays.get('mean_net_return'), '{:+.2%}')}.",
        "",
        "### SA12 contre ses contrôles",
        "",
        "| Coûts | Contrôle | Sharpe SA12 | Sharpe contrôle | Écart | Intervalle 95 % | "
        "Perte max. SA12 | Perte max. contrôle |",
        "|---|---|---:|---:|---:|---|---:|---:|",
        *rows,
        "",
        "D0 : même ARIMA, même variance, filtre de direction toujours actif. D1 : même ARIMA, "
        "variance EWMA. D2 : moyenne constante et GARCH. Ce sont des contrôles de recherche, "
        "sans code de catalogue, et aucun n'est candidat. Bootstrap apparié par blocs de "
        f"{BOOTSTRAP_BLOCK} séances, {BOOTSTRAP_DRAWS} tirages, graine {BOOTSTRAP_SEED}.",
        "",
        "Écart de perte jointe `log(v) + e²/v` SA12 moins D1 (même moyenne, donc une "
        f"comparaison de variances) : "
        f"{_cell(variance.loc['SA12 - D1 (variance, same mean)', 'estimate'], '{:+.4f}')}, "
        f"intervalle [{_cell(variance.loc['SA12 - D1 (variance, same mean)', 'low'], '{:+.4f}')} "
        f"; {_cell(variance.loc['SA12 - D1 (variance, same mean)', 'high'], '{:+.4f}')}].",
        "",
        f"### Statut de l'hypothèse préinscrite `sa12_arima_garch` : **{outcome}**",
        "",
        *[f"- {reason}" for reason in reasons],
        "",
        "Ce statut répond à une seule question, écrite avant le run : le filtre de direction "
        "améliore-t-il le même dimensionnement de risque sans lui (D0) ? Il ne dit pas "
        "« ARIMA-GARCH ne fonctionne jamais », et l'apport de GARCH se lit à part, contre D1.",
        "",
    ]
    return "\n".join(lines)


def manifest(
    results: Mapping[str, StrategyResult],
    strategies: Mapping[str, Strategy],
    register: Mapping[str, object],
    stressed: object,
    status: tuple[str, Sequence[str]],
    quality: Mapping[str, object],
    timings: Mapping[str, float],
) -> dict[str, object]:
    """Return everything the study depends on, serialisable: code, data, costs, trials."""
    reference = results[SA12]
    lock = (REPOSITORY / "uv.lock").read_bytes()
    packages = ("numpy", "scipy", "pandas", "arch", "statsmodels", "matplotlib")
    return {
        "study": "sa12_arima_garch",
        "hypothesis_id": "sa12_arima_garch",
        "status": {"outcome": status[0], "reasons": list(status[1])},
        "period": {"start": str(reference.start), "end": str(reference.end)},
        "initial_cash": INITIAL_CASH,
        "universe": list(UNIVERSE),
        "analytics": ANALYTICS.definition(),
        "execution": reference.configuration["execution"],
        "execution_stressed": {"factor": COST_STRESS, "costs": str(stressed)},
        "quality_rules": QUALITY_V1.definition(),
        "bootstrap": {
            "block": BOOTSTRAP_BLOCK,
            "draws": BOOTSTRAP_DRAWS,
            "seed": BOOTSTRAP_SEED,
            "level": BOOTSTRAP_LEVEL,
        },
        "forecast_variance_floor": FORECAST_VARIANCE_FLOOR,
        "thresholds": {
            "minimum_forecast_pairs": MINIMUM_FORECAST_PAIRS,
            "minimum_completed_position_episodes": MINIMUM_COMPLETED_EPISODES,
            "minimum_usable_share": MINIMUM_USABLE_SHARE,
            "fallback_alert_share": FALLBACK_ALERT_SHARE,
        },
        "operational_quality": dict(quality),
        "trial_register": dict(register),
        "source": reference.source.definition(),
        "data_state": reference.data_state.digest,
        "inputs": reference.configuration["inputs"],
        "environment": reference.configuration["environment"],
        "lockfile_sha256": hashlib.sha256(lock).hexdigest(),
        "versions": {name: importlib.metadata.version(name) for name in packages},
        # The last digits of a fit depend on how many threads the linear algebra uses.
        "threads": {name: os.environ.get(name) for name in THREAD_VARIABLES},
        "strategies": {name: strategy.definition() for name, strategy in strategies.items()},
        "run_ids": {name: result.run_id for name, result in results.items()},
        "timings_seconds": dict(timings),
    }


def run_books(
    runner: StrategyRunner, strategies: Mapping[str, Strategy], label: str, period: tuple[str, str]
) -> dict[str, StrategyResult]:
    """Run every book on one period and return the results by name."""
    results: dict[str, StrategyResult] = {}
    for name, strategy in strategies.items():
        print(f"running {name} ({label}) ...", file=sys.stderr)
        results[name] = runner.run(strategy, UNIVERSE, *period)
    return results


def main(arguments: Sequence[str] | None = None) -> int:
    """Run the study and write every export."""
    parser = argparse.ArgumentParser(description="Run the SA12 ARIMA-GARCH study.")
    parser.add_argument("--output", type=Path, default=Path("results/arima_garch_study"))
    parser.add_argument("--store", type=Path, default=STORE)
    parser.add_argument("--start", default=COMMON_PERIOD[0], help="first measured session")
    parser.add_argument("--end", default=COMMON_PERIOD[1], help="last measured session")
    options = parser.parse_args(arguments)
    period = (options.start, options.end)
    require_statsmodels()
    require_arch()

    strategies = participants()
    family = {SA12: strategies[SA12], **controls()}
    own = family[SA12]
    assert isinstance(own, ArimaGarch)
    timings: dict[str, float] = {}

    runner = build_runner(options.store)
    started = time.perf_counter()
    base = run_books(runner, strategies, "costs x1", period)
    timings["every run at costs x1"] = time.perf_counter() - started
    stressed_execution = doubled(EXECUTION)
    started = time.perf_counter()
    stressed = run_books(
        replace(runner, execution=stressed_execution), strategies, "costs x2", period
    )
    timings[f"every run at costs x{COST_STRESS:g}"] = time.perf_counter() - started

    details, register = scored(base)
    stressed_details, _ = scored(stressed)
    summary = summary_frame(base, details)
    stressed_summary = summary_frame(stressed, stressed_details)
    for frame, results in ((summary, base), (stressed_summary, stressed)):
        frame["sortino"] = [sortino(results[str(name)].equity()) for name in frame.index]

    # Everything read back from the store is read before the first file is written.
    started = time.perf_counter()
    signals = {name: book.forecast_signal().signal_id for name, book in family.items()}  # type: ignore[attr-defined]
    captured: dict[str, dict[date, dict[str, object]]] = {key: {} for key in set(signals.values())}
    histories = book_histories(base, strategies, capture=captured)
    timings["signals of every book recomputed for the exports"] = time.perf_counter() - started
    open_returns = realised_open_returns(base[SA12], FUND)
    sessions = sessions_of(open_returns)
    with base[SA12].reading() as store:
        opens = store.at(base[SA12].records()[-1].valuation_time).history(FUND, BarField.OPEN)
    forecasts = {name: forecast_frame(captured[signals[name]], sessions) for name in family}
    for name, book in family.items():
        assert isinstance(book, ArimaGarch)
        histories[name] = joint_history(histories[name], forecasts[name], opens, book)

    paired = {
        name: pair_at_two_sessions(
            pd.Series(frame["mu_h2"]),
            open_returns,
            sessions,
            forecast_variance=pd.Series(frame["return_variance_h2"].astype("float64")),
        )
        for name, frame in forecasts.items()
    }
    own_pairs = paired[SA12].pairs
    rolling = open_returns.rolling(own.estimation_returns).mean()
    means = mean_table(paired[SA12], pd.Series(rolling))
    entries = entry_signals(own_pairs, own.entry_threshold)
    joint = pd.DataFrame.from_dict(
        {
            name: evaluate_joint(
                paired[name].pairs, variance_floor=FORECAST_VARIANCE_FLOOR
            ).definition()
            for name in (SA12, D1, D2)
        },
        orient="index",
    ).rename_axis("book")
    loss = {
        name: joint_losses(paired[name].pairs, variance_floor=FORECAST_VARIANCE_FLOOR)
        for name in (SA12, D1, D2)
    }
    zero = pd.Series(0.0, index=own_pairs.index)
    losses = pd.DataFrame(
        [
            loss_difference_row("SA12 - D1 (variance, same mean)", loss[SA12], loss[D1]),
            loss_difference_row("SA12 - D2 (joint mean and variance)", loss[SA12], loss[D2]),
            loss_difference_row(
                "ARIMA - zero (squared error of the mean)",
                squared_errors(own_pairs),
                squared_errors(own_pairs, zero),
            ),
            loss_difference_row(
                "ARIMA - mean of the window (squared error of the mean)",
                squared_errors(own_pairs),
                squared_errors(own_pairs, pd.Series(rolling)),
            ),
        ]
    )
    evaluation = own_pairs.assign(
        error=own_pairs["realised"] - own_pairs["forecast_mean"],
        joint_loss=loss[SA12],
        squared_error=squared_errors(own_pairs),
        squared_error_zero=squared_errors(own_pairs, zero),
    )
    fills = pd.concat(
        [result.fills().assign(book=name) for name, result in base.items()], ignore_index=True
    )
    stays_frame = episodes(histories[SA12], fills.loc[fills["book"] == SA12])
    stays: dict[str, object] = dict(episode_summary(stays_frame))
    stays["completed"] = (
        sum(1 for still_open in stays_frame["open"] if not still_open) if len(stays_frame) else 0
    )
    quality = operational_quality(forecasts[SA12])
    coverage = {
        "pairs": len(own_pairs),
        "origins": paired[SA12].origins,
        "exclusions": dict(paired[SA12].exclusions),
    }
    comparison = comparison_frame(base, stressed)
    status = hypothesis_status(
        comparison,
        forecast_pairs=len(own_pairs),
        completed_episodes=int(stays["completed"]),  # type: ignore[call-overload]
        quality=quality,
    )
    yearly = yearly_frame({name: result.equity() for name, result in base.items()})

    output: Path = options.output
    output.mkdir(parents=True, exist_ok=True)
    summary.to_csv(output / "summary.csv")
    summary.to_csv(output / "global_metrics.csv")
    stressed_summary.to_csv(output / "summary_costs_x2.csv")
    spread = register["trial_sharpe_std"]
    assert isinstance(register["trials"], int)
    quality_table(
        details,
        trials=register["trials"],
        trial_sharpe_std=float("nan") if spread is None else float(spread),  # type: ignore[arg-type]
    ).to_csv(output / "quality_details.csv")
    forecasts[SA12].to_csv(output / "sa12_forecasts.csv")
    for name in (D1, D2):
        forecasts[name].to_csv(output / f"forecasts_{slug(name)}.csv")
    evaluation.to_csv(output / "sa12_forecast_evaluation.csv")
    means.to_csv(output / "sa12_mean_evaluation.csv")
    joint.to_csv(output / "sa12_joint_evaluation.csv")
    losses.to_csv(output / "sa12_loss_differences.csv", index=False)
    histories[SA12].to_csv(output / "sa12_history.csv")
    base[SA12].orders().to_csv(output / "sa12_orders.csv", index=False)
    base[SA12].fills().to_csv(output / "sa12_fills.csv", index=False)
    base[SA12].rejects().to_csv(output / "sa12_rejects.csv", index=False)
    stays_frame.to_csv(output / "sa12_position_episodes.csv", index=False)
    comparison.to_csv(output / "study_comparisons.csv", index=False)
    yearly.to_csv(output / "yearly.csv")
    equity = {name: result.equity() for name, result in base.items()}
    gross = {f"{name} (gross)": result.equity(Book.GROSS) for name, result in base.items()}
    pd.DataFrame({**equity, **gross}).rename_axis("session_date").to_csv(output / "equity.csv")
    fills.to_csv(output / "fills.csv", index=False)
    for name, history in histories.items():
        history.to_csv(output / f"history_{slug(name)}.csv")
    record = manifest(
        base, strategies, register, stressed_execution.costs, status, quality, timings
    )
    for target in ("manifest.json", "config.json"):
        (output / target).write_text(
            json.dumps(record, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
        )
    (output / "study.md").write_text(
        study_markdown(
            summary,
            stressed_summary,
            comparison,
            quality,
            means,
            joint,
            losses,
            entries,
            stays,
            coverage,
            status,
            register,
            timings,
        ),
        encoding="utf-8",
    )
    (output / "report_extra_SA12.md").write_text(
        report_extra(quality, means, entries, losses, comparison, stays, coverage, status),
        encoding="utf-8",
    )
    print(summary[["rank", "quality", "net_return", "sharpe", "max_drawdown"]].to_string())
    print(comparison[["costs", "control", "sharpe_sa12", "sharpe_control", "sharpe_difference"]])
    print("hypothesis:", *status)
    print(f"wrote {output}; benchmark {BENCHMARK}, references {HELD} and {SPLIT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
