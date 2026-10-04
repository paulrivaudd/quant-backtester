"""The weights a frozen network proposes for the tradable funds, as one signal."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from quant_backtester.ml.config import NeuralStrategyConfig
from quant_backtester.ml.features import FeatureVector, NeuralFeatureBuilder
from quant_backtester.ml.network import NeuralRuntime
from quant_backtester.signals.base import Signal, SignalResult, build_result_frame
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.types import PriceBasis, SignalStatus, SignalUnit, WindowMode

DIAGNOSTIC_COLUMNS = (
    "cash_weight",
    "clipped_values",
    "faulty_series",
    "series_last_dates",
    "series_ages",
    "model_id",
)
"""Columns added to the usual ones: what the decision export and a reader of a
flat day need to tell a data problem from a choice of cash."""


@dataclass(frozen=True, slots=True)
class NeuralAllocationSignal(Signal):
    """One softmax weight per tradable fund, from one multi-market input.

    Attributes
    ----------
    signal_id : str
        Stable name of this instance.
    config : NeuralStrategyConfig
        The series read, their order, the transformations and the thresholds.
    model_id : str
        The content identity of the frozen network and its normalisation.
    information_cutoff : datetime
        The last instant whose information reached the model.
    _runtime : NeuralRuntime
        The network and its normalisation, loaded before the run. Not part of
        the definition: ``model_id`` is what identifies it.

    Notes
    -----
    The input is built once per decision from every series of ``feature_ids``
    and the network is run once; each tradable fund's row then carries its
    weight, a fraction of equity. Cash is the complement, in ``cash_weight``.
    The observed series are configured here and are not the instruments the
    signal is asked about: the engine asks for ``tradable_ids`` only.

    When one required series is missing, stale, incomplete or not positive,
    no fund has a value and every row carries that series' status. A network
    output that is not finite, or a set of instruments other than
    ``tradable_ids``, stops the run: neither is a market situation.

    Nothing is read from a file and nothing is trained here.
    """

    signal_id: str
    config: NeuralStrategyConfig
    model_id: str
    information_cutoff: datetime
    _runtime: NeuralRuntime = field(repr=False, compare=False)

    def definition(self) -> Mapping[str, object]:
        """Return every parameter that changes the number, the model's identity included."""
        return {
            "type": "NeuralAllocationSignal",
            "model_id": self.model_id,
            "information_cutoff": self.information_cutoff.isoformat(),
            "config": self.config.definition(),
            "bar_basis": PriceBasis.ADJUSTED.value,
            "bar_window_mode": WindowMode.CONSECUTIVE_SESSIONS.value,
            "level_basis": PriceBasis.RAW.value,
            "level_window_mode": WindowMode.AVAILABLE_OBSERVATIONS.value,
            "unit": SignalUnit.FRACTION.value,
        }

    def compute(self, context: SignalContext, instrument_ids: Sequence[str]) -> SignalResult:
        """Return the proposed weight of each tradable fund at the context's instant.

        Parameters
        ----------
        context : SignalContext
            Environment of the decision.
        instrument_ids : Sequence[str]
            The funds of ``config.tradable_ids``, all of them, in any order:
            the engine asks in its own canonical order, and each row is
            matched to its output by name.

        Returns
        -------
        SignalResult
            One row per fund. ``input_start_date`` and ``input_end_date`` span
            every series read, ``max_input_age_sessions`` is the oldest
            series' age and ``observations_used`` counts the observations of
            all of them.

        Raises
        ------
        ValueError
            If the instruments are not exactly the model's outputs, or the
            network returns a weight that is not finite.
        """
        outputs = self.config.tradable_ids
        if len(instrument_ids) != len(outputs) or set(instrument_ids) != set(outputs):
            raise ValueError(
                f"{self.signal_id} proposes weights for {', '.join(outputs)} and for nothing "
                f"else, and was asked for {', '.join(instrument_ids)}"
            )
        features = NeuralFeatureBuilder(self.config).build(context)
        weights = dict.fromkeys(outputs, float("nan"))
        cash = float("nan")
        clipped: int | None = None
        if features.values is not None:
            proposed, clipped = self._runtime.propose(np.asarray(features.values))
            # The network's outputs are in the order of tradable_ids, whatever
            # order the engine asks in: each weight is matched by name.
            weights = {
                name: float(value) for name, value in zip(outputs, proposed[:-1], strict=True)
            }
            cash = float(proposed[-1])
        shared = _shared_diagnostics(features)
        frame = build_result_frame(
            {
                instrument_id: {
                    "value": weights[instrument_id],
                    "status": features.status,
                    **shared,
                }
                for instrument_id in instrument_ids
            }
        )
        frame["cash_weight"] = cash
        frame["clipped_values"] = clipped
        frame["faulty_series"] = ",".join(
            f"{item.instrument_id}:{item.status.value}" for item in features.faulty
        )
        frame["series_last_dates"] = json.dumps(
            {
                item.instrument_id: item.last_date.isoformat() if item.last_date else None
                for item in features.series
            }
        )
        frame["series_ages"] = json.dumps(
            {item.instrument_id: item.age_sessions for item in features.series}
        )
        frame["model_id"] = self.model_id
        return SignalResult(
            signal_id=self.signal_id,
            as_of=context.as_of,
            _frame=frame,
            definition=self.definition(),
        )


def _shared_diagnostics(features: FeatureVector) -> dict[str, object]:
    """Return the diagnostics every row of one input shares."""
    firsts = [item.first_date for item in features.series if item.first_date is not None]
    lasts = [item.last_date for item in features.series if item.last_date is not None]
    ages = [item.age_sessions for item in features.series if item.age_sessions is not None]
    used = sum(item.observations for item in features.series)
    usable = features.status is SignalStatus.OK
    return {
        "input_start_date": min(firsts) if firsts else None,
        "input_end_date": max(lasts) if lasts else None,
        "observations_used": used if usable else None,
        "max_input_age_sessions": max(ages) if ages else None,
    }
