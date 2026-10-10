"""The return a frozen signature model forecasts for the next investable period.

At the evening of ``t`` the signal builds the features of its window, takes
the model its schedule plans for that month - and only if that model could be
had by then - and returns the forecast simple return from the open of ``t +
1``, where an order decided now is filled, to the open of ``t + 2``.

Nothing is trained here and nothing is read from a file: the schedule and its
artifacts are loaded before the run. The forecast of a decision is a function
of the context and of the schedule, whatever was computed before.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import pandas as pd

from quant_backtester.ml.signatures.artifacts import (
    NO_MODEL,
    ScheduleEntry,
    SignatureModelSchedule,
    SignaturePrediction,
)
from quant_backtester.signals.base import Signal, SignalResult, build_result_frame
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.signatures.logsignature import (
    FeatureSpec,
    SignatureFeatureBuilder,
    SignatureFeatures,
)
from quant_backtester.signals.types import SignalStatus, SignalUnit, WindowMode, require_identifier

MODEL_COLUMNS = ("model_id", "model_month", "information_cutoff", "clipped", "reason", "reference")
"""The columns a result carries beside the usual ones: which model, and what was wrong."""


@dataclass(frozen=True, slots=True)
class SignatureExplanation:
    """Everything one decision's forecast was made of.

    Attributes
    ----------
    features : SignatureFeatures
        The features built at the decision, usable or not.
    entry : ScheduleEntry
        The month's entry of the schedule: a model, or the reason there is none.
    prediction : SignaturePrediction | None
        The forecast and its contributions; ``None`` without features or
        without a model.
    """

    features: SignatureFeatures
    entry: ScheduleEntry
    prediction: SignaturePrediction | None

    @property
    def status(self) -> SignalStatus:
        """Return the status of the forecast: ``OK`` only with features and a model."""
        if self.features.status is not SignalStatus.OK:
            return self.features.status
        return SignalStatus.OK if self.prediction is not None else SignalStatus.INSUFFICIENT_HISTORY

    @property
    def reason(self) -> str | None:
        """Return what was wrong beyond the status: the features' reason, or the missing model's."""
        if self.features.status is not SignalStatus.OK:
            return self.features.reason
        return None if self.entry.artifact is not None else f"{NO_MODEL}:{self.entry.reason}"


@dataclass(frozen=True, slots=True)
class SignatureReturnSignal(Signal):
    """The forecast simple return of one fund over the next open-to-open period.

    Attributes
    ----------
    signal_id : str
        Stable name of this instance.
    instrument_id : str
        The fund whose return is forecast, and the only one the signal answers for.
    features : FeatureSpec
        The representation the models read: possibly several processes, of
        which the fund forecast is one or not.
    schedule_id : str
        The identity of the schedule of models.
    _schedule : SignatureModelSchedule
        The models, loaded before the run. Not part of the definition:
        ``schedule_id`` is what identifies it.

    Raises
    ------
    ValueError
        If a name is empty or the schedule handed over is another one.

    Notes
    -----
    ``value`` is the forecast as a decimal simple return, of unit
    ``FRACTION``. A window that is short, holed, stale or invalid gives its
    status; so does a reference activity of zero. A month for which no model
    could be calibrated gives ``INSUFFICIENT_HISTORY`` with the reason
    ``NO_MODEL``: a decision in cash that stays in the results. A model whose
    cutoff or availability is not before the decision, a month the schedule
    does not cover and a forecast that is not finite are not market
    situations: they stop the run.
    """

    signal_id: str
    instrument_id: str
    features: FeatureSpec
    schedule_id: str
    _schedule: SignatureModelSchedule = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        """Refuse an empty name or a schedule that is not the one identified."""
        require_identifier(self.signal_id, "signal_id")
        require_identifier(self.instrument_id, "instrument_id")
        if self._schedule.schedule_id != self.schedule_id:
            raise ValueError("the schedule handed to the signal is not the one it names")

    def definition(self) -> Mapping[str, object]:
        """Return every parameter that changes the number, the schedule's identity included."""
        return {
            "type": "SignatureReturnSignal",
            "instrument_id": self.instrument_id,
            "features": self.features.definition(),
            "schedule_id": self.schedule_id,
            "variant_id": self._schedule.variant_id,
            "target": "SIMPLE_TOTAL_RETURN_NEXT_OPEN_TO_FOLLOWING_OPEN",
            "window_mode": WindowMode.CONSECUTIVE_SESSIONS.value,
            "unit": SignalUnit.FRACTION.value,
        }

    def explain(self, context: SignalContext) -> SignatureExplanation:
        """Return the features, the model and the decomposed forecast of one decision.

        Raises
        ------
        ModelCausalityError
            If the schedule plans no model for the decision's month, or one
            the decision could not have had.
        ValueError
            If the model returns a forecast that is not finite.
        """
        built = SignatureFeatureBuilder(self.features).build(context)
        entry = self._schedule.entry_at(context.as_of)
        prediction = None
        vector = built.values  # noqa: PD011 - a field of SignatureFeatures, not a frame
        if vector is not None and entry.artifact is not None:
            if entry.artifact.feature_names != built.names:
                raise ValueError(
                    f"the model of {entry.month} was calibrated on other features than "
                    "those this signal builds"
                )
            prediction = entry.artifact.predict(vector)
        return SignatureExplanation(built, entry, prediction)

    def compute(self, context: SignalContext, instrument_ids: Sequence[str]) -> SignalResult:
        """Return the forecast return of the fund at the context's instant.

        Raises
        ------
        ValueError
            If asked about anything other than the fund it forecasts.
        """
        if tuple(instrument_ids) != (self.instrument_id,):
            raise ValueError(
                f"{self.signal_id} forecasts {self.instrument_id} and nothing else, and was "
                f"asked for {', '.join(instrument_ids)}"
            )
        explained = self.explain(context)
        built, prediction, artifact = (
            explained.features,
            explained.prediction,
            explained.entry.artifact,
        )
        frame = build_result_frame(
            {
                self.instrument_id: {
                    "value": float("nan") if prediction is None else prediction.mean,
                    "status": explained.status,
                    "input_start_date": built.window_start,
                    "input_end_date": built.window_end,
                    "observations_used": None,
                    "max_input_age_sessions": built.age_sessions,
                }
            }
        )
        extras: dict[str, object] = {
            "model_id": None if artifact is None else artifact.model_id,
            "model_month": explained.entry.month,
            "information_cutoff": (
                None if artifact is None else artifact.information_cutoff.isoformat()
            ),
            "clipped": None if prediction is None else prediction.clipped,
            "reason": explained.reason,
            "reference": None if prediction is None else prediction.reference,
        }
        for column in MODEL_COLUMNS:
            frame[column] = pd.Series([extras[column]], index=frame.index, dtype="object")
        return SignalResult(
            signal_id=self.signal_id,
            as_of=context.as_of,
            _frame=frame,
            definition=self.definition(),
        )
