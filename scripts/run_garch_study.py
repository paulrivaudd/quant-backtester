"""Run the SA11 study: GARCH volatility control against its controls and every ETF book.

Every book is run by the same engine on :data:`COMMON_PERIOD`, the period on
which ``SA11`` fits its model on a full window from the first decision, with
100 000 EUR, the costs of the ETF comparison and quantities fixed at the
decision. From the repository root, once the store is filled and the ``stats``
extra installed (``uv sync --extra stats``):

    uv run python scripts/run_garch_study.py --output results/garch_study

The participants are those of ``run_etf_strategies_comparison.py`` - ``SA1``
to ``SA6``, ``SA9``, ``SA10``, ``SA11``, the fund held and the even split -
and one control without a catalogue code: the allocation rule of ``SA11`` on
an EWMA of decay 0.94. ``SA7`` and ``SA8`` are not run: their instruments are
not registered. ``ML1`` is not in the table: its information stops at the end
of 2024, so a common table would have to start in 2025.

Three questions are kept apart, because an answer to one is not an answer to
another:

- the **ranking**: ``QUALITY_V1`` against the fund held, deflated by an
  explicit register of the configurations tried here (:func:`trial_register`);
- the **forecast**: QLIKE of each variance forecast against the next session's
  squared return, read after the fact (``forecast_evaluation.csv``);
- the **economic test** of the registered hypothesis: the net Sharpe ratio and
  the drawdown of ``SA11`` against ``SA6`` and the EWMA control, with a paired
  block bootstrap, and again in a second real run with every cost doubled.

The history of ``ETF_WORLD`` was looked at in every earlier exercise: this is
a retrospective evaluation with chronological forecasts, not an untouched
sample, and the register of trials does not hold the variants tried in those
exercises. The ranking is exploratory in that sense.

What is written: ``summary.csv``, ``quality_details.csv``,
``forecast_diagnostics.csv``, ``forecast_evaluation.csv``,
``forecast_evaluation_summary.csv``, ``forecast_qlike_differences.csv``,
``comparison.csv``, ``yearly.csv``,
``equity.csv``, ``fills.csv``, one ``history_<book>.csv`` per book (the closes,
the signals it read, its weights and its value at every session),
``config.json``, ``study.md`` and five figures.

The tests are in ``tests/scripts/test_run_garch_study.py``.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import statistics
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from run_etf_strategies_comparison import (
    ANALYTICS,
    BENCHMARK,
    COMMON_PERIOD,
    EXECUTION,
    FIGURE_DPI,
    HELD,
    INITIAL_CASH,
    INK,
    MUTED,
    REPOSITORY,
    SPLIT,
    STORE,
    SURFACE,
    UNIVERSE,
    _style,
    books,
    build_runner,
    closes_of,
    indexed,
    quality_details,
    quality_table,
    sessions_of,
    slug,
    summary_row,
)

from quant_backtester.analytics.curves import Book, drawdown_curve
from quant_backtester.analytics.quality import QUALITY_V1, QualityScore, session_sharpe
from quant_backtester.analytics.relative import RelativePerformanceStats
from quant_backtester.analytics.uncertainty import (
    PairedBootstrap,
    PairedStatistic,
    UndefinedStatistic,
    paired_block_bootstrap,
)
from quant_backtester.analytics.volatility_forecast import (
    ForecastEvaluation,
    compare_forecasts,
    pair_forecasts,
    paired_loss_difference,
    qlike_loss,
    qlike_losses,
)
from quant_backtester.backtest.runner import StrategyResult, StrategyRunner
from quant_backtester.execution.costs import CostModel
from quant_backtester.execution.model import ExecutionModel
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.engine import SignalRequest
from quant_backtester.signals.models.garch import ForecastSource, require_arch
from quant_backtester.signals.types import SignalStatus
from quant_backtester.strategies import EwmaVolControl, GarchVolControl, RealizedVolControl
from quant_backtester.strategies.base import Strategy
from quant_backtester.strategies.catalogue import entry

GARCH, VOL_CONTROL = entry("SA11").display_name, entry("SA6").display_name
"""The strategy under study and its main scientific comparator."""

EWMA = "EWMA 0.94 control"
"""The control: the rule of ``SA11`` on an EWMA forecast. No catalogue code."""

FUND = "ETF_WORLD"
"""The fund ``SA11`` and its two controls hold."""

BOOTSTRAP_BLOCK, BOOTSTRAP_DRAWS, BOOTSTRAP_SEED, BOOTSTRAP_LEVEL = 20, 5_000, 20261010, 0.95
"""The paired block bootstrap of a Sharpe difference, fixed before any run."""

QLIKE_VARIANCE_FLOOR = 1e-12
"""Smallest variance QLIKE is evaluated at. A floor of the metric, counted when applied."""

FALLBACK_ALERT_SHARE = 0.05
"""Share of fallback decisions above which the results are not attributed to GARCH alone."""

COST_STRESS = 2.0
"""What every cost is multiplied by in the second real run."""

SUMMARY_COLUMNS = (
    "rank",
    "code",
    "quality",
    "block_market",
    "block_significance",
    "block_risk",
    "block_robustness",
    "block_implementation",
    "net_return",
    "annualised_return",
    "volatility",
    "sharpe",
    "max_drawdown",
    "alpha_vs_market",
    "beta_vs_market",
    "information_ratio_vs_market",
    "costs_eur",
    "turnover_per_year",
    "average_exposure",
    "fills",
    "sessions",
    "first_session",
    "last_session",
    "diagnostics",
)
"""Columns every row of the common table carries first, in this order."""


STUDY_CODES = ("SA1", "SA2", "SA3", "SA4", "SA5", "SA6", "SA9", "SA10", "SA11")
"""The catalogued strategies of this study, fixed on 2026-10-10: a strategy
catalogued later has its own study and does not enter this one's register."""


def participants() -> dict[str, Strategy]:
    """Return every book of the study by display name: the comparison's, and the control.

    The comparison's books as they stood when the study was run - a strategy
    catalogued since is left out, so that the study and its count of trials
    stay reproducible - then the EWMA control.
    """
    kept = {entry(code).display_name for code in STUDY_CODES} | {HELD, SPLIT}
    return {
        **{name: book for name, book in books().items() if name in kept},
        EWMA: EwmaVolControl(),
    }


def doubled(execution: ExecutionModel, factor: float = COST_STRESS) -> ExecutionModel:
    """Return the same execution with the three rates and the commission floor scaled."""
    costs = execution.costs
    return replace(
        execution,
        costs=CostModel(
            commission_rate=factor * costs.commission_rate,
            minimum_commission=factor * costs.minimum_commission,
            half_spread_rate=factor * costs.half_spread_rate,
            slippage_rate=factor * costs.slippage_rate,
        ),
    )


def code_of(name: str) -> str:
    """Return the short code of a book: its catalogue code, or its own name."""
    return name.split(" - ")[0] if " - " in name else name


def trial_register(net: Mapping[str, pd.Series]) -> dict[str, object]:  # type: ignore[type-arg]
    """Return the register of the configurations tried in this research, and their dispersion.

    Parameters
    ----------
    net : Mapping[str, pd.Series]
        Net equity of every book of the study on the common period.

    Returns
    -------
    dict[str, object]
        ``names`` - every strategy configuration examined here, the control
        included; the fund held and the even split are references, not
        trials. ``trials`` - their count. ``sharpes`` - the per-session
        Sharpe ratio of each trial that has one. ``excluded`` - the trials
        whose Sharpe ratio is undefined, kept in the count and left out of the
        dispersion, never read as zero. ``trial_sharpe_std`` - the sample
        standard deviation of the defined ones: zero for a single trial,
        ``None`` when several trials leave fewer than two defined values, in
        which case no significance can be stated. ``complete`` is ``False``:
        the variants tried in the earlier exercises on the same history are
        not in this register.
    """
    names = [name for name in net if name not in (HELD, SPLIT)]
    sharpes = {name: session_sharpe(net[name], ANALYTICS) for name in names}
    defined = {name: value for name, value in sharpes.items() if value is not None}
    spread: float | None
    if len(names) == 1:
        spread = 0.0
    elif len(defined) > 1:
        spread = statistics.stdev(defined.values())
    else:
        spread = None
    return {
        "names": names,
        "trials": len(names),
        "sharpes": defined,
        "excluded": [name for name in names if name not in defined],
        "trial_sharpe_std": spread,
        "complete": False,
    }


def ranking(scores: Mapping[str, float | None]) -> dict[str, int | None]:
    """Return the dense rank of each book by decreasing score, unrounded.

    Parameters
    ----------
    scores : Mapping[str, float | None]
        The quality score per book; ``None`` for a book that is not scored.

    Returns
    -------
    dict[str, int | None]
        ``1`` for the highest score. Exactly equal scores share a rank and the
        next score takes the next rank. A score of zero is ranked, last among
        the ranked; a book without a score has no rank and is out of the
        ranking.
    """
    distinct = sorted({score for score in scores.values() if score is not None}, reverse=True)
    place = {score: position + 1 for position, score in enumerate(distinct)}
    return {name: None if score is None else place[score] for name, score in scores.items()}


def turnover_per_year(result: StrategyResult) -> float:
    """Return the value traded in a year as a multiple of the average net equity."""
    equity = result.equity()
    years = (len(equity) - 1) / ANALYTICS.sessions_per_year
    traded = math.fsum(float(value) for value in result.fills()["traded_value"])
    return traded / float(equity.mean()) / years


def study_row(
    name: str,
    result: StrategyResult,
    benchmark: pd.Series,  # type: ignore[type-arg]
    market: pd.Series,  # type: ignore[type-arg]
    detail: QualityScore | None,
    rank: int | None,
) -> dict[str, object]:
    """Return one book's row of the common table.

    Parameters
    ----------
    name : str
        The book.
    result : StrategyResult
        Its finished run.
    benchmark : pd.Series
        Net equity of ``SA1`` over the same sessions.
    market : pd.Series
        Net equity of the fund held over the same sessions, same costs.
    detail : QualityScore | None
        Its quality score against the fund held; ``None`` for the fund itself.
    rank : int | None
        Its rank; ``None`` when it is not scored.

    Returns
    -------
    dict[str, object]
        The columns of :data:`SUMMARY_COLUMNS`, then the comparison's own.
        Alpha, beta and the information ratio are against the fund held by
        the engine with the same costs, the economic benchmark of the study.
    """
    base = summary_row(result, benchmark)
    measures = {} if detail is None else dict(detail.measures)
    blocks = {} if detail is None else dict(detail.blocks)
    equity = result.equity()
    market_beta: float | None = None
    if detail is not None:
        market_beta = RelativePerformanceStats.from_equity(equity, market, ANALYTICS).beta
    row: dict[str, object] = {
        "rank": rank,
        "code": code_of(name),
        "quality": None if detail is None else detail.score,
        **{f"block_{block}": blocks.get(block) for block in QUALITY_V1.weights},
        "net_return": base["net_return"],
        "annualised_return": base["annualised_return"],
        "volatility": base["volatility"],
        "sharpe": base["sharpe"],
        "max_drawdown": base["max_drawdown"],
        "alpha_vs_market": measures.get("alpha_annualised"),
        "beta_vs_market": market_beta,
        "information_ratio_vs_market": measures.get("information_ratio"),
        "costs_eur": base["costs_eur"],
        "turnover_per_year": turnover_per_year(result),
        "average_exposure": base["average_exposure"],
        "fills": base["fills"],
        "sessions": len(equity),
        "first_session": equity.index[0],
        "last_session": equity.index[-1],
        "diagnostics": "market_fund_not_scored" if detail is None else "|".join(detail.diagnostics),
    }
    for key, value in base.items():
        row.setdefault(key, value)
    return row


def summary_frame(
    results: Mapping[str, StrategyResult], details: Mapping[str, QualityScore | None]
) -> pd.DataFrame:
    """Return the common table, ranked: scored books by decreasing score, then the others.

    Books with exactly equal scores share a rank and are listed by name;
    books that are not scored come last, by name, with an empty rank.
    """
    scores = {name: None if detail is None else detail.score for name, detail in details.items()}
    ranks = ranking(scores)
    benchmark = results[BENCHMARK].equity()
    rows = {
        name: study_row(name, result, benchmark, results[HELD].equity(), details[name], ranks[name])
        for name, result in results.items()
    }
    order = sorted(rows, key=lambda name: (ranks[name] is None, ranks[name] or 0, name))
    frame = pd.DataFrame.from_dict({name: rows[name] for name in order}, orient="index")
    frame["rank"] = frame["rank"].astype("Int64")
    return frame.rename_axis("book")


# --- what each book read -----------------------------------------------------------------


def signal_columns(strategy: Strategy) -> list[tuple[str, SignalRequest | None, object]]:
    """Return ``(signal_id, request, signal)`` for every signal a strategy declares."""
    declared = []
    for item in strategy.required_signals():
        if isinstance(item, SignalRequest):
            declared.append((item.signal.signal_id, item, item.signal))
        else:
            declared.append((item.signal_id, None, item))
    return declared


def book_histories(
    results: Mapping[str, StrategyResult],
    strategies: Mapping[str, Strategy],
    *,
    capture: dict[str, dict[date, dict[str, object]]] | None = None,
) -> dict[str, pd.DataFrame]:
    """Return, per book, the closes, the signals it read, its weights and its value by session.

    Parameters
    ----------
    results : Mapping[str, StrategyResult]
        The finished runs, all on the same sessions and the same store.
    strategies : Mapping[str, Strategy]
        The strategy of each run.
    capture : dict[str, dict[date, dict[str, object]]] | None
        Signal ids whose whole row - value, status and every diagnostic column
        - is wanted, each mapped to a dictionary this function fills by
        session. A signal that carries its diagnostics in its frame is then
        computed once here, not once for its value and once for the rest.

    Returns
    -------
    dict[str, pd.DataFrame]
        One frame per book, indexed by session: ``close_<fund>`` (raw close),
        one column per declared signal and instrument, ``target_<fund>`` and
        ``held_<fund>`` weights, ``net_equity`` and ``gross_equity``. A signal
        without a value at a decision is empty there. The signals are computed
        again by the strategy's own signal objects on a reader fixed at each
        recorded decision instant.

    Raises
    ------
    StoreChanged
        If the store no longer holds what the runs read.
    """
    any_result = next(iter(results.values()))
    closes = closes_of(any_result)
    values: dict[str, dict[date, dict[str, float]]] = {name: {} for name in results}
    with any_result.reading() as store:
        for record in any_result.records():
            if record.decision_time is None:
                continue
            context = SignalContext(
                market=store.at(record.decision_time),
                instruments=any_result.reader.instruments,
                calendars=any_result.reader.calendars,
            )
            computed: dict[tuple[str, tuple[str, ...]], pd.DataFrame] = {}
            for name, strategy in strategies.items():
                row: dict[str, float] = {}
                for signal_id, request, signal in signal_columns(strategy):
                    names = None if request is None else request.names()
                    instruments = tuple(UNIVERSE if names is None else names)
                    key = (json.dumps(signal.definition_json(), sort_keys=True), instruments)  # type: ignore[attr-defined]
                    if key not in computed:
                        computed[key] = signal.compute(context, instruments).frame  # type: ignore[attr-defined]
                        if capture is not None and signal_id in capture:
                            first = computed[key].iloc[0].to_dict()
                            capture[signal_id][record.session_date] = {
                                str(column): value for column, value in first.items()
                            }
                    statuses = computed[key]["status"].to_dict()
                    numbers = computed[key]["value"].to_dict()
                    for instrument_id in instruments:
                        usable = statuses[instrument_id] is SignalStatus.OK
                        row[f"{signal_id}[{instrument_id}]"] = (
                            float(numbers[instrument_id]) if usable else float("nan")
                        )
                values[name][record.session_date] = row
    histories: dict[str, pd.DataFrame] = {}
    for name, result in results.items():
        frame = pd.DataFrame.from_dict(values[name], orient="index")
        parts = [
            pd.DataFrame({f"close_{fund}": series for fund, series in closes.items()}),
            frame,
            result.target_weights().add_prefix("target_"),
            result.weights().add_prefix("held_"),
            result.equity().rename("net_equity"),
            result.equity(Book.GROSS).rename("gross_equity"),
        ]
        joined = pd.concat(parts, axis=1).reindex(result.equity().index)
        histories[name] = joined.rename_axis("session_date")
    return histories


def forecast_diagnostics(result: StrategyResult, strategy: GarchVolControl) -> pd.DataFrame:
    """Return one row per decision of ``SA11``: window, forecast, source, parameters.

    Parameters
    ----------
    result : StrategyResult
        A finished run of ``strategy``.
    strategy : GarchVolControl
        The strategy that was run.

    Returns
    -------
    pd.DataFrame
        ``origin`` (the session decided on), ``target`` left to the pairing,
        ``instrument_id``, the window's status and bounds, the information
        cutoff, the forecast's daily variance and annualised volatility, its
        source, the reason of a fallback, the estimated parameters in decimal
        units, convergence and warnings. Computed again by the strategy's own
        signal on a reader fixed at each recorded decision instant: the same
        pure computation the run decided on, never one that saw its target.

    Raises
    ------
    StoreChanged
        If the store no longer holds what the run read.
    """
    signal = strategy.forecast_signal()
    annualization = signal.config.annualization
    rows: list[dict[str, object]] = []
    with result.reading() as store:
        for record in result.records():
            if record.decision_time is None:
                continue
            context = SignalContext(
                market=store.at(record.decision_time),
                instruments=result.reader.instruments,
                calendars=result.reader.calendars,
            )
            window, forecast = signal.diagnose(context, strategy.instrument_id)
            row: dict[str, object] = {
                "origin": record.session_date,
                "instrument_id": strategy.instrument_id,
                "window_status": window.status.value,
                "fit_start": window.dates[0] if window.dates else None,
                "fit_end": window.dates[-1] if window.dates else None,
                "information_cutoff": record.decision_time.isoformat(),
                "window_closes": len(window.points),
            }
            if forecast is not None:
                row.update(forecast.diagnostics())
                row["annualized_volatility"] = forecast.annualized_volatility(annualization)
            rows.append(row)
    columns = [
        "origin",
        "instrument_id",
        "window_status",
        "fit_start",
        "fit_end",
        "information_cutoff",
        "window_closes",
        "n_returns",
        "forecast_source",
        "fallback_reason",
        "forecast_variance",
        "annualized_volatility",
        "omega_decimal",
        "alpha",
        "beta",
        "nu",
        "persistence",
        "last_filtered_variance",
        "backcast",
        "loglikelihood",
        "converged",
        "iterations",
        "warnings",
    ]
    return pd.DataFrame(rows).reindex(columns=columns)


def fallback_summary(diagnostics: pd.DataFrame) -> dict[str, object]:
    """Return how often the fallback was used among the decisions with a valid window.

    Returns
    -------
    dict[str, object]
        ``valid_windows``, ``garch``, ``fallback``, ``fallback_failed``, the
        ``fallback_share`` among valid windows (``None`` without one),
        ``reasons`` by count, the ``episodes`` - runs of consecutive fallback
        decisions, as ``(first, last, decisions)`` - and ``reserve``: whether
        the share exceeds :data:`FALLBACK_ALERT_SHARE`. A diagnostic, never a
        switch on the positions.
    """
    valid = diagnostics.loc[diagnostics["window_status"] == SignalStatus.OK.value]
    source = valid["forecast_source"]
    fallen = source.isin([ForecastSource.EWMA_FALLBACK.value, ForecastSource.FALLBACK_FAILED.value])
    episodes: list[tuple[str, str, int]] = []
    run: list[date] = []
    for origin, is_fallback in zip(valid["origin"], fallen, strict=True):
        if is_fallback:
            run.append(origin)
        elif run:
            episodes.append((str(run[0]), str(run[-1]), len(run)))
            run = []
    if run:
        episodes.append((str(run[0]), str(run[-1]), len(run)))
    share = float(fallen.mean()) if len(valid) else None
    return {
        "decisions": len(diagnostics),
        "valid_windows": len(valid),
        "garch": int((source == ForecastSource.GARCH.value).sum()),
        "fallback": int((source == ForecastSource.EWMA_FALLBACK.value).sum()),
        "fallback_failed": int((source == ForecastSource.FALLBACK_FAILED.value).sum()),
        "fallback_share": share,
        "reasons": {
            str(reason): int(count)
            for reason, count in valid.loc[fallen, "fallback_reason"].value_counts().items()
        },
        "episodes": episodes,
        "reserve": share is not None and share > FALLBACK_ALERT_SHARE,
    }


def daily_variance(annualized_volatility: pd.Series) -> pd.Series:  # type: ignore[type-arg]
    """Return the daily variance an annualised volatility stands for."""
    return annualized_volatility**2 / ANALYTICS.sessions_per_year


def forecast_pairs(
    diagnostics: pd.DataFrame,
    histories: Mapping[str, pd.DataFrame],
    session_returns: pd.Series,  # type: ignore[type-arg]
) -> dict[str, pd.DataFrame]:
    """Return the forecast-realisation pairs of each variance forecast compared.

    Parameters
    ----------
    diagnostics : pd.DataFrame
        What :func:`forecast_diagnostics` returned.
    histories : Mapping[str, pd.DataFrame]
        What :func:`book_histories` returned: the EWMA control's and ``SA6``'s
        signals are read from it.
    session_returns : pd.Series
        Realised daily log return of the fund by session, on adjusted closes.

    Returns
    -------
    dict[str, pd.DataFrame]
        ``GARCH accepted`` (the origins whose fit was used), ``SA11 policy``
        (GARCH or its fallback, every valid origin), ``EWMA 0.94`` and ``SA6
        estimator`` - the larger of its two realised volatilities, converted
        to a daily variance, without the allocation floor.
    """
    sessions = sessions_of(session_returns)
    by_origin = diagnostics.set_index("origin")
    policy = by_origin["forecast_variance"].astype("float64")
    accepted = policy.where(by_origin["forecast_source"] == ForecastSource.GARCH.value)
    ewma_history = histories[EWMA]
    ewma_column = next(column for column in ewma_history if column.startswith("ewma"))
    vol_history = histories[VOL_CONTROL]
    vol_columns = [column for column in vol_history if column.startswith("volatility_")]
    larger = pd.Series(vol_history[vol_columns].max(axis=1, skipna=False))
    forecasts: dict[str, pd.Series] = {  # type: ignore[type-arg]
        "GARCH accepted": accepted,
        "SA11 policy": policy,
        "EWMA 0.94": daily_variance(pd.Series(ewma_history[ewma_column])),
        "SA6 estimator": daily_variance(larger),
    }
    return {
        name: pair_forecasts(series.dropna(), session_returns, sessions)
        for name, series in forecasts.items()
    }


def evaluation_frame(pairs: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    """Return every pair side by side: one row per origin, a variance and a QLIKE per forecast."""
    parts = []
    for name, frame in pairs.items():
        loss = [
            qlike_loss(variance, outcome, variance_floor=QLIKE_VARIANCE_FLOOR)
            for variance, outcome in zip(
                frame["forecast_variance"], frame["realised_return"], strict=True
            )
        ]
        key = slug(name)
        parts.append(
            pd.DataFrame(
                {f"variance_{key}": frame["forecast_variance"], f"qlike_{key}": loss},
                index=frame.index,
            )
        )
    widest = max(pairs.values(), key=len)
    base = widest[["target", "realised_return"]]
    return pd.concat([base, *parts], axis=1).rename_axis("origin")


def evaluation_summary(pairs: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    """Return the losses of each forecast on its own origins and on GARCH's accepted ones."""
    shared = list(pairs["GARCH accepted"].index)
    everywhere = [
        origin for origin in shared if all(origin in frame.index for frame in pairs.values())
    ]
    scopes: dict[str, Mapping[str, ForecastEvaluation]] = {
        "own origins": compare_forecasts(pairs, variance_floor=QLIKE_VARIANCE_FLOOR),
        "origins of accepted GARCH fits": compare_forecasts(
            pairs, variance_floor=QLIKE_VARIANCE_FLOOR, origins=everywhere
        ),
    }
    rows = [
        {"scope": scope, "forecast": name, **evaluation.definition()}
        for scope, evaluations in scopes.items()
        for name, evaluation in evaluations.items()
    ]
    return pd.DataFrame(rows)


QLIKE_COMPARISONS = (
    ("GARCH accepted", "EWMA 0.94"),
    ("GARCH accepted", "SA6 estimator"),
    ("EWMA 0.94", "SA6 estimator"),
)
"""The pairs of forecasts whose difference of mean QLIKE is given an interval."""


def qlike_difference_frame(pairs: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    """Return the difference of mean QLIKE between forecasts, with a bootstrap interval.

    Returns
    -------
    pd.DataFrame
        One row per pair of :data:`QLIKE_COMPARISONS`, on the origins both
        forecasts have: the mean of the paired differences (negative when the
        first forecast is the better one) and its moving-block bootstrap
        interval, under the conventions of the Sharpe bootstrap. A lower mean
        QLIKE whose interval includes zero is an observed difference, not a
        demonstrated one.
    """
    losses = {
        name: qlike_losses(frame, variance_floor=QLIKE_VARIANCE_FLOOR)
        for name, frame in pairs.items()
    }
    rows = []
    for first, second in QLIKE_COMPARISONS:
        measured = paired_loss_difference(
            losses[first],
            losses[second],
            block=BOOTSTRAP_BLOCK,
            draws=BOOTSTRAP_DRAWS,
            seed=BOOTSTRAP_SEED,
            level=BOOTSTRAP_LEVEL,
        )
        rows.append({"first": first, "second": second, **measured.definition()})
    return pd.DataFrame(rows)


# --- the economic test -------------------------------------------------------------------


def sharpe_difference(
    strategy: pd.Series,  # type: ignore[type-arg]
    control: pd.Series,  # type: ignore[type-arg]
) -> PairedBootstrap | str:
    """Return the bootstrapped Sharpe difference, or the reason it is refused."""
    try:
        return paired_block_bootstrap(
            strategy,
            control,
            statistic=PairedStatistic.SHARPE,
            block=BOOTSTRAP_BLOCK,
            draws=BOOTSTRAP_DRAWS,
            seed=BOOTSTRAP_SEED,
            level=BOOTSTRAP_LEVEL,
            config=ANALYTICS,
        )
    except UndefinedStatistic as refused:
        return f"refused: {refused}"


def comparison_frame(
    base: Mapping[str, StrategyResult], stressed: Mapping[str, StrategyResult]
) -> pd.DataFrame:
    """Return ``SA11`` against each control, at both cost levels.

    Returns
    -------
    pd.DataFrame
        One row per control and cost level: the two net Sharpe ratios, returns
        and maximum drawdowns, their differences, and the paired block
        bootstrap of the Sharpe difference - or the reason it was refused,
        never a zero in its place.
    """
    rows: list[dict[str, object]] = []
    for label, results in (("x1", base), (f"x{COST_STRESS:g}", stressed)):
        own = results[GARCH].report().net
        for control in (VOL_CONTROL, EWMA, HELD):
            other = results[control].report().net
            outcome = sharpe_difference(results[GARCH].equity(), results[control].equity())
            row: dict[str, object] = {
                "costs": label,
                "control": control,
                "sharpe_sa11": own.sharpe_ratio,
                "sharpe_control": other.sharpe_ratio,
                "net_return_sa11": own.total_return,
                "net_return_control": other.total_return,
                "return_difference": own.total_return - other.total_return,
                "max_drawdown_sa11": own.drawdown.depth,
                "max_drawdown_control": other.drawdown.depth,
                "drawdown_difference": own.drawdown.depth - other.drawdown.depth,
            }
            if isinstance(outcome, PairedBootstrap):
                row.update(
                    {
                        "sharpe_difference": outcome.estimate,
                        "interval_low": outcome.low,
                        "interval_high": outcome.high,
                        "interval_level": outcome.level,
                        "bootstrap": "ok",
                    }
                )
            else:
                row["bootstrap"] = outcome
            rows.append(row)
    return pd.DataFrame(rows)


def verdict(comparison: pd.DataFrame) -> tuple[str, list[str]]:
    """Return the outcome of the registered hypothesis and the reasons, from the comparison.

    Returns
    -------
    tuple[str, list[str]]
        ``REFUTED`` when a criterion of refutation is met at either cost
        level, ``UNCERTAIN`` when none is met and a bootstrap interval of a
        Sharpe difference includes zero or was refused, ``SUPPORTED``
        otherwise. The fund held is reported and is not part of the test.
    """
    reasons: list[str] = []
    uncertain: list[str] = []
    tested = comparison.loc[comparison["control"].isin([VOL_CONTROL, EWMA])]
    for row in tested.to_dict(orient="records"):
        where = f"{row['control']} at costs {row['costs']}"
        if not row["sharpe_sa11"] > row["sharpe_control"]:
            reasons.append(f"net Sharpe not above {where}")
        if row["max_drawdown_sa11"] < row["max_drawdown_control"]:
            reasons.append(f"maximum drawdown deeper than {where}")
        if row["bootstrap"] != "ok":
            uncertain.append(f"Sharpe difference against {where}: bootstrap {row['bootstrap']}")
        elif row["interval_low"] <= 0.0 <= row["interval_high"]:
            uncertain.append(f"Sharpe difference against {where}: interval includes zero")
    if reasons:
        return "REFUTED", reasons + uncertain
    if uncertain:
        return "UNCERTAIN", uncertain
    return "SUPPORTED", []


def yearly_frame(curves: Mapping[str, pd.Series]) -> pd.DataFrame:  # type: ignore[type-arg]
    """Return each book's net return by calendar year, every year of the period.

    The first year starts at the first session of the period and the last one
    ends at its last session: both are partial years and are labelled by
    their sessions, in the ``sessions`` row, so that none is read as a full one.
    """
    columns: dict[str, dict[str, float]] = {}
    counts: dict[str, float] = {}
    for name, curve in curves.items():
        days = sessions_of(curve)
        row: dict[str, float] = {}
        for year in sorted({day.year for day in days}):
            inside = [day for day in days if day.year == year]
            before = [day for day in days if day.year < year]
            start = curve.loc[before[-1]] if before else curve.loc[inside[0]]
            row[str(year)] = float(curve.loc[inside[-1]] / start) - 1.0
            counts[str(year)] = float(len(inside))
        columns[name] = row
    frame = pd.DataFrame.from_dict(columns, orient="index")
    frame.loc["sessions"] = counts
    return frame.rename_axis("book")


# --- figures -----------------------------------------------------------------------------

PALETTE = {GARCH: "#2a78d6", VOL_CONTROL: "#eb6834", EWMA: "#2f855a", HELD: "#0b0b0b"}
"""The four curves of the dedicated comparison, the same in every figure."""


def _figure(title: str, note: str, rows: int = 1) -> tuple[Figure, list]:  # type: ignore[type-arg]
    """Return a figure of stacked panels on one time axis."""
    figure = Figure(figsize=(13, 4.4 * rows + 0.8), layout="constrained", facecolor=SURFACE)
    panels = list(np.atleast_1d(figure.subplots(rows, 1, sharex=True)))
    for axes in panels:
        _style(axes)
    figure.suptitle(title, x=0.01, ha="left", fontsize=14, color=INK, fontweight="bold")
    figure.supxlabel(note, x=0.01, ha="left", fontsize=9, color=MUTED)
    return figure, panels


def study_figures(
    results: Mapping[str, StrategyResult],
    histories: Mapping[str, pd.DataFrame],
    diagnostics: pd.DataFrame,
) -> dict[str, Figure]:
    """Return the five figures of the study, by file name.

    Net equity of every book; drawdowns of the four books of the dedicated
    comparison; the fund's weight in ``SA11`` and its two controls; the three
    volatility estimates with the fallback days marked; cumulative costs.
    """
    figures: dict[str, Figure] = {}
    figure, (axes,) = _figure(
        "Net equity on the common period, rebased to 100",
        "Logarithmic scale. Net of costs; cash earns nothing. Grey: the other books.",
    )
    axes.set_yscale("log")
    for name, result in results.items():
        curve = indexed(result.equity())
        colour = PALETTE.get(name, "#b5b4ae")
        width = 2.0 if name in PALETTE else 0.9
        axes.plot(list(curve.index), list(curve), color=colour, linewidth=width, label=name)
    axes.legend(loc="upper left", fontsize=8, frameon=False, labelcolor=MUTED, ncols=2)
    figures["equity_common.png"] = figure

    figure, (axes,) = _figure(
        "Drawdown of SA11, its two controls and the fund held",
        "Percent below the running peak of net equity.",
    )
    for name, colour in PALETTE.items():
        depth = drawdown_curve(results[name].equity()) * 100.0
        axes.plot(list(depth.index), list(depth), color=colour, linewidth=1.4, label=name)
    axes.legend(loc="lower left", fontsize=9, frameon=False, labelcolor=MUTED)
    figures["drawdowns_vol_controls.png"] = figure

    figure, (axes,) = _figure(
        "Weight of ETF_WORLD held by SA11 and its two controls",
        "Percent of net equity at each valuation; the rest is cash.",
    )
    for name in (GARCH, VOL_CONTROL, EWMA):
        held = histories[name][f"held_{FUND}"].fillna(0.0) * 100.0
        axes.plot(list(held.index), list(held), color=PALETTE[name], linewidth=1.2, label=name)
    axes.set_ylim(0.0, 102.0)
    axes.legend(loc="lower left", fontsize=9, frameon=False, labelcolor=MUTED)
    figures["weights_vol_controls.png"] = figure

    figure, (axes,) = _figure(
        "Annualised volatility estimated at each decision",
        "GARCH: one-step forecast (or its EWMA fallback, marked). EWMA 0.94. SA6: the larger "
        "of its 20- and 60-return realised volatilities. Dashed: the 12% target.",
    )
    by_origin = diagnostics.set_index("origin")
    garch = by_origin["annualized_volatility"].astype("float64") * 100.0
    axes.plot(list(garch.index), list(garch), color=PALETTE[GARCH], linewidth=1.3, label="SA11")
    fallen = by_origin.index[by_origin["forecast_source"] == ForecastSource.EWMA_FALLBACK.value]
    axes.scatter(
        list(fallen),
        list(garch.loc[fallen]),
        color="#c53030",
        s=18,
        zorder=3,
        label=f"fallback ({len(fallen)})",
    )
    ewma_history = histories[EWMA]
    ewma_column = next(column for column in ewma_history if column.startswith("ewma"))
    ewma = ewma_history[ewma_column] * 100.0
    axes.plot(list(ewma.index), list(ewma), color=PALETTE[EWMA], linewidth=1.0, label="EWMA 0.94")
    vol_history = histories[VOL_CONTROL]
    larger = (
        vol_history[[column for column in vol_history if column.startswith("volatility_")]].max(
            axis=1, skipna=False
        )
        * 100.0
    )
    axes.plot(
        list(larger.index), list(larger), color=PALETTE[VOL_CONTROL], linewidth=1.0, label="SA6"
    )
    axes.axhline(12.0, color=MUTED, linewidth=0.8, linestyle="--")
    axes.set_ylabel("% a year", fontsize=9, color=MUTED)
    axes.legend(loc="upper right", fontsize=9, frameon=False, labelcolor=MUTED)
    figures["volatility_estimates.png"] = figure

    figure, (axes,) = _figure("Cumulative costs paid by each book", "EUR, on 100 000 EUR at start.")
    for name, result in results.items():
        paid = result.costs()["total_cost"].cumsum()
        colour = PALETTE.get(name, "#b5b4ae")
        axes.plot(list(paid.index), list(paid), color=colour, linewidth=1.3, label=name)
    axes.legend(loc="upper left", fontsize=8, frameon=False, labelcolor=MUTED, ncols=2)
    figures["cumulative_costs.png"] = figure
    return figures


# --- the written study -------------------------------------------------------------------


def _cell(value: object, pattern: str) -> str:
    """Return one cell of a table, ``n/a`` for a figure that does not exist."""
    if value is None or value is pd.NA:
        return "n/a"
    if isinstance(value, float) and math.isnan(value):
        return "n/a"
    return pattern.format(value)


def markdown_table(frame: pd.DataFrame, columns: Sequence[tuple[str, str, str]]) -> str:
    """Return a frame as a Markdown table of ``(column, heading, pattern)``, index first."""
    head = "| " + " | ".join([str(frame.index.name or ""), *[h for _, h, _ in columns]]) + " |"
    rule = "|" + "---|" * (len(columns) + 1)
    lines = [head, rule]
    for name, row in frame.iterrows():
        cells = [_cell(row[column], pattern) for column, _, pattern in columns]
        lines.append("| " + " | ".join([str(name), *cells]) + " |")
    return "\n".join(lines)


def study_markdown(
    summary: pd.DataFrame,
    stressed_summary: pd.DataFrame,
    comparison: pd.DataFrame,
    evaluation: pd.DataFrame,
    qlike_differences: pd.DataFrame,
    fallback: Mapping[str, object],
    yearly: pd.DataFrame,
    register: Mapping[str, object],
    timings: Mapping[str, float],
) -> str:
    """Return the written study: ranking, dedicated comparison, forecasts, decision, limits."""
    outcome, reasons = verdict(comparison)
    differences = qlike_differences.set_index(
        qlike_differences["first"].astype(str) + " - " + qlike_differences["second"].astype(str)
    ).rename_axis("difference of mean QLIKE")
    first, last = summary["first_session"].iloc[0], summary["last_session"].iloc[0]
    ranked = [
        ("rank", "rank", "{}"),
        ("quality", "score", "{:.1%}"),
        ("block_market", "market", "{:.2f}"),
        ("block_significance", "signif.", "{:.2f}"),
        ("block_risk", "risk", "{:.2f}"),
        ("block_robustness", "robust.", "{:.2f}"),
        ("block_implementation", "implem.", "{:.2f}"),
        ("net_return", "net", "{:+.1%}"),
        ("annualised_return", "net/yr", "{:+.2%}"),
        ("volatility", "vol", "{:.1%}"),
        ("sharpe", "Sharpe", "{:+.2f}"),
        ("max_drawdown", "max DD", "{:.1%}"),
        ("alpha_vs_market", "alpha/yr", "{:+.2%}"),
        ("beta_vs_market", "beta", "{:.2f}"),
        ("information_ratio_vs_market", "IR", "{:+.2f}"),
        ("costs_eur", "costs EUR", "{:,.0f}"),
        ("turnover_per_year", "turnover/yr", "{:.2f}"),
        ("average_exposure", "expo", "{:.0%}"),
    ]
    dedicated = comparison.set_index(
        comparison["costs"].astype(str) + " vs " + comparison["control"].astype(str)
    ).rename_axis("costs vs control")
    forecast = evaluation.set_index(
        evaluation["scope"].astype(str) + " / " + evaluation["forecast"].astype(str)
    ).rename_axis("scope / forecast")
    share = fallback["fallback_share"]
    lines = [
        "# SA11 - GARCH vol control: retrospective study",
        "",
        f"Common period {first} to {last}, {int(summary['sessions'].iloc[0])} sessions, "
        f"{INITIAL_CASH:,.0f} EUR, costs of the ETF comparison, quantities fixed at the "
        "decision, cash unpaid. A retrospective evaluation with chronological forecasts: "
        "the history was looked at before, so this is not an untouched sample.",
        "",
        "## Ranking (QUALITY_V1, against ETF_WORLD bought and held)",
        "",
        markdown_table(summary, ranked),
        "",
        f"Deflated by {register['trials']} trials (dispersion of per-session Sharpe ratios "
        f"{_cell(register['trial_sharpe_std'], '{:.5f}')}). "
        "The register holds the configurations run here "
        "and not the variants of earlier exercises: the ranking is exploratory. The score "
        "is a composite index, not a probability of making money. A book without a score "
        "has no rank.",
        "",
        f"## The same table with every cost paid x{COST_STRESS:g} (second real run)",
        "",
        markdown_table(stressed_summary, ranked),
        "",
        "## SA11 against its controls",
        "",
        markdown_table(
            dedicated,
            [
                ("sharpe_sa11", "Sharpe SA11", "{:+.3f}"),
                ("sharpe_control", "Sharpe control", "{:+.3f}"),
                ("sharpe_difference", "difference", "{:+.3f}"),
                ("interval_low", "95% low", "{:+.3f}"),
                ("interval_high", "95% high", "{:+.3f}"),
                ("return_difference", "net return diff.", "{:+.2%}"),
                ("max_drawdown_sa11", "max DD SA11", "{:.2%}"),
                ("max_drawdown_control", "max DD control", "{:.2%}"),
                ("bootstrap", "bootstrap", "{}"),
            ],
        ),
        "",
        f"Paired block bootstrap: blocks of {BOOTSTRAP_BLOCK} sessions, {BOOTSTRAP_DRAWS} "
        f"draws, seed {BOOTSTRAP_SEED}, {BOOTSTRAP_LEVEL:.0%} interval. It is conditional on "
        "the experiment examined and carries neither the uncertainty of the estimation nor "
        "that of having chosen the rule.",
        "",
        "## Forecast of risk (ex post, close to close)",
        "",
        markdown_table(
            forecast,
            [
                ("pairs", "pairs", "{:.0f}"),
                ("qlike", "QLIKE", "{:.4f}"),
                ("variance_mse", "variance MSE", "{:.3e}"),
                ("mean_ratio", "mean r2/q", "{:.3f}"),
                ("residual_std", "std z", "{:.3f}"),
                ("residual_kurtosis", "kurtosis z", "{:.2f}"),
                ("residual_beyond_two", "|z|>2", "{:.1%}"),
                ("floor_applications", "floored", "{:.0f}"),
            ],
        ),
        "",
        "QLIKE = log(q) + r2/q, lower is better; q is floored at "
        f"{QLIKE_VARIANCE_FLOOR:g} for the metric only. One squared daily return is a very "
        "noisy proxy of a variance. QLIKE measures the close-to-close forecast, not the "
        "profit of an allocation filled at the open. It is a loss, negative here because "
        "the variances are far below one; it is not a return.",
        "",
        markdown_table(
            differences,
            [
                ("pairs", "pairs", "{:.0f}"),
                ("estimate", "mean difference", "{:+.4f}"),
                ("low", "95% low", "{:+.4f}"),
                ("high", "95% high", "{:+.4f}"),
                ("excludes_zero", "excludes zero", "{}"),
            ],
        ),
        "",
        "Paired differences of QLIKE on shared origins, negative when the first forecast is "
        f"the better one; moving-block bootstrap, blocks of {BOOTSTRAP_BLOCK} origins, "
        f"{BOOTSTRAP_DRAWS} draws, seed {BOOTSTRAP_SEED}. A lowest mean QLIKE whose interval "
        "includes zero is the best one observed, not a demonstrated superiority. The "
        "standardised residuals keep fat tails under every forecast (kurtosis above 3).",
        "",
        "## Fallback",
        "",
        f"{fallback['valid_windows']} decisions had a valid window: {fallback['garch']} used "
        f"the GARCH fit, {fallback['fallback']} the EWMA fallback, "
        f"{fallback['fallback_failed']} had no usable fallback. Fallback share: "
        f"{_cell(share, '{:.2%}')}. Reasons: {fallback['reasons'] or 'none'}. Episodes: "
        f"{fallback['episodes'] or 'none'}.",
        (
            "**Reserve:** the share is above 5%, so the results are those of GARCH with its "
            "fallback and are not attributed to GARCH alone."
            if fallback["reserve"]
            else "The share is at or below 5%: no reserve on attributing the results to GARCH."
        ),
        "",
        "## Net return by calendar year",
        "",
        markdown_table(
            yearly.drop(index="sessions"),
            [(column, column, "{:+.1%}") for column in yearly.columns],
        ),
        "",
        "Sessions of each year inside the period: "
        + ", ".join(f"{column}: {count:.0f}" for column, count in yearly.loc["sessions"].items())
        + ". The first and the last year are partial.",
        "",
        "## Decision on the registered hypothesis (`sa11_garch_vol_control`)",
        "",
        f"**{outcome}.**",
        *[f"- {reason}" for reason in reasons],
        "",
        (
            "`REFUTED` is an operational verdict: a criterion of refutation written before "
            "the run is met - a net Sharpe ratio not above a control's, or a deeper maximum "
            "drawdown. It is not a statistical proof that this configuration is inferior: "
            "where an interval of a Sharpe difference includes zero, the two books are not "
            "told apart at that level, and the lines above say where that is the case. Nor "
            "does it say anything of GARCH models in general. GARCH did not clearly beat "
            "the simple rules after costs, so the simple rules are kept; a better likelihood "
            "or a lower QLIKE alone does not justify the strategy."
            if outcome != "SUPPORTED"
            else "SA11 beat both controls after costs, at both cost levels, with intervals "
            "that exclude zero."
        ),
        "",
        "## Limits",
        "",
        "- The store is not a set of provider vintages: restated closes are what a decision "
        "read, as far as the store can say.",
        "- The forecast covers close to close and orders are filled at the next open.",
        "- A prospective check starts at the first XPAR session after 2026-10-10 with this "
        "configuration frozen; it does not exist yet.",
        "- SA7 and SA8 were not run (instruments not registered). ML1 is reported apart.",
        "",
        "## Timings",
        "",
        *[f"- {label}: {seconds:.1f} s" for label, seconds in timings.items()],
        "",
    ]
    return "\n".join(lines)


def configuration(
    results: Mapping[str, StrategyResult],
    strategies: Mapping[str, Strategy],
    register: Mapping[str, object],
    stressed: ExecutionModel,
) -> dict[str, object]:
    """Return everything the study depends on, serialisable: code, data, costs, trials."""
    reference = results[GARCH]
    lock = (REPOSITORY / "uv.lock").read_bytes()
    packages = ("numpy", "scipy", "pandas", "arch", "statsmodels", "matplotlib")
    return {
        "study": "sa11_garch_vol_control",
        "hypothesis_id": "sa11_garch_vol_control",
        "period": {"start": str(reference.start), "end": str(reference.end)},
        "initial_cash": INITIAL_CASH,
        "universe": list(UNIVERSE),
        "analytics": ANALYTICS.definition(),
        "execution": reference.configuration["execution"],
        "execution_stressed": {"factor": COST_STRESS, "costs": str(stressed.costs)},
        "quality_rules": QUALITY_V1.definition(),
        "bootstrap": {
            "block": BOOTSTRAP_BLOCK,
            "draws": BOOTSTRAP_DRAWS,
            "seed": BOOTSTRAP_SEED,
            "level": BOOTSTRAP_LEVEL,
        },
        "qlike_variance_floor": QLIKE_VARIANCE_FLOOR,
        "fallback_alert_share": FALLBACK_ALERT_SHARE,
        "trial_register": dict(register),
        "source": reference.source.definition(),
        "data_state": reference.data_state.digest,
        "environment": reference.configuration["environment"],
        "lockfile_sha256": hashlib.sha256(lock).hexdigest(),
        "versions": {name: importlib.metadata.version(name) for name in packages},
        "strategies": {name: strategy.definition() for name, strategy in strategies.items()},
        "run_ids": {name: result.run_id for name, result in results.items()},
    }


def run_all(runner: StrategyRunner, strategies: Mapping[str, Strategy], label: str) -> dict:  # type: ignore[type-arg]
    """Run every book on the common period and return the results by name."""
    results: dict[str, StrategyResult] = {}
    for name, strategy in strategies.items():
        print(f"running {name} ({label}) ...", file=sys.stderr)
        results[name] = runner.run(strategy, UNIVERSE, *COMMON_PERIOD)
    return results


def scored(results: Mapping[str, StrategyResult]) -> tuple[dict, dict]:  # type: ignore[type-arg]
    """Return the quality details of a set of runs and the register they were deflated by."""
    net = {name: result.equity() for name, result in results.items()}
    gross = {name: result.equity(Book.GROSS) for name, result in results.items()}
    register = trial_register(net)
    spread = register["trial_sharpe_std"]
    if spread is None:
        # Several trials and no dispersion to estimate: no significance is made up.
        return dict.fromkeys(net), register
    assert isinstance(spread, float) and isinstance(register["trials"], int)
    details = quality_details(net, gross, trials=register["trials"], trial_sharpe_std=spread)
    return details, register


def main(arguments: Sequence[str] | None = None) -> int:
    """Run the study and write every export."""
    parser = argparse.ArgumentParser(description="Run the SA11 GARCH volatility control study.")
    parser.add_argument("--output", type=Path, default=Path("results/garch_study"))
    parser.add_argument("--store", type=Path, default=STORE)
    options = parser.parse_args(arguments)
    require_arch()

    strategies = participants()
    garch = strategies[GARCH]
    assert isinstance(garch, GarchVolControl)
    assert isinstance(strategies[VOL_CONTROL], RealizedVolControl)
    timings: dict[str, float] = {}

    runner = build_runner(options.store)
    started = time.perf_counter()
    base = run_all(runner, strategies, "costs x1")
    timings["every run at costs x1"] = time.perf_counter() - started
    stressed_execution = doubled(EXECUTION)
    started = time.perf_counter()
    stressed = run_all(replace(runner, execution=stressed_execution), strategies, "costs x2")
    timings[f"every run at costs x{COST_STRESS:g}"] = time.perf_counter() - started

    details, register = scored(base)
    stressed_details, _ = scored(stressed)
    summary = summary_frame(base, details)
    stressed_summary = summary_frame(stressed, stressed_details)

    # Everything read back from the store is read before the first file is
    # written: a store that changed since the runs stops the export whole.
    started = time.perf_counter()
    diagnostics = forecast_diagnostics(base[GARCH], garch)
    timings["GARCH calibration alone, one fit per decision"] = time.perf_counter() - started
    histories = book_histories(base, strategies)
    with base[GARCH].reading() as store:
        adjusted = store.at(base[GARCH].records()[-1].valuation_time).adjusted_history(FUND)
    session_returns = np.log(adjusted / adjusted.shift(1)).dropna()
    pairs = forecast_pairs(diagnostics, histories, session_returns)
    evaluation = evaluation_summary(pairs)
    qlike_differences = qlike_difference_frame(pairs)
    comparison = comparison_frame(base, stressed)
    fallback = fallback_summary(diagnostics)
    yearly = yearly_frame({name: result.equity() for name, result in base.items()})
    figures = study_figures(base, histories, diagnostics)

    output: Path = options.output
    output.mkdir(parents=True, exist_ok=True)
    summary.to_csv(output / "summary.csv")
    stressed_summary.to_csv(output / "summary_costs_x2.csv")
    spread = register["trial_sharpe_std"]
    assert isinstance(register["trials"], int)
    quality_table(
        details,
        trials=register["trials"],
        trial_sharpe_std=float("nan") if spread is None else float(spread),  # type: ignore[arg-type]
    ).to_csv(output / "quality_details.csv")
    diagnostics.to_csv(output / "forecast_diagnostics.csv", index=False)
    evaluation_frame(pairs).to_csv(output / "forecast_evaluation.csv")
    evaluation.to_csv(output / "forecast_evaluation_summary.csv", index=False)
    qlike_differences.to_csv(output / "forecast_qlike_differences.csv", index=False)
    comparison.to_csv(output / "comparison.csv", index=False)
    yearly.to_csv(output / "yearly.csv")
    equity = {name: result.equity() for name, result in base.items()}
    gross = {f"{name} (gross)": result.equity(Book.GROSS) for name, result in base.items()}
    pd.DataFrame({**equity, **gross}).rename_axis("session_date").to_csv(output / "equity.csv")
    pd.concat(
        [result.fills().assign(book=name) for name, result in base.items()], ignore_index=True
    ).to_csv(output / "fills.csv", index=False)
    for name, history in histories.items():
        history.to_csv(output / f"history_{slug(name)}.csv")
    config = configuration(base, strategies, register, stressed_execution)
    config["fallback"] = dict(fallback)
    config["timings_seconds"] = timings
    (output / "config.json").write_text(
        json.dumps(config, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    (output / "study.md").write_text(
        study_markdown(
            summary,
            stressed_summary,
            comparison,
            evaluation,
            qlike_differences,
            fallback,
            yearly,
            register,
            timings,
        ),
        encoding="utf-8",
    )
    for name, figure in figures.items():
        figure.savefig(output / name, dpi=FIGURE_DPI, facecolor=SURFACE)

    print(summary[["rank", "quality", "net_return", "sharpe", "max_drawdown"]].to_string())
    print(comparison.to_string())
    print("hypothesis:", *verdict(comparison))
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
