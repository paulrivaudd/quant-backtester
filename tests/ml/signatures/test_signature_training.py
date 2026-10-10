"""The monthly calibration: what it cuts, purges, fits and freezes, and what cannot leak in."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("torch")
pytest.importorskip("esig")
pytest.importorskip("sklearn")

import torch

from quant_backtester.backtest.timetable import BacktestTimetable
from quant_backtester.data.calendars import CalendarRegistry, TradingCalendar
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.ml.dataset import ForwardOpenReturnBuilder, exit_session
from quant_backtester.ml.signatures.artifacts import ScheduleEntry
from quant_backtester.ml.signatures.config import (
    ModelKind,
    SignatureModelConfig,
    SignatureTrainingConfig,
    SignatureVariant,
)
from quant_backtester.ml.signatures.models import (
    AdditiveWeights,
    LinearWeights,
    internal_contributions,
)
from quant_backtester.ml.signatures.training import (
    SignatureAdditiveRegressor,
    additive_weights,
    calibrate_month,
    calibration_environment,
    feature_histories,
    fit_additive,
    month_blocks,
)
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.signatures.logsignature import (
    FeatureKind,
    SignatureFeatureBuilder,
    SignatureFeatures,
    kept_keys,
    log_signature,
)
from quant_backtester.signals.types import SignalStatus

YEAR = (date(2026, 1, 5), date(2026, 12, 31))
CUTOFF = date(2026, 8, 31)
"""The last session of August: the model of September reads nothing after its evening."""

Calibrate = Callable[..., tuple[ScheduleEntry, list[dict[str, object]]]]
Variants = Callable[..., SignatureVariant]
Models = Callable[..., SignatureModelConfig]
Markets = Callable[..., MarketDataReader]
Frames = dict[str, pd.DataFrame]


def vector_of(features: SignatureFeatures) -> np.ndarray | None:
    """Return the raw vector of some features, ``None`` when they are unusable."""
    values = features.values  # noqa: PD011 - a field of SignatureFeatures, not a frame
    return None if values is None else np.asarray(values, dtype=np.float64)


def sessions_of(calendar: TradingCalendar) -> list[date]:
    """Return the sessions of the drawn year."""
    return [day.session_date for day in calendar.sessions(*YEAR)]


@pytest.fixture
def calibrate(calendars: CalendarRegistry, xpar: TradingCalendar) -> Calibrate:
    """Return the calibration of a variant at a cutoff, on a given store."""

    def run(
        reader: MarketDataReader,
        variant: SignatureVariant,
        cutoff: date = CUTOFF,
        month: str = "2026-09",
    ) -> tuple[ScheduleEntry, list[dict[str, object]]]:
        timetable = BacktestTimetable()
        sessions = sessions_of(xpar)
        builders = {"only": SignatureFeatureBuilder(variant.features)}
        known = [session for session in sessions if session <= cutoff]
        features = feature_histories(reader, calendars, timetable, known, builders)["only"]
        instant = timetable.decision_instant(cutoff)
        return calibrate_month(
            variant,
            month=month,
            cutoff=cutoff,
            sessions=sessions,
            calendar=xpar,
            features=features,
            labels=ForwardOpenReturnBuilder(reader, xpar, timetable),
            information_cutoff=instant,
            available_at=instant + timedelta(hours=12),
        )

    return run


def scale_after(day: date, column: str, factor: float) -> Callable[[Frames], None]:
    """Return a change of one column of every fund on the sessions after a day."""

    def mutate(frames: Frames) -> None:
        for frame in frames.values():
            later = frame["session_date"] > day
            frame.loc[later, column] = frame.loc[later, column] * factor
            frame.loc[later, "high"] = frame.loc[later, ["open", "high", "close"]].max(axis=1)
            frame.loc[later, "low"] = frame.loc[later, ["open", "low", "close"]].min(axis=1)

    return mutate


# --- the network ------------------------------------------------------------------------


def test_the_network_is_additive_centred_and_of_157_parameters() -> None:
    torch.manual_seed(3)
    model = SignatureAdditiveRegressor(13, 4).double()
    inputs = torch.randn(6, 13, dtype=torch.float64)

    assert sum(parameter.numel() for parameter in model.parameters()) == 157
    assert not model.contributions(torch.zeros(2, 13, dtype=torch.float64)).any()
    assert torch.allclose(model(inputs), model.bias + model.contributions(inputs).sum(dim=1))
    with pytest.raises(ValueError, match="reads"):
        model.contributions(torch.zeros(2, 12, dtype=torch.float64))


def test_the_plain_arrays_forecast_what_the_network_forecasts() -> None:
    """Inference is written in NumPy: it has to be the model that was trained."""
    torch.manual_seed(4)
    model = SignatureAdditiveRegressor(5, 4).double()
    with torch.no_grad():
        model.bias.fill_(0.3)
    inputs = np.random.default_rng(1).normal(0.0, 2.0, (20, 5))

    weights = additive_weights(model)
    by_arrays = weights.bias + internal_contributions(weights, inputs).sum(axis=1)

    assert isinstance(weights, AdditiveWeights) and weights.parameters == 61
    assert np.allclose(by_arrays, model(torch.from_numpy(inputs)).detach().numpy(), atol=1e-13)


def drawn_examples(count: int = 300) -> tuple[np.ndarray, np.ndarray]:
    """Return normalised features and a target that is one of them, plus noise."""
    rng = np.random.default_rng(11)
    inputs = rng.normal(0.0, 1.0, (count, 13))
    return inputs, 0.6 * inputs[:, 3] + rng.normal(0.0, 0.05, count)


def test_a_fit_is_reproducible_and_keeps_the_first_best_epoch_of_validation(
    signature_model_of: Models,
) -> None:
    inputs, targets = drawn_examples()
    config = replace(signature_model_of(), learning_rate=0.02, max_epochs=60, patience=60)
    cut = (inputs[:200], targets[:200], inputs[200:], targets[200:])

    weights, history, epoch = fit_additive(*cut, config)
    again, history_again, epoch_again = fit_additive(*cut, config)

    assert [row["epoch"] for row in history] == [float(index) for index in range(1, 61)]
    assert history == history_again and epoch == epoch_again
    assert np.array_equal(weights.hidden_weight, again.hidden_weight)
    # The epoch kept is the first that beat every earlier one by more than the minimum.
    best, kept = float("inf"), 0
    for row in history:
        if row["validation_loss"] < best - config.minimum_improvement:
            best, kept = row["validation_loss"], int(row["epoch"])
    assert epoch == kept
    # The weights returned are those of that epoch, not of the last one run.
    forecast = weights.bias + internal_contributions(weights, cut[2]).sum(axis=1)
    assert float(np.mean((forecast - cut[3]) ** 2)) == pytest.approx(best, rel=1e-12)
    assert best < 0.5 * float(np.var(cut[3]))  # it learnt the feature the target is made of


def test_the_fit_stops_when_validation_stops_improving(signature_model_of: Models) -> None:
    inputs, targets = drawn_examples()
    unrelated = np.random.default_rng(12).normal(0.0, 1.0, 100)  # nothing to learn
    config = replace(signature_model_of(), learning_rate=0.05, max_epochs=300, patience=5)

    _, history, epoch = fit_additive(inputs[:200], targets[:200], inputs[200:], unrelated, config)

    assert len(history) < 300 and len(history) == epoch + 5


def test_another_seed_is_another_model(signature_model_of: Models) -> None:
    inputs, targets = drawn_examples()
    cut = (inputs[:200], targets[:200], inputs[200:], targets[200:])

    first, _, _ = fit_additive(*cut, signature_model_of())
    second, _, _ = fit_additive(*cut, replace(signature_model_of(), seed=7))

    assert not np.array_equal(first.hidden_weight, second.hidden_weight)


def test_a_loss_that_is_not_finite_stops_the_calibration(signature_model_of: Models) -> None:
    inputs, targets = drawn_examples()
    broken = targets.copy()
    broken[5] = float("nan")

    with pytest.raises(FloatingPointError, match="training loss"):
        fit_additive(inputs[:200], broken[:200], inputs[200:], targets[200:], signature_model_of())
    with pytest.raises(FloatingPointError, match="validation loss"):
        fit_additive(
            inputs[:200], targets[:200], inputs[200:], np.full(100, np.inf), signature_model_of()
        )


def test_a_target_made_of_an_area_is_found_through_the_whole_route(
    signature_variant_of: Variants, linear_artifact_of: Callable[..., object]
) -> None:
    """Path, log-signature, scaler, model, forecast: a route, not a proof on any fund."""
    from quant_backtester.ml.features import FeatureScaler
    from quant_backtester.ml.signatures.models import fit_ridge, predict

    rng = np.random.default_rng(21)
    keys = kept_keys(3)
    area = keys.index("[1,2]")
    features = []
    for _ in range(240):
        points = np.zeros((11, 3))
        points[1:, 0] = np.cumsum(rng.normal(0.0, 1.0, 10))
        points[1:, 1] = np.cumsum(rng.uniform(0.0, 0.2, 10))
        points[:, 2] = np.linspace(0.0, 1.0, 11)
        features.append(log_signature(points, 3))
    raw = np.asarray(features)
    targets = 0.8 * raw[:, area] + rng.normal(0.0, 0.01, 240)  # in percentage points

    scaler = FeatureScaler.fit(raw[:160], 5.0)
    inputs, _ = scaler.transform(raw[:160])
    held, _ = scaler.transform(raw[160:])
    weights = fit_ridge(inputs, targets[:160], alpha=1.0)
    forecast = predict(weights, held, target_scale=100.0)

    assert isinstance(weights, LinearWeights)
    assert int(np.argmax(np.abs(weights.coefficients))) == area
    assert float(np.corrcoef(forecast, targets[160:] / 100.0)[0, 1]) > 0.95


# --- the blocks -------------------------------------------------------------------------


def test_two_origins_are_purged_at_each_boundary(xpar: TradingCalendar) -> None:
    sessions = sessions_of(xpar)
    cut = SignatureTrainingConfig(80, 30, 60, 20, 0.9)

    blocks = month_blocks(sessions, CUTOFF, xpar, cut)

    last = sessions.index(CUTOFF)
    candidates = sessions[last - 29 : last + 1]
    assert blocks.complete
    assert blocks.validation == tuple(candidates[:-2])
    assert blocks.validation_purged == tuple(candidates[-2:])
    assert (len(blocks.training), len(blocks.training_purged)) == (78, 2)
    assert blocks.training_purged == tuple(sessions[last - 31 : last - 29])
    # The last label of each block ends before the next block begins.
    assert exit_session(blocks.training[-1], xpar) < blocks.validation[0]
    assert exit_session(blocks.validation[-1], xpar) == CUTOFF
    assert blocks.training[0] == sessions[last - 109]


def test_a_holiday_is_not_an_increment_of_a_date(xpar: TradingCalendar) -> None:
    """Paris is shut on Good Friday and Easter Monday: 3 and 6 April 2026."""
    sessions = sessions_of(xpar)
    cut = SignatureTrainingConfig(20, 10, 10, 5, 0.9)
    first_validation = date(2026, 4, 7)
    cutoff = sessions[sessions.index(first_validation) + 9]

    blocks = month_blocks(sessions, cutoff, xpar, cut)

    assert blocks.validation[0] == first_validation
    # Decided on 1 April, filled on the 2nd, the label ends at the open of the 7th: purged,
    # although the 1st plus two days is the 3rd. The label of 31 March ends on 2 April: kept.
    assert blocks.training_purged == (date(2026, 4, 1), date(2026, 4, 2))
    assert blocks.training[-1] == date(2026, 3, 31)
    # And a cutoff on the eve of the long weekend still purges its last two origins only.
    before_easter = month_blocks(sessions, date(2026, 4, 2), xpar, cut)
    assert before_easter.validation_purged == (date(2026, 4, 1), date(2026, 4, 2))
    assert before_easter.validation[-1] == date(2026, 3, 31)


def test_a_history_too_short_for_both_blocks_is_said_so(xpar: TradingCalendar) -> None:
    sessions = sessions_of(xpar)
    cut = SignatureTrainingConfig(80, 30, 60, 20, 0.9)

    short = month_blocks(sessions, sessions[50], xpar, cut)
    shorter = month_blocks(sessions, sessions[10], xpar, cut)

    assert not short.complete and len(short.training) == 19  # 21 candidates, two purged
    assert not shorter.complete and shorter.training == () and len(shorter.validation) == 9
    with pytest.raises(ValueError, match="not one of the sessions"):
        month_blocks(sessions, date(2026, 4, 3), xpar, cut)


# --- the features of the past -----------------------------------------------------------


def test_each_origin_has_the_features_a_decision_of_that_evening_built(
    make_signature_market: Markets,
    signature_variant_of: Variants,
    calendars: CalendarRegistry,
    xpar: TradingCalendar,
) -> None:
    reader = make_signature_market()
    builder = SignatureFeatureBuilder(signature_variant_of().features)
    sessions = sessions_of(xpar)[:40]
    timetable = BacktestTimetable()

    history = feature_histories(reader, calendars, timetable, sessions, {"only": builder})["only"]

    assert list(history) == sessions
    assert history[sessions[18]].status is SignalStatus.INSUFFICIENT_HISTORY
    assert history[sessions[19]].status is SignalStatus.OK  # twenty sessions of history
    for session in (sessions[19], sessions[39]):
        at_decision = builder.build(
            SignalContext(
                market=reader.at(timetable.decision_instant(session)),
                instruments=reader.instruments,
                calendars=calendars,
            )
        )
        built, direct = vector_of(history[session]), vector_of(at_decision)
        assert built is not None and direct is not None
        assert np.array_equal(built, direct)


def test_a_price_or_a_volume_of_later_changes_no_feature_of_before(
    make_signature_market: Markets,
    signature_variant_of: Variants,
    calendars: CalendarRegistry,
    xpar: TradingCalendar,
) -> None:
    """The look-ahead guard of the features: the future is rewritten, the past does not move."""
    day = date(2026, 3, 16)
    sessions = [session for session in sessions_of(xpar) if session <= date(2026, 4, 30)]
    builders = {"only": SignatureFeatureBuilder(signature_variant_of().features)}
    timetable = BacktestTimetable()

    def history(
        name: str, mutate: Callable[[Frames], None] | None = None
    ) -> dict[date, SignatureFeatures]:
        reader = make_signature_market(name, mutate=mutate)
        return feature_histories(reader, calendars, timetable, sessions, builders)["only"]

    base = history("base")
    for column in ("close", "volume"):
        changed = history(f"later_{column}", scale_after(day, column, 1.5))
        moved = 0
        for session in sessions:
            before, after = vector_of(base[session]), vector_of(changed[session])
            if before is None or after is None:
                assert before is None and after is None
            elif session <= day:
                assert np.array_equal(before, after)
            else:
                moved += int(not np.array_equal(before, after))
        assert moved > 0  # the change was real: the features after it are other features


# --- one month's calibration ------------------------------------------------------------


@pytest.mark.parametrize("kind", [ModelKind.RIDGE, ModelKind.NEURAL_ADDITIVE])
def test_a_month_gets_a_frozen_model_and_the_account_of_its_fit(
    kind: ModelKind,
    calibrate: Calibrate,
    make_signature_market: Markets,
    signature_variant_of: Variants,
    xpar: TradingCalendar,
) -> None:
    variant = signature_variant_of(kind=kind)

    entry, rows = calibrate(make_signature_market(), variant)
    artifact = entry.artifact

    assert artifact is not None and entry.month == "2026-09" and entry.reason is None
    assert artifact.kind is kind and artifact.variant_id == variant.variant_id
    assert artifact.feature_names == variant.features.names() and len(artifact.feature_names) == 13
    assert (artifact.training_examples, artifact.validation_examples) == (78, 28)
    assert exit_session(artifact.training_end, xpar) < artifact.validation_start
    assert exit_session(artifact.validation_end, xpar) == CUTOFF
    assert artifact.information_cutoff == BacktestTimetable().decision_instant(CUTOFF)
    assert artifact.available_at - artifact.information_cutoff == timedelta(hours=12)
    assert artifact.environment == calibration_environment(kind, FeatureKind.LOGSIGNATURE)
    assert artifact.environment["backend"] == "esig_roughpy"
    first = rows[0]
    assert first["status"] == "CALIBRATED" and first["model_id"] == artifact.model_id
    assert (first["training_purged"], first["validation_purged"]) == (2, 2)
    assert (first["training_valid"], first["validation_valid"]) == (78, 28)
    if kind is ModelKind.RIDGE:
        assert len(rows) == 1 and artifact.selected_epoch is None
        assert artifact.weights.parameters == 14
    else:
        assert [row["epoch"] for row in rows] == [float(n) for n in range(1, len(rows) + 1)]
        assert artifact.selected_epoch is not None and 1 <= artifact.selected_epoch <= len(rows)
        assert artifact.weights.parameters == 157
        assert {row["selected_epoch"] for row in rows} == {artifact.selected_epoch}
    # A forecast of the frozen model is its reference plus its contributions.
    prediction = artifact.predict([float(value) for value in artifact.scaler_mean])
    assert prediction.contributions == pytest.approx([0.0] * 13, abs=1e-15)
    assert prediction.mean == pytest.approx(prediction.reference)


def test_a_calibration_is_reproducible_to_the_identifier(
    calibrate: Calibrate, make_signature_market: Markets, signature_variant_of: Variants
) -> None:
    variant = signature_variant_of(kind=ModelKind.NEURAL_ADDITIVE)

    first, _ = calibrate(make_signature_market("one"), variant)
    second, _ = calibrate(make_signature_market("two"), variant)

    assert first.artifact is not None and second.artifact is not None
    assert first.artifact.model_id == second.artifact.model_id


@pytest.mark.parametrize("kind", [ModelKind.RIDGE, ModelKind.NEURAL_ADDITIVE])
@pytest.mark.parametrize("column", ["open", "close", "volume"])
def test_the_month_a_model_is_for_changes_nothing_of_the_model(
    kind: ModelKind,
    column: str,
    calibrate: Calibrate,
    make_signature_market: Markets,
    signature_variant_of: Variants,
) -> None:
    """The look-ahead guard of the calibration: the test month is rewritten, the model stays."""
    variant = signature_variant_of(kind=kind)

    base, _ = calibrate(make_signature_market("base"), variant)
    changed, _ = calibrate(
        make_signature_market("changed", mutate=scale_after(CUTOFF, column, 1.4)), variant
    )

    assert base.artifact is not None and changed.artifact is not None
    assert base.artifact.model_id == changed.artifact.model_id


def test_the_validation_labels_choose_an_epoch_and_never_touch_the_normalisation(
    calibrate: Calibrate,
    make_signature_market: Markets,
    signature_variant_of: Variants,
    xpar: TradingCalendar,
) -> None:
    sessions = sessions_of(xpar)
    first_validation = sessions[sessions.index(CUTOFF) - 29]

    def other_opens(frames: Frames) -> None:
        """Rewrite the opens of the validation block: its labels, and no feature."""
        rng = np.random.default_rng(5)
        for frame in frames.values():
            block = (frame["session_date"] >= first_validation) & (frame["session_date"] <= CUTOFF)
            shaken = frame.loc[block, "open"] * np.exp(rng.normal(0.0, 0.03, int(block.sum())))
            frame.loc[block, "open"] = shaken
            frame.loc[block, "high"] = frame.loc[block, ["open", "high", "close"]].max(axis=1)
            frame.loc[block, "low"] = frame.loc[block, ["open", "low", "close"]].min(axis=1)

    for kind in (ModelKind.RIDGE, ModelKind.NEURAL_ADDITIVE):
        variant = signature_variant_of(kind=kind)
        base, base_rows = calibrate(make_signature_market(f"base_{kind.value}"), variant)
        other, other_rows = calibrate(
            make_signature_market(f"other_{kind.value}", mutate=other_opens), variant
        )
        assert base.artifact is not None and other.artifact is not None
        assert np.array_equal(base.artifact.scaler_mean, other.artifact.scaler_mean)
        assert np.array_equal(base.artifact.scaler_std, other.artifact.scaler_std)
        assert base.artifact.training_label_mean == other.artifact.training_label_mean
        assert base_rows[0]["training_loss"] == other_rows[0]["training_loss"]
        assert base_rows[0]["validation_loss"] != other_rows[0]["validation_loss"]
        if kind is ModelKind.RIDGE:
            # Nothing is selected for a ridge: validation does not reach its weights at all.
            for name, values in base.artifact.weights.arrays().items():
                assert np.array_equal(other.artifact.weights.arrays()[name], values)


def test_the_normalisation_is_that_of_the_training_block_alone(
    calibrate: Calibrate,
    make_signature_market: Markets,
    signature_variant_of: Variants,
    calendars: CalendarRegistry,
    xpar: TradingCalendar,
) -> None:
    variant = signature_variant_of()
    reader = make_signature_market()
    sessions = sessions_of(xpar)
    blocks = month_blocks(sessions, CUTOFF, xpar, variant.training)
    features = feature_histories(
        reader,
        calendars,
        BacktestTimetable(),
        blocks.training,
        {"only": SignatureFeatureBuilder(variant.features)},
    )["only"]
    rows = np.asarray([vector_of(features[origin]) for origin in blocks.training])

    entry, _ = calibrate(reader, variant)

    assert entry.artifact is not None
    assert np.allclose(entry.artifact.scaler_mean, rows.mean(axis=0), rtol=1e-12, atol=0.0)


def test_a_month_without_enough_examples_gets_no_model_and_says_why(
    calibrate: Calibrate,
    make_signature_market: Markets,
    signature_variant_of: Variants,
    xpar: TradingCalendar,
) -> None:
    reader = make_signature_market()
    variant = signature_variant_of()
    sessions = sessions_of(xpar)

    # The blocks reach back to sessions the path has no history for.
    share, share_rows = calibrate(reader, variant, sessions[113], "2026-07")
    few, few_rows = calibrate(reader, variant, sessions[80], "2026-05")
    strict = replace(variant, training=SignatureTrainingConfig(80, 30, 60, 29, 0.9))
    held, _ = calibrate(reader, strict)

    assert share.artifact is None and share.reason is not None
    assert share.reason.startswith("VALID_SHARE:") and share.reason.endswith("<0.9")
    assert share_rows == [{**share_rows[0], "status": share.reason}] and len(share_rows) == 1
    assert share_rows[0]["training_valid"] == 63  # 78 after the purge, 15 without a window
    assert few.artifact is None and few.reason is not None
    assert few.reason.startswith("TRAINING_EXAMPLES:") and few_rows[0]["month"] == "2026-05"
    assert held.artifact is None and held.reason == "VALIDATION_EXAMPLES:28<29"


def test_a_missing_open_stops_the_calibration_and_is_not_a_return_of_zero(
    calibrate: Calibrate, make_signature_market: Markets, signature_variant_of: Variants
) -> None:
    from quant_backtester.ml.dataset import MissingForwardOpen

    def without_an_open(frames: Frames) -> None:
        frame = frames["ETF_EU"]
        frame.loc[frame["session_date"] == date(2026, 6, 15), "open"] = float("nan")

    with pytest.raises(MissingForwardOpen):
        calibrate(make_signature_market(mutate=without_an_open), signature_variant_of())
