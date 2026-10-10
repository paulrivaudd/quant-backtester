"""A frozen model and its schedule: identified by content, used only when it could be had."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from quant_backtester.ml.signatures.artifacts import (
    ARRAYS_FILE,
    ArtifactMismatch,
    ModelCausalityError,
    ScheduleEntry,
    SignatureArtifact,
    SignatureModelSchedule,
)
from quant_backtester.ml.signatures.config import ModelKind, SignatureVariant
from quant_backtester.ml.signatures.models import LinearWeights

CUTOFF = datetime(2026, 8, 31, 21, 0, tzinfo=UTC)
"""23:00 in Paris on the last session of August."""

Variants = Callable[..., SignatureVariant]
Artifacts = Callable[..., SignatureArtifact]


def coefficients(count: int = 13) -> list[float]:
    """Return one distinct coefficient per feature."""
    return [0.01 * (index + 1) for index in range(count)]


def test_the_forecast_is_the_reference_plus_the_contributions(
    signature_variant_of: Variants, linear_artifact_of: Artifacts
) -> None:
    artifact = linear_artifact_of(
        signature_variant_of(), "2026-09", CUTOFF, coefficients=coefficients(), bias=0.05
    )
    values = [float(index) for index in range(13)]

    prediction = artifact.predict(values)

    assert prediction.reference == pytest.approx(0.0005)
    assert len(prediction.contributions) == 13
    assert prediction.mean == pytest.approx(prediction.reference + sum(prediction.contributions))
    assert prediction.contributions[2] == pytest.approx(0.03 * 2.0 / 100.0)
    assert artifact.kind is ModelKind.RIDGE and artifact.variant_id == "test_logsig3"
    assert (artifact.input_clip, artifact.target_scale) == (5.0, 100.0)


def test_a_normalised_feature_beyond_the_clip_is_clipped_and_counted(
    signature_variant_of: Variants, linear_artifact_of: Artifacts
) -> None:
    artifact = linear_artifact_of(
        signature_variant_of(), "2026-09", CUTOFF, coefficients=coefficients()
    )

    inside = artifact.predict([1.0] * 13)
    beyond = artifact.predict([1.0] * 12 + [40.0])

    assert inside.clipped == 0 and beyond.clipped == 1
    assert beyond.contributions[12] == pytest.approx(0.13 * 5.0 / 100.0)  # clipped at 5


def test_a_vector_that_is_not_the_models_is_refused(
    signature_variant_of: Variants, linear_artifact_of: Artifacts
) -> None:
    artifact = linear_artifact_of(signature_variant_of(), "2026-09", CUTOFF)

    with pytest.raises(ValueError, match="13 finite features"):
        artifact.predict([0.0] * 12)
    with pytest.raises(ValueError, match="13 finite features"):
        artifact.predict([0.0] * 12 + [float("nan")])


def test_an_artifact_is_identified_by_everything_it_is_made_of(
    signature_variant_of: Variants, linear_artifact_of: Artifacts
) -> None:
    """Two models of one dimension are two models."""
    variant = signature_variant_of()
    base = linear_artifact_of(variant, "2026-09", CUTOFF, coefficients=coefficients())
    same = linear_artifact_of(variant, "2026-09", CUTOFF, coefficients=coefficients())
    others = [
        linear_artifact_of(variant, "2026-09", CUTOFF, coefficients=coefficients()[::-1]),
        linear_artifact_of(variant, "2026-09", CUTOFF, coefficients=coefficients(), bias=0.1),
        linear_artifact_of(
            variant, "2026-09", CUTOFF - timedelta(days=1), coefficients=coefficients()
        ),
        linear_artifact_of(
            signature_variant_of("another"), "2026-09", CUTOFF, coefficients=coefficients()
        ),
        replace(base, scaler_std=np.full(13, 2.0), model_id=""),
        replace(base, feature_names=base.feature_names[::-1], model_id=""),
        replace(base, training_label_mean=0.001, model_id=""),
    ]

    assert same.model_id == base.model_id and len(base.model_id) == 64
    assert len({base.model_id, *(other.model_id for other in others)}) == len(others) + 1


def test_an_artifact_comes_back_from_its_folder_or_is_refused(
    signature_variant_of: Variants, linear_artifact_of: Artifacts, tmp_path: Path
) -> None:
    artifact = linear_artifact_of(
        signature_variant_of(), "2026-09", CUTOFF, coefficients=coefficients(), bias=0.05
    )
    folder = artifact.save(tmp_path / "2026-09")

    loaded = SignatureArtifact.load(folder)

    assert loaded.model_id == artifact.model_id
    assert loaded.predict([1.0] * 13) == artifact.predict([1.0] * 13)
    assert loaded.information_cutoff == CUTOFF and loaded.month == "2026-09"
    # Another model's arrays in the same folder: the same shapes, not the same model.
    other = linear_artifact_of(signature_variant_of(), "2026-09", CUTOFF, bias=9.0)
    arrays = {
        **other.weights.arrays(),
        "scaler_mean": other.scaler_mean,
        "scaler_std": other.scaler_std,
    }
    np.savez(folder / ARRAYS_FILE, **arrays)  # type: ignore[arg-type]
    with pytest.raises(ArtifactMismatch, match="recorded identity"):
        SignatureArtifact.load(folder)


def test_an_artifact_that_contradicts_itself_is_refused(
    signature_variant_of: Variants, linear_artifact_of: Artifacts
) -> None:
    base = linear_artifact_of(signature_variant_of(), "2026-09", CUTOFF)

    with pytest.raises(ArtifactMismatch, match="disagree"):
        replace(base, weights=LinearWeights(np.zeros(5), 0.0), model_id="")
    with pytest.raises(ValueError, match="before its information cutoff"):
        replace(base, available_at=CUTOFF - timedelta(hours=1), model_id="")
    with pytest.raises(ValueError, match="timezone-aware"):
        replace(base, information_cutoff=CUTOFF.replace(tzinfo=None), model_id="")
    with pytest.raises(ArtifactMismatch, match="recorded identity"):
        replace(base, training_examples=101)  # the content moved under a kept identity


def schedule(
    signature_variant_of: Variants, linear_artifact_of: Artifacts
) -> SignatureModelSchedule:
    """Return a schedule with a model for September, none for October, one for November."""
    variant = signature_variant_of()
    return SignatureModelSchedule(
        variant_id=variant.variant_id,
        timezone="Europe/Paris",
        entries=(
            ScheduleEntry("2026-09", linear_artifact_of(variant, "2026-09", CUTOFF)),
            ScheduleEntry("2026-10", None, "TRAINING_EXAMPLES:10<60"),
            ScheduleEntry(
                "2026-11",
                linear_artifact_of(
                    variant, "2026-11", datetime(2026, 10, 30, 22, 0, tzinfo=UTC), bias=0.2
                ),
            ),
        ),
    )


def test_a_decision_takes_the_model_of_its_month(
    signature_variant_of: Variants, linear_artifact_of: Artifacts
) -> None:
    planned = schedule(signature_variant_of, linear_artifact_of)

    first = planned.entry_at(datetime(2026, 9, 1, 21, 0, tzinfo=UTC))
    last = planned.entry_at(datetime(2026, 9, 30, 21, 0, tzinfo=UTC))
    none = planned.entry_at(datetime(2026, 10, 15, 21, 0, tzinfo=UTC))

    assert first.artifact is not None and first is last  # one frozen model for the month
    assert none.artifact is None and none.identity == "NO_MODEL:TRAINING_EXAMPLES:10<60"
    # The month is that of the local date: 22:30 UTC on 31 October is 23:30 in Paris,
    # still October, whose entry holds no model.
    assert planned.month_of(datetime(2026, 10, 31, 22, 30, tzinfo=UTC)) == "2026-10"
    assert planned.month_of(datetime(2026, 8, 31, 22, 30, tzinfo=UTC)) == "2026-09"  # CEST


def test_a_model_a_decision_could_not_have_had_stops_the_run(
    signature_variant_of: Variants, linear_artifact_of: Artifacts
) -> None:
    variant = signature_variant_of()
    late = linear_artifact_of(
        variant, "2026-09", datetime(2026, 9, 10, 21, 0, tzinfo=UTC), bias=0.3
    )
    slow = linear_artifact_of(
        variant, "2026-09", CUTOFF, bias=0.4, available_after=timedelta(days=3)
    )

    def plan(artifact: SignatureArtifact) -> SignatureModelSchedule:
        return SignatureModelSchedule(
            variant.variant_id, "Europe/Paris", (ScheduleEntry("2026-09", artifact),)
        )

    with pytest.raises(ModelCausalityError, match="cannot be used"):
        plan(late).entry_at(datetime(2026, 9, 1, 21, 0, tzinfo=UTC))  # cutoff in the future
    with pytest.raises(ModelCausalityError, match="cannot be used"):
        plan(slow).entry_at(datetime(2026, 9, 1, 21, 0, tzinfo=UTC))  # not ready yet
    assert plan(slow).entry_at(datetime(2026, 9, 4, 21, 0, tzinfo=UTC)).artifact is slow
    with pytest.raises(ModelCausalityError, match="does not cover"):
        plan(slow).entry_at(datetime(2026, 12, 1, 21, 0, tzinfo=UTC))
    with pytest.raises(ValueError, match="timezone-aware"):
        plan(slow).entry_at(datetime(2026, 9, 4, 21, 0))


def test_a_schedule_is_identified_by_its_months_and_their_models(
    signature_variant_of: Variants, linear_artifact_of: Artifacts
) -> None:
    planned = schedule(signature_variant_of, linear_artifact_of)
    again = schedule(signature_variant_of, linear_artifact_of)
    shorter = replace(planned, entries=planned.entries[:2])

    assert planned.schedule_id == again.schedule_id != shorter.schedule_id
    months = planned.definition()["months"]
    assert isinstance(months, dict) and list(months) == ["2026-09", "2026-10", "2026-11"]
    assert months["2026-10"].startswith("NO_MODEL:")


def test_a_schedule_a_decision_could_read_two_ways_is_refused(
    signature_variant_of: Variants, linear_artifact_of: Artifacts
) -> None:
    variant = signature_variant_of()
    artifact = linear_artifact_of(variant, "2026-09", CUTOFF)
    entry = ScheduleEntry("2026-09", artifact)

    with pytest.raises(ValueError, match="once, in order"):
        SignatureModelSchedule(variant.variant_id, "Europe/Paris", (entry, entry))
    with pytest.raises(ValueError, match="belongs to"):
        SignatureModelSchedule("another_variant", "Europe/Paris", (entry,))
    with pytest.raises(ValueError, match="planned for"):
        ScheduleEntry("2026-10", artifact)
    with pytest.raises(ValueError, match="not both"):
        ScheduleEntry("2026-09", artifact, "a reason")
    with pytest.raises(ValueError, match="not both"):
        ScheduleEntry("2026-09", None)
