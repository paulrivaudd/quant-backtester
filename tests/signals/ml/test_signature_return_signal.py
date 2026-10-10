"""The forecast of a frozen signature model: which model, on which features, known when."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("esig")
pytest.importorskip("roughpy")

from quant_backtester.data.reader import MarketDataReader
from quant_backtester.ml.signatures.artifacts import (
    ModelCausalityError,
    ScheduleEntry,
    SignatureModelSchedule,
)
from quant_backtester.ml.signatures.config import SignatureVariant
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.ml.signature_return import MODEL_COLUMNS, SignatureReturnSignal
from quant_backtester.signals.signatures.logsignature import (
    FeatureKind,
    SignatureFeatureBuilder,
    kept_keys,
)
from quant_backtester.signals.signatures.path import SignaturePathConfig
from quant_backtester.signals.types import SignalStatus

FUND, OTHER = "ETF_EU", "ETF_OTHER"
DECISION = date(2026, 9, 14)

Markets = Callable[..., MarketDataReader]
Contexts = Callable[[MarketDataReader, datetime], SignalContext]
Variants = Callable[..., SignatureVariant]
Schedules = Callable[..., SignatureModelSchedule]
Frames = dict[str, pd.DataFrame]


def evening(day: date) -> datetime:
    """Return the decision instant of a September or October session: 23:00 in Paris."""
    return datetime(day.year, day.month, day.day, 21, 0, tzinfo=UTC)


def signal_of(schedule: SignatureModelSchedule, variant: SignatureVariant) -> SignatureReturnSignal:
    """Return the signal reading a schedule of a variant."""
    return SignatureReturnSignal(
        signal_id=f"signature_return_{variant.variant_id}",
        instrument_id=variant.instrument_id,
        features=variant.features,
        schedule_id=schedule.schedule_id,
        _schedule=schedule,
    )


def coefficients(count: int = 13) -> list[float]:
    """Return one distinct coefficient per feature."""
    return [0.02 * (index + 1) * (-1) ** index for index in range(count)]


def test_the_value_is_the_forecast_of_the_months_model_in_decimal(
    make_signature_market: Markets,
    make_context: Contexts,
    signature_variant_of: Variants,
    signature_schedule_of: Schedules,
) -> None:
    variant = signature_variant_of()
    schedule = signature_schedule_of(variant, {"2026-09": coefficients()})
    signal = signal_of(schedule, variant)
    context = make_context(make_signature_market(), evening(DECISION))

    result = signal.compute(context, (FUND,))
    explained = signal.explain(context)

    assert result.status(FUND) is SignalStatus.OK
    features, prediction = explained.features, explained.prediction
    assert prediction is not None
    # The scaler of the hand-written model is the identity: the forecast is the sum of
    # coefficient times feature clipped at five, in percentage points, divided once by
    # one hundred.
    raw = np.asarray(features.values)
    by_hand = float(np.dot(coefficients(), np.clip(raw, -5.0, 5.0))) / 100.0
    assert result.value(FUND) == pytest.approx(by_hand, rel=1e-12)
    assert prediction.reference + sum(prediction.contributions) == pytest.approx(by_hand)
    assert prediction.clipped == int((np.abs(raw) > 5.0).sum())
    assert features.names == tuple(f"{FUND}:{key}" for key in kept_keys(3))
    row = result.frame.loc[FUND]
    artifact = schedule.entries[0].artifact
    assert artifact is not None
    assert (row["model_id"], row["model_month"]) == (artifact.model_id, "2026-09")
    assert row["information_cutoff"] == artifact.information_cutoff.isoformat()
    assert row["reason"] is None and row["reference"] == 0.0
    assert row["clipped"] == prediction.clipped
    assert (row["input_start_date"], row["input_end_date"]) == (date(2026, 8, 18), DECISION)
    assert row["max_input_age_sessions"] == 0
    assert set(MODEL_COLUMNS) <= set(result.frame.columns)


def test_the_signal_and_the_calibration_build_the_same_features(
    make_signature_market: Markets,
    make_context: Contexts,
    signature_variant_of: Variants,
    signature_schedule_of: Schedules,
) -> None:
    variant = signature_variant_of()
    signal = signal_of(signature_schedule_of(variant, {"2026-09": 0.1}), variant)
    context = make_context(make_signature_market(), evening(DECISION))

    at_inference = signal.explain(context).features
    at_calibration = SignatureFeatureBuilder(variant.features).build(context)

    assert at_inference == at_calibration and at_inference.status is SignalStatus.OK


@pytest.mark.parametrize("column", ["close", "volume", "open"])
def test_a_bar_of_tomorrow_changes_nothing_of_tonights_forecast(
    column: str,
    make_signature_market: Markets,
    make_context: Contexts,
    signature_variant_of: Variants,
    signature_schedule_of: Schedules,
) -> None:
    """The look-ahead guard: the days after the decision are rewritten, the forecast stays."""
    variant = signature_variant_of()
    signal = signal_of(signature_schedule_of(variant, {"2026-09": coefficients()}), variant)

    def later(frames: Frames) -> None:
        for frame in frames.values():
            after = frame["session_date"] > DECISION
            frame.loc[after, column] = frame.loc[after, column] * 1.3
            frame.loc[after, "high"] = frame.loc[after, ["open", "high", "close"]].max(axis=1)
            frame.loc[after, "low"] = frame.loc[after, ["open", "low", "close"]].min(axis=1)

    base = signal.compute(make_context(make_signature_market("base"), evening(DECISION)), (FUND,))
    changed_market = make_signature_market("changed", mutate=later)
    changed = signal.compute(make_context(changed_market, evening(DECISION)), (FUND,))
    next_day = signal.compute(make_context(changed_market, evening(date(2026, 9, 15))), (FUND,))
    next_base = signal.compute(
        make_context(make_signature_market("again"), evening(date(2026, 9, 15))), (FUND,)
    )

    assert changed.value(FUND) == base.value(FUND)
    if column != "open":  # an open is not a feature: it is only ever a label
        assert next_day.value(FUND) != next_base.value(FUND)


def test_a_month_without_a_model_is_a_status_and_a_reason_not_a_forecast(
    make_signature_market: Markets,
    make_context: Contexts,
    signature_variant_of: Variants,
    signature_schedule_of: Schedules,
) -> None:
    variant = signature_variant_of()
    schedule = signature_schedule_of(
        variant, {"2026-09": 0.1, "2026-10": "TRAINING_EXAMPLES:10<60"}
    )
    signal = signal_of(schedule, variant)

    result = signal.compute(
        make_context(make_signature_market(), evening(date(2026, 10, 14))), (FUND,)
    )

    row = result.frame.loc[FUND]
    assert result.status(FUND) is SignalStatus.INSUFFICIENT_HISTORY
    assert np.isnan(result.value(FUND))
    assert row["reason"] == "NO_MODEL:TRAINING_EXAMPLES:10<60"
    assert row["model_id"] is None and row["model_month"] == "2026-10"
    assert row["input_end_date"] == date(2026, 10, 14)  # the features were there: no model was


def test_a_window_that_cannot_be_built_gives_its_own_status_and_reason(
    make_signature_market: Markets,
    make_context: Contexts,
    signature_variant_of: Variants,
    signature_schedule_of: Schedules,
) -> None:
    variant = signature_variant_of()
    signal = signal_of(signature_schedule_of(variant, {"2026-01": 0.1, "2026-09": 0.1}), variant)

    def hole(frames: Frames) -> None:
        frame = frames[FUND]
        kept = frame.loc[frame["session_date"] != date(2026, 9, 9)]
        frames[FUND] = pd.DataFrame(kept).reset_index(drop=True)

    def no_volume(frames: Frames) -> None:
        frame = frames[FUND]
        frame.loc[frame["session_date"] == date(2026, 9, 9), "volume"] = float("nan")

    short = signal.compute(
        make_context(make_signature_market("short"), datetime(2026, 1, 20, 22, 0, tzinfo=UTC)),
        (FUND,),
    )
    holed = signal.compute(
        make_context(make_signature_market("holed", mutate=hole), evening(DECISION)), (FUND,)
    )
    silent = signal.compute(
        make_context(make_signature_market("silent", mutate=no_volume), evening(DECISION)),
        (FUND,),
    )

    assert short.status(FUND) is SignalStatus.INSUFFICIENT_HISTORY
    assert short.frame.loc[FUND, "model_id"] is not None  # the model was there: no window was
    assert holed.status(FUND) is SignalStatus.NON_CONSECUTIVE_HISTORY
    assert silent.status(FUND) is not SignalStatus.OK
    for result in (short, holed, silent):
        assert np.isnan(result.value(FUND)) and result.frame.loc[FUND, "clipped"] is None


def test_a_model_the_decision_could_not_have_had_stops_the_run(
    make_signature_market: Markets,
    make_context: Contexts,
    signature_variant_of: Variants,
    linear_artifact_of: Callable[..., object],
) -> None:
    variant = signature_variant_of()
    market = make_signature_market()
    late = linear_artifact_of(variant, "2026-09", evening(date(2026, 9, 20)))
    schedule = SignatureModelSchedule(
        variant.variant_id,
        "Europe/Paris",
        (ScheduleEntry("2026-09", late),),  # type: ignore[arg-type]
    )
    signal = signal_of(schedule, variant)

    with pytest.raises(ModelCausalityError, match="cannot be used"):
        signal.compute(make_context(market, evening(DECISION)), (FUND,))
    with pytest.raises(ModelCausalityError, match="does not cover"):
        signal.compute(make_context(market, evening(date(2026, 10, 14))), (FUND,))
    # Once its information is in the past and it is ready, the same model is used.
    assert (
        signal.compute(make_context(market, evening(date(2026, 9, 22))), (FUND,)).status(FUND)
        is SignalStatus.OK
    )


def test_the_context_variant_reads_two_blocks_and_never_falls_back_on_one(
    make_signature_market: Markets,
    make_context: Contexts,
    signature_variant_of: Variants,
    signature_schedule_of: Schedules,
) -> None:
    variant = signature_variant_of("test_context", instruments=(FUND, OTHER))
    weights = coefficients(26)
    signal = signal_of(signature_schedule_of(variant, {"2026-09": weights}), variant)

    def other_later(frames: Frames) -> None:
        frame = frames[OTHER]
        after = frame["session_date"] > DECISION
        frame.loc[after, ["open", "high", "low", "close"]] *= 1.3
        frame.loc[after, "volume"] *= 3.0

    def other_holed(frames: Frames) -> None:
        frame = frames[OTHER]
        kept = frame.loc[frame["session_date"] != date(2026, 9, 9)]
        frames[OTHER] = pd.DataFrame(kept).reset_index(drop=True)

    base_context = make_context(make_signature_market("base"), evening(DECISION))
    base = signal.compute(base_context, (FUND,))
    future = signal.compute(
        make_context(make_signature_market("future", mutate=other_later), evening(DECISION)),
        (FUND,),
    )
    holed = signal.compute(
        make_context(make_signature_market("holed", mutate=other_holed), evening(DECISION)),
        (FUND,),
    )

    names = signal.explain(base_context).features.names
    assert len(names) == 26
    assert names[:13] == tuple(f"{FUND}:{key}" for key in kept_keys(3))
    assert names[13:] == tuple(f"{OTHER}:{key}" for key in kept_keys(3))
    assert base.status(FUND) is SignalStatus.OK and future.value(FUND) == base.value(FUND)
    # The second process is required: without its window there is no forecast at all.
    assert holed.status(FUND) is SignalStatus.NON_CONSECUTIVE_HISTORY
    assert str(holed.frame.loc[FUND, "reason"]).startswith(OTHER)
    # And the two blocks are two different descriptions: swapping them is another forecast.
    swapped = signature_variant_of("test_swapped", instruments=(OTHER, FUND))
    other = signal_of(signature_schedule_of(swapped, {"2026-09": weights}), swapped)
    assert other.compute(base_context, (FUND,)).value(FUND) != base.value(FUND)


def test_a_model_fitted_on_other_features_is_refused(
    make_signature_market: Markets,
    make_context: Contexts,
    signature_variant_of: Variants,
    signature_schedule_of: Schedules,
    signature_path: SignaturePathConfig,
) -> None:
    """Thirteen numbers are not enough: they must be the thirteen the model was fitted on."""
    variant = signature_variant_of()
    schedule = signature_schedule_of(variant, {"2026-09": 0.1})
    other = signature_variant_of(instruments=(OTHER,))  # same size, another process
    signal = SignatureReturnSignal(
        signal_id="mismatched",
        instrument_id=FUND,
        features=other.features,
        schedule_id=schedule.schedule_id,
        _schedule=schedule,
    )

    with pytest.raises(ValueError, match="other features"):
        signal.compute(make_context(make_signature_market(), evening(DECISION)), (FUND,))
    assert other.features.kind is FeatureKind.LOGSIGNATURE and signature_path.steps == 10


def test_the_signal_is_identified_by_its_schedule_and_answers_for_one_fund(
    make_signature_market: Markets,
    make_context: Contexts,
    signature_variant_of: Variants,
    signature_schedule_of: Schedules,
) -> None:
    variant = signature_variant_of()
    one = signature_schedule_of(variant, {"2026-09": 0.1})
    two = signature_schedule_of(variant, {"2026-09": 0.2})

    assert signal_of(one, variant).fingerprint() != signal_of(two, variant).fingerprint()
    assert signal_of(one, variant).fingerprint() == signal_of(one, variant).fingerprint()
    definition = signal_of(one, variant).definition()
    assert definition["schedule_id"] == one.schedule_id
    assert definition["target"] == "SIMPLE_TOTAL_RETURN_NEXT_OPEN_TO_FOLLOWING_OPEN"
    with pytest.raises(ValueError, match="not the one it names"):
        SignatureReturnSignal("s", FUND, variant.features, two.schedule_id, one)
    with pytest.raises(ValueError, match="nothing else"):
        signal_of(one, variant).compute(
            make_context(make_signature_market(), evening(DECISION)), (FUND, OTHER)
        )
