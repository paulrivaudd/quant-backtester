"""Run the SA13 study: a neural additive model on a log-signature, against its controls.

The models are calibrated first, one per variant and per month, each on what was
known at the evening of the last session of the month before; the schedules of
frozen models are then handed to the books, and every book is run by the same
engine on :data:`STUDY_PERIOD` - the months for which the store lets a model be
calibrated - with 100 000 EUR, the costs of the ETF comparison and quantities
fixed at the decision. The book is continuous: a new month is a new model, never
a new portfolio. From the repository root, once the store is filled and the
``ml``, ``stats`` and ``signatures`` extras are installed:

    OMP_NUM_THREADS=1 uv run python scripts/run_signature_study.py \
        --output results/signature_study

One thread is asked for because the last digits of a fit move with the number of
threads the linear algebra uses; the setting is recorded in the manifest.
``--start`` and ``--end`` state another period, for a check of the plumbing.

The participants are the books of ``run_etf_strategies_comparison.py`` re-run on
this period, ``SA13``, and eight controls that carry no catalogue code:

- **C0**, the same models, the same availability and the same sizing with the
  direction filter always on: what the timing learnt is worth - the registered
  economic hypothesis;
- **C1**, Ridge on the same 13 coefficients: what the neurons add;
- **C2**, the additive model on order 2 (5 coefficients): what order 3 adds;
- **C3**, the additive model with the volume channel at zero: what volume adds;
- **C4**, the additive model on nine classical indicators: what the signature
  adds as a representation;
- **C5**, Ridge on the raw trajectory (120 values): what the compression adds;
- **C6** and **C7**, the additive model and Ridge on the log-signatures of the
  World fund and of the S&P 500 PEA fund (26 coefficients): what a second
  explanatory process adds.

The forecasts are judged on the return they were made for - from the open after
the decision to the open after that, corporate actions by the engine's
convention - and the books on their net equity valued at the close. ``ML1`` is
left out: its artifacts were calibrated on a period this one overlaps. The
gradient-boosted variant of the specification is not developed.

The history was looked at before: this is a retrospective evaluation with a
sequential, causal re-estimation. The register of trials holds the
configurations run here and not the variants of earlier exercises.

What is written: ``manifest.json``, ``model_schedule.csv``,
``training_history.csv``, ``signature_features.csv``,
``prediction_contributions.csv``, ``forecast_evaluation.csv``,
``forecast_summary.csv``, ``mse_differences.csv``, ``calibration_summary.csv``,
``component_functions.csv``, ``component_function_stability.csv``,
``feature_domain.csv``, ``contribution_summary.csv``, ``coverage.csv``,
``global_metrics.csv``, ``quality_details.csv``,
``sa13_history.csv``, ``sa13_orders.csv``, ``sa13_fills.csv``,
``sa13_rejects.csv``, ``sa13_position_episodes.csv``, ``study_comparisons.csv``,
``sharpe_sensitivity.csv``, ``study.md``, the frozen models under
``artifacts/``, and the files the report writer reads (``summary.csv``,
``summary_costs_x2.csv``, ``yearly.csv``, ``equity.csv``, ``fills.csv``,
``config.json``, one ``history_<book>.csv`` per book and
``report_extra_SA13.md``).

The tests are in ``tests/scripts/test_run_signature_study.py``.
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
from datetime import date, timedelta
from itertools import pairwise
from pathlib import Path

import numpy as np
import pandas as pd
from run_arima_garch_study import RANKING_COLUMNS, THREAD_VARIABLES, sortino
from run_etf_strategies_comparison import (
    ANALYTICS,
    BENCHMARK,
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
    slug,
)
from run_garch_study import (
    BOOTSTRAP_DRAWS,
    BOOTSTRAP_LEVEL,
    BOOTSTRAP_SEED,
    COST_STRESS,
    FUND,
    GARCH,
    VOL_CONTROL,
    book_histories,
    doubled,
    markdown_table,
    scored,
    summary_frame,
    yearly_frame,
)
from run_review_diagnostics import episode_summary, episodes

from quant_backtester.analytics.curves import Book
from quant_backtester.analytics.quality import QUALITY_V1
from quant_backtester.analytics.return_forecast import (
    PairedForecasts,
    evaluate_mean,
    out_of_sample_r2,
    pair_at_two_sessions,
)
from quant_backtester.analytics.uncertainty import (
    PairedBootstrap,
    PairedStatistic,
    UndefinedStatistic,
    paired_block_bootstrap,
)
from quant_backtester.analytics.volatility_forecast import paired_loss_difference
from quant_backtester.backtest.runner import StrategyResult, StrategyRunner
from quant_backtester.backtest.timetable import BacktestTimetable
from quant_backtester.data.calendars import CalendarRegistry, TradingCalendar
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.data.schemas import BarField
from quant_backtester.ml.dataset import ForwardOpenReturnBuilder, MissingForwardOpen
from quant_backtester.ml.signatures.artifacts import ScheduleEntry, SignatureModelSchedule
from quant_backtester.ml.signatures.config import (
    ModelKind,
    SignatureModelConfig,
    SignatureTrainingConfig,
    SignatureVariant,
)
from quant_backtester.ml.signatures.models import AdditiveWeights, internal_contributions
from quant_backtester.signals.signatures.logsignature import (
    FeatureKind,
    FeatureSpec,
    SignatureFeatureBuilder,
    SignatureFeatures,
    require_esig,
)
from quant_backtester.signals.signatures.path import SignaturePathConfig
from quant_backtester.signals.types import SignalStatus
from quant_backtester.strategies.adaptive.rules import (
    conservative_volatility,
    gated_volatility_rule,
)
from quant_backtester.strategies.base import Strategy
from quant_backtester.strategies.catalogue import entry
from quant_backtester.strategies.examples.signatures_neurons import STRATEGY_ID, SignaturesNeurons

SA13 = entry("SA13").display_name
"""The strategy under study."""

ARIMA = entry("SA12").display_name
"""``SA12``, compared when its estimators are installed."""

C0 = "C0 - same risk no filter"
"""The control of the registered hypothesis: the models of ``SA13``, the filter always on."""

CORE_VARIANT = "sa13_nam_logsig3"
"""The variant of ``SA13``: the additive model on the order-3 log-signature of the fund."""

MODEL_CONTROLS = {
    "C1 - Ridge logsig3": "research_sa13_ridge_logsig3",
    "C2 - NAM logsig2": "research_sa13_nam_logsig2",
    "C3 - NAM no volume": "research_sa13_nam_no_volume",
    "C4 - NAM classical": "research_sa13_nam_classical",
    "C5 - Ridge raw trajectory": "research_sa13_ridge_raw_trajectory",
    "C6 - NAM context SP500": "research_sa13_nam_context_sp500",
    "C7 - Ridge context SP500": "research_sa13_ridge_context_sp500",
}
"""The controls that are another model or another representation: book name and variant."""

C1, C2, C3, C4, C5, C6, C7 = tuple(MODEL_CONTROLS)

CONTEXT_FUND = "ETF_SP500_PEA"
"""The second explanatory process of the context variants. It is never traded by them."""

STUDY_PERIOD = ("2023-01-02", "2026-10-09")
"""The months the store lets a model be calibrated for: the first cutoff that
holds 900 valid training examples and 95% of valid features is 2022-12-30."""

MODEL_AVAILABILITY_DELAY = timedelta(hours=12)
"""Assumed time between a model's information cutoff - 23:00 in Paris on the
last session of a month - and the instant it may be used. A historical
assumption, stated: a prospective run uses the hour the model is really ready."""

BOOTSTRAP_BLOCK = 60
"""Sessions per block of the paired bootstraps of this study."""

SENSITIVITY_BLOCKS = (20, 120)
"""The other block lengths the main difference is reported with, announced before the run."""

MINIMUM_TEST_SESSIONS = 504
"""Fewest test sessions the hypothesis is judged on."""

MINIMUM_COMPLETED_EPISODES = 30
"""Fewest completed position episodes the hypothesis is judged on."""

MINIMUM_USABLE_SHARE = 0.95
"""Share of decisions with a model and usable features under which nothing is concluded."""

INSUFFICIENT, NOT_SUPPORTED = "INSUFFICIENT_EVIDENCE", "NOT_SUPPORTED"
UNCERTAIN, SUPPORTED = "UNCERTAIN", "SUPPORTED_RETROSPECTIVE"
"""The four statuses of the economic hypothesis, sufficiency judged first."""

FUNCTION_GRID = tuple(float(value) for value in np.linspace(-5.0, 5.0, 21))
"""The normalised values each component function is tabulated at: the clipped domain."""

GROUPS = (
    "reference",
    "displacements",
    "price_volume",
    "price_time",
    "volume_time",
    "order_3",
    "other",
)
"""The groups the contributions of a forecast are summed by."""

PATH = SignaturePathConfig(
    steps=60,
    volume_reference_sessions=60,
    price_scale=100.0,
    use_volume=True,
    max_age_sessions=0,
)
"""The path of the specification: 61 points after 60 sessions of volume reference."""

TRAINING = SignatureTrainingConfig(
    training_candidate_origins=1008,
    validation_candidate_origins=126,
    minimum_training_examples=900,
    minimum_validation_examples=100,
    minimum_valid_share=0.95,
)
"""The monthly cut of the specification."""


def model_of(kind: ModelKind) -> SignatureModelConfig:
    """Return the frozen configuration of a model of the study, of either kind."""
    return SignatureModelConfig(
        kind=kind,
        hidden_units=4,
        learning_rate=1e-3,
        weight_decay=1e-3,
        max_epochs=300,
        patience=30,
        minimum_improvement=1e-6,
        gradient_clip_norm=1.0,
        seed=20261010,
        input_clip=5.0,
        target_scale=100.0,
        ridge_alpha=10.0,
    )


def variants(
    *,
    fund: str = FUND,
    context: str = CONTEXT_FUND,
    path: SignaturePathConfig = PATH,
    training: SignatureTrainingConfig = TRAINING,
    models: Mapping[ModelKind, SignatureModelConfig] | None = None,
) -> dict[str, SignatureVariant]:
    """Return the eight variants of the study by identifier, ``SA13``'s first.

    Parameters
    ----------
    fund : str
        The fund whose return every variant forecasts.
    context : str
        The second process of the two context variants.
    path : SignaturePathConfig
        The window every representation is built from.
    training : SignatureTrainingConfig
        The monthly cut, the same for every variant.
    models : Mapping[ModelKind, SignatureModelConfig] | None
        The model of each kind; those of the specification when ``None``.

    Returns
    -------
    dict[str, SignatureVariant]
        Each control changes one thing: the model, the order, the volume
        channel, the representation, or the processes read. The parameters
        exist so that the same variants can be built on a small synthetic
        market; the study itself calls this without arguments.
    """
    chosen = models or {kind: model_of(kind) for kind in ModelKind}
    silent = replace(path, use_volume=False)

    def spec(
        kind: FeatureKind = FeatureKind.LOGSIGNATURE,
        depth: int = 3,
        *,
        window: SignaturePathConfig = path,
        processes: tuple[str, ...] = (fund,),
    ) -> FeatureSpec:
        return FeatureSpec(kind, window, depth, processes)

    described = {
        CORE_VARIANT: (spec(), ModelKind.NEURAL_ADDITIVE),
        MODEL_CONTROLS[C1]: (spec(), ModelKind.RIDGE),
        MODEL_CONTROLS[C2]: (spec(depth=2), ModelKind.NEURAL_ADDITIVE),
        MODEL_CONTROLS[C3]: (spec(window=silent), ModelKind.NEURAL_ADDITIVE),
        MODEL_CONTROLS[C4]: (spec(FeatureKind.CLASSICAL), ModelKind.NEURAL_ADDITIVE),
        MODEL_CONTROLS[C5]: (spec(FeatureKind.RAW_TRAJECTORY), ModelKind.RIDGE),
        MODEL_CONTROLS[C6]: (spec(processes=(fund, context)), ModelKind.NEURAL_ADDITIVE),
        MODEL_CONTROLS[C7]: (spec(processes=(fund, context)), ModelKind.RIDGE),
    }
    return {
        variant_id: SignatureVariant(variant_id, fund, features, chosen[kind], training)
        for variant_id, (features, kind) in described.items()
    }


# --- the monthly calibrations ------------------------------------------------------------


def calibration_months(
    sessions: Sequence[date], start: date, end: date
) -> list[tuple[str, date | None]]:
    """Return each month of a period with the session its model's information stops at.

    Parameters
    ----------
    sessions : Sequence[date]
        The sessions of the calendar in order, from before the period.
    start, end : date
        The first and last sessions of the period.

    Returns
    -------
    list[tuple[str, date | None]]
        ``("YYYY-MM", cutoff)`` for every month holding a session of the
        period, the cutoff being the last session before the month's first
        day - ``None`` when the calendar handed in holds none, in which case
        the month can have no model.
    """
    months: list[tuple[str, date | None]] = []
    seen: set[str] = set()
    for session in sessions:
        if not start <= session <= end:
            continue
        month = f"{session.year:04d}-{session.month:02d}"
        if month in seen:
            continue
        seen.add(month)
        before = [day for day in sessions if day < date(session.year, session.month, 1)]
        months.append((month, before[-1] if before else None))
    return months


def spec_key(spec: FeatureSpec) -> str:
    """Return what identifies a representation: two variants that share it share its features."""
    return json.dumps(spec.definition(), sort_keys=True)


def feature_cache(
    reader: MarketDataReader,
    calendars: CalendarRegistry,
    timetable: BacktestTimetable,
    sessions: Sequence[date],
    chosen: Mapping[str, SignatureVariant],
) -> dict[str, dict[date, SignatureFeatures]]:
    """Build, once per representation, the features of every session at its own instant.

    Returns
    -------
    dict[str, dict[date, SignatureFeatures]]
        By :func:`spec_key`. The calibration of every month and the export of
        every forecast read from here; the run's own signal builds the same
        features again from the same builder, and :func:`require_same_forecasts`
        checks that the two agree.
    """
    from quant_backtester.ml.signatures.training import feature_histories

    builders = {
        spec_key(variant.features): SignatureFeatureBuilder(variant.features)
        for variant in chosen.values()
    }
    return feature_histories(reader, calendars, timetable, sessions, builders)


def calibrate_schedules(
    chosen: Mapping[str, SignatureVariant],
    months: Sequence[tuple[str, date | None]],
    *,
    reader: MarketDataReader,
    calendar: TradingCalendar,
    timetable: BacktestTimetable,
    sessions: Sequence[date],
    features: Mapping[str, Mapping[date, SignatureFeatures]],
    availability_delay: timedelta = MODEL_AVAILABILITY_DELAY,
) -> tuple[dict[str, SignatureModelSchedule], pd.DataFrame, pd.DataFrame]:
    """Calibrate every variant for every month and return the schedules and their account.

    Parameters
    ----------
    chosen : Mapping[str, SignatureVariant]
        The variants, by identifier.
    months : Sequence[tuple[str, date | None]]
        What :func:`calibration_months` returned.
    reader : MarketDataReader
        The store the labels are read from, on a reader fixed at each cutoff.
    calendar : TradingCalendar
        What dates the labels and the purge.
    timetable : BacktestTimetable
        Gives the instant a cutoff's information stops at.
    sessions : Sequence[date]
        The sessions of the calendar in order.
    features : Mapping[str, Mapping[date, SignatureFeatures]]
        What :func:`feature_cache` returned.
    availability_delay : timedelta
        Time after the cutoff before a model may be used.

    Returns
    -------
    tuple[dict[str, SignatureModelSchedule], pd.DataFrame, pd.DataFrame]
        The schedule of each variant - every month in it, with a frozen model
        or the reason it has none - one row per variant and month, and the
        training history of every calibration.
    """
    from quant_backtester.ml.signatures.training import calibrate_month

    labels = ForwardOpenReturnBuilder(reader, calendar, timetable)
    schedules: dict[str, SignatureModelSchedule] = {}
    planned: list[dict[str, object]] = []
    history: list[dict[str, object]] = []
    for variant_id, variant in chosen.items():
        entries: list[ScheduleEntry] = []
        for month, cutoff in months:
            if cutoff is None:
                found = ScheduleEntry(month, None, "NO_SESSION_BEFORE_THE_MONTH")
                rows: list[dict[str, object]] = [
                    {"month": month, "variant_id": variant_id, "status": found.reason}
                ]
            else:
                instant = timetable.decision_instant(cutoff)
                found, rows = calibrate_month(
                    variant,
                    month=month,
                    cutoff=cutoff,
                    sessions=sessions,
                    calendar=calendar,
                    features=features[spec_key(variant.features)],
                    labels=labels,
                    information_cutoff=instant,
                    available_at=instant + availability_delay,
                )
            entries.append(found)
            history.extend(rows)
            planned.append(schedule_row(variant_id, found, cutoff))
            print(f"calibrated {variant_id} {month}: {found.identity[:24]}", file=sys.stderr)
        schedules[variant_id] = SignatureModelSchedule(
            variant_id, timetable.timezone, tuple(entries)
        )
    return schedules, pd.DataFrame(planned), pd.DataFrame(history)


def schedule_row(variant_id: str, found: ScheduleEntry, cutoff: date | None) -> dict[str, object]:
    """Return one month of a schedule as it is exported: the model, or why there is none."""
    artifact = found.artifact
    row: dict[str, object] = {
        "variant_id": variant_id,
        "month": found.month,
        "cutoff_session": cutoff,
        "status": "CALIBRATED" if artifact is not None else f"NO_MODEL:{found.reason}",
    }
    if artifact is None:
        return row
    return {
        **row,
        "model_id": artifact.model_id,
        "kind": artifact.kind.value,
        "information_cutoff": artifact.information_cutoff.isoformat(),
        "available_at": artifact.available_at.isoformat(),
        "training_start": artifact.training_start,
        "training_end": artifact.training_end,
        "validation_start": artifact.validation_start,
        "validation_end": artifact.validation_end,
        "training_examples": artifact.training_examples,
        "validation_examples": artifact.validation_examples,
        "selected_epoch": artifact.selected_epoch,
        "training_label_mean": artifact.training_label_mean,
        "parameters": artifact.weights.parameters,
    }


def calibration_summary(
    planned: pd.DataFrame, chosen: Mapping[str, SignatureVariant]
) -> pd.DataFrame:
    """Return, per variant, how its monthly calibrations ended.

    Returns
    -------
    pd.DataFrame
        Indexed by variant: the months, those with a model, the mean numbers
        of training and validation examples, and for the additive models the
        mean selected epoch and ``at_epoch_cap`` - the calibrations whose
        selected epoch is the last one allowed, so that the validation loss
        was still improving when the fit stopped. Published as a limit of the
        frozen configuration; raising the cap after reading it would be
        another variant.
    """
    rows: dict[str, dict[str, object]] = {}
    for variant_id, part in planned.groupby("variant_id", sort=False):
        variant = chosen[str(variant_id)]
        fitted = part.loc[part["status"] == "CALIBRATED"]
        row: dict[str, object] = {
            "kind": variant.model.kind.value,
            "features": len(variant.features.names()),
            "months": len(part),
            "months_with_model": len(fitted),
            "mean_training_examples": None,
            "mean_validation_examples": None,
            "mean_selected_epoch": None,
            "at_epoch_cap": None,
        }
        if len(fitted):
            row["mean_training_examples"] = _mean(pd.Series(fitted["training_examples"]))
            row["mean_validation_examples"] = _mean(pd.Series(fitted["validation_examples"]))
        if len(fitted) and variant.model.kind is ModelKind.NEURAL_ADDITIVE:
            epochs = fitted["selected_epoch"].to_numpy(dtype="float64")
            row["mean_selected_epoch"] = float(epochs.mean())
            row["at_epoch_cap"] = int((epochs >= variant.model.max_epochs).sum())
        rows[str(variant_id)] = row
    return pd.DataFrame.from_dict(rows, orient="index").rename_axis("variant_id")


def study_books(
    schedules: Mapping[str, SignatureModelSchedule], chosen: Mapping[str, SignatureVariant]
) -> dict[str, SignaturesNeurons]:
    """Return ``SA13`` and its eight controls on schedules already calibrated.

    ``C0`` reads the very schedule ``SA13`` reads; every other control has the
    rule of ``SA13`` on its own models. A control is recorded under a research
    identifier, never under a catalogue code.
    """
    core = chosen[CORE_VARIANT]
    family = {
        SA13: SignaturesNeurons.from_schedule(
            schedules[CORE_VARIANT], core, strategy_id=STRATEGY_ID
        ),
        C0: SignaturesNeurons.from_schedule(
            schedules[CORE_VARIANT],
            core,
            direction_filter=False,
            strategy_id="research_sa13_c0_no_filter",
        ),
    }
    for name, variant_id in MODEL_CONTROLS.items():
        family[name] = SignaturesNeurons.from_schedule(
            schedules[variant_id], chosen[variant_id], strategy_id=variant_id
        )
    return family


# --- forecasts and their composition -----------------------------------------------------


def group_of(name: str) -> str:
    """Return the group a feature's contribution is summed in.

    ``name`` is qualified by its process, ``ETF_WORLD:[1,2]``. The two
    displacements of a log-signature are one group, each area of order 2 its
    own, every coefficient of order 3 one group; a feature of another
    representation is ``other``.
    """
    key = name.split(":", 1)[-1]
    if key in ("1", "2"):
        return "displacements"
    named = {"[1,2]": "price_volume", "[1,3]": "price_time", "[2,3]": "volume_time"}
    if key in named:
        return named[key]
    return "order_3" if key.startswith("[") else "other"


def forecast_frame(
    schedule: SignatureModelSchedule,
    features: Mapping[date, SignatureFeatures],
    sessions: Sequence[date],
    timetable: BacktestTimetable,
) -> pd.DataFrame:
    """Return one row per decision of a variant: the forecast, its model and its composition.

    Parameters
    ----------
    schedule : SignatureModelSchedule
        The frozen models of the variant.
    features : Mapping[date, SignatureFeatures]
        The features of each session, each built at its own instant.
    sessions : Sequence[date]
        The decisions to describe.
    timetable : BacktestTimetable
        Gives the instant of each decision, at which the month's model is taken.

    Returns
    -------
    pd.DataFrame
        Indexed by ``origin``: ``status`` and ``reason``, the model's month,
        identifier and training mean, ``forecast`` and ``reference`` as
        decimal returns, the count of clipped features, one ``contribution``
        column per feature and one ``group`` column per group, in decimal.
        The forecast is the reference plus the contributions; nothing in a
        row was computed with a later session.
    """
    rows: dict[date, dict[str, object]] = {}
    for origin in sessions:
        built = features[origin]
        found = schedule.entry_at(timetable.decision_instant(origin))
        artifact = found.artifact
        row: dict[str, object] = {
            "status": built.status.value,
            "reason": built.reason,
            "model_month": found.month,
            "model_id": None if artifact is None else artifact.model_id,
            "training_label_mean": None if artifact is None else artifact.training_label_mean,
            "window_start": built.window_start,
            "window_end": built.window_end,
            "zero_volume_sessions": built.zero_volume_sessions,
            "forecast": float("nan"),
        }
        vector = built.values  # noqa: PD011 - a field of SignatureFeatures, not a frame
        if vector is not None and artifact is None:
            row["status"] = SignalStatus.INSUFFICIENT_HISTORY.value
            row["reason"] = found.identity
        if vector is not None and artifact is not None:
            prediction = artifact.predict(vector)
            row.update(
                {
                    "forecast": prediction.mean,
                    "reference": prediction.reference,
                    "clipped": prediction.clipped,
                }
            )
            sums: dict[str, float] = dict.fromkeys(GROUPS, 0.0)
            sums["reference"] = prediction.reference
            for name, part in zip(built.names, prediction.contributions, strict=True):
                row[f"contribution[{name}]"] = part
                sums[group_of(name)] += part
            row.update({f"group[{group}]": value for group, value in sums.items()})
        rows[origin] = row
    return pd.DataFrame.from_dict(rows, orient="index").rename_axis("origin")


def require_same_forecasts(frame: pd.DataFrame, history: pd.DataFrame, column: str) -> None:
    """Raise unless the forecasts exported are those the run's own signal computed.

    Parameters
    ----------
    frame : pd.DataFrame
        What :func:`forecast_frame` returned, from the cache of features.
    history : pd.DataFrame
        The book's history, holding the signal recomputed at each decision.
    column : str
        The signal's column in it.

    Raises
    ------
    RuntimeError
        If a decision has a forecast in one and not in the other, or two
        different numbers: the features of the calibration and those of the
        inference would not be the same, and nothing exported could be trusted.
    """
    exported = frame["forecast"].astype("float64").reindex(history.index)
    computed = history[column].astype("float64")
    same = (exported.isna() & computed.isna()) | (exported == computed)
    if not bool(same.all()):
        first = same.index[~same.to_numpy()][0]
        raise RuntimeError(
            f"{column}: the forecast exported for {first} ({exported[first]!r}) is not the one "
            f"the run computed ({computed[first]!r})"
        )


def realised_labels(
    reader: MarketDataReader,
    calendar: TradingCalendar,
    timetable: BacktestTimetable,
    sessions: Sequence[date],
    instrument_id: str,
) -> pd.Series:  # type: ignore[type-arg]
    """Return the realised return of each interval that is known, indexed by its exit session.

    Parameters
    ----------
    reader : MarketDataReader
        The store, read on a reader fixed at the last of the sessions.
    calendar : TradingCalendar
        What dates the labels.
    timetable : BacktestTimetable
        Gives the instant the opens are read at.
    sessions : Sequence[date]
        Consecutive sessions of the venue, the origins and the last one known.
    instrument_id : str
        The fund.

    Returns
    -------
    pd.Series
        The return from the open after an origin to the open after that, with
        corporate actions by the engine's convention: the label of the models,
        read once after the runs. The two last sessions are origins whose label
        is not known yet - pending, not invented - and an origin whose open is
        missing is left out and counted as missing by the pairing.
    """
    known_until = sessions[-1]
    labels = ForwardOpenReturnBuilder(reader, calendar, timetable)
    known = list(sessions[:-2])
    exits = list(sessions[2:])
    values: dict[date, float] = {}
    try:
        built = labels.build(known, [instrument_id], known_until=known_until)
        values = {out: float(built[row, 0]) for row, out in enumerate(exits)}
    except MissingForwardOpen:
        for origin, out in zip(known, exits, strict=True):
            try:
                one = labels.build([origin], [instrument_id], known_until=known_until)
            except MissingForwardOpen:
                continue
            values[out] = float(one[0, 0])
    return pd.Series(values, dtype="float64").sort_index()


def evaluation_frame(
    forecasts: pd.DataFrame,
    realised: pd.Series,
    sessions: Sequence[date],  # type: ignore[type-arg]
) -> tuple[pd.DataFrame, PairedForecasts]:
    """Pair a variant's forecasts with their realised returns and add the two references.

    Returns
    -------
    tuple[pd.DataFrame, PairedForecasts]
        The pairs, indexed by origin, with ``reference_train_mean`` - the mean
        label of the training block of the model that made the forecast,
        frozen with it - the three squared errors and the forecast error; and
        the pairing itself, for its count of origins left out.
    """
    paired = pair_at_two_sessions(pd.Series(forecasts["forecast"]), realised, sessions)
    pairs = paired.pairs.drop(columns=["forecast_variance"])
    mean = forecasts["training_label_mean"].reindex(pairs.index).astype("float64")
    actual = pairs["realised"].astype("float64")
    said = pairs["forecast_mean"].astype("float64")
    frame = pairs.assign(
        model_month=forecasts["model_month"].reindex(pairs.index),
        reference_train_mean=mean,
        error=said - actual,
        squared_error=(said - actual) ** 2,
        squared_error_zero=actual**2,
        squared_error_train_mean=(mean - actual) ** 2,
    )
    return frame, paired


def _mean(values: pd.Series) -> float:  # type: ignore[type-arg]
    """Return the mean of a column of numbers."""
    return float(np.mean(values.to_numpy(dtype="float64")))


def summary_row(pairs: pd.DataFrame) -> dict[str, object]:
    """Return the errors of one set of pairs, with the two naive forecasts beside them."""
    actual = [float(value) for value in pairs["realised"]]
    said = [float(value) for value in pairs["forecast_mean"]]
    reference = [float(value) for value in pairs["reference_train_mean"]]
    measured = evaluate_mean(actual, said).definition()
    count = len(pairs)
    return {
        **measured,
        "mse_zero": _mean(pd.Series(pairs["squared_error_zero"])) if count else None,
        "mse_train_mean": _mean(pd.Series(pairs["squared_error_train_mean"])) if count else None,
        "r2_oos_vs_train_mean": out_of_sample_r2(actual, said, reference),
        "first_origin": pairs.index[0] if count else None,
        "last_origin": pairs.index[-1] if count else None,
    }


def invested_origins(held: pd.Series, sessions: Sequence[date]) -> set[date]:  # type: ignore[type-arg]
    """Return the origins whose forecast was followed by a position actually carried.

    An origin ``t`` is invested when the fund was held at the valuation of
    ``t + 1``: the position was there over the interval the forecast was made
    for. Read on the weights held, not on the target asked for.
    """
    weights = held.to_dict()
    return {
        origin
        for origin, entry_session in pairwise(sessions)
        if float(weights.get(entry_session, 0.0) or 0.0) > 0.0
    }


def forecast_summary(
    evaluations: Mapping[str, pd.DataFrame],
    pairings: Mapping[str, PairedForecasts],
    invested: Mapping[str, set[date]],
) -> pd.DataFrame:
    """Return, per book and sample, the errors of the forecasts and what was left out."""
    rows: list[dict[str, object]] = []
    for name, pairs in evaluations.items():
        carried = pairs.loc[[origin in invested[name] for origin in pairs.index]]
        for sample, part in (("all valid forecasts", pairs), ("invested", carried)):
            rows.append(
                {
                    "book": name,
                    "sample": sample,
                    **summary_row(part),
                    "origins": pairings[name].origins,
                    **{
                        f"left_out_{key}": count for key, count in pairings[name].exclusions.items()
                    },
                }
            )
    return pd.DataFrame(rows)


MSE_COMPARISONS = (
    ("SA13 - zero forecast", SA13, "zero"),
    ("SA13 - training mean", SA13, "train_mean"),
    ("SA13 - C1 (the neurons, against Ridge on the same log-signature)", SA13, C1),
    ("SA13 - C2 (order 3, against order 2)", SA13, C2),
    ("SA13 - C3 (the volume, against none)", SA13, C3),
    ("SA13 - C4 (the signature, against classical indicators)", SA13, C4),
    ("SA13 - C5 (the compression, against the raw trajectory)", SA13, C5),
    ("C6 - SA13 (a second process, against the fund alone)", C6, SA13),
    ("C6 - C7 (the neurons on two processes, against Ridge)", C6, C7),
)
"""The paired differences of squared error reported: the first less the second."""


def mse_differences(evaluations: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    """Return each paired difference of squared error with its block bootstrap interval.

    Negative when the first is the better forecast. Each difference is taken
    on the origins both forecasts have; a pair of books sharing fewer than two
    gives a row that says so, never a zero.
    """
    rows: list[dict[str, object]] = []
    for label, first, second in MSE_COMPARISONS:
        own = evaluations[first]
        if second in ("zero", "train_mean"):
            other = pd.Series(own[f"squared_error_{second}"])
        else:
            other = pd.Series(evaluations[second]["squared_error"])
        mine = pd.Series(own["squared_error"])
        shared = [origin for origin in mine.index if origin in other.index]
        if len(shared) < 2:
            rows.append({"comparison": label, "pairs": len(shared), "bootstrap": "refused"})
            continue
        measured = paired_loss_difference(
            mine.loc[shared],
            other.loc[shared],
            block=BOOTSTRAP_BLOCK,
            draws=BOOTSTRAP_DRAWS,
            seed=BOOTSTRAP_SEED,
            level=BOOTSTRAP_LEVEL,
        )
        rows.append({"comparison": label, **measured.definition(), "bootstrap": "ok"})
    return pd.DataFrame(rows)


def component_functions(schedule: SignatureModelSchedule) -> pd.DataFrame:
    """Tabulate each component function of each month's additive model, in basis points.

    Returns
    -------
    pd.DataFrame
        One row per month, feature and value of :data:`FUNCTION_GRID`:
        ``g_j(z)`` divided by the target's scale, times ``1e4``. The grid is
        the clipped domain; where the observations actually lie on it is in
        ``feature_domain.csv``. Empty for a schedule without additive models.
    """
    rows: list[dict[str, object]] = []
    grid = np.asarray(FUNCTION_GRID)
    for found in schedule.entries:
        artifact = found.artifact
        if artifact is None or not isinstance(artifact.weights, AdditiveWeights):
            continue
        count = len(artifact.feature_names)
        inputs = np.repeat(grid[:, None], count, axis=1)
        values = internal_contributions(artifact.weights, inputs) / artifact.target_scale * 1e4
        for column, name in enumerate(artifact.feature_names):
            for row, point in enumerate(FUNCTION_GRID):
                rows.append(
                    {
                        "month": found.month,
                        "feature": name,
                        "z": point,
                        "contribution_bp": float(values[row, column]),
                    }
                )
    return pd.DataFrame(rows)


def function_stability(functions: pd.DataFrame) -> pd.DataFrame:
    """Return how much each component function moves from one month's model to the next.

    Per feature, at ``z = -2``, ``-1``, ``1`` and ``2``: the mean over the
    months of the contribution, its standard deviation across months, and the
    share of months in which it has the sign of that mean. A measure of
    stability, not of truth: a stable function may be stably wrong.
    """
    if functions.empty:
        return pd.DataFrame()
    rows: list[dict[str, object]] = []
    kept = functions.loc[functions["z"].isin([-2.0, -1.0, 1.0, 2.0])]
    for (feature, point), part in kept.groupby(["feature", "z"], sort=False):
        values = part["contribution_bp"].to_numpy(dtype="float64")
        mean = float(values.mean())
        rows.append(
            {
                "feature": feature,
                "z": point,
                "months": len(values),
                "mean_bp": mean,
                "std_across_months_bp": float(values.std(ddof=1)) if len(values) > 1 else None,
                "share_of_months_with_the_sign_of_the_mean": float(
                    (np.sign(values) == np.sign(mean)).mean()
                ),
            }
        )
    return pd.DataFrame(rows)


def feature_domain(
    schedule: SignatureModelSchedule,
    features: Mapping[date, SignatureFeatures],
    sessions: Sequence[date],
    timetable: BacktestTimetable,
) -> pd.DataFrame:
    """Return where the normalised features of the test decisions lie, feature by feature.

    Each decision's raw features are normalised by the scaler of the model
    that decision used, before clipping. Per feature: the count, five
    quantiles and the share beyond the clip on each side.
    """
    normalised: dict[str, list[float]] = {}
    clip = 0.0
    for origin in sessions:
        artifact = schedule.entry_at(timetable.decision_instant(origin)).artifact
        vector = features[origin].values  # noqa: PD011 - a field of SignatureFeatures
        if artifact is None or vector is None:
            continue
        clip = artifact.input_clip
        scaled = (np.asarray(vector) - artifact.scaler_mean) / artifact.scaler_std
        for name, value in zip(artifact.feature_names, scaled, strict=True):
            normalised.setdefault(name, []).append(float(value))
    rows = []
    for name, values in normalised.items():
        array = np.asarray(values)
        low, quarter, median, three, high = np.quantile(array, [0.01, 0.25, 0.5, 0.75, 0.99])
        rows.append(
            {
                "feature": name,
                "group": group_of(name),
                "decisions": len(array),
                "q01": float(low),
                "q25": float(quarter),
                "median": float(median),
                "q75": float(three),
                "q99": float(high),
                "share_clipped_low": float((array < -clip).mean()),
                "share_clipped_high": float((array > clip).mean()),
            }
        )
    return pd.DataFrame(rows)


def contribution_summary(frame: pd.DataFrame, when: Mapping[str, Sequence[date]]) -> pd.DataFrame:
    """Return the mean contribution of each group, in basis points, over sets of decisions.

    Parameters
    ----------
    frame : pd.DataFrame
        What :func:`forecast_frame` returned.
    when : Mapping[str, Sequence[date]]
        Named sets of decisions: every usable one, those before an entry,
        those before an exit.

    Returns
    -------
    pd.DataFrame
        One row per set: its count, the mean forecast and the mean of each
        group, all in basis points. A contribution to a forecast, never a
        contribution to a profit.
    """
    columns = [f"group[{group}]" for group in GROUPS if f"group[{group}]" in frame.columns]
    rows: dict[str, dict[str, object]] = {}
    for label, origins in when.items():
        part = frame.loc[[origin for origin in origins if origin in frame.index]]
        part = part.loc[part["forecast"].notna()]
        row: dict[str, object] = {"decisions": len(part)}
        row["forecast_bp"] = float(part["forecast"].mean() * 1e4) if len(part) else None
        for column in columns:
            name = column.removeprefix("group[").removesuffix("]")
            row[f"{name}_bp"] = (
                float(part[column].astype("float64").mean() * 1e4) if len(part) else None
            )
        rows[label] = row
    return pd.DataFrame.from_dict(rows, orient="index").rename_axis("decisions_of")


# --- the economic test -------------------------------------------------------------------


def sharpe_difference(
    strategy: pd.Series,  # type: ignore[type-arg]
    control: pd.Series,  # type: ignore[type-arg]
    block: int = BOOTSTRAP_BLOCK,
) -> PairedBootstrap | str:
    """Return the bootstrapped Sharpe difference of two books, or the reason it is refused."""
    try:
        return paired_block_bootstrap(
            strategy,
            control,
            statistic=PairedStatistic.SHARPE,
            block=block,
            draws=BOOTSTRAP_DRAWS,
            seed=BOOTSTRAP_SEED,
            level=BOOTSTRAP_LEVEL,
            config=ANALYTICS,
        )
    except (UndefinedStatistic, ValueError) as refused:
        return f"refused: {refused}"


def comparison_controls(results: Mapping[str, StrategyResult]) -> list[str]:
    """Return the books ``SA13`` is compared with: its controls, then the references run."""
    references = [VOL_CONTROL, GARCH, ARIMA, HELD, SPLIT]
    return [C0, *MODEL_CONTROLS, *(name for name in references if name in results)]


def comparison_frame(
    base: Mapping[str, StrategyResult], stressed: Mapping[str, StrategyResult]
) -> pd.DataFrame:
    """Return ``SA13`` against each control and reference, at both cost levels.

    One row per control and cost level: the net Sharpe ratios, returns and
    maximum drawdowns, and the paired block bootstrap of the Sharpe
    difference - or the reason it was refused, never a zero.
    """
    rows: list[dict[str, object]] = []
    for label, results in (("x1", base), (f"x{COST_STRESS:g}", stressed)):
        own = results[SA13].report().net
        for control in comparison_controls(results):
            other = results[control].report().net
            outcome = sharpe_difference(results[SA13].equity(), results[control].equity())
            row: dict[str, object] = {
                "costs": label,
                "control": control,
                "sharpe_sa13": own.sharpe_ratio,
                "sharpe_control": other.sharpe_ratio,
                "net_return_sa13": own.total_return,
                "net_return_control": other.total_return,
                "max_drawdown_sa13": own.drawdown.depth,
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


def sensitivity_frame(
    base: Mapping[str, StrategyResult], stressed: Mapping[str, StrategyResult]
) -> pd.DataFrame:
    """Return the main difference, ``SA13`` less ``C0``, at every announced block length.

    The interval of :data:`BOOTSTRAP_BLOCK` is the one the hypothesis is
    judged on; the two others were announced as sensitivities and all three
    are published, not the most favourable.
    """
    rows: list[dict[str, object]] = []
    for label, results in (("x1", base), (f"x{COST_STRESS:g}", stressed)):
        for block in sorted({BOOTSTRAP_BLOCK, *SENSITIVITY_BLOCKS}):
            outcome = sharpe_difference(results[SA13].equity(), results[C0].equity(), block)
            row: dict[str, object] = {
                "costs": label,
                "block": block,
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
    test_sessions: int,
    completed_episodes: int,
    usable_share: float | None,
) -> tuple[str, list[str]]:
    """Return the status of the registered hypothesis - ``SA13`` against ``C0`` - and why.

    Parameters
    ----------
    comparison : pd.DataFrame
        What :func:`comparison_frame` returned.
    test_sessions : int
        Sessions of the test.
    completed_episodes : int
        Position episodes of ``SA13`` that were closed.
    usable_share : float | None
        Share of its decisions with an authorised model and usable features.

    Returns
    -------
    tuple[str, list[str]]
        Sufficiency first: fewer sessions or episodes than required, or a
        share of usable decisions under 95% or undefined, give
        ``INSUFFICIENT_EVIDENCE``. Then ``NOT_SUPPORTED`` for a Sharpe
        difference at or below zero at the costs of reference; ``UNCERTAIN``
        for a positive one whose interval includes zero, a refused bootstrap,
        a difference that does not stay positive at doubled costs or a
        drawdown deeper than ``C0``'s; ``SUPPORTED_RETROSPECTIVE`` otherwise.
    """
    reasons: list[str] = []
    if test_sessions < MINIMUM_TEST_SESSIONS:
        reasons.append(f"{test_sessions} test sessions, under {MINIMUM_TEST_SESSIONS}")
    if completed_episodes < MINIMUM_COMPLETED_EPISODES:
        reasons.append(
            f"{completed_episodes} completed position episodes, under {MINIMUM_COMPLETED_EPISODES}"
        )
    if usable_share is None or usable_share < MINIMUM_USABLE_SHARE:
        shown = "undefined" if usable_share is None else f"{usable_share:.2%}"
        reasons.append(
            f"share of decisions with a model and usable features {shown}, under "
            f"{MINIMUM_USABLE_SHARE:.0%}"
        )
    if reasons:
        return INSUFFICIENT, reasons
    against = comparison.loc[comparison["control"] == C0].set_index("costs")
    base, stress = against.loc["x1"], against.loc[f"x{COST_STRESS:g}"]
    difference = base["sharpe_difference"]
    if difference is None or pd.isna(difference):
        return UNCERTAIN, [f"Sharpe difference against C0 at base costs: {base['bootstrap']}"]
    if float(difference) <= 0.0:
        return NOT_SUPPORTED, [
            f"Sharpe difference against C0 at base costs: {float(difference):+.3f}"
        ]
    if float(base["interval_low"]) <= 0.0:
        reasons.append(
            "interval of the Sharpe difference against C0 includes zero: "
            f"[{float(base['interval_low']):+.3f} ; {float(base['interval_high']):+.3f}]"
        )
    doubled_difference = stress["sharpe_difference"]
    if doubled_difference is None or pd.isna(doubled_difference):
        reasons.append(f"Sharpe difference against C0 at doubled costs: {stress['bootstrap']}")
    elif float(doubled_difference) <= 0.0:
        reasons.append(
            f"Sharpe difference against C0 at doubled costs: {float(doubled_difference):+.3f}"
        )
    if float(base["max_drawdown_sa13"]) < float(base["max_drawdown_control"]):
        reasons.append("maximum drawdown deeper than C0's")
    return (UNCERTAIN, reasons) if reasons else (SUPPORTED, [])


SECONDARY_QUESTIONS = (
    ("neurons", "SA13 - C1 (the neurons, against Ridge on the same log-signature)", False),
    ("order_3", "SA13 - C2 (order 3, against order 2)", False),
    ("volume", "SA13 - C3 (the volume, against none)", False),
    ("signature_vs_classical", "SA13 - C4 (the signature, against classical indicators)", False),
    ("compression_vs_raw", "SA13 - C5 (the compression, against the raw trajectory)", False),
    ("second_process", "C6 - SA13 (a second process, against the fund alone)", False),
)
"""The questions concluded apart from the economic one, each on one difference of MSE."""


def secondary_conclusions(differences: pd.DataFrame) -> dict[str, str]:
    """Return, per secondary question, what the difference of squared error lets be said.

    ``LOWER_MSE_INTERVAL_EXCLUDES_ZERO`` when the first forecast of the pair
    has the lower error and the interval of the difference is below zero;
    ``LOWER_MSE_NOT_TOLD_FROM_ZERO`` when it is lower and the interval includes
    zero; ``NOT_LOWER`` otherwise; ``NOT_MEASURED`` when the two forecasts
    shared too few origins. A statement about forecast errors on this path,
    not about usefulness.
    """
    by_label = differences.set_index("comparison")
    conclusions: dict[str, str] = {}
    for question, label, _ in SECONDARY_QUESTIONS:
        row = by_label.loc[label]
        if row.get("bootstrap") != "ok":
            conclusions[question] = "NOT_MEASURED"
        elif float(row["estimate"]) >= 0.0:
            conclusions[question] = "NOT_LOWER"
        elif float(row["high"]) < 0.0:
            conclusions[question] = "LOWER_MSE_INTERVAL_EXCLUDES_ZERO"
        else:
            conclusions[question] = "LOWER_MSE_NOT_TOLD_FROM_ZERO"
    return conclusions


# --- histories ---------------------------------------------------------------------------


def signature_history(
    history: pd.DataFrame,
    forecasts: pd.DataFrame,
    opens: pd.Series,  # type: ignore[type-arg]
    strategy: SignaturesNeurons,
) -> pd.DataFrame:
    """Return a book's history with its forecast, what it is made of, its gate and its target.

    Parameters
    ----------
    history : pd.DataFrame
        The generic history of the book: closes, signals, weights, value.
    forecasts : pd.DataFrame
        What :func:`forecast_frame` returned for the variant the book reads.
    opens : pd.Series
        Raw opens of the fund by session.
    strategy : SignaturesNeurons
        The book's strategy, for its thresholds and its sizing.

    Returns
    -------
    pd.DataFrame
        Numeric columns only, a row per session: the closes, ``open_<fund>``,
        ``model_month`` (the month of the model used, as ``YYYYMM``; empty
        without a model), ``forecast_bp``, the contribution of each group in
        basis points, the two realised volatilities, ``gate`` (1 when the
        forecast lets the position be held, read on the weight held that
        evening), ``theoretical_weight`` (the target before the band), then
        the weights targeted and held and the value.
    """
    fund = strategy.instrument_id
    signal_column = f"{strategy.forecast_signal().signal_id}[{fund}]"
    short_column = f"{strategy.short_signal().signal_id}[{fund}]"
    long_column = f"{strategy.long_signal().signal_id}[{fund}]"
    days = list(history.index)
    # A book that never held the fund has no weight column: it held zero throughout.
    history = history.assign(
        **{
            column: 0.0
            for column in (f"target_{fund}", f"held_{fund}")
            if column not in history.columns
        }
    )
    held = history[f"held_{fund}"].fillna(0.0).to_numpy(dtype="float64")
    mean = history[signal_column].to_numpy(dtype="float64")
    short = history[short_column].to_numpy(dtype="float64")
    long = history[long_column].to_numpy(dtype="float64")
    gates, weights = [], []
    for row in range(len(days)):
        estimate = conservative_volatility(
            None if math.isnan(short[row]) else float(short[row]),
            None if math.isnan(long[row]) else float(long[row]),
            floor=strategy.volatility_floor,
        )
        usable = estimate is not None and not math.isnan(mean[row])
        target = gated_volatility_rule(
            fund,
            float(mean[row]) if usable else None,
            estimate,
            held=held[row] > 0.0,
            entry_threshold=strategy.entry_threshold,
            exit_threshold=strategy.exit_threshold,
            target_volatility=strategy.target_volatility,
            floor=strategy.volatility_floor,
            gated=strategy.direction_filter,
        )
        gates.append(target.diagnostics.get("gate", float("nan")))
        weights.append(dict(target.weights).get(fund, 0.0) if usable else float("nan"))
    aligned = forecasts.reindex(history.index)
    months = [
        float(str(month).replace("-", "")) if model is not None and not pd.isna(model) else np.nan
        for month, model in zip(aligned["model_month"], aligned["model_id"], strict=True)
    ]
    extra: dict[str, object] = {
        f"open_{fund}": opens.reindex(history.index).astype("float64"),
        "model_month": months,
        "forecast_bp": mean * 1e4,
    }
    for group in GROUPS:
        column = f"group[{group}]"
        if column in aligned.columns and group != "other":
            extra[f"{group}_bp"] = aligned[column].astype("float64") * 1e4
    extra.update({"gate": gates, "theoretical_weight": weights})
    rest = history.drop(columns=[signal_column])
    closes = [column for column in rest.columns if column.startswith("close_")]
    others = [column for column in rest.columns if column not in closes]
    return pd.concat(
        [rest[closes], pd.DataFrame(extra, index=history.index), rest[others]], axis=1
    ).rename_axis("session_date")


def episode_decisions(
    stays: pd.DataFrame, sessions: Sequence[date]
) -> tuple[list[date], list[date]]:
    """Return the decisions that opened each stay and those that closed each completed one.

    A stay entered at the valuation of ``e`` was decided at the evening of the
    session before ``e``; a stay back in cash at the valuation of ``x`` was
    closed by the decision of the session before ``x``.
    """
    place = {day: rank for rank, day in enumerate(sessions)}
    entries: list[date] = []
    exits: list[date] = []
    for row in range(len(stays)):
        first, last = stays["entry"].iloc[row], stays["exit"].iloc[row]
        if place.get(first, 0) > 0:
            entries.append(sessions[place[first] - 1])
        if not bool(stays["open"].iloc[row]) and place.get(last, 0) > 0:
            exits.append(sessions[place[last] - 1])
    return entries, exits


# --- the written study -------------------------------------------------------------------


def _cell(value: object, pattern: str) -> str:
    """Return one cell of a table, ``n/a`` for a figure that does not exist."""
    if value is None or value is pd.NA or (isinstance(value, float) and math.isnan(value)):
        return "n/a"
    return pattern.format(value)


FORECAST_COLUMNS = (
    ("pairs", "pairs", "{:.0f}"),
    ("mse", "MSE", "{:.4e}"),
    ("mse_zero", "MSE zero", "{:.4e}"),
    ("mse_train_mean", "MSE train mean", "{:.4e}"),
    ("r2_oos_vs_train_mean", "R2 OOS", "{:+.4f}"),
    ("mae", "MAE", "{:.5f}"),
    ("bias", "bias", "{:+.5f}"),
    ("correlation", "corr.", "{:+.3f}"),
    ("sign_accuracy", "sign", "{:.1%}"),
    ("always_up_accuracy", "always up", "{:.1%}"),
    ("balanced_accuracy", "balanced", "{:.1%}"),
    ("forecast_up", "forecasts > 0", "{:.0f}"),
)
"""The columns of the tables of forecast errors."""

COMPARISON_COLUMNS = (
    ("sharpe_sa13", "Sharpe SA13", "{:+.3f}"),
    ("sharpe_control", "Sharpe control", "{:+.3f}"),
    ("sharpe_difference", "difference", "{:+.3f}"),
    ("interval_low", "95% low", "{:+.3f}"),
    ("interval_high", "95% high", "{:+.3f}"),
    ("net_return_sa13", "net SA13", "{:+.2%}"),
    ("net_return_control", "net control", "{:+.2%}"),
    ("max_drawdown_sa13", "max DD SA13", "{:.2%}"),
    ("max_drawdown_control", "max DD control", "{:.2%}"),
)
"""The columns of the table of ``SA13`` against its controls."""


def coverage_frame(planned: pd.DataFrame, forecasts: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    """Return, per book, the months with a model and the decisions with a usable forecast."""
    names = {CORE_VARIANT: SA13, **{variant: name for name, variant in MODEL_CONTROLS.items()}}
    rows: dict[str, dict[str, object]] = {}
    for variant_id, part in planned.groupby("variant_id", sort=False):
        name = names[str(variant_id)]
        frame = forecasts[name]
        usable = int((frame["status"] == SignalStatus.OK.value).sum())
        reasons = frame.loc[frame["status"] != SignalStatus.OK.value, "reason"].astype(str)
        rows[name] = {
            "variant_id": variant_id,
            "months": len(part),
            "months_with_model": int((part["status"] == "CALIBRATED").sum()),
            "decisions": len(frame),
            "usable_decisions": usable,
            "usable_share": usable / len(frame) if len(frame) else None,
            "unusable_reasons": {
                str(key): int(count)
                for key, count in reasons.str.split(":")
                .str[:2]
                .str.join(":")
                .value_counts()
                .items()
            },
        }
    return pd.DataFrame.from_dict(rows, orient="index").rename_axis("book")


def study_markdown(
    summary: pd.DataFrame,
    stressed_summary: pd.DataFrame,
    comparison: pd.DataFrame,
    sensitivity: pd.DataFrame,
    coverage: pd.DataFrame,
    calibrations: pd.DataFrame,
    errors: pd.DataFrame,
    differences: pd.DataFrame,
    contributions: pd.DataFrame,
    stays: Mapping[str, object],
    status: tuple[str, Sequence[str]],
    secondary: Mapping[str, str],
    register: Mapping[str, object],
    timings: Mapping[str, float],
) -> str:
    """Return the written study: ranking, coverage, forecasts, the test of the filter, limits."""
    outcome, reasons = status
    first, last = summary["first_session"].iloc[0], summary["last_session"].iloc[0]
    dedicated = comparison.set_index(
        comparison["costs"].astype(str) + " vs " + comparison["control"].astype(str)
    ).rename_axis("costs vs control")
    blocks = sensitivity.set_index(
        sensitivity["costs"].astype(str) + ", blocks of " + sensitivity["block"].astype(str)
    ).rename_axis("costs, block")
    lines = [
        "# SA13 - Signatures Neurons: retrospective study",
        "",
        f"Test period {first} to {last}, {int(summary['sessions'].iloc[0])} sessions, one "
        f"continuous book of {INITIAL_CASH:,.0f} EUR, costs of the ETF comparison, quantities "
        "fixed at the decision, cash unpaid. One model per variant and per month, calibrated "
        "on what was known at the evening of the last session of the month before and frozen "
        "for the month. A retrospective evaluation with a sequential re-estimation: the "
        "history had been looked at before.",
        "",
        "## Ranking on the test period (QUALITY_V1, against ETF_WORLD bought and held)",
        "",
        markdown_table(summary, RANKING_COLUMNS),
        "",
        f"Deflated by {register['trials']} trials: every catalogued strategy re-run on this "
        "period, SA13 and its eight controls; the fund held and the even split are references. "
        "These books are strongly correlated and are not independent experiments, and the "
        "variants of earlier exercises are not in the register: the ranking is exploratory "
        "and a rank is not a probability of success. C0 to C7 are controls, not candidates. "
        "The scores of earlier studies were measured from an older date and are not "
        "comparable with these.",
        "",
        f"## The same table with every cost paid x{COST_STRESS:g} (second real run, same models)",
        "",
        markdown_table(stressed_summary, RANKING_COLUMNS),
        "",
        "## Coverage: months with a model, decisions with a usable forecast",
        "",
        markdown_table(
            coverage,
            [
                ("months", "months", "{}"),
                ("months_with_model", "with a model", "{}"),
                ("decisions", "decisions", "{}"),
                ("usable_decisions", "usable", "{}"),
                ("usable_share", "share", "{:.2%}"),
                ("unusable_reasons", "unusable, by reason", "{}"),
            ],
        ),
        "",
        "A month without a model and a day without a signal are days in cash that stay in the "
        "results of the book.",
        "",
        "## The monthly calibrations",
        "",
        markdown_table(
            calibrations,
            [
                ("kind", "model", "{}"),
                ("features", "features", "{}"),
                ("months_with_model", "models", "{}"),
                ("mean_training_examples", "training examples", "{:.0f}"),
                ("mean_validation_examples", "validation examples", "{:.0f}"),
                ("mean_selected_epoch", "mean selected epoch", "{:.0f}"),
                ("at_epoch_cap", "selected at the cap", "{:.0f}"),
            ],
        ),
        "",
        "`selected at the cap` counts the additive models whose selected epoch is the last "
        "one allowed: their validation loss was still improving when the fit stopped. The cap "
        "was frozen before the first fit; raising it after reading this would be another "
        "variant.",
        "",
        "## Forecasts out of training (next open to the open after)",
        "",
        markdown_table(
            errors.loc[errors["sample"] == "all valid forecasts"].set_index("book"),
            FORECAST_COLUMNS,
        ),
        "",
        "On the forecasts followed by a position actually carried:",
        "",
        markdown_table(
            errors.loc[errors["sample"] == "invested"].set_index("book"), FORECAST_COLUMNS
        ),
        "",
        "`MSE zero` and `MSE train mean` are the errors, on the same pairs, of a forecast of "
        "zero and of the mean label of the training block frozen with each model. `R2 OOS` is "
        "one less the ratio of the model's squared error to that of the training mean. The "
        "sign is scored on the realisations that are not exactly zero and is to be read "
        "against 'always up', which only measures the drift of the fund.",
        "",
        markdown_table(
            differences.set_index("comparison"),
            [
                ("pairs", "pairs", "{:.0f}"),
                ("estimate", "mean difference of squared error", "{:+.3e}"),
                ("low", "95% low", "{:+.3e}"),
                ("high", "95% high", "{:+.3e}"),
                ("excludes_zero", "excludes zero", "{}"),
            ],
        ),
        "",
        f"Paired differences on shared origins, negative when the first is the better one; "
        f"moving-block bootstrap, blocks of {BOOTSTRAP_BLOCK}, {BOOTSTRAP_DRAWS} draws, seed "
        f"{BOOTSTRAP_SEED}. The windows overlap heavily: a thousand rows are not a thousand "
        "independent experiments.",
        "",
        "## What a forecast of SA13 is made of (mean contributions, basis points)",
        "",
        markdown_table(
            contributions,
            [
                ("decisions", "decisions", "{:.0f}"),
                ("forecast_bp", "forecast", "{:+.2f}"),
                ("reference_bp", "reference", "{:+.2f}"),
                ("displacements_bp", "displacements", "{:+.2f}"),
                ("price_volume_bp", "price-volume", "{:+.2f}"),
                ("price_time_bp", "price-time", "{:+.2f}"),
                ("volume_time_bp", "volume-time", "{:+.2f}"),
                ("order_3_bp", "order 3", "{:+.2f}"),
            ],
        ),
        "",
        "A forecast is its reference plus its contributions, exactly. `z = 0` is a "
        "statistical reference of the features, not a path a market could follow, and a "
        "contribution to a forecast is not a contribution to a profit: the economic weight of "
        "a group is tested by the variant refitted without it.",
        "",
        "## SA13 against its controls and the references",
        "",
        markdown_table(dedicated, COMPARISON_COLUMNS),
        "",
        "The main difference, SA13 less C0, at the three announced block lengths:",
        "",
        markdown_table(
            blocks,
            [
                ("sharpe_difference", "difference", "{:+.3f}"),
                ("interval_low", "95% low", "{:+.3f}"),
                ("interval_high", "95% high", "{:+.3f}"),
                ("bootstrap", "bootstrap", "{}"),
            ],
        ),
        "",
        f"Position episodes of SA13: {stays.get('stays', 0)} "
        f"({stays.get('completed', 0)} completed), {stays.get('gains', 0)} with a net gain; "
        f"mean net return per episode {_cell(stays.get('mean_net_return'), '{:+.2%}')}.",
        "",
        "## Status of the registered hypothesis (`sa13_signatures_neurons`): SA13 against C0",
        "",
        f"**{outcome}.**",
        *[f"- {reason}" for reason in reasons],
        "",
        "The status answers one question - does the direction filter learnt from the "
        "log-signature improve the same risk sizing without it - under the criteria written "
        "before the first fit. The intervals are conditional on the path already produced: "
        "they carry neither the uncertainty of the re-estimations nor the selection of ideas.",
        "",
        "Concluded apart, on the paired differences of squared error above:",
        "",
        *[f"- {question}: {answer}" for question, answer in secondary.items()],
        "",
        "A favourable economic result would not show that the signatures or the neurons were "
        "needed; an unfavourable one does not show that a log-signature carries no information.",
        "",
        "## Limits",
        "",
        "- The 12 hours between a model's cutoff and its availability are an assumption of "
        "the historical run.",
        "- The realised volatilities of the sizing are a proxy on closes, not a forecast of "
        "the variance of the label.",
        "- The models of the comparison differ in capacity: 157 parameters for SA13, 61 at "
        "order 2, 109 on the classical indicators, 313 on two processes. A comparison does "
        "not isolate one cause.",
        "- The store is not a set of provider vintages.",
        "- A prospective observation starts at the first XPAR session at which the artifacts "
        "really exist, with this configuration frozen; it does not exist yet.",
        "",
        "## Timings",
        "",
        *[f"- {label}: {seconds:.0f} s" for label, seconds in timings.items()],
        "",
    ]
    return "\n".join(lines)


SECONDARY_FRENCH = {
    "neurons": "Apport des neurones (SA13 contre Ridge sur les mêmes log-signatures)",
    "order_3": "Apport de l'ordre 3 (contre l'ordre 2)",
    "volume": "Apport du volume (contre le canal de volume à zéro)",
    "signature_vs_classical": "Apport des signatures (contre neuf indicateurs classiques)",
    "compression_vs_raw": "Apport de la compression (contre la trajectoire brute en Ridge)",
    "second_process": "Apport d'un second processus (World + S&P 500 contre World seul)",
}
"""The secondary questions as the report names them."""

CONCLUSION_FRENCH = {
    "LOWER_MSE_INTERVAL_EXCLUDES_ZERO": "erreur quadratique plus faible, intervalle sous zéro",
    "LOWER_MSE_NOT_TOLD_FROM_ZERO": (
        "erreur quadratique plus faible, intervalle contenant zéro : non établi"
    ),
    "NOT_LOWER": "erreur quadratique non plus faible : non soutenu sur ce chemin",
    "NOT_MEASURED": "non mesuré (trop peu d'origines communes)",
}
"""The conclusions on a difference of squared error as the report words them."""


DECISION_SETS_FRENCH = {
    "every usable decision": "Toutes les décisions utilisables",
    "decisions that opened a position": "Décisions qui ont ouvert une position",
    "decisions that closed a position": "Décisions qui ont fermé une position",
}
"""The sets of decisions of the table of contributions as the report names them."""


def report_extra(
    coverage: pd.DataFrame,
    calibrations: pd.DataFrame,
    errors: pd.DataFrame,
    differences: pd.DataFrame,
    contributions: pd.DataFrame,
    comparison: pd.DataFrame,
    sensitivity: pd.DataFrame,
    stays: Mapping[str, object],
    status: tuple[str, Sequence[str]],
    secondary: Mapping[str, str],
) -> str:
    """Return the section of the SA13 report that only this study can write, in French."""
    outcome, reasons = status
    own = coverage.loc[SA13]
    fitted = calibrations.loc[CORE_VARIANT]
    measured = errors.set_index(["book", "sample"])
    everything, carried = (
        measured.loc[(SA13, "all valid forecasts")],
        measured.loc[(SA13, "invested")],
    )
    against = comparison.set_index(["costs", "control"])
    rows = []
    for costs in ("x1", f"x{COST_STRESS:g}"):
        for control in comparison["control"].drop_duplicates():
            row = against.loc[(costs, control)]
            rows.append(
                f"| {costs} | {control} | {_cell(row['sharpe_sa13'], '{:+.3f}')} | "
                f"{_cell(row['sharpe_control'], '{:+.3f}')} | "
                f"{_cell(row['sharpe_difference'], '{:+.3f}')} | "
                f"[{_cell(row.get('interval_low'), '{:+.3f}')} ; "
                f"{_cell(row.get('interval_high'), '{:+.3f}')}] | "
                f"{_cell(row['max_drawdown_sa13'], '{:.2%}')} | "
                f"{_cell(row['max_drawdown_control'], '{:.2%}')} |"
            )
    blocks = [
        f"| {row['costs']} | {row['block']} | {_cell(row.get('sharpe_difference'), '{:+.3f}')} | "
        f"[{_cell(row.get('interval_low'), '{:+.3f}')} ; "
        f"{_cell(row.get('interval_high'), '{:+.3f}')}] |"
        for _, row in sensitivity.iterrows()
    ]
    gaps = [
        f"| {row['comparison']} | {_cell(row.get('pairs'), '{:.0f}')} | "
        f"{_cell(row.get('estimate'), '{:+.3e}')} | [{_cell(row.get('low'), '{:+.3e}')} ; "
        f"{_cell(row.get('high'), '{:+.3e}')}] |"
        for _, row in differences.iterrows()
    ]
    parts = [
        f"| {DECISION_SETS_FRENCH.get(str(label), str(label))} | "
        f"{_cell(row.get('decisions'), '{:.0f}')} | "
        f"{_cell(row.get('forecast_bp'), '{:+.2f}')} | "
        f"{_cell(row.get('reference_bp'), '{:+.2f}')} | "
        f"{_cell(row.get('displacements_bp'), '{:+.2f}')} | "
        f"{_cell(row.get('price_volume_bp'), '{:+.2f}')} | "
        f"{_cell(row.get('price_time_bp'), '{:+.2f}')} | "
        f"{_cell(row.get('volume_time_bp'), '{:+.2f}')} | "
        f"{_cell(row.get('order_3_bp'), '{:+.2f}')} |"
        for label, row in contributions.iterrows()
    ]
    lines = [
        "### Couverture, prévisions et composition (étude SA13)",
        "",
        f"- **Couverture.** {own['months_with_model']} mois sur {own['months']} ont un modèle "
        f"calibré ; {own['usable_decisions']} décisions sur {own['decisions']} ont un modèle "
        f"autorisé et des features utilisables ({_cell(own['usable_share'], '{:.2%}')}). "
        f"Motifs des décisions inutilisables : {own['unusable_reasons'] or 'aucun'}. Les mois "
        "sans modèle et les séances sans signal restent dans la performance, en cash.",
        f"- **Calibrations.** {_cell(fitted['mean_training_examples'], '{:.0f}')} exemples "
        f"d'apprentissage et {_cell(fitted['mean_validation_examples'], '{:.0f}')} de validation "
        f"en moyenne par mois ; époque retenue moyenne "
        f"{_cell(fitted['mean_selected_epoch'], '{:.0f}')} ; "
        f"{_cell(fitted['at_epoch_cap'], '{:.0f}')} modèle(s) sur {fitted['months_with_model']} "
        "retenu(s) à la dernière époque autorisée, c'est-à-dire avec une perte de validation "
        "encore en baisse à l'arrêt. Ce plafond était gelé avant le premier ajustement.",
        "- **Erreur de prévision, toutes prévisions valides.** "
        f"{_cell(everything['pairs'], '{:.0f}')} paires ; MSE "
        f"{_cell(everything['mse'], '{:.4e}')}, contre "
        f"{_cell(everything['mse_zero'], '{:.4e}')} pour la prévision nulle et "
        f"{_cell(everything['mse_train_mean'], '{:.4e}')} pour la moyenne d'apprentissage gelée "
        f"avec chaque modèle ; R² hors apprentissage "
        f"{_cell(everything['r2_oos_vs_train_mean'], '{:+.4f}')} ; corrélation "
        f"prévision/réalisation {_cell(everything['correlation'], '{:+.3f}')}.",
        f"- **Signe.** Juste {_cell(everything['sign_accuracy'], '{:.1%}')}, contre "
        f"{_cell(everything['always_up_accuracy'], '{:.1%}')} pour « toujours en hausse » ; "
        f"justesse équilibrée {_cell(everything['balanced_accuracy'], '{:.1%}')} ; "
        f"{_cell(everything['forecast_up'], '{:.0f}')} prévisions positives.",
        f"- **Prévisions suivies d'une position portée.** {_cell(carried['pairs'], '{:.0f}')} "
        f"paires ; MSE {_cell(carried['mse'], '{:.4e}')} ; signe juste "
        f"{_cell(carried['sign_accuracy'], '{:.1%}')} contre "
        f"{_cell(carried['always_up_accuracy'], '{:.1%}')} pour « toujours en hausse ».",
        f"- **Épisodes de position.** {stays.get('stays', 0)} épisodes, dont "
        f"{stays.get('completed', 0)} terminés ; {stays.get('gains', 0)} gagnants ; net moyen "
        f"{_cell(stays.get('mean_net_return'), '{:+.2%}')}.",
        "",
        "### De quoi une prévision de SA13 est faite (contributions moyennes, en points de base)",
        "",
        "| Décisions | Nombre | Prévision | Référence | Déplacements | Prix-volume | "
        "Prix-temps | Volume-temps | Ordre 3 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        *parts,
        "",
        "Chaque prévision est exactement sa référence plus ses contributions. Une "
        "contribution à la prévision n'est pas une contribution au résultat : le poids "
        "économique d'un groupe se teste par la variante réentraînée sans lui (C2 pour "
        "l'ordre 3, C3 pour le volume). Le point `z = 0` est une référence statistique des "
        "features, pas un chemin de marché réalisable.",
        "",
        "### Écarts d'erreur quadratique (premier moins second, négatif = premier meilleur)",
        "",
        "| Comparaison | Paires | Écart moyen | Intervalle 95 % |",
        "|---|---:|---:|---|",
        *gaps,
        "",
        f"Bootstrap par blocs mobiles de {BOOTSTRAP_BLOCK} origines, {BOOTSTRAP_DRAWS} tirages, "
        f"graine {BOOTSTRAP_SEED}. Les fenêtres se recouvrent fortement : mille lignes ne sont "
        "pas mille expériences indépendantes.",
        "",
        "### SA13 contre ses contrôles et les références",
        "",
        "| Coûts | Contrôle | Sharpe SA13 | Sharpe contrôle | Écart | Intervalle 95 % | "
        "Perte max. SA13 | Perte max. contrôle |",
        "|---|---|---:|---:|---:|---|---:|---:|",
        *rows,
        "",
        "C0 : mêmes modèles, même disponibilité, même dimensionnement, filtre de direction "
        "toujours actif. C1 : Ridge sur les 13 mêmes coefficients. C2 : réseau additif à "
        "l'ordre 2. C3 : réseau additif sans volume. C4 : réseau additif sur neuf indicateurs "
        "classiques. C5 : Ridge sur la trajectoire brute. C6 et C7 : réseau additif et Ridge "
        "sur World + S&P 500. Ce sont des contrôles de recherche, sans code de catalogue, et "
        f"aucun n'est candidat. Bootstrap apparié par blocs de {BOOTSTRAP_BLOCK} séances, "
        f"{BOOTSTRAP_DRAWS} tirages, graine {BOOTSTRAP_SEED}.",
        "",
        "Écart principal, SA13 moins C0, aux trois longueurs de bloc annoncées :",
        "",
        "| Coûts | Bloc | Écart de Sharpe | Intervalle 95 % |",
        "|---|---:|---:|---|",
        *blocks,
        "",
        f"### Statut de l'hypothèse préinscrite `sa13_signatures_neurons` : **{outcome}**",
        "",
        *[f"- {reason}" for reason in reasons],
        "",
        "Ce statut répond à une seule question, écrite avant le premier ajustement : le "
        "filtre de direction appris sur la log-signature améliore-t-il le même "
        "dimensionnement de risque sans lui (C0) ? Les intervalles sont conditionnels au "
        "chemin déjà produit ; ils ne portent ni l'incertitude des réestimations ni la "
        "sélection des idées. Conclusions séparées, sur les écarts d'erreur quadratique :",
        "",
        *[
            f"- {SECONDARY_FRENCH[question]} : {CONCLUSION_FRENCH[answer]}."
            for question, answer in secondary.items()
        ],
        "",
    ]
    return "\n".join(lines)


def manifest(
    results: Mapping[str, StrategyResult],
    strategies: Mapping[str, Strategy],
    chosen: Mapping[str, SignatureVariant],
    schedules: Mapping[str, SignatureModelSchedule],
    register: Mapping[str, object],
    stressed: object,
    status: tuple[str, Sequence[str]],
    secondary: Mapping[str, str],
    coverage: pd.DataFrame,
    timings: Mapping[str, float],
) -> dict[str, object]:
    """Return everything the study depends on, serialisable: code, data, models, trials."""
    reference = results[SA13]
    lock = (REPOSITORY / "uv.lock").read_bytes()
    packages = ("numpy", "scipy", "pandas", "torch", "scikit-learn", "esig", "roughpy")
    return {
        "study": "sa13_signatures_neurons",
        "hypothesis_id": "sa13_signatures_neurons",
        "status": {"outcome": status[0], "reasons": list(status[1])},
        "secondary_conclusions": dict(secondary),
        "period": {"start": str(reference.start), "end": str(reference.end)},
        "initial_cash": INITIAL_CASH,
        "universe": list(UNIVERSE),
        "analytics": ANALYTICS.definition(),
        "execution": reference.configuration["execution"],
        "execution_stressed": {"factor": COST_STRESS, "costs": str(stressed)},
        "quality_rules": QUALITY_V1.definition(),
        "bootstrap": {
            "block": BOOTSTRAP_BLOCK,
            "sensitivity_blocks": list(SENSITIVITY_BLOCKS),
            "draws": BOOTSTRAP_DRAWS,
            "seed": BOOTSTRAP_SEED,
            "level": BOOTSTRAP_LEVEL,
        },
        "thresholds": {
            "minimum_test_sessions": MINIMUM_TEST_SESSIONS,
            "minimum_completed_position_episodes": MINIMUM_COMPLETED_EPISODES,
            "minimum_usable_decision_share": MINIMUM_USABLE_SHARE,
        },
        "model_availability_delay_seconds": MODEL_AVAILABILITY_DELAY.total_seconds(),
        "variants": {name: variant.definition() for name, variant in chosen.items()},
        "model_schedules": {
            name: {"schedule_id": schedule.schedule_id, **schedule.definition()}
            for name, schedule in schedules.items()
        },
        "coverage": coverage.to_dict(orient="index"),
        "not_run": {
            "ML1": "its artifacts were calibrated on a period this test overlaps",
            "gradient boosting on the log-signature": "optional, not developed",
        },
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


def calendar_sessions(
    reader: MarketDataReader,
    calendar: TradingCalendar,
    timetable: BacktestTimetable,
    instrument_id: str,
    end: date,
) -> list[date]:
    """Return the venue's sessions from the fund's first bar to the end of the period."""
    closes = reader.at(timetable.decision_instant(end)).history(instrument_id, BarField.CLOSE)
    first = min(day for day in closes.index if isinstance(day, date))
    return [day.session_date for day in calendar.sessions(first, end)]


def main(arguments: Sequence[str] | None = None) -> int:
    """Calibrate the models, run the study and write every export."""
    parser = argparse.ArgumentParser(description="Run the SA13 signature study.")
    parser.add_argument("--output", type=Path, default=Path("results/signature_study"))
    parser.add_argument("--store", type=Path, default=STORE)
    parser.add_argument("--start", default=STUDY_PERIOD[0], help="first measured session")
    parser.add_argument("--end", default=STUDY_PERIOD[1], help="last measured session")
    options = parser.parse_args(arguments)
    period = (options.start, options.end)
    start, end = date.fromisoformat(options.start), date.fromisoformat(options.end)
    require_esig()
    timings: dict[str, float] = {}

    runner = build_runner(options.store)
    reader, timetable = runner.reader, runner.timetable
    calendar = runner.calendars.get(runner.reference_calendar_id)
    sessions = calendar_sessions(reader, calendar, timetable, FUND, end)
    months = calibration_months(sessions, start, end)
    chosen = variants()
    cutoffs = [cutoff for _, cutoff in months if cutoff is not None]
    reach = TRAINING.training_candidate_origins + TRAINING.validation_candidate_origins
    oldest = max(sessions.index(cutoffs[0]) - reach + 1, 0) if cutoffs else 0

    started = time.perf_counter()
    features = feature_cache(reader, runner.calendars, timetable, sessions[oldest:], chosen)
    timings["features of every origin, six representations"] = time.perf_counter() - started
    started = time.perf_counter()
    schedules, planned, training_history = calibrate_schedules(
        chosen,
        months,
        reader=reader,
        calendar=calendar,
        timetable=timetable,
        sessions=sessions,
        features=features,
    )
    timings["monthly calibrations of the eight variants"] = time.perf_counter() - started

    family = study_books(schedules, chosen)
    strategies: dict[str, Strategy] = {**books(), **family}
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
    histories = book_histories(base, strategies)
    timings["signals of every book recomputed for the exports"] = time.perf_counter() - started
    own = base[SA13]
    test_sessions = [record.session_date for record in own.records()]
    with own.reading() as store:
        market = store.at(own.records()[-1].valuation_time)
        opens = market.history(FUND, BarField.OPEN)
        realised = realised_labels(store, calendar, timetable, test_sessions, FUND)

    forecasts: dict[str, pd.DataFrame] = {}
    for name, book in family.items():
        if name == C0:
            continue
        frame = forecast_frame(
            schedules[book.variant_id],
            features[spec_key(chosen[book.variant_id].features)],
            test_sessions,
            timetable,
        )
        column = f"{book.forecast_signal().signal_id}[{FUND}]"
        require_same_forecasts(frame, histories[name], column)
        forecasts[name] = frame
    for name, book in family.items():
        source = forecasts[SA13 if name == C0 else name]
        histories[name] = signature_history(histories[name], source, opens, book)

    evaluations: dict[str, pd.DataFrame] = {}
    pairings: dict[str, PairedForecasts] = {}
    invested: dict[str, set[date]] = {}
    for name, frame in forecasts.items():
        evaluations[name], pairings[name] = evaluation_frame(frame, realised, test_sessions)
        invested[name] = invested_origins(pd.Series(histories[name][f"held_{FUND}"]), test_sessions)
    errors = forecast_summary(evaluations, pairings, invested)
    differences = mse_differences(evaluations)
    functions = component_functions(schedules[CORE_VARIANT])
    stability = function_stability(functions)
    domain = feature_domain(
        schedules[CORE_VARIANT],
        features[spec_key(chosen[CORE_VARIANT].features)],
        test_sessions,
        timetable,
    )

    fills = pd.concat(
        [result.fills().assign(book=name) for name, result in base.items()], ignore_index=True
    )
    stays_frame = episodes(histories[SA13], fills.loc[fills["book"] == SA13])
    stays: dict[str, object] = dict(episode_summary(stays_frame))
    completed = (
        sum(1 for still_open in stays_frame["open"] if not still_open) if len(stays_frame) else 0
    )
    stays["completed"] = completed
    entries, exits = episode_decisions(stays_frame, test_sessions) if len(stays_frame) else ([], [])
    usable = forecasts[SA13].index[forecasts[SA13]["forecast"].notna()]
    contributions = contribution_summary(
        forecasts[SA13],
        {
            "every usable decision": list(usable),
            "decisions that opened a position": entries,
            "decisions that closed a position": exits,
        },
    )
    coverage = coverage_frame(planned, forecasts)
    calibrations = calibration_summary(planned, chosen)
    comparison = comparison_frame(base, stressed)
    sensitivity = sensitivity_frame(base, stressed)
    share = coverage.loc[SA13, "usable_share"]
    status = hypothesis_status(
        comparison,
        test_sessions=len(test_sessions),
        completed_episodes=completed,
        usable_share=None if share is None else float(share),  # type: ignore[arg-type]
    )
    secondary = secondary_conclusions(differences)
    yearly = yearly_frame({name: result.equity() for name, result in base.items()})

    output: Path = options.output
    output.mkdir(parents=True, exist_ok=True)
    for variant_id, schedule in schedules.items():
        for found in schedule.entries:
            if found.artifact is not None:
                found.artifact.save(output / "artifacts" / variant_id / found.month)
    planned.to_csv(output / "model_schedule.csv", index=False)
    training_history.to_csv(output / "training_history.csv", index=False)
    core_features = features[spec_key(chosen[CORE_VARIANT].features)]
    names = chosen[CORE_VARIANT].features.names()
    pd.DataFrame.from_dict(
        {
            origin: {
                "status": built.status.value,
                "reason": built.reason,
                "window_start": built.window_start,
                "window_end": built.window_end,
                "zero_volume_sessions": built.zero_volume_sessions,
                "depth": chosen[CORE_VARIANT].features.depth,
                **dict(zip(names, built.values or [float("nan")] * len(names), strict=True)),  # noqa: PD011
            }
            for origin, built in core_features.items()
        },
        orient="index",
    ).rename_axis("origin").to_csv(output / "signature_features.csv")
    described = forecasts[SA13].copy()
    for column in [
        name for name in described.columns if name.startswith(("contribution[", "group["))
    ]:
        described[f"{column}_bp"] = described[column].astype("float64") * 1e4
    described.to_csv(output / "prediction_contributions.csv")
    for name, variant_id in MODEL_CONTROLS.items():
        forecasts[name].to_csv(output / f"prediction_contributions_{variant_id}.csv")
    pd.concat([frame.assign(book=name) for name, frame in evaluations.items()]).to_csv(
        output / "forecast_evaluation.csv"
    )
    errors.to_csv(output / "forecast_summary.csv", index=False)
    differences.to_csv(output / "mse_differences.csv", index=False)
    functions.to_csv(output / "component_functions.csv", index=False)
    stability.to_csv(output / "component_function_stability.csv", index=False)
    domain.to_csv(output / "feature_domain.csv", index=False)
    contributions.to_csv(output / "contribution_summary.csv")
    coverage.to_csv(output / "coverage.csv")
    calibrations.to_csv(output / "calibration_summary.csv")
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
    histories[SA13].join(
        forecasts[SA13][["status", "reason", "model_id", "window_start", "window_end"]]
    ).to_csv(output / "sa13_history.csv")
    own.orders().to_csv(output / "sa13_orders.csv", index=False)
    own.fills().to_csv(output / "sa13_fills.csv", index=False)
    own.rejects().to_csv(output / "sa13_rejects.csv", index=False)
    stays_frame.to_csv(output / "sa13_position_episodes.csv", index=False)
    comparison.to_csv(output / "study_comparisons.csv", index=False)
    sensitivity.to_csv(output / "sharpe_sensitivity.csv", index=False)
    yearly.to_csv(output / "yearly.csv")
    equity = {name: result.equity() for name, result in base.items()}
    gross = {f"{name} (gross)": result.equity(Book.GROSS) for name, result in base.items()}
    pd.DataFrame({**equity, **gross}).rename_axis("session_date").to_csv(output / "equity.csv")
    fills.to_csv(output / "fills.csv", index=False)
    for name, history in histories.items():
        history.to_csv(output / f"history_{slug(name)}.csv")
    record = manifest(
        base,
        strategies,
        chosen,
        schedules,
        register,
        stressed_execution.costs,
        status,
        secondary,
        coverage,
        timings,
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
            sensitivity,
            coverage,
            calibrations,
            errors,
            differences,
            contributions,
            stays,
            status,
            secondary,
            register,
            timings,
        ),
        encoding="utf-8",
    )
    (output / "report_extra_SA13.md").write_text(
        report_extra(
            coverage,
            calibrations,
            errors,
            differences,
            contributions,
            comparison,
            sensitivity,
            stays,
            status,
            secondary,
        ),
        encoding="utf-8",
    )
    print(summary[["rank", "quality", "net_return", "sharpe", "max_drawdown"]].to_string())
    print(comparison[["costs", "control", "sharpe_sa13", "sharpe_control", "sharpe_difference"]])
    print(errors[["book", "sample", "pairs", "mse", "r2_oos_vs_train_mean", "sign_accuracy"]])
    print("hypothesis:", *status)
    print("secondary:", secondary)
    print(f"wrote {output}; benchmark {BENCHMARK}, references {HELD} and {SPLIT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
